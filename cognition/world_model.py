"""World Model evidence graph (Meterless World Model engine, custom code).

Nodes:
- EntityNode: Vendor, Subsidiary, Executive, CourtCase.
- ClaimNode: one finding about the vendor, with domain, severity,
  confidence and a Markovian lifecycle state.
- EvidenceNode: one source record backing a claim, with its source type,
  whether it is a primary source, a raw excerpt and a citation locator.

Edges:
- SUPPORTS: evidence backs a claim.
- CONTRADICTS: one record contradicts a claim (the PR vs reality catch).
- DERIVED_FROM: a claim was derived from another claim or record.

The Writer scores ONLY claims in state VERIFIED. Discarded claims never
contribute to the score; they are listed in the report appendix instead.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from cognition.markov_state import ClaimState, validate_transition


class EntityNode(BaseModel):
    entity_id: str
    entity_type: str  # Vendor | Subsidiary | Executive | CourtCase
    name: str
    attributes: Dict[str, str] = Field(default_factory=dict)


class ClaimNode(BaseModel):
    claim_id: str
    domain: str  # FINANCIAL | LEGAL | REPUTATION
    statement: str
    severity: float = Field(ge=0.0, le=20.0)
    confidence: float = Field(ge=0.0, le=1.0)
    state: ClaimState = ClaimState.PROPOSED
    evidence_ids: List[str] = Field(default_factory=list)
    retry_count: int = 0
    retry_directive: Optional[str] = None
    # Source supplied flags, e.g. {"claims_growth": true} on a PR record.
    metadata: Dict[str, object] = Field(default_factory=dict)

    def move_to(self, new_state):
        """Move to a new state, enforcing the Markovian transition rules."""
        if not validate_transition(self.state, new_state):
            raise ValueError(
                "Illegal claim transition %s -> %s for %s"
                % (self.state, new_state, self.claim_id))
        old = self.state
        self.state = ClaimState(new_state)
        return old


class EvidenceNode(BaseModel):
    evidence_id: str
    source_type: str  # ZETARIS_SQL | COURT_DOCKET | SEC_FILING |
    # NEWS_ARTICLE | COMPANY_PR | CUSTOMER_REVIEW
    is_primary_source: bool
    raw_excerpt: str
    citation_locator: str
    claim_id: Optional[str] = None


class Edge(BaseModel):
    edge_type: str  # SUPPORTS | CONTRADICTS | DERIVED_FROM
    source_id: str
    target_id: str
    reason: str = ""


class WorldModel:
    """The evidence graph for one vendor investigation."""

    def __init__(self, vendor_name):
        self.vendor_name = vendor_name
        self.entities: Dict[str, EntityNode] = {}
        self.claims: Dict[str, ClaimNode] = {}
        self.evidence: Dict[str, EvidenceNode] = {}
        self.edges: List[Edge] = []
        # Free-form signals the Evaluator may use, e.g. revenue_yoy_pct.
        self.signals: Dict[str, object] = {}

    def add_entity(self, entity):
        self.entities[entity.entity_id] = entity
        return entity

    def add_claim(self, claim):
        self.claims[claim.claim_id] = claim
        return claim

    def add_evidence(self, evidence):
        self.evidence[evidence.evidence_id] = evidence
        if evidence.claim_id and evidence.claim_id in self.claims:
            claim = self.claims[evidence.claim_id]
            if evidence.evidence_id not in claim.evidence_ids:
                claim.evidence_ids.append(evidence.evidence_id)
        return evidence

    def link(self, edge_type, source_id, target_id, reason=""):
        edge = Edge(edge_type=edge_type, source_id=source_id,
                    target_id=target_id, reason=reason)
        self.edges.append(edge)
        return edge

    def verified_claims(self):
        return [c for c in self.claims.values()
                if c.state == ClaimState.VERIFIED]

    def discarded_claims(self):
        return [c for c in self.claims.values()
                if c.state == ClaimState.DISCARDED]

    def get_contradictions(self):
        return [e for e in self.edges if e.edge_type == "CONTRADICTS"]

    def to_mermaid(self):
        """Render the graph as a Mermaid flowchart for report.md."""
        lines = ["```mermaid", "flowchart TD"]
        vendor_node = "V[%s]" % self.vendor_name
        lines.append("    %s" % vendor_node)
        for claim in self.claims.values():
            label = "%s<br/>%s %.1f conf %.2f<br/>%s" % (
                claim.claim_id, claim.domain, claim.severity,
                claim.confidence, claim.state.value)
            lines.append('    %s["%s"]' % (claim.claim_id, label))
            lines.append("    %s --> %s" % (vendor_node.split("[")[0],
                                            claim.claim_id))
        for evidence in self.evidence.values():
            label = "%s<br/>%s" % (evidence.evidence_id,
                                   evidence.source_type)
            lines.append('    %s["%s"]' % (evidence.evidence_id, label))
            if evidence.claim_id:
                lines.append("    %s --> %s" % (evidence.evidence_id,
                                                evidence.claim_id))
        for edge in self.edges:
            if edge.edge_type == "CONTRADICTS":
                lines.append("    %s -.->|contradicts| %s" % (
                    edge.source_id, edge.target_id))
            elif edge.edge_type == "DERIVED_FROM":
                lines.append("    %s -.->|derived from| %s" % (
                    edge.source_id, edge.target_id))
        lines.append("```")
        return "\n".join(lines)
