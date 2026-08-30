"""
StatePacket: the signed, timestamped message a robot broadcasts to neighbors.

In a real deployment this would be cryptographically signed (e.g. Ed25519).
Here we use a lightweight HMAC-style digest so the trust layer can detect
tampering/spoofing in addition to position lies. Each robot has its own
secret key; a packet whose signature doesn't verify against the claimed
sender's key is dropped as a spoof.
"""

from dataclasses import dataclass, asdict
import hashlib
import hmac


@dataclass
class StatePacket:
    robot_id: str
    x: int
    y: int
    heading: tuple          # (dx, dy) unit-ish heading
    velocity: float
    token_bid: float
    tick: int
    ttl: int = 2
    signature: str = ""

    def _payload_bytes(self) -> bytes:
        core = (
            f"{self.robot_id}|{self.x}|{self.y}|{self.heading}|"
            f"{self.velocity}|{self.token_bid}|{self.tick}"
        )
        return core.encode("utf-8")

    def sign(self, secret_key: bytes) -> "StatePacket":
        self.signature = hmac.new(secret_key, self._payload_bytes(), hashlib.sha256).hexdigest()
        return self

    def verify(self, secret_key: bytes) -> bool:
        expected = hmac.new(secret_key, self._payload_bytes(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.signature)

    @property
    def pos(self):
        return (self.x, self.y)

    def to_dict(self):
        return asdict(self)
