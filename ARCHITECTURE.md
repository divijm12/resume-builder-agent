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

summary_variants:            # present in the file, NOT consumed by any stage yet -- known unused field
  - id: "general"
    text: ""

skills:
  - name: "Python"
    tags: ["backend", "data"]  # no `years` field in practice

experience:
  - id: "exp_001"
    company: ""
    title: ""
    start: "2024-05"
    end: "present"            # or a real "YYYY-MM" date; "present" ranks highest in _date_rank
    bullets:
      - id: "b_001"
        text: ""
        tags: ["data-pipeline", "etl", "python"]
        metrics: true          # has quantified impact -- present in the data, not read by tailor.py's
                                # guardrails (those key off exact-text matching against skill names/tech
                                # lists, not tags); still useful as a human-readable hint in the file

projects:
  - id: "proj_001"
    name: ""
    status: "in-progress"
    date: "present"
    tech: ["Python", "PostgreSQL"]   # protects these terms from being dropped in a reworded bullet
    bullets: [...]                    # same {id, text, tags, metrics} shape as experience bullets

education:
  - degree: ""
    institution: ""
    honors: ""
    start: ""
    end: "2025-05"    # real graduation date -- score.py computes time-since-graduation from this
                       # (added 2026-08-30); leave blank only if genuinely not yet graduated

certifications:
  - name: ""
    year: 2025
```

Every bullet gets an `id` and `tags`. Tailoring = **selecting, reordering, and lightly rewording** bullets to match a JD's requirements — never inventing new ones. This keeps hallucination risk near zero and makes tailoring fast/cheap (small diffs, not full regeneration). In practice, the guardrails that actually gate a reword (see Stage 2) key off exact-text matching against `skills[].name` and `projects[].tech[]`, not the per-bullet `tags` — tags are there for human scanning, not enforcement.

### `data/applications.db` (SQLite)
Versioned in `data/schema.sql` (tracked in git — the live `.db` itself is gitignored, contains personal data). Current shape:
```sql
applications(
  id, created_at, company, role_title, jd_raw, jd_parsed_json,
  match_score, resume_variant_path, cover_letter_path,
  tailor_result_json,  -- full tailor.py output as one JSON blob (tailored_resume, diff_summary,
                        -- validation_log, unaddressed_*, ats_scan_notes, score_before/after,
                        -- overall_score_delta) -- everything the review UI needs without re-deriving
  mode,                -- 'honest' | 'aggressive' (default), see Stage 2 -- reword intensity only,
                        -- neither mode fabricates
  status,               -- drafted | applied | outreach_sent | interview | rejected | ghosted | offer
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
**In:** raw JD text (pasted) -- URL fetching and per-hash caching were part of the original plan below but never built; only raw pasted text is supported today
**Out:** `jd_parsed.json` — `{role, company, seniority, must_have_skills[], nice_to_have[], responsibilities[], keywords[]}`
**Notes (original plan, not implemented):** if given a URL, fetch and strip boilerplate before parsing; cache parsed JDs by hash to avoid re-parsing.

### Stage 1 — Scoring
**In:** `jd_parsed.json` + `master_resume.yaml`
**Out:** `{overall_score, matched_skills[], missing_skills[], reword_opportunities[], hard_gaps[], top_missing_keywords[] (max 5), red_flags[] (max 3)}`
**Notes:** Separate "gaps you can reword toward" from "gaps you genuinely don't have" — don't let the tailoring stage paper over the second kind. Prompted with a senior-recruiter persona: score + gaps as before, plus a fast hiring-manager read (`top_missing_keywords`, `red_flags`) for a quick gut-check before the full tailoring pass.

### Stage 2 — Tailoring
**In:** `jd_parsed.json` + scoring output + master resume + `mode` (`"honest"` | `"aggressive"`, default `"aggressive"`)
**Modes (added 2026-08-28):** naming and framing follow Tsenta (a real product in this space) — `"honest"` only selects, reorders, and relabels skills; bullet text is never touched, enforced in code (`validate_and_build` sets a selected bullet's text to the master resume's original unconditionally when `mode="honest"`, before any guardrail even runs — a model that ignored the honest-mode instruction still can't leak a reworded bullet through). `"aggressive"` is the original, heavily-tested behavior: selection/reordering/relabeling *and* bullet rewording. **Neither mode ever fabricates** — the same guardrails below apply in full to both; the modes differ only in reword intensity, not honesty. This mirrors Tsenta's own AI disclosure ("applications use only true facts from the resume you uploaded") applying to both of their client-side "Honest"/"Aggressive" options — confirmed by checking their actual product copy/docs before building this, after an initial request described a fabrication-permitting mode that doesn't match how either mode actually works there.
**Out:** `{tailored_resume, diff_summary[], validation_log[], unaddressed_hard_gaps[], unaddressed_red_flags[], unaddressed_reword_opportunities[], ats_scan_notes[], score_before, score_after, overall_score_delta}` — `tailored_resume` is a filtered/reordered/lightly-reworded subset of master bullets, never new content. `score_before` is the scoring-stage input passed through; `score_after` re-runs Stage 1's own scoring function against the finished `tailored_resume` so the impact of tailoring is measured, not assumed — this makes every tailoring run two model calls, not one. `diff_summary` is the model's own narrative of its selection/ordering/skill choices in plain language (no internal ids — the model is barred by prompt, and backstopped in code, from putting one in), plus code-generated lines noting which sections had bullets actually reworded (built only from bullets that survived every guardrail below, since the model is separately barred from narrating specific bullet-wording changes itself — its own pre-validation claim can describe an edit that gets reverted a moment later, which happened for real in production) — safe for direct end-user display. `validation_log` is the code-computed ground truth and guardrail actions described below — references master_resume.yaml bullet ids (e.g. "b_004") and raw rejection messages, so it's an audit trail for verifying the no-fabrication rule held, not written for end-user display; a UI should hide or collapse it rather than show it inline (split out 2026-08-28 after a user pointed out the review UI's "what changed" section was leaking internal bullet ids into plain view).
**Hard rule (put this in CLAUDE.md):** no new claims, numbers, or skills not present in the master resume.
**Notes:** Enforced in code, not just prompted — every selected bullet/experience/project id is validated against `master_resume.yaml` (unknown ids dropped), a reworded bullet is reverted to its original text if it introduces a number, drops or adds a named skill/tech term from the master resume's *global* vocabulary (all skill names + every project's `tech` list, not scoped to that bullet's own project — applies to experience bullets too, not just project bullets) without it being a textual expansion of something already there, or staples a "-- demonstrating X" clause onto the end instead of actually rewording (this last one is a structural check — new text == original + a trailing --/em-dash clause — added after prompt-only enforcement of it proved unreliable across repeated runs). Every selected skill must resolve to a real `master_skill_name` (an optional `display_as` allows a JD-matching relabel of that *same* skill — e.g. "LLM agent development" shown as "Agentic AI solutions" — but the underlying skill must be real; an unresolvable `master_skill_name` is dropped). Experience, projects, education, and certifications are all sorted strictly reverse-chronological in code (`_date_rank()`, parsed from each entry's date field(s) — "present" ranks above any fixed date), regardless of model output order — not left to the model's judgment. Rejections/relabels are appended to `validation_log` (not `diff_summary`), along with a code-computed ground truth of which bullet ids and skills actually changed (independent of the model's own self-reported notes, which can otherwise describe an edit that didn't actually happen). Every item in the scoring output's `reword_opportunities` must be addressed this pass (relabel, reword, or reorder) — these exist specifically because score.py already determined the master resume genuinely covers them, so skipping one is a miss, not caution; `unaddressed_reword_opportunities` should normally come back empty, and a warning is logged if it doesn't. The scoring output's `top_missing_keywords` and `red_flags` are handled the same way but with a real "no coverage" escape hatch — genuinely-covered ones get surfaced via reword (an "accomplished X, measured by Y, by doing Z" formula built only from facts already in the bullet, never adding a claim/technology the bullet didn't already make) or via skill relabeling/selection/ordering; ones with no real coverage are listed back out in `unaddressed_hard_gaps`/`unaddressed_red_flags` rather than faked. The model also self-reviews its own output as an ATS/hiring-manager skim ("200 resumes in one sitting") and rewrites any bullet that would get skipped as too generic/vague — logged in `ats_scan_notes`. The prompt explicitly warns against over-correcting into making zero changes: the guardrails constrain *what* a change must look like, not *whether* to make one. **Score guardrail (added 2026-08-28, user-specified, non-negotiable):** after rescoring, if `score_after < score_before`, everything this pass produced is discarded and `tailored_resume` falls back to the full, unmodified master resume (`_full_selection_plan` run through `validate_and_build` in `"honest"` mode) — `score_after` is then set to the same object as `score_before` rather than re-scored, since a fresh rescore of identical content is itself an LLM call and could return a slightly different number, which would turn a guarantee into a probability. `overall_score_delta` becomes exactly `0`, and every item from the scoring input's `hard_gaps`/`red_flags`/`reword_opportunities` is reported back out as unaddressed, since nothing was changed.

### Stage 3 — Render
**In:** the `tailored_resume` dict (tailor.py's output, or its `tailored_resume` key alone)
**Out:** `<Firstname>_<Lastname>_<Company>_<Role>.docx` + `.pdf` under `outputs/<company>_<role>_<date>/`
**Notes:** `render/render.py` (one file, one consistent style — not one-off formatting per application). docx is built with `python-docx`; pdf is an independent render with `reportlab`, not a docx→pdf conversion — Word's AppleScript `save as` automation (`docx2pdf`) is broken on the dev machine's Word build (command exists in Word's own `.sdef` but is rejected at runtime, error -1708), and a pure-Python PDF library avoids depending on any installed app at all. Both use Calibri: docx by font-name reference (relies on the reader having it installed — standard resume-building practice); pdf by embedding the actual Calibri TTF files bundled with this machine's Word install (`_register_calibri_fonts()`), since a PDF needs real font data, not just a name — falls back to Helvetica with a printed warning if no Calibri file is found on the machine. Dates are formatted with abbreviated month names (`_format_month_year()` — "2024-05" → "May 2024"; "present" → "Present"; a bare year like "2025" passes through unchanged). Refuses to overwrite an existing `outputs/` folder (hard rule 4 — every output is versioned).

**Hard one-page rule:** the resume must render to exactly one page, and content is never dropped to force that — every bullet/skill the tailoring stage selected must appear. `find_one_page_layout()` searches a fixed sequence of (margin, font-scale) candidates from most spacious to most compact — margins tighten to a 0.4in floor before font scale is touched at all, since smaller margins don't hurt readability the way smaller text does — using the reportlab PDF render as ground truth (exact page count via `pypdf`) and picking the first candidate that fits. If even the most compact candidate still overflows, that layout is used anyway with a printed warning rather than truncating content. The winning (margin, scale) is applied to both the pdf and the docx render; the docx's one-page fit is therefore a close estimate calibrated off the PDF, not independently verified, since docx has no accessible pagination info without an actual rendering engine (Word's automation is broken; no LibreOffice installed).

### Stage 4 — Cover Letter
Built 2026-08-30 (`agents/cover_letter.py`), opt-in per run (off by default --
one more paid API call).
**In:** `jd_parsed.json` + `tailored_resume` (the finished Stage 2 output,
not `master_resume.yaml` -- the letter's emphasis has to match what the
resume actually emphasizes for this JD, not the candidate's full untailored
history).
**Out:** `{cover_letter_text, validation_log, model}`, then rendered to
`<...>_Cover_Letter.docx/.pdf` in the same `outputs/` folder as the resume
(`render_cover_letter_docx`/`_pdf`, `find_one_page_layout_cover_letter` --
same Calibri/one-page-search infrastructure as the resume, adapted for a
single flowing letter instead of discrete sections).
**No-fabrication guardrail, adapted for free-form prose:** a resume bullet
that gets reworded badly has a known-good original to revert to; a cover
letter sentence doesn't. So instead, the model's structured output
(`CoverLetterDraft`, a list of paragraphs of `{text,
source_bullet_ids}` claims) must cite which real tailored-resume bullet(s)
ground each substantive claim; code then verifies every number in a claim
against its cited bullets' actual text (reusing `tailor.py`'s
`_numeric_tokens()`) and drops any claim that fails -- entirely, not
reworded, since there's no safe rewrite to fall back to -- logging the drop.
Verified live: a real run generated a letter whose every specific claim
(a "recurring data failures... by half" fix, a "40% API latency" reduction,
"100k+ records") traced back word-for-word to real tailored-resume bullets,
with a genuine opening hook instead of the "I am writing to express
interest..." cliché the prompt explicitly bans.
**Honest limitation:** unlike numbers, named skill/tech fabrication isn't
hard-blocked -- code can confirm a mentioned term IS real (in the master
resume's vocabulary) but can't enumerate every term that could be invented
from nothing. Same class of gap as `tailor.py`'s documented turfgrass/
genericization limitation; leans on prompting plus the fact that nothing in
this pipeline sends anything without manual review (CLAUDE.md hard rule 2).

### Stage 5 — Contact Discovery
Built 2026-08-30 (`agents/find_contact.py`), triggered on demand from the
Application Detail page ("Find hiring contact" button), not bundled into
the main pipeline run -- it only needs a company name, not the JD, and
shouldn't spend a Hunter credit on every run whether wanted or not.
**Hunter.io only, not Apollo.io**, despite the original plan naming both:
verified directly against both providers' pricing pages before building
anything -- **Apollo's free plan has no API access at all** (gated behind
a "Custom"/enterprise plan; some sources cite $119+/month minimum), while
**Hunter's free plan does** (50 credits/month, no expiration, confirmed
live against a real key). CLAUDE.md hard rule 3 applies regardless of
provider: no LinkedIn scraping, ever.
**In:** company name (from the application's own `company` column).
**Out:** `{contacts: [{name, title, email, confidence, verified, verification_status, decision_maker, sources_count, source}], message, error}`
-- a *ranked list*, not a single pick; a human chooses which one (if any)
is worth recording, same "human decides" pattern as the status dropdown.
Uses Hunter's Domain Search endpoint, which accepts a **plain company
name** directly (`company=Anduril`) -- no separate domain-lookup step.
Each candidate's own `verification.status` from Hunter is already present
in that one response, so no second call to Hunter's separate Email
Verifier endpoint is needed for the initial list.
**Hard rule 3 enforcement, in code:** `verified` is `True` only when
Hunter's own status is `"valid"` -- `"accept_all"` (the domain accepts
mail to *any* address, so a hit there doesn't confirm this specific
person) and `"unknown"` both map to `False`. There is no code path that
can mark a contact verified without Hunter itself having confirmed it.
**Known limitation, not job-specific:** Hunter has no notion of the role
being applied for -- it returns whoever it has found associated with that
company's domain across the public web, which may skew toward people with
more public presence (execs, sales, PR) rather than actual recruiters or
hiring managers. Each candidate's real `title` is shown precisely so a
human can judge relevance themselves; there's no keyword-based re-ranking
by role relevance (deliberately -- a fragile keyword matcher could quietly
misrank things worse than a plain confidence sort).
**No scraping fallback in v1:** CLAUDE.md's original plan named "fetch
company team/press pages directly" as a fallback when Hunter finds
nothing. Deliberately out of scope for now -- every company site is
structured differently, so a generic scraper would be fragile and often
silently wrong. When Hunter finds nothing, `message` says so plainly
instead of guessing from a scrape.

### Stage 6 — Outreach Draft
**In:** contact + jd_parsed + tailored_resume summary
**Out:** `outreach_draft.md`
**Notes:** drafts only. Lands in a review queue.

### Stage 7 — Review Queue (human checkpoint)
Built 2026-08-28 as a full web app (`review/backend/` + `review/frontend/`), not the originally-planned CLI — the user wanted a real trigger-and-review interface, not a read-only list. **In:** `POST /api/jobs {jd_text, company?, role?, tailor_model?, mode?, generate_cover_letter?}` on the FastAPI backend, which runs `apply.py`'s pipeline as a `BackgroundTasks` job (never blocks the request — the pipeline takes up to ~1min across 4-5 sequential Anthropic calls) and reports live per-stage progress via an in-memory job store, polled by the frontend at `GET /api/jobs/{id}`. **Model split (added 2026-08-30):** `tailor_model` only selects the model for the tailoring stage (and the cover letter stage, when requested) — ingest and both scoring calls always run on a fixed fast model regardless, per `apply.py`'s `run_pipeline` docstring; switching to Sonnet used to mean 4 slow calls, this way it's 1. **Cover letter (added 2026-08-30):** `generate_cover_letter` defaults to off (one more paid call, so it's opt-in per run); `GET /api/applications/{id}/file` gained `type=cover_letter_pdf|cover_letter_docx` alongside the existing `pdf|docx`, both deriving from the (only-when-generated) `cover_letter_path` column the same way the resume types already derive from `resume_variant_path`. **Contact discovery (added 2026-08-30):** `POST /api/applications/{id}/find-contact` looks up that application's `company` and calls Stage 5, returning the ranked candidate list without writing anything — `PATCH /api/applications/{id}` (the same endpoint the status dropdown already used) gained optional `contact_name`/`contact_email`/`contact_source`/`contact_verified` fields so the frontend can save whichever candidate a human picks. **Out:** a React app (Vite + TypeScript + Tailwind) with three views — `/new` (paste JD, pick tailoring model/mode, optionally request a cover letter, watch progress, auto-redirects to the result), `/` (applications list), `/applications/:id` (score before/after, hard gaps, red flags, matched skills, diff summary, PDF/docx download links for the resume and, when generated, the cover letter, a "Find hiring contact" flow, status dropdown wired to `PATCH /api/applications/{id}`). Sending is still never automated — this stage only reviews/tracks what `apply.py` already generated. See `LEARNING_LOG.md` sections 4, 6, and 7 for the reasoning behind the async job design and a from-first-principles explanation of the web/React concepts involved.

### Orchestrator — `apply.py`
Not a pipeline stage — the "one layer up" that CLAUDE.md's working style refers to. Agents (`agents/*.py`) stay pure (JSON in, JSON out, no side effects); `apply.py` is what actually chains ingest → score → tailor → render and owns the file/DB persistence those stages don't do themselves. Built 2026-08-28 specifically to close the gap between hard rule 4 ("log the application in `applications.db` immediately after generation") being written down from Phase 0 and actually being implemented — nothing wrote to `applications.db` before this existed. `run_pipeline()` auto-extracts company/role from the parsed JD (`--company`/`--role` override if the JD doesn't state one or extraction is wrong) and calls `log_application()` right after rendering, inserting one `applications` row (status defaults to `'drafted'`) and one `resume_versions` row (`diff_from_master` = the tailoring stage's `diff_summary`, JSON-encoded). `match_score` logged is `score_after` (the tailored resume's score), not `score_before` — the row should reflect what's actually being submitted.

---

## 4. Tech stack

- **Language:** Python (best library support for resume parsing, email APIs, SQLite)
- **State:** SQLite (`applications.db`) — simple, local, queryable
- **Resume source of truth:** YAML
- **Orchestration:** standalone Python scripts in `agents/`, one per pipeline stage, each calling the Anthropic API directly (see CLAUDE.md) — not Claude Code skills
- **Email verification/finding:** Hunter.io or Apollo.io API (free tier is enough at your volume)
- **Sending:** Gmail API, OAuth, draft-then-confirm — never blind SMTP send
- **Rendering:** `python-docx` for `.docx`, `reportlab` for `.pdf` (independent renders, not a docx→pdf conversion — see Stage 3 notes)
- **Review UI:** originally planned as a CLI, built instead as a full web app (2026-08-28) — FastAPI backend (`review/backend/`) + React/Vite/TypeScript/Tailwind frontend (`review/frontend/`), since the user wanted a real trigger-and-review interface, not a read-only list. See Stage 7.

---

## 5. Guardrails (non-negotiable)

1. Tailoring/cover-letter agents may only reorder, filter, or lightly reword existing resume content — never fabricate experience, metrics, or skills.
2. No email is ever sent without landing in the review queue first and getting explicit approval.
3. Contact discovery only uses verified sources (API-verified emails or direct company pages) — no scraping LinkedIn profiles.
4. Every generated resume/cover-letter version is saved and linked to the application row, so nothing is ever silently overwritten.
5. Unverified contacts are visibly flagged as unverified in the review queue, never silently treated as equal to verified ones.
