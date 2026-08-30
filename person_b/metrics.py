"""
metrics.py — Person B metrics logging (Week 1).

Deterministic bookkeeping only. No LLM calls. Does not move robots or
resolve auctions — logs what Person A's sim (or mock_data) emits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EventType = Literal["auction_won", "quarantine", "server_killed"]


@dataclass
class QuarantineRecord:
    detected_tick: int
    resolved_tick: int | None = None


@dataclass
class MetricsLog:
    """
    Append-only log for SwarmDock Person B metrics.

    - log_event(event): store SwarmDock Event dicts
    - log_throughput(tick, jobs_completed): cumulative jobs at each tick
    - quarantine_times: robot_id -> {detected_tick, resolved_tick}
    """

    events: list[dict[str, Any]] = field(default_factory=list)
    throughput_series: list[tuple[int, int]] = field(default_factory=list)
    quarantine_times: dict[str, dict[str, int | None]] = field(default_factory=dict)

    def log_event(self, event: dict[str, Any]) -> None:
        """
        Record one Event.

        Expected shape:
            {"type": "auction_won"|"quarantine"|"server_killed",
             "robot_id": str, "timestamp": float}

        On type=="quarantine", starts a quarantine_times entry if missing
        (detected_tick = int(timestamp), resolved_tick = None).
        """
        self._validate_event(event)
        self.events.append(dict(event))

        if event["type"] == "quarantine":
            robot_id = event["robot_id"]
            detected = int(event["timestamp"])
            if robot_id not in self.quarantine_times:
                self.quarantine_times[robot_id] = {
                    "detected_tick": detected,
                    "resolved_tick": None,
                }

    def log_throughput(self, tick: int, jobs_completed: int) -> None:
        """Record cumulative jobs completed as of `tick` (Person A's counter)."""
        if tick < 0:
            raise ValueError("tick must be >= 0")
        if jobs_completed < 0:
            raise ValueError("jobs_completed must be >= 0")
        self.throughput_series.append((tick, jobs_completed))

    def mark_quarantine_resolved(self, robot_id: str, resolved_tick: int) -> None:
        """
        Optional helper for when a quarantined robot is reinstated.

        Not required for Step 1-3, but keeps quarantine_times complete once
        trust.py starts emitting recovery.
        """
        if robot_id not in self.quarantine_times:
            self.quarantine_times[robot_id] = {
                "detected_tick": resolved_tick,
                "resolved_tick": resolved_tick,
            }
        else:
            self.quarantine_times[robot_id]["resolved_tick"] = resolved_tick

    def recovery_time_ticks(self, robot_id: str) -> int | None:
        """
        Ticks from detection to resolution for one robot.

        Returns None if never detected, or still unresolved.
        """
        rec = self.quarantine_times.get(robot_id)
        if rec is None or rec["resolved_tick"] is None:
            return None
        detected = rec["detected_tick"]
        resolved = rec["resolved_tick"]
        if detected is None or resolved is None:
            return None
        return int(resolved) - int(detected)

    def jobs_between(self, start_tick: int, end_tick: int) -> int | None:
        """
        Jobs completed in (start_tick, end_tick] from the throughput series.

        Returns None if the series does not cover the window.
        """
        if not self.throughput_series:
            return None
        by_tick = {t: jobs for t, jobs in self.throughput_series}
        if end_tick not in by_tick:
            return None
        start_jobs = by_tick.get(start_tick, 0)
        return max(0, by_tick[end_tick] - start_jobs)

    def summary(self) -> dict[str, Any]:
        return {
            "n_events": len(self.events),
            "event_counts": self._event_counts(),
            "throughput_points": len(self.throughput_series),
            "last_jobs_completed": (
                self.throughput_series[-1][1] if self.throughput_series else 0
            ),
            "quarantine_times": dict(self.quarantine_times),
        }

    def _event_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.events:
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        return counts

    @staticmethod
    def _validate_event(event: dict[str, Any]) -> None:
        required = {"type", "robot_id", "timestamp"}
        missing = required - set(event)
        if missing:
            raise ValueError(f"Event missing fields: {sorted(missing)}")
        if event["type"] not in ("auction_won", "quarantine", "server_killed"):
            raise ValueError(f"Unknown event type: {event['type']!r}")
        if not isinstance(event["robot_id"], str):
            raise TypeError("robot_id must be str")
        if not isinstance(event["timestamp"], (int, float)):
            raise TypeError("timestamp must be float (or int)")


if __name__ == "__main__":
    try:
        from .mock_data import generate_mock_event, generate_mock_tick
    except ImportError:
        from mock_data import generate_mock_event, generate_mock_tick

    log = MetricsLog()
    for tick in range(0, 30):
        states = generate_mock_tick(6, tick, seed=1, liar_id="R3", liar_start_tick=20)
        jobs = tick // 3  # fake cumulative throughput
        log.log_throughput(tick, jobs)
        for s in states:
            if s["status"] == "quarantined" and s["robot_id"] not in log.quarantine_times:
                log.log_event(generate_mock_event("quarantine", s["robot_id"], tick))

    print(log.summary())

