"""Writer agent: deterministic scoring plus report.md / report.json.

The score is NEVER guessed by a model. It is computed in pure Python
from VERIFIED claims only:

    S_fin    = min(35, sum severity x 2.0 x confidence)  [FINANCIAL]
    S_leg    = min(25, sum severity x 2.0 x confidence)  [LEGAL]
    P_contra = 25 if at least one CONTRADICTS edge exists else 0
    S_rep    = min(15, sum severity x 1.2 x confidence)  [REPUTATION]
    Total    = round(S_fin + S_leg + P_contra + S_rep)

Tiers: 0-34 LOW, 35-64 MODERATE, 65-100 HIGH.

Red flags are VERIFIED FINANCIAL or LEGAL claims with severity >= 6.
Each red flag maps to a mitigation with a contract clause and a points
reduction; the residual score shows what the score would be if every
mitigation were applied. The Path to Greenlight table is what turns
this report into an actionable procurement tool.
"""

from datetime import datetime, timezone

from pydantic import BaseModel


def tier_for(total):
    if total >= 65:
        return "HIGH"
    if total >= 35:
        return "MODERATE"
    return "LOW"


def recommendation_for(tier):
    if tier == "HIGH":
        return ("DO NOT PROCEED as-is: resolve the red flags below or "
                "apply the Path to Greenlight mitigations before signing.")
    if tier == "MODERATE":
        return ("PROCEED WITH CONDITIONS: apply the mitigations below "
                "and monitor the flagged areas through onboarding.")
    return ("PROCEED: no material red flags found; standard onboarding "
            "checks still apply.")


def compute_score(verified_claims, contradictions):
    """Compute the deterministic breakdown from verified claims."""
    fin = 0.0
    leg = 0.0
    rep = 0.0
    detail = []
    for claim in verified_claims:
        if claim.domain == "FINANCIAL":
            contribution = claim.severity * 2.0 * claim.confidence
            fin += contribution
            detail.append((claim, contribution))
        elif claim.domain == "LEGAL":
            contribution = claim.severity * 2.0 * claim.confidence
            leg += contribution
            detail.append((claim, contribution))
        elif claim.domain == "REPUTATION":
            contribution = claim.severity * 1.2 * claim.confidence
            rep += contribution
            detail.append((claim, contribution))
    s_fin = min(35.0, fin)
    s_leg = min(25.0, leg)
    s_rep = min(15.0, rep)
    p_contra = 25.0 if contradictions else 0.0
    total = round(s_fin + s_leg + p_contra + s_rep)
    return {
        "financial": round(s_fin, 2),
        "legal": round(s_leg, 2),
        "contradiction": round(p_contra, 2),
        "reputation": round(s_rep, 2),
        "total": total,
        "tier": tier_for(total),
        "detail": detail,
    }


# Mitigation catalog, keyed by flag kind. Values are recommendation
# templates: they describe what would reduce the risk, and by how
# much, for any vendor that has that kind of flag.
MITIGATIONS = {
    "revenue": ("Require audited financial statements and a $100k escrow",
                "Escrow + Right-to-Audit Clause", 15),
    "cash": ("Require a bank guarantee and milestone based payments",
             "Payment-on-Delivery Clause", 12),
    "legal": ("Obtain an independent legal opinion and a full indemnity",
              "Indemnity + Termination-for-Cause Clause", 15),
    "contradiction": ("Require independent third party verification and "
                      "a disclosure warranty",
                      "Disclosure Warranty Clause", 10),
    "general": ("Require quarterly business reviews and service credits",
                "Service Credit Clause", 8),
}


def _flag_kind(statement):
    text = statement.lower()
    if "revenue" in text:
        return "revenue"
    if "cash" in text:
        return "cash"
    if ("lawsuit" in text or "court" in text or "counterfeit" in text
            or "dispute" in text):
        return "legal"
    return "general"


def build_path_to_greenlight(score, red_flags, contradictions):
    """Build the mitigation table and the residual score."""
    rows = []
    reduction = 0
    for claim in red_flags:
        kind = _flag_kind(claim.statement)
        action, clause, points = MITIGATIONS[kind]
        rows.append({
            "red_flag": claim.statement,
            "mitigation": action,
            "sla_clause": clause,
            "points_reduced": points,
        })
        reduction += points
    for edge in contradictions:
        action, clause, points = MITIGATIONS["contradiction"]
        rows.append({
            "red_flag": "Company PR contradicts Zetaris data (%s)"
                        % edge.reason,
            "mitigation": action,
            "sla_clause": clause,
            "points_reduced": points,
        })
        reduction += points
    residual = max(0, score["total"] - reduction)
    return rows, residual, tier_for(residual)


class ReportJson(BaseModel):
    vendor_name: str
    procurement_context: str
    sample_mode: bool
    score: int
    tier: str
    recommendation: str
    breakdown: dict
    claims: list
    contradictions: list
    red_flags: list
    discarded_claims: list
    path_to_greenlight: list
    residual_score: int
    residual_tier: str
    citations: list
    model: str
    trace_file: str
    generated_at: str


class WriterAgent:
    AGENT_ID = "WriterAgent"

    def write(self, world, procurement_context, sample_mode, model,
              trace_file, generate_fn, tracer):
        verified = world.verified_claims()
        discarded = world.discarded_claims()
        contradictions = world.get_contradictions()
        score = compute_score(verified, contradictions)
        red_flags = [c for c in verified
                     if c.domain in ("FINANCIAL", "LEGAL")
                     and c.severity >= 6.0]
        greenlight, residual, residual_tier = build_path_to_greenlight(
            score, red_flags, contradictions)
        summary = generate_fn(
            "Write a one paragraph executive summary of a vendor "
            "due-diligence report.",
            "Vendor %s scored %d/100 (%s). Verified claims: %d. "
            "Contradictions: %d. Summarize the decision."
            % (world.vendor_name, score["total"], score["tier"],
               len(verified), len(contradictions)))
        citations = []
        for claim in verified:
            for evidence_id in claim.evidence_ids:
                evidence = world.evidence.get(evidence_id)
                if evidence:
                    citations.append({
                        "claim_id": claim.claim_id,
                        "source_type": evidence.source_type,
                        "citation_locator": evidence.citation_locator,
                        "excerpt": evidence.raw_excerpt,
                    })
        generated_at = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z")
        report = ReportJson(
            vendor_name=world.vendor_name,
            procurement_context=procurement_context or "",
            sample_mode=sample_mode,
            score=score["total"],
            tier=score["tier"],
            recommendation=recommendation_for(score["tier"]),
            breakdown={
                "financial": score["financial"],
                "legal": score["legal"],
                "contradiction": score["contradiction"],
                "reputation": score["reputation"],
            },
            claims=[{
                "claim_id": c.claim_id,
                "domain": c.domain,
                "statement": c.statement,
                "severity": c.severity,
                "confidence": c.confidence,
                "state": c.state.value,
                "citations": [world.evidence[e].citation_locator
                              for e in c.evidence_ids
                              if e in world.evidence],
            } for c in verified],
            contradictions=[{
                "source_claim_id": e.source_id,
                "target_claim_id": e.target_id,
                "reason": e.reason,
            } for e in contradictions],
            red_flags=[{
                "claim_id": c.claim_id,
                "statement": c.statement,
                "severity": c.severity,
            } for c in red_flags],
            discarded_claims=[{
                "claim_id": c.claim_id,
                "statement": c.statement,
                "retry_count": c.retry_count,
            } for c in discarded],
            path_to_greenlight=greenlight,
            residual_score=residual,
            residual_tier=residual_tier,
            citations=citations,
            model=model,
            trace_file=trace_file,
            generated_at=generated_at)
        report_data = report.model_dump()
        markdown = self._render_markdown(
            world, report_data, score, verified, discarded,
            contradictions, red_flags, greenlight, residual, residual_tier,
            sample_mode, summary.get("text", ""))
        tracer.log(
            step="writer", agent=self.AGENT_ID, engine="writer",
            model=model, event_type="score_computed",
            action="write_report",
            input_summary="%d verified claims" % len(verified),
            output_summary="score %d/100 %s" % (score["total"],
                                                score["tier"]),
            handoff_to=None, status="success")
        return markdown, report_data

    def _render_markdown(self, world, report, score, verified, discarded,
                         contradictions, red_flags, greenlight, residual,
                         residual_tier, sample_mode, executive_text):
        lines = []
        if sample_mode:
            lines.append("[SYNTHETIC SANDBOX FIXTURE - SAMPLE DATA ONLY: "
                         "%s]" % world.vendor_name)
            lines.append("")
        lines.append("# Receipts Due-Diligence Report: %s"
                     % world.vendor_name)
        lines.append("")
        lines.append("## Executive Decision")
        lines.append("")
        lines.append("**Risk score: %d/100 (%s)**"
                     % (score["total"], score["tier"]))
        lines.append("")
        lines.append(report["recommendation"])
        lines.append("")
        lines.append(executive_text)
        lines.append("")
        lines.append("## Transparent Math Breakdown")
        lines.append("")
        lines.append("Scores are computed from VERIFIED claims only. "
                     "Discarded claims contribute zero.")
        lines.append("")
        lines.append("| Domain | Claim | Severity | Confidence | "
                     "Contribution |")
        lines.append("|---|---|---|---|---|")
        for claim, contribution in score["detail"]:
            factor = 2.0 if claim.domain in ("FINANCIAL", "LEGAL") else 1.2
            lines.append("| %s | %s | %.1f | %.2f | %.2f "
                         "(%.1f x %.1f x %.2f) |"
                         % (claim.domain, claim.statement, claim.severity,
                            claim.confidence, contribution,
                            claim.severity, factor, claim.confidence))
        lines.append("| Contradiction penalty | %d CONTRADICTS edge(s) | "
                     "| | %.2f |"
                     % (len(contradictions), score["contradiction"]))
        lines.append("")
        lines.append("- Financial (capped at 35): %.2f" % score["financial"])
        lines.append("- Legal (capped at 25): %.2f" % score["legal"])
        lines.append("- Contradiction: %.2f" % score["contradiction"])
        lines.append("- Reputation (capped at 15): %.2f"
                     % score["reputation"])
        lines.append("- **Total: %d/100 (%s)**"
                     % (score["total"], score["tier"]))
        lines.append("")
        lines.append("## Evidence Graph")
        lines.append("")
        lines.append(world.to_mermaid())
        lines.append("")
        lines.append("## Verified Findings")
        lines.append("")
        for claim in verified:
            cites = [world.evidence[e].citation_locator
                     for e in claim.evidence_ids if e in world.evidence]
            lines.append("- **[%s] %s** (severity %.1f, confidence %.2f)"
                         % (claim.domain, claim.statement, claim.severity,
                            claim.confidence))
            for cite in cites:
                lines.append("  - Source: %s" % cite)
        if not verified:
            lines.append("- No verified findings.")
        lines.append("")
        lines.append("## Red Flags")
        lines.append("")
        for flag in red_flags:
            lines.append("- %s (severity %.1f)"
                         % (flag.statement, flag.severity))
        if not red_flags:
            lines.append("- None.")
        lines.append("")
        lines.append("## Path to Greenlight")
        lines.append("")
        lines.append("If every mitigation below were applied, the score "
                     "would fall from **%d** to **%d (%s)**."
                     % (score["total"], residual, residual_tier))
        lines.append("")
        lines.append("| Red Flag | Mitigation Action | Recommended "
                     "SLA / Contract Clause | Points Reduced |")
        lines.append("|---|---|---|---|")
        for row in greenlight:
            lines.append("| %s | %s | %s | %d |"
                         % (row["red_flag"], row["mitigation"],
                            row["sla_clause"], row["points_reduced"]))
        if not greenlight:
            lines.append("| No red flags | No action required | - | 0 |")
        lines.append("")
        lines.append("## Appendix: Rejected Rumors and Unverified Claims")
        lines.append("")
        lines.append("These claims were challenged by the Evaluator and "
                     "discarded after retries. They contribute zero to "
                     "the score.")
        lines.append("")
        for claim in discarded:
            lines.append("- %s (retries: %d)"
                         % (claim.statement, claim.retry_count))
        if not discarded:
            lines.append("- None. Every proposed claim was verified.")
        lines.append("")
        lines.append("## Audit Trail")
        lines.append("")
        lines.append("- Model / provider: %s" % report["model"])
        lines.append("- Sample mode: %s" % report["sample_mode"])
        lines.append("- Trace file: %s" % report["trace_file"])
        lines.append("- Generated at: %s" % report["generated_at"])
        lines.append("- Agents: PlannerAgent, FinancialExecutor, "
                     "LegalExecutor, ReputationExecutor, EvaluatorAgent, "
                     "WriterAgent")
        lines.append("- Engines: World Model (evidence graph), Markovian "
                     "(claim lifecycle)")
        return "\n".join(lines) + "\n"
