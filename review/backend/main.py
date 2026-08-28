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

import json
import sqlite3
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

import apply  # noqa: E402  (must follow sys.path insert)
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

DB_PATH = REPO_ROOT / "data" / "applications.db"
OUTPUTS_DIR = REPO_ROOT / "outputs"
RESUME_PATH = REPO_ROOT / "data" / "master_resume.yaml"

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
    model: Optional[str] = None
    mode: Optional[str] = None


def _run_job(job_id: str, jd_text: str, company: Optional[str], role: Optional[str], model: str, mode: str):
    def report(stage: str):
        with JOBS_LOCK:
            JOBS[job_id]["stage"] = stage

    try:
        result = apply.run_pipeline(
            jd_text,
            company_override=company,
            role_override=role,
            model=model,
            mode=mode,
            outputs_dir=OUTPUTS_DIR,
            db_path=DB_PATH,
            resume_path=RESUME_PATH,
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
        body.model or apply.DEFAULT_MODEL, body.mode or "aggressive",
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
            "SELECT id, created_at, company, role_title, match_score, status, mode "
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


class UpdateApplicationRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


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
    if type not in ("pdf", "docx"):
        raise HTTPException(400, "type must be 'pdf' or 'docx'")
    conn = _get_db()
    try:
        row = conn.execute("SELECT resume_variant_path FROM applications WHERE id = ?", (app_id,)).fetchone()
    finally:
        conn.close()
    if row is None or not row["resume_variant_path"]:
        raise HTTPException(404, "application or resume file not found")

    stored_path = Path(row["resume_variant_path"])
    docx_path = stored_path if stored_path.is_absolute() else REPO_ROOT / stored_path
    file_path = docx_path if type == "docx" else docx_path.with_suffix(".pdf")
    if not file_path.exists():
        raise HTTPException(404, "file not found on disk")

    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if type == "docx"
        else "application/pdf"
    )
    return FileResponse(str(file_path), media_type=media_type, filename=file_path.name)


@app.get("/api/health")
def health():
    return {"ok": True}
