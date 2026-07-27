#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anomalías de ACCESO por horario (por cliente). ITHOS avisa cuando alguien ficha fuera
de su horario / es denegado por franja horaria. Multi-sistema (habla con el adaptador
comun/acceso.py): funciona con HikCentral y BioStar 2, que traen su configuración de
horarios por su propia API — el cliente NO configura horarios a mano.

REGLAS pedidas:
  - OFF por defecto. NUNCA se activa solo. Se prende por cliente (config).
  - Sistemas SIN control de horario (IVMS/ZKTeco/Honeywell): no aplica (nuestra empresa
    usa IVMS y no toma control horario -> nunca corre, aunque esté prendido).
  - Cuando aplica, toma la config del sistema por API automáticamente (sin configurar).

Config por cliente (clientes.json -> "anomalias"):
  {"enabled": true, "revisar_min": 10}
Envía por los MISMOS canales del cliente. Anti-spam: una vez por evento por día.
"""

import os
import json
import asyncio
import logging
from datetime import datetime

log = logging.getLogger("anomalias")
BASE = os.path.dirname(os.path.abspath(__file__))


def _estado_path(cliente):
    seguro = "".join(ch if ch.isalnum() else "_" for ch in (cliente or "cliente"))
    return os.path.join(BASE, f"anomalias_estado_{seguro}.json")


def _cargar(cliente):
    try:
        return json.load(open(_estado_path(cliente), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _guardar(cliente, st):
    try:
        json.dump(st, open(_estado_path(cliente), "w", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass


def _texto(anoms):
    hora = datetime.now().strftime("%H:%M")
    lineas = [f"🚨 *Anomalía de acceso* — {hora}"]
    for a in anoms:
        lineas.append(f"• {a.get('nombre', '?')} — {a.get('motivo', 'fuera de horario')}"
                      + (f" ({a['cuando']})" if a.get("cuando") else ""))
    return "\n".join(lineas)


async def vigilar_anomalias(conf, notif, stop=None):
    """Loop por cliente. Solo corre si el cliente lo prendió Y su sistema de acceso
    soporta control de horario (autoconfig por API). Si no, no hace nada."""
    a = conf.get("anomalias") or {}
    cliente = conf.get("nombre", "cliente")
    if not a.get("enabled"):
        return                                       # OFF por defecto
    from comun import acceso as ACC
    adap = ACC.adaptador(conf)
    if not adap.soporta_anomalias():
        log.info("Anomalías: %s usa un sistema sin control de horario (%s). No aplica.",
                 cliente, getattr(adap, "tipo", "?"))
        return                                       # IVMS/ZKTeco/Honeywell -> no aplica
    revisar = max(60, int(a.get("revisar_min", 10)) * 60)
    log.info("Anomalías de horario activas para %s (%s, cada %smin, autoconfig por API).",
             cliente, adap.tipo, revisar // 60)
    while stop is None or not stop.is_set():
        try:
            anoms = await asyncio.to_thread(adap.anomalias)
            if anoms:
                st = _cargar(cliente)
                hoy = datetime.now().strftime("%Y-%m-%d")
                if st.get("dia") != hoy:
                    st = {"dia": hoy, "avisados": []}
                clave = lambda x: f"{x.get('nombre')}|{x.get('cuando')}"  # noqa: E731
                nuevos = [x for x in anoms if clave(x) not in st["avisados"]]
                if nuevos:
                    if notif:
                        await asyncio.to_thread(notif.enviar, _texto(nuevos))
                    st["avisados"].extend(clave(x) for x in nuevos)
                    _guardar(cliente, st)
                    log.info("Anomalías: avisé %d en %s.", len(nuevos), cliente)
        except Exception as e:  # noqa: BLE001
            log.warning("Anomalías %s: %s", cliente, e)
        await asyncio.sleep(revisar)
