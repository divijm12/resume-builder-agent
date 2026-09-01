# Learning Log

This file exists to teach, not just document. Every time we build something
in this project, I'll add an entry here explaining *what* we built, *why*
that approach and not another, and — just as important — *what went wrong*
along the way and what that failure taught us. Think of it as the running
commentary track on the whole project, written for someone learning how AI
agents and this kind of tooling actually get built, not just what the final
code looks like.

---

## 1. The core idea: agents are just LLM calls with structure around them

Before anything else: there's no magic in "AI agent." `agents/ingest_jd.py`,
`agents/score.py`, and `agents/tailor.py` are each just one function that
sends a prompt to Claude and gets structured JSON back (via `output_format`
in the SDK — you describe the shape you want with a Pydantic model, and the
API guarantees the response matches it, instead of you having to parse free
text and hope). The "agent" behavior — three stages that each do one job and
hand off to the next — is something *we* designed in Python, not something
the LLM does on its own. This is the single most important thing to
internalize: an LLM call is a function that's really good at language tasks
but has no memory, no state, and no enforcement of its own promises. Every
guarantee in this codebase (never fabricate, always fit one page, always log
to the DB) had to be built by *us*, in code, around the LLM call — not
assumed from a well-written prompt.

## 2. The single biggest lesson of this whole project: prompts don't hold

We spent an enormous amount of this build on one recurring problem: telling
Claude "don't fabricate content" in the prompt worked *most* of the time,
but not *reliably*. Concretely, across many test runs of `tailor.py`:

- It dropped a real detail ("a turfgrass disease outbreak research project")
  down to generic ("a research project") — even though it was explicitly
  told to preserve every fact.
- It dropped named technologies that were genuinely used ("Sarvam AI",
  "Redis", "Claude Code") while rewording a bullet.
- It *added* things that were never there — "using Python" appeared in a
  bullet that never mentioned Python, and "REST API design" got claimed for
  a project with no REST API in its tech stack.
- Worst of all: after we explicitly banned all of the above in the prompt,
  a *different* variant of the same mistake would show up in a later,
  unrelated test run — appending a "— demonstrating X" clause to sneak in
  an unearned claim, sometimes with an em-dash, sometimes with a comma.

**The lesson:** an instruction in a system prompt is a strong nudge, not a
guarantee. LLMs are non-deterministic — the same prompt can produce a clean
result once and a subtly wrong one the next time, especially on a cheap,
fast model like Haiku (which is what we're using everywhere for cost). If a
mistake is *structurally checkable* — did this bullet's text change, does
this exact word still appear, did a number get added that wasn't there
before — **you write code to check it, you don't just ask nicely.** That's
why `tailor.py` has real Python logic (regex term-matching, exact-text
comparison) reverting any bullet that violates a rule, on every single run,
instead of trusting the model's word. Prompting still matters — it's why
the model tries to do the right thing in the first place — but the code is
what makes it *actually true* every time, not just usually true.

The corollary: some mistakes genuinely can't be caught by code (was
"demonstrating strong software design principles" a fair inference or an
overclaim?) — those stay as prompt-level judgment calls, and we accepted
that as a known, permanent limitation rather than chasing a heuristic that
would just create new false positives elsewhere.

## 3. Why a database exists at all (`applications.db`)

It would be easy to think the "product" here is the resume file. It isn't
— `applications.db` is. A resume PDF is disposable; you generate a new one
per job. What's actually valuable, and what no commercial resume tool gives
you, is the *history*: which resume variant you used for which company,
what score it got, what changed, and — once you start tracking outcomes —
which patterns actually get responses. That's a question only a database
can answer over time; a folder of PDFs can't. This is also why we're about
to add a `tailor_result_json` column: storing the *entire* structured
tailoring result (not just the final score) means the review UI can show
you gaps, red flags, and diffs without ever re-deriving them — the data
that would let you answer "am I losing points because of a real skill gap,
or because I keep phrasing things badly" already exists, we just have to
keep it.

## 4. Why we're adding a real backend + frontend now (FastAPI + React)

Up to this point, using the tool meant running `python apply.py --jd-file
...` from the terminal and reading JSON. That's fine for testing, bad for
actually using something day to day. Two concrete technical decisions worth
understanding:

- **Why FastAPI, and why "background tasks" instead of just running the
  pipeline in the request handler:** the pipeline makes four sequential
  calls to the Anthropic API and can take up to a minute. If a web server
  just ran that inline, the browser tab would sit there with no feedback for
  a minute, and if anything hiccups, you'd get a raw timeout with no
  information. Instead, the API endpoint starts the job and *immediately*
  returns a job ID; the actual work happens in the background, and the
  frontend asks "is it done yet?" every couple of seconds (this is called
  *polling* — the simplest way to track something async, at the cost of a
  small delay before you find out something finished). This is a very
  common pattern for anything backed by a slow, external, paid API call.

- **Why not a heavier job queue (Celery/Redis):** those exist to let *many
  workers on possibly different machines* pull jobs off a shared queue.
  We have one user, running one job at a time, on one machine. Reaching for
  that infrastructure here would be solving a scaling problem we don't have
  — the kind of premature complexity worth actively avoiding. A plain
  in-memory Python dictionary tracking `{job_id: status}` does the same job
  at our actual scale, with zero extra moving parts to misconfigure or debug.

## 5. Lesson: version your schema, even for a "personal" SQLite file

We only just noticed that `applications.db`'s table structure had existed
*only* as a one-off terminal command from early in this project — never
saved anywhere as a file. That means if this repo were cloned fresh, or the
local `.db` file were ever deleted, there'd be no record of what tables were
supposed to exist. The `.db` file itself is (correctly) gitignored, since it
holds real personal data — but the *shape* of that data is not personal, and
belongs in git. `data/schema.sql` fixes that: it's the reproducible
definition, checked into version control, that the real database gets built
from. General rule: **the data is private, the structure of the data
usually isn't — track the structure.**

---

## 6. Web APIs from first principles (client, server, endpoints, HTTP)

You asked what all of this actually means, so let's build it up from
scratch using `review/backend/main.py` as the concrete example — every term
below maps to a real line of code we just wrote and tested.

**Client and server.** Two programs talking to each other over a network.
The **server** sits and waits, ready to answer questions — that's
`main.py`, running via `uvicorn` (a program that keeps a Python process
alive and feeds it incoming network requests). The **client** is whatever
initiates a question — for us that was literally `curl` on the command
line simulating what the browser will do later. Neither has to be on a
different physical computer; right now both are running on your laptop,
just as separate processes talking over `localhost` (a special address
that always means "this machine").

**HTTP.** The *protocol* — the agreed-upon format — that clients and
servers use to talk. Every HTTP interaction is one **request** (from
client to server) and one **response** (server back to client). A request
has three important parts: a **method** (what kind of action), a **path**
(which thing), and optionally a **body** (data attached to the request).
When you ran `curl -X POST http://127.0.0.1:8000/api/jobs -d @job_body.json`,
that was one request: method `POST`, path `/api/jobs`, body = the JD text
as JSON.

**Endpoint.** A server doesn't just accept any request — it only responds
to the specific method+path combinations it's been programmed to handle.
Each one is an endpoint. In `main.py`, `@app.post("/api/jobs")` directly
above `def create_job(...)` *is* the declaration of an endpoint: "if a
POST request arrives at the path `/api/jobs`, run this function and send
back whatever it returns." FastAPI's whole job is turning these Python
function decorators into a real, running network listener — you write
normal Python functions and FastAPI handles all the HTTP plumbing.

**The methods we used, and why each one:**
- `GET` — "give me data, don't change anything." `GET /api/applications`
  (list all), `GET /api/jobs/{job_id}` (check status). Safe to call
  repeatedly — that's exactly what polling relies on.
- `POST` — "create a new thing." `POST /api/jobs` creates a new pipeline
  run and hands back a `job_id` for it.
- `PATCH` — "update *part* of an existing thing." `PATCH
  /api/applications/1` with `{"status": "applied"}` changed only the
  status column, leaving everything else on that row untouched.
This GET/POST/PATCH convention is called **REST** — it's not enforced by
any tool, it's just a widely-shared naming convention so that anyone
reading your API's endpoint list can guess what each one does.

**Request/response bodies are JSON.** JSON (`{"status": "applied"}`) is
just a text format for structured data — the same shape Python dicts have,
which is why converting between them (`json.dumps`/`json.loads`, or in
FastAPI's case, automatically via Pydantic models like
`CreateJobRequest`) is trivial. This is also why the *entire* tailoring
result could be stuffed into one `tailor_result_json` database column
back in section 3/5 — JSON doesn't care how deeply nested or complex the
data is, it just needs to round-trip through text.

**Status codes.** A 3-digit number at the very front of every response,
summarizing the outcome before you even look at the body. We saw three:
`200` (default "it worked"), `404` ("the thing you asked for doesn't
exist" — we return this explicitly via `raise HTTPException(404, ...)`
when a job_id or application id isn't found), and `400` ("your request
itself was invalid" — we saw this exact case when PATCHing an invalid
status string; the database's own `CHECK` constraint rejected it, and we
turned that into a proper 400 instead of letting the server crash).

**Why the pipeline can't just run inside the request handler.** A request
handler function is expected to return quickly — the client is sitting
there waiting the whole time. Our pipeline takes up to a minute (4
sequential paid API calls). If `create_job()` just called
`apply.run_pipeline()` directly and waited, the browser tab would hang
with zero feedback, and any reasonable timeout would kill the connection
before it finished. FastAPI's `BackgroundTasks` (`background_tasks.add_task(_run_job, ...)`
in `create_job()`) is the fix: the endpoint schedules `_run_job` to run
*after* it has already sent its response, so the client gets `{"job_id":
"..."}` back in milliseconds while the real work continues unattended.

**Polling, concretely.** Since the client already got its instant
response and moved on, how does it find out when the slow work actually
finishes? It asks again. And again. `GET /api/jobs/{job_id}` just reads
the current value out of the in-memory `JOBS` dict, which `_run_job`
updates as it goes (`report("scoring")`, `report("tailoring")`, etc. —
this is the `progress_callback` we wired into `apply.run_pipeline()` in
section 4/checkpoint 1). The literal bash `for` loop with `sleep 5` I ran
to test this *is* polling — the React frontend will do the same thing on
a faster interval, just with a `setInterval` instead of a shell loop, and
render the result instead of printing it.

**CORS**, one more term you'll see in the code (`CORSMiddleware`): a
security rule built into every browser that blocks a webpage loaded from
one address (e.g. `http://localhost:5173`, where the React dev server
will run) from making requests to a *different* address (`http://localhost:8000`,
our backend) — unless the server explicitly says "requests from that
address are allowed." That's all `app.add_middleware(CORSMiddleware,
allow_origins=["http://localhost:5173", ...])` does. This only matters
for browser JavaScript; it's why `curl` never had this problem testing
the backend directly — the CORS check is enforced by browsers, not
servers, but the server has to opt in on the browser's behalf.

**Backend vs. frontend**, tying it together: the **backend** (`main.py`,
this checkpoint) owns the logic, the database, and the only code allowed
to talk to the Anthropic API or the filesystem. The **frontend** (React,
next checkpoint) is a webpage that owns nothing but presentation — it
calls the backend's endpoints to do anything real, and just renders
whatever JSON comes back. This separation is why we could fully test and
verify the backend with nothing but `curl` — the frontend is purely a
prettier client than the one we've been using.

---

## 7. React, from first principles (components, state, props, routing)

The backend was the logic; the frontend (`review/frontend/`) is purely
about *showing* that logic to a human and reacting to clicks. A few core
ideas, each grounded in a real file we just wrote:

**A component is a function that returns UI.** `NewApplication`,
`ApplicationsList`, `ApplicationDetail` — each is just a normal
TypeScript function that returns a description of what should appear on
screen, written in a syntax called **JSX** that looks like HTML mixed
into JavaScript (`<h1>Applications</h1>` inside a `.tsx` file). React's
job is turning that description into actual DOM elements in the browser,
and — critically — *re-running* the function and updating only what
changed whenever the data it depends on changes. You never manually
write `document.getElementById(...).innerText = ...` anywhere in this
codebase; you just describe what the UI should look like for the current
data, and React keeps the screen in sync.

**State is a component's own memory.** `useState` (e.g. `const [jdText,
setJdText] = useState("")` in `NewApplication.tsx`) gives a component a
piece of data it owns and can change. Calling `setJdText(newValue)` does
two things: updates the stored value, *and* tells React "re-run this
component's function, something changed." That's the entire mechanism
by which typing in the textarea makes the textarea show what you typed —
every keystroke calls `setJdText`, which triggers a re-render with the
new value.

**Props are how a parent hands data down to a child.** `Pills({items,
tone})` in `ApplicationDetail.tsx` is a small component that takes data
from its caller (`<Pills items={tr.unaddressed_hard_gaps} tone="red" />`)
and renders it — it has no idea where `items` came from, it just displays
whatever it's given. This is how the same `Pills` component renders hard
gaps in red and matched skills in green elsewhere on the same page — one
reusable piece of UI, configured differently by whoever uses it.

**`useEffect` is for "do this side effect when X happens," not for
rendering.** Fetching data from our backend is a side effect (it reaches
outside the component, over the network) — you can't just call `fetch()`
directly inside the component function, because that function re-runs on
every render and would refire the request constantly. `useEffect(() => {
listApplications().then(setApplications) }, [])` says "run this once,
right after the first render" (the empty `[]` is the key — it means "no
inputs to watch, so only run once"). Our polling hook
(`useJobPolling.ts`) is the same idea with a twist: its effect sets up a
`setInterval` that keeps firing every 1.5s until the job is done, and
`useEffect`'s cleanup function (the part returned at the end) is what
stops that interval when the component using it goes away — otherwise
you'd leak a timer that keeps trying to update a page that no longer
exists.

**Routing is just "which component do I show for this URL."**
`react-router-dom`'s `<Routes>` in `main.tsx` maps URL paths to
components: `/` → `ApplicationsList`, `/new` → `NewApplication`,
`/applications/:id` → `ApplicationDetail` (the `:id` part is a
placeholder — `useParams()` inside that component reads back whatever
was actually in the URL, e.g. `1` from `/applications/1`). Clicking a
`<Link to="/new">` doesn't reload the page from the server the way a
normal `<a href>` would — it just swaps which component is rendered,
instantly, which is why the whole app feels instant to navigate despite
being "just" a webpage.

**Why TypeScript on top of this:** every function above has typed
inputs/outputs (`api.ts` defines `interface ApplicationDetail`, etc.), so
if the backend's JSON shape and the frontend's expectations ever drift
apart, you get a compiler error pointing at the exact mismatch instead of
a blank page and a silent `undefined` at runtime. We ran `npx tsc
--noEmit` before ever starting a dev server specifically to catch that
class of bug for free, before spending a single API call testing it live.

---

## 8. Honest vs. Aggressive tailoring modes -- and a lesson in checking a premise

This one's worth writing down because of *how* it got resolved, not just
what got built. The ask was for an "aggressive" mode that could invent
numbers and technologies to inflate the match score, justified by "I've
seen other tools offer this — if they can, why can't you." That's worth
pausing on: a feature request justified by a competitor's behavior is only
as good as whether the competitor actually behaves that way. So before
building anything, the competitor (Tsenta, a real YC-backed company in
this exact space) got looked up directly — their own AI disclosure page
says applications use "only true facts from the résumé you uploaded," and
their client-side copy for "Aggressive" mode literally says "Rewrites and
tailors the content to match each job description" — nothing about
inventing facts. The premise didn't hold up. **Always check whether the
example you're being pointed to actually does what it's claimed to do,
especially before using it to justify skipping a safety constraint** — the
research took two web searches and settled the entire question.

What got built instead mirrors what Tsenta actually does: two modes, same
no-fabrication guarantee, differing only in *how much* rewording happens.
"Honest" only selects, reorders, and relabels skills — bullet text is
never touched. "Aggressive" (the previous default, unchanged) additionally
rewords bullet text, still bound by every guardrail already in this file.

The implementation choice here is the same lesson from section 2, applied
again: Honest mode's "bullet text never changes" guarantee is enforced in
*code*, not prompted. `validate_and_build(..., mode="honest")` sets
`new_text = original` unconditionally before any of the guardrail checks
even run — so there's no way for a model that ignores its instructions to
leak a reworded bullet through in Honest mode, because the code never even
looks at what the model returned for that field. Contrast that with skill
*relabeling* (`display_as`), which stays prompt-governed in both modes,
same as before — a one-word/phrase substitution anchored to a real skill
is low enough risk that prompting is an acceptable line of defense there,
the same tradeoff this project has made consistently: code-enforce what's
structurally checkable and high-risk, prompt-govern what's genuinely a
judgment call.

---

## 9. Redesigning the UI: pick a direction before writing a line of app code

The frontend worked but had zero visual identity — plain white/slate
Tailwind defaults everywhere. The temptation when asked to "make it
creative" is to just start changing colors in the React components. Instead
we did something worth understanding as a general workflow: **mock up the
actual visual direction somewhere cheap and disposable before touching the
real app.**

Concretely, three full visual treatments of the same screen ("New
Application") were built as static HTML files — dark terminal/CI aesthetic,
warm paper/editorial aesthetic, and a dark analytics-dashboard aesthetic —
and put on one shared canvas as a Claude Design artifact, a separate
published page, not committed to the repo. That let you compare three real,
fully-styled options side by side and just point at the one you wanted
("C"), instead of me guessing at a palette and you finding out you disliked
it only after it was wired into working React components. The general
principle: **when a decision is genuinely subjective and hard to evaluate
from a text description (an aesthetic, a layout, a wording choice with
several good options), produce the actual candidates cheaply and let the
comparison decide it — don't debate it in the abstract.**

Once "C" (dark, `Space Grotesk` + `IBM Plex Mono`, cyan/magenta accents,
mission-control-style gauges and stat tiles) was chosen, only *then* did we
touch `review/frontend/`. A few concrete techniques worth knowing from that
implementation pass:

- **Design tokens as CSS custom properties.** `index.css` now defines
  `--bg`, `--panel`, `--text`, `--cyan`, etc. once at the top (`:root { ... }`)
  instead of the same hex codes being retyped in every component. This is
  the same idea as `master_resume.yaml` being one source of truth instead of
  scattering resume facts across files — one place to change a color, every
  usage follows.
- **An SVG ring as a progress gauge, from math you can actually follow.**
  The "Avg Match" gauge (`AvgMatchGauge` in `NewApplication.tsx`) isn't an
  image or a chart library — it's one `<circle>` drawn with
  `stroke-dasharray` set to its own circumference (`2 * Math.PI * r`) and
  `stroke-dashoffset` set to `circumference * (1 - pct/100)`. A circle's
  outline is just a line that happens to loop back on itself;
  `stroke-dasharray` chops that line into a dash-gap pattern, and setting
  the dash length equal to the whole circumference with a gap of zero, then
  *offsetting* where that dash starts, is what makes only part of the ring
  appear "filled." No new dependency needed for what looks like a
  data-viz widget.
- **Don't fabricate data to fill a mockup-inspired layout.** The original
  design sketch showed a gauge for "the current job's match score" sitting
  next to the JD textarea — but on the real New Application page, no score
  exists yet until the pipeline actually runs the scoring stage. Rather than
  hardcode a fake percentage to match the mockup's look, that tile was
  repurposed to show your *real* portfolio-wide average match score (pulled
  live from `listApplications()`). Same visual language, honest data — the
  same "never fabricate" principle from section 2, just showing up in UI
  design instead of resume content this time.
- **Verifying a UI change without spending API credits.** To see the
  Applications list and the Application Detail page actually populated
  (not just their empty states), a synthetic row was inserted directly into
  `applications.db` with `sqlite3` — no pipeline run, no Anthropic API call
  — then deleted again after the screenshot. Same zero-cost-first instinct
  as the mocked Python tests used earlier in this project: verify with fake
  data before ever reaching for a real, paid run.

---

## 10. A real production bug, and the same lesson showing up a third time

You ran a real job through the dashboard and flagged something that
"didn't make sense": `diff_summary` said a GeoVerify bullet was reworded
from "TensorFlow liveness detection" to something generic. Worth walking
through what was actually going on, because the real bug wasn't where it
looked.

**What had actually happened, verified by reading the real DB row:** your
guardrail worked. `validation_log` showed the TensorFlow rewording attempt
was caught and reverted — the resume you downloaded still said "TensorFlow
liveness detection," word for word. The *real* bug was that `diff_summary`
(the text you read) is written by the model as part of the same response
that proposes the edit, *before* the guardrail code runs on it. So it was
describing an attempt, not an outcome — two of its three "changes" never
survived contact with `validate_and_build`, and the summary never found
out.

**First fix:** stop letting the model narrate specific bullet-wording
changes in `diff_summary` at all. That kind of claim is exactly the thing
this file can verify in code (did the text change, did it pass every
guardrail) — so it's generated from `reworded_by_parent`, a dict built only
from bullets that actually survived, never from the model's own words.
Also closed a related regression: the internal ids (`b_003`, `p_008`) were
leaking into that same field again, so those got barred too, with a code
backstop stripping/dropping any line one still slips into.

**Then it happened again, in a different shape.** Testing that fix against
the same real job description, the model obeyed the letter of the new
rule — no ids anywhere — while still violating the actual point: `"reworded
the GeoVerify bullet to emphasize data validation..."` names no id, but
it's still a specific claim about a bullet's wording, and that exact bullet
had just been reverted by the same guardrail. This is the *exact* pattern
from section 2, just showing up a level deeper: telling a model "don't do
X" gets you "doesn't do X in the way I described," not "doesn't do X." So
the fix couldn't be a better sentence in the prompt — it had to be another
code check: any `diff_summary` line that both names a project with a
reverted reword *and* uses a reword-claiming verb ("reworded"/"rewrote")
gets dropped, while lines that mention the same project for a legitimate
reason (selection, ordering) survive, because they don't carry that verb.

**Why this is worth internalizing, not just noting:** the fix for "the
model claims something false" is never "ask it more precisely not to." The
fix is "make the false claim impossible to say, or make code check every
claim against ground truth before showing it to anyone." Two layered
backstops on the same field, both derived from real production failures,
both verified with a synthetic test *before* spending an API call to
confirm — that's the same zero-cost-first discipline as every other fix in
this project, just applied to a bug in the narration layer instead of the
resume content itself.

---

## 11. Three more real fixes in one session: dates, a hard score floor, and a truncation bug

**Why score.py didn't know how long you'd worked somewhere.** A real run's
red_flags claimed "only 6 months current role experience" for a role that
actually started 2024-05 — over two years earlier. The cause: `score.py`
handed the model raw `start`/`end` dates and asked it to reason about
"present," but an LLM has no built-in, reliable notion of today's actual
date — it tends to reason as if "now" is near its training data's
timeframe. The fix wasn't a better-worded prompt (this project's prompts
have never held reliably for anything checkable); it was computing the
duration in Python (`_tenure_str`) and handing the model the finished
answer, the same move as `tailor.py`'s `_date_rank` for chronological
sorting. Same idea, taken further: since your resume's education entry had
no graduation date at all, there was no way for the model to judge whether
"entry-level, 0–2 years" made sense against your actual timeline — adding
the real graduation date (2025-05) and computing, in code, how much of
each job's tenure fell before vs. after it (pre-grad reads as internship/
part-time work, post-grad as real professional tenure) gave the scorer an
honestly calibrated basis instead of a guess.

**A hard floor: tailoring can never make your score worse.** You asked for
a non-negotiable guarantee — if the tailored resume would score lower than
your resume as-is, don't ship it, fall back to the original. The
interesting engineering question wasn't "add an if-statement," it was how
to make the fallback a genuine *guarantee* rather than "probably fine."
The key move: when the guardrail fires, `score_after` is set to the exact
same object as `score_before` — never re-scored — because re-scoring is
itself another LLM call, and even identical content can come back with a
slightly different number the second time. A guarantee can't be built on
top of something non-deterministic; it has to be built on "this is
literally the content that number was already measured against." Verified
with mocked API calls (both "guardrail should fire" and "guardrail should
stay out of the way" cases) before ever spending a real request on it —
and then it fired for real on a genuinely mismatched JD (a J&J embedded-
systems role against a resume with no C++ or embedded Linux at all):
proposed tailoring scored 47 vs. the original 50, got discarded, you got
your honest resume back unchanged.

**A plain infrastructure bug, for contrast.** Running the pipeline with
Sonnet for the first time failed outright: "Invalid JSON: EOF while
parsing a string." Not a model-reasoning problem — `tailor.py`'s API call
was capped at `max_tokens=8000`, sized around Haiku's typically terser
output, and Sonnet's more elaborate response got cut off mid-sentence
before the JSON could close. Worth noting only because it's a different
*kind* of bug than everything else in this log: not "the model said
something untrue," just "the response didn't fit in the box we gave it."
Raising the cap (16000) fixed it outright — no guardrail, no code
verification needed, because there was nothing to verify: a truncated
response either parses or it doesn't.

---

## 12. Cover letters: a guardrail for content with no "original" to fall back to

Every guardrail up to this point leaned on one convenient fact: a resume
bullet has a known-good original sitting right there in `master_resume.yaml`.
If a reworded version drops a number or a named technology, the fix is
mechanical — throw the bad version away, use the real one instead. That
trick stops working the moment the content isn't a bullet anymore. A cover
letter is free-form prose, generated from scratch, with no prior "true"
version anywhere to revert to. So the interesting design question in
`agents/cover_letter.py` wasn't "how do we catch a bad claim" — it was
"once we catch one, what do we even replace it with?"

The answer: don't try to fix the sentence, cite it instead. The model's
structured output isn't just a string of letter text — it's a list of
`{text, source_bullet_ids}` claims, where `source_bullet_ids` names which
real resume bullets that specific sentence is grounded in. Code then does
something it's done since section 2: reuse `_numeric_tokens()` and check
that any number in the claim actually appears in the bullet(s) it cited.
If it doesn't — or if the claim cites nothing at all but states a number
anyway — the whole claim is dropped from the final letter. Not reworded,
not softened: removed, because there's no safe rewritten version to fall
back to the way there is for a bullet. This is the same philosophy as
every prior guardrail (verify in code, don't trust the model's word) aimed
at a genuinely different failure shape (nothing to substitute in when
verification fails).

One thing this design deliberately does *not* solve, and says so in its
own docstring: a model could still invent a plausible-sounding skill or
technology that was never mentioned anywhere in the real resume. Numbers
are closed-form — either the digits match a citation or they don't. Skill
names aren't — code can confirm a mentioned skill *is* real (it's in the
master resume's vocabulary), but can't prove a negative over the space of
every technology someone might claim to know. This is the same category of
gap as the turfgrass case from section 2: some fabrication risks are
structurally checkable, some aren't, and pretending otherwise would just
be a worse kind of dishonesty than admitting the limitation plainly.
What actually keeps this safe in practice is upstream of the code: this
produces a *draft*, and nothing in this entire pipeline sends anything
without a human reading it first (hard rule 2, unchanged since Phase 0).

A second thing worth naming: the prompt explicitly asked for something
code can't verify at all — a letter that sounds like a person wrote it,
opens with a real hook instead of "I am writing to express interest in
the [Role] position," and would actually make a recruiter want to keep
reading. That's a taste requirement, not a fact-checking one, and it
turned out to matter just as much as the guardrail — a citation-verified
letter that reads like a form would have technically passed every check
and still been worse than useless. Tested against a real J&J JD: the
generated opener was "When I trace through a system failure, I don't stop
at the surface symptom — I instrument, measure, and validate my way to
root cause," and every specific claim in the letter traced back, word for
word, to a real bullet in that run's tailored resume. Both things were
true at once — grounded and human — because the citation requirement was
designed as bookkeeping alongside the sentence, never as a constraint on
how the sentence itself could be written.

---

## 13. Contact discovery: checking a premise before writing a line of code

CLAUDE.md had said "Hunter.io or Apollo.io" since Phase 0, as if they were
interchangeable options. Before writing `agents/find_contact.py`, both
providers' actual pricing pages got checked directly instead of trusting
that old assumption — and it turned out to be wrong. Apollo's free plan
has *no API access at all*; it's gated behind a "Custom" enterprise plan
you'd have to talk to a salesperson to even price. Hunter's free plan
does include real API access — 50 credits a month, confirmed by calling
its account-info endpoint with a real key before writing anything else.
This is the same discipline as the Tsenta research back in section 8:
a plan written down early in a project is a snapshot of what seemed true
*then*, not a guarantee. The five minutes it took to check saved a much
worse five minutes of building against a provider that wasn't usable.

**Why nothing here gets auto-selected.** Hunter's Domain Search doesn't
know what job you're applying for — it returns real people it's found
associated with a company's domain, with their real titles, and nothing
more. It might hand back a VP of Sales as confidently as an actual
recruiter. So the design never picks one automatically: `find_contacts()`
returns a full ranked list, the UI shows every candidate's title so you
can judge relevance yourself, and only `PATCH /api/applications/{id}`
(a deliberate button click) ever writes one onto an application. This is
the same "human decides" shape as the status dropdown, applied to a new
kind of data — the tool surfaces information, it doesn't make the call.

**The one thing that *is* enforced in code, not left to a badge to get
right:** Hunter's own response already grades each email's deliverability
as `valid`, `accept_all`, or `unknown`. It would have been easy to treat
"Hunter found this email" as good enough and label everything found as
verified. Instead, `verified` is `True` only for `valid` — `accept_all`
(the mail server accepts anything sent to that domain, so a hit there
doesn't actually confirm this one address belongs to this one person) and
`unknown` both come back `False`. CLAUDE.md's hard rule 3 says "flag
unverified contacts clearly, don't silently treat them as equal to
verified ones" — that's not a UI copywriting concern, it's a data
mapping that the code enforces before the badge ever gets a chance to lie.

---

## 14. Surfacing relevance without hiding anything

After using contact discovery for real, a reasonable question came up:
could it surface recruiters or people on the actual hiring team, instead
of just whoever Hunter happens to have on file for a company? The first
instinct — write a keyword matcher that guesses relevance from a person's
free-text job title — was already considered and rejected back in
section 13, because a fragile string-matcher on arbitrary titles ("Head
of Factory Systems"? "Director — Simulation"?) can quietly misrank things
worse than doing nothing at all.

But the situation had actually changed: Hunter's own response turned out
to already include a `department` field — not a guess extracted from free
text, but a value Hunter itself assigns from a fixed, documented list of
19 buckets (`it`, `hr`, `product`, `sales`, and so on). That's real
structured data, not a fragile heuristic, so the earlier rejection didn't
apply anymore. This is the same lesson as section 13's Apollo/Hunter
premise-check, pointed at code instead of a provider choice: re-examine a
past "no" when the facts underneath it have actually changed, rather than
either reflexively repeating the old decision or reflexively reversing it
without checking why it was made.

What got built instead is a small, bounded keyword table — the job title
on *this* application (e.g. "Backend Software Engineer") maps onto
Hunter's *own* 19-value vocabulary (roughly: engineer/developer/backend
-> `it`, product manager -> `product`, and so on), never onto arbitrary
open-ended text. Contacts tagged `hr` (recruiters) or matching that
inferred department get a label and sort to the top. Everyone else keeps
their raw `department` and no label, but stays in the list. Nothing is
filtered out — a design choice confirmed explicitly rather than assumed,
because a hard filter risks making a company's contact list look emptier
than it really is whenever Hunter's data happens not to tag anyone in the
matching department. Boosting can only ever help; filtering can silently
hide the one contact worth reaching out to.

Verified live against Anduril Industries with role title "Backend
Software Engineer": the two contacts Hunter had tagged `it` (a "Head of
Factory Systems" and a "Chief Engineer" — titles a keyword-on-title
matcher would likely have missed or mismatched) came back labeled
"Engineering/IT" and sorted above eight other real, verified contacts in
sales, product, operations, and management — all still visible, just
lower in the list.

---

## 15. The cheapest feature is the one that reuses a call you're already making

After the relevance-boost work, the natural next question was: can we find
the actual hiring manager, not just a best-guess department match? The
honest answer is no data provider has that as a queryable field — Hunter,
Apollo, ZoomInfo, none of them know which specific person owns a specific
open req at a specific company. That mapping lives inside the company's
own ATS and isn't public.

But there's a cheap, free-standing exception: sometimes the JD *itself*
names the hiring manager or team directly in its own text ("you'll report
to Jane Doe, our VP of Engineering", "join our Data Platform team"). That
information doesn't need a new API call to extract — `ingest_jd.py`
already sends the full JD text to Claude once, for the existing structured
parse. Three more optional fields (`hiring_manager_name`,
`hiring_manager_title`, `team_name`) just ride along in that same request
and same response schema. No new pipeline stage, no new cost, no new
guardrail category — the same "only extract what's explicitly stated,
leave it null otherwise" discipline already governing every other field
on `JDParsed` covers these too.

Worth remembering as a pattern: before reaching for a new tool or a new
API call to answer a question, check whether an existing call already has
access to the raw material and just isn't being asked the extra question
yet. Verified against a synthetic JD that named both a manager and a team
(both extracted correctly) and the real Snowflake JD, which turned out to
be a good test by accident — it doesn't name a manager (correctly `null`)
but *does* name a specific team ("the Data Platform team," right there in
its own "About the team" section), which came back extracted correctly
too. That's a stronger check than a clean null would have been: it shows
the model is actually reading for a real, specific mention, not just
defaulting to empty.

**Immediate follow-up, same day:** extracting the name is only half the
job — it should actually be used. The requirement, stated plainly: if the
JD names someone, go find that specific person *in addition to* the
regular candidate list, never *instead of* it. Hunter has a second
endpoint for exactly this, Email Finder (`name` + `company` in, one
person's likely email out), and its own docs state a miss costs no
credit — worth checking directly rather than assuming, same discipline as
every other provider-behavior claim in this project. That guarantee is
what makes it safe to *always* attempt this lookup whenever a name is
available, with no cost risk on a miss.

The merge logic is the actual design point, not the extra API call: a hit
gets deduped against the existing list by email (so a person Domain
Search already found doesn't show up twice) and re-labeled "Named in JD"
with the highest boost of any signal so far; a miss changes nothing.
Tested four cases with mocked data before spending anything real — found
+ already-present (dedup), found + new person (added, list still has
everyone else), not found (list unaffected), and no name given at all
(identical to before this feature existed) — then verified live against
Anduril Industries with a real name from an earlier test ("Camrin Opp"):
came back deduped, relabeled, and sorted first, with the other 9 real
contacts, including the previous top department match, still fully
present underneath. The rule "boost, never filter or replace" from the
department-boost feature carried over unchanged to a stronger signal —
consistent design across two feature passes, not something reinvented
each time.

---

## 16. Reuse the guardrail, not just the shape; and a prompt "target" isn't a guarantee

Phase 5's outreach draft agent (`agents/draft_outreach.py`) is the third
agent in this project shaped like "model proposes claims with citations,
code verifies every number against the citation, drops what fails." The
first two times (tailoring, then the cover letter), that guardrail got
written fresh each time, adapted to the new context. This time it didn't
need to be rewritten at all -- `draft_outreach.py` just imports
`CoverLetterClaim` and `validate_and_build` directly from
`cover_letter.py` and calls them as-is, renaming one output key locally.
Same principle as section 15 (reuse what already exists before building
something new), one level more specific: when the *shape* of a problem
repeats, check whether the *code* that already solved it can be called
directly, not just copied and adapted. A future divergence (say, outreach
needing a length cap a cover letter doesn't) is still an easy, deliberate
fork later -- it just isn't the default.

The more interesting lesson came from the very first real output. The
prompt asked for "3-6 sentences," and the model wrote something
grammatically fine, fully fact-checked, zero fabrication -- and about 700
characters, reading like a compressed cover letter, because it chained
three separate accomplishments into one long sentence with "and this,
and that, and also this." The user's own reaction, watching the real
output: "keep it less than 500 chars." That's a much more concrete
target than "short," and it exposed exactly what "short" had failed to
constrain: sentence count says nothing about how much gets crammed into
each sentence.

Two things followed from that, and they're different in kind. The prompt
got more specific and mechanical ("at most one comma in the hook
sentence," "pick one accomplishment and stop," an explicit character
budget) -- that's the same "vague instructions don't hold, specific ones
do better" lesson this project has hit before. But the length target
itself only got a *soft*, logged enforcement in code, not a hard
truncate, and that was a deliberate choice, not a shortcut: this project
has a hard rule for fabrication (revert/drop, no exceptions) because a
fabricated fact is unambiguously wrong. A draft running 550 characters
instead of 500 is not wrong, it's just longer than ideal -- and a
truncate can't tell the difference between "trailing filler" and "the
middle of a fact-checked sentence" or "the sign-off." Cutting blind text
to hit a number would trade a real problem (occasionally long) for a
worse one (occasionally broken). So `generate_outreach_draft` appends a
validation_log note when the body runs over budget and leaves the text
alone -- the same "guardrails enforce correctness in code, style stays
prompt-governed with honest limits" split this project has kept
consistently, just applied to a length target instead of a factual one.
Verified against real data (id 9, Snowflake, read-only) across three
prompt iterations: 700+ characters with three chained accomplishments,
down to 575 with one accomplishment but still a bit dense, down to 454
with the tightened "one comma, one thing" instruction -- and zero
fabrication or em dashes at any point, confirming the fabrication
guardrail and the length tuning are genuinely independent concerns that
didn't trade off against each other.

**Same-day follow-up:** the length fix didn't fix formatting -- a real
draft could be a correct 450 characters and still read as one unbroken
block, greeting and sign-off run together with the body, because nothing
in the schema or prompt told the model to put them on separate lines.
The fix split into two different kinds of guarantee, on purpose. The
greeting-on-its-own-paragraph rule stays prompt-governed (soft-checked,
logged if violated) because there's no cheap way to force a paragraph
break in the *right* place without risking a worse split than the model
already tried. The sign-off is different: "Warm regards, then the
candidate's real name, then their real email, each on its own line" has
no ambiguity and no judgment call in it at all -- it's the same
name/email on every single draft, sourced straight from
`tailored_resume["basics"]`. So it stopped being something the model
writes and became something code constructs after validation, the same
move this project made for tenure/graduation dates in `score.py` months
earlier (section 11): when a piece of output is fully mechanical, stop
asking a language model to reproduce it faithfully every time and just
compute it. One trap caught before shipping: the sign-off construction
originally ran unconditionally, which meant an all-claims-dropped empty
body would still get "Warm regards, Name, email" appended to it --
turning a correctly-empty draft (the 422 guard's whole reason to exist)
into one that looked finished but said nothing. Caught by re-running the
existing mocked test suite after the change, not by a new test written
to look for it specifically -- a reminder that rerunning old tests after
a change earns its keep even when the change looks unrelated to what
they cover.

**Same-day follow-up, a different axis entirely:** the user asked a
sharp question after the formatting fix -- is the outreach draft always
grounded in the JD and the resume? The honest answer split the guardrail
into two things that sound similar but aren't. "Grounded in the resume"
was already solved: every number cites a real bullet, checked in code.
But "relevant to the JD" was never checked at all -- the model picks one
accomplishment to highlight, and nothing verified that accomplishment
actually matched what this specific posting asked for. A true, real,
resume-grounded claim can still be the wrong thing to lead with for this
job.

The fix is a second, independent, code-computed check: tokenize the JD's
own stated skills/keywords/responsibilities, tokenize the model's chosen
claim (and its cited bullet's text, in case the model paraphrased away
the literal term), and flag it if there's zero overlap. Same "soft flag,
not a hard drop" choice as the length check, for the same reason: a
keyword check can't see a real synonym ("Kafka" vs "streaming systems"),
so treating a miss as *proof* of irrelevance would be its own kind of
false claim.

Writing the mocked tests for this caught a real bug before it ever ran
against paid API calls: the tokenizer's regex was written to preserve
punctuation inside compound tech terms ("node.js", "c++"), but it also
silently absorbed a sentence's trailing period into the last word --
"Kafka." tokenized as one unit, which never equals "Kafka" from the JD
side. That would have made the relevance check fire a false "not
relevant" warning on nearly every real sentence, since almost every
sentence ends in a period. It only surfaced because the test asserted
the *positive* case too (a genuinely relevant claim should NOT be
flagged), not just the negative case (an irrelevant one should be) --
a reminder that a guardrail test suite needs to prove the check stays
quiet when it should, not only that it fires when it should.

---

## 17. Two ways to send an email, and why "it works" isn't the deciding factor

The last piece of Phase 5 was a real send button — the first thing this
project ever built that performs an action with a real-world side effect
outside the tool itself. Before writing any code, it was worth stating
plainly why this feels different from everything before it: a fabricated
resume bullet is invisible until someone reads a docx; a bad outreach
send has already gone to a real recruiter the moment "send" returns 200.
There's no revert.

There are two genuinely different ways to let code send email as you,
and this project ended up trying both in sequence, which is a good side
by side comparison to keep:

**OAuth2 + the Gmail API** (built first, then replaced). Requires a
Google Cloud project, enabling the Gmail API, an OAuth consent screen,
a Desktop OAuth client, and a one-time browser-based consent flow that
produces a token. The upside is real and specific: the token can be
scoped to `gmail.send` only, meaning even if it leaked, the most it
could ever do is send mail as you — it cannot read, search, or delete
anything in the inbox. This is Google's own recommended pattern for a
third-party app acting on someone else's mailbox, and it's the more
"correct" choice on paper.

**SMTP + a Gmail App Password** (what shipped). A 16-character password
generated once at myaccount.google.com/apppasswords (requires 2-Step
Verification), dropped into `.env`. No Google Cloud project, no consent
screen, no browser flow — just `smtplib.SMTP("smtp.gmail.com", 587)`,
`login()`, `send_message()`. The tradeoff is real too: an App Password
is account-level, not send-scoped — anyone holding it could technically
also read mail over IMAP with the same credential. It's a blunter tool.

The switch happened because of a fact that mattered more than the
security tradeoff on paper: this exact pattern already existed and
already worked, in a different project (Teleworld Mobile Tracker's
`GMAIL_APP_PASSWORD`, used for real price-alert emails for weeks). A
known-working, already-battle-tested setup that takes one step beats an
unproven "more correct" setup that takes five, especially for a
single-user local tool where both credentials live in the same
`.env`/gitignore trust boundary either way — the OAuth token wasn't
protecting against a threat model this project actually has (a
multi-tenant server, a published app other people log into); it was
solving for a threat model (a leaked long-lived credential granting
broad account access) that matters much more to a hosted product than a
personal script on one machine.

**The one requirement that didn't move regardless of which mechanism won:**
nothing about either approach can be hardcoded if this project is ever
open-sourced — every credential (App Password, OAuth token, whichever)
has to be something each person generates for their own account and
drops into their own gitignored `.env` or `token.json`, with the shared
code containing zero trace of any specific person's account. Both
designs satisfy this equally; it was worth stating explicitly and
re-checking before writing a line of code, not assumed, since "works for
me" and "safe to hand to someone else" are different bars and it's easy
to accidentally build only the first one.

The actual code enforcing hard rule 2 ("never auto-send") didn't change
between the two designs either: exactly one function
(`gmail_client.send_email`) can call out to an email server, it's called
from exactly one FastAPI endpoint, and that endpoint only fires from a
frontend confirmation modal that shows the literal final text before the
click. That boundary is what makes "never auto-send" a guarantee instead
of a hope — and it's independent of which credential mechanism sits
behind it.

---

## 18. A URL is data, not a claim -- and why editable beats "trust the model"

Three small, unrelated-sounding requests landed together after the send
button shipped: make the draft editable in the UI, stop saying "tailored
resume" to a recruiter who doesn't care about that framing, and add a
second email type that explicitly asks for a referral against one
specific job posting (gated on the user pasting in a real link). The
first two were quick prompt/UI fixes. The third one surfaced a bug this
project's own guardrail machinery was specifically designed to catch --
just not on the input it was built for.

The referral prompt told the model to include the job posting URL
verbatim inside its answer. The very first mocked test written for this
(before any real API call) failed in a way worth sitting with: the URL
`https://acme.com/careers/software-engineer-123` got treated as
containing an unverified number, `123`, and the numeric-fabrication
guardrail (built for catching an invented percentage or headcount)
dropped the entire sentence -- URL included. The guardrail was doing
exactly its job; it just had no way to know a job-id number in a URL
isn't the same kind of claim as "reduced latency by 40%." Structurally
they look identical to a regex.

The fix wasn't a smarter regex or a URL-shaped exception carved into the
numeric checker -- it was noticing the URL didn't need to be something
the *model* produced at all. It's not a claim about the candidate; it's
a piece of data the user already typed in, known verbatim before the API
call even happens. So it stopped being part of the model's citation-
checked output and became a deterministic line of code appends after
validation, the same move already made for the sign-off a day earlier.
Verified the fix held even in the failure case: ran it for real against
Snowflake's data and the model *did* write the raw URL anyway despite
the instruction not to -- that specific sentence got correctly dropped
by the numeric guardrail exactly as designed, and the email still came
out complete and sendable, because the link line never depended on that
sentence surviving. The bug only ever mattered when the link's fate rode
on the model's compliance; once it didn't, the guardrail catching a bad
sentence became a non-event instead of a broken email.

The editable-UI change is worth naming as a design principle, not just a
UI nicety: everything built so far in this project treats the model's
output as either good enough to ship as-is or dropped by a guardrail --
there was no third option where a human just fixes the one thing that's
off. Making the draft a real text field before send closes that gap
cheaply. A soft validation flag (the length check, the JD-relevance
check) was always "worth a second look, not a hard stop" in principle;
until this change, there was nowhere to act on that second look except
regenerating and hoping. Now there is.

---

## 19. The email said "attached" and nothing was

Right after the send button shipped, a gap surfaced that's worth naming
plainly: every draft's own text said "my resume is attached" (and "a
cover letter too" when one existed), and the send endpoint sent exactly
that text with zero actual attachments. The email wasn't wrong to write
-- it's what a normal outreach email says -- but the code hadn't caught
up to make that sentence true. Nothing in this project's guardrail
machinery would have caught this either: the fabrication checks only
look at claims about the *candidate's history*, not at whether the
email's own stated behavior (an attachment) actually happens.

The fix is a real hard requirement, not a soft flag like most of this
project's other checks: `gmail_client.send_email()` now treats a missing
attachment file as an error that stops the send entirely, rather than
letting an email go out that claims something false. This is a
deliberate departure from the "soft flag, let a human decide" pattern
used everywhere else in Stage 6 (length, JD-relevance, formatting) --
those are judgment calls where a human's read might reasonably differ
from the check; "does this file exist on disk" isn't a judgment call,
it's a fact, so it gets a hard stop instead of a warning.

Verified in the same two-step order as every other feature here: a
mocked test first (both files present, only one present, a missing one
raises and confirms *nothing* got sent, no attachments at all still
works) before spending anything real, then one live self-test send using
the actual PDF files from a real application (Jobright's resume + cover
letter) to a synthetic contact pointed at the user's own inbox --
confirmed both files arrived and opened correctly, and the real
Snowflake/Jobright rows were untouched throughout.

---

## 20. The first agent whose job is fidelity, not selection

Every agent built so far shares one assumption: `master_resume.yaml` is
already trusted, already correct, already someone's real reviewed
history -- tailor.py selects from it, cover_letter.py and
draft_outreach.py cite it, but none of them ever *create* it. That
assumption breaks the moment you ask "how does someone new even get a
master_resume.yaml in the first place" -- a real, necessary question
before this project could mean anything to an open-source user, not just
its original one.

The interesting design fork was realizing this new stage's risk profile
is the mirror image of everything else in the pipeline. Tailoring's
danger is *adding* something that isn't true. Onboarding's danger is
*losing* something that already is -- summarizing away a real detail
while converting free-flowing resume prose into discrete, tagged
bullets. The existing numeric-fabrication guardrail still applies (a
number appearing in the structured output that was never anywhere in
the uploaded resume is exactly as wrong here as an invented metric is in
a reworded bullet) but it has to run differently: tailor.py always has a
single original bullet to diff a reworded version against 1:1; this
stage is doing the segmentation itself, deciding where one bullet ends
and the next begins, so there's no fixed original to align to. The
honest fix was checking globally -- every number in the whole draft
must appear somewhere in the whole source text -- which is a real,
weaker guarantee (it can't catch a number that leaked into the wrong
bullet) and worth stating as exactly that rather than quietly presenting
it as equivalent to the stronger per-bullet check elsewhere.

The other real design tension was what happens when the guardrail
*does* flag something. Every other guardrail in this project has a safe
fallback to revert to -- tailor.py reverts to the untouched master
bullet, the outreach agent drops an unverifiable claim entirely. This
stage has no fallback: the model's transcription attempt is the only
candidate content there is. Dropping a flagged bullet wouldn't make the
resume more correct, it would just silently delete a real
accomplishment the user would then have to notice is missing and
re-add by hand anyway. So the design leans harder on the review step
that already has to exist here regardless (a human confirms before this
becomes the real source of truth) -- flag it clearly, show the raw
extracted text right there for comparison, and trust the same "human
decides" mechanism this project has used for every other judgment call
it can't safely automate.

Verified end to end with a synthetic fake resume, not the real one:
mocked tests first (id-assignment matching the real file's exact
numbering convention, a deliberately fabricated number correctly
flagged, a real number elsewhere in the source correctly not flagged),
then a real API call, then the full live path through the actual
dashboard -- upload, parse, hand-edit, confirm, verify a backup got
created and the file changed -- and finally restored the user's real
`master_resume.yaml` from that same backup (plus its own git history,
since it turned out to already be a tracked file) before ending the
task, so a test resume was never at risk of becoming the live one used
for a real application.

---

## 21. A feature that reveals its own next requirement by being used

The upload feature from the previous session was tested for real the
same day it shipped -- with a second real resume, belonging to a real
person (a friend, with consent, used for testing). That single test run
immediately exposed the exact gap the design hadn't accounted for:
uploading a new resume just overwrote the old one. There was no way to
keep both, and no way for a past application to say which one it had
used. The fix wasn't a bug fix -- the upload feature worked exactly as
designed -- it revealed that the design's assumption (one resume, ever)
was too narrow the moment a second real resume existed.

This is worth naming as a pattern: some gaps only become visible through
real use, not through more design review beforehand. The first version
of "let a user give the system their resume" was scoped correctly for
"a resume" (singular) because that was the only case discussed. The
moment a real second case showed up, the singular design was
retroactively wrong, not because anyone missed something obvious, but
because the requirement genuinely didn't exist until someone did the
thing that created it.

**A real safety moment, not just a design one:** before touching
anything, `git status` showed the live `master_resume.yaml` held a
completely different person's real PII than what was committed. Rather
than assume it was a mistake and quietly restore the "correct" data (or
assume it was intentional and build straight through it), the right move
was to stop and ask -- both what should happen to that specific data,
and what actually happened, before writing any code that would move or
duplicate it. It turned out to be exactly the intentional test that
motivated this whole feature request, but a second real person's PII
sitting uncommitted in a repo isn't something to guess about.

**Design choice made along the way, not originally planned:** the new
`data/master_resumes/` library is fully gitignored, unlike the original
single `master_resume.yaml`, which had been tracked in git since Phase 0
("you want version history on resume changes"). That tradeoff made sense
when there was only ever one person's data, already flagged for future
redaction before any public push. It stops making sense the moment a
second real person's data can end up in the same directory -- the
original owner doesn't get to decide someone else's PII goes into a
project's git history. The new backup mechanism (already built the
previous session) gives local point-in-time recovery without that
tradeoff.

**Verification, in the same order as every feature before it:** file
migration first (Divij's committed resume and the uncommitted Harshpreet
data split into two named library entries, confirmed byte-for-byte via a
direct diff before either was touched further), then a DB migration on
the real, populated database (non-destructive `ALTER TABLE`, backfilling
the two existing real applications with `"Main Resume"` since that was
the only resume that existed when they were logged), then endpoint-level
checks, and finally one real pipeline run through the actual `/api/jobs`
endpoint against the second resume -- confirmed both the database row
and the rendered output filename reflected the right person, not a
silent fallback to the default. Cleaned up the test application and its
output files afterward; the two real applications and the real resume
data were never at risk throughout.

---

*(more entries added as this project continues)*
