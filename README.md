# wow-voz

Jugar a World of Warcraft (Forever, bajo Wine en Linux) **guiado por la voz**. Dices una orden y se pulsa la tecla que tú pulsarías: "salta", "salta dos veces", "adelante", "atrás", "gira a la derecha", "caminar automático", "para", "siguiente objetivo", "lanza bola de fuego"...

No es un bot ni automatiza nada. **Una orden es una acción**, la que dices, cuando la dices. Nada se repite ni se encadena solo, igual que con el teclado o el mando. Es un módulo aparte de [WoW AI](../wow-ai): funciona sin él y no toca su código.

## Cómo funciona

```
micrófono ──► frase ──► Vosk (lista cerrada) ─┐
                    └─► Vosk (libre) ─────────┴─► ¿coinciden? ── sí ─► orden (≈0,3 s)
                                                        │ no
                                                        ▼
                                       JEV: ¿qué orden querías decir? ── segura ─► orden (≈0,6 s)
                                                        │ duda
                                                        ▼
                                       Whisper (mejor transcripción) ─► JEV ─► orden, o nada
                                                                                   │
                     teclado virtual (/dev/uinput) ◄── solo si WoW es la ventana activa
```

1. **Vosk dos veces a la vez** sobre el mismo audio: con la lista cerrada de órdenes (responde siempre con una de ellas) y en libre (lo que dijiste de verdad). Si coinciden, es una orden exacta, en unos 30–300 ms.
2. **JEV** (el modelo de decisiones de TypeSafe, vía OpenRouter) lee la frase libre y elige la orden, o *ninguna*. "Dale un salto" → saltar; "muévete un poquito hacia delante" → adelante; "oye, ¿qué hora es?" → nada. Los números los saca wow-voz de tus palabras, no JEV, porque contar no es lo suyo.
3. Si JEV duda (confianza < 0,8), **Whisper** transcribe mejor y JEV decide otra vez. Si sigue sin estar claro, **no pasa nada**: hablar con alguien de la habitación no mueve al personaje.

**Teclas.** El teclado virtual es un dispositivo `/dev/uinput`, igual que el mando virtual de Sunshine. El escritorio lo trata como un teclado más y las teclas van a la ventana activa. Las teclas se resuelven con tu distribución de teclado, así que "-" o "º" caen donde tu teclado español los tiene.

**Qué tecla hace qué.** El addon **WoW Voz** (`addon/WoWVoz`) solo lee: apunta tus atajos reales (moverse, saltar, caminar automático, objetivo...) y qué hechizo, objeto o macro hay en cada botón de las barras, con su tecla. El juego lo guarda en disco al hacer `/reload` o al salir, y wow-voz lo recarga solo. Sin él se usan las teclas por defecto de WoW (W A S D Q E, Espacio, Bloq Num, Tab, 1–0 - =).

## Órdenes

| Dices | Hace |
|---|---|
| salta · salta dos/tres veces · brinca | Espacio (hasta 5 veces) |
| adelante · avanza · atrás · retrocede (+ "tres" = 3 s) | W / S un momento (1 s; máximo 5 s) |
| a la izquierda · a la derecha | Q / E (paso lateral) |
| gira a la izquierda/derecha · media vuelta | A / D medio segundo / un segundo |
| corre · caminar automático | Bloq Num |
| para · alto · quieto | Suelta todo y corta el caminar automático |
| siguiente objetivo · objetivo amigo | Tab / objetivo aliado |
| interactúa · siéntate · mapa · bolsas | Sus atajos |
| lanza/usa/tira *nombre* · *nombre* · botón *tres* | La tecla del botón donde está ese hechizo, objeto o macro |
| voz pausa · voz activa (activa la voz, empieza) | Deja de obedecer / vuelve a obedecer |

Cualquier otra forma de decirlo pasa por JEV.

**Pitidos** (por los altavoces del PC): uno ascendente al arrancar o al decir "voz activa", uno descendente al pausar, y dos pitidos graves si das una orden estando en pausa.

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
