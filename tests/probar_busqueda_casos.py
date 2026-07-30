#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de la BÚSQUEDA DE ANTECEDENTES: "¿qué tickets tuvimos con este problema y cómo los
resolvimos?". Sin red: la mesa de ayuda se reemplaza por un histórico de mentira.

Regresión de un caso real. A "decime todos los tickets que ya resolvimos donde no se mostraban
las fichadas pero sí en HikCentral" ITHOS contestó con tres números, uno de ellos INEXISTENTE, se
salteó el ticket que sí correspondía y ofreció como resueltos tickets que en realidad se habían
cerrado porque la categoría estaba mal cargada. Tres causas, una por bloque de este test:

  1. Sólo miraba los últimos 60 tickets y comparaba la frase entera como subcadena: el histórico
     viejo era inalcanzable y una pregunta en lenguaje natural no coincidía con nada.
  2. Nunca leía la solución ni los seguimientos, así que no distinguía una resolución técnica de
     un cierre administrativo, ni la respuesta del técnico del comentario del propio solicitante.
  3. El asistente no salía a buscar: respondía con los tickets ABIERTOS del panorama y con lo que
     el modelo "recordaba" — de ahí el número inventado.

Uso:  python tests/probar_busqueda_casos.py
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

from comun import conversacion as C     # noqa: E402
from comun import tickets as T          # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


# --------------------------------------------------------------------------------------
# Histórico de mentira, calcado del real: el caso que corresponde está escrito con otras
# palabras ("la fichada", "hik central" separado) y varios cierres son administrativos.
# --------------------------------------------------------------------------------------
SOLICITANTE = 26          # quien abre los tickets
TECNICO = 7               # soporte
ADMIN_TXT = ("Estimados, por favor, colocar como corresponde las categorías; de ahora en más, si "
             "la categoría no corresponde a la adecuada, se cerrará inmediatamente pidiendo el "
             "cambio de la categoría correspondiente.")

HISTORICO = [
    # (id, asunto, descripción, [(autor, seguimiento)], [solución])
    (545, "Legajo 05808 Martínez Alexis",
     "El agente manifiesta tener error al momento de querer realizar el fichaje biométrico, en "
     "reportes ITH la fichada no figura pero si aparece en hik central, esperamos una solución.",
     [(SOLICITANTE, "El agente dice si tiene que mandar la foto nuevamente."), (TECNICO, ADMIN_TXT)],
     []),
    (495, "Legajo 09795 Verdile Giuliana",
     "La agente detallada en el titulo tiene la fichada en hik central, pero no se ve reflejada "
     "aun en ith reportes, adjunto las capturas para su análisis.",
     [(TECNICO, "No se encontró ningún error ni inconsistencia en los reportes: nuestro sistema "
                "solo toma las fichadas reales, no los fallidos que muestra hikcentral.")],
     []),
    (546, "Legajo 12381 Balcarce Nadia Mariela",
     "El agente manifiesta recibir error al fichar la salida, podemos ver que las fichadas se ven "
     "reflejadas en el hik central y no asi en ITH reportes.",
     [(TECNICO, ADMIN_TXT)],
     []),
    (549, "Legajo 5808 Martínez Alexis Ezequiel",
     "El agente tiene problemas para fichar y ver sus registros, las fichadas llegan a hik central "
     "y no así a ITH reportes.",
     [(SOLICITANTE, "Seguimos con problemas con los registros biométricos de este agente."),
      (TECNICO, ADMIN_TXT)],
     []),
    (191, "Reporte",
     "Al sacar el reporte de ausentismo me está faltando gente que se encuentra ausente.",
     [(TECNICO, "Desde nuestras bases eliminamos la coma de las Unidades Organizativas.")],
     []),
    (300, "Impresora sin tóner",
     "La impresora de administración no imprime, parece que se quedó sin tóner.",
     [(TECNICO, "Se cambió el tóner.")],
     ["Se cambió el tóner y se probó una impresión."]),
]


def corpus_falso(estados=(4, 5, 6)):
    """Lo mismo que devuelve _corpus() leyendo la mesa de ayuda, pero armado en memoria."""
    docs = []
    for tid, asunto, desc, fus, sols in HISTORICO:
        soporte = [t for a, t in fus if a != SOLICITANTE]
        h_prob = T._normalizar(f"{asunto} {desc}")
        h_resto = T._normalizar(" ".join([t for _, t in fus] + sols))
        docs.append({"t": {"id": tid, "name": asunto, "status": 6}, "id": tid, "problema": desc,
                     "fus": [t for _, t in fus], "fus_soporte": soporte, "sols": sols,
                     "h_prob": h_prob, "j_prob": h_prob.replace(" ", ""),
                     "h_resto": h_resto, "j_resto": h_resto.replace(" ", "")})
    return docs


class MesaFalsa(T._GLPI):
    """El adaptador real, con el histórico ya cargado (no toca la red)."""

    def __init__(self):
        self.gl, self.ent = {"glpi_url": "https://falsa"}, 0
        self.ithos_id = 28

    def _corpus(self, estados):
        return corpus_falso(estados)


CONSULTA = ("decime todos los tickets que ya resolvimos con problemas de que no se mostraban las "
            "fichadas pero si en HikCentral, así tomo de modelo esos tickets")


print("\n=== 1 · ENCONTRAR el caso aunque esté escrito con otras palabras ===")
casos = MesaFalsa().casos_similares(CONSULTA)
ids = [c["id"] for c in casos]
ok(545 in ids, "encuentra el ticket que dice 'la fichada' en singular y 'hik central' separado",
   f"ids={ids}")
ok(495 in ids, "encuentra el otro caso del mismo problema (el que antes se salteaba)", f"ids={ids}")
ok(300 not in ids, "no trae un ticket de otro tema (impresora)", f"ids={ids}")
ok(all(T._raiz(w) for w in ("fichadas",)) and
   T._contiene("fichadas", T._normalizar("la fichada no figura"), "lafichadanofigura"),
   "'fichadas' reconoce 'la fichada' (misma raíz)")
ok(T._contiene("hikcentral", T._normalizar("aparece en hik central"),
               T._normalizar("aparece en hik central").replace(" ", "")),
   "'HikCentral' reconoce 'hik central' escrito separado")
ok("resolvimos" not in T._palabras(CONSULTA) and "problemas" in T._palabras(CONSULTA),
   "las palabras con que se PREGUNTA no cuentan como parte del caso",
   str(T._palabras(CONSULTA)))

print("\n=== 2 · Distinguir una RESOLUCIÓN REAL de un cierre administrativo ===")
por_id = {c["id"]: c for c in casos}
ok(por_id[495]["resuelto_de_verdad"] and "fichadas reales" in por_id[495]["resolucion"],
   "toma como resolución lo que escribió el TÉCNICO", por_id[495]["resolucion"][:60])
ok(not por_id[546]["resuelto_de_verdad"] and por_id[546]["cierre_administrativo"],
   "el cierre por 'la categoría está mal cargada' NO cuenta como resuelto")
ok(not por_id[545]["resuelto_de_verdad"],
   "un comentario del propio solicitante no se presenta como la solución",
   por_id[545]["resolucion"][:60])
ok(549 not in ids or not por_id[549]["resuelto_de_verdad"],
   "tampoco cuenta 'seguimos con problemas' escrito por quien abrió el ticket")
ok(T._cierre_administrativo(ADMIN_TXT), "reconoce el texto del cierre administrativo")
ok(not T._cierre_administrativo("Se cambió el tóner y se probó una impresión."),
   "una solución técnica de verdad NO se marca como administrativa")

print("\n=== 3 · El asistente SALE A BUSCAR (y no puede inventar números) ===")
ok(C._pide_antecedentes(CONSULTA), "detecta que están preguntando por casos ya trabajados")
ok(C._pide_antecedentes("hubo algún caso parecido antes?"), "detecta 'caso parecido'")
ok(not C._pide_antecedentes("cerrá el ticket 545"), "una orden común no dispara la búsqueda")
ok(not C._pide_antecedentes("hola, cómo va todo"), "una charla no dispara la búsqueda")


class IAFalsa:
    """Se queda con lo que se le manda, para poder mirar qué contexto recibió el modelo."""

    def __init__(self):
        self.prompt = self.sistema = ""

    def chat(self, sistema, prompt, json_out=False, max_tokens=None):
        self.sistema, self.prompt = sistema, prompt
        return '{"acciones": [], "recordar": null, "respuesta": "Listo."}'


# Las herramientas REALES del asistente, con la mesa de ayuda falsa detrás.
T.adaptador = lambda cli_cfg: MesaFalsa()
herr = C.herramientas_tickets({"nombre": "test"})
herr["tickets_abiertos"] = {"desc": "abiertos",
                            "fn": lambda a: "Hay 1 ticket abierto. #900 Otra cosa"}
ok("casos_parecidos" in herr, "el asistente tiene la herramienta de antecedentes")
texto_tool = herr["casos_parecidos"]["fn"]({"problema": CONSULTA})
ok("#545" in texto_tool and "#495" in texto_tool,
   "la herramienta devuelve los casos reales con su número")
ok("administrativo" in texto_tool, "y marca los que se cerraron sin resolución técnica")

ia = IAFalsa()
asis = C.Asistente(ia, herr, empresa="test")
asis.responder_texto(CONSULTA, canal="whatsapp", remitente="5491156660181")
ctx = ia.prompt
ok("ANTECEDENTES" in ctx, "el modelo recibe los antecedentes REALES antes de responder")
ok("#545" in ctx and "#495" in ctx, "los tickets que corresponden llegan al contexto")
ok("ÚNICOS números que existen" in ctx or "ÚNICOS números" in ctx,
   "se le aclara que no hay más números que esos (contra los inventados)")
ok("administrativo" in ctx.lower(),
   "el contexto marca cuáles se cerraron sin resolución técnica")

ia2 = IAFalsa()
C.Asistente(ia2, herr, empresa="test").responder_texto("cerrá el ticket 545", canal="whatsapp")
ok("ANTECEDENTES" not in ia2.prompt,
   "una orden normal NO paga el costo de revisar el histórico entero")

print("\n" + "=" * 70)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("TODO OK · la búsqueda de antecedentes trae los casos reales y no inventa ninguno")
