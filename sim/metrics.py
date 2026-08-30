"""
Metrics collection (Person B + shared harness).

Tracks the numbers compared between the decentralized swarm and the
centralized baseline, including SwarmDock success-criteria fields:

  * recovery_seconds          -- ticks from lie start to quarantine (1 tick = 1s)
  * throughput_during_recovery -- tasks completed inside the recovery window
  * recovery_throughput_ratio -- swarm / central in that window (≥ 0.80 target)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean


TICKS_PER_MINUTE = 60  # 1 tick == 1 second by convention


@dataclass
class Metrics:
    mode: str = "decentralized"
    ticks: int = 0
    tasks_completed: int = 0
    wait_samples: list = field(default_factory=list)
    conflict_samples: list = field(default_factory=list)
    quarantined_ids: set = field(default_factory=set)
    false_positive_ids: set = field(default_factory=set)
    num_honest: int = 0
    fault_start_tick: int | None = None
    fault_detect_tick: int | None = None

    # per-tick series
    throughput_series: list = field(default_factory=list)
    active_series: list = field(default_factory=list)

    # SwarmDock recovery-window bookkeeping
    tasks_at_fault_start: int | None = None
    tasks_at_recovery_end: int | None = None
    server_killed: bool = False
    tasks_after_server_kill: int = 0
    server_kill_tick: int | None = None

    def record_task(self, wait_ticks: int) -> None:
        self.tasks_completed += 1
        self.wait_samples.append(wait_ticks)

    def record_conflict(self, contend_ticks: int) -> None:
        self.conflict_samples.append(contend_ticks)

    def record_tick(self, active_count: int) -> None:
        self.throughput_series.append(self.tasks_completed)
        self.active_series.append(active_count)

    def mark_fault_start(self, tick: int) -> None:
        if self.fault_start_tick is None:
            self.fault_start_tick = tick
            self.tasks_at_fault_start = self.tasks_completed

    def mark_recovery_end(self, tick: int) -> None:
        if self.fault_detect_tick is None:
            self.fault_detect_tick = tick
            self.tasks_at_recovery_end = self.tasks_completed

    @property
    def throughput_per_min(self) -> float:
        if self.ticks == 0:
            return 0.0
        return self.tasks_completed / (self.ticks / TICKS_PER_MINUTE)

    @property
    def avg_wait(self) -> float:
        return mean(self.wait_samples) if self.wait_samples else 0.0

    @property
    def avg_conflict_resolution(self) -> float:
        return mean(self.conflict_samples) if self.conflict_samples else 0.0

    @property
    def fault_detection_latency(self) -> int | None:
        if self.fault_start_tick is None or self.fault_detect_tick is None:
            return None
        return self.fault_detect_tick - self.fault_start_tick

    @property
    def recovery_seconds(self) -> float | None:
        lat = self.fault_detection_latency
        return float(lat) if lat is not None else None

    @property
    def tasks_during_recovery(self) -> int | None:
        if self.tasks_at_fault_start is None or self.tasks_at_recovery_end is None:
            return None
        return self.tasks_at_recovery_end - self.tasks_at_fault_start

    @property
    def false_positive_rate(self) -> float:
        if self.num_honest == 0:
            return 0.0
        return len(self.false_positive_ids) / self.num_honest

    def window_tasks(self, start_tick: int, end_tick: int) -> int:
        """Tasks completed in (start_tick, end_tick] from the cumulative series."""
        if not self.throughput_series:
            return 0
        end_tick = min(end_tick, len(self.throughput_series) - 1)
        start_tick = max(0, start_tick)
        at_end = self.throughput_series[end_tick]
        at_start = self.throughput_series[start_tick] if start_tick < len(self.throughput_series) else 0
        return max(0, at_end - at_start)

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "ticks": self.ticks,
            "tasks_completed": self.tasks_completed,
            "throughput_per_min": round(self.throughput_per_min, 3),
            "avg_wait_ticks": round(self.avg_wait, 3),
            "avg_conflict_resolution_ticks": round(self.avg_conflict_resolution, 3),
            "fault_detection_latency_ticks": self.fault_detection_latency,
            "recovery_seconds": self.recovery_seconds,
            "tasks_during_recovery": self.tasks_during_recovery,
            "false_positive_rate": round(self.false_positive_rate, 3),
            "quarantined": sorted(self.quarantined_ids),
            "server_killed": self.server_killed,
            "tasks_after_server_kill": self.tasks_after_server_kill,
        }

    def print_summary(self) -> None:
        s = self.summary()
        print(f"\n===== METRICS [{s['mode']}] =====")
        print(f"  ticks run .................. {s['ticks']}")
        print(f"  tasks completed ............ {s['tasks_completed']}")
        print(f"  throughput ................. {s['throughput_per_min']} tasks/min")
        print(f"  avg wait ................... {s['avg_wait_ticks']} ticks")
        print(f"  avg conflict resolution .... {s['avg_conflict_resolution_ticks']} ticks")
        lat = s["fault_detection_latency_ticks"]
        print(f"  fault-detection latency .... {lat if lat is not None else 'n/a'} ticks")
        print(f"  recovery seconds ........... {s['recovery_seconds'] if s['recovery_seconds'] is not None else 'n/a'}")
        print(f"  false-positive quarantines . {s['false_positive_rate']}")
        print(f"  quarantined robots ......... {s['quarantined'] or 'none'}")
        if s["server_killed"]:
            print(f"  tasks after server kill .... {s['tasks_after_server_kill']}")
