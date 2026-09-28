#!/usr/bin/env bash
# wow-voice installer for Linux and macOS (Windows: install.ps1): a Python venv with
# Vosk, the Vosk models, the WoW Voice addon, and on Linux the systemd user units.
# Safe to run again (it only adds what is missing).
#
#   ./install.sh                      Spanish and English models, addon found automatically
#   ./install.sh --lang en            English model only
#   ./install.sh --addons "<.../World of Warcraft/_classic_beta_/Interface/AddOns>"
#   ./install.sh --no-systemd         no services (run it by hand: see the README)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(uname -s)" = Darwin ]; then HOME_DIR="${WOWVOICE_HOME:-$HOME/Library/Application Support/wow-voice}"
else HOME_DIR="${WOWVOICE_HOME:-$HOME/.local/share/wow-voice}"; fi
LANGS="es en"
ADDONS=""
SYSTEMD=1

while [ $# -gt 0 ]; do
	case "$1" in
		--lang) LANGS="$2"; shift 2 ;;
		--addons) ADDONS="$2"; shift 2 ;;
		--no-systemd) SYSTEMD=0; shift ;;
		-h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
		*) echo "unknown option: $1 (see --help)"; exit 2 ;;
	esac
done

OS="$(uname -s)"
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

# 1. What wow-voice runs on.
missing=()
needs="python3 curl unzip"
[ "$OS" = Linux ] && needs="$needs arecord xprop"
for c in $needs; do command -v "$c" >/dev/null || missing+=("$c"); done
if [ ${#missing[@]} -gt 0 ]; then
	warn "missing: ${missing[*]}"
	echo "   Debian/Ubuntu: sudo apt install python3-venv alsa-utils x11-utils curl unzip"
	echo "   Fedora:        sudo dnf install python3 alsa-utils xprop curl unzip"
	echo "   Arch:          sudo pacman -S python alsa-utils xorg-xprop curl unzip"
	echo "   macOS:         brew install python   (curl and unzip come with macOS)"
	exit 1
fi
if [ "$OS" = Linux ] && ! command -v pw-play >/dev/null && ! command -v paplay >/dev/null && ! command -v aplay >/dev/null; then
	warn "no sound player (pw-play, paplay, aplay): no beeps."
fi

# 2. Python and Vosk.
say "Python venv in $HOME_DIR/venv"
mkdir -p "$HOME_DIR/vosk"
[ -x "$HOME_DIR/venv/bin/python" ] || python3 -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/pip" install -q --upgrade pip
"$HOME_DIR/venv/bin/pip" install -q -r "$REPO/requirements.txt"

# 3. The speech models (about 40 MB each).
for l in $LANGS; do
	case "$l" in
		es) model=vosk-model-small-es-0.42 ;;
		en) model=vosk-model-small-en-us-0.15 ;;
		*) warn "no model for language '$l' (es, en)"; continue ;;
	esac
	if [ -d "$HOME_DIR/vosk/$model" ]; then
		say "Vosk model $model: already there"
	else
		say "Downloading the Vosk model $model"
		curl -fL --progress-bar -o "$HOME_DIR/vosk/$model.zip" "https://alphacephei.com/vosk/models/$model.zip"
		unzip -q "$HOME_DIR/vosk/$model.zip" -d "$HOME_DIR/vosk" && rm "$HOME_DIR/vosk/$model.zip"
	fi
done

# 4. The addon, into the game's AddOns folder.
if [ -z "$ADDONS" ]; then
	found=()
	for base in "$HOME"/Games/* "$HOME/.wine" "$HOME"/.steam/steam/steamapps/compatdata/*/pfx \
		"$HOME"/.local/share/Steam/steamapps/compatdata/*/pfx; do
		for d in "$base"/drive_c/"Program Files (x86)"/"World of Warcraft"/_*_/Interface/AddOns; do
			[ -d "$d" ] && found+=("$d")
		done
	done
	for d in "/Applications/World of Warcraft"/_*_/Interface/AddOns; do
		[ -d "$d" ] && found+=("$d")
	done
	if [ ${#found[@]} -eq 1 ]; then
		ADDONS="${found[0]}"
	elif [ ${#found[@]} -gt 1 ]; then
		warn "several WoW installs; pick one with --addons:"
		printf '     %s\n' "${found[@]}"
	else
		warn "WoW's AddOns folder not found; copy addon/WoWVoice there yourself, or use --addons"
	fi
fi
if [ -n "$ADDONS" ]; then
	say "Addon WoW Voice -> $ADDONS"
	mkdir -p "$ADDONS"
	cp -r "$REPO/addon/WoWVoice" "$ADDONS/"
	echo "   Restart the game (a new addon is only found at start), then /reload once in game."
fi

# 5. Permission to press keys: /dev/uinput on Linux, Accessibility on macOS.
if [ "$OS" = Darwin ]; then
	warn "macOS: allow your terminal (or Python) in System Settings > Privacy & Security > Accessibility"
	echo "   (to press keys) and Screen Recording (for the in-game on/off button), and Microphone."
elif [ ! -w /dev/uinput ]; then
	warn "/dev/uinput is not writable for you: wow-voice can't press keys yet. One way:"
	echo '   echo '\''KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"'\'' | sudo tee /etc/udev/rules.d/60-wow-voice-uinput.rules'
	echo '   sudo udevadm control --reload && sudo udevadm trigger && sudo modprobe uinput   (then log out and in)'
fi

# 6. Services and the toggle command.
if [ "$OS" = Linux ]; then
	mkdir -p "$HOME/.local/bin"
	ln -sf "$REPO/bin/wow-voice-toggle" "$HOME/.local/bin/wow-voice-toggle"
fi
if [ "$OS" = Linux ] && [ "$SYSTEMD" = 1 ] && command -v systemctl >/dev/null; then
	say "systemd user units"
	mkdir -p "$HOME/.config/systemd/user"
	for f in "$REPO"/systemd/*.in; do
		sed -e "s|@REPO@|$REPO|g" -e "s|@PYTHON@|$HOME_DIR/venv/bin/python|g" "$f" > "$HOME/.config/systemd/user/$(basename "${f%.in}")"
	done
	systemctl --user daemon-reload
fi

cat <<EOF

$(say "Done.")
   Start:        systemctl --user start wow-voice   (Linux)   or: cd "$REPO" && "$HOME_DIR/venv/bin/python" -m wowvoice
   Watch it:     journalctl --user -u wow-voice -f   (Linux)   or the terminal it runs in
   Try a phrase: cd "$REPO" && "$HOME_DIR/venv/bin/python" -m wowvoice --say "jump twice" --lang en
   Optional:     JEV (understands free phrasing): put OPENROUTER_API_KEY=... in ~/.config/wow-voice/openrouter.env
                 learning from misses (needs the claude CLI): systemctl --user enable --now wow-voice-learn.timer
EOF
