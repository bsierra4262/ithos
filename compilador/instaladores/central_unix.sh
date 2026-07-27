#!/usr/bin/env bash
# =============================================================================
# ITHOS Central - instalador para Linux y macOS (VPS/KVM Linux o Mac con Docker)
# Uso:   sudo bash central_unix.sh       (Linux)
#        bash central_unix.sh            (macOS con Docker Desktop)
# Deja el cerebro corriendo con HTTPS/WSS automatico (Let's Encrypt via Caddy).
# En Windows usá:  central_windows.ps1
# =============================================================================
set -e
AZUL='\033[1;34m'; VERDE='\033[1;32m'; N='\033[0m'
say(){ echo -e "${AZUL}==>${N} $1"; }
ok(){ echo -e "${VERDE}OK ${N} $1"; }

cd "$(dirname "$0")/.."
RAIZ="$(pwd)"; say "Proyecto en: $RAIZ"
SO="$(uname -s)"; say "Sistema: $SO"

# 1) Docker
if ! command -v docker >/dev/null 2>&1; then
  if [ "$SO" = "Darwin" ]; then
    echo "Instalá Docker Desktop para Mac (https://www.docker.com/products/docker-desktop) y reintentá."; exit 1
  fi
  say "Instalando Docker..."; curl -fsSL https://get.docker.com | sh
fi
ok "Docker presente."

# 2) Dominio para HTTPS/WSS
read -rp "Dominio apuntando a este servidor (ej: ithos.tuempresa.com) [enter=solo HTTP]: " DOMINIO
if [ -n "$DOMINIO" ]; then
  sed -i.bak "s/tu-dominio.com/$DOMINIO/g" Caddyfile && rm -f Caddyfile.bak
  ok "Caddyfile listo para https://$DOMINIO  (agentes: wss://$DOMINIO/ws)"
else
  say "Sin dominio: central en http://IP:8080 (agregá dominio luego)."
fi

# 3) clientes.json
if [ ! -f ITHOS/central/clientes.json ]; then
  cp ITHOS/central/clientes.ejemplo.json ITHOS/central/clientes.json 2>/dev/null || echo '{"clientes": []}' > ITHOS/central/clientes.json
  ok "ITHOS/central/clientes.json creado."
fi

# 4) Credenciales del Gestor (.env) — SOLO INTELLIHELP entra al panel superadmin
if [ ! -f .env ]; then
  read -rp "Usuario admin del Gestor [enter=intellihelp]: " ADMIN_USER
  ADMIN_USER="${ADMIN_USER:-intellihelp}"
  read -rp "Contraseña admin [enter=genero una fuerte]: " ADMIN_TOKEN
  if [ -z "$ADMIN_TOKEN" ]; then
    ADMIN_TOKEN="$(openssl rand -base64 24 2>/dev/null || head -c18 /dev/urandom | base64)"
    say "Contraseña generada (guardala): $ADMIN_TOKEN"
  fi
  cat > .env <<EOF
ITHOS_ADMIN_USER=$ADMIN_USER
ITHOS_ADMIN_TOKEN=$ADMIN_TOKEN
ITHOS_DATA=/data
EOF
  chmod 600 .env
  ok ".env creado (permisos 600). Entrás al panel con: $ADMIN_USER / (tu contraseña)."
else
  ok ".env ya existe (no lo piso)."
fi

# 5) Levantar
say "Construyendo y levantando (central + panel + caddy)..."
docker compose up -d --build

IP="$( (hostname -I 2>/dev/null || ipconfig getifaddr en0 2>/dev/null) | awk '{print $1}')"
echo
ok "ITHOS Gestor corriendo."
echo "   • Agente (WSS):  wss://${DOMINIO:-TU-DOMINIO}/ws"
echo "   • Panel (login): https://${DOMINIO:-TU-DOMINIO}/     (SOLO INTELLIHELP)"
echo "   • Alta cliente:  generá el enlace temporal desde el panel (botón de alta)"
echo "   • Logs:          docker compose logs -f central panel"
if [ -z "$DOMINIO" ]; then
  echo "   ⚠ Sin dominio no hay HTTPS: el panel superadmin NO debe quedar en HTTP público."
  echo "     Poné el dominio en el Caddyfile y volvé a levantar antes de usarlo en serio."
fi
