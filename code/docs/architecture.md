# Architecture

One orchestrator leads five specialists. The orchestrator's model understands the question;
code computes every number; a second calculation checks every number; a person approves
the answer before it is filed.

```mermaid
flowchart TD
    Q[Case file: one CFO question] --> O

    subgraph Agents
        O["Orchestrator<br/>model: Groq gpt-oss-120b<br/>question to typed spec, picks the team"]
        D["Definitions and period<br/>code: answerability gate<br/>RS5 / RS6 / RS7, calendar, coverage"]
        DA["Data analyst<br/>code: metric registry to SQL"]
        V["Targets and variance<br/>code: vs target, vs previous period,<br/>margin and revenue bridges"]
        C["Context analyst<br/>model: Gemini Flash summary<br/>notes and promo briefs, claims checked in code"]
        VE["Verifier<br/>code: second SQL path,<br/>RS2 reconciliation, invariants"]
        W["Writer<br/>model: Gemini Flash<br/>grounding check, template fallback"]
    end

    O --> D
    D -- "cannot answer" --> W
    D -- answerable --> DA
    DA -- "target / comparison / why" --> V
    DA -- "plain value or breakdown" --> VE
    V -- "why question" --> C
    V --> VE
    C --> VE
    VE -- "mismatch: send back (max 2)" --> DA
    VE --> W
    W -- answered --> A{"Finance controller approves<br/>CLI or HTML approval page"}
    W -- "refusal (no approval needed)" --> S
    A -- approve --> S["Save: mock_system/report_store/&lt;case_id&gt;.md<br/>+ audit/query_log.jsonl"]
    A -- "change + note" --> W
    A -- reject --> X[Nothing written]

    subgraph Tools["Tools (agents reach data only through these)"]
        T1[(sales.sqlite, read-only)]
        T2[Metric registry + compiler]
        T3[Finance calendar]
        T4[Docs reader: untrusted, screened]
        T5[LLM gateway: retries, fallback, call log]
    end
```

## How the team changes with the question

| Question | Agents that run |
| --- | --- |
| What was South's gross margin in August 2026? | Definitions, Data analyst, Verifier, Writer |
| Which sales channel had the highest net revenue in Q1 FY27? | Definitions, Data analyst, Verifier, Writer |
| Did Central meet its revenue target in July 2026? | + Targets and variance |
| Why did South's margin drop in September 2026? | + Targets and variance, Context analyst |
| Gross margin by salesperson / December 2026 / change a target | Definitions, Writer (stops at the gate) |

## State and persistence

Agents share a typed LangGraph state, not chat transcripts. It is checkpointed to
`.state/checkpoints.db` (SQLite) after every node, keyed by run id, so a run paused for
approval survives the process ending and resumes with `python -m app approve <run_id>`.

## Logs

| File | One line per |
| --- | --- |
| `logs/llm_calls.jsonl` | model call attempt: node, provider, model, status, latency, tokens, cost |
| `logs/trace.jsonl` | graph event: plan, gate decision, verifier result, approval |
| `mock_system/audit/query_log.jsonl` | SQL query of an approved run, rerunnable (RS3) |
