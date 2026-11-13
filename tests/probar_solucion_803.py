#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test del ticket #803 ("Legajo 14616 Facundo Martín Gutiérrez Mónaco", 13-nov-2026), sin red.

QUÉ PASÓ. La técnica dejó su resolución como comentario PÚBLICO y, siete segundos después, ITHOS
pasó el ticket a Resuelto cargando como SOLUCIÓN **ese mismo comentario, copiado palabra por
palabra**. Salieron dos cosas mal:

  1. EL CLIENTE LEYÓ DOS VECES LO MISMO. El comentario de la técnica ya lo veía; la solución era el
     mismo texto otra vez (sin las capturas, porque la copia se lleva el texto y no las imágenes).
     Y era texto INTERNO: nombres de scripts .sql, consultas a la base, chequeos en la terminal,
     parámetros de vinculación. Nada de eso es para el solicitante.

  2. EL HISTORIAL MINTIÓ. La solución quedó registrada a nombre de ITHOS (usuario 28) y no de la
     técnica que la escribió (usuario 30) — teniendo su token configurado. Para cualquiera que
     mire el ticket después, el que resolvió fue el robot.

LA REGLA. La solución que lee el cliente es un RESUMEN corto, escrito para él, y va a nombre del
técnico que resolvió. La explicación técnica no se mueve ni se borra: queda donde ya estaba, en el
comentario. Y si el resumen no sale —la IA no contesta, o devuelve el texto del técnico de nuevo—
se carga una frase genérica: repetirle lo que ya leyó es peor que no resumirlo.

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
import ciclo as CI                      # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


LAURA = 30                               # la técnica que resolvió el #803
ITHOS = 28

# El comentario REAL de la técnica, recortado: procedimiento interno de punta a punta.
RESOLUCION = (
    "Buenos días. Se verificó el legajo 14616 en la base de datos. Se corrió el script "
    "HikInOut.sql para revisar las marcaciones y luego Incidencias.sql para descartar registros "
    "duplicados. Se controló la terminal del ingreso: estaba sin vincular, por lo que se "
    "reconfiguraron los parámetros de PIN y Bluetooth y se reinició el equipo. Se probó una "
    "fichada de prueba y quedó registrada correctamente.")

RESUMEN_BUENO = ("Ya se normalizó el registro de sus fichadas y la terminal del ingreso quedó "
                 "operativa. Puede fichar con normalidad.")


class IAFalsa:
    """Una IA de mentira: devuelve lo que se le diga, o explota si se le pide."""

    def __init__(self, respuesta=None, explota=False):
        self.respuesta, self.explota = respuesta, explota
        self.prompts = []

    def chat(self, sistema, usuario, json_out=False):
        self.prompts.append((sistema, usuario))
        if self.explota:
            raise RuntimeError("503 cadena de IA caída")
        return self.respuesta


def triage_con(ia):
    t = TR.Triage.__new__(TR.Triage)
    t.ia = ia
    t.cfg_glpi = {}
    return t


print("\n=== 1 · Reconocer una SOLUCIÓN que es el texto del técnico otra vez ===")
ok(TR._repite_al_tecnico(RESOLUCION, RESOLUCION) is True,
   "el texto copiado tal cual se detecta (es EXACTAMENTE lo que pasó en el #803)")
ok(TR._repite_al_tecnico(RESOLUCION.replace("\n", " ") + " Saludos.", RESOLUCION) is True,
   "y también si le cambian el formato o le pegan una línea al final")
ok(TR._repite_al_tecnico(
    "Se corrió el script HikInOut.sql para revisar las marcaciones y luego Incidencias.sql "
    "para descartar registros duplicados.", RESOLUCION) is True,
   "un RECORTE largo del comentario tampoco es un resumen")
ok(TR._repite_al_tecnico(RESUMEN_BUENO, RESOLUCION) is False,
   "un resumen de verdad SÍ pasa (si no, nunca se podría resumir nada)")
ok(TR._repite_al_tecnico("Se normalizó el registro de sus fichadas.", RESOLUCION) is False,
   "y una frase corta que comparte un par de palabras no cuenta como copia")

print("\n=== 2 · La solución que ve el cliente se RESUME, no se copia ===")
ia = IAFalsa(RESUMEN_BUENO)
tri = triage_con(ia)
sal = tri.resumen_para_el_cliente(RESOLUCION)
ok(sal == RESUMEN_BUENO, "se carga el resumen que escribió la IA", sal[:60])
ok("HikInOut.sql" not in sal and "Incidencias.sql" not in sal,
   "sin los nombres de los scripts internos")
ok(len(sal) < len(RESOLUCION) / 2, "y es bastante más corto que el comentario del técnico",
   f"{len(sal)} vs {len(RESOLUCION)} caracteres")

pedido = ia.prompts[0][0]
ok("CLIENTE" in pedido, "a la IA se le dice para quién escribe")
ok("PROHIBIDO copiar" in pedido, "y que NO copie frases del comentario")
for prohibido in ("scripts", ".sql", "bases de datos", "direcciones IP", "parámetros"):
    ok(prohibido in pedido, f"se le prohíbe explícitamente nombrar: {prohibido}")
ok("emojis" in pedido, "y sin emojis (la voz después lee esto)")

print("\n=== 3 · Si la IA devuelve el texto del técnico, NO se le repite al cliente ===")
# Pedirle que resuma no es garantía: puede devolver el original casi intacto. Por eso se comprueba.
tri_loro = triage_con(IAFalsa(RESOLUCION))
sal_loro = tri_loro.resumen_para_el_cliente(RESOLUCION)
ok(sal_loro != RESOLUCION, "el pegado se descarta", sal_loro[:50])
ok("HikInOut.sql" not in sal_loro, "y el detalle interno no llega al cliente")
ok("resolvió el inconveniente" in sal_loro, "va la solución genérica en su lugar")

print("\n=== 4 · Si la IA está caída, tampoco se copia: va la genérica ===")
tri_sin_ia = triage_con(IAFalsa(explota=True))
sal_caida = tri_sin_ia.resumen_para_el_cliente(RESOLUCION)
ok(sal_caida and "HikInOut.sql" not in sal_caida,
   "sin IA se carga igual una solución (sin ella el cliente no tendría qué aprobar)", sal_caida[:50])
ok(not TR._repite_al_tecnico(sal_caida, RESOLUCION), "y nunca es el texto del técnico")
ok(triage_con(IAFalsa("")).resumen_para_el_cliente("") != "",
   "un comentario vacío tampoco deja la solución vacía")

print("\n=== 5 · El pasaje a Resuelto carga el RESUMEN y a nombre del TÉCNICO ===")
cargado = {}


class TriageEspia(TR.Triage):
    def __init__(self):
        self.ia = IAFalsa(RESUMEN_BUENO)
        self.cfg_glpi = {}
        self.cli = self

    def marcar_resuelto(self, tid, solucion="", autor=None):
        cargado["tid"], cargado["sol"], cargado["autor"] = tid, solucion, autor
        return True

    def pedir_confirmacion(self, tid):
        return True

    def abrir(self):
        pass

    def cerrar(self):
        pass

    def request(self, path, metodo="GET", data=None, **k):
        if path.endswith("/ITILSolution"):
            return [{"id": 158, "status": 2}]
        return {"status": 5}


TriageEspia().a_confirmacion_del_cliente(803, RESOLUCION, autor=LAURA)
ok(cargado.get("sol") == RESUMEN_BUENO,
   "la solución que se carga es el RESUMEN, no el comentario del técnico",
   str(cargado.get("sol"))[:55])
ok("HikInOut.sql" not in str(cargado.get("sol")),
   "el procedimiento interno NO viaja a la solución (el bug del #803)")
ok(cargado.get("autor") == LAURA,
   "y se carga a nombre de la técnica que resolvió, no de ITHOS", str(cargado.get("autor")))
ok(cargado.get("autor") not in (None, 0, ITHOS),
   "el historial deja de decir que resolvió el robot (y tampoco se carga sin autor)")

print("\n=== 6 · El ciclo le pasa QUIÉN resolvió (antes no se lo pasaba a nadie) ===")
CICLO_SRC = open(os.path.join(APP, "central", "ciclo.py"), encoding="utf-8").read()
ok("a_confirmacion_del_cliente(t[\"id\"], cont,\n" in CICLO_SRC
   and "autor=int(ult.get(\"users_id\") or 0)" in CICLO_SRC,
   "el ciclo pasa el autor del comentario que resolvió")
ok("a_confirmacion_del_cliente(t[\"id\"], cont)" not in CICLO_SRC,
   "y ya no hace el pasaje sin autor (así quedaba todo a nombre de ITHOS)")

print("\n=== 7 · La explicación del técnico NO se toca ===")
# Lo que se arregla es la SOLUCIÓN duplicada, no la explicación: su comentario queda donde está.
TRI_SRC = open(os.path.join(APP, "central", "triage.py"), encoding="utf-8").read()
paso = TRI_SRC[TRI_SRC.index("def a_confirmacion_del_cliente"):]
paso = paso[:paso.index("def marcar_resuelto")]
ok("resumen_para_el_cliente(solucion)" in paso,
   "el pasaje resume antes de cargar")
ok("autor=autor" in paso, "y propaga el autor hasta la carga de la solución")
ok("ITILFollowup" not in paso and "delete" not in paso.lower(),
   "el pasaje no borra ni reescribe ningún comentario del ticket")

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("  SOLUCIÓN DEL #803: OK — resumen para el cliente y a nombre de quien resolvió")
print("=" * 78)
