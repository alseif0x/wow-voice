"""Settings: these defaults, overridden by ~/.config/wow-voz/config.json."""

from __future__ import annotations

import json
import os

VENV = os.path.expanduser("~/.local/share/wow-ai-voice")
CONFIG_FILE = os.path.expanduser("~/.config/wow-voz/config.json")

DEFAULTS = {
    # Recognition
    "voskModel": f"{VENV}/vosk/vosk-model-small-es-0.42",
    "whisperModel": "small",
    "whisperFallback": True,
    "device": "cpu",
    # JEV (the same OpenRouter key file the RusticOS pilots and WoW AI use)
    "jevKeyFile": "~/.config/rustic-os/openrouter.env",
    "jevTimeout": 2.5,
    "jevMinConfidence": 0.8,
    "jevMinConfidenceWhisper": 0.9,  # after Whisper (the phrase was already hard to hear)
    # Microphone and phrases
    "recordCommand": ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw"],
    "threshold": 700,
    "silenceMs": 360,
    "maxPhraseMs": 5000,
    # The game
    "savedVariables": "~/Games/battlenet/drive_c/Program Files (x86)/World of Warcraft/_classic_beta_/WTF/Account/*/SavedVariables/WoWVoz.lua",
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
    for k in ("voskModel", "jevKeyFile", "savedVariables", "wowAiListeningFile", "log"):
        if isinstance(cfg.get(k), str):
            cfg[k] = os.path.expanduser(cfg[k])
    return cfg
