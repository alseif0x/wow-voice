"""Doing an Order: the keys, in the game only, one order at a time.

Orders go into a queue and a worker thread presses their keys. "para" is special:
it jumps the queue, cuts a hold short, drops what was waiting and releases every
key. Keys are pressed only while WoW is the active window (checked before every
key), and holds are capped, so a misheard order can't run away.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import wave

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
        self.walking = False  # WoW starts every session running
        self.paused = bool(cfg.get("startPaused", False))
        self.notify = lambda what: None  # "ok" / "error": set by main for the beeps
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
        self.notify("error")
        return False

    def _hand_to_wow_ai(self, o: Order) -> None:
        """"oye IA ...": leave the phrase for WoW AI's bridge, then press its Talk
        key; the bridge takes this audio instead of recording (docs in its voice.js)."""
        chord = self.chord("WOWAI_TALK")
        if not chord:
            self.log("WoW AI's Talk has no key (is WoW AI loaded, and the WoW Voz addon up to date?)")
            self.notify("error")
            return
        path = os.path.expanduser(self.cfg.get("wowAiHandoff", "~/.cache/wow-ai/voice-in.wav"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pcm = (o.extra or {}).get("pcm") or b""
        with wave.open(path + ".tmp", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm)
        os.replace(path + ".tmp", path)
        with open(path + ".json", "w", encoding="utf-8") as f:
            json.dump({"text": o.text, "t": time.time()}, f, ensure_ascii=False)
        if self._focused():
            self.kb.press(chord)
            self.notify("ok")

    def _do(self, o: Order) -> None:
        c = self.cfg
        if o.kind == "_cancel_autorun":
            chord = self.chord("MOVEBACKWARD")
            if chord and self._focused():
                self.kb.press(chord, 0.06)
            self.autorun = False
            return
        if o.kind == "ask_ai":
            self._hand_to_wow_ai(o)
            return
        if o.kind == "combo":
            # Each part as if said on its own, one after another; "para" still cuts them all.
            for part in (o.extra or {}).get("orders", []):
                if self.stop_event.is_set():
                    break
                self._do(part)
                self.stop_event.wait(0.15)
            return
        if o.kind == "button":
            b = o.button or {}
            if "number" in b:
                b = self.keymap.button_by_number(b["number"]) or {}
            chord = self.button_chord(b)
            if not chord:
                self.log(f"no key on that button ({b.get('name') or b.get('command')})")
                self.notify("error")
                return
            if self._focused():
                self.kb.press(chord)
                self.notify("ok")
            return
        command, how, _, _ = INTENTS[o.kind]
        chord = self.chord(command) if command else None
        if not chord:
            self.log(f"no usable key for {command} (bind it to a keyboard key in WoW, or /reload with the WoW Voz addon)")
            self.notify("error")
            return
        if not self._focused():
            return
        self.notify("ok")
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
        elif how == "jumpmove":
            jump = self.chord("JUMP")
            if not jump:
                self.log("no usable key for JUMP")
                return
            # Hold the direction, jump once it is moving, keep going until the landing.
            done = threading.Event()

            def hold_dir():
                self.kb.hold(chord, float(c.get("jumpMoveSeconds", 0.9)), self.stop_event)
                done.set()
            t = threading.Thread(target=hold_dir, daemon=True)
            t.start()
            if not self.stop_event.wait(0.12):
                self.kb.press(jump)
            done.wait(3)
        elif how in ("walkmode", "runmode", "walkgo", "rungo"):
            # One key toggles walk/run: press it only when it changes something.
            want_walk = how in ("walkmode", "walkgo")
            if self.walking != want_walk:
                self.kb.press(chord)
                self.walking = want_walk
            # "camina" / "corre" also get going (autorun, until "para"); "despacio" / "más rápido" only change the pace.
            if how in ("walkgo", "rungo") and not self.autorun:
                go = self.chord("TOGGLEAUTORUN")
                if not go:
                    self.log("no usable key for TOGGLEAUTORUN")
                    return
                self.stop_event.wait(0.05)
                self.kb.press(go)
                self.autorun = True
        elif how == "turn":
            # Keyboard turning in WoW is 180 degrees a second.
            deg = max(5.0, min(float(o.degrees or c.get("turnDegrees", 45)), 180.0))
            self.kb.hold(chord, deg / float(c.get("turnDegreesPerSecond", 180)), self.stop_event)
