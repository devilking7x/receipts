"""Receipts entry point: CLI investigation runner and API server.

CLI examples:
    python run.py --vendor "Helios Semiconductor" --sample-mode
    python run.py --vendor "Helios Semiconductor" --context "Chip supply"
    python run.py --serve            # FastAPI on port 8000

Modes:
- Sample mode (default, SAMPLE_MODE=true): zero credentials, the full
  pipeline runs on cached fixture data. Fixture vendors are Helios
  Semiconductor, Northwind Supply Co. and Bluepeak Manufacturing.
- Live mode (--live): Nightshift Runtime plus Zetaris. Requires a
  real .env with METERLESS_RUNTIME_TOKEN and ZETARIS credentials.
  Zetaris is load-bearing: if it is unavailable, the run fails with
  a clear message instead of inventing financial data.
"""

import argparse
import sys

from agents.pipeline import VendorNotFoundError, orchestrate
from config import load_config
from data_layer.zetaris_client import ZetarisDataLayerUnavailableError


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Receipts: AI procurement due-diligence investigator")
    parser.add_argument("--vendor", default="",
                        help="Vendor / supplier name to investigate")
    parser.add_argument("--context", default="",
                        help="Procurement context, e.g. contract size")
    parser.add_argument("--sample-mode", dest="sample_mode",
                        action="store_true", default=None,
                        help="Run on cached fixture data (default)")
    parser.add_argument("--live", dest="sample_mode", action="store_false",
                        help="Run against live Nightshift + Zetaris")
    parser.add_argument("--serve", action="store_true",
                        help="Start the FastAPI server on port 8000")
    parser.add_argument("--out-dir", default="output",
                        help="Directory for report.md and report.json")
    args = parser.parse_args(argv)

    if args.serve:
        import uvicorn
        print("Starting Receipts API on http://0.0.0.0:8000 ...")
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
        return 0

    if not args.vendor:
        parser.print_help()
        return 2

    overrides = {}
    if args.sample_mode is not None:
        overrides["sample_mode"] = args.sample_mode
    config = load_config(overrides)
    print("Investigating vendor: %s" % args.vendor)
    print("Mode: %s" % ("SAMPLE_MODE (cached fixtures)"
                         if config.sample_mode else "LIVE"))
    try:
        result = orchestrate(args.vendor, args.context, config,
                             args.out_dir, "logs/traces.jsonl")
    except VendorNotFoundError as exc:
        print("ERROR: %s" % exc)
        return 1
    except ZetarisDataLayerUnavailableError as exc:
        print("ERROR (Zetaris load-bearing failure): %s" % exc)
        return 1
    print("")
    print("Risk score: %d/100 (%s)" % (result.score, result.tier))
    print("Report (markdown): %s" % result.report_md_path)
    print("Report (JSON): %s" % result.report_json_path)
    print("Traces: %s" % result.trace_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
