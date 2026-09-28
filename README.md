# wow-voz

Jugar a World of Warcraft (Forever, bajo Wine en Linux) **guiado por la voz**. Dices una orden y se pulsa la tecla que tú pulsarías: "salta", "salta dos veces", "adelante", "atrás", "gira a la derecha", "caminar automático", "para", "siguiente objetivo", "lanza bola de fuego"...

No es un bot ni automatiza nada. **Una orden es una acción**, la que dices, cuando la dices. Nada se repite ni se encadena solo, igual que con el teclado o el mando. Es un módulo aparte de [WoW AI](../wow-ai): funciona sin él y no toca su código.

## Cómo funciona

```
micrófono ──► frase ──► Vosk (lista cerrada + tus alias) ─┐
                    └─► Vosk (libre) ─────────────────────┴─► ¿iguales o casi iguales? ── sí ─► orden (≈50–300 ms)
                                                                     │ no
                                                                     ▼
                         alias · botón por sonido · "oye IA ..." · órdenes combinadas
                                                                     │ no
                                                                     ▼
                         JEV (frase libre + la frase de orden más parecida como pista) ── segura ─► orden (≈0,5 s)
                                                                     │ duda
                                                                     ▼
                                              nada (y se apunta el fallo para aprender)
```

1. **Vosk dos veces a la vez** sobre el mismo audio: con la lista cerrada de órdenes (y tus alias) y en libre. Si dicen lo mismo, o suenan casi igual ("gira de echa" / "gira a la derecha"), es esa orden.
2. **La frase libre** se compara con los alias, con los nombres de tus botones por sonido ("es viscera" → Eviscerar), con "oye IA ..." y con órdenes combinadas ("salta y gira a la derecha": todas o ninguna).
3. **JEV** (el modelo de decisiones de TypeSafe, vía OpenRouter) lee la frase libre, con la frase de orden más parecida como pista, y elige la orden o *ninguna*. Solo actúa con confianza ≥ 0,8. Los números salen de tus palabras, no de JEV.
4. Si no está claro, **no pasa nada**, y el fallo queda apuntado para el aprendizaje.

Whisper ya no se usa, por velocidad; se puede volver a activar con `whisperFallback: true`.

## Aprendizaje de palabras

wow-voz apunta en `~/.cache/wow-voz/misses.jsonl` cada frase que no entendió, y la orden que dijiste justo después (en menos de 6 s), porque la gente repite: "quieres pierda"... "izquierda".

Cada hora, `wow-voz-learn` (un temporizador de systemd) le pasa esos fallos a un agente, por defecto `claude -p --model opus --effort low` (`learnCommand` en la configuración). El agente propone alias. **El propio programa comprueba cada propuesta** y solo la acepta si:
- el fallo fue seguido de esa orden dos veces, o una vez y JEV adivinó lo mismo;
- no es una palabra común ("hola", "vale"...);
- no significa ya otra orden.

Lo aceptado va a `~/.config/wow-voz/learned.json`, que wow-voz recarga solo. Lo que aprendió o rechazó queda en `~/.cache/wow-voz/learn.log`.

**Tus propios alias** van en `~/.config/wow-voz/aliases.json`, que manda sobre los aprendidos:

```json
{ "evis": "button:Eviscerar", "patada": "button:Patada", "gira un pelín": {"order": "turn_right", "degrees": 10} }
```

## Preguntar a la IA

"**Oye IA**, ¿qué misión hago ahora?". wow-voz deja el audio de la frase en `~/.cache/wow-ai/voice-in.wav` y pulsa la tecla de "Hablar" de WoW AI (el addon WoW Voz le asigna una si no tiene). El puente de WoW AI ve el audio reciente, lo transcribe en lugar de grabar, le quita el "oye IA" y lo envía al chat activo.

## Órdenes

| Dices | Hace |
|---|---|
| salta · salta dos/tres veces · brinca | Espacio (hasta 5 veces) |
| adelante · avanza · atrás · retrocede (+ "tres" = 3 s) | W / S un momento (1 s; máximo 5 s) |
| un poco a la izquierda · izquierda · gira a la izquierda · mucho a la izquierda | Gira ~20° · ~45° · ~90° · ~135° (igual a la derecha) |
| media vuelta · gira totalmente · gira 180 grados / gira a la derecha treinta grados | 180° / los grados que digas |
| paso a la izquierda · de lado a la derecha | Q / E (paso lateral, sin girar) |
| caminar automático · automático · sigue recto · todo recto | Bloq Num |
| **correr**: corre · correr · camina rápido · más rápido — **andar**: anda · andar · camina · caminar · despacio | Modo correr / modo andar (pulsa la tecla solo si cambia algo) |
| pon el foco · focus / vuelve al foco / quita el foco / asiste al foco | `/focus` · `/target focus` · `/clearfocus` · `/assist focus` |
| asiste | Objetivo de tu objetivo |
| para · alto · quieto | Suelta todo y corta el caminar automático |
| siguiente objetivo · objetivo amigo | Tab / objetivo aliado |
| interactúa · siéntate · mapa · bolsas | Sus atajos |
| lanza/usa/tira *nombre* · *nombre* · botón *tres* | La tecla del botón donde está ese hechizo, objeto o macro |
| voz pausa · voz activa (activa la voz, empieza) | Deja de obedecer / vuelve a obedecer |
| salta y gira a la derecha, luego adelante | Varias órdenes seguidas (hasta 3; si una no se entiende, ninguna) |
| oye IA, *pregunta* | Se la pasa a WoW AI |

Cualquier otra forma de decirlo pasa por JEV.

**Activar y desactivar:**
- **En el juego:** el botón **Voz: ON / OFF** del addon (clic; Mayús + arrastrar para moverlo), `/wowvoz`, o un atajo en *Opciones > Atajos > WoW Voz*. El addon pinta un cuadrado de 8 píxeles en la esquina superior derecha (magenta = activo, cian = apagado) y wow-voz lo lee de la ventana del juego dos veces por segundo.
- **Fuera:** `wow-voz-toggle`, para asignarlo a un atajo del escritorio.
- **Por voz:** "voz pausa" / "voz activa".

**Pitidos** (por los altavoces del PC):
- ascendente: al arrancar o al decir "voz activa";
- descendente: al pausar;
- dos graves: has dado una orden estando en pausa;
- un tic: orden pulsada;
- un zumbido: la orden no tiene tecla, o WoW no es la ventana activa.

**Seguros:**
- Nada se pulsa si WoW no es la ventana activa.
- Lo que se mantiene pulsado tiene un máximo de tiempo.
- "Para" corta al instante lo que esté en marcha.
- Mientras el botón **Hablar** de WoW AI está grabando, lo que dices es para la IA y no se toma como orden.

## Uso

```bash
cd ~/projects/programs/wow-voz
P=~/.local/share/wow-ai-voice/bin/python
$P -m wowvoz --keys            # qué tecla hace cada cosa (atajos del addon o por defecto)
$P -m wowvoz --say "dale un salto"   # qué haría una frase, sin micrófono ni teclas
$P -m wowvoz --dry-run         # escucha y dice qué pulsaría, sin pulsar
$P -m wowvoz --calibrar        # mide el ruido y tu voz, y ajusta el umbral del micrófono
$P -m wowvoz.learn             # aprender ahora de los fallos (lo mismo que el temporizador)
$P -m wowvoz                   # a jugar
systemctl --user start wow-voz # como servicio (arranca activo; "voz pausa" / "voz activa")
journalctl --user -u wow-voz -f   # lo que oye y hace
```

Configuración: `~/.config/wow-voz/config.json`, sobre los valores de `wowvoz/config.py`. Por ejemplo, `threshold` (volumen mínimo que cuenta como voz), `holdSeconds`, `jevMinConfidence` o `startPaused`.

## Instalación

Usa el mismo entorno de Python que la voz de WoW AI (`~/.local/share/wow-ai-voice`, con faster-whisper), más Vosk y su modelo en español:

```bash
~/.local/share/wow-ai-voice/bin/pip install vosk
cd ~/.local/share/wow-ai-voice && mkdir -p vosk && cd vosk
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip && unzip vosk-model-small-es-0.42.zip
cp -r addon/WoWVoz ".../World of Warcraft/_classic_beta_/Interface/AddOns/"   # y reinicia el juego
cp systemd/wow-voz.service ~/.config/systemd/user/ && systemctl --user daemon-reload
```

`/dev/uinput` tiene que ser accesible para tu usuario. La regla de udev de Sunshine (`60-sunshine.rules`, `TAG+="uaccess"`) ya lo hace.

La clave de JEV: `OPENROUTER_API_KEY`, o la línea `OPENROUTER_API_KEY=...` de `~/.config/rustic-os/openrouter.env`.

## Límites

- **El micrófono tiene que estar en el PC.** Moonlight no envía el micrófono del cliente.
- **Las barras que cambian** (sigilo, formas, montura) cambian lo que hay en cada tecla. wow-voz pulsa la tecla del botón donde el addon vio ese hechizo por última vez.
- **Los atajos que solo están en el mando o el ratón** no se pueden pulsar desde el teclado. Asígnales también una tecla en WoW.
- **Las normas de Blizzard** prohíben la automatización (bots, una pulsación que hace varias acciones). wow-voz es una orden = una tecla, como remapear teclas o las herramientas de voz de accesibilidad, pero no hay un texto oficial que lo permita expresamente. Úsalo sabiéndolo.

## Pruebas

```bash
~/.local/share/wow-ai-voice/bin/python -m unittest discover -s tests -v
```
