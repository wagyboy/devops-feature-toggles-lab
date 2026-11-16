"""Admin console: change a flag at runtime (rollout, kill switch), read the experiment metrics."""
import csv
import io

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import delete, insert, select

from .auth import check_csrf, role_required
from .db import engine, events, flag_audit, flag_overrides
from .flags import all_flags, bucket
from .metrics import daily_counts, summary

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/")
@role_required("admin")
def console():
    with engine().connect() as conn:
        audit = conn.execute(select(flag_audit).order_by(flag_audit.c.id.desc()).limit(15)).mappings().all()
    return render_template("admin.html", flags=all_flags(), audit=audit, my_buckets={
        name: bucket(name, g.user["id"]) for name in all_flags()})


@bp.post("/flags/<name>")
@role_required("admin")
def set_flag(name):
    check_csrf()
    flags = all_flags()
    if name not in flags:
        abort(404)
    old = flags[name]
    actor = g.user["login"]
    with engine().begin() as conn:
        if request.form.get("action") == "reset":
            conn.execute(delete(flag_overrides).where(flag_overrides.c.flag == name))
            change = "reset to flags.json defaults"
        else:
            enabled = request.form.get("enabled") == "on"
            try:
                rollout = max(0, min(100, int(request.form.get("rollout", old.rollout))))
            except ValueError:
                abort(400, "rollout must be a number from 0 to 100")
            conn.execute(delete(flag_overrides).where(flag_overrides.c.flag == name))
            conn.execute(insert(flag_overrides).values(flag=name, enabled=enabled, rollout=rollout, updated_by=actor))
            change = f"enabled {old.enabled}->{enabled}, rollout {old.rollout}->{rollout}"
        conn.execute(insert(flag_audit).values(actor=actor, flag=name, change=change))
    flash(f"{name}: {change}")
    return redirect(url_for("admin.console"))


@bp.get("/metrics")
@role_required("admin")
def metrics():
    return render_template("metrics.html", s=summary(), days=daily_counts())


@bp.get("/events.csv")
@role_required("admin")
def events_csv():
    # pseudonymous export: internal user ids, no GitHub logins
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["ts", "user_id", "visit_id", "event", "sku", "low_stock", "source", "quick_buy", "stock_badge"]
    w.writerow(cols)
    with engine().connect() as conn:
        for r in conn.execute(select(*[events.c[c] for c in cols]).order_by(events.c.id)):
            w.writerow(r)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=events.csv"})
