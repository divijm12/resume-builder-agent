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

*(more entries added as we build the backend and frontend)*
