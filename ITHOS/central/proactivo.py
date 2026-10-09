#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS PROACTIVO por cliente: vigila los tickets ABIERTOS y avisa SOLO cuando algo
necesita atención, sin que nadie pregunte. Hoy: alerta de SLA por vencer / vencido.

El aviso se manda AGRUPADO POR TÉCNICO ASIGNADO y lo @MENCIONA (WhatsApp) para que le suene a él
y no al resto: cada uno ve sus tickets. Los tickets cuyo asignado no está en el bloque `tecnicos`
del cliente van en un aviso normal al grupo (sin @mención).

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

from comun import ambitos as AMB
from datetime import datetime

log = logging.getLogger("proactivo")
BASE = os.path.dirname(os.path.abspath(__file__))


# El estado va al VOLUMEN y se escribe atómico (comun/estado.py). Antes se guardaba al lado de
# este archivo, que en el servidor está DENTRO de la imagen del contenedor: cada deploy lo borraba
# y los avisos que ya se habían mandado volvían a salir.
def _cargar(cliente):
    from comun import estado as _E
    return _E.cargar("proactivo_estado", cliente)


def _guardar(cliente, st):
    from comun import estado as _E
    _E.guardar("proactivo_estado", cliente, st)


def _texto_alerta(en_riesgo, para="", zona=None):
    # La hora que LEE EL CLIENTE tiene que ser la SUYA. El servidor corre en UTC: la alerta decía
    # "21:40" cuando para él eran las 18:40, y encima la clave anti-spam "una vez por día" rotaba
    # a las 21:00 de su hora, así que la misma alerta podía salir dos veces esa noche.
    from comun.horario import ahora_zona
    hoy = ahora_zona({"zona_horaria": zona}).strftime("%H:%M")
    venc = [t for t in en_riesgo if t.get("vencido")]
    porv = [t for t in en_riesgo if not t.get("vencido")]
    lineas = [f"⚠️ *SLA en riesgo* — {hoy}" + (f" · asignados a {para}" if para else "")]
    for t in venc:
        lineas.append(f"🔴 #{t['id']} {str(t.get('asunto'))[:45]} — *SLA VENCIDO*")
    for t in porv:
        lineas.append(f"🟠 #{t['id']} {str(t.get('asunto'))[:45]} — vence en "
                      f"{t.get('faltan_horas')} h")
    return "\n".join(lineas)


def _por_tecnico(conf, tickets):
    """Agrupa los tickets en riesgo por TÉCNICO ASIGNADO (mapeo 'tecnicos' del cliente):
    [(nombres, telefonos, [tickets])]. Los tickets SIN asignado configurado van al final con
    telefonos=[] -> aviso normal al grupo, sin @mención. Así se @menciona SOLO al asignado."""
    from comun import tickets as T
    grupos, sueltos = {}, []
    for t in tickets:
        tels = T.telefonos_asignados(conf, t.get("asignados") or [])
        if not tels:
            sueltos.append(t)
            continue
        clave = ",".join(tels)
        g = grupos.setdefault(clave, {"tels": tels, "nombres": T.nombres_asignados(
            conf, t.get("asignados") or []), "tickets": []})
        g["tickets"].append(t)
    salida = [(", ".join(g["nombres"]), g["tels"], g["tickets"]) for g in grupos.values()]
    if sueltos:
        salida.append(("", [], sueltos))
    return salida


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

    from comun.horario import en_horario_atencion, ahora_local
    zona = conf.get("zona_horaria")

    while stop is None or not stop.is_set():
        try:
            # El aviso es para el EQUIPO, pero igual sale por WhatsApp: solo DENTRO del horario de
            # atención del cliente (default Lun-Vie 09:00-18:00, su zona). Fuera de horario no se
            # marca como avisado, así el ticket en riesgo se avisa al abrir la jornada (09:00).
            en_riesgo = (await asyncio.to_thread(adap.en_riesgo_sla, aviso_horas)
                         if en_horario_atencion(conf) else [])
            if en_riesgo:
                st = _cargar(cliente)
                # El "día" es el del CLIENTE: con la fecha del servidor (UTC) el contador se
                # reiniciaba a las 21:00 de su hora y la misma alerta podía repetirse esa noche.
                hoy = ahora_local(conf).strftime("%Y-%m-%d")
                if st.get("dia") != hoy:                # nuevo día -> reset avisos
                    st = {"dia": hoy, "avisados": []}
                nuevos = [t for t in en_riesgo if t["id"] not in st["avisados"]]
                if nuevos:
                    if notif:
                        # Un aviso POR TÉCNICO ASIGNADO, @mencionándolo (WhatsApp) para que le
                        # SUENE a él; los tickets sin asignado configurado van en un aviso normal.
                        for nombres, tels, ts in _por_tecnico(conf, nuevos):
                            texto = _texto_alerta(ts, nombres, zona)
                            if tels and hasattr(notif, "enviar_mencion"):
                                await asyncio.to_thread(
                                    lambda t=texto, x=tels: AMB.llamar(
                                        notif.enviar_mencion, t, x, tipo=AMB.SLA))
                            else:
                                await asyncio.to_thread(
                                    lambda t=texto: AMB.llamar(notif.enviar, t, tipo=AMB.SLA))
                    st["avisados"].extend(t["id"] for t in nuevos)
                    _guardar(cliente, st)
                    log.info("Proactivo: avisé %d tickets SLA a %s.", len(nuevos), cliente)
        except Exception as e:  # noqa: BLE001
            log.warning("Proactivo SLA %s: %s", cliente, e)
        await asyncio.sleep(revisar)
