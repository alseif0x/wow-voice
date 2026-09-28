"""wow-voz: play WoW guided by your voice.

  python -m wowvoz              listen and play (keys go to WoW only while it has focus)
  python -m wowvoz --dry-run    listen, but only print what it would press
  python -m wowvoz --say TEXT   what TEXT would do (no microphone, nothing pressed)
  python -m wowvoz --file X.wav what a 16 kHz mono recording would do
  python -m wowvoz --keys       the key map it is using
  python -m wowvoz --paused     start paused ("voz activa" to begin)
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import time
import wave

from . import commands as C
from . import config
from .actions import Actions
from .game import Focus, load_keymap
from .keyboard import DryKeyboard, Keyboard, XKeymap
from .beeps import Beeps
from .listen import FRAME_BYTES, Phrases, microphone, other_listener_active


def x_display() -> None:
    """Point DISPLAY/XAUTHORITY at GNOME's Xwayland, where WoW (under Wine) lives."""
    if not os.environ.get("DISPLAY"):
        out = subprocess.run(["pgrep", "-a", "Xwayland"], capture_output=True, text=True).stdout
        m = re.search(r"Xwayland (:\d+)", out)
        os.environ["DISPLAY"] = m.group(1) if m else ":0"
    if not os.environ.get("XAUTHORITY"):
        auth = sorted(glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"), key=os.path.getmtime, reverse=True)
        if auth:
            os.environ["XAUTHORITY"] = auth[0]


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
    if o.kind == "button":
        b = o.button or {}
        what = b.get("name") or (f"botón {b['number']}" if "number" in b else b.get("command"))
        return f"button {what}"
    extra = f" x{o.count}" if o.count > 1 else (f" {o.seconds:g}s" if o.seconds else "")
    return o.kind + extra


def main() -> int:
    ap = argparse.ArgumentParser(prog="wow-voz", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--say")
    ap.add_argument("--file")
    ap.add_argument("--keys", action="store_true")
    ap.add_argument("--paused", action="store_true")
    ap.add_argument("--config", default=config.CONFIG_FILE)
    args = ap.parse_args()
    cfg = config.load(args.config)
    if args.paused:
        cfg["startPaused"] = True
    log = make_log(cfg["log"])
    x_display()

    keymap = load_keymap(cfg["savedVariables"])
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
        o = C.parse(args.say, rec.buttons) or rec.ask_jev(args.say, "jev")
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
        xk = XKeymap()
    except OSError as e:
        log(f"no X keyboard map ({e}); run it inside the desktop session")
        return 2
    kb = DryKeyboard(log) if args.dry_run else Keyboard()
    if cfg.get("whisperFallback", True):
        # Whisper is the slow last resort: load it now, so its first use doesn't wait for that.
        import threading
        threading.Thread(target=lambda: rec.whisper_text(b"\0" * 6400), daemon=True).start()
    focus = Focus(cfg["windowName"])
    acts = Actions(kb, keymap, xk, focus, cfg, log)
    log(f"wow-voz listening{' (dry run)' if args.dry_run else ''}{' - paused, say \"voz activa\"' if acts.paused else ''}")
    log(f"key map: {keymap.source}; {len(rec.buttons)} named buttons")
    beeps = Beeps(cfg)
    beeps.play("off" if acts.paused else "on")
    phrases = Phrases(float(cfg["threshold"]), int(cfg["silenceMs"]), int(cfg["maxPhraseMs"]))
    sv_mtime = 0.0
    last_check = 0.0
    # The microphone is read on its own thread, so no audio is lost while a phrase is worked out.
    import queue
    import threading
    frames: queue.Queue = queue.Queue(maxsize=2000)

    def reader():
        for fr in microphone(cfg["recordCommand"]):
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
                paths = glob.glob(cfg["savedVariables"])
                m = max((os.path.getmtime(p) for p in paths), default=0.0)
                if m != sv_mtime:
                    sv_mtime = m
                    keymap = load_keymap(cfg["savedVariables"])
                    acts.keymap = keymap
                    rec.set_buttons(keymap.named_buttons())
                    log(f"key map: {keymap.source}; {len(rec.buttons)} named buttons")
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
                continue
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
