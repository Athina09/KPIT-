"""
Trust & anomaly detection (Person B: Byzantine position verification).

Two layers live here:

  * TrustMonitor      -- the per-robot mismatch counter and witness-quorum evaluator,
                         kept so legacy simulate.py / swarm_simulate.py demos run.

  * DistributedTrust  -- Person B ownership: writes trust_score and flips
                         status to "quarantined" on RobotState. Never moves
                         robots or resolves auctions.
"""

from __future__ import annotations

from core.contracts import Event


class TrustMonitor:
    """Compares robot broadcasts to ground truth and evaluates witness reports."""

    def __init__(self, mismatch_threshold: int = 3, witness_threshold: int = 3, consecutive_threshold: int = 2):
        self.mismatch_threshold = mismatch_threshold
        self.witness_threshold = witness_threshold
        self.consecutive_threshold = consecutive_threshold
        self.mismatch_counts: dict[str, int] = {}
        self.witness_reports: dict[int, dict[str, bool]] = {}
        self.consensus_streak = 0

    def check(self, broadcast: dict, grid_world) -> bool:
        robot_id = broadcast["robot_id"]
        claimed_pos = (broadcast["x"], broadcast["y"])
        real_pos = grid_world.ground_truth_position(robot_id)

        if claimed_pos != real_pos:
            self.mismatch_counts[robot_id] = self.mismatch_counts.get(robot_id, 0) + 1
        else:
            self.mismatch_counts[robot_id] = 0

        return self.mismatch_counts[robot_id] >= self.mismatch_threshold

    def is_quarantined(self, robot_id: str) -> bool:
        return self.mismatch_counts.get(robot_id, 0) >= self.mismatch_threshold

    def record_witness(self, witness_id: str, is_match: bool | None, tick: int) -> None:
        if is_match is None:
            return
        self.witness_reports.setdefault(tick, {})[witness_id] = is_match

    def evaluate_for_quarantine(self, tick: int) -> bool:
        reports = self.witness_reports.get(tick, {})
        mismatches = sum(1 for match in reports.values() if not match)

        if mismatches >= self.witness_threshold:
            self.consensus_streak += 1
        else:
            self.consensus_streak = 0

        keep_ticks = [t for t in self.witness_reports if t >= tick - 5]
        self.witness_reports = {t: self.witness_reports[t] for t in keep_ticks}

        return self.consensus_streak >= self.consecutive_threshold

    def witness_verdict(self, witness_robot, target_robot_id: str, claimed_pos: tuple[int, int] | None, grid_world) -> bool | None:
        if witness_robot.robot_id == target_robot_id:
            return None
        if claimed_pos is None:
            return None

        dist = abs(witness_robot.x - claimed_pos[0]) + abs(witness_robot.y - claimed_pos[1])
        if dist > getattr(witness_robot, "sensing_radius", 1):
            return None

        actual_robot = grid_world.cell_occupancy.get(claimed_pos)
        return actual_robot == target_robot_id


class DistributedTrust:
    """
    Fleet-wide trust state assembled from purely local observations.

    Person B contract: only mutates robot.trust_score and robot.status
    (via freeze / reinstatement). Never calls step_forward or auction settle.
    """

    def __init__(self, config):
        self.config = config
        self.reputation: dict[str, float] = {}
        self.quarantined: set[str] = set()
        self.last_good_pos: dict[str, tuple[int, int]] = {}
        self.first_flag_tick: dict[str, int] = {}
        self.quarantine_tick: dict[str, int] = {}
        self.false_positives: set[str] = set()
        self.events: list[Event] = []

    def ensure(self, robot_id: str) -> None:
        if robot_id not in self.reputation:
            self.reputation[robot_id] = self.config.reputation_start

    def evaluate(self, tick: int, robots: dict, world, delivered_packets: dict, secret_keys: dict) -> dict:
        cfg = self.config
        scores = {}
        voters = {}
        clean_voters = {}

        for observer_id, observer in robots.items():
            if getattr(observer, "status", None) == "quarantined" or observer.quarantined:
                continue
            sensed = world.robots_within(observer.x, observer.y, cfg.comm_range)
            for packet in delivered_packets.get(observer_id, []):
                about = packet.robot_id
                key = secret_keys.get(about)
                if key is None or not packet.verify(key):
                    self._add_vote(scores, voters, about, observer_id, weight=2.0)
                    continue
                if about not in sensed:
                    continue
                real = sensed[about]
                claimed = packet.pos
                dist = ((real[0] - claimed[0]) ** 2 + (real[1] - claimed[1]) ** 2) ** 0.5
                if dist > cfg.mismatch_tolerance:
                    w = self.reputation.get(observer_id, cfg.reputation_start)
                    self._add_vote(scores, voters, about, observer_id, weight=w)
                else:
                    clean_voters.setdefault(about, set()).add(observer_id)

        self._apply(tick, scores, voters, clean_voters, robots, world)
        return scores

    def _add_vote(self, scores: dict, voters: dict, about: str, reporter: str, weight: float) -> None:
        scores[about] = scores.get(about, 0.0) + weight
        voters.setdefault(about, set()).add(reporter)

    def _apply(self, tick: int, scores: dict, voters: dict, clean_voters: dict, robots: dict, world) -> None:
        cfg = self.config

        for rid, robot in robots.items():
            self.ensure(rid)
            score = scores.get(rid, 0.0)
            n_flag = len(voters.get(rid, ()))
            n_clean = len(clean_voters.get(rid, ()))
            n_witnesses = max(1, n_flag + n_clean)
            vote_fraction = n_flag / n_witnesses

            flagged = (
                score >= cfg.quarantine_score_threshold
                and vote_fraction >= cfg.quarantine_vote_fraction
            )
            verified_clean = (not flagged) and n_clean > 0

            if flagged:
                self.reputation[rid] = max(0.0, self.reputation[rid] - cfg.reputation_penalty)
                if tick is not None and rid not in self.first_flag_tick:
                    self.first_flag_tick[rid] = tick
            elif verified_clean:
                self.reputation[rid] = min(
                    cfg.reputation_start, self.reputation[rid] + cfg.reputation_recovery
                )
                truth = world.ground_truth_position(rid)
                if truth is not None:
                    self.last_good_pos[rid] = truth

            # Person B writes trust_score + status only — never moves the robot.
            robot.trust_score = self.reputation[rid]

            if self.reputation[rid] <= cfg.reputation_quarantine_at and rid not in self.quarantined:
                self.quarantined.add(rid)
                robot.freeze()  # sets status="quarantined"
                if tick is not None:
                    self.quarantine_tick[rid] = tick
                    self.events.append(
                        Event(type="quarantine", robot_id=rid, timestamp=float(tick))
                    )
                if not getattr(robot, "is_liar", False):
                    self.false_positives.add(rid)
            elif (
                cfg.allow_reinstatement
                and rid in self.quarantined
                and self.reputation[rid] >= cfg.reputation_reinstate_at
            ):
                self.quarantined.discard(rid)
                robot.quarantined = False
                robot.status = "active"
                robot.trust_score = self.reputation[rid]

    def avoid_cells(self) -> set[tuple[int, int]]:
        return {self.last_good_pos[rid] for rid in self.quarantined if rid in self.last_good_pos}

    def is_quarantined(self, robot_id: str) -> bool:
        return robot_id in self.quarantined
