"""Event tracking and the per-variant numbers behind the two hypotheses."""
import math
from collections import defaultdict

from flask import g, session
from sqlalchemy import insert, select

from .db import engine, events, users
from .flags import variants


def track(event: str, sku: str | None = None, low_stock: bool | None = None, source: str | None = None) -> None:
    if g.user is None:
        return
    v = variants(g.user)
    with engine().begin() as conn:
        conn.execute(insert(events).values(user_id=g.user["id"], visit_id=session.get("visit", "-"), event=event,
                                           sku=sku, low_stock=low_stock, source=source,
                                           quick_buy=v["quick_buy"], stock_badge=v["stock_badge"]))


def track_many(rows: list[dict]) -> None:
    if g.user is None or not rows:
        return
    v = variants(g.user)
    base = {"user_id": g.user["id"], "visit_id": session.get("visit", "-"), "source": None,
            "quick_buy": v["quick_buy"], "stock_badge": v["stock_badge"]}
    with engine().begin() as conn:
        conn.execute(insert(events), [{**base, **r} for r in rows])


def _rate(num: int, den: int) -> float | None:
    return round(100 * num / den, 1) if den else None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for k successes out of n, in percent.
    With a handful of testers a single rate looks precise but is not; the interval shows how wide
    the plausible range is, and overlapping intervals mean the data cannot tell the variants apart.
    Wilson (not the normal approximation) stays inside 0-100% and behaves at k = 0 or k = n."""
    if not n:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)


def overlap(a: tuple[float, float] | None, b: tuple[float, float] | None) -> bool | None:
    if a is None or b is None:
        return None
    return a[0] <= b[1] and b[0] <= a[1]


def summary() -> dict:
    """Aggregate in Python: the experiment is small, and this keeps SQLite and PostgreSQL identical.
    Admin accounts (the team) are excluded so our own testing does not count as user behaviour."""
    with engine().connect() as conn:
        admins = {r.id for r in conn.execute(select(users.c.id).where(users.c.role == "admin"))}
        rows = [r for r in conn.execute(select(events)).mappings() if r["user_id"] not in admins]

    h1 = {v: {"users": set(), "visits": set(), "buy_visits": set(), "purchases": 0, "from_list": 0}
          for v in (True, False)}
    h2 = {v: {"users": set(), "impressions": 0, "clicks": 0, "low_purchases": 0} for v in (True, False)}
    for r in rows:
        a, b = h1[r["quick_buy"]], h2[r["stock_badge"]]
        a["users"].add(r["user_id"])
        b["users"].add(r["user_id"])
        if r["event"] == "list_view":
            a["visits"].add(r["visit_id"])
        elif r["event"] == "purchase":
            a["buy_visits"].add(r["visit_id"])
            a["purchases"] += 1
            a["from_list"] += r["source"] == "list"
            b["low_purchases"] += bool(r["low_stock"])
        elif r["event"] == "impression" and r["low_stock"]:
            b["impressions"] += 1
        elif r["event"] == "click" and r["low_stock"]:
            b["clicks"] += 1

    out = {"events": len(rows), "h1": {}, "h2": {}}
    for v in (True, False):
        a, b = h1[v], h2[v]
        visits = len(a["visits"])
        buy_visits = len(a["buy_visits"] & a["visits"])
        out["h1"][v] = {"users": len(a["users"]), "visits": visits, "buy_visits": buy_visits,
                        "conversion": _rate(buy_visits, visits), "ci": wilson(buy_visits, visits),
                        "purchases": a["purchases"], "from_list": a["from_list"]}
        out["h2"][v] = {"users": len(b["users"]), "impressions": b["impressions"], "clicks": b["clicks"],
                        "ctr": _rate(b["clicks"], b["impressions"]), "ci": wilson(b["clicks"], b["impressions"]),
                        "low_purchases": b["low_purchases"]}
    out["h1_overlap"] = overlap(out["h1"][True]["ci"], out["h1"][False]["ci"])
    out["h2_overlap"] = overlap(out["h2"][True]["ci"], out["h2"][False]["ci"])
    return out


def daily_counts() -> list[tuple[str, int, int]]:
    """(day, events, distinct users) for the activity table."""
    per_day = defaultdict(lambda: [0, set()])
    with engine().connect() as conn:
        for r in conn.execute(select(events.c.ts, events.c.user_id)):
            d = per_day[r.ts.strftime("%Y-%m-%d")]
            d[0] += 1
            d[1].add(r.user_id)
    return [(day, n, len(u)) for day, (n, u) in sorted(per_day.items())]
