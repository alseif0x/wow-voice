"""wow-voz: play WoW guided by your voice.

  python -m wowvoz              listen and play (keys go to WoW only while it has focus)
  python -m wowvoz --dry-run    listen, but only print what it would press
  python -m wowvoz --say TEXT   what TEXT would do (no microphone, nothing pressed)
  python -m wowvoz --file X.wav what a 16 kHz mono recording would do
  python -m wowvoz --keys       the key map it is using
  python -m wowvoz --paused     start paused ("voz activa" / "voice on" to begin)
  python -m wowvoz --calibrate  measure the room and your voice, and set the microphone threshold
  python -m wowvoz --lang en    speak English (es, en; default: the game's language)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import wave

from . import commands as C
from . import config
from . import lang
from .actions import Actions
from .game import find_saved_variables, load_keymap
from .keyboard import DryKeyboard
from .platforms import current as current_system
from .beeps import Beeps
from .listen import FRAME_BYTES, Phrases, microphone, other_listener_active


def make_log(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def log(msg: str) -> None:
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    return log


def describe(o: C.Order) -> str:
    if o.kind == "ask_ai":
        return f"ask WoW AI: {o.text!r}"
    if o.kind == "combo":
        return " + ".join(describe(p) for p in (o.extra or {}).get("orders", []))
    if o.kind == "button":
        b = o.button or {}
        what = b.get("name") or (f"button {b['number']}" if "number" in b else b.get("command"))
        return f"button {what}"
    extra = f" x{o.count}" if o.count > 1 else (f" {o.seconds:g}s" if o.seconds else (f" {o.degrees:g}°" if o.degrees else ""))
    return o.kind + extra


def calibrate(cfg: dict, path: str) -> int:
    """Measure the room, then the voice, and save a threshold between them."""
    import json
    from .listen import rms
    import statistics

    def levels(seconds: float) -> list[float]:
        out = []
        for fr in microphone(cfg):
            out.append(rms(fr))
            if len(out) * 0.03 >= seconds:
                break
        return out

    print(C.L.CALIBRATE["quiet"])
    time.sleep(0.5)
    quiet = sorted(levels(3.0))
    print(C.L.CALIBRATE["speak"])
    time.sleep(0.3)
    voice = sorted(levels(5.0))
    noise = quiet[int(len(quiet) * 0.95)] if quiet else 0
    loud = [v for v in voice if v > noise * 2] or voice
    speech = statistics.median(loud) if loud else 0
    if speech <= noise * 1.5:
        print(C.L.CALIBRATE["fail"].format(noise=noise, speech=speech))
        return 1
    threshold = round(max(noise * 1.8, min(speech * 0.35, noise + (speech - noise) * 0.3)))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data["threshold"] = threshold
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(C.L.CALIBRATE["done"].format(noise=noise, speech=speech, threshold=threshold, path=path))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="wow-voz", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--say")
    ap.add_argument("--file")
    ap.add_argument("--keys", action="store_true")
    ap.add_argument("--paused", action="store_true")
    ap.add_argument("--config", default=config.CONFIG_FILE)
    ap.add_argument("--calibrar", "--calibrate", action="store_true")
    ap.add_argument("--lang", choices=lang.LANGUAGES, help="spoken language (default: the config's, or the game's)")
    args = ap.parse_args()
    cfg = config.load(args.config)
    if args.lang:
        cfg["language"] = args.lang
    if args.paused:
        cfg["startPaused"] = True
    log = make_log(cfg["log"])
    system = current_system()
    system.setup()

    keymap = load_keymap(cfg["savedVariables"])
    C.set_language(lang.pick(cfg.get("language", "auto"), keymap.locale))
    cfg["voskModel"] = cfg.get("voskModel") or os.path.join(cfg["voskDir"], C.L.VOSK_MODEL)

    if args.calibrar:
        return calibrate(cfg, args.config)
    if args.keys:
        print(f"key map: {keymap.source}{' - ' + keymap.character if keymap.character else ''}")
        for cmd, keys in sorted(keymap.bindings.items()):
            print(f"  {cmd:22} {', '.join(keys)}")
        for b in keymap.buttons:
            print(f"  {b.get('command') or '':22} {', '.join(b.get('keys') or []) or '(no key)':10} {b.get('name') or ''}")
        return 0

    from .recognize import Recognizer
    rec = Recognizer(cfg, log)
    rec.set_buttons(keymap.named_buttons())

    if args.say is not None:
        from .recognize import ask_ai_question
        b = C.button_by_sound(args.say, rec.buttons, float(cfg.get("nearMatch", 0.75)))
        q = ask_ai_question(args.say)
        o = (rec.exact(args.say) or (C.Order("ask_ai", text=q, via="wake word") if q else None)
             or (C.Order("button", button=b, text=args.say, via="sound") if b else None)
             or rec.combined(args.say) or rec.ask_jev(args.say, "jev"))
        print(describe(o) + f"  (via {o.via or 'parse'}, confidence {o.confidence:.2f})" if o else "no order")
        return 0
    if args.file:
        w = wave.open(args.file)
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            print("the file must be 16 kHz mono")
            return 2
        o, heard = rec.order_for(w.readframes(w.getnframes()))
        print(f"heard {heard}")
        print(describe(o) + f"  (via {o.via})" if o else "no order")
        return 0

    try:
        xk = system.Keymap()
        kb = DryKeyboard(log) if args.dry_run else system.Keyboard()
    except OSError as e:
        log(f"no keyboard for the game ({e}); on Linux run it inside the desktop session, with /dev/uinput writable")
        return 2
    from .learn import MissLog
    misses = MissLog()
    focus = system.Focus(cfg["windowName"])
    acts = Actions(kb, keymap, xk, focus, cfg, log)
    log(f"wow-voz listening, in {C.L.NAME}{' (dry run)' if args.dry_run else ''}{' - paused, say \"voz activa\"' if acts.paused else ''}")
    log(f"key map: {keymap.source}; {len(rec.buttons)} named buttons")
    beeps = Beeps(cfg)
    beeps.play("off" if acts.paused else "on")
    if cfg.get("beepOnOrder", True):
        acts.notify = lambda what: beeps.play(what, every=0.3 if what == "ok" else 2)

    def set_on(on: bool, why: str) -> None:
        if on == (not acts.paused):
            return
        acts.submit(C.Order("resume" if on else "pause"))
        beeps.play("on" if on else "off")
        log(f"voice orders {'ON' if on else 'OFF'} ({why})")

    # The in-game switch (the WoW Voz addon's button): followed whenever it changes.
    import threading
    if cfg.get("gameSwitch", True):
        def watch_switch():
            try:
                sw = system.Switch(cfg.get("windowName", "World of Warcraft").strip("^$"))
            except OSError as e:
                log(f"in-game switch unavailable: {e}")
                return
            last = None
            while True:
                try:
                    state = sw.read()
                except Exception:  # a window going away mid-read
                    state = None
                if state is not None and state != last:
                    if last is not None or state != (not acts.paused):
                        set_on(state, "the in-game button")
                    last = state
                time.sleep(0.5)
        threading.Thread(target=watch_switch, daemon=True).start()

    # Outside the game: `wow-voz-toggle` (systemctl --user kill -s USR1 wow-voz; not on Windows).
    import signal
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, lambda *_: set_on(acts.paused, "wow-voz-toggle"))
    phrases = Phrases(float(cfg["threshold"]), int(cfg["silenceMs"]), int(cfg["maxPhraseMs"]))
    sv_mtime = 0.0
    last_check = 0.0
    # The microphone is read on its own thread, so no audio is lost while a phrase is worked out.
    import queue
    import threading
    frames: queue.Queue = queue.Queue(maxsize=2000)

    def reader():
        for fr in microphone(cfg):
            try:
                frames.put_nowait(fr)
            except queue.Full:
                pass
        frames.put(None)
    threading.Thread(target=reader, daemon=True).start()

    def frame_stream():
        while True:
            fr = frames.get()
            if fr is None:
                return
            yield fr
    try:
        for frame in frame_stream():
            now = time.monotonic()
            if now - last_check > 10:  # the addon's data changes on /reload and logout
                last_check = now
                paths = find_saved_variables(cfg["savedVariables"])
                m = max((os.path.getmtime(p) for p in paths), default=0.0)
                if m != sv_mtime:
                    sv_mtime = m
                    keymap = load_keymap(cfg["savedVariables"])
                    acts.keymap = keymap
                    rec.set_buttons(keymap.named_buttons())
                    log(f"key map: {keymap.source}; {len(rec.buttons)} named buttons")
                if rec.refresh_aliases():
                    log(f"aliases: {len(rec.aliases.table)} (yours and learned)")
            pcm = phrases.feed(frame)
            if pcm is None:
                continue
            if other_listener_active(cfg["wowAiListeningFile"]):
                continue  # that phrase is for WoW AI's "Talk", not an order
            t0 = time.monotonic()
            o, heard = rec.order_for(pcm)
            ms = int((time.monotonic() - t0) * 1000)
            said = heard.get("whisper") or heard.get("free") or heard.get("grammar") or ""
            if not o and not heard.get("free") and not heard.get("whisper"):
                continue  # noise with no words in it
            if not o:
                log(f"\"{said}\" -> nothing ({ms} ms)")
                if not acts.paused:
                    misses.miss(heard)
                continue
            if not acts.paused:
                misses.success(o)
            result = acts.submit(o)
            log(f"\"{said}\" -> {describe(o)} via {o.via} ({ms} ms): {result}")
            if o.kind == "resume":
                beeps.play("on")
            elif o.kind == "pause":
                beeps.play("off")
            elif result.startswith("ignored: paused"):
                beeps.play("paused", every=4)
    except KeyboardInterrupt:
        pass
    finally:
        kb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
