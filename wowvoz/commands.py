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

NUMBERS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
           "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12}
COUNT_WORDS = ["dos", "tres", "cuatro", "cinco"]
FILLER = {"vale", "venga", "eh", "porfa", "ya", "ahora", "oye", "bueno"}


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


# Turning, by how much: a bare "izquierda" is a small, natural turn; "gira" a
# quarter; "mucho" more; "media vuelta" half. Or "... N grados".
TURNS = {}
for _side, _word in (("left", "izquierda"), ("right", "derecha")):
    TURNS.update({
        f"un poco a la {_word}": (_side, 20), f"un poco {_word}": (_side, 20), f"poquito a la {_word}": (_side, 20),
        _word: (_side, 45), f"a la {_word}": (_side, 45), f"hacia la {_word}": (_side, 45),
        f"gira a la {_word}": (_side, 90), f"gira {_word}": (_side, 90), f"gira hacia la {_word}": (_side, 90),
        f"mucho a la {_word}": (_side, 135), f"gira mucho a la {_word}": (_side, 135), f"muy a la {_word}": (_side, 135),
    })
for _p in ("media vuelta", "date la vuelta", "da la vuelta", "vuelta"):
    TURNS[_p] = ("left", 180)
DEGREE_WORDS = {"diez": 10, "veinte": 20, "treinta": 30, "cuarenta y cinco": 45, "sesenta": 60, "noventa": 90,
                "ciento veinte": 120, "ciento ochenta": 180}

# id -> (binding command or None, how it is done, Spanish phrases, JEV criteria)
INTENTS = {
    "jump":         ("JUMP", "tap", ["salta", "salto", "brinca"], "Jump (\"salta\", \"dale un salto\")."),
    "forward":      ("MOVEFORWARD", "hold", ["adelante", "avanza", "camina", "hacia adelante"], "Walk forward for a moment (\"adelante\", \"avanza un poco\")."),
    "back":         ("MOVEBACKWARD", "hold", ["atrás", "retrocede", "hacia atrás", "marcha atrás"], "Walk backward for a moment (\"atrás\", \"retrocede\")."),
    "strafe_left":  ("STRAFELEFT", "hold", ["paso a la izquierda", "de lado a la izquierda", "lateral izquierda"], "Step sideways to the left, without turning (\"paso a la izquierda\")."),
    "strafe_right": ("STRAFERIGHT", "hold", ["paso a la derecha", "de lado a la derecha", "lateral derecha"], "Step sideways to the right, without turning (\"paso a la derecha\")."),
    "turn_left":    ("TURNLEFT", "turn", [p for p, (d, _) in TURNS.items() if d == "left"], "Turn to the left, a little or a lot (\"izquierda\", \"gira a la izquierda\", \"media vuelta\")."),
    "turn_right":   ("TURNRIGHT", "turn", [p for p, (d, _) in TURNS.items() if d == "right"], "Turn to the right, a little or a lot (\"derecha\", \"gira a la derecha\")."),
    "autorun":      ("TOGGLEAUTORUN", "tap", ["corre", "caminar automático", "correr automático", "camina solo", "auto correr", "sigue recto", "todo recto", "sigue adelante", "recto"], "Switch autorun on or off: keep going straight ahead on its own (\"corre\", \"caminar automático\", \"sigue recto\", \"todo recto\")."),
    "stop":         (None, "stop", ["para", "alto", "quieto", "detente", "stop", "frena"], "Stop moving: stop walking, running or autorun (\"para\", \"alto\")."),
    "target":       ("TARGETNEARESTENEMY", "tap", ["siguiente objetivo", "objetivo", "cambia de objetivo", "otro enemigo"], "Target the next nearest enemy (\"siguiente objetivo\")."),
    "target_friend": ("TARGETNEARESTFRIEND", "tap", ["objetivo amigo", "aliado"], "Target the nearest friendly character."),
    "interact":     ("INTERACTTARGET", "tap", ["interactúa", "habla con él", "coge eso"], "Interact with the target: talk, loot, use (\"interactúa\")."),
    "sit":          ("SITORSTAND", "tap", ["siéntate", "levántate", "sentarse"], "Sit down or stand up."),
    "map":          ("TOGGLEWORLDMAP", "tap", ["mapa", "abre el mapa", "cierra el mapa"], "Open or close the world map."),
    "bags":         ("TOGGLEBACKPACK", "tap", ["bolsas", "abre las bolsas", "mochila"], "Open or close the bags."),
    "pause":        (None, "pause", ["voz pausa", "pausa voz", "pausa la voz", "deja de escuchar"], "Stop listening to voice orders for now."),
    "resume":       (None, "resume", ["voz activa", "activa voz", "activa la voz", "escúchame", "empieza"], "Start listening to voice orders again."),
}
CAST_VERBS = ["lanza", "usa", "tira", "activa"]

NONE_CRITERIA = ("Not an order for the character: talking to someone in the room, a question or a request for the "
                 "AI assistant, chat, noise, or a sentence that only mentions a word like \"para\" or \"salta\".")
JEV_INSTRUCTIONS = ("The player of World of Warcraft said `utterance` out loud while playing. It may be a voice order "
                    "for their character (the options below) or something else. Pick the order they gave, or none. "
                    "Speech recognition can mishear words: judge what they meant.")


def norm(s: str) -> str:
    """Lowercase, no accents or punctuation, single spaces."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9ñ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def spoken_name(name: str) -> str:
    """A spell or item name as it would be said: "Bola de Fuego (Rango 1)" -> "bola de fuego"."""
    return norm(re.sub(r"\(.*?\)", "", name))


def phrases(buttons: list[dict]) -> list[str]:
    """Every exact phrase Vosk's grammar accepts (Vosk drops words it doesn't know)."""
    out = []
    for iid, (_, how, words, _) in INTENTS.items():
        out.extend(words)
        if iid == "jump":
            out.extend(f"{w} {n} veces" for w in words for n in COUNT_WORDS)
        if how == "hold":
            out.extend(f"{w} {n}" for w in words for n in COUNT_WORDS)
        if how == "turn":
            word = "izquierda" if iid == "turn_left" else "derecha"
            out.extend(f"gira a la {word} {d} grados" for d in DEGREE_WORDS)
    for b in buttons:
        n = spoken_name(b.get("name") or "")
        if n:
            out.append(n)
            out.extend(f"{v} {n}" for v in CAST_VERBS)
    out.extend(f"botón {w}" for w in list(NUMBERS)[2:])
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


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
    # "botón tres"
    m = re.fullmatch(r"boton (\w+)", t)
    if m:
        n = NUMBERS.get(m.group(1)) or (int(m.group(1)) if m.group(1).isdigit() else None)
        return Order("button", button={"number": n}, text=text) if n and 1 <= n <= 12 else None
    for p, (side, deg) in TURNS.items():
        if t == norm(p):
            return Order("turn_left" if side == "left" else "turn_right", degrees=float(deg), text=text)
    m = re.fullmatch(r"(?:gira )?(?:a la |hacia la )?(izquierda|derecha) (.+) grados", t)
    if m and norm(m.group(2)) in {norm(k): v for k, v in DEGREE_WORDS.items()}:
        deg = {norm(k): v for k, v in DEGREE_WORDS.items()}[norm(m.group(2))]
        return Order("turn_left" if m.group(1) == "izquierda" else "turn_right", degrees=float(deg), text=text)
    for iid, (_, how, ws, _) in INTENTS.items():
        for w in ws:
            wn = norm(w)
            if t == wn:
                return Order(iid, text=text)
            if iid == "jump":
                m = re.fullmatch(re.escape(wn) + r" (\w+) veces", t)
                if m and m.group(1) in NUMBERS:
                    return Order(iid, count=NUMBERS[m.group(1)], text=text)
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


def jev_request(utterance: str, buttons: list[dict], model: str = "typesafe/jev-1.13") -> tuple[dict, dict]:
    opts = jev_options(buttons)
    q = {"type": "choice", "instructions": JEV_INSTRUCTIONS, "criteria": {k: v[0] for k, v in opts.items()}}
    return {"model": model, "state": {"utterance": utterance[:300]}, "questions": {"order": q}}, opts


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
    if choice == "jump" and n and "veces" in words:
        o.count = n
    how = INTENTS[choice][1]
    if how == "hold" and n and ("segundos" in words or "segundo" in words):
        o.seconds = float(n)
    if how == "turn":
        o.degrees = turn_degrees(words)
    return o


def turn_degrees(words: list[str]) -> float:
    """How far a free phrase says to turn: "un poco" 20, "gira" 90, "mucho" 135, "vuelta" 180, "N grados", else 45."""
    t = " ".join(words)
    for k, v in sorted(DEGREE_WORDS.items(), key=lambda kv: -len(kv[0])):
        if f"{norm(k)} grados" in t:
            return float(v)
    if "vuelta" in words:
        return 180.0
    if "mucho" in words or "muy" in words:
        return 135.0
    if "poco" in words or "poquito" in words:
        return 20.0
    if "gira" in words or "girar" in words:
        return 90.0
    return 45.0
