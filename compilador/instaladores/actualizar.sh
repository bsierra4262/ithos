#!/usr/bin/env bash
# =============================================================================
# ITHOS Gestor — ACTUALIZAR en la VPS (seguro): backup -> traer código -> rebuild
#                 -> verificar salud. Los datos (clientes.json + volumen) PERSISTEN.
# Uso (en la VPS):   bash compilador/instaladores/actualizar.sh
# Requisito previo: correr esto SOLO si las baterías de test pasaron en LOCAL.
#
# El stack de Docker vive en ITHOS/ (docker-compose.yml) y el proyecto de compose se llama
# SIEMPRE 'jarvis-cloud' (así se creó en la VPS): por eso todo se hace con `compose -p`, sin
# depender del nombre de la carpeta. Los .md/tests/compilador quedan fuera del stack.
# =============================================================================
set -e
AZUL='\033[1;34m'; VERDE='\033[1;32m'; ROJO='\033[1;31m'; N='\033[0m'
say(){ echo -e "${AZUL}==>${N} $1"; }
ok(){ echo -e "${VERDE}OK ${N} $1"; }
err(){ echo -e "${ROJO}ERROR${N} $1"; }

cd "$(dirname "$0")/../.."                 # raíz del proyecto (compilador/instaladores/../..)
RAIZ="$(pwd)"; say "Proyecto en: $RAIZ"
PROYECTO="${ITHOS_COMPOSE_PROJECT:-jarvis-cloud}"
COMPOSE=(docker compose -p "$PROYECTO" -f "$RAIZ/ITHOS/docker-compose.yml" --project-directory "$RAIZ/ITHOS")
say "Stack: proyecto '$PROYECTO' con $RAIZ/ITHOS/docker-compose.yml"

# 1) BACKUP de lo crítico ANTES de tocar nada (config + secretos + estado + volumen)
STAMP="$(date +%Y%m%d-%H%M%S)"
BK="/root/ithos-backups/$STAMP"; mkdir -p "$BK"
cp -f ITHOS/central/clientes.json "$BK/" 2>/dev/null || true
cp -f ITHOS/central/cuota_*.json  "$BK/" 2>/dev/null || true
cp -f ITHOS/.env                  "$BK/" 2>/dev/null || true
VOL="$(docker volume ls -q | grep -m1 ithos_data || true)"
if [ -n "$VOL" ]; then
  docker run --rm -v "$VOL":/data -v "$BK":/bk alpine \
    tar czf /bk/ithos_data.tar.gz -C /data . 2>/dev/null || true
fi
ok "Backup en $BK  (config + secretos + volumen de datos)"

# 2) TRAER EL CÓDIGO NUEVO. Con git: pull. Sin git: descomprimí el .tar.gz nuevo ANTES de correr esto.
if [ -d .git ]; then
  say "Trayendo cambios (git pull)..."
  git pull --ff-only
else
  say "Sin git: se asume que ya descomprimiste el paquete nuevo sobre esta carpeta."
  say "  (ITHOS/.env y ITHOS/central/clientes.json NO se pisan: no viajan en el paquete)"
fi

# 2.5) AVISO DE MANTENIMIENTO: le avisamos al cliente por SUS canales (WhatsApp/email/Telegram/...)
#      ANTES de tocar nada; al reconectar su agente se le avisa que ITHOS ya está disponible.
#      Best-effort y OPCIONAL: con ITHOS_SIN_AVISO=1 se saltea (deploys cortos, sin ruido al grupo).
if [ -z "$ITHOS_SIN_AVISO" ]; then
  say "Avisando 'mantenimiento' a los clientes conectados (antes de tocar nada)..."
  if "${COMPOSE[@]}" exec -T central python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/mantenimiento', data=b'', timeout=25)" 2>/dev/null; then
    ok "Aviso de mantenimiento enviado por los canales del cliente"
    sleep 3          # que los mensajes salgan antes de recrear el contenedor
  else
    say "  (no se pudo avisar o no había central corriendo; sigo igual)"
  fi
fi

# 2.6) VERSIÓN del GESTOR: sube sola (control de versiones) en cada deploy.
python3 compilador/build/bump_version.py gestor patch 2>/dev/null && ok "Versión del Gestor actualizada" || true

# 3) REBUILD. Los volúmenes (ithos_data) y clientes.json PERSISTEN: no se pierde nada de los clientes.
say "Reconstruyendo y recreando contenedores..."
"${COMPOSE[@]}" up -d --build

# 4) VERIFICAR SALUD (breve). Si algo no quedó "Up", avisar cómo revertir.
sleep 6
if [ "$("${COMPOSE[@]}" ps --status running -q | wc -l)" -ge 2 ]; then
  ok "Contenedores arriba. Verificá el login del Gestor y que un agente conecte (Conectadas >= 1)."
  echo "   Logs:  docker compose -p $PROYECTO logs -f central panel"
else
  err "Algo no levantó. Revisá:  docker compose -p $PROYECTO logs --tail=80"
  echo "   ROLLBACK:  git checkout <commit-anterior> && bash compilador/instaladores/actualizar.sh"
  echo "   (o restaurá el backup de $BK: clientes.json, .env y ithos_data.tar.gz)"
  exit 1
fi
