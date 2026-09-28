"""Español: lo que se dice para cada orden, y las palabras que las acompañan."""

import re

NAME = "Spanish"
VOSK_MODEL = "vosk-model-small-es-0.42"

NUMBERS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
           "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12}
COUNT_WORDS = ["dos", "tres", "cuatro", "cinco"]     # "salta dos veces", "adelante tres"
TIMES = "veces"
TIMES_SPECIAL: dict[str, int] = {}                   # (English has "twice")
SECONDS = {"segundo", "segundos"}
BUTTON_WORD = "botón"
BUTTON_NUMBERS = ["uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce"]
FILLER = {"vale", "venga", "eh", "porfa", "ya", "ahora", "oye", "bueno"}
CAST_VERBS = ["lanza", "usa", "tira", "activa"]
# Several orders in one breath: "salta y gira a la derecha, luego adelante".
CONNECTORS = ["y luego", "y despues", "luego", "despues", "y"]

# Turning, by how much: a bare "izquierda" is a small, natural turn; "gira" a
# quarter; "mucho" more; "media vuelta" half. Or "... N grados".
SIDES = {"left": "izquierda", "right": "derecha"}
TURNS = {}
for _side, _w in SIDES.items():
    TURNS.update({
        f"un poco a la {_w}": (_side, 20), f"un poco {_w}": (_side, 20), f"poquito a la {_w}": (_side, 20),
        _w: (_side, 45), f"a la {_w}": (_side, 45), f"hacia la {_w}": (_side, 45),
        f"gira a la {_w}": (_side, 90), f"gira {_w}": (_side, 90), f"gira hacia la {_w}": (_side, 90),
        f"mucho a la {_w}": (_side, 135), f"gira mucho a la {_w}": (_side, 135), f"muy a la {_w}": (_side, 135),
    })
AROUND = ["media vuelta", "date la vuelta", "da la vuelta", "vuelta", "vuelta completa", "gira totalmente",
          "gira atrás", "gira hacia atrás", "mira atrás", "mira hacia atrás", "date vuelta",
          "gira completamente", "gira del todo", "gira ciento ochenta", "gira ciento ochenta grados", "ciento ochenta grados",
          "giro ciento ochenta", "date media vuelta"]
DEGREES = "grados"
DEGREE_WORDS = {"diez": 10, "veinte": 20, "treinta": 30, "cuarenta y cinco": 45, "sesenta": 60, "noventa": 90,
                "ciento veinte": 120, "ciento ochenta": 180}
TURN_VERBS = ["gira", "giro"]
SIDE_PREFIXES = ["a la", "hacia la"]
TURN_DEGREES_PHRASE = "gira a la {side} {n} grados"
# How far a free phrase says to turn (JEV picked the side).
AMOUNT = {"around": {"vuelta"}, "much": {"mucho", "muy"}, "little": {"poco", "poquito"}, "turn": {"gira", "girar"}}

PHRASES = {
    "jump": ["salta", "salto", "brinca"],
    "jump_left": ["salta a la izquierda", "salta izquierda", "salto a la izquierda"],
    "jump_right": ["salta a la derecha", "salta derecha", "salto a la derecha"],
    "jump_forward": ["salta adelante", "salta hacia adelante", "salto adelante"],
    "jump_back": ["salta atrás", "salta hacia atrás", "salto atrás"],
    "forward": ["adelante", "avanza", "hacia adelante", "un paso adelante"],
    "back": ["atrás", "retrocede", "hacia atrás", "marcha atrás"],
    "strafe_left": ["paso a la izquierda", "de lado a la izquierda", "lateral izquierda", "camina a la izquierda", "camina izquierda",
                    "corre a la izquierda", "corre izquierda", "muévete a la izquierda", "ve a la izquierda"],
    "strafe_right": ["paso a la derecha", "de lado a la derecha", "lateral derecha", "camina a la derecha", "camina derecha",
                     "corre a la derecha", "corre derecha", "muévete a la derecha", "ve a la derecha"],
    "autorun": ["caminar automático", "camina automático", "correr automático", "automático", "auto", "camina solo",
                "sigue recto", "todo recto", "sigue adelante", "recto"],
    "walk": ["andar", "anda", "camina", "caminar", "a caminar", "a andar", "camina lento", "anda despacio", "camina despacio",
             "ve despacio", "anda lento"],
    "run": ["corre", "correr", "a correr", "corre rápido", "camina rápido", "anda rápido"],
    "slower": ["despacio", "más despacio", "modo andar", "más lento", "lento"],
    "faster": ["más rápido", "rápido", "modo correr"],
    "stop": ["para", "alto", "quieto", "detente", "stop", "frena"],
    "target": ["siguiente objetivo", "objetivo", "cambia de objetivo", "otro enemigo"],
    "target_friend": ["objetivo amigo", "aliado"],
    "focus": ["foco", "pon el foco", "marca el foco", "enfoca", "focus", "ponle foco"],
    "target_focus": ["objetivo foco", "selecciona el foco", "apunta al foco", "vuelve al foco", "coge el foco"],
    "focus_friend": ["focus aliado", "foco aliado", "foco al aliado", "pon el foco en el aliado", "enfoca al aliado"],
    "clear_focus": ["quita el foco", "borra el foco", "sin foco", "limpia el foco"],
    "assist_focus": ["ayuda al foco", "asiste al foco", "objetivo del foco"],
    "assist": ["asiste", "objetivo de mi objetivo"],
    "interact": ["interactúa", "habla con él", "coge eso", "recoger", "recoge", "coge", "saquea", "saquear", "abre",
                 "despojar", "despoja", "despojo", "botín", "recoger botín", "coge el botín", "recoger todo", "recoge todo", "coge todo"],
    "sit": ["siéntate", "levántate", "sentarse"],
    "close": ["cierra", "cerrar", "cierra eso", "cierra la ventana", "escape"],
    "map": ["mapa", "abre el mapa", "cierra el mapa"],
    "bags": ["bolsas", "abre las bolsas", "mochila"],
    "ask_ai": [],
    "pause": ["voz pausa", "pausa voz", "pausa la voz", "deja de escuchar"],
    "resume": ["voz activa", "activa voz", "activa la voz", "escúchame", "empieza"],
}

# "Oye IA, ¿qué misión hago?": a question for WoW AI. Without "oye" in front,
# only a literal "ia" and a real question ("y a la derecha" sounds like "IA la derecha").
ASK_AI = re.compile(r"^(?:oye |eh |hey |ey |pregunta(?:le)? a la |dile a la |oiga )?(?:ia|i a|y a|la ia|inteligencia artificial|asistente)\b(.*)$")
WAKE = ("oye", "eh", "hey", "ey", "pregunta", "dile", "oiga")
AI_BARE = "ia"
AI_EXAMPLE = "oye IA, ¿qué misión hago?"

# For JEV's criteria: words that are orders but also ordinary speech, and a mishearing.
NONE_EXAMPLES = ("para", "salta")
HINT_EXAMPLE = ('gira de echa', 'gira a la derecha')

# Never learned as an alias (wow-voz-learn): everyday words.
NEVER_LEARN = {"hola", "si", "no", "vale", "bueno", "que", "eh", "ah", "oye", "venga", "gracias", "adios", "nada", "ya", "mira"}

CALIBRATE = {
    "quiet": "Silencio unos segundos, sin hablar... (midiendo el ruido de la habitación)",
    "speak": 'Ahora di varias veces, a tu volumen normal: "salta", "adelante", "izquierda"...',
    "fail": "No distingo tu voz del ruido (ruido {noise:.0f}, voz {speech:.0f}). ¿El micrófono está silenciado o lejos?",
    "done": "Ruido {noise:.0f}, voz {speech:.0f} -> umbral {threshold} guardado en {path}. Reinicia wow-voz para usarlo.",
}
