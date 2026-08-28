# Job Application Agent System — Architecture

## 1. Philosophy

This is a **pipeline of specialized agents with human checkpoints**, not one big autonomous agent. Every stage has a strict input/output contract (structured JSON in, structured JSON out) so it can be tested, re-run, and debugged in isolation. Sending anything (email, application) always requires a manual confirmation step.

Core principle: **the resume is data, not a document.** Everything downstream — tailoring, scoring, cover letters — reads/writes structured fields. The .docx/.pdf is a rendering step at the very end, not the source of truth.

---

## 2. Data model (source of truth)

### `data/master_resume.yaml`
```yaml
basics:
  name: ""
  email: ""
  phone: ""
  location: ""
  links: {linkedin: "", github: "", portfolio: ""}

summary_variants:
  - id: "general"
    text: ""

skills:
  - name: "Python"
    tags: ["backend", "data"]
    years: 5

experience:
  - id: "exp_001"
    company: ""
    title: ""
    start: "2022-01"
    end: "present"
    bullets:
      - id: "b_001"
        text: ""
        tags: ["leadership", "python", "scale"]
        metrics: true   # has quantified impact
      - id: "b_002"
        text: ""
        tags: ["data-pipeline"]

education: [...]
projects: [...]
certifications: [...]
```

Every bullet gets an `id` and `tags`. Tailoring = **selecting, reordering, and lightly rewording** tagged bullets to match a JD's tags — never inventing new ones. This keeps hallucination risk near zero and makes tailoring fast/cheap (small diffs, not full regeneration).

### `data/applications.db` (SQLite)
```sql
applications(
  id, created_at, company, role_title, jd_raw, jd_parsed_json,
  match_score, resume_variant_path, cover_letter_path,
  status,          -- drafted | applied | outreach_sent | interview | rejected | ghosted | offer
  contact_name, contact_email, contact_source, contact_verified,
  outreach_sent_at, response_received, notes
)

resume_versions(
  id, application_id, diff_from_master, created_at, file_path
)
```

This DB is the actual product. After ~30 applications, you can query which bullet tags / resume structures correlate with responses — something no SaaS tool gives you since they don't see your outcomes.

---

## 3. Pipeline stages (agents)

Each stage = one Claude Code subagent / skill with a narrow job.

### Stage 0 — JD Ingest
**In:** raw JD text or URL
**Out:** `jd_parsed.json` — `{role, company, seniority, must_have_skills[], nice_to_have[], responsibilities[], keywords[]}`
**Notes:** if URL, fetch and strip boilerplate before parsing. Cache parsed JDs by hash to avoid re-parsing.

### Stage 1 — Scoring
**In:** `jd_parsed.json` + `master_resume.yaml`
**Out:** `{overall_score, matched_skills[], missing_skills[], reword_opportunities[], hard_gaps[], top_missing_keywords[] (max 5), red_flags[] (max 3)}`
**Notes:** Separate "gaps you can reword toward" from "gaps you genuinely don't have" — don't let the tailoring stage paper over the second kind. Prompted with a senior-recruiter persona: score + gaps as before, plus a fast hiring-manager read (`top_missing_keywords`, `red_flags`) for a quick gut-check before the full tailoring pass.

### Stage 2 — Tailoring
**In:** `jd_parsed.json` + scoring output + master resume
**Out:** `{tailored_resume, diff_summary[], unaddressed_hard_gaps[], unaddressed_red_flags[], ats_scan_notes[]}` — `tailored_resume` is a filtered/reordered/lightly-reworded subset of master bullets, never new content
**Hard rule (put this in CLAUDE.md):** no new claims, numbers, or skills not present in the master resume.
**Notes:** Enforced in code, not just prompted — every selected bullet/skill/experience id is validated against `master_resume.yaml` (unknown ids dropped), and a reworded bullet is reverted to its original text if it introduces a number not present in the source bullet. Experience entries keep master-resume chronological order regardless of model output order; projects keep the model's relevance-ranked order. Rejections are appended to `diff_summary` so they're visible in review. The scoring output's `top_missing_keywords` and `red_flags` are explicit priorities for this stage — genuinely-covered ones get surfaced in the tailored bullets (using an "accomplished X, measured by Y, by doing Z" reword formula built only from facts already in the original bullet); ones with no real coverage are listed back out in `unaddressed_hard_gaps`/`unaddressed_red_flags` rather than faked. The model also self-reviews its own output as an ATS/hiring-manager skim ("200 resumes in one sitting") and rewrites any bullet that would get skipped as too generic/vague — logged in `ats_scan_notes`.

### Stage 3 — Render
**In:** `tailored_resume.yaml`
**Out:** `.docx`/`.pdf` via a template (use the docx skill)
**Notes:** keep 1–2 visual templates, not one-off formatting per application.

### Stage 4 — Cover Letter
**In:** `jd_parsed.json` + `tailored_resume.yaml`
**Out:** `cover_letter.md` → rendered doc
**Notes:** independent from Stage 2 so either can be regenerated alone.

### Stage 5 — Contact Discovery
**In:** company name, role
**Out:** `{name, title, email, source, verified: bool}[]`
**Notes:** Use Hunter.io/Apollo API or public company team/press pages — not LinkedIn scraping (ToS risk + account ban risk). Anything unverified gets flagged, never auto-used.

### Stage 6 — Outreach Draft
**In:** contact + jd_parsed + tailored_resume summary
**Out:** `outreach_draft.md`
**Notes:** drafts only. Lands in a review queue.

### Stage 7 — Review Queue (human checkpoint)
A simple local view (CLI table or lightweight web UI) listing pending drafts: resume diff, cover letter, outreach email, contact confidence. You approve/edit/send from here. **Sending is the one action that is never automated.**

---

## 4. Tech stack

- **Language:** Python (best library support for resume parsing, email APIs, SQLite)
- **State:** SQLite (`applications.db`) — simple, local, queryable
- **Resume source of truth:** YAML
- **Orchestration:** Claude Code with one skill per pipeline stage (see CLAUDE.md)
- **Email verification/finding:** Hunter.io or Apollo.io API (free tier is enough at your volume)
- **Sending:** Gmail API, OAuth, draft-then-confirm — never blind SMTP send
- **Rendering:** docx skill for Word output
- **Review UI:** start with a CLI (`rich`/`textual` table) — upgrade to a small Streamlit app only if the CLI starts feeling limiting

---

## 5. Guardrails (non-negotiable)

1. Tailoring/cover-letter agents may only reorder, filter, or lightly reword existing resume content — never fabricate experience, metrics, or skills.
2. No email is ever sent without landing in the review queue first and getting explicit approval.
3. Contact discovery only uses verified sources (API-verified emails or direct company pages) — no scraping LinkedIn profiles.
4. Every generated resume/cover-letter version is saved and linked to the application row, so nothing is ever silently overwritten.
5. Unverified contacts are visibly flagged as unverified in the review queue, never silently treated as equal to verified ones.
