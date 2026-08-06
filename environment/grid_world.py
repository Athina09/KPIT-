"""
GridWorld: the shared warehouse floor.
Every robot agent queries this to know what's around it.
"""

class GridWorld:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cell_occupancy = {}
        # spacing for intersections (cells where auctions happen)
        # default: every 2 cells (0,2,4,...)
        self.intersection_spacing = 2

    def is_free(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        return self.cell_occupancy.get((x, y)) is None

    def place_robot(self, robot_id, x, y):
        self.cell_occupancy[(x, y)] = robot_id

    def free_cells(self):
        return [(x, y)
                for x in range(self.width)
                for y in range(self.height)
                if self.cell_occupancy.get((x, y)) is None]

    def move_robot(self, robot_id, old_pos, new_pos):
        if self.cell_occupancy.get(old_pos) == robot_id:
            del self.cell_occupancy[old_pos]
        self.cell_occupancy[new_pos] = robot_id

    def ground_truth_position(self, robot_id):
        for pos, rid in self.cell_occupancy.items():
            if rid == robot_id:
                return pos
        return None

    def is_intersection(self, x, y):
        """Return True if (x,y) is considered an intersection cell.

        By default uses `intersection_spacing` so intersections occur at
        coordinates divisible by that spacing. This is a simple model
        suitable for initial development and tests.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        s = self.intersection_spacing
        return (x % s == 0) and (y % s == 0)

    def intersection_zone_center(self, x, y):
        """Return the nearest intersection center if (x,y) is in the zone.

        A robot is considered inside an intersection zone if it is on an
        intersection cell or immediately adjacent to one. This allows
        multi-way coordination for 4-way crossing conflicts.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        for nx in range(max(0, x - 1), min(self.width, x + 2)):
            for ny in range(max(0, y - 1), min(self.height, y + 2)):
                if self.is_intersection(nx, ny):
                    return (nx, ny)
        return None