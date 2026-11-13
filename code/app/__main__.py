"""Entry point for your system. Run these from the code/ folder:

    python -m app run --case ../samples/UC2-S01.json --out out/UC2-S01.json
    python -m app run --case <case.json> --out <result.json> --auto-approve
    python -m app approve <run_id> --action approve|reject|change
    python -m app eval --cases tests/cases

Keep the command names and options. Everything behind them is yours to build,
in this package or in modules it imports.

eval writes tests/score.json when it runs tests/cases, in this format:
    {"cases": 20, "score": 85.0, "per_case": [{"case_id": "...", "score": 1.0}]}
score is 0 to 100; each per_case score is 0 to 1.
"""

import argparse
import json
import sys
from pathlib import Path

from .config import CODE_DIR  # loads code/.env and resolves DATA_DIR
from .runner import RunNotFound, resume_run, start_run
from .scoring import score_case


def run_case(case: dict, auto_approve: bool, out_path: str | None = None) -> dict:
    """Run one case end to end and return its result (format: ../schema/result.schema.json)."""
    return start_run(case, auto_approve, out_path)


def approve(run_id: str, action: str, note: str = "") -> dict:
    """Resume a paused run with the person's decision."""
    return resume_run(run_id, action, note)


def cmd_run(args) -> None:
    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    result = run_case(case, args.auto_approve, args.out)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{result['case_id']}: {result['decision']} ({result['reason_code']}) -> {out}")
    if result.get("approval", {}).get("status") == "pending":
        print(f"Waiting for approval. Run id: {result['trace_id']}")
        print(f'  python -m app approve {result["trace_id"]} --action approve|reject|change [--note "..."]')


def cmd_eval(args) -> None:
    cases_dir = Path(args.cases).resolve()
    expected_dir = cases_dir / "expected"
    if not expected_dir.is_dir():
        expected_dir = cases_dir.parent / "expected"
    per_case = []
    for case_file in sorted(cases_dir.glob("*.json")):
        case = json.loads(case_file.read_text(encoding="utf-8"))
        expected = json.loads((expected_dir / case_file.name).read_text(encoding="utf-8"))
        try:
            result = run_case(case, auto_approve=True)
            out = CODE_DIR / "out" / case_file.name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            score = score_case(result, expected)
        except Exception as e:
            print(f"{case['case_id']}: {type(e).__name__}: {e}", file=sys.stderr)
            score = 0.0
        per_case.append({"case_id": case["case_id"], "score": score})
        print(f"{case['case_id']}  {score:.2f}")
    total = round(100 * sum(c["score"] for c in per_case) / len(per_case), 1) if per_case else 0.0
    print(f"Score: {total}% over {len(per_case)} cases")
    if cases_dir.is_relative_to(CODE_DIR / "tests"):
        report = {"cases": len(per_case), "score": total, "per_case": per_case}
        (CODE_DIR / "tests" / "score.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def cmd_approve(args) -> None:
    try:
        result = approve(args.run_id, args.action, args.note)
    except RunNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    status = result.get("approval", {}).get("status")
    print(f"{args.run_id}: {status}")
    if status == "pending":
        print("Revised answer is waiting for approval again:")
        print(result.get("answer", ""))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app", description="UC2: Business review analyst")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run one case end to end and write the result")
    p.add_argument("--case", required=True, help="case JSON file")
    p.add_argument("--out", required=True, help="where to write the result JSON")
    p.add_argument("--auto-approve", action="store_true", help="approve at the approval step without waiting")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("eval", help="run every case in a folder and print the score")
    p.add_argument("--cases", required=True, help="folder of case JSON files")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("approve", help="resume a paused run")
    p.add_argument("run_id")
    p.add_argument("--action", required=True, choices=["approve", "reject", "change"])
    p.add_argument("--note", default="", help="for --action change: what to change in the answer")
    p.set_defaults(func=cmd_approve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
