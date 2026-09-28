"""A virtual keyboard: the keys wow-voice presses, as if typed on a real one.

This is the Linux one (Windows and macOS: platforms/windows.py, platforms/macos.py,
same interface). It creates a keyboard device through /dev/uinput. The desktop sees it as one
more keyboard and sends its keys to the focused window, so it does exactly what
your hands would. Key names are WoW's binding names ("W", "SPACE", "SHIFT-1",
"NUMLOCK", "-"); they are turned into keycodes through the X keyboard map of the
session, so a Spanish (or any) layout is respected: WoW's "-" is wherever your
layout has "-".
"""

from __future__ import annotations

import ctypes
import ctypes.util
import fcntl
import os
import struct
import threading
import time

# linux/uinput.h, linux/input-event-codes.h
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EV_SYN, EV_KEY, SYN_REPORT = 0, 1, 0
KEY_LEFTSHIFT, KEY_LEFTCTRL, KEY_LEFTALT, KEY_RIGHTALT = 42, 29, 56, 100

# WoW binding key names -> X keysym names. Single printable characters are
# handled apart (their keysym is the character itself).
NAMED = {
    "SPACE": "space", "TAB": "Tab", "ENTER": "Return", "ESCAPE": "Escape", "BACKSPACE": "BackSpace",
    "NUMLOCK": "Num_Lock", "CAPSLOCK": "Caps_Lock", "SCROLLLOCK": "Scroll_Lock", "PRINTSCREEN": "Print",
    "PAUSE": "Pause", "INSERT": "Insert", "DELETE": "Delete", "HOME": "Home", "END": "End",
    "PAGEUP": "Prior", "PAGEDOWN": "Next", "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "NUMPADPLUS": "KP_Add", "NUMPADMINUS": "KP_Subtract", "NUMPADMULTIPLY": "KP_Multiply",
    "NUMPADDIVIDE": "KP_Divide", "NUMPADDECIMAL": "KP_Decimal", "NUMPADENTER": "KP_Enter", "NUMPADEQUALS": "KP_Equal",
}
for _i in range(10):
    NAMED[f"NUMPAD{_i}"] = f"KP_{_i}"
for _i in range(1, 25):
    NAMED[f"F{_i}"] = f"F{_i}"

MODIFIERS = {"SHIFT": KEY_LEFTSHIFT, "CTRL": KEY_LEFTCTRL, "ALT": KEY_LEFTALT}


class Unsupported(ValueError):
    """A binding the keyboard can't press (a mouse button, a gamepad button)."""


def split_binding(key: str) -> tuple[list[str], str]:
    """"ALT-CTRL-SHIFT-F" -> (["ALT", "CTRL", "SHIFT"], "F"). A lone "-" is the key itself."""
    parts = key.split("-")
    mods = []
    while len(parts) > 1 and parts[0] in MODIFIERS:
        mods.append(parts.pop(0))
    rest = "-".join(parts)
    return mods, rest


def keysym_for(name: str) -> int | str:
    """The X keysym (a number) for a WoW key name, or its keysym name for XStringToKeysym."""
    if name.startswith(("BUTTON", "MOUSEWHEEL", "PAD")):
        raise Unsupported(f"{name} is a mouse or gamepad button")
    if name in NAMED:
        return NAMED[name]
    if len(name) == 1:
        ch = name.lower()
        code = ord(ch)
        return code if code < 0x100 else 0x1000000 + code
    raise Unsupported(f"unknown key name {name!r}")


class XKeymap:
    """Keysym -> (evdev keycode, extra modifier) through the session's X keyboard map."""

    def __init__(self, display: str | None = None):
        path = ctypes.util.find_library("X11")
        if not path:
            raise OSError("libX11 not found")
        self.x = ctypes.CDLL(path)
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XStringToKeysym.restype = ctypes.c_ulong
        self.x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x.XkbKeycodeToKeysym.restype = ctypes.c_ulong
        self.x.XkbKeycodeToKeysym.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_int, ctypes.c_int]
        self.dpy = self.x.XOpenDisplay(display.encode() if display else None)
        if not self.dpy:
            raise OSError(f"cannot open X display {display or os.environ.get('DISPLAY')}")

    def code_for(self, name: str) -> tuple[int, list[int]]:
        """A WoW key name -> (keycode, extra modifier keycodes this layout needs for it)."""
        code, extra = self.lookup(keysym_for(name))
        return code, [extra] if extra is not None else []

    def modifier(self, mod: str) -> int:
        return MODIFIERS[mod]

    def lookup(self, keysym: int | str) -> tuple[int, int | None]:
        sym = keysym if isinstance(keysym, int) else self.x.XStringToKeysym(keysym.encode())
        if not sym:
            raise Unsupported(f"no keysym {keysym!r}")
        kc = self.x.XKeysymToKeycode(self.dpy, sym)
        if not kc:
            raise Unsupported(f"no key for keysym {keysym!r} in this keyboard layout")
        # Level 0 plain, 1 Shift, 2 AltGr (Spanish "=" is Shift+0, "@" AltGr+2).
        for level, extra in ((0, None), (1, KEY_LEFTSHIFT), (2, KEY_RIGHTALT)):
            if self.x.XkbKeycodeToKeysym(self.dpy, kc, 0, level) == sym:
                return kc - 8, extra
        return kc - 8, None


def resolve(key: str, keymap) -> list:
    """A WoW binding -> the key codes to hold together (modifiers first, key last).
    `keymap` is this system's (XKeymap here; platforms/windows.py, platforms/macos.py)."""
    mods, name = split_binding(key)
    if name.startswith(("BUTTON", "MOUSEWHEEL", "PAD")):
        raise Unsupported(f"{name} is a mouse or gamepad button")
    code, extras = keymap.code_for(name)
    codes = [keymap.modifier(m) for m in mods]
    for extra in extras:
        if extra not in codes:
            codes.append(extra)
    codes.append(code)
    return codes


class Keyboard:
    """The uinput device. press() taps a chord; hold() keeps it down, interruptible."""

    def __init__(self, name: str = "wow-voice keyboard"):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_SYN)
        for code in range(1, 249):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        # struct uinput_user_dev: name[80], input_id (bustype, vendor, product, version), ff_effects_max, abs[4][64]
        dev = struct.pack("80sHHHHi", name.encode()[:79], 0x03, 0x1209, 0x5756, 1, 0) + b"\0" * (4 * 64 * 4)
        os.write(self.fd, dev)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        self.down: set[int] = set()
        self.lock = threading.Lock()
        time.sleep(0.5)  # let the desktop pick the new keyboard up

    def _emit(self, etype: int, code: int, value: int) -> None:
        os.write(self.fd, struct.pack("llHHi", 0, 0, etype, code, value))

    def _set(self, codes: list[int], value: int) -> None:
        # One event report per key, with a moment between them: when a modifier
        # and its key arrive in the same report, the desktop can apply the key
        # before the modifier (Ctrl+Tab would land as Tab).
        with self.lock:
            order = codes if value else list(reversed(codes))
            for i, c in enumerate(order):
                self._emit(EV_KEY, c, value)
                self._emit(EV_SYN, SYN_REPORT, 0)
                (self.down.add if value else self.down.discard)(c)
                if i + 1 < len(order):
                    time.sleep(0.02)

    def press(self, codes: list[int], tap: float = 0.06) -> None:
        self._set(codes, 1)
        time.sleep(tap)
        self._set(codes, 0)

    def hold(self, codes: list[int], seconds: float, stop: threading.Event) -> None:
        self._set(codes, 1)
        try:
            stop.wait(seconds)
        finally:
            self._set(codes, 0)

    def release_all(self) -> None:
        with self.lock:
            for c in list(self.down):
                self._emit(EV_KEY, c, 0)
            self.down.clear()
            self._emit(EV_SYN, SYN_REPORT, 0)

    def close(self) -> None:
        try:
            self.release_all()
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


class DryKeyboard:
    """Prints what would be pressed (--dry-run, tests)."""

    def __init__(self, log=print):
        self.log = log
        self.events: list[tuple] = []

    def press(self, codes, tap=0.04):
        self.events.append(("press", tuple(codes)))
        self.log(f"[dry] press {codes}")

    def hold(self, codes, seconds, stop):
        self.events.append(("hold", tuple(codes), seconds))
        self.log(f"[dry] hold {codes} {seconds:.1f} s")
        stop.wait(min(seconds, 0.01))

    def release_all(self):
        self.events.append(("release",))

    def close(self):
        pass
