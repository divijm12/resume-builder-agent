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

*(more entries added as we build the frontend)*
