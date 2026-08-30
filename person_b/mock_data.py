"""
mock_data.py — fake but realistic RobotState streams for Person B.

Use this to build and unit-test trust / metrics / fault logic without waiting
on Person A's live sim output. Shapes match the shared SwarmDock contract.
"""

from __future__ import annotations

import random
from typing import Any, Literal

RobotStatus = Literal["active", "auctioning", "quarantined"]

# Grid used only for plausible x/y ranges in mock data (not Person A's world).
DEFAULT_WIDTH = 12
DEFAULT_HEIGHT = 12


def generate_mock_tick(
    n_robots: int,
    tick: int,
    *,
    seed: int | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    liar_id: str | None = None,
    liar_start_tick: int = 20,
) -> list[dict[str, Any]]:
    """
    Produce a list of RobotState dicts for one tick.

    Parameters
    ----------
    n_robots:
        Number of robots (ids R1..Rn).
    tick:
        Simulation tick (also written into each RobotState).
    seed:
        Optional RNG seed. If None, derived from (n_robots, tick) so the
        same call is reproducible without forcing a global seed.
    width, height:
        Bounds for x/y (exclusive upper bound).
    liar_id:
        If set (e.g. "R3"), that robot's trust_score decays after
        liar_start_tick to simulate a detectable Byzantine broadcast.
        Positions stay in-bounds; trust_score is what Person B would update.
    liar_start_tick:
        Tick at which the liar begins looking untrustworthy in the mock.

    Returns
    -------
    list[dict]
        RobotState dicts matching the shared contract.
    """
    if n_robots < 1:
        raise ValueError("n_robots must be >= 1")
    if tick < 0:
        raise ValueError("tick must be >= 0")

    rng = random.Random(seed if seed is not None else (n_robots * 10_000 + tick))

    states: list[dict[str, Any]] = []
    for i in range(1, n_robots + 1):
        robot_id = f"R{i}"
        urgency = rng.randint(1, 10)
        # Budget scales with urgency; small jitter so auctions look contested.
        token_budget = round(urgency * 10.0 + rng.uniform(-2.0, 2.0), 2)
        token_budget = max(0.0, token_budget)

        x = rng.randrange(width)
        y = rng.randrange(height)

        # Default: healthy fleet. Most robots active; a few auctioning.
        trust_score = round(rng.uniform(0.85, 1.0), 3)
        status: RobotStatus = "auctioning" if rng.random() < 0.15 else "active"

        if liar_id is not None and robot_id == liar_id and tick >= liar_start_tick:
            # Mock "detected liar" trajectory: trust drops over a few ticks.
            ticks_lying = tick - liar_start_tick
            trust_score = round(max(0.0, 1.0 - 0.25 * (ticks_lying + 1)), 3)
            if trust_score <= 0.2:
                status = "quarantined"
            else:
                status = "active"

        states.append(
            {
                "robot_id": robot_id,
                "x": x,
                "y": y,
                "urgency": urgency,
                "token_budget": token_budget,
                "trust_score": trust_score,
                "status": status,
                "tick": tick,
            }
        )

    return states


def generate_mock_event(
    event_type: Literal["auction_won", "quarantine", "server_killed"],
    robot_id: str,
    tick: int,
) -> dict[str, Any]:
    """Build one Event dict matching the shared SwarmDock contract."""
    return {
        "type": event_type,
        "robot_id": robot_id,
        "timestamp": float(tick),
    }


if __name__ == "__main__":
    # Quick smoke check — not part of the sim loop.
    for t in (0, 20, 24):
        batch = generate_mock_tick(6, t, seed=42, liar_id="R3", liar_start_tick=20)
        print(f"tick={t} n={len(batch)} R3={batch[2]}")
