from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from marketplace_pricer.db import DB


@dataclass(frozen=True)
class WeeklyRollup:
    week_start: datetime
    buy_cost_cents: int
    sell_revenue_cents: int
    net_profit_cents: int


def _fmt_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents_abs = abs(cents)
    return f"{sign}${cents_abs // 100:,}.{cents_abs % 100:02d}"


def _week_start(dt: datetime) -> datetime:
    # Monday-based weeks (UTC)
    dt = dt.astimezone(timezone.utc)
    return (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def weekly_rollup(db: DB, *, weeks: int = 8) -> list[WeeklyRollup]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT kind, amount_cents, fees_cents, occurred_at
            FROM inventory
            ORDER BY occurred_at DESC
            """
        ).fetchall()

    buckets: dict[datetime, dict[str, int]] = defaultdict(lambda: {"buy": 0, "sell": 0})
    for row in rows:
        occurred_at = row["occurred_at"]
        if not occurred_at:
            continue
        try:
            dt = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00"))
        except Exception:
            continue
        ws = _week_start(dt)
        kind = str(row["kind"])
        amount = int(row["amount_cents"])
        fees = int(row["fees_cents"] or 0)

        if kind == "buy":
            buckets[ws]["buy"] += amount + fees
        elif kind == "sell":
            buckets[ws]["sell"] += amount - fees

    weeks_sorted = sorted(buckets.keys(), reverse=True)[: max(weeks, 1)]
    out: list[WeeklyRollup] = []
    for ws in weeks_sorted:
        buy_cost = buckets[ws]["buy"]
        sell_rev = buckets[ws]["sell"]
        net = sell_rev - buy_cost
        out.append(
            WeeklyRollup(
                week_start=ws,
                buy_cost_cents=buy_cost,
                sell_revenue_cents=sell_rev,
                net_profit_cents=net,
            )
        )
    return out


def print_weekly_report(db: DB, *, weeks: int = 8) -> None:
    rollups = weekly_rollup(db, weeks=weeks)
    if not rollups:
        print("No inventory transactions recorded yet.")
        return

    print("WeekStart(UTC)\tBuys\tSells\tNet")
    for r in rollups:
        print(
            f"{r.week_start.date().isoformat()}\t{_fmt_money(r.buy_cost_cents)}\t{_fmt_money(r.sell_revenue_cents)}\t{_fmt_money(r.net_profit_cents)}"
        )

