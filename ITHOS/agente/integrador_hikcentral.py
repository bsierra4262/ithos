#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrador HikCentral (agente) — HikCentral Professional OpenAPI (gateway "Artemis").
Consulta los eventos de control de acceso (fichajes) y manda un evento "acceso" al
central por cada uno nuevo.

Auth: appKey/appSecret con firma HMAC-SHA256 por request (esquema Artemis).
Config (agente/config.json -> integrador):
  {"tipo":"hikcentral","host":"https://IP:443","app_key":"...","app_secret":"...",
   "poll_interval":3, "verify_ssl": false}

NOTA: probar/ajustar con el HikCentral real del cliente (endpoint y campos de evento
pueden variar según versión). El endpoint de eventos de acceso suele ser
/artemis/api/acs/v1/door/events o /artemis/api/acs/v1/event/... — ajustar acá.
"""

import time
import json
import hmac
import base64
import hashlib
import logging
import urllib.request
from datetime import datetime, timedelta

log = logging.getLogger("integrador.hikcentral")
_EVENTOS = "/artemis/api/acs/v1/door/events"   # ajustar según versión del cliente


def _iso(dt):
    """ISO8601 con offset local (formato que exige HikCentral, ej. 2024-08-06T10:00:00+00:00)."""
    off = -time.timezone
    sig = "+" if off >= 0 else "-"
    off = abs(off)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f"{sig}{off // 3600:02d}:{(off % 3600) // 60:02d}"


def _firmar(method, path, app_key, app_secret, body_md5=""):
    accept, ctype = "application/json", "application/json"
    partes = [method, accept, body_md5, ctype,
              f"x-ca-key:{app_key}", path]
    string_to_sign = "\n".join(partes)
    firma = base64.b64encode(hmac.new(app_secret.encode(), string_to_sign.encode(),
                                      hashlib.sha256).digest()).decode()
    return {"Accept": accept, "Content-Type": ctype, "X-Ca-Key": app_key,
            "X-Ca-Signature": firma,
            "X-Ca-Signature-Headers": "x-ca-key"}


def _post(host, path, app_key, app_secret, payload, verify_ssl):
    body = json.dumps(payload).encode()
    md5 = base64.b64encode(hashlib.md5(body).digest()).decode()
    headers = _firmar("POST", path, app_key, app_secret, md5)
    ctx = None
    if not verify_ssl:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(host.rstrip("/") + path, data=body,
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.loads(r.read().decode())


def _mapear(ev):
    """Mapea un evento de HikCentral -> {nombre, tipo}. Ajustar campos si difieren."""
    nombre = str(ev.get("personName") or ev.get("name") or "").strip()
    device = str(ev.get("doorName") or ev.get("devName") or "").strip()   # nombre del lector/puerta
    dev = device.lower()
    ok = ev.get("eventType") not in (None, "", 0) and bool(nombre)
    if "sala tecnica" in dev:
        tipo = "sala"
    elif not ok or not nombre:
        tipo = "alerta"
    else:
        tipo = "bienvenida"
    clave = f"{ev.get('serialNo') or ev.get('eventId')}|{ev.get('eventTime')}"
    # El CENTRAL clasifica por 'device' según la config del cliente (thin agent); 'tipo' va de respaldo.
    return clave, {"nombre": nombre, "device": device, "es_fallo": tipo == "alerta", "tipo": tipo}


def vigilar(cfg, enviar_evento, stop=None):
    host = cfg["host"]
    ak, sk = cfg["app_key"], cfg["app_secret"]
    intervalo = cfg.get("poll_interval", 3)
    verify = cfg.get("verify_ssl", False)
    vistos = set()
    baseline = False
    log.info("HikCentral integrador iniciado (%s).", host)
    while stop is None or not stop.is_set():
        try:
            # Ventana de tiempo requerida por la OpenAPI; se pagina hasta que
            # responseStatusStrg deje de ser "MORE".
            fin = datetime.now()
            ini = fin - timedelta(minutes=cfg.get("ventana_min", 5))
            eventos, page = [], 1
            while True:
                payload = {"pageNo": page, "pageSize": 100,
                           "startTime": _iso(ini), "endTime": _iso(fin)}
                r = _post(host, _EVENTOS, ak, sk, payload, verify)
                data = r.get("data") or {}
                eventos += data.get("list") or []
                if str(r.get("responseStatusStrg") or data.get("responseStatusStrg")
                       or "").upper() != "MORE" or page >= 20:
                    break
                page += 1
            if not baseline:
                for ev in eventos:
                    vistos.add(_mapear(ev)[0])
                baseline = True
                log.info("HikCentral baseline: %d eventos.", len(vistos))
            else:
                for ev in reversed(eventos):
                    clave, datos = _mapear(ev)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    if len(vistos) > 6000:
                        vistos = set(list(vistos)[-5000:])
                    enviar_evento({"evento": "acceso", "datos": datos})
        except Exception as e:  # noqa: BLE001
            log.warning("HikCentral error: %s", e)
        time.sleep(intervalo)
