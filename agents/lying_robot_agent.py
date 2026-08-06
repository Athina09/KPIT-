from typing import Optional
from agents.robot_agent import RobotAgent
from agents.fault_injection import FaultProfile


class LyingRobotAgent(RobotAgent):
    """A robot that broadcasts a FALSE position to its neighbors,
    while its real position (in the grid world) stays accurate.
    This simulates a faulty sensor or a malicious/compromised robot.
    Used only to test that TrustMonitor catches it."""

    def __init__(self, robot_id, x, y, package_urgency=1.0,
                 token_budget=0.0, token_capacity=None, token_refill_rate=0.5,
                 status="navigate", sensing_radius=1, lie_offset=(2, 2),
                 fault_profile: Optional[FaultProfile] = None):
        super().__init__(
            robot_id,
            x,
            y,
            package_urgency=package_urgency,
            token_budget=token_budget,
            token_capacity=token_capacity,
            token_refill_rate=token_refill_rate,
            status=status,
            sensing_radius=sensing_radius,
            fault_profile=fault_profile,
        )
        self.lie_offset = lie_offset

    def broadcast_state(self, tick=None):
        payload = super().broadcast_state(tick=tick)
        if self.fault_profile is not None:
            return self.fault_profile.apply(payload, self, tick=tick)

        # reports a position that is deliberately wrong
        fake_x = self.x + self.lie_offset[0]
        fake_y = self.y + self.lie_offset[1]
        return {
            "robot_id": self.robot_id,
            "x": fake_x,
            "y": fake_y,
            "urgency": self.package_urgency,
        }