#!/usr/bin/env python3
"""Stage 1 -- Scoring agent.

Pure function: jd_parsed.json + master_resume.yaml in, score JSON out
(schema per ARCHITECTURE.md). No file writes, no DB writes -- orchestration/
persistence happens one layer up.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

import anthropic
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5"

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
    "that reads as a stretch. Be specific and honest, not diplomatic."
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
    user_content = (
        f"Job description (parsed):\n{json.dumps(jd_parsed, indent=2)}\n\n"
        f"Candidate's master resume:\n{yaml.dump(master_resume, sort_keys=False)}"
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
