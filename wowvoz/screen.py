"""The WoW Voz addon's on/off switch, read off the game window.

The addon paints an 8x8 pixel square in the top-right corner: magenta when voice
orders are on, cyan when off. This reads a 16x16 corner of the game window
itself (under Xwayland the root window holds no picture of other clients, so
WoW AI's capture reads the window too) and says which it is, or None.
"""

from __future__ import annotations

import ctypes
import ctypes.util

Window = ctypes.c_ulong
Atom = ctypes.c_ulong


class XImage(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int), ("height", ctypes.c_int), ("xoffset", ctypes.c_int),
        ("format", ctypes.c_int), ("data", ctypes.c_void_p), ("byte_order", ctypes.c_int),
        ("bitmap_unit", ctypes.c_int), ("bitmap_bit_order", ctypes.c_int), ("bitmap_pad", ctypes.c_int),
        ("depth", ctypes.c_int), ("bytes_per_line", ctypes.c_int), ("bits_per_pixel", ctypes.c_int),
        ("red_mask", ctypes.c_ulong), ("green_mask", ctypes.c_ulong), ("blue_mask", ctypes.c_ulong),
        ("obdata", ctypes.c_void_p),
        ("create_image", ctypes.c_void_p), ("destroy_image", ctypes.c_void_p),
        ("get_pixel", ctypes.c_void_p), ("put_pixel", ctypes.c_void_p),
        ("sub_image", ctypes.c_void_p), ("add_pixel", ctypes.c_void_p),
    ]


class XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
        ("root", Window), ("class", ctypes.c_int), ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long), ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long), ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


def classify(rgb) -> bool | None:
    """Magenta = on, cyan = off, anything else = not the marker."""
    r, g, b = rgb
    if b < 160:
        return None
    if r > 180 and g < 90:
        return True
    if g > 180 and r < 90:
        return False
    return None


class Switch:
    CORNER = 16

    def __init__(self, window_name: str = "World of Warcraft"):
        self.name = window_name.encode()
        self.x = ctypes.CDLL(ctypes.util.find_library("X11"))
        X = self.x
        X.XOpenDisplay.restype = ctypes.c_void_p
        X.XOpenDisplay.argtypes = [ctypes.c_char_p]
        X.XDefaultRootWindow.restype = Window
        X.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        X.XInternAtom.restype = Atom
        X.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        X.XGetWindowProperty.argtypes = [ctypes.c_void_p, Window, Atom, ctypes.c_long, ctypes.c_long, ctypes.c_int, Atom,
                                         ctypes.POINTER(Atom), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                         ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
        X.XFetchName.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(ctypes.c_void_p)]
        X.XGetWindowAttributes.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(XWindowAttributes)]
        X.XGetImage.restype = ctypes.POINTER(XImage)
        X.XGetImage.argtypes = [ctypes.c_void_p, Window, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
        X.XFree.argtypes = [ctypes.c_void_p]
        X.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._errors = [0]
        handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self._handler = handler(lambda d, e: self._count())
        X.XSetErrorHandler(self._handler)
        self.dpy = X.XOpenDisplay(None)
        if not self.dpy:
            raise OSError("cannot open the X display")
        self.root = X.XDefaultRootWindow(self.dpy)
        self.A_LIST = X.XInternAtom(self.dpy, b"_NET_CLIENT_LIST", 0)
        self.A_WINDOW = X.XInternAtom(self.dpy, b"WINDOW", 0)
        self.win = None

    def _count(self):
        self._errors[0] += 1
        return 0

    def _find(self):
        X = self.x
        typ, fmt = Atom(), ctypes.c_int()
        n, rest, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        if X.XGetWindowProperty(self.dpy, self.root, self.A_LIST, 0, 4096, 0, self.A_WINDOW, ctypes.byref(typ),
                                ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(rest), ctypes.byref(data)) != 0 or not data:
            return None
        arr = ctypes.cast(data, ctypes.POINTER(Window))
        wins = [arr[i] for i in range(n.value)]
        X.XFree(data)
        for w in wins:
            name = ctypes.c_void_p()
            if X.XFetchName(self.dpy, w, ctypes.byref(name)) and name.value:
                hit = ctypes.string_at(name.value) == self.name
                X.XFree(name.value)
                if hit:
                    return w
        return None

    def read(self) -> bool | None:
        """True (on), False (off), or None (no game window, or no marker on it)."""
        X = self.x
        if self.win is None:
            self.win = self._find()
            if self.win is None:
                return None
        a = XWindowAttributes()
        before = self._errors[0]
        if not X.XGetWindowAttributes(self.dpy, self.win, ctypes.byref(a)) or self._errors[0] != before or a.map_state != 2:
            self.win = None
            return None
        c = self.CORNER
        if a.width < c or a.height < c:
            return None
        img = X.XGetImage(self.dpy, self.win, a.width - c, 0, c, c, 0xFFFFFFFF, 2)
        X.XSync(self.dpy, 0)
        if not img or self._errors[0] != before:
            self.win = None
            return None
        im = img.contents
        try:
            if im.bits_per_pixel not in (24, 32):
                return None
            buf = ctypes.string_at(im.data, im.bytes_per_line * im.height)
            bpp, stride = im.bits_per_pixel // 8, im.bytes_per_line
            order = "little" if im.byte_order == 0 else "big"
            chans = []
            for m in (im.red_mask, im.green_mask, im.blue_mask):
                s = 0
                while m and not (m >> s) & 1:
                    s += 1
                chans.append((s, (m >> s) if m else 1))
            # The marker's middle: 4 px in from the top-right corner.
            x, y = c - 4, 4
            o = y * stride + x * bpp
            v = int.from_bytes(buf[o:o + bpp], order)
            rgb = tuple(((v >> s) & mm) * 255 // mm for s, mm in chans)
        finally:
            destroy = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(XImage))(im.destroy_image)
            destroy(img)
        return classify(rgb)
