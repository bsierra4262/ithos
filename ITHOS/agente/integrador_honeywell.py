#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrador Honeywell (agente) — Pro-Watch API Service (REST). Consulta los eventos de
acceso y manda evento "acceso" al central por cada uno nuevo.

Pro-Watch API Service expone REST/SignalR (puertos por defecto 8734/8735). Autenticación
por Basic auth PRE-EMPTIVA con un usuario de Pro-Watch que tenga habilitada la "Web
password". (Ref.: Honeywell Pro-Watch API Service Integration Guide.)

Config (agente/config.json -> integrador):
  {"tipo":"honeywell","host":"https://IP:8734","usuario":"...","password":"...",
   "eventos_path":"/api/Events","poll_interval":3, "verify_ssl": false}
Compat: si se pasa "auth":"bearer" y "api_key", usa Bearer en vez de Basic.
La API de Honeywell varía entre versiones/on-prem; endpoint y campos son configurables.
"""

import ssl
import time
import json
import base64
import logging
import urllib.request

log = logging.getLogger("integrador.honeywell")


def _ctx(verify):
    if verify:
        return None
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _headers(cfg):
    if (cfg.get("auth") or "basic").lower() == "bearer":
        return {"Authorization": f"Bearer {cfg.get('api_key', '')}",
                "Content-Type": "application/json"}
    tok = base64.b64encode(f"{cfg.get('usuario', '')}:{cfg.get('password', '')}".encode()).decode()
    return {"Authorization": "Basic " + tok, "Content-Type": "application/json"}


def _mapear(ev):
    nombre = str(ev.get("CardholderName") or ev.get("cardholderName")
                 or ev.get("personName") or "").strip()
    device = str(ev.get("ReaderName") or ev.get("readerName") or ev.get("doorName") or "").strip()
    dev = device.lower()
    desc = str(ev.get("EventDescription") or ev.get("description") or "").lower()
    granted = "grant" in desc or "valid" in desc or bool(nombre)
    denied = "deni" in desc or "invalid" in desc
    if "sala tecnica" in dev:
        tipo = "sala"
    elif denied or not nombre or not granted:
        tipo = "alerta"
    else:
        tipo = "bienvenida"
    clave = f"{ev.get('EventId') or ev.get('id') or ev.get('Timestamp')}"
    # El CENTRAL clasifica por 'device' según la config del cliente (thin agent); 'tipo' va de respaldo.
    return clave, {"nombre": nombre, "device": device, "es_fallo": tipo == "alerta", "tipo": tipo}


def vigilar(cfg, enviar_evento, stop=None):
    host = cfg["host"].rstrip("/")
    path = cfg.get("eventos_path", "/api/Events")
    intervalo = cfg.get("poll_interval", 3)
    verify = cfg.get("verify_ssl", False)
    vistos, baseline = set(), False
    log.info("Honeywell Pro-Watch integrador iniciado (%s).", host)
    while stop is None or not stop.is_set():
        try:
            req = urllib.request.Request(f"{host}{path}?limit=50", headers=_headers(cfg))
            with urllib.request.urlopen(req, timeout=20, context=_ctx(verify)) as r:
                d = json.loads(r.read().decode() or "{}")
            eventos = d.get("events") or d.get("Events") or d.get("value") or d.get("data") or []
            if not baseline:
                for ev in eventos:
                    vistos.add(_mapear(ev)[0])
                baseline = True
                log.info("Honeywell baseline: %d eventos.", len(vistos))
            else:
                for ev in reversed(eventos):
                    clave, datos = _mapear(ev)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    enviar_evento({"evento": "acceso", "datos": datos})
        except Exception as e:  # noqa: BLE001
            log.warning("Honeywell error: %s", e)
        time.sleep(intervalo)
