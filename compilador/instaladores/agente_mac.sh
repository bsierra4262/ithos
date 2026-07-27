#!/usr/bin/env bash
# =============================================================================
# ITHOS Agente - instalador para macOS (equipo del cliente con parlantes+mic)
# Uso:  bash agente_mac.sh
# Instala dependencias, pide central_url + api_key y crea un LaunchAgent que
# arranca el agente al iniciar sesion y se reconecta solo.
# =============================================================================
set -e
cd "$(dirname "$0")/.."
RAIZ="$(pwd)"; AGENTE="$RAIZ/agente"
echo "==> Proyecto en: $RAIZ"

command -v python3 >/dev/null || { echo "Instalá Python 3 (https://www.python.org/downloads/macos/) y reintentá."; exit 1; }
# ffmpeg (notas de voz) + portaudio (micrófono) via Homebrew, si está.
command -v ffmpeg >/dev/null || { command -v brew >/dev/null && { echo "Instalando ffmpeg y portaudio..."; brew install ffmpeg portaudio; } || echo "Instalá ffmpeg a mano si usás notas de voz."; }
echo "==> Instalando dependencias..."
pip3 install -r "$AGENTE/requirements.txt"

read -rp "URL del Central (ej: wss://ithos.tuempresa.com/ws): " URL
read -rp "API key del agente (te la da el panel /alta): " APIKEY
python3 - "$AGENTE/config.json" "$URL" "$APIKEY" <<'PY'
import json,sys
p,url,key=sys.argv[1],sys.argv[2],sys.argv[3]
try: c=json.load(open(p))
except Exception: c={}
if url: c["central_url"]=url
if key: c["api_key"]=key
json.dump(c,open(p,"w"),ensure_ascii=False,indent=2)
print("OK config.json actualizado.")
PY

PLIST="$HOME/Library/LaunchAgents/com.ithos.agente.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.ithos.agente</string>
  <key>ProgramArguments</key>
  <array><string>$(command -v python3)</string><string>$AGENTE/agente.py</string></array>
  <key>WorkingDirectory</key><string>$AGENTE</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "OK LaunchAgent 'com.ithos.agente' cargado (arranca solo, se reconecta)."
echo "   Ver:     launchctl list | grep ithos"
echo "   Detener: launchctl unload $PLIST"
