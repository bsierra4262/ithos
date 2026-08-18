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
RESPONSABLES = {"bsierra": 7, "jayala": 8}
NOMBRES = {"bsierra": "Brian Sierra", "jayala": "Alejandro Ayala"}
ITHOS_ID = 28
TECNICOS = {28, 7, 8}
TECNICOS_HUMANOS = {7, 8}          # técnicos personas (sin ITHOS): sus comentarios pueden resolver


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
