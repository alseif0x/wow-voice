"""Learning from misses: what was said, what it turned out to mean.

wow-voice appends every phrase it didn't act on to misses.jsonl, and when an order
does work within a few seconds of a miss, that order too (people repeat
themselves: "quieres pierda" ... "izquierda"). `python -m wowvoice.learn` (the
wow-voice-learn timer, hourly) reads what is new, asks an agent (Claude or Codex,
headless) which misses clearly meant which order, checks every proposal itself,
and adds the good ones to learned.json, which wow-voice picks up on its own.

Nothing is added on the agent's word alone: an alias needs a miss followed by
that order, twice, or once plus JEV having guessed the same order. Common words
and phrases that already mean another order are refused.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from . import commands as C
from . import config
from . import lang
from .aliases import LEARNED_FILE, USER_FILE, _read, valid
from .game import load_keymap

MISSES = os.path.expanduser("~/.cache/wow-voice/misses.jsonl")
LOG = os.path.expanduser("~/.cache/wow-voice/learn.log")
FOLLOW_SECONDS = 6.0


class MissLog:
    """Used by wow-voice while it runs."""

    def __init__(self, path: str = MISSES):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.last_miss: dict | None = None

    def _write(self, rec: dict) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def miss(self, heard: dict) -> None:
        free = heard.get("free") or ""
        if not free:
            return
        rec = {"type": "miss", "t": round(time.time(), 2), "free": free, "grammar": heard.get("grammar") or "", "jev": heard.get("jev") or {}}
        self._write(rec)
        self.last_miss = rec

    def success(self, order: C.Order) -> None:
        m = self.last_miss
        if not m or time.time() - m["t"] > FOLLOW_SECONDS:
            return
        self.last_miss = None
        spec = f"button:{(order.button or {}).get('name')}" if order.kind == "button" and (order.button or {}).get("name") else order.kind
        if order.kind == "button" and not (order.button or {}).get("name"):
            return
        self._write({"type": "follow", "t": round(time.time(), 2), "miss": m["free"], "order": spec, "said": order.text})


def _log(msg: str) -> None:
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M ") + msg + "\n")
    print(msg)


def evidence(lines: list[dict]) -> dict[str, dict]:
    """miss phrase -> {"orders": {spec: n}, "jev": {choice: n}, "misses": n}."""
    ev: dict[str, dict] = {}
    for r in lines:
        if r.get("type") == "miss":
            e = ev.setdefault(C.norm(r.get("free", "")), {"orders": {}, "jev": {}, "misses": 0, "grammar": {}})
            e["misses"] += 1
            ch = (r.get("jev") or {}).get("choice")
            if ch and ch != "none":
                e["jev"][ch] = e["jev"].get(ch, 0) + 1
            g = r.get("grammar")
            if g and g != "[unk]":
                e["grammar"][g] = e["grammar"].get(g, 0) + 1
        elif r.get("type") == "follow":
            e = ev.setdefault(C.norm(r.get("miss", "")), {"orders": {}, "jev": {}, "misses": 0, "grammar": {}})
            e["orders"][r["order"]] = e["orders"].get(r["order"], 0) + 1
    return {k: v for k, v in ev.items() if k}


def acceptable(phrase: str, spec: str, ev: dict, buttons: list[dict], taken: dict) -> str:
    """"" when the alias may be added, else why not."""
    words = phrase.split()
    if not 1 <= len(words) <= 6 or phrase in C.L.NEVER_LEARN or phrase in C.FILLER:
        return "too short, too long or a common word"
    if not valid(spec, buttons):
        return "not an order"
    if phrase in taken and taken[phrase] != spec:
        return f"already means {taken[phrase]}"
    e = ev.get(phrase)
    if not e:
        return "no evidence in the log"
    follows = e["orders"].get(spec, 0)
    jev_same = e["jev"].get(spec, 0) if not spec.startswith("button:") else 0
    if follows >= 2 or (follows >= 1 and jev_same >= 1):
        return ""
    return f"not enough evidence (followed by it {follows}x, JEV guessed it {jev_same}x)"


def existing_phrases(buttons: list[dict]) -> dict[str, str]:
    out = {}
    for iid, (_, _, words, _) in C.INTENTS.items():
        for w in words:
            out[C.norm(w)] = iid
    for p, (side, _) in C.TURNS.items():
        out[C.norm(p)] = "turn_left" if side == "left" else "turn_right"
    return out


def ask_agent(cmd: list[str], prompt: str, timeout: int) -> dict:
    try:
        res = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        _log(f"agent failed: {e}")
        return {}
    out = res.stdout.strip()
    start, end = out.find("{"), out.rfind("}")
    if start < 0 or end < start:
        _log(f"agent gave no JSON (exit {res.returncode})")
        return {}
    try:
        data = json.loads(out[start:end + 1])
    except ValueError:
        _log("agent gave unreadable JSON")
        return {}
    return data.get("aliases") if isinstance(data.get("aliases"), dict) else {}


PROMPT = """You tune a voice-control program for World of Warcraft ({language} speech, Vosk small model).
Below are phrases it misheard or couldn't place ("misses"), with evidence: which order the player
said right after (within 6 s), what JEV (a decision model) guessed, and which order phrase the
closed-grammar recognizer thought it was. Propose aliases ONLY for misses that clearly are a
mishearing of, or another way of saying, one of the orders. Never map ordinary speech, questions
or words that could easily be said for other reasons. When unsure, leave it out: an empty result
is fine.

Orders (id: example phrases):
{orders}
Action-bar buttons (use "button:<name>"): {buttons}
Aliases already in use: {aliases}

Misses and evidence (phrase: evidence):
{misses}

Reply with JSON only: {{"aliases": {{"<miss phrase exactly as listed>": "<order id or button:name>"}}}}
"""


def main() -> int:
    cfg = config.load()
    try:
        with open(MISSES, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip().startswith("{")]
    except OSError:
        _log("no misses yet")
        return 0
    ev = evidence(lines)  # the whole history each time: small, and nothing counted twice
    keymap = load_keymap(cfg["savedVariables"])
    C.set_language(lang.pick(cfg.get("language", "auto"), keymap.locale))
    buttons = keymap.named_buttons()
    learned = _read(LEARNED_FILE)
    user = _read(USER_FILE)
    taken = {**existing_phrases(buttons), **{C.norm(k): v for k, v in learned.items()}, **{C.norm(k): v for k, v in user.items()}}
    candidates = {k: v for k, v in ev.items() if k not in taken and (v["orders"] or v["jev"])}
    added = {}
    if candidates and cfg.get("learnCommand", True) is not False:
        orders = "\n".join(f"- {iid}: {', '.join(words[:4]) if words else crit}" for iid, (_, _, words, crit) in C.INTENTS.items())
        prompt = PROMPT.format(language=C.L.NAME, orders=orders, buttons=", ".join(b["name"] for b in buttons) or "(none)",
                               aliases=json.dumps({**learned, **user}, ensure_ascii=False),
                               misses="\n".join(f"- {k}: {json.dumps(v, ensure_ascii=False)}" for k, v in list(candidates.items())[:60]))
        cmd = cfg.get("learnCommand") or ["claude", "-p", "--model", "opus", "--effort", "low"]
        proposals = ask_agent(cmd, prompt, int(cfg.get("learnTimeout", 240)))
        for phrase, spec in proposals.items():
            p = C.norm(str(phrase))
            why = acceptable(p, spec, ev, buttons, taken)
            if why:
                _log(f"refused {p!r} -> {spec}: {why}")
                continue
            added[p] = spec
            taken[p] = spec
    # Without an agent (or on top of it): what the log itself proves beyond doubt.
    for p, e in ev.items():
        if p in taken:
            continue
        best = max(e["orders"].items(), key=lambda kv: kv[1], default=(None, 0))
        if best[0] and best[1] >= 3 and not acceptable(p, best[0], ev, buttons, taken):
            added[p] = best[0]
            taken[p] = best[0]
    if added:
        learned.update(added)
        os.makedirs(os.path.dirname(LEARNED_FILE), exist_ok=True)
        with open(LEARNED_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(learned, f, ensure_ascii=False, indent=2)
        os.replace(LEARNED_FILE + ".tmp", LEARNED_FILE)
        for p, spec in added.items():
            _log(f"learned {p!r} -> {spec}")
    else:
        _log(f"nothing new to learn ({len(candidates)} candidate phrase(s))")
    # Keep the log bounded: the last 5000 lines are plenty of evidence.
    if len(lines) > 5000:
        with open(MISSES + ".tmp", "w", encoding="utf-8") as f:
            for r in lines[-5000:]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(MISSES + ".tmp", MISSES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
