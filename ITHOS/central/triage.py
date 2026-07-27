#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Triage-apply del Central. Clasifica un ticket con la IA enchufable (cerebro) y lo
aplica en GLPI como el usuario ITHOS: categoría, prioridad, SLA/OLA, asignación
(ITHOS + responsable), primera respuesta y estado (en espera / en curso).
Portado del monolito, con IA pluggable. Además: seguimiento (respuesta del cliente
-> en curso + aviso; recordatorio diario).

Los mapeos (categorías, SLA, usuarios) son de SRT/ITH; en el producto se configuran
por cliente.
"""

import os
import re
import sys
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from comun import ia as IA          # noqa: E402
from comun import glpi as G         # noqa: E402
import cerebro                      # noqa: E402

log = logging.getLogger("triage")

CATEGORIAS = {"MOLINETES": 11, "TERMINALES": 13, "HIK-CENTRAL": 12, "INTERFACE": 15}
NIVEL_SLA = {
    "LEVE":      {"slas_id_tto": 1, "slas_id_ttr": 6, "olas_id_tto": 1, "olas_id_ttr": 2},
    "GRAVE":     {"slas_id_tto": 2, "slas_id_ttr": 3, "olas_id_tto": 4, "olas_id_ttr": 3},
    "MUY GRAVE": {"slas_id_tto": 4, "slas_id_ttr": 5, "olas_id_tto": 5, "olas_id_ttr": 6},
}
PRIORIDAD_NUM = {"Baja": 2, "Media": 3, "Alta": 4, "Urgente": 5}
NIVEL_POR_PRIORIDAD = {"Baja": "LEVE", "Media": "LEVE", "Alta": "GRAVE",
                       "Urgente": "MUY GRAVE"}
RESPONSABLES = {"bsierra": 7, "jayala": 8}
NOMBRES = {"bsierra": "Brian Sierra", "jayala": "Alejandro Ayala"}
ITHOS_ID = 28
TECNICOS = {28, 7, 8}
TECNICOS_HUMANOS = {7, 8}          # técnicos personas (sin ITHOS): sus comentarios pueden resolver

ZONA_DEFAULT = "America/Argentina/Buenos_Aires"
# Horario de atención por defecto: Lunes(0)-Viernes(4) de 09:00 a 18:00 (coincide con el calendario
# del SLA de SRT). Configurable por cliente vía cfg['horario_atencion']={'dias':[0-6],'desde','hasta'}.
_HORARIO_DEFAULT = {"dias": [0, 1, 2, 3, 4], "desde": "09:00", "hasta": "18:00"}


def _ahora_zona(cfg, ahora=None):
    """AHORA en la zona horaria del cliente (no la del servidor)."""
    if ahora is not None:
        return ahora
    zona = cfg.get("zona_horaria") or ZONA_DEFAULT
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(zona))
    except Exception:  # noqa: BLE001
        return datetime.now()


def en_horario_atencion(cfg, ahora=None):
    """True si AHORA (zona del cliente) está DENTRO del horario de atención (default Lun-Vie 9-18)."""
    h = cfg.get("horario_atencion") or _HORARIO_DEFAULT
    ahora = _ahora_zona(cfg, ahora)
    if ahora.weekday() not in h.get("dias", _HORARIO_DEFAULT["dias"]):
        return False
    hhmm = ahora.strftime("%H:%M")
    return str(h.get("desde", "09:00")) <= hhmm < str(h.get("hasta", "18:00"))


def proximo_inicio_horario(cfg, ahora=None):
    """datetime (aware) del PRÓXIMO inicio del horario de atención (default próximo día hábil 09:00)."""
    h = cfg.get("horario_atencion") or _HORARIO_DEFAULT
    dias = h.get("dias", _HORARIO_DEFAULT["dias"])
    desde = str(h.get("desde", "09:00"))
    hh, mm = int(desde[:2]), int(desde[3:5])
    ahora = _ahora_zona(cfg, ahora)
    cand = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
    for _ in range(9):                       # como mucho una semana hacia adelante
        if cand.weekday() in dias and cand > ahora:
            return cand
        cand = (cand + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return cand


def _nota_interna_horario(dt):
    """Nota PRIVADA (solo técnicos) avisando que el ticket entró fuera de horario y cuándo reabre solo.
    El CLIENTE NO ve esto: solo ve la respuesta profesional normal (sin avisos de horario)."""
    cuando = dt.strftime("%d/%m a las %H:%M") if dt else "el próximo día hábil"
    return ("Nota interna (el cliente no la ve): el ticket ingresó FUERA del horario de atención, así "
            f"que queda EN ESPERA y se reabrirá solo (EN CURSO) {cuando}.")


# El saludo al solicitante vive en comun/glpi.py (compartido con el camino de voz aplicar_ciclo).
_saludo_solicitante = G.saludo_solicitante


class Triage:
    def __init__(self, cfg_glpi, cfg_ia, gestor=None):
        self.cfg_glpi = cfg_glpi
        self.cli = G.GLPIClient(cfg_glpi, token=cfg_glpi["glpi_ithos_token"])
        # Token de LECTURA para resolver el nombre del SOLICITANTE (el de ithos no puede leer /User).
        self._tok_lect = (cfg_glpi.get("glpi_superadmin_token") or cfg_glpi.get("glpi_user_token")
                          or cfg_glpi["glpi_ithos_token"])
        self._nombres = {}          # caché uid -> nombre de pila del solicitante
        self.ia = IA.crear_texto(cfg_ia, gestor=gestor)

    def _nombre_solicitante(self, ticket):
        """Nombre de PILA de quien ABRIÓ el ticket (solicitante), para saludarlo en la 1ª respuesta.
        NO usa nombres del TEXTO del ticket (esos son la persona AFECTADA). '' si no se resuelve.
        Usa el token de LECTURA (el de ithos no puede leer /User) y cachea por uid."""
        try:
            uid = int(ticket.get("users_id_recipient") or 0)
        except (TypeError, ValueError):
            uid = 0
        if not uid:
            return ""
        if uid not in self._nombres:
            self._nombres[uid] = G.nombre_pila(G.sesion(self.cfg_glpi, self._tok_lect), uid)
        return self._nombres[uid]

    def _tecnicos_asignados(self, tid):
        """user-ids de los TÉCNICOS ya asignados (Ticket_User type 2) al ticket. Se usa para RESPETAR
        una asignación MANUAL: si ya hay un técnico humano, ITHOS no vuelve a auto-asignar el default."""
        try:
            us = self.cli.request(f"/Ticket/{tid}/Ticket_User")
            return {int(u.get("users_id") or 0) for u in us
                    if isinstance(u, dict) and int(u.get("type") or 0) == 2}
        except Exception:  # noqa: BLE001
            return set()

    def procesar(self, ticket):
        tid = ticket.get("id")
        # ¿ITHOS YA triageó este ticket? El marcador es que ITHOS esté ASIGNADO. Si SÍ -> NO re-triagear:
        # respetar los cambios MANUALES del técnico (categoría/asignación/prioridad); si volvió a 'Nuevo',
        # solo lo sacamos de ahí para que no quede en loop. El PRIMER triage (ITHOS aún NO asignado) SÍ
        # categoriza/asigna aunque el ticket venga MAL CARGADO (esa corrección inicial siempre se hace).
        asignados = set()
        try:
            self.cli.abrir()
            asignados = self._tecnicos_asignados(tid)
            if ITHOS_ID in asignados and int(ticket.get("status") or 1) == 1:
                self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 2}})
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.cli.cerrar()
        if ITHOS_ID in asignados:
            log.info("Triage: #%s ya triado por ITHOS; respeto los cambios manuales (no re-categorizo "
                     "ni re-asigno).", tid)
            return None
        # -- PRIMER triage --
        solicitante = self._nombre_solicitante(ticket)
        a = cerebro.clasificar_ticket(self.ia, ticket.get("name", ""),
                                      ticket.get("content", ""), solicitante=solicitante)
        if not a:
            log.warning("Triage: no se pudo clasificar el ticket %s", tid)
            return None
        # El saludo SIEMPRE es para el solicitante (quien abrió el ticket), no para la persona
        # afectada que aparezca en el texto. Se corrige de forma determinística por las dudas.
        a["primera_respuesta"] = _saludo_solicitante(a.get("primera_respuesta", ""), solicitante)
        prioridad = a.get("prioridad", "Media")
        nivel = NIVEL_POR_PRIORIDAD.get(prioridad, "LEVE")
        num = PRIORIDAD_NUM.get(prioridad, 3)
        resp_login = a.get("responsable", "bsierra")
        resp_id = RESPONSABLES.get(resp_login, RESPONSABLES["bsierra"])
        try:
            self.cli.abrir()
            campos = {"urgency": num, "impact": num, "priority": num}
            cat = CATEGORIAS.get(a.get("categoria"))
            # 1er triage: CATEGORIZA SIEMPRE (aunque venga mal cargado con otra categoría). El respeto a
            # la categoría manual es AGUAS ARRIBA (si ITHOS ya lo triageó, ni entra acá).
            if cat:
                campos["itilcategories_id"] = cat
            campos.update(NIVEL_SLA[nivel])
            self.cli.request(f"/Ticket/{tid}", "PUT", {"input": campos})
            # ASIGNACIÓN: ITHOS siempre. El responsable AUTOMÁTICO (bsierra/jayala) SOLO si NO hay ya un
            # técnico HUMANO asignado a mano -> se respeta una reasignación manual previa.
            a_poner = [ITHOS_ID]
            if not (asignados & TECNICOS_HUMANOS):
                a_poner.append(resp_id)
            for uid in a_poner:
                if uid in asignados:
                    continue
                try:
                    self.cli.request("/Ticket_User", "POST",
                                     {"input": {"tickets_id": tid, "users_id": uid,
                                                "type": 2}})
                except Exception:  # noqa: BLE001
                    pass  # ya asignado (ERROR_GLPI_ADD): estado final correcto
            # Estado según el HORARIO: si el ticket ENTRÓ fuera del horario de atención y NO necesita datos
            # del cliente, queda EN ESPERA hasta que abra el horario y la agenda lo reabre solo. OJO: el
            # CLIENTE ve SOLO la respuesta profesional; lo del horario va como NOTA INTERNA (no se entera).
            necesita = bool(a.get("necesita_info"))
            fuera = (not necesita) and (not en_horario_atencion(self.cfg_glpi))
            # PÚBLICO: la 1ª respuesta tal cual. NO FATAL: si GLPI la rechaza (p. ej. el usuario MySQL de
            # GLPI sin permiso INSERT), igual dejamos el ticket categorizado/asignado/con estado.
            try:
                self.cli.request("/ITILFollowup", "POST",
                                 {"input": {"itemtype": "Ticket", "items_id": tid,
                                            "content": a.get("primera_respuesta", "")}})
            except Exception as e:  # noqa: BLE001
                log.warning("Triage #%s: no pude agregar la 1ª respuesta (¿permiso INSERT de GLPI en "
                            "glpi_itilfollowups?): %s", tid, str(e)[:120])
            # PRIVADO (is_private=1, SOLO técnicos — el cliente NO lo ve): la nota del cerebro (ticket mal
            # cargado / dato faltante / corrección) y, si entró fuera de horario, el aviso interno de que
            # queda EN ESPERA y cuándo reabre solo.
            internas = []
            nt = (a.get("nota_tecnico") or "").strip()
            if nt:
                internas.append(nt)
            dt_reapertura = proximo_inicio_horario(self.cfg_glpi) if fuera else None
            if fuera:
                internas.append(_nota_interna_horario(dt_reapertura))
            for _txt in internas:
                try:
                    self.cli.request("/ITILFollowup", "POST",
                                     {"input": {"itemtype": "Ticket", "items_id": tid,
                                                "content": _txt, "is_private": 1}})
                except Exception as e:  # noqa: BLE001
                    log.warning("Triage #%s: no pude agregar una nota interna (¿permiso INSERT?): %s",
                                tid, str(e)[:120])
            self.cli.request(f"/Ticket/{tid}", "PUT",
                             {"input": {"status": 4 if (necesita or fuera) else 2}})
        except Exception as e:  # noqa: BLE001
            log.error("Triage: fallo al aplicar el ticket %s: %s", tid, e)
            return None
        finally:
            self.cli.cerrar()
        if fuera:                               # reapertura AUTOMÁTICA y SILENCIOSA al abrir el horario
            self._agendar_reapertura_horario(tid, dt_reapertura)
        estado_txt = ("EN ESPERA (datos)" if necesita
                      else "EN ESPERA (fuera de horario)" if fuera else "EN CURSO")
        log.info("Triage OK #%s: cat=%s prio=%s -> %s (%s)", tid, a.get("categoria"),
                 prioridad, resp_login, estado_txt)
        return {"prioridad": prioridad, "nivel": nivel, "responsable_login": resp_login,
                "responsable_nombre": NOMBRES.get(resp_login, resp_login),
                "categoria": a.get("categoria"), "necesita_info": necesita,
                "fuera_horario": fuera}

    def _agendar_reapertura_horario(self, tid, dt=None):
        """Agenda la reapertura (EN CURSO) del ticket al comenzar el próximo horario de atención.
        Reusa la AGENDA (mismo reactivador que los pospuestos): one-shot y se auto-limpia. La
        reactivación es SILENCIOSA para el cliente (silencioso=True): pasa a EN CURSO sin ningún
        mensaje público — el cliente NO se entera del corte; el equipo sí recibe el aviso interno."""
        try:
            from comun import agenda
            cliente = self.cfg_glpi.get("nombre_cliente") or "cliente"
            dt = dt or proximo_inicio_horario(self.cfg_glpi)
            agenda.programar(cliente, tid, dt.timestamp(),
                             f"al comenzar el horario de atención ({dt.strftime('%d/%m %H:%M')})",
                             silencioso=True)
            log.info("Triage #%s: fuera de horario -> EN ESPERA; reapertura SILENCIOSA agendada para %s.",
                     tid, dt.strftime("%Y-%m-%d %H:%M"))
        except Exception as e:  # noqa: BLE001
            log.warning("Triage #%s: no pude agendar la reapertura por horario: %s", tid, str(e)[:120])

    def poner_en_curso(self, tid):
        try:
            self.cli.abrir()
            self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 2}})
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Triage: no pude poner en curso #%s: %s", tid, e)
            return False
        finally:
            self.cli.cerrar()

    def marcar_resuelto(self, tid, solucion=""):
        """Pasa el ticket a RESUELTO (status 5). Intenta cargar la SOLUCIÓN (así queda documentada
        y GLPI lo deja en Resuelto); si el perfil no permite ITILSolution, cae a cambiar el estado."""
        try:
            self.cli.abrir()
            try:
                self.cli.request("/ITILSolution", "POST", {"input": {
                    "itemtype": "Ticket", "items_id": tid,
                    "content": solucion or "Resuelto por el equipo de soporte técnico."}})
            except Exception:  # noqa: BLE001
                self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 5}})
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Triage: no pude marcar resuelto #%s: %s", tid, e)
            return False
        finally:
            self.cli.cerrar()

    def recordar(self, tid, texto):
        try:
            self.cli.abrir()
            self.cli.request("/ITILFollowup", "POST",
                             {"input": {"itemtype": "Ticket", "items_id": tid, "content": texto}})
            self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 4}})
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self.cli.cerrar()

    def _followup(self, tid, texto):
        # NO FATAL: si GLPI rechaza el followup (p. ej. el usuario MySQL de GLPI sin permiso INSERT en
        # glpi_itilfollowups), NO abortamos el cambio de estado que hace el caller (en espera / cerrar /
        # etc.). El comentario no se agrega, pero el ESTADO del ticket igual queda correcto.
        try:
            self.cli.request("/ITILFollowup", "POST",
                             {"input": {"itemtype": "Ticket", "items_id": tid, "content": texto}})
        except Exception as e:  # noqa: BLE001
            log.warning("No pude agregar el comentario a #%s (¿permiso INSERT de GLPI en "
                        "glpi_itilfollowups?): %s", tid, str(e)[:120])

    def nota_interna(self, tid, texto):
        """Followup PRIVADO (is_private=1): SOLO lo ven los TÉCNICOS (el cliente no). Abre y cierra su
        propia sesión (se llama desde el ciclo). NO FATAL."""
        try:
            self.cli.abrir()
            self.cli.request("/ITILFollowup", "POST",
                             {"input": {"itemtype": "Ticket", "items_id": tid,
                                        "content": texto, "is_private": 1}})
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("No pude agregar la nota interna a #%s: %s", tid, str(e)[:120])
            return False
        finally:
            self.cli.cerrar()

    def pedir_confirmacion(self, tid):
        """Ticket resuelto: ITHOS pide al cliente que confirme antes de cerrar."""
        try:
            self.cli.abrir()
            self._followup(tid, "Le informamos que su solicitud fue resuelta. Por "
                           "favor, confírmenos si ya puede fichar con normalidad para "
                           "cerrar el ticket; si el inconveniente persiste, respóndanos "
                           "y lo reabrimos de inmediato. Saludos, Soporte ITH.")
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self.cli.cerrar()

    def recordar_confirmacion(self, tid):
        """Ticket RESUELTO y el cliente aún no respondió: recordatorio (una vez por día) para que
        confirme o avise que sigue. Es un recordatorio LEGÍTIMO (le pedimos que confirme), distinto
        de los recordatorios falsos de 'EN ESPERA de datos' que no se envían."""
        try:
            self.cli.abrir()
            self._followup(tid, "Le recordamos que su ticket figura como resuelto. Por favor "
                           "confírmenos si ya puede fichar con normalidad para cerrarlo; si el "
                           "inconveniente continúa, respóndanos y lo reabrimos. Soporte ITH.")
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self.cli.cerrar()

    def cerrar(self, tid):
        try:
            self.cli.abrir()
            self._followup(tid, "El cliente confirmó la solución. Cerramos el ticket. "
                           "Gracias por su colaboración. Soporte ITH.")
            self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 6}})
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self.cli.cerrar()

    def reabrir(self, tid):
        try:
            self.cli.abrir()
            self._followup(tid, "El cliente indica que el inconveniente continúa. "
                           "Reabrimos el ticket para seguir trabajando en la solución.")
            self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 2}})
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self.cli.cerrar()

    def cliente_confirma(self, texto):
        """Usa la IA para decidir si el cliente CONFIRMA que se solucionó.
        Devuelve True/False, o None si la IA no está disponible (para NO cerrar ni
        reabrir por error — se reintenta en el próximo ciclo)."""
        try:
            r = self.ia.chat(
                "Interpretá la INTENCIÓN real del cliente (aunque sea informal o breve). "
                "confirma=true SOLO si expresa que su problema YA quedó resuelto / que ya "
                "funciona / que está conforme. Si duda, se queja, pregunta o dice que sigue "
                "igual: false. Respondé SOLO JSON: {\"confirma\": true|false}.",
                texto, json_out=True)
            import json as _j
            return bool(_j.loads(r).get("confirma"))
        except Exception:  # noqa: BLE001
            return None

    def tecnico_resolvio(self, texto):
        """Usa la IA para decidir si el comentario de un TÉCNICO indica que el ticket QUEDÓ
        RESUELTO (no solo un avance). Devuelve True/False, o None si la IA no está disponible."""
        try:
            r = self.ia.chat(
                "Sos un asistente de mesa de ayuda. Un TÉCNICO dejó un comentario en un ticket. "
                "Decidí si el comentario indica que el problema YA quedó RESUELTO/solucionado y "
                "listo para cerrar (resuelto=true), o si es solo un AVANCE, un pedido de datos o "
                "que sigue en gestión (resuelto=false). Ante la duda, false. "
                "Respondé SOLO JSON: {\"resuelto\": true|false}.",
                texto, json_out=True)
            import json as _j
            return bool(_j.loads(r).get("resuelto"))
        except Exception:  # noqa: BLE001
            return None

    def explica_procedimiento(self, texto):
        """IA: ¿la resolución EXPLICA el procedimiento (qué se hizo, con detalle útil para la base de
        conocimiento) -> True, o es solo un cierre vago tipo 'listo/solucionado/ya funciona' SIN explicar
        cómo -> False? None si la IA no está (para NO molestar al técnico por error)."""
        try:
            r = self.ia.chat(
                "Un técnico documentó cómo resolvió un ticket de soporte técnico. Decidí si el texto "
                "EXPLICA el procedimiento —qué hizo, con pasos o detalle suficiente para que otro lo "
                "repita y para una BASE DE CONOCIMIENTO— (explica=true), o si es solo un cierre vago del "
                "tipo 'solucionado', 'listo', 'ya funciona', 'resuelto', 'ok' SIN explicar cómo se hizo "
                "(explica=false). Ante la duda, false. Respondé SOLO JSON: {\"explica\": true|false}.",
                texto, json_out=True)
            import json as _j
            return bool(_j.loads(r).get("explica"))
        except Exception:  # noqa: BLE001
            return None

    def tecnico_pide_confirmacion(self, texto):
        """IA: para AVANZAR, ¿el CLIENTE debe responder/confirmar/coordinar algo (coordinar un día u
        horario para un trabajo/visita; reubicar/mover/instalar/reemplazar algo a acordar con el cliente;
        aprobar/dar el OK; quedar a la espera de una decisión del cliente)? -> pide_confirmacion=true,
        AUNQUE esté redactado impersonal ('se deberá coordinar la reubicación', 'próximos pasos:
        coordinar el reemplazo'). Si es una SOLUCIÓN ya aplicada, un avance interno o info que no
        requiere respuesta del cliente: false. None si la IA no está."""
        try:
            r = self.ia.chat(
                "Un TÉCNICO dejó un comentario en un ticket de soporte. Decidí si, para poder AVANZAR, "
                "el CLIENTE debe responder / confirmar / coordinar algo ANTES de continuar.\n"
                "- pide_confirmacion=true si el comentario o sus 'próximos pasos' implican: coordinar un "
                "día u horario para hacer un trabajo o una visita; reubicar, mover, instalar o reemplazar "
                "algo que hay que ACORDAR con el cliente; pedir una aprobación, un OK o una confirmación; "
                "o quedar a la espera de una decisión o respuesta del cliente. Cuenta AUNQUE esté escrito "
                "en tercera persona o de forma impersonal (ej.: 'se deberá coordinar la reubicación', "
                "'próximos pasos: coordinar el reemplazo y la visita', 'a coordinar con el cliente', "
                "'queda sujeto a la confirmación del cliente').\n"
                "- pide_confirmacion=false SOLO si es una SOLUCIÓN ya aplicada y lista, un avance "
                "puramente interno del equipo, o información que NO necesita ninguna respuesta del "
                "cliente.\n"
                "Respondé SOLO JSON: {\"pide_confirmacion\": true|false}.",
                texto, json_out=True)
            import json as _j
            return bool(_j.loads(r).get("pide_confirmacion"))
        except Exception:  # noqa: BLE001
            return None

    def poner_en_espera_pedido(self, tid, comentario_tecnico):
        """El técnico pidió coordinar/confirmar algo con el cliente -> EN ESPERA (status 4) + un
        followup pidiéndole al CLIENTE que confirme/responda respecto de lo que planteó el técnico."""
        try:
            msg = self._mensaje_pedir_confirmacion(comentario_tecnico)
            self.cli.abrir()
            self._followup(tid, msg)
            self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 4}})
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self.cli.cerrar()

    def _mensaje_pedir_confirmacion(self, comentario_tecnico):
        """Redacta, PARA EL CLIENTE, el pedido de confirmación/coordinación basado en lo que planteó el
        técnico (ej. 'coordinemos un día'). Si la IA no está, usa un texto genérico."""
        try:
            r = self.ia.chat(
                "Un TÉCNICO de soporte le pide algo al cliente en un ticket (coordinar un día/horario, "
                "confirmar una acción, dar el OK para un trabajo, etc.). Redactá un mensaje BREVE y "
                "profesional PARA EL CLIENTE (de usted) que le transmita ese pedido y le solicite que "
                "RESPONDA/CONFIRME para avanzar. No inventes datos; basate en el comentario. Terminá "
                "con 'Quedamos a la espera de su respuesta. Soporte ITH.'. Respondé SOLO el mensaje.",
                comentario_tecnico, json_out=False)
            r = (r or "").strip()
            if r:
                # Garantizamos el marcador estable (_MARCA_COORDINACION) por si la IA no lo incluyó:
                # el ciclo lo usa para NO volver a pedir coordinación del mismo comentario tras un
                # reinicio (ver _es_pedido_coordinacion / _coordinacion_despues_de).
                if _MARCA_COORDINACION not in r.lower():
                    r += " Quedamos a la espera de su respuesta. Soporte ITH."
                return r
        except Exception:  # noqa: BLE001
            pass
        return ("Para avanzar con su solicitud necesitamos coordinar/confirmar algunos detalles con "
                "usted. Por favor respóndanos para continuar. Quedamos a la espera de su respuesta. "
                "Soporte ITH.")


def frase_triage(res, t):
    return (f"Ticket número {t.get('id')} procesado. Prioridad {res['prioridad']}, "
            f"nivel {res['nivel']}. Asignado a {res['responsable_nombre']}. "
            f"Primera respuesta enviada.")


def mensaje_triage(res, t):
    return (f"✅ *Ticket #{t.get('id')} procesado por ITHOS*\n"
            f"Categoría: {res.get('categoria')} · Prioridad: {res['prioridad']} "
            f"({res['nivel']})\nAsignado a: {res['responsable_nombre']} (+ ITHOS)\n"
            f"Primera respuesta enviada.")


def _nombre_usuario(cliente, uid):
    try:
        u = cliente.request(f"/User/{uid}")
        if isinstance(u, list):
            u = u[0] if u else {}
        n = f"{u.get('firstname') or ''} {u.get('realname') or ''}".strip()
        return n or u.get("name") or f"usuario {uid}"
    except Exception:  # noqa: BLE001
        return f"usuario {uid}"


# Firmas estables (subcadenas) de los textos de `pedir_confirmacion` y `recordar_confirmacion`.
# Si se cambian esos textos, mantener estas subcadenas dentro para que la detección siga andando.
_MARCA_CONFIRMACION = "su solicitud fue resuelta"
_MARCA_RECORDATORIO = "le recordamos que su ticket figura como resuelto"
_MARCA_COORDINACION = "a la espera de su respuesta"   # marcador estable del pedido de COORDINACIÓN
_MARCA_PROCEDIMIENTO = "documentá paso a paso"   # marcador de la nota interna que pide el procedimiento
_NOTA_PEDIR_PROCEDIMIENTO = (
    "Nota interna (el cliente no la ve): para nuestra base de conocimiento, por favor documentá "
    "PASO A PASO qué hiciste para resolver este ticket (el procedimiento), no solo que quedó resuelto. "
    "Así queda el registro y nos sirve para resolver más rápido los casos futuros.")
_INTERVALO_RECORDATORIO = timedelta(hours=24)   # recordatorio de confirmación: una vez por día


def _es_aviso_confirmacion(f):
    """True si el followup `f` es un aviso de ITHOS pidiendo/recordando la confirmación."""
    if int(f.get("users_id") or 0) not in TECNICOS:
        return False
    c = str(f.get("content", "")).lower()
    return _MARCA_CONFIRMACION in c or _MARCA_RECORDATORIO in c


def _ya_pidio_confirmacion(fu):
    """True si ITHOS ya dejó el pedido (o un recordatorio) de confirmación en el ticket. Lee la
    verdad del propio GLPI (no el estado en memoria), así NO se repite el pedido tras un reinicio."""
    return any(_es_aviso_confirmacion(f) for f in fu)


def _es_pedido_coordinacion(f):
    """True si el followup `f` es un pedido de ITHOS de coordinar/confirmar algo con el cliente."""
    if int(f.get("users_id") or 0) not in TECNICOS:
        return False
    return _MARCA_COORDINACION in str(f.get("content", "")).lower()


def _coordinacion_despues_de(fu, tec_fu_id):
    """True si ITHOS ya dejó un pedido de coordinación POSTERIOR al comentario `tec_fu_id`. Así el
    pedido NO se repite para el MISMO comentario del técnico tras un reinicio (el estado en memoria
    se pierde), pero SÍ se puede volver a pedir si el técnico deja un comentario NUEVO más adelante.
    Lee la verdad del propio GLPI, no la memoria."""
    return any(_es_pedido_coordinacion(f) and int(f.get("id") or 0) > int(tec_fu_id or 0) for f in fu)


def _ya_pidio_procedimiento(fu):
    """True si ITHOS ya pidió (por nota interna) el procedimiento paso a paso (no repetir tras un
    reinicio). Lee la verdad de GLPI, no la memoria."""
    return any(int(f.get("users_id") or 0) in TECNICOS
               and _MARCA_PROCEDIMIENTO in str(f.get("content", "")).lower() for f in fu)


def _texto_resolucion(cliente, tid, fu):
    """Junta el texto de la RESOLUCIÓN para que la IA juzgue si explica el procedimiento: la
    ITILSolution documentada (si hay) + el último comentario de un técnico HUMANO. '' si no hay nada."""
    partes = []
    try:
        sol = cliente.request(f"/Ticket/{tid}/ITILSolution")
        if isinstance(sol, list):
            for s in sol:
                c = re.sub(r"<[^>]+>", " ", str(s.get("content", ""))).strip()
                if c:
                    partes.append(c)
    except Exception:  # noqa: BLE001
        pass
    tec = [f for f in fu if int(f.get("users_id") or 0) in TECNICOS_HUMANOS]
    if tec:
        c = re.sub(r"<[^>]+>", " ", str(tec[-1].get("content", ""))).strip()
        if c:
            partes.append(c)
    return "  ".join(partes).strip()


def _parse_fecha(s):
    """Parsea una fecha de GLPI ('YYYY-MM-DD HH:MM:SS') a datetime naive. None si no se puede."""
    txt = str(s or "")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(txt, fmt)
        except (ValueError, TypeError):
            pass
    return None


def _ultimo_aviso_confirmacion(fu):
    """Fecha del último aviso de confirmación de ITHOS (pedido o recordatorio), o None. Se usa
    para el recordatorio DIARIO de forma robusta ante reinicios (no depende del estado en memoria)."""
    fechas = [_parse_fecha(f.get("date_creation") or f.get("date"))
              for f in fu if _es_aviso_confirmacion(f)]
    fechas = [d for d in fechas if d]
    return max(fechas) if fechas else None


def _followups_por_ticket(cliente, tam=2000):
    """{ticket_id: [followups]} en UNA sola lectura masiva de ITILFollowup (paginada). Evita el
    N+1 del poller (una request por ticket). Devuelve None si la lectura masiva falla o no es una
    lista -> el llamador cae al modo por-ticket (mismo resultado, más lento pero correcto)."""
    mapa, inicio, vistos = {}, 0, 0
    while True:
        try:
            chunk = cliente.request(f"/ITILFollowup?range={inicio}-{inicio + tam - 1}")
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(chunk, list):
            return None
        for f in chunk:
            if isinstance(f, dict):
                vistos += 1
                if str(f.get("itemtype")) == "Ticket":
                    mapa.setdefault(int(f.get("items_id") or 0), []).append(f)
        if len(chunk) < tam:                 # última página incompleta -> no hay más
            break
        inicio += tam
        if inicio > 1000000:                 # tope de seguridad
            break
    # Red de seguridad: si vimos followups pero NINGUNO mapeó a un Ticket (campos inesperados),
    # NO confiamos en el modo masivo -> None para caer al modo por-ticket (correcto y seguro).
    if vistos and not mapa:
        return None
    return mapa


def gestionar_ciclo(cliente, triage, entidad, estado):
    """Sync (se corre en thread). Gestiona el ciclo de vida de los tickets abiertos:
      - status 4 (EN ESPERA de info): el cliente responde -> EN CURSO; si no, recordatorio.
      - status 5 (RESUELTO): ITHOS pide confirmación; si el cliente confirma -> CERRADO;
        si dice que sigue -> REABIERTO; si no responde -> recordatorio de confirmación.
    NUNCA cierra sin confirmación real del cliente. Devuelve anuncios {texto, wa}.
    Baseline = último followup de un técnico; un followup posterior de un NO técnico
    es una respuesta del cliente (robusto ante reinicios)."""
    anuncios = []
    try:
        tickets = G.de_entidad(cliente.tickets_recientes(40), entidad)
    except Exception:  # noqa: BLE001
        return anuncios

    # Con MUCHOS tickets a revisar (abiertos + resueltos), traer TODOS los followups en UNA lectura
    # masiva evita el N+1 (una request por ticket). Con pocos (caso común) el modo por-ticket ya es
    # instantáneo. Si la lectura masiva falla, fu_map=None y se cae al modo por-ticket (mismo dato).
    relevantes = [t for t in tickets if int(t.get("status", 1)) in (1, 2, 4, 5)]
    fu_map = _followups_por_ticket(cliente) if len(relevantes) > 8 else None

    for t in tickets:
        tid = str(t.get("id"))
        status = int(t.get("status", 1))
        if status not in (1, 2, 4, 5):        # abiertos + resuelto (los cerrados no se tocan)
            estado.pop(tid, None)
            continue
        if fu_map is not None:
            fu = fu_map.get(int(t["id"]), [])
        else:
            try:
                fu = [f for f in cliente.request(f"/Ticket/{t['id']}/ITILFollowup")
                      if isinstance(f, dict)]
            except Exception:  # noqa: BLE001
                continue
        st = estado.setdefault(tid, {})
        base = max((int(f["id"]) for f in fu
                    if int(f.get("users_id") or 0) in TECNICOS), default=0)
        nuevos = [f for f in fu if int(f["id"]) > base
                  and int(f.get("users_id") or 0) not in TECNICOS]

        # ¿Un TÉCNICO HUMANO resolvió el ticket con un comentario? -> marcarlo Resuelto y pedirle
        # confirmación al cliente (mismo flujo que si lo pasaran a 'Resuelto' a mano). Solo en
        # tickets abiertos (no resueltos/cerrados) y una sola vez por comentario nuevo del técnico.
        if status in (1, 2, 4) and not _ya_pidio_confirmacion(fu):
            tec_fus = [f for f in fu if int(f.get("users_id") or 0) in TECNICOS_HUMANOS]
            ult = tec_fus[-1] if tec_fus else None
            if ult and int(ult["id"]) > int(st.get("ultimo_tec_fu", 0)):
                st["ultimo_tec_fu"] = int(ult["id"])
                cont = re.sub(r"<[^>]+>", " ", str(ult.get("content", ""))).strip()
                if triage.tecnico_resolvio(cont):
                    # Marcamos Resuelto con una nota de solución ESTÁNDAR: NO copiamos el
                    # comentario del técnico (ya está en el ticket; duplicarlo se lee como una
                    # confirmación repetida). Pedimos UNA sola confirmación al cliente.
                    if triage.marcar_resuelto(t["id"]) and triage.pedir_confirmacion(t["id"]):
                        st["confirm_pedido"] = True
                        anuncios.append({
                            "texto": f"El técnico resolvió el ticket número {t['id']}. Lo marqué "
                                     "resuelto y le pedí al cliente que confirme para cerrarlo.",
                            "wa": f"✅ *Ticket #{t['id']}* — resuelto por el técnico. Pedí "
                                  "confirmación al cliente para cerrarlo."})
                    continue                  # ya lo procesamos en este ciclo
                # ¿El técnico PIDE COORDINAR/CONFIRMAR algo con el cliente (no es una solución)? -> lo
                # dejamos EN ESPERA de la respuesta del cliente y le transmitimos el pedido para que
                # confirme. Solo si NO estaba ya en espera (status 4) y si NO pedimos ya coordinación
                # por ESTE comentario (robusto ante reinicios). Avisa por voz + WhatsApp.
                # IMPORTANTE: `cont` es SIEMPRE el comentario de un TÉCNICO HUMANO (viene de `tec_fus`
                # = users_id in TECNICOS_HUMANOS), NUNCA del cliente. Si el CLIENTE escribe algo como
                # "coordinemos una reunión", eso es una respuesta del cliente (`nuevos`) y NO dispara
                # esta lógica: la coordinación en espera es exclusiva de lo que pide el TÉCNICO.
                if (status != 4 and not _coordinacion_despues_de(fu, int(ult["id"]))
                        and triage.tecnico_pide_confirmacion(cont)):
                    if triage.poner_en_espera_pedido(t["id"], cont):
                        anuncios.append({
                            "texto": f"En el ticket número {t['id']} el técnico pidió coordinar con el "
                                     "cliente. Lo dejé en espera y le pedí que confirme para avanzar.",
                            "wa": f"⏳ *Ticket #{t['id']}* — el técnico necesita coordinar/confirmar con "
                                  "el cliente. En ESPERA de su respuesta."})
                    continue                  # ya lo procesamos en este ciclo

        if status == 4:                       # EN ESPERA: solo detectamos si el cliente respondió
            if nuevos:
                autor = _nombre_usuario(cliente, nuevos[-1].get("users_id"))
                if triage.poner_en_curso(t["id"]):
                    anuncios.append({
                        "texto": f"El cliente {autor} respondió el ticket número "
                                 f"{t['id']}. Vuelve a estar en curso.",
                        "wa": f"🔔 *Ticket #{t['id']}* — {autor} respondió. En curso otra vez."})
                estado.pop(tid, None)
            # NO se envían recordatorios automáticos al cliente ("esperamos su respuesta"): eran
            # ruido y muchas veces FALSOS (el ticket puede estar pospuesto o en gestión por soporte,
            # no a la espera del cliente). Si el cliente responde, arriba lo pasamos a EN CURSO.

        elif status == 5:                     # RESUELTO: confirmar antes de cerrar
            # Feedback INTERNO al equipo (para la BASE DE CONOCIMIENTO): si la resolución NO explica el
            # PROCEDIMIENTO (no hay solución, o es un 'listo/solucionado' vago sin explicar cómo), ITHOS
            # le pide al técnico por nota PRIVADA que documente PASO A PASO qué hizo. Se revisa una vez
            # por sesión (st) y una sola vez por ticket (marcador en GLPI). El cliente NO lo ve.
            if not st.get("rev_solucion"):
                st["rev_solucion"] = True
                if not _ya_pidio_procedimiento(fu):
                    resol = _texto_resolucion(cliente, t["id"], fu)
                    explica = triage.explica_procedimiento(resol) if resol else False
                    if explica is False:      # False EXPLÍCITO (no None -> IA caída): no explica -> pedir
                        triage.nota_interna(t["id"], _NOTA_PEDIR_PROCEDIMIENTO)
            if not st.get("confirm_pedido") and _ya_pidio_confirmacion(fu):
                st["confirm_pedido"] = True    # ya se pidió antes (p. ej. reinicio) -> no repetir
            if not st.get("confirm_pedido"):
                if triage.pedir_confirmacion(t["id"]):
                    st["confirm_pedido"] = True
            elif nuevos:
                autor = _nombre_usuario(cliente, nuevos[-1].get("users_id"))
                texto = " ".join(str(f.get("content", "")) for f in nuevos)
                conf = triage.cliente_confirma(texto)
                if conf is None:
                    continue  # IA no disponible ahora -> reintentar próximo ciclo
                if conf:
                    if triage.cerrar(t["id"]):
                        anuncios.append({
                            "texto": f"El cliente {autor} confirmó la solución del "
                                     f"ticket número {t['id']}. Ticket cerrado.",
                            "wa": f"✅ *Ticket #{t['id']}* — {autor} confirmó. Cerrado."})
                else:
                    if triage.reabrir(t["id"]):
                        anuncios.append({
                            "texto": f"El cliente {autor} indica que el ticket número "
                                     f"{t['id']} sigue sin resolverse. Reabierto.",
                            "wa": f"🔁 *Ticket #{t['id']}* — {autor} reporta que sigue. Reabierto."})
                estado.pop(tid, None)
            else:
                # RESUELTO, confirmación ya pedida y SIN respuesta del cliente todavía: recordatorio
                # UNA VEZ POR DÍA para que confirme (o avise que sigue). La respuesta del cliente
                # (elif de arriba) SIEMPRE tiene prioridad y corta los recordatorios; al cerrar
                # (status 6) el ticket sale del ciclo y no se recuerda más.
                ult = _ultimo_aviso_confirmacion(fu)
                if ult and (datetime.now() - ult) >= _INTERVALO_RECORDATORIO:
                    triage.recordar_confirmacion(t["id"])
    return anuncios
