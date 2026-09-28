"""macOS: Quartz keyboard events (CGEventPost), the frontmost app's name, the
marker read with a window capture, and afplay for beeps.

Keys need the Accessibility permission for the terminal or Python that runs
wow-voice (System Settings > Privacy & Security > Accessibility); the in-game
on/off button needs Screen Recording too. Key codes are the physical ANSI (US)
positions: on other layouts, letters and digits are where WoW expects them, but
a binding on a symbol key ("-", "=") may not be.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import re
import subprocess
import threading
import time

from ..keyboard import Unsupported

# Carbon's kVK_* virtual key codes (ANSI positions).
KEYCODES = {
    "A": 0x00, "S": 0x01, "D": 0x02, "F": 0x03, "H": 0x04, "G": 0x05, "Z": 0x06, "X": 0x07, "C": 0x08, "V": 0x09,
    "B": 0x0B, "Q": 0x0C, "W": 0x0D, "E": 0x0E, "R": 0x0F, "Y": 0x10, "T": 0x11, "1": 0x12, "2": 0x13, "3": 0x14,
    "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
    "O": 0x1F, "U": 0x20, "[": 0x21, "I": 0x22, "P": 0x23, "L": 0x25, "J": 0x26, "'": 0x27, "K": 0x28, ";": 0x29,
    "\\": 0x2A, ",": 0x2B, "/": 0x2C, "N": 0x2D, "M": 0x2E, ".": 0x2F, "`": 0x32,
    "ENTER": 0x24, "TAB": 0x30, "SPACE": 0x31, "BACKSPACE": 0x33, "ESCAPE": 0x35, "CAPSLOCK": 0x39,
    "NUMPADDECIMAL": 0x41, "NUMPADMULTIPLY": 0x43, "NUMPADPLUS": 0x45, "NUMLOCK": 0x47, "NUMPADDIVIDE": 0x4B,
    "NUMPADENTER": 0x4C, "NUMPADMINUS": 0x4E, "NUMPADEQUALS": 0x51,
    "NUMPAD0": 0x52, "NUMPAD1": 0x53, "NUMPAD2": 0x54, "NUMPAD3": 0x55, "NUMPAD4": 0x56, "NUMPAD5": 0x57,
    "NUMPAD6": 0x58, "NUMPAD7": 0x59, "NUMPAD8": 0x5B, "NUMPAD9": 0x5C,
    "F1": 0x7A, "F2": 0x78, "F3": 0x63, "F4": 0x76, "F5": 0x60, "F6": 0x61, "F7": 0x62, "F8": 0x64, "F9": 0x65,
    "F10": 0x6D, "F11": 0x67, "F12": 0x6F, "F13": 0x69, "F14": 0x6B, "F15": 0x71, "F16": 0x6A, "F17": 0x40,
    "F18": 0x4F, "F19": 0x50, "F20": 0x5A,
    "INSERT": 0x72, "HOME": 0x73, "PAGEUP": 0x74, "DELETE": 0x75, "END": 0x77, "PAGEDOWN": 0x79,
    "LEFT": 0x7B, "RIGHT": 0x7C, "DOWN": 0x7D, "UP": 0x7E,
}
# (key code, the flag it sets on the events while held)
MODIFIERS = {"SHIFT": (0x38, 0x00020000), "CTRL": (0x3B, 0x00040000), "ALT": (0x3A, 0x00080000)}
kCGHIDEventTap = 0


def _quartz():
    path = ctypes.util.find_library("ApplicationServices") or \
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    q = ctypes.cdll.LoadLibrary(path)
    q.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    q.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    q.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    q.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    q.CFRelease.argtypes = [ctypes.c_void_p]
    return q


def setup() -> None:
    pass


class Keymap:
    """WoW key names -> (key code, modifier flag or 0)."""

    def code_for(self, name: str) -> tuple[tuple[int, int], list]:
        key = name.upper() if len(name) == 1 else name
        if key not in KEYCODES:
            raise Unsupported(f"unknown key name {name!r}")
        return (KEYCODES[key], 0), []

    def modifier(self, mod: str) -> tuple[int, int]:
        return MODIFIERS[mod]


class Keyboard:
    def __init__(self, quartz=None):
        self.q = quartz or _quartz()
        self.down: set[tuple] = set()
        self.lock = threading.Lock()

    def _flags(self) -> int:
        f = 0
        for _, flag in self.down:
            f |= flag
        return f

    def _send(self, code: tuple[int, int], down: bool) -> None:
        ev = self.q.CGEventCreateKeyboardEvent(None, code[0], down)
        if not ev:
            return
        self.q.CGEventSetFlags(ev, self._flags())
        self.q.CGEventPost(kCGHIDEventTap, ev)
        self.q.CFRelease(ev)

    def _set(self, codes: list, value: int) -> None:
        with self.lock:
            order = codes if value else list(reversed(codes))
            for i, c in enumerate(order):
                # The event carries the modifiers held after it: Ctrl's own key-up
                # must not still say Ctrl is down.
                (self.down.add if value else self.down.discard)(c)
                self._send(c, bool(value))
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
                self.down.discard(c)
                self._send(c, False)

    def close(self) -> None:
        self.release_all()


def frontmost_app() -> str:
    try:
        from AppKit import NSWorkspace  # pyobjc-framework-Cocoa
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(app.localizedName()) if app else ""
    except ImportError:
        pass
    # Without pyobjc: Launch Services' own tool (no permission needed).
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=2).stdout.strip()
    out = subprocess.run(["lsappinfo", "info", "-only", "name", asn], capture_output=True, text=True, timeout=2).stdout
    m = re.search(r'"(?:LSDisplayName|name)"="(.*)"', out)
    return m.group(1) if m else ""


class Focus:
    """Is the frontmost app WoW?"""

    def __init__(self, window_name: str = "World of Warcraft", ttl: float = 0.4):
        self.pattern = re.compile(window_name)
        self.ttl = ttl
        self._at = 0.0
        self._ok = False

    def game_focused(self) -> bool:
        now = time.monotonic()
        if now - self._at > self.ttl:
            try:
                self._ok = bool(self.pattern.search(frontmost_app()))
            except (OSError, subprocess.SubprocessError):
                self._ok = False
            self._at = now
        return self._ok


class Switch:
    """The addon's marker, from a capture of the top-right corner of WoW's window
    (pyobjc-framework-Quartz and the Screen Recording permission)."""

    CORNER = 48  # points: enough to reach past a title bar

    def __init__(self, window_name: str = "World of Warcraft"):
        try:
            import Quartz  # noqa: F401
        except ImportError as e:
            raise OSError("the in-game switch needs pyobjc-framework-Quartz") from e
        self.name = window_name

    def read(self) -> bool | None:
        import Quartz
        from ..screen import classify
        info = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
        win = next((w for w in info if w.get("kCGWindowOwnerName") == self.name and w.get("kCGWindowLayer") == 0), None)
        if not win:
            return None
        b = win["kCGWindowBounds"]
        c = self.CORNER
        rect = Quartz.CGRectMake(b["X"] + b["Width"] - c, b["Y"], c, c)
        img = Quartz.CGWindowListCreateImage(rect, Quartz.kCGWindowListOptionIncludingWindow, win["kCGWindowNumber"],
                                             Quartz.kCGWindowImageBoundsIgnoreFraming)
        if not img:
            return None
        w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
        stride = Quartz.CGImageGetBytesPerRow(img)
        data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
        buf = bytes(data)
        found = None
        # Look for the marker in the corner (below a title bar, if the window has one).
        for y in range(0, h, 2):
            for x in range(w - 1, max(-1, w - 24), -2):
                o = y * stride + x * 4
                bgra = buf[o:o + 4]
                if len(bgra) < 4:
                    continue
                state = classify((bgra[2], bgra[1], bgra[0]))
                if state is not None:
                    found = state
                    break
            if found is not None:
                break
        return found


def play(path: str, configured=None) -> None:
    try:
        subprocess.Popen(list(configured or ["afplay"]) + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
