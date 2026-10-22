"""Receipts configuration.

Loads settings from environment variables (and an optional local .env file
via python-dotenv). No secret values live here; only names and defaults.

Key rules honored by this module:
- SAMPLE_MODE defaults to true, so a fresh clone with no credentials still
  runs the full pipeline on cached fixture data.
- When running inside Docker, 127.0.0.1 / localhost service URLs resolve to
  host.docker.internal, because inside a container localhost is the
  container itself, not the developer machine.
- The NVIDIA API key is NEVER read here. It lives only inside the
  Nightshift desktop app (Providers tab). This app talks to Nightshift's
  local Runtime endpoint with the Runtime token, never to NVIDIA directly.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# The default model string used in docs and traces. This is the exact
# Nemotron lane model string confirmed from the Nightshift model picker.
# NOTE: the value "meterless/auto" is deliberately NEVER used by this app:
# it may route to a non NVIDIA model, which would break the requirement
# that NVIDIA award relevant work visibly uses Nemotron.
DEFAULT_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _resolve_docker_host(url):
    """Rewrite loopback service URLs for Docker containers.

    Inside Docker, 127.0.0.1 refers to the container itself. If the
    /.dockerenv marker exists, point loopback hosts at host.docker.internal
    so the app can still reach Nightshift / Zetaris on the host machine.
    """
    if not url:
        return url
    if not os.path.exists("/.dockerenv"):
        return url
    for loopback in ("http://127.0.0.1", "http://localhost",
                     "https://127.0.0.1", "https://localhost"):
        if url.startswith(loopback):
            return url.replace(loopback, "http://host.docker.internal", 1)
    return url


@dataclass
class AppConfig:
    sample_mode: bool = True
    meterless_base_url: str = "http://127.0.0.1:8088/v1"
    meterless_runtime_token: str = ""
    meterless_model: str = DEFAULT_MODEL
    zetaris_rest_url: str = "http://localhost:8888/api/v1.0"
    zetaris_org_id: str = "1"
    zetaris_api_key: str = ""
    zetaris_username: str = ""
    zetaris_password: str = ""
    zetaris_enabled: bool = True
    request_timeout_s: float = 30.0

    def __post_init__(self):
        self.meterless_base_url = _resolve_docker_host(
            self.meterless_base_url.rstrip("/"))
        self.zetaris_rest_url = _resolve_docker_host(
            self.zetaris_rest_url.rstrip("/"))

    @property
    def live_mode(self):
        return not self.sample_mode


def load_config(overrides=None):
    """Build an AppConfig from the environment, plus optional overrides.

    Overrides is a dict of field name to value (used by the API layer when
    a request explicitly asks for sample mode or live mode).
    """
    overrides = overrides or {}
    cfg = AppConfig(
        sample_mode=_as_bool(os.getenv("SAMPLE_MODE"), True),
        meterless_base_url=os.getenv(
            "METERLESS_BASE_URL", "http://127.0.0.1:8088/v1"),
        meterless_runtime_token=os.getenv("METERLESS_RUNTIME_TOKEN", ""),
        meterless_model=os.getenv("METERLESS_MODEL", DEFAULT_MODEL),
        zetaris_rest_url=os.getenv(
            "ZETARIS_REST_URL", "http://localhost:8888/api/v1.0"),
        zetaris_org_id=os.getenv("ZETARIS_ORG_ID", "1"),
        zetaris_api_key=os.getenv("ZETARIS_API_KEY", ""),
        zetaris_username=os.getenv("ZETARIS_USERNAME", ""),
        zetaris_password=os.getenv("ZETARIS_PASSWORD", ""),
        zetaris_enabled=_as_bool(os.getenv("ZETARIS_ENABLED"), True),
        request_timeout_s=float(os.getenv("REQUEST_TIMEOUT_S", "30")),
    )
    for key, value in overrides.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    cfg.__post_init__()
    return cfg
