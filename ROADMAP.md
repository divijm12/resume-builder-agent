# Roadmap

Build in phases that are each independently useful — don't wait for the full pipeline to get value.

## Phase 0 — Foundation (day 1–2)
- [ ] Convert your current resume into `data/master_resume.yaml`, tagging every bullet by skill/theme
- [ ] Set up `applications.db` schema
- [ ] Set up repo structure (see CLAUDE.md below) and git-init it — you want version history on resume changes

**Done when:** you have a structured resume file and empty DB, no AI yet.

## Phase 1 — Score + Tailor (the actual time-saver)
- [ ] JD ingest agent (paste text → parsed JSON)
- [ ] Scoring agent (parsed JD + master resume → score + gaps)
- [ ] Tailoring agent (score + master resume → tailored resume, reorder/reword only)
- [ ] Render to docx
- [ ] Manually test on 5 real JDs, read every output closely for hallucinated content

**Done when:** you paste a JD and get a tailored, honest resume + score in under a minute.

## Phase 2 — Cover letters
- [ ] Cover letter agent, same JD input
- [ ] Render to docx/pdf
- [ ] Test against Phase 1 outputs on the same 5 JDs

**Done when:** tailored resume + cover letter both come out of one JD paste.

## Phase 3 — Tracking loop
- [ ] Every generated application writes a row to `applications.db`
- [ ] Simple CLI to list applications and update status (applied/interview/rejected/etc.)
- [ ] A few canned queries: response rate by resume variant, by tag emphasis, by company size

**Done when:** you're logging every real application you send, even ones you tailor by hand.
This phase matters more than it sounds — it's your actual edge over commercial tools.

## Phase 4 — Contact discovery (optional, higher effort/risk)
- [ ] Integrate Hunter.io or Apollo.io API
- [ ] Fallback: fetch company "team"/press pages directly
- [ ] Confidence/verified flag surfaced clearly
- [ ] Test on 10 companies, check false-positive rate by hand

**Done when:** contact discovery returns verified-or-flagged results you'd trust to send to.

## Phase 5 — Outreach drafting + review queue
- [ ] Outreach draft agent
- [ ] Review queue (CLI table is fine to start): shows resume diff, cover letter, draft email, contact confidence
- [ ] Gmail API integration for send-after-approval only
- [ ] Log outreach sent/response into `applications.db`

**Done when:** you can review and approve a full application + outreach package in under 3 minutes per company.

## Phase 6 — Polish / stretch (only if you're enjoying it)
- [ ] Small web UI instead of CLI for the review queue
- [ ] Auto-suggest which of your resume "variants" to A/B test next based on response data
- [ ] Weekly summary report (applications sent, response rate, interview rate)

---

## Suggested order of effort
Phases 1–3 alone will already save you the most time and give you the data-driven edge. Phases 4–5 are valuable but carry real risk (email deliverability, verification quality) — build them once 1–3 are solid and you trust the tailoring output completely.
