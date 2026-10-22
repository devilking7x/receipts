"""Secondary evidence client: legal records, reputation, primary lookup.

SAMPLE_MODE serves records from the vendor fixture (legal_records,
reputation_records, primary_records). LIVE mode tries the Zetaris
legal tables best effort and degrades to an empty result with a note
when a table is missing. Search is NOT load-bearing: only the
financial executor (Zetaris) fails closed. A missing secondary source
never crashes the pipeline; the Evaluator simply has less to check.

fetch_primary(claim, vendor_name) is the Evaluator retry path: given
a challenged claim, it looks for a primary record matching the claim
(by keyword overlap on the claim statement in sample mode, or by a
docket lookup in live mode). Returns a record dict or None.
"""

import re

from data_layer.zetaris_client import ZetarisDataLayerUnavailableError


def _keywords(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    stop = {"the", "a", "an", "of", "and", "or", "is", "was", "for",
            "to", "in", "on", "by", "with", "faces", "face", "claim",
            "claims", "alleges", "alleged", "reported", "reports"}
    return {w for w in words if len(w) > 2 and w not in stop}


class SearchClient:
    def __init__(self, config, zetaris_client, sample_data_by_vendor=None):
        self.config = config
        self.zetaris_client = zetaris_client
        # In sample mode: {vendor_name_lower: fixture_dict}.
        self.sample_data_by_vendor = sample_data_by_vendor or {}

    def _sample_fixture(self, vendor_name):
        return self.sample_data_by_vendor.get(vendor_name.lower())

    def fetch_legal(self, vendor_name):
        """Return legal / news records for a vendor."""
        if self.config.sample_mode:
            fixture = self._sample_fixture(vendor_name)
            if not fixture:
                return []
            return list(fixture.get("legal_records", []))
        try:
            return self.zetaris_client.query(
                "SELECT * FROM legal_filings WHERE vendor = '%s'"
                % vendor_name.replace("'", "''"))
        except ZetarisDataLayerUnavailableError:
            return []

    def fetch_reputation(self, vendor_name):
        """Return reputation records (PR statements, reviews) for a vendor."""
        if self.config.sample_mode:
            fixture = self._sample_fixture(vendor_name)
            if not fixture:
                return []
            return list(fixture.get("reputation_records", []))
        try:
            return self.zetaris_client.query(
                "SELECT * FROM reputation_signals WHERE vendor = '%s'"
                % vendor_name.replace("'", "''"))
        except ZetarisDataLayerUnavailableError:
            return []

    def fetch_primary(self, claim, vendor_name=""):
        """Look for a primary record backing a challenged claim.

        Keyword overlap ignores the vendor name itself: without that,
        every record for the vendor would "match" every claim about
        the vendor, and an unrelated rumor could be wrongly verified
        by an unrelated docket.
        """
        if self.config.sample_mode:
            fixture = self._sample_fixture(vendor_name)
            if not fixture:
                return None
            vendor_words = set(re.findall(r"[a-z0-9]+",
                                          vendor_name.lower()))
            want = _keywords(claim.statement) - vendor_words
            for record in fixture.get("primary_records", []):
                hay = _keywords(
                    str(record.get("excerpt", "")) + " "
                    + str(record.get("docket", "")) + " "
                    + str(record.get("title", ""))) - vendor_words
                if want & hay:
                    return record
            return None
        # Live mode: a docket lookup through Zetaris, best effort.
        # Same matching rule as sample mode: a primary record only
        # verifies the claim when its text shares keywords with the
        # claim (excluding vendor words), so an unrelated docket can
        # never verify an unrelated rumor.
        try:
            rows = self.zetaris_client.query(
                "SELECT * FROM court_dockets WHERE vendor = '%s'"
                % vendor_name.replace("'", "''"))
        except ZetarisDataLayerUnavailableError:
            return None
        vendor_words = set(re.findall(r"[a-z0-9]+",
                                      vendor_name.lower()))
        want = _keywords(claim.statement) - vendor_words
        if not want:
            return None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not row.get("is_primary_source"):
                continue
            hay = _keywords(" ".join(
                str(v) for v in row.values())) - vendor_words
            if want & hay:
                return row
        return None
