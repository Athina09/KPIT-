"""
Centralized baseline (Person A: comparison scheduler).

Same grid / robots / urgencies / tasks as the swarm, but every move is
arbitrated by a single global "server":

  * one central planner computes A* for all robots
  * conflicts resolved by global urgency priority + reservation table
  * when ServerKillInjector fires, server_alive becomes False and the
    fleet deadlocks (no further moves) — proving the single point of failure
    the SwarmDock success criteria require.
"""

from __future__ import annotations

import random

from core.contracts import Event
from sim.engine import SwarmEngine
from sim.fault_injection import ServerKillInjector
from sim.metrics import Metrics


class CentralizedEngine:
    def __init__(self, config, verbose: bool = False, server_kill: bool = True):
        self.config = config
        self.verbose = verbose
        self.server_alive = True
        self.events: list[Event] = []

        seed_engine = SwarmEngine(config)
        self.world = seed_engine.world
        self.robots = seed_engine.robots
        self.goals = dict(seed_engine.goals)

        self.rng = random.Random(config.seed + 1)
        self.task_wait = {rid: 0 for rid in self.robots}
        self.contend_ticks = {rid: 0 for rid in self.robots}
        self.metrics = Metrics(
            mode="centralized",
            num_honest=sum(1 for r in self.robots.values() if not r.is_liar),
        )
        self.kill_injector = (
            ServerKillInjector.from_config(config) if server_kill else None
        )

    def _random_free_cell(self, taken):
        while True:
            c = (self.rng.randrange(self.world.width), self.rng.randrange(self.world.height))
            if c not in taken and self.world.is_walkable(*c):
                return c

    def _assign_new_task(self, robot) -> None:
        taken = {(r.x, r.y) for r in self.robots.values()} | set(self.goals.values())
        g = self._random_free_cell(taken)
        robot.goal = g
        self.goals[robot.robot_id] = g
        robot.path = []
        self.task_wait[robot.robot_id] = 0

    def run(self, frame_sink=None):
        cfg = self.config
        tasks_at_kill: int | None = None

        for tick in range(cfg.max_ticks):
            if self.kill_injector:
                evt = self.kill_injector.apply(tick, self)
                if evt is not None:
                    self.events.append(evt)
                    self.metrics.server_killed = True
                    self.metrics.server_kill_tick = tick
                    tasks_at_kill = self.metrics.tasks_completed

            # Server dead -> full deadlock (success criterion #4)
            if not self.server_alive:
                active = sum(1 for r in self.robots.values() if not r.at_goal())
                self.metrics.record_tick(active)
                if frame_sink is not None:
                    frame_sink(self._frame(tick))
                if self.verbose:
                    print(f"tick {tick:3d} | DEADLOCKED (server killed)")
                continue

            desired = {}
            for rid, robot in self.robots.items():
                if robot.at_goal():
                    continue
                nxt = robot.next_cell(self.world, blocked=None)
                if nxt is not None:
                    desired[rid] = nxt

            order = sorted(
                desired.keys(),
                key=lambda rid: self.robots[rid].package_urgency,
                reverse=True,
            )
            reserved: set = set()
            contested_cells: dict = {}
            for rid in desired:
                contested_cells.setdefault(desired[rid], []).append(rid)

            for rid in order:
                robot = self.robots[rid]
                cell = desired[rid]
                is_contested = len(contested_cells[cell]) > 1
                if self.world.is_free(*cell) and cell not in reserved:
                    robot.step_forward(cell[0] - robot.x, cell[1] - robot.y, self.world)
                    reserved.add(cell)
                    if is_contested:
                        self.metrics.record_conflict(self.contend_ticks[rid] + 1)
                        self.events.append(
                            Event(type="auction_won", robot_id=rid, timestamp=float(tick))
                        )
                    self.contend_ticks[rid] = 0
                else:
                    robot.wait_time += 1
                    self.task_wait[rid] += 1
                    if is_contested:
                        self.contend_ticks[rid] += 1

            for rid, robot in self.robots.items():
                if robot.at_goal():
                    self.metrics.record_task(self.task_wait[rid])
                    self._assign_new_task(robot)

            active = sum(1 for r in self.robots.values() if not r.at_goal())
            self.metrics.record_tick(active)
            if frame_sink is not None:
                frame_sink(self._frame(tick))
            if self.verbose:
                print(f"tick {tick:3d} | tasks={self.metrics.tasks_completed:3d} (central)")

        self.metrics.ticks = cfg.max_ticks
        if tasks_at_kill is not None:
            self.metrics.tasks_after_server_kill = (
                self.metrics.tasks_completed - tasks_at_kill
            )
        return self.metrics

    def _frame(self, tick: int) -> dict:
        return {
            "tick": tick,
            "width": self.world.width,
            "height": self.world.height,
            "obstacles": sorted(list(self.world.obstacles)),
            "intersections": sorted(list(self.world.intersection_cells)),
            "server_alive": self.server_alive,
            "robots": {
                rid: r.to_robot_state(tick).to_dict() | {
                    "goal": self.goals[rid],
                    "is_liar": r.is_liar,
                }
                for rid, r in self.robots.items()
            },
            "tasks_completed": self.metrics.tasks_completed,
        }
