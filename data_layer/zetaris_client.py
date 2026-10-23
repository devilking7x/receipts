"""Zetaris data layer adapter (load-bearing).

LIVE mode talks to the Zetaris REST API at ZETARIS_REST_URL
(default http://localhost:8888/api/v1.0 -- the REST port, never the
3000 web UI port). Every request carries Authorization: Bearer plus
X-Org-ID plus a fresh X-Request-ID UUID. SQL runs through
POST /sql-editor/sqls/run.

FAIL-CLOSED: in live mode, if Zetaris is disabled, has no credentials,
is unreachable, or answers with an error, this module raises
ZetarisDataLayerUnavailableError. The financial executor propagates
that error, so the pipeline fails loudly instead of silently running
on invented data. That is what makes Zetaris load-bearing.

SAMPLE_MODE: the pipeline injects fixture rows (cached data) into this
client, so the same code path serves sample runs with zero credentials.
"""

import uuid

import httpx


class ZetarisDataLayerUnavailableError(Exception):
    """Raised when Zetaris is required but unavailable (live mode)."""


class ZetarisClient:
    def __init__(self, config, sample_rows_by_vendor=None):
        self.config = config
        # In sample mode: {vendor_name_lower: [row, ...]} from fixtures.
        self.sample_rows_by_vendor = sample_rows_by_vendor or {}

    def is_available(self):
        if self.config.sample_mode:
            return True
        if not self.config.zetaris_enabled:
            return False
        return bool(self.config.zetaris_api_key
                    or self.config.zetaris_username)

    def query(self, sql, limit=100):
        """Run a SQL query and return a list of row dicts."""
        if self.config.sample_mode:
            # Sample mode has no live SQL engine; the caller uses
            # query_financials() which serves fixture rows instead.
            raise ZetarisDataLayerUnavailableError(
                "Raw SQL is not available in SAMPLE_MODE; use "
                "query_financials() with fixture data.")
        if not self.is_available():
            raise ZetarisDataLayerUnavailableError(
                "Zetaris is disabled or has no credentials. Set "
                "ZETARIS_API_KEY (or ZETARIS_USERNAME) and make sure "
                "the Zetaris container is running.")
        url = self.config.zetaris_rest_url.rstrip("/") + "/sql-editor/sqls/run"
        headers = {
            "Authorization": "Bearer %s" % self.config.zetaris_api_key,
            "X-Org-ID": str(self.config.zetaris_org_id),
            "X-Request-ID": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
        body = {
            "queryId": str(uuid.uuid4()),
            "sql": sql,
            "source": "SqlEditor",
            "limit": limit,
        }
        try:
            with httpx.Client(timeout=self.config.request_timeout_s) as client:
                resp = client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            raise ZetarisDataLayerUnavailableError(
                "Zetaris REST request failed: %s" % exc) from exc
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "rows", "result", "records"):
                rows = payload.get(key)
                if isinstance(rows, list):
                    return rows
                if isinstance(rows, dict):
                    return [rows]
        return []

    def query_financials(self, vendor_name):
        """Return financial rows for a vendor.

        Sample mode serves the vendor fixture rows. Live mode runs a
        federated SQL query joining financial records with entity
        metadata, so the Zetaris CTO sees genuine data federation.
        """
        if self.config.sample_mode:
            rows = self.sample_rows_by_vendor.get(vendor_name.lower())
            if rows is None:
                return []
            return rows
        # Zetaris resolves tables only as <container>.<view>; the live
        # tables live in the `receipts` schemastore container.
        sql = (
            "SELECT f.* FROM receipts.corp_financials_2025 f "
            "JOIN receipts.entity_metadata e ON f.vendor = e.vendor "
            "WHERE f.vendor = '%s'" % vendor_name.replace("'", "''"))
        return self.query(sql)
