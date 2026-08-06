from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any


@dataclass
class FaultProfile:
    """Defines how a robot's broadcast state is corrupted for testing."""
    description: str = "generic fault"
    active_from_tick: int = 0
    active_until_tick: Optional[int] = None
    inject_position_offset: Optional[Tuple[int, int]] = None
    fake_token_budget: Optional[float] = None
    fake_urgency: Optional[float] = None
    wrong_status: Optional[str] = None
    eta_bias: float = 0.0
    silent: bool = False
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def is_active(self, tick: int) -> bool:
        if tick < self.active_from_tick:
            return False
        if self.active_until_tick is not None and tick > self.active_until_tick:
            return False
        return True

    def apply(self, payload: Optional[dict], robot, tick: Optional[int] = None) -> Optional[dict]:
        """Apply fault transformations to a broadcast payload."""
        if not self.is_active(tick if tick is not None else 0):
            return payload

        if self.silent:
            return None

        if payload is None:
            payload = {}

        faulty = dict(payload)
        if self.inject_position_offset is not None and "x" in faulty and "y" in faulty:
            faulty["x"] = faulty["x"] + self.inject_position_offset[0]
            faulty["y"] = faulty["y"] + self.inject_position_offset[1]
            faulty["fault_type"] = "lying_position"

        if self.fake_token_budget is not None:
            faulty["token_budget"] = self.fake_token_budget
            faulty["fault_type"] = faulty.get("fault_type", "false_token")

        if self.fake_urgency is not None:
            faulty["urgency"] = self.fake_urgency
            faulty["fault_type"] = faulty.get("fault_type", "false_urgency")

        if self.wrong_status is not None:
            faulty["status"] = self.wrong_status
            faulty["fault_type"] = faulty.get("fault_type", "false_status")

        if self.eta_bias and "ETA" in faulty and faulty["ETA"] is not None:
            faulty["ETA"] = max(0, faulty["ETA"] + self.eta_bias)
            faulty["fault_type"] = faulty.get("fault_type", "wrong_eta")

        if self.extra_metadata:
            faulty.update(self.extra_metadata)
            faulty["fault_type"] = faulty.get("fault_type", "custom_fault")

        return faulty
