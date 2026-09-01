# Roadmap

Build in phases that are each independently useful — don't wait for the full pipeline to get value.

## Phase 0 — Foundation (day 1–2)
- [x] Convert your current resume into `data/master_resume.yaml`, tagging every bullet by skill/theme
- [x] Set up `applications.db` schema
- [x] Set up repo structure (see CLAUDE.md below) and git-init it — you want version history on resume changes
- [x] Standing "Upload master resume" onboarding -- built 2026-09-01 (`agents/parse_resume.py`, dashboard's "Resume" page), because the original master resume above only existed from manual work; anyone else (or this user, on a refresh) can now upload a `.pdf`/`.docx` any time, review the parsed draft against a fidelity guardrail (flags any number not present in the original text), hand-edit it, and confirm before it's saved -- a backup of whatever was there before is made automatically first.
- [x] Named resume library + per-application tracking -- extended same day, explicit user request after testing the upload feature with a second real resume and realizing it silently overwrote the first with no way to tell which one produced a past application. `data/master_resumes/<slug>.yaml` (+ `_index.json`) now holds as many resumes as you want side by side; the New Application page picks which one to use; `applications.resume_name` records the human label used, shown on both the Applications list and Application Detail. Deleting a resume from the library (with a backup first) is also supported, blocked only when it's the last one left.
- [x] Permanent regression test suite (`tests/`, run via `python -m pytest tests/`) -- added 2026-09-01, consolidating every ad-hoc verification script written for a guardrail so far into one re-runnable, fully mocked suite (52 tests, zero API cost, under a second). See ARCHITECTURE.md section 6 and LEARNING_LOG.md section 23.
- [x] Auto-create `applications.db` from `schema.sql` on first use -- found 2026-09-01 via a real end-to-end run against a genuine fresh clone (never caught by code review or the mocked test suite, since both implicitly assumed a DB that had existed on this machine since Phase 0): a fresh clone's dashboard home page and the CLI pipeline both crashed with "no such table" because nothing had ever applied the schema. Fixed with `apply.ensure_schema()`, called at dashboard startup and at the top of `run_pipeline()`. See LEARNING_LOG.md section 24.

**Done when:** you have a structured resume file and empty DB, no AI yet. ✅ Done 2026-08-27. Onboarding for a *new* user/resume done 2026-09-01.

## Phase 1 — Score + Tailor (the actual time-saver)
- [x] JD ingest agent (paste text → parsed JSON)
- [x] Scoring agent (parsed JD + master resume → score + gaps)
- [x] Tailoring agent (score + master resume → tailored resume, reorder/reword only)
- [x] Render to docx (+ pdf)
- [x] Manually test closely for hallucinated content — done far more heavily than "5 JDs": iterated repeatedly against the same real JD (Micron) specifically because it kept surfacing new fabrication classes each round (dropped domain detail, dropped named tech, added unsupported claims, appended "demonstrating X" clauses) — each one fixed and re-verified. "Dropped domain detail" (the turfgrass case) got a real code-level fix 2026-09-01 -- a distinctive-phrase-drop check with a targeted retry before reverting, see ARCHITECTURE.md Stage 2. Known remaining gap: the appended-clause guardrail only catches em-dash-style separators, not comma-led ones — see ARCHITECTURE.md Stage 2 notes.
- [x] Honest/Aggressive tailoring modes (both non-fabricating; added 2026-08-28)
- [x] Hard guardrail: tailoring can never score lower than doing nothing (added 2026-08-30, falls back to the untouched master resume rather than ship a worse result)
- [x] Tenure/graduation-date facts computed in code instead of left for the model to guess (added 2026-08-30)
- [x] Per-stage model split: only the tailoring call is user-selectable (Haiku/Sonnet); ingest and scoring are hard-locked to a fast model (added 2026-08-30)

**Done when:** you paste a JD and get a tailored, honest resume + score in under a minute. ✅ Done 2026-08-28 — `apply.py` does this in one command. Hardened well past that bar since — see LEARNING_LOG.md sections 8–11 for the fabrication/scoring bugs found and fixed along the way.

## Phase 2 — Cover letters
- [x] Cover letter agent, same JD input -- built off the tailored resume, not the master resume, so its emphasis matches what got tailored for this JD (`agents/cover_letter.py`)
- [x] Render to docx/pdf (`render_cover_letter_docx`/`_pdf`, same Calibri/one-page infrastructure as the resume)
- [x] Test against Phase 1 outputs on the same JDs -- verified with a real J&J JD: every specific claim in the generated letter traced back word-for-word to real tailored-resume bullets, genuine opening hook (not the banned cliché), one-page PDF/docx both rendered cleanly

**Done when:** tailored resume + cover letter both come out of one JD paste. ✅ Done 2026-08-30 -- opt-in per run (a checkbox/`--cover-letter` flag), not automatic, since it's one more paid API call. Free-form prose has no "known-good original" to revert a bad claim to the way a resume bullet does, so the guardrail design here is new: the model cites which tailored-resume bullet(s) ground each claim, and code verifies every number against the citation, dropping (not rewriting) anything that fails -- see ARCHITECTURE.md Stage 4 and LEARNING_LOG.md for the full design and its one honest limitation (named-skill fabrication isn't hard-blocked, same class of gap as tailor.py's turfgrass case).

## Phase 3 — Tracking loop
- [x] Every generated application writes a row to `applications.db` — `apply.py` logs an `applications` row + `resume_versions` row immediately after rendering, per CLAUDE.md hard rule 4
- [x] List applications and update status (applied/interview/rejected/etc.) — originally scoped as a CLI, built instead as the full `review/` web dashboard (2026-08-28), which does this and more (trigger runs, view diffs/gaps, download files)
- [ ] A few canned queries: response rate by resume variant, by tag emphasis, by company size — deliberately not started yet; only a handful of real applications are logged so far, not enough volume for correlation queries to say anything meaningful

**Done when:** you're logging every real application you send, even ones you tailor by hand.
This phase matters more than it sounds — it's your actual edge over commercial tools.

## Phase 4 — Contact discovery (optional, higher effort/risk)
- [x] Integrate Hunter.io API -- Apollo.io turned out not to be viable: confirmed against their own pricing page that the free plan has no API access at all (gated behind a "Custom"/enterprise plan). Hunter's free plan does (50 credits/month) (`agents/find_contact.py`)
- [ ] Fallback: fetch company "team"/press pages directly -- deliberately skipped for v1; every company site is structured differently, so a generic scraper would be fragile and often silently wrong. Revisit only if "Hunter found nothing" turns out to happen a lot in practice.
- [x] Confidence/verified flag surfaced clearly -- `verified` is only ever `True` when Hunter's own status is `"valid"`, enforced in code; the UI shows a green "Verified" / amber "Unverified" badge per candidate, never blurring the distinction
- [x] Surface recruiters/team-relevant contacts -- added 2026-08-31: Hunter's own `department` field (a fixed 19-value vocabulary) is matched against the application's `role_title` via a small keyword table; recruiters and department-matched contacts are boosted to the top and labeled (e.g. "Recruiting", "Engineering/IT"), nothing filtered out
- [ ] Test on 10 companies, check false-positive rate by hand -- only tested on two real companies (Anduril Industries, Snowflake) so far; worth doing a proper pass across several before trusting this at volume

**Done when:** contact discovery returns verified-or-flagged results you'd trust to send to. ✅ Core flow done 2026-08-30, relevance boost added 2026-08-31 -- a "Find hiring contact" button on the Application Detail page returns a ranked list of real candidates (name, title, email, confidence, department, verified/unverified, and a relevance label for recruiters/team matches), and a human picks which one (if any) to save; nothing is auto-selected or auto-sent. Hunter's results are still company-wide, not scoped to one specific job posting -- the relevance boost narrows that gap via department matching but doesn't eliminate it -- see ARCHITECTURE.md Stage 5.

## Phase 5 — Outreach drafting + review queue
- [x] Outreach draft agent -- built 2026-08-31, draft-only per explicit user choice (`agents/draft_outreach.py`), on-demand "Draft outreach email" button on Application Detail, never sends anything (hard rule 2)
- [x] Review queue -- already covered by the existing web dashboard (Phase 3/6); the new "Outreach draft" section slots into the same Application Detail page, shows subject/body/validation log with a copy-to-clipboard button
- [x] Real send capability -- built 2026-08-31 (`review/backend/gmail_client.py`), SMTP + a Gmail App Password (`.env`: `GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD`), not OAuth2/the Gmail API -- deliberately simpler setup (no Google Cloud project/consent screen), a pattern already proven in another one of the author's own projects. A "Send email" button on the Outreach draft section, gated behind a confirmation modal showing the exact recipient/subject/body (and any validation warnings) before it actually sends -- satisfies hard rule 2's "explicit user confirmation step," never an automatic send from any pipeline stage or agent. Real attachments (added 2026-08-31, explicit user request): the resume PDF, and the cover letter PDF if one exists, are actually attached now -- previously the draft's own text said "attached" while nothing was; a missing attachment file is now a hard send-blocking error, not a silent gap.
- [x] Log outreach sent into `applications.db` -- `outreach_sent_at`/`status='outreach_sent'` are now set automatically by the send endpoint on a real successful send, closing the loop these columns were added for back in Phase 0
- [ ] Log response received -- `response_received` column still exists unused; no UI wired to it yet (would need a manual "mark as responded" action, deliberately not built this pass)
- [x] Two email types + editable draft -- added 2026-08-31 per explicit user feedback: "cold" (original) and "referral" (explicitly asks for a referral, requires a job posting link -- no code path produces a referral draft without one, which is the actual enforcement behind "can't send a referral without a link"). The job link is inserted deterministically in code, never written by the model, after a real test showed the model embedding the raw URL tripped the numeric-fabrication guardrail (a URL's job-id number looks like an unverified metric). Both prompts also stopped saying "tailored resume" to the recipient. The draft is now a real editable text field in the UI, not read-only -- what gets sent is whatever's currently in that field.

**Done when:** you can review and approve a full application + outreach package in under 3 minutes per company, and send it without leaving the dashboard. ✅ Both draft generation and real sending are done as of 2026-08-31 -- response tracking is the one remaining loose end.

## Phase 6 — Polish / stretch (only if you're enjoying it)
- [x] Small web UI instead of CLI for the review queue — done as part of Phase 3, went straight to a full React dashboard (`review/frontend/`) rather than a CLI; redesigned with a real visual identity 2026-08-28
- [ ] Auto-suggest which of your resume "variants" to A/B test next based on response data
- [ ] Weekly summary report (applications sent, response rate, interview rate)

---

## Suggested order of effort
Phases 1–3 alone will already save you the most time and give you the data-driven edge. Phases 4–5 are valuable but carry real risk (email deliverability, verification quality) — build them once 1–3 are solid and you trust the tailoring output completely.

**Current position (2026-08-31):** Phases 1 and 2 are both solid and well past their original bar. Phase 3 is logging/tracking-complete, its analytics item still deliberately waiting on more real usage (a handful of logged applications isn't enough volume for correlation queries to say anything meaningful). Phase 4's core contact-discovery flow, including the department-based relevance boost and named-in-JD targeted lookup, is now built and verified against two real companies (Anduril, Snowflake) -- worth testing against a few more before fully trusting it at volume. **Phase 5 is now fully built end-to-end**, including real sending -- the first feature in this whole project that touches a real, external, hard-to-undo action. Deliberately built with hard rule 2 enforced by construction, not just convention: exactly one code path can send (`gmail_client.py`), called from exactly one endpoint, which only fires on an explicit confirmed click showing the exact final text first. Only remaining loose end anywhere in the roadmap is response tracking (Phase 5's `response_received` column, unused) and Phase 3's analytics item -- both are "wait for more real usage" items, not build blockers.
