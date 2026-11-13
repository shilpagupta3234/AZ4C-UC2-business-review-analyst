# Use case 2: Business review analyst

**Who it's for:** the finance controller at Saffron Trail Foods Ltd, a fictional packaged-foods company selling in five regions of India.

**The problem:** before every leadership review the CFO asks questions like "Why did South's margin drop in September?" Analysts take half a day per question, and their numbers often don't agree.

## What your system does

Takes one question in plain English, works out the answer from the sales data, explains it with numbers that add up, and files the answer in the mock report store.

## How a run starts

```json
{ "case_id": "UC2-S01", "input": { "question": "What was South's gross margin in August 2026?" } }
```

## What you get

- **Tables** in `data/sales.sqlite` (also as CSV), April 2025 to September 2026: regions, customers, products, orders and order lines, returns, promotions, targets.
- **Documents** in `docs/`:
  - `metric_definitions.md`: how finance defines each number. Your answers must use these definitions.
  - `finance_calendar.md`: how months, quarters and the financial year are named.
  - `reporting_standards.md`: how finance expects numbers to be reported and checked. Your system must follow it.
  - `commentary/`: regional managers' monthly notes.
  - `promo_briefs/`: what each promotion was meant to do.

## What your system returns

- `decision`: `answered` or `cannot_answer`
- `reason_code`: `ANSWERED`, `DATA_NOT_AVAILABLE`, `WRITE_REQUEST_REFUSED` or `AMBIGUOUS_QUESTION`
- `answer`: a short explanation for the CFO
- `figures`: the numbers in the answer, by name
- `queries`: every query your system ran
- `citations`: the tables and documents used

## Who approves (Parts B and C)

The finance controller approves every answer before it goes into the leadership report.

## What it writes

- The approved answer in `mock_system/report_store/<case_id>.md`
- Every query run, in `mock_system/audit/query_log.jsonl`

*Synthetic and fictional data.*
