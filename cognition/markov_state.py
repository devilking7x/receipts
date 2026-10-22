"""Markovian claim lifecycle (Meterless Markovian engine, custom code).

Every claim found by an executor moves through a small state machine:

    PROPOSED -> CHALLENGED -> RETRY_IN_PROGRESS -> VERIFIED
                                                  -> DISCARDED

Rules:
- A claim starts PROPOSED.
- The Evaluator may move it to CHALLENGED when its evidence is missing,
  secondary only for a severe claim, or contradicted by stronger data.
- A challenged claim moves to RETRY_IN_PROGRESS while the owning executor
  looks for a primary record.
- After retry it lands in VERIFIED (primary evidence found) or DISCARDED
  (retries exhausted, or its content is contradicted).
- VERIFIED and DISCARDED are terminal: no further transitions are allowed.

Every transition is recorded in the JSONL trace log by the caller.
"""

from enum import Enum


class ClaimState(str, Enum):
    PROPOSED = "PROPOSED"
    CHALLENGED = "CHALLENGED"
    RETRY_IN_PROGRESS = "RETRY_IN_PROGRESS"
    VERIFIED = "VERIFIED"
    DISCARDED = "DISCARDED"


ALLOWED_TRANSITIONS = {
    ClaimState.PROPOSED: {ClaimState.CHALLENGED, ClaimState.VERIFIED},
    ClaimState.CHALLENGED: {ClaimState.RETRY_IN_PROGRESS,
                            ClaimState.DISCARDED},
    ClaimState.RETRY_IN_PROGRESS: {ClaimState.VERIFIED,
                                   ClaimState.DISCARDED,
                                   ClaimState.CHALLENGED},
    ClaimState.VERIFIED: set(),
    ClaimState.DISCARDED: set(),
}

# A claim at or above this severity that rests only on secondary sources
# must be challenged and retried against a primary record (Evaluator
# Rule B). Below this, a secondary sourced observation may be verified
# at its stated confidence.
SEVERE_THRESHOLD = 8.0

# Maximum retry attempts for a challenged claim before it is discarded.
MAX_RETRIES = 2


def validate_transition(from_state, to_state):
    """Return True when moving from_state -> to_state is legal."""
    allowed = ALLOWED_TRANSITIONS.get(ClaimState(from_state), set())
    return ClaimState(to_state) in allowed


def transition_name(from_state, to_state):
    """Render a transition the way traces record it, e.g. PROPOSED->CHALLENGED."""
    return "%s->%s" % (from_state, to_state)
