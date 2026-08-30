"""
CommsBus: local-only, neighbor-to-neighbor broadcast/gossip (Feature 2).

There is NO central router. Each tick, robots publish a signed StatePacket to
the bus; the bus only delivers a packet to robots that are physically within
`comm_range` of the sender (RF/UWB/IR neighbor sensing). Packets carry a TTL so
a robot can re-gossip a neighbor's packet one or two hops further, which is how
discrepancy scores propagate for distributed voting -- still without any global
node ever seeing the whole fleet.
"""

from collections import defaultdict


class CommsBus:
    def __init__(self, world, config):
        self.world = world
        self.config = config
        self._outbox = []                       # packets published this tick
        self.delivered = defaultdict(list)      # robot_id -> [StatePacket] received

    def reset_tick(self):
        self._outbox = []
        self.delivered = defaultdict(list)

    def publish(self, packet):
        self._outbox.append(packet)

    def _in_range(self, a_pos, b_pos):
        (ax, ay), (bx, by) = a_pos, b_pos
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 <= self.config.comm_range

    def deliver(self, robots):
        """Route this tick's outbox to in-range receivers (single hop).

        `robots` is {robot_id: RobotAgent}. Delivery is based on GROUND-TRUTH
        sender position (physical RF), not the possibly-lying claimed position.
        """
        for packet in self._outbox:
            sender_pos = self.world.ground_truth_position(packet.robot_id)
            if sender_pos is None:
                continue
            for rid, robot in robots.items():
                if rid == packet.robot_id:
                    continue
                if self._in_range(sender_pos, (robot.x, robot.y)):
                    self.delivered[rid].append(packet)

    def gossip(self, robots, rumors):
        """Second-stage propagation of discrepancy rumors (multi-hop, TTL-bound).

        `rumors` is a list of (about_id, reporter_id, score, ttl). Each robot
        forwards rumors it holds to its in-range neighbors while ttl > 0. This
        is how a local majority vote forms without a central aggregator.
        """
        forwarded = defaultdict(list)
        for about_id, reporter_id, score, ttl in rumors:
            if ttl <= 0:
                continue
            src_pos = self.world.ground_truth_position(reporter_id)
            if src_pos is None:
                continue
            for rid, robot in robots.items():
                if rid == reporter_id:
                    continue
                if self._in_range(src_pos, (robot.x, robot.y)):
                    forwarded[rid].append((about_id, reporter_id, score, ttl - 1))
        return forwarded

    def inbox(self, robot_id):
        return self.delivered.get(robot_id, [])
