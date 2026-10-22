"""API + scoring tests for Receipts (added after the judge-mode review).

Covers the surfaces the original three tests did not:
- FastAPI: GET /health, POST /run in sample mode (success + unknown
  vendor + malformed input).
- Scoring: caps, tier boundaries, and the contradiction bonus, all
  through the real compute_score / tier_for functions.

These tests change no app logic. The API tests run the real pipeline
in sample mode; the endpoint writes to ./output and ./logs/traces.jsonl
relative to the working directory, so each API test chdirs into a
tmp_path (via monkeypatch) to stay hermetic. Verification runs use a
/tmp copy of the repo for the same reason.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.writer import compute_score, tier_for
from app.main import app

SAMPLE_VENDORS = (
    "Helios Semiconductor",
    "Northwind Supply Co.",
    "Bluepeak Manufacturing",
)


def _client(monkeypatch, tmp_path):
    """TestClient with sample mode forced and cwd isolated to tmp_path."""
    monkeypatch.setenv("SAMPLE_MODE", "true")
    for key in ("METERLESS_RUNTIME_TOKEN", "ZETARIS_API_KEY",
                "ZETARIS_USERNAME", "ZETARIS_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


def _claim(domain, severity, confidence):
    return SimpleNamespace(domain=domain, severity=severity,
                          confidence=confidence)


# ---------------------------------------------------------------- API

def test_health_returns_200(monkeypatch, tmp_path):
    """GET /health returns 200 with status ok."""
    client = _client(monkeypatch, tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "receipts"
    assert body["sample_mode"] is True


def test_api_run_helios_sample_mode(monkeypatch, tmp_path):
    """POST /run Helios in sample mode returns 200 with score 76 HIGH."""
    client = _client(monkeypatch, tmp_path)
    response = client.post("/run", json={
        "vendor_name": "Helios Semiconductor",
        "procurement_context": "Semiconductor component supplier",
        "sample_mode": True,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 76
    assert body["tier"] == "HIGH"
    assert body["vendor_name"] == "Helios Semiconductor"


def test_api_run_unknown_vendor_returns_404_with_vendor_list(
        monkeypatch, tmp_path):
    """Unknown vendor in sample mode returns 404 listing sample vendors."""
    client = _client(monkeypatch, tmp_path)
    response = client.post("/run", json={
        "vendor_name": "Unknown Vendor XYZ",
        "sample_mode": True,
    })
    assert response.status_code == 404
    detail = response.json()["detail"]
    for vendor in SAMPLE_VENDORS:
        assert vendor in detail


def test_api_missing_vendor_field_is_clean_422(monkeypatch, tmp_path):
    """Missing vendor field returns a clean 422, never a stack trace."""
    client = _client(monkeypatch, tmp_path)
    response = client.post("/run", json={})
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert "detail" in response.json()


def test_api_empty_vendor_string_is_clean_404(monkeypatch, tmp_path):
    """Empty vendor string returns a clean 404, never a crash."""
    client = _client(monkeypatch, tmp_path)
    response = client.post("/run", json={
        "vendor_name": "",
        "sample_mode": True,
    })
    assert response.status_code == 404
    assert "Traceback" not in response.text
    detail = response.json()["detail"]
    for vendor in SAMPLE_VENDORS:
        assert vendor in detail


# ------------------------------------------------------------- Scoring

def test_financial_score_capped_at_35():
    """FINANCIAL contribution above 35 is capped at exactly 35."""
    claims = [_claim("FINANCIAL", 20.0, 1.0)]  # 20 x 2.0 x 1.0 = 40
    result = compute_score(claims, [])
    assert result["financial"] == 35.0


def test_legal_score_capped_at_25():
    """LEGAL contribution above 25 is capped at exactly 25."""
    claims = [_claim("LEGAL", 20.0, 1.0)]  # 20 x 2.0 x 1.0 = 40
    result = compute_score(claims, [])
    assert result["legal"] == 25.0


def test_reputation_score_capped_at_15():
    """REPUTATION contribution above 15 is capped at exactly 15."""
    claims = [_claim("REPUTATION", 20.0, 1.0)]  # 20 x 1.2 x 1.0 = 24
    result = compute_score(claims, [])
    assert result["reputation"] == 15.0


def test_tier_boundaries():
    """Tier edges: 34 LOW, 35 MODERATE, 64 MODERATE, 65 HIGH."""
    assert tier_for(34) == "LOW"
    assert tier_for(35) == "MODERATE"
    assert tier_for(64) == "MODERATE"
    assert tier_for(65) == "HIGH"


def test_compute_score_tier_boundaries():
    """Totals through compute_score land on the right tier edges."""
    low = compute_score([_claim("FINANCIAL", 17.0, 1.0)], [])  # 34.0
    assert low["total"] == 34
    assert low["tier"] == "LOW"
    moderate = compute_score([_claim("FINANCIAL", 17.5, 1.0)], [])  # 35.0
    assert moderate["total"] == 35
    assert moderate["tier"] == "MODERATE"


def test_contradiction_adds_exactly_25():
    """One CONTRADICTS edge adds exactly 25, nothing more or less."""
    claims = [_claim("FINANCIAL", 5.0, 1.0)]  # 5 x 2.0 x 1.0 = 10
    without = compute_score(claims, [])
    assert without["total"] == 10
    assert without["contradiction"] == 0.0
    with_contra = compute_score(claims, ["dummy-edge"])
    assert with_contra["contradiction"] == 25.0
    assert with_contra["total"] == 35
    assert with_contra["total"] - without["total"] == 25
