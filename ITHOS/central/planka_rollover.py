#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rollover automático de PLANKA (solo el cliente ITHOS INTELLIHELP; NO toca SRT).

De AGOSTO en adelante el tablero del equipo se organiza por SEMANAS:
  · un PROYECTO por mes   -> "Agosto 2026", "Septiembre 2026", ...  (queda de historial)
  · un BOARD por semana   -> "Semana 1 · 03/08–07/08", ... con las 4 listas
    (Por hacer / Haciendo / En revisión / Esperando / Hecho)

Cada semana ISO (lunes) pertenece al proyecto del mes de SU lunes -> el reparto es
determinístico y sin huecos (cada día cae en exactamente una semana). Al cambiar de
semana o de mes, ITHOS ARRASTRA lo NO terminado (todo lo que no esté en "Hecho") al nuevo
board, en su MISMA lista; lo terminado queda como historial de esa semana.

Todo es IDEMPOTENTE: si el proyecto / board / lista ya existen, sólo se resuelven sus IDs.
Julio (y meses anteriores) NO se tocan: siguen con su board mensual (config 'mes_legacy').
"""
import re
import logging
from datetime import date, datetime, timedelta

log = logging.getLogger("planka.rollover")

MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Nombres EXACTOS de las listas (igual que el board de Julio) y su orden.
LISTAS = ["Por hacer", "Haciendo", "En revisión / Esperando", "Hecho"]

# Igual que el integrador: nombre de lista -> clave interna (tolerante a acentos/variantes).
_ALIAS = {
    "por hacer": "por_hacer", "haciendo": "haciendo",
    "en revision / esperando": "en_espera", "en revisión / esperando": "en_espera",
    "en espera": "en_espera", "esperando": "en_espera",
    "en revision": "en_espera", "en revisión": "en_espera", "hecho": "hecho",
}
POS = 65536


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def clave_lista(nombre):
    """Nombre de lista -> clave ('por_hacer'|'haciendo'|'en_espera'|'hecho') o None si no es una de las nuestras."""
    return _ALIAS.get(_norm(nombre))


def nombre_mes(anio, mes):
    return f"{MESES[mes]} {anio}"


def _lunes(f):
    """Lunes (date) de la semana ISO que contiene a f (acepta date o datetime)."""
    d = f.date() if isinstance(f, datetime) else f
    return d - timedelta(days=d.weekday())


def semanas_del_mes(anio, mes):
    """Semanas cuyo LUNES cae en ese mes (cada una = lun..vie, la semana laboral).
    Devuelve [{'num','lunes','viernes','nombre'}]. Sin huecos: cada día pertenece a la
    semana de su lunes (la última semana del mes puede terminar en el mes siguiente)."""
    d1 = date(anio, mes, 1)
    mon = d1 - timedelta(days=d1.weekday())          # lunes de la semana del día 1 (quizá del mes anterior)
    while mon.month != mes or mon.year != anio:      # avanzar al primer lunes DE este mes
        mon += timedelta(days=7)
    out, n = [], 1
    while mon.month == mes and mon.year == anio:
        vie = mon + timedelta(days=4)
        out.append({"num": n, "lunes": mon, "viernes": vie,
                    "nombre": f"Semana {n} · {mon:%d/%m}–{vie:%d/%m}"})
        mon += timedelta(days=7)
        n += 1
    return out


def semana_actual(f):
    """(anio, mes, dict_semana) del período que contiene a f (según su lunes)."""
    mon = _lunes(f)
    for s in semanas_del_mes(mon.year, mon.month):
        if s["lunes"] == mon:
            return mon.year, mon.month, s
    vie = mon + timedelta(days=4)                    # fallback defensivo (no debería ocurrir)
    return mon.year, mon.month, {"num": 0, "lunes": mon, "viernes": vie,
                                 "nombre": f"Semana · {mon:%d/%m}–{vie:%d/%m}"}


def semana_key(f):
    """Clave estable de la semana ISO ('YYYY-Www'): sirve para detectar cuándo cambió el período."""
    iso = _lunes(f).isocalendar()
    return f"{iso[0]}-W{int(iso[1]):02d}"


def mes_key(f):
    """Clave 'YYYY-MM' del MES al que pertenece la semana de f (el mes de su lunes)."""
    return _lunes(f).strftime("%Y-%m")


class Rollover:
    """Crea/resuelve (idempotente) el proyecto del mes, sus boards semanales y las 4 listas,
    y arrastra lo no terminado al cambiar de período. Cachea los IDs para no repreguntar."""

    def __init__(self, pk, ithos_id):
        self.pk = pk
        self.ithos_id = str(ithos_id or "")
        self._proj = {}        # nombre_proyecto -> project_id
        self._boards = {}      # (project_id, nombre_board) -> board_id
        self._listas = {}      # board_id -> {clave: list_id}

    # ------------------------------------------------------------------ índice / creación
    def _reindex(self):
        """Relee proyectos+boards existentes (para no duplicar lo que ya está)."""
        items, inc = self.pk.proyectos()
        for p in items:
            self._proj[p.get("name")] = str(p.get("id"))
        for b in (inc.get("boards", []) if isinstance(inc, dict) else []):
            self._boards[(str(b.get("projectId")), b.get("name"))] = str(b.get("id"))

    def asegurar_proyecto(self, nombre):
        if nombre in self._proj:
            return self._proj[nombre]
        self._reindex()
        if nombre in self._proj:
            return self._proj[nombre]
        pid = str(self.pk.crear_proyecto(nombre).get("id"))
        self._proj[nombre] = pid
        log.info("Planka rollover: proyecto '%s' creado (%s).", nombre, pid)
        return pid

    def asegurar_board(self, project_id, nombre, position=POS):
        k = (str(project_id), nombre)
        if k in self._boards:
            return self._boards[k]
        self._reindex()
        if k in self._boards:
            return self._boards[k]
        bid = str(self.pk.crear_board(project_id, nombre, position).get("id"))
        self._boards[k] = bid
        if self.ithos_id:                                    # ITHOS = manager + editor del board nuevo
            self.pk.asegurar_acceso(project_id, bid, self.ithos_id)
        log.info("Planka rollover: board '%s' creado (%s).", nombre, bid)
        return bid

    def asegurar_listas(self, board_id):
        """{clave: list_id} del board. Reusa las que ya están; crea SÓLO las que falten."""
        if board_id in self._listas:
            return self._listas[board_id]
        inc = self.pk.board(board_id)
        por_clave = {}
        for l in (inc.get("lists", []) if isinstance(inc, dict) else []):
            cl = clave_lista(l.get("name"))
            if cl:
                por_clave[cl] = str(l["id"])
        for i, nom in enumerate(LISTAS):
            cl = clave_lista(nom)
            if cl not in por_clave:
                nid = str(self.pk.crear_lista(board_id, nom, (i + 1) * POS).get("id"))
                por_clave[cl] = nid
                log.info("Planka rollover: lista '%s' creada en board %s.", nom, board_id)
        self._listas[board_id] = por_clave
        return por_clave

    def asegurar_semana(self, f):
        """Asegura el proyecto del mes + TODOS sus boards semanales + las 4 listas de cada uno,
        y devuelve el board de la semana ACTUAL:
        {'proyecto','project_id','board_id','listas','semana','skey'}."""
        anio, mes, sem = semana_actual(f)
        pnombre = nombre_mes(anio, mes)
        pid = self.asegurar_proyecto(pnombre)
        board_actual = None
        for s in semanas_del_mes(anio, mes):
            bid = self.asegurar_board(pid, s["nombre"], s["num"] * POS)
            self.asegurar_listas(bid)
            if s["lunes"] == sem["lunes"]:
                board_actual = bid
        listas = self.asegurar_listas(board_actual) if board_actual else {}
        return {"proyecto": pnombre, "project_id": pid, "board_id": board_actual,
                "listas": listas, "semana": sem["nombre"], "skey": semana_key(f)}

    # ------------------------------------------------------------------ arrastre (carry-forward)
    def arrastrar(self, board_origen, board_destino):
        """Mueve al board destino lo NO terminado del origen, en su MISMA lista (por clave).
        Lo que está en 'Hecho' NO se mueve (queda de historial). Devuelve cuántas movió."""
        if not board_origen or not board_destino or board_origen == board_destino:
            return 0
        inc = self.pk.board(board_origen)
        clave_por_lista = {}
        for l in (inc.get("lists", []) if isinstance(inc, dict) else []):
            cl = clave_lista(l.get("name"))
            if cl:
                clave_por_lista[str(l["id"])] = cl
        destino = self.asegurar_listas(board_destino)        # {clave: list_id}
        movidas = 0
        for c in (inc.get("cards", []) if isinstance(inc, dict) else []):
            cl = clave_por_lista.get(str(c.get("listId")))
            if not cl or cl == "hecho":
                continue
            dest_list = destino.get(cl)
            if not dest_list:
                continue
            try:
                self.pk.mover_a_board(str(c["id"]), board_destino, dest_list, (movidas + 1) * POS)
                movidas += 1
            except Exception as e:  # noqa: BLE001
                log.warning("Planka rollover: no pude mover la card %s: %s", c.get("id"), e)
        return movidas
