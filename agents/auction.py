"""
Auction: resolves conflicts when two+ robots want the same cell.
Every robot runs this SAME function locally — that's what makes
it decentralized. If both robots compute it correctly, they
independently arrive at the same winner without talking to a server.
"""

def resolve_conflict(robots_wanting_cell):
    """
    robots_wanting_cell: list of RobotAgent instances all trying
    to move into the same cell this tick.
    Returns: the winning RobotAgent.
    """
    if len(robots_wanting_cell) == 1:
        return robots_wanting_cell[0]

    bids = [(robot, robot.compute_bid()) for robot in robots_wanting_cell]
    winner, winning_bid = max(bids, key=lambda pair: pair[1])

    for robot, bid in bids:
        if robot is not winner:
            robot.wait_time += 1

    return winner