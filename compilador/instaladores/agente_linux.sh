#!/usr/bin/env bash
# =============================================================================
# ITHOS Agente - instalador para el equipo del cliente (Linux, parlantes+mic)
# Uso:  sudo bash agente_linux.sh
# Instala dependencias, pide central_url + api_key y crea un servicio systemd
# que arranca el agente al iniciar y se reconecta solo.
# =============================================================================
set -e
cd "$(dirname "$0")/.."
RAIZ="$(pwd)"; AGENTE="$RAIZ/agente"
echo "==> Proyecto en: $RAIZ"

command -v python3 >/dev/null || { echo "Instalando python3..."; apt-get update && apt-get install -y python3 python3-pip; }
# ffmpeg (notas de voz) + portaudio (micrófono, sounddevice) + ODBC SQL Server (IVMS, opcional)
command -v ffmpeg >/dev/null || { echo "Instalando ffmpeg y portaudio..."; apt-get update && apt-get install -y ffmpeg libportaudio2; }
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

# El MODO depende de si el agente habla por los PARLANTES (portero):
#   · PORTERO -> servicio de USUARIO (systemd --user): corre en la sesión del usuario, que TIENE
#     audio (PipeWire/PulseAudio). Un servicio de SISTEMA no tiene audio (como la sesión 0 de Windows).
#   · sin voz -> servicio de sistema (arranca sin que nadie inicie sesión, pero SIN audio).
read -rp "Este equipo habla por los PARLANTES (portero/voz)? [S/n]: " PORTERO
if [ "${PORTERO,,}" = "n" ]; then
  SVC=/etc/systemd/system/ithos-agente.service
  cat > "$SVC" <<EOF
[Unit]
Description=ITHOS Agente
After=network-online.target
[Service]
WorkingDirectory=$AGENTE
ExecStart=$(command -v python3) agente.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now ithos-agente
  echo "OK Servicio de sistema 'ithos-agente' (sin audio; ok si NO hace de portero)."
  echo "   Logs: journalctl -u ithos-agente -f"
else
  UDIR="$HOME/.config/systemd/user"; mkdir -p "$UDIR"
  cat > "$UDIR/ithos-agente.service" <<EOF
[Unit]
Description=ITHOS Agente (portero, con audio)
After=default.target
[Service]
WorkingDirectory=$AGENTE
ExecStart=$(command -v python3) agente.py
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now ithos-agente
  loginctl enable-linger "$USER" 2>/dev/null || true   # sobrevive aunque cierres la sesión gráfica
  echo "OK Servicio de USUARIO 'ithos-agente' (CON audio, para el portero)."
  echo "  IMPORTANTE para que suene tras un corte de luz: activá AUTOLOGIN gráfico de este usuario"
  echo "  (GNOME: Configuración > Usuarios > Inicio de sesión automático). Así: vuelve la luz ->"
  echo "  bootea -> autologin -> sesión con audio -> arranca el portero."
  echo "   Logs: journalctl --user -u ithos-agente -f"
fi
