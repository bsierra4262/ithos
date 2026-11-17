#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: la wiki del equipo (Outline) conectada a ITHOS, sin red.

QUÉ SE PIDIÓ (Brian, 17-nov-2026): que ITHOS lea la wiki, redacte y suba los procedimientos que
salen de los tickets, cada uno donde corresponde, y que así se vuelva más inteligente.

LO QUE NO PUEDE PASAR, y por eso se prueba primero:
  · que lea o escriba la colección de CREDENCIALES ("Core IT - Sensitive & Credentials", los Vault):
    lo que lee termina en la base de conocimiento y de ahí en una respuesta por WhatsApp;
  · que un artículo lleve el NOMBRE o el LEGAJO de la persona afectada;
  · que publique un ticket que no está cerrado, uno que no explica cómo se resolvió, o el mismo
    ticket dos veces (tras un reinicio);
  · que duplique artículos: el mismo problema suma el caso al artículo que ya existe.

Uso:  python tests/probar_wiki.py
"""

import json
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))
_TMP = tempfile.mkdtemp(prefix="ithos_wiki_")
os.environ["ITHOS_DATA"] = _TMP

from comun import outline as OL     # noqa: E402
from comun import estado as E       # noqa: E402
import kb_auto                      # noqa: E402
import wiki as W                    # noqa: E402

FALLAS = []


def ok(cond, msg):
    print(("  OK   " if cond else "  FALLA ") + msg)
    if not cond:
        FALLAS.append(msg)


COLS = [{"id": "c-sd", "name": "IT Service Desk & Support"},
        {"id": "c-net", "name": "Network Engineering"},
        {"id": "c-vault", "name": "Core IT - Sensitive & Credentials"}]
DOCS = [{"id": "d-srt", "collectionId": "c-sd", "title": "Servicio de Mantenimiento Control de Acceso SRT",
         "text": "Prioridades: acceso físico."},
        {"id": "d-red", "collectionId": "c-net", "title": "Topología de red", "text": "Switches y VLANs."},
        {"id": "d-v1", "collectionId": "c-vault", "title": "Vault: Credenciales VPN", "text": "usuario: x / clave: y"},
        {"id": "d-v2", "collectionId": "c-sd", "title": "🔑 Vault: claves del inventario", "text": "secreto"}]


class _OutlineFalso(OL.Outline):
    def __init__(self):
        super().__init__("https://wiki.ejemplo/home", "tok")
        self.docs = [dict(d) for d in DOCS]
        self.escrito = []

    def _post(self, metodo, datos=None):
        datos = datos or {}
        if metodo == "collections.list":
            return {"data": COLS if datos.get("offset", 0) == 0 else []}
        if metodo == "documents.list":
            return {"data": self.docs if datos.get("offset", 0) == 0 else []}
        if metodo == "documents.info":
            return {"data": next(d for d in self.docs if d["id"] == datos["id"])}
        if metodo == "documents.create":
            nuevo = {"id": f"d-nuevo{len(self.escrito)}", "collectionId": datos["collectionId"],
                     "title": datos["title"], "text": datos["text"], "url": "/doc/nuevo",
                     "parentDocumentId": datos.get("parentDocumentId")}
            self.docs.append(nuevo)
            self.escrito.append(("crear", datos))
            return {"data": nuevo}
        if metodo == "documents.update":
            self.escrito.append(("agregar", datos))
            return {"data": {"id": datos["id"], "url": "/doc/existente"}}
        raise AssertionError(metodo)


print("\n=== 1 · Lo sensible no se lee ni se escribe ===")
o = _OutlineFalso()
ok("Core IT - Sensitive & Credentials" not in [c["name"] for c in o.colecciones()],
   "la colección de credenciales no aparece")
titulos = [d["title"] for d in o.documentos()]
ok(not any("Vault" in t for t in titulos), "ningún Vault, ni siquiera uno guardado en otra colección")
ok(len(titulos) == 2, "quedan los dos documentos normales")
try:
    o.crear("c-vault", "x", "y")
    ok(False, "no deja escribir en la colección sensible")
except OL.OutlineError:
    ok(True, "no deja escribir en la colección sensible")
try:
    o.agregar("d-v2", "x")
    ok(False, "no deja modificar un Vault")
except OL.OutlineError:
    ok(True, "no deja modificar un Vault")
ok(OL.Outline("https://wiki.ejemplo/home/", "t").base == "https://wiki.ejemplo",
   "acepta la URL de la portada (/home) y arma la de la API")

print("\n=== 2 · La wiki entra a la base de conocimiento, sincronizada ===")
CLI = "EMPRESA WIKI TEST"
n, total = W.importar({}, CLI, cli=o)
inst = os.path.join(kb_auto.kb_dir(CLI), "instructivos")
archivos = sorted(os.listdir(inst))
ok(n == 2 and len(archivos) == 2, f"escribe los 2 documentos permitidos ({archivos})")
contenido = "".join(open(os.path.join(inst, f), encoding="utf-8").read() for f in archivos)
ok("clave: y" not in contenido and "secreto" not in contenido, "ni una credencial en la KB")
o.docs = [d for d in o.docs if d["id"] != "d-red"]
W.importar({}, CLI, cli=o)
ok(len(os.listdir(inst)) == 1, "un documento borrado de la wiki sale de la KB")

print("\n=== 3 · Redactar y publicar un ticket cerrado ===")
TICKET = {"id": 849, "asunto": "Legajo 13722 Berretta Silvia Patricia",
          "problema": "La persona detallada en el título no puede realizar el fichaje biométrico",
          "solucion": "No estaba sincronizado en la terminal de Sarmiento. Le quitamos el PIN y le "
                      "volvimos a dar acceso.", "estado": 6, "fecha_cierre": "17/11/2026"}


class _IA:
    def __init__(self, respuesta):
        self.r, self.llamadas = respuesta, 0

    def chat(self, sistema, texto, json_out=False):
        self.llamadas += 1
        if isinstance(self.r, Exception):
            raise self.r
        return json.dumps(self.r)


BUENA = {"publicable": True, "titulo": "Berretta (13722) no puede fichar: usuario no sincronizado",
         "coleccion": "IT Service Desk & Support", "mismo_doc": None,
         "sintoma": "Silvia Berretta, legajo 13722, no puede fichar en la terminal de Sarmiento.",
         "causa": "El usuario no estaba sincronizado en la terminal.",
         "pasos": ["Quitar el PIN del usuario", "Volver a darle acceso en la terminal"],
         "verificacion": "Pedir que fiche de nuevo.", "resumen": "Se resincronizó al usuario."}
o = _OutlineFalso()
PADRE = "Servicio de Mantenimiento Control de Acceso SRT"
estado, url = W.publicar_ticket(o, _IA(BUENA), TICKET, padre_cfg=PADRE)
ok(estado == "publicado" and o.escrito and o.escrito[-1][0] == "crear", "publica un artículo nuevo")
d = o.escrito[-1][1]
ok(d["collectionId"] == "c-sd", "en la colección que eligió (Service Desk)")
ok(d.get("parentDocumentId") == "d-srt", "dentro del documento del servicio de SRT (configurado)")
ok(d.get("publish") is True, "publicado, no en borrador")
todo = d["title"] + d["text"]
ok("13722" not in todo and "Berretta" not in todo and "Silvia" not in todo,
   "sin el nombre ni el legajo de la persona, aunque la IA los haya puesto")
ok("Sarmiento" in todo, "la sede sí queda: no es un dato personal")
ok("1. Quitar el PIN" in d["text"] and "## Casos" in d["text"] and "#849" in d["text"],
   "con el procedimiento numerado y el ticket de referencia")
ok(url == "https://wiki.ejemplo/doc/nuevo", "devuelve el link completo")

print("\n=== 4 · El mismo problema no se duplica: suma el caso ===")
# Caso real del ensayo: #821, #822 y #823 con el mismo procedimiento salían como tres artículos.
o = _OutlineFalso()
CASI = [{**BUENA, "titulo": t, "sintoma": s, "pasos": p} for t, s, p in (
    ("Usuario no puede fichar: corrección de parámetros y sincronización", "No puede fichar",
     ["Corregir los parámetros de acceso del usuario", "Sincronizar al usuario en el sistema"]),
    ("Problema de fichaje: parámetros de acceso", "El agente no puede fichar",
     ["Corregir los parámetros de acceso del usuario", "Sincronizar la cuenta del usuario"]),
    ("Usuario no puede fichar - sincronización", "El usuario no puede fichar ni registrar asistencia",
     ["Corregir los parámetros de acceso", "Sincronizar al usuario en el control de acceso"]))]
estados = [W.publicar_ticket(o, _IA(r), dict(TICKET, id=i))[0] for i, r in zip((821, 822, 823), CASI)]
ok(estados == ["publicado", "agregado", "agregado"],
   f"tres casos con el mismo procedimiento = UN artículo con tres casos ({estados})")
agregados = [e[1] for e in o.escrito if e[0] == "agregar"]
ok(agregados and all(e.get("append") is True for e in agregados),
   "suma al final del artículo, sin pisar lo que ya tenía")
ok(all("13722" not in e["text"] for e in agregados), "el caso que suma tampoco lleva el legajo")
o = _OutlineFalso()
estado, _ = W.publicar_ticket(o, _IA({**BUENA, "mismo_doc": "d-srt"}), TICKET)
ok(estado == "publicado" and o.escrito[-1][0] == "crear",
   "nunca le suma un caso a un documento que escribió el equipo, aunque la IA lo proponga")

print("\n=== 5 · Lo que no se publica ===")
o = _OutlineFalso()
ok(W.publicar_ticket(o, _IA({**BUENA, "publicable": False}), TICKET)[0] == "no_publicable"
   and not o.escrito, "si el técnico no explicó cómo lo resolvió, no se escribe nada")
ok(W.publicar_ticket(o, _IA(RuntimeError("429")), TICKET)[0] == "sin_ia" and not o.escrito,
   "sin IA no se escribe nada (y se reintenta después)")
ok(W.publicar_ticket(o, _IA({**BUENA, "coleccion": "Core IT - Sensitive & Credentials",
                              "padre": None}), TICKET)[0] == "publicado"
   and o.escrito[-1][1]["collectionId"] == "c-sd",
   "si la IA elige la colección sensible, cae en Service Desk")

print("\n=== 6 · La vuelta: sólo cerrados, de a pocos, y nunca dos veces ===")
from comun import tickets as T     # noqa: E402
LISTA = [dict(TICKET, id=i, estado=st) for i, st in ((1, 6), (2, 5), (3, 6), (4, 6), (5, 6))]


class _Adap:
    def resueltos(self, n):
        return LISTA


_o = _OutlineFalso()
_orig_a, _orig_d = T.adaptador, OL.desde_config
T.adaptador = lambda conf: _Adap()
OL.desde_config = lambda conf: _o
try:
    E.guardar("wiki", CLI, {})
    ia = _IA(BUENA)
    hechos1 = W.publicar_cerrados({"nombre": CLI}, ia, CLI, por_vuelta=2)
    ok([h[0] for h in hechos1] == [1, 3], "toma sólo los CERRADOS (el #2 está resuelto) y de a 2")
    hechos2 = W.publicar_cerrados({"nombre": CLI}, ia, CLI, por_vuelta=2)
    ok([h[0] for h in hechos2] == [4, 5], "la vuelta siguiente sigue donde quedó")
    llamadas = ia.llamadas
    ok(W.publicar_cerrados({"nombre": CLI}, ia, CLI) == [] and ia.llamadas == llamadas,
       "con todo hecho no vuelve a llamar a la IA ni a publicar (sobrevive un reinicio)")
    E.guardar("wiki", CLI, {})
    sin = W.publicar_cerrados({"nombre": CLI}, _IA(RuntimeError("cuota")), CLI)
    ok(sin == [] and not E.cargar("wiki", CLI).get("hechos"),
       "sin IA no marca nada como hecho: lo retoma cuando vuelve")
finally:
    T.adaptador, OL.desde_config = _orig_a, _orig_d

print("\n=== 7 · Lo que escribió ITHOS no es la resolución ===")
g = T._GLPI.__new__(T._GLPI)
g.ithos_id = 28
fu = {849: [{"texto": "El inconveniente quedó solucionado; le quitamos el PIN.", "autor": 7},
            {"texto": "Hola Facundo, recibimos el ticket. No hace falta que nos manden nada más.",
             "autor": 28}]}
ok("quitamos el PIN" in g._mejor_solucion(849, {"users_id_recipient": 26}, {}, fu),
   "toma el comentario del técnico, no la respuesta de ITHOS que vino después")

print()
if FALLAS:
    print(f"FALLARON {len(FALLAS)}")
    sys.exit(1)
print("TODO OK · la wiki se lee sin lo sensible y cada ticket cerrado deja su procedimiento")
