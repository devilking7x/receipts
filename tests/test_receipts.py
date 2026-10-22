"""Receipts critical tests: exactly three, each proving a core claim.

1. test_zetaris_load_bearing: in live mode with Zetaris disabled, the
   financial executor must raise ZetarisDataLayerUnavailableError.
   This proves Zetaris is load-bearing, not decorative.
2. test_evaluator_retry: a severe secondary sourced claim is
   challenged, retried against a primary record, and verified, with
   the retry visible in traces.
3. test_sample_mode: SAMPLE_MODE=true runs the whole pipeline with
   zero credentials and never claims a live model.

All tests are hermetic: no network, no live services, no credentials.
"""

import asyncio
import json

import pytest

from agents.executors import FinancialExecutor
from agents.pipeline import orchestrate
from cognition.generator import Tracer
from cognition.world_model import WorldModel
from config import AppConfig, load_config
from data_layer.zetaris_client import (
    ZetarisClient,
    ZetarisDataLayerUnavailableError,
)


def _dummy_generate(system_prompt, user_prompt, response_schema=None):
    return {"text": "test summary", "model": "sample-mock",
            "latency_ms": 0, "tokens": 1, "provider_fallback": False}


def test_zetaris_load_bearing(tmp_path):
    """Live mode + Zetaris disabled -> financial executor fails closed."""
    config = AppConfig(sample_mode=False, zetaris_enabled=False)
    client = ZetarisClient(config)
    executor = FinancialExecutor(client)
    world = WorldModel("Helios Semiconductor")
    tracer = Tracer(str(tmp_path / "traces.jsonl"))
    with pytest.raises(ZetarisDataLayerUnavailableError):
        asyncio.run(executor.run(world, None, "Helios Semiconductor",
                                 _dummy_generate, tracer))


def test_evaluator_retry(tmp_path):
    """Severe secondary claim -> challenged -> retried -> verified."""
    config = AppConfig(sample_mode=True)
    result = orchestrate("Helios Semiconductor", "", config,
                         str(tmp_path / "out"),
                         str(tmp_path / "traces.jsonl"))
    assert result.score == 76
    assert result.tier == "HIGH"
    verified_statements = [c["statement"].lower()
                           for c in result.report["claims"]]
    assert any("counterfeit" in s for s in verified_statements)
    assert result.report["discarded_claims"], \
        "expected at least one discarded claim (the unverified rumor)"
    with open(result.trace_path, encoding="utf-8") as fh:
        traces = [json.loads(line) for line in fh if line.strip()]
    transitions = [t.get("markov_transition") or "" for t in traces]
    assert any("RETRY_IN_PROGRESS" in t for t in transitions)
    assert any(t.get("event_type") == "claim_verified" for t in traces)


def test_sample_mode(monkeypatch, tmp_path):
    """Zero credentials -> full pipeline runs, mock model only."""
    for key in ("METERLESS_RUNTIME_TOKEN", "ZETARIS_API_KEY",
                "ZETARIS_USERNAME", "ZETARIS_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SAMPLE_MODE", "true")
    config = load_config()
    assert config.sample_mode is True
    assert config.meterless_runtime_token == ""
    assert config.zetaris_api_key == ""
    result = orchestrate("Helios Semiconductor", "", config,
                         str(tmp_path / "out"),
                         str(tmp_path / "traces.jsonl"))
    assert result.score == 76
    assert result.tier == "HIGH"
    assert result.report["model"] == "sample-mock"
    with open(result.report_md_path, encoding="utf-8") as fh:
        markdown = fh.read()
    assert "[SYNTHETIC SANDBOX FIXTURE" in markdown
    with open(result.trace_path, encoding="utf-8") as fh:
        traces = [json.loads(line) for line in fh if line.strip()]
    assert traces, "expected runtime traces"
    for entry in traces:
        model = entry.get("model") or ""
        assert "nemotron" not in model.lower(), \
            "sample mode must never claim Nemotron, got %s" % model
        assert model != "meterless/auto"
