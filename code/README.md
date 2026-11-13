# Business review analyst (AZ4C UC2)

A team of AI agents that answers the CFO's sales and margin questions for Saffron Trail Foods
with numbers that add up, shows how each number was worked out, and files the answer only
after the finance controller approves it. Built for Part A + B (AI Engineer / Lead).

**In plain words:** you type a question such as *"What was South's gross margin in August
2026?"*. The system works the answer out from the sales data (34.67%), checks every number a
second way, and shows it to the finance controller. Only after they press **Approve** is the
answer saved in the report store.

---

## Step-by-step guide (no coding knowledge needed)

Follow the steps in order. Each step says what to type and what you should see. Windows and
Mac/Linux commands are given side by side; use the one for your computer.

### Step 0: What you need

| What | Where to get it | Time |
| --- | --- | --- |
| **Python 3.12** | [python.org/downloads](https://www.python.org/downloads/). On Windows, tick **"Add python.exe to PATH"** on the first install screen | 5 min |
| **A free Groq key** | [console.groq.com/keys](https://console.groq.com/keys) > Create API Key. Copy it somewhere safe | 2 min |
| **A free Gemini key** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) > Create API key | 2 min |
| **This project folder** | Download or clone this repository | 1 min |

The keys are optional: without them the system still runs and gives the same numbers, using
its built-in rules instead of the AI models. With them, the AI models plan and write the answers.

### Step 1: Open a terminal inside the `code` folder

- **Windows:** open the project folder in File Explorer, open the `code` folder, click the
  address bar at the top, type `powershell` and press Enter.
- **Mac:** right-click the `code` folder in Finder > *New Terminal at Folder*.
- **Linux:** right-click inside the `code` folder > *Open in Terminal*.

Check you are in the right place:

| Windows | Mac / Linux |
| --- | --- |
| `dir app` | `ls app` |

**You should see** a list of files including `__main__.py`. If you see "cannot find path", you
are not in the `code` folder: go back to Step 1.

### Step 2: Create a private Python space for this project (a "virtual environment")

This keeps the project's packages separate from the rest of your computer. Run once.

| Windows | Mac / Linux |
| --- | --- |
| `py -3.12 -m venv .venv` | `python3.12 -m venv .venv` |
| `.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |

**You should see** `(.venv)` at the start of the terminal line.

- Windows says *"running scripts is disabled"*? Run
  `Set-ExecutionPolicy -Scope Process Bypass`, press `Y` if asked, then run the
  `Activate.ps1` line again.
- *"py is not recognized"* or *"python3.12: command not found"*? Python 3.12 is not installed,
  or was installed without "Add to PATH": go back to Step 0.

**Every time you open a new terminal**, run the second line again (activate) before the steps below.

### Step 3: Install the packages

```
python -m pip install -r requirements.txt
```

**You should see** many lines ending with `Successfully installed ...`. This takes 1 to 3 minutes.

### Step 4: Add your keys

| Windows | Mac / Linux |
| --- | --- |
| `copy .env.example .env` | `cp .env.example .env` |
| `notepad .env` | `nano .env` (or open `.env` in any text editor) |

Fill in the two key lines, with no quotes and no spaces around `=`:

```
GROQ_API_KEY=gsk_your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here
```

Leave the two `BASE_URL` lines as they are. Save and close the file. The `.env` file stays on
your computer and is never uploaded (it is listed in `.gitignore`). Never paste a key anywhere else.

### Step 5: Check that everything works

```
python -m pytest -q
```

**You should see** a row of dots and then `193 passed` (the number of automatic checks). It
takes about 20 seconds. These checks use a built-in fake AI, so they pass with or without keys.

### Step 6: Ask your first question

This runs the pack's first sample question: *"What was South's gross margin in August 2026?"*

| Windows | Mac / Linux |
| --- | --- |
| `python -m app run --case ..\samples\UC2-S01.json --out out\UC2-S01.json` | `python -m app run --case ../samples/UC2-S01.json --out out/UC2-S01.json` |

**You should see** (the run id will be different):

```
UC2-S01: answered (ANSWERED) -> out/UC2-S01.json
Waiting for approval. Run id: 3f2a9c1e-...
  python -m app approve 3f2a9c1e-... --action approve|reject|change [--note "..."]
```

With keys this takes 10 to 40 seconds (the free AI plans are slow); without keys about 1 second.
The full answer is in `out/UC2-S01.json`; open it with any text editor.

### Step 7: Approve the answer

Copy the run id from Step 6 and run:

```
python -m app approve <run id> --action approve
```

**You should see** `<run id>: approved`. The answer is now saved in
`mock_system/report_store/UC2-S01.md`, and the database queries behind it in
`mock_system/audit/query_log.jsonl`.

Instead of `approve` you can use `--action reject` (nothing is saved) or
`--action change --note "Lead with the margin figure"` (the answer is rewritten with your note
and waits for approval again).

### Step 8: Use the approval page (easier than Step 6 and 7)

```
python -m app.ui.web
```

**You should see** `Approval desk: http://127.0.0.1:8000`. Open that address in your browser.

1. Type a question in **Ask a question** on the left, for example
   *Which region had the lowest gross margin in Q1 FY27?*, and press **Get answer**.
2. The answer opens with a green **Verified** stamp (every number was checked a second way).
3. Press **Approve and file**, **Reject**, or write a note and press **Request change**.

The page only works on your own computer. To stop it, press `Ctrl+C` in the terminal.

### Step 9: See the score

```
python -m app eval --cases tests/cases
python -m app eval --cases ../samples
```

**You should see** one line per question (`1.00` = fully correct) and then
`Score: 100.0% over 28 cases` and `Score: 100.0% over 5 cases`.

### Questions you can ask

Any of these measures: **gross sales, discounts, net revenue, net COGS, gross margin %,
contribution margin, revenue against target, promotion cost**. Broken down by **region, channel,
category, brand, product, customer or month**, for any month, quarter (Q1 FY27 = April to June
2026) or financial year (FY26 = April 2025 to March 2026) from **April 2025 to September 2026**.

| Kind | Example |
| --- | --- |
| A value | What was contribution margin for West in August 2026? |
| A breakdown | What was gross sales by channel in FY26? |
| A ranking | Which product had the highest net revenue in Q2 FY27? |
| A comparison | How did East's gross margin change from Q1 FY27 to Q2 FY27? |
| A target | Did Central meet its revenue target in July 2026? |
| A "why" | Why did South's margin drop in September 2026? |

The system politely refuses, and says why, when the data cannot answer: salesperson,
marketing spend, inventory or forecasts (not in the data); a period without a month, quarter or
year ("last month", "2026" on its own); dates after September 2026; and any request to change
data.

### If something goes wrong

| What you see | What to do |
| --- | --- |
| `No module named app` | You are not in the `code` folder. Go back to Step 1 |
| `No module named langgraph` (or another package) | The virtual environment is not active or packages are missing: run the activate line from Step 2, then Step 3 |
| `(.venv)` is missing at the start of the line | Run the activate line from Step 2 |
| In `out/<case>.json`, `"answer_source"` is `"template"` | The AI models were not used: check the keys in `.env` (Step 4). The numbers are still correct |
| It takes a long time | Free AI plans limit speed. The system waits, switches provider if needed, and always finishes |
| `Address already in use` when starting the page | The page is already running in another terminal. Use that one, or run `python -m app.ui.web --port 8001` |
| A change to the code does not show on the page | Stop the page with `Ctrl+C`, start it again, then refresh the browser |

---

## Command reference

| Command | What it does |
| --- | --- |
| `python -m app run --case ../samples/UC2-S01.json --out out/UC2-S01.json` | Runs one case; pauses at approval and prints the run id |
| `python -m app approve <run_id> --action approve` | Approves: the answer is filed in `mock_system/` |
| `python -m app approve <run_id> --action reject` | Rejects: nothing is written |
| `python -m app approve <run_id> --action change --note "..."` | Sends a note to the writer; the run waits for approval again |
| `python -m app run ... --auto-approve` | Approves without waiting |
| `python -m app eval --cases tests/cases` | Runs the 28 test cases, prints the score, writes `tests/score.json` |
| `python -m app eval --cases ../samples` | Scores the pack's 5 samples |
| `python -m app.ui.web` | Approval page (bonus) at http://127.0.0.1:8000: ask a question, then approve, reject or request a change. Plain HTML, no JavaScript, no extra package |
| `python -m pytest` / `python -m ruff check .` | 193 unit and integration tests / lint |

`DATA_DIR` defaults to the repository root (where `data/` and `docs/` are). Point it at another
copy of the pack with `DATA_DIR=/path/to/pack`. With `make` installed: `make install`,
`make check`, `make eval`, `make ui`.

## Design

See `docs/architecture.md` for the diagram. The principle: **the model plans and writes; code
computes and checks.** No model does arithmetic or supplies a number.

| Agent | Kind | Job |
| --- | --- | --- |
| Orchestrator | model | Turns the question into a typed `QuerySpec` (metrics, periods, regions, grouping, question type) and picks the team |
| Definitions and period | code | The gate: write requests (RS6), data not held (RS5), unclear measure or period (RS7), periods outside the data, unknown regions. Resolves names to ids and dates |
| Data analyst | code + tools | Computes each figure through the metric registry; every figure becomes a fact with a label (RS1) and the queries behind it |
| Targets and variance | code + tools | Actual vs target (M7), change vs another period, and for "why" questions a bridge whose drivers add up to the change exactly (RS2) |
| Context analyst | model + tools | Reads managers' notes and promotion briefs, removes instruction-like text, checks each claim against the tables (RS4); the model only summarises |
| Verifier | code + tools | Recomputes every figure with separately written SQL, checks group totals (INR 1) and bridges (0.1 pp); sends work back at most twice |
| Writer | model | Writes the answer from verified facts; rejected if it contains a number not in the facts, misses the headline figure, or ignores a disagreeing note |

**How the orchestrator decides what runs next.** The model's spec is checked against the
question: the periods and regions must be the ones written in the question, every metric must
exist in the registry, missing data may be claimed only for data the question asks for, and a
"why" or target question must be typed as one. A failing spec is sent back once with the errors,
then replaced by a deterministic parser's spec. The team follows from the spec: targets,
comparisons and "why" questions bring in Targets and variance; only "why" questions bring in the
Context analyst; questions the data cannot answer stop at the gate and skip every specialist.
Skipped agents and the reason are recorded in the result's `plan`.

## Tools

| Tool | Takes | Returns |
| --- | --- | --- |
| `compute_metric` | metric id, period, filters, grouping | values per group, the measures behind them, query ids |
| `run_measures` | measure ids, period, filters | raw totals for bridges |
| `data_coverage` | - | date range, regions, channels, categories |
| `ReadOnlyDB.run` | one SELECT and bound values | rows and a logged query id |
| `docs.commentary`, `docs.promo_brief` | month and region, or promo id | screened text and removed sentences |

The metric registry (`app/semantic/metrics.py`) holds M1-M8 from `metric_definitions.md`;
`compiler.py` turns a metric into SQL once, tested: refunds count in the return month, region
comes from the order, damaged returns keep their cost. The database is opened read-only, and
`sqlglot` refuses anything but a single SELECT on known tables.

**Tool errors.** A database error is retried once; if it persists the run ends `cannot_answer`
with the reason. Asking for a cut the data does not have (targets by channel) is refused with
`DATA_NOT_AVAILABLE`.

## Models used and why

| Role | Primary | Fallback | Why |
| --- | --- | --- | --- |
| Orchestrator | Groq `openai/gpt-oss-120b` | Gemini `gemini-3.6-flash` | Planning is where reasoning quality matters; Groq is fast and cheap ($0.15 / $0.60 per 1M tokens) |
| Context, Writer | Gemini `gemini-3.6-flash` | Groq `openai/gpt-oss-20b` | Summarising and writing need fluency, not deep reasoning |

Two providers spread free-tier rate limits, and either can carry a run alone. All calls use
temperature 0 and JSON output validated with Pydantic. Model names can be changed in `.env`.
A typical run makes 1 model call (refusal), 2 (value, ranking, target) or 3 ("why").

## Failure handling

| Failure | Response |
| --- | --- |
| Bad model reply (not JSON, wrong shape) | Sent back once with the validation error, then the fallback model |
| Model reply that is valid but wrong (hallucinated period, a region left out, missing data the question doesn't ask for, a target question typed as "why", number not in facts) | Sent back once with the problems; then the deterministic parser or the fixed template |
| Rate limit (429) | Waits `retry-after` (exponential backoff otherwise); a wait over 20 s or 3 limits in a row switch provider and rest it for 60 s, shared by later runs |
| Provider outage or timeout | 30 s timeout, 3 tries, then the other provider |
| No model available at all | The run still completes: deterministic plan and template answer, marked in the result |
| Figures that disagree | Verifier sends back to the data analyst, twice at most, then `cannot_answer` |
| Missing data | Gate refuses with `DATA_NOT_AVAILABLE` and names what is missing; nothing is estimated |
| Unclear period ("2026" alone, "January to September 2026") | Gate asks for a month, quarter or financial year and names the choices (RS7); nothing is guessed |
| Runaway run | 12 model calls per run, 5,000 rows and 10 s per query |
| Crash or restart while waiting | State is checkpointed in SQLite; `approve` resumes the run |
| Instructions inside documents or data | Removed before any model sees them (notes, product names) and reported |

## Tests and score

- `tests/cases/` + `tests/expected/`: 28 graded cases in the pack's format. Expected answers were
  computed with hand-written SQL, independent of this code. They include hard cases: a note that
  disagrees with the tables, an instruction planted in a note, data not held (salesperson,
  marketing, inventory, forecast), future months, write requests, relative periods, a month with
  no year, an unknown region, rankings by category, brand and customer, targets, and "why".
- `tests/unit/` (131) and `tests/integration/` (62): every failure path above is simulated with a
  scripted fake model: bad replies, hallucinated periods, invented numbers, rate limits, outages,
  database errors, send-backs, and approve, reject and change.

| Suite | Score |
| --- | --- |
| `python -m app eval --cases tests/cases` | 100.0% over 28 cases |
| `python -m app eval --cases ../samples` | 100.0% over 5 cases |
| `python -m pytest` | 193 passed |

The eval scores were measured with real models (Groq `openai/gpt-oss-120b` and Gemini
`gemini-3.6-flash`). Without keys the system runs on its rules and template and gives the same
scores.