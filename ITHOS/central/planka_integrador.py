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
  · ROLLOVER automático (de Agosto en adelante, ver planka_rollover.py): un proyecto por mes, un board
    por semana (bloques del mes: 1-7, 8-14, ...) y un board MENSUAL de archivo. Al cambiar de semana/mes
    crea lo que falte, ARRASTRA lo no terminado y al cerrar el mes lo consolida en su MENSUAL; al cerrar
    el AÑO junta los 12 meses en "AÑO <a>" y borra los proyectos mensuales. Agrega al equipo como miembro
    de cada board (para poder asignarlos). Todo con la fecha REAL (nada se dispara antes de tiempo). Julio
    y meses anteriores quedan como están (config 'mes_legacy'). Idempotente y sobrevive reinicios.

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

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, ".."))
sys.path.insert(0, _AQUI)
from comun import planka as PK   # noqa: E402
import planka_rollover as RO      # noqa: E402

log = logging.getLogger("planka.integ")

# Estado del período (semana/board en curso) para el rollover: sobrevive reinicios.
_DATA = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
try:
    os.makedirs(_DATA, exist_ok=True)
except OSError:
    _DATA = _AQUI

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
        self._activo_prev = set() # pids con tareas activas el último seguimiento (para "terminó -> ¿qué sigue?")
        # --- rollover automático semanal/mensual (de Agosto en adelante; ver planka_rollover.py) ---
        _equipo = [u.get("planka_id") for u in self.cfg.get("usuarios", []) if u.get("planka_id")]
        self._roll = RO.Rollover(self.pk, self.ithos_id, _equipo)
        self._board_cfg = self.board_id           # board configurado (Julio 'MENSUAL' = mensual heredado)
        self._mes_legacy = str(self.cfg.get("mes_legacy") or "")  # "YYYY-MM": ese mes y anteriores = mensual
        self._periodo_key = None                  # semana en curso ("YYYY-MM-Wn"); None = aún no arrancó
        self._mes_key = None                      # mes en curso ("YYYY-MM"), para detectar el cierre de mes
        self._meses_cerrados = set()              # meses ya archivados en su board MENSUAL (no re-copiar)
        self._anios_cerrados = set()              # años ya consolidados en "AÑO <a>" (no re-cerrar)
        self._estado_file = os.path.join(_DATA, "planka_estado_periodo.json")
        self._reenviar_flag = os.path.join(_DATA, "planka_reenviar_resumen.flag")  # bandera de reenvío manual
        self._cargar_periodo()                    # restaura board/semana/mes del último arranque (si hubo)

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

    # ------------------------------------------------------------------ período (rollover semanal/mensual)
    def _cargar_periodo(self):
        """Restaura {semana, board, mes, meses_cerrados} del último arranque, para no re-arrastrar ni
        re-consolidar ni perder el hilo si ITHOS se reinició (incluso justo en un cambio de semana/mes)."""
        try:
            d = json.load(open(self._estado_file, encoding="utf-8"))
            if d.get("board_id"):
                self.board_id = str(d["board_id"])
                self._periodo_key = d.get("skey")
                self._mes_key = d.get("mes_key")
                self._meses_cerrados = set(d.get("meses_cerrados") or [])
                self._anios_cerrados = set(d.get("anios_cerrados") or [])
        except (OSError, ValueError):
            pass

    def _guardar_periodo(self):
        try:
            json.dump({"skey": self._periodo_key, "board_id": self.board_id,
                       "mes_key": self._mes_key, "meses_cerrados": sorted(self._meses_cerrados),
                       "anios_cerrados": sorted(self._anios_cerrados)},
                      open(self._estado_file, "w", encoding="utf-8"), ensure_ascii=False)
        except OSError as e:  # noqa: BLE001
            log.debug("Planka: no pude guardar el estado del período: %s", e)

    def _asegurar_periodo(self, ahora):
        """Resuelve el BOARD del período actual (semana = bloque del mes). Para 'mes_legacy' y anteriores
        usa el board mensual configurado (Julio). Después: proyecto del mes + board de la semana + MENSUAL
        (creándolos si faltan), CONSOLIDA en su MENSUAL el mes que cierra, y ARRASTRA lo no terminado al
        nuevo período. Barato si el período no cambió."""
        skey = RO.semana_key(ahora)
        if skey == self._periodo_key and self.board_id and self._clave_a_id:
            return                                            # mismo período: nada que hacer
        primera_vez = self._periodo_key is None
        mkey = RO.mes_key(ahora)
        if self._mes_legacy and mkey <= self._mes_legacy:
            nuevo = self._board_cfg                           # modo mensual heredado (Julio y anteriores)
        else:
            # ¿cambió el MES (ya en modo semanal)? consolidar el mes que cierra en su MENSUAL (una sola vez).
            if (self._mes_key and self._mes_key != mkey and not primera_vez
                    and self._mes_key > self._mes_legacy and self._mes_key not in self._meses_cerrados):
                try:
                    a, m = self._mes_key.split("-")
                    cop = self._roll.copiar_a_mensual(int(a), int(m))
                    self._meses_cerrados.add(self._mes_key)
                    log.info("Planka rollover: cerré %s -> %d tarjeta(s) archivadas en MENSUAL.",
                             self._mes_key, cop)
                except Exception as e:  # noqa: BLE001
                    log.warning("Planka rollover: no pude consolidar el mes %s: %s", self._mes_key, e)
            try:
                nuevo = self._roll.asegurar_semana(ahora).get("board_id")
            except Exception as e:  # noqa: BLE001
                log.warning("Planka rollover: no pude asegurar el período: %s", e)
                return
        if nuevo and nuevo != self.board_id:
            prev = self.board_id
            self.board_id = nuevo
            self._clave_a_id, self._id_a_clave = {}, {}
            self._asegurar_listas()
            if not primera_vez and prev:                      # cambió de semana/mes -> arrastrar lo pendiente
                try:
                    mov = self._roll.arrastrar(prev, nuevo)
                    if mov:
                        log.info("Planka rollover: arrastré %d tarjeta(s) al nuevo período (%s).", mov, skey)
                except Exception as e:  # noqa: BLE001
                    log.warning("Planka rollover: no pude arrastrar: %s", e)
                self._arrancado = False                       # re-baseline (no avisar 'asignación' de lo arrastrado)
                self._miembros, self._estado = {}, {}
        elif nuevo and not self._clave_a_id:
            self._asegurar_listas()
        # CIERRE DE AÑO: al entrar (con la fecha REAL) a un año nuevo estando en modo semanal, junta
        # el año viejo en "AÑO <a>" (un board por mes) y borra sus proyectos mensuales. Lo pendiente
        # de diciembre ya se arrastró a enero más arriba, así que borrar el año viejo no pierde nada.
        # Sólo corre cuando el año realmente cambia (dic->ene); nunca antes.
        if not primera_vez and self._mes_key and not (self._mes_legacy and mkey <= self._mes_legacy):
            anio_viejo, anio_nuevo = self._mes_key[:4], mkey[:4]
            if anio_viejo != anio_nuevo and anio_viejo not in self._anios_cerrados:
                try:
                    cop, borr = self._roll.consolidar_y_cerrar_anio(int(anio_viejo))
                    self._anios_cerrados.add(anio_viejo)
                    log.info("Planka rollover: cerré el AÑO %s -> %d tarjeta(s) archivadas, %d proyecto(s) borrados.",
                             anio_viejo, cop, borr)
                except Exception as e:  # noqa: BLE001
                    log.warning("Planka rollover: no pude cerrar el año %s: %s", anio_viejo, e)
        self._mes_key = mkey
        self._periodo_key = skey
        self._guardar_periodo()

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
    @staticmethod
    def _limpiar(nombre):
        """Deja el título de la tarjeta prolijo para leer: sin espacios de más ni punto/coma final."""
        return re.sub(r"\s+", " ", (nombre or "").strip()).rstrip(" .,;")

    def _bloques_tarjetas(self, cards):
        """Texto agrupado por lista, UNA tarjeta por línea (legible aunque haya muchas)."""
        por = {}
        for _cid, c in cards:
            por.setdefault(c["list"], []).append(c["nombre"])
        bloques = []
        for clave in ("por_hacer", "haciendo", "en_espera"):
            items = por.get(clave)
            if not items:
                continue
            lineas = "\n".join(f"   •  {self._limpiar(n)}" for n in items)
            bloques.append(f"{_EMOJI_LISTA[clave]} *{_ETIQ[clave]}*  ({len(items)})\n{lineas}")
        return "\n\n".join(bloques)

    def resumen(self, u, snap):
        """RESUMEN diario para una persona (o None si no tiene nada pendiente). Una tarjeta por línea,
        agrupada por lista, para que se lea claro aunque tenga muchas."""
        cards = self._cards_usuario(str(u["planka_id"]), snap,
                                    listas=("por_hacer", "haciendo", "en_espera"))
        if not cards:
            return None
        nom = u["nombre"].split()[0]
        return (f"Buen día {nom} 👋\n"
                f"Esto es lo que tenés para hoy:\n\n"
                f"{self._bloques_tarjetas(cards)}\n\n"
                "Cuando termines o avances con alguna, escribime: _ithos, terminé…_")

    def seguimiento(self, u, snap, ahora):
        """'¿cómo vas?' horario: solo Haciendo + En espera, salteando lo movido hace <1h. Una tarjeta
        por línea si hay varias. Registra qué preguntó (contexto para resolver un 'terminé eso' vago)."""
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
        if len(activos) == 1:
            cuerpo = f"¿cómo venís con *{self._limpiar(activos[0][1])}*?"
        else:
            lineas = "\n".join(f"   •  {self._limpiar(n)}" for _, n in activos)
            cuerpo = "¿cómo venís con estas?\n" + lineas
        return (f"{nom}, {cuerpo}\n\n"
                "Si ya terminaste alguna o la pasaste a otra etapa, avisame "
                "(_ithos, terminé…_) y la actualizo.")

    def _tiene_activas(self, pid, snap):
        """¿La persona tiene alguna tarjeta en Haciendo o En revisión/Esperando? (sin el skip <1h)."""
        return bool(self._cards_usuario(pid, snap, listas=("haciendo", "en_espera")))

    def pregunta_siguiente(self, u, snap):
        """Cuando la persona TERMINÓ todo lo que tenía en Haciendo + En revisión/Esperando: le pregunta
        qué sigue. Le ofrece lo que tenga en 'Por hacer' o que cargue una tarea nueva."""
        nom = u["nombre"].split()[0]
        pendientes = [c["nombre"] for _cid, c in
                      self._cards_usuario(str(u["planka_id"]), snap, listas=("por_hacer",))]
        if pendientes:
            lineas = "\n".join(f"   •  {self._limpiar(n)}" for n in pendientes)
            cola = ("Te queda esto en *Por hacer*:\n" + lineas +
                    "\n\n¿Con cuál seguís? Decime _ithos, empiezo…_ y la paso a *Haciendo*, "
                    "o _ithos, agregá…_ si querés cargar una nueva.")
        else:
            cola = "¿Qué tarea vas a hacer ahora? Decime _ithos, agregá…_ y la creo."
        return f"¡Bien {nom}! 🙌 Terminaste todo lo que tenías en curso.\n{cola}"

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
            self.pk.agregar_miembro_board(self.board_id, str(asignado["planka_id"]))  # miembro del board primero
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
        if self.project_id:
            self.pk.asegurar_acceso(self.project_id, self.board_id, self.ithos_id)
        try:
            self._asegurar_periodo(self._ahora())             # resuelve la semana/mes actual (o board legacy)
        except Exception as e:  # noqa: BLE001
            log.warning("Planka: no pude resolver el período inicial: %s", e)
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
        ahora = self._ahora()
        self._asegurar_periodo(ahora)              # crea/rota el board de la semana/mes si hace falta
        if not self._asegurar_listas():
            return
        snap = self._snapshot()
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

        # Reenvío MANUAL del resumen (bandera que crea soporte): manda el resumen a todos UNA vez,
        # con el formato actual. Sirve para corregir un envío mal formateado sin esperar al otro día.
        if os.path.exists(self._reenviar_flag):
            try:
                os.remove(self._reenviar_flag)
            except OSError:
                pass
            n = 0
            for u in self._por_pid.values():
                txt = self.resumen(u, snap)
                if txt:
                    enviar(txt, [u["telefono"]])
                    n += 1
            log.info("Planka: resumen REENVIADO manualmente a %d persona(s).", n)

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
        # SEGUIMIENTO 10:00-18:00 en punto (una vez por hora): pregunta SOLO por Haciendo + En
        # revisión/Esperando. Cuando alguien TERMINA todo lo que tenía en curso, le pregunta qué sigue.
        desde = int(str(self.cfg.get("seguimiento_desde", "10:00"))[:2])
        hasta = int(str(self.cfg.get("seguimiento_hasta", "18:00"))[:2])
        hkey = ahora.strftime("%Y-%m-%d-%H")
        if ahora.minute == 0 and desde <= ahora.hour <= hasta and self._segui_key != hkey:
            self._segui_key = hkey
            activo_ahora = set()
            for u in self._por_pid.values():
                pid = str(u["planka_id"])
                if self._tiene_activas(pid, snap):
                    activo_ahora.add(pid)
                    txt = self.seguimiento(u, snap, ahora)     # ¿cómo venís? (respeta el skip <1h)
                    if txt:
                        enviar(txt, [u["telefono"]])
                elif pid in self._activo_prev:                 # tenía activas y ya no -> terminó
                    txt = self.pregunta_siguiente(u, snap)
                    if txt:
                        enviar(txt, [u["telefono"]])
            self._activo_prev = activo_ahora                   # base para detectar el próximo "terminó"
            log.info("Planka: seguimiento horario enviado (%s).", hkey)
