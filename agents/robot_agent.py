"""
RobotAgent: one instance per robot in the swarm.
Each robot only knows its OWN state and whatever its neighbors
choose to broadcast — nothing is shared through a central brain.
"""

class RobotAgent:
    def __init__(self, robot_id, x, y, package_urgency=1.0):
        self.robot_id = robot_id
        self.x = x
        self.y = y
        self.package_urgency = package_urgency  # higher = more urgent
        self.wait_time = 0  # ticks spent waiting, prevents starvation
        self.quarantined = False

    def broadcast_state(self):
        """What this robot tells its neighbors. A liar robot would
        override this method to send false info — that's what the
        trust monitor is designed to catch."""
        return {
            "robot_id": self.robot_id,
            "x": self.x,
            "y": self.y,
            "urgency": self.package_urgency,
        }

    def compute_bid(self):
        """Token bid = urgency + a small bonus for how long it's waited.
        The wait_time term stops a low-urgency robot from being blocked
        forever by higher-urgency robots (starvation)."""
        return self.package_urgency + 0.1 * self.wait_time

    def step_forward(self, dx, dy, grid_world):
        new_x, new_y = self.x + dx, self.y + dy
        if grid_world.is_free(new_x, new_y):
            grid_world.move_robot(self.robot_id, (self.x, self.y), (new_x, new_y))
            self.x, self.y = new_x, new_y
            self.wait_time = 0
            return True
        else:
            self.wait_time += 1
            return False

    def freeze(self):
        """Called when the trust monitor quarantines this robot."""
        self.quarantined = True