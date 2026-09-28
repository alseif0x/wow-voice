"""Linux: a /dev/uinput keyboard, the X keyboard map, xprop for the active window,
the game window's corner read through X, and PipeWire / PulseAudio / ALSA for beeps.
WoW runs under Wine or Proton, whose window is an X (or Xwayland) window."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess

from ..game import Focus  # noqa: F401  (xprop)
from ..keyboard import Keyboard  # noqa: F401  (/dev/uinput)
from ..keyboard import XKeymap as Keymap  # noqa: F401
from ..screen import Switch  # noqa: F401  (the game window through X)


def setup() -> None:
    """Point DISPLAY/XAUTHORITY at the Xwayland WoW lives on (GNOME and others)."""
    if not os.environ.get("DISPLAY"):
        out = subprocess.run(["pgrep", "-a", "Xwayland"], capture_output=True, text=True).stdout
        m = re.search(r"Xwayland (:\d+)", out)
        os.environ["DISPLAY"] = m.group(1) if m else ":0"
    if not os.environ.get("XAUTHORITY"):
        auth = sorted(glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"), key=os.path.getmtime, reverse=True)
        if auth:
            os.environ["XAUTHORITY"] = auth[0]


def player(configured: list[str] | None = None) -> list[str] | None:
    if configured:
        return list(configured)
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


_PLAYER = None


def play(path: str, configured: list[str] | None = None) -> None:
    global _PLAYER
    cmd = player(configured) if configured else (_PLAYER or player())
    _PLAYER = _PLAYER or cmd
    if cmd:
        try:
            subprocess.Popen(cmd + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
