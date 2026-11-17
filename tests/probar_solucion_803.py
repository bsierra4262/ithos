#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de lo que ITHOS escribe cuando un técnico resuelve: tickets #803, #831 y #844, sin red.

EL PROBLEMA, TRES VECES. Cuando un técnico resuelve con un comentario, ITHOS pasa el ticket a
Resuelto. Y cada vez que además cargó una SOLUCIÓN propia, el cliente terminó leyendo la misma
resolución dos veces:

  · #803 (13-nov) — la solución era el comentario de la técnica COPIADO, y encima sin las capturas,
    porque se copiaba el texto plano que se le pasa a la IA.
  · #831 (17-nov) — se cambió por un RESUMEN redactado por ITHOS. La misma cosa dicha dos veces,
    sólo que más corta.
  · #844 (17-nov) — se cambió por el comentario CRUDO, tal cual, con sus capturas. Dos veces lo
    mismo, ahora idéntico.

LA REGLA (Brian: «que deje mi respuesta como autorización y ITHOS no escriba nada»). ITHOS NO CARGA
NINGUNA SOLUCIÓN. El comentario del técnico ES la resolución: ya está en el ticket, entero, con sus
capturas y a su nombre. ITHOS sólo pasa el ticket a Resuelto —con eso el SLA deja de correr— y
escribe su pedido de confirmación, que es otra cosa. Y el que resolvió se queda con el ticket.

Uso:  python tests/probar_solucion_803.py
"""

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

import triage as TR                     # noqa: E402
import ciclo as CI                      # noqa: E402,F401

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


LAURA = 30                               # la técnica que resolvió el #803
ITHOS = 28

TRI_SRC = open(os.path.join(APP, "central", "triage.py"), encoding="utf-8").read()
CICLO_SRC = open(os.path.join(APP, "central", "ciclo.py"), encoding="utf-8").read()


class _Registro:
    """Mesa de ayuda de mentira: anota TODO lo que se le pide."""

    session = "s"

    def __init__(self):
        self.pedidos = []

    def abrir(self):
        pass

    def cerrar(self):
        pass

    def request(self, path, metodo="GET", data=None, **k):
        self.pedidos.append((path, metodo, data))
        if path.endswith("/Ticket_User"):
            return []
        return {"status": 5}


def pasaje(autor=LAURA):
    """Corre el pasaje a Resuelto de verdad y devuelve todo lo que le pidió a la mesa de ayuda."""
    tri = TR.Triage.__new__(TR.Triage)
    tri.cfg_glpi = {}
    tri.cli = _Registro()
    tri.pedir_confirmacion = lambda tid: tri.cli.pedidos.append(("CONFIRMACION", "POST", None))
    resultado = tri.a_confirmacion_del_cliente(844, autor=autor)
    return resultado, tri.cli.pedidos


print("\n=== 1 · ITHOS NO carga ninguna solución ===")
salio, pedidos = pasaje()
ok(salio is True, "el pasaje a Resuelto sale bien")
soluciones = [p for p in pedidos if "/ITILSolution" in p[0] and p[1] == "POST"]
ok(soluciones == [],
   "no se crea NINGUNA solución: la resolución es el comentario del técnico", str(soluciones))
ok(any(p[0] == "/Ticket/844" and p[1] == "PUT"
       and ((p[2] or {}).get("input") or {}).get("status") == 5 for p in pedidos),
   "el ticket pasa a RESUELTO (así el SLA de resolución deja de correr)")
ok(("CONFIRMACION", "POST", None) in pedidos,
   "y lo único que ITHOS le escribe al cliente es el pedido de confirmación")
ok(not any("/ITILFollowup" in p[0] and p[1] in ("PUT", "DELETE") for p in pedidos),
   "el comentario del técnico no se toca: ni se edita ni se borra")

print("\n=== 2 · Las tres formas que se probaron ya no existen ===")
ok("resumen_para_el_cliente" not in TRI_SRC, "#831: no hay resumidor")
ok("_sesion_de" not in TRI_SRC,
   "#844: no hay carga de solución con el usuario del técnico (no hay solución que cargar)")
paso = TRI_SRC[TRI_SRC.index("def a_confirmacion_del_cliente"):]
paso = paso[:paso.index("def marcar_resuelto")]
ok("ITILSolution" not in paso.split('"""', 2)[-1], "el pasaje no toca soluciones en ningún lado")
marc = TRI_SRC[TRI_SRC.index("def marcar_resuelto"):]
marc = marc[:marc.index("\n    def ", 10)]
ok("ITILSolution" not in marc.split('"""', 2)[-1], "y marcar_resuelto sólo cambia el estado")

print("\n=== 3 · El ciclo le pasa QUIÉN resolvió, no el texto ===")
ok('autor=int(ult.get("users_id") or 0))' in CICLO_SRC,
   "se pasa el autor, para que se quede con el ticket")
ok('a_confirmacion_del_cliente(t["id"], ult.get("content")' not in CICLO_SRC
   and 'a_confirmacion_del_cliente(t["id"], cont' not in CICLO_SRC,
   "y NO el texto: no hay nada que copiar a ningún lado")
ok("cont = _texto_plano(" in CICLO_SRC and "tecnico_resolvio(cont)" in CICLO_SRC,
   "el texto plano se sigue usando para lo que sirve: que la IA lo lea")

print("\n=== 4 · El cliente contesta escribiendo, y eso alcanza ===")
# Sin solución cargada la mesa de ayuda no le dibuja los botones de aprobar/rechazar. Se resigna a
# propósito: el pedido de confirmación le dice que responda, y el ciclo lee esa respuesta igual. De
# paso se va el problema del #803, donde el cliente apretó «aprobar» mientras escribía que seguía
# sin poder fichar y el ticket se cerró solo.
ok("status == 5 and _ya_pidio_confirmacion(fu)" in CICLO_SRC,
   "un ticket Resuelto con el pedido de confirmación hecho cuenta como 'esperando confirmación'")
ok("triage.cliente_confirma(dijo)" in CICLO_SRC,
   "y lo que el cliente escribe se interpreta: confirma -> cierra, sigue -> reabre")

print("\n=== 5 · Sin autor, igual se resuelve ===")
salio2, pedidos2 = pasaje(autor=None)
ok(salio2 is True, "si no se sabe quién resolvió, el ticket pasa a Resuelto igual")
ok(not any("/Ticket_User" in p[0] and p[1] in ("POST", "DELETE") for p in pedidos2),
   "pero no se toca la asignación: no se le saca el ticket a nadie a ciegas")

print("\n=== 6 · El que resolvió se QUEDA con el ticket ===")
# Pedido de Brian: un ticket puede terminar asignado a varias personas, y el que lo resuelve capaz
# no era ninguna de ellas. Si quedan todos asignados, GLPI le suma el SLA a los cuatro —el reporte
# no dice quién resolvió qué— y la @mención de WhatsApp los nombra a todos.
BORRADOS, AGREGADOS = [], []


class _CliActores:
    """Mesa de ayuda de mentira: el ticket viene asignado a ITHOS, Brian, Laura y Lisandro."""

    session = "s"

    def __init__(self, asignados=(28, 7, 30, 31)):
        self.asignados = asignados

    def abrir(self):
        pass

    def cerrar(self):
        pass

    def request(self, path, metodo="GET", data=None, **k):
        if path.endswith("/Ticket_User") and metodo == "GET":
            return [{"id": 500 + u, "users_id": u, "type": 2} for u in self.asignados]
        if path == "/Ticket_User" and metodo == "POST":
            AGREGADOS.append(data["input"]["users_id"])
        if path.startswith("/Ticket_User/") and metodo == "DELETE":
            BORRADOS.append(int(path.rsplit("/", 1)[1]) - 500)
        return {}


tri = TR.Triage.__new__(TR.Triage)
tri.cfg_glpi = {}
tri.cli = _CliActores()
ok(tri.dejar_solo_al_que_resolvio(831, LAURA) is True, "se aplica cuando resolvió una persona")
ok(sorted(BORRADOS) == [7, 31],
   "se saca a los demás técnicos del campo 'Asignado a'", str(sorted(BORRADOS)))
ok(28 not in BORRADOS,
   "pero ITHOS se queda: es el agente que sigue trabajando el ticket, no compite en el reporte")
ok(AGREGADOS == [], "y a quien ya estaba asignado no se lo vuelve a agregar")

BORRADOS.clear()
AGREGADOS.clear()
tri.cli = _CliActores(asignados=(28, 7))          # el que resolvió NO estaba asignado
tri.dejar_solo_al_que_resolvio(831, LAURA)
ok(AGREGADOS == [LAURA],
   "si resolvió alguien que no tenía el ticket, se le asigna a él", str(AGREGADOS))
ok(sorted(BORRADOS) == [7], "y se saca al que lo tenía y no lo resolvió", str(BORRADOS))

BORRADOS.clear()
AGREGADOS.clear()
ok(tri.dejar_solo_al_que_resolvio(831, None) is False, "sin autor no se toca la asignación")
ok(tri.dejar_solo_al_que_resolvio(831, ITHOS) is False,
   "y si 'resolvió' ITHOS tampoco: el robot no se queda con el ticket de nadie")
ok(BORRADOS == [] and AGREGADOS == [], "en esos dos casos no se borra ni se agrega nada")


class _CliRoto(_CliActores):
    def request(self, path, metodo="GET", data=None, **k):
        raise RuntimeError("GLPI no responde")


tri.cli = _CliRoto()
ok(tri.dejar_solo_al_que_resolvio(831, LAURA) is False,
   "si GLPI falla devuelve False, pero NO rompe: el ticket ya quedó resuelto")

paso6 = TRI_SRC[TRI_SRC.index("def a_confirmacion_del_cliente"):]
paso6 = paso6[:paso6.index("def marcar_resuelto")]
ok("dejar_solo_al_que_resolvio(tid, autor)" in paso6,
   "y el pasaje a Resuelto lo hace solo, sin que nadie tenga que acordarse")

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("  RESOLUCIÓN: OK — es el comentario del técnico; ITHOS sólo pide la confirmación")
print("=" * 78)
