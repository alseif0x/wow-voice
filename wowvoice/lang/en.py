"""English: what is said for each order, and the words around them.

The phrases follow what voice-control profiles for WoW (GameAccess/SpecialEffect's
Gavpi pack, VoiceAttack profiles) and players use: "forward", "strafe left",
"auto run", "next target", "loot", "cast <spell>".
"""

import re

NAME = "English"
VOSK_MODEL = "vosk-model-small-en-us-0.15"

NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
COUNT_WORDS = ["two", "three", "four", "five"]       # "jump three times", "forward two"
TIMES = "times"
TIMES_SPECIAL = {"twice": 2}                         # "jump twice"
SECONDS = {"second", "seconds"}
BUTTON_WORD = "button"
BUTTON_NUMBERS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]
FILLER = {"ok", "okay", "please", "now", "um", "uh", "hey", "so", "well", "just"}
CAST_VERBS = ["cast", "use", "press", "hit"]
CONNECTORS = ["and then", "after that", "then", "and"]

# A bare "left" is a small, natural turn; "turn left" a quarter; "hard left"
# more; "turn around" half. Or "... N degrees".
SIDES = {"left": "left", "right": "right"}
TURNS = {}
for _side, _w in SIDES.items():
    TURNS.update({
        f"a little {_w}": (_side, 20), f"little {_w}": (_side, 20), f"a bit {_w}": (_side, 20), f"slightly {_w}": (_side, 20),
        f"a little to the {_w}": (_side, 20),
        _w: (_side, 45), f"to the {_w}": (_side, 45), f"face {_w}": (_side, 45), f"look {_w}": (_side, 45),
        f"turn {_w}": (_side, 90), f"turn to the {_w}": (_side, 90), f"{_w} turn": (_side, 90),
        f"hard {_w}": (_side, 135), f"sharp {_w}": (_side, 135), f"turn hard {_w}": (_side, 135), f"turn sharp {_w}": (_side, 135),
    })
AROUND = ["turn around", "about face", "one eighty", "turn one eighty", "look behind", "look back", "face the other way",
          "u turn", "turn back", "spin around", "one hundred eighty degrees", "turn one hundred eighty degrees"]
DEGREES = "degrees"
DEGREE_WORDS = {"ten": 10, "twenty": 20, "thirty": 30, "forty five": 45, "sixty": 60, "ninety": 90,
                "one twenty": 120, "one hundred twenty": 120, "one eighty": 180, "one hundred eighty": 180}
TURN_VERBS = ["turn"]
SIDE_PREFIXES = ["to the"]
TURN_DEGREES_PHRASE = "turn {side} {n} degrees"
AMOUNT = {"around": {"around", "behind"}, "much": {"hard", "sharp", "way"}, "little": {"little", "bit", "slightly"},
          "turn": {"turn", "turning"}}

PHRASES = {
    "jump": ["jump", "hop", "jump up"],
    "jump_left": ["jump left", "jump to the left", "hop left"],
    "jump_right": ["jump right", "jump to the right", "hop right"],
    "jump_forward": ["jump forward", "jump ahead", "leap forward"],
    "jump_back": ["jump back", "jump backward", "jump backwards"],
    "forward": ["forward", "forwards", "move forward", "go forward", "move ahead", "step forward", "ahead"],
    "back": ["back", "backward", "backwards", "move back", "go back", "back up", "backpedal", "step back"],
    "strafe_left": ["strafe left", "step left", "sidestep left", "slide left", "move left", "walk left", "run left", "go left"],
    "strafe_right": ["strafe right", "step right", "sidestep right", "slide right", "move right", "walk right", "run right", "go right"],
    "autorun": ["auto run", "autorun", "auto walk", "keep going", "keep moving", "go straight", "straight ahead"],
    "walk": ["walk", "start walking", "walk forward", "walk slowly", "walk slow"],
    "run": ["run", "start running", "run forward", "run fast", "go fast"],
    "slower": ["slow down", "slower", "walk mode", "walking speed", "slow"],
    "faster": ["faster", "speed up", "run mode", "running speed", "fast"],
    "stop": ["stop", "halt", "freeze", "hold up", "stop moving", "stand still"],
    "target": ["next target", "target", "tab", "tab target", "target enemy", "next enemy", "switch target", "change target"],
    "target_friend": ["target friend", "target ally", "friendly target", "next friend"],
    "focus": ["focus", "set focus", "focus target", "mark focus"],
    "target_focus": ["target focus", "select focus", "back to focus", "get focus"],
    "focus_friend": ["focus friend", "focus ally", "focus friendly"],
    "clear_focus": ["clear focus", "remove focus", "drop focus", "no focus"],
    "assist_focus": ["assist focus", "help focus", "target of focus"],
    "assist": ["assist", "assist target", "target of target"],
    "interact": ["interact", "loot", "loot it", "loot all", "loot that", "pick up", "pick it up", "grab", "grab it",
                 "talk", "talk to him", "talk to her", "open", "open it", "gather", "skin"],
    "sit": ["sit", "sit down", "stand up", "stand"],
    "close": ["close", "close it", "close that", "close window", "escape", "cancel"],
    "map": ["map", "open map", "close map", "world map"],
    "bags": ["bags", "bag", "open bags", "backpack", "inventory"],
    "ask_ai": [],
    "pause": ["voice pause", "pause voice", "voice off", "stop listening"],
    "resume": ["voice on", "voice resume", "resume voice", "start listening", "listen up"],
}

# "Hey AI, what quest should I do?": a question for WoW AI. Always with a wake
# word in front: a bare "I ..." starts half of what anybody says.
ASK_AI = re.compile(r"^(?:hey |ok |okay |ask (?:the )?|yo )(?:ai|a i|the ai|assistant)\b(.*)$")
WAKE = ("hey", "ok", "okay", "ask", "yo")
AI_BARE = None
AI_EXAMPLE = "hey AI, what quest should I do?"

NONE_EXAMPLES = ("stop", "jump")
HINT_EXAMPLE = ("turn write", "turn right")

NEVER_LEARN = {"hello", "hi", "yes", "no", "yeah", "okay", "ok", "what", "the", "thanks", "hey", "oh", "um", "uh",
               "well", "so", "nothing", "look", "wait", "sorry"}

CALIBRATE = {
    "quiet": "Quiet for a few seconds, don't speak... (measuring the room's noise)",
    "speak": 'Now say a few times, at your normal volume: "jump", "forward", "left"...',
    "fail": "I can't tell your voice from the noise (noise {noise:.0f}, voice {speech:.0f}). Is the microphone muted or far away?",
    "done": "Noise {noise:.0f}, voice {speech:.0f} -> threshold {threshold} saved in {path}. Restart wow-voice to use it.",
}
