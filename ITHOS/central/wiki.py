#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
La WIKI del equipo (Outline) conectada a ITHOS, en los dos sentidos.

LEER. La wiki entra en la base de conocimiento del cliente: cada documento de las colecciones
permitidas se guarda en `instructivos/` y la KB lo combina con lo aprendido de los tickets. Es una
SINCRONIZACIÓN: lo que se borra o se mueve a una colección sensible en la wiki, sale de la KB.

ESCRIBIR. Cuando un ticket se CIERRA y lo que escribió el técnico explica cómo se resolvió, ITHOS
redacta el procedimiento y lo publica en la colección que corresponde por el tema. Al cierre y no
al resolverse: si el cliente después dice que sigue fallando, el procedimiento estaba mal, y eso no
puede quedar escrito en la wiki como la forma de resolverlo. Si ya hay un artículo sobre el MISMO
problema, no se duplica: se le suma el caso. Así la wiki crece con cada ticket y la KB con ella.

TRES REGLAS que no se negocian:
  · Nada sensible: las colecciones de credenciales no se leen ni se escriben (comun/outline.py).
  · Nada inventado: el artículo dice SÓLO lo que dicen el ticket y el técnico.
  · Nada personal: ni el nombre ni el legajo de la persona afectada; el artículo describe el caso.

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
    "(el problema) y lo que escribió el técnico (cómo lo resolvió). Armá un artículo de procedimiento "
    "para la wiki del equipo.\n"
    "REGLAS: escribí SÓLO lo que dicen el ticket y el técnico; no inventes pasos, comandos, menús, "
    "causas, verificaciones ni nombres de sistemas. 'causa' y 'verificacion' van SÓLO si el técnico "
    "las dice; si no, null. NO pongas datos personales de la persona afectada (ni nombre, ni legajo, "
    "ni DNI): describí el caso en general ('un empleado no puede fichar'). El título nombra el "
    "PROBLEMA y su solución en general, no el caso. Español rioplatense, impersonal y claro, para "
    "otro técnico.\n"
    "Elegí la COLECCIÓN (una de la lista, por el tema). Si uno de los ARTÍCULOS DE ITHOS existentes "
    "trata el mismo problema con el mismo procedimiento, poné su id en 'mismo_doc': se le suma este "
    "caso en vez de crear otro.\n"
    "publicable=false si el texto del técnico NO explica cómo se resolvió (sólo dice 'listo', "
    "'solucionado', 'ya funciona'); ante la duda, false.\n"
    "Respondé SOLO JSON: {\"publicable\": true|false, \"titulo\": \"...\", \"coleccion\": \"<nombre "
    "exacto>\", \"mismo_doc\": \"<id o null>\", \"sintoma\": \"...\", "
    "\"causa\": \"<o null>\", \"pasos\": [\"...\"], \"verificacion\": \"<o null>\", "
    "\"resumen\": \"<una línea: qué se hizo>\"}")


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


def _sin_datos_personales(texto, ticket):
    """Saca del texto el nombre y los números de la persona afectada que trae el ticket. La IA
    tiene la orden de no ponerlos; esto es la red por si igual se le escapa uno."""
    asunto = f"{ticket.get('asunto', '')} {ticket.get('problema', '')}"
    numeros = set(re.findall(r"\b\d{4,}\b", asunto))
    # El nombre de la persona viene en el asunto DESPUÉS del legajo ("Legajo 13722 Berretta Silvia").
    # Sólo esas palabras: una sede o un equipo con mayúscula ("terminal Sarmiento") no es un dato
    # personal y borrarlo dejaría el artículo sin sentido.
    m = re.search(r"\b\d{4,}\b\s*[-–:,]?\s*(.+)$", ticket.get("asunto", ""))
    nombres = set(re.findall(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}\b", m.group(1))) if m else set()
    for n in numeros:
        texto = re.sub(rf"\b{re.escape(n)}\b", "[legajo]", texto)
    for w in nombres:
        texto = re.sub(rf"\b{re.escape(w)}\b", "[persona]", texto)
    return texto


def _articulo(a, tid, fecha):
    partes = [f"## Síntoma\n\n{a.get('sintoma', '').strip()}"]
    if a.get("causa"):
        partes.append(f"## Causa\n\n{str(a['causa']).strip()}")
    pasos = [str(p).strip() for p in (a.get("pasos") or []) if str(p).strip()]
    partes.append("## Procedimiento\n\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(pasos, 1)))
    if a.get("verificacion"):
        partes.append(f"## Cómo verificar\n\n{str(a['verificacion']).strip()}")
    partes.append(f"_{MARCA_ITHOS}. Cada caso nuevo del mismo problema se suma abajo._")
    partes.append(f"## Casos\n\n- Ticket #{tid} ({fecha}): {str(a.get('resumen') or '').strip()}")
    return "\n\n".join(partes)


MARCA_ITHOS = "Redactado por ITHOS a partir de los tickets cerrados"
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


def publicar_ticket(cli, ia, ticket, cols=None, docs=None, padre_cfg=None):
    """Redacta y publica (o suma a un artículo existente) el procedimiento de UN ticket cerrado.
    Devuelve (estado, url): 'publicado' | 'agregado' | 'no_publicable' | 'sin_ia'.

    QUÉ CUENTA COMO "EL MISMO ARTÍCULO". Sólo los artículos que escribió ITHOS (llevan su marca):
    nunca se le suma un caso a un documento del equipo. Y no se deja en manos de la IA sola: en el
    ensayo con tickets reales escribió tres artículos casi iguales para tres casos con el mismo
    procedimiento. Además de lo que diga la IA, se compara el contenido."""
    cols = cols if cols is not None else cli.colecciones()
    docs = docs if docs is not None else cli.documentos()
    propios = [d for d in docs if MARCA_ITHOS in (d.get("text") or "")]
    lista_cols = "\n".join(f"- {c['name']}" for c in cols)
    lista_docs = "\n".join(f"- id={d['id']} · {d['coleccion']} · {d.get('title', '')}" for d in propios[:80])
    entrada = (f"COLECCIONES:\n{lista_cols}\n\nARTÍCULOS DE ITHOS:\n{lista_docs or '(ninguno)'}\n\n"
               f"TICKET #{ticket['id']}: {ticket.get('asunto', '')}\n{ticket.get('problema', '')}\n\n"
               f"LO QUE ESCRIBIÓ EL TÉCNICO:\n{ticket.get('solucion', '')}")
    try:
        a = _json(ia.chat(_SISTEMA_REDACTOR, entrada, json_out=True))
    except Exception as e:  # noqa: BLE001
        log.info("Wiki: sin IA para el ticket #%s (%s); se reintenta después.", ticket["id"], e)
        return "sin_ia", ""
    if not a or a.get("publicable") is not True or not a.get("pasos"):
        return "no_publicable", ""
    fecha = ticket.get("fecha_cierre") or datetime.now().strftime("%d/%m/%Y")
    por_id = {d["id"]: d for d in propios}
    mismo = por_id.get(str(a.get("mismo_doc") or ""))
    if mismo is None and propios:
        nuevo = " ".join([str(a.get("titulo") or ""), str(a.get("sintoma") or "")]
                         + [str(p) for p in a.get("pasos") or []])
        mejor = max(propios, key=lambda d: _parecido(nuevo, f"{d.get('title', '')} {d.get('text', '')}"))
        if _parecido(nuevo, f"{mejor.get('title', '')} {mejor.get('text', '')}") >= _UMBRAL_MISMO:
            mismo = mejor
    if mismo:
        resumen = _sin_datos_personales(str(a.get("resumen") or a.get("sintoma") or ""), ticket)
        doc = cli.agregar(mismo["id"], f"\n- Ticket #{ticket['id']} ({fecha}): {resumen}")
        return "agregado", cli.url_de(doc or mismo)
    col = next((c for c in cols if c["name"] == a.get("coleccion")), None) \
        or next((c for c in cols if _RE_SERVICE_DESK.search(c["name"])), None)
    if col is None:
        return "no_publicable", ""
    padre = _resolver_padre(docs, padre_cfg)
    padre_id = padre["id"] if padre and padre.get("collectionId") == col["id"] else None
    titulo = _sin_datos_personales(str(a.get("titulo") or "").strip(), ticket) or "Procedimiento"
    texto = _sin_datos_personales(_articulo(a, ticket["id"], fecha), ticket)
    doc = cli.crear(col["id"], titulo, texto, padre_id=padre_id)
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
    pendientes = [t for t in T.adaptador(conf).resueltos(80)
                  if str(t.get("estado")) == "6" and str(t["id"]) not in hechos]
    if not pendientes:
        return []
    cols, docs = cli.colecciones(), cli.documentos()
    salida = []
    padre_cfg = (conf.get("kb_outline") or {}).get("padre")
    for t in pendientes[:por_vuelta]:
        estado, url = publicar_ticket(cli, ia, t, cols, docs, padre_cfg=padre_cfg)
        if estado == "sin_ia":
            break                                  # la IA no está: se sigue en la próxima vuelta
        hechos[str(t["id"])] = estado
        salida.append((t["id"], estado, url))
        if estado == "publicado":
            docs = cli.documentos()                # el nuevo cuenta para no duplicar el siguiente
            log.info("Wiki: procedimiento del ticket #%s publicado: %s", t["id"], url)
            if avisar:
                try:
                    avisar(f"📚 Nuevo procedimiento en la wiki (ticket #{t['id']}): {url}")
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
            if any(e == "publicado" for _, e, _ in hechos):
                await asyncio.to_thread(importar, conf, cliente)
        except Exception as e:  # noqa: BLE001
            log.warning("Wiki %s: %s", cliente, e)
        await asyncio.sleep(CADA_SEG)
