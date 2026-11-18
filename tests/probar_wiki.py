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
            self.escrito.append(("agregar" if datos.get("append") else "reemplazar", datos))
            for d in self.docs:
                if d["id"] == datos["id"]:
                    d["text"] = d.get("text", "") + datos["text"] if datos.get("append") else datos["text"]
            return {"data": {"id": datos["id"], "url": "/doc/existente"}}
        raise AssertionError(metodo)

    def subir_imagen(self, nombre, datos, tipo, doc_id):
        self.escrito.append(("imagen", {"nombre": nombre, "doc": doc_id, "tipo": tipo}))
        return f"/api/attachments.redirect?id={nombre}"


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

    def chat(self, sistema, texto, json_out=False, max_tokens=None):
        self.llamadas += 1
        self.max_tokens = max_tokens
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
ok("1. Quitar el PIN" in d["text"] and W.CASOS in d["text"] and "#849" in d["text"],
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

print("\n=== 8 · El paso a paso es el del técnico, con sus capturas (Brian, 17-nov) ===")
# Lo que reportó Brian: el artículo salía genérico ("se corrigieron los parámetros de acceso")
# porque se tomaba la SOLUCIÓN de dos líneas que se carga al cerrar, y el paso a paso con capturas
# que el técnico deja en un seguimiento (HikInOut.sql, Nivel de acceso, la terminal) se perdía.
HTML_GLPI = ("&lt;p&gt;Empezamos revisando sus fichadas con la consulta HikINOut query.sql.&lt;br&gt;"
             "&lt;a href=\"/front/document.send.php?docid=259&amp;itemtype=Ticket&amp;items_id=664\"&gt;"
             "&lt;img alt=\"x\" src=\"/front/document.send.php?docid=259&amp;itemtype=Ticket&amp;items_id=664\" /&gt;"
             "&lt;/a&gt;&lt;br&gt;Luego en HikCentral, pestaña Nivel de acceso: #1 Bluetooth #2 PIN.&lt;/p&gt;"
             "&lt;p&gt;&lt;img src=\"/front/document.send.php?docid=250&amp;itemtype=Ticket\" /&gt;&lt;/p&gt;")
txt = T._texto_con_capturas(HTML_GLPI)
ok(txt.index("HikINOut") < txt.index("[[img:259]]") < txt.index("Nivel de acceso") < txt.index("[[img:250]]"),
   "el HTML de GLPI queda en texto con cada captura en el lugar donde la puso el técnico")


class _GLPIFalso:
    """Un ticket como #822: el solicitante adjuntó fotos suyas en la terminal; el técnico, capturas."""
    _pooled = True

    def request(self, path):
        if path == "/Ticket/822":
            return {"name": "Agente Cabañas Martin", "content": "Legajo 16421. No funciona su fichaje",
                    "users_id_recipient": 27, "status": 6, "closedate": "2026-11-16 14:00:00",
                    "itilcategories_id": 13}
        if path == "/ITILCategory/13":
            return {"name": "TERMINALES"}
        if path.startswith("/Ticket/822/Ticket_User"):
            return [{"type": 1, "users_id": 27}, {"type": 2, "users_id": 30}]
        if path.startswith("/Ticket/822/ITILFollowup"):
            if "range=0-" in path and not path.endswith("range=0-499"):
                return []
            return [{"users_id": 28, "content": "Hola Pablo, recibimos el ticket.", "date_creation": "2026-11-16 12:25"},
                    {"users_id": 27, "content": "Sigue igual", "date_creation": "2026-11-16 12:30"},
                    {"users_id": 30, "content": HTML_GLPI, "date_creation": "2026-11-16 13:59"}]
        if "/TicketTask" in path or "/ITILSolution" in path:
            return [{"users_id": 30, "content": "Se corrigieron los parámetros de acceso.",
                     "date_creation": "2026-11-16 14:00"}] if "/ITILSolution" in path and path.endswith("499") else []
        if path.startswith("/Ticket/822/Document_Item"):
            return [{"documents_id": 457}, {"documents_id": 259}, {"documents_id": 600}]
        if path == "/Document/457":
            return {"mime": "image/jpeg", "users_id": 27}          # foto del solicitante: no va
        if path == "/Document/600":
            return {"mime": "image/png", "users_id": 30}           # captura suelta del técnico: va
        raise AssertionError(path)

    def descargar(self, path):
        return b"\x89PNG", "image/png"

    def cerrar(self):
        pass


g = T._GLPI.__new__(T._GLPI)
g.ithos_id = 28
g._c_admin = lambda: _GLPIFalso()
h = g.historial(822)
todo_h = " ".join(e["texto"] for e in h["soporte"])
ok("recibimos el ticket" not in todo_h and "Sigue igual" not in todo_h,
   "afuera lo de ITHOS y lo del solicitante")
ok("HikINOut" in todo_h and "Se corrigieron" in todo_h, "adentro el seguimiento del técnico y la solución")
ok("[[img:457]]" not in todo_h, "la foto que mandó el solicitante (su cara en la terminal) no entra")
ok("[[img:600]]" in todo_h and h["soporte"][-1]["tipo"] == "Adjuntos",
   "la captura que el técnico adjuntó sin embeber entra al final")
ok(h["categoria"] == "TERMINALES" and h["fecha_cierre"] == "16/11/2026", "trae la categoría y la fecha de cierre")

ticket_rico = {**TICKET, "id": 664, "categoria": "TERMINALES", "asunto": "Legajo 08609 Bufacchi Fernando",
               "problema": "Legajo: 08609 - Bufacchi, Fernando. Al fichar aparece otro nombre",
               "soporte": [{"tipo": "ITILFollowup", "fecha": "2026-08-10",
                            "texto": "Corrimos HikInOut.sql [[img:259]] y en Nivel de acceso había PIN [[img:250]] "
                                     "y lo borramos [[img:251]]"}]}
entrada, mapa = W._entrada_soporte(ticket_rico)
ok(mapa == {1: 259, 2: 250, 3: 251} and "[CAPTURA 1]" in entrada and "[[img" not in entrada,
   "la IA recibe las capturas numeradas en su lugar")
PASOS_RICOS = {**BUENA, "titulo": "Agente no puede fichar: PIN y Bluetooth en HikCentral",
               "sintoma": "Al fichar aparece el nombre de otro agente (Fernando Bufacchi, legajo 08609).",
               "herramientas": ["SQL Server (base ITH)", "HikCentral"],
               "pasos": [{"titulo": "Revisar las fichadas (HikInOut.sql)",
                          "detalle": "Ejecutar HikInOut.sql con el legajo 08609: última fichada el 5/8.", "capturas": [1]},
                         {"titulo": "Quitar PIN y Bluetooth",
                          "detalle": "En HikCentral > Nivel de acceso, borrar el Código PIN y Guardar.", "capturas": [2]}],
               "atencion": "Revisar también al otro agente que aparece en la terminal."}


class _Fuente:
    def __init__(self):
        self.bajadas = []

    def imagen(self, did):
        self.bajadas.append(did)
        return b"\x89PNG", "image/png"


o, fu_ = _OutlineFalso(), _Fuente()
ia8 = _IA(PASOS_RICOS)
estado, _ = W.publicar_ticket(o, ia8, ticket_rico, padre_cfg=PADRE, fuente=fu_)
texto = o.docs[-1]["text"]
ok(estado == "publicado", "publica el artículo")
ok((ia8.max_tokens or 0) >= 4000, "pide lugar para el paso a paso entero (el tope corto lo cortaba a la mitad)")
ok("HikInOut.sql" in texto and "Nivel de acceso" in texto and "Código PIN" in texto,
   "el paso a paso es el literal: consulta, pantalla y campo")
ok(texto.index("### 1.") < texto.index("captura1") < texto.index("### 2.") < texto.index("captura2"),
   "cada captura queda debajo del paso que ilustra")
ok("captura3" in texto, "la captura que la IA no asignó a ningún paso no se pierde")
imgs = [e[1] for e in o.escrito if e[0] == "imagen"]
ok(len(imgs) == 3 and all(i["doc"] == o.docs[-1]["id"] for i in imgs),
   "las capturas se suben ASOCIADAS al artículo (sueltas, el equipo no las vería)")
ok(fu_.bajadas == [259, 250, 251], "se bajan de GLPI las del técnico, en orden")
ok(":::info" in texto and "🛠️ Procedimiento paso a paso" in texto and ":::warning" in texto
   and "🏷️ Categoría en GLPI:** TERMINALES" in texto, "formato de wiki: recuadros, secciones, categoría")
ok("08609" not in texto and "Bufacchi" not in texto and "Fernando" not in texto,
   "ni el legajo ni el nombre, tampoco los que vienen en la descripción ('Legajo: 08609 - Bufacchi, Fernando')")

print("\n=== 9 · Un caso mejor documentado mejora el artículo y conserva los casos ===")
o = _OutlineFalso()
pobre = {**BUENA, "pasos": ["Corregir los parámetros de acceso", "Sincronizar al usuario"],
         "titulo": "Agente no puede fichar: parámetros de acceso", "sintoma": "El agente no puede fichar"}
W.publicar_ticket(o, _IA(pobre), dict(TICKET, id=823))
art = o.docs[-1]
rico = {**PASOS_RICOS, "mismo_doc": art["id"]}
estado, _ = W.publicar_ticket(o, _IA(rico), ticket_rico, fuente=_Fuente())
ok(estado == "mejorado" and o.escrito[-1][0] == "reemplazar",
   "el caso con el paso a paso completo reescribe el artículo de ITHOS")
ok("#823" in art["text"] and "#664" in art["text"] and "HikInOut.sql" in art["text"],
   "conserva el caso anterior, suma el nuevo y queda el procedimiento completo")
ok(art["text"].count(W.CASOS) == 1, "una sola lista de casos")
estado, _ = W.publicar_ticket(o, _IA({**pobre, "mismo_doc": art["id"]}), dict(TICKET, id=824))
ok(estado == "agregado" and "HikInOut.sql" in art["text"] and "#824" in art["text"],
   "un caso más pobre después NO pisa el procedimiento completo: sólo suma el caso")

print()
if FALLAS:
    print(f"FALLARON {len(FALLAS)}")
    sys.exit(1)
print("TODO OK · la wiki se lee sin lo sensible y cada ticket cerrado deja su procedimiento")
