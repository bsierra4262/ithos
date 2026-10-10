#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrador GLPI (pluggable). Vigila tickets nuevos de un cliente, los TRIAGEA
(clasifica/asigna/responde vía ITHOS) y empuja los anuncios de voz al agente.
Maneja el seguimiento (respuesta del cliente -> en curso; recordatorio diario).

Corre en el CENTRAL (GLPI nube, ej. ITH) o en el AGENTE (GLPI privado): mismo
código, cambia dónde se instancia. enviar_comando(cmd) y wa (WhatsApp) son callbacks.
"""

import os
import sys
import asyncio
import logging

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from comun import glpi as G   # noqa: E402
import triage as T            # noqa: E402

log = logging.getLogger("integrador.glpi")

# Cada cuántas vueltas se revisa el histórico COMPLETO en busca de tickets olvidados en 'Nuevo'.
# Con el intervalo por defecto (60 s) son ~10 minutos: suficiente para que nada quede colgado y
# lo bastante espaciado para no leer todo el histórico a cada rato.
_VUELTAS_BARRIDO = 10


def pendientes_triage(recientes):
    """Tickets que NECESITAN primera respuesta / triage: los que están en estado NUEVO (status 1).
    El triage los mueve a En curso / En espera y asigna a ITHOS, así dejan de estar en 'Nuevo' y
    NO se re-procesan. Incluye los que entraron mientras ITHOS estaba apagado: al arrancar se pone
    al día (no depende de haber corrido 24/7). Ordenados por id (los más viejos primero)."""
    return sorted((t for t in recientes if isinstance(t, dict) and int(t.get("status", 1)) == 1),
                  key=lambda x: int(x.get("id", 0)))


async def vigilar(cfg_glpi, enviar_comando, triage=None, wa=None, stop=None,
                  nombre_cliente="cliente"):
    from comun import metricas
    # TODAS las entidades del cliente, no sólo la principal: un cliente tiene una entidad por área
    # (mesa de ayuda, soporte técnico, infraestructura) y los tickets entran por cualquiera de ellas.
    entidad = G.entidades_de(cfg_glpi)
    # Una mesa de ayuda no necesita que la miren cada pocos segundos: cada vuelta lee los tickets,
    # sus seguimientos y consulta la IA. A 5s eran 17.280 vueltas por día contra GLPI (y contra la
    # cuota de IA) para atender un puñado de tickets.
    intervalo = cfg_glpi.get("poll_interval", 60)
    # CON EL TOKEN DE ITHOS, no con el de super admin. `GLPIClient(cfg)` sin token cae a
    # `glpi_user_token`, que es el usuario administrador: el único que puede BORRAR. Todo el ciclo
    # de vida —leer, comentar, cambiar estados— estaba corriendo con ese permiso, cuando ITHOS
    # tiene a propósito un perfil acotado ("Crear y Asignar Tickets") para que un error suyo no
    # pueda destruir nada. El privilegio mínimo no es un detalle: es el diseño.
    cliente = G.GLPIClient(cfg_glpi, token=(cfg_glpi.get("glpi_ithos_token")
                                            or cfg_glpi.get("glpi_user_token")))
    seg_estado = {}
    anunciados = set()          # tickets ya anunciados (para no repetir el aviso de llegada)
    log.info("GLPI integrador iniciado (entidades %s, cada %ss, triage=%s).",
             entidad, intervalo, triage is not None)

    async def decir(texto, cachear=False):
        await enviar_comando({"accion": "decir", "texto": texto, "cachear": cachear})

    async def avisar_wa(mensaje, telefonos=None):
        """Manda el aviso por WhatsApp @MENCIONANDO al TÉCNICO ASIGNADO (solo a él) cuando se sabe
        su teléfono (config 'tecnicos'). Si el canal no soporta menciones o no hay teléfono, va el
        aviso normal — nunca se pierde."""
        if not wa or not mensaje:
            return
        from comun import ambitos as AV
        fn = getattr(wa, "enviar_mencion", None)
        if telefonos and fn:
            await asyncio.to_thread(lambda: AV.llamar(fn, mensaje, telefonos, tipo=AV.TICKETS))
        else:
            await asyncio.to_thread(lambda: AV.llamar(wa.enviar, mensaje, tipo=AV.TICKETS))

    fallos = 0
    vueltas = 0
    while stop is None or not stop.is_set():
        try:
            vueltas += 1
            # BARRIDO COMPLETO cada tanto. El poll normal mira los 30 tickets MÁS NUEVOS, que es lo
            # que hace falta para atender lo que entra. Pero un ticket que QUEDE en 'Nuevo' —porque
            # su triage falló, o porque entraron treinta más mientras tanto— va saliendo de esa
            # ventana y no se vuelve a mirar NUNCA: deja de existir para el circuito, sin categoría,
            # sin asignar, sin primera respuesta y sin SLA corriendo. Que hoy no pase depende del
            # volumen de tickets y de que el triage no falle, y ninguna de las dos es una garantía.
            # Cada `_VUELTAS_BARRIDO` se mira el histórico entero para rescatarlos.
            def leer():
                if cliente.session is None:
                    cliente.abrir()
                if vueltas % _VUELTAS_BARRIDO == 1:
                    return G.de_entidad(cliente.todos_tickets(), entidad)
                return G.de_entidad(cliente.tickets_recientes(30), entidad)
            recientes = await asyncio.to_thread(leer)
            fallos = 0                              # lectura OK -> resetea el backoff

            # Triage de los tickets en estado NUEVO (status 1). No se gatilla por 'id > baseline'
            # sino por ESTADO: así atiende también los que entraron con ITHOS apagado (al arrancar
            # se pone al día). El triage los pasa a En curso/En espera -> dejan de estar en 'Nuevo'
            # y no se re-procesan. Reintenta si un triage falló (sigue en 'Nuevo'), sin re-anunciar.
            for t in pendientes_triage(recientes):
                tid = int(t["id"])
                if tid not in anunciados:                 # aviso de llegada UNA sola vez por ticket
                    anunciados.add(tid)
                    log.info("Ticket a triage #%s: %s", tid, t.get("name"))
                    metricas.registrar(nombre_cliente, "ticket")
                    metricas.registrar(nombre_cliente, "anuncio")
                    await decir(G.frase_ticket(t))
                    await avisar_wa(G.mensaje_ticket(t))   # recién llega: todavía sin asignado
                if triage is not None:
                    res = await asyncio.to_thread(triage.procesar, t)
                    if res:
                        await decir(T.frase_triage(res, t))
                        # Ya quedó asignado -> el aviso @menciona al TÉCNICO ASIGNADO (solo a él).
                        await avisar_wa(T.mensaje_triage(res, t), res.get("telefonos"))

            # 3) Seguimiento (respuesta del cliente / recordatorio)
            if triage is not None:
                anuncios = await asyncio.to_thread(
                    T.gestionar_ciclo, cliente, triage, entidad, seg_estado)
                for an in anuncios:
                    if an.get("texto"):
                        await decir(an["texto"])
                    await avisar_wa(an.get("wa"), an.get("tel"))
        except Exception as e:  # noqa: BLE001
            fallos += 1
            # No spamear: loguea el 1º error y luego 1 de cada 12 (con el MOTIVO de GLPI en el mensaje).
            if fallos == 1 or fallos % 12 == 0:
                log.warning("GLPI integrador error (x%d): %s", fallos, e)
            cliente.session = None
        # Backoff ante errores PERSISTENTES (ej. 400 de config): del intervalo normal hasta 60s, así
        # deja de golpear GLPI cada 5s. Con la lectura OK vuelve al intervalo normal.
        await asyncio.sleep(intervalo if fallos == 0 else min(60, intervalo * (2 ** min(fallos, 4))))
