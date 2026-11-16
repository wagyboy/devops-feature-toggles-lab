"""Authentication (GitHub OAuth 2.0) and authorization (two roles: customer, admin)."""
import hmac
import secrets
import time
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, Flask, abort, current_app, g, redirect, render_template, request, session, url_for
from sqlalchemy import insert, select, update

from .db import engine, users

bp = Blueprint("auth", __name__)
VISIT_GAP_SECONDS = 30 * 60  # a new "visit" starts after 30 minutes without a request


def init_app(app: Flask) -> None:
    # one OAuth registry per app instance, so tests (and any second app) never share a client
    app.extensions["github"] = OAuth(app).register(
        "github",
        client_id=app.config["GITHUB_CLIENT_ID"],
        client_secret=app.config["GITHUB_CLIENT_SECRET"],
        # S106 false positive: the keyword contains "token", but the value is GitHub's public endpoint
        access_token_url="https://github.com/login/oauth/access_token",  # noqa: S106
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": ""},  # no scope: only the public profile, the least privilege that works
    )
    app.register_blueprint(bp)
    app.before_request(load_user)
    app.jinja_env.globals["csrf_token"] = csrf_token


def _github():
    return current_app.extensions["github"]


# ---------- CSRF: one random token per session, required on every state-changing POST ----------

def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf() -> None:
    sent = request.form.get("csrf", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, "missing or invalid CSRF token")


# ---------- who is signed in ----------

def load_user() -> None:
    g.user = None
    uid = session.get("uid")
    if uid is None:
        return
    with engine().connect() as conn:
        g.user = conn.execute(select(users).where(users.c.id == uid)).mappings().first()
    if g.user is None:          # account removed: drop the stale session
        session.clear()
        return
    now = time.time()
    if now - session.get("last_seen", 0) > VISIT_GAP_SECONDS:
        session["visit"] = secrets.token_hex(8)
    session["last_seen"] = now


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(role: str):
    """RBAC check on the server. Hiding a link in the template is UX, this is the security boundary."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _sign_in(provider: str, provider_id: str, login: str, avatar: str | None) -> None:
    role = "admin" if login.lower() in current_app.config["ADMIN_LOGINS"] else "customer"
    with engine().begin() as conn:
        row = conn.execute(select(users.c.id).where(users.c.provider == provider,
                                                    users.c.provider_id == provider_id)).first()
        if row:
            uid = row.id
            # role is re-derived at every sign-in, so removing someone from ADMIN_GITHUB_LOGINS revokes it
            conn.execute(update(users).where(users.c.id == uid).values(login=login, avatar=avatar, role=role))
        else:
            uid = conn.execute(insert(users).values(provider=provider, provider_id=provider_id, login=login,
                                                    avatar=avatar, role=role)).inserted_primary_key[0]
    nxt = session.get("next")
    session.clear()             # new session on sign-in: no session fixation
    session.permanent = True
    session["uid"] = uid
    session["next"] = nxt


def _safe_next(target: str | None) -> str:
    # only local paths, so the sign-in flow cannot be used as an open redirect
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("shop.index")


# ---------- routes ----------

@bp.get("/login")
def login():
    session["next"] = _safe_next(request.args.get("next"))
    return render_template("login.html", github=bool(current_app.config["GITHUB_CLIENT_ID"]),
                           dev_login=current_app.config["DEV_LOGIN"])


@bp.get("/login/github")
def login_github():
    if not current_app.config["GITHUB_CLIENT_ID"]:
        abort(404)
    # The callback URL is built from configuration, not from the request's Host header
    # (Semgrep flask-url-for-external-true: a forged Host must not steer where GitHub sends the code).
    # Authlib adds a random `state` and checks it on return (CSRF protection for the OAuth flow).
    callback_url = current_app.config["PUBLIC_URL"].rstrip("/") + url_for("auth.callback")
    return _github().authorize_redirect(callback_url)


@bp.get("/auth/callback")
def callback():
    _github().authorize_access_token()
    profile = _github().get("user").json()
    _sign_in("github", str(profile["id"]), profile["login"], profile.get("avatar_url"))
    return redirect(_safe_next(session.pop("next", None)))


@bp.post("/dev-login")
def dev_login():
    if not current_app.config["DEV_LOGIN"]:
        abort(404)
    check_csrf()
    login_name = request.form.get("login", "").strip()[:40]
    if not login_name.replace("-", "").isalnum():
        abort(400, "login must be letters, digits or '-'")
    _sign_in("dev", login_name.lower(), login_name, None)
    return redirect(_safe_next(session.pop("next", None)))


@bp.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("auth.login"))
