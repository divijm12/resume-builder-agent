#!/usr/bin/env python3
"""FastAPI backend for the review/apply web UI.

Wraps apply.py's run_pipeline() so a browser can trigger the full
ingest -> score -> tailor -> render -> log pipeline and track it. The
pipeline makes several sequential Anthropic API calls and can take up to
a minute, so it never runs inline in a request handler -- POST /api/jobs
starts it via FastAPI's BackgroundTasks and returns immediately with a
job_id; the frontend polls GET /api/jobs/{id} for progress. Job state is
a plain in-memory dict -- no Redis/Celery, this is a single-user local
tool and job state loss on a backend restart is an acceptable tradeoff at
this scale (see LEARNING_LOG.md).

Run from this directory: `uvicorn main:app --reload --port 8000`
"""

import io
import json
import re
import sqlite3
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

import apply  # noqa: E402  (must follow sys.path insert)
import find_contact  # noqa: E402  (agents/ is on sys.path via apply's own import above)
import draft_outreach  # noqa: E402  (agents/ is on sys.path via apply's own import above)
import parse_resume  # noqa: E402  (agents/ is on sys.path via apply's own import above)
import gmail_client  # noqa: E402  (same directory as this file)
from docx import Document
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pypdf import PdfReader

DB_PATH = REPO_ROOT / "data" / "applications.db"
OUTPUTS_DIR = REPO_ROOT / "outputs"
MASTER_RESUMES_DIR = REPO_ROOT / "data" / "master_resumes"
MASTER_RESUME_INDEX_PATH = MASTER_RESUMES_DIR / "_index.json"
RESUME_BACKUPS_DIR = REPO_ROOT / "data" / "master_resume_backups"
MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB -- generous for a resume, defensive against abuse
DEFAULT_RESUME_SLUG = "main"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "resume"


def _load_resume_index() -> dict:
    if not MASTER_RESUME_INDEX_PATH.exists():
        return {}
    return json.loads(MASTER_RESUME_INDEX_PATH.read_text())


def _save_resume_index(index: dict) -> None:
    MASTER_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    MASTER_RESUME_INDEX_PATH.write_text(json.dumps(index, indent=2))


def _resume_path(slug: str) -> Path:
    return MASTER_RESUMES_DIR / f"{slug}.yaml"

app = FastAPI(title="Resume Pipeline Review API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# job_id -> {status: running|done|error, stage, application_id, error}
JOBS: dict = {}
JOBS_LOCK = threading.Lock()

# A fresh clone has no applications.db (gitignored) and nothing else ever
# applies data/schema.sql to create one -- without this, a plain page load
# of the applications list (GET /api/applications) 500s with "no such
# table" before a user has done anything at all. apply.ensure_schema is
# the single source of truth (the CLI path calls it too, inside
# run_pipeline); safe to call here since it no-ops once the table exists.
apply.ensure_schema(DB_PATH)


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class CreateJobRequest(BaseModel):
    jd_text: str
    company: Optional[str] = None
    role: Optional[str] = None
    tailor_model: Optional[str] = None
    mode: Optional[str] = None
    generate_cover_letter: Optional[bool] = None
    resume_slug: Optional[str] = None


def _run_job(
    job_id: str, jd_text: str, company: Optional[str], role: Optional[str],
    tailor_model: str, mode: str, generate_cover_letter_flag: bool, resume_slug: str,
):
    def report(stage: str):
        with JOBS_LOCK:
            JOBS[job_id]["stage"] = stage

    try:
        index = _load_resume_index()
        resume_label = index.get(resume_slug, {}).get("label", resume_slug)
        result = apply.run_pipeline(
            jd_text,
            company_override=company,
            role_override=role,
            tailor_model=tailor_model,
            mode=mode,
            generate_cover_letter_flag=generate_cover_letter_flag,
            outputs_dir=OUTPUTS_DIR,
            db_path=DB_PATH,
            resume_path=_resume_path(resume_slug),
            resume_name=resume_label,
            progress_callback=report,
        )
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["application_id"] = result["application_id"]
    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)


@app.post("/api/jobs")
def create_job(body: CreateJobRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running", "stage": "starting", "application_id": None, "error": None}
    background_tasks.add_task(
        _run_job, job_id, body.jd_text, body.company, body.role,
        body.tailor_model or apply.DEFAULT_MODEL, body.mode or "aggressive",
        bool(body.generate_cover_letter), body.resume_slug or DEFAULT_RESUME_SLUG,
    )
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@app.get("/api/applications")
def list_applications():
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id, created_at, company, role_title, match_score, status, mode, resume_name "
            "FROM applications ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/applications/{app_id}")
def get_application(app_id: int):
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "application not found")
    data = dict(row)
    jd_parsed_json = data.pop("jd_parsed_json", None)
    tailor_result_json = data.pop("tailor_result_json", None)
    data["jd_parsed"] = json.loads(jd_parsed_json) if jd_parsed_json else None
    data["tailor_result"] = json.loads(tailor_result_json) if tailor_result_json else None
    return data


@app.post("/api/applications/{app_id}/find-contact")
def find_application_contact(app_id: int):
    """Look up candidate hiring contacts for this application's company via
    Hunter.io. Does NOT write anything to the DB -- a human picks which
    contact, if any, is worth recording (PATCH /api/applications/{id} with
    the chosen fields), same "human decides" pattern as the status dropdown.

    Passes this application's role_title through so find_contacts() can
    boost recruiters/team-relevant contacts to the top, and, when the JD
    itself named a real hiring manager (agents/ingest_jd.py's
    hiring_manager_name), passes that through too so find_contacts() can
    run one additional targeted Hunter lookup for that specific person --
    see agents/find_contact.py's module docstring. All of this is
    ranking/labeling/merging only: it is never sent to Hunter as a filter,
    so the full candidate list Domain Search would return on its own is
    always still present."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT company, role_title, jd_parsed_json FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "application not found")
    jd_parsed = json.loads(row["jd_parsed_json"]) if row["jd_parsed_json"] else {}
    hiring_manager_name = jd_parsed.get("hiring_manager_name")
    return find_contact.find_contacts(
        row["company"], role_title=row["role_title"], hiring_manager_name=hiring_manager_name
    )


class DraftOutreachRequest(BaseModel):
    email_type: str = "cold"  # "cold" | "referral"
    job_link: Optional[str] = None


@app.post("/api/applications/{app_id}/draft-outreach")
def draft_application_outreach(app_id: int, body: DraftOutreachRequest):
    """Generate a short, hand-editable outreach email draft (Stage 6).
    Draft-only, per CLAUDE.md hard rule 2 -- writes a scratch .md file next
    to the resume/cover letter and records its path, but never sends
    anything and never requires a saved contact first (see
    agents/draft_outreach.py's module docstring for the greeting fallback
    that degrades gracefully when no contact is saved yet).

    email_type="referral" requires job_link -- there's no code path here
    or in draft_outreach.py that produces a referral draft without one,
    which is the actual enforcement behind "a referral ask can't be sent
    without a job link": nothing to send without a draft, no draft
    without a link."""
    if body.email_type not in draft_outreach.EMAIL_TYPES:
        raise HTTPException(400, f"email_type must be one of {draft_outreach.EMAIL_TYPES}")
    if body.email_type == "referral" and not body.job_link:
        raise HTTPException(400, "job_link is required for a referral request email")

    conn = _get_db()
    try:
        row = conn.execute(
            """SELECT company, role_title, jd_parsed_json, tailor_result_json,
                      resume_variant_path, cover_letter_path, contact_name
               FROM applications WHERE id = ?""",
            (app_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "application not found")
    if not row["resume_variant_path"]:
        raise HTTPException(404, "no resume generated for this application yet")

    jd_parsed = json.loads(row["jd_parsed_json"]) if row["jd_parsed_json"] else {}
    tailored_resume = json.loads(row["tailor_result_json"])["tailored_resume"]
    # Same human-verified-first fallback as the greeting logic in
    # draft_outreach.py's own docstring: a saved contact (from Find Contact)
    # outranks a JD-stated name, which outranks no name at all.
    contact_name = row["contact_name"] or jd_parsed.get("hiring_manager_name")

    result = draft_outreach.generate_outreach_draft(
        jd_parsed,
        tailored_resume,
        row["company"],
        contact_name=contact_name,
        has_cover_letter=bool(row["cover_letter_path"]),
        email_type=body.email_type,
        job_link=body.job_link,
    )
    if not result["body_text"].strip():
        raise HTTPException(
            422, "Every claim in the generated draft failed verification -- nothing safe to show. Try again."
        )

    stored_path = Path(row["resume_variant_path"])
    resume_path = stored_path if stored_path.is_absolute() else REPO_ROOT / stored_path
    output_dir = resume_path.parent
    draft_path = output_dir / "outreach_draft.md"
    # Overwritten in place on every regeneration -- unlike resume_variant_path/
    # cover_letter_path (the submitted artifacts, never overwritten per hard
    # rule 4), this is explicitly a scratch draft meant for hand-editing
    # before sending, so there's no "previous version" worth preserving here.
    draft_path.write_text(f"Subject: {result['subject']}\n\n{result['body_text']}\n")

    conn = _get_db()
    try:
        conn.execute(
            "UPDATE applications SET outreach_draft_path = ? WHERE id = ?", (str(draft_path), app_id)
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "subject": result["subject"],
        "body_text": result["body_text"],
        "validation_log": result["validation_log"],
        "draft_path": str(draft_path),
    }


class SendOutreachRequest(BaseModel):
    subject: str
    body_text: str


@app.post("/api/applications/{app_id}/send-outreach")
def send_application_outreach(app_id: int, body: SendOutreachRequest):
    """Actually send the outreach email via the connected Gmail account
    (gmail_client.py). THIS IS THE ONLY CODE PATH IN THE ENTIRE CODEBASE
    THAT CAN CALL gmail_client.send_email -- no pipeline stage, no agent,
    nothing in apply.py touches it. It only fires on an explicit POST from
    a confirmed frontend click (CLAUDE.md hard rule 2's "explicit user
    confirmation step").

    Sends exactly `subject`/`body_text` as given -- whatever the frontend
    currently has on screen -- never re-read from outreach_draft.md, so
    there's no chance of sending something other than what was just
    reviewed in the confirmation modal.

    Always attaches the resume PDF; also attaches the cover letter PDF if
    one was generated for this application. The draft text tells the
    recipient a resume (and cover letter, if applicable) is attached, so
    this makes that literally true rather than just asserted -- a missing
    file is a hard error (see gmail_client.send_email), not a silent gap."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT contact_email, resume_variant_path, cover_letter_path FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "application not found")
    if not row["contact_email"]:
        raise HTTPException(400, "no contact email saved for this application -- find and save a contact first")
    if not row["resume_variant_path"]:
        raise HTTPException(404, "no resume generated for this application yet")

    def _resolve_pdf(stored_path_str: str) -> Path:
        stored_path = Path(stored_path_str)
        docx_path = stored_path if stored_path.is_absolute() else REPO_ROOT / stored_path
        return docx_path.with_suffix(".pdf")

    attachment_paths = [_resolve_pdf(row["resume_variant_path"])]
    if row["cover_letter_path"]:
        attachment_paths.append(_resolve_pdf(row["cover_letter_path"]))

    try:
        gmail_client.send_email(row["contact_email"], body.subject, body.body_text, attachment_paths=attachment_paths)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Gmail send failed: {e}")

    sent_at = None
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE applications SET outreach_sent_at = datetime('now'), status = 'outreach_sent' WHERE id = ?",
            (app_id,),
        )
        conn.commit()
        sent_at = conn.execute(
            "SELECT outreach_sent_at FROM applications WHERE id = ?", (app_id,)
        ).fetchone()["outreach_sent_at"]
    finally:
        conn.close()

    return {"sent": True, "sent_at": sent_at}


class UpdateApplicationRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    # Set together once a human picks one candidate from POST .../find-contact's
    # results -- this endpoint never writes a contact itself, see that handler.
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_source: Optional[str] = None
    contact_verified: Optional[bool] = None


@app.patch("/api/applications/{app_id}")
def update_application(app_id: int, body: UpdateApplicationRequest):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return {"ok": True}
    conn = _get_db()
    try:
        existing = conn.execute("SELECT id FROM applications WHERE id = ?", (app_id,)).fetchone()
        if existing is None:
            raise HTTPException(404, "application not found")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        try:
            conn.execute(f"UPDATE applications SET {set_clause} WHERE id = ?", (*updates.values(), app_id))
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise HTTPException(400, f"invalid update: {e}")
    finally:
        conn.close()
    return {"ok": True}


@app.get("/api/applications/{app_id}/file")
def get_application_file(app_id: int, type: str = "pdf"):
    valid_types = ("pdf", "docx", "cover_letter_pdf", "cover_letter_docx")
    if type not in valid_types:
        raise HTTPException(400, f"type must be one of {valid_types}")
    is_cover_letter = type.startswith("cover_letter_")
    column = "cover_letter_path" if is_cover_letter else "resume_variant_path"

    conn = _get_db()
    try:
        row = conn.execute(f"SELECT {column} FROM applications WHERE id = ?", (app_id,)).fetchone()
    finally:
        conn.close()
    if row is None or not row[column]:
        raise HTTPException(404, "application or file not found")

    stored_path = Path(row[column])
    docx_path = stored_path if stored_path.is_absolute() else REPO_ROOT / stored_path
    wants_pdf = type in ("pdf", "cover_letter_pdf")
    file_path = docx_path.with_suffix(".pdf") if wants_pdf else docx_path
    if not file_path.exists():
        raise HTTPException(404, "file not found on disk")

    media_type = (
        "application/pdf" if wants_pdf
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    # Starlette's FileResponse defaults Content-Disposition to "attachment"
    # whenever `filename` is passed -- that's what was forcing a save-to-disk
    # dialog for PDFs instead of letting the browser render them inline.
    # docx has no native browser renderer either way, so a download is still
    # the only sensible behavior there -- only PDFs get "inline".
    disposition = "inline" if wants_pdf else "attachment"
    return FileResponse(str(file_path), media_type=media_type, filename=file_path.name, content_disposition_type=disposition)


# ---------------------------------------------------------------------------
# Master resume library -- upload -> parse -> human-reviewed draft ->
# confirm, as one NAMED entry among possibly several. Always available
# (not a one-time setup step), since resumes are meant to be added/updated
# over time, not just created once. Never writes a resume file directly
# from an upload -- only /confirm does that, and only after a human has
# seen the parsed draft. Applications record which named resume produced
# them (apply.py's resume_name column) so a library with several resumes
# never leaves it ambiguous which one scored/tailored a given application.
# ---------------------------------------------------------------------------


@app.get("/api/master-resumes")
def list_master_resumes():
    """Every resume currently in the library, with light stats -- so the
    New Application page can offer a real choice and the Resume page can
    show what exists before someone adds or replaces one. Empty list (not
    an error) on a fresh clone with nothing uploaded yet."""
    index = _load_resume_index()
    entries = []
    for slug, meta in index.items():
        path = _resume_path(slug)
        if not path.exists():
            continue  # index entry outlived its file somehow -- skip, don't crash
        resume = yaml.safe_load(path.read_text()) or {}
        entries.append(
            {
                "slug": slug,
                "label": meta.get("label", slug),
                "name": (resume.get("basics") or {}).get("name"),
                "experience_count": len(resume.get("experience") or []),
                "project_count": len(resume.get("projects") or []),
                "skill_count": len(resume.get("skills") or []),
                "updated_at": meta.get("updated_at"),
            }
        )
    entries.sort(key=lambda e: e["updated_at"] or "", reverse=True)
    return entries


@app.post("/api/master-resumes/parse")
async def parse_master_resume(file: UploadFile = File(...), model: str = "claude-sonnet-5"):
    """Extract text from an uploaded resume (.pdf or .docx) and parse it
    into a draft -- never writes anything. The caller must review the
    returned draft (and its validation_log) and POST to /confirm, with a
    chosen name, to actually save it into the library."""
    filename = (file.filename or "").lower()
    if not (filename.endswith(".pdf") or filename.endswith(".docx")):
        raise HTTPException(400, "Only .pdf or .docx files are supported")

    contents = await file.read()
    if len(contents) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(400, f"File too large -- max {MAX_RESUME_UPLOAD_BYTES // (1024 * 1024)}MB")

    try:
        if filename.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(contents))
            raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            doc = Document(io.BytesIO(contents))
            raw_text = "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        raise HTTPException(400, f"Could not read that file: {e}")

    if not raw_text.strip():
        raise HTTPException(400, "No text could be extracted from that file -- it may be a scanned image, not real text")

    result = parse_resume.parse_resume_draft(raw_text, model=model)
    return {
        "draft_yaml": yaml.dump(result["draft"], sort_keys=False),
        "validation_log": result["validation_log"],
        "raw_text": raw_text,
        "suggested_label": result["draft"].get("basics", {}).get("name") or "",
    }


class ConfirmMasterResumeRequest(BaseModel):
    label: str
    yaml_text: str


@app.post("/api/master-resumes/confirm")
def confirm_master_resume(body: ConfirmMasterResumeRequest):
    """Write the (possibly hand-edited) reviewed draft into the library
    under `label`. Same label as an existing entry -> treated as a refresh
    of that resume (backs up its previous content first, same safety net
    as before); a new label -> adds a new entry alongside the others.
    Never destroys another named resume."""
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "A name is required for this resume")

    try:
        parsed = yaml.safe_load(body.yaml_text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"Not valid YAML: {e}")

    if not isinstance(parsed, dict) or not all(k in parsed for k in ("basics", "skills", "experience")):
        raise HTTPException(400, "Missing required top-level keys: basics, skills, experience")

    slug = _slugify(label)
    path = _resume_path(slug)

    if path.exists():
        RESUME_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = RESUME_BACKUPS_DIR / f"{slug}_{timestamp}.yaml"
        backup_path.write_text(path.read_text())

    MASTER_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(body.yaml_text)

    index = _load_resume_index()
    index[slug] = {"label": label, "updated_at": datetime.now().isoformat()}
    _save_resume_index(index)

    return {"ok": True, "slug": slug}


@app.delete("/api/master-resumes/{slug}")
def delete_master_resume(slug: str):
    """Removes a named resume from the library. Backs it up first (same
    mechanism as an overwrite) rather than a bare delete -- recoverable by
    hand if this turns out to be a mistake. Applications that already used
    this resume keep their own resume_name string regardless (a plain
    snapshot, not a reference to the file), so deleting doesn't corrupt
    any historical record. Refuses to delete the last resume in the
    library -- the dashboard should never be left with zero to choose from."""
    index = _load_resume_index()
    if slug not in index:
        raise HTTPException(404, "no such resume")
    if len(index) <= 1:
        raise HTTPException(400, "Can't delete the only resume in the library")

    path = _resume_path(slug)
    if path.exists():
        RESUME_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = RESUME_BACKUPS_DIR / f"{slug}_{timestamp}_deleted.yaml"
        backup_path.write_text(path.read_text())
        path.unlink()

    del index[slug]
    _save_resume_index(index)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}
