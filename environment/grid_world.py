"""
GridWorld: the shared warehouse floor.

Every robot agent queries this to know what's around it. The world holds
ground-truth occupancy (used by the trust layer to catch liars) plus static
obstacles and designated intersection cells (conflict zones).

The original minimal API (is_free / place_robot / move_robot /
ground_truth_position) is preserved so the legacy demos keep working; the new
decentralized engine uses the richer helpers (obstacles, neighbors, A*).
"""

from __future__ import annotations

import heapq
import random


class GridWorld:
    def __init__(self, width: int, height: int, obstacles=None, intersections=None, intersection_spacing: int = 2):
        self.width = width
        self.height = height
        self.cell_occupancy = {}
        self.intersection_spacing = intersection_spacing
        self.obstacles = set(obstacles) if obstacles else set()
        self.intersection_cells = set(intersections) if intersections else set()

    # ------------------------------------------------------------------ #
    # construction helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def from_config(cls, config, reserved=None):
        """Build a world with random obstacles from a SimConfig.

        `reserved` cells (robot starts/goals) are never turned into walls.
        """
        rng = random.Random(config.seed)
        reserved = set(reserved or set())
        world = cls(config.width, config.height, intersections=config.intersections())

        num_walls = int(config.width * config.height * config.obstacle_density)
        attempts = 0
        while len(world.obstacles) < num_walls and attempts < num_walls * 20:
            attempts += 1
            cx, cy = rng.randrange(config.width), rng.randrange(config.height)
            cell = (cx, cy)
            if cell in reserved or cell in world.intersection_cells:
                continue
            world.obstacles.add(cell)
        return world

    # ------------------------------------------------------------------ #
    # occupancy (ground truth)
    # ------------------------------------------------------------------ #
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_free(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        if (x, y) in self.obstacles:
            return False
        return self.cell_occupancy.get((x, y)) is None

    def is_walkable(self, x: int, y: int) -> bool:
        """Free of static walls & in bounds (ignores transient robots)."""
        return self.in_bounds(x, y) and (x, y) not in self.obstacles

    def place_robot(self, robot_id: str, x: int, y: int) -> None:
        self.cell_occupancy[(x, y)] = robot_id

    def free_cells(self):
        return [
            (x, y)
            for x in range(self.width)
            for y in range(self.height)
            if self.cell_occupancy.get((x, y)) is None and (x, y) not in self.obstacles
        ]

    def move_robot(self, robot_id: str, old_pos: tuple[int, int], new_pos: tuple[int, int]) -> None:
        if self.cell_occupancy.get(old_pos) == robot_id:
            del self.cell_occupancy[old_pos]
        self.cell_occupancy[new_pos] = robot_id

    def remove_robot(self, robot_id: str) -> None:
        for pos, rid in list(self.cell_occupancy.items()):
            if rid == robot_id:
                del self.cell_occupancy[pos]

    def ground_truth_position(self, robot_id: str) -> tuple[int, int] | None:
        for pos, rid in self.cell_occupancy.items():
            if rid == robot_id:
                return pos
        return None

    def occupant(self, x: int, y: int) -> str | None:
        return self.cell_occupancy.get((x, y))

    def is_intersection(self, x: int, y: int) -> bool:
        """Return True if (x,y) is considered an intersection cell."""
        if not self.in_bounds(x, y):
            return False
        if self.intersection_cells:
            return (x, y) in self.intersection_cells
        s = self.intersection_spacing
        return (x % s == 0) and (y % s == 0)

    def intersection_zone_center(self, x: int, y: int) -> tuple[int, int] | None:
        """Return the nearest intersection center if (x,y) is in the zone.

        A robot is considered inside an intersection zone if it is on an
        intersection cell or immediately adjacent to one. This allows
        multi-way coordination for 4-way crossing conflicts.
        """
        if not self.in_bounds(x, y):
            return None
        for nx in range(max(0, x - 1), min(self.width, x + 2)):
            for ny in range(max(0, y - 1), min(self.height, y + 2)):
                if self.is_intersection(nx, ny):
                    return (nx, ny)
        return None

    # ------------------------------------------------------------------ #
    # local sensing (Feature 3: neighbors verify each other)
    # ------------------------------------------------------------------ #
    def robots_within(self, x: int, y: int, radius: float) -> dict[str, tuple[int, int]]:
        """Ground-truth occupied cells within Euclidean `radius` of (x, y).

        Returns {robot_id: (x, y)}. This models a robot's own local sensor
        (range/bearing) that the trust layer cross-checks against broadcasts.
        """
        found = {}
        for (ox, oy), rid in self.cell_occupancy.items():
            if (ox, oy) == (x, y):
                continue
            if ((ox - x) ** 2 + (oy - y) ** 2) ** 0.5 <= radius:
                found[rid] = (ox, oy)
        return found

    # ------------------------------------------------------------------ #
    # local A* (Feature 4: no global planner, each robot replans locally)
    # ------------------------------------------------------------------ #
    def astar(self, start: tuple[int, int], goal: tuple[int, int], blocked=None) -> list[tuple[int, int]]:
        """Shortest 4-connected path from start to goal avoiding walls and
        `blocked` cells (e.g. quarantined robots' last-known positions).

        Returns a list of cells [start, ..., goal] or [] if unreachable.
        """
        blocked = set(blocked or set())
        if start == goal:
            return [start]

        def h(a, b):
            return abs(a[0] - b[0]) + abs(a[1] - b[1])

        open_heap = [(h(start, goal), 0, start)]
        came_from = {}
        g_score = {start: 0}
        closed = set()

        while open_heap:
            _, g, current = heapq.heappop(open_heap)
            if current == goal:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                return list(reversed(path))
            if current in closed:
                continue
            closed.add(current)

            cx, cy = current
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                nbr = (nx, ny)
                if not self.is_walkable(nx, ny):
                    continue
                if nbr in blocked and nbr != goal:
                    continue
                tentative = g + 1
                if tentative < g_score.get(nbr, float("inf")):
                    came_from[nbr] = current
                    g_score[nbr] = tentative
                    heapq.heappush(open_heap, (tentative + h(nbr, goal), tentative, nbr))
        return []
