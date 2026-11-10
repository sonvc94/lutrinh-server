"""``GET /`` opens the admin (302 → /admin/)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_redirects_to_admin(anon: TestClient) -> None:
    for r in (anon.get("/", follow_redirects=False), anon.head("/", follow_redirects=False)):
        assert r.status_code == 302
        assert r.headers["location"] == "/admin/"
