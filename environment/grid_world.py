"""
GridWorld: the shared warehouse floor.
Every robot agent queries this to know what's around it.
"""

class GridWorld:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cell_occupancy = {}

    def is_free(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        return self.cell_occupancy.get((x, y)) is None

    def place_robot(self, robot_id, x, y):
        self.cell_occupancy[(x, y)] = robot_id

    def move_robot(self, robot_id, old_pos, new_pos):
        if self.cell_occupancy.get(old_pos) == robot_id:
            del self.cell_occupancy[old_pos]
        self.cell_occupancy[new_pos] = robot_id

    def ground_truth_position(self, robot_id):
        for pos, rid in self.cell_occupancy.items():
            if rid == robot_id:
                return pos
        return None