"""
Decentralized swarm engine (Person A ownership + Person B trust hook).

Per tick, with NO global planner or scheduler:

  1. every robot broadcasts a signed StatePacket to in-range neighbors
  2. Person B trust cross-verifies claimed vs sensed positions -> quarantine
  3. each active robot locally A*-replans toward its goal
  4. cell contention settled by local token auction (skips status==quarantined)
  5. token budgets regenerate; finished tasks are re-issued

Emits SwarmDock RobotState / Event contracts every tick.
"""

from __future__ import annotations

import random

from agents.auction import TokenAuction
from agents.comms import CommsBus
from agents.lying_robot_agent import LyingRobotAgent
from agents.robot_agent import RobotAgent
from agents.trust_monitor import DistributedTrust
from core.contracts import Event, clamp_urgency
from environment.grid_world import GridWorld
from sim.metrics import Metrics


class SwarmEngine:
    def __init__(self, config, fault_injector=None, verbose: bool = False):
        self.config = config
        self.verbose = verbose
        self.fault_injector = fault_injector
        self.rng = random.Random(config.seed)

        self.robots: dict = {}
        self.goals: dict = {}
        self.task_wait: dict = {}
        self.contend_ticks: dict = {}
        self.events: list[Event] = []
        self.server_alive = True  # swarm ignores server kill; flag kept for symmetry

        self._build()

        self.trust = DistributedTrust(config)
        self.auction = TokenAuction(config)
        self.comms = CommsBus(self.world, config)
        self.metrics = Metrics(mode="decentralized", num_honest=0)
        for r in self.robots.values():
            self.trust.ensure(r.robot_id)
            if not r.is_liar:
                self.metrics.num_honest += 1

    def _random_free_cell(self, world, taken):
        while True:
            c = (self.rng.randrange(world.width), self.rng.randrange(world.height))
            if c not in taken and world.is_walkable(*c):
                return c

    def _build(self):
        cfg = self.config
        pre = GridWorld(cfg.width, cfg.height, intersections=cfg.intersections())
        taken: set = set()
        starts, goals = [], []
        for _ in range(cfg.num_robots):
            s = self._random_free_cell(pre, taken)
            taken.add(s)
            starts.append(s)
        for _ in range(cfg.num_robots):
            g = self._random_free_cell(pre, taken | set(goals))
            goals.append(g)

        reserved = set(starts) | set(goals)
        self.world = GridWorld.from_config(cfg, reserved=reserved)

        for i in range(cfg.num_robots):
            rid = f"R{i+1}"
            sx, sy = starts[i]
            urgency = clamp_urgency(self.rng.randint(cfg.urgency_min, cfg.urgency_max))
            if i == cfg.fault_robot_index:
                robot = LyingRobotAgent(
                    rid, sx, sy, package_urgency=urgency,
                    lie_offset=cfg.fault_offset, config=cfg,
                )
                robot.lying_active = False
            else:
                robot = RobotAgent(rid, sx, sy, package_urgency=urgency, config=cfg)
            robot.goal = goals[i]
            self.world.place_robot(rid, sx, sy)
            self.robots[rid] = robot
            self.goals[rid] = goals[i]
            self.task_wait[rid] = 0
            self.contend_ticks[rid] = 0

    def _secret_keys(self) -> dict:
        return {rid: r.secret_key for rid, r in self.robots.items()}

    def _assign_new_task(self, robot) -> None:
        taken = {(r.x, r.y) for r in self.robots.values()}
        taken |= {self.goals[rid] for rid in self.goals}
        new_goal = self._random_free_cell(self.world, taken)
        robot.goal = new_goal
        self.goals[robot.robot_id] = new_goal
        robot.path = []
        self.task_wait[robot.robot_id] = 0

    def run(self, frame_sink=None):
        cfg = self.config
        for tick in range(cfg.max_ticks):
            if self.fault_injector:
                self.fault_injector.apply(tick, self.robots)
                if (cfg.fault_robot_index >= 0
                        and tick == cfg.fault_start_tick):
                    self.metrics.mark_fault_start(tick)

            # SwarmDock: server kill is a no-op for the decentralized swarm
            if (getattr(cfg, "server_kill_tick", -1) >= 0
                    and tick == cfg.server_kill_tick):
                self.events.append(
                    Event(type="server_killed", robot_id="SERVER", timestamp=float(tick))
                )
                # deliberately do NOT set server_alive=False — swarm has no server

            self._comms_and_trust(tick)
            self._movement_and_auction(tick)
            self.auction.regen(self.robots)

            if (self.metrics.fault_detect_tick is None
                    and cfg.fault_robot_index >= 0):
                liar_id = f"R{cfg.fault_robot_index + 1}"
                if self.trust.is_quarantined(liar_id):
                    self.metrics.mark_recovery_end(tick)

            active = sum(
                1 for r in self.robots.values()
                if r.status != "quarantined" and not r.at_goal()
            )
            self.metrics.record_tick(active)

            if frame_sink is not None:
                frame_sink(self.frame(tick))

            if self.verbose:
                self._print_tick(tick)

        self.metrics.ticks = cfg.max_ticks
        self.metrics.quarantined_ids = set(self.trust.quarantined)
        self.metrics.false_positive_ids = set(self.trust.false_positives)
        self.events.extend(self.trust.events)
        return self.metrics

    def _comms_and_trust(self, tick: int) -> None:
        self.comms.reset_tick()
        for robot in self.robots.values():
            self.comms.publish(robot.build_packet(tick))
        self.comms.deliver(self.robots)
        self.trust.evaluate(
            tick, self.robots, self.world, self.comms.delivered, self._secret_keys()
        )

    def _movement_and_auction(self, tick: int) -> None:
        avoid = self.trust.avoid_cells()

        desired = {}
        for rid, robot in self.robots.items():
            # SwarmDock rule: auction / movement skips quarantined robots
            if not self.auction.eligible(robot) or robot.at_goal():
                robot.set_auctioning(False)
                continue
            nxt = robot.next_cell(self.world, blocked=avoid)
            if nxt is not None:
                desired[rid] = nxt

        contenders_by_cell: dict = {}
        for rid, cell in desired.items():
            contenders_by_cell.setdefault(cell, []).append(rid)

        claimed: set = set()
        for cell, rids in contenders_by_cell.items():
            for rid in rids:
                self.robots[rid].set_auctioning(True)

            bids = [(rid, self.robots[rid].compute_token_bid()) for rid in rids]
            winner_id, loser_ids = self.auction.resolve_cell(bids)
            contested = len(rids) > 1

            winner = self.robots[winner_id]
            if self.world.is_free(*cell) and cell not in claimed:
                winner.step_forward(cell[0] - winner.x, cell[1] - winner.y, self.world)
                claimed.add(cell)
                if contested:
                    self.metrics.record_conflict(self.contend_ticks[winner_id] + 1)
                    self.events.append(
                        Event(type="auction_won", robot_id=winner_id, timestamp=float(tick))
                    )
                self.contend_ticks[winner_id] = 0
                winner.set_auctioning(False)
            else:
                winner.wait_time += 1
                self.task_wait[winner_id] += 1
                if contested:
                    self.contend_ticks[winner_id] += 1

            self.auction.settle(self.robots, winner_id, loser_ids)
            for lid in loser_ids:
                self.task_wait[lid] += 1
                if contested:
                    self.contend_ticks[lid] += 1
                self.robots[lid].set_auctioning(False)

        for rid, robot in self.robots.items():
            if not self.auction.eligible(robot):
                continue
            if robot.at_goal():
                self.metrics.record_task(self.task_wait[rid])
                self._assign_new_task(robot)

    def frame(self, tick: int) -> dict:
        return {
            "tick": tick,
            "width": self.world.width,
            "height": self.world.height,
            "obstacles": sorted(list(self.world.obstacles)),
            "intersections": sorted(list(self.world.intersection_cells)),
            "robots": {
                rid: r.to_robot_state(tick).to_dict() | {
                    "goal": self.goals[rid],
                    "bid": round(r.compute_token_bid(), 2),
                    "is_liar": r.is_liar,
                }
                for rid, r in self.robots.items()
            },
            "events": [e.to_dict() for e in self.events if int(e.timestamp) == tick],
            "tasks_completed": self.metrics.tasks_completed,
        }

    def _print_tick(self, tick: int) -> None:
        q = sorted(self.trust.quarantined)
        print(f"tick {tick:3d} | tasks={self.metrics.tasks_completed:3d} "
              f"| quarantined={q if q else '-'}")
