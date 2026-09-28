"""Language packs: everything wow-voice understands in one spoken language.

Each pack (es.py, en.py) has the order phrases, the number and turn words, the
words that join several orders, the wake words for WoW AI, the Vosk model it
needs, and the few lines wow-voice prints. `commands.set_language()` loads one.
A new language is one more file with the same names.
"""

from __future__ import annotations

import importlib
import os

LANGUAGES = ("es", "en")


def load(code: str):
    if code not in LANGUAGES:
        raise ValueError(f"unknown language {code!r} (have: {', '.join(LANGUAGES)})")
    return importlib.import_module(f".{code}", __name__)


def pick(setting: str = "auto", game_locale: str = "", env: dict | None = None) -> str:
    """"es" / "en" as configured; "auto" follows the game's language (the WoW Voice
    addon saves it: esES, enUS...), then the desktop's ($LANG), then English."""
    if setting in LANGUAGES:
        return setting
    env = os.environ if env is None else env
    for loc in (game_locale or "", env.get("LANG", "")):
        code = loc[:2].lower()
        if code in LANGUAGES:
            return code
    return "en"
