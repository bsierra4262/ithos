#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TRIAGE: la PRIMERA PASADA sobre un ticket nuevo.

Lo clasifica con la IA (`cerebro`) y lo aplica en la mesa de ayuda como el usuario ITHOS:
categoría, urgencia/impacto/prioridad, SLA/OLA, asignación, primera respuesta y estado. También
expone las acciones que después usa el ciclo de vida (marcar resuelto, pedir confirmación, dejar
en espera, notas internas).

Lo que pasa DESPUÉS del triage vive en `ciclo.py`; los textos y sus marcadores, en
`textos_ticket.py`; quién es el equipo, en `equipo.py`.

Los mapeos de categorías y SLA son los de SRT/ITH; en el producto se configuran por cliente.
"""

import os
import re
import sys
import logging
from datetime import datetime, timedelta

_AQUI = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_AQUI, ".."), _AQUI):   # ITHOS/ y ITHOS/central/
    if _p not in sys.path:
        sys.path.insert(0, _p)
from comun import ia as IA          # noqa: E402
from comun import glpi as G         # noqa: E402
import cerebro                      # noqa: E402

log = logging.getLogger("triage")

# Las categorías y los SLA se leen de GLPI POR ENTIDAD (`G.catalogo_entidad`): cada área del cliente
# tiene los suyos, con ids distintos —'TERMINALES' es la 13 en la mesa de ayuda de SRT y la 55 en
# soporte técnico—, y ponerle a un ticket el id de otra entidad es cargarlo mal. Estos valores son el
# ÚLTIMO recurso, sólo por si GLPI no contesta cuando hay que clasificar.
CATEGORIAS = {"MOLINETES": 11, "TERMINALES": 13, "HIK-CENTRAL": 12, "INTERFACE": 15}
NIVEL_SLA = {
    "LEVE":      {"slas_id_tto": 1, "slas_id_ttr": 6, "olas_id_tto": 1, "olas_id_ttr": 2},
    "GRAVE":     {"slas_id_tto": 2, "slas_id_ttr": 3, "olas_id_tto": 4, "olas_id_ttr": 3},
    "MUY GRAVE": {"slas_id_tto": 4, "slas_id_ttr": 5, "olas_id_tto": 5, "olas_id_ttr": 6},
}
PRIORIDAD_NUM = {"Baja": 2, "Media": 3, "Alta": 4, "Urgente": 5}
NIVEL_POR_PRIORIDAD = {"Baja": "LEVE", "Media": "LEVE", "Alta": "GRAVE",
                       "Urgente": "MUY GRAVE"}

# El equipo, los textos y el ciclo viven en sus propios módulos. Se re-exportan acá porque `triage`
# es la puerta de entrada de todo lo de tickets del Gestor, y para no romper a quien ya lo importa.
from equipo import (RESPONSABLES, NOMBRES, ITHOS_ID, TECNICOS,            # noqa: E402,F401
                    TECNICOS_HUMANOS, ids_humanos, ids_tecnicos,
                    _asignados_humanos, _nombres_por_id)
from textos_ticket import (_MARCA_ESPERA_CLIENTE, _MARCA_SIN_ATENDER,     # noqa: E402,F401
                           _CIERRE_ESPERA, _DIAS_HABILES_ESCALADA, _HORAS_SIN_ATENDER,
                           _RE_DESPEDIDA_ESPERA, _RE_FIRMA_FINAL, _ALCANCE_TXT,
                           _NOTA_PEDIR_PROCEDIMIENTO, _nota_alcance, _nota_interna_horario,
                           _nota_respuesta_fuera_horario, _nota_sin_atender, _con_cierre_espera,
                           _texto_recordatorio_espera, _nota_escalada_espera,
                           frase_triage, mensaje_triage)

# El HORARIO DE ATENCIÓN del cliente vive en comun/horario.py (única fuente de verdad, compartida
# con el ciclo, el proactivo de SLA y los reportes): nada de lo que sale hacia afuera cae de noche
# ni un fin de semana.
from comun.horario import (ZONA_DEFAULT, HORARIO_DEFAULT as _HORARIO_DEFAULT,  # noqa: E402,F401
                           ahora_zona as _ahora_zona, ahora_local as _ahora_local,
                           es_dia_habil, en_horario_atencion, proximo_inicio_horario,
                           dias_habiles_entre, horas_habiles_entre)


_MARCA_SIN_ATENDER = "el cliente respondió y todavía no le contestamos"
# Horas HÁBILES que puede quedar sin respuesta del técnico antes de que salte el aviso.
_HORAS_SIN_ATENDER = 2


# El saludo al solicitante vive en comun/glpi.py (compartido con el camino de voz aplicar_ciclo).
_saludo_solicitante = G.saludo_solicitante


class Triage:
    @property
    def ent(self):
        """La entidad PRINCIPAL del cliente. Sale siempre de la config, así vale también para un
        Triage armado a mano (los tests) sin depender de que alguien la haya seteado."""
        return int((self.cfg_glpi or {}).get("entity_id", 0) or 0)

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

    def _antecedentes(self, tid, ticket):
        """Casos parecidos REALES ya trabajados de este cliente, para que el triage clasifique con
        precedentes y no con la intuición del modelo: si un biométrico caído en una sede siempre
        fue un caso grave de instalaciones, el ticket nuevo se lee con esa historia a la vista.
        Nunca es fatal: si no se puede leer el histórico, el triage sigue igual que antes."""
        try:
            from comun import tickets as TK
            adap = TK.adaptador({"integrador_glpi": self.cfg_glpi})
            casos = adap.casos_similares(
                f"{ticket.get('name', '')} {TK._sin_html(ticket.get('content', ''))}",
                tope=4, excluir=(tid,))
        except Exception as e:  # noqa: BLE001
            log.debug("Triage #%s: sin antecedentes (%s)", tid, str(e)[:80])
            return ""
        partes = []
        for c in casos:
            resol = (c["resolucion"] if c["resuelto_de_verdad"]
                     else "(se cerró sin dejar registrada una resolución técnica)")
            partes.append(f"- #{c['id']} «{c['asunto']}»: {c['problema'][:280]}\n"
                          f"  Cómo terminó: {resol[:280]}")
        return "\n".join(partes)

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
        a = cerebro.clasificar_ticket(
            self.ia, ticket.get("name", ""), ticket.get("content", ""), solicitante=solicitante,
            antecedentes=self._antecedentes(tid, ticket))
        if not a:
            log.warning("Triage: no se pudo clasificar el ticket %s", tid)
            return None
        # COHERENCIA: lo que decidió el modelo tiene que sostenerse solo. Si lo que falla es el
        # equipo o la sede, el ticket NO queda esperando un legajo que no existe, la prioridad no
        # baja del piso de su alcance y lo toma instalaciones. No depende del prompt.
        a, correcciones = cerebro.coherente(a, ticket.get("name", ""), ticket.get("content", ""))
        if correcciones:
            log.info("Triage #%s: alcance=%s, corregido -> %s", tid, a.get("alcance"),
                     "; ".join(correcciones))
        # El saludo SIEMPRE es para el solicitante (quien abrió el ticket), no para la persona
        # afectada que aparezca en el texto. Se corrige de forma determinística por las dudas.
        a["primera_respuesta"] = _saludo_solicitante(a.get("primera_respuesta", ""), solicitante)
        prioridad = a.get("prioridad", "Media")
        nivel = NIVEL_POR_PRIORIDAD.get(prioridad, "LEVE")
        num = PRIORIDAD_NUM.get(prioridad, 3)
        resp_login = a.get("responsable", "bsierra")
        from comun import tickets as TK
        _ficha = TK.tecnico_por_id(self.cfg_glpi, resp_login) or {}
        try:
            resp_id = int(_ficha.get("glpi_id"))
        except (TypeError, ValueError):
            resp_id = RESPONSABLES.get(resp_login, RESPONSABLES["bsierra"])
        # ACOMPAÑAN: mientras alguien se forma, trabaja el MISMO ticket que su responsable, al mismo
        # tiempo y con el mismo criterio. Se declara en la config (`responsable` en su ficha).
        acompanan = [u for u in TK.acompanan_a(self.cfg_glpi, resp_login) if u != resp_id]
        try:
            self.cli.abrir()
            campos = {"urgency": num, "impact": num, "priority": num}
            # La categoría y el SLA son los DE LA ENTIDAD DEL TICKET: cada área del cliente tiene los
            # suyos, con ids propios. Antes se usaban siempre los de la entidad principal, así que un
            # ticket de otra área quedaba mal categorizado y sin SLA.
            ent_ticket = int(ticket.get("entities_id", self.ent) or self.ent)
            catalogo = G.catalogo_entidad(self.cfg_glpi, ent_ticket)
            # Los valores fijos son de la entidad PRINCIPAL: sirven de red sólo ahí. En otra
            # entidad, antes que ponerle el id de una categoría o un SLA ajenos —cargarlo mal—,
            # se deja sin poner y el ticket igual entra al circuito (asignado y contestado).
            propio = ent_ticket == self.ent
            cat = catalogo["categorias"].get(str(a.get("categoria") or "").upper()) \
                or (CATEGORIAS.get(a.get("categoria")) if propio else None)
            # 1er triage: CATEGORIZA SIEMPRE (aunque venga mal cargado con otra categoría). El respeto a
            # la categoría manual es AGUAS ARRIBA (si ITHOS ya lo triageó, ni entra acá).
            if cat:
                campos["itilcategories_id"] = cat
            sla = catalogo["sla"].get(nivel) or (NIVEL_SLA[nivel] if propio else None)
            if sla:
                campos.update(sla)
            else:
                log.warning("Triage #%s: la entidad %s no tiene SLA cargado — el ticket se atiende "
                            "igual, pero sin reloj de SLA.", tid, ent_ticket)
            self.cli.request(f"/Ticket/{tid}", "PUT", {"input": campos})
            # ASIGNACIÓN: ITHOS siempre. El responsable AUTOMÁTICO (bsierra/jayala) SOLO si NO hay ya un
            # técnico HUMANO asignado a mano -> se respeta una reasignación manual previa.
            humanos = ids_humanos(self.cfg_glpi)
            a_poner = [ITHOS_ID]
            if not (asignados & humanos):
                a_poner.extend([resp_id] + acompanan)
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
            # Si hay que IR al lugar, el ticket también queda esperando al cliente: lo que falta es
            # que nos confirme CUÁNDO podemos pasar. No es un dato del afectado, es una
            # coordinación, y el ciclo se la recuerda una vez por día hábil igual que cualquier otra.
            visita = bool(a.get("requiere_visita"))
            espera_cliente = necesita or visita
            fuera = (not espera_cliente) and (not en_horario_atencion(self.cfg_glpi))
            # PÚBLICO: la 1ª respuesta tal cual. NO FATAL: si GLPI la rechaza (p. ej. el usuario MySQL de
            # GLPI sin permiso INSERT), igual dejamos el ticket categorizado/asignado/con estado.
            # Si FALTA UN DATO (necesita_info), se le agrega el cierre con el marcador de ESPERA para
            # que el ciclo sepa que el ticket quedó esperando al CLIENTE y le recuerde una vez por día
            # hábil hasta que responda (igual que el pedido de confirmación del técnico).
            respuesta = a.get("primera_respuesta", "")
            if espera_cliente:
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
            # Si hubo que corregir la clasificación (el alcance no era el que decía), el técnico se
            # entera: es lo que explica por qué el ticket entra con esa prioridad y en sus manos.
            if correcciones:
                internas.append(_nota_alcance(a, correcciones))
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
                             {"input": {"status": 4 if (espera_cliente or fuera) else 2}})
        except Exception as e:  # noqa: BLE001
            log.error("Triage: fallo al aplicar el ticket %s: %s", tid, e)
            return None
        finally:
            self.cli.cerrar()
        if fuera:                               # reapertura AUTOMÁTICA y SILENCIOSA al abrir el horario
            self._agendar_reapertura_horario(tid, dt_reapertura)
        estado_txt = ("EN ESPERA (datos)" if necesita
                      else "EN ESPERA (coordinar la visita)" if visita
                      else "EN ESPERA (fuera de horario)" if fuera else "EN CURSO")
        log.info("Triage OK #%s: cat=%s prio=%s -> %s (%s)", tid, a.get("categoria"),
                 prioridad, resp_login, estado_txt)
        # QUIÉN quedó ASIGNADO de verdad: el técnico humano que ya estaba (asignación manual, que se
        # respeta) o el responsable que puso ITHOS. Se devuelve para @MENCIONARLO en WhatsApp (solo
        # a él) y para que el aviso diga el nombre correcto, no siempre el del default.
        asignados_finales = sorted((asignados & humanos) or ({resp_id} | set(acompanan)))
        from comun import tickets as TK
        nombres = (TK.nombres_asignados(self.cfg_glpi, asignados_finales)
                   or _nombres_por_id(asignados_finales) or [NOMBRES.get(resp_login, resp_login)])
        return {"prioridad": prioridad, "nivel": nivel, "responsable_login": resp_login,
                "responsable_nombre": ", ".join(nombres),
                "asignados": asignados_finales,
                "telefonos": TK.telefonos_asignados(self.cfg_glpi, asignados_finales),
                "categoria": a.get("categoria"), "necesita_info": necesita,
                "requiere_visita": visita, "alcance": a.get("alcance"),
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

    def esperar_hasta_horario(self, tid, motivo=""):
        """El cliente respondió FUERA del horario de atención. Si el ticket quedara EN CURSO, el SLA
        correría toda la noche o todo el fin de semana contra un equipo que no está trabajando, y el
        lunes ya nace vencido. Así que queda EN ESPERA y se reabre SOLO al comenzar la jornada.

        El cliente no se entera del corte —el aviso va como nota interna— y no recibe recordatorios:
        no le estamos pidiendo nada, la pelota es nuestra. Devuelve la fecha de reapertura o None."""
        dt = proximo_inicio_horario(self.cfg_glpi)
        try:
            self.cli.abrir()
            self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 4}})
        except Exception as e:  # noqa: BLE001
            log.warning("Triage: no pude dejar en espera por horario #%s: %s", tid, e)
            return None
        finally:
            self.cli.cerrar()
        self.nota_interna(tid, _nota_respuesta_fuera_horario(dt, motivo))
        self._agendar_reapertura_horario(tid, dt)
        return dt

    def avisar_tecnico_sin_atender(self, tid, desde, horas):
        """Aviso de SUPERVISOR al técnico asignado: el cliente respondió y nadie le contestó. Va
        como NOTA INTERNA (el cliente no la ve); el ciclo lo repite por WhatsApp @mencionándolo."""
        return self.nota_interna(tid, _nota_sin_atender(desde, horas))

    def _sesion_de(self, uid):
        """Sesión de GLPI con el token del TÉCNICO `uid`, o None si no lo tiene configurado.

        Sirve para que lo que hace un técnico quede a SU nombre: si la solución la carga ITHOS (o
        peor, el usuario administrador), el historial dice que resolvió alguien que no resolvió."""
        try:
            from comun import tickets as TK
            ficha = TK.tecnico_por_id(self.cfg_glpi, uid) or {}
            login = str(ficha.get("glpi_login") or "").strip()
            token = self.cfg_glpi.get(f"glpi_{login}_token") if login else None
            return G.sesion(self.cfg_glpi, token) if token else None
        except Exception:  # noqa: BLE001
            return None

    def marcar_resuelto(self, tid, solucion="", autor=None):
        """Pasa el ticket a RESUELTO (status 5), cargando la SOLUCIÓN cuando se le pasa el texto.

        POR QUÉ IMPORTA LA SOLUCIÓN: en GLPI el cliente aprueba o rechaza LA SOLUCIÓN. Un ticket
        que pasa a Resuelto sin cargar ninguna no le deja al solicitante nada que aprobar ni que
        rechazar: ve el ticket resuelto y no tiene cómo decir "sigue igual". Con la solución
        cargada, GLPI la deja pendiente de su aprobación y le muestra los dos botones.

        El texto que se carga son LAS PALABRAS DEL TÉCNICO (su propio comentario), y si se indica
        el `autor` y tiene su token configurado, se carga CON SU USUARIO: el ticket dice quién
        resolvió de verdad, no ITHOS ni el administrador.

        Sin texto sólo cambia el estado (compatibilidad)."""
        if not solucion:
            try:
                self.cli.abrir()
                self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 5}})
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("Triage: no pude marcar resuelto #%s: %s", tid, e)
                return False
            finally:
                self.cli.cerrar()
        propia = self._sesion_de(autor)
        if propia is not None:
            try:
                propia.request("/ITILSolution", "POST", {"input": {
                    "itemtype": "Ticket", "items_id": tid,
                    "content": solucion or "Resuelto por el equipo de soporte técnico."}})
                return True
            except Exception as e:  # noqa: BLE001
                log.info("Triage #%s: no pude cargar la solución con el usuario del técnico (%s); "
                         "la carga ITHOS.", tid, str(e)[:90])
            finally:
                propia.cerrar()
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
        """¿El comentario de un TÉCNICO dice que el ticket QUEDÓ RESUELTO (no sólo un avance)?
        True/False, o None si la IA no está disponible.

        Si el técnico lo dice CON TODAS LAS LETRAS, se toma como resuelto sin preguntarle a la IA:
        un comentario que arranca con "el inconveniente quedó solucionado" y sigue con dos párrafos
        de diagnóstico se leía como un simple avance, y el ticket quedaba En curso con el técnico
        dando el trabajo por terminado. Lo que el técnico AFIRMA no se somete a interpretación.

        OJO: esto se consulta DESPUÉS de descartar que quede algo en manos del cliente. Un "se
        solucionó el acceso, pero falta que ustedes revisen la terminal" NO cierra el ticket: lo
        deja esperando al cliente. Esa decisión la toma el ciclo, en ese orden."""
        if cerebro.dice_resuelto(texto):
            return True
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
        """IA: ¿queda algo EN MANOS DEL CLIENTE para poder avanzar o cerrar? -> True.

        Cuenta coordinar un día/horario, aprobar algo, decidir, y también que el cliente tenga que
        gestionar algo de su lado (escalarlo a otra área, reconectar o revisar un equipo suyo).
        Vale aunque esté redactado impersonal ('se deberá coordinar la reubicación') y AUNQUE el
        comentario diga que una parte ya quedó resuelta: si falta algo del cliente, el ticket sigue
        esperándolo. False si es una solución cerrada o un avance interno. None si la IA no está."""
        try:
            r = self.ia.chat(
                "Un TÉCNICO dejó un comentario en un ticket de soporte. Decidí si queda algo EN MANOS "
                "DEL CLIENTE para poder avanzar o para dar el caso por cerrado.\n"
                "- pide_confirmacion=true si el comentario o sus 'próximos pasos' implican: coordinar un "
                "día u horario para hacer un trabajo o una visita; reubicar, mover, instalar o reemplazar "
                "algo que hay que ACORDAR con el cliente; pedir una aprobación, un OK o una confirmación; "
                "quedar a la espera de una decisión o respuesta del cliente; o que el CLIENTE tenga que "
                "gestionar algo de su lado para cerrarlo del todo (escalarlo o derivarlo a otra área "
                "suya, revisar/reconectar/reparar un equipo o un enlace que es de él, dar de alta o "
                "corregir un dato en un sistema suyo). Cuenta AUNQUE esté escrito en tercera persona o "
                "de forma impersonal (ej.: 'se deberá coordinar la reubicación', 'próximos pasos: "
                "coordinar el reemplazo y la visita', 'a coordinar con el cliente', 'queda sujeto a la "
                "confirmación del cliente').\n"
                "- IMPORTANTE: también es true cuando el comentario dice que UNA PARTE quedó resuelta "
                "pero QUEDA ALGO PENDIENTE del lado del cliente para que quede resuelto del todo (ej.: "
                "'se solucionó el acceso, pero la terminal de la sede está desconectada'). Que una "
                "parte esté lista no cierra el caso si falta algo de él.\n"
                "- pide_confirmacion=false SOLO si es una SOLUCIÓN completa y cerrada, un avance "
                "puramente interno del equipo, o información que NO necesita ninguna respuesta ni "
                "ninguna gestión del cliente.\n"
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
        """Redacta, PARA EL CLIENTE, qué necesitamos de él, a partir de lo que planteó el técnico.

        Tiene que quedar claro QUÉ TIENE QUE HACER, no sólo que estamos esperando: si el técnico
        avanzó una parte y falta algo del lado del cliente (que lo derive a otra área suya, que
        revise un equipo propio), el mensaje lo dice con todas las letras. Si la IA no está, va un
        texto genérico."""
        try:
            r = self.ia.chat(
                "Un TÉCNICO de soporte dejó un comentario en un ticket y para seguir hace falta algo "
                "DEL CLIENTE. Redactá un mensaje BREVE y profesional PARA EL CLIENTE (de usted).\n"
                "Tiene que tener, en este orden y en pocas líneas:\n"
                "1. Qué se hizo o qué se resolvió hasta ahora, si el comentario lo dice.\n"
                "2. QUÉ FALTA y POR QUÉ el caso todavía no se puede dar por cerrado.\n"
                "3. QUÉ NECESITAMOS DE ÉL, concreto y accionable: coordinar un día y horario, dar el "
                "OK, o gestionar algo de su lado. Que quede claro qué tiene que hacer, no sólo que "
                "estamos esperando.\n"
                "REGLA para el punto 3: si lo que falta está en la INFRAESTRUCTURA DEL CLIENTE —un "
                "equipo o una terminal desconectada, sin energía o sin red—, pedile expresamente que "
                "lo ESCALE al área de sistemas/IT de su organización para que revisen ese equipo, y "
                "que verifiquen que esté ENERGIZADO y que tenga CONEXIÓN DE RED. Aclarále que en "
                "cuanto vuelva a estar en línea podemos sincronizarlo y dar el caso por cerrado.\n"
                "No inventes datos ni pasos que el comentario no diga; no uses tecnicismos internos "
                "ni nombres de consultas o archivos. Terminá con 'Quedamos a la espera de su "
                "respuesta. Soporte ITH.'. Respondé SOLO el mensaje.",
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


# El CICLO DE VIDA (lo que pasa después del triage) vive en `ciclo.py`. Se re-exporta para que
# quien ya importaba `triage.gestionar_ciclo` siga funcionando igual.
from ciclo import gestionar_ciclo   # noqa: E402,F401
