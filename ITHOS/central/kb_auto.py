#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base de conocimiento AUTOMÁTICA por cliente. ITHOS lee los casos RESUELTOS del sistema
de tickets del cliente (problema + solución) y arma una base que después usa para
responder casos parecidos. Funciona con CUALQUIER sistema (GLPI, Zendesk, Jira,
Freshservice, osTicket…) porque habla con el adaptador genérico comun/tickets.py.
Cada empresa tiene su propia KB, AISLADA (una nunca ve la de otra).

Hoy muchos tickets no explican cómo se resolvieron: se toma la SOLUCIÓN o, si no hay,
el último seguimiento del técnico. Cuando se sumen instructivos (.md en la carpeta de
KB del cliente), se combinan automáticamente con lo que se sacó de los tickets.

La KB vive en la carpeta ESTABLE del usuario: ~/.ithos/kb_<cliente>/  (portable).
"""

import os
import re
import sys
import time
import html
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DATA = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")


def kb_dir(cliente):
    seguro = "".join(ch if ch.isalnum() else "_" for ch in (cliente or "cliente"))
    d = os.path.join(DATA, f"kb_{seguro}")
    os.makedirs(d, exist_ok=True)
    return d


def _limpiar(texto):
    t = html.unescape(texto or "")                    # &#60;p&#62; -> <p>, &amp; -> & ...
    t = re.sub(r"<[^>]+>", " ", t)                     # sacar HTML del texto enriquecido
    t = html.unescape(t)                              # por si quedaron entidades anidadas
    return re.sub(r"\s+", " ", t).strip()[:1500]


def generar(cli_cfg, cliente, n=80):
    """Lee casos resueltos del sistema de tickets del cliente y arma la KB
    (Problema + Solución). Devuelve cuántos casos con solución encontró."""
    from comun import tickets as T
    adap = T.adaptador(cli_cfg)
    tipo = ((cli_cfg.get("tickets") or {}).get("tipo")) or "glpi"
    casos = []
    for c in adap.resueltos(n):
        sol = _limpiar(c.get("solucion", ""))
        if not sol:
            continue
        casos.append(f"## Caso #{c.get('id')}: {c.get('asunto', '')}\n"
                     f"**Problema:** {_limpiar(c.get('problema', ''))}\n"
                     f"**Solución:** {sol}\n")
    ruta = os.path.join(kb_dir(cliente), "casos_resueltos.md")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(f"# Casos resueltos ({tipo}) — {cliente}\n\n" + "\n".join(casos))
    return len(casos)


def refrescar_async(cli_cfg, cliente, horas=2, forzar=False):
    """Regenera la KB en segundo plano si falta, está vieja (>horas) o se fuerza (p. ej. tras
    resolver/cerrar un ticket). No bloquea. Umbral bajo (2h) para que siempre esté fresca."""
    ruta = os.path.join(kb_dir(cliente), "casos_resueltos.md")
    try:
        if not forzar and os.path.exists(ruta) and (time.time() - os.path.getmtime(ruta)) < horas * 3600:
            return
    except Exception:  # noqa: BLE001
        pass

    def _tarea():
        try:
            generar(cli_cfg, cliente)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_tarea, name="kb-auto", daemon=True).start()


# ------------------------------------------------------------- subida de instructivos
def _texto_de(nombre, datos):
    """Extrae texto plano de un archivo subido (PDF, TXT, MD, CSV, DOCX). '' si no se puede."""
    import io
    ext = os.path.splitext(nombre or "")[1].lower()
    try:
        if ext == ".pdf":
            import pypdf
            r = pypdf.PdfReader(io.BytesIO(datos))
            return "\n".join((p.extract_text() or "") for p in r.pages)
        if ext in (".txt", ".md", ".csv", ".log"):
            return datos.decode("utf-8", "ignore")
        if ext == ".docx":
            import zipfile
            with zipfile.ZipFile(io.BytesIO(datos)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            return re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))
    except Exception:  # noqa: BLE001
        return ""
    return ""


def subir_archivos(cliente, archivos):
    """Sube VARIOS archivos a la KB del cliente de una (instructivos/manuales). archivos:
    lista de (nombre, bytes). Extrae el texto y lo guarda como .md en kb_<cliente>/instructivos/;
    la KB los combina solos con los casos resueltos. Devuelve (cargados, total)."""
    d = os.path.join(kb_dir(cliente), "instructivos")
    os.makedirs(d, exist_ok=True)
    n = 0
    for nombre, datos in archivos:
        txt = _limpiar_doc(_texto_de(nombre, datos))
        if not txt.strip():
            continue
        seguro = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in (nombre or "doc"))
        base = os.path.splitext(seguro)[0] or f"doc_{int(time.time())}"
        with open(os.path.join(d, base + ".md"), "w", encoding="utf-8") as f:
            f.write(f"# Instructivo: {nombre}\n\n{txt.strip()}")
        n += 1
    return n, len(archivos)


def importar_outline(cliente, base_url, api_token, limit=100):
    """Trae documentos de OUTLINE (wiki/base de conocimiento OPEN-SOURCE) a la KB del cliente.
    API oficial: POST {base}/api/documents.list con Authorization Bearer -> data:[{title,text}].
    Guarda cada doc como .md en instructivos/ (la KB los combina solos con los casos resueltos).
    Devuelve (traidos, total). Aislado por cliente. Requiere URL de la instancia + API token."""
    import json
    import urllib.request
    base = (base_url or "").rstrip("/")
    d = os.path.join(kb_dir(cliente), "instructivos")
    os.makedirs(d, exist_ok=True)
    req = urllib.request.Request(
        base + "/api/documents.list",
        data=json.dumps({"limit": max(1, min(int(limit), 100))}).encode(),
        headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        docs = (json.load(r) or {}).get("data", []) or []
    traidos = 0
    for doc in docs:
        titulo = (doc.get("title") or "documento").strip()
        texto = _limpiar_doc(doc.get("text") or "")
        if not texto.strip():
            continue
        seguro = ("".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in titulo)[:60]
                  or "outline")
        with open(os.path.join(d, "outline_" + seguro + ".md"), "w", encoding="utf-8") as f:
            f.write(f"# {titulo}\n\n{texto.strip()}")
        traidos += 1
    return traidos, len(docs)


def _limpiar_doc(t):
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t or "")).strip()


def listar_instructivos(cliente):
    d = os.path.join(kb_dir(cliente), "instructivos")
    try:
        return sorted(os.path.splitext(f)[0] for f in os.listdir(d) if f.endswith(".md"))
    except Exception:  # noqa: BLE001
        return []


# ------------------------------------------------------------------ auto-regeneración semanal
def _escribir_atomico(ruta, datos):
    """Escribe JSON sin dejarlo a medias: a un temporal y recién ahí se renombra.

    Escribir directo sobre el archivo lo TRUNCA antes de empezar: si el proceso muere en el
    medio —un deploy, un reinicio— queda cortado, y como todas las lecturas tienen un `except` que
    devuelve vacío, el archivo roto se lee como "no hay nada" y el estado se pierde EN SILENCIO."""
    import json as _j
    import os as _o
    tmp = str(ruta) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            _j.dump(datos, f, ensure_ascii=False)
        _o.replace(tmp, ruta)
    except OSError:
        try:
            _o.remove(tmp)
        except OSError:
            pass
        raise


def _auto_estado_path(cliente):
    return os.path.join(kb_dir(cliente), "_auto_estado.json")


def _auto_cargar(cliente):
    import json
    try:
        return json.load(open(_auto_estado_path(cliente), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _auto_guardar(cliente, st):
    import json
    try:
        _escribir_atomico(_auto_estado_path(cliente), st)
    except Exception:  # noqa: BLE001
        pass


async def vigilar(conf, stop=None):
    """Regenera la BASE DE CONOCIMIENTO SOLA, una vez por SEMANA (después de la semana laboral), sin
    que el cliente tenga que apretar ningún botón. Aprende de los tickets RESUELTOS e IMPORTA la wiki
    de Outline si está configurada. ON por defecto (se apaga con conf['kb']['auto']=false). Por
    cliente, aislado, en el central. Config: conf['kb'] = {auto, dia_semana (0=lun..6=dom), hora}."""
    import asyncio
    import logging
    from datetime import datetime
    log = logging.getLogger("kb-auto")
    kb = conf.get("kb") or {}
    if kb.get("auto") is False:
        return
    gl = conf.get("integrador_glpi") or {}
    tk = conf.get("tickets") or {}
    if not gl.get("glpi_url") and (tk.get("tipo") in (None, "", "ninguno")):
        return                                  # sin sistema de tickets no hay de qué aprender solo
    cliente = conf.get("nombre", "cliente")
    ol = conf.get("kb_outline") or {}
    try:
        dia = int(kb.get("dia_semana", 5))      # 5 = sábado (después de lun–vie)
    except (TypeError, ValueError):
        dia = 5
    try:
        hh, mm = [int(x) for x in str(kb.get("hora", "03:00")).split(":")[:2]]
    except Exception:  # noqa: BLE001
        hh, mm = 3, 0
    log.info("KB auto-regeneración SEMANAL activa para %s (día %s a las %02d:%02d).",
             cliente, dia, hh, mm)
    while stop is None or not stop.is_set():
        try:
            ahora = datetime.now()
            if ahora.weekday() == dia and ahora.hour == hh and ahora.minute == mm:
                clave = "S" + ahora.strftime("%Y-%W")     # una vez por semana ISO
                st = _auto_cargar(cliente)
                if st.get("ultima") != clave:
                    n = await asyncio.to_thread(generar, conf, cliente)
                    if ol.get("url") and ol.get("token"):
                        try:
                            await asyncio.to_thread(importar_outline, cliente,
                                                    ol["url"], ol["token"])
                        except Exception:  # noqa: BLE001
                            pass
                    st["ultima"] = clave
                    _auto_guardar(cliente, st)
                    log.info("KB regenerada SOLA para %s: %s casos (semana %s).", cliente, n, clave)
        except Exception as e:  # noqa: BLE001
            log.warning("KB auto %s: %s", cliente, e)
        await asyncio.sleep(30)
