"""Smoke test: Nightshift, Zetaris, and the SAMPLE_MODE pipeline.

- Nightshift check: GET /v1/models on the Runtime. SKIPPED when no
  runtime token is configured.
- Zetaris check: SELECT 1 through the REST API. SKIPPED when no
  Zetaris credential is configured.
- Sample check: the full SAMPLE_MODE pipeline for Helios must score
  76/100 HIGH. This is the portable check; it runs anywhere.

Exit code 0 means no check FAILED (SKIP is not failure).
Use --sample-only to run just the portable check.
"""

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from agents.pipeline import orchestrate  # noqa: E402
from config import load_config  # noqa: E402
from data_layer.zetaris_client import ZetarisClient  # noqa: E402
from data_layer.zetaris_client import ZetarisDataLayerUnavailableError  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Receipts smoke test")
    parser.add_argument("--sample-only", action="store_true")
    args = parser.parse_args()
    failed = False

    def report(name, outcome, detail=""):
        nonlocal failed
        print("[%s] %s %s" % (outcome, name, detail))
        if outcome == "FAIL":
            failed = True

    config = load_config()
    if not args.sample_only:
        # Nightshift check.
        if not config.meterless_runtime_token:
            report("Nightshift /v1/models", "SKIP",
                   "(no METERLESS_RUNTIME_TOKEN configured)")
        else:
            from cognition.generator import discover_models
            models = discover_models(config)
            report("Nightshift /v1/models",
                   "PASS" if models else "FAIL",
                   "(%d models)" % len(models))
        # Zetaris check.
        if not (config.zetaris_api_key or config.zetaris_username):
            report("Zetaris SELECT 1", "SKIP",
                   "(no Zetaris credential configured)")
        else:
            live_config = load_config({"sample_mode": False})
            client = ZetarisClient(live_config)
            try:
                rows = client.query("SELECT 1 AS one")
                report("Zetaris SELECT 1", "PASS", "(rows=%s)" % rows)
            except ZetarisDataLayerUnavailableError as exc:
                report("Zetaris SELECT 1", "FAIL", "(%s)" % exc)

    # Sample pipeline check (always runs).
    with tempfile.TemporaryDirectory() as tmp:
        result = orchestrate(
            "Helios Semiconductor", "", load_config({"sample_mode": True}),
            os.path.join(tmp, "out"), os.path.join(tmp, "traces.jsonl"))
        ok = result.score == 76 and result.tier == "HIGH"
        report("SAMPLE_MODE Helios pipeline",
               "PASS" if ok else "FAIL",
               "(%d/100 %s)" % (result.score, result.tier))

    print("")
    print("SMOKE %s" % ("FAILED" if failed else "PASSED"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
