#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
La WIKI del equipo (Outline) conectada a ITHOS, en los dos sentidos.

LEER. La wiki entra en la base de conocimiento del cliente: cada documento de las colecciones
permitidas se guarda en `instructivos/` y la KB lo combina con lo aprendido de los tickets. Es una
SINCRONIZACIÓN: lo que se borra o se mueve a una colección sensible en la wiki, sale de la KB.

ESCRIBIR. Cuando un ticket se CIERRA y lo que escribió soporte explica cómo se resolvió, ITHOS
redacta el procedimiento y lo publica en la colección que corresponde por el tema. Es el paso a
paso LITERAL del técnico —qué consulta corrió, qué pantalla abrió, qué encontró, qué cambió— con
cada captura que dejó en el ticket debajo del paso que ilustra; no un resumen genérico. Al cierre y
no al resolverse: si el cliente después dice que sigue fallando, el procedimiento estaba mal, y eso
no puede quedar escrito en la wiki como la forma de resolverlo. Si ya hay un artículo sobre el
MISMO problema, no se duplica: se le suma el caso, y si este caso trae el procedimiento más
completo, el artículo se reescribe con él. Así la wiki crece con cada ticket y la KB con ella.

TRES REGLAS que no se negocian:
  · Nada sensible: las colecciones de credenciales no se leen ni se escriben (comun/outline.py).
  · Nada inventado: el artículo dice SÓLO lo que dicen el ticket y el técnico.
  · Nada personal: ni el nombre ni el legajo de la persona afectada; el artículo describe el caso.
    Las capturas son las del TÉCNICO (consultas, HikCentral, la terminal), que el equipo ya ve en
    GLPI; las fotos que manda el solicitante desde la terminal (su cara, su nombre) no se suben.

Va despacio a propósito (pocos tickets por vuelta): la primera vez hay muchos tickets cerrados para
recorrer y cada uno es una consulta de IA; de golpe se comería la cuota del día del triage.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime

from comun import estado as E
from comun import outline as OL

log = logging.getLogger("wiki")

_PREFIJO = "wiki"
POR_VUELTA = 3                    # tickets que se redactan por vuelta (cuida la cuota de IA)
CADA_SEG = 30 * 60                # una vuelta cada media hora
IMPORTAR_CADA_SEG = 6 * 3600      # la wiki se vuelve a leer cada 6 horas
_RE_SERVICE_DESK = re.compile(r"service\s*desk|soporte|support|mesa de ayuda", re.I)

_SISTEMA_REDACTOR = (
    "Sos el redactor de la base de conocimiento de una mesa de ayuda de IT. Te paso un ticket CERRADO "
    "(el problema) y TODO lo que escribió soporte, en orden. Armá el artículo de procedimiento para la "
    "wiki del equipo: el que va a usar el próximo técnico que tenga el mismo problema.\n"
    "EL PASO A PASO ES LITERAL Y COMPLETO, NO UN RESUMEN. Un paso por cada acción que hizo el técnico, "
    "en su orden, con TODO lo concreto que nombró: el nombre exacto de cada consulta o script "
    "(HikInOut.sql, Incidencias.sql…), el sistema y la pantalla/pestaña/campo (HikCentral > Nivel de "
    "acceso > Código PIN), qué valor encontró, qué significa ('estado 3 = dada de baja'), qué cambió y "
    "cómo lo guardó. Mal: 'Se corrigieron los parámetros de acceso'. Bien: 'En HikCentral, pestaña "
    "Nivel de acceso, desmarcar «Abrir la puerta mediante Bluetooth» y borrar el Código PIN; Guardar'. "
    "Las marcas [CAPTURA n] son las capturas del técnico en el lugar donde las puso: asigná cada una al "
    "paso que ilustra (en 'capturas'), sin perder ninguna.\n"
    "REGLAS: escribí SÓLO lo que dicen el ticket y soporte; no inventes pasos, comandos, menús, causas "
    "ni verificaciones. 'causa', 'verificacion' y 'atencion' van SÓLO si soporte las dice; si no, null. "
    "Ni nombres ni legajos ni DNI de las personas (afectados u otros agentes): 'el agente', 'otro "
    "agente'. Nunca contraseñas. El título nombra el PROBLEMA y su solución en general, no el caso. "
    "Español rioplatense, en infinitivo para los pasos ('Ejecutar…', 'Verificar…'), claro y sin "
    "relleno.\n"
    "Elegí la COLECCIÓN (una de la lista, por el tema). Si uno de los ARTÍCULOS DE ITHOS existentes "
    "trata el mismo problema con el mismo procedimiento, poné su id en 'mismo_doc'.\n"
    "publicable=false si soporte NO explica cómo se resolvió (sólo 'listo', 'solucionado', 'ya "
    "funciona', o es un trámite: categoría mal cargada, duplicado); ante la duda, false.\n"
    "Respondé SOLO JSON: {\"publicable\": true|false, \"titulo\": \"...\", \"coleccion\": \"<nombre "
    "exacto>\", \"mismo_doc\": \"<id o null>\", \"sintoma\": \"...\", \"causa\": \"<o null>\", "
    "\"herramientas\": [\"<sistemas, consultas y pantallas que se usan>\"], "
    "\"pasos\": [{\"titulo\": \"<acción corta>\", \"detalle\": \"<todo lo concreto>\", "
    "\"capturas\": [n]}], \"verificacion\": \"<o null>\", \"atencion\": \"<advertencias o null>\", "
    "\"resumen\": \"<una línea: qué se encontró y qué se hizo en ESTE caso>\"}")


# ===================================================================== LEER: la wiki -> la KB
def importar(conf, cliente, cli=None):
    """Sincroniza la wiki con `instructivos/` de la KB del cliente. Devuelve (escritos, total)."""
    import kb_auto
    cli = cli or OL.desde_config(conf)
    if cli is None:
        return 0, 0
    destino = os.path.join(kb_auto.kb_dir(cliente), "instructivos")
    os.makedirs(destino, exist_ok=True)
    docs = cli.documentos()
    vigentes = set()
    for d in docs:
        texto = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", d.get("text") or "")).strip()
        if not texto:
            continue
        nombre = "outline_" + _seguro(d.get("title") or "documento") + "_" + str(d.get("id", ""))[:8] + ".md"
        vigentes.add(nombre)
        with open(os.path.join(destino, nombre), "w", encoding="utf-8") as f:
            f.write(f"# {d.get('title', '').strip()}\n\n_Wiki · {d['coleccion']}_\n\n{texto}")
    for f in os.listdir(destino):                 # lo que ya no está en la wiki, sale de la KB
        if f.startswith("outline_") and f.endswith(".md") and f not in vigentes:
            try:
                os.remove(os.path.join(destino, f))
            except OSError:
                pass
    return len(vigentes), len(docs)


def _seguro(t):
    return "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in t)[:60] or "doc"


# ===================================================================== ESCRIBIR: tickets -> la wiki
def _json(r):
    if isinstance(r, dict):
        return r
    s = str(r or "")
    m = re.search(r"\{.*\}", s, re.S)
    try:
        return json.loads(m.group(0) if m else s)
    except (ValueError, AttributeError):
        return {}


_NO_NOMBRE = {"Legajo", "Agente", "Sede", "Saludos", "Buenos", "Buen", "Hola", "Id"}


def _sin_datos_personales(texto, ticket):
    """Saca del texto el nombre y los números de la persona afectada que trae el ticket. La IA
    tiene la orden de no ponerlos; esto es la red por si igual se le escapa uno."""
    asunto = f"{ticket.get('asunto', '')} {ticket.get('problema', '')}"
    numeros = set(re.findall(r"\b\d{4,}\b", asunto))
    # El nombre de la persona viene DESPUÉS del legajo ("Legajo 13722 Berretta Silvia", "Legajo:
    # 06544 - Ortiz, Mariano"), en el asunto o en la primera línea donde aparece el legajo en la
    # descripción. Sólo esas palabras: una sede o un equipo con mayúscula ("terminal Sarmiento") no
    # es un dato personal y borrarlo dejaría el artículo sin sentido.
    nombres = set()
    for fuente in (ticket.get("asunto", ""), ticket.get("problema", "")):
        for linea in str(fuente).splitlines():
            m = re.search(r"\b\d{4,}\b\s*[-–:,]?\s*(.+)$", linea)
            if m:
                nombres |= set(re.findall(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}\b", m.group(1)[:60]))
    for n in numeros:
        texto = re.sub(rf"\b{re.escape(n)}\b", "[legajo]", texto)
    for w in nombres - _NO_NOMBRE:
        texto = re.sub(rf"\b{re.escape(w)}\b", "[persona]", texto)
    return texto


def _limpio(a, ticket):
    """El artículo de la IA con cada texto pasado por el filtro de datos personales. Va ANTES de
    poner las URL de las capturas: un número de legajo podría coincidir con un tramo de una URL."""
    def f(x):
        return _sin_datos_personales(str(x or "").strip(), ticket)
    pasos = []
    for p in a.get("pasos") or []:
        if isinstance(p, dict):
            pasos.append({"titulo": f(p.get("titulo")), "detalle": f(p.get("detalle")),
                          "capturas": [int(n) for n in p.get("capturas") or [] if str(n).isdigit()]})
        elif str(p).strip():
            pasos.append({"titulo": f(p), "detalle": "", "capturas": []})
    return {**a, "titulo": f(a.get("titulo")), "sintoma": f(a.get("sintoma")), "causa": f(a.get("causa")),
            "verificacion": f(a.get("verificacion")), "atencion": f(a.get("atencion")),
            "resumen": f(a.get("resumen") or a.get("sintoma")),
            "herramientas": [f(h) for h in a.get("herramientas") or [] if str(h).strip()], "pasos": pasos}


MARCA_ITHOS = "Redactado por ITHOS a partir de los tickets cerrados"
CASOS = "## 📋 Casos"
_RE_CASOS = re.compile(r"^## (?:📋 )?Casos\s*$", re.M)


def _cuerpo(a, capturas=None, categoria=""):
    """El artículo SIN la lista de casos, en el formato de la wiki: el problema en un recuadro,
    las herramientas, el paso a paso con cada captura debajo del paso que ilustra, cómo
    verificar y las advertencias. `capturas`: {n: url} de las capturas ya subidas."""
    capturas = capturas or {}
    intro = [f"**🩺 Síntoma:** {a['sintoma']}"] + ([f"**🧩 Causa:** {a['causa']}"] if a.get("causa") else [])
    partes = [":::info\n" + "\n\n".join(intro) + "\n:::"]
    datos = []
    if a.get("herramientas"):
        datos.append("**🧰 Herramientas:** " + " · ".join(a["herramientas"]))
    if categoria:
        datos.append(f"**🏷️ Categoría en GLPI:** {categoria}")
    if datos:
        partes.append("\n\n".join(datos))
    partes.append("## 🛠️ Procedimiento paso a paso")
    usadas = set()
    for i, p in enumerate(a["pasos"], 1):
        bloque = [f"### {i}. {p['titulo'] or 'Paso ' + str(i)}"]
        if p.get("detalle"):
            bloque.append(p["detalle"])
        for n in p.get("capturas") or []:
            if n in capturas and n not in usadas:
                usadas.add(n)
                bloque.append(f"![Paso {i}]({capturas[n]})")
        partes.append("\n\n".join(bloque))
    resto = [n for n in sorted(capturas) if n not in usadas]   # ninguna captura se pierde
    if resto:
        partes.append("### Capturas del caso\n\n" + "\n\n".join(f"![Captura]({capturas[n]})" for n in resto))
    if a.get("verificacion"):
        partes.append(f"## ✅ Cómo verificar\n\n{a['verificacion']}")
    if a.get("atencion"):
        partes.append(f":::warning\n**⚠️ Atención:** {a['atencion']}\n:::")
    partes.append(f"---\n\n_{MARCA_ITHOS}. Cada caso nuevo del mismo problema se suma abajo._")
    return "\n\n".join(partes)


def _caso(tid, fecha, resumen):
    return f"- Ticket #{tid} ({fecha}): {resumen}"


def _articulo(a, tid, fecha, capturas=None, categoria=""):
    return f"{_cuerpo(a, capturas, categoria)}\n\n{CASOS}\n\n{_caso(tid, fecha, a['resumen'])}"


def _riqueza(texto):
    """Cuánto procedimiento tiene un artículo: pasos + capturas (una captura vale doble)."""
    t = _RE_CASOS.split(texto or "")[0]
    return len(re.findall(r"^###? ?\d+\.", t, re.M)) + len(re.findall(r"^\d+\. ", t, re.M)) + 2 * t.count("![")
# Qué parte del artículo nuevo (0..1) ya está en uno existente para que sea el MISMO procedimiento.
# Medido con casos reales: el mismo procedimiento redactado distinto da ~0,7; problemas distintos, ~0.
_UMBRAL_MISMO = 0.6
_VACIAS = set("""a al ante con de del desde el en entre la las lo los para por que se sin su sus un
una uno y o e es fue ya le les ha han ser esta este como mas no si al usuario""".split())


def _palabras(texto):
    t = re.sub(r"[^a-záéíóúñü0-9 ]", " ", (texto or "").lower())
    return {w for w in t.split() if len(w) > 2 and w not in _VACIAS}


def _parecido(nuevo, existente):
    """Qué parte de las palabras de contenido de `nuevo` ya están en `existente` (contención).
    No Jaccard: el artículo existente trae encabezados y la lista de casos, y esas palabras de más
    diluían el parecido hasta que tres casos idénticos salían como tres artículos. Sin IA."""
    pa, pb = _palabras(nuevo), _palabras(existente)
    return len(pa & pb) / len(pa) if pa and pb else 0.0


def _resolver_padre(docs, padre_cfg):
    """El documento bajo el que van los artículos del cliente (config `kb_outline.padre`: su título
    o su id). None si no está configurado o no existe."""
    p = str(padre_cfg or "").strip().lower()
    if not p:
        return None
    return next((d for d in docs if d["id"] == padre_cfg or (d.get("title") or "").strip().lower() == p),
                None)


MAX_CAPTURAS = 20                 # por artículo: un procedimiento real usa ~10
MAX_TOKENS = 5000                 # el artículo en JSON; entra en el límite por minuto de Groq free


def _entrada_soporte(ticket):
    """Lo que escribió soporte, en orden, con las capturas numeradas [CAPTURA n] para la IA.
    Devuelve (texto, {n: id del documento en GLPI})."""
    if not ticket.get("soporte"):                      # sin historial: sólo la solución
        return str(ticket.get("solucion") or ""), {}
    mapa, bloques = {}, []
    for e in ticket["soporte"]:
        def numerar(m):
            if len(mapa) >= MAX_CAPTURAS:
                return ""
            n = len(mapa) + 1
            mapa[n] = int(m.group(1))
            return f"[CAPTURA {n}]"
        txt = re.sub(r"\[\[img:(\d+)\]\]", numerar, e.get("texto") or "")
        bloques.append(f"[{e.get('tipo', '')} {str(e.get('fecha', ''))[:16]}]\n{txt}")
    return "\n\n".join(bloques), mapa


def _subir_capturas(cli, fuente, mapa, usadas, tid, doc_id):
    """Sube a la wiki, asociadas al artículo `doc_id`, las capturas que usa. Devuelve {n: url}.
    Una que no se pudo bajar o subir se saltea (el artículo sale igual, sin esa imagen)."""
    urls = {}
    for n in sorted(usadas):
        if n not in mapa or fuente is None:
            continue
        try:
            datos, tipo = fuente.imagen(mapa[n])
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}.get(tipo)
            if not ext:
                continue
            urls[n] = cli.subir_imagen(f"ticket{tid}_captura{n}.{ext}", datos, tipo, doc_id)
        except Exception as e:  # noqa: BLE001
            log.info("Wiki: la captura %s del ticket #%s no se pudo subir (%s).", n, tid, e)
    return urls


def publicar_ticket(cli, ia, ticket, cols=None, docs=None, padre_cfg=None, fuente=None):
    """Redacta y publica (o suma a un artículo existente) el procedimiento de UN ticket cerrado.
    Devuelve (estado, url): 'publicado' | 'agregado' | 'mejorado' | 'no_publicable' | 'sin_ia'.

    `ticket` trae, si se pudo leer, `soporte`: TODO lo que escribió soporte con las capturas en su
    lugar (adaptador.historial). Con eso el artículo es el paso a paso real, con las pantallas;
    sin eso, lo que diga la solución. `fuente` es el adaptador de tickets, para bajar las capturas.

    QUÉ CUENTA COMO "EL MISMO ARTÍCULO". Sólo los artículos que escribió ITHOS (llevan su marca):
    nunca se toca un documento del equipo. Y no se deja en manos de la IA sola: en el ensayo con
    tickets reales escribió tres artículos casi iguales para tres casos con el mismo procedimiento.
    Además de lo que diga la IA, se compara el contenido. Si el caso nuevo trae el procedimiento
    MÁS COMPLETO (más pasos, capturas), el artículo se reescribe con él y conserva sus casos: el
    primer ticket que llega no siempre es el mejor documentado."""
    cols = cols if cols is not None else cli.colecciones()
    docs = docs if docs is not None else cli.documentos()
    propios = [d for d in docs if MARCA_ITHOS in (d.get("text") or "")]
    lista_cols = "\n".join(f"- {c['name']}" for c in cols)
    lista_docs = "\n".join(f"- id={d['id']} · {d['coleccion']} · {d.get('title', '')}" for d in propios[:80])
    texto_soporte, mapa = _entrada_soporte(ticket)
    entrada = (f"COLECCIONES:\n{lista_cols}\n\nARTÍCULOS DE ITHOS:\n{lista_docs or '(ninguno)'}\n\n"
               f"TICKET #{ticket['id']}: {ticket.get('asunto', '')}\n{ticket.get('problema', '')}\n\n"
               f"LO QUE ESCRIBIÓ SOPORTE (en orden):\n{texto_soporte}")
    try:
        # Un paso a paso real con su detalle no entra en el tope corto que tiene el JSON del
        # agente en algunos proveedores (1.500-2.000 tokens): saldría cortado y sin cerrar.
        a = _json(ia.chat(_SISTEMA_REDACTOR, entrada, json_out=True, max_tokens=MAX_TOKENS))
    except Exception as e:  # noqa: BLE001
        log.info("Wiki: sin IA para el ticket #%s (%s); se reintenta después.", ticket["id"], e)
        return "sin_ia", ""
    if not a or a.get("publicable") is not True or not a.get("pasos"):
        return "no_publicable", ""
    a = _limpio(a, ticket)
    if not a["pasos"]:
        return "no_publicable", ""
    tid = ticket["id"]
    fecha = ticket.get("fecha_cierre") or datetime.now().strftime("%d/%m/%Y")
    categoria = ticket.get("categoria") or ""
    usadas = {n for p in a["pasos"] for n in p["capturas"]} | set(mapa)   # ninguna se pierde
    por_id = {d["id"]: d for d in propios}
    mismo = por_id.get(str(a.get("mismo_doc") or ""))
    if mismo is None and propios:
        nuevo = " ".join([a["titulo"], a["sintoma"]] + [f"{p['titulo']} {p['detalle']}" for p in a["pasos"]])
        mejor = max(propios, key=lambda d: _parecido(nuevo, f"{d.get('title', '')} {d.get('text', '')}"))
        if _parecido(nuevo, f"{mejor.get('title', '')} {mejor.get('text', '')}") >= _UMBRAL_MISMO:
            mismo = mejor
    if mismo:
        caso = _caso(tid, fecha, a["resumen"])
        previo = mismo.get("text") or ""
        if len(a["pasos"]) + 2 * len(mapa) > _riqueza(previo):
            urls = _subir_capturas(cli, fuente, mapa, usadas, tid, mismo["id"])
            partes = _RE_CASOS.split(previo, maxsplit=1)
            casos = partes[1].strip() if len(partes) > 1 else ""
            texto = f"{_cuerpo(a, urls, categoria)}\n\n{CASOS}\n\n{casos}\n{caso}".replace("\n\n\n", "\n\n")
            doc = cli.reemplazar(mismo["id"], texto)
            return "mejorado", cli.url_de(doc or mismo)
        doc = cli.agregar(mismo["id"], f"\n{caso}")
        return "agregado", cli.url_de(doc or mismo)
    col = next((c for c in cols if c["name"] == a.get("coleccion")), None) \
        or next((c for c in cols if _RE_SERVICE_DESK.search(c["name"])), None)
    if col is None:
        return "no_publicable", ""
    padre = _resolver_padre(docs, padre_cfg)
    padre_id = padre["id"] if padre and padre.get("collectionId") == col["id"] else None
    doc = cli.crear(col["id"], a["titulo"] or "Procedimiento", _articulo(a, tid, fecha, {}, categoria),
                    padre_id=padre_id)
    urls = _subir_capturas(cli, fuente, mapa, usadas, tid, doc.get("id")) if mapa and doc.get("id") else {}
    if urls:                                   # las capturas se suben asociadas al artículo ya creado
        doc = cli.reemplazar(doc["id"], _articulo(a, tid, fecha, urls, categoria)) or doc
    return "publicado", cli.url_de(doc)


def publicar_cerrados(conf, ia, cliente, avisar=None, por_vuelta=POR_VUELTA):
    """Una vuelta: toma los tickets CERRADOS que todavía no se procesaron y publica hasta
    `por_vuelta`. Lo hecho queda anotado por cliente, así un reinicio no vuelve a publicar nada."""
    from comun import tickets as T
    cli = OL.desde_config(conf)
    if cli is None or ia is None:
        return []
    st = E.cargar(_PREFIJO, cliente)
    hechos = st.setdefault("hechos", {})
    fuente = T.adaptador(conf)
    pendientes = [t for t in fuente.resueltos(80)
                  if str(t.get("estado")) == "6" and str(t["id"]) not in hechos]
    if not pendientes:
        return []
    cols, docs = cli.colecciones(), cli.documentos()
    salida = []
    padre_cfg = (conf.get("kb_outline") or {}).get("padre")
    for t in pendientes[:por_vuelta]:
        if hasattr(fuente, "historial"):           # el paso a paso real, con sus capturas
            try:
                t = {**t, **fuente.historial(t["id"])}
            except Exception as e:  # noqa: BLE001
                log.info("Wiki: no pude leer el historial del ticket #%s (%s); va con la solución.", t["id"], e)
        estado, url = publicar_ticket(cli, ia, t, cols, docs, padre_cfg=padre_cfg, fuente=fuente)
        if estado == "sin_ia":
            break                                  # la IA no está: se sigue en la próxima vuelta
        hechos[str(t["id"])] = estado
        salida.append((t["id"], estado, url))
        if estado in ("publicado", "mejorado"):
            docs = cli.documentos()                # el nuevo cuenta para no duplicar el siguiente
            log.info("Wiki: procedimiento del ticket #%s %s: %s", t["id"], estado, url)
            if avisar:
                que = "Nuevo procedimiento" if estado == "publicado" else "Procedimiento mejorado"
                try:
                    avisar(f"📚 {que} en la wiki (ticket #{t['id']}): {url}")
                except Exception:  # noqa: BLE001
                    pass
        elif estado == "agregado":
            log.info("Wiki: el ticket #%s se sumó a un artículo existente: %s", t["id"], url)
    E.guardar(_PREFIJO, cliente, st)
    return salida


async def vigilar(conf, ia, avisar=None, stop=None):
    """La tarea de fondo del cliente: cada media hora publica unos pocos tickets cerrados, y cada
    seis horas vuelve a leer la wiki para la KB."""
    cliente = conf.get("nombre", "cliente")
    if OL.desde_config(conf) is None:
        return
    log.info("Wiki (Outline) conectada para %s: lee la wiki y publica los procedimientos.", cliente)
    ultima_import = 0.0
    import time
    while stop is None or not stop.is_set():
        try:
            if time.time() - ultima_import > IMPORTAR_CADA_SEG:
                n, total = await asyncio.to_thread(importar, conf, cliente)
                ultima_import = time.time()
                log.info("Wiki: %d de %d documentos en la base de conocimiento de %s.", n, total, cliente)
            hechos = await asyncio.to_thread(publicar_cerrados, conf, ia, cliente, avisar)
            if any(e in ("publicado", "mejorado") for _, e, _ in hechos):
                await asyncio.to_thread(importar, conf, cliente)
        except Exception as e:  # noqa: BLE001
            log.warning("Wiki %s: %s", cliente, e)
        await asyncio.sleep(CADA_SEG)
