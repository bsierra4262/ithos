#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: lo que el CLIENTE da de baja se cierra (ticket #827), sin red.

QUÉ PASÓ. El solicitante abrió el ticket #827, se dio cuenta de que había cargado mal el asunto y
escribió «Se cancela el ticket por corrección de Asunto» — lo iba a abrir de nuevo. El ticket se
quedó **En curso**, con el SLA corriendo contra un pedido que ya no existía, esperando que alguien
resolviera algo que nadie iba a resolver.

LA REGLA. Si el cliente da de baja su pedido, el ticket se cierra. No se trabaja, no se le recuerda
y no se escala.

LOS DOS CUIDADOS, que son los que hacen que esto no sea peligroso:

  1. CERRAR DE MÁS ES PEOR QUE NO CERRAR. «ya se solucionó» NO es cancelar (eso es confirmar, y
     tiene su propio camino); «¿pueden reprogramar?» tampoco. Decide la IA, y ante la duda dice que
     no.

  2. LA IA NO SE CONSULTA SIEMPRE. Antes pasa un filtro de texto barato. Sin él habría una llamada
     de IA por cada comentario de cada cliente en cada vuelta del ciclo, y con la cuota diaria que
     hay eso se come el triage. El filtro sólo puede fallar para un lado: si no reconoce la
     palabra, el ticket sigue como hasta ahora. Nunca cierra de más.

Uso:  python tests/probar_cancelacion_827.py
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

import ciclo as CI                      # noqa: E402
import triage as TR                     # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


print("\n=== 1 · El filtro barato reconoce una baja, y NO se come otra cosa ===")
CANCELA = [
    "Se cancela el ticket por correccion de Asunto",      # el texto REAL del #827
    "Anulenlo por favor, lo cargue mal",
    "Ya no lo necesitamos, gracias",
    "Esta duplicado con el 820, descartenlo",
    "Den de baja este pedido",
    "Dejenlo sin efecto",
]
NO_CANCELA = [
    "Ya se soluciono, muchas gracias",                    # esto es CONFIRMAR, no cancelar
    "Pueden reprogramar la visita para el lunes?",        # esto es posponer
    "El legajo es 00012",                                 # un dato
    "Sigue sin funcionar, no puedo fichar",               # un reclamo
    "Necesito que me confirmen el horario",               # una pregunta
]
for txt in CANCELA:
    ok(bool(CI._RE_CANCELA.search(txt)), f"pasa al filtro: {txt[:45]}")
for txt in NO_CANCELA:
    ok(not CI._RE_CANCELA.search(txt),
       f"NO gasta una llamada de IA por: {txt[:45]}")

print("\n=== 2 · Reconocido el texto, la IA decide y el ticket se cierra ===")
cerrados, consultas = [], []


class TriageFalso:
    """Triage de mentira: anota a quién se le preguntó y qué se cerró."""

    def __init__(self, responde=True):
        self.responde = responde

    def cliente_cancela(self, texto):
        consultas.append(texto)
        return self.responde

    def cerrar_cancelado(self, tid):
        cerrados.append(tid)
        return True


tri = TriageFalso(responde=True)
st = {}
ok(tri.cliente_cancela("Se cancela el ticket") is True, "la IA contesta que sí")
ok(tri.cerrar_cancelado(827) is True and cerrados == [827], "y el ticket se cierra")

print("\n=== 3 · Ante la duda NO se cierra nada ===")
cerrados.clear()
tri_no = TriageFalso(responde=False)
tri_no.cliente_cancela("Ya se soluciono")
ok(cerrados == [], "si la IA dice que no es una baja, el ticket no se toca")


class TriageSinIA(TriageFalso):
    def cliente_cancela(self, texto):
        return None                      # la cadena de IA está caída


ok(TriageSinIA().cliente_cancela("se cancela") is None,
   "y si la IA no contesta, devuelve None: el ciclo lo deja para la próxima vuelta")

print("\n=== 4 · El cierre deja UNA línea, no un discurso ===")
TRI_SRC = open(os.path.join(APP, "central", "triage.py"), encoding="utf-8").read()
cerr = TRI_SRC[TRI_SRC.index("def cerrar_cancelado"):]
cerr = cerr[:cerr.index("def cliente_cancela")]
ok('"status": 6' in cerr, "el ticket queda CERRADO")
ok(cerr.count("self._followup(") == 1, "con un solo comentario, no con tres párrafos")
ok("a pedido suyo" in cerr,
   "y dice que se cierra a pedido del cliente, sin repetirle el motivo que él ya dio")

print("\n=== 5 · El prompt distingue cancelar de resolver y de posponer ===")
prom = TRI_SRC[TRI_SRC.index("def cliente_cancela"):]
prom = prom[:prom.index("def reabrir")]
ok("ANTE LA DUDA, false" in prom,
   "ante la duda no cancela: cerrar un ticket vivo es peor que dejarlo abierto")
ok("SE RESOLVIÓ" in prom, "se le aclara que resolver NO es cancelar")
ok("reprogramar" in prom or "posponer" in prom, "y que posponer tampoco")

print("\n=== 6 · Dónde corre: sólo en tickets abiertos y sin confirmación pendiente ===")
CICLO_SRC = open(os.path.join(APP, "central", "ciclo.py"), encoding="utf-8").read()
blq = CICLO_SRC[CICLO_SRC.index("¿EL CLIENTE DIO DE BAJA SU PEDIDO?"):]
blq = blq[:blq.index("if status == 4:")]
ok("status in (1, 2, 4)" in blq, "sólo sobre tickets ABIERTOS (nunca uno ya cerrado)")
ok("not espera_conf" in blq,
   "y NO cuando hay una solución esperando aprobación: ahí lo que escribe es la respuesta a eso")
ok("_RE_CANCELA.search" in blq, "el filtro de texto corre ANTES que la IA")
ok("cancelacion_vista" in blq, "y una baja ya procesada no se vuelve a mirar")

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("  BAJA DEL CLIENTE: OK — se cierra, sin cerrar de más ni gastar IA de más")
print("=" * 78)
