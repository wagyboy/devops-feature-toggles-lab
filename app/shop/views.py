"""Shop pages. The two experiments change what is rendered; the server enforces what is allowed."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select, text

from .auth import check_csrf, login_required
from .db import engine, products
from .flags import all_flags, is_on
from .metrics import track, track_many

bp = Blueprint("shop", __name__)


def _threshold() -> int:
    return int(all_flags()["stock_badge"].params.get("low_stock_threshold", 5))


def _product(sku: str):
    with engine().connect() as conn:
        row = conn.execute(select(products).where(products.c.sku == sku)).mappings().first()
    if row is None:
        abort(404)
    return row


@bp.get("/")
@login_required
def index():
    with engine().connect() as conn:
        rows = conn.execute(select(products).order_by(products.c.sku)).mappings().all()
    limit = _threshold()
    track("list_view")
    # impressions of low-stock items are the denominator of H2's click-through rate
    track_many([{"event": "impression", "sku": p["sku"], "low_stock": True} for p in rows if p["stock"] <= limit])
    return render_template("index.html", products=rows, low_limit=limit,
                           quick_buy=is_on("quick_buy", g.user), stock_badge=is_on("stock_badge", g.user))


@bp.get("/p/<sku>")
@login_required
def product(sku):
    p = _product(sku)
    low = p["stock"] <= _threshold()
    if request.args.get("src") == "list":
        track("click", sku=sku, low_stock=low)
    track("product_view", sku=sku, low_stock=low)
    return render_template("product.html", p=p, low=low, stock_badge=is_on("stock_badge", g.user))


@bp.post("/buy/<sku>")
@login_required
def buy(sku):
    check_csrf()
    p = _product(sku)
    source = "list" if request.form.get("source") == "list" else "product"
    # Access boundary of the quick_buy experiment: buying straight from the list is only allowed
    # for users in the "on" group. A crafted POST from the "off" group is refused, not just hidden.
    if source == "list" and not is_on("quick_buy", g.user):
        abort(403)
    track("purchase", sku=sku, low_stock=p["stock"] <= _threshold(), source=source)
    flash(f"Order placed: {p['name']} (${p['price']}). This is a demo shop, nothing is charged.")
    return redirect(url_for("shop.thanks", sku=sku))


@bp.get("/thanks/<sku>")
@login_required
def thanks(sku):
    return render_template("thanks.html", p=_product(sku))


@bp.get("/search")
@login_required
def search():
    q = request.args.get("q", "")[:100]
    with engine().connect() as conn:
        # bound parameter: the input is data, never SQL
        rows = conn.execute(select(products).where(products.c.name.ilike(f"%{q}%"))).mappings().all()
    # Jinja2 autoescaping turns <script> into &lt;script&gt;
    return render_template("search.html", q=q, products=rows)


@bp.get("/health")
def health():
    with engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
