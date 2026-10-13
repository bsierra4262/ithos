#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: cuando ITHOS no puede LEER el estado de un ticket, no inventa uno.

EL BUG. `_tecnicos_asignados()` atrapaba el error de lectura y devolvía un conjunto vacío. Pero
vacío significa «no hay nadie asignado», que es exactamente lo que dice un ticket todavía SIN
triagear. Las dos situaciones quedaban indistinguibles, así que una caída pasajera de GLPI se leía
como «ticket nuevo» y el triage volvía a correr sobre un ticket YA trabajado: le cambiaba la
categoría, la prioridad y la asignación que había puesto el técnico a mano.

Y no es hipotético: el MySQL compartido del hosting rechaza conexiones en ráfagas (se ve en el log
de GLPI, `CheckDatabaseStatusListener`, varias en el mismo segundo), que es justo la condición que
lo dispara.

LA REGLA. Ante la duda NO se triagea. Reintentar en la vuelta siguiente (~1 minuto) no cuesta
nada; pisarle el trabajo a una persona, sí.

SEGUNDO CASO. La asignación del responsable se hacía con `except Exception: pass`, comentado como
«ya asignado, estado final correcto». Eso vale para el error ESPERADO de GLPI (alta duplicada),
pero se tragaba igual una caída real, y entonces el ticket quedaba SIN responsable y en silencio.
Ahora se verifica el estado final: si falta alguien, se avisa.

Uso:  python tests/probar_triage_ante_la_duda.py
"""

import logging
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))

import triage as TR                         # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


class Capturador(logging.Handler):
    def __init__(self):
        super().__init__()
        self.registros = []

    def emit(self, r):
        self.registros.append((r.levelno, r.getMessage()))


def capturando(fn):
    """Corre `fn` capturando lo que registra el triage. Devuelve (resultado, [(nivel, mensaje)])."""
    cap = Capturador()
    TR.log.addHandler(cap)
    nivel = TR.log.level
    TR.log.setLevel(logging.DEBUG)
    try:
        return fn(), cap.registros
    finally:
        TR.log.removeHandler(cap)
        TR.log.setLevel(nivel)


class GLPICaido:
    """GLPI que acepta la sesión pero falla al leer: la ráfaga del MySQL compartido."""

    session = "x"

    def __init__(self):
        self.escrituras = []

    def abrir(self):
        return self

    def cerrar(self):
        pass

    def request(self, path, metodo="GET", *a, **k):
        if metodo != "GET":
            self.escrituras.append((path, metodo))
            return {"id": 1}
        raise RuntimeError("Lost connection to MySQL server during query")


class GLPISano:
    """GLPI que responde: el ticket YA tiene a ITHOS y a un técnico humano asignados."""

    session = "x"

    def __init__(self, asignados=(28, 7)):
        self.asignados = asignados
        self.escrituras = []

    def abrir(self):
        return self

    def cerrar(self):
        pass

    def request(self, path, metodo="GET", *a, **k):
        if metodo != "GET":
            self.escrituras.append((path, metodo))
            return {"id": 1}
        if path.endswith("/Ticket_User"):
            return [{"users_id": u, "type": 2} for u in self.asignados]
        return {}


TICKET = {"id": 666, "name": "El molinete no abre", "content": "no anda", "status": 1}


print("\n=== 1 · Si NO se puede leer quién está asignado, NO se triagea ===")
tri = TR.Triage.__new__(TR.Triage)
tri.cli = GLPICaido()
tri.cfg_glpi = {}
resultado, registros = capturando(lambda: tri.procesar(dict(TICKET)))
ok(resultado is None, "procesar() devuelve None: no se triagea en esta vuelta")
ok(not tri.cli.escrituras,
   "y NO escribe NADA en el ticket: ni categoría, ni prioridad, ni asignación",
   str(tri.cli.escrituras[:3]))
ok(any(n == logging.WARNING for n, _m in registros),
   "queda avisado por qué se salteó", str([m[:60] for _n, m in registros][:1]))

print("\n=== 2 · Y el error de lectura ya no se disfraza de 'no hay nadie asignado' ===")
tri2 = TR.Triage.__new__(TR.Triage)
tri2.cli = GLPICaido()
tri2.cfg_glpi = {}
try:
    tri2._tecnicos_asignados(666)
    ok(False, "_tecnicos_asignados() propaga el error de lectura")
except Exception as e:  # noqa: BLE001
    ok(True, "_tecnicos_asignados() propaga el error de lectura", type(e).__name__)

print("\n=== 3 · Cuando SÍ se puede leer, el comportamiento de siempre ===")
tri3 = TR.Triage.__new__(TR.Triage)
tri3.cli = GLPISano(asignados=(28, 7))      # 28 = ITHOS, ya triado
tri3.cfg_glpi = {}
resultado, registros = capturando(lambda: tri3.procesar(dict(TICKET)))
ok(resultado is None, "un ticket YA triado por ITHOS no se vuelve a triagear")
ok(any("ya triado" in m for _n, m in registros),
   "y se dice que es por eso, no por un error", str([m[:50] for _n, m in registros][:1]))
ok(tri3.cli.escrituras == [("/Ticket/666", "PUT")],
   "lo único que hace es sacarlo de 'Nuevo' para que no quede en loop",
   str(tri3.cli.escrituras))

print("\n=== 4 · Las dos situaciones son DISTINGUIBLES (que era todo el bug) ===")
sano = TR.Triage.__new__(TR.Triage)
sano.cli = GLPISano(asignados=())           # leído OK, y de verdad no hay nadie
sano.cfg_glpi = {}
ok(sano._tecnicos_asignados(666) == set(),
   "ticket sin asignar -> conjunto vacío (se pudo leer, no hay nadie)")
caido = TR.Triage.__new__(TR.Triage)
caido.cli = GLPICaido()
caido.cfg_glpi = {}
try:
    caido._tecnicos_asignados(666)
    distinto = False
except Exception:  # noqa: BLE001
    distinto = True
ok(distinto, "GLPI caído -> excepción, NO un conjunto vacío que parezca lo mismo")

print("\n" + "=" * 70)
if FALLAS:
    print(f"  FALLAS: {len(FALLAS)}")
    for f in FALLAS:
        print("   -", f)
    print("=" * 70)
    sys.exit(1)
print("  ANTE LA DUDA NO SE TRIAGEA: OK — todos los chequeos verdes")
print("=" * 70)
