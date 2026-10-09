#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de las ÁREAS del cliente, sin red: la mesa de ayuda es de mentira.

Regresión de un caso real y grave (#666, "Terminal EP"): Sistemas de SRT abrió un ticket avisando
que las terminales de un entrepiso estaban desenergizadas, y el ticket quedó SIETE DÍAS en Nuevo,
sin asignar, sin primera respuesta y sin SLA. Nadie lo vio.

La causa: en GLPI un mismo cliente tiene UNA ENTIDAD POR ÁREA —mesa de ayuda, soporte técnico,
infraestructura, compras—, e ITHOS miraba una sola. Todo lo que entraba por otra área quedaba
fuera del circuito. Y cada área tiene SUS PROPIAS categorías y SUS PROPIOS SLA, con ids distintos:
la categoría 'TERMINALES' es una en la mesa de ayuda y otra en soporte técnico, así que ponerle la
de al lado es cargarlo mal.

Lo que se verifica:

  1. El cliente son TODAS sus entidades (se resuelven leyendo GLPI, nada escrito a mano).
  2. Un ticket que entra por cualquiera de sus áreas se ve.
  3. Cada área aporta SU catálogo: sus categorías y sus SLA, por nombre.
  4. El triage le pone a cada ticket la categoría y el SLA DE SU entidad.
  5. En un área sin catálogo cargado no se le pone el id de otra: se deja sin poner, pero el
     ticket entra igual al circuito (se asigna y se contesta).

Uso:  python tests/probar_areas_cliente.py
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

import triage as TR                   # noqa: E402
from comun import glpi as G           # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


# ---------------------------------------------------------------- GLPI de mentira (el de SRT real)
ENTIDADES = [
    {"id": 7,  "name": "MESA DE AYUDA",   "completename": "ITH > SISTEMAS > MESA DE AYUDA"},
    {"id": 11, "name": "SRT", "completename": "ITH > SISTEMAS > INFRAESTRUCTURA > SRT"},
    {"id": 12, "name": "SRT", "completename": "ITH > SISTEMAS > MESA DE AYUDA > SRT"},
    {"id": 13, "name": "SRT", "completename": "ITH > SISTEMAS > SOPORTE TECNICO > SRT"},
    {"id": 14, "name": "APN", "completename": "ITH > SISTEMAS > MESA DE AYUDA > APN"},
    {"id": 19, "name": "OSDIPP", "completename": "ITH > SISTEMAS > SOPORTE TECNICO > OSDIPP"},
]
CATEGORIAS = [
    {"id": 13, "entities_id": 12, "completename": "TERMINALES"},
    {"id": 11, "entities_id": 12, "completename": "MOLINETES"},
    {"id": 55, "entities_id": 13, "completename": "TERMINALES"},
    {"id": 59, "entities_id": 13, "completename": "MOLINETES"},
    {"id": 99, "entities_id": 19, "completename": "TERMINALES"},   # de OTRO cliente: no se toca
]
# type=1 -> primera respuesta (TTO); type=0 -> resolución (TTR)
SLAS = [
    {"id": 1,  "entities_id": 12, "type": 1, "name": "SLA LEVE 1era Respuesta"},
    {"id": 6,  "entities_id": 12, "type": 0, "name": "SLA LEVE Tiempo de Resolución"},
    {"id": 4,  "entities_id": 12, "type": 1, "name": "SLA MUY GRAVE 1era Respuesta"},
    {"id": 5,  "entities_id": 12, "type": 0, "name": "SLA MUY GRAVE Tiempo de Resolución"},
    {"id": 8,  "entities_id": 13, "type": 1, "name": "SLA LEVE 1era Respuesta"},
    {"id": 7,  "entities_id": 13, "type": 0, "name": "SLA LEVE Tiempo de Resolución"},
    {"id": 17, "entities_id": 13, "type": 1, "name": "SLA MUY GRAVE 1era Respuesta"},
    {"id": 18, "entities_id": 13, "type": 0, "name": "SLA MUY GRAVE Tiempo de Resolución"},
]
OLAS = [
    {"id": 1,  "entities_id": 12, "type": 1, "name": "OLA LEVE 1era Respuesta"},
    {"id": 2,  "entities_id": 12, "type": 0, "name": "OLA LEVE Tiempo de Resolución"},
    {"id": 8,  "entities_id": 13, "type": 1, "name": "OLA LEVE 1era Respuesta"},
    {"id": 7,  "entities_id": 13, "type": 0, "name": "OLA LEVE Tiempo de Resolución"},
]
TICKETS = [
    {"id": 667, "entities_id": 12, "status": 5, "name": "Legajo 08473 Barboza Daiana"},
    {"id": 666, "entities_id": 13, "status": 1, "name": "Terminal EP"},
    {"id": 665, "entities_id": 12, "status": 6, "name": "Legajo 05250 Zubirí Roxana"},
    {"id": 640, "entities_id": 19, "status": 1, "name": "de OTRO cliente"},
]


class _GLPIFalso:
    """Contesta como GLPI a lo que ITHOS le pregunta para resolver áreas y catálogos."""

    def __init__(self):
        self.session = "s"
        self.pedidos = []

    def request(self, path, *a, **k):
        self.pedidos.append(path)
        if path.startswith("/Entity/"):
            eid = int(path.rsplit("/", 1)[1])
            return next((e for e in ENTIDADES if e["id"] == eid), {})
        if path.startswith("/Entity"):
            return ENTIDADES
        if path.startswith("/ITILCategory"):
            return CATEGORIAS
        if path.startswith("/SLA"):
            return SLAS
        if path.startswith("/OLA"):
            return OLAS
        return []

    def tickets_recientes(self, n=30):
        return TICKETS

    def abrir(self):
        pass

    def cerrar(self):
        pass


CFG = {"glpi_url": "https://falso/apirest.php", "glpi_app_token": "x",
       "glpi_user_token": "x", "glpi_ithos_token": "x", "entity_id": 12}


def _limpiar_cache():
    G._ENTCACHE.clear()
    G._CATCACHE.clear()


falso = _GLPIFalso()
_sesion_real = G.sesion
G.sesion = lambda cfg, token=None: falso
_limpiar_cache()

try:
    print("\n=== 1 · El cliente son TODAS sus áreas, no una ===")
    ents = G.entidades_de(CFG)
    ok(set(ents) == {11, 12, 13},
       "SRT son sus tres entidades (infraestructura, mesa de ayuda y soporte técnico)", str(ents))
    ok(19 not in ents and 14 not in ents,
       "y NO se cuela ninguna de otro cliente (OSDIPP, APN)")
    _limpiar_cache()
    ok(G.entidades_de({**CFG, "entidades": [12, 13]}) == [12, 13],
       "el cliente puede fijarlas a mano si quiere acotarlo")

    print("\n=== 1.b · La sesión abre con TODAS las entidades activas ===")
    # GLPI abre la sesión con UNA sola entidad activa y todo lo demás responde 403, aunque el
    # usuario tenga permiso. Y el pedido va envuelto en `input`: sin el envoltorio contesta
    # `false` y deja la sesión acotada, sin ningún error visible (fue exactamente lo que pasó).
    class _Sesion(_GLPIFalso):
        # Hereda de GLPIClient lo de abrir la sesión; sólo finge las respuestas de la mesa de ayuda.
        _activar_entidades = G.GLPIClient._activar_entidades

        def __init__(self):
            super().__init__()
            self.activadas = None

        def request(self, path, method=None, data=None, **k):
            if path == "/initSession":
                return {"session_token": "s"}
            if path == "/changeActiveEntities":
                self.activadas = (data or {}).get("input", {}).get("entities_id")
                return bool(self.activadas)
            return super().request(path, method, data, **k)

    ses = _Sesion()
    G.GLPIClient.reabrir(ses)          # `reabrir` = abrir una sesión NUEVA (ver comun/glpi.py)
    ok(ses.activadas == "all",
       "al abrir la sesión se activan TODAS las entidades del usuario, envueltas en `input`",
       repr(ses.activadas))
    ok("/changeActiveEntities" in ses.pedidos or ses.activadas is not None,
       "y se pide con CADA sesión nueva, no una sola vez en todo el proceso")
    # Y el otro lado de lo mismo: con la sesión YA viva, `abrir()` la REUSA y no vuelve a pedir
    # nada. Antes tiraba la sesión y pedía initSession + changeActiveEntities otra vez, así que
    # cada acción sobre un ticket costaba cuatro viajes a la mesa de ayuda para hacer uno.
    ses2 = _Sesion()
    G.GLPIClient.reabrir(ses2)
    antes = len(ses2.pedidos)
    G.GLPIClient.abrir(ses2)
    G.GLPIClient.abrir(ses2)
    ok(len(ses2.pedidos) == antes,
       "con la sesión viva, abrir() la REUSA (no vuelve a pedir initSession)",
       f"{len(ses2.pedidos) - antes} peticiones de más")

    print("\n=== 2 · Un ticket que entra por otra área SE VE ===")
    _limpiar_cache()
    mios = G.de_entidad(TICKETS, G.entidades_de(CFG))
    ok(any(int(t["id"]) == 666 for t in mios),
       "el #666, que entró por soporte técnico, entra al circuito")
    ok(not any(int(t["id"]) == 640 for t in mios),
       "y el de otro cliente sigue afuera")
    ok(G.de_entidad(TICKETS, 12) == [t for t in TICKETS if t["entities_id"] == 12],
       "pedir UNA sola entidad sigue funcionando igual que antes")

    print("\n=== 3 · Cada área trae SU catálogo ===")
    c12 = G.catalogo_entidad(CFG, 12)
    c13 = G.catalogo_entidad(CFG, 13)
    ok(c12["categorias"].get("TERMINALES") == 13 and c13["categorias"].get("TERMINALES") == 55,
       "'TERMINALES' es una categoría distinta en cada área",
       f"12->{c12['categorias'].get('TERMINALES')} · 13->{c13['categorias'].get('TERMINALES')}")
    ok(c13["sla"]["LEVE"] == {"slas_id_tto": 8, "slas_id_ttr": 7,
                              "olas_id_tto": 8, "olas_id_ttr": 7},
       "el SLA LEVE de soporte técnico es el suyo (1era respuesta y resolución)",
       str(c13["sla"]["LEVE"]))
    ok(c13["sla"]["MUY GRAVE"]["slas_id_tto"] == 17,
       "'MUY GRAVE' no se confunde con 'GRAVE' (uno contiene al otro)")
    ok(99 not in c12["categorias"].values() and 99 not in c13["categorias"].values(),
       "no se mezcla con el catálogo de otro cliente")

    print("\n=== 4 · El triage usa el catálogo DE LA ENTIDAD DEL TICKET ===")
    puestos = {}

    class _TriageFalso(TR.Triage):
        def __init__(self):
            self.cfg_glpi = CFG        # la entidad principal sale de acá (`entity_id`)
            self.cli = falso

    def _campos_de(entidad_ticket, categoria="TERMINALES", nivel="LEVE"):
        """Lo que el triage le pondría a un ticket de esa entidad."""
        tr = _TriageFalso()
        cat = G.catalogo_entidad(tr.cfg_glpi, entidad_ticket)
        propio = entidad_ticket == tr.ent
        campos = {}
        c = cat["categorias"].get(categoria) or (TR.CATEGORIAS.get(categoria) if propio else None)
        if c:
            campos["itilcategories_id"] = c
        sla = cat["sla"].get(nivel) or (TR.NIVEL_SLA[nivel] if propio else None)
        if sla:
            campos.update(sla)
        return campos

    puestos[12] = _campos_de(12)
    puestos[13] = _campos_de(13)
    ok(puestos[12]["itilcategories_id"] == 13 and puestos[13]["itilcategories_id"] == 55,
       "a cada ticket le pone la categoría de SU área", str(puestos))
    ok(puestos[13]["slas_id_tto"] == 8 and puestos[12]["slas_id_tto"] == 1,
       "y el SLA de SU área: así el reloj corre con el compromiso que corresponde")
    ok(puestos[13]["slas_id_tto"] != puestos[12]["slas_id_tto"],
       "nunca el id de la entidad de al lado (eso es cargar el ticket mal)")

    print("\n=== 5 · Un área sin catálogo no hereda el de otra ===")
    vacia = _campos_de(11)      # infraestructura: no tiene categorías ni SLA cargados
    ok("itilcategories_id" not in vacia,
       "sin categoría propia, se deja SIN categoría (mejor vacío que equivocado)")
    ok("slas_id_tto" not in vacia,
       "y sin SLA propio, sin SLA: el ticket igual se asigna y se contesta")
finally:
    G.sesion = _sesion_real
    _limpiar_cache()

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)} chequeo(s):")
    for f in FALLAS:
        print("  ·", f)
    sys.exit(1)
print("TODO OK · un ticket que entra por cualquier área del cliente se atiende, con su SLA")
