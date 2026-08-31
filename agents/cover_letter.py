#!/usr/bin/env python3
"""Stage 4 -- Cover letter agent.

Pure function: jd_parsed.json + tailored_resume.json in, {cover_letter_text,
validation_log, model} JSON out. No file writes, no DB writes --
orchestration/persistence happens one layer up, same as every other agent.

Grounded in tailored_resume (not master_resume): the letter's emphasis has
to match what the resume already emphasizes for this specific JD, not the
full, untailored candidate history -- otherwise the two documents could
tell contradicting stories about the same application.

Same no-fabrication hard rule as tailor.py, adapted for free-form prose. A
cover letter has no "known-good original" to revert a bad claim to the way
a resume bullet does -- reword a bullet badly and there's a real original
to fall back to; a cover letter sentence that turns out to invent a number
has no true version sitting anywhere to substitute in. So instead: every
claim in the model's structured output must cite which real tailored_resume
bullet(s) it's grounded in, and code verifies every number in a claim
against its cited bullets' actual text -- same guarantee tailor.py gives
per bullet (revert on an unverifiable number), just checked against a
citation instead of an original/new pair. A claim that fails is dropped
from the final letter entirely (not silently reworded, since there's
nothing safe to reword it to), and the drop is logged in validation_log.

Named skill/tech term fabrication has a real, honest limitation here (same
class as tailor.py's documented turfgrass/genericization gap): code can
verify a mentioned term IS real (present in the master resume's
vocabulary) but can't enumerate every possible invented term someone could
claim, so that risk leans on prompting (ground every substantive claim in
a citation) plus the fact that this only ever produces a draft -- nothing
in this pipeline sends anything without manual review (CLAUDE.md hard
rule 2).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

import anthropic
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

from tailor import _numeric_tokens

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You write a cover letter for this candidate, for this specific job, grounded "
    "only in the tailored resume content given to you -- you may NEVER invent an "
    "experience, metric, skill, or claim that isn't already there. The tailored "
    "resume is what's actually being submitted alongside this letter, so the "
    "letter's emphasis must match it -- don't foreground something the resume "
    "chose to de-emphasize for this JD, and don't contradict what it says.\n\n"
    "Write like a person, not a form. Never open with 'I am writing to express "
    "interest in the [Role] position at [Company]' or any close variant of it -- "
    "find a genuine hook specific to this candidate and this role instead. The "
    "goal is a letter a recruiter would actually enjoy reading and remember, not "
    "one that restates the resume's bullets in sentence form. Be specific and "
    "confident, not generic ('hardworking team player') or falsely modest.\n\n"
    "Every claim that states a specific fact, number, or named skill must cite "
    "the tailored resume bullet id(s) it's drawn from in source_bullet_ids. "
    "Generic connective sentences -- an opening hook, a transition, a closing "
    "line -- that assert no specific fact can have an empty source_bullet_ids "
    "list. The citation is bookkeeping alongside the sentence, not a style "
    "requirement on it: write the sentence exactly as you would for a human "
    "reader, then separately note which bullet(s) back it. A claim you can't "
    "honestly cite to a real bullet shouldn't be written at all -- leave it out "
    "rather than write something ungrounded and cite nothing."
)


class CoverLetterClaim(BaseModel):
    text: str
    source_bullet_ids: List[str] = []


class CoverLetterDraft(BaseModel):
    paragraphs: List[List[CoverLetterClaim]]


def _bullet_lookup(tailored_resume: dict) -> dict:
    """bullet id -> text, across the tailored resume's experience and projects."""
    lookup = {}
    for exp in tailored_resume.get("experience", []):
        for b in exp.get("bullets", []):
            lookup[b["id"]] = b["text"]
    for proj in tailored_resume.get("projects", []):
        for b in proj.get("bullets", []):
            lookup[b["id"]] = b["text"]
    return lookup


def validate_and_build(draft: dict, tailored_resume: dict) -> dict:
    """Enforce the no-fabrication hard rule and assemble the final letter text.

    A claim citing an unknown bullet id has that id dropped from its citation
    list (logged). A claim containing a number not present in the text of its
    (validated) cited bullets is dropped from the letter entirely (logged) --
    including any claim with zero valid citations that contains a number at
    all. A paragraph that loses every one of its claims is dropped, not left
    as an empty gap.
    """
    bullet_text = _bullet_lookup(tailored_resume)
    warnings = []
    final_paragraphs = []

    for para in draft["paragraphs"]:
        surviving = []
        for claim in para:
            text = claim["text"]
            cited_ids = claim.get("source_bullet_ids", [])
            valid_ids = [bid for bid in cited_ids if bid in bullet_text]
            unknown_ids = [bid for bid in cited_ids if bid not in bullet_text]
            if unknown_ids:
                warnings.append(
                    f"Claim {text!r} cited unknown bullet id(s) {unknown_ids} -- "
                    f"dropped from its citations."
                )

            cited_text = " ".join(bullet_text[bid] for bid in valid_ids)
            bad_numbers = _numeric_tokens(text) - _numeric_tokens(cited_text)
            if bad_numbers:
                warnings.append(
                    f"Claim {text!r} contains number(s) {sorted(bad_numbers)} not "
                    f"present in its cited bullet(s) -- dropped from the letter."
                )
                continue

            surviving.append(text)

        if surviving:
            final_paragraphs.append(" ".join(surviving))
        elif para:
            warnings.append("A paragraph lost every one of its claims to validation -- dropped entirely.")

    return {
        "cover_letter_text": "\n\n".join(final_paragraphs),
        "validation_log": warnings,
    }


def generate_cover_letter(jd_parsed: dict, tailored_resume: dict, model: str = DEFAULT_MODEL) -> dict:
    """Produce a cover letter grounded in the tailored resume for this JD."""
    client = anthropic.Anthropic()
    user_content = (
        f"Job description (parsed):\n{json.dumps(jd_parsed, indent=2)}\n\n"
        f"Candidate's tailored resume for this job (only reference bullet ids/facts "
        f"from here):\n{yaml.dump(tailored_resume, sort_keys=False)}"
    )
    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=CoverLetterDraft,
    )
    draft = response.parsed_output.model_dump()
    result = validate_and_build(draft, tailored_resume)
    result["model"] = model
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate a cover letter from a tailored resume.")
    parser.add_argument("--jd-json", required=True, help="Path to jd_parsed.json")
    parser.add_argument("--tailored-resume-json", required=True, help="Path to a tailored_resume dict (JSON)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    jd_parsed = json.loads(Path(args.jd_json).read_text())
    tailored_resume = json.loads(Path(args.tailored_resume_json).read_text())

    result = generate_cover_letter(jd_parsed, tailored_resume, model=args.model)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
