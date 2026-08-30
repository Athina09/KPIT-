"""
Decentralized intersection arbitration via a token-based priority auction.

Every robot runs this SAME logic locally on the set of neighbor bids it heard,
so two robots contending for one cell independently compute the same winner
without any server. Economics:

  * bid           = min(budget, urgency-derived) + wait_bid_bonus * wait_time
  * winner        pays `bid_cost_on_win` tokens
  * each loser     gets `refund_on_loss` tokens back (anti-starvation)
  * every tick     budgets regenerate by `decay_recovery_per_tick` up to a cap
  * ties           broken deterministically by robot_id (stable across robots)

The `resolve_conflict` function resolves cell conflicts for multi-robot scenarios
and emits auction events when requested.
"""

from __future__ import annotations

import random
from typing import Callable, Optional


def resolve_conflict(
    robots_wanting_cell,
    tick: Optional[int] = None,
    emit_event: Optional[Callable] = None,
    token_cost: float = 1.0,
    token_weight: float = 0.5,
    rng: Optional[random.Random] = None,
    msg_bus=None,
):
    """
    robots_wanting_cell: list of RobotAgent instances all trying
        to move into the same cell this tick.
    tick: simulation tick (for events)
    emit_event: optional callable(Event) to publish events
    token_cost: how many tokens the winner pays
    token_weight: multiplier for token_budget influence on bids
    rng: optional Random instance for deterministic tie-breaking
    msg_bus: optional MessageBus to query broadcast info about competitors

    Returns: the winning RobotAgent.

    Auction uses effective_bid = compute_bid() + token_weight * token_budget,
    plus optional adjustments from broadcast info (e.g., if a robot has very
    high ETA, it gets a small penalty). Ties broken deterministically.
    """
    if not robots_wanting_cell:
        return None
    if len(robots_wanting_cell) == 1:
        return robots_wanting_cell[0]

    if rng is None:
        rng = random.Random()

    bids = []
    for robot in robots_wanting_cell:
        base = robot.compute_bid()
        token_term = token_weight * float(getattr(robot, "token_budget", getattr(robot, "budget", 0.0)))
        effective = base + token_term

        # optional: adjust bid based on broadcast info (e.g., ETA penalty)
        if msg_bus is not None and tick is not None:
            try:
                broadcasts = msg_bus.get_messages_from_robot(robot.robot_id, tick=tick)
                for b in broadcasts:
                    eta = b.get("ETA")
                    # high ETA = far from intersection = gets slight penalty
                    # (encourages robots close to intersection to go first)
                    if eta is not None and eta > 2:
                        effective -= 0.05 * (eta - 2)
            except Exception:
                pass

        bids.append((robot, effective))

    # find max effective bid
    max_bid = max(b[1] for b in bids)
    eps = 1e-9
    top = [r for r, b in bids if abs(b - max_bid) <= eps]

    if len(top) > 1:
        # Prefer robots that have been repeatedly blocked on the same target.
        max_livelock = max(getattr(r, "livelock_counter", 0) for r in top)
        top = [r for r in top if getattr(r, "livelock_counter", 0) == max_livelock]
        if len(top) > 1:
            # deterministic fallback avoids repeated randomness in hard ties
            top.sort(key=lambda r: r.robot_id)
    winner = top[0]

    # deduct token cost from winner
    if hasattr(winner, "token_budget"):
        winner.token_budget = max(0.0, winner.token_budget - token_cost)
    if hasattr(winner, "budget"):
        winner.budget = max(0.0, winner.budget - token_cost)

    losers = [r for r in robots_wanting_cell if r is not winner]
    for l in losers:
        l.wait_time += 1

    # emit auction_won event when requested
    if emit_event is not None:
        try:
            from agents.robot_state import Event
            payload = {
                "winner": winner.robot_id,
                "losers": [l.robot_id for l in losers],
                "winning_bid": max_bid,
                "broadcasts_used": msg_bus is not None,
            }
            emit_event(Event(type="auction_won", tick=tick if tick is not None else 0, robot_id=winner.robot_id, payload=payload))
        except Exception:
            # graceful: if Event import fails, call emit_event with a dict
            emit_event({"type": "auction_won", "tick": tick, "robot_id": winner.robot_id, "payload": {"losers": [l.robot_id for l in losers], "winning_bid": max_bid}})

    return winner


class TokenAuction:
    def __init__(self, config):
        self.config = config
        self.last_resolution_ticks = []   # for the "conflict resolution time" metric

    def _tie_break_key(self, bid_entry):
        """Higher bid first; deterministic robot_id tie-break so every robot
        computing the auction locally agrees on the winner."""
        robot_id, bid = bid_entry
        return (bid, robot_id)

    def eligible(self, robot) -> bool:
        """SwarmDock rule: auction skips any robot where status == quarantined."""
        status = getattr(robot, "status", None)
        if status == "quarantined" or getattr(robot, "quarantined", False):
            return False
        return True

    def resolve_cell(self, contenders):
        """contenders: list of (robot_id, bid). Returns (winner_id, losers)."""
        if not contenders:
            return None, []
        ranked = sorted(contenders, key=self._tie_break_key, reverse=True)
        winner_id = ranked[0][0]
        losers = [rid for rid, _ in ranked[1:]]
        return winner_id, losers

    def settle(self, robots, winner_id, loser_ids):
        """Apply token economics after a cell is decided."""
        cfg = self.config
        if winner_id in robots:
            w = robots[winner_id]
            w.budget = max(0.0, w.budget - cfg.bid_cost_on_win)
            w.wait_time = 0
        for rid in loser_ids:
            if rid in robots:
                loser = robots[rid]
                cap = loser.starting_budget * cfg.max_budget_multiplier
                loser.budget = min(cap, loser.budget + cfg.refund_on_loss)
                loser.wait_time += 1

    def regen(self, robots):
        """Passive decay-recovery so low-priority robots aren't starved."""
        cfg = self.config
        for robot in robots.values():
            if not self.eligible(robot):
                continue
            cap = robot.starting_budget * cfg.max_budget_multiplier
            robot.budget = min(cap, robot.budget + cfg.decay_recovery_per_tick)
