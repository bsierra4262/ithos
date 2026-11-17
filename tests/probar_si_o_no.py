#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: un sí/no dudoso de la IA nunca cierra ni reabre un ticket (sin red).

EL BUG. Las preguntas de sí/no que ITHOS le hace a la IA —¿el cliente confirma?, ¿cancela?, ¿el
técnico resolvió?, ¿explica el procedimiento?, ¿le pide algo al cliente?— se leían con
`bool(json.loads(r).get(clave))`. Eso tiene dos agujeros, y los dos deciden sobre tickets reales:

  1. LA CLAVE NO VIENE. `bool(None)` es False. Para `confirma` eso se lee como «el cliente dice que
     sigue igual» y el ticket se REABRE aunque el cliente lo haya dado por bueno. Apareció midiendo
     la IA local: a «listo afirmativamente!» contestó un JSON sin la clave `confirma`.

  2. EL VALOR VIENE COMO TEXTO. `bool("false")` es True —cualquier texto no vacío lo es—. Para
     `confirma` eso CIERRA un ticket que el cliente dijo que seguía roto.

LA REGLA. Sólo cuentan los sí/no inequívocos. Todo lo demás es None, que los que llaman ya tratan
como «la IA no supo»: no se toca el ticket y se vuelve a mirar en la próxima vuelta.

Uso:  python tests/probar_si_o_no.py
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

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


S = TR._si_o_no

print("\n=== 1 · Los sí/no de verdad se leen ===")
ok(S('{"confirma": true}', "confirma") is True, "true es sí")
ok(S('{"confirma": false}', "confirma") is False, "false es no")
ok(S('{"cancela": "true"}', "cancela") is True, 'el texto "true" también es sí')
ok(S('{"cancela": "No"}', "cancela") is False, 'y "No" es no')

print("\n=== 2 · El bug 1: la clave no viene -> NO es un 'no' ===")
ok(S('{"conforme": true}', "confirma") is None,
   "una respuesta sin la clave es 'no sé', no 'sigue igual' (antes REABRÍA el ticket)")
ok(S('{}', "confirma") is None, "un JSON vacío tampoco decide nada")

print("\n=== 3 · El bug 2: 'false' como texto -> NO es un 'sí' ===")
ok(S('{"confirma": "false"}', "confirma") is False,
   '"false" como texto es no (antes bool("false") daba True y CERRABA el ticket)')

print("\n=== 4 · Cualquier otra cosa es 'no sé' ===")
for raro, que in (('{"confirma": null}', "null"),
                  ('{"confirma": 1}', "un número"),
                  ('{"confirma": "quizás"}', "un texto que no es sí ni no"),
                  ('{"confirma": ["true"]}', "una lista"),
                  ("no es JSON", "algo que ni es JSON"),
                  ("", "una respuesta vacía")):
    ok(S(raro, "confirma") is None, f"{que} -> None")

print("\n=== 5 · Las cinco preguntas usan la lectura segura ===")
SRC = open(os.path.join(RAIZ, "ITHOS", "central", "triage.py"), encoding="utf-8").read()
ok("bool(_j.loads(r).get(" not in SRC,
   "ya no queda ningún bool(...) a secas sobre lo que devuelve la IA")
for clave in ("confirma", "cancela", "resuelto", "explica", "pide_confirmacion"):
    ok(f'_si_o_no(r, "{clave}")' in SRC, f"la pregunta '{clave}' pasa por _si_o_no")

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("  SÍ/NO DE LA IA: OK — lo dudoso nunca cierra ni reabre un ticket")
print("=" * 78)
