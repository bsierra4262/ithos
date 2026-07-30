#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Acceso al PROPIO CÓDIGO del proyecto, para que ITHOS pueda responder con MÁXIMO detalle
sobre su implementación: sabe qué archivos tiene, qué hace cada uno, y puede LEER el código
fuente real de cualquier archivo para explicarlo función por función. Como lee los archivos
en el momento, SIEMPRE está al día (no hay que documentar a mano cada cambio).

Uso (lo usa comun/conversacion.py en el modo admin/técnico):
  indice()            -> lista de todos los .py con una descripción (del docstring)
  detectar_archivo(t) -> nombre de archivo mencionado en la pregunta (o None)
  leer(nombre)        -> (ruta_relativa, código fuente) del archivo pedido
"""

import os
import re
import glob

_ALIAS = {
    "demo": "iniciar_demo.py", "la demo": "iniciar_demo.py",
    "el asistente": "comun/conversacion.py", "conversacion": "comun/conversacion.py",
    "la ia": "comun/ia.py", "la voz": "comun/locucion.py",
    "el central": "central/main.py", "el panel": "central/panel.py",
    "tickets": "comun/tickets.py", "acceso": "comun/acceso.py",
    "whatsapp": "comun/whatsapp.py", "canales": "comun/canales.py",
    "vincular whatsapp": "comun/whatsapp_link.py", "qr whatsapp": "comun/whatsapp_link.py",
    "conocimiento": "comun/conocimiento.py", "voz id": "comun/vozid.py",
    "wake word": "comun/wake.py", "palabra clave": "comun/wake.py",
    "audio": "comun/audio.py", "facturacion": "comun/facturacion.py",
}


def raiz():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _archivos():
    root = raiz()
    out = []
    for ruta in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        if "__pycache__" in ruta or os.path.getsize(ruta) == 0:
            continue
        rel = os.path.relpath(ruta, root).replace("\\", "/")
        out.append((rel, ruta))
    return sorted(out)


def _docstring(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            src = f.read(4000)
        m = re.search(r'"""(.*?)"""', src, re.S)
        if m:
            for linea in m.group(1).strip().splitlines():
                if linea.strip():
                    return linea.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def indice():
    """Índice de TODO el proyecto: cada archivo con una línea de qué hace."""
    return "\n".join(f"- {rel}: {_docstring(ruta)}" for rel, ruta in _archivos())


def detectar_archivo(texto):
    """Devuelve el archivo mencionado en la pregunta (nombre.py, módulo o alias), o None."""
    t = (texto or "").lower()
    m = re.search(r"\b([\w./-]+\.py)\b", t)          # mención explícita de un .py
    if m:
        return m.group(1)
    for alias, arch in _ALIAS.items():               # alias comunes ('la demo', 'el panel'…)
        if re.search(r"\b" + re.escape(alias) + r"\b", t):
            return arch
    for rel, _ in _archivos():                        # nombre de módulo sin extensión
        base = os.path.basename(rel)[:-3]
        if len(base) >= 4 and re.search(r"\b" + re.escape(base) + r"\b", t):
            return rel
    return None


def leer(nombre, max_chars=16000):
    """Devuelve (ruta_relativa, código) del archivo que mejor matchee, o None."""
    if not nombre:
        return None
    n = os.path.basename(str(nombre)).lower().replace(".py", "")
    archs = _archivos()
    cand = None
    for rel, ruta in archs:                           # match exacto por nombre de archivo
        if os.path.basename(rel)[:-3].lower() == n:
            cand = (rel, ruta)
            break
    if not cand:                                      # match parcial
        for rel, ruta in archs:
            if n in rel.lower():
                cand = (rel, ruta)
                break
    if not cand:
        return None
    rel, ruta = cand
    try:
        with open(ruta, encoding="utf-8") as f:
            src = f.read()
    except Exception:  # noqa: BLE001
        return None
    if len(src) > max_chars:
        src = src[:max_chars] + "\n… (archivo recortado por longitud) …"
    return rel, src
