#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente de OUTLINE, la wiki del equipo (https://www.getoutline.com/developers).

Toda la API es `POST /api/<método>` con `Authorization: Bearer <api key>`. ITHOS la usa para dos
cosas: LEER la wiki (alimenta su base de conocimiento) y ESCRIBIR los procedimientos que salen de
los tickets cerrados.

LO SENSIBLE NO SE TOCA. Una colección cuyo nombre habla de credenciales o secretos ("Core IT -
Sensitive & Credentials", los "Vault") no se lee ni se escribe nunca: lo que ITHOS lee termina en su
base de conocimiento y de ahí en una respuesta por WhatsApp. Lo mismo un documento con "vault" en el
título aunque esté en otra colección. La lista se puede ampliar por cliente (`excluir`).

User-Agent de navegador: la wiki está detrás de Cloudflare, que rechaza el de Python (error 1010).
"""

import json
import logging
import re
import urllib.error
import urllib.request

log = logging.getLogger("outline")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ITHOS"
# Nombres que marcan una colección o un documento como SENSIBLE (nunca se lee ni se escribe).
_RE_SENSIBLE = re.compile(r"sensitive|sensible|credencial|credential|vault|secret|password|contraseñ",
                          re.I)


class OutlineError(Exception):
    pass


class Outline:
    def __init__(self, url, token, excluir=None, timeout=60):
        base = (url or "").strip().rstrip("/")
        base = re.sub(r"/(home|api)$", "", base)          # aceptan la URL de la portada o la de la API
        self.base = base
        self.token = (token or "").strip()
        self.excluir = {str(x).strip().lower() for x in (excluir or []) if str(x).strip()}
        self.timeout = timeout

    # ------------------------------------------------------------------ transporte
    def _post(self, metodo, datos=None):
        req = urllib.request.Request(
            f"{self.base}/api/{metodo}", method="POST", data=json.dumps(datos or {}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise OutlineError(f"{metodo}: HTTP {e.code} {e.read().decode(errors='replace')[:200]}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise OutlineError(f"{metodo}: {e}") from e

    def _todos(self, metodo, datos=None):
        """Recorre todas las páginas (la API devuelve de a 100 como máximo)."""
        out, off = [], 0
        while True:
            lote = (self._post(metodo, {**(datos or {}), "offset": off, "limit": 100}) or {}).get("data") or []
            out += lote
            if len(lote) < 100:
                return out
            off += 100

    # ------------------------------------------------------------------ qué se puede tocar
    def es_sensible(self, nombre):
        n = (nombre or "").strip()
        return bool(_RE_SENSIBLE.search(n)) or n.lower() in self.excluir

    def colecciones(self):
        """Las colecciones que ITHOS puede leer y escribir (sin las sensibles)."""
        return [c for c in self._todos("collections.list") if not self.es_sensible(c.get("name"))]

    def documentos(self):
        """Todos los documentos publicados de las colecciones permitidas, con su colección."""
        cols = {c["id"]: c["name"] for c in self.colecciones()}
        out = []
        for d in self._todos("documents.list"):
            col = cols.get(d.get("collectionId"))
            if col is None or self.es_sensible(d.get("title")):
                continue
            out.append({**d, "coleccion": col})
        return out

    # ------------------------------------------------------------------ escritura
    def crear(self, coleccion_id, titulo, texto, padre_id=None, publicar=True):
        if coleccion_id not in {c["id"] for c in self.colecciones()}:
            raise OutlineError("colección no permitida (sensible o inexistente)")
        datos = {"collectionId": coleccion_id, "title": titulo[:100], "text": texto,
                 "publish": bool(publicar)}
        if padre_id:
            datos["parentDocumentId"] = padre_id
        return (self._post("documents.create", datos) or {}).get("data") or {}

    def agregar(self, doc_id, texto):
        """Suma texto AL FINAL de un documento existente (no pisa lo que escribió el equipo)."""
        actual = (self._post("documents.info", {"id": doc_id}) or {}).get("data") or {}
        if self.es_sensible(actual.get("title")):
            raise OutlineError("documento sensible: no se modifica")
        return (self._post("documents.update", {"id": doc_id, "text": texto, "append": True,
                                                "publish": True}) or {}).get("data") or {}

    def url_de(self, doc):
        u = (doc or {}).get("url") or ""
        return self.base + u if u.startswith("/") else u


def desde_config(conf):
    """El cliente de Outline de esta empresa, o None si no tiene la wiki configurada."""
    ol = (conf or {}).get("kb_outline") or {}
    if not ol.get("url") or not ol.get("token"):
        return None
    return Outline(ol["url"], ol["token"], excluir=ol.get("excluir"))
