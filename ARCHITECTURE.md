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
**Out:** `{tailored_resume, diff_summary[], unaddressed_hard_gaps[], unaddressed_red_flags[], unaddressed_reword_opportunities[], ats_scan_notes[], score_before, score_after, overall_score_delta}` — `tailored_resume` is a filtered/reordered/lightly-reworded subset of master bullets, never new content. `score_before` is the scoring-stage input passed through; `score_after` re-runs Stage 1's own scoring function against the finished `tailored_resume` so the impact of tailoring is measured, not assumed — this makes every tailoring run two model calls, not one.
**Hard rule (put this in CLAUDE.md):** no new claims, numbers, or skills not present in the master resume.
**Notes:** Enforced in code, not just prompted — every selected bullet/experience/project id is validated against `master_resume.yaml` (unknown ids dropped), a reworded bullet is reverted to its original text if it introduces a number, drops or adds a named skill/tech term from the master resume's *global* vocabulary (all skill names + every project's `tech` list, not scoped to that bullet's own project — applies to experience bullets too, not just project bullets) without it being a textual expansion of something already there, or staples a "-- demonstrating X" clause onto the end instead of actually rewording (this last one is a structural check — new text == original + a trailing --/em-dash clause — added after prompt-only enforcement of it proved unreliable across repeated runs). Every selected skill must resolve to a real `master_skill_name` (an optional `display_as` allows a JD-matching relabel of that *same* skill — e.g. "LLM agent development" shown as "Agentic AI solutions" — but the underlying skill must be real; an unresolvable `master_skill_name` is dropped). Experience, projects, education, and certifications are all sorted strictly reverse-chronological in code (`_date_rank()`, parsed from each entry's date field(s) — "present" ranks above any fixed date), regardless of model output order — not left to the model's judgment. Rejections/relabels are appended to `diff_summary`, along with a code-computed ground truth of which bullet ids and skills actually changed (independent of the model's own self-reported notes, which can otherwise describe an edit that didn't actually happen). Every item in the scoring output's `reword_opportunities` must be addressed this pass (relabel, reword, or reorder) — these exist specifically because score.py already determined the master resume genuinely covers them, so skipping one is a miss, not caution; `unaddressed_reword_opportunities` should normally come back empty, and a warning is logged if it doesn't. The scoring output's `top_missing_keywords` and `red_flags` are handled the same way but with a real "no coverage" escape hatch — genuinely-covered ones get surfaced via reword (an "accomplished X, measured by Y, by doing Z" formula built only from facts already in the bullet, never adding a claim/technology the bullet didn't already make) or via skill relabeling/selection/ordering; ones with no real coverage are listed back out in `unaddressed_hard_gaps`/`unaddressed_red_flags` rather than faked. The model also self-reviews its own output as an ATS/hiring-manager skim ("200 resumes in one sitting") and rewrites any bullet that would get skipped as too generic/vague — logged in `ats_scan_notes`. The prompt explicitly warns against over-correcting into making zero changes: the guardrails constrain *what* a change must look like, not *whether* to make one.

### Stage 3 — Render
**In:** the `tailored_resume` dict (tailor.py's output, or its `tailored_resume` key alone)
**Out:** `<Firstname>_<Lastname>_<Company>_<Role>.docx` + `.pdf` under `outputs/<company>_<role>_<date>/`
**Notes:** `render/render.py` (one file, one consistent style — not one-off formatting per application). docx is built with `python-docx`; pdf is an independent render with `reportlab`, not a docx→pdf conversion — Word's AppleScript `save as` automation (`docx2pdf`) is broken on the dev machine's Word build (command exists in Word's own `.sdef` but is rejected at runtime, error -1708), and a pure-Python PDF library avoids depending on any installed app at all. Both use Calibri: docx by font-name reference (relies on the reader having it installed — standard resume-building practice); pdf by embedding the actual Calibri TTF files bundled with this machine's Word install (`_register_calibri_fonts()`), since a PDF needs real font data, not just a name — falls back to Helvetica with a printed warning if no Calibri file is found on the machine. Dates are formatted with abbreviated month names (`_format_month_year()` — "2024-05" → "May 2024"; "present" → "Present"; a bare year like "2025" passes through unchanged). Refuses to overwrite an existing `outputs/` folder (hard rule 4 — every output is versioned).

**Hard one-page rule:** the resume must render to exactly one page, and content is never dropped to force that — every bullet/skill the tailoring stage selected must appear. `find_one_page_layout()` searches a fixed sequence of (margin, font-scale) candidates from most spacious to most compact — margins tighten to a 0.4in floor before font scale is touched at all, since smaller margins don't hurt readability the way smaller text does — using the reportlab PDF render as ground truth (exact page count via `pypdf`) and picking the first candidate that fits. If even the most compact candidate still overflows, that layout is used anyway with a printed warning rather than truncating content. The winning (margin, scale) is applied to both the pdf and the docx render; the docx's one-page fit is therefore a close estimate calibrated off the PDF, not independently verified, since docx has no accessible pagination info without an actual rendering engine (Word's automation is broken; no LibreOffice installed).

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
- **Orchestration:** standalone Python scripts in `agents/`, one per pipeline stage, each calling the Anthropic API directly (see CLAUDE.md) — not Claude Code skills
- **Email verification/finding:** Hunter.io or Apollo.io API (free tier is enough at your volume)
- **Sending:** Gmail API, OAuth, draft-then-confirm — never blind SMTP send
- **Rendering:** `python-docx` for `.docx`, `reportlab` for `.pdf` (independent renders, not a docx→pdf conversion — see Stage 3 notes)
- **Review UI:** start with a CLI (`rich`/`textual` table) — upgrade to a small Streamlit app only if the CLI starts feeling limiting

---

## 5. Guardrails (non-negotiable)

1. Tailoring/cover-letter agents may only reorder, filter, or lightly reword existing resume content — never fabricate experience, metrics, or skills.
2. No email is ever sent without landing in the review queue first and getting explicit approval.
3. Contact discovery only uses verified sources (API-verified emails or direct company pages) — no scraping LinkedIn profiles.
4. Every generated resume/cover-letter version is saved and linked to the application row, so nothing is ever silently overwritten.
5. Unverified contacts are visibly flagged as unverified in the review queue, never silently treated as equal to verified ones.
