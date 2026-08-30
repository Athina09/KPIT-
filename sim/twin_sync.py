"""
Digital-twin sync channel (Feature 6).

The simulation is the source of truth; a physical robot on a grid mat mirrors
its simulated twin. This module writes one JSON frame per tick to a JSON Lines
file (and optionally stdout). A thin firmware/bridge on the physical robot reads
the stream and:

  * drives the motors to the twin's (x, y) cell, and
  * when its twin is quarantined, FREEZES in place and raises the fault
    indicator (LED/buzzer) -- the visible "collective isolation" moment.

JSONL is transport-agnostic on purpose: pipe it over serial, MQTT, or a
WebSocket to whatever hardware you have. `PHYSICAL_ROBOT_ID` selects which
robot the single demo unit mirrors.
"""

import json


class TwinSync:
    def __init__(self, path="twin_stream.jsonl", physical_robot_id="R1", echo=False):
        self.path = path
        self.physical_robot_id = physical_robot_id
        self.echo = echo
        self._fh = open(path, "w")

    def __call__(self, frame):
        """Frame sink compatible with engine.run(frame_sink=...)."""
        self._fh.write(json.dumps(frame) + "\n")
        self._fh.flush()
        if self.echo:
            self._print_hardware_view(frame)

    def _print_hardware_view(self, frame):
        r = frame["robots"].get(self.physical_robot_id)
        if not r:
            return
        if r["quarantined"]:
            indicator = "FAULT LED=ON  BUZZER=ON  MOTORS=FROZEN"
        else:
            indicator = "status OK      MOTORS=RUN"
        print(f"[twin {self.physical_robot_id}] tick={frame['tick']:3d} "
              f"cell=({r['x']},{r['y']}) -> {indicator}")

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass
