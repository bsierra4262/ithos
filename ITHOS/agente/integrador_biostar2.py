#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrador BioStar 2 (agente) — API REST de Suprema BioStar 2. Loguea, consulta el
log de eventos de acceso y manda un evento "acceso" al central por cada uno nuevo.

Auth: POST /api/login {"User":{"login_id","password"}} -> header 'bs-session-id'.
Config (agente/config.json -> integrador):
  {"tipo":"biostar2","host":"https://IP:443","login_id":"admin","password":"...",
   "poll_interval":3, "verify_ssl": false}

NOTA: probar/ajustar con el BioStar 2 real del cliente (los nombres de campos del
evento pueden variar según versión).
"""

import ssl
import json
import time
import logging
import urllib.request

log = logging.getLogger("integrador.biostar2")


def _ctx(verify):
    if verify:
        return None
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _req(host, path, method="GET", data=None, session=None, verify=False):
    headers = {"Content-Type": "application/json"}
    if session:
        headers["bs-session-id"] = session
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(host.rstrip("/") + path, data=body,
                                 headers=headers, method=method)
    resp = urllib.request.urlopen(req, timeout=20, context=_ctx(verify))
    return resp, json.loads(resp.read().decode() or "{}")


def _login(host, login_id, password, verify):
    resp, _ = _req(host, "/api/login", "POST",
                   {"User": {"login_id": login_id, "password": password}}, verify=verify)
    return resp.headers.get("bs-session-id")


def _mapear(ev):
    usr = ev.get("user") or {}
    nombre = str(usr.get("name") or ev.get("user_id") or "").strip()
    device = str((ev.get("device") or {}).get("name") or "").strip()   # nombre del lector/puerta
    dev = device.lower()
    # event_type_id de "acceso concedido" vs denegado varía; heurística simple:
    concedido = "grant" in str(ev.get("event_type_id") or "").lower() or bool(nombre)
    if "sala tecnica" in dev:
        tipo = "sala"
    elif not concedido or not nombre:
        tipo = "alerta"
    else:
        tipo = "bienvenida"
    # El CENTRAL clasifica por 'device' según la config del cliente (thin agent); 'tipo' va de respaldo.
    return f"{ev.get('id') or ev.get('datetime')}", {
        "nombre": nombre, "device": device, "es_fallo": tipo == "alerta", "tipo": tipo}


def vigilar(cfg, enviar_evento, stop=None):
    host = cfg["host"]
    verify = cfg.get("verify_ssl", False)
    intervalo = cfg.get("poll_interval", 3)
    session = None
    vistos = set()
    baseline = False
    log.info("BioStar 2 integrador iniciado (%s).", host)
    while stop is None or not stop.is_set():
        try:
            if not session:
                session = _login(host, cfg["login_id"], cfg["password"], verify)
                log.info("BioStar 2: sesión iniciada.")
            consulta = {"Query": {"limit": 50,
                                  "orders": [{"desc": True, "column": "datetime"}]}}
            _, r = _req(host, "/api/events/search", "POST", consulta, session, verify)
            eventos = r.get("EventCollection", {}).get("rows") or r.get("events") or []
            if not baseline:
                for ev in eventos:
                    vistos.add(_mapear(ev)[0])
                baseline = True
                log.info("BioStar 2 baseline: %d eventos.", len(vistos))
            else:
                for ev in reversed(eventos):
                    clave, datos = _mapear(ev)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    enviar_evento({"evento": "acceso", "datos": datos})
        except Exception as e:  # noqa: BLE001
            log.warning("BioStar 2 error: %s", e)
            session = None
        time.sleep(intervalo)
