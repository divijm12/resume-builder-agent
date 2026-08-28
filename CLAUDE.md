# CLAUDE.md

Guidance for Claude Code when working in this repository. See `ARCHITECTURE.md` and `ROADMAP.md` for full context — this file is the day-to-day operating rules.

## What this project is

A personal job-application pipeline: paste a JD → score against my resume → generate a tailored resume + cover letter → (later) find a verified hiring contact → draft outreach → I review and send manually. Built incrementally per `ROADMAP.md`.

## Repo structure
```
apply.py                   # orchestrator: ingest -> score -> tailor -> render -> log
data/
  master_resume.yaml       # source of truth, structured, tagged bullets
  schema.sql                # versioned applications.db schema (the .db itself is gitignored)
  applications.db          # SQLite — one row per application
agents/
  ingest_jd.py
  score.py
  tailor.py
  cover_letter.py          # not yet built (Phase 2)
  find_contact.py          # not yet built (Phase 4)
  draft_outreach.py        # not yet built (Phase 5)
render/
  render.py                # builds docx (python-docx) + pdf (reportlab) programmatically,
                            # no template file -- see ARCHITECTURE.md Stage 3
review/
  backend/
    main.py                 # FastAPI: wraps apply.py's pipeline as a REST API + job polling
  frontend/                 # React (Vite + TS + Tailwind): paste-JD-to-review web UI
outputs/
  <company>_<role>_<date>/
    <Firstname>_<Lastname>_<Company>_<Role>.docx
    <Firstname>_<Lastname>_<Company>_<Role>.pdf
    cover_letter.docx      # not yet built (Phase 2)
    outreach_draft.md      # not yet built (Phase 5)
```

## Hard rules — do not violate these

1. **Never fabricate resume content.** Tailoring and cover-letter agents may only select, reorder, and lightly reword bullets that already exist in `master_resume.yaml`. If a JD requirement isn't covered by any tagged bullet, surface it as a gap — do not invent a bullet or metric to cover it.
2. **Never auto-send.** Outreach emails and application submissions always land in `review/` for manual approval. No agent calls a "send" API without an explicit user confirmation step in that run.
3. **Never scrape LinkedIn profiles for contact info.** Use Hunter.io/Apollo API or direct company website sources only. Flag unverified contacts clearly — don't silently treat them as equal to verified ones.
4. **Every output is versioned.** Write new files per application into `outputs/<company>_<role>_<date>/`, never overwrite a previous version. Log the application in `applications.db` immediately after generation, not after sending.
5. **Structured in, structured out.** Every agent stage takes and returns JSON/YAML matching the schemas in `ARCHITECTURE.md`. If a stage needs to change its schema, update `ARCHITECTURE.md` in the same commit.

## Working style

- Build and test one pipeline stage at a time (see `ROADMAP.md` phases) — don't wire the full pipeline before each stage is verified independently on a few real JDs.
- When adding a new agent, write it as a pure function: JSON in, JSON out, no side effects (no DB writes, no file writes, no network calls beyond its one job). Orchestration/persistence happens one layer up.
- Prefer small, inspectable diffs in tailored resumes over full regeneration — makes hallucination easy to spot in review.
- When in doubt about a scope decision, default to the more conservative/manual option and ask rather than automating further.

## Commands
- `python apply.py --jd-file path/to/jd.txt` — run the full pipeline (ingest → score → tailor → render) and log it to `applications.db`. Add `--company`/`--role` to override auto-extracted values, `--mode honest|aggressive` to control tailoring intensity (default `aggressive`; see ARCHITECTURE.md Stage 2 — neither mode fabricates).
- `python agents/ingest_jd.py --file path/to/jd.txt` — Stage 0 alone
- `python agents/score.py --jd-json path/to/jd_parsed.json` — Stage 1 alone
- `python agents/tailor.py --jd-json ... --score-json ... [--mode honest|aggressive]` — Stage 2 alone
- `python render/render.py --tailored-json ... --company ... --role ...` — Stage 3 alone
- `cd review/backend && uvicorn main:app --reload --port 8000` — start the review API (needs `.env` at repo root). **`--reload` only watches `review/backend/` by default — it does NOT pick up edits to `agents/*.py`, `apply.py`, or `render/render.py`, since those live outside that directory.** After editing anything outside `review/backend/`, restart the uvicorn process manually (kill it and relaunch) — confirmed the hard way: a long-running server silently served pre-fix `tailor.py` code for an entire debugging session because of this. Don't assume a running dashboard reflects the latest agent/pipeline code without checking when the backend process was last started.
- `cd review/frontend && npm run dev` — start the review web UI (http://localhost:5173), needs the backend running
