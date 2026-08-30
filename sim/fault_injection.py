"""
Fault injection (Person B + shared harness).

Two fault modes:

  1. Lying robot — a chosen robot starts broadcasting a false position at
     `start_tick` so the trust layer can be measured for recovery time.
  2. Server kill — the centralized baseline's "server" is marked dead at
     `server_kill_tick`. The swarm ignores this; the baseline deadlocks.
"""

from __future__ import annotations

from agents.lying_robot_agent import LyingRobotAgent
from core.contracts import Event


class FaultInjector:
    """Lying-robot injector used by the decentralized swarm."""

    def __init__(self, robot_index: int, start_tick: int, offset=(2, 2)):
        self.robot_id = f"R{robot_index + 1}" if robot_index >= 0 else None
        self.start_tick = start_tick
        self.offset = offset
        self._activated = False

    @classmethod
    def from_config(cls, config):
        if config.fault_robot_index < 0:
            return None
        return cls(config.fault_robot_index, config.fault_start_tick, config.fault_offset)

    def apply(self, tick: int, robots: dict) -> Event | None:
        if self.robot_id is None or self._activated:
            return None
        if tick >= self.start_tick and self.robot_id in robots:
            robot = robots[self.robot_id]
            if isinstance(robot, LyingRobotAgent):
                robot.lie_offset = self.offset
                robot.lying_active = True
                self._activated = True
        return None


class ServerKillInjector:
    """
    Marks the centralized scheduler as dead. Swarm engines ignore this.

    When applied to CentralizedEngine, movement stops permanently (deadlock).
    Emits a SwarmDock Event(type="server_killed").
    """

    def __init__(self, kill_tick: int):
        self.kill_tick = kill_tick
        self._activated = False

    @classmethod
    def from_config(cls, config):
        if getattr(config, "server_kill_tick", -1) < 0:
            return None
        return cls(config.server_kill_tick)

    def apply(self, tick: int, engine) -> Event | None:
        if self._activated or tick < self.kill_tick:
            return None
        self._activated = True
        engine.server_alive = False
        return Event(type="server_killed", robot_id="SERVER", timestamp=float(tick))
