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
from typing import Callable, Optional

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / "agents"))
sys.path.insert(0, str(REPO_ROOT / "render"))

import yaml

from ingest_jd import ingest_jd
from score import score_jd
from tailor import MODES, tailor_resume
from cover_letter import generate_cover_letter
from render import (
    _slug,
    _split_name,
    find_one_page_layout,
    find_one_page_layout_cover_letter,
    render_docx,
    render_pdf,
    render_cover_letter_docx,
    render_cover_letter_pdf,
)

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
    tailor_result: dict,
    mode: str = "aggressive",
    cover_letter_path: Optional[Path] = None,
) -> int:
    """Insert one applications row + one resume_versions row. Called once per
    apply.py run, immediately after rendering -- never after sending, since
    nothing in this pipeline sends anything (CLAUDE.md hard rule 2).

    tailor_result_json stores the full tailor_resume() output (tailored
    resume, diff_summary, unaddressed_*, ats_scan_notes, score_before/after)
    so a review UI can show gaps/diffs without re-deriving anything.
    cover_letter_path stays NULL unless a cover letter was generated this
    run (opt-in, see run_pipeline's generate_cover_letter param)."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            """
            INSERT INTO applications
                (company, role_title, jd_raw, jd_parsed_json, match_score, resume_variant_path, cover_letter_path, tailor_result_json, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company, role_title, jd_raw, json.dumps(jd_parsed), match_score, str(docx_path),
                str(cover_letter_path) if cover_letter_path else None, json.dumps(tailor_result), mode,
            ),
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
    tailor_model: str = DEFAULT_MODEL,
    mode: str = "aggressive",
    generate_cover_letter_flag: bool = False,
    outputs_dir: Path = Path("outputs"),
    db_path: Path = Path("data/applications.db"),
    resume_path: Path = Path("data/master_resume.yaml"),
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """progress_callback, if given, is called with a stage name
    ("ingesting"/"scoring"/"tailoring"/"cover_letter"/"rendering"/"logging"
    -- "cover_letter" only fires when generate_cover_letter_flag is set)
    right before each stage starts -- CLI usage passes none, so behavior
    there is unchanged. This is how a caller (e.g. a web backend) can
    report live progress on a run that takes several sequential API calls.

    tailor_model: only affects the tailoring stage (and the cover letter
    stage, when requested -- both are the genuine judgment calls a
    stronger model can plausibly improve). Ingest and scoring (both the
    before- and after-tailoring score) always use their own module
    defaults (Haiku) regardless of this -- those stages are cheap, largely
    mechanical, and have shown no benefit from a bigger model in this
    project. This also keeps score_before and score_after on the same
    model, which the score-drop guardrail depends on for a fair comparison
    -- see tailor.py's tailor_resume docstring.

    generate_cover_letter_flag: opt-in, off by default -- adds one more
    paid API call, so it's a deliberate choice per run, not automatic."""

    def report(stage: str):
        if progress_callback:
            progress_callback(stage)

    master_resume = yaml.safe_load(resume_path.read_text())

    report("ingesting")
    jd_parsed = ingest_jd(jd_text)
    report("scoring")
    score = score_jd(jd_parsed, master_resume)
    report("tailoring")
    tailored = tailor_resume(jd_parsed, score, master_resume, model=tailor_model, mode=mode)

    company = company_override or jd_parsed.get("company") or "UnknownCompany"
    role = role_override or jd_parsed.get("role") or "UnknownRole"

    folder_name = f"{_slug(company)}_{_slug(role)}_{date.today().isoformat()}"
    output_dir = outputs_dir / folder_name
    if output_dir.exists():
        raise FileExistsError(f"{output_dir} already exists -- refusing to overwrite a previous version.")

    first, last = _split_name(tailored["tailored_resume"].get("basics", {}).get("name", ""))
    name_part = f"{_slug(first)}_{_slug(last)}" if last else _slug(first)
    file_base = f"{name_part}_{_slug(company)}_{_slug(role)}"

    cover_letter_result = None
    cover_letter_docx_path = None
    cover_letter_pdf_path = None
    if generate_cover_letter_flag:
        report("cover_letter")
        cover_letter_result = generate_cover_letter(jd_parsed, tailored["tailored_resume"], model=tailor_model)
        cl_layout = find_one_page_layout_cover_letter(
            tailored["tailored_resume"].get("basics", {}), company, cover_letter_result["cover_letter_text"]
        )
        cover_letter_docx_path = output_dir / f"{file_base}_Cover_Letter.docx"
        cover_letter_pdf_path = output_dir / f"{file_base}_Cover_Letter.pdf"
        render_cover_letter_docx(
            tailored["tailored_resume"].get("basics", {}), company, cover_letter_result["cover_letter_text"],
            cover_letter_docx_path, margin_in=cl_layout["margin_in"], scale=cl_layout["scale"],
        )
        render_cover_letter_pdf(
            tailored["tailored_resume"].get("basics", {}), company, cover_letter_result["cover_letter_text"],
            cover_letter_pdf_path, margin_in=cl_layout["margin_in"], scale=cl_layout["scale"],
        )

    report("rendering")
    layout = find_one_page_layout(tailored["tailored_resume"])
    docx_path = output_dir / f"{file_base}.docx"
    pdf_path = output_dir / f"{file_base}.pdf"
    render_docx(tailored["tailored_resume"], docx_path, margin_in=layout["margin_in"], scale=layout["scale"])
    render_pdf(tailored["tailored_resume"], pdf_path, margin_in=layout["margin_in"], scale=layout["scale"])

    report("logging")
    application_id = log_application(
        db_path,
        company=company,
        role_title=role,
        jd_raw=jd_text,
        jd_parsed=jd_parsed,
        match_score=tailored["score_after"]["overall_score"],
        docx_path=docx_path,
        diff_summary=tailored["diff_summary"],
        tailor_result=tailored,
        mode=mode,
        cover_letter_path=cover_letter_docx_path,
    )

    return {
        "application_id": application_id,
        "company": company,
        "role_title": role,
        "docx_path": str(docx_path),
        "pdf_path": str(pdf_path),
        "cover_letter_docx_path": str(cover_letter_docx_path) if cover_letter_docx_path else None,
        "cover_letter_pdf_path": str(cover_letter_pdf_path) if cover_letter_pdf_path else None,
        "cover_letter_validation_log": cover_letter_result["validation_log"] if cover_letter_result else None,
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
    parser.add_argument(
        "--tailor-model", default=DEFAULT_MODEL,
        help=f"Claude model for the tailoring stage only -- ingest/scoring always use their own default (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--mode", choices=MODES, default="aggressive",
        help="'aggressive' (default) rewords bullets; 'honest' only selects/reorders/relabels",
    )
    parser.add_argument(
        "--cover-letter", action="store_true",
        help="Also generate a cover letter (one more API call) -- off by default",
    )
    parser.add_argument("--outputs-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--db", type=Path, default=Path("data/applications.db"))
    parser.add_argument("--resume", type=Path, default=Path("data/master_resume.yaml"))
    args = parser.parse_args()

    jd_text = args.jd_file.read_text() if args.jd_file else args.jd_text

    result = run_pipeline(
        jd_text,
        company_override=args.company,
        role_override=args.role,
        tailor_model=args.tailor_model,
        mode=args.mode,
        generate_cover_letter_flag=args.cover_letter,
        outputs_dir=args.outputs_dir,
        db_path=args.db,
        resume_path=args.resume,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
