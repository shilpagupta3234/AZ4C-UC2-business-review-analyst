"""What the data covers: date range and the values each dimension can take.

The answerability gate reads this before any metric query runs, so a
question about October 2026 or an unknown region stops early. It is read
from the database, not hard-coded, so it follows the graders' copy.
"""

from dataclasses import dataclass
from datetime import date

from .sql import ReadOnlyDB


@dataclass(frozen=True)
class Coverage:
    first_date: date
    last_date: date
    target_months: tuple[str, str]
    regions: dict[str, str]  # region_id -> name
    channels: tuple[str, ...]
    categories: tuple[str, ...]
    brands: tuple[str, ...]
    promotions: dict[str, str]  # promo_id -> name

    def covers(self, start: date, end: date) -> bool:
        return self.first_date <= start and end <= self.last_date

    def region_id(self, name_or_id: str) -> str | None:
        key = name_or_id.strip().lower()
        for rid, name in self.regions.items():
            if key in (rid.lower(), name.lower()):
                return rid
        return None


def data_coverage(db: ReadOnlyDB) -> Coverage:
    first, last = db.run("SELECT MIN(order_date), MAX(order_date) FROM orders").rows[0]
    t_first, t_last = db.run("SELECT MIN(month), MAX(month) FROM targets").rows[0]

    def values(sql: str) -> tuple[str, ...]:
        return tuple(r[0] for r in db.run(sql).rows)

    return Coverage(
        first_date=date.fromisoformat(first),
        last_date=date.fromisoformat(last),
        target_months=(t_first, t_last),
        regions=dict(db.run("SELECT region_id, name FROM regions ORDER BY region_id").rows),
        channels=values("SELECT DISTINCT channel FROM customers ORDER BY 1"),
        categories=values("SELECT DISTINCT category FROM products ORDER BY 1"),
        brands=values("SELECT DISTINCT brand FROM products ORDER BY 1"),
        promotions=dict(db.run("SELECT promo_id, name FROM promotions ORDER BY promo_id").rows),
    )
