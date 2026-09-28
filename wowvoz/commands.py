"""The voice orders: what can be said, what each one presses.

Every order is one thing you would do with a key: jump (N times if you say how
many), walk forward or back for a moment, step sideways, turn, autorun, stop,
target, sit, open the map or the bags, or press the action button that holds a
spell, item or macro. Nothing repeats or chains by itself: "salta dos veces" is
two jumps because you said two.

`phrases()` lists every exact phrase for Vosk's closed grammar; `parse()` turns a
phrase (from Vosk, or free text) into an Order; `jev_request()` asks JEV which
order a free phrase means when parse() can't tell.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from . import lang

# id -> (binding command or None, how it is done, JEV criteria). The phrases for
# each come from the language pack (lang/es.py, lang/en.py): see set_language().
BASE = {
    "jump":         ("JUMP", "tap", "Jump in place, once or the number of times said."),
    # Jumping while moving that way: the direction held a moment, the jump in the middle.
    "jump_left":    ("STRAFELEFT", "jumpmove", "Jump sideways to the left."),
    "jump_right":   ("STRAFERIGHT", "jumpmove", "Jump sideways to the right."),
    "jump_forward": ("MOVEFORWARD", "jumpmove", "Jump forward."),
    "jump_back":    ("MOVEBACKWARD", "jumpmove", "Jump backward."),
    "forward":      ("MOVEFORWARD", "hold", "Walk forward for a moment."),
    "back":         ("MOVEBACKWARD", "hold", "Walk backward for a moment."),
    "strafe_left":  ("STRAFELEFT", "hold", "Step sideways to the left, without turning."),
    "strafe_right": ("STRAFERIGHT", "hold", "Step sideways to the right, without turning."),
    "turn_left":    ("TURNLEFT", "turn", "Turn to the left, a little or a lot."),
    "turn_right":   ("TURNRIGHT", "turn", "Turn to the right, a little or a lot."),
    "turn_around":  ("TURNLEFT", "turn", "Turn around to face the other way, 180 degrees, no side needed."),
    "autorun":      ("TOGGLEAUTORUN", "tap", "Switch autorun on or off: keep going straight ahead on its own."),
    "walk":         ("TOGGLERUN", "walkgo", "Walk forward at walking speed, on its own until told to stop."),
    "run":          ("TOGGLERUN", "rungo", "Run forward at running speed, on its own until told to stop."),
    "slower":       ("TOGGLERUN", "walkmode", "Slow down to walking speed without starting to move."),
    "faster":       ("TOGGLERUN", "runmode", "Speed up to running without starting to move."),
    "stop":         (None, "stop", "Stop moving: stop walking, running or autorun."),
    "target":       ("TARGETNEARESTENEMY", "tap", "Target the next nearest enemy."),
    "target_friend": ("TARGETNEARESTFRIEND", "tap", "Target the nearest friendly character."),
    "focus":        ("WOWVOZ_FOCUS", "tap", "Set the current target as focus."),
    "target_focus": ("WOWVOZ_TARGETFOCUS", "tap", "Target the focus again."),
    "focus_friend": ("WOWVOZ_FOCUSFRIEND", "tap", "Set the nearest friendly character as focus, keeping the current target."),
    "clear_focus":  ("WOWVOZ_CLEARFOCUS", "tap", "Clear the focus."),
    "assist_focus": ("WOWVOZ_ASSISTFOCUS", "tap", "Target what the focus is targeting."),
    "assist":       ("ASSISTTARGET", "tap", "Target what the current target is targeting."),
    "interact":     ("INTERACTTARGET", "tap", "Interact with what is in front: loot a corpse, talk to a character, open or pick up an object."),
    "sit":          ("SITORSTAND", "tap", "Sit down or stand up."),
    "close":        ("TOGGLEGAMEMENU", "tap", "Close the open window or menu (Escape)."),
    "map":          ("TOGGLEWORLDMAP", "tap", "Open or close the world map."),
    "bags":         ("TOGGLEBACKPACK", "tap", "Open or close the bags."),
    "ask_ai":       ("WOWAI_TALK", "ask_ai", "A question or request for the AI assistant (WoW AI), usually starting with a wake word."),
    "pause":        (None, "pause", "Stop listening to voice orders for now."),
    "resume":       (None, "resume", "Start listening to voice orders again."),
}

# Filled in by set_language(): id -> (command, how, phrases, JEV criteria). The
# same dict object throughout (other modules import it), refilled in place.
INTENTS: dict[str, tuple] = {}
L = None  # the language pack in use
LANGUAGE = ""


def set_language(code: str) -> None:
    """Use this language's phrases and words for everything below."""
    global L, LANGUAGE, NUMBERS, COUNT_WORDS, FILLER, CAST_VERBS, TURNS, AROUND, DEGREE_WORDS, SPLIT, NONE_CRITERIA, HINT_NOTE
    L = lang.load(code)
    LANGUAGE = code
    NUMBERS, COUNT_WORDS, FILLER, CAST_VERBS = L.NUMBERS, L.COUNT_WORDS, L.FILLER, L.CAST_VERBS
    TURNS, AROUND, DEGREE_WORDS = L.TURNS, L.AROUND, L.DEGREE_WORDS
    INTENTS.clear()
    for iid, (command, how, crit) in BASE.items():
        if iid in ("turn_left", "turn_right"):
            words = [p for p, (d, _) in TURNS.items() if d == iid[5:]]
        elif iid == "turn_around":
            words = list(AROUND)
        else:
            words = list(L.PHRASES.get(iid, []))
        examples = words[:3] or ([L.AI_EXAMPLE] if iid == "ask_ai" else [])
        if examples:
            crit = f"{crit} Said like: " + ", ".join(f'"{e}"' for e in examples) + "."
        INTENTS[iid] = (command, how, words, crit)
    joins = "|".join(r"\b" + re.escape(c) + r"\b" for c in sorted(L.CONNECTORS, key=len, reverse=True))
    SPLIT = re.compile(r"\s*(?:,|" + joins + r")\s*")
    NONE_CRITERIA = ("Not an order for the character: talking to someone in the room, a question or a request for the "
                     f"AI assistant, chat, noise, or a sentence that only mentions a word like \"{L.NONE_EXAMPLES[0]}\" "
                     f"or \"{L.NONE_EXAMPLES[1]}\".")
    HINT_NOTE = (" `closest_order_phrase` is the order phrase the sound was closest to: only a hint about mishearing "
                 f"(\"{L.HINT_EXAMPLE[0]}\" was \"{L.HINT_EXAMPLE[1]}\"). Ordinary speech always has some closest phrase "
                 "too, so pick none when `utterance` is clearly not an order.")


JEV_INSTRUCTIONS = ("The player of World of Warcraft said `utterance` out loud while playing. It may be a voice order "
                    "for their character (the options below) or something else. Pick the order they gave, or none. "
                    "Speech recognition can mishear words: judge what they meant.")


@dataclass
class Order:
    kind: str                 # an id from INTENTS, or "button"
    count: int = 1            # jumps
    seconds: float = 0.0      # holds (0 = the default)
    degrees: float = 0.0      # turns (0 = the default)
    button: dict | None = None
    text: str = ""
    via: str = ""             # vosk, vosk+jev, whisper+jev
    confidence: float = 1.0
    extra: dict = field(default_factory=dict)


def norm(s: str) -> str:
    """Lowercase, no accents or punctuation, single spaces."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9ñ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def spoken_name(name: str) -> str:
    """A spell or item name as it would be said: "Bola de Fuego (Rango 1)" -> "bola de fuego"."""
    return norm(re.sub(r"\(.*?\)", "", name))


def short_names(buttons: list[dict]) -> dict[str, dict]:
    """"golpe" for "Golpe siniestro": a button's first word, when it is long enough,
    no other button starts with it, and it isn't an order word."""
    firsts: dict[str, list[dict]] = {}
    for b in buttons:
        words = spoken_name(b.get("name") or "").split()
        if len(words) >= 2 and len(words[0]) >= 4:
            firsts.setdefault(words[0], []).append(b)
    taken = {norm(w) for _, _, ws, _ in INTENTS.values() for w in ws for w in w.split()} | set(NUMBERS) | set(CAST_VERBS)
    return {w: bs[0] for w, bs in firsts.items() if len(bs) == 1 and w not in taken}


def phrases(buttons: list[dict]) -> list[str]:
    """Every exact phrase Vosk's grammar accepts (Vosk drops words it doesn't know)."""
    out = []
    for iid, (_, how, words, _) in INTENTS.items():
        out.extend(words)
        if iid == "jump":
            out.extend(f"{w} {n} {L.TIMES}" for w in words for n in COUNT_WORDS)
            out.extend(f"{w} {n}" for w in words for n in L.TIMES_SPECIAL)
        if how == "hold":
            out.extend(f"{w} {n}" for w in words for n in COUNT_WORDS)
        if iid in ("turn_left", "turn_right"):
            side = L.SIDES[iid[5:]]
            out.extend(L.TURN_DEGREES_PHRASE.format(side=side, n=d) for d in DEGREE_WORDS)
    for b in buttons:
        n = spoken_name(b.get("name") or "")
        if n:
            out.append(n)
            out.extend(f"{v} {n}" for v in CAST_VERBS)
    for w in short_names(buttons):
        out.append(w)
        out.extend(f"{v} {w}" for v in CAST_VERBS)
    out.extend(f"{L.BUTTON_WORD} {w}" for w in L.BUTTON_NUMBERS)
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def split_orders(text: str) -> list[str]:
    """"salta y gira a la derecha, luego adelante" -> ["salta", "gira a la derecha", "adelante"]."""
    t = norm(text.replace(",", " , "))
    return [p for p in (x.strip() for x in SPLIT.split(t)) if p]


def close_enough(grammar: str, free: str, min_ratio: float = 0.75) -> bool:
    """Vosk's closed-list guess and its free transcript sound alike ("gira a la
    derecha" / "gira de echa", "salta" / "falta"): the order is taken. Ordinary
    speech is far from any order phrase ("hola" / "salta" is 0.22)."""
    from difflib import SequenceMatcher
    g, f = norm(grammar), norm(free)
    if not g or not f or abs(len(g.split()) - len(f.split())) > 1:
        return False
    # One word against one word: only the same length give or take a letter
    # ("falta"/"salta" yes, "proyecto"/"recto" no).
    if len(g.split()) == 1 and len(f.split()) == 1 and abs(len(g) - len(f)) > 1:
        return False
    return SequenceMatcher(None, g, f).ratio() >= min_ratio


def button_by_sound(text: str, buttons: list[dict], min_ratio: float = 0.75) -> dict | None:
    """The button whose name sounds most like what was said (with or without
    "lanza/usa..."), when it is close enough and clearly the best."""
    from difflib import SequenceMatcher
    t = norm(text)
    for v in CAST_VERBS:
        if t.startswith(v + " "):
            t = t[len(v) + 1:]
            break
    tc = t.replace(" ", "")
    scored = []
    for b in buttons:
        n = spoken_name(b.get("name") or "")
        if n:
            scored.append((SequenceMatcher(None, tc, n.replace(" ", "")).ratio(), b))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] >= min_ratio and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.15):
        return scored[0][1]
    return None


def _number_in(words: list[str]) -> int | None:
    for w in words:
        if w in NUMBERS:
            return NUMBERS[w]
        if w.isdigit():
            return int(w)
    return None


def parse(text: str, buttons: list[dict]) -> Order | None:
    """An exact order phrase -> Order; anything else -> None (then JEV decides)."""
    t = norm(text)
    words = [w for w in t.split() if w not in FILLER]
    t = " ".join(words)
    if not t:
        return None
    # "botón tres" / "button three"
    m = re.fullmatch(norm(L.BUTTON_WORD) + r" (\w+)", t)
    if m:
        n = NUMBERS.get(m.group(1)) or (int(m.group(1)) if m.group(1).isdigit() else None)
        return Order("button", button={"number": n}, text=text) if n and 1 <= n <= 12 else None
    for p in AROUND:
        if t == norm(p):
            return Order("turn_around", degrees=180.0, text=text)
    verbs = "|".join(map(re.escape, L.TURN_VERBS))
    preps = "|".join(re.escape(norm(p)) for p in L.SIDE_PREFIXES)
    left, right, deg_word = norm(L.SIDES["left"]), norm(L.SIDES["right"]), norm(L.DEGREES)
    if re.fullmatch(rf"(?:(?:{verbs}) )?180(?: {deg_word})?", t):
        return Order("turn_around", degrees=180.0, text=text)
    for p, (side, deg) in TURNS.items():
        if t == norm(p):
            return Order("turn_left" if side == "left" else "turn_right", degrees=float(deg), text=text)
    m = re.fullmatch(rf"(?:(?:{verbs}) )?(?:(?:{preps}) )?({left}|{right}) (\d{{1,3}})(?: {deg_word})?", t)
    if m and 5 <= int(m.group(2)) <= 180:
        return Order("turn_left" if m.group(1) == left else "turn_right", degrees=float(m.group(2)), text=text)
    m = re.fullmatch(rf"(?:(?:{verbs}) )?(?:(?:{preps}) )?({left}|{right}) (.+) {deg_word}", t)
    words_deg = {norm(k): v for k, v in DEGREE_WORDS.items()}
    if m and norm(m.group(2)) in words_deg:
        return Order("turn_left" if m.group(1) == left else "turn_right", degrees=float(words_deg[norm(m.group(2))]), text=text)
    for iid, (_, how, ws, _) in INTENTS.items():
        for w in ws:
            wn = norm(w)
            if t == wn:
                return Order(iid, text=text)
            if iid == "jump":
                m = re.fullmatch(re.escape(wn) + r" (\w+) " + re.escape(L.TIMES), t)
                if m and m.group(1) in NUMBERS:
                    return Order(iid, count=NUMBERS[m.group(1)], text=text)
                for special, n in L.TIMES_SPECIAL.items():
                    if t == f"{wn} {special}":
                        return Order(iid, count=n, text=text)
            if how == "hold":
                m = re.fullmatch(re.escape(wn) + r" (\w+)", t)
                if m and (m.group(1) in NUMBERS or m.group(1).isdigit()):
                    return Order(iid, seconds=float(_number_in([m.group(1)]) or 0), text=text)
    for b in buttons:
        n = spoken_name(b.get("name") or "")
        if not n:
            continue
        if t == n or any(t == f"{v} {n}" for v in CAST_VERBS):
            return Order("button", button=b, text=text)
    for w, b in short_names(buttons).items():
        if t == w or any(t == f"{v} {w}" for v in CAST_VERBS):
            return Order("button", button=b, text=text)
    return None


# ---------------------------------------------------------------------------
# JEV: which order does a free phrase mean?
# ---------------------------------------------------------------------------

def jev_options(buttons: list[dict], limit: int = 30) -> dict[str, tuple[str, dict | None]]:
    """option id -> (criteria, button or None)."""
    opts = {"none": (NONE_CRITERIA, None)}
    for iid, (_, _, _, crit) in INTENTS.items():
        opts[iid] = (crit, None)
    for i, b in enumerate(buttons[:limit]):
        name = (b.get("name") or "").strip()
        if name:
            kind = {"spell": "Cast the spell", "item": "Use the item", "macro": "Run the macro"}.get(b.get("kind") or "", "Use")
            opts[f"button_{i}"] = (f'{kind} "{name}" (on an action bar button).', b)
    return opts


def jev_request(utterance: str, buttons: list[dict], model: str = "typesafe/jev-1.13", hint: str = "") -> tuple[dict, dict]:
    opts = jev_options(buttons)
    q = {"type": "choice", "instructions": JEV_INSTRUCTIONS + (HINT_NOTE if hint else ""), "criteria": {k: v[0] for k, v in opts.items()}}
    state = {"utterance": utterance[:300]}
    if hint:
        state["closest_order_phrase"] = hint[:120]
    return {"model": model, "state": state, "questions": {"order": q}}, opts


def order_from_jev(answer: dict, opts: dict, utterance: str, min_conf: float) -> Order | None:
    """JEV's choice -> Order when it is an order and sure enough. Numbers come from the words, not JEV."""
    a = (answer or {}).get("answers", {}).get("order") if isinstance(answer, dict) else None
    if not isinstance(a, dict) or a.get("type") != "choice" or a.get("choice") not in opts:
        return None
    conf = float(a.get("confidence") or 0)
    choice = a["choice"]
    if choice == "none" or conf < min_conf:
        return None
    words = norm(utterance).split()
    n = _number_in(words)
    crit, button = opts[choice]
    if button is not None:
        return Order("button", button=button, text=utterance, confidence=conf)
    o = Order(choice, text=utterance, confidence=conf)
    if choice == "jump":
        special = next((v for k, v in L.TIMES_SPECIAL.items() if k in words), None)
        if special or (n and L.TIMES in words):
            o.count = special or n
    how = INTENTS[choice][1]
    if how == "hold" and n and L.SECONDS & set(words):
        o.seconds = float(n)
    if how == "turn":
        o.degrees = 180.0 if choice == "turn_around" else turn_degrees(words)
    return o


def turn_degrees(words: list[str]) -> float:
    """How far a free phrase says to turn: "un poco" / "a little" 20, "gira" / "turn" 90,
    "mucho" / "hard" 135, "vuelta" / "around" 180, "N grados" / "N degrees", else 45."""
    t = " ".join(words)
    for w in words:
        if w.isdigit() and 5 <= int(w) <= 180:
            return float(w)
    for k, v in sorted(DEGREE_WORDS.items(), key=lambda kv: -len(kv[0])):
        if f"{norm(k)} {norm(L.DEGREES)}" in t:
            return float(v)
    ws = set(words)
    if ws & L.AMOUNT["around"]:
        return 180.0
    if ws & L.AMOUNT["much"]:
        return 135.0
    if ws & L.AMOUNT["little"]:
        return 20.0
    if ws & L.AMOUNT["turn"]:
        return 90.0
    return 45.0


set_language("es")
