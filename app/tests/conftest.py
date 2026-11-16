import re

import pytest
from sqlalchemy import delete, insert

from shop import create_app
from shop.db import flag_overrides


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
        "SECRET_KEY": "test-only",
        "DEV_LOGIN": True,
        "SESSION_COOKIE_SECURE": False,   # the test client talks plain http
        "ADMIN_LOGINS": {"boss"},
    })
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_from(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def sign_in(client, login: str):
    page = client.get("/login").get_data(as_text=True)
    return client.post("/dev-login", data={"login": login, "csrf": csrf_from(page)}, follow_redirects=True)


def set_flag(app, name: str, enabled: bool = True, rollout: int = 100):
    """Pin a flag for the test, the same way the admin console stores an override."""
    with app.extensions["engine"].begin() as conn:
        conn.execute(delete(flag_overrides).where(flag_overrides.c.flag == name))
        conn.execute(insert(flag_overrides).values(flag=name, enabled=enabled, rollout=rollout, updated_by="test"))
