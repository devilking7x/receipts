"""Web UI tests for Receipts.

The UI is a single self-contained HTML file served by FastAPI — no
CDN, no build step — so these tests only assert that both routes serve
that page and that it wires up to the real POST /run endpoint. The
pipeline itself is covered by the API tests; the UI adds no logic.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ui_root_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Receipts" in response.text
    assert "/run" in response.text  # UI calls the real API, no hardcoded output


def test_ui_alias_serves_same_page():
    response = client.get("/ui")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Investigate vendor" in response.text


def test_ui_has_no_external_resources():
    """No CDN or web fonts: the page must work offline in Docker."""
    response = client.get("/")
    assert "http://fonts." not in response.text
    assert "https://fonts." not in response.text
    assert "cdn.jsdelivr" not in response.text
    assert "unpkg.com" not in response.text
