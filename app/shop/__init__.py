"""Feature-toggle shop: the A9 storefront plus sign-in, two toggled experiments and their metrics."""
import os
import secrets
import time
from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import admin, auth, db, views

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' https://avatars.githubusercontent.com; "
                               "frame-ancestors 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def _secret_key(instance_path: str) -> str:
    """Every worker process must sign sessions with the same key.
    Deployed: SECRET_KEY from the platform's secret store, and refuse to start without it.
    Local: generate one key once and keep it in instance/ (git-ignored), shared by all workers."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    if os.environ.get("RENDER"):
        raise RuntimeError("SECRET_KEY is not set")
    path = os.path.join(instance_path, "secret_key")
    try:
        with open(path, "x", encoding="ascii") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    for _ in range(50):                      # another worker may be writing it right now
        with open(path, encoding="ascii") as f:
            key = f.read().strip()
        if key:
            return key
        time.sleep(0.05)
    raise RuntimeError(f"could not read {path}")


def _logins(value: str) -> set[str]:
    return {s.strip().lower() for s in value.split(",") if s.strip()}


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    env = os.environ
    app.config.from_mapping(
        # Secrets come only from the environment (Render secret store in production, .env locally).
        SECRET_KEY=_secret_key(app.instance_path),
        DATABASE_URL=env.get("DATABASE_URL") or "sqlite:///" + os.path.join(app.instance_path, "shop.db"),
        GITHUB_CLIENT_ID=env.get("GITHUB_CLIENT_ID", ""),
        GITHUB_CLIENT_SECRET=env.get("GITHUB_CLIENT_SECRET", ""),
        # Public base URL for the OAuth callback. Render sets RENDER_EXTERNAL_URL itself.
        PUBLIC_URL=env.get("PUBLIC_URL") or env.get("RENDER_EXTERNAL_URL") or "http://localhost:8000",
        # Not secret: which GitHub accounts get the admin role (toggle console, metrics).
        ADMIN_LOGINS=_logins(env.get("ADMIN_GITHUB_LOGINS", "")),
        # Local testing without GitHub. Refused below on the deployed service.
        DEV_LOGIN=env.get("DEV_LOGIN") == "1",
        FLAGS_FILE=os.path.join(os.path.dirname(__file__), "flags.json"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",  # Lax, not Strict: the OAuth callback is a cross-site redirect
        SESSION_COOKIE_SECURE=env.get("SESSION_COOKIE_SECURE", "1") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)
    if app.config["DEV_LOGIN"] and env.get("RENDER"):
        raise RuntimeError("DEV_LOGIN must never be enabled on the deployed service")

    # Render terminates TLS at its proxy; trust exactly one hop for client IP and scheme.
    # X-Forwarded-Host is not trusted: no URL is ever built from the request's host.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    db.init_app(app)
    auth.init_app(app)
    app.register_blueprint(views.bp)
    app.register_blueprint(admin.bp)

    @app.after_request
    def add_security_headers(resp):
        resp.headers.update(SECURITY_HEADERS)
        return resp

    return app
