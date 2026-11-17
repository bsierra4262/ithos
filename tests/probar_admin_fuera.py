#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: la cuenta `admin` no figura en ningún ticket (ticket #849 y otros 16), sin red.

QUÉ PASÓ. Los clientes cargan el ticket con el formulario de la mesa de ayuda, que tiene una
pregunta «Observadores», y ahí elegían también a `admin` —la cuenta de súper administrador que GLPI
crea al instalarse—. Después ITHOS, que pasa a SOLICITANTES a los observadores del cliente para que
puedan responder el ticket, tomaba a admin por uno de ellos. Resultado: admin figuraba como
solicitante y observador en 17 tickets, desde el #798.

LA REGLA (Brian: «el admin no debe figurar de todas formas, el admin ve todo igual»). Las cuentas
internas se sacan del ticket en cualquier rol, y nunca se pasan a solicitante.

Uso:  python tests/probar_admin_fuera.py
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "ITHOS"))
sys.path.insert(0, os.path.join(RAIZ, "ITHOS", "central"))

import triage as TR                     # noqa: E402
import equipo as EQ                     # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


ADMIN, FACUNDO, PABLO, BRIAN, ITHOS = 2, 26, 27, 7, 28

# Los actores del #849 tal como quedaron al crearse: Facundo solicitante, y como observadores lo
# que eligió en el formulario (admin incluido).
ACTORES = [{"id": 1, "users_id": FACUNDO, "type": 1},
           {"id": 2, "users_id": ADMIN, "type": 3},
           {"id": 3, "users_id": BRIAN, "type": 3},
           {"id": 4, "users_id": PABLO, "type": 3},
           {"id": 5, "users_id": ITHOS, "type": 2}]


class _Mesa:
    def __init__(self):
        self.borrados, self.agregados = [], []

    def request(self, path, metodo="GET", data=None, **k):
        if path.endswith("/Ticket_User") and metodo == "GET":
            return ACTORES
        if path == "/Ticket_User" and metodo == "POST":
            self.agregados.append((data["input"]["users_id"], data["input"]["type"]))
        if path.startswith("/Ticket_User/") and metodo == "DELETE":
            self.borrados.append(int(path.rsplit("/", 1)[1]))
        return {}


tri = TR.Triage.__new__(TR.Triage)
tri.cfg_glpi = {}
tri.cli = _Mesa()
tri._habilitar_respuesta_del_cliente(849, humanos={BRIAN, 8, 30, 31})

print("\n=== 1 · admin sale del ticket ===")
ok(2 in tri.cli.borrados, "se saca la fila de admin (estaba de observador)", str(tri.cli.borrados))
ok((ADMIN, 1) not in tri.cli.agregados,
   "y NUNCA se lo pasa a solicitante (el bug: 17 tickets así)", str(tri.cli.agregados))

print("\n=== 2 · El resto sigue funcionando como antes ===")
ok((PABLO, 1) in tri.cli.agregados,
   "el observador del cliente (Pablo) pasa a solicitante, para poder responder")
ok((BRIAN, 1) not in tri.cli.agregados, "a un técnico no se lo hace solicitante")
ok(not any(b in (1, 3, 4, 5) for b in tri.cli.borrados),
   "y no se saca a nadie más que a admin", str(tri.cli.borrados))

print("\n=== 3 · Se puede ampliar por cliente ===")
ok(EQ.cuentas_internas({}) == {2}, "por defecto la cuenta interna es admin (id 2)")
ok(EQ.cuentas_internas({"cuentas_internas": [99, "98", "basura"]}) == {2, 98, 99},
   "un cliente puede sumar las suyas, y lo que no es un id se ignora")

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("  ADMIN: OK — no figura en ningún ticket y nunca queda como solicitante")
print("=" * 78)
