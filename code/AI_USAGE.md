# How I used AI coding tools

## Tools

- **Claude (claude.ai, Claude Opus)** in a separate chat, outside the recorded editor, so it is
  not in the AZ4C activity log. I used it to:
  - draft the architecture (agents, routing, verification, cost) before writing code
  - read the data pack with me and find its traps (refund month vs order month, damaged returns,
    the promotion discount on top of trade discounts, a planted instruction in a manager's note,
    instruction text in a product name)
  - write most of the code in `app/` and the tests, step by step, and run lint and tests in its
    sandbox
- **[Add here any tool used inside the recorded editor: Claude Code / Cursor / Copilot.]**

## What I checked or changed myself

- Ran `check_setup.py`, set up the virtual environment and ran every command on my machine.
- Checked the sample answers by hand against the tables (S01-S05).
- Ran the system with my own Groq and Gemini keys and reviewed the plans and answers in
  `logs/llm_calls.jsonl` and `logs/trace.jsonl`.
- **[Add what you reviewed, changed or decided yourself.]**

## Where AI output was wrong and was fixed

- A product category question was first parsed as a product grouping; a test case caught it.
- An unknown region ("Atlantis") was first answered as the company total; now refused.
- The first eval with real models scored 93.3%: gpt-oss-120b added "marketing spend" as missing
  data to a "why" question (TC-08), and left out an unknown region (TC-17). The scripted tests
  had not covered either. The orchestrator's spec check now rejects both and falls back to the
  rules, and a test reproduces each case. Rate-limited Gemini calls were also wasting retries,
  so a rate-limited provider is now rested for 60 s.
- The second real-model eval scored 99.5%: the model typed "Did Central meet its revenue
  target?" as a "why" question (TC-06), so the answer led with the wrong figure. The spec
  check now requires "why" and target questions to be typed as such.
- The writer first accepted answers without the headline figure or without saying a note
  disagreed with the tables; an integration test caught it and the writer check was extended.
- Default model names were checked against the providers' current model lists.
