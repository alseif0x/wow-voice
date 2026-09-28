"""What wow-voz knows about the game: which key does what, and whether WoW has focus.

The key map comes from the WoWVoz addon's saved data (WTF/Account/<account>/
SavedVariables/WoWVoz.lua), written by the game on /reload and logout; without
it, WoW's default keys are assumed. Focus is the X window the desktop reports as
active: keys are only ever pressed while it is WoW's.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import time

# WoW's defaults, for a character the addon hasn't reported yet.
DEFAULT_BINDINGS = {
    "MOVEFORWARD": ["W"], "MOVEBACKWARD": ["S"], "TURNLEFT": ["A"], "TURNRIGHT": ["D"],
    "STRAFELEFT": ["Q"], "STRAFERIGHT": ["E"], "JUMP": ["SPACE"], "TOGGLEAUTORUN": ["NUMLOCK"],
    "SITORSTAND": ["X"], "TARGETNEARESTENEMY": ["TAB"], "TOGGLEWORLDMAP": ["M"], "TOGGLEBACKPACK": ["B"],
    "TOGGLERUN": ["NUMPADDIVIDE"], "TOGGLEGAMEMENU": ["ESCAPE"],
}
DEFAULT_BAR_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "="]


# ---------------------------------------------------------------------------
# A small Lua table reader, enough for SavedVariables files
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r'\s*(?:(--[^\n]*)|("(?:\\.|[^"\\])*")|(\[)|(\])|(\{)|(\})|(=)|(,|;)|(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|(true|false|nil)|([A-Za-z_][A-Za-z0-9_]*))', re.S)


def _unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n.isdigit():
                j = i + 1
                while j < len(s) and j < i + 4 and s[j].isdigit():
                    j += 1
                out.append(chr(int(s[i + 1:j])))
                i = j
                continue
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_lua(src: str) -> dict:
    """Top-level `NAME = <value>` assignments of a SavedVariables file."""
    toks = []
    pos = 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            if src[pos:].strip() == "":
                break
            raise ValueError(f"unreadable Lua at {pos}")
        pos = m.end()
        if m.group(1):
            continue
        for kind, g in (("str", 2), ("[", 3), ("]", 4), ("{", 5), ("}", 6), ("=", 7), (",", 8), ("num", 9), ("kw", 10), ("name", 11)):
            if m.group(g) is not None:
                toks.append((kind, m.group(g)))
                break
    i = 0

    def value():
        nonlocal i
        kind, t = toks[i]
        i += 1
        if kind == "str":
            return _unescape(t[1:-1])
        if kind == "num":
            return float(t) if any(c in t for c in ".eE") else int(t)
        if kind == "kw":
            return {"true": True, "false": False, "nil": None}[t]
        if kind == "{":
            out, n = {}, 1
            while toks[i][0] != "}":
                if toks[i][0] == "[":
                    i += 1
                    key = value()
                    i += 1  # ]
                    i += 1  # =
                    out[key] = value()
                elif toks[i][0] == "name" and toks[i + 1][0] == "=":
                    key = toks[i][1]
                    i += 2
                    out[key] = value()
                else:
                    out[n] = value()
                    n += 1
                if toks[i][0] == ",":
                    i += 1
            i += 1
            return out
        raise ValueError(f"unexpected {t!r}")

    result = {}
    while i < len(toks):
        if toks[i][0] == "name" and i + 1 < len(toks) and toks[i + 1][0] == "=":
            name = toks[i][1]
            i += 2
            result[name] = value()
        else:
            i += 1
    return result


def as_list(t) -> list:
    if isinstance(t, dict):
        return [t[k] for k in sorted(k for k in t if isinstance(k, int))]
    return list(t or [])


# ---------------------------------------------------------------------------
# Key map
# ---------------------------------------------------------------------------

class KeyMap:
    """Binding command -> keys, and the named things on the action bars."""

    def __init__(self, bindings: dict, buttons: list, source: str, character: str = ""):
        self.bindings = bindings
        self.buttons = buttons       # [{slot, command, keys, kind, id, name}]
        self.source = source
        self.character = character

    def keys(self, command: str) -> list[str]:
        return self.bindings.get(command) or []

    def named_buttons(self) -> list[dict]:
        """Buttons with a spell, item or macro on them and a key to press, one per name."""
        seen, out = set(), []
        for b in self.buttons:
            name = (b.get("name") or "").strip()
            if name and b.get("keys") and name.lower() not in seen:
                seen.add(name.lower())
                out.append(b)
        return out

    def button_by_number(self, n: int) -> dict | None:
        """"botón 3" = main bar button 3."""
        for b in self.buttons:
            if b.get("command") == f"ACTIONBUTTON{n}":
                return b
        return {"slot": n, "command": f"ACTIONBUTTON{n}", "keys": [DEFAULT_BAR_KEYS[n - 1]]} if 1 <= n <= 12 else None


def default_keymap() -> KeyMap:
    buttons = [{"slot": i + 1, "command": f"ACTIONBUTTON{i + 1}", "keys": [k]} for i, k in enumerate(DEFAULT_BAR_KEYS)]
    return KeyMap(dict(DEFAULT_BINDINGS), buttons, "WoW defaults (the WoWVoz addon hasn't reported yet)")


def find_saved_variables(wtf_glob: str) -> list[str]:
    return sorted(glob.glob(os.path.expanduser(wtf_glob)), key=lambda p: os.path.getmtime(p), reverse=True)


def load_keymap(wtf_glob: str) -> KeyMap:
    for path in find_saved_variables(wtf_glob):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                db = parse_lua(fh.read()).get("WoWVozDB") or {}
        except (OSError, ValueError, IndexError):
            continue
        cur = db.get("current")
        if not isinstance(cur, dict):
            continue
        bindings = dict(DEFAULT_BINDINGS)
        for cmd, keys in (cur.get("bindings") or {}).items():
            ks = [k for k in as_list(keys) if isinstance(k, str)]
            if ks:
                bindings[cmd] = ks
        buttons = []
        for b in as_list(cur.get("buttons")):
            if isinstance(b, dict):
                buttons.append({"slot": b.get("slot"), "command": b.get("command"), "keys": [k for k in as_list(b.get("keys")) if isinstance(k, str)],
                                "kind": b.get("kind"), "id": b.get("id"), "name": b.get("name")})
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cur.get("time") or os.path.getmtime(path)))
        return KeyMap(bindings, buttons, f"{path} ({when})", str(cur.get("character") or ""))
    return default_keymap()


# ---------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------

class Focus:
    """Is the active X window WoW's? Asked through xprop, cached briefly."""

    def __init__(self, window_name: str = "World of Warcraft", ttl: float = 0.4):
        self.pattern = re.compile(window_name)
        self.ttl = ttl
        self._at = 0.0
        self._ok = False

    def _active_name(self) -> str:
        root = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"window id # (0x[0-9a-fA-F]+)", root)
        if not m or int(m.group(1), 16) == 0:
            return ""
        out = subprocess.run(["xprop", "-id", m.group(1), "WM_NAME", "_NET_WM_NAME"], capture_output=True, text=True, timeout=2).stdout
        names = re.findall(r'= "(.*)"', out)
        return names[-1] if names else ""

    def game_focused(self) -> bool:
        now = time.monotonic()
        if now - self._at > self.ttl:
            try:
                self._ok = bool(self.pattern.search(self._active_name()))
            except (OSError, subprocess.SubprocessError):
                self._ok = False
            self._at = now
        return self._ok
