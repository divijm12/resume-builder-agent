#!/usr/bin/env python3
"""Stage -1 -- Master resume onboarding agent.

Pure function: raw resume text in, a draft master_resume.yaml-shaped
dict out. No file writes, no DB writes -- orchestration/persistence
(the actual write to data/master_resume.yaml) happens one layer up,
after a human reviews and confirms the draft.

This is the only way, besides hand-editing the YAML directly, that
someone gives this tool their own resume -- so it has to work for
anyone's content, not just this project's original test data. Unlike
tailor.py/cover_letter.py (which select/reword FROM an already-trusted
master_resume.yaml), this stage is the one place a resume's raw content
first becomes structured data, so its job is transcription fidelity, not
selection: reproduce what's already true in someone's real resume
accurately and completely, never summarize away a specific detail.

Guardrail, scoped honestly: this stage segments unstructured prose into
discrete bullets, so there's no 1:1 original-bullet-to-new-bullet mapping
the way tailor.py's reword step has -- a per-bullet numeric diff isn't
possible. Instead, _fabricated_numbers() checks GLOBALLY: every numeric
token appearing anywhere in the parsed draft's bullets must appear
somewhere in the raw input text. This is looser than tailor.py's
per-bullet check (it can't catch a number that leaked into the wrong
bullet) but does catch true fabrication -- a number that was never
anywhere in the source. Never auto-drops a flagged bullet: there is no
known-good original to fall back to here (unlike tailor.py, which can
always revert to the untouched master bullet), so surfacing it for the
human review step that must happen before this becomes the real
master_resume.yaml is the only honest move.

IDs are assigned by code after parsing, never by the model -- they're
just internal handles (uniqueness is all that matters), the same
"compute what's fully mechanical" choice already made for outreach
sign-offs and job-posting links.
"""

import argparse
import json
from pathlib import Path
from typing import List, Optional

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from tailor import _numeric_tokens

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "You extract a candidate's resume into structured fields. This is transcription, "
    "not rewriting: reproduce every bullet's facts, numbers, dates, and named tools/"
    "technologies faithfully and completely. Never summarize away a specific detail "
    "into something vaguer, never invent a number, date, employer, or claim that isn't "
    "in the text, and never merge two distinct accomplishments into one bullet if the "
    "original text presented them separately.\n\n"
    "Segment each role/project's description into individual bullets the same way the "
    "original resume does (or, if it's a dense paragraph, split at natural accomplishment "
    "boundaries -- one bullet per distinct achievement). For each bullet, tag it with a "
    "few lowercase-hyphenated keywords describing its subject matter (e.g. 'data-pipeline', "
    "'machine-learning', 'cross-functional') and set metrics=true only if the bullet "
    "contains a real number/percentage/count from the text.\n\n"
    "For skills, extract every named tool, technology, language, framework, or named "
    "professional skill mentioned anywhere in the resume (not just in a dedicated skills "
    "section) as its own entry, each tagged with a few lowercase-hyphenated category tags.\n\n"
    "For projects, extract a 'tech' list of every named technology used in that project. "
    "A project's 'status' field must be exactly the literal string 'in-progress' or "
    "'complete' -- infer which one from context (an ongoing/current project is "
    "'in-progress'; a past hackathon, school project, or anything described in past "
    "tense is 'complete'), never any other wording.\n\n"
    "Leave optional fields (location, links, honors, certifications) empty/absent rather "
    "than guessing if the resume doesn't state them."
)


class SkillEntry(BaseModel):
    name: str
    tags: List[str] = []


class BulletEntry(BaseModel):
    text: str
    tags: List[str] = []
    metrics: bool = False


class ExperienceEntry(BaseModel):
    company: str
    title: str
    start: str
    end: str
    bullets: List[BulletEntry]


class ProjectEntry(BaseModel):
    name: str
    status: str
    date: str
    tech: List[str] = []
    bullets: List[BulletEntry]


class EducationEntry(BaseModel):
    degree: str
    institution: str
    honors: str = ""
    start: str = ""
    end: str = ""


class CertificationEntry(BaseModel):
    name: str
    year: Optional[int] = None


class ParsedResumeDraft(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    skills: List[SkillEntry]
    experience: List[ExperienceEntry]
    projects: List[ProjectEntry] = []
    education: List[EducationEntry] = []
    certifications: List[CertificationEntry] = []


def _assign_ids(draft: dict) -> None:
    """Mutates draft in place. Matches the real master_resume.yaml's own
    convention exactly: exp_NNN/proj_NNN per entry, b_NNN/p_NNN as global
    sequential counters across ALL experience/project bullets respectively
    (confirmed against the real file -- b_001..b_005 span two experience
    entries, p_001..p_009 span four projects)."""
    bullet_n = 1
    for i, exp in enumerate(draft.get("experience", []), start=1):
        exp["id"] = f"exp_{i:03d}"
        for bullet in exp.get("bullets", []):
            bullet["id"] = f"b_{bullet_n:03d}"
            bullet_n += 1

    proj_bullet_n = 1
    for i, proj in enumerate(draft.get("projects", []), start=1):
        proj["id"] = f"proj_{i:03d}"
        for bullet in proj.get("bullets", []):
            bullet["id"] = f"p_{proj_bullet_n:03d}"
            proj_bullet_n += 1


def _fabricated_numbers(draft: dict, raw_text: str) -> List[str]:
    """Global numeric-fabrication check -- see module docstring for why
    this is global rather than per-bullet. Returns validation_log lines,
    one per bullet containing a number not found anywhere in raw_text."""
    source_numbers = _numeric_tokens(raw_text)
    warnings = []
    for exp in draft.get("experience", []):
        for bullet in exp.get("bullets", []):
            bad = _numeric_tokens(bullet["text"]) - source_numbers
            if bad:
                warnings.append(
                    f"Bullet {bullet.get('id', '?')!r} ({exp.get('company', '?')}) contains "
                    f"number(s) {sorted(bad)} not found anywhere in the uploaded resume text -- "
                    f"double-check this wasn't introduced during parsing: {bullet['text']!r}"
                )
    for proj in draft.get("projects", []):
        for bullet in proj.get("bullets", []):
            bad = _numeric_tokens(bullet["text"]) - source_numbers
            if bad:
                warnings.append(
                    f"Bullet {bullet.get('id', '?')!r} ({proj.get('name', '?')}) contains "
                    f"number(s) {sorted(bad)} not found anywhere in the uploaded resume text -- "
                    f"double-check this wasn't introduced during parsing: {bullet['text']!r}"
                )
    return warnings


def parse_resume_draft(raw_text: str, model: str = DEFAULT_MODEL) -> dict:
    """Produce a draft master_resume.yaml-shaped dict from raw resume text.
    Never writes anything -- the caller shows this to a human for review
    before it becomes the real master_resume.yaml."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": raw_text}],
        output_format=ParsedResumeDraft,
    )
    parsed = response.parsed_output.model_dump()

    draft = {
        "basics": {
            "name": parsed["name"],
            "email": parsed["email"],
            "phone": parsed["phone"],
            "location": parsed["location"],
            "links": {
                "linkedin": parsed["linkedin"],
                "github": parsed["github"],
                "portfolio": parsed["portfolio"],
            },
        },
        "summary_variants": [],
        "skills": parsed["skills"],
        "experience": parsed["experience"],
        "projects": parsed["projects"],
        "education": parsed["education"],
        "certifications": parsed["certifications"],
    }
    _assign_ids(draft)
    validation_log = _fabricated_numbers(draft, raw_text)

    return {"draft": draft, "validation_log": validation_log, "model": model}


def main():
    parser = argparse.ArgumentParser(description="Parse raw resume text into a draft master_resume.yaml.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Path to a text file containing the resume")
    source.add_argument("--text", type=str, help="Raw resume text")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    raw_text = args.file.read_text() if args.file else args.text
    result = parse_resume_draft(raw_text, model=args.model)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
