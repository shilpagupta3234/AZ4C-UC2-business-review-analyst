"""Finance calendar (docs/finance_calendar.md), as plain code.

- Months are calendar months.
- The financial year runs 1 April to 31 March and is named after the year it
  ends in: FY27 = 1 Apr 2026 to 31 Mar 2027.
- Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar.

Relative phrases ("last month", "this quarter") are not resolved here. The
reporting standards (RS7) say an unclear period must be clarified, not guessed.
"""

import calendar as _cal
import re
from dataclasses import dataclass
from datetime import date

DOC_REF = "finance_calendar.md"

MONTHS = {name.lower(): i for i, name in enumerate(_cal.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(_cal.month_abbr) if name})
MONTHS["sept"] = 9


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str  # how finance names it, e.g. "August 2026", "Q1 FY27", "FY26"
    grain: str  # month | quarter | fy

    def months(self) -> list[str]:
        """Every calendar month in the period, as 'YYYY-MM'."""
        out, y, m = [], self.start.year, self.start.month
        while (y, m) <= (self.end.year, self.end.month):
            out.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out


def month(year: int, m: int) -> Period:
    last = _cal.monthrange(year, m)[1]
    return Period(date(year, m, 1), date(year, m, last), f"{_cal.month_name[m]} {year}", "month")


def fiscal_year(fy: int) -> Period:
    """fy is the calendar year the financial year ends in (FY27 -> 2027)."""
    return Period(date(fy - 1, 4, 1), date(fy, 3, 31), f"FY{fy % 100:02d}", "fy")


def quarter(q: int, fy: int) -> Period:
    if q not in (1, 2, 3, 4):
        raise ValueError(f"quarter must be 1-4, got {q}")
    first_month = {1: 4, 2: 7, 3: 10, 4: 1}[q]
    year = fy if q == 4 else fy - 1
    end = month(year, first_month + 2)
    return Period(date(year, first_month, 1), end.end, f"Q{q} FY{fy % 100:02d}", "quarter")


def previous(p: Period) -> Period:
    """The period just before p, at the same grain (for period-over-period)."""
    if p.grain == "month":
        y, m = (p.start.year - 1, 12) if p.start.month == 1 else (p.start.year, p.start.month - 1)
        return month(y, m)
    if p.grain == "quarter":
        q, fy = int(p.label[1]), _fy_number(p.label.split()[1])
        return quarter(4, fy - 1) if q == 1 else quarter(q - 1, fy)
    return fiscal_year(_fy_number(p.label) - 1)


def _fy_number(token: str) -> int:
    n = int(re.sub(r"\D", "", token))
    return 2000 + n if n < 100 else n


_FY = r"(?:FY|financial\s+year)\s?'?(\d{2}|\d{4})"  # "financial year 2026" is FY26 (named by its end)
_QUARTER_RE = re.compile(rf"\bQ([1-4])\s*,?\s*{_FY}\b", re.I)
_FY_RE = re.compile(rf"\b{_FY}\b", re.I)
_ISO_MONTH_RE = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])\b")
_MONTH_YEAR_RE = re.compile(r"\b([A-Za-z]{3,9})\.?,?\s+(20\d{2})\b")


_MONTH_NAME = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# "January to September 2026": a span of months, only the last of which has a year.
_MONTH_SPAN_RE = re.compile(
    rf"\b{_MONTH_NAME}\s+(?:to|through|till|until|-)\s+{_MONTH_NAME}\s+20\d{{2}}\b", re.I
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b(?!-\d)")  # not the year of an ISO month like 2026-08
_NAMED_BEFORE_RE = re.compile(rf"(?:{_MONTH_NAME}|fy|year|q[1-4]|-)\s*'?$", re.I)


def month_span(text: str) -> str | None:
    """The text of a month span such as "January to September 2026", if the question has one."""
    m = _MONTH_SPAN_RE.search(text)
    return m.group(0) if m else None


def bare_year(text: str) -> int | None:
    """A year written on its own ("revenue of 2026"): two financial years or a calendar year."""
    for m in _YEAR_RE.finditer(text):
        if not _NAMED_BEFORE_RE.search(text[: m.start()].rstrip()):
            return int(m.group(1))
    return None


def parse_periods(text: str) -> list[Period]:
    """Every explicit period named in text, in the order they appear.

    Returns [] when the text names no period it can pin down. A month without a
    year ("in August") is not resolved, because the data spans two Augusts.
    """
    found: list[tuple[int, Period]] = []
    taken: list[range] = []

    def add(m: re.Match, p: Period) -> None:
        span = range(m.start(), m.end())
        if not any(set(span) & set(t) for t in taken):
            taken.append(span)
            found.append((m.start(), p))

    for m in _QUARTER_RE.finditer(text):
        add(m, quarter(int(m.group(1)), _fy_number(m.group(2))))
    for m in _FY_RE.finditer(text):
        add(m, fiscal_year(_fy_number(m.group(1))))
    for m in _ISO_MONTH_RE.finditer(text):
        add(m, month(int(m.group(1)), int(m.group(2))))
    for m in _MONTH_YEAR_RE.finditer(text):
        num = MONTHS.get(m.group(1).lower())
        if num:
            add(m, month(int(m.group(2)), num))
    return [p for _, p in sorted(found, key=lambda x: x[0])]
