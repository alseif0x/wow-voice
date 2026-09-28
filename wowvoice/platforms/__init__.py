"""What depends on the operating system, behind one interface.

Each module (linux.py, windows.py, macos.py) gives:

  setup()            anything to do first (Linux: find the X display WoW is on)
  Keymap()           WoW key names -> this system's key codes (code_for, modifier)
  Keyboard()         press / hold / release_all / close, with those codes
  Focus(pattern)     game_focused(): is the active window WoW's?
  Switch(title)      read(): the WoW Voice addon's on/off marker (True / False / None);
                     raises OSError where it can't be read
  play(path)         play a short WAV file, without waiting

`current()` is the module for the system this runs on.
"""

from __future__ import annotations

import importlib
import sys


def name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def current():
    return importlib.import_module(f".{name()}", __name__)
