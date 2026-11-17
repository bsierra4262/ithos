#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QUIÉN es el equipo de soporte de cada cliente.

Separar esto importa: es lo que distingue un comentario NUESTRO de una respuesta del CLIENTE. Un
técnico que no esté acá se lee como si fuera el cliente —su resolución no cierra el ticket y el
ciclo cree que el cliente contestó—, así que sumar a alguien al equipo es cargarlo en la config
(`tecnicos`), nunca tocar código.
"""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_AQUI, ".."), _AQUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Equipo por DEFECTO (SRT/ITH), sólo como respaldo si el cliente todavía no cargó el suyo.
RESPONSABLES = {"bsierra": 7, "jayala": 8, "lzaltron": 30, "lcampos": 31}
NOMBRES = {"bsierra": "Brian Sierra", "jayala": "Alejandro Ayala",
           "lzaltron": "Laura Zaltron", "lcampos": "Lisandro Campos"}
ITHOS_ID = 28
# CUENTAS INTERNAS de la mesa de ayuda: no son personas del cliente ni del equipo, y no tienen que
# figurar en ningún ticket. Hoy es una: `admin` (id 2), la cuenta de súper administrador que GLPI
# crea al instalarse. Ve todos los tickets igual, así que agregarla no le suma nada a nadie.
# Pasó de verdad: los clientes la elegían como observador en el formulario y ITHOS, que pasa a
# solicitantes a los observadores del cliente para que puedan responder, la tomaba por uno de
# ellos: quedaba como SOLICITANTE en 17 tickets. Se puede ampliar por cliente (`cuentas_internas`).
CUENTAS_INTERNAS = {2}
TECNICOS = {28, 7, 8, 30, 31}
TECNICOS_HUMANOS = {7, 8, 30, 31}  # técnicos personas (sin ITHOS): sus comentarios pueden resolver

# ---------------------------------------------------------------------------------------------
# A QUIÉN LE ENTRA CADA TICKET (decisión de Brian, 17-nov-2026).
#
# Los chicos ya tienen autonomía para resolver, así que el día a día es de ellos y no pasa por
# Brian. Son tres destinos y el orden importa:
#
#   1. INSTALACIONES — equipamiento caído en una sede. Hay que IR al lugar, así que lo toma
#      Alejandro, pase lo que pase con la prioridad. Gana sobre las otras dos reglas.
#   2. ESCALAMIENTO — lo que sale Alta o Urgente, o sea un sector, una sede o varias sedes sin
#      poder fichar. Eso lo mira Brian.
#   3. MESA — todo lo demás (Baja y Media): lo trabajan Laura y Lisandro.
#
# La mesa se reparte POR CARGA: cada ticket va al que tenga menos tickets abiertos en ese
# momento. Turnarse a ciegas no sirve, porque dos tickets seguidos no cuestan lo mismo y al que
# le toca el complicado se le acumulan los que vienen atrás.
MESA = ("lzaltron", "lcampos")     # el día a día, repartido por carga
INSTALACIONES = "jayala"           # hay que ir al lugar
ESCALAMIENTO = "bsierra"           # Alta y Urgente
# Valor que usa el clasificador cuando el ticket es para la mesa: la PERSONA la elige el triage,
# que es el único que puede preguntarle a GLPI cuántos tickets abiertos tiene cada uno.
MESA_PENDIENTE = "mesa"


def menos_cargado(cfg_glpi, logins=MESA):
    """De `logins`, el que tenga MENOS tickets abiertos ahora. Ante un empate, el primero.

    Se le pregunta a GLPI, que es la única fuente que sabe la verdad: un contador nuestro se
    desincroniza en cuanto alguien asigna un ticket a mano, y acá eso pasa todo el tiempo.

    SI GLPI NO CONTESTA no se rompe nada: devuelve el primero de la lista. El ticket entra igual
    y con responsable; lo peor que pasa es que el reparto quede desparejo esa vez. Dejar un
    ticket sin asignar por no poder contar sería mucho peor."""
    from comun import glpi as G
    from comun import tickets as TK
    cargas = []
    try:
        cli = G.sesion(cfg_glpi)
        for login in logins:
            uid = RESPONSABLES.get(login)
            ficha = TK.tecnico_por_id(cfg_glpi, login) or {}
            try:
                uid = int(ficha.get("glpi_id") or uid)
            except (TypeError, ValueError):
                pass
            if not uid:
                continue
            # Campo 5 = 'Asignado a' (el TÉCNICO), nunca observador ni solicitante. Campo 12 = el
            # estado, que se filtra acá: sólo cuentan los ABIERTOS (nuevo / en curso / en espera).
            r = cli.request(f"/search/Ticket?criteria[0][field]=5&criteria[0][searchtype]=equals"
                            f"&criteria[0][value]={uid}&forcedisplay[0]=12&range=0-300")
            abiertos = sum(1 for d in (r.get("data") or [])
                           if str(d.get("12") or "0") in ("1", "2", "4"))
            cargas.append((abiertos, login))
    except Exception:  # noqa: BLE001
        return logins[0]
    if not cargas:
        return logins[0]
    # min() sobre la TUPLA desempataría por el login, o sea alfabéticamente. Se ordena sólo por la
    # cantidad: así el empate lo gana el primero de `logins`, que es lo que dice el contrato.
    return min(cargas, key=lambda c: c[0])[1]


def ids_humanos(cfg):
    """Ids de los TÉCNICOS PERSONAS del cliente (sin ITHOS), leídos de su config `tecnicos`. Sus
    comentarios resuelven un ticket y son los que reciben las @menciones. Si el cliente todavía no
    tiene el equipo cargado, se usa el de SRT/ITH por defecto."""
    from comun import tickets as TK
    ids = set()
    for t in TK.tecnicos(cfg):
        try:
            ids.add(int(t.get("glpi_id") or t.get("id")))
        except (TypeError, ValueError):
            pass
    return (ids or set(TECNICOS_HUMANOS)) - {ITHOS_ID}


def cuentas_internas(cfg):
    """Las cuentas que no tienen que figurar en ningún ticket: las de siempre más las que el
    cliente agregue en su config (`cuentas_internas: [ids]`)."""
    extra = set()
    for v in ((cfg or {}).get("cuentas_internas") or []):
        try:
            extra.add(int(v))
        except (TypeError, ValueError):
            pass
    return set(CUENTAS_INTERNAS) | extra


def ids_tecnicos(cfg):
    """Los técnicos personas MÁS ITHOS: quiénes hablan 'del lado de soporte' en un ticket."""
    return ids_humanos(cfg) | {ITHOS_ID}


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
