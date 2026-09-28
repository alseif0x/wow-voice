import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wowvoz import commands as C  # noqa: E402
from wowvoz.actions import Actions  # noqa: E402
from wowvoz.game import KeyMap, default_keymap, load_keymap, parse_lua  # noqa: E402
from wowvoz.keyboard import DryKeyboard, Unsupported, keysym_for, split_binding  # noqa: E402
from wowvoz.listen import FRAME_BYTES, Phrases  # noqa: E402

BUTTONS = [
    {"slot": 1, "command": "ACTIONBUTTON1", "keys": ["1"], "kind": "spell", "id": 133, "name": "Bola de Fuego"},
    {"slot": 2, "command": "ACTIONBUTTON2", "keys": ["2"], "kind": "item", "id": 6948, "name": "Piedra de hogar"},
    {"slot": 61, "command": "MULTIACTIONBAR1BUTTON1", "keys": ["SHIFT-1"], "kind": "spell", "id": 5, "name": "Golpe siniestro (Rango 2)"},
]


class Parse(unittest.TestCase):
    def test_exact_orders(self):
        cases = {
            "salta": ("jump", 1), "salta dos veces": ("jump", 2), "Brinca tres veces": ("jump", 3),
            "adelante": ("forward", 1), "atrás": ("back", 1), "a la izquierda": ("strafe_left", 1),
            "gira a la derecha": ("turn_right", 1), "media vuelta": ("turn_around", 1),
            "corre": ("autorun", 1), "caminar automático": ("autorun", 1), "para": ("stop", 1),
            "siguiente objetivo": ("target", 1), "voz pausa": ("pause", 1), "voz activa": ("resume", 1),
            "vale, salta": ("jump", 1),
        }
        for text, (kind, count) in cases.items():
            o = C.parse(text, BUTTONS)
            self.assertIsNotNone(o, text)
            self.assertEqual((o.kind, o.count), (kind, count), text)

    def test_seconds_and_buttons(self):
        self.assertEqual(C.parse("adelante tres", BUTTONS).seconds, 3.0)
        o = C.parse("lanza bola de fuego", BUTTONS)
        self.assertEqual((o.kind, o.button["id"]), ("button", 133))
        self.assertEqual(C.parse("Piedra de hogar", BUTTONS).button["id"], 6948)
        self.assertEqual(C.parse("usa golpe siniestro", BUTTONS).button["id"], 5, "the rank in brackets is not said")
        self.assertEqual(C.parse("botón tres", BUTTONS).button, {"number": 3})

    def test_sentences_are_not_orders(self):
        for text in ["para qué sirve esto", "no salta nada", "adelante con la misión de mañana", "", "botón trece"]:
            self.assertIsNone(C.parse(text, BUTTONS), text)

    def test_every_grammar_phrase_parses(self):
        for p in C.phrases(BUTTONS):
            self.assertIsNotNone(C.parse(p, BUTTONS), p)


class Jev(unittest.TestCase):
    def test_request_offers_orders_buttons_and_none(self):
        body, opts = C.jev_request("tírale una bola de fuego a ese lobo", BUTTONS)
        q = body["questions"]["order"]
        self.assertEqual(q["type"], "choice")
        self.assertEqual(body["state"], {"utterance": "tírale una bola de fuego a ese lobo"})
        self.assertIn("none", q["criteria"])
        self.assertIn("jump", q["criteria"])
        self.assertIn('Cast the spell "Bola de Fuego"', q["criteria"]["button_0"])

    def test_answers(self):
        _, opts = C.jev_request("x", BUTTONS)
        ans = lambda choice, conf: {"answers": {"order": {"type": "choice", "choice": choice, "confidence": conf}}}
        o = C.order_from_jev(ans("jump", 0.99), opts, "salta dos veces seguidas", 0.8)
        self.assertEqual((o.kind, o.count), ("jump", 2), "the count comes from the words, not JEV")
        self.assertEqual(C.order_from_jev(ans("button_0", 0.9), opts, "tírale una bola", 0.8).button["id"], 133)
        self.assertIsNone(C.order_from_jev(ans("jump", 0.5), opts, "x", 0.8), "not sure enough")
        self.assertIsNone(C.order_from_jev(ans("none", 1.0), opts, "x", 0.8))
        self.assertIsNone(C.order_from_jev(ans("run_lua", 1.0), opts, "x", 0.8), "a choice we did not offer")
        self.assertIsNone(C.order_from_jev({}, opts, "x", 0.8))


class FakeFocus:
    def __init__(self, ok=True):
        self.ok = ok

    def game_focused(self):
        return self.ok


def run_orders(orders, focus=True, cfg=None, keymap=None):
    kb = DryKeyboard(log=lambda *_: None)
    km = keymap or KeyMap(default_keymap().bindings, BUTTONS, "test")
    acts = Actions(kb, km, None, FakeFocus(focus), cfg or {"jumpInterval": 0.01, "holdSeconds": 0.01}, log=lambda *_: None)
    for o in orders:
        acts.submit(o)
    time.sleep(0.3)
    return kb.events, acts


class Doing(unittest.TestCase):
    def test_jumps_holds_and_buttons(self):
        ev, _ = run_orders([C.Order("jump", count=2), C.Order("forward"), C.parse("lanza bola de fuego", BUTTONS)])
        self.assertEqual([e[0] for e in ev], ["press", "press", "hold", "press"])

    def test_counts_and_holds_are_capped(self):
        ev, _ = run_orders([C.Order("jump", count=40), C.Order("forward", seconds=60)], cfg={"jumpInterval": 0.0, "maxHoldSeconds": 0.02})
        self.assertEqual(sum(1 for e in ev if e[0] == "press"), 5)
        self.assertEqual([e[2] for e in ev if e[0] == "hold"], [0.1])

    def test_nothing_without_focus(self):
        ev, _ = run_orders([C.Order("jump"), C.Order("forward")], focus=False)
        self.assertEqual(ev, [])

    def test_pause_resume_and_stop(self):
        ev, acts = run_orders([C.Order("pause"), C.Order("jump")])
        self.assertTrue(acts.paused)
        self.assertEqual([e for e in ev if e[0] == "press"], [])
        acts.submit(C.Order("resume"))
        acts.submit(C.Order("autorun"))
        time.sleep(0.1)
        self.assertTrue(acts.autorun)
        acts.submit(C.Order("stop"))
        time.sleep(0.1)
        self.assertFalse(acts.autorun, "stop taps back to end autorun")
        self.assertIn(("release",), ev)

    def test_stop_cuts_a_hold(self):
        kb = DryKeyboard(log=lambda *_: None)
        started = []

        def hold(codes, seconds, stop):
            started.append(time.monotonic())
            stop.wait(seconds)
            started.append(time.monotonic())
        kb.hold = hold
        acts = Actions(kb, KeyMap(default_keymap().bindings, [], "t"), None, FakeFocus(), {"maxHoldSeconds": 5}, log=lambda *_: None)
        acts.submit(C.Order("forward", seconds=5))
        time.sleep(0.1)
        acts.submit(C.Order("stop"))
        time.sleep(0.1)
        self.assertLess(started[1] - started[0], 1.0)


class Keys(unittest.TestCase):
    def test_binding_names(self):
        self.assertEqual(split_binding("ALT-CTRL-SHIFT-F"), (["ALT", "CTRL", "SHIFT"], "F"))
        self.assertEqual(split_binding("-"), ([], "-"))
        self.assertEqual(split_binding("SHIFT--"), (["SHIFT"], "-"))
        self.assertEqual(keysym_for("SPACE"), "space")
        self.assertEqual(keysym_for("W"), ord("w"))
        self.assertEqual(keysym_for("º"), 0xBA)
        with self.assertRaises(Unsupported):
            keysym_for("BUTTON3")
        with self.assertRaises(Unsupported):
            keysym_for("PAD1")


class SavedVariables(unittest.TestCase):
    SV = '''
WoWVozDB = {
["current"] = {
["character"] = "Luke-Classic Beta PvP 2",
["time"] = 1790610000,
["bindings"] = {
["JUMP"] = {
"SPACE", -- [1]
"MOUSEWHEELDOWN", -- [2]
},
["MOVEFORWARD"] = {
"UP", -- [1]
},
},
["buttons"] = {
{
["slot"] = 1,
["command"] = "ACTIONBUTTON1",
["keys"] = {
"1", -- [1]
},
["kind"] = "spell",
["id"] = 1752,
["name"] = "Golpe \\"siniestro\\"",
}, -- [1]
},
},
}
'''

    def test_reads_the_addon_data(self):
        d = parse_lua(self.SV)["WoWVozDB"]["current"]
        self.assertEqual(d["bindings"]["JUMP"][2], "MOUSEWHEELDOWN")
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "WoWVoz.lua")
            open(p, "w").write(self.SV)
            km = load_keymap(os.path.join(tmp, "*.lua"))
            self.assertEqual(km.character, "Luke-Classic Beta PvP 2")
            self.assertEqual(km.keys("MOVEFORWARD"), ["UP"])
            self.assertEqual(km.keys("MOVEBACKWARD"), ["S"], "defaults fill the rest")
            self.assertEqual(km.named_buttons()[0]["name"], 'Golpe "siniestro"')
            self.assertEqual(load_keymap(os.path.join(tmp, "none*.lua")).source.split(" ")[0], "WoW")


class Phrasing(unittest.TestCase):
    def test_a_phrase_is_voice_then_silence(self):
        import math
        import struct
        loud = struct.pack("<480h", *[int(4000 * math.sin(i / 3)) for i in range(480)])
        quiet = b"\0" * FRAME_BYTES
        ph = Phrases(threshold=700, silence_ms=360, max_ms=5000)
        out = [ph.feed(f) for f in [quiet] * 5 + [loud] * 10 + [quiet] * 15]
        got = [o for o in out if o]
        self.assertEqual(len(got), 1)
        self.assertGreaterEqual(len(got[0]), 10 * FRAME_BYTES, "the voice and a little before it")
        self.assertEqual([o for o in (ph.feed(quiet) for _ in range(50)) if o], [], "silence is not a phrase")


if __name__ == "__main__":
    unittest.main()
