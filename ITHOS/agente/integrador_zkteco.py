#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrador ZKTeco (agente). Soporta las DOS plataformas actuales de ZKTeco:

  - "zkbiosecurity" / ZKBio CVSecurity (control de ACCESO):
      Auth: POST /api-token-auth/ {"username","password"} -> {"token"}
            header 'Authorization: Token <token>'
      Eventos: GET /acc/api/transactions/?page_size=50&ordering=-id
  - "zkbiotime" / BioTime 8.5 (control de ASISTENCIA/fichaje):
      Auth: POST /jwt-api-token-auth/ {"username","password"} -> {"token"}
            header 'Authorization: JWT <token>'
      Fichajes: GET /iclock/api/transactions/?page_size=50&ordering=-id

Config (agente/config.json -> integrador):
  {"tipo":"zkteco","plataforma":"zkbiosecurity","host":"http://IP:8098",
   "username":"...","password":"...","poll_interval":3}
(referencia: BioTime 8.5 API User Manual; ZKBio CVSecurity API).
"""

import time
import json
import logging
import urllib.request

log = logging.getLogger("integrador.zkteco")

# Por plataforma: (login_path, prefijo_header, transacciones_path)
PLATAFORMAS = {
    "zkbiosecurity": ("/api-token-auth/", "Token", "/acc/api/transactions/"),
    "zkbiotime": ("/jwt-api-token-auth/", "JWT", "/iclock/api/transactions/"),
}


def _json(url, headers=None, data=None, method="GET"):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode() or "{}")


def _mapear(ev):
    nombre = str(ev.get("name") or ev.get("emp_name")
                 or (f"{ev.get('first_name','')} {ev.get('last_name','')}").strip()
                 or ev.get("pin") or ev.get("emp_code") or "").strip()
    device = str(ev.get("device_name") or ev.get("terminal_alias")
                 or ev.get("terminal") or "").strip()        # nombre del lector/terminal
    dev = device.lower()
    estado = str(ev.get("event_name") or ev.get("verify_type_name")
                 or ev.get("punch_state_display") or "").lower()
    if "sala tecnica" in dev:
        tipo = "sala"
    elif "deni" in estado or "fail" in estado or "invalid" in estado or not nombre:
        tipo = "alerta"
    else:
        tipo = "bienvenida"
    clave = f"{ev.get('id') or ev.get('event_time') or ev.get('punch_time')}"
    # El CENTRAL clasifica por 'device' según la config del cliente (thin agent); 'tipo' va de respaldo.
    return clave, {"nombre": nombre, "device": device, "es_fallo": tipo == "alerta", "tipo": tipo}


def vigilar(cfg, enviar_evento, stop=None):
    host = cfg["host"].rstrip("/")
    plat = (cfg.get("plataforma") or "zkbiosecurity").lower()
    login_path, prefijo, tx_path = PLATAFORMAS.get(plat, PLATAFORMAS["zkbiosecurity"])
    tx_path = cfg.get("transacciones_path", tx_path)
    intervalo = cfg.get("poll_interval", 3)
    token = None
    vistos, baseline = set(), False
    log.info("ZKTeco integrador iniciado (%s, %s).", host, plat)
    while stop is None or not stop.is_set():
        try:
            if not token:
                token = _json(f"{host}{login_path}", {"Content-Type": "application/json"},
                              {"username": cfg["username"], "password": cfg["password"]},
                              "POST").get("token")
            h = {"Authorization": f"{prefijo} {token}"}
            r = _json(f"{host}{tx_path}?page_size=50&ordering=-id", h)
            eventos = r.get("data") or r.get("results") or []
            if not baseline:
                for ev in eventos:
                    vistos.add(_mapear(ev)[0])
                baseline = True
                log.info("ZKTeco baseline: %d eventos.", len(vistos))
            else:
                for ev in reversed(eventos):
                    clave, datos = _mapear(ev)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    enviar_evento({"evento": "acceso", "datos": datos})
        except Exception as e:  # noqa: BLE001
            log.warning("ZKTeco error: %s", e)
            token = None
        time.sleep(intervalo)
