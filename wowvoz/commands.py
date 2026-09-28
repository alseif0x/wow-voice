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
# Half a turn needs no side: its own order, so JEV isn't torn between left and right.
AROUND = ["media vuelta", "date la vuelta", "da la vuelta", "vuelta", "vuelta completa", "gira totalmente",
          "gira atrás", "gira hacia atrás", "mira atrás", "mira hacia atrás", "date vuelta",
          "gira completamente", "gira del todo", "gira ciento ochenta", "gira ciento ochenta grados", "ciento ochenta grados",
          "giro ciento ochenta", "date media vuelta"]
DEGREE_WORDS = {"diez": 10, "veinte": 20, "treinta": 30, "cuarenta y cinco": 45, "sesenta": 60, "noventa": 90,
                "ciento veinte": 120, "ciento ochenta": 180}

# id -> (binding command or None, how it is done, Spanish phrases, JEV criteria)
INTENTS = {
    "jump":         ("JUMP", "tap", ["salta", "salto", "brinca"], "Jump in place (\"salta\", \"dale un salto\")."),
    # Jumping while moving that way: the direction held a moment, the jump in the middle.
    "jump_left":    ("STRAFELEFT", "jumpmove", ["salta a la izquierda", "salta izquierda", "salto a la izquierda"], "Jump sideways to the left (\"salta a la izquierda\")."),
    "jump_right":   ("STRAFERIGHT", "jumpmove", ["salta a la derecha", "salta derecha", "salto a la derecha"], "Jump sideways to the right (\"salta a la derecha\")."),
    "jump_forward": ("MOVEFORWARD", "jumpmove", ["salta adelante", "salta hacia adelante", "salto adelante"], "Jump forward (\"salta adelante\")."),
    "jump_back":    ("MOVEBACKWARD", "jumpmove", ["salta atrás", "salta hacia atrás", "salto atrás"], "Jump backward (\"salta atrás\")."),
    "forward":      ("MOVEFORWARD", "hold", ["adelante", "avanza", "hacia adelante", "un paso adelante"], "Walk forward for a moment (\"adelante\", \"avanza un poco\")."),
    "back":         ("MOVEBACKWARD", "hold", ["atrás", "retrocede", "hacia atrás", "marcha atrás"], "Walk backward for a moment (\"atrás\", \"retrocede\")."),
    "strafe_left":  ("STRAFELEFT", "hold", ["paso a la izquierda", "de lado a la izquierda", "lateral izquierda", "camina a la izquierda", "camina izquierda", "corre a la izquierda", "corre izquierda", "muévete a la izquierda", "ve a la izquierda"], "Step sideways to the left, without turning (\"paso a la izquierda\")."),
    "strafe_right": ("STRAFERIGHT", "hold", ["paso a la derecha", "de lado a la derecha", "lateral derecha", "camina a la derecha", "camina derecha", "corre a la derecha", "corre derecha", "muévete a la derecha", "ve a la derecha"], "Step sideways to the right, without turning (\"paso a la derecha\")."),
    "turn_left":    ("TURNLEFT", "turn", [p for p, (d, _) in TURNS.items() if d == "left"], "Turn to the left, a little or a lot (\"izquierda\", \"gira a la izquierda\", \"media vuelta\")."),
    "turn_right":   ("TURNRIGHT", "turn", [p for p, (d, _) in TURNS.items() if d == "right"], "Turn to the right, a little or a lot (\"derecha\", \"gira a la derecha\")."),
    "turn_around":  ("TURNLEFT", "turn", AROUND, "Turn around to face the other way, 180 degrees, no side needed (\"media vuelta\", \"gira 180 grados\", \"gira totalmente\")."),
    "autorun":      ("TOGGLEAUTORUN", "tap", ["caminar automático", "camina automático", "correr automático", "automático", "auto", "camina solo", "sigue recto", "todo recto", "sigue adelante", "recto"], "Switch autorun on or off: keep going straight ahead on its own (\"caminar automático\", \"automático\", \"sigue recto\")."),
    "walk":         ("TOGGLERUN", "walkgo", ["andar", "anda", "camina", "caminar", "a caminar", "a andar", "camina lento", "anda despacio", "camina despacio", "ve despacio", "anda lento"], "Walk forward at walking speed, on its own until \"para\" (\"camina\", \"anda\", \"camina despacio\")."),
    "run":          ("TOGGLERUN", "rungo", ["corre", "correr", "a correr", "corre rápido", "camina rápido", "anda rápido"], "Run forward at running speed, on its own until \"para\" (\"corre\", \"correr\", \"camina rápido\")."),
    "slower":       ("TOGGLERUN", "walkmode", ["despacio", "más despacio", "modo andar", "más lento", "lento"], "Slow down to walking speed without starting to move (\"despacio\", \"más despacio\")."),
    "faster":       ("TOGGLERUN", "runmode", ["más rápido", "rápido", "modo correr"], "Speed up to running without starting to move (\"más rápido\", \"rápido\")."),
    "stop":         (None, "stop", ["para", "alto", "quieto", "detente", "stop", "frena"], "Stop moving: stop walking, running or autorun (\"para\", \"alto\")."),
    "target":       ("TARGETNEARESTENEMY", "tap", ["siguiente objetivo", "objetivo", "cambia de objetivo", "otro enemigo"], "Target the next nearest enemy (\"siguiente objetivo\")."),
    "target_friend": ("TARGETNEARESTFRIEND", "tap", ["objetivo amigo", "aliado"], "Target the nearest friendly character."),
    "focus":        ("WOWVOZ_FOCUS", "tap", ["foco", "pon el foco", "marca el foco", "enfoca", "focus", "ponle foco"], "Set the current target as focus (\"pon el foco\", \"focus\")."),
    "target_focus": ("WOWVOZ_TARGETFOCUS", "tap", ["objetivo foco", "selecciona el foco", "apunta al foco", "vuelve al foco", "coge el foco"], "Target the focus again (\"vuelve al foco\")."),
    "focus_friend": ("WOWVOZ_FOCUSFRIEND", "tap", ["focus aliado", "foco aliado", "foco al aliado", "pon el foco en el aliado", "enfoca al aliado"], "Set the nearest friendly character as focus, keeping the current target (\"focus aliado\")."),
    "clear_focus":  ("WOWVOZ_CLEARFOCUS", "tap", ["quita el foco", "borra el foco", "sin foco", "limpia el foco"], "Clear the focus (\"quita el foco\")."),
    "assist_focus": ("WOWVOZ_ASSISTFOCUS", "tap", ["ayuda al foco", "asiste al foco", "objetivo del foco"], "Target what the focus is targeting (\"asiste al foco\")."),
    "assist":       ("ASSISTTARGET", "tap", ["asiste", "objetivo de mi objetivo"], "Assist: target what your target is targeting."),
    "interact":     ("INTERACTTARGET", "tap", ["interactúa", "habla con él", "coge eso", "recoger", "recoge", "coge", "saquea", "saquear", "abre"], "Interact with the target: talk, loot, pick up, open (\"interactúa\", \"recoger\", \"saquea\")."),
    "sit":          ("SITORSTAND", "tap", ["siéntate", "levántate", "sentarse"], "Sit down or stand up."),
    "close":        ("TOGGLEGAMEMENU", "tap", ["cierra", "cerrar", "cierra eso", "cierra la ventana", "escape"], "Close the open window (Escape): \"cierra\", \"cerrar\"."),
    "map":          ("TOGGLEWORLDMAP", "tap", ["mapa", "abre el mapa", "cierra el mapa"], "Open or close the world map."),
    "bags":         ("TOGGLEBACKPACK", "tap", ["bolsas", "abre las bolsas", "mochila"], "Open or close the bags."),
    "ask_ai":       ("WOWAI_TALK", "ask_ai", [], "A question or request for the AI assistant (WoW AI), usually starting with \"oye IA\" (\"oye IA, ¿qué misión hago?\")."),
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
    for w in short_names(buttons):
        out.append(w)
        out.extend(f"{v} {w}" for v in CAST_VERBS)
    out.extend(f"botón {w}" for w in list(NUMBERS)[2:])
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


SPLIT = re.compile(r"\s*(?:,|\by luego\b|\by despues\b|\bluego\b|\bdespues\b|\by\b)\s*")


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
    # "botón tres"
    m = re.fullmatch(r"boton (\w+)", t)
    if m:
        n = NUMBERS.get(m.group(1)) or (int(m.group(1)) if m.group(1).isdigit() else None)
        return Order("button", button={"number": n}, text=text) if n and 1 <= n <= 12 else None
    for p in AROUND:
        if t == norm(p):
            return Order("turn_around", degrees=180.0, text=text)
    if re.fullmatch(r"(?:gira |giro )?180(?: grados)?", t):
        return Order("turn_around", degrees=180.0, text=text)
    for p, (side, deg) in TURNS.items():
        if t == norm(p):
            return Order("turn_left" if side == "left" else "turn_right", degrees=float(deg), text=text)
    m = re.fullmatch(r"(?:gira |giro )?(?:a la |hacia la )?(izquierda|derecha) (\d{1,3})(?: grados)?", t)
    if m and 5 <= int(m.group(2)) <= 180:
        return Order("turn_left" if m.group(1) == "izquierda" else "turn_right", degrees=float(m.group(2)), text=text)
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


HINT_NOTE = (" `closest_order_phrase` is the order phrase the sound was closest to: only a hint about mishearing "
             "(\"gira de echa\" was \"gira a la derecha\"). Ordinary speech always has some closest phrase too, so pick "
             "none when `utterance` is clearly not an order.")


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
    if choice == "jump" and n and "veces" in words:
        o.count = n
    how = INTENTS[choice][1]
    if how == "hold" and n and ("segundos" in words or "segundo" in words):
        o.seconds = float(n)
    if how == "turn":
        o.degrees = 180.0 if choice == "turn_around" else turn_degrees(words)
    return o


def turn_degrees(words: list[str]) -> float:
    """How far a free phrase says to turn: "un poco" 20, "gira" 90, "mucho" 135, "vuelta" 180, "N grados", else 45."""
    t = " ".join(words)
    for w in words:
        if w.isdigit() and 5 <= int(w) <= 180:
            return float(w)
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
