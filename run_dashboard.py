"""
Top-level experiment runner + metrics dashboard (Feature 5, ties in 1-4 & 6).

Runs the decentralized swarm and the centralized baseline on the SAME scenario,
injects a Byzantine fault, streams the swarm to the digital-twin channel, then:

  * prints a side-by-side metrics comparison
  * writes dashboard_data.json (consumed by index.html web dashboard)
  * renders comparison_charts.png (matplotlib) if matplotlib is available

Usage:
    python3 run_dashboard.py                 # default 8-robot scenario w/ fault
    python3 run_dashboard.py --robots 12 --ticks 300 --no-fault
"""

import argparse
import json

from core.config import SimConfig
from sim.engine import SwarmEngine
from sim.baseline import CentralizedEngine
from sim.fault_injection import FaultInjector
from sim.twin_sync import TwinSync


def build_config(args):
    cfg = SimConfig(
        num_robots=args.robots,
        width=args.width,
        height=args.height,
        max_ticks=args.ticks,
        seed=args.seed,
    )
    if not args.no_fault:
        cfg.fault_robot_index = min(2, args.robots - 1)  # R3 lies by default
        cfg.fault_start_tick = args.fault_tick
    return cfg


def run_all(cfg, echo_twin=False):
    # --- decentralized swarm (with fault + twin sync) ---
    frames = []
    twin = TwinSync(physical_robot_id="R1", echo=echo_twin)

    def swarm_sink(frame):
        frames.append(frame)
        twin(frame)

    injector = FaultInjector.from_config(cfg)
    swarm = SwarmEngine(cfg, fault_injector=injector)
    swarm_metrics = swarm.run(frame_sink=swarm_sink)
    twin.close()

    # --- centralized baseline (same scenario, no server kill) ---
    central = CentralizedEngine(cfg, server_kill=False)
    central_metrics = central.run()

    return swarm_metrics, central_metrics, frames


def print_comparison(swarm_m, central_m):
    swarm_m.print_summary()
    central_m.print_summary()

    def pct(a, b):
        if b == 0:
            return "n/a"
        return f"{(a - b) / b * 100:+.1f}%"

    print("\n===== DECENTRALIZED vs CENTRALIZED =====")
    print(f"  throughput ....... {swarm_m.throughput_per_min:.2f} vs "
          f"{central_m.throughput_per_min:.2f} tasks/min "
          f"({pct(swarm_m.throughput_per_min, central_m.throughput_per_min)})")
    print(f"  avg wait ......... {swarm_m.avg_wait:.2f} vs {central_m.avg_wait:.2f} ticks")
    print(f"  conflict resolve . {swarm_m.avg_conflict_resolution:.2f} vs "
          f"{central_m.avg_conflict_resolution:.2f} ticks")
    lat = swarm_m.fault_detection_latency
    print(f"  fault detection .. {lat if lat is not None else 'n/a'} ticks "
          f"(baseline: no distributed trust)")
    print(f"  false positives .. {swarm_m.false_positive_rate:.2f}")


def export_dashboard(swarm_m, central_m, frames, path="dashboard_data.json"):
    data = {
        "decentralized": {
            "summary": swarm_m.summary(),
            "throughput_series": swarm_m.throughput_series,
            "active_series": swarm_m.active_series,
        },
        "centralized": {
            "summary": central_m.summary(),
            "throughput_series": central_m.throughput_series,
            "active_series": central_m.active_series,
        },
        "frames": frames,
    }
    with open(path, "w") as fh:
        json.dump(data, fh)
    print(f"\nWrote {path} ({len(frames)} replay frames) -> open index.html")


def render_charts(swarm_m, central_m, path="comparison_charts.png"):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # matplotlib optional
        print(f"(matplotlib unavailable, skipping charts: {e})")
        return

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    axes[0].plot(swarm_m.throughput_series, label="decentralized", color="#2b8a3e")
    axes[0].plot(central_m.throughput_series, label="centralized", color="#1c7ed6")
    axes[0].set_title("Cumulative tasks completed")
    axes[0].set_xlabel("tick")
    axes[0].set_ylabel("tasks")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    labels = ["throughput/min", "avg wait", "conflict resolve"]
    swarm_vals = [swarm_m.throughput_per_min, swarm_m.avg_wait, swarm_m.avg_conflict_resolution]
    central_vals = [central_m.throughput_per_min, central_m.avg_wait, central_m.avg_conflict_resolution]
    x = range(len(labels))
    axes[1].bar([i - 0.2 for i in x], swarm_vals, width=0.4, label="decentralized", color="#2b8a3e")
    axes[1].bar([i + 0.2 for i in x], central_vals, width=0.4, label="centralized", color="#1c7ed6")
    axes[1].set_xticks(list(x))
    axes[1].set_xticklabels(labels, rotation=10)
    axes[1].set_title("Key metrics")
    axes[1].legend()
    axes[1].grid(alpha=0.3, axis="y")

    fig.tight_layout()
    fig.savefig(path, dpi=110)
    print(f"Wrote {path}")


def main():
    ap = argparse.ArgumentParser(description="Decentralized swarm vs centralized baseline")
    ap.add_argument("--robots", type=int, default=8)
    ap.add_argument("--width", type=int, default=12)
    ap.add_argument("--height", type=int, default=12)
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fault-tick", type=int, default=20)
    ap.add_argument("--no-fault", action="store_true")
    ap.add_argument("--echo-twin", action="store_true", help="print physical-twin view each tick")
    args = ap.parse_args()

    cfg = build_config(args)
    swarm_m, central_m, frames = run_all(cfg, echo_twin=args.echo_twin)
    print_comparison(swarm_m, central_m)
    export_dashboard(swarm_m, central_m, frames)
    render_charts(swarm_m, central_m)


if __name__ == "__main__":
    main()
