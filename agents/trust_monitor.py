"""
TrustMonitor: one instance per target robot, aggregating witness reports.
Each neighbor that can observe the target's claimed position casts an
independent vote on whether the claim is truthful.
"""

class TrustMonitor:
    def __init__(self, witness_threshold=3, consecutive_threshold=2):
        self.witness_threshold = witness_threshold
        self.consecutive_threshold = consecutive_threshold
        self.witness_reports = {}
        self.consensus_streak = 0

    def record_witness(self, witness_id, is_match, tick):
        if is_match is None:
            return
        self.witness_reports.setdefault(tick, {})[witness_id] = is_match

    def evaluate_for_quarantine(self, tick):
        reports = self.witness_reports.get(tick, {})
        mismatches = sum(1 for match in reports.values() if not match)

        if mismatches >= self.witness_threshold:
            self.consensus_streak += 1
        else:
            self.consensus_streak = 0

        keep_ticks = [t for t in self.witness_reports if t >= tick - 5]
        self.witness_reports = {t: self.witness_reports[t] for t in keep_ticks}

        return self.consensus_streak >= self.consecutive_threshold

    def witness_verdict(self, witness_robot, target_robot_id, claimed_pos, grid_world):
        if witness_robot.robot_id == target_robot_id:
            return None
        if claimed_pos is None:
            return None

        dist = abs(witness_robot.x - claimed_pos[0]) + abs(witness_robot.y - claimed_pos[1])
        if dist > getattr(witness_robot, "sensing_radius", 1):
            return None

        actual_robot = grid_world.cell_occupancy.get(claimed_pos)
        return actual_robot == target_robot_id