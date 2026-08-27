# CLAUDE.md

Guidance for Claude Code when working in this repository. See `ARCHITECTURE.md` and `ROADMAP.md` for full context — this file is the day-to-day operating rules.

## What this project is

A personal job-application pipeline: paste a JD → score against my resume → generate a tailored resume + cover letter → (later) find a verified hiring contact → draft outreach → I review and send manually. Built incrementally per `ROADMAP.md`.

## Repo structure
```
data/
  master_resume.yaml       # source of truth, structured, tagged bullets
  applications.db          # SQLite — one row per application
agents/
  ingest_jd.py
  score.py
  tailor.py
  cover_letter.py
  find_contact.py
  draft_outreach.py
render/
  resume_template.docx
  render.py
review/
  cli.py                   # review queue
outputs/
  <company>_<role>_<date>/
    resume.docx
    cover_letter.docx
    outreach_draft.md
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
(fill in as they're built, e.g.)
- `python agents/score.py --jd path/to/jd.txt` — score JD against master resume
- `python review/cli.py` — open the review queue
