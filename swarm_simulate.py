import json
import random
import sys
from copy import deepcopy
from pathlib import Path
from statistics import mean
from environment.grid_world import GridWorld
from agents.robot_agent import RobotAgent
from agents.lying_robot_agent import LyingRobotAgent
from agents.trust_monitor import TrustMonitor
from agents.message_bus import MessageBus
from agents.fault_injection import FaultProfile
from agents.job import Job, JobGenerator
from agents.robot_state import Event


# Movement intent logic moved to RobotAgent.desire_target(goal)

def choose_robot_goal(robot, jobs):
    if robot.assigned_job_id is None:
        return None
    job = jobs.get(robot.assigned_job_id)
    if job is None:
        return None
    if job.status == "picked_up":
        return job.dropoff
    return job.pickup


class SimulationMetrics:
    def __init__(self, tick_length_seconds=1.0):
        self.tick_length_seconds = tick_length_seconds
        self.robot_state_history = []
        self.spawned_jobs = []
        self.completed_jobs = []
        self.quarantine_events = []
        self.events = []

    def record_robot_state(self, tick, state):
        self.robot_state_history.append({"tick": tick, "state": state})

    def record_job_spawn(self, tick, job):
        self.spawned_jobs.append({
            "job_id": job.job_id,
            "spawned_tick": tick,
            "urgency": job.urgency,
            "pickup": job.pickup,
            "dropoff": job.dropoff,
        })

    def record_job_completion(self, job):
        self.completed_jobs.append({
            "job_id": job.job_id,
            "urgency": job.urgency,
            "spawned_tick": job.spawned_tick,
            "picked_up_tick": job.picked_up_tick,
            "delivered_tick": job.delivered_tick,
            "transit_time": None if job.delivered_tick is None else job.delivered_tick - job.spawned_tick,
            "pickup_delay": None if job.picked_up_tick is None else job.picked_up_tick - job.spawned_tick,
        })

    def record_quarantine(self, tick, robot_state, reason=None):
        self.quarantine_events.append({
            "tick": tick,
            "robot_id": robot_state.get("robot_id", None) if isinstance(robot_state, dict) else getattr(robot_state, "robot_id", None),
            "reason": reason,
            "robot_state": robot_state,
        })

    def record_event(self, event):
        self.events.append(event)

    def throughput_jobs_per_minute(self, total_ticks):
        if total_ticks <= 0:
            return 0.0
        total_time_minutes = (total_ticks * self.tick_length_seconds) / 60.0
        if total_time_minutes == 0:
            return 0.0
        return len(self.completed_jobs) / total_time_minutes

    def average_delivery_time(self):
        times = [r["transit_time"] for r in self.completed_jobs if r["transit_time"] is not None]
        if not times:
            return None
        return sum(times) / len(times)

    def average_quarantine_delay(self):
        if not self.quarantine_events:
            return None
        return sum(e["tick"] for e in self.quarantine_events) / len(self.quarantine_events)

    def summarize(self, total_ticks):
        return {
            "jobs_spawned": len(self.spawned_jobs),
            "jobs_delivered": len(self.completed_jobs),
            "throughput_jobs_per_minute": self.throughput_jobs_per_minute(total_ticks),
            "average_delivery_time": self.average_delivery_time(),
            "quarantine_events": len(self.quarantine_events),
            "average_quarantine_tick": self.average_quarantine_delay(),
        }

    def print_summary(self, total_ticks):
        print("\n=== METRICS SUMMARY ===")
        print(f"Total ticks simulated: {total_ticks}")
        print(f"Jobs spawned: {len(self.spawned_jobs)}")
        print(f"Jobs delivered: {len(self.completed_jobs)}")
        print(f"Throughput (jobs/min): {self.throughput_jobs_per_minute(total_ticks):.2f}")
        avg_delivery = self.average_delivery_time()
        if avg_delivery is not None:
            print(f"Average delivery time (ticks): {avg_delivery:.2f}")
        else:
            print("Average delivery time (ticks): N/A")
        if self.quarantine_events:
            print(f"Quarantine events: {len(self.quarantine_events)}")
            print(f"Average quarantine tick: {self.average_quarantine_delay():.2f}")
        else:
            print("Quarantine events: 0")
        print("Urgency vs transit time:")
        for rec in sorted(self.completed_jobs, key=lambda r: r["urgency"], reverse=True):
            print(f"  job={rec['job_id']} urgency={rec['urgency']} transit={rec['transit_time']} pickup_delay={rec['pickup_delay']}")


def update_job_progress(robot, jobs, tick):
    if robot.assigned_job_id is None:
        return None
    job = jobs.get(robot.assigned_job_id)
    if job is None:
        return None
    if not robot.carrying_package and (robot.x, robot.y) == job.pickup:
        job.status = "picked_up"
        job.picked_up_tick = tick
        robot.carrying_package = True
        robot.status = "navigate"
        return None
    elif robot.carrying_package and (robot.x, robot.y) == job.dropoff:
        job.status = "delivered"
        job.delivered_tick = tick
        completed = job
        robot.assigned_job_id = None
        robot.carrying_package = False
        robot.package_urgency = 1.0
        robot.status = "navigate"
        return completed
    return None


def assign_jobs(robots, jobs):
    pending = [job for job in jobs.values() if job.status == "pending"]
    free_robots = [robot for robot in robots.values()
                   if not robot.quarantined and robot.assigned_job_id is None and not robot.carrying_package]
    if not pending or not free_robots:
        return

    # assign highest urgency jobs first to the nearest available robot
    pending.sort(key=lambda job: (-job.urgency, job.spawned_tick))
    for job in pending:
        if not free_robots:
            break
        best_robot = min(free_robots, key=lambda r: r.manhattan_dist(job.pickup))
        job.assigned_robot = best_robot.robot_id
        job.status = "assigned"
        best_robot.assigned_job_id = job.job_id
        best_robot.package_urgency = job.urgency
        best_robot.status = "navigate"
        free_robots.remove(best_robot)


def generate_job_stream(world, max_ticks, seed, spawn_rate=0.6, urgency_range=(1.0, 10.0)):
    job_generator = JobGenerator(world, spawn_rate=spawn_rate, urgency_range=urgency_range, seed=seed)
    jobs_by_tick = {}
    for tick in range(max_ticks):
        jobs_by_tick[tick] = job_generator.generate(tick)
    return jobs_by_tick


def resolve_central_conflict(robots_wanting_cell):
    if not robots_wanting_cell:
        return None
    def sort_key(robot):
        robot_num = int(robot.robot_id[1:]) if robot.robot_id.startswith("R") else 0
        return (robot.package_urgency, robot.wait_time, -robot_num)
    return max(robots_wanting_cell, key=sort_key)


def scheduler_is_disabled(tick, failure_tick=None, recovery_tick=None):
    if failure_tick is None:
        return False
    if recovery_tick is None:
        return tick >= failure_tick
    return failure_tick <= tick < recovery_tick


def aggregate_metrics_across_runs(metric_runs, total_ticks):
    if not metric_runs:
        return {}
    summaries = [metrics.summarize(total_ticks) for metrics in metric_runs]
    delivery_times = [summary["average_delivery_time"] for summary in summaries if summary["average_delivery_time"] is not None]
    return {
        "runs": len(metric_runs),
        "jobs_spawned_mean": round(mean(summary["jobs_spawned"] for summary in summaries), 2),
        "jobs_delivered_mean": round(mean(summary["jobs_delivered"] for summary in summaries), 2),
        "throughput_jobs_per_minute_mean": round(mean(summary["throughput_jobs_per_minute"] for summary in summaries), 2),
        "average_delivery_time_mean": round(mean(delivery_times), 2) if delivery_times else None,
        "quarantine_events_mean": round(mean(summary["quarantine_events"] for summary in summaries), 2),
        "average_quarantine_tick_mean": round(mean(summary["average_quarantine_tick"] for summary in summaries if summary["average_quarantine_tick"] is not None), 2) if any(summary["average_quarantine_tick"] is not None for summary in summaries) else None,
    }


def print_statistical_summary(label, metric_runs, total_ticks):
    summary = aggregate_metrics_across_runs(metric_runs, total_ticks)
    print(f"\n=== {label} MULTI-SEED SUMMARY ===")
    print(f"Runs: {summary['runs']}")
    print(f"Average jobs spawned: {summary['jobs_spawned_mean']:.2f}")
    print(f"Average jobs delivered: {summary['jobs_delivered_mean']:.2f}")
    print(f"Average throughput (jobs/min): {summary['throughput_jobs_per_minute_mean']:.2f}")
    if summary["average_delivery_time_mean"] is not None:
        print(f"Average delivery time (ticks): {summary['average_delivery_time_mean']:.2f}")
    else:
        print("Average delivery time (ticks): N/A")
    if summary["quarantine_events_mean"] is not None:
        print(f"Average quarantine events: {summary['quarantine_events_mean']:.2f}")
    if summary["average_quarantine_tick_mean"] is not None:
        print(f"Average quarantine tick: {summary['average_quarantine_tick_mean']:.2f}")


def save_multi_seed_results(results, output_path):
    if output_path is None:
        return None
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return str(output_file)


def run_centralized(num_robots=6, width=8, height=8, max_ticks=40,
                    seed=42, initial_positions=None, pre_generated_jobs=None,
                    scheduler_failure_tick=None, scheduler_recovery_tick=None):
    rng = random.Random(seed)
    world = GridWorld(width=width, height=height)
    msg_bus = None

    robots = {}
    jobs = {}
    used_cells = set()
    if initial_positions is None:
        initial_positions = []
        while len(initial_positions) < num_robots:
            pos = (rng.randrange(width), rng.randrange(height))
            if pos not in used_cells:
                used_cells.add(pos)
                initial_positions.append(pos)
    else:
        used_cells.update(initial_positions)

    for i in range(num_robots):
        rid = f"R{i+1}"
        sx, sy = initial_positions[i]
        urgency = round(rng.uniform(1.0, 3.0), 2)
        token_budget = round((urgency - 1.0) / (3.0 - 1.0) * 9.0 + 1.0, 2)
        robot = RobotAgent(
            rid,
            sx,
            sy,
            package_urgency=urgency,
            token_budget=token_budget,
            token_capacity=max(token_budget, 10.0),
            token_refill_rate=0.5,
        )
        world.place_robot(rid, sx, sy)
        robots[rid] = robot

    print("Centralized fleet initialized:")
    for rid, robot in robots.items():
        print(f"  {rid}: start=({robot.x},{robot.y}) urgency={robot.package_urgency}")
    if scheduler_failure_tick is not None:
        print(f"Centralized scheduler will fail at tick {scheduler_failure_tick}"
              f"{' and recover at tick ' + str(scheduler_recovery_tick) if scheduler_recovery_tick is not None else ''}")

    metrics = SimulationMetrics()
    if pre_generated_jobs is None:
        job_generator = JobGenerator(world, spawn_rate=0.6, urgency_range=(1.0, 10.0), seed=seed)

    for tick in range(max_ticks):
        print(f"\n--- [Central] Tick {tick} ---")
        for robot in robots.values():
            robot.refill_tokens()

        if pre_generated_jobs is None:
            new_jobs = job_generator.generate(tick)
        else:
            new_jobs = [deepcopy(job) for job in pre_generated_jobs.get(tick, [])]

        for job in new_jobs:
            jobs[job.job_id] = job
            metrics.record_job_spawn(tick, job)
            print(f"CENTRAL NEW JOB {job.job_id}: pickup={job.pickup} dropoff={job.dropoff} urgency={job.urgency}")

        scheduler_disabled = scheduler_is_disabled(tick, scheduler_failure_tick, scheduler_recovery_tick)
        if scheduler_disabled:
            print(f"CENTRALIZED SCHEDULER OFFLINE on tick {tick}; no assignments or movement updates.")
            for rid, robot in robots.items():
                goal = choose_robot_goal(robot, jobs)
                robot.update_state_after_move(goal, False, (robot.x, robot.y))
                metrics.record_robot_state(tick, robot.to_state())
                status = "IDLE"
                if robot.carrying_package:
                    status = f"CARRYING JOB={robot.assigned_job_id}"
                elif robot.assigned_job_id is not None:
                    status = f"JOB={robot.assigned_job_id}"
                print(f"[Central] {rid}: pos=({robot.x},{robot.y}) wait={robot.wait_time} "
                      f"goal={goal} {status} "
                      f"token={robot.token_budget:.2f}/{robot.token_capacity:.2f} "
                      f"livelock={getattr(robot, 'livelock_counter', 0)}")
            continue

        assign_jobs(robots, jobs)

        active = [rid for rid, r in robots.items() if r.assigned_job_id is not None or r.carrying_package]
        if not active and not any(job.status in ("pending", "assigned", "picked_up") for job in jobs.values()):
            print("Centralized: no active robots and no outstanding jobs this tick.")
            continue

        intents = {}
        intent_info = {}
        for rid in active:
            robot = robots[rid]
            goal = choose_robot_goal(robot, jobs)
            if goal is None:
                continue
            candidates = robot.desire_target(goal)
            if not candidates:
                continue
            dx, dy = candidates[0]
            target = (robot.x + dx, robot.y + dy)
            intent_info[rid] = (target, (dx, dy), goal)
            intents.setdefault(target, []).append(rid)

        for target, rlist in intents.items():
            if len(rlist) == 1:
                rid = rlist[0]
                robot = robots[rid]
                _, (dx, dy), goal = intent_info[rid]
                if world.is_free(*target):
                    robot.step_forward(dx, dy, world)
                    moved = True
                else:
                    robot.wait_time += 1
                    moved = False
                robot.update_state_after_move(goal, moved, target)
                completed_job = update_job_progress(robot, jobs, tick)
                if completed_job is not None:
                    metrics.record_job_completion(completed_job)
            else:
                robot_objs = [robots[rid] for rid in rlist]
                winner = resolve_central_conflict(robot_objs)
                for rid in rlist:
                    robot = robots[rid]
                    if robot is winner and world.is_free(*intent_info[rid][0]):
                        _, (dx, dy), goal = intent_info[rid]
                        robot.step_forward(dx, dy, world)
                        moved = True
                        robot.update_state_after_move(goal, moved, intent_info[rid][0])
                        completed_job = update_job_progress(robot, jobs, tick)
                        if completed_job is not None:
                            metrics.record_job_completion(completed_job)
                    else:
                        _, _, goal = intent_info[rid]
                        robot.update_state_after_move(goal, False, intent_info[rid][0])
                        robot.wait_time += 1

        for rid, robot in robots.items():
            metrics.record_robot_state(tick, robot.to_state())
            goal = choose_robot_goal(robot, jobs)
            status = "IDLE"
            if robot.carrying_package:
                status = f"CARRYING JOB={robot.assigned_job_id}"
            elif robot.assigned_job_id is not None:
                status = f"JOB={robot.assigned_job_id}"
            print(f"[Central] {rid}: pos=({robot.x},{robot.y}) wait={robot.wait_time} "
                  f"goal={goal} {status} "
                  f"token={robot.token_budget:.2f}/{robot.token_capacity:.2f} "
                  f"livelock={getattr(robot, 'livelock_counter', 0)}")
    else:
        print(f"\nCentralized fleet stopped after {max_ticks} ticks.")

    metrics.print_summary(max_ticks)
    return metrics


def compare_two_fleets(num_robots=6, width=8, height=8, max_ticks=40, seed=42,
                       central_scheduler_failure_tick=None, central_scheduler_recovery_tick=None):
    rng = random.Random(seed)
    initial_positions = []
    used_cells = set()
    while len(initial_positions) < num_robots:
        pos = (rng.randrange(width), rng.randrange(height))
        if pos not in used_cells:
            used_cells.add(pos)
            initial_positions.append(pos)

    generator_world = GridWorld(width=width, height=height)
    for pos_index, pos in enumerate(initial_positions):
        rid = f"R{pos_index+1}"
        generator_world.place_robot(rid, pos[0], pos[1])

    pre_generated_jobs = generate_job_stream(generator_world, max_ticks, seed)

    print("\n=== TWO-FLEET COMPARISON START ===")
    print("Shared initial positions:")
    for idx, pos in enumerate(initial_positions):
        print(f"  R{idx+1}: {pos}")

    print("\n--- Swarm fleet ---")
    swarm_metrics = run_swarm(num_robots=num_robots, width=width, height=height,
                              max_ticks=max_ticks, seed=seed,
                              initial_positions=initial_positions,
                              pre_generated_jobs=pre_generated_jobs,
                              enable_faulty_robot=False)

    if central_scheduler_failure_tick is not None:
        print(f"\n--- Centralized fleet (scheduler failure at tick {central_scheduler_failure_tick}) ---")
    else:
        print("\n--- Centralized fleet ---")
    central_metrics = run_centralized(num_robots=num_robots, width=width, height=height,
                                      max_ticks=max_ticks, seed=seed,
                                      initial_positions=initial_positions,
                                      pre_generated_jobs=pre_generated_jobs,
                                      scheduler_failure_tick=central_scheduler_failure_tick,
                                      scheduler_recovery_tick=central_scheduler_recovery_tick)

    print("\n=== COMPARISON SUMMARY ===")
    print("Swarm metrics:")
    swarm_metrics.print_summary(max_ticks)
    print("\nCentralized metrics:")
    central_metrics.print_summary(max_ticks)
    return swarm_metrics, central_metrics


def run_multi_seed_comparison(num_seeds=5, start_seed=1, num_robots=6, width=8, height=8,
                               max_ticks=40, central_scheduler_failure_tick=None,
                               central_scheduler_recovery_tick=None, output_path=None):
    seeds = list(range(start_seed, start_seed + num_seeds))
    swarm_results = []
    central_results = []
    print(f"\n=== MULTI-SEED COMPARISON RUN ({len(seeds)} seeds) ===")
    for seed in seeds:
        print(f"\n=== Seed {seed} ===")
        swarm_metrics, central_metrics = compare_two_fleets(
            num_robots=num_robots,
            width=width,
            height=height,
            max_ticks=max_ticks,
            seed=seed,
            central_scheduler_failure_tick=central_scheduler_failure_tick,
            central_scheduler_recovery_tick=central_scheduler_recovery_tick,
        )
        swarm_results.append(swarm_metrics)
        central_results.append(central_metrics)

    print_statistical_summary("Swarm", swarm_results, max_ticks)
    print_statistical_summary("Centralized", central_results, max_ticks)
    results = {
        "seeds": seeds,
        "swarm": aggregate_metrics_across_runs(swarm_results, max_ticks),
        "centralized": aggregate_metrics_across_runs(central_results, max_ticks),
    }
    saved_path = save_multi_seed_results(results, output_path)
    if saved_path is not None:
        print(f"\nSaved multi-seed results to {saved_path}")
    return results


def run_swarm(num_robots=6, width=8, height=8, max_ticks=40, seed=42,
              initial_positions=None, pre_generated_jobs=None,
              enable_faulty_robot=True, faulty_robot_index=2):
    rng = random.Random(seed)
    world = GridWorld(width=width, height=height)
    msg_bus = MessageBus()

    robots = {}
    trust_monitors = {}
    jobs = {}
    completed_jobs = []
    used_cells = set()

    if initial_positions is None:
        initial_positions = []
        while len(initial_positions) < num_robots:
            pos = (rng.randrange(width), rng.randrange(height))
            if pos not in used_cells:
                used_cells.add(pos)
                initial_positions.append(pos)
    else:
        used_cells.update(initial_positions)

    if pre_generated_jobs is None:
        job_generator = JobGenerator(world, spawn_rate=0.6, urgency_range=(1.0, 10.0), seed=seed)

    for i in range(num_robots):
        rid = f"R{i+1}"
        sx, sy = initial_positions[i]

        urgency = round(rng.uniform(1.0, 3.0), 2)
        token_budget = round((urgency - 1.0) / (3.0 - 1.0) * 9.0 + 1.0, 2)
        if enable_faulty_robot and i == faulty_robot_index:
            liar_profile = FaultProfile(
                description="position_liar",
                inject_position_offset=(2, 2),
                active_from_tick=0,
                active_until_tick=None,
            )
            robot = LyingRobotAgent(
                rid,
                sx,
                sy,
                package_urgency=urgency,
                token_budget=token_budget,
                token_capacity=max(token_budget, 10.0),
                token_refill_rate=0.5,
                fault_profile=liar_profile,
            )
        else:
            robot = RobotAgent(
                rid,
                sx,
                sy,
                package_urgency=urgency,
                token_budget=token_budget,
                token_capacity=max(token_budget, 10.0),
                token_refill_rate=0.5,
            )
        world.place_robot(rid, sx, sy)

        robots[rid] = robot
        trust_monitors[rid] = TrustMonitor()

    print("Swarm initialized:")
    for rid, robot in robots.items():
        print(f"  {rid}: start=({robot.x},{robot.y}) urgency={robot.package_urgency}")

    metrics = SimulationMetrics()

    for tick in range(max_ticks):
        print(f"\n--- Tick {tick} ---")
        msg_bus.advance_tick(tick)
        for robot in robots.values():
            robot.refill_tokens()

        # spawn new jobs and assign them to available robots
        if pre_generated_jobs is None:
            new_jobs = job_generator.generate(tick)
        else:
            new_jobs = [deepcopy(job) for job in pre_generated_jobs.get(tick, [])]
        for job in new_jobs:
            jobs[job.job_id] = job
            metrics.record_job_spawn(tick, job)
            print(f"NEW JOB {job.job_id}: pickup={job.pickup} dropoff={job.dropoff} urgency={job.urgency}")
        assign_jobs(robots, jobs)

        active = [rid for rid, r in robots.items() if not r.quarantined and (r.assigned_job_id is not None or r.carrying_package)]
        if not active and not any(job.status in ("pending", "assigned", "picked_up") for job in jobs.values()):
            print("No active robots and no outstanding jobs this tick.")
            # continue to allow future job spawns
            continue

        # collect movement intents for this tick
        intents = {}  # target -> list of robot ids
        intent_info = {}  # rid -> (target, (dx,dy), goal)
        zone_intents = {}  # intersection_zone -> list of robot ids
        for rid in active:
            robot = robots[rid]
            goal = choose_robot_goal(robot, jobs)
            if goal is None:
                continue
            candidates = robot.desire_target(goal)
            if not candidates:
                continue
            dx, dy = candidates[0]
            target = (robot.x + dx, robot.y + dy)
            intent_info[rid] = (target, (dx, dy), goal)
            intents.setdefault(target, []).append(rid)
            zone = world.intersection_zone_center(*target) or world.intersection_zone_center(robot.x, robot.y)
            if zone is not None:
                zone_intents.setdefault(zone, []).append(rid)

        # resolve intents: multi-intersection zones first, then target-level auctions
        from agents.auction import resolve_conflict

        events = []
        def emit_event(e):
            events.append(e)
            metrics.record_event(e)

        processed = set()
        for zone, rlist in zone_intents.items():
            if len(rlist) <= 1:
                continue
            active_zone_rids = [rid for rid in rlist if rid in intent_info]
            if len(active_zone_rids) <= 1:
                continue

            robot_objs = [robots[rid] for rid in active_zone_rids]
            winner = resolve_conflict(robot_objs, tick=tick, emit_event=emit_event, rng=rng, msg_bus=msg_bus)
            for rid in active_zone_rids:
                robot = robots[rid]
                target, (dx, dy), goal = intent_info[rid]
                if robot is winner and world.is_free(*target):
                    robot.step_forward(dx, dy, world)
                    moved = True
                else:
                    moved = False
                robot.update_state_after_move(goal, moved, target)
                completed_job = update_job_progress(robot, jobs, tick)
                if completed_job is not None:
                    metrics.record_job_completion(completed_job)
                processed.add(rid)

        for target, rlist in intents.items():
            unprocessed = [rid for rid in rlist if rid not in processed]
            if not unprocessed:
                continue

            if len(unprocessed) == 1:
                rid = unprocessed[0]
                robot = robots[rid]
                _, (dx, dy), goal = intent_info[rid]
                if world.is_free(*target):
                    robot.step_forward(dx, dy, world)
                    moved = True
                else:
                    robot.wait_time += 1
                    moved = False
                robot.update_state_after_move(goal, moved, target)
                completed_job = update_job_progress(robot, jobs, tick)
                if completed_job is not None:
                    metrics.record_job_completion(completed_job)
            else:
                robot_objs = [robots[rid] for rid in unprocessed]
                winner = resolve_conflict(robot_objs, tick=tick, emit_event=emit_event, rng=rng, msg_bus=msg_bus)
                for rid in unprocessed:
                    robot = robots[rid]
                    if robot is winner:
                        _, (dx, dy), goal = intent_info[rid]
                        if world.is_free(*target):
                            robot.step_forward(dx, dy, world)
                            moved = True
                        else:
                            robot.wait_time += 1
                            moved = False
                        robot.update_state_after_move(goal, moved, target)
                        completed_job = update_job_progress(robot, jobs, tick)
                        if completed_job is not None:
                            metrics.record_job_completion(completed_job)
                    else:
                        _, _, goal = intent_info[rid]
                        robot.update_state_after_move(goal, False, target)

        # print emitted events (e.g., auction_won)
        for ev in events:
            # support Event dataclass or dict
            try:
                print(f"EVENT {ev.type} @tick {ev.tick}: robot={ev.robot_id} payload={ev.payload}")
            except Exception:
                print(f"EVENT: {ev}")

        # Local broadcasts at intersections: robots located on an
        # intersection cell announce {robot_id, urgency, ETA} to
        # neighbors within their sensing radius.
        local_broadcasts = {}
        for rid, robot in robots.items():
            if robot.quarantined:
                continue
            if world.is_intersection(robot.x, robot.y):
                # ETA: estimated ticks to the next intersection along path
                eta = None
                goal = choose_robot_goal(robot, jobs)
                if goal is not None:
                    eta = robot.eta_to_next_intersection(goal, world)
                msg = robot.broadcast_state(tick=tick)
                if msg is None:
                    continue
                # ensure local broadcast messages always carry a pos field
                if "pos" not in msg and "x" in msg and "y" in msg:
                    msg["pos"] = (msg["x"], msg["y"])
                msg.setdefault("ETA", eta)
                msg.setdefault("urgency", robot.package_urgency)
                # publish to message bus
                msg_bus.publish(msg, tick=tick)
                # deliver to neighbors within sensing radius
                for other_rid, other in robots.items():
                    if other_rid == rid:
                        continue
                    dist = abs(other.x - robot.x) + abs(other.y - robot.y)
                    if dist <= getattr(robot, "sensing_radius", 1):
                        local_broadcasts.setdefault(other_rid, []).append(msg)

        # print local broadcasts for debugging/inspection and record witness votes
        for receiver, msgs in local_broadcasts.items():
            witness_robot = robots[receiver]
            for m in msgs:
                claimed_pos = m.get("pos")
                verdict = trust_monitors[m["robot_id"]].witness_verdict(
                    witness_robot, m["robot_id"], claimed_pos, world
                )
                trust_monitors[m["robot_id"]].record_witness(receiver, verdict, tick)
                verdict_label = "MATCH" if verdict else "MISMATCH" if verdict is False else "UNSEEN"
                print(f"BROADCAST -> {receiver}: from={m['robot_id']} pos={m['pos']} urgency={m['urgency']} ETA={m['ETA']} witness={receiver} verdict={verdict_label}")

        # evaluate quorum-based quarantines after witnesses have reported
        for target_rid, monitor in trust_monitors.items():
            robot = robots.get(target_rid)
            if robot is None or robot.quarantined:
                continue
            if monitor.evaluate_for_quarantine(tick):
                actual_position = world.ground_truth_position(target_rid)
                claimed_position = None
                # attempt to use the last broadcast from the same tick
                for msgs in local_broadcasts.values():
                    for m in msgs:
                        if m["robot_id"] == target_rid:
                            claimed_position = m.get("pos")
                            break
                    if claimed_position is not None:
                        break
                robot.freeze()
                reports = monitor.witness_reports.get(tick, {})
                mismatch_count = sum(1 for match in reports.values() if not match)
                quarantine_event = Event(
                    type="quarantine",
                    tick=tick,
                    robot_id=target_rid,
                    payload={
                        "reason": "witness_quorum",
                        "claimed_position": claimed_position,
                        "actual_position": actual_position,
                        "mismatch_votes": mismatch_count,
                        "witness_count": len(reports),
                        "consensus_streak": monitor.consensus_streak,
                    },
                )
                emit_event(quarantine_event)
                metrics.record_quarantine(tick, robot.to_state(), reason="witness_quorum")
                print(f"{target_rid} QUARANTINED — witness quorum reached ({mismatch_count}/{len(reports)}) on tick {tick}.")

        for rid, robot in robots.items():
            metrics.record_robot_state(tick, robot.to_state())
            goal = choose_robot_goal(robot, jobs)
            status = "IDLE"
            if robot.carrying_package:
                status = f"CARRYING JOB={robot.assigned_job_id}"
            elif robot.assigned_job_id is not None:
                status = f"JOB={robot.assigned_job_id}"
            print(f"{rid}: pos=({robot.x},{robot.y}) wait={robot.wait_time} "
                  f"quarantined={robot.quarantined} goal={goal} {status} "
                  f"token={robot.token_budget:.2f}/{robot.token_capacity:.2f} "
                  f"livelock={getattr(robot, 'livelock_counter', 0)}")
    else:
        print(f"\nStopped after {max_ticks} ticks (some robots may not have finished).")

    metrics.print_summary(max_ticks)
    return metrics


if __name__ == "__main__":
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        args = sys.argv[2:]
        options = {}
        for index in range(0, len(args), 2):
            if index + 1 >= len(args):
                break
            raw_key = args[index].lstrip('-')
            key = raw_key.replace('-', '_')
            value = args[index + 1]
            if key in {"num_seeds", "start_seed", "max_ticks", "num_robots", "width", "height"}:
                options[key] = int(value)
            else:
                options[key] = value

        if mode == "compare":
            compare_two_fleets(num_robots=6, width=8, height=8, max_ticks=40, seed=42)
        elif mode == "compare_failure":
            compare_two_fleets(
                num_robots=6,
                width=8,
                height=8,
                max_ticks=40,
                seed=42,
                central_scheduler_failure_tick=10,
                central_scheduler_recovery_tick=20,
            )
        elif mode == "multi_seed":
            run_multi_seed_comparison(
                num_seeds=options.get("num_seeds", 5),
                start_seed=options.get("start_seed", 1),
                num_robots=options.get("num_robots", 6),
                width=options.get("width", 8),
                height=options.get("height", 8),
                max_ticks=options.get("max_ticks", 40),
                output_path=options.get("output"),
            )
        elif mode == "multi_seed_failure":
            run_multi_seed_comparison(
                num_seeds=options.get("num_seeds", 5),
                start_seed=options.get("start_seed", 1),
                num_robots=options.get("num_robots", 6),
                width=options.get("width", 8),
                height=options.get("height", 8),
                max_ticks=options.get("max_ticks", 40),
                central_scheduler_failure_tick=10,
                central_scheduler_recovery_tick=20,
                output_path=options.get("output"),
            )
        else:
            run_swarm(num_robots=6, width=8, height=8, max_ticks=40)
    else:
        run_swarm(num_robots=6, width=8, height=8, max_ticks=40)