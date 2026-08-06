import random
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class Job:
    job_id: str
    pickup: Tuple[int, int]
    dropoff: Tuple[int, int]
    urgency: float
    spawned_tick: int
    assigned_robot: Optional[str] = None
    status: str = "pending"  # pending, assigned, picked_up, delivered
    picked_up_tick: Optional[int] = None
    delivered_tick: Optional[int] = None
    metadata: dict = field(default_factory=dict)


class JobGenerator:
    def __init__(self, world, spawn_rate: float = 0.3, urgency_range=(1.0, 10.0), seed=None):
        self.world = world
        self.spawn_rate = spawn_rate
        self.urgency_range = urgency_range
        self.rng = random.Random(seed)
        self.next_job_id = 1

    def _pick_location(self, excluded=None):
        excluded = excluded or set()
        free = [pos for pos in self.world.free_cells() if pos not in excluded]
        if not free:
            return None
        return self.rng.choice(free)

    def generate(self, tick: int, max_new_jobs=2):
        num_jobs = 0
        while num_jobs < max_new_jobs and self.rng.random() < self.spawn_rate:
            num_jobs += 1

        new_jobs = []
        for _ in range(num_jobs):
            pickup = self._pick_location()
            if pickup is None:
                break
            excluded = {pickup}
            dropoff = self._pick_location(excluded=excluded)
            if dropoff is None:
                break
            urgency = round(self.rng.uniform(*self.urgency_range), 2)
            job = Job(
                job_id=f"J{self.next_job_id}",
                pickup=pickup,
                dropoff=dropoff,
                urgency=urgency,
                spawned_tick=tick,
            )
            self.next_job_id += 1
            new_jobs.append(job)
        return new_jobs
