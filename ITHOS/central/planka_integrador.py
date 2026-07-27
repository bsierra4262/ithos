#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrador PLANKA <-> WhatsApp (solo para el cliente ITHOS INTELLIHELP; NO toca SRT).

Mantiene el tablero Kanban del equipo (Planka) 100% actualizado desde WhatsApp:
  · 09:00  -> RESUMEN por persona: @menciona a cada uno con sus tarjetas asignadas.
  · 10:00-18:00, cada hora EN PUNTO (Lun-Vie) -> "¿cómo vas?" por las tarjetas ACTIVAS
    (Haciendo + En espera), salteando las que se movieron hace <1h.
  · ESCUCHA PROACTIVA: cualquiera, desde su número, dice "ithos, terminé/empecé tal tarea"
    (aunque ITHOS no haya preguntado) -> la IA lo interpreta y MUEVE la tarjeta sola.
  · @mención al ASIGNAR una tarjeta a alguien (evento puntual).

El trigger "ithos" ya lo aplica el handler de WhatsApp (comun/whatsapp.py); acá solo llega lo que
ya lo mencionó. Reusa el MISMO grupo/conexión de WhatsApp del cliente. La cadencia (cada 1h) fue
decisión de Brian (ver la memoria del proyecto).
"""

import os
import re
import sys
import json
import asyncio
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from comun import planka as PK   # noqa: E402

log = logging.getLogger("planka.integ")

ZONA_DEFAULT = "America/Argentina/Buenos_Aires"
# Mapeo nombre-de-lista (en el board) -> clave interna. Tolerante a acentos/variantes.
_ALIAS = {
    "por hacer": "por_hacer", "porhacer": "por_hacer", "todo": "por_hacer", "to do": "por_hacer",
    "haciendo": "haciendo", "en curso": "haciendo", "doing": "haciendo",
    "en revision / esperando": "en_espera", "en revisión / esperando": "en_espera",
    "en espera": "en_espera", "esperando": "en_espera", "en revision": "en_espera",
    "en revisión": "en_espera", "revision": "en_espera", "review": "en_espera",
    "hecho": "hecho", "done": "hecho", "terminado": "hecho", "listo": "hecho",
}
_EMOJI_LISTA = {"por_hacer": "📋", "haciendo": "🔨", "en_espera": "⏳", "hecho": "✅"}
_ETIQ = {"por_hacer": "Por hacer", "haciendo": "Haciendo", "en_espera": "En espera", "hecho": "Hecho"}


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


class PlankaIntegrador:
    def __init__(self, cfg, ia, zona=ZONA_DEFAULT):
        self.cfg = cfg or {}
        self.ia = ia
        self.zona = zona
        self.pk = PK.Planka(self.cfg.get("url"), self.cfg.get("api_key"))
        self.ithos_id = str(self.cfg.get("ithos_user_id") or "")
        self.board_id = str(self.cfg.get("board_id") or "")
        self.project_id = str(self.cfg.get("project_id") or "")
        # usuarios: por teléfono (para el remitente de WhatsApp) y por planka_id
        self._por_tel = {}
        self._por_pid = {}
        for u in self.cfg.get("usuarios", []):
            tel = re.sub(r"\D", "", str(u.get("telefono") or ""))
            if tel:
                self._por_tel[tel] = u
            if u.get("planka_id"):
                self._por_pid[str(u["planka_id"])] = u
        self._clave_a_id = {}     # clave interna ('hecho'...) -> list_id
        self._id_a_clave = {}     # list_id -> clave interna
        self._estado = {}         # card_id -> {"list": clave, "ts": epoch del último cambio de lista}
        self._miembros = {}       # card_id -> set(planka_id) del último snapshot (para detectar asignaciones)
        self._resumen_key = None  # día del último resumen enviado ("YYYY-MM-DD")
        self._segui_key = None    # hora del último seguimiento ("YYYY-MM-DD-HH")
        self._ult_pregunta = {}   # planka_id -> [card_ids] que ITHOS preguntó recién (contexto para "esa/eso")
        self._arrancado = False

    # ------------------------------------------------------------------ helpers
    def _ahora(self):
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(self.zona))
        except Exception:  # noqa: BLE001
            return datetime.now()

    def _asegurar_listas(self):
        """Resuelve las listas del board por NOMBRE (robusto a que cambien los IDs cada mes)."""
        if self._clave_a_id:
            return True
        try:
            listas = self.pk.board(self.board_id).get("lists", [])
        except PK.PlankaError as e:
            log.warning("Planka: no pude leer el board %s: %s", self.board_id, e)
            return False
        for l in listas:
            clave = _ALIAS.get(_norm(l.get("name")))
            if clave:
                self._clave_a_id[clave] = str(l["id"])
                self._id_a_clave[str(l["id"])] = clave
        return bool(self._clave_a_id)

    def _snapshot(self):
        """{card_id: {"nombre","list":clave,"list_id","miembros":set(pid)}} del board actual."""
        inc = self.pk.board(self.board_id)
        cards = inc.get("cards", []) if isinstance(inc, dict) else []
        memb = inc.get("cardMemberships", []) if isinstance(inc, dict) else []
        por_card = {}
        for m in memb:
            por_card.setdefault(str(m.get("cardId")), set()).add(str(m.get("userId")))
        snap = {}
        for c in cards:
            lid = str(c.get("listId"))
            clave = self._id_a_clave.get(lid)
            if not clave:                          # tarjeta en archive/trash u otra lista -> ignorar
                continue
            cid = str(c["id"])
            snap[cid] = {"nombre": c.get("name", ""), "list": clave, "list_id": lid,
                         "miembros": por_card.get(cid, set())}
        return snap

    def _cards_usuario(self, pid, snap, listas=None):
        """Tarjetas asignadas a `pid`, opcionalmente filtradas por claves de lista."""
        out = []
        for cid, c in snap.items():
            if pid in c["miembros"] and (listas is None or c["list"] in listas):
                out.append((cid, c))
        return out

    # ------------------------------------------------------------------ textos
    def _linea_tarjetas(self, cards):
        """Agrupa 'nombre (Lista)' por lista para un texto lindo."""
        por = {}
        for _cid, c in cards:
            por.setdefault(c["list"], []).append(c["nombre"])
        partes = []
        for clave in ("por_hacer", "haciendo", "en_espera"):
            if por.get(clave):
                partes.append(f"{_EMOJI_LISTA[clave]} *{_ETIQ[clave]}*: " + ", ".join(por[clave]))
        return partes

    def resumen(self, u, snap):
        """Texto del RESUMEN diario para una persona (o None si no tiene nada pendiente)."""
        cards = self._cards_usuario(str(u["planka_id"]), snap,
                                    listas=("por_hacer", "haciendo", "en_espera"))
        if not cards:
            return None
        partes = self._linea_tarjetas(cards)
        nom = u["nombre"].split()[0]
        return (f"Buen día {nom} 👋 Esto tenés para hoy:\n" + "\n".join(partes) +
                "\n\n(Cuando avances, avisame: \"ithos, terminé tal tarea\".)")

    def seguimiento(self, u, snap, ahora):
        """Texto del '¿cómo vas?' horario: solo Haciendo + En espera, salteando lo movido hace <1h.
        Registra qué tarjetas preguntó (contexto para resolver un 'terminé eso' vago después)."""
        pid = str(u["planka_id"])
        activos = []
        for cid, c in self._cards_usuario(pid, snap, listas=("haciendo", "en_espera")):
            ts = self._estado.get(cid, {}).get("ts", 0)
            if ahora.timestamp() - ts < 3600:      # se movió hace <1h -> no preguntar
                continue
            activos.append((cid, c["nombre"]))
        if not activos:
            self._ult_pregunta.pop(pid, None)
            return None
        self._ult_pregunta[pid] = [cid for cid, _ in activos]   # contexto para el próximo mensaje
        nom = u["nombre"].split()[0]
        lista = " y ".join(f"\"{n}\"" for _, n in activos)
        return (f"{nom}, ¿cómo venís con {lista}? "
                "Si ya terminaste o pasaste a otra, decime (\"ithos, terminé X\") y lo actualizo.")

    # ------------------------------------------------------------------ interpretar mensajes
    def interpretar(self, remitente_tel, texto):
        """Un miembro escribió (ya con 'ithos'). Si MUEVE una tarjeta suya o pide CREAR una tarea nueva,
        lo hace y devuelve la confirmación; si no es sobre el tablero, devuelve None (lo maneja el asistente)."""
        tel = re.sub(r"\D", "", str(remitente_tel or ""))
        u = self._por_tel.get(tel) or self._por_tel.get(tel[-10:])   # tolera prefijo país
        if not u or not (texto or "").strip():
            return None
        if not self._asegurar_listas():
            return None
        try:
            snap = self._snapshot()
        except PK.PlankaError:
            return None
        pid = str(u["planka_id"])
        cards = self._cards_usuario(pid, snap)
        by_id = {cid: c for cid, c in cards}
        lista_cards = [{"id": cid, "nombre": c["nombre"], "lista": _ETIQ[c["list"]]} for cid, c in cards]
        ctx = [by_id[cid]["nombre"] for cid in self._ult_pregunta.get(pid, []) if cid in by_id]
        equipo = [x["nombre"] for x in self._por_pid.values()]
        try:
            r = self.ia.chat(
                "Sos el asistente del tablero Kanban del equipo (listas: Por hacer, Haciendo, En espera, "
                "Hecho). Un integrante escribió por WhatsApp. Decidí la acción:\n"
                "- 'mover': movió/actualizó UNA de SUS tarjetas -> card_id + lista destino ('hecho'=terminó, "
                "'haciendo'=empezó, 'en_espera'=trabada, 'por_hacer'=todavía no). Movés SOLO si queda CLARO "
                "cuál tarjeta (por tema/nombre). Si es VAGO ('terminé eso') usá el CONTEXTO; si sigue ambiguo, "
                "'nada' (NO adivines).\n"
                "- 'crear': pide dar de ALTA una tarea nueva ('cargá/creá/agregá/anotá tal cosa') -> titulo "
                "(claro y corto), lista destino (default 'por_hacer'), y para (nombre de la persona del "
                "EQUIPO a asignar; si dice 'a mí' o no aclara, poné 'yo').\n"
                "- 'nada': saludo/pregunta/otra cosa que no toca el tablero.\n"
                "Respondé SOLO JSON: {\"accion\":\"mover\"|\"crear\"|\"nada\",\"card_id\":\"\",\"lista\":"
                "\"por_hacer\"|\"haciendo\"|\"en_espera\"|\"hecho\",\"titulo\":\"\",\"para\":\"\"}.\n"
                "SUS TARJETAS: " + json.dumps(lista_cards, ensure_ascii=False) +
                "\nEQUIPO: " + json.dumps(equipo, ensure_ascii=False) +
                (("\nCONTEXTO (le preguntaste recién por estas): " + json.dumps(ctx, ensure_ascii=False)) if ctx else ""),
                texto, json_out=True)
            d = json.loads(r)
        except Exception as e:  # noqa: BLE001
            log.warning("Planka: no pude interpretar el mensaje: %s", str(e)[:120])
            return None
        if d.get("accion") == "crear":
            return self._crear(u, d)
        if d.get("accion") == "mover":
            return self._mover(u, cards, d)
        return None

    def _mover(self, u, cards, d):
        cid = str(d.get("card_id") or "")
        clave = d.get("lista")
        c = next((c for i, c in cards if i == cid), None)
        if not c or clave not in self._clave_a_id or c["list"] == clave:
            return None
        try:
            self.pk.mover_tarjeta(cid, self._clave_a_id[clave])
            self._estado.setdefault(cid, {})["list"] = clave
            self._estado[cid]["ts"] = self._ahora().timestamp()
            log.info("Planka: '%s' -> %s (por %s)", c["nombre"], clave, u["nombre"])
            return f"✅ Listo, moví \"{c['nombre']}\" a *{_ETIQ[clave]}*."
        except PK.PlankaError as e:  # noqa: BLE001
            log.warning("Planka: no pude mover la tarjeta %s: %s", cid, e)
            return None

    def _crear(self, u, d):
        """Alta de una tarea NUEVA por WhatsApp: la crea en la lista pedida (default Por hacer) y la
        asigna a la persona indicada (o al que escribió)."""
        titulo = (d.get("titulo") or "").strip()
        if not titulo:
            return None
        clave = d.get("lista") if d.get("lista") in self._clave_a_id else "por_hacer"
        para = _norm(d.get("para") or "")
        asignado = u
        if para and para not in ("yo", "mi", "mí", "para mi", "para mí", "a mi", "a mí"):
            asignado = self._match_persona(para) or u
        try:
            card = self.pk.crear_tarjeta(self._clave_a_id[clave], titulo)
            self.pk.asignar(card["id"], str(asignado["planka_id"]))
            log.info("Planka: creada '%s' en %s para %s (por %s).", titulo, clave,
                     asignado["nombre"], u["nombre"])
            quien = "vos" if asignado is u else asignado["nombre"].split()[0]
            return f"✅ Creé \"{titulo}\" en *{_ETIQ[clave]}* para {quien}."
        except PK.PlankaError as e:  # noqa: BLE001
            log.warning("Planka: no pude crear la tarjeta: %s", e)
            return None

    def _match_persona(self, nombre):
        """Matchea un nombre (aunque sea parcial: 'carlos', 'ale') a un usuario del equipo. None si no."""
        n = _norm(nombre)
        if not n:
            return None
        for x in self._por_pid.values():
            xn = _norm(x["nombre"])
            if n == xn or n in xn.split() or xn.split()[0] == n or (len(n) >= 3 and n in xn):
                return x
        return None

    # ------------------------------------------------------------------ loop
    async def vigilar(self, enviar, stop=None):
        """Loop: detecta asignaciones (@mención) + dispara el resumen (09:00) y el seguimiento
        (10:00-18:00 en punto, Lun-Vie). `enviar(texto, telefonos)` manda al grupo con @menciones."""
        self.pk.asegurar_acceso(self.project_id, self.board_id, self.ithos_id)
        if not self._asegurar_listas():
            log.warning("Planka integrador: no pude resolver las listas del board; reintento en loop.")
        log.info("Planka integrador activo (board %s, %d usuarios).", self.board_id, len(self._por_pid))
        while stop is None or not stop.is_set():
            try:
                await asyncio.to_thread(self._tick, enviar)
            except Exception as e:  # noqa: BLE001
                log.warning("Planka integrador tick: %s", e)
            await asyncio.sleep(30)

    def _tick(self, enviar):
        if not self._asegurar_listas():
            return
        snap = self._snapshot()
        ahora = self._ahora()
        # 1) detectar cambios de lista (para el skip <1h) y ASIGNACIONES nuevas (@mención)
        primero = not self._arrancado
        for cid, c in snap.items():
            prev = self._estado.get(cid)
            if prev is None or prev.get("list") != c["list"]:
                self._estado[cid] = {"list": c["list"], "ts": ahora.timestamp()}
            nuevos = c["miembros"] - self._miembros.get(cid, set())
            if not primero:                        # no avisar en el primer snapshot (baseline)
                for pid in nuevos:
                    u = self._por_pid.get(pid)
                    if u and pid != self.ithos_id:
                        enviar(f"🔔 Te asignaron la tarea \"{c['nombre']}\" "
                               f"({_ETIQ[c['list']]}).", [u["telefono"]])
            self._miembros[cid] = set(c["miembros"])
        # limpiar tarjetas borradas del estado
        for cid in list(self._estado):
            if cid not in snap:
                self._estado.pop(cid, None); self._miembros.pop(cid, None)
        self._arrancado = True

        # 2) scheduler (solo días hábiles Lun-Vie)
        if ahora.weekday() >= 5:
            return
        hhmm = ahora.strftime("%H:%M")
        dia = ahora.strftime("%Y-%m-%d")
        # RESUMEN 09:00 (una vez al día)
        if hhmm == self.cfg.get("resumen_hora", "09:00") and self._resumen_key != dia:
            self._resumen_key = dia
            for u in self._por_pid.values():
                txt = self.resumen(u, snap)
                if txt:
                    enviar(txt, [u["telefono"]])
            log.info("Planka: resumen diario enviado (%s).", dia)
        # SEGUIMIENTO 10:00-18:00 en punto (una vez por hora)
        desde = int(str(self.cfg.get("seguimiento_desde", "10:00"))[:2])
        hasta = int(str(self.cfg.get("seguimiento_hasta", "18:00"))[:2])
        hkey = ahora.strftime("%Y-%m-%d-%H")
        if ahora.minute == 0 and desde <= ahora.hour <= hasta and self._segui_key != hkey:
            self._segui_key = hkey
            for u in self._por_pid.values():
                txt = self.seguimiento(u, snap, ahora)
                if txt:
                    enviar(txt, [u["telefono"]])
            log.info("Planka: seguimiento horario enviado (%s).", hkey)
