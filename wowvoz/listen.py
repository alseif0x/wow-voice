"""The microphone, cut into phrases.

arecord streams 16 kHz mono; an energy VAD marks a phrase from the first 90 ms
of voice to the first `silenceMs` of quiet (short, so orders are quick), with a
little audio kept from before it started, and never longer than `maxPhraseMs`.
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
from collections import deque

RATE = 16000
FRAME_MS = 30
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2


def rms(frame: bytes) -> float:
    n = len(frame) // 2
    if not n:
        return 0.0
    s = struct.unpack(f"<{n}h", frame[: n * 2])
    return math.sqrt(sum(x * x for x in s) / n)


class Phrases:
    """Feed frames, get finished phrases (bytes) back."""

    def __init__(self, threshold: float, silence_ms: int, max_ms: int, pre_ms: int = 240):
        self.threshold = threshold
        self.silence_frames = max(1, silence_ms // FRAME_MS)
        self.max_frames = max_ms // FRAME_MS
        self.pre: deque[bytes] = deque(maxlen=max(1, pre_ms // FRAME_MS))
        self.cur: list[bytes] | None = None
        self.loud = 0
        self.quiet = 0

    def feed(self, frame: bytes) -> bytes | None:
        level = rms(frame)
        if self.cur is None:
            self.pre.append(frame)
            self.loud = self.loud + 1 if level >= self.threshold else 0
            if self.loud >= 3:  # 90 ms of voice
                self.cur = list(self.pre)
                self.pre.clear()
                self.quiet = 0
            return None
        self.cur.append(frame)
        self.quiet = self.quiet + 1 if level < self.threshold else 0
        if self.quiet >= self.silence_frames or len(self.cur) >= self.max_frames:
            out = b"".join(self.cur)
            self.cur = None
            self.loud = 0
            return out
        return None


def microphone(cmd: list[str]):
    """Yield FRAME_BYTES frames from the recording command until it ends."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            frame = p.stdout.read(FRAME_BYTES)
            if not frame or len(frame) < FRAME_BYTES:
                break
            yield frame
    finally:
        p.kill()


def other_listener_active(flag_file: str) -> bool:
    """WoW AI's "Talk" is recording (its bridge touches this file meanwhile): not an order."""
    return bool(flag_file) and os.path.exists(os.path.expanduser(flag_file))
