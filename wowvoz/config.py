"""Settings: these defaults, overridden by ~/.config/wow-voz/config.json."""

from __future__ import annotations

import json
import os

HOME = os.environ.get("WOWVOZ_HOME") or os.path.expanduser("~/.local/share/wow-voz")  # venv and Vosk models
CONFIG_FILE = os.path.expanduser("~/.config/wow-voz/config.json")

# Where the game keeps the WoW Voz addon's notes (the most recent one found is used).
_WOW = "drive_c/Program Files (x86)/World of Warcraft/_*_/WTF/Account/*/SavedVariables/WoWVoz.lua"
SAVED_VARIABLES = [
    f"~/Games/*/{_WOW}",                                     # Lutris (Battle.net prefix)
    f"~/.wine/{_WOW}",                                       # plain Wine
    f"~/.steam/steam/steamapps/compatdata/*/pfx/{_WOW}",     # Steam / Proton
    f"~/.local/share/Steam/steamapps/compatdata/*/pfx/{_WOW}",
    f"~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata/*/pfx/{_WOW}",
]

DEFAULTS = {
    # Language: "es", "en", or "auto" (the game's language, then the desktop's).
    "language": "auto",
    # Recognition: the Vosk model for the language, from voskDir (or voskModel, a path, to pick one).
    "voskDir": f"{HOME}/vosk",
    "voskModel": "",
    # JEV (optional): OPENROUTER_API_KEY, or a file with an OPENROUTER_API_KEY=... line.
    "jevKeyFile": "~/.config/wow-voz/openrouter.env",
    "jevTimeout": 2.5,
    "jevMinConfidence": 0.8,
    "nearMatch": 0.75,  # how alike Vosk's closed-list guess and its free transcript must sound
    # Microphone and phrases
    "recordCommand": ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw"],
    "threshold": 700,
    "silenceMs": 360,
    "maxPhraseMs": 5000,
    # The game
    "savedVariables": SAVED_VARIABLES,
    "windowName": "^World of Warcraft$",
    "wowAiListeningFile": "~/.cache/wow-ai/listening",
    # How long things last
    "holdSeconds": 1.0,
    "maxHoldSeconds": 5.0,
    "turnDegrees": 45,            # a bare "izquierda" / "derecha"
    "turnDegreesPerSecond": 180,  # WoW's keyboard turn rate
    "jumpInterval": 0.9,
    "maxCount": 5,
    "startPaused": False,
    # Short beeps on the PC's speakers: voice orders on / off, and "paused" when an order is ignored.
    "beeps": True,
    "beepOnOrder": True,  # a tick when an order is pressed, a low buzz when it can't be
    # "oye IA ...": the phrase audio is left here for WoW AI's bridge, then its Talk key is pressed.
    "wowAiHandoff": "~/.cache/wow-ai/voice-in.wav",
    # wow-voz-learn: the agent that reviews misses (text in, JSON out; no tools needed).
    "learnCommand": ["claude", "-p", "--model", "opus", "--effort", "low"],  # or e.g. ["ocx", "claude", "-p", "--model", "gpt-6-sol"]
    "learnTimeout": 240,
    # Follow the WoW Voz addon's on/off button (a marker in the game's top-right corner).
    "gameSwitch": True,
    "playCommand": ["pw-play"],
    "log": "~/.cache/wow-voz/wow-voz.log",
}


def load(path: str = CONFIG_FILE) -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    for k in ("voskDir", "voskModel", "jevKeyFile", "savedVariables", "wowAiListeningFile", "log"):
        if isinstance(cfg.get(k), str):
            cfg[k] = os.path.expanduser(cfg[k])
        elif isinstance(cfg.get(k), list):
            cfg[k] = [os.path.expanduser(v) for v in cfg[k]]
    return cfg
