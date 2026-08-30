"""
trust.py — Person B stub (Week 1).

Will own: distrust counters, neighbor cross-verification, multi-witness
quarantine consensus. Writes only trust_score and status="quarantined"
on RobotState — never moves robots or resolves auctions.

TODO (later steps): implement score_neighbor / vote_quarantine.
"""

from __future__ import annotations

from typing import Any


class TrustMonitor:
    """Stub — deterministic trust layer, no LLM calls."""

    def __init__(self, mismatch_threshold: int = 3) -> None:
        self.mismatch_threshold = mismatch_threshold
        # robot_id -> consecutive mismatch count (to be filled in)
        self.distrust_counts: dict[str, int] = {}

    def update(self, states: list[dict[str, Any]], tick: int) -> list[dict[str, Any]]:
        """
        Inspect a tick of RobotState dicts; return Event dicts (e.g. quarantine).

        Stub: returns no events yet.
        """
        raise NotImplementedError("trust.update — Week 1 stub; implement next step")
