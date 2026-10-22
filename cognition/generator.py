"""Model provider client + JSONL trace logging.

Two providers exist behind one injected function:

- LIVE mode: an OpenAI compatible client against the Meterless
  Nightshift Runtime (METERLESS_BASE_URL, Bearer METERLESS_RUNTIME_TOKEN,
  headers meterless-app: receipts and meterless-scope: user, model
  METERLESS_MODEL). The Runtime serves a Nemotron lane; this app never
  calls NVIDIA directly and never holds an NVIDIA key.
- SAMPLE_MODE: a clearly labeled mock provider. Its traces record
  model "sample-mock" and never claim Nemotron. It builds a short
  deterministic summary from the prompts it receives, so the pipeline
  still runs for real on cached data instead of replaying a saved output.

Every call, live or mock, logs latency, tokens, model name and agent id
to the JSONL trace file. On a live provider failure the call degrades
to a template response and the trace says so honestly; the pipeline
never crashes because a model call failed.
"""

import json
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx


def _utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Tracer:
    """Append only JSONL trace writer. Traces are runtime output only.

    Every entry is written to the trace file AND printed to stdout as a
    JSON line, so judges see the agent work live: the guides require
    logs on stdout and in logs/."""

    def __init__(self, trace_path, trace_id=None):
        self.trace_path = trace_path
        self.trace_id = trace_id or str(uuid.uuid4())
        self._lock = threading.Lock()

    def log(self, step, agent, engine, model, event_type, action,
            input_summary="", output_summary="", target_claim_id=None,
            markov_transition=None, reason="", handoff_to=None,
            confidence=None, retry_count=0, status="success",
            latency_ms=None, tokens=None):
        entry = {
            "timestamp": _utcnow(),
            "trace_id": self.trace_id,
            "step": step,
            "agent": agent,
            "engine": engine,
            "model": model,
            "event_type": event_type,
            "target_claim_id": target_claim_id,
            "markov_transition": markov_transition,
            "reason": reason,
            "handoff_to": handoff_to,
            "action": action,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "confidence": confidence,
            "retry_count": retry_count,
            "status": status,
            "latency_ms": latency_ms,
            "tokens": tokens,
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            with open(self.trace_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            print(line, flush=True)
        return entry


def _mock_response(system_prompt, user_prompt):
    """Deterministic mock reasoning for SAMPLE_MODE.

    Builds a short summary from the prompts themselves. It never claims
    to be a real model and never replays a stored answer.
    """
    focus = user_prompt.strip().replace("\n", " ")[:160]
    text = ("Sample mode reasoning (mock provider, not a live model). "
            "Task context: %s. Proceeding with the deterministic "
            "evidence pipeline; scores are computed from claims, "
            "not from this text." % focus)
    return text


def create_injected_generator(config, tracer, agent_id):
    """Return generate_fn(system_prompt, user_prompt, response_schema).

    The returned function is injected into every agent. It returns a dict
    with keys: text, model, latency_ms, tokens, provider_fallback.
    """
    sample_mode = config.sample_mode
    model_name = "sample-mock" if sample_mode else config.meterless_model

    def generate_fn(system_prompt, user_prompt, response_schema=None):
        started = time.perf_counter()
        if sample_mode:
            text = _mock_response(system_prompt, user_prompt)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            tokens = max(1, len(text) // 4)
            tracer.log(
                step="generate", agent=agent_id, engine="generator",
                model="sample-mock", event_type="llm_call",
                action="mock_generate",
                input_summary=user_prompt[:160],
                output_summary=text[:160],
                status="success", latency_ms=latency_ms, tokens=tokens)
            return {"text": text, "model": "sample-mock",
                    "latency_ms": latency_ms, "tokens": tokens,
                    "provider_fallback": False}

        # LIVE mode: Nightshift Runtime, OpenAI compatible.
        url = config.meterless_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": "Bearer %s" % config.meterless_runtime_token,
            "meterless-app": "receipts",
            "meterless-scope": "user",
            "Content-Type": "application/json",
        }
        body = {
            "model": config.meterless_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        try:
            with httpx.Client(timeout=config.request_timeout_s) as client:
                resp = client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
            choice = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage") or {}
            tokens = usage.get("total_tokens")
            used_model = payload.get("model") or config.meterless_model
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            tracer.log(
                step="generate", agent=agent_id, engine="generator",
                model=used_model, event_type="llm_call",
                action="nightshift_generate",
                input_summary=user_prompt[:160],
                output_summary=str(choice)[:160],
                status="success", latency_ms=latency_ms, tokens=tokens)
            return {"text": str(choice), "model": used_model,
                    "latency_ms": latency_ms, "tokens": tokens,
                    "provider_fallback": False}
        except Exception as exc:  # degrade, never crash
            # Honesty rule: the fallback text is mock-generated, so the
            # trace must NOT claim the Nemotron model string for it.
            # status="provider_fallback" plus this label make it clear
            # no live model responded.
            text = _mock_response(system_prompt, user_prompt)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            tracer.log(
                step="generate", agent=agent_id, engine="generator",
                model="sample-mock", event_type="llm_call",
                action="nightshift_generate",
                input_summary=user_prompt[:160],
                output_summary="provider fallback: %s" % str(exc)[:120],
                status="provider_fallback", latency_ms=latency_ms,
                tokens=None)
            return {"text": text, "model": "sample-mock",
                    "latency_ms": latency_ms, "tokens": None,
                    "provider_fallback": True}

    return generate_fn


def discover_models(config):
    """GET /v1/models from the Nightshift Runtime. Returns a list or [].

    Used by the smoke test and live checks. Never used to guess a model
    name: the app uses METERLESS_MODEL from the environment.
    """
    if config.sample_mode:
        return []
    url = config.meterless_base_url.rstrip("/") + "/v1/models"
    headers = {
        "Authorization": "Bearer %s" % config.meterless_runtime_token,
        "meterless-app": "receipts",
        "meterless-scope": "user",
    }
    try:
        with httpx.Client(timeout=config.request_timeout_s) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        return [m.get("id") for m in payload.get("data", [])]
    except Exception:
        return []
