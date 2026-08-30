"""
RobotAgent (Person A): one instance per robot in the swarm.

Each robot only knows its OWN state and whatever its neighbors choose to
broadcast — nothing is shared through a central brain.

SwarmDock contract: emit RobotState via to_robot_state(tick). Auction logic
must skip any robot where status == "quarantined". Person B writes
trust_score / status="quarantined" only — this module never invents trust.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional, Dict, Any

from core.contracts import RobotState, RobotStatus, clamp_urgency
from core.state import StatePacket
from agents.fault_injection import FaultProfile

if TYPE_CHECKING:
    from core.config import SimConfig


class RobotAgent:
    is_liar = False

    def __init__(
        self,
        robot_id: str,
        x: int,
        y: int,
        package_urgency: int | float = 5,
        token_budget: float = 0.0,
        token_capacity: float | None = None,
        token_refill_rate: float = 0.5,
        status: RobotStatus | str = "active",
        sensing_radius: int = 1,
        fault_profile: Optional[FaultProfile] = None,
        config: SimConfig | None = None,
    ):
        self.robot_id = robot_id
        self.x = x
        self.y = y
        self.package_urgency = clamp_urgency(package_urgency)
        self.wait_time = 0
        self.quarantined = False
        self.token_budget = float(token_budget)
        self.token_capacity = float(token_capacity) if token_capacity is not None else max(float(token_budget), 10.0)
        self.token_refill_rate = float(token_refill_rate)
        self.status = status if status in ("active", "auctioning", "quarantined") else "active"
        self.sensing_radius = sensing_radius
        self.assigned_job_id = None
        self.carrying_package = False
        self.livelock_counter = 0
        self.last_intended_target = None
        self.fault_profile = fault_profile

        # SwarmDock contract fields (Person B owns trust_score / quarantined status)
        self.trust_score: float = 1.0

        self.config = config
        scale = config.starting_token_scale if config else 10.0
        self.starting_budget = float(self.package_urgency) * scale
        self.budget = self.starting_budget if token_budget == 0.0 else float(token_budget)
        self.heading = (0, 0)
        self.velocity = 0.0
        self.goal = None
        self.path: list = []
        self.done = False
        self.spawn_tick = 0
        self.finish_tick = None
        self.secret_key = os.urandom(16)

    # ------------------------------------------------------------------ #
    # SwarmDock contract
    # ------------------------------------------------------------------ #
    def to_robot_state(self, tick: int) -> RobotState:
        return RobotState(
            robot_id=self.robot_id,
            x=self.x,
            y=self.y,
            urgency=int(self.package_urgency),
            token_budget=float(self.budget),
            trust_score=float(self.trust_score),
            status=self.status,
            tick=tick,
        )

    def set_auctioning(self, active: bool) -> None:
        """Person A: mark contention without touching trust_score."""
        if self.status == "quarantined":
            return
        self.status = "auctioning" if active else "active"

    # ------------------------------------------------------------------ #
    # Broadcast & State
    # ------------------------------------------------------------------ #
    def broadcast_state(self, tick: Optional[int] = None) -> dict:
        """What this robot tells its neighbors. A liar robot would
        override this method to send false info — that's what the
        trust monitor is designed to catch."""
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

    def refill_tokens(self) -> None:
        """Gradually refill tokens each tick to prevent long-term starvation."""
        if self.quarantined:
            return
        if self.token_budget >= self.token_capacity:
            return
        refill = float(self.token_refill_rate)
        if self.wait_time > 0:
            refill += 0.1
        self.token_budget = min(self.token_capacity, self.token_budget + refill)

    def to_state(self):
        """Return a RobotState representation or schema."""
        try:
            from agents.robot_state import RobotState as LegacyRobotState
            return LegacyRobotState(
                robot_id=self.robot_id,
                x=self.x,
                y=self.y,
                urgency=float(self.package_urgency),
                wait_time=self.wait_time,
                quarantined=self.quarantined,
                token_budget=getattr(self, "token_budget", self.budget),
                token_capacity=self.token_capacity,
                token_refill_rate=self.token_refill_rate,
                status=str(self.status),
                sensing_radius=self.sensing_radius,
                livelock_counter=self.livelock_counter,
                meta={
                    "assigned_job_id": self.assigned_job_id,
                    "carrying_package": self.carrying_package,
                    "fault_profile": getattr(self.fault_profile, "description", None),
                },
            )
        except Exception:
            return {
                "robot_id": self.robot_id,
                "x": self.x,
                "y": self.y,
                "urgency": self.package_urgency,
                "wait_time": self.wait_time,
                "quarantined": self.quarantined,
                "token_budget": getattr(self, "token_budget", self.budget),
                "token_capacity": self.token_capacity,
                "token_refill_rate": self.token_refill_rate,
                "status": self.status,
                "sensing_radius": self.sensing_radius,
                "livelock_counter": self.livelock_counter,
                "meta": {
                    "assigned_job_id": self.assigned_job_id,
                    "carrying_package": self.carrying_package,
                    "fault_profile": getattr(self.fault_profile, "description", None),
                },
            }

    def desire_target(self, goal):
        """Return an ordered list of candidate (dx,dy) moves toward `goal`."""
        gx, gy = goal
        dx_needed = gx - self.x
        dy_needed = gy - self.y

        if dx_needed == 0 and dy_needed == 0:
            return []

        moves_in_order = []
        if abs(dx_needed) >= abs(dy_needed) and dx_needed != 0:
            moves_in_order.append((1 if dx_needed > 0 else -1, 0))
            if dy_needed != 0:
                moves_in_order.append((0, 1 if dy_needed > 0 else -1))
        elif dy_needed != 0:
            moves_in_order.append((0, 1 if dy_needed > 0 else -1))
            if dx_needed != 0:
                moves_in_order.append((1 if dx_needed > 0 else -1, 0))

        return moves_in_order

    def manhattan_dist(self, goal):
        gx, gy = goal
        return abs(gx - self.x) + abs(gy - self.y)

    def update_state_after_move(self, goal, moved: bool, attempted_target=None):
        """Simple FSM transitions."""
        if attempted_target is not None:
            if moved:
                self.livelock_counter = 0
            elif attempted_target == self.last_intended_target:
                self.livelock_counter += 1
            else:
                self.livelock_counter = 1
            self.last_intended_target = attempted_target

        if self.status == "navigate" or self.status == "active":
            if goal and self.manhattan_dist(goal) == 1:
                self.status = "approach"
        elif self.status == "approach":
            if attempted_target is not None:
                self.status = "auction"
        elif self.status == "auction":
            if moved:
                self.status = "cross"
        elif self.status == "cross":
            if moved:
                self.status = "resume"
        elif self.status == "resume":
            self.status = "active"

    def eta_to_next_intersection(self, goal, grid_world, max_steps=None):
        """Estimate ticks to the next intersection along the path."""
        if max_steps is None:
            max_steps = (grid_world.width * grid_world.height) + 1

        if grid_world.is_intersection(self.x, self.y):
            return 0

        sim_x, sim_y = self.x, self.y
        eta = 0
        steps = 0
        while steps < max_steps:
            gx, gy = goal
            dx_needed = gx - sim_x
            dy_needed = gy - sim_y
            if dx_needed == 0 and dy_needed == 0:
                return None

            moves_in_order = []
            if abs(dx_needed) >= abs(dy_needed) and dx_needed != 0:
                moves_in_order.append((1 if dx_needed > 0 else -1, 0))
                if dy_needed != 0:
                    moves_in_order.append((0, 1 if dy_needed > 0 else -1))
            elif dy_needed != 0:
                moves_in_order.append((0, 1 if dy_needed > 0 else -1))
                if dx_needed != 0:
                    moves_in_order.append((1 if dx_needed > 0 else -1, 0))

            if not moves_in_order:
                return None

            dx, dy = moves_in_order[0]
            sim_x += dx
            sim_y += dy
            eta += 1
            steps += 1

            if grid_world.is_intersection(sim_x, sim_y):
                return eta

        return None

    def compute_bid(self) -> float:
        """Token bid = urgency + wait bonus + livelock bonus."""
        return float(self.package_urgency) + 0.1 * self.wait_time + 0.2 * self.livelock_counter

    def step_forward(self, dx: int, dy: int, grid_world) -> bool:
        new_x, new_y = self.x + dx, self.y + dy
        if grid_world.is_free(new_x, new_y):
            grid_world.move_robot(self.robot_id, (self.x, self.y), (new_x, new_y))
            self.x, self.y = new_x, new_y
            self.heading = (dx, dy)
            self.velocity = 1.0
            self.wait_time = 0
            return True
        self.wait_time += 1
        self.velocity = 0.0
        return False

    def freeze(self) -> None:
        """Called by Person B trust layer when quarantine consensus fires."""
        self.quarantined = True
        self.status = "quarantined"

    # ------------------------------------------------------------------ #
    # decentralized-engine API
    # ------------------------------------------------------------------ #
    def compute_token_bid(self) -> float:
        cfg = self.config
        bonus = (cfg.wait_bid_bonus if cfg else 0.15) * self.wait_time
        return self.budget + bonus

    def build_packet(self, tick: int) -> StatePacket:
        cx, cy = self.claimed_position()
        packet = StatePacket(
            robot_id=self.robot_id,
            x=cx,
            y=cy,
            heading=self.heading,
            velocity=self.velocity,
            token_bid=self.compute_token_bid(),
            tick=tick,
            ttl=(self.config.packet_ttl if self.config else 2),
        )
        return packet.sign(self.secret_key)

    def claimed_position(self) -> tuple[int, int]:
        return (self.x, self.y)

    def plan_path(self, world, blocked=None) -> None:
        if self.goal is None:
            self.path = []
            return
        self.path = world.astar((self.x, self.y), self.goal, blocked=blocked)

    def next_cell(self, world, blocked=None):
        if self.goal is None or (self.x, self.y) == self.goal:
            return None
        blocked = set(blocked or set())
        need_replan = len(self.path) < 2 or self.path[0] != (self.x, self.y)
        if not need_replan and self.path[1] in blocked:
            need_replan = True
        if need_replan:
            self.plan_path(world, blocked=blocked)
        if len(self.path) >= 2:
            return self.path[1]
        return None

    def at_goal(self) -> bool:
        return self.goal is not None and (self.x, self.y) == self.goal
