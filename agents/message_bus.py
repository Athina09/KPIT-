"""
MessageBus: a simple pub-sub for robot broadcasts.

Robots publish broadcasts when at intersections.
Robots (or the scheduler) can query the bus for neighbor info during auctions.
"""

from typing import Dict, List, Optional


class MessageBus:
    """Simple in-memory message bus for robot broadcasts.

    Each tick, robots at intersections publish their state to the bus.
    Subscribers (e.g., auction resolver) can query recent messages.
    """

    def __init__(self):
        # {tick: [messages]}
        self.messages_by_tick: Dict[int, List[dict]] = {}
        self.current_tick = 0

    def advance_tick(self, tick: int):
        """Mark a new tick. Typically called at start of each simulation step."""
        self.current_tick = tick
        if tick not in self.messages_by_tick:
            self.messages_by_tick[tick] = []

    def publish(self, message: dict, tick: Optional[int] = None):
        """Publish a broadcast message.

        message: dict with keys like {'robot_id', 'urgency', 'ETA', 'pos', ...}
        tick: simulation tick (defaults to current_tick)
        """
        if tick is None:
            tick = self.current_tick
        if tick not in self.messages_by_tick:
            self.messages_by_tick[tick] = []
        self.messages_by_tick[tick].append(message)

    def get_messages(self, tick: Optional[int] = None) -> List[dict]:
        """Fetch all messages published in a tick (default: current_tick)."""
        if tick is None:
            tick = self.current_tick
        return self.messages_by_tick.get(tick, [])

    def get_messages_from_robot(self, robot_id: str, tick: Optional[int] = None) -> List[dict]:
        """Fetch all messages from a specific robot in a tick."""
        if tick is None:
            tick = self.current_tick
        msgs = self.messages_by_tick.get(tick, [])
        return [m for m in msgs if m.get("robot_id") == robot_id]

    def get_messages_in_range(self, center_x: int, center_y: int, radius: int,
                               tick: Optional[int] = None) -> List[dict]:
        """Fetch all messages from robots within a radius of (center_x, center_y).

        Useful for auction participants to see who else is bidding.
        """
        if tick is None:
            tick = self.current_tick
        msgs = self.messages_by_tick.get(tick, [])
        result = []
        for m in msgs:
            if "pos" in m:
                px, py = m["pos"]
                dist = abs(px - center_x) + abs(py - center_y)
                if dist <= radius:
                    result.append(m)
        return result

    def clear_old_ticks(self, keep_last_n: int = 5):
        """Remove old ticks to avoid unbounded memory growth."""
        ticks = sorted(self.messages_by_tick.keys())
        if len(ticks) > keep_last_n:
            for tick in ticks[:-keep_last_n]:
                del self.messages_by_tick[tick]
