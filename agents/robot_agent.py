from typing import Optional
from agents.fault_injection import FaultProfile

"""
RobotAgent: one instance per robot in the swarm.
Each robot only knows its OWN state and whatever its neighbors
choose to broadcast — nothing is shared through a central brain.
"""

class RobotAgent:
    def __init__(self, robot_id, x, y, package_urgency=1.0, token_budget=0.0,
                 token_capacity=None, token_refill_rate=0.5,
                 status="navigate", sensing_radius=1,
                 fault_profile: Optional[FaultProfile] = None):
        self.robot_id = robot_id
        self.x = x
        self.y = y
        self.package_urgency = package_urgency  # higher = more urgent
        self.wait_time = 0  # ticks spent waiting, prevents starvation
        self.quarantined = False
        self.token_budget = token_budget
        self.token_capacity = token_capacity if token_capacity is not None else max(token_budget, 10.0)
        self.token_refill_rate = token_refill_rate
        self.status = status
        self.sensing_radius = sensing_radius
        self.assigned_job_id = None
        self.carrying_package = False
        self.livelock_counter = 0
        self.last_intended_target = None
        self.fault_profile = fault_profile

    def broadcast_state(self, tick=None):
        """What this robot tells its neighbors. A liar robot would
        override this method to send false info — that's what the
        trust monitor is designed to catch."""
        payload = {
            "robot_id": self.robot_id,
            "x": self.x,
            "y": self.y,
            "urgency": self.package_urgency,
            "status": self.status,
            "token_budget": self.token_budget,
            "assigned_job_id": self.assigned_job_id,
            "carrying_package": self.carrying_package,
        }
        if self.fault_profile is not None:
            return self.fault_profile.apply(payload, self, tick=tick)
        return payload

    def refill_tokens(self):
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
        """Return a RobotState dataclass (agents.robot_state.RobotState)."""
        try:
            from agents.robot_state import RobotState
        except Exception:
            # graceful fallback if schema module is unavailable
            return {
                "robot_id": self.robot_id,
                "x": self.x,
                "y": self.y,
                "urgency": self.package_urgency,
                "wait_time": self.wait_time,
                "quarantined": self.quarantined,
                "token_budget": getattr(self, "token_budget", 0.0),
                "token_capacity": getattr(self, "token_capacity", 0.0),
                "token_refill_rate": getattr(self, "token_refill_rate", 0.0),
                "status": getattr(self, "status", "navigate"),
                "sensing_radius": getattr(self, "sensing_radius", 1),
                "livelock_counter": self.livelock_counter,
                "meta": {
                    "assigned_job_id": self.assigned_job_id,
                    "carrying_package": self.carrying_package,
                    "fault_profile": getattr(self.fault_profile, "description", None),
                },
            }

    def desire_target(self, goal):
        """Return an ordered list of candidate (dx,dy) moves toward `goal`.

        This mirrors the greedy_step heuristic used by the simulator and
        is intended to let higher-level code collect movement intents
        and run auctions when multiple robots target the same cell.
        """
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
        """Simple FSM transitions:

        - navigate -> approach when adjacent to goal
        - approach -> auction when a target is being contested (simulator can set status)
        - auction -> cross when move succeeded
        - cross -> resume -> navigate after crossing
        This helper is deliberately small; the simulator/scheduler will drive
        auction decisions and set statuses when required.
        """
        if attempted_target is not None:
            if moved:
                self.livelock_counter = 0
            elif attempted_target == self.last_intended_target:
                self.livelock_counter += 1
            else:
                self.livelock_counter = 1
            self.last_intended_target = attempted_target

        if self.status == "navigate":
            if self.manhattan_dist(goal) == 1:
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
            self.status = "navigate"

    def eta_to_next_intersection(self, goal, grid_world, max_steps=None):
        """Estimate ticks (steps) to the next intersection along the greedy path.

        Simulates greedy moves (using `desire_target`) without changing
        agent state, stopping when an intersection cell is reached or the
        goal is reached. Returns integer ETA (0 if already on intersection),
        or None if no intersection is reachable within `max_steps`.
        """
        if max_steps is None:
            max_steps = (grid_world.width * grid_world.height) + 1

        # If already on intersection, ETA is 0
        if grid_world.is_intersection(self.x, self.y):
            return 0

        # simulate steps
        sim_x, sim_y = self.x, self.y
        eta = 0
        steps = 0
        while steps < max_steps:
            # compute candidate moves from simulated position toward goal
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

    def compute_bid(self):
        """Token bid = urgency + a small bonus for how long it's waited.
        The wait_time term stops a low-urgency robot from being blocked
        forever by higher-urgency robots (starvation)."""
        return self.package_urgency + 0.1 * self.wait_time + 0.2 * self.livelock_counter

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