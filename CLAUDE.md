# CLAUDE.md

Guidance for Claude Code when working in this repository. See `ARCHITECTURE.md` and `ROADMAP.md` for full context — this file is the day-to-day operating rules.

## What this project is

A personal job-application pipeline: paste a JD → score against my resume → generate a tailored resume + cover letter → (later) find a verified hiring contact → draft outreach → I review and send manually. Built incrementally per `ROADMAP.md`.

## Repo structure
```
apply.py                   # orchestrator: ingest -> score -> tailor -> render -> log
data/
  master_resumes/          # gitignored (contains real PII, possibly of more than one person)
                            # -- a NAMED LIBRARY of resumes, not a single file. <slug>.yaml per
                            # resume + _index.json (slug -> {label, updated_at}). Add/refresh one
                            # any time via the dashboard's "Resume" page (upload -> review ->
                            # confirm) -- never hand it a raw upload without reviewing the draft
                            # first. Each application logs which named resume it used
                            # (applications.resume_name), so it's never ambiguous later.
  master_resume_backups/   # gitignored -- one timestamped backup made automatically before any
                            # overwrite or delete in the library above
  schema.sql                # versioned applications.db schema (the .db itself is gitignored)
  applications.db          # SQLite — one row per application; gitignored, auto-created from
                            # schema.sql on first use (apply.ensure_schema) if missing
agents/
  parse_resume.py          # Stage -1, always-available onboarding -- see ARCHITECTURE.md
  ingest_jd.py
  score.py
  tailor.py
  cover_letter.py          # Stage 4, opt-in per run -- see ARCHITECTURE.md
  find_contact.py          # Stage 5, on-demand per application -- see ARCHITECTURE.md
  draft_outreach.py        # Stage 6, on-demand per application, draft-only -- see ARCHITECTURE.md
render/
  render.py                # builds docx (python-docx) + pdf (reportlab) programmatically,
                            # no template file -- see ARCHITECTURE.md Stage 3
review/
  backend/
    main.py                 # FastAPI: wraps apply.py's pipeline as a REST API + job polling
    gmail_client.py          # sends outreach email via SMTP + Gmail App Password -- see hard rule 2
  frontend/                 # React (Vite + TS + Tailwind): paste-JD-to-review web UI
outputs/
  <company>_<role>_<date>/
    <Firstname>_<Lastname>_<Company>_<Role>.docx
    <Firstname>_<Lastname>_<Company>_<Role>.pdf
    <Firstname>_<Lastname>_<Company>_<Role>_Cover_Letter.docx/.pdf  # only when requested
    outreach_draft.md      # only when requested -- re-editable draft, overwritten on regeneration
```

## Hard rules — do not violate these

1. **Never fabricate resume content.** Tailoring and cover-letter agents may only select, reorder, and lightly reword bullets that already exist in `master_resume.yaml`. If a JD requirement isn't covered by any tagged bullet, surface it as a gap — do not invent a bullet or metric to cover it.
2. **Never auto-send.** Outreach emails and application submissions always land in `review/` for manual approval. No agent calls a "send" API without an explicit user confirmation step in that run. In practice: `review/backend/gmail_client.py` is the only code path in the entire codebase that can send an email, it's called from exactly one endpoint (`POST /api/applications/{id}/send-outreach`), and that endpoint only fires on an explicit confirmed click in the frontend's send-confirmation modal (shows the exact recipient/subject/body before sending). No pipeline stage or agent ever calls it.
3. **Never scrape LinkedIn profiles for contact info.** Use Hunter.io/Apollo API or direct company website sources only. Flag unverified contacts clearly — don't silently treat them as equal to verified ones. In practice this is Hunter.io only — confirmed directly against both providers' pricing pages that Apollo's free plan has no API access at all (gated behind a "Custom"/enterprise plan), while Hunter's free plan does (50 credits/month). `find_contact.py`'s `verified` field is only ever `True` when Hunter's own status is `"valid"` — never for `"accept_all"` or `"unknown"`.
4. **Every output is versioned.** Write new files per application into `outputs/<company>_<role>_<date>/`, never overwrite a previous version. Log the application in `applications.db` immediately after generation, not after sending.
5. **Structured in, structured out.** Every agent stage takes and returns JSON/YAML matching the schemas in `ARCHITECTURE.md`. If a stage needs to change its schema, update `ARCHITECTURE.md` in the same commit.
6. **Tailoring can never score lower than doing nothing.** `tailor.py` rescores its own output; if that rescore comes in below the untouched master resume's original score, the tailoring is discarded and the full master resume is used unchanged instead. Enforced in code (`tailor_resume`'s guardrail, not a prompt instruction) by falling back to the exact content the original score was measured against — a guarantee, not a best-effort check.

## Working style

- Build and test one pipeline stage at a time (see `ROADMAP.md` phases) — don't wire the full pipeline before each stage is verified independently on a few real JDs.
- When adding a new agent, write it as a pure function: JSON in, JSON out, no side effects (no DB writes, no file writes, no network calls beyond its one job). Orchestration/persistence happens one layer up.
- Prefer small, inspectable diffs in tailored resumes over full regeneration — makes hallucination easy to spot in review.
- When in doubt about a scope decision, default to the more conservative/manual option and ask rather than automating further.
- Run `python -m pytest tests/` before considering a change to any guardrail-bearing agent done — it's fast, free, and mocked (see Commands below). Add a new test alongside any new guardrail rather than only verifying it ad hoc and discarding the script.

## Commands
- `python agents/parse_resume.py --file path/to/resume.txt [--model claude-sonnet-5|claude-haiku-4-5]` — Stage -1 alone (raw text in, draft JSON out, never writes anything). The dashboard's "Resume" page wraps this with file upload (.pdf/.docx) + a naming/review-and-edit step before anything gets saved into `data/master_resumes/<slug>.yaml` — always available (add or refresh a resume any time), not just a first-run step.
- `python apply.py --jd-file path/to/jd.txt` — run the full pipeline (ingest → score → tailor → render) and log it to `applications.db`. Add `--company`/`--role` to override auto-extracted values, `--mode honest|aggressive` to control tailoring intensity (default `aggressive`; see ARCHITECTURE.md Stage 2 — neither mode fabricates), `--tailor-model <model>` to pick the model for tailoring only (ingest/scoring always use their own fast default — see ARCHITECTURE.md Stage 7), `--cover-letter` to also generate a cover letter (off by default — one more paid API call), `--resume path/to/master_resumes/<slug>.yaml` to pick which library entry to use (default `data/master_resumes/main.yaml`), `--resume-name "Label"` to log a human-readable name on the application row (defaults to the file's own stem).
- `python agents/ingest_jd.py --file path/to/jd.txt` — Stage 0 alone
- `python agents/score.py --jd-json path/to/jd_parsed.json` — Stage 1 alone
- `python agents/tailor.py --jd-json ... --score-json ... [--mode honest|aggressive]` — Stage 2 alone
- `python agents/cover_letter.py --jd-json ... --tailored-resume-json ...` — Stage 4 alone (needs a `tailored_resume` dict, not the raw master resume)
- `python agents/find_contact.py --company "Some Company"` — Stage 5 alone. Needs `HUNTER_API_KEY` in `.env` (free plan, 50 credits/month — sign up at hunter.io; Apollo.io is not usable here, see hard rule 3).
- `python agents/draft_outreach.py --jd-json ... --tailored-resume-json ... --company ... [--contact-name ...] [--has-cover-letter]` — Stage 6 alone. Draft-only, never sends anything (hard rule 2).
- Sending a drafted email (via the dashboard's "Send email" button only, see hard rule 2) needs `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `.env` — enable 2-Step Verification on your Google account, generate an App Password at myaccount.google.com/apppasswords, then add both to `.env`. Nothing is hardcoded to any specific account — anyone running this repo sets up their own.
- `python render/render.py --tailored-json ... --company ... --role ...` — Stage 3 alone
- `cd review/backend && uvicorn main:app --reload --port 8000` — start the review API (needs `.env` at repo root). **`--reload` only watches `review/backend/` by default — it does NOT pick up edits to `agents/*.py`, `apply.py`, or `render/render.py`, since those live outside that directory.** After editing anything outside `review/backend/`, restart the uvicorn process manually (kill it and relaunch) — confirmed the hard way: a long-running server silently served pre-fix `tailor.py` code for an entire debugging session because of this. Don't assume a running dashboard reflects the latest agent/pipeline code without checking when the backend process was last started.
- `cd review/frontend && npm run dev` — start the review web UI (http://localhost:5173), needs the backend running
- `python -m pytest tests/` — run the regression suite for every guardrail (fabrication checks, verified-status mapping, the turfgrass-style distinctive-detail retry, attachment enforcement, etc.). Fully mocked — no API calls, no cost, runs in under a second. Run this after touching `agents/*.py` or `review/backend/gmail_client.py`, before trusting the change; it does NOT run automatically as part of a real pipeline execution and never touches real data.
