"""Data layer: load-bearing Zetaris adapter, secondary search client,
and raw sample fixtures for zero credential runs."""

import json
import os

from data_layer.search_client import SearchClient
from data_layer.zetaris_client import (
    ZetarisClient,
    ZetarisDataLayerUnavailableError,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "sample_fixtures")


def load_sample_fixtures():
    """Load every sample fixture, keyed by lowercased vendor name.

    Fixtures hold RAW records only: financial rows, legal records,
    reputation records and primary records. No fixture contains a
    computed score, tier, or verdict; those are always computed by
    the pipeline from the records at run time.
    """
    fixtures = {}
    if not os.path.isdir(FIXTURE_DIR):
        return fixtures
    for fname in sorted(os.listdir(FIXTURE_DIR)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(FIXTURE_DIR, fname),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        vendor = str(data.get("vendor_name", "")).lower()
        if vendor:
            fixtures[vendor] = data
    return fixtures


__all__ = [
    "SearchClient",
    "ZetarisClient",
    "ZetarisDataLayerUnavailableError",
    "load_sample_fixtures",
]
