#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reportes PROACTIVOS por cliente: ITHOS manda solo un resumen (tickets + SLA) con la
frecuencia que el cliente elige (diario/semanal/mensual), a la hora indicada, por sus
canales configurados. Cada cliente lo configura a su gusto (o lo apaga).

Config por cliente (clientes.json -> "reportes"):
  {"enabled": true, "frecuencia": "diario|semanal|mensual", "hora": "09:00",
   "dia_semana": 0-6 (lunes=0, para semanal), "dia_mes": 1-28 (para mensual),
   "dias_habiles": true (SOLO diario: NO manda sábados ni domingos; el lunes cubre el finde
                         para no perder el viernes),
   "formato": ["pdf","csv"] (adjuntos; [] = solo texto), "por_tecnico": true}
Manda un resumen ITIL (texto) + los adjuntos elegidos (PDF/CSV) por los MISMOS canales
de "notificaciones" del cliente (los que soporten adjuntos).
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta

log = logging.getLogger("reportes-prog")
BASE = os.path.dirname(os.path.abspath(__file__))


def _estado_path(cliente):
    seguro = "".join(ch if ch.isalnum() else "_" for ch in (cliente or "cliente"))
    return os.path.join(BASE, f"reporte_estado_{seguro}.json")


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


def texto_reporte(cfg_glpi, entidad, periodo="mensual", zona="America/Argentina/Buenos_Aires",
                  empresa=""):
    """Resumen ITIL legible (formato WhatsApp/Telegram) del período."""
    from comun import reportes_itil as RI
    k = RI.calcular(cfg_glpi, entidad, periodo, zona, con_tecnico=True)
    return RI.resumen_texto(k, empresa)


def enviar_reporte(conf, notif, periodo=None, desde=None, hasta=None):
    """Genera el reporte ITIL del período y lo manda (texto + adjuntos PDF/CSV según config)
    por los canales del cliente. Devuelve True si mandó algo. Con `desde`/`hasta` ('YYYY-MM-DD')
    saca un rango A MANO (p. ej. el reporte del LUNES que cubre el finde para no perder el viernes)."""
    from comun import reportes_itil as RI
    gl = conf.get("integrador_glpi") or {}
    if not gl.get("glpi_url") or not notif:
        return False
    r = conf.get("reportes") or {}
    empresa = conf.get("nombre", "")
    zona = conf.get("zona_horaria", "America/Argentina/Buenos_Aires")
    ent = int(gl.get("entity_id", 0))
    periodo = periodo or (r.get("frecuencia") or "mensual")
    con_tec = bool(r.get("por_tecnico", True))
    if desde and hasta:
        # Rango explícito (cobertura del finde para el diario con días hábiles): del día pedido al día
        # pedido, con los datos reales de ese tramo.
        k = RI.calcular(gl, ent, "personalizado", zona, con_tecnico=con_tec, desde=desde, hasta=hasta)
    else:
        # cerrado=True: el reporte AUTOMÁTICO cubre el período COMPLETO ANTERIOR (diario=ayer, semanal=
        # semana pasada, mensual=mes pasado) -> siempre con datos reales, nunca vacío por mandarlo antes
        # de que arranque la jornada.
        k = RI.calcular(gl, ent, periodo, zona, con_tecnico=con_tec, cerrado=True)
    k["empresa"] = empresa
    notif.enviar(RI.resumen_texto(k, empresa))
    formatos = r.get("formato", ["pdf"])
    seguro = "".join(ch if ch.isalnum() else "_" for ch in empresa) or "reporte"
    base = f"reporte_ITIL_{seguro}_{periodo}"
    fn = getattr(notif, "enviar_documento", None)
    if fn:
        if "pdf" in formatos:
            pdf = RI.pdf_bytes(k, empresa)
            if pdf:
                fn(base + ".pdf", pdf, "application/pdf", f"Reporte ITIL {k['etiqueta']}")
        if "csv" in formatos:
            fn(base + ".csv", RI.csv_bytes(k, empresa), "text/csv", f"Reporte ITIL {k['etiqueta']}")
    return True


def _clave_periodo(r, ahora):
    """Devuelve la clave del período si AHORA corresponde enviar (hora/día), o None."""
    try:
        hh, mm = [int(x) for x in str(r.get("hora", "08:00")).split(":")]
    except Exception:  # noqa: BLE001
        hh, mm = 8, 0
    if ahora.hour != hh or ahora.minute != mm:
        return None
    freq = (r.get("frecuencia") or "diario").lower()
    if freq == "diario":
        # días hábiles: NO enviar sábados (weekday 5) ni domingos (6). El lunes cubre el finde para
        # no perder el viernes (ver _rango_diario_habil). Sin la opción, manda todos los días (antes).
        if r.get("dias_habiles") and ahora.weekday() >= 5:
            return None
        return "D" + ahora.strftime("%Y-%m-%d")
    if freq == "semanal":
        if ahora.weekday() != int(r.get("dia_semana", 0) or 0):
            return None
        return "W" + ahora.strftime("%Y-%W")
    if freq == "mensual":
        if ahora.day != int(r.get("dia_mes", 1) or 1):
            return None
        return "M" + ahora.strftime("%Y-%m")
    return None


def _rango_diario_habil(ahora):
    """Rango ('YYYY-MM-DD' desde, hasta) del reporte DIARIO con días hábiles cuando hubo días
    saltados antes (típicamente el LUNES). Cubre desde el último día HÁBIL previo (que fue el
    último envío) hasta AYER, así el viernes NO se pierde: el lunes cubre viernes+sábado+domingo.
    En un día hábil normal (martes a viernes) devuelve solo AYER."""
    hasta = ahora - timedelta(days=1)                 # ayer
    ult_habil = hasta
    while ult_habil.weekday() >= 5:                    # retrocede sobre el finde saltado (sáb/dom)
        ult_habil -= timedelta(days=1)
    return ult_habil.strftime("%Y-%m-%d"), hasta.strftime("%Y-%m-%d")


def _ahora_cliente(zona):
    """AHORA en la zona horaria del CLIENTE (no la del servidor, que está en otro país/UTC). Así el
    reporte sale a la hora local que el cliente eligió, en su región."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(zona or "America/Argentina/Buenos_Aires"))
    except Exception:  # noqa: BLE001
        return datetime.now()


async def vigilar_reportes(conf, notif, stop=None):
    """Loop por cliente: cuando corresponde, manda el reporte por sus canales."""
    r = conf.get("reportes") or {}
    gl = conf.get("integrador_glpi") or {}
    cliente = conf.get("nombre", "cliente")
    zona = conf.get("zona_horaria", "America/Argentina/Buenos_Aires")
    if not r.get("enabled") or not gl.get("glpi_url"):
        return
    log.info("Reportes programados activos para %s (%s a las %s, hora de %s).",
             cliente, r.get("frecuencia"), r.get("hora"), zona)
    while stop is None or not stop.is_set():
        try:
            ahora = _ahora_cliente(zona)                       # HORA DEL CLIENTE, no del servidor
            clave = _clave_periodo(r, ahora)
            if clave:
                st = _cargar(cliente)
                if st.get("ultimo") != clave:
                    freq = (r.get("frecuencia") or "diario").lower()
                    if (freq in ("diario", "dia", "hoy") and r.get("dias_habiles")
                            and ahora.weekday() == 0):
                        # LUNES con días hábiles: cubrir el finde (viernes..domingo), sin perder el viernes.
                        d, h = _rango_diario_habil(ahora)
                        await asyncio.to_thread(enviar_reporte, conf, notif, "personalizado", d, h)
                    else:
                        await asyncio.to_thread(enviar_reporte, conf, notif)
                    st["ultimo"] = clave
                    _guardar(cliente, st)
                    log.info("Reporte ITIL enviado a %s (%s).", cliente, clave)
        except Exception as e:  # noqa: BLE001
            log.warning("Reporte programado %s: %s", cliente, e)
        await asyncio.sleep(30)
