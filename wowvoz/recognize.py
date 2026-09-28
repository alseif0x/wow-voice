"""From a spoken phrase to an Order, fastest path first:

  1. Vosk twice on the same audio, at the same time: once with the closed list of
     order phrases (it always answers with one of them) and once free (what was
     really said). When they agree, it is an exact order: done in ~0.3 s.
  2. When they don't, JEV reads the free transcript and says which order was
     meant, or none ("dale un salto" -> jump; a sentence to someone else -> none).
  3. When JEV isn't sure, Whisper transcribes the audio better and JEV decides
     again. Still not sure: nothing happens.
"""

from __future__ import annotations

import json
import threading

from . import commands as C
from . import jev


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
        self._whisper = None

    def set_buttons(self, buttons: list[dict]) -> None:
        self.buttons = buttons
        g = json.dumps(C.phrases(buttons) + ["[unk]"], ensure_ascii=False)
        self.grammar = self.vosk.KaldiRecognizer(self.model, 16000, g)

    def _vosk(self, rec, pcm: bytes, out: dict, key: str) -> None:
        rec.AcceptWaveform(pcm)
        out[key] = json.loads(rec.FinalResult()).get("text", "")
        rec.Reset()

    def whisper_text(self, pcm: bytes) -> str:
        import numpy as np
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(self.cfg["whisperModel"], device=self.cfg.get("device", "cpu"), compute_type="int8")
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = self._whisper.transcribe(audio, language="es", beam_size=1, vad_filter=False,
                                           initial_prompt="World of Warcraft. Salta, adelante, atrás, gira, corre, para, objetivo.")
        return " ".join(s.text.strip() for s in segs).strip()

    def ask_jev(self, text: str, via: str) -> C.Order | None:
        return self.jev_decision(text, via)[0]

    def jev_decision(self, text: str, via: str, min_conf: float | None = None) -> tuple[C.Order | None, bool]:
        """(order or None, sure): sure is True when JEV answered confidently,
        order or "none" alike, so there is no point asking Whisper."""
        body, opts = C.jev_request(text, self.buttons)
        ans, err, ms = jev.decide(body, self.cfg["jevKeyFile"], float(self.cfg.get("jevTimeout", 2.5)))
        if ans is None:
            self.log(f"  jev: {err} ({ms} ms)")
            return None, False
        a = ans.get("answers", {}).get("order", {})
        conf = float(a.get("confidence") or 0)
        min_conf = float(min_conf if min_conf is not None else self.cfg.get("jevMinConfidence", 0.8))
        self.log(f"  jev: {a.get('choice')} {conf:.2f} ({ms} ms)")
        o = C.order_from_jev(ans, opts, text, min_conf)
        if o:
            o.via = via
        return o, conf >= min_conf

    def order_for(self, pcm: bytes) -> tuple[C.Order | None, dict]:
        """The order in this phrase, if any, and what each stage heard (for the log)."""
        heard: dict = {}
        t1 = threading.Thread(target=self._vosk, args=(self.grammar, pcm, heard, "grammar"))
        t2 = threading.Thread(target=self._vosk, args=(self.free, pcm, heard, "free"))
        t1.start(); t2.start(); t1.join(); t2.join()
        g, f = heard.get("grammar", ""), heard.get("free", "")
        if not g and not f:
            return None, heard
        agree = g and g != "[unk]" and C.norm(" ".join(w for w in f.split() if C.norm(w) not in C.FILLER)) == C.norm(g)
        if agree:
            o = C.parse(g, self.buttons)
            if o:
                o.via = "vosk"
                return o, heard
        # Not word for word, but sounding the same: a misheard order.
        if g and g != "[unk]" and f and C.close_enough(g, f, float(self.cfg.get("nearMatch", 0.75))):
            o = C.parse(g, self.buttons)
            if o:
                o.via = "vosk~"
                return o, heard
        # A free phrase: exact after all? ("vale, salta" with a filler word)
        if f:
            o = C.parse(f, self.buttons)
            if o:
                o.via = "vosk"
                return o, heard
            o, sure = self.jev_decision(f, "vosk+jev")
            if o or sure:
                return o, heard  # an order, or surely none: Whisper wouldn't change that
        # Whisper only for a real phrase Vosk heard something in, not for room noise.
        if f and self.cfg.get("whisperFallback", True) and len(pcm) > 16000 * 2 * 0.4:
            w = self.whisper_text(pcm)
            heard["whisper"] = w
            if w and C.norm(w) != C.norm(f):
                # The last resort gets a stricter bar: a misheard phrase shouldn't move you.
                o = C.parse(w, self.buttons) or self.jev_decision(w, "whisper+jev", float(self.cfg.get("jevMinConfidenceWhisper", 0.9)))[0]
                if o:
                    if not o.via:
                        o.via = "whisper"
                    return o, heard
        return None, heard
