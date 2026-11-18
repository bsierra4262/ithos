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
import time
import urllib.error
import urllib.request
import uuid

log = logging.getLogger("outline")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ITHOS"
# Nombres que marcan una colección o un documento como SENSIBLE (nunca se lee ni se escribe).
_RE_SENSIBLE = re.compile(r"sensitive|sensible|credencial|credential|vault|secret|password|contraseñ",
                          re.I)


_REINTENTOS_429 = 5


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
    def _post(self, metodo, datos=None, _intento=0):
        req = urllib.request.Request(
            f"{self.base}/api/{metodo}", method="POST", data=json.dumps(datos or {}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            # Outline limita algunas operaciones por minuto (subir imágenes: un artículo con diez
            # capturas lo alcanza). Se espera lo que pide y se reintenta; cortar dejaría el
            # artículo a medio armar.
            if e.code == 429 and _intento < _REINTENTOS_429:
                try:
                    espera = float(e.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    espera = 0
                time.sleep(min(max(espera, 15 * (_intento + 1)), 90))
                return self._post(metodo, datos, _intento + 1)
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

    def reemplazar(self, doc_id, texto):
        """Reescribe el texto entero de un documento. Quien llama se asegura de que sea uno que
        escribió ITHOS: los del equipo sólo reciben texto al final (`agregar`)."""
        actual = (self._post("documents.info", {"id": doc_id}) or {}).get("data") or {}
        if self.es_sensible(actual.get("title")):
            raise OutlineError("documento sensible: no se modifica")
        return (self._post("documents.update", {"id": doc_id, "text": texto, "publish": True})
                or {}).get("data") or {}

    def subir_imagen(self, nombre, datos, tipo, doc_id):
        """Sube una imagen al almacenamiento de la wiki y devuelve la URL para el markdown.

        Va SIEMPRE asociada a su documento: una imagen suelta la ve sólo quien la subió, y el
        equipo vería el artículo con las capturas rotas.

        Son dos pasos: `attachments.create` reserva el archivo y devuelve adónde y con qué campos
        subirlo; después va el archivo en un formulario multipart. Con el almacenamiento local de
        Outline ese destino es la propia API (lleva el token); con S3 es una URL firmada (no)."""
        r = (self._post("attachments.create", {"name": nombre, "contentType": tipo, "size": len(datos),
                                               "preset": "documentAttachment", "documentId": doc_id})
             or {}).get("data") or {}
        destino, adjunto = r.get("uploadUrl") or "", r.get("attachment") or {}
        if not destino or not adjunto.get("url"):
            raise OutlineError("attachments.create no devolvió adónde subir la imagen")
        propio = destino.startswith("/")
        destino = self.base + destino if propio else destino
        frontera = "----ithos" + uuid.uuid4().hex
        partes = []
        for k, v in (r.get("form") or {}).items():
            partes.append(f'--{frontera}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        partes.append(f'--{frontera}\r\nContent-Disposition: form-data; name="file"; filename="{nombre}"\r\n'
                      f"Content-Type: {tipo}\r\n\r\n".encode() + datos + b"\r\n")
        partes.append(f"--{frontera}--\r\n".encode())
        cab = {"Content-Type": f"multipart/form-data; boundary={frontera}", "User-Agent": _UA}
        if propio:
            cab["Authorization"] = f"Bearer {self.token}"
        cuerpo = b"".join(partes)
        for intento in range(_REINTENTOS_429 + 1):
            req = urllib.request.Request(destino, method="POST", data=cuerpo, headers=cab)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp.read()
                return adjunto["url"]
            except urllib.error.HTTPError as e:
                if e.code == 429 and intento < _REINTENTOS_429:      # mismo límite por minuto
                    time.sleep(min(15 * (intento + 1), 90))
                    continue
                raise OutlineError(f"subir imagen: HTTP {e.code} {e.read().decode(errors='replace')[:200]}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise OutlineError(f"subir imagen: {e}") from e
        return adjunto["url"]

    def url_de(self, doc):
        u = (doc or {}).get("url") or ""
        return self.base + u if u.startswith("/") else u


def desde_config(conf):
    """El cliente de Outline de esta empresa, o None si no tiene la wiki configurada."""
    ol = (conf or {}).get("kb_outline") or {}
    if not ol.get("url") or not ol.get("token"):
        return None
    return Outline(ol["url"], ol["token"], excluir=ol.get("excluir"))
