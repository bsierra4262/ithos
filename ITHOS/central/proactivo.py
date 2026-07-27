#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS PROACTIVO por cliente: vigila los tickets ABIERTOS y avisa SOLO cuando algo
necesita atención, sin que nadie pregunte. Hoy: alerta de SLA por vencer / vencido.

Funciona con CUALQUIER sistema de tickets (habla con el adaptador comun/tickets.py):
GLPI ya lo calcula por su time_to_resolve; los demás se suman al completar su
integración. TODO por cliente (config aislada) y por SUS canales configurados.

Config por cliente (clientes.json -> "proactivo"):
  {"sla_enabled": true, "aviso_horas": 4, "revisar_min": 15}
  - aviso_horas: avisa cuando falten <= N horas para vencer el SLA (o ya venció).
  - revisar_min: cada cuántos minutos revisa.
Apagado por defecto: si no hay bloque "proactivo" o sla_enabled=false, no hace nada.
Anti-spam: avisa UNA vez por ticket por día (estado en disco, por cliente).
"""

import os
import json
import asyncio
import logging
from datetime import datetime

log = logging.getLogger("proactivo")
BASE = os.path.dirname(os.path.abspath(__file__))


def _estado_path(cliente):
    seguro = "".join(ch if ch.isalnum() else "_" for ch in (cliente or "cliente"))
    return os.path.join(BASE, f"proactivo_estado_{seguro}.json")


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


def _texto_alerta(en_riesgo):
    hoy = datetime.now().strftime("%H:%M")
    venc = [t for t in en_riesgo if t.get("vencido")]
    porv = [t for t in en_riesgo if not t.get("vencido")]
    lineas = [f"⚠️ *SLA en riesgo* — {hoy}"]
    for t in venc:
        lineas.append(f"🔴 #{t['id']} {str(t.get('asunto'))[:45]} — *SLA VENCIDO*")
    for t in porv:
        lineas.append(f"🟠 #{t['id']} {str(t.get('asunto'))[:45]} — vence en "
                      f"{t.get('faltan_horas')} h")
    return "\n".join(lineas)


async def vigilar_sla(conf, notif, stop=None):
    """Loop por cliente: avisa por sus canales cuando un ticket está por vencer el SLA
    (o ya venció) y sigue abierto. Una alerta por ticket por día."""
    p = conf.get("proactivo") or {}
    cliente = conf.get("nombre", "cliente")
    if not p.get("sla_enabled"):
        return
    aviso_horas = float(p.get("aviso_horas", 4))
    revisar = max(60, int(p.get("revisar_min", 15)) * 60)

    from comun import tickets as T
    adap = T.adaptador(conf)
    log.info("Proactivo SLA activo para %s (aviso <= %sh, cada %smin).",
             cliente, aviso_horas, revisar // 60)

    while stop is None or not stop.is_set():
        try:
            en_riesgo = await asyncio.to_thread(adap.en_riesgo_sla, aviso_horas)
            if en_riesgo:
                st = _cargar(cliente)
                hoy = datetime.now().strftime("%Y-%m-%d")
                if st.get("dia") != hoy:                # nuevo día -> reset avisos
                    st = {"dia": hoy, "avisados": []}
                nuevos = [t for t in en_riesgo if t["id"] not in st["avisados"]]
                if nuevos:
                    if notif:
                        await asyncio.to_thread(notif.enviar, _texto_alerta(nuevos))
                    st["avisados"].extend(t["id"] for t in nuevos)
                    _guardar(cliente, st)
                    log.info("Proactivo: avisé %d tickets SLA a %s.", len(nuevos), cliente)
        except Exception as e:  # noqa: BLE001
            log.warning("Proactivo SLA %s: %s", cliente, e)
        await asyncio.sleep(revisar)
