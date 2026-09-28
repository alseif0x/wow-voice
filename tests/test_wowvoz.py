import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wowvoz import commands as C  # noqa: E402
from wowvoz import lang  # noqa: E402
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
            "adelante": ("forward", 1), "atrás": ("back", 1), "paso a la izquierda": ("strafe_left", 1),
            "gira a la derecha": ("turn_right", 1), "media vuelta": ("turn_around", 1),
            "corre": ("run", 1), "correr": ("run", 1), "camina rápido": ("run", 1), "andar": ("walk", 1), "camina": ("walk", 1), "caminar": ("walk", 1), "avanza": ("forward", 1),
            "caminar automático": ("autorun", 1), "automático": ("autorun", 1), "sigue recto": ("autorun", 1), "todo recto": ("autorun", 1), "para": ("stop", 1),
            "siguiente objetivo": ("target", 1), "voz pausa": ("pause", 1), "voz activa": ("resume", 1),
            "camina lento": ("walk", 1), "a correr": ("run", 1), "más despacio": ("slower", 1), "más rápido": ("faster", 1),
            "salta a la izquierda": ("jump_left", 1), "salta adelante": ("jump_forward", 1), "camina a la izquierda": ("strafe_left", 1),
            "corre derecha": ("strafe_right", 1), "recoger": ("interact", 1), "saquea": ("interact", 1),
            "pon el foco": ("focus", 1), "vuelve al foco": ("target_focus", 1), "quita el foco": ("clear_focus", 1), "focus aliado": ("focus_friend", 1), "asiste": ("assist", 1),
            "vale, salta": ("jump", 1),
        }
        for text, (kind, count) in cases.items():
            o = C.parse(text, BUTTONS)
            self.assertIsNotNone(o, text)
            self.assertEqual((o.kind, o.count), (kind, count), text)

    def test_turns_are_small_unless_said_otherwise(self):
        cases = {"izquierda": ("turn_left", 45), "a la derecha": ("turn_right", 45), "un poco a la izquierda": ("turn_left", 20),
                 "gira a la derecha": ("turn_right", 90), "mucho a la izquierda": ("turn_left", 135),
                 "media vuelta": ("turn_around", 180), "gira totalmente": ("turn_around", 180), "Gira 180 grados.": ("turn_around", 180),
                 "180 grados": ("turn_around", 180), "gira a la derecha 30 grados": ("turn_right", 30),
                 "gira a la derecha treinta grados": ("turn_right", 30),
                 "gira a la izquierda cuarenta y cinco grados": ("turn_left", 45)}
        for text, (kind, deg) in cases.items():
            o = C.parse(text, BUTTONS)
            self.assertEqual((o.kind, o.degrees), (kind, deg), text)
        self.assertEqual(C.turn_degrees(C.norm("gírate un poquito a la derecha").split()), 20)
        self.assertEqual(C.turn_degrees(C.norm("date la vuelta entera").split()), 180)
        self.assertEqual(C.turn_degrees(C.norm("mira a la izquierda").split()), 45)

    def test_seconds_and_buttons(self):
        self.assertEqual(C.parse("adelante tres", BUTTONS).seconds, 3.0)
        o = C.parse("lanza bola de fuego", BUTTONS)
        self.assertEqual((o.kind, o.button["id"]), ("button", 133))
        self.assertEqual(C.parse("Piedra de hogar", BUTTONS).button["id"], 6948)
        self.assertEqual(C.parse("usa golpe siniestro", BUTTONS).button["id"], 5, "the rank in brackets is not said")
        self.assertEqual(C.parse("botón tres", BUTTONS).button, {"number": 3})
        self.assertEqual(C.parse("golpe", BUTTONS).button["id"], 5, "a unique first word is a short name")
        self.assertEqual(C.parse("piedra", BUTTONS).button["id"], 6948)
        self.assertEqual(C.parse("cerrar", BUTTONS).kind, "close")
        self.assertEqual(C.parse("mira atrás", BUTTONS).kind, "turn_around")

    def test_sentences_are_not_orders(self):
        for text in ["para qué sirve esto", "no salta nada", "adelante con la misión de mañana", "", "botón trece"]:
            self.assertIsNone(C.parse(text, BUTTONS), text)

    def test_misheard_orders_are_close_ordinary_speech_is_not(self):
        for g, f in [("gira a la derecha", "gira de echa"), ("salta", "falta"), ("siguiente objetivo", "siguiente objeto")]:
            self.assertTrue(C.close_enough(g, f), (g, f))
        for g, f in [("salta", "hola"), ("para", "otra vez"), ("adelante", "vamos a la moneda"), ("izquierda", "que te quiero decir algo"), ("para", "vale"), ("recto", "proyecto")]:
            self.assertFalse(C.close_enough(g, f), (g, f))

    def test_buttons_by_sound(self):
        buttons = BUTTONS + [{"slot": 3, "command": "ACTIONBUTTON3", "keys": ["3"], "kind": "spell", "name": "Eviscerar"}]
        self.assertEqual(C.button_by_sound("es viscera", buttons)["name"], "Eviscerar")
        self.assertEqual(C.button_by_sound("lanza es viscerar", buttons)["name"], "Eviscerar")
        self.assertIsNone(C.button_by_sound("vamos a comer", buttons))
        self.assertIsNone(C.button_by_sound("hola", buttons))

    def test_every_grammar_phrase_parses(self):
        for p in C.phrases(BUTTONS):
            self.assertIsNotNone(C.parse(p, BUTTONS), p)


EN_BUTTONS = [
    {"slot": 1, "command": "ACTIONBUTTON1", "keys": ["1"], "kind": "spell", "id": 133, "name": "Fireball"},
    {"slot": 2, "command": "ACTIONBUTTON2", "keys": ["2"], "kind": "item", "id": 6948, "name": "Hearthstone"},
    {"slot": 3, "command": "ACTIONBUTTON3", "keys": ["3"], "kind": "spell", "id": 1752, "name": "Sinister Strike (Rank 2)"},
]


class English(unittest.TestCase):
    def setUp(self):
        C.set_language("en")

    def tearDown(self):
        C.set_language("es")

    def test_exact_orders(self):
        cases = {
            "jump": ("jump", 1), "jump twice": ("jump", 2), "jump three times": ("jump", 3), "hop": ("jump", 1),
            "forward": ("forward", 1), "move forward": ("forward", 1), "backpedal": ("back", 1), "strafe left": ("strafe_left", 1),
            "auto run": ("autorun", 1), "walk": ("walk", 1), "run": ("run", 1), "slow down": ("slower", 1), "speed up": ("faster", 1),
            "stop": ("stop", 1), "next target": ("target", 1), "tab target": ("target", 1), "focus": ("focus", 1),
            "clear focus": ("clear_focus", 1), "assist": ("assist", 1), "loot": ("interact", 1), "loot all": ("interact", 1),
            "pick up": ("interact", 1), "sit down": ("sit", 1), "open bags": ("bags", 1), "world map": ("map", 1),
            "voice off": ("pause", 1), "voice on": ("resume", 1), "jump to the left": ("jump_left", 1), "ok jump": ("jump", 1),
        }
        for text, (kind, count) in cases.items():
            o = C.parse(text, EN_BUTTONS)
            self.assertIsNotNone(o, text)
            self.assertEqual((o.kind, o.count), (kind, count), text)

    def test_turns(self):
        cases = {"left": ("turn_left", 45), "a little right": ("turn_right", 20), "turn left": ("turn_left", 90),
                 "hard right": ("turn_right", 135), "turn around": ("turn_around", 180), "one eighty": ("turn_around", 180),
                 "turn right 30 degrees": ("turn_right", 30), "turn left thirty degrees": ("turn_left", 30),
                 "turn right forty five degrees": ("turn_right", 45)}
        for text, (kind, deg) in cases.items():
            o = C.parse(text, EN_BUTTONS)
            self.assertEqual((o.kind, o.degrees), (kind, deg), text)
        self.assertEqual(C.turn_degrees(C.norm("turn a little bit to the right").split()), 20)
        self.assertEqual(C.turn_degrees(C.norm("spin all the way around").split()), 180)

    def test_buttons_seconds_and_combined(self):
        self.assertEqual(C.parse("cast fireball", EN_BUTTONS).button["id"], 133)
        self.assertEqual(C.parse("sinister strike", EN_BUTTONS).button["id"], 1752)
        self.assertEqual(C.parse("button three", EN_BUTTONS).button, {"number": 3})
        self.assertEqual(C.parse("forward three", EN_BUTTONS).seconds, 3.0)
        self.assertEqual(C.split_orders("jump and turn right, then forward"), ["jump", "turn right", "forward"])
        self.assertIsNone(C.parse("what is for dinner", EN_BUTTONS))

    def test_every_grammar_phrase_parses(self):
        for p in C.phrases(EN_BUTTONS):
            self.assertIsNotNone(C.parse(p, EN_BUTTONS), p)

    def test_ask_ai_needs_a_wake_word(self):
        from wowvoz.recognize import ask_ai_question
        self.assertEqual(ask_ai_question("hey ai what quest should i do"), "what quest should i do")
        self.assertEqual(ask_ai_question("ask the ai where is the vendor"), "where is the vendor")
        self.assertIsNone(ask_ai_question("i think we should go left"))

    def test_jev_criteria_show_english_examples(self):
        body, _ = C.jev_request("loot that thing", EN_BUTTONS)
        crit = body["questions"]["order"]["criteria"]
        self.assertIn('"loot"', crit["interact"])
        self.assertIn('"stop"', crit["none"])


class Languages(unittest.TestCase):
    def test_pick(self):
        self.assertEqual(lang.pick("en"), "en")
        self.assertEqual(lang.pick("auto", "esES", {}), "es")
        self.assertEqual(lang.pick("auto", "enGB", {}), "en")
        self.assertEqual(lang.pick("auto", "", {"LANG": "es_ES.UTF-8"}), "es")
        self.assertEqual(lang.pick("auto", "frFR", {"LANG": "fr_FR.UTF-8"}), "en")

    def test_packs_have_the_same_orders(self):
        es, en = lang.load("es"), lang.load("en")
        self.assertEqual(set(es.PHRASES), set(en.PHRASES))
        self.assertEqual(set(es.PHRASES) | {"turn_left", "turn_right", "turn_around"}, set(C.BASE))


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
    time.sleep(0.7)
    return kb.events, acts


class Doing(unittest.TestCase):
    def test_jump_while_moving_holds_the_direction_and_jumps(self):
        ev, _ = run_orders([C.Order("jump_left")], cfg={"jumpMoveSeconds": 0.2})
        self.assertIn("hold", [e[0] for e in ev])
        self.assertIn("press", [e[0] for e in ev])

    def test_pace_orders_press_the_toggle_only_when_it_changes(self):
        ev, acts = run_orders([C.Order("slower"), C.Order("slower"), C.Order("faster"), C.Order("faster")])
        self.assertEqual(sum(1 for e in ev if e[0] == "press"), 2)
        self.assertFalse(acts.walking)
        self.assertFalse(acts.autorun)

    def test_camina_and_corre_get_going(self):
        # camina: walk toggle + autorun; corre while moving: only the toggle back to running.
        ev, acts = run_orders([C.Order("walk"), C.Order("run")])
        self.assertEqual(sum(1 for e in ev if e[0] == "press"), 3)
        self.assertTrue(acts.autorun)
        self.assertFalse(acts.walking)
        # corre from standing, already running: only autorun.
        ev, acts = run_orders([C.Order("run")])
        self.assertEqual(sum(1 for e in ev if e[0] == "press"), 1)
        self.assertTrue(acts.autorun)

    def test_turn_time_follows_the_degrees(self):
        ev, _ = run_orders([C.Order("turn_left", degrees=45), C.Order("turn_right", degrees=180), C.Order("turn_left", degrees=999)],
                           cfg={"turnDegreesPerSecond": 180})
        self.assertEqual([round(e[2], 2) for e in ev if e[0] == "hold"], [0.25, 1.0, 1.0])

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
["character"] = "Aria-Reino de Prueba",
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
            self.assertEqual(km.character, "Aria-Reino de Prueba")
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


class Combined(unittest.TestCase):
    def test_split(self):
        self.assertEqual(C.split_orders("Salta y gira a la derecha, luego adelante"), ["salta", "gira a la derecha", "adelante"])
        self.assertEqual(C.split_orders("salta dos veces"), ["salta dos veces"])

    def test_combo_runs_every_part_in_order(self):
        ev, _ = run_orders([C.Order("combo", extra={"orders": [C.Order("jump"), C.Order("turn_right", degrees=45), C.Order("forward")]})],
                           cfg={"turnDegreesPerSecond": 10000, "holdSeconds": 0.01})
        self.assertEqual([e[0] for e in ev], ["press", "hold", "hold"])


class AliasesAndLearning(unittest.TestCase):
    def test_aliases_resolve_and_are_checked(self):
        from wowvoz.aliases import Aliases
        with tempfile.TemporaryDirectory() as tmp:
            user, learned = os.path.join(tmp, "a.json"), os.path.join(tmp, "l.json")
            with open(user, "w") as f:
                f.write('{"Evis": "button:Bola de Fuego", "un pelín derecha": {"order": "turn_right", "degrees": 10}, "raro": "run_lua"}')
            with open(learned, "w") as f:
                f.write('{"quieres pierda": "turn_left", "evis": "jump"}')
            a = Aliases(user, learned)
            self.assertTrue(a.refresh())
            self.assertEqual(a.order_for("evis", BUTTONS).button["id"], 133, "yours win over learned")
            self.assertEqual(a.order_for("Quieres pierda", BUTTONS).kind, "turn_left")
            self.assertEqual(a.order_for("un pelín derecha", BUTTONS).degrees, 10)
            self.assertIsNone(a.order_for("raro", BUTTONS), "not an order")
            self.assertFalse(a.refresh(), "unchanged files are not reread")

    def test_ask_ai(self):
        from wowvoz.recognize import ask_ai_question
        self.assertEqual(ask_ai_question("oye ia qué misión hago"), "que mision hago")
        self.assertEqual(ask_ai_question("pregúntale a la ia cuánto oro tengo"), "cuanto oro tengo")
        self.assertIsNone(ask_ai_question("ya"))
        self.assertIsNone(ask_ai_question("y a la derecha"), "no wake word, too short")
        self.assertIsNone(ask_ai_question("salta"))

    def test_jev_gets_the_closest_phrase_as_a_hint(self):
        body, _ = C.jev_request("gira de echa", BUTTONS, hint="gira a la derecha")
        self.assertEqual(body["state"]["closest_order_phrase"], "gira a la derecha")
        self.assertIn("only a hint", body["questions"]["order"]["instructions"])
        self.assertNotIn("closest_order_phrase", C.jev_request("x", BUTTONS)[0]["state"])

    def test_learning_needs_evidence(self):
        from wowvoz import learn as Lr
        lines = [
            {"type": "miss", "free": "quieres pierda", "grammar": "izquierda", "jev": {"choice": "turn_left", "confidence": 0.5}},
            {"type": "follow", "miss": "quieres pierda", "order": "turn_left", "said": "izquierda"},
            {"type": "miss", "free": "hola", "grammar": "salta", "jev": {"choice": "none", "confidence": 0.99}},
            {"type": "follow", "miss": "hola", "order": "jump", "said": "salta"},
            {"type": "follow", "miss": "hola", "order": "jump", "said": "salta"},
            {"type": "miss", "free": "otra vez", "grammar": "atras", "jev": {"choice": "back", "confidence": 0.5}},
        ]
        ev = Lr.evidence(lines)
        taken = Lr.existing_phrases(BUTTONS)
        self.assertEqual(Lr.acceptable("quieres pierda", "turn_left", ev, BUTTONS, taken), "", "followed by it and JEV agreed")
        self.assertIn("common word", Lr.acceptable("hola", "jump", ev, BUTTONS, taken))
        self.assertIn("not enough evidence", Lr.acceptable("otra vez", "back", ev, BUTTONS, taken))
        self.assertIn("already means", Lr.acceptable("salta", "back", ev, BUTTONS, taken))
        self.assertIn("not an order", Lr.acceptable("quieres pierda", "run_lua", ev, BUTTONS, taken))

    def test_miss_log_pairs_a_miss_with_the_order_right_after(self):
        from wowvoz.learn import MissLog
        with tempfile.TemporaryDirectory() as tmp:
            log = MissLog(os.path.join(tmp, "m.jsonl"))
            log.miss({"free": "quieres pierda", "grammar": "izquierda"})
            log.success(C.Order("turn_left", text="izquierda"))
            log.success(C.Order("jump", text="salta"))  # no miss before it: nothing
            import json
            with open(os.path.join(tmp, "m.jsonl")) as f:
                recs = [json.loads(line) for line in f]
            self.assertEqual([r["type"] for r in recs], ["miss", "follow"])
            self.assertEqual(recs[1]["order"], "turn_left")


class OtherSystems(unittest.TestCase):
    """Windows and macOS key handling, against stand-ins for their system calls."""

    def test_windows_layout_modifiers_and_order(self):
        from wowvoz.keyboard import resolve
        from wowvoz.platforms import windows as W

        class User32:
            sent = []

            def MapVirtualKeyW(self, vk, kind):
                return vk + 0x100

            def VkKeyScanW(self, ch):  # a Spanish layout: "=" is Shift+0, "@" is AltGr+2
                return {ord("="): 0x0130, ord("@"): 0x0632, ord("w"): 0x0057}.get(ch, -1)

            def SendInput(self, n, ref, size):
                ki = ref._obj.u.ki
                self.sent.append((ki.wVk, bool(ki.dwFlags & W.KEYEVENTF_KEYUP)))
                return 1

        u = User32()
        km = W.Keymap(u)
        self.assertEqual(resolve("W", km), [(0x57, 0x157, False)])
        self.assertEqual([c[0] for c in resolve("=", km)], [0xA0, 0x30])            # Shift + 0
        self.assertEqual([c[0] for c in resolve("SHIFT-=", km)], [0xA0, 0x30])      # Shift once
        self.assertEqual([c[0] for c in resolve("@", km)], [0xA2, 0xA5, 0x32])      # AltGr = Ctrl + right Alt
        self.assertEqual(resolve("NUMPADDIVIDE", km)[0][2], True)                    # extended key
        self.assertEqual(ctypes_size_ok(W), True)
        kb = W.Keyboard(u)
        kb.press(resolve("CTRL-SHIFT-F12", km), tap=0)
        self.assertEqual(u.sent, [(0xA2, False), (0xA0, False), (0x7B, False), (0x7B, True), (0xA0, True), (0xA2, True)])
        with self.assertRaises(Unsupported):
            resolve("PAD1", km)

    def test_macos_keys_carry_the_held_modifiers(self):
        from wowvoz.keyboard import resolve
        from wowvoz.platforms import macos as M

        class Quartz:
            events = []

            def CGEventCreateKeyboardEvent(self, src, code, down):
                self.events.append([code, down, None])
                return len(self.events)

            def CGEventSetFlags(self, ev, flags):
                self.events[ev - 1][2] = flags

            def CGEventPost(self, tap, ev):
                pass

            def CFRelease(self, ev):
                pass

        q = Quartz()
        km = M.Keymap()
        codes = resolve("CTRL-SHIFT-F12", km)
        self.assertEqual([c[0] for c in codes], [0x3B, 0x38, 0x6F])
        M.Keyboard(q).press(codes, tap=0)
        f12_down = next(e for e in q.events if e[0] == 0x6F and e[1])
        self.assertEqual(f12_down[2], 0x00040000 | 0x00020000)                      # Ctrl + Shift held
        self.assertEqual(q.events[-1], [0x3B, False, 0])                             # all released
        self.assertEqual(resolve("W", km), [(0x0D, 0)])

    def test_system_by_platform(self):
        from wowvoz import platforms
        self.assertIn(platforms.name(), ("linux", "windows", "macos"))


def ctypes_size_ok(W):
    """INPUT must be as big as Windows' (40 bytes on 64-bit, 28 on 32-bit)."""
    import ctypes
    return ctypes.sizeof(W.INPUT) in (40, 28)
