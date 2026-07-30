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
            # Si FALTA UN DATO (necesita_info), se le agrega el cierre con el marcador de ESPERA para
            # que el ciclo sepa que el ticket quedó esperando al CLIENTE y le recuerde una vez por día
            # hábil hasta que responda (igual que el pedido de confirmación del técnico).
            respuesta = a.get("primera_respuesta", "")
            if necesita:
                respuesta = _con_cierre_espera(respuesta)
            try:
                self.cli.request("/ITILFollowup", "POST",
                                 {"input": {"itemtype": "Ticket", "items_id": tid,
                                            "content": respuesta}})
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
        # QUIÉN quedó ASIGNADO de verdad: el técnico humano que ya estaba (asignación manual, que se
        # respeta) o el responsable que puso ITHOS. Se devuelve para @MENCIONARLO en WhatsApp (solo
        # a él) y para que el aviso diga el nombre correcto, no siempre el del default.
        asignados_finales = sorted((asignados & TECNICOS_HUMANOS) or {resp_id})
        from comun import tickets as TK
        nombres = (TK.nombres_asignados(self.cfg_glpi, asignados_finales)
                   or _nombres_por_id(asignados_finales) or [NOMBRES.get(resp_login, resp_login)])
        return {"prioridad": prioridad, "nivel": nivel, "responsable_login": resp_login,
                "responsable_nombre": ", ".join(nombres),
                "asignados": asignados_finales,
                "telefonos": TK.telefonos_asignados(self.cfg_glpi, asignados_finales),
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

    def recordar_espera(self, tid, motivo="confirmacion"):
        """El ticket está EN ESPERA porque el CLIENTE tiene que responder algo para que podamos
        AVANZAR: un DATO que le pedimos (motivo='datos') o una CONFIRMACIÓN/coordinación
        (motivo='confirmacion'). Recordatorio UNA VEZ POR DÍA HÁBIL, a la misma hora, hasta que
        responda. Es un recordatorio LEGÍTIMO: nosotros le pedimos algo y el trabajo no avanza sin
        eso. Mantiene el ticket EN ESPERA (SLA pausado)."""
        try:
            self.cli.abrir()
            self._followup(tid, _texto_recordatorio_espera(motivo))
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            self.cli.cerrar()

    def avisar_tecnico_sin_respuesta(self, tid, dias, motivo="confirmacion"):
        """Pasaron `dias` HÁBILES y el cliente nunca contestó lo que le pedimos: se le avisa al
        TÉCNICO ASIGNADO por NOTA INTERNA (privada, el cliente NO la ve) para que decida (llamarlo,
        posponerlo o cerrarlo). El aviso por WhatsApp @mencionándolo lo manda el ciclo."""
        return self.nota_interna(tid, _nota_escalada_espera(dias, motivo))

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
                # Garantizamos el marcador estable de ESPERA (_MARCA_ESPERA_CLIENTE) por si la IA no
                # lo incluyó: el ciclo lo usa para recordarle al cliente una vez por día hábil y para
                # NO volver a pedir coordinación del mismo comentario tras un reinicio (ver
                # _es_pedido_al_cliente / _coordinacion_despues_de).
                return _con_cierre_espera(r)
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
# Marcador estable de que ITHOS le PIDIÓ ALGO AL CLIENTE y espera su respuesta. Cubre los DOS casos
# en que el ticket queda EN ESPERA por el cliente: (a) falta un DATO que le pedimos en la primera
# respuesta, y (b) tiene que CONFIRMAR/COORDINAR algo para que podamos avanzar. En los dos casos el
# ciclo le recuerda una vez por día hábil hasta que responda (y el SLA queda pausado en 'En espera').
_MARCA_ESPERA_CLIENTE = "a la espera de su respuesta"
_MARCA_PROCEDIMIENTO = "documentá paso a paso"   # marcador de la nota interna que pide el procedimiento
_MARCA_RECORDATORIO_ESPERA = "le recordamos que su ticket está a la espera"
_MARCA_ESCALADA_ESPERA = "sigue sin respuesta del cliente"
_DIAS_HABILES_ESCALADA = 5        # días HÁBILES sin respuesta -> avisar al TÉCNICO ASIGNADO
# TODOS los recordatorios al cliente (espera por datos, espera por confirmación y confirmación de un
# ticket resuelto) salen UNO POR DÍA HÁBIL y SIEMPRE dentro del horario de atención del cliente
# (default Lun-Vie 09:00-18:00 en SU zona, `en_horario_atencion`): a la misma hora, nunca de noche
# ni un fin de semana. La hora es la de apertura: el primer ciclo del día que cae en horario.
_CIERRE_ESPERA = " Quedamos a la espera de su respuesta. Soporte ITH."


def _con_cierre_espera(texto):
    """Agrega al final el cierre con el marcador de ESPERA (si no lo trae ya). Se usa en la 1ª
    respuesta cuando FALTA un dato del cliente: así el ciclo reconoce que el ticket espera SU
    respuesta y le recuerda una vez por día hábil, igual que con el pedido de confirmación."""
    t = (texto or "").strip()
    return t if _MARCA_ESPERA_CLIENTE in t.lower() else (t + _CIERRE_ESPERA).strip()


def _texto_recordatorio_espera(motivo):
    """Recordatorio PÚBLICO al cliente, según QUÉ estamos esperando ('datos' o 'confirmacion').
    Incluye a propósito el marcador de espera (_MARCA_ESPERA_CLIENTE) para que el propio ciclo lo
    reconozca como el último aviso, y el de RECORDATORIO para distinguirlo del pedido original."""
    if motivo == "datos":
        cuerpo = ("de la información que le solicitamos para poder avanzar. Cuando pueda, "
                  "respóndanos con ese dato y continuamos con la gestión.")
    else:
        cuerpo = ("de su confirmación para poder avanzar. Cuando pueda, respóndanos para "
                  "coordinar y continuamos con la gestión.")
    return f"{_MARCA_RECORDATORIO_ESPERA.capitalize()} {cuerpo}{_CIERRE_ESPERA}"


def _nota_escalada_espera(dias, motivo):
    que = ("la información que le pedimos" if motivo == "datos"
           else "el pedido de coordinación/confirmación")
    return ("Nota interna (el cliente no la ve): hace " + str(dias) + " días hábiles que este ticket "
            f"está EN ESPERA y sigue sin respuesta del cliente a {que}. Le mandamos un recordatorio "
            "por día hábil. Conviene contactarlo por otra vía (teléfono), posponerlo con fecha o "
            "cerrarlo si ya no corresponde.")


_NOTA_PEDIR_PROCEDIMIENTO = (
    "Nota interna (el cliente no la ve): para nuestra base de conocimiento, por favor documentá "
    "PASO A PASO qué hiciste para resolver este ticket (el procedimiento), no solo que quedó resuelto. "
    "Así queda el registro y nos sirve para resolver más rápido los casos futuros.")


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


def _es_pedido_al_cliente(f):
    """True si el followup `f` es un pedido PÚBLICO de ITHOS al cliente (un dato que falta o una
    confirmación para avanzar) y por lo tanto el ticket está esperando SU respuesta. Las notas
    internas (is_private) NO cuentan: el cliente no las ve."""
    if int(f.get("users_id") or 0) not in TECNICOS or int(f.get("is_private") or 0):
        return False
    return _MARCA_ESPERA_CLIENTE in str(f.get("content", "")).lower()


def _coordinacion_despues_de(fu, tec_fu_id):
    """True si ITHOS ya dejó un pedido al cliente POSTERIOR al comentario `tec_fu_id`. Así el
    pedido NO se repite para el MISMO comentario del técnico tras un reinicio (el estado en memoria
    se pierde), pero SÍ se puede volver a pedir si el técnico deja un comentario NUEVO más adelante.
    Lee la verdad del propio GLPI, no la memoria."""
    return any(_es_pedido_al_cliente(f) and int(f.get("id") or 0) > int(tec_fu_id or 0) for f in fu)


def _ultimo_id_cliente(fu):
    """Mayor id de followup de un NO técnico = la última vez que HABLÓ el cliente (0 si nunca)."""
    return max((int(f.get("id") or 0) for f in fu
                if int(f.get("users_id") or 0) not in TECNICOS), default=0)


def _espera_pendiente(fu):
    """(fecha del PRIMER pedido, fecha del ÚLTIMO aviso, motivo) si el ticket está esperando una
    respuesta DEL CLIENTE y todavía no contestó. None si no aplica. `motivo`:
      · 'datos'        -> le pedimos un DATO que falta (la primera respuesta del triage), o
      · 'confirmacion' -> tiene que CONFIRMAR/COORDINAR algo para que podamos avanzar.
    Pendiente = hay un pedido PÚBLICO de ITHOS POSTERIOR a lo último que dijo el cliente. Se lee del
    propio GLPI (no de la memoria) -> sobrevive reinicios y no manda recordatorios falsos: si el
    cliente ya respondió, el ciclo lo pasa a EN CURSO y esto deja de dar True."""
    avisos = [f for f in fu if _es_pedido_al_cliente(f)]
    if not avisos:
        return None
    if max(int(f.get("id") or 0) for f in avisos) <= _ultimo_id_cliente(fu):
        return None                          # el cliente ya contestó después del pedido
    fechas = sorted(d for d in (_parse_fecha(f.get("date_creation") or f.get("date"))
                                for f in avisos) if d)
    if not fechas:
        return None
    # El motivo lo define el ÚLTIMO pedido (es lo que estamos esperando AHORA): si ese pedido es la
    # PRIMERA respuesta del ticket (el primer followup público de ITHOS), falta un DATO; cualquier
    # pedido posterior es una COORDINACIÓN/confirmación planteada por el técnico.
    # `fechas[0]` (el PRIMER pedido) es la referencia para la escalada: mide cuánto lleva el ticket
    # trabado esperando al cliente, aunque en el medio le hayamos pedido otra cosa.
    publicos = [int(f.get("id") or 0) for f in fu
                if int(f.get("users_id") or 0) in TECNICOS and not int(f.get("is_private") or 0)]
    ultimo_pedido = max(int(f.get("id") or 0) for f in avisos)
    motivo = "datos" if publicos and ultimo_pedido == min(publicos) else "confirmacion"
    return fechas[0], fechas[-1], motivo


def _ya_escalo_espera(fu):
    """True si ITHOS ya avisó al técnico (nota interna) que el cliente no responde. Lee GLPI, no la
    memoria -> no se repite la escalada tras un reinicio."""
    return any(int(f.get("users_id") or 0) in TECNICOS
               and _MARCA_ESCALADA_ESPERA in str(f.get("content", "")).lower() for f in fu)


def es_dia_habil(cfg, dt):
    """True si `dt` cae en un día de atención del cliente (default Lun-Vie)."""
    h = cfg.get("horario_atencion") or _HORARIO_DEFAULT
    return dt.weekday() in h.get("dias", _HORARIO_DEFAULT["dias"])


def dias_habiles_entre(cfg, desde, hasta):
    """Días HÁBILES transcurridos entre dos fechas (sin contar el día de `desde`, contando el de
    `hasta`). Sirve para 'a los 5 días hábiles sin respuesta'. 0 si `hasta` <= `desde`."""
    if not desde or not hasta or hasta <= desde:
        return 0
    d, fin, n = desde.date(), hasta.date(), 0
    while d < fin:
        d += timedelta(days=1)
        if es_dia_habil(cfg, d):
            n += 1
    return n


def _ahora_local(cfg):
    """AHORA en la zona del cliente, SIN tzinfo, para comparar con las fechas de GLPI (naive)."""
    return _ahora_zona(cfg).replace(tzinfo=None)


def _esta_pospuesto(cfg, tid):
    """True si el ticket tiene una REACTIVACIÓN programada (lo pospusieron a un día/hora): entonces
    NO se le recuerda nada al cliente hasta esa fecha (el técnico decidió esperar)."""
    try:
        from comun import agenda
        cliente = cfg.get("nombre_cliente") or "cliente"
        return any(str(x.get("tid")) == str(tid) for x in agenda.pendientes(cliente))
    except Exception:  # noqa: BLE001
        return False


def _asignados_humanos(cliente, tid):
    """user-ids de los TÉCNICOS HUMANOS asignados ('Asignado a', Ticket_User type=2), sin ITHOS."""
    try:
        us = cliente.request(f"/Ticket/{tid}/Ticket_User")
        return sorted({int(u.get("users_id") or 0) for u in us
                       if isinstance(u, dict) and int(u.get("type") or 0) == 2} - {0, ITHOS_ID})
    except Exception:  # noqa: BLE001
        return []


def _nombres_por_id(ids):
    """Nombres de los técnicos por su user-id de GLPI, como respaldo si el cliente no configuró
    el bloque 'tecnicos' (mapeo histórico de SRT/ITH)."""
    por_id = {uid: NOMBRES.get(login, login) for login, uid in RESPONSABLES.items()}
    return [por_id[i] for i in ids if i in por_id]


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
      - status 4 esperando que el cliente CONFIRME/COORDINE para avanzar: recordatorio DIARIO en
        días hábiles y, a los 5 días hábiles sin respuesta, aviso al TÉCNICO ASIGNADO.
      - status 5 (RESUELTO): ITHOS pide confirmación; si el cliente confirma -> CERRADO;
        si dice que sigue -> REABIERTO; si no responde -> recordatorio de confirmación.
    NUNCA cierra sin confirmación real del cliente. Devuelve anuncios {texto, wa, tel}: `tel` son
    los teléfonos del TÉCNICO ASIGNADO para @mencionarlo en WhatsApp (solo a él).
    Baseline = último followup de un técnico; un followup posterior de un NO técnico
    es una respuesta del cliente (robusto ante reinicios)."""
    anuncios = []
    cfg = getattr(triage, "cfg_glpi", None) or {}
    try:
        tickets = G.de_entidad(cliente.tickets_recientes(40), entidad)
    except Exception:  # noqa: BLE001
        return anuncios

    _cache_asig = {}

    def asignado(tid):
        """(telefonos, nombres) del TÉCNICO ASIGNADO al ticket, para @mencionarlo SOLO a él. Se
        resuelve una vez por ticket y SOLO cuando hay algo que anunciar (nada de N+1 por ciclo)."""
        tid = int(tid)
        if tid not in _cache_asig:
            from comun import tickets as TK
            ids = _asignados_humanos(cliente, tid)
            _cache_asig[tid] = (TK.telefonos_asignados(cfg, ids),
                                TK.nombres_asignados(cfg, ids) or _nombres_por_id(ids))
        return _cache_asig[tid]

    def anunciar(tid, texto, wa):
        """Suma un anuncio del ticket con la @mención al asignado (y su nombre en el texto, para los
        canales sin menciones: Telegram/email/Teams)."""
        tels, nombres = asignado(tid)
        if nombres:
            wa = f"{wa}\n👤 Asignado a: {', '.join(nombres)}"
        anuncios.append({"texto": texto, "wa": wa, "tel": tels})

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
                        anunciar(
                            t["id"],
                            f"El técnico resolvió el ticket número {t['id']}. Lo marqué "
                            "resuelto y le pedí al cliente que confirme para cerrarlo.",
                            f"✅ *Ticket #{t['id']}* — resuelto por el técnico. Pedí "
                            "confirmación al cliente para cerrarlo.")
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
                        anunciar(
                            t["id"],
                            f"En el ticket número {t['id']} el técnico pidió coordinar con el "
                            "cliente. Lo dejé en espera y le pedí que confirme para avanzar.",
                            f"⏳ *Ticket #{t['id']}* — el técnico necesita coordinar/confirmar con "
                            "el cliente. En ESPERA de su respuesta.")
                    continue                  # ya lo procesamos en este ciclo

        if status == 4:                       # EN ESPERA
            if nuevos:                        # el cliente respondió -> EN CURSO
                autor = _nombre_usuario(cliente, nuevos[-1].get("users_id"))
                if triage.poner_en_curso(t["id"]):
                    anunciar(t["id"],
                             f"El cliente {autor} respondió el ticket número "
                             f"{t['id']}. Vuelve a estar en curso.",
                             f"🔔 *Ticket #{t['id']}* — {autor} respondió. En curso otra vez.")
                estado.pop(tid, None)
            else:
                # NO se envían recordatorios automáticos genéricos ("esperamos su respuesta"): eran
                # ruido y muchas veces FALSOS (el ticket puede estar pospuesto o en gestión por
                # soporte). ÚNICA excepción, porque acá SÍ le pedimos algo CONCRETO: el ticket está
                # esperando que el CLIENTE responda —un DATO que le pedimos o una CONFIRMACIÓN para
                # poder avanzar— y el SLA queda pausado en 'En espera'. Entonces sí:
                #   · un recordatorio POR DÍA HÁBIL, a la misma hora (la de apertura), hasta que
                #     responda (cuando responde, el 'if nuevos' de arriba lo pasa a EN CURSO), y
                #   · a los 5 días hábiles sin respuesta, aviso al TÉCNICO ASIGNADO (nota interna
                #     privada + WhatsApp @mencionándolo) para que decida.
                # Si el ticket está POSPUESTO (reactivación agendada), no se molesta a nadie.
                espera = _espera_pendiente(fu)
                if espera and not _esta_pospuesto(cfg, t["id"]):
                    primero, ultimo, motivo = espera
                    ahora = _ahora_local(cfg)
                    # El recordatorio sale DENTRO del horario de atención del cliente (default
                    # Lun-Vie 09:00-18:00, su zona): nunca de noche ni un fin de semana. Uno por día.
                    if en_horario_atencion(cfg) and ultimo.date() < ahora.date():
                        if triage.recordar_espera(t["id"], motivo):
                            log.info("Ciclo #%s: recordatorio diario al cliente (%s; en espera "
                                     "desde %s).", t["id"], motivo, primero.date())
                    habiles = dias_habiles_entre(cfg, primero, ahora)
                    if (habiles >= _DIAS_HABILES_ESCALADA and not st.get("escalado_espera")
                            and not _ya_escalo_espera(fu)):
                        st["escalado_espera"] = True
                        triage.avisar_tecnico_sin_respuesta(t["id"], habiles, motivo)
                        que = ("la información que le pedimos" if motivo == "datos"
                               else "el pedido de coordinación")
                        anunciar(t["id"],
                                 f"El ticket número {t['id']} lleva {habiles} días hábiles en "
                                 f"espera y el cliente no respondió.",
                                 f"⌛ *Ticket #{t['id']}* — {habiles} días hábiles sin respuesta del "
                                 f"cliente a {que}. Requiere una definición: contactarlo, "
                                 "posponerlo o cerrarlo.")

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
                        anunciar(t["id"],
                                 f"El cliente {autor} confirmó la solución del "
                                 f"ticket número {t['id']}. Ticket cerrado.",
                                 f"✅ *Ticket #{t['id']}* — {autor} confirmó. Cerrado.")
                else:
                    if triage.reabrir(t["id"]):
                        anunciar(t["id"],
                                 f"El cliente {autor} indica que el ticket número "
                                 f"{t['id']} sigue sin resolverse. Reabierto.",
                                 f"🔁 *Ticket #{t['id']}* — {autor} reporta que sigue. Reabierto.")
                estado.pop(tid, None)
            else:
                # RESUELTO, confirmación ya pedida y SIN respuesta del cliente todavía: recordatorio
                # UNA VEZ POR DÍA HÁBIL, a la misma hora y DENTRO del horario de atención (no de
                # noche ni un fin de semana), para que confirme o avise que sigue. La respuesta del
                # cliente (elif de arriba) SIEMPRE tiene prioridad y corta los recordatorios; al
                # cerrar (status 6) el ticket sale del ciclo y no se recuerda más.
                ult = _ultimo_aviso_confirmacion(fu)
                if (ult and en_horario_atencion(cfg)
                        and ult.date() < _ahora_local(cfg).date()):
                    triage.recordar_confirmacion(t["id"])
    return anuncios
