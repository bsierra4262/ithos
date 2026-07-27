#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocolo de mensajes ITHOS (JSON sobre WebSocket) entre el Central (cerebro en
la nube) y los Agentes (instalados en cada cliente).

El Central nunca toca hardware: recibe EVENTOS de los agentes y devuelve COMANDOS.
"""

# --- Tipos de mensaje ---
# Agente -> Central
AUTH = "auth"          # {"tipo": AUTH, "api_key": "..."}
EVENTO = "evento"      # {"tipo": EVENTO, "evento": <EV_*>, "datos": {...}}
PONG = "pong"

# Central -> Agente
AUTH_OK = "auth_ok"    # {"tipo": AUTH_OK, "cliente": "...", "config": {...}}
AUTH_ERROR = "auth_error"
COMANDO = "comando"    # {"tipo": COMANDO, "accion": <AC_*>, ...}
PING = "ping"

# --- Eventos (agente -> central) ---
EV_ACCESO = "acceso"   # fichaje: {"nombre","device","es_fallo"[,"tipo" compat]}. El CENTRAL clasifica
#   la terminal (entrada/salida/sala) por 'device' según la config del cliente (thin agent).
EV_TICKET = "ticket"   # ticket nuevo detectado por el agente (opcional)
EV_TERMINALES = "terminales_descubiertos"  # el agente DESCUBRE las terminales del cliente y las lista
#   para que las mapee desde el panel: {"terminales": ["Puerta Principal", "Sala Tecnica", ...]}
EV_ESTADO = "estado_agente"   # el agente reporta su salud para el dashboard: {"microfono":bool,
#   "integrador":bool, "integrador_tipo":str, "voz":bool}. El gestor lo combina con el estado de los
#   canales (WhatsApp/email/...) -> en producción TODO debe estar activo.
EV_CONSULTA_VOZ = "consulta_voz"  # el usuario habló ("ITHOS, ...") o mandó un audio:
#   datos {"audio_b64": "...", "mime": "audio/wav"} o {"texto": "..."}
EV_PRECACHE = "precache_acceso"   # el agente pide PRE-CACHEAR saludos de personas conocidas
#   (del baseline del integrador): {"nombres": ["Facundo Monaco", ...]}. El central devuelve los
#   textos de saludo para que el agente los genere y cachee -> la 1ª fichada es INSTANTÁNEA.

# --- Acciones (central -> agente) ---
AC_DECIR = "decir"        # reproducir voz: {"texto","cachear"[,"solo_cachear"]}. Con solo_cachear=True
#   el agente GENERA y CACHEA el audio pero NO lo reproduce (pre-cacheo en segundo plano).
AC_WHATSAPP = "whatsapp"  # postear a WhatsApp (si el agente lo maneja localmente)


def comando(accion, **datos):
    return {"tipo": COMANDO, "accion": accion, **datos}
