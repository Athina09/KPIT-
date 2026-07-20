from agents.robot_agent import RobotAgent


class LyingRobotAgent(RobotAgent):
    """A robot that broadcasts a FALSE position to its neighbors,
    while its real position (in the grid world) stays accurate.
    This simulates a faulty sensor or a malicious/compromised robot.
    Used only to test that TrustMonitor catches it."""

    def __init__(self, robot_id, x, y, package_urgency=1.0, lie_offset=(2, 2)):
        super().__init__(robot_id, x, y, package_urgency)
        self.lie_offset = lie_offset

    def broadcast_state(self):
        # reports a position that is deliberately wrong
        fake_x = self.x + self.lie_offset[0]
        fake_y = self.y + self.lie_offset[1]
        return {
            "robot_id": self.robot_id,
            "x": fake_x,
            "y": fake_y,
            "urgency": self.package_urgency,
        }