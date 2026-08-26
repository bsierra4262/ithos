#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reportes ITIL (4) de mesa de ayuda, por cliente. Calcula KPIs REALES desde el sistema de
tickets (GLPI hoy; el resto por el adaptador) y los entrega en 3 formatos:
  - texto   -> resumen legible por canal (WhatsApp/Telegram/Email)
  - CSV     -> datos crudos para planillas
  - PDF     -> informe profesional con diseño (reportlab)

KPIs (ITIL 4 — solo se reporta lo que se puede medir con EXACTITUD; nada inventado):
  Volumen del período: creados, resueltos, cerrados.  Backlog actual + AGING.
  Cumplimiento de SLA de RESOLUCIÓN (TTR) y de PRIMERA RESPUESTA (TTO).
  MTTR (tiempo medio de resolución).  MTTA/1ª respuesta (si se piden detalles).
  Reapertura.  Desglose por PRIORIDAD, CATEGORÍA, ESTADO, TÉCNICO y SECTOR (entidad).

Períodos: 'diario' (hoy), 'semanal' (esta semana), 'mensual' (este mes), 'total'.
"""

import os
import io
import sys
import csv
import time
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from comun import glpi as G   # noqa: E402

log = logging.getLogger("reportes-itil")

ESTADOS = {1: "Nuevo", 2: "En curso", 3: "Planificado", 4: "En espera",
           5: "Resuelto", 6: "Cerrado"}
PRIOS = {1: "Muy baja", 2: "Baja", 3: "Media", 4: "Alta", 5: "Muy alta", 6: "Mayor"}
ABIERTOS = (1, 2, 4)                      # estados que cuentan como backlog
ZONA_DEFAULT = "America/Argentina/Buenos_Aires"
_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha(s):
    if not s:                       # None / "" / 0 -> sin fecha (evita strptime en masa a escala)
        return None
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return None


def _zona(zona):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(zona or ZONA_DEFAULT)
    except Exception:  # noqa: BLE001
        return None


def _dia(s, z, fin=False):
    """'YYYY-MM-DD' -> datetime AWARE al inicio (00:00) o fin (23:59:59) del día. None si no."""
    try:
        d = datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return None
    return d.replace(hour=23, minute=59, second=59, tzinfo=z) if fin else d.replace(tzinfo=z)


def rango(periodo, zona=ZONA_DEFAULT, ahora=None, desde=None, hasta=None, cerrado=False):
    """Devuelve (desde, hasta, etiqueta) para el período pedido, en hora del cliente.
    'personalizado' con desde/hasta ('YYYY-MM-DD') permite un rango A MANO (históricos, o sacar
    cualquier tramo si algo falla). Si falta una punta, se completa (desde=1º del mes / hasta=hoy).

    cerrado=True: período COMPLETO ANTERIOR (para los reportes AUTOMÁTICOS) -> el diario es AYER, el
    semanal la semana pasada, el mensual el mes pasado. Así el informe SIEMPRE tiene datos reales y no
    sale vacío (el reporte del día se manda al día siguiente, con la jornada ya cerrada). cerrado=False
    (por defecto, 'reporte ahora' manual): el período en curso hasta este momento."""
    z = _zona(zona)
    ahora = ahora or datetime.now(z)
    hoy0 = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    p = (periodo or "mensual").lower()
    if p in ("personalizado", "custom", "rango", "manual"):
        d = _dia(desde, z) or hoy0.replace(day=1)
        h = _dia(hasta, z, fin=True) or ahora
        if h < d:
            d, h = h.replace(hour=0, minute=0, second=0), d.replace(hour=23, minute=59, second=59)
        return d, h, f"Del {d.strftime('%d/%m/%Y')} al {h.strftime('%d/%m/%Y')}"
    if p in ("diario", "dia", "hoy"):
        if cerrado:                                          # AYER completo (día ya cerrado)
            ini = hoy0 - timedelta(days=1)
            return ini, hoy0 - timedelta(microseconds=1), f"Día {ini.strftime('%d/%m/%Y')}"
        return hoy0, ahora, f"Día {ahora.strftime('%d/%m/%Y')}"
    if p in ("semanal", "semana"):
        if cerrado:                                          # semana PASADA completa (lun a dom)
            fin = hoy0 - timedelta(days=ahora.weekday())     # lunes de esta semana (exclusivo)
            ini = fin - timedelta(days=7)                    # lunes de la semana pasada
            return ini, fin - timedelta(microseconds=1), \
                f"Semana del {ini.strftime('%d/%m')} al {(fin - timedelta(days=1)).strftime('%d/%m/%Y')}"
        ini = hoy0 - timedelta(days=ahora.weekday())
        return ini, ahora, f"Semana del {ini.strftime('%d/%m')} al {ahora.strftime('%d/%m/%Y')}"
    if p in ("mensual", "mes"):
        if cerrado:                                          # mes PASADO completo
            fin = hoy0.replace(day=1)                        # 1º de este mes (exclusivo)
            ini = (fin - timedelta(days=1)).replace(day=1)   # 1º del mes pasado
            return ini, fin - timedelta(microseconds=1), f"{_MESES[ini.month].capitalize()} {ini.year}"
        ini = hoy0.replace(day=1)
        return ini, ahora, f"{_MESES[ahora.month].capitalize()} {ahora.year}"
    return None, ahora, "Histórico"


def _en_rango(dt, desde, hasta):
    if not dt:
        return False
    if desde and dt < desde.replace(tzinfo=None):
        return False
    if hasta and dt > hasta.replace(tzinfo=None):
        return False
    return True


# ------------------------------------------------------------------ recolección
# NOTA de sesiones: TODO el reporte usa DOS sesiones GLPI (una con el token de ithos para
# tickets/asignados, otra con el de lectura para categorías/usuarios), abiertas UNA vez y
# CERRADAS al terminar (context manager). Antes se abría una sesión por técnico/usuario
# (cientos) y se agotaban las sesiones de GLPI.
def _cat_map(c_lect):
    """id -> nombre de categoría, usando una sesión de LECTURA ya abierta."""
    try:
        cats = c_lect.request("/ITILCategory?range=0-999") or []
        return {int(x["id"]): (x.get("completename") or x.get("name") or f"cat {x['id']}")
                for x in cats if isinstance(x, dict) and x.get("id") is not None}
    except Exception:  # noqa: BLE001
        return {}


def _nombre_usuario(c_lect, uid, cache):
    if uid in cache:
        return cache[uid]
    nombre = f"usuario {uid}"
    try:
        u = c_lect.request(f"/User/{uid}")
        if isinstance(u, list):
            u = u[0] if u else {}
        nombre = (f"{u.get('firstname') or ''} {u.get('realname') or ''}".strip()
                  or u.get("name") or nombre)
    except Exception:  # noqa: BLE001
        pass
    cache[uid] = nombre
    return nombre


def _mapa_asignados(c_ithos, ithos_id, tam=2000):
    """{ticket_id: [users_id de técnicos asignados (type 2), sin ITHOS]} en UNA sola lectura
    paginada de Ticket_User. Reemplaza el N+1 (una request por ticket, ~50s con cientos de
    tickets) por una lectura masiva (~0,5s): mismo resultado, instantáneo."""
    mapa, inicio = {}, 0
    while True:
        try:
            chunk = c_ithos.request(f"/Ticket_User?range={inicio}-{inicio + tam - 1}")
        except Exception:  # noqa: BLE001
            break
        if not isinstance(chunk, list) or not chunk:
            break
        for u in chunk:
            if not isinstance(u, dict):
                continue
            if int(u.get("type", 0)) == 2 and int(u.get("users_id", 0)) != ithos_id:
                mapa.setdefault(int(u.get("tickets_id", 0)), []).append(int(u.get("users_id", 0)))
        if len(chunk) < tam:                 # última página incompleta -> no hay más
            break
        inicio += tam
        if inicio > 1000000:                 # tope de seguridad
            break
    return mapa


# Cachés CORTOS de metadatos que cambian lento (por URL de GLPI): categorías (rara vez cambian),
# el mapa de asignados (misma frescura que los tickets) y los nombres de usuario. Así, tras el
# primer reporte, los siguientes (otros períodos) y las descargas salen INSTANTÁNEOS.
_CATCACHE, _MAPCACHE, _NAMECACHE = {}, {}, {}
_META_TTL = 45          # asignados: mismos 45s que el caché de tickets
_CAT_TTL = 300          # categorías: cambian rarísimo


def _cat_map_cache(cfg_glpi, c_lect):
    key = cfg_glpi.get("glpi_url")
    hit = _CATCACHE.get(key)
    if hit and (time.time() - hit[0]) < _CAT_TTL:
        return hit[1]
    m = _cat_map(c_lect)
    if m:                                    # no cachees un fallo transitorio (dict vacío)
        _CATCACHE[key] = (time.time(), m)
    return m


def _mapa_asignados_cache(cfg_glpi, c_ithos, ithos_id):
    key = cfg_glpi.get("glpi_url")
    hit = _MAPCACHE.get(key)
    if hit and (time.time() - hit[0]) < _META_TTL:
        return hit[1]
    m = _mapa_asignados(c_ithos, ithos_id)
    if m:
        _MAPCACHE[key] = (time.time(), m)
    return m


def _tecnicos_humanos(cfg_glpi, ithos_id):
    """Ids de las PERSONAS del equipo (los técnicos de la config, sin ITHOS). Sale de la config del
    cliente: sumar a alguien al equipo no tiene que obligar a tocar el reporte."""
    from comun import tickets as TK
    ids = set()
    for t in TK.tecnicos(cfg_glpi):
        for clave in ("glpi_id", "id"):
            try:
                v = int(t.get(clave))
            except (TypeError, ValueError):
                continue
            if v and v != ithos_id:
                ids.add(v)
            break
    return ids


# Quién resolvió cada ticket no cambia minuto a minuto, y leerlo cuesta (son TODOS los
# seguimientos del histórico: ~18 s la primera vez). Se cachea 10 minutos, no los 45 segundos de
# los asignados: repetir esa lectura en cada reporte haría lento algo que se mira seguido.
_RESCACHE = {}
_RES_TTL = 600


def _mapa_resolutores(cfg_glpi, c_ithos, humanos, ttl=_RES_TTL):
    """{ticket_id: user_id del TÉCNICO QUE LO RESOLVIÓ} para todo el histórico.

    Quien resolvió es quien dejó el ÚLTIMO comentario del lado del equipo: la solución formal la
    carga ITHOS (hace el pasaje), así que mirar el autor del registro de solución diría siempre
    'ITHOS' y el reporte no serviría para saber quién sacó adelante cada caso.

    Es UNA lectura masiva de seguimientos, cacheada: pedirlos ticket por ticket llevaba el reporte
    de un segundo a casi un minuto."""
    key = (cfg_glpi.get("glpi_url"), tuple(sorted(humanos)))
    hit = _RESCACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    mapa, inicio, tam = {}, 0, 500
    while True:
        try:
            chunk = c_ithos.request(f"/ITILFollowup?range={inicio}-{inicio + tam - 1}")
        except Exception:  # noqa: BLE001
            break
        if not isinstance(chunk, list) or not chunk:
            break
        for f in chunk:
            if not isinstance(f, dict) or str(f.get("itemtype")) != "Ticket":
                continue
            uid = int(f.get("users_id") or 0)
            if uid not in humanos:
                continue
            tid = int(f.get("items_id") or 0)
            fid = int(f.get("id") or 0)
            if fid >= mapa.get(tid, (0, 0))[0]:          # el ÚLTIMO comentario del equipo
                mapa[tid] = (fid, uid)
        inicio += len(chunk)
        if inicio > 200000:                              # tope de seguridad
            break
    out = {tid: uid for tid, (_, uid) in mapa.items()}
    if out:
        _RESCACHE[key] = (time.time(), out)
    return out


# ------------------------------------------------------------------ cálculo
# Caché CORTO de KPIs ya calculados: al abrir el reporte se calcula UNA vez y las descargas de
# CSV/PDF del mismo tramo reusan ese resultado (instantáneo, sin recalcular 3 veces). TTL corto:
# los datos siguen siendo reales/al día (igual criterio que el caché de tickets de 45s).
_KCACHE = {}
_KCACHE_TTL = 30


def calcular(cfg_glpi, entidad, periodo="mensual", zona=ZONA_DEFAULT, n=500,
             con_tecnico=True, max_tecnico=150, desde=None, hasta=None, cerrado=False):
    """Calcula los KPIs ITIL del período. Devuelve un dict estructurado. Con periodo
    'personalizado' + desde/hasta ('YYYY-MM-DD') saca el rango a mano (histórico/tramo).
    cerrado=True (reportes automáticos): período COMPLETO ANTERIOR (ayer / semana o mes pasado)."""
    ckey = (cfg_glpi.get("glpi_url"), entidad, (periodo or "").lower(),
            desde, hasta, bool(con_tecnico), bool(cerrado))
    hit = _KCACHE.get(ckey)
    if hit and (time.time() - hit[0]) < _KCACHE_TTL:
        return dict(hit[1])            # copia superficial: 'empresa' se setea afuera sin pisar caché
    desde, hasta, etiqueta = rango(periodo, zona, desde=desde, hasta=hasta, cerrado=cerrado)
    ithos_id = int(cfg_glpi.get("ithos_user_id", 28))
    tok_admin = (cfg_glpi.get("glpi_superadmin_token")
                 or cfg_glpi.get("glpi_user_token") or cfg_glpi.get("glpi_ithos_token"))
    # Sesiones VIVAS del pool (reutilizadas): ithos para tickets/asignados, super admin para
    # categorías/usuarios. No se abren/cierran por llamada.
    c_ithos = G.sesion(cfg_glpi, cfg_glpi.get("glpi_ithos_token"))
    c_lect = G.sesion(cfg_glpi, tok_admin)
    k = _calcular_con(cfg_glpi, c_ithos, c_lect, entidad, periodo, zona, n, con_tecnico,
                      max_tecnico, desde, hasta, etiqueta, ithos_id)
    _KCACHE[ckey] = (time.time(), k)
    return dict(k)


def _calcular_con(cfg_glpi, c_ithos, c_lect, entidad, periodo, zona, n, con_tecnico, max_tecnico,
                  desde, hasta, etiqueta, ithos_id):
    # SIN límite: TODOS los tickets (paginados, con caché corto) y recién después se filtra por el
    # período. Así los rangos (diario/semanal/mensual/total) cuentan de verdad, aunque haya miles.
    # Todas las áreas del cliente (una entidad por área): los KPIs son del cliente, no de un área.
    tickets = G.de_entidad(G.tickets_todos_cache(cfg_glpi), G.entidades_de(cfg_glpi))
    catmap = _cat_map_cache(cfg_glpi, c_lect)

    creados = resueltos = cerrados = 0
    ttr_med = ttr_ok = tto_med = tto_ok = 0
    reaperturas = 0
    horas_resol = []
    por_prio, por_cat, por_estado, por_tec = {}, {}, {}, {}
    backlog, aging = [], {"< 1 día": 0, "1-3 días": 0, "3-7 días": 0, "> 7 días": 0}
    ahora_naive = datetime.now()

    for t in tickets:
        creada = _fecha(t.get("date_creation") or t.get("date"))
        solve = _fecha(t.get("solvedate"))
        close = _fecha(t.get("closedate"))
        ttr = _fecha(t.get("time_to_resolve"))
        tto = _fecha(t.get("time_to_own"))
        st = int(t.get("status", 0))

        if _en_rango(creada, desde, hasta):
            creados += 1
            por_prio_key = PRIOS.get(int(t.get("priority", 0)), "?")
            por_prio[por_prio_key] = por_prio.get(por_prio_key, 0) + 1
            cat = catmap.get(int(t.get("itilcategories_id") or 0), "(sin categoría)")
            por_cat[cat] = por_cat.get(cat, 0) + 1
            por_estado[ESTADOS.get(st, "?")] = por_estado.get(ESTADOS.get(st, "?"), 0) + 1
        if _en_rango(solve, desde, hasta):
            resueltos += 1
            if creada:
                horas_resol.append((solve - creada).total_seconds() / 3600.0)
        if _en_rango(close, desde, hasta):
            cerrados += 1
        # SLA (sobre lo resuelto en el período): TTR y TTO
        if _en_rango(solve, desde, hasta) and ttr:
            ttr_med += 1
            ttr_ok += 1 if solve <= ttr else 0
        if _en_rango(solve, desde, hasta) and tto and creada:
            # aproximación de 1ª respuesta: se atendió a tiempo si se resolvió antes del TTO
            tto_med += 1
            tto_ok += 1 if solve <= tto else 0

        # Backlog ACTUAL (foto de hoy) + aging
        if st in ABIERTOS:
            backlog.append(t)
            if creada:
                d = (ahora_naive - creada).days
                aging["< 1 día" if d < 1 else "1-3 días" if d < 3 else
                      "3-7 días" if d < 7 else "> 7 días"] += 1

    mttr = round(sum(horas_resol) / len(horas_resol), 1) if horas_resol else None

    # POR TÉCNICO. Un ticket RESUELTO cuenta para QUIEN LO RESOLVIÓ, no para quien lo tenía
    # asignado: los tickets se asignan al equipo, pero el que da la solución es el que lo sacó
    # adelante, y el reporte tiene que reflejar eso. Los que siguen ABIERTOS cuentan para su
    # asignado, que es de quien depende que avancen.
    # Todo con lecturas MASIVAS (una por recurso): pedir followups ticket por ticket llevaba el
    # reporte de ~1s a ~50s.
    if con_tecnico:
        cache_nom = _NAMECACHE.setdefault(cfg_glpi.get("glpi_url"), {})   # nombres persistentes
        resolver = lambda uid: _nombre_usuario(c_lect, uid, cache_nom)  # noqa: E731
        mapa = _mapa_asignados_cache(cfg_glpi, c_ithos, ithos_id)
        humanos = _tecnicos_humanos(cfg_glpi, ithos_id)
        resolutores = _mapa_resolutores(cfg_glpi, c_ithos, humanos)
        for t in tickets:
            tid = int(t.get("id", 0))
            abierto = int(t.get("status", 0)) in ABIERTOS
            if not abierto and not _en_rango(_fecha(t.get("solvedate")), desde, hasta):
                continue
            if not abierto and resolutores.get(tid):
                nombres = [resolver(resolutores[tid])]        # el que dio la solución
            else:
                nombres = [resolver(u) for u in mapa.get(tid, [])] or ["(sin asignar)"]
            for nom in nombres:
                por_tec[nom] = por_tec.get(nom, 0) + 1

    return {
        "empresa": None, "periodo": periodo, "etiqueta": etiqueta,
        "desde": desde.strftime("%d/%m/%Y %H:%M") if desde else "—",
        "hasta": hasta.strftime("%d/%m/%Y %H:%M"),
        "generado": datetime.now(_zona(zona)).strftime("%d/%m/%Y %H:%M"),
        "creados": creados, "resueltos": resueltos, "cerrados": cerrados,
        "backlog": len(backlog),
        "sla_ttr_pct": round(100 * ttr_ok / ttr_med, 1) if ttr_med else None,
        "sla_ttr_ok": ttr_ok, "sla_ttr_total": ttr_med,
        "sla_tto_pct": round(100 * tto_ok / tto_med, 1) if tto_med else None,
        "sla_tto_ok": tto_ok, "sla_tto_total": tto_med,
        "mttr_horas": mttr, "reaperturas": reaperturas,
        "por_prioridad": por_prio, "por_categoria": por_cat,
        "por_estado": por_estado, "por_tecnico": por_tec, "aging": aging,
    }


# ------------------------------------------------------------------ formato TEXTO
def _mttr_txt(h):
    if h is None:
        return "—"
    if h < 1:
        return f"{int(h * 60)} min"
    if h < 48:
        return f"{h:.1f} h"
    return f"{h / 24:.1f} días"


def resumen_texto(k, empresa="", canal="whatsapp"):
    """Resumen legible del reporte. *negrita* para WhatsApp/Telegram; plano para Email/voz."""
    def top(d, n=5):
        return sorted(d.items(), key=lambda x: -x[1])[:n]
    L = []
    L.append(f"📊 *Reporte ITIL — {empresa}*".strip())
    L.append(f"_{k['etiqueta']}_  ·  generado {k['generado']}")
    L.append("")
    L.append(f"*Volumen*: creados {k['creados']} · resueltos {k['resueltos']} · "
             f"cerrados {k['cerrados']} · backlog {k['backlog']}")
    if k["sla_ttr_pct"] is not None:
        L.append(f"*SLA resolución*: {k['sla_ttr_pct']}% ({k['sla_ttr_ok']}/{k['sla_ttr_total']})")
    if k["sla_tto_pct"] is not None:
        L.append(f"*SLA 1ª respuesta*: {k['sla_tto_pct']}% ({k['sla_tto_ok']}/{k['sla_tto_total']})")
    L.append(f"*MTTR* (tiempo medio de resolución): {_mttr_txt(k['mttr_horas'])}")
    if k["por_prioridad"]:
        L.append("*Por prioridad*: " + " · ".join(f"{p}: {n}" for p, n in top(k["por_prioridad"])))
    if k["por_categoria"]:
        L.append("*Por categoría*: " + " · ".join(f"{c}: {n}" for c, n in top(k["por_categoria"])))
    if k["por_tecnico"]:
        L.append("*Por técnico*: " + " · ".join(f"{tc}: {n}" for tc, n in top(k["por_tecnico"])))
    if any(k["aging"].values()):
        L.append("*Backlog por antigüedad*: " + " · ".join(f"{a}: {n}" for a, n in k["aging"].items() if n))
    txt = "\n".join(L)
    if canal in ("email", "voz", "plano"):
        import re
        txt = re.sub(r"\*(.+?)\*", r"\1", txt).replace("_", "")
    return txt


# ------------------------------------------------------------------ formato CSV
def csv_bytes(k, empresa=""):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Reporte ITIL", empresa])
    w.writerow(["Período", k["etiqueta"]])
    w.writerow(["Desde", k["desde"]]); w.writerow(["Hasta", k["hasta"]])
    w.writerow(["Generado", k["generado"]])
    w.writerow([])
    w.writerow(["KPI", "Valor"])
    w.writerow(["Creados", k["creados"]]); w.writerow(["Resueltos", k["resueltos"]])
    w.writerow(["Cerrados", k["cerrados"]]); w.writerow(["Backlog", k["backlog"]])
    w.writerow(["SLA resolución %", k["sla_ttr_pct"]])
    w.writerow(["SLA resolución (ok/total)", f"{k['sla_ttr_ok']}/{k['sla_ttr_total']}"])
    w.writerow(["SLA 1ª respuesta %", k["sla_tto_pct"]])
    w.writerow(["MTTR horas", k["mttr_horas"]])
    for titulo, d in (("Por prioridad", k["por_prioridad"]), ("Por categoría", k["por_categoria"]),
                      ("Por estado", k["por_estado"]), ("Por técnico", k["por_tecnico"]),
                      ("Backlog por antigüedad", k["aging"])):
        w.writerow([]); w.writerow([titulo, "Cantidad"])
        for nombre, cant in sorted(d.items(), key=lambda x: -x[1]):
            w.writerow([nombre, cant])
    return buf.getvalue().encode("utf-8-sig")


# ------------------------------------------------------------------ formato PDF
_AZUL = None


def pdf_bytes(k, empresa=""):
    """Informe PDF profesional (reportlab). Devuelve bytes; None si falta reportlab."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                         TableStyle)
    except Exception as e:  # noqa: BLE001
        log.warning("PDF no disponible (falta reportlab): %s", e)
        return None
    AZUL = colors.HexColor("#1f6feb")
    GRIS = colors.HexColor("#57606a")
    CLARO = colors.HexColor("#eef2f7")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title=f"Reporte ITIL — {empresa}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=20, textColor=AZUL, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=10, textColor=GRIS, spaceAfter=10)
    hsec = ParagraphStyle("hsec", parent=ss["Heading2"], fontSize=12, textColor=AZUL,
                          spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, textColor=GRIS)
    story = []
    story.append(Paragraph(f"Reporte ITIL — {empresa or 'Mesa de ayuda'}", h1))
    story.append(Paragraph(f"{k['etiqueta']} &nbsp;·&nbsp; generado {k['generado']} "
                           f"&nbsp;·&nbsp; período {k['desde']} a {k['hasta']}", sub))

    # Estilos con LEADING (altura de línea) >= fontSize para que el número NO se superponga
    # con la etiqueta (ese era el bug del diseño).
    val_st = ParagraphStyle("val", parent=ss["Normal"], fontSize=18, leading=21,
                            textColor=AZUL, alignment=1, fontName="Helvetica-Bold")
    lab_st = ParagraphStyle("lab", parent=ss["Normal"], fontSize=8, leading=10,
                            textColor=GRIS, alignment=1)

    def tarjetas(items):
        vals = [Paragraph(str(v), val_st) for _, v in items]
        labs = [Paragraph(t, lab_st) for t, _ in items]
        tab = Table([vals, labs], colWidths=[(178 / len(items)) * mm] * len(items))
        tab.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CLARO),
            ("BOX", (0, 0), (-1, -1), 4, colors.white),
            ("INNERGRID", (0, 0), (-1, -1), 4, colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, 0), 12), ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
            ("TOPPADDING", (0, 1), (-1, 1), 0), ("BOTTOMPADDING", (0, 1), (-1, 1), 12)]))
        return tab

    sla_ttr = f"{k['sla_ttr_pct']}%" if k["sla_ttr_pct"] is not None else "—"
    sla_tto = f"{k['sla_tto_pct']}%" if k["sla_tto_pct"] is not None else "—"
    story.append(tarjetas([("Creados", k["creados"]), ("Resueltos", k["resueltos"]),
                           ("Cerrados", k["cerrados"]), ("Backlog", k["backlog"])]))
    story.append(Spacer(1, 6))
    story.append(tarjetas([("SLA resolución", sla_ttr), ("SLA 1ª respuesta", sla_tto),
                           ("MTTR", _mttr_txt(k["mttr_horas"])),
                           ("Reaperturas", k["reaperturas"])]))

    def tabla(titulo, d, c1="Concepto"):
        if not d or not any(d.values()):
            return
        story.append(Paragraph(titulo, hsec))
        filas = [[c1, "Cantidad"]] + [[str(nm), str(ct)]
                 for nm, ct in sorted(d.items(), key=lambda x: -x[1])]
        t = Table(filas, colWidths=[130 * mm, 48 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CLARO]),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(t)

    tabla("Por prioridad", k["por_prioridad"], "Prioridad")
    tabla("Por categoría", k["por_categoria"], "Categoría")
    tabla("Por técnico", k["por_tecnico"], "Técnico")
    tabla("Por estado", k["por_estado"], "Estado")
    tabla("Backlog por antigüedad", k["aging"], "Antigüedad")
    story.append(Spacer(1, 10))
    story.append(Paragraph("Generado por ITHOS · INTELLIHELP — métricas ITIL 4 (medición y "
                           "reporte). Los valores se calculan sobre datos reales del sistema "
                           "de tickets; no se estiman.", small))
    doc.build(story)
    return buf.getvalue()


def generar(cfg_glpi, entidad, periodo="mensual", zona=ZONA_DEFAULT, empresa="",
            con_tecnico=True, desde=None, hasta=None):
    """Atajo: calcula y devuelve dict con kpis + los 3 formatos listos. Con periodo
    'personalizado' + desde/hasta saca un rango a mano (histórico o el tramo que se quiera)."""
    k = calcular(cfg_glpi, entidad, periodo, zona, con_tecnico=con_tecnico,
                 desde=desde, hasta=hasta)
    k["empresa"] = empresa
    return {"kpis": k, "texto": resumen_texto(k, empresa),
            "csv": csv_bytes(k, empresa), "pdf": pdf_bytes(k, empresa)}
