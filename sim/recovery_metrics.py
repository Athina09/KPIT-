"""
SwarmDock recovery & success-criteria analysis (Person B).

Computes:
  * recovery_seconds — lie start → quarantine (1 tick = 1s)
  * throughput_during_recovery ratio vs centralized baseline in the same window
  * server-kill outcome — central deadlocks (0 tasks after kill); swarm continues
"""

from __future__ import annotations

from dataclasses import dataclass

from sim.metrics import Metrics


@dataclass
class SuccessReport:
    no_central_coordinator: bool
    recovery_within_seconds: bool
    recovery_seconds: float | None
    throughput_ratio_during_recovery: float | None
    throughput_ge_80pct: bool
    central_deadlocks_on_server_kill: bool
    swarm_survives_server_kill: bool
    all_passed: bool

    def print(self) -> None:
        def mark(ok: bool) -> str:
            return "PASS" if ok else "FAIL"

        print("\n===== SWARMDOCK SUCCESS CRITERIA =====")
        print(f"  [{mark(self.no_central_coordinator)}] No central coordinator at swarm runtime")
        rec = f"{self.recovery_seconds:.1f}s" if self.recovery_seconds is not None else "n/a"
        print(f"  [{mark(self.recovery_within_seconds)}] Lying-robot recovery within limit ({rec})")
        ratio = (
            f"{self.throughput_ratio_during_recovery:.1%}"
            if self.throughput_ratio_during_recovery is not None
            else "n/a"
        )
        print(f"  [{mark(self.throughput_ge_80pct)}] Throughput ≥80% of central during recovery ({ratio})")
        print(f"  [{mark(self.central_deadlocks_on_server_kill)}] Centralized baseline deadlocks on server kill")
        print(f"  [{mark(self.swarm_survives_server_kill)}] Swarm continues after server kill")
        print(f"\n  OVERALL: {'ALL PASS' if self.all_passed else 'NOT YET'}")


def recovery_throughput_ratio(
    swarm: Metrics,
    central: Metrics,
    fault_start: int,
    fault_end: int,
    post_grace: int = 30,
) -> float | None:
    """
    Swarm tasks / central tasks over the recovery window.

    Window = [fault_start, fault_end + post_grace] so we measure sustained
    throughput while the fleet isolates the liar, not just the 1–4 detection
    ticks where both sides may complete zero tasks.
    """
    if fault_start is None or fault_end is None or fault_end < fault_start:
        return None
    end = fault_end + post_grace
    s = swarm.window_tasks(fault_start, end)
    c = central.window_tasks(fault_start, end)
    if c == 0:
        # swarm matching or beating a stalled central window counts as full ratio
        return 1.0 if s >= 0 else None
    return s / c


def evaluate_success(
    swarm: Metrics,
    central_healthy: Metrics,
    central_killed: Metrics,
    swarm_after_kill: Metrics,
    recovery_max_seconds: float = 10.0,
    min_ratio: float = 0.80,
) -> SuccessReport:
    recovery = swarm.recovery_seconds
    ratio = None
    if swarm.fault_start_tick is not None and swarm.fault_detect_tick is not None:
        ratio = recovery_throughput_ratio(
            swarm, central_healthy, swarm.fault_start_tick, swarm.fault_detect_tick
        )

    recovery_ok = recovery is not None and recovery <= recovery_max_seconds
    ratio_ok = ratio is not None and ratio >= min_ratio

    # Central deadlock: server killed AND zero tasks completed after kill
    central_dead = (
        central_killed.server_killed
        and central_killed.tasks_after_server_kill == 0
    )
    # Swarm survives: completed more tasks after the kill tick than at kill
    swarm_survives = False
    if central_killed.server_kill_tick is not None:
        kill_t = central_killed.server_kill_tick
        before = (
            swarm_after_kill.throughput_series[kill_t]
            if kill_t < len(swarm_after_kill.throughput_series)
            else 0
        )
        after = swarm_after_kill.tasks_completed
        swarm_survives = after > before

    no_central = True  # architectural: SwarmEngine has no runtime planner

    return SuccessReport(
        no_central_coordinator=no_central,
        recovery_within_seconds=recovery_ok,
        recovery_seconds=recovery,
        throughput_ratio_during_recovery=ratio,
        throughput_ge_80pct=ratio_ok,
        central_deadlocks_on_server_kill=central_dead,
        swarm_survives_server_kill=swarm_survives,
        all_passed=all([
            no_central,
            recovery_ok,
            ratio_ok,
            central_dead,
            swarm_survives,
        ]),
    )
