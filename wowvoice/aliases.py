"""Your own words for things, and the ones wow-voice learned from its misses.

Two files, same format, both reloaded when they change:

  ~/.config/wow-voice/aliases.json   yours, edited by hand
  ~/.config/wow-voice/learned.json   written by wow-voice-learn (the log reviewer)

    {
      "evis": "button:Eviscerar",
      "patada": "button:Patada",
      "quieres pierda": "turn_left",
      "gira un pelín": {"order": "turn_right", "degrees": 15}
    }

A value is an order id (see commands.INTENTS), "button:<name on the action bar>",
or {"order": id, "degrees"/"count"/"seconds": n}. Yours win over learned ones.
"""

from __future__ import annotations

import json
import os

from . import commands as C

USER_FILE = os.path.expanduser("~/.config/wow-voice/aliases.json")
LEARNED_FILE = os.path.expanduser("~/.config/wow-voice/learned.json")


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def valid(value, buttons: list[dict]) -> bool:
    if isinstance(value, str):
        if value.startswith("button:"):
            name = C.spoken_name(value[7:])
            return any(C.spoken_name(b.get("name") or "") == name for b in buttons)
        return value in C.INTENTS
    if isinstance(value, dict):
        return value.get("order") in C.INTENTS
    return False


def to_order(value, buttons: list[dict], text: str) -> C.Order | None:
    if isinstance(value, str) and value.startswith("button:"):
        name = C.spoken_name(value[7:])
        for b in buttons:
            if C.spoken_name(b.get("name") or "") == name:
                return C.Order("button", button=b, text=text, via="alias")
        return None
    spec = value if isinstance(value, dict) else {"order": value}
    kind = spec.get("order")
    if kind not in C.INTENTS:
        return None
    o = C.Order(kind, text=text, via="alias")
    for k in ("count", "seconds", "degrees"):
        if isinstance(spec.get(k), (int, float)):
            setattr(o, k, spec[k] if k != "count" else int(spec[k]))
    if C.INTENTS[kind][1] == "turn" and not o.degrees:
        o.degrees = 180.0 if kind == "turn_around" else 45.0
    return o


class Aliases:
    def __init__(self, user_file: str = USER_FILE, learned_file: str = LEARNED_FILE):
        self.files = [learned_file, user_file]  # later wins
        self.mtimes: tuple = ()
        self.table: dict[str, object] = {}

    def refresh(self) -> bool:
        """Reload when a file changed; True when the table changed."""
        mt = tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in self.files)
        if mt == self.mtimes:
            return False
        self.mtimes = mt
        table = {}
        for f in self.files:
            for phrase, value in _read(f).items():
                n = C.norm(str(phrase))
                if n:
                    table[n] = value
        changed = table != self.table
        self.table = table
        return changed

    def phrases(self) -> list[str]:
        return list(self.table)

    def order_for(self, text: str, buttons: list[dict]) -> C.Order | None:
        v = self.table.get(C.norm(text))
        return to_order(v, buttons, text) if v is not None and valid(v, buttons) else None
