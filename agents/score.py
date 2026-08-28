#!/usr/bin/env python3
"""Stage 1 -- Scoring agent.

Pure function: jd_parsed.json + master_resume.yaml in, score JSON out
(schema per ARCHITECTURE.md). No file writes, no DB writes -- orchestration/
persistence happens one layer up.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import List

import anthropic
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5"


def _parse_ym(value) -> "tuple[int, int] | None":
    """'2024-05' -> (2024, 5); None/'' /unparseable -> None."""
    if not value:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})$", str(value).strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _ym_index(year: int, month: int) -> int:
    """Single comparable/subtractable integer for a (year, month) pair."""
    return year * 12 + month


def _fmt_duration(total_months: int) -> str:
    years, months = divmod(max(total_months, 0), 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months or not years:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    return " ".join(parts)


def _annotate_resume_dates(master_resume: dict) -> dict:
    """Returns a copy of master_resume with code-computed date facts attached
    for the model -- never mutates the real master_resume.yaml data, and
    never modifies the dict passed in.

    The model has no reliable notion of today's actual date (it tends to
    reason as if 'now' is near its training data's timeframe) and no reliable
    arithmetic over date ranges, so every fact here is computed in Python and
    handed over directly, the same reasoning as tailor.py's _date_rank:
    compute what's structurally computable in code, don't leave it to the
    model to guess.

    Two things get computed:
    - computed_tenure on every experience entry: how long that role has
      actually run, e.g. '2 years 3 months (ongoing)'.
    - When the first education entry has a real graduation date (its 'end'
      field), computed_time_since_graduation on that entry, and --
      critically -- computed_tenure_relative_to_graduation on every
      experience entry that overlaps the graduation date at all, splitting
      that role's tenure into a before-graduation portion (likely
      internship/part-time/co-op work done while still enrolled) and an
      after-graduation portion (post-grad professional experience). A JD's
      'entry-level, 0-2 years' framing is really about time since
      graduation, not raw total resume tenure -- see the prompt.
    """
    annotated = dict(master_resume)
    today_idx = _ym_index(date.today().year, date.today().month)

    education = master_resume.get("education", [])
    grad_idx = _ym_index(*_parse_ym(education[0].get("end"))) if education and _parse_ym(education[0].get("end")) else None

    annotated_experience = []
    for exp in master_resume.get("experience", []):
        entry = dict(exp)
        start_ym = _parse_ym(exp.get("start"))
        ongoing = str(exp.get("end", "")).strip().lower() == "present"
        end_ym = (date.today().year, date.today().month) if ongoing else _parse_ym(exp.get("end"))
        if start_ym and end_ym:
            start_idx, end_idx = _ym_index(*start_ym), _ym_index(*end_ym)
            entry["computed_tenure"] = _fmt_duration(end_idx - start_idx) + (" (ongoing)" if ongoing else "")
            if grad_idx is not None:
                pre = max(0, min(end_idx, grad_idx) - start_idx)
                post = max(0, end_idx - max(start_idx, grad_idx))
                if pre and post:
                    entry["computed_tenure_relative_to_graduation"] = (
                        f"{_fmt_duration(pre)} before graduation (while still enrolled -- "
                        f"reads as internship/part-time/co-op), {_fmt_duration(post)} after "
                        f"graduation (post-grad professional experience)"
                    )
                elif pre:
                    entry["computed_tenure_relative_to_graduation"] = (
                        f"entirely before graduation ({_fmt_duration(pre)}, while still enrolled "
                        f"-- reads as internship/part-time/co-op)"
                    )
                elif post:
                    entry["computed_tenure_relative_to_graduation"] = (
                        f"entirely after graduation ({_fmt_duration(post)} of post-grad "
                        f"professional experience)"
                    )
        annotated_experience.append(entry)
    annotated["experience"] = annotated_experience

    if grad_idx is not None:
        annotated_education = []
        for i, edu in enumerate(education):
            e = dict(edu)
            if i == 0:
                since = today_idx - grad_idx
                e["computed_time_since_graduation"] = (
                    f"{_fmt_duration(since)} since graduation" if since >= 0
                    else f"not yet graduated -- {_fmt_duration(-since)} remaining"
                )
            annotated_education.append(e)
        annotated["education"] = annotated_education

    return annotated

SYSTEM_PROMPT = (
    "You are a senior recruiter at this exact company, reviewing this candidate's "
    "resume against this specific job description. Score the match, and think like "
    "a hiring manager scanning the resume for problems in under 10 seconds -- call "
    "out what would make them hesitate.\n\n"
    "Ground everything in the structured resume data given to you -- never assume "
    "skills or experience that aren't in it. Distinguish two kinds of gaps: "
    "reword_opportunities are JD requirements the resume already covers in "
    "substance but doesn't state in matching language (a bullet could be lightly "
    "reworded to surface it); hard_gaps are JD requirements the resume has no real "
    "coverage for at all -- don't let the first category hide the second.\n\n"
    "overall_score is 0-100. top_missing_keywords is the 5 most important missing "
    "keywords/skills a recruiter or ATS skim would flag first. red_flags is the "
    "top 3 things that would make a hiring manager hesitate on a 10-second scan -- "
    "e.g. a hard requirement with zero coverage, a seniority mismatch, or a pattern "
    "that reads as a stretch. Be specific and honest, not diplomatic.\n\n"
    "Each experience entry includes a 'computed_tenure' field (e.g. '2 years 3 "
    "months (ongoing)') computed in code from today's real date -- use that "
    "figure for any claim about how long the candidate has been in a role. Do "
    "not compute or estimate a duration yourself from 'start'/'end' dates; you "
    "have no reliable way to know today's actual date, and a wrong tenure claim "
    "is exactly the kind of factual error a real recruiter would never make.\n\n"
    "When a 'computed_time_since_graduation' field is present on the "
    "education entry, use it -- not raw resume tenure -- to judge whether a "
    "JD's stated seniority/years-of-experience expectations are a reasonable "
    "fit. A JD asking for '0-2 years of experience, entry-level' is written "
    "for candidates within roughly that range of their OWN graduation date, "
    "not for someone with literally zero work on their resume. Experience "
    "entries also carry 'computed_tenure_relative_to_graduation' when they "
    "overlap the graduation date -- time logged before graduation happened "
    "while the candidate was still enrolled and reads as internship/part-time/"
    "co-op work, not a disqualifying amount of prior professional tenure; "
    "only the after-graduation portion is genuine post-grad professional "
    "experience. Do not flag a seniority mismatch or 'overqualified' red flag "
    "based on total resume tenure alone if computed_time_since_graduation "
    "itself is within or near the JD's stated experience range -- weigh time "
    "since graduation as the primary signal for entry-level fit, prior "
    "experience as a secondary, real, but non-disqualifying factor."
)


class ScoreResult(BaseModel):
    overall_score: float
    matched_skills: List[str]
    missing_skills: List[str]
    reword_opportunities: List[str]
    hard_gaps: List[str]
    top_missing_keywords: List[str] = Field(
        max_length=5, description="Top 5 missing keywords a recruiter/ATS skim would flag first"
    )
    red_flags: List[str] = Field(
        max_length=3, description="Top 3 things a hiring manager would flag in a 10-second scan"
    )


def score_jd(jd_parsed: dict, master_resume: dict, model: str = DEFAULT_MODEL) -> dict:
    """Score a parsed JD against the master resume. Schema per ARCHITECTURE.md Stage 1."""
    client = anthropic.Anthropic()
    annotated_resume = _annotate_resume_dates(master_resume)
    user_content = (
        f"Job description (parsed):\n{json.dumps(jd_parsed, indent=2)}\n\n"
        f"Candidate's master resume:\n{yaml.dump(annotated_resume, sort_keys=False)}"
    )
    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=ScoreResult,
    )
    return response.parsed_output.model_dump()


def main():
    parser = argparse.ArgumentParser(description="Score a parsed JD against the master resume.")
    parser.add_argument("--jd-json", required=True, help="Path to jd_parsed.json, or '-' to read from stdin")
    parser.add_argument("--resume", type=Path, default=Path("data/master_resume.yaml"), help="Path to master_resume.yaml")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    jd_text = sys.stdin.read() if args.jd_json == "-" else Path(args.jd_json).read_text()
    jd_parsed = json.loads(jd_text)
    master_resume = yaml.safe_load(args.resume.read_text())

    result = score_jd(jd_parsed, master_resume, model=args.model)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
