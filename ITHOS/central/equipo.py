#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QUIÉN es el equipo de soporte y a quién le entra cada ticket. TODO sale de la CONFIGURACIÓN
(clientes.json), nunca del código:

  · `tecnicos`: las personas (glpi_id, glpi_login, nombre, teléfonos, responsable).
  · `integrador_glpi.ithos_user_id`: la cuenta de ITHOS en GLPI.
  · `reparto`: qué login cubre cada ROL del triage —
        {"mesa": ["login1", "login2"], "instalaciones": "login3", "escalamiento": "login4"}

Separar el equipo importa: es lo que distingue un comentario NUESTRO de una respuesta del
CLIENTE. Un técnico que no esté en la config se lee como si fuera el cliente —su resolución no
cierra el ticket y el ciclo cree que el cliente contestó—, así que sumar a alguien es cargarlo
en la config. Se lee al importar (el Gestor se reinicia cuando la config cambia).

A QUIÉN LE ENTRA CADA TICKET (decisión de Brian, 17-nov-2026). Tres roles, y el orden importa:
  1. INSTALACIONES — equipamiento caído en una sede. Hay que IR al lugar: gana sobre las otras.
  2. ESCALAMIENTO — lo que sale Alta o Urgente (un sector, una sede o varias sin poder fichar).
  3. MESA — todo lo demás (Baja y Media), repartido POR CARGA: cada ticket va al que tenga
     menos tickets abiertos en ese momento. Turnarse a ciegas no sirve: dos tickets seguidos
     no cuestan lo mismo y al que le toca el complicado se le acumulan los que vienen atrás.
"""

import json
import logging
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_AQUI, ".."), _AQUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

log = logging.getLogger("equipo")

# Se llenan EN EL LUGAR desde la config (`configurar`): quien los importó ve siempre lo vigente.
RESPONSABLES = {}          # login -> id de GLPI
NOMBRES = {}               # login -> nombre
TECNICOS = set()           # ids de soporte: las personas + ITHOS
TECNICOS_HUMANOS = set()   # las personas (sus comentarios pueden resolver un ticket)
MESA = []                  # logins del rol "mesa"
ROLES = {}                 # rol -> login ("instalaciones", "escalamiento")
ITHOS_ID = None            # cuenta de ITHOS en GLPI

# CUENTAS INTERNAS de la mesa de ayuda: no son personas del cliente ni del equipo, y no tienen que
# figurar en ningún ticket. Hoy es una: `admin` (id 2), la cuenta de súper administrador que GLPI
# crea al instalarse. Pasó de verdad: los clientes la elegían como observador y ITHOS, que pasa a
# solicitantes a los observadores del cliente, la dejaba como SOLICITANTE. Se amplía por config
# (`cuentas_internas`).
CUENTAS_INTERNAS = {2}

# Valor que usa el clasificador cuando el ticket es para la mesa: la PERSONA la elige el triage,
# que es el único que puede preguntarle a GLPI cuántos tickets abiertos tiene cada uno.
MESA_PENDIENTE = "mesa"


def configurar(cfg):
    """Carga el equipo desde la config (`tecnicos`, `reparto`, `integrador_glpi.ithos_user_id`)."""
    global ITHOS_ID
    cfg = cfg or {}
    gl = cfg.get("integrador_glpi") or {}
    RESPONSABLES.clear()
    NOMBRES.clear()
    TECNICOS_HUMANOS.clear()
    for t in (cfg.get("tecnicos") or gl.get("tecnicos") or []):
        if not isinstance(t, dict):
            continue
        try:
            uid = int(t.get("glpi_id") or t.get("id"))
        except (TypeError, ValueError):
            continue
        login = str(t.get("glpi_login") or t.get("login") or "").strip().lower()
        if login:
            RESPONSABLES[login] = uid
            NOMBRES[login] = t.get("nombre") or login
        TECNICOS_HUMANOS.add(uid)
    try:
        ITHOS_ID = int(gl.get("ithos_user_id") or cfg.get("ithos_user_id"))
    except (TypeError, ValueError):
        ITHOS_ID = None
    TECNICOS.clear()
    TECNICOS.update(TECNICOS_HUMANOS | ({ITHOS_ID} if ITHOS_ID else set()))
    reparto = cfg.get("reparto") or gl.get("reparto") or {}
    MESA[:] = [str(x).strip().lower() for x in (reparto.get("mesa") or []) if str(x).strip()]
    ROLES.clear()
    for rol in ("instalaciones", "escalamiento"):
        if reparto.get(rol):
            ROLES[rol] = str(reparto[rol]).strip().lower()
    if cfg.get("tecnicos") is not None or gl:
        faltan = [x for x, ok in (("tecnicos", TECNICOS_HUMANOS),
                                  ("integrador_glpi.ithos_user_id", ITHOS_ID),
                                  ("reparto.mesa", MESA)) if not ok]
        if faltan:
            log.error("Equipo incompleto en la config: falta %s.", ", ".join(faltan))


def _cargar_de_config():
    """El equipo de la empresa de clientes.json (el mismo archivo que lee el Gestor). Los datos
    del equipo no son secretos: no hace falta descifrar nada."""
    ruta = os.environ.get("ITHOS_CLIENTES") or os.path.join(_AQUI, "clientes.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            clientes = json.load(f).get("clientes") or []
    except (OSError, ValueError):
        return
    for c in clientes:
        if c.get("activo", True) and (c.get("tecnicos") or (c.get("integrador_glpi") or {}).get("tecnicos")):
            configurar(c)
            return


def instalaciones():
    """Login de quien cubre INSTALACIONES (hay que ir al lugar)."""
    return ROLES.get("instalaciones", "")


def escalamiento():
    """Login de quien cubre ESCALAMIENTO (Alta y Urgente)."""
    return ROLES.get("escalamiento", "")


_cargar_de_config()


def menos_cargado(cfg_glpi, logins=None):
    """De `logins`, el que tenga MENOS tickets abiertos ahora. Ante un empate, el primero.

    Se le pregunta a GLPI, que es la única fuente que sabe la verdad: un contador nuestro se
    desincroniza en cuanto alguien asigna un ticket a mano, y acá eso pasa todo el tiempo.

    SI GLPI NO CONTESTA no se rompe nada: devuelve el primero de la lista. El ticket entra igual
    y con responsable; lo peor que pasa es que el reparto quede desparejo esa vez. Dejar un
    ticket sin asignar por no poder contar sería mucho peor."""
    logins = list(logins or MESA)
    if not logins:
        return escalamiento()
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
    """Ids de los TÉCNICOS PERSONAS (sin ITHOS), leídos de la config `tecnicos`. Sus comentarios
    resuelven un ticket y son los que reciben las @menciones."""
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
    """Nombres de los técnicos por su user-id de GLPI (de la config cargada)."""
    por_id = {uid: NOMBRES.get(login, login) for login, uid in RESPONSABLES.items()}
    return [por_id[i] for i in ids if i in por_id]
