"""Three parallel executors (asyncio.gather).

- FinancialExecutor: Zetaris, LOAD-BEARING. In live mode a missing or
  unreachable Zetaris raises ZetarisDataLayerUnavailableError and the
  pipeline stops loudly instead of inventing financial data.
- LegalExecutor: legal filings and news records via the search client.
- ReputationExecutor: PR statements and customer reviews.

Every finding becomes a ClaimNode plus an EvidenceNode in the World
Model. Executors never output bare prose as findings. Each executor
also calls its injected generate_fn for a short summary, which is
traced but never decides the findings.
"""

import asyncio
import re

from cognition.world_model import ClaimNode, EvidenceNode


def _slug(vendor_name):
    slug = re.sub(r"[^a-z0-9]+", "-", vendor_name.lower()).strip("-")
    return slug or "vendor"


def _evidence_id(claim_id, index):
    return "%s-EV%d" % (claim_id, index)


class FinancialExecutor:
    AGENT_ID = "FinancialExecutor"

    def __init__(self, zetaris_client):
        self.zetaris_client = zetaris_client

    async def run(self, world, task, vendor_name, generate_fn, tracer):
        # Fail-closed: in live mode this raises when Zetaris is down.
        rows = await asyncio.to_thread(
            self.zetaris_client.query_financials, vendor_name)
        slug = _slug(vendor_name)
        claims = []
        for index, row in enumerate(rows):
            claim_id = "%s-FIN-%d" % (slug, index + 1)
            statement = str(row.get(
                "excerpt") or "Financial record %s = %s"
                % (row.get("metric", "unknown"), row.get("value")))
            claim = ClaimNode(
                claim_id=claim_id, domain="FINANCIAL", statement=statement,
                severity=float(row.get("severity", 0.0)),
                confidence=float(row.get("confidence", 0.0)))
            evidence = EvidenceNode(
                evidence_id=_evidence_id(claim_id, 1),
                source_type="ZETARIS_SQL", is_primary_source=True,
                raw_excerpt=statement,
                citation_locator=str(row.get("citation", "")),
                claim_id=claim_id)
            world.add_claim(claim)
            world.add_evidence(evidence)
            world.link("SUPPORTS", evidence.evidence_id, claim_id,
                       "Zetaris record backs the financial claim")
            if row.get("metric") == "revenue_yoy_pct":
                world.signals["revenue_yoy_pct"] = row.get("value")
            claims.append(claim)
            tracer.log(
                step="executor_financial", agent=self.AGENT_ID,
                engine="world_model", model="",
                event_type="claim_proposed", action="propose_claim",
                input_summary="Zetaris row %s" % row.get("metric"),
                output_summary=statement[:120],
                target_claim_id=claim_id,
                markov_transition="None->PROPOSED",
                handoff_to="EvaluatorAgent", status="success")
        summary = await asyncio.to_thread(
            generate_fn,
            "Summarize financial findings briefly.",
            "Financial findings for %s: %d claims from Zetaris."
            % (vendor_name, len(claims)))
        tracer.log(
            step="executor_financial", agent=self.AGENT_ID,
            engine="generator", model=summary.get("model", ""),
            event_type="executor_summary", action="summarize",
            input_summary="%d financial claims" % len(claims),
            output_summary=str(summary.get("text", ""))[:160],
            handoff_to="EvaluatorAgent", status="success")
        return claims


class LegalExecutor:
    AGENT_ID = "LegalExecutor"

    def __init__(self, search_client):
        self.search_client = search_client

    async def run(self, world, task, vendor_name, generate_fn, tracer):
        records = await asyncio.to_thread(
            self.search_client.fetch_legal, vendor_name)
        slug = _slug(vendor_name)
        claims = []
        for index, record in enumerate(records):
            claim_id = "%s-LEG-%d" % (slug, index + 1)
            statement = str(record.get("title") or record.get("excerpt", ""))
            claim = ClaimNode(
                claim_id=claim_id, domain="LEGAL", statement=statement,
                severity=float(record.get("severity", 0.0)),
                confidence=float(record.get("confidence", 0.0)))
            evidence = EvidenceNode(
                evidence_id=_evidence_id(claim_id, 1),
                source_type=str(record.get("source_type", "NEWS_ARTICLE")),
                is_primary_source=bool(record.get("is_primary_source")),
                raw_excerpt=str(record.get("excerpt", "")),
                citation_locator=str(record.get("citation", "")),
                claim_id=claim_id)
            world.add_claim(claim)
            world.add_evidence(evidence)
            world.link("SUPPORTS", evidence.evidence_id, claim_id,
                       "Legal record backs the legal claim")
            claims.append(claim)
            tracer.log(
                step="executor_legal", agent=self.AGENT_ID,
                engine="world_model", model="",
                event_type="claim_proposed", action="propose_claim",
                input_summary="Legal record: %s" % statement[:80],
                output_summary=statement[:120],
                target_claim_id=claim_id,
                markov_transition="None->PROPOSED",
                handoff_to="EvaluatorAgent", status="success")
        summary = await asyncio.to_thread(
            generate_fn,
            "Summarize legal findings briefly.",
            "Legal findings for %s: %d claims." % (vendor_name,
                                                    len(claims)))
        tracer.log(
            step="executor_legal", agent=self.AGENT_ID,
            engine="generator", model=summary.get("model", ""),
            event_type="executor_summary", action="summarize",
            input_summary="%d legal claims" % len(claims),
            output_summary=str(summary.get("text", ""))[:160],
            handoff_to="EvaluatorAgent", status="success")
        return claims


class ReputationExecutor:
    AGENT_ID = "ReputationExecutor"

    def __init__(self, search_client):
        self.search_client = search_client

    async def run(self, world, task, vendor_name, generate_fn, tracer):
        records = await asyncio.to_thread(
            self.search_client.fetch_reputation, vendor_name)
        slug = _slug(vendor_name)
        claims = []
        for index, record in enumerate(records):
            claim_id = "%s-REP-%d" % (slug, index + 1)
            statement = str(record.get("excerpt", ""))
            metadata = {}
            if record.get("claims_growth"):
                metadata["claims_growth"] = True
            claim = ClaimNode(
                claim_id=claim_id, domain="REPUTATION", statement=statement,
                severity=float(record.get("severity", 0.0)),
                confidence=float(record.get("confidence", 0.0)),
                metadata=metadata)
            evidence = EvidenceNode(
                evidence_id=_evidence_id(claim_id, 1),
                source_type=str(record.get("source_type", "CUSTOMER_REVIEW")),
                is_primary_source=bool(record.get("is_primary_source")),
                raw_excerpt=statement,
                citation_locator=str(record.get("citation", "")),
                claim_id=claim_id)
            world.add_claim(claim)
            world.add_evidence(evidence)
            world.link("SUPPORTS", evidence.evidence_id, claim_id,
                       "Reputation record backs the reputation claim")
            claims.append(claim)
            tracer.log(
                step="executor_reputation", agent=self.AGENT_ID,
                engine="world_model", model="",
                event_type="claim_proposed", action="propose_claim",
                input_summary="Reputation record: %s" % statement[:80],
                output_summary=statement[:120],
                target_claim_id=claim_id,
                markov_transition="None->PROPOSED",
                handoff_to="EvaluatorAgent", status="success")
        summary = await asyncio.to_thread(
            generate_fn,
            "Summarize reputation findings briefly.",
            "Reputation findings for %s: %d claims." % (vendor_name,
                                                          len(claims)))
        tracer.log(
            step="executor_reputation", agent=self.AGENT_ID,
            engine="generator", model=summary.get("model", ""),
            event_type="executor_summary", action="summarize",
            input_summary="%d reputation claims" % len(claims),
            output_summary=str(summary.get("text", ""))[:160],
            handoff_to="EvaluatorAgent", status="success")
        return claims


async def run_all(world, plan, vendor_name, generate_fns, tracer,
                  zetaris_client, search_client):
    """Run the three executors concurrently.

    Financial failure is load-bearing and propagates. Legal and
    reputation failures degrade to empty results with a warning trace.
    """
    from data_layer.zetaris_client import ZetarisDataLayerUnavailableError

    tasks = {t.task_type: t for t in plan.tasks}
    fin = FinancialExecutor(zetaris_client)
    leg = LegalExecutor(search_client)
    rep = ReputationExecutor(search_client)
    results = await asyncio.gather(
        fin.run(world, tasks.get("FINANCIAL_TASK"), vendor_name,
                generate_fns["FinancialExecutor"], tracer),
        leg.run(world, tasks.get("LEGAL_TASK"), vendor_name,
                generate_fns["LegalExecutor"], tracer),
        rep.run(world, tasks.get("REPUTATION_TASK"), vendor_name,
                generate_fns["ReputationExecutor"], tracer),
        return_exceptions=True)
    fin_result, leg_result, rep_result = results
    if isinstance(fin_result, Exception):
        if isinstance(fin_result, ZetarisDataLayerUnavailableError):
            raise fin_result
        raise fin_result
    for label, result, agent in (
            ("legal", leg_result, "LegalExecutor"),
            ("reputation", rep_result, "ReputationExecutor")):
        if isinstance(result, Exception):
            tracer.log(
                step="executor_%s" % label, agent=agent,
                engine="world_model", model="",
                event_type="executor_degraded", action="degrade",
                input_summary="executor failed: %s" % str(result)[:120],
                output_summary="continuing with no %s claims" % label,
                handoff_to="EvaluatorAgent", status="degraded")
    return {
        "financial": fin_result if not isinstance(fin_result, Exception) else [],
        "legal": leg_result if not isinstance(leg_result, Exception) else [],
        "reputation": rep_result if not isinstance(rep_result, Exception) else [],
    }
