"""Adversarial Evaluator (Markovian critique loop).

Rules, applied in order:
- Rule C (cross-domain contradiction): a company PR claim of growth
  against a negative Zetaris revenue signal creates a CONTRADICTS edge
  plus a CRITICAL_RED_FLAG trace, and the PR claim is discarded
  (its content is false, even though the company did say it).
- Rule A (citation audit): a claim with no evidence is challenged.
- Rule B (source authority): a severe claim (severity >= 8.0) backed
  only by secondary sources is challenged, then retried with a
  directive demanding a primary record. A primary record verifies it
  (severity and confidence come from the primary record); exhausted
  retries discard it.

Challenged claims move PROPOSED -> CHALLENGED -> RETRY_IN_PROGRESS
-> VERIFIED or DISCARDED. Every transition is traced.
"""

from cognition.markov_state import (
    MAX_RETRIES,
    SEVERE_THRESHOLD,
    ClaimState,
)
from cognition.world_model import EvidenceNode


class EvaluatorAgent:
    AGENT_ID = "EvaluatorAgent"

    def _trace(self, tracer, step, event_type, action, claim_id,
               transition, reason, output, status="success", retry=0):
        tracer.log(
            step=step, agent=self.AGENT_ID, engine="markovian", model="",
            event_type=event_type, action=action,
            input_summary="claim %s" % claim_id,
            output_summary=output, target_claim_id=claim_id,
            markov_transition=transition, reason=reason,
            handoff_to="WriterAgent", status=status, retry_count=retry)

    def _challenge_and_retry(self, world, claim, reason, directive,
                             retry_fetcher, tracer):
        old = claim.move_to(ClaimState.CHALLENGED)
        self._trace(tracer, "evaluator", "claim_challenged", "challenge",
                    claim.claim_id, "%s->%s" % (old.value, "CHALLENGED"),
                    reason, "claim challenged")
        claim.retry_directive = directive
        old = claim.move_to(ClaimState.RETRY_IN_PROGRESS)
        self._trace(tracer, "evaluator", "retry_started", "retry",
                    claim.claim_id, "%s->%s" % (old.value,
                                                "RETRY_IN_PROGRESS"),
                    directive, "retry started")
        found = None
        for attempt in range(1, MAX_RETRIES + 1):
            record = retry_fetcher(claim)
            claim.retry_count = attempt
            self._trace(tracer, "evaluator", "retry_attempt", "retry",
                        claim.claim_id, None,
                        "retry attempt %d: %s" % (
                            attempt, "primary record found"
                            if record else "no primary record"),
                        "retry attempt %d" % attempt, retry=attempt)
            if record:
                found = record
                break
        if found:
            evidence = EvidenceNode(
                evidence_id="%s-EV-PRIMARY" % claim.claim_id,
                source_type=str(found.get("source_type", "COURT_DOCKET")),
                is_primary_source=True,
                raw_excerpt=str(found.get("excerpt", "")),
                citation_locator=str(found.get("citation", "")),
                claim_id=claim.claim_id)
            world.add_evidence(evidence)
            world.link("SUPPORTS", evidence.evidence_id, claim.claim_id,
                       "Primary record verifies the challenged claim")
            if found.get("severity") is not None:
                claim.severity = float(found["severity"])
            if found.get("confidence") is not None:
                claim.confidence = float(found["confidence"])
            old = claim.move_to(ClaimState.VERIFIED)
            self._trace(tracer, "evaluator", "claim_verified", "verify",
                        claim.claim_id,
                        "%s->%s" % (old.value, "VERIFIED"),
                        "primary record verified the claim",
                        "claim verified via primary record",
                        retry=claim.retry_count)
        else:
            old = claim.move_to(ClaimState.DISCARDED)
            self._trace(tracer, "evaluator", "claim_discarded", "discard",
                        claim.claim_id,
                        "%s->%s" % (old.value, "DISCARDED"),
                        "retries exhausted without a primary record",
                        "claim discarded", retry=claim.retry_count)

    def evaluate(self, world, retry_fetcher, tracer):
        """Run all rules over the world model. Returns a result dict."""
        # Rule C first: PR growth claims against negative revenue.
        revenue_yoy = world.signals.get("revenue_yoy_pct")
        if isinstance(revenue_yoy, (int, float)) and revenue_yoy < 0:
            revenue_claim = None
            for claim in world.claims.values():
                if (claim.domain == "FINANCIAL"
                        and "revenue" in claim.statement.lower()):
                    revenue_claim = claim
                    break
            for claim in list(world.claims.values()):
                if (claim.state == ClaimState.PROPOSED
                        and claim.domain == "REPUTATION"
                        and claim.metadata.get("claims_growth")):
                    target_id = (revenue_claim.claim_id
                                 if revenue_claim else claim.claim_id)
                    world.link(
                        "CONTRADICTS", claim.claim_id, target_id,
                        "PR claims growth while Zetaris shows revenue "
                        "decline of %s percent" % revenue_yoy)
                    tracer.log(
                        step="evaluator", agent=self.AGENT_ID,
                        engine="markovian", model="",
                        event_type="contradiction_detected",
                        action="flag_contradiction",
                        input_summary="PR growth claim vs revenue %s"
                                      % revenue_yoy,
                        output_summary="CRITICAL_RED_FLAG: PR growth "
                                       "contradicts Zetaris data",
                        target_claim_id=claim.claim_id,
                        reason="company PR contradicts Zetaris data",
                        handoff_to="WriterAgent", status="success")
                    old = claim.move_to(ClaimState.CHALLENGED)
                    self._trace(tracer, "evaluator", "claim_challenged",
                                "challenge", claim.claim_id,
                                "%s->%s" % (old.value, "CHALLENGED"),
                                "content contradicted by Zetaris data",
                                "claim challenged")
                    old = claim.move_to(ClaimState.DISCARDED)
                    self._trace(tracer, "evaluator", "claim_discarded",
                                "discard", claim.claim_id,
                                "%s->%s" % (old.value, "DISCARDED"),
                                "PR content contradicted by primary data",
                                "claim discarded")

        # Rules A and B, then verify everything else.
        for claim in list(world.claims.values()):
            if claim.state != ClaimState.PROPOSED:
                continue
            evidences = [world.evidence[eid]
                         for eid in claim.evidence_ids
                         if eid in world.evidence]
            if not evidences:
                self._challenge_and_retry(
                    world, claim, "no evidence attached to claim",
                    "Attach a cited evidence record for this claim.",
                    retry_fetcher, tracer)
            elif (claim.severity >= SEVERE_THRESHOLD
                    and all(not e.is_primary_source for e in evidences)):
                self._challenge_and_retry(
                    world, claim,
                    "severe claim backed only by secondary sources",
                    "Fetch a primary record (court docket, filing, or "
                    "primary filing) for this claim.",
                    retry_fetcher, tracer)
            else:
                old = claim.move_to(ClaimState.VERIFIED)
                self._trace(tracer, "evaluator", "claim_verified", "verify",
                            claim.claim_id,
                            "%s->%s" % (old.value, "VERIFIED"),
                            "passed citation and source authority rules",
                            "claim verified")
        tracer.log(
            step="evaluator", agent=self.AGENT_ID, engine="markovian",
            model="", event_type="evaluation_complete",
            action="complete",
            input_summary="%d claims evaluated" % len(world.claims),
            output_summary="%d verified, %d discarded, %d contradictions"
                           % (len(world.verified_claims()),
                              len(world.discarded_claims()),
                              len(world.get_contradictions())),
            handoff_to="WriterAgent", status="success")
        return {
            "verified": world.verified_claims(),
            "discarded": world.discarded_claims(),
            "contradictions": world.get_contradictions(),
        }
