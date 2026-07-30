#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HORARIO DE ATENCIÓN del cliente — única fuente de verdad para "¿estamos en horario?" y "¿cuántos
días hábiles pasaron?". La usan el triage (esperas, recordatorios y escaladas), el proactivo de SLA
y los reportes programados, así TODOS respetan el mismo calendario del cliente y su zona horaria.

Config por cliente (clientes.json):
    "zona_horaria": "America/Argentina/Buenos_Aires",
    "horario_atencion": {"dias": [0,1,2,3,4], "desde": "09:00", "hasta": "18:00"}
Sin bloque `horario_atencion` se asume Lunes a Viernes de 09:00 a 18:00 (el calendario del SLA
de SRT). `dias` usa la numeración de datetime.weekday(): 0 = lunes … 6 = domingo.
"""

from datetime import datetime, timedelta

ZONA_DEFAULT = "America/Argentina/Buenos_Aires"
HORARIO_DEFAULT = {"dias": [0, 1, 2, 3, 4], "desde": "09:00", "hasta": "18:00"}


def ahora_zona(cfg, ahora=None):
    """AHORA en la zona horaria del cliente (no la del servidor)."""
    if ahora is not None:
        return ahora
    zona = (cfg or {}).get("zona_horaria") or ZONA_DEFAULT
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(zona))
    except Exception:  # noqa: BLE001
        return datetime.now()


def ahora_local(cfg, ahora=None):
    """AHORA en la zona del cliente, SIN tzinfo: para comparar con fechas de sistemas externos
    (GLPI devuelve las fechas sin zona)."""
    return ahora_zona(cfg, ahora).replace(tzinfo=None)


def _cfg(cfg):
    return (cfg or {}).get("horario_atencion") or HORARIO_DEFAULT


def es_dia_habil(cfg, dt):
    """True si `dt` cae en un día de atención del cliente (default Lun-Vie)."""
    return dt.weekday() in _cfg(cfg).get("dias", HORARIO_DEFAULT["dias"])


def en_horario_atencion(cfg, ahora=None):
    """True si AHORA (zona del cliente) está DENTRO del horario de atención (default Lun-Vie 9-18).
    Es la puerta de todo lo que le escribimos al cliente y de los avisos al equipo: nada sale de
    noche ni un fin de semana."""
    h = _cfg(cfg)
    ahora = ahora_zona(cfg, ahora)
    if not es_dia_habil(cfg, ahora):
        return False
    hhmm = ahora.strftime("%H:%M")
    return str(h.get("desde", "09:00")) <= hhmm < str(h.get("hasta", "18:00"))


def proximo_inicio_horario(cfg, ahora=None):
    """datetime (con zona) del PRÓXIMO inicio del horario de atención (default próximo hábil 09:00)."""
    h = _cfg(cfg)
    dias = h.get("dias", HORARIO_DEFAULT["dias"])
    desde = str(h.get("desde", "09:00"))
    hh, mm = int(desde[:2]), int(desde[3:5])
    ahora = ahora_zona(cfg, ahora)
    cand = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
    for _ in range(9):                       # como mucho una semana hacia adelante
        if cand.weekday() in dias and cand > ahora:
            return cand
        cand = (cand + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return cand


def dias_habiles_entre(cfg, desde, hasta):
    """Días HÁBILES transcurridos entre dos fechas (sin contar el día de `desde`, contando el de
    `hasta`). Sirve para "a los 5 días hábiles sin respuesta". 0 si `hasta` <= `desde`."""
    if not desde or not hasta or hasta <= desde:
        return 0
    d, fin, n = desde.date(), hasta.date(), 0
    while d < fin:
        d += timedelta(days=1)
        if es_dia_habil(cfg, d):
            n += 1
    return n
