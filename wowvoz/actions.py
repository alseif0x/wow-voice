"""Doing an Order: the keys, in the game only, one order at a time.

Orders go into a queue and a worker thread presses their keys. "para" is special:
it jumps the queue, cuts a hold short, drops what was waiting and releases every
key. Keys are pressed only while WoW is the active window (checked before every
key), and holds are capped, so a misheard order can't run away.
"""

from __future__ import annotations

import queue
import threading
import time

from .commands import INTENTS, Order
from .keyboard import Unsupported, resolve


class Actions:
    def __init__(self, keyboard, keymap, xkeymap, focus, cfg: dict, log=print):
        self.kb = keyboard
        self.keymap = keymap
        self.xkeymap = xkeymap
        self.focus = focus
        self.cfg = cfg
        self.log = log
        self.q: queue.Queue[Order] = queue.Queue()
        self.stop_event = threading.Event()
        self.autorun = False
        self.paused = bool(cfg.get("startPaused", False))
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    # -- the chords for a binding command ---------------------------------

    def chord(self, command: str) -> list[int] | None:
        for key in self.keymap.keys(command):
            try:
                return resolve(key, self.xkeymap) if self.xkeymap else [hash(key) % 200 + 1]
            except Unsupported:
                continue
        return None

    def button_chord(self, button: dict) -> list[int] | None:
        for key in button.get("keys") or []:
            try:
                return resolve(key, self.xkeymap) if self.xkeymap else [hash(key) % 200 + 1]
            except Unsupported:
                continue
        return None

    # -- queueing ------------------------------------------------------------

    def submit(self, order: Order) -> str:
        """Queue an order; returns what happens, for the log."""
        if order.kind == "pause":
            self.paused = True
            self.halt()
            return "voice orders paused (say \"voz activa\")"
        if order.kind == "resume":
            self.paused = False
            return "voice orders on"
        if self.paused:
            return "ignored: paused"
        if order.kind == "stop":
            self.halt()
            if self.autorun:
                self.q.put(Order("_cancel_autorun"))
            return "stop"
        self.q.put(order)
        return "queued"

    def halt(self) -> None:
        self.stop_event.set()
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        self.kb.release_all()

    # -- the worker -----------------------------------------------------------

    def _run(self) -> None:
        while True:
            order = self.q.get()
            self.stop_event.clear()
            try:
                self._do(order)
            except Exception as e:  # keep serving
                self.log(f"order {order.kind} failed: {e}")
                self.kb.release_all()

    def _focused(self) -> bool:
        if self.focus is None or self.focus.game_focused():
            return True
        self.log("WoW is not the active window: nothing pressed")
        return False

    def _do(self, o: Order) -> None:
        c = self.cfg
        if o.kind == "_cancel_autorun":
            chord = self.chord("MOVEBACKWARD")
            if chord and self._focused():
                self.kb.press(chord, 0.06)
            self.autorun = False
            return
        if o.kind == "button":
            b = o.button or {}
            if "number" in b:
                b = self.keymap.button_by_number(b["number"]) or {}
            chord = self.button_chord(b)
            if not chord:
                self.log(f"no key on that button ({b.get('name') or b.get('command')})")
                return
            if self._focused():
                self.kb.press(chord)
            return
        command, how, _, _ = INTENTS[o.kind]
        chord = self.chord(command) if command else None
        if not chord:
            self.log(f"no usable key for {command} (bind it to a keyboard key in WoW)")
            return
        if not self._focused():
            return
        if how == "tap":
            n = max(1, min(int(o.count or 1), int(c.get("maxCount", 5))))
            for i in range(n):
                if self.stop_event.is_set() or not self._focused():
                    break
                self.kb.press(chord)
                if i + 1 < n:
                    self.stop_event.wait(float(c.get("jumpInterval", 0.9)) if o.kind == "jump" else 0.25)
            if o.kind == "autorun":
                self.autorun = not self.autorun
        elif how == "hold":
            secs = o.seconds or float(c.get("holdSeconds", 1.0))
            secs = max(0.1, min(secs, float(c.get("maxHoldSeconds", 5.0))))
            self.kb.hold(chord, secs, self.stop_event)
            if o.kind in ("forward", "back"):
                self.autorun = False  # walking by hand ends autorun
        elif how == "turn":
            # Keyboard turning in WoW is 180 degrees a second.
            deg = max(5.0, min(float(o.degrees or c.get("turnDegrees", 45)), 180.0))
            self.kb.hold(chord, deg / float(c.get("turnDegreesPerSecond", 180)), self.stop_event)
