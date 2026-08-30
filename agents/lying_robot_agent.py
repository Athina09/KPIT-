"""
LyingRobotAgent: a robot that broadcasts a FALSE position while its real
position (in the grid world) stays accurate. Simulates a faulty sensor or a
malicious/compromised robot. Used to test that the trust layer catches it.

`lying_active` lets the fault-injection tool switch the lie on at a chosen tick,
so we can measure fault-detection latency and throughput dip from a clean start.
"""

from __future__ import annotations

from typing import Optional
from agents.robot_agent import RobotAgent
from agents.fault_injection import FaultProfile


class LyingRobotAgent(RobotAgent):
    is_liar = True

    def __init__(
        self,
        robot_id: str,
        x: int,
        y: int,
        package_urgency: int | float = 1.0,
        token_budget: float = 0.0,
        token_capacity: float | None = None,
        token_refill_rate: float = 0.5,
        status: str = "active",
        sensing_radius: int = 1,
        lie_offset: tuple[int, int] = (2, 2),
        fault_profile: Optional[FaultProfile] = None,
        config=None,
    ):
        super().__init__(
            robot_id=robot_id,
            x=x,
            y=y,
            package_urgency=package_urgency,
            token_budget=token_budget,
            token_capacity=token_capacity,
            token_refill_rate=token_refill_rate,
            status=status,
            sensing_radius=sensing_radius,
            fault_profile=fault_profile,
            config=config,
        )
        self.lie_offset = lie_offset
        self.lying_active = True   # fault injector can toggle this per tick

    def claimed_position(self) -> tuple[int, int]:
        if not self.lying_active:
            return (self.x, self.y)
        return (self.x + self.lie_offset[0], self.y + self.lie_offset[1])

    def broadcast_state(self, tick: Optional[int] = None) -> dict:
        cx, cy = self.claimed_position()
        payload = {
            "robot_id": self.robot_id,
            "x": cx,
            "y": cy,
            "urgency": self.package_urgency,
            "status": self.status,
            "token_budget": getattr(self, "token_budget", self.budget),
            "assigned_job_id": self.assigned_job_id,
            "carrying_package": self.carrying_package,
        }
        if self.fault_profile is not None:
            return self.fault_profile.apply(payload, self, tick=tick)
        return payload
