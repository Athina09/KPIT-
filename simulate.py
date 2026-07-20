from environment.grid_world import GridWorld
from agents.robot_agent import RobotAgent
from agents.trust_monitor import TrustMonitor


def run_demo():
    world = GridWorld(width=5, height=5)

    robot_a = RobotAgent("R1", x=0, y=2, package_urgency=2.0)
    robot_b = RobotAgent("R2", x=4, y=2, package_urgency=1.0)
    world.place_robot("R1", 0, 2)
    world.place_robot("R2", 4, 2)

    goals = {"R1": 4, "R2": 0}
    robots = {"R1": robot_a, "R2": robot_b}
    trust_monitors = {"R1": TrustMonitor(), "R2": TrustMonitor()}

    for tick in range(20):
        print(f"\n--- Tick {tick} ---")

        # each tick, the higher bid (urgency + wait_time) goes first --
        # this IS the token auction, just applied as move-order every tick
        order = sorted(robots.keys(), key=lambda rid: robots[rid].compute_bid(), reverse=True)

        for rid in order:
            robot = robots[rid]
            if robot.quarantined:
                continue
            goal_x = goals[rid]

            if robot.x == goal_x and robot.y == 2:
                continue  # already home, sitting in the main lane

            dx, dy = 0, 0
            if robot.x != goal_x:
                step = 1 if robot.x < goal_x else -1
                if world.is_free(robot.x + step, robot.y):
                    dx, dy = step, 0
                else:
                    # forward blocked -- sidestep into an adjacent row to get around
                    for try_dy in (1, -1):
                        if world.is_free(robot.x, robot.y + try_dy):
                            dx, dy = 0, try_dy
                            break
            else:
                # reached the right x, but sidestepped off the main lane -- return to it
                if robot.y != 2:
                    step = 1 if robot.y < 2 else -1
                    if world.is_free(robot.x, robot.y + step):
                        dx, dy = 0, step

            if (dx, dy) != (0, 0):
                robot.step_forward(dx, dy, world)
            else:
                robot.wait_time += 1

        for rid, robot in robots.items():
            if robot.quarantined:
                continue
            broadcast = robot.broadcast_state()
            if trust_monitors[rid].check(broadcast, world):
                robot.freeze()
                print(f"{rid} QUARANTINED — broadcast didn't match ground truth.")

        for rid, robot in robots.items():
            print(f"{rid}: pos=({robot.x},{robot.y}) wait={robot.wait_time} quarantined={robot.quarantined}")

        if robot_a.x == goals["R1"] and robot_a.y == 2 and robot_b.x == goals["R2"] and robot_b.y == 2:
            print("\nBoth robots reached their goals.")
            break


if __name__ == "__main__":
    run_demo()