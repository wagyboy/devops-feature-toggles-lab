"""Functional, toggle-state and security tests through HTTP."""
from conftest import csrf_from, set_flag, sign_in
from sqlalchemy import func, select

from shop.db import events, flag_audit

# ---------- A&A ----------


def test_pages_require_sign_in(client):
    for path in ("/", "/p/SKU-100", "/search?q=a", "/admin/", "/admin/metrics"):
        r = client.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"], path


def test_health_is_public(client):
    assert client.get("/health").json == {"status": "ok"}


def test_customer_cannot_open_admin(client):
    sign_in(client, "alice")
    assert client.get("/admin/").status_code == 403
    assert client.get("/admin/events.csv").status_code == 403
    assert client.get("/admin/summary.csv").status_code == 403
    page = client.get("/").get_data(as_text=True)
    assert client.post("/admin/flags/quick_buy", data={"csrf": csrf_from(page), "rollout": "100"}).status_code == 403


def test_admin_role_from_config(client):
    sign_in(client, "boss")
    assert client.get("/admin/").status_code == 200


def test_dev_login_disabled_returns_404(app, client):
    app.config["DEV_LOGIN"] = False
    page = client.get("/login").get_data(as_text=True)
    assert "Dev sign-in" not in page
    assert client.post("/dev-login", data={"login": "x"}).status_code == 404


def test_open_redirect_is_blocked(client):
    client.get("/login?next=//evil.example/x")
    page = client.get("/login?next=//evil.example/x").get_data(as_text=True)
    r = client.post("/dev-login", data={"login": "alice", "csrf": csrf_from(page)})
    assert r.headers["Location"] == "/"


def test_oauth_callback_ignores_forged_host(tmp_path):
    from shop import create_app
    app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{tmp_path / 'o.db'}", "SECRET_KEY": "t",
                      "GITHUB_CLIENT_ID": "test-client", "PUBLIC_URL": "https://shop.example"})
    r = app.test_client().get("/login/github", headers={"Host": "evil.example"})
    loc = r.headers["Location"]
    assert loc.startswith("https://github.com/login/oauth/authorize")
    assert "redirect_uri=https%3A%2F%2Fshop.example%2Fauth%2Fcallback" in loc
    assert "evil.example" not in loc and "state=" in loc


def test_post_without_csrf_is_rejected(app, client):
    set_flag(app, "quick_buy", rollout=100)
    sign_in(client, "alice")
    assert client.post("/buy/SKU-100", data={"source": "product"}).status_code == 400
    assert client.post("/logout").status_code == 400


# ---------- quick_buy: on and off ----------


def test_quick_buy_on_shows_button_and_buys_from_list(app, client):
    set_flag(app, "quick_buy", rollout=100)
    sign_in(client, "alice")
    page = client.get("/").get_data(as_text=True)
    assert "Buy now" in page
    r = client.post("/buy/SKU-100", data={"csrf": csrf_from(page), "source": "list"}, follow_redirects=True)
    assert r.status_code == 200 and "Order placed" in r.get_data(as_text=True)


def test_quick_buy_off_hides_button_and_refuses_crafted_post(app, client):
    set_flag(app, "quick_buy", rollout=0)
    sign_in(client, "alice")
    page = client.get("/").get_data(as_text=True)
    assert "Buy now" not in page
    # server-side boundary: the hidden feature cannot be reached by posting the form by hand
    assert client.post("/buy/SKU-100", data={"csrf": csrf_from(page), "source": "list"}).status_code == 403
    # the normal path through the product page still works (regression)
    r = client.post("/buy/SKU-100", data={"csrf": csrf_from(page), "source": "product"})
    assert r.status_code == 302


# ---------- stock_badge: on and off ----------


def test_stock_badge_on_and_off(app, client):
    sign_in(client, "alice")
    set_flag(app, "stock_badge", rollout=100)
    on = client.get("/").get_data(as_text=True)
    assert "Only 2 left" in on and "Only 30 left" not in on   # only items at or under the threshold
    set_flag(app, "stock_badge", rollout=0)
    assert "left</span>" not in client.get("/").get_data(as_text=True)


# ---------- runtime switching, audit, metrics ----------


def test_admin_switch_takes_effect_on_next_request_and_is_audited(app, client):
    set_flag(app, "quick_buy", rollout=0)
    sign_in(client, "boss")
    page = client.get("/admin/").get_data(as_text=True)
    assert "Buy now" not in client.get("/").get_data(as_text=True)
    client.post("/admin/flags/quick_buy", data={"csrf": csrf_from(page), "enabled": "on", "rollout": "100"})
    assert "Buy now" in client.get("/").get_data(as_text=True)
    client.post("/admin/flags/quick_buy", data={"csrf": csrf_from(page), "rollout": "100"})   # unchecked = killed
    assert "Buy now" not in client.get("/").get_data(as_text=True)
    with app.extensions["engine"].connect() as conn:
        assert conn.execute(select(func.count()).select_from(flag_audit)).scalar_one() == 2


def test_admin_console_shows_killed_flag_as_off(app, client):
    # issue #4: with the kill switch off and rollout 100 the console said "on by bucket"
    set_flag(app, "quick_buy", enabled=False, rollout=100)
    sign_in(client, "boss")
    page = client.get("/admin/").get_data(as_text=True)
    assert "<strong>off</strong> <span class=\"muted\">(killed)</span>" in page
    assert "Buy now" not in client.get("/").get_data(as_text=True)
    set_flag(app, "quick_buy", enabled=True, rollout=100)
    page = client.get("/admin/").get_data(as_text=True)
    assert "<strong>on</strong>" in page and "(killed)" not in page


def test_events_record_both_variants(app, client):
    set_flag(app, "quick_buy", rollout=100)
    set_flag(app, "stock_badge", rollout=0)
    sign_in(client, "alice")
    client.get("/")
    client.get("/p/SKU-800?src=list")
    with app.extensions["engine"].connect() as conn:
        rows = conn.execute(select(events)).mappings().all()
    kinds = [r["event"] for r in rows]
    # sign-in redirects to "/", so two list views; each shows the 4 low-stock items
    assert kinds.count("list_view") == 2 and kinds.count("impression") == 8 and "click" in kinds
    assert all(r["quick_buy"] is True and r["stock_badge"] is False for r in rows)


def test_metrics_exclude_admins(app, client):
    sign_in(client, "boss")
    client.get("/")
    page = client.get("/admin/metrics").get_data(as_text=True)
    assert "0 events from non-admin users" in page
    assert "95% interval" in page and "Not enough data" in page


def test_summary_csv_matches_metrics_and_excludes_admins(app, client):
    set_flag(app, "quick_buy", rollout=100)
    set_flag(app, "stock_badge", rollout=0)
    sign_in(client, "alice")          # one visit: a list view with the 4 low-stock items
    admin = app.test_client()
    sign_in(admin, "boss")            # the admin's own list view must not be counted
    resp = admin.get("/admin/summary.csv")
    assert resp.status_code == 200 and resp.mimetype == "text/csv"
    lines = resp.get_data(as_text=True).splitlines()
    assert lines[0] == "hypothesis,flag,variant,users,metric,denominator,successes,rate_pct,ci_low_pct,ci_high_pct"
    assert lines[1] == "H1,quick_buy,on,1,visit conversion,1,0,0.0,0.0,79.3"
    assert lines[2] == "H1,quick_buy,off,0,visit conversion,0,0,,,"
    assert lines[3] == "H2,stock_badge,on,0,low-stock click-through,0,0,,,"
    assert lines[4] == "H2,stock_badge,off,1,low-stock click-through,4,0,0.0,0.0,49.0"
    assert len(lines) == 5


def test_summary_csv_with_data_in_both_variants(app, client):
    # alice: quick_buy on, stock_badge off; she only views the list
    set_flag(app, "quick_buy", rollout=100)
    set_flag(app, "stock_badge", rollout=0)
    sign_in(client, "alice")
    # bob: the opposite variants; he clicks a low-stock item and buys it from the product page
    set_flag(app, "quick_buy", rollout=0)
    set_flag(app, "stock_badge", rollout=100)
    bob = app.test_client()
    sign_in(bob, "bob")
    page = bob.get("/p/SKU-800?src=list").get_data(as_text=True)
    assert bob.post("/buy/SKU-800", data={"csrf": csrf_from(page), "source": "product"}).status_code == 302
    admin = app.test_client()
    sign_in(admin, "boss")
    lines = admin.get("/admin/summary.csv").get_data(as_text=True).splitlines()
    assert lines[1] == "H1,quick_buy,on,1,visit conversion,1,0,0.0,0.0,79.3"
    assert lines[2] == "H1,quick_buy,off,1,visit conversion,1,1,100.0,20.7,100.0"
    assert lines[3] == "H2,stock_badge,on,1,low-stock click-through,4,1,25.0,4.6,69.9"
    assert lines[4] == "H2,stock_badge,off,1,low-stock click-through,4,0,0.0,0.0,49.0"


def test_search_escapes_input(client):
    sign_in(client, "alice")
    page = client.get("/search?q=<script>alert(1)</script>").get_data(as_text=True)
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


def test_security_headers(client):
    r = client.get("/health")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"


def test_second_worker_survives_the_create_table_race(tmp_path, monkeypatch):
    # Two gunicorn workers on an empty database: the other one creates the tables first, so this
    # worker's CREATE TABLE fails. It must retry and boot, not crash and take the service down.
    from sqlalchemy.exc import OperationalError

    from shop import create_app, db
    real, calls = db.metadata.create_all, []

    def lose_the_race_once(engine):
        calls.append(1)
        real(engine)
        if len(calls) == 1:
            raise OperationalError("CREATE TABLE products", {}, Exception("table products already exists"))

    monkeypatch.setattr(db.metadata, "create_all", lose_the_race_once)
    app = create_app({"DATABASE_URL": f"sqlite:///{tmp_path / 'race.db'}", "SECRET_KEY": "test-only"})
    assert len(calls) == 2
    with app.extensions["engine"].connect() as conn:
        assert conn.execute(select(func.count()).select_from(db.products)).scalar_one() == 8
