# Resume Builder Agent

A personal job-application pipeline: paste a job description, and it scores it against your resume, generates a tailored resume + cover letter, finds a verified hiring contact, drafts outreach, and tracks everything in a local database — with a review-and-approve step before anything is ever sent.

Built as a set of small, single-purpose agents (each one Python + the Anthropic API) orchestrated by one script, with a FastAPI backend and a React dashboard on top.

## Why this instead of just pasting into a chat window

The model capability is the same either way. What this adds:

- **Guardrails enforced in code, not just prompted.** Tailoring and cover-letter generation can only reorder, filter, or lightly reword your real resume content — fabricated metrics, dropped technical detail, and unsupported claims are caught and reverted (or retried) by code, not by hoping the prompt holds. See `ARCHITECTURE.md` section 5.
- **A structured source of truth.** Your resume lives as tagged, structured data (`data/master_resumes/`), not prose re-typed into a chat every time.
- **Everything is tracked.** Every generated resume/cover letter version, every score, every contact, and every outreach draft is logged to a local SQLite database and never silently overwritten.
- **Nothing sends itself.** Outreach emails land in a review queue and only go out on an explicit, confirmed click.

Chat is simpler for a single one-off application. This is for repetition and volume.

## Features

- **Score** a job description against your resume (hard/nice-to-have gap analysis)
- **Tailor** your resume for a specific role — Honest mode (selection/reordering only, bullet text locked) or Aggressive mode (also rewords, still 100% non-fabricating)
- **Generate a cover letter** — every claim is cited back to a real resume bullet and verified in code
- **Render** to `.docx` and `.pdf`, laid out to fit one page automatically
- **Find a verified hiring contact** for the company (Hunter.io), with relevance boosting for HR/department matches and named-in-JD hiring managers
- **Draft outreach** (cold or referral-ask), editable before sending
- **Send** via your own Gmail account, with attachments verified present before anything goes out
- **A named resume library** — upload as many resumes as you want, pick which one to use per application, see which one was used on every past application
- **A review dashboard** (React + FastAPI) to run the whole pipeline and review every stage

## Setup

**Requirements:** Python 3.10+, Node 18+, an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone <this-repo>
cd Resume_Builder_Tool
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY at minimum
```

Start the backend and frontend:

```bash
cd review/backend && uvicorn main:app --reload --port 8000
```

```bash
cd review/frontend && npm install && npm run dev
```

Open `http://localhost:5173`. On first run, go to the dashboard's **Resume** page and upload your resume — it gets parsed, you review the draft, and confirm before it's saved. Nothing about this tool works without that step; there's no resume checked into the repo.

`HUNTER_API_KEY` (contact discovery) and `GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD` (sending) are optional — the pipeline runs fully without them, those two features just won't be available. See `.env.example` for where to get each.

## Using it from the command line instead

Every stage is also a standalone script — see `CLAUDE.md`'s Commands section for the full list. The full pipeline:

```bash
python apply.py --jd-file path/to/jd.txt --resume data/master_resumes/main.yaml
```

## Project structure and design docs

- **`ARCHITECTURE.md`** — data model, every pipeline stage, guardrails, tech stack
- **`CLAUDE.md`** — day-to-day operating rules and the full command reference
- **`ROADMAP.md`** — what's built, what's next
- **`LEARNING_LOG.md`** — a teaching-voice log of real bugs found and design decisions made while building this, written as the author learned agent-building alongside the project

## Guardrails, briefly

1. Tailoring/cover-letter agents may only reorder, filter, or lightly reword existing resume content — never fabricate experience, metrics, or skills.
2. No email is ever sent without landing in a review queue first and getting explicit approval.
3. Contact discovery only uses verified sources (Hunter.io API) — no scraping.
4. Every generated resume/cover-letter version is saved and linked to its application, never silently overwritten.
5. Unverified contacts are visibly flagged as unverified, never treated as equal to verified ones.

Full detail in `ARCHITECTURE.md`.

## Testing

```bash
python -m pytest tests/
```

52 tests, fully mocked, no API calls, runs in under a second. Covers every guardrail above.

## License

MIT — see `LICENSE`.
