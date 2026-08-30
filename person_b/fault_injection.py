"""
fault_injection.py — Person B stub (Week 1).

Will own: lying-robot injection and server-kill fault scheduling so we can
measure recovery time and prove the >=80% throughput gate.

TODO (later steps): activate_liar(tick), kill_server(tick).
"""

from __future__ import annotations

from typing import Any


class FaultInjector:
    """Stub — schedules Byzantine / server-kill faults for experiments."""

    def __init__(
        self,
        liar_robot_id: str | None = None,
        liar_start_tick: int = 20,
        server_kill_tick: int | None = None,
    ) -> None:
        self.liar_robot_id = liar_robot_id
        self.liar_start_tick = liar_start_tick
        self.server_kill_tick = server_kill_tick

    def apply(self, tick: int, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Mutate or annotate states for this tick; return any fault Events.

        Stub: not implemented yet.
        """
        raise NotImplementedError(
            "fault_injection.apply — Week 1 stub; implement next step"
        )
