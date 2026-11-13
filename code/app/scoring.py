"""Scores a result against an expected file, the way the pack describes.

Scored fields: decision, reason_code (one of the accepted codes), amount
(within tolerance; null must stay null), key_numbers (each must appear among
the result's numbers), must_cite (each id must be in citations) and
needs_human. The case score is the share of these checks that pass.
"""


def _numbers(result: dict) -> list[float]:
    nums = [v for v in (result.get("figures") or {}).values() if isinstance(v, (int, float))]
    if isinstance(result.get("amount"), (int, float)):
        nums.append(result["amount"])
    return nums


def _cited(expected_id: str, citations: list[str]) -> bool:
    eid = expected_id.lower()
    return any(c.lower() == eid or eid in c.lower() for c in citations)


def check_case(result: dict, expected: dict) -> dict[str, bool]:
    checks = {
        "decision": result.get("decision") == expected["decision"],
        "reason_code": result.get("reason_code") in expected["reason_code"],
        "needs_human": result.get("needs_human") == expected["needs_human"],
    }
    exp_amount = expected.get("amount")
    if exp_amount is None:
        checks["amount"] = result.get("amount") is None
    else:
        got = result.get("amount")
        checks["amount"] = (
            isinstance(got, (int, float)) and abs(got - exp_amount["value"]) <= exp_amount["tolerance"]
        )
    nums = _numbers(result)
    for i, kn in enumerate(expected.get("key_numbers", [])):
        checks[f"key_number_{i + 1}"] = any(abs(n - kn["value"]) <= kn["tolerance"] for n in nums)
    citations = result.get("citations") or []
    for cid in expected.get("must_cite", []):
        checks[f"cite:{cid}"] = _cited(cid, citations)
    return checks


def score_case(result: dict, expected: dict) -> float:
    checks = check_case(result, expected)
    return round(sum(checks.values()) / len(checks), 4)
