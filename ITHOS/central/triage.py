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


# El saludo al solicitante vive en comun/glpi.py (compartido con el camino de voz aplicar_ciclo).
_saludo_solicitante = G.saludo_solicitante

# Lo que la SOLUCIÓN que lee el cliente no puede ser: una copia de lo que el técnico ya escribió.
_TOPE_RESUMEN = 700          # caracteres: una solución para el cliente es corta, no un informe
_VENTANA_COPIA = 10          # palabras seguidas iguales -> es un pegado, no un resumen


def _palabras(texto):
    """Las palabras de un texto, en minúscula y sin puntuación, para poder compararlo."""
    return re.findall(r"\w+", str(texto or "").lower(), flags=re.UNICODE)


def _repite_al_tecnico(resumen, original):
    """¿El `resumen` es en realidad el texto del técnico otra vez?

    POR QUÉ EXISTE. La solución que ve el cliente tiene que ser un resumen corto, NO el comentario
    del técnico copiado: en el ticket #803 el cliente leyó dos veces el mismo procedimiento interno
    (nombres de scripts, consultas a la base, parámetros de la terminal). Pedirle a la IA que
    resuma no alcanza como garantía —puede devolver el texto casi intacto—, así que se comprueba.

    Se considera copia si el resumen es casi tan largo como el original, o si arrastra una tirada
    de `_VENTANA_COPIA` palabras seguidas igual que el original. Comparar palabra por palabra (y no
    el texto crudo) evita que un cambio de comillas o de salto de línea lo dé por distinto."""
    pr, po = _palabras(resumen), _palabras(original)
    if not pr or not po:
        return False
    # El piso de palabras va por encima de lo que se le pide a la IA (50), así que un resumen
    # legítimo de un comentario corto nunca se descarta por largo: lo descarta la regla de abajo,
    # que es la que mira si el texto es el mismo.
    if len(resumen) > _TOPE_RESUMEN or len(pr) > max(len(po) * 0.6, 55):
        return True
    if len(po) < _VENTANA_COPIA:
        return False
    tiradas = {" ".join(po[i:i + _VENTANA_COPIA]) for i in range(len(po) - _VENTANA_COPIA + 1)}
    unido = " ".join(pr)
    return any(t in unido for t in tiradas)


class Triage:
    @property
    def ent(self):
        """La entidad PRINCIPAL del cliente. Sale siempre de la config, así vale también para un
        Triage armado a mano (los tests) sin depender de que alguien la haya seteado."""
        return int((self.cfg_glpi or {}).get("entity_id", 0) or 0)

    def __init__(self, cfg_glpi, cfg_ia, gestor=None):
        self.cfg_glpi = cfg_glpi
        # SESIÓN DEL POOL, reutilizada. Antes era un cliente propio, y como cada método hace
        # `abrir()` … `cerrar()`, cada acción sobre un ticket costaba CUATRO viajes a GLPI:
        # initSession + changeActiveEntities + la operación + killSession. Peor: una operación
        # lógica como "resolver y pedir confirmación" abría y cerraba TRES sesiones. Con el pool,
        # `abrir()` encuentra la sesión viva y `cerrar()` es un no-op (no la mata), así que queda
        # UN viaje por operación. Si la sesión expira, `request()` la reabre sola.
        self.cli = G.sesion(cfg_glpi, cfg_glpi["glpi_ithos_token"])
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
        una asignación MANUAL: si ya hay un técnico humano, ITHOS no vuelve a auto-asignar el default.

        PROPAGA el error de lectura a propósito. Antes lo atrapaba y devolvía un conjunto vacío,
        pero vacío significa «no hay nadie asignado», que es indistinguible de «no pude leer».
        Confundir las dos cosas hacía que una caída pasajera de GLPI se leyera como «ticket sin
        triagear» y ITHOS volviera a categorizar y asignar un ticket YA trabajado, pisándole la
        decisión al técnico. Quién llama decide qué hacer cuando no se puede leer."""
        us = self.cli.request(f"/Ticket/{tid}/Ticket_User")
        return {int(u.get("users_id") or 0) for u in us
                if isinstance(u, dict) and int(u.get("type") or 0) == 2}

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
        # OJO con el caso "no se pudo leer": antes el error se tragaba y `asignados` quedaba VACÍO,
        # que es exactamente lo mismo que dice un ticket todavía sin triagear. Resultado: una caída
        # pasajera de GLPI —y el MySQL compartido del hosting rechaza conexiones de a ratos— hacía
        # que ITHOS re-triageara un ticket YA trabajado y le pisara la categoría y la asignación al
        # técnico, que es justo lo que no puede pasar. Ante la duda NO se triagea: reintentar en la
        # vuelta siguiente (~1 minuto) no cuesta nada; pisar el trabajo de una persona, sí.
        asignados = set()
        try:
            self.cli.abrir()
            asignados = self._tecnicos_asignados(tid)
            if ITHOS_ID in asignados and int(ticket.get("status") or 1) == 1:
                self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 2}})
        except Exception as e:  # noqa: BLE001
            log.warning("Triage #%s: no pude leer quién está asignado (%s). NO lo triageo en esta "
                        "vuelta; si ya estaba trabajado, re-triagearlo pisaría al técnico.",
                        tid, str(e)[:120])
            return None
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
            fallaron = []
            for uid in a_poner:
                if uid in asignados:
                    continue
                try:
                    self.cli.request("/Ticket_User", "POST",
                                     {"input": {"tickets_id": tid, "users_id": uid,
                                                "type": 2}})
                except Exception as e:  # noqa: BLE001
                    fallaron.append((uid, str(e)[:90]))
            # El error ESPERADO acá es que GLPI rechace un alta duplicada (ERROR_GLPI_ADD): el
            # responsable ya estaba puesto y el estado final es el correcto. Antes se tragaba
            # cualquier excepción por igual, así que una caída de GLPI dejaba el ticket SIN
            # responsable y en silencio. En vez de adivinar por el texto del error, se vuelve a
            # leer QUIÉN quedó asignado: si falta alguno, eso sí es un problema y se avisa.
            if fallaron:
                try:
                    quedaron = self._tecnicos_asignados(tid)
                except Exception as e:  # noqa: BLE001
                    # Si tampoco se puede releer, se avisa igual: lo que no puede pasar es que un
                    # ticket se quede sin responsable y nadie se entere.
                    log.warning("Triage #%s: no pude verificar la asignación (%s).", tid, str(e)[:90])
                    quedaron = set()
                faltan = [uid for uid, _ in fallaron if uid not in quedaron]
                if faltan:
                    log.error("Triage #%s: NO se pudo asignar a %s (%s). El ticket queda sin esos "
                              "responsables: hay que asignarlos a mano.",
                              tid, faltan, fallaron[0][1])
            self._habilitar_respuesta_del_cliente(tid, humanos)
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

    def _habilitar_respuesta_del_cliente(self, tid, humanos):
        """Que la gente del CLIENTE que sigue el ticket pueda RESPONDERLO.

        En SRT los compañeros del área se agregan como OBSERVADORES para estar al tanto. Pero la
        mesa de ayuda sólo deja escribir a los SOLICITANTES: el que no abrió el ticket lo ve y no
        tiene dónde contestar. Pasó de verdad (#673: lo abrió una persona y la otra no podía ni
        responder), y rompe el circuito entero, porque la confirmación del cierre la da el cliente.

        Se los suma como solicitantes —sin sacarles el rol de observador— y sólo a ellos: los
        técnicos y ITHOS no se tocan."""
        try:
            actores = self.cli.request(f"/Ticket/{tid}/Ticket_User") or []
        except Exception:  # noqa: BLE001
            return
        equipo = set(humanos or ()) | {ITHOS_ID}
        solicitantes = {int(u.get("users_id") or 0) for u in actores if int(u.get("type", 0)) == 1}
        for u in actores:
            uid = int(u.get("users_id") or 0)
            if int(u.get("type", 0)) != 3 or uid in equipo or uid in solicitantes:
                continue                       # sólo observadores del CLIENTE que no son ya solicitantes
            try:
                self.cli.request("/Ticket_User", "POST", {"input": {
                    "tickets_id": tid, "users_id": uid, "type": 1}})
                log.info("Triage #%s: %s podrá responder el ticket (estaba sólo de observador).",
                         tid, uid)
            except Exception:  # noqa: BLE001
                pass                           # no es fatal: el ticket igual queda atendido

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

    def resumen_para_el_cliente(self, texto):
        """El comentario del técnico, resumido en una o dos líneas PARA EL CLIENTE.

        EL PROBLEMA QUE RESUELVE (ticket #803). La solución se cargaba con el comentario del
        técnico copiado tal cual. Como ese comentario es PÚBLICO, el cliente terminaba leyendo dos
        veces exactamente lo mismo, y encima el detalle interno —nombres de scripts, consultas a la
        base de datos, parámetros de la terminal— que no es para él.

        La explicación técnica NO se pierde ni se mueve: sigue donde estaba, en el comentario del
        técnico. Lo único que cambia es la SOLUCIÓN, que pasa a decir en criollo qué quedó resuelto.

        Si la IA no contesta, o contesta algo que es el texto del técnico otra vez, se carga un
        texto genérico. Es a propósito: una solución corta y sin detalle sigue cumpliendo lo único
        que GLPI necesita de ella —que el cliente tenga qué aprobar o rechazar—, y el detalle ya lo
        tiene a la vista. Repetirle el texto sería peor que no resumirlo."""
        generico = ("El equipo técnico resolvió el inconveniente reportado. El detalle de lo "
                    "realizado quedó asentado en el ticket.")
        limpio = str(texto or "").strip()
        if not limpio:
            return generico
        try:
            r = (self.ia.chat(
                "Sos de la mesa de ayuda ITH. Un TÉCNICO dejó un comentario explicando cómo "
                "resolvió un ticket. Escribí la SOLUCIÓN que va a leer el CLIENTE.\n"
                "- UNA o DOS oraciones. Nunca más de 50 palabras.\n"
                "- Decí QUÉ quedó resuelto y qué puede hacer ahora el cliente, no CÓMO se hizo.\n"
                "- PROHIBIDO copiar frases del comentario: es un resumen, no un recorte.\n"
                "- PROHIBIDO nombrar detalle interno: scripts, archivos .sql, consultas, tablas, "
                "bases de datos, rutas, direcciones IP, comandos, parámetros de configuración ni "
                "herramientas nuestras.\n"
                "- Español rioplatense, de usted, cordial y sobrio. Sin emojis, sin saludo inicial "
                "y sin firma: eso lo pone el sistema aparte.\n"
                "Respondé SOLO el texto de la solución, sin comillas.",
                limpio, json_out=False) or "").strip()
        except Exception as e:  # noqa: BLE001
            log.info("Triage: no pude resumir la solución para el cliente (%s); va la genérica.",
                     str(e)[:90])
            return generico
        r = re.sub(r"<[^>]+>", " ", r)
        r = re.sub(r"\s+", " ", r).strip().strip('"').strip()
        if not r or _repite_al_tecnico(r, limpio):
            log.info("Triage: el resumen de la solución repetía el texto del técnico; va la "
                     "genérica (al cliente no se le repite lo que ya leyó).")
            return generico
        return r

    def a_confirmacion_del_cliente(self, tid, solucion, autor=None):
        """El técnico resolvió: el ticket queda ESPERANDO QUE EL CLIENTE CONFIRME.

        QUÉ SE CARGA COMO SOLUCIÓN: un RESUMEN corto escrito para el cliente
        (`resumen_para_el_cliente`), NO el comentario del técnico copiado. Su explicación ya está
        en el ticket y es pública: repetirla entera en la solución le hacía leer dos veces lo mismo.

        A NOMBRE DE QUIÉN: del técnico que resolvió (`autor`), cuando tiene su token configurado.
        Si la carga ITHOS, el historial del ticket dice que resolvió ITHOS, y no es verdad.

        POR QUÉ QUEDA EN 'RESUELTO' Y NO EN 'EN ESPERA': se probó dejarlo en espera, que describe
        mejor la situación, y la mesa de ayuda entonces NO le dibuja al cliente los botones de
        APROBAR / RECHAZAR —sólo el cuadro de responder—. Esos botones son el modo natural en que
        el cliente cierra o rechaza, así que se elige tenerlos. No se pierde nada de lo otro: al
        resolver queda grabada la fecha de solución, con lo cual el SLA de resolución deja de
        correr, y el vigilante tampoco alerta por un ticket resuelto. Y si el cliente contesta
        escribiendo en vez de apretar el botón, también se cierra o se reabre."""
        if not self.marcar_resuelto(tid, self.resumen_para_el_cliente(solucion), autor=autor):
            return False
        self.pedir_confirmacion(tid)
        try:
            self.cli.abrir()
            # Que haya quedado como corresponde no se da por hecho: se comprueba. El ticket tiene
            # que estar RESUELTO y la solución PENDIENTE de aprobación; si algo lo movió, se
            # corrige (un ticket a medio camino no se lo nota nadie hasta que es tarde).
            if int((self.cli.request(f"/Ticket/{tid}") or {}).get("status", 0)) != 5:
                self.cli.request(f"/Ticket/{tid}", "PUT", {"input": {"status": 5}})
            sol = self.cli.request(f"/Ticket/{tid}/ITILSolution") or []
            if sol:
                ultima = sorted(sol, key=lambda s: int(s.get("id") or 0))[-1]
                if int(ultima.get("status") or 0) != 2:
                    self.cli.request(f"/ITILSolution/{ultima['id']}", "PUT", {"input": {
                        "id": ultima["id"], "status": 2}})     # 2 = pendiente del cliente
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Triage #%s: no pude dejarlo esperando la confirmación: %s", tid, e)
            return False
        finally:
            self.cli.cerrar()

    def marcar_resuelto(self, tid, solucion="", autor=None):
        """Pasa el ticket a RESUELTO (status 5), cargando la SOLUCIÓN cuando se le pasa el texto.

        POR QUÉ IMPORTA LA SOLUCIÓN: en GLPI el cliente aprueba o rechaza LA SOLUCIÓN. Un ticket
        que pasa a Resuelto sin cargar ninguna no le deja al solicitante nada que aprobar ni que
        rechazar: ve el ticket resuelto y no tiene cómo decir "sigue igual". Con la solución
        cargada, la mesa de ayuda la deja pendiente de su aprobación y le muestra los dos botones.

        A NOMBRE DE QUIÉN SE CARGA: de `autor`, el técnico que resolvió, siempre que tenga su
        token configurado (`_sesion_de`). Si la carga ITHOS, el historial dice que el que resolvió
        fue ITHOS —y en el ticket #803 lo dijo, con la resolución escrita por una técnica que sí
        tenía token—. Cuando no hay token para ese técnico, la carga ITHOS: es el último recurso,
        porque sin solución cargada el cliente se queda sin los botones.

        El TEXTO que se le pasa acá ya viene resumido para el cliente (ver
        `a_confirmacion_del_cliente`): esta función no reescribe nada, carga lo que recibe.

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
            except Exception as e:  # noqa: BLE001
                # Último recurso: dejarlo resuelto igual. Pero SIN solución el cliente no tiene en
                # la mesa de ayuda los botones de aprobar/rechazar, así que esto se avisa fuerte:
                # es un ticket que va a quedar esperando una confirmación que él no puede dar.
                log.warning("Triage #%s: NO pude cargar la solución (%s). El ticket queda resuelto "
                            "pero el cliente no va a poder aprobarla ni rechazarla.", tid, str(e)[:120])
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
        """Agrega el comentario. Devuelve True si GLPI lo ACEPTÓ, False si lo rechazó.

        NO FATAL: si GLPI rechaza el followup (p. ej. el usuario MySQL de GLPI sin permiso INSERT en
        glpi_itilfollowups), NO abortamos el cambio de estado que hace el caller (en espera / cerrar /
        etc.). El comentario no se agrega, pero el ESTADO del ticket igual queda correcto.

        PERO EL RESULTADO SE DEVUELVE, y eso importa: los avisos al cliente se espacian mirando el
        ÚLTIMO comentario que quedó EN EL TICKET. Si acá se traga el error y el caller contesta que
        mandó algo que nunca se escribió, el ciclo cree que el aviso salió, el ticket no cambia, y en
        la vuelta siguiente lo vuelve a intentar. Para siempre. Que el caller sepa la verdad."""
        try:
            self.cli.request("/ITILFollowup", "POST",
                             {"input": {"itemtype": "Ticket", "items_id": tid, "content": texto}})
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("No pude agregar el comentario a #%s (¿permiso INSERT de GLPI en "
                        "glpi_itilfollowups?): %s", tid, str(e)[:120])
            return False

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
            return self._followup(tid, _texto_recordatorio_espera(motivo))
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
            return self._followup(
                tid, "Le informamos que su solicitud fue resuelta. Por favor, confírmenos si ya "
                     "puede fichar con normalidad para cerrar el ticket; si el inconveniente "
                     "persiste, respóndanos y lo reabrimos de inmediato. Saludos, Soporte ITH.")
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
            return self._followup(
                tid, "Le recordamos que su ticket figura como resuelto. Por favor confírmenos si "
                     "ya puede fichar con normalidad para cerrarlo; si el inconveniente continúa, "
                     "respóndanos y lo reabrimos. Soporte ITH.")
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
                "- MIRÁ QUIÉN HACE LA ACCIÓN, no si la tarea está pendiente. Si el que la va a hacer "
                "es EL EQUIPO DE SOPORTE ('vamos a encargar el repuesto', 'lo pedimos nosotros', 'ya "
                "solicitamos el recambio', 'queda a la espera del proveedor'), eso es TRABAJO NUESTRO "
                "y va false, por más que falte tiempo para terminarlo. Sólo es true si hace falta que "
                "el CLIENTE haga algo o responda algo.\n"
                "- Y MIRÁ CUÁNDO. Si lo que involucra al cliente es para MÁS ADELANTE y depende de "
                "algo nuestro que todavía no pasó ('cuando llegue la pieza coordinamos', 'una vez "
                "instalado le avisamos', 'apenas esté lo vemos con ustedes'), TODAVÍA no le estamos "
                "pidiendo nada: va false. Se le pedirá cuando llegue el momento.\n"
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
