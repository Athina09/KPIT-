"""
SwarmDock shared data contract.

Person A's sim engine emits RobotState / Event in exactly this shape.
Person B's trust layer writes trust_score and flips status to "quarantined"
— it never moves robots or resolves auctions.

DO NOT change field names without telling the other person.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RobotStatus = Literal["active", "auctioning", "quarantined"]
EventType = Literal["auction_won", "quarantine", "server_killed"]


@dataclass
class RobotState:
    robot_id: str
    x: int
    y: int
    urgency: int              # 1-10
    token_budget: float
    trust_score: float        # owned/written by Person B
    status: RobotStatus       # "active" | "auctioning" | "quarantined"
    tick: int

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_quarantined(self) -> bool:
        return self.status == "quarantined"


@dataclass
class Event:
    type: EventType           # "auction_won" | "quarantine" | "server_killed"
    robot_id: str
    timestamp: float          # tick as float seconds (1 tick == 1s)

    def to_dict(self) -> dict:
        return asdict(self)


def clamp_urgency(value: int | float) -> int:
    """Map any urgency into the SwarmDock 1–10 integer contract."""
    return max(1, min(10, int(round(float(value)))))
