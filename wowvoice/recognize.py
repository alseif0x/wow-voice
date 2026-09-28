"""From a spoken phrase to an Order, with Vosk and JEV only:

  1. Vosk twice on the same audio, at the same time: once with the closed list of
     order phrases (yours and learned aliases included), once free. The same
     phrase, or sounding alike, is the order: ~50-300 ms.
  2. The free transcript is checked against aliases, button names by sound, and
     "oye IA ..." / "hey AI ..." (a question for WoW AI).
  3. Otherwise JEV reads the free transcript, with Vosk's closest order phrase
     as a hint about mishearing, and picks the order or none.
  Not sure: nothing happens, and the miss is logged for wow-voice-learn.
"""

from __future__ import annotations

import json
import threading

from . import commands as C
from . import jev
from .aliases import LEARNED_FILE, USER_FILE, Aliases

def ask_ai_question(free: str) -> str | None:
    """"oye IA, qué misión hago" / "hey AI, what quest now" -> the question; None when it isn't one."""
    t = C.norm(free)
    m = C.L.ASK_AI.match(t)
    if not m:
        return None
    # Without a wake word in front, only a literal "ia" and a real question (the
    # language pack says which word, if any): "y a la derecha" sounds like "IA la derecha".
    bare = C.L.AI_BARE
    if not t.startswith(C.L.WAKE) and not (bare and t.startswith(bare + " ") and len(m.group(1).split()) >= 3):
        return None
    return m.group(1).strip() or None


class Recognizer:
    def __init__(self, cfg: dict, log=print):
        import vosk
        vosk.SetLogLevel(-1)
        self.cfg = cfg
        self.log = log
        self.vosk = vosk
        self.model = vosk.Model(cfg["voskModel"])
        self.free = vosk.KaldiRecognizer(self.model, 16000)
        self.grammar = None
        self.buttons: list[dict] = []
        self.aliases = Aliases(cfg.get("aliasesFile") or USER_FILE, cfg.get("learnedFile") or LEARNED_FILE)
        self.aliases.refresh()

    def known(self, phrase: str) -> bool:
        """Every word in Vosk's vocabulary? (It drops unknown words from a grammar,
        which would turn "lanza eviscerar" into a bare "lanza".)"""
        find = getattr(self.model, "vosk_model_find_word", None)
        if find is None:
            return True
        return all(find(w) >= 0 for w in phrase.split())

    def set_buttons(self, buttons: list[dict]) -> None:
        self.buttons = buttons
        all_phrases = C.phrases(buttons) + self.aliases.phrases()
        phrases = [p for p in dict.fromkeys(all_phrases) if self.known(p)]
        unknown = sorted({C.spoken_name(b.get("name") or "") for b in buttons} - set(phrases) - {""})
        if unknown:
            self.log(f"not in Vosk's vocabulary (left to sound matching, aliases and JEV): {', '.join(unknown)}")
        self.grammar = self.vosk.KaldiRecognizer(self.model, 16000, json.dumps(phrases + ["[unk]"], ensure_ascii=False))

    def refresh_aliases(self) -> bool:
        if self.aliases.refresh():
            self.set_buttons(self.buttons)
            return True
        return False

    def _vosk(self, rec, pcm: bytes, out: dict, key: str) -> None:
        rec.AcceptWaveform(pcm)
        out[key] = json.loads(rec.FinalResult()).get("text", "")
        rec.Reset()

    def exact(self, text: str) -> C.Order | None:
        return self.aliases.order_for(text, self.buttons) or C.parse(text, self.buttons)

    def jev_decision(self, text: str, via: str, hint: str = "", min_conf: float | None = None) -> tuple[C.Order | None, dict]:
        """(order or None, what JEV said)."""
        body, opts = C.jev_request(text, self.buttons, hint=hint)
        ans, err, ms = jev.decide(body, self.cfg["jevKeyFile"], float(self.cfg.get("jevTimeout", 2.5)))
        if ans is None:
            self.log(f"  jev: {err} ({ms} ms)")
            return None, {"error": err}
        a = ans.get("answers", {}).get("order", {})
        conf = float(a.get("confidence") or 0)
        min_conf = float(min_conf if min_conf is not None else self.cfg.get("jevMinConfidence", 0.8))
        self.log(f"  jev: {a.get('choice')} {conf:.2f} ({ms} ms)")
        o = C.order_from_jev(ans, opts, text, min_conf)
        if o:
            o.via = via
        return o, {"choice": a.get("choice"), "confidence": round(conf, 2)}

    def ask_jev(self, text: str, via: str) -> C.Order | None:
        return self.jev_decision(text, via)[0]

    def combined(self, text: str) -> C.Order | None:
        """"salta y gira a la derecha, luego adelante" -> up to 3 orders, only when
        every part is one (exactly, as an alias, or by JEV); otherwise none of them."""
        parts = C.split_orders(text)
        if len(parts) < 2 or len(parts) > int(self.cfg.get("maxCombined", 3)):
            return None
        orders = []
        for part in parts:
            o = self.exact(part)
            if not o:
                b = C.button_by_sound(part, self.buttons, float(self.cfg.get("nearMatch", 0.75)))
                o = C.Order("button", button=b, text=part) if b else None
            if not o:
                o, _ = self.jev_decision(part, "jev")
            if not o or o.kind in ("pause", "resume", "ask_ai"):
                return None
            orders.append(o)
        return C.Order("combo", text=text, via="vosk+", extra={"orders": orders})

    def order_for(self, pcm: bytes) -> tuple[C.Order | None, dict]:
        """The order in this phrase, if any, and what each stage heard (for the log and the learner)."""
        heard: dict = {}
        t1 = threading.Thread(target=self._vosk, args=(self.grammar, pcm, heard, "grammar"))
        t2 = threading.Thread(target=self._vosk, args=(self.free, pcm, heard, "free"))
        t1.start(); t2.start(); t1.join(); t2.join()
        g, f = heard.get("grammar", ""), heard.get("free", "")
        if not g and not f:
            return None, heard
        g_ok = bool(g) and g != "[unk]"
        f_clean = " ".join(w for w in f.split() if C.norm(w) not in C.FILLER)
        # 1. The same phrase, or sounding alike.
        same = g_ok and C.norm(f_clean) == C.norm(g)
        if g_ok and (same or (f and C.close_enough(g, f, float(self.cfg.get("nearMatch", 0.75))))):
            o = self.exact(g)
            if o:
                if o.via != "alias":
                    o.via = "vosk" if same else "vosk~"
                return o, heard
        if not f:
            return None, heard
        # 2. The free transcript: exact, an alias, a question for WoW AI, a button by sound.
        o = self.exact(f)
        if o:
            o.via = o.via or "vosk"
            return o, heard
        q = ask_ai_question(f)
        if q:
            return C.Order("ask_ai", text=q, via="vosk", extra={"pcm": pcm}), heard
        b = C.button_by_sound(f, self.buttons, float(self.cfg.get("nearMatch", 0.75)))
        if b:
            return C.Order("button", button=b, text=f, via="vosk~"), heard
        # Several orders in one breath: "salta y gira a la derecha".
        combo = self.combined(f)
        if combo:
            return combo, heard
        # 3. JEV, with the closest order phrase as a hint.
        o, said = self.jev_decision(f, "vosk+jev", hint=g if g_ok else "")
        heard["jev"] = said
        if o and o.kind == "ask_ai":
            o.text = f
            o.extra["pcm"] = pcm
        return o, heard
