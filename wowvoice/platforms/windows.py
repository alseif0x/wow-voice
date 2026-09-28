"""Windows: SendInput with scan codes (what games read), the keyboard layout in use
through VkKeyScanW (a Spanish "=" is Shift+0, "@" AltGr+2), the foreground
window's title, and the marker's pixel read off the screen.

Only ctypes and the standard library: nothing to install besides Vosk and
sounddevice (the microphone).
"""

from __future__ import annotations

import ctypes
import re
import threading
import time

from ..keyboard import Unsupported

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0008
MAPVK_VK_TO_VSC = 0

# WoW key names -> virtual-key codes.
VK = {
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "ESCAPE": 0x1B, "BACKSPACE": 0x08, "NUMLOCK": 0x90,
    "CAPSLOCK": 0x14, "SCROLLLOCK": 0x91, "PRINTSCREEN": 0x2C, "PAUSE": 0x13, "INSERT": 0x2D, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22, "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25,
    "RIGHT": 0x27, "NUMPADMULTIPLY": 0x6A, "NUMPADPLUS": 0x6B, "NUMPADMINUS": 0x6D, "NUMPADDECIMAL": 0x6E,
    "NUMPADDIVIDE": 0x6F, "NUMPADENTER": 0x0D,
}
for _i in range(10):
    VK[f"NUMPAD{_i}"] = 0x60 + _i
for _i in range(1, 25):
    VK[f"F{_i}"] = 0x6F + _i
# Keys whose scan code carries the E0 prefix.
EXTENDED = {"INSERT", "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN", "UP", "DOWN", "LEFT", "RIGHT",
            "NUMPADDIVIDE", "NUMPADENTER", "NUMLOCK", "PRINTSCREEN"}
# (vk, scan code, extended)
MODIFIERS = {"SHIFT": (0xA0, 0x2A, False), "CTRL": (0xA2, 0x1D, False), "ALT": (0xA4, 0x38, False)}
ALTGR = (0xA5, 0x38, True)  # right Alt; Windows reads AltGr as Ctrl + right Alt


# Windows' own sizes (DWORD and LONG are 32 bits there), whatever this Python's C long is.
DWORD, LONG, WORD, ULONG_PTR = ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint16, ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):  # the union's largest member: INPUT must be its size
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD), ("dwFlags", DWORD), ("time", DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", DWORD), ("u", _INPUTUNION)]


def _user32():
    return ctypes.WinDLL("user32", use_last_error=True)


def setup() -> None:
    # Screen coordinates in real pixels (the marker is read by position).
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class Keymap:
    """WoW key names -> (vk, scan code, extended) through the keyboard layout in use."""

    def __init__(self, user32=None):
        self.u = user32 or _user32()

    def _key(self, vk: int, extended: bool = False) -> tuple[int, int, bool]:
        scan = self.u.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        if not scan:
            raise Unsupported(f"no scan code for virtual key {vk:#x}")
        return (vk, scan, extended)

    def code_for(self, name: str) -> tuple[tuple, list[tuple]]:
        if name in VK:
            return self._key(VK[name], name in EXTENDED), []
        if len(name) != 1:
            raise Unsupported(f"unknown key name {name!r}")
        r = self.u.VkKeyScanW(ord(name.lower()))
        if r == -1 or r == 0xFFFF:
            raise Unsupported(f"no key for {name!r} in this keyboard layout")
        vk, state = r & 0xFF, (r >> 8) & 0xFF
        extras = []
        if state & 0x06 == 0x06:        # Ctrl+Alt = AltGr
            extras += [MODIFIERS["CTRL"], ALTGR]
        elif state & 0x01:
            extras.append(MODIFIERS["SHIFT"])
        return self._key(vk), extras

    def modifier(self, mod: str) -> tuple[int, int, bool]:
        return MODIFIERS[mod]


class Keyboard:
    """SendInput, one key at a time (modifiers first, a moment between keys)."""

    def __init__(self, user32=None):
        self.u = user32 or _user32()
        self.down: set[tuple] = set()
        self.lock = threading.Lock()

    def _send(self, code: tuple, up: bool) -> None:
        vk, scan, extended = code
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0) | (KEYEVENTF_KEYUP if up else 0)
        inp = INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)))
        self.u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _set(self, codes: list, value: int) -> None:
        with self.lock:
            order = codes if value else list(reversed(codes))
            for i, c in enumerate(order):
                self._send(c, up=not value)
                (self.down.add if value else self.down.discard)(c)
                if i + 1 < len(order):
                    time.sleep(0.02)

    def press(self, codes: list, tap: float = 0.06) -> None:
        self._set(codes, 1)
        time.sleep(tap)
        self._set(codes, 0)

    def hold(self, codes: list, seconds: float, stop: threading.Event) -> None:
        self._set(codes, 1)
        try:
            stop.wait(seconds)
        finally:
            self._set(codes, 0)

    def release_all(self) -> None:
        with self.lock:
            for c in list(self.down):
                self._send(c, up=True)
            self.down.clear()

    def close(self) -> None:
        self.release_all()


def _title(u, hwnd) -> str:
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


class Focus:
    """Is the foreground window WoW's (by title)?"""

    def __init__(self, window_name: str = "World of Warcraft", ttl: float = 0.4, user32=None):
        self.pattern = re.compile(window_name)
        self.u = user32 or _user32()
        self.ttl = ttl
        self._at = 0.0
        self._ok = False

    def game_focused(self) -> bool:
        now = time.monotonic()
        if now - self._at > self.ttl:
            try:
                self._ok = bool(self.pattern.search(_title(self.u, self.u.GetForegroundWindow())))
            except OSError:
                self._ok = False
            self._at = now
        return self._ok


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class Switch:
    """The addon's marker, read from the screen at the game window's top-right corner
    (the game must be visible: windowed or windowed fullscreen, WoW's default)."""

    def __init__(self, window_name: str = "World of Warcraft"):
        self.u = _user32()
        self.gdi = ctypes.WinDLL("gdi32")
        self.name = window_name

    def read(self) -> bool | None:
        from ..screen import classify
        hwnd = self.u.FindWindowW(None, self.name)
        if not hwnd or self.u.IsIconic(hwnd):
            return None
        rc = RECT()
        if not self.u.GetClientRect(hwnd, ctypes.byref(rc)) or rc.right < 16 or rc.bottom < 16:
            return None
        pt = POINT(rc.right - 4, 4)  # the marker's middle, 4 px in from the corner
        self.u.ClientToScreen(hwnd, ctypes.byref(pt))
        hdc = self.u.GetDC(0)
        try:
            c = self.gdi.GetPixel(hdc, pt.x, pt.y)
        finally:
            self.u.ReleaseDC(0, hdc)
        if c == 0xFFFFFFFF:  # CLR_INVALID
            return None
        return classify((c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF))


def play(path: str, configured=None) -> None:
    import winsound
    try:
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except RuntimeError:
        pass
