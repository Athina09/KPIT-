"""
Central configuration for the decentralized swarm simulation.

A single SimConfig object is threaded through every subsystem so that
experiments (swarm vs. centralized baseline, fault-injection runs, etc.)
are reproducible from one place.
"""

from dataclasses import dataclass, field


@dataclass
class SimConfig:
    # --- world ---
    width: int = 12
    height: int = 12
    num_robots: int = 8
    obstacle_density: float = 0.06          # fraction of cells that are walls
    intersection_stride: int = 3            # every Nth row/col is a corridor -> intersections at crossings
    seed: int = 42
    max_ticks: int = 200

    # --- package urgency distribution (SwarmDock: int 1-10) ---
    urgency_min: int = 1
    urgency_max: int = 10

    # --- SwarmDock success-criteria knobs ---
    recovery_max_seconds: float = 10.0      # lying-robot recovery must complete within this
    recovery_throughput_ratio: float = 0.80 # swarm ≥ this fraction of central during recovery
    server_kill_tick: int = -1              # -1 = off; else tick when central "server" dies

    # --- token economics (Feature 1) ---
    starting_token_scale: float = 10.0      # starting_budget = urgency * this
    bid_cost_on_win: float = 1.0            # tokens spent when a robot wins right-of-way
    refund_on_loss: float = 0.5             # tokens refunded to a loser (anti-starvation)
    decay_recovery_per_tick: float = 0.25   # passive budget regen per tick
    wait_bid_bonus: float = 0.15            # bid += this * wait_time (bounds worst-case delay)
    max_budget_multiplier: float = 1.5      # cap budget at starting_budget * this

    # --- communication layer (Feature 2) ---
    comm_range: float = 4.0                 # Euclidean neighbor sensing radius
    packet_ttl: int = 2                     # gossip time-to-live (hops kept in local cache)

    # --- trust / Byzantine detection (Feature 3) ---
    mismatch_tolerance: float = 0.9         # sensed-vs-claimed distance under this = agreement
    quarantine_vote_fraction: float = 0.5   # fraction of WITNESSING neighbors that must flag it
    quarantine_score_threshold: float = 1.0 # aggregated discrepancy score needed (>=1 witness)
    reputation_start: float = 1.0
    reputation_penalty: float = 0.34        # per confirmed-mismatch tick
    reputation_recovery: float = 0.08       # per clean tick
    reputation_quarantine_at: float = 0.2   # reputation floor that triggers quarantine
    reputation_reinstate_at: float = 0.7    # reputation needed to rejoin (if recovery enabled)
    allow_reinstatement: bool = True

    # --- fault injection (Feature 5) ---
    fault_robot_index: int = -1             # -1 = none; otherwise which robot lies
    fault_start_tick: int = 5
    fault_offset: tuple = (2, 2)            # false-position delta

    def rng_seed(self) -> int:
        return self.seed

    def intersections(self):
        """Cells that sit at the crossing of two corridors."""
        xs = [x for x in range(self.width) if x % self.intersection_stride == 0]
        ys = [y for y in range(self.height) if y % self.intersection_stride == 0]
        return {(x, y) for x in xs for y in ys}
