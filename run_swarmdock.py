"""
SwarmDock success-criteria runner.

Runs the four required experiments and prints PASS/FAIL against the spec:

  1. No central coordinator at swarm runtime (architectural)
  2. Swarm recovers from an injected lying robot within seconds
  3. Swarm throughput stays ≥80% of centralized baseline during recovery
  4. Centralized baseline deadlocks on server kill; swarm does not

Usage:
    python3 run_swarmdock.py
    python3 run_swarmdock.py --robots 10 --ticks 180 --fault-tick 20 --kill-tick 60
"""

from __future__ import annotations

import argparse
import json

from core.config import SimConfig
from sim.baseline import CentralizedEngine
from sim.engine import SwarmEngine
from sim.fault_injection import FaultInjector
from sim.recovery_metrics import evaluate_success


def build_config(args) -> SimConfig:
    return SimConfig(
        num_robots=args.robots,
        width=args.width,
        height=args.height,
        max_ticks=args.ticks,
        seed=args.seed,
        urgency_min=1,
        urgency_max=10,
        fault_robot_index=args.fault_robot,
        fault_start_tick=args.fault_tick,
        server_kill_tick=args.kill_tick,
        recovery_max_seconds=args.recovery_max,
        recovery_throughput_ratio=args.min_ratio,
    )


def run_lying_recovery(cfg: SimConfig):
    """Swarm with liar + healthy centralized baseline (same seed, no kill)."""
    swarm_cfg = SimConfig(**{**cfg.__dict__, "server_kill_tick": -1})
    central_cfg = SimConfig(**{**cfg.__dict__, "fault_robot_index": -1, "server_kill_tick": -1})

    injector = FaultInjector.from_config(swarm_cfg)
    swarm = SwarmEngine(swarm_cfg, fault_injector=injector)
    swarm_m = swarm.run()

    central = CentralizedEngine(central_cfg, server_kill=False)
    central_m = central.run()
    return swarm_m, central_m, swarm.events


def run_server_kill(cfg: SimConfig):
    """Central deadlocks on kill; swarm keeps completing tasks after kill tick."""
    kill_cfg = SimConfig(**{
        **cfg.__dict__,
        "fault_robot_index": -1,
        "server_kill_tick": cfg.server_kill_tick,
    })

    central = CentralizedEngine(kill_cfg, server_kill=True)
    central_m = central.run()

    swarm = SwarmEngine(kill_cfg, fault_injector=None)
    swarm_m = swarm.run()
    return swarm_m, central_m


def main():
    ap = argparse.ArgumentParser(description="SwarmDock success-criteria runner")
    ap.add_argument("--robots", type=int, default=8)
    ap.add_argument("--width", type=int, default=12)
    ap.add_argument("--height", type=int, default=12)
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fault-robot", type=int, default=2, help="0-based index of liar")
    ap.add_argument("--fault-tick", type=int, default=20)
    ap.add_argument("--kill-tick", type=int, default=60)
    ap.add_argument("--recovery-max", type=float, default=10.0)
    ap.add_argument("--min-ratio", type=float, default=0.80)
    args = ap.parse_args()

    cfg = build_config(args)

    print("Running lying-robot recovery experiment...")
    swarm_m, central_healthy, events = run_lying_recovery(cfg)
    swarm_m.print_summary()
    central_healthy.print_summary()

    print("\nRunning server-kill experiment...")
    swarm_kill_m, central_killed = run_server_kill(cfg)
    swarm_kill_m.print_summary()
    central_killed.print_summary()

    report = evaluate_success(
        swarm=swarm_m,
        central_healthy=central_healthy,
        central_killed=central_killed,
        swarm_after_kill=swarm_kill_m,
        recovery_max_seconds=cfg.recovery_max_seconds,
        min_ratio=cfg.recovery_throughput_ratio,
    )
    report.print()

    # sample of SwarmDock contract events
    sample = [e.to_dict() for e in events[:8]]
    print("\nSample SwarmDock events:")
    for e in sample:
        print(f"  {e}")

    out = {
        "swarm": swarm_m.summary(),
        "central_healthy": central_healthy.summary(),
        "central_killed": central_killed.summary(),
        "swarm_after_kill": swarm_kill_m.summary(),
        "success": {
            "no_central_coordinator": report.no_central_coordinator,
            "recovery_within_seconds": report.recovery_within_seconds,
            "recovery_seconds": report.recovery_seconds,
            "throughput_ratio_during_recovery": report.throughput_ratio_during_recovery,
            "throughput_ge_80pct": report.throughput_ge_80pct,
            "central_deadlocks_on_server_kill": report.central_deadlocks_on_server_kill,
            "swarm_survives_server_kill": report.swarm_survives_server_kill,
            "all_passed": report.all_passed,
        },
        "events_sample": sample,
    }
    with open("swarmdock_results.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print("\nWrote swarmdock_results.json")

    raise SystemExit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
