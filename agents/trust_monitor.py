"""
TrustMonitor: one instance per robot, checking its neighbors.
Compares what a neighbor SAYS its position is (broadcast_state)
against what the grid world ACTUALLY has recorded (ground truth).
A mismatch a few times in a row = quarantine that robot.
"""

class TrustMonitor:
    def __init__(self, mismatch_threshold=3):
        self.mismatch_threshold = mismatch_threshold
        self.mismatch_counts = {}

    def check(self, broadcast, grid_world):
        robot_id = broadcast["robot_id"]
        claimed_pos = (broadcast["x"], broadcast["y"])
        real_pos = grid_world.ground_truth_position(robot_id)

        if claimed_pos != real_pos:
            self.mismatch_counts[robot_id] = self.mismatch_counts.get(robot_id, 0) + 1
        else:
            self.mismatch_counts[robot_id] = 0

        return self.mismatch_counts[robot_id] >= self.mismatch_threshold

    def is_quarantined(self, robot_id):
        return self.mismatch_counts.get(robot_id, 0) >= self.mismatch_threshold