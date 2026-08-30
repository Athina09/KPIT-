# SwarmDock — Decentralized Warehouse Swarm

A grid-world simulation of a **decentralized robot swarm** that arbitrates
intersections with a **token-based priority auction**, communicates only with
local neighbors, and detects/quarantines robots broadcasting false positions
via **multi-witness trust consensus** — with no central planner at runtime.

Deliverable: pure Python simulation + metrics (no hardware, no frontend
framework required). Optional web replay via `dashboard.html`.

## SwarmDock shared contract

```python
RobotState = {
    "robot_id": str, "x": int, "y": int,
    "urgency": int,          # 1-10
    "token_budget": float,
    "trust_score": float,    # owned/written by Person B
    "status": str,           # "active" | "auctioning" | "quarantined"
    "tick": int,
}
Event = {
    "type": str,             # "auction_won" | "quarantine" | "server_killed"
    "robot_id": str,
    "timestamp": float,
}
```

Defined in `core/contracts.py`. Auction skips `status == "quarantined"`.
Trust writes `trust_score` / `status` only — never moves robots.

## Team ownership

| Person | Owns |
|--------|------|
| **A** | grid world, robot FSM, tick loop, token auction, job/urgency gen, centralized baseline |
| **B** | trust scoring, neighbor cross-verify, quarantine consensus, fault injection (liar + server kill), metrics, recovery analysis |

## Success criteria (verified by `run_swarmdock.py`)

1. No central coordinator at swarm runtime
2. Lying-robot recovery within seconds
3. Swarm throughput ≥80% of centralized baseline during recovery
4. Centralized baseline deadlocks on server kill; swarm does not

## Install

```bash
cd /Users/apple/KPIT/KPIT-
pip install -r requirements.txt   # matplotlib optional (PNG charts)
```

## Run

```bash
# SwarmDock success-criteria suite (PASS/FAIL)
python3 run_swarmdock.py

# Full dashboard export (swarm vs central + twin stream)
python3 run_dashboard.py

# Legacy minimal demos
python3 simulate.py
python3 swarm_simulate.py
```

`run_swarmdock.py` writes `swarmdock_results.json`.
`run_dashboard.py` writes `dashboard_data.json`, `comparison_charts.png`, `twin_stream.jsonl`.

## Module map

| Concern | Path |
|---------|------|
| Contract | `core/contracts.py` |
| Config | `core/config.py` |
| Grid + local A* | `environment/grid_world.py` |
| Robot FSM | `agents/robot_agent.py` |
| Token auction | `agents/auction.py` |
| Comms | `agents/comms.py` |
| Trust / quarantine | `agents/trust_monitor.py` |
| Swarm engine | `sim/engine.py` |
| Central baseline | `sim/baseline.py` |
| Faults (liar + server kill) | `sim/fault_injection.py` |
| Metrics + recovery gate | `sim/metrics.py`, `sim/recovery_metrics.py` |
