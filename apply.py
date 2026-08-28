#!/usr/bin/env python3
"""End-to-end pipeline orchestrator.

Runs ingest -> score -> tailor -> render in one command and logs the result
to data/applications.db, per CLAUDE.md hard rule 4 ("every output is
versioned... log the application in applications.db immediately after
generation, not after sending"). The agents/*.py stages themselves stay
pure (JSON in, JSON out, no side effects, per CLAUDE.md working style) --
this script is the "one layer up" that owns file/DB persistence.

Company/role for the output filename and DB row are auto-extracted from
the JD (jd_parsed.role / .company) unless overridden via --company/--role
-- falls back to "UnknownCompany"/"UnknownRole" if the JD doesn't state
one, rather than fabricating a value or crashing on anonymized JDs.
"""

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / "agents"))
sys.path.insert(0, str(REPO_ROOT / "render"))

import yaml

from ingest_jd import ingest_jd
from score import score_jd
from tailor import tailor_resume
from render import _slug, _split_name, find_one_page_layout, render_docx, render_pdf

DEFAULT_MODEL = "claude-haiku-4-5"


def log_application(
    db_path: Path,
    *,
    company: str,
    role_title: str,
    jd_raw: str,
    jd_parsed: dict,
    match_score,
    docx_path: Path,
    diff_summary: list,
) -> int:
    """Insert one applications row + one resume_versions row. Called once per
    apply.py run, immediately after rendering -- never after sending, since
    nothing in this pipeline sends anything (CLAUDE.md hard rule 2)."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            """
            INSERT INTO applications
                (company, role_title, jd_raw, jd_parsed_json, match_score, resume_variant_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (company, role_title, jd_raw, json.dumps(jd_parsed), match_score, str(docx_path)),
        )
        application_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO resume_versions (application_id, diff_from_master, file_path)
            VALUES (?, ?, ?)
            """,
            (application_id, json.dumps(diff_summary), str(docx_path)),
        )
        conn.commit()
        return application_id
    finally:
        conn.close()


def run_pipeline(
    jd_text: str,
    *,
    company_override: str = None,
    role_override: str = None,
    model: str = DEFAULT_MODEL,
    outputs_dir: Path = Path("outputs"),
    db_path: Path = Path("data/applications.db"),
    resume_path: Path = Path("data/master_resume.yaml"),
) -> dict:
    master_resume = yaml.safe_load(resume_path.read_text())

    jd_parsed = ingest_jd(jd_text, model=model)
    score = score_jd(jd_parsed, master_resume, model=model)
    tailored = tailor_resume(jd_parsed, score, master_resume, model=model)

    company = company_override or jd_parsed.get("company") or "UnknownCompany"
    role = role_override or jd_parsed.get("role") or "UnknownRole"

    folder_name = f"{_slug(company)}_{_slug(role)}_{date.today().isoformat()}"
    output_dir = outputs_dir / folder_name
    if output_dir.exists():
        raise FileExistsError(f"{output_dir} already exists -- refusing to overwrite a previous version.")

    first, last = _split_name(tailored["tailored_resume"].get("basics", {}).get("name", ""))
    name_part = f"{_slug(first)}_{_slug(last)}" if last else _slug(first)
    file_base = f"{name_part}_{_slug(company)}_{_slug(role)}"

    layout = find_one_page_layout(tailored["tailored_resume"])
    docx_path = output_dir / f"{file_base}.docx"
    pdf_path = output_dir / f"{file_base}.pdf"
    render_docx(tailored["tailored_resume"], docx_path, margin_in=layout["margin_in"], scale=layout["scale"])
    render_pdf(tailored["tailored_resume"], pdf_path, margin_in=layout["margin_in"], scale=layout["scale"])

    application_id = log_application(
        db_path,
        company=company,
        role_title=role,
        jd_raw=jd_text,
        jd_parsed=jd_parsed,
        match_score=tailored["score_after"]["overall_score"],
        docx_path=docx_path,
        diff_summary=tailored["diff_summary"],
    )

    return {
        "application_id": application_id,
        "company": company,
        "role_title": role,
        "docx_path": str(docx_path),
        "pdf_path": str(pdf_path),
        "score_before": tailored["score_before"]["overall_score"],
        "score_after": tailored["score_after"]["overall_score"],
        "unaddressed_hard_gaps": tailored["unaddressed_hard_gaps"],
        "unaddressed_red_flags": tailored["unaddressed_red_flags"],
        "layout_fits_one_page": layout["fits"],
    }


def main():
    parser = argparse.ArgumentParser(description="Run the full JD -> tailored resume pipeline and log it to applications.db.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--jd-file", type=Path, help="Path to a text file containing the JD")
    source.add_argument("--jd-text", type=str, help="Raw JD text")
    parser.add_argument("--company", help="Override the company name (else auto-extracted from the JD)")
    parser.add_argument("--role", help="Override the role title (else auto-extracted from the JD)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--outputs-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--db", type=Path, default=Path("data/applications.db"))
    parser.add_argument("--resume", type=Path, default=Path("data/master_resume.yaml"))
    args = parser.parse_args()

    jd_text = args.jd_file.read_text() if args.jd_file else args.jd_text

    result = run_pipeline(
        jd_text,
        company_override=args.company,
        role_override=args.role,
        model=args.model,
        outputs_dir=args.outputs_dir,
        db_path=args.db,
        resume_path=args.resume,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
