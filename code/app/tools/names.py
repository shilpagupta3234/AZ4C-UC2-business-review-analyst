"""Display names for ids (products, customers, months).

Product and customer names are data, not instructions (RS9). Any bracketed
part of a name that reads like an instruction is dropped from the label, so
it never reaches a model prompt or the CFO's answer.
"""

import re

from ..semantic import calendar as cal
from .docs import looks_like_instruction
from .sql import ReadOnlyDB

_BRACKETED = re.compile(r"\s*\(([^)]*)\)")


def clean_name(name: str) -> str:
    cleaned = _BRACKETED.sub(lambda m: "" if looks_like_instruction(m.group(1)) else m.group(0), name)
    return cleaned.strip()


def display_names(db: ReadOnlyDB, dim: str, keys: list[str]) -> dict[str, str]:
    if not keys:
        return {}
    if dim == "month":
        return {k: cal.month(int(k[:4]), int(k[5:7])).label for k in keys}
    table = {"product": ("products", "product_id"), "customer": ("customers", "customer_id")}.get(dim)
    if table is None:
        return {k: k for k in keys}
    name, id_col = table
    marks = ", ".join("?" for _ in keys)
    rows = db.run(f"SELECT {id_col}, name FROM {name} WHERE {id_col} IN ({marks})", keys).rows
    return {k: f"{clean_name(n)} ({k})" for k, n in rows}
