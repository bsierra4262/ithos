#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: cerrar, reabrir y poner en espera un ticket por chat avisa al grupo y no explota, sin red.

QUÉ PASÓ. Al partir el asistente en dos módulos (agosto), `herramientas.py` se quedó sin importar
`_id_ticket`. GLPI hacía el cambio de estado y, justo después, armar el aviso tiraba `NameError`: la
acción quedaba hecha, pero el que la pidió recibía un error y el grupo no se enteraba. Nadie lo vio
porque ningún test pasaba por ahí: los dos que probaban acciones usaban la versión vieja atada a
GLPI, que producción ya no usa.

Uso:  python tests/probar_acciones_chat.py
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "ITHOS"))

from comun import herramientas as H   # noqa: E402
from comun import tickets as T        # noqa: E402

FALLAS = []


def ok(cond, msg):
    print(("  OK   " if cond else "  FALLA ") + msg)
    if not cond:
        FALLAS.append(msg)


class _Adap:
    def __init__(self):
        self.hecho = []

    def cambiar_estado(self, tid, estado):
        self.hecho.append((tid, estado))
        return f"Ticket {tid}: {estado}"


adap = _Adap()
_orig = T.adaptador
T.adaptador = lambda cfg: adap
try:
    avisos = []
    acc = H.acciones_tickets({"nombre": "TEST S.A."}, avisar=avisos.append)
    print("\n=== Las acciones que cambian el estado avisan al grupo ===")
    for nombre, estado, palabra in (("cerrar_ticket", "cerrado", "cerrado"),
                                    ("reabrir_ticket", "reabrir", "reabierto"),
                                    ("poner_en_espera", "en_espera", "EN ESPERA")):
        antes = len(avisos)
        try:
            acc[nombre]["fn"]({"id": "#597"})
            exploto = None
        except Exception as e:  # noqa: BLE001
            exploto = e
        ok(exploto is None, f"{nombre}: no explota después de hacer el cambio ({exploto!r})")
        ok(adap.hecho[-1] == ("#597", estado), f"{nombre}: le pide el cambio al sistema de tickets")
        ok(len(avisos) == antes + 1 and "#597" in avisos[-1] and palabra in avisos[-1]
           and "##" not in avisos[-1],
           f"{nombre}: avisa al grupo con el número limpio")
finally:
    T.adaptador = _orig

print()
if FALLAS:
    print(f"FALLARON {len(FALLAS)}")
    sys.exit(1)
print("TODO OK")
