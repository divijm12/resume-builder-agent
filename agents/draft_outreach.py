#!/usr/bin/env python3
"""Stage 6 -- Outreach draft agent (draft-only, per CLAUDE.md hard rule 2).

Pure function: jd_parsed.json + tailored_resume.json in, {subject,
body_text, validation_log, model} JSON out. No file writes, no DB writes,
no sending of any kind -- orchestration/persistence happens one layer up,
same as every other agent. This produces a hand-editable draft; nothing
in this pipeline ever calls a "send" API.

Reuses cover_letter.py's guardrail machinery directly rather than forking
a copy -- this project already does one-level-down reuse (cover_letter.py
imports _numeric_tokens from tailor.py). validate_and_build() gives the
exact same citation-verification, numeric-fabrication check, and em-dash
stripping a cover letter gets; its "cover_letter_text" key is renamed to
"body_text" here rather than reimplemented. If outreach drafts ever need
something a cover letter doesn't (e.g. a length cap), that's the moment
to fork -- not before.

Greeting fallback (three tiers, cheapest signal first): a human-verified
contact_name (saved via Find Contact) if present, else jd_parsed's own
hiring_manager_name (JD-stated, see ingest_jd.py) if present, else a
neutral "Hi there," -- both sources already exist on every application
row, so this costs nothing extra to wire.

Same anti-AI-tell writing-style guardrail as cover_letter.py: no em
dashes, avoid stock phrases/tricolon overuse/uniform sentence rhythm --
arguably even more important here since this is addressed to one real
named person, not a generic reader.
"""

import argparse
import json
from pathlib import Path
from typing import List, Optional

import anthropic
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

from cover_letter import CoverLetterClaim, _strip_em_dashes, validate_and_build

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5"

# User-specified target -- a real outreach note, not a mini cover letter.
# Enforced in the prompt; checked here only as a soft, logged flag (never a
# hard truncate) since cutting mid-sentence could break a citation-verified
# claim or drop the sign-off -- worse than a slightly-long draft a human
# will read and hand-edit anyway.
BODY_LENGTH_BUDGET = 500

SYSTEM_PROMPT = (
    "You write a short outreach email a candidate will send to a real person at a "
    "company they're applying to, grounded only in the tailored resume content given "
    "to you -- you may NEVER invent an experience, metric, skill, or claim that isn't "
    "already there. This is a cold or warm outreach note, not a cover letter: short, "
    "plain sentences, not a full letter. It accompanies (doesn't replace) the tailored "
    "resume, and a cover letter too if one exists.\n\n"
    "Greet the recipient by name if one is given; otherwise use a neutral 'Hi there,' "
    "-- never invent a name. State plainly and briefly that the candidate is applying "
    "for this role. Include exactly ONE genuine, specific hook connecting the "
    "candidate's real background to this role or company -- a single accomplishment "
    "or detail, in one short sentence with at most one comma in it. Do NOT chain "
    "multiple actions or accomplishments together with 'and'/commas/gerund lists "
    "('designing X, validating Y, and instrumenting Z') into one long sentence -- "
    "that reads like a cover letter paragraph, not a quick email. Pick the single "
    "most relevant accomplishment and describe ONLY that one; naming a second or "
    "third thing the candidate also did is the most common way this goes over length. "
    "Mention that a "
    "tailored resume is attached, and a cover letter too if told one exists -- this "
    "can be a short standalone sentence, it doesn't need to absorb the hook sentence "
    "too. Close with a light, low-pressure call to action (e.g. open to a quick chat, "
    "happy to answer questions) and a sign-off using the candidate's real name.\n\n"
    "Keep every sentence short enough to say in one breath. This is an email someone "
    "dashes off, not a polished paragraph. The entire body must fit under 500 "
    "characters total (roughly 80-90 words) -- this is a strict budget, not a "
    "suggestion. If your draft is running long, cut the hook down to fewer words or "
    "shorten the call to action; never cut the greeting, the reason you're writing, "
    "or the sign-off to make room.\n\n"
    "Avoid every tell of AI-generated writing. Never use an em dash (the '--' or '—' "
    "character) anywhere -- use a period, comma, or semicolon instead. Do not lean on "
    "tricolon lists. Avoid stock phrases like 'I'm excited/passionate about', 'I "
    "would welcome the opportunity to', 'I wanted to reach out regarding', or any "
    "sentence that could be copy-pasted into a different candidate's email to a "
    "different company without changing a word. This should read like one specific "
    "person wrote it quickly and meant it, not like a template.\n\n"
    "Every claim that states a specific fact, number, or named skill must cite the "
    "tailored resume bullet id(s) it's drawn from in source_bullet_ids. The greeting, "
    "the 'I'm applying for X' sentence, the attachment mention, and the sign-off "
    "assert no specific fact and can have an empty source_bullet_ids list. A claim "
    "you can't honestly cite to a real bullet shouldn't be written at all."
)


class OutreachDraftSchema(BaseModel):
    subject: str
    paragraphs: List[List[CoverLetterClaim]]


def generate_outreach_draft(
    jd_parsed: dict,
    tailored_resume: dict,
    company: str,
    contact_name: Optional[str] = None,
    has_cover_letter: bool = False,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Produce a short outreach email draft grounded in the tailored resume.

    contact_name should already reflect the caller's own fallback order
    (saved contact -> JD-stated hiring manager -> None) -- this function
    just uses whatever it's given, or a neutral greeting if given nothing.
    """
    client = anthropic.Anthropic()
    context_lines = [
        f"Company: {company}",
        f"Recipient name: {contact_name if contact_name else '(none given -- use a neutral greeting)'}",
        f"A cover letter also exists for this application: {has_cover_letter}",
        "",
        f"Job description (parsed):\n{json.dumps(jd_parsed, indent=2)}",
        "",
        f"Candidate's tailored resume for this job (only reference bullet ids/facts "
        f"from here):\n{yaml.dump(tailored_resume, sort_keys=False)}",
    ]
    user_content = "\n".join(context_lines)

    response = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=OutreachDraftSchema,
    )
    draft = response.parsed_output.model_dump()

    validated = validate_and_build({"paragraphs": draft["paragraphs"]}, tailored_resume)
    subject = _strip_em_dashes(draft["subject"])
    body_text = validated["cover_letter_text"]
    validation_log = validated["validation_log"]

    if len(body_text) > BODY_LENGTH_BUDGET:
        validation_log.append(
            f"Body is {len(body_text)} characters, over the {BODY_LENGTH_BUDGET}-character "
            f"target -- not truncated (would risk cutting a verified claim or the sign-off "
            f"mid-sentence), but worth a manual trim before sending."
        )

    return {
        "subject": subject,
        "body_text": body_text,
        "validation_log": validation_log,
        "model": model,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a short outreach email draft from a tailored resume.")
    parser.add_argument("--jd-json", required=True, help="Path to jd_parsed.json")
    parser.add_argument("--tailored-resume-json", required=True, help="Path to a tailored_resume dict (JSON)")
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument("--contact-name", default=None, help="Recipient name, if known")
    parser.add_argument("--has-cover-letter", action="store_true", help="Mention that a cover letter also exists")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    jd_parsed = json.loads(Path(args.jd_json).read_text())
    tailored_resume = json.loads(Path(args.tailored_resume_json).read_text())

    result = generate_outreach_draft(
        jd_parsed,
        tailored_resume,
        args.company,
        contact_name=args.contact_name,
        has_cover_letter=args.has_cover_letter,
        model=args.model,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
