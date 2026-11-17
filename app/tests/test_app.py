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


def test_search_escapes_input(client):
    sign_in(client, "alice")
    page = client.get("/search?q=<script>alert(1)</script>").get_data(as_text=True)
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


def test_security_headers(client):
    r = client.get("/health")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
