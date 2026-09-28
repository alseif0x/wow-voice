"""Short tones on the PC's speakers, so you know what voice control is doing
without looking: on (rising), off (falling), and "I'm paused" (two low blips)
when an order is heard while paused."""

from __future__ import annotations

import math
import os
import struct
import subprocess
import time
import wave

RATE = 22050
TONES = {
    "on": [(660, 0.09), (990, 0.12)],
    "off": [(990, 0.09), (660, 0.12)],
    "paused": [(440, 0.07), (0, 0.05), (440, 0.07)],
}


def _write(path: str, tones) -> None:
    frames = bytearray()
    for freq, secs in tones:
        n = int(RATE * secs)
        for i in range(n):
            env = min(1.0, i / (RATE * 0.008), (n - i) / (RATE * 0.008))
            v = int(math.sin(2 * math.pi * freq * i / RATE) * 8000 * env) if freq else 0
            frames += struct.pack("<h", v)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


class Beeps:
    def __init__(self, cfg: dict):
        self.on = bool(cfg.get("beeps", True))
        self.cmd = list(cfg.get("playCommand") or ["pw-play"])
        self.dir = os.path.expanduser("~/.cache/wow-voz")
        self.last: dict[str, float] = {}
        os.makedirs(self.dir, exist_ok=True)
        for name, tones in TONES.items():
            _write(os.path.join(self.dir, f"{name}.wav"), tones)

    def play(self, name: str, every: float = 0.0) -> None:
        if not self.on:
            return
        now = time.monotonic()
        if every and now - self.last.get(name, -1e9) < every:
            return
        self.last[name] = now
        try:
            subprocess.Popen(self.cmd + [os.path.join(self.dir, f"{name}.wav")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
