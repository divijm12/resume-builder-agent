#!/usr/bin/env python3
"""Stage 0 -- JD Ingest agent.

Pure function: raw JD text in, jd_parsed.json out (schema per ARCHITECTURE.md).
No file writes, no DB writes -- orchestration/persistence happens one layer up.
"""

import argparse
import json
from pathlib import Path
from typing import List, Optional

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You extract structured fields from a job description. Only use information "
    "explicitly present in the JD text -- never infer or invent a company name, "
    "skill, or responsibility that isn't stated. Leave a field empty if the JD "
    "doesn't specify it."
)


class JDParsed(BaseModel):
    role: str
    company: Optional[str] = None
    seniority: Optional[str] = None
    must_have_skills: List[str]
    nice_to_have: List[str]
    responsibilities: List[str]
    keywords: List[str]


def ingest_jd(jd_text: str, model: str = DEFAULT_MODEL) -> dict:
    """Parse raw JD text into the Stage 0 schema defined in ARCHITECTURE.md."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": jd_text}],
        output_format=JDParsed,
    )
    return response.parsed_output.model_dump()


def main():
    parser = argparse.ArgumentParser(description="Parse a raw job description into structured JSON.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Path to a text file containing the JD")
    source.add_argument("--text", type=str, help="Raw JD text")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    jd_text = args.file.read_text() if args.file else args.text
    result = ingest_jd(jd_text, model=args.model)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
