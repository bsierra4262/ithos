#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rollover automático de PLANKA (solo el cliente ITHOS INTELLIHELP; NO toca SRT).

De AGOSTO en adelante el tablero del equipo se organiza por SEMANAS DENTRO DEL MES:
  · un PROYECTO por mes   -> "Agosto 2026", "Septiembre 2026", ...  (queda de historial)
  · un BOARD por semana   -> "Semana 1 · 01–07/08", ... (bloques de 7 días del MES, no cruzan
    de mes) con las 4 listas (Por hacer / Haciendo / En revisión / Esperando / Hecho)
  · un BOARD "MENSUAL"    -> el archivo del mes: al CERRAR el mes se copian ahí TODAS las
    tarjetas del mes (hechas y pendientes), en su lista final.

Al cambiar de semana o de mes se crea lo que falte y se ARRASTRA lo NO terminado (todo lo que
no esté en "Hecho") al nuevo período, en su MISMA lista; lo terminado queda de historial. Al
cambiar de MES, además, se consolida el mes que cierra en su board "MENSUAL".

Cada persona del equipo se agrega como MIEMBRO de cada board (requisito de Planka para poder
asignarle tarjetas). Todo es IDEMPOTENTE. Julio (y meses anteriores) NO se tocan: siguen con su
board mensual heredado (config 'mes_legacy').
"""
import re
import logging
from datetime import date, datetime, timedelta

log = logging.getLogger("planka.rollover")

MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Nombres EXACTOS de las listas (igual que el board de Julio) y su orden.
LISTAS = ["Por hacer", "Haciendo", "En revisión / Esperando", "Hecho"]
MENSUAL = "MENSUAL"                       # board de archivo del mes (pestaña extra)

# Nombre de lista -> clave interna (tolerante a acentos/variantes).
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
    """Nombre de lista -> clave ('por_hacer'|'haciendo'|'en_espera'|'hecho') o None si no es nuestra."""
    return _ALIAS.get(_norm(nombre))


def nombre_mes(anio, mes):
    return f"{MESES[mes]} {anio}"


def ultimo_dia(anio, mes):
    d = date(anio, 12, 31) if mes == 12 else date(anio, mes + 1, 1) - timedelta(days=1)
    return d.day


def semanas_del_mes(anio, mes):
    """Semanas = BLOQUES de 7 días DENTRO del mes: [1-7],[8-14],[15-21],[22-28],[29-fin].
    Nunca cruzan de mes, así el mes cierra EXACTO el último día. Devuelve
    [{'num','desde','hasta','nombre'}]."""
    ult = ultimo_dia(anio, mes)
    out, n, d = [], 1, 1
    while d <= ult:
        h = min(d + 6, ult)
        out.append({"num": n, "desde": date(anio, mes, d), "hasta": date(anio, mes, h),
                    "nombre": f"Semana {n} · {d:02d}–{h:02d}/{mes:02d}"})
        d += 7
        n += 1
    return out


def semana_actual(f):
    """(anio, mes, dict_semana) del bloque que contiene a f (por su día del mes)."""
    d = f.date() if isinstance(f, datetime) else f
    sems = semanas_del_mes(d.year, d.month)
    idx = min((d.day - 1) // 7, len(sems) - 1)
    return d.year, d.month, sems[idx]


def semana_key(f):
    """Clave estable de la semana ('YYYY-MM-Wn'): detecta cuándo cambió el período (semana o mes)."""
    d = f.date() if isinstance(f, datetime) else f
    idx = min((d.day - 1) // 7, len(semanas_del_mes(d.year, d.month)) - 1) + 1
    return f"{d.year}-{d.month:02d}-W{idx}"


def mes_key(f):
    """Clave 'YYYY-MM' del mes de f (con bloques, cada día pertenece a su propio mes)."""
    d = f.date() if isinstance(f, datetime) else f
    return f"{d.year}-{d.month:02d}"


class Rollover:
    """Crea/resuelve (idempotente) el proyecto del mes, sus boards semanales + MENSUAL y las 4 listas,
    agrega al equipo como miembro de cada board, arrastra lo no terminado y consolida el mes al cerrar.
    Cachea los IDs para no repreguntar."""

    def __init__(self, pk, ithos_id, equipo=None):
        self.pk = pk
        self.ithos_id = str(ithos_id or "")
        self.equipo = [str(x) for x in (equipo or []) if x]   # planka_ids del equipo (para asignarles)
        self._proj = {}        # nombre_proyecto -> project_id
        self._boards = {}      # (project_id, nombre_board) -> board_id
        self._listas = {}      # board_id -> {clave: list_id}

    # ------------------------------------------------------------------ índice / creación
    def _reindex(self):
        items, inc = self.pk.proyectos()
        for p in items:
            self._proj[p.get("name")] = str(p.get("id"))
        for b in (inc.get("boards", []) if isinstance(inc, dict) else []):
            self._boards[(str(b.get("projectId")), b.get("name"))] = str(b.get("id"))

    def _sumar_miembros(self, project_id, board_id):
        """ITHOS (manager+editor) + TODO el equipo como miembros del board, para poder asignarles."""
        if self.ithos_id:
            self.pk.asegurar_acceso(project_id, board_id, self.ithos_id)
        for uid in self.equipo:
            self.pk.agregar_miembro_board(board_id, uid)

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
        self._sumar_miembros(project_id, bid)               # equipo miembro (solo al crear)
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

    def asegurar_mes(self, anio, mes):
        """Proyecto del mes + boards de TODAS las semanas (bloques) + board MENSUAL + listas + miembros.
        Devuelve {'project_id','semanas':{num:board_id},'mensual_board_id'}."""
        pid = self.asegurar_proyecto(nombre_mes(anio, mes))
        sems = semanas_del_mes(anio, mes)
        semanas = {}
        for s in sems:
            bid = self.asegurar_board(pid, s["nombre"], s["num"] * POS)
            self.asegurar_listas(bid)
            semanas[s["num"]] = bid
        mens = self.asegurar_board(pid, MENSUAL, (len(sems) + 1) * POS)   # pestaña extra, al final
        self.asegurar_listas(mens)
        return {"project_id": pid, "semanas": semanas, "mensual_board_id": mens}

    def asegurar_semana(self, f):
        """Asegura el mes y devuelve el board de la semana ACTUAL:
        {'proyecto','project_id','board_id','mensual_board_id','listas','semana','skey'}."""
        anio, mes, sem = semana_actual(f)
        info = self.asegurar_mes(anio, mes)
        bid = info["semanas"][sem["num"]]
        return {"proyecto": nombre_mes(anio, mes), "project_id": info["project_id"],
                "board_id": bid, "mensual_board_id": info["mensual_board_id"],
                "listas": self.asegurar_listas(bid), "semana": sem["nombre"], "skey": semana_key(f)}

    # ------------------------------------------------------------------ arrastre (carry-forward)
    def arrastrar(self, board_origen, board_destino):
        """Mueve al board destino lo NO terminado del origen, en su MISMA lista (por clave).
        Lo que está en 'Hecho' NO se mueve (queda de historial). Devuelve cuántas movió."""
        if not board_origen or not board_destino or board_origen == board_destino:
            return 0
        inc = self.pk.board(board_origen)
        clave_por_lista = {str(l["id"]): clave_lista(l.get("name")) for l in inc.get("lists", [])}
        destino = self.asegurar_listas(board_destino)        # {clave: list_id}
        movidas = 0
        for c in (inc.get("cards", []) if isinstance(inc, dict) else []):
            cl = clave_por_lista.get(str(c.get("listId")))
            if not cl or cl == "hecho" or cl not in destino:
                continue
            try:
                self.pk.mover_a_board(str(c["id"]), board_destino, destino[cl], (movidas + 1) * POS)
                movidas += 1
            except Exception as e:  # noqa: BLE001
                log.warning("Planka rollover: no pude mover la card %s: %s", c.get("id"), e)
        return movidas

    # ------------------------------------------------------------------ cierre de mes (archivo MENSUAL)
    def copiar_a_mensual(self, anio, mes):
        """Copia TODAS las tarjetas de las semanas del mes al board MENSUAL (archivo del mes), en su
        misma lista y conservando asignados. Devuelve cuántas copió. (Guardar el 'ya cerrado' es
        responsabilidad del que llama, para no duplicar si se corre dos veces.)"""
        info = self.asegurar_mes(anio, mes)
        mens = info["mensual_board_id"]
        destino = self.asegurar_listas(mens)                 # {clave: list_id}
        copiadas = 0
        for _num, bid in sorted(info["semanas"].items()):
            inc = self.pk.board(bid)
            id2clave = {str(l["id"]): clave_lista(l.get("name")) for l in inc.get("lists", [])}
            memb = {}
            for m in inc.get("cardMemberships", []):
                memb.setdefault(str(m.get("cardId")), []).append(str(m.get("userId")))
            for c in inc.get("cards", []):
                cl = id2clave.get(str(c.get("listId")))
                if not cl or cl not in destino:
                    continue
                try:
                    nueva = self.pk.crear_tarjeta(destino[cl], c.get("name", ""),
                                                  c.get("description"), (copiadas + 1) * POS)
                    for uid in memb.get(str(c["id"]), []):
                        self.pk.asignar(nueva["id"], uid)
                    copiadas += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("Planka rollover: no pude copiar la card %s a MENSUAL: %s", c.get("id"), e)
        return copiadas
