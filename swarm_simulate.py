import random
from environment.grid_world import GridWorld
from agents.robot_agent import RobotAgent
from agents.lying_robot_agent import LyingRobotAgent
from agents.trust_monitor import TrustMonitor


def greedy_step(robot, goal):
    """Decide candidate steps toward the goal, biggest-gap axis first."""
    gx, gy = goal
    dx_needed = gx - robot.x
    dy_needed = gy - robot.y

    if dx_needed == 0 and dy_needed == 0:
        return []

    moves_in_order = []
    if abs(dx_needed) >= abs(dy_needed) and dx_needed != 0:
        moves_in_order.append((1 if dx_needed > 0 else -1, 0))
        if dy_needed != 0:
            moves_in_order.append((0, 1 if dy_needed > 0 else -1))
    elif dy_needed != 0:
        moves_in_order.append((0, 1 if dy_needed > 0 else -1))
        if dx_needed != 0:
            moves_in_order.append((1 if dx_needed > 0 else -1, 0))

    return moves_in_order


def run_swarm(num_robots=6, width=8, height=8, max_ticks=40, seed=42):
    rng = random.Random(seed)
    world = GridWorld(width=width, height=height)

    robots = {}
    trust_monitors = {}
    goals = {}
    used_cells = set()

    for i in range(num_robots):
        rid = f"R{i+1}"

        while True:
            sx, sy = rng.randrange(width), rng.randrange(height)
            if (sx, sy) not in used_cells:
                used_cells.add((sx, sy))
                break

        while True:
            gx, gy = rng.randrange(width), rng.randrange(height)
            if (gx, gy) != (sx, sy):
                break

        urgency = round(rng.uniform(1.0, 3.0), 2)
        if i == 2:  # make R3 the liar for this test
            robot = LyingRobotAgent(rid, sx, sy, package_urgency=urgency)
        else:
            robot = RobotAgent(rid, sx, sy, package_urgency=urgency)
        world.place_robot(rid, sx, sy)

        robots[rid] = robot
        goals[rid] = (gx, gy)
        trust_monitors[rid] = TrustMonitor()

    print("Swarm initialized:")
    for rid, robot in robots.items():
        print(f"  {rid}: start=({robot.x},{robot.y}) goal={goals[rid]} urgency={robot.package_urgency}")

    for tick in range(max_ticks):
        print(f"\n--- Tick {tick} ---")

        active = [rid for rid, r in robots.items() if not r.quarantined
                  and (r.x, r.y) != goals[rid]]
        if not active:
            print("All active robots have reached their goals.")
            break

        order = sorted(active, key=lambda rid: robots[rid].compute_bid(), reverse=True)
        claimed_cells = set()

        for rid in order:
            robot = robots[rid]
            candidates = greedy_step(robot, goals[rid])
            moved = False

            for dx, dy in candidates:
                target = (robot.x + dx, robot.y + dy)
                if world.is_free(*target) and target not in claimed_cells:
                    robot.step_forward(dx, dy, world)
                    claimed_cells.add(target)
                    moved = True
                    break

            if not moved:
                robot.wait_time += 1

        for rid, robot in robots.items():
            if robot.quarantined:
                continue
            broadcast = robot.broadcast_state()
            if trust_monitors[rid].check(broadcast, world):
                robot.freeze()
                print(f"{rid} QUARANTINED — broadcast didn't match ground truth.")

        for rid, robot in robots.items():
            status = "DONE" if (robot.x, robot.y) == goals[rid] else ""
            print(f"{rid}: pos=({robot.x},{robot.y}) wait={robot.wait_time} "
                  f"quarantined={robot.quarantined} {status}")
    else:
        print(f"\nStopped after {max_ticks} ticks (some robots may not have finished).")


if __name__ == "__main__":
    run_swarm(num_robots=6, width=8, height=8, max_ticks=40)