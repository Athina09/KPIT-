from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class RobotState:
    """Canonical RobotState schema used across components.

    - Keep this schema stable once frozen in Week 4.
    - Fields chosen to match existing code and planned features.
    """
    robot_id: str
    x: int
    y: int
    urgency: float  # package urgency (higher = more urgent)
    wait_time: int = 0  # ticks spent waiting
    quarantined: bool = False
    token_budget: float = 0.0  # auction tokens currently held
    token_capacity: float = 0.0  # maximum token budget capacity
    token_refill_rate: float = 0.0  # tokens regained per tick when waiting
    status: str = "navigate"  # one of: navigate, approach, auction, cross, resume
    sensing_radius: int = 1  # local broadcast radius (cells)
    eta: Optional[int] = None  # estimated ticks to intersection, if known
    livelock_counter: int = 0  # repeated blocked attempts at the same target
    meta: Dict[str, Any] = field(default_factory=dict)  # extensible extra data


@dataclass
class Event:
    """Simple event envelope used for emitting system events.

    - `type` is a short event name, e.g. "auction_won", "robot_moved".
    - `tick` is the simulation tick when the event occurred.
    - `payload` contains event-specific fields.
    """
    type: str
    tick: int
    robot_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
