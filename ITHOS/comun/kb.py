#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base de conocimiento por cliente. Carga documentos de texto de una carpeta y, dada
una consulta, devuelve los fragmentos más relevantes para inyectar como contexto en
los prompts de la IA (RAG liviano por coincidencia de palabras; sin embeddings).
Config: {"kb_dir": "kb/NOMBRE_CLIENTE"}.
"""

import os
import re
import glob


def _trozos(texto, largo=800):
    parrafos = re.split(r"\n\s*\n", texto)
    trozos, actual = [], ""
    for p in parrafos:
        if len(actual) + len(p) < largo:
            actual += "\n" + p
        else:
            if actual.strip():
                trozos.append(actual.strip())
            actual = p
    if actual.strip():
        trozos.append(actual.strip())
    return trozos


def cargar(kb_dir):
    docs = []
    for ruta in glob.glob(os.path.join(kb_dir, "**", "*.txt"), recursive=True) + \
            glob.glob(os.path.join(kb_dir, "**", "*.md"), recursive=True):
        try:
            with open(ruta, encoding="utf-8") as f:
                docs.extend(_trozos(f.read()))
        except Exception:  # noqa: BLE001
            pass
    return docs


def buscar(kb_dir, consulta, k=3):
    """Devuelve los k fragmentos más relevantes (por palabras en común)."""
    docs = cargar(kb_dir)
    if not docs:
        return []
    palabras = set(re.findall(r"\w+", consulta.lower()))
    puntuados = []
    for d in docs:
        dp = set(re.findall(r"\w+", d.lower()))
        puntuados.append((len(palabras & dp), d))
    puntuados.sort(reverse=True, key=lambda x: x[0])
    return [d for score, d in puntuados[:k] if score > 0]


def contexto(kb_dir, consulta, k=3):
    frags = buscar(kb_dir, consulta, k)
    if not frags:
        return ""
    return "CONTEXTO (base de conocimiento del cliente):\n" + "\n---\n".join(frags)
