#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESTADO persistente de las tareas de fondo (anti-spam de avisos, último reporte enviado, etc.).

Existe para que haya UN solo lugar donde se guarda eso, y para arreglar dos cosas que estaban
repetidas en cada tarea:

  · **Dónde**. Varias guardaban al lado de su propio `.py`, que en el servidor vive DENTRO de la
    imagen del contenedor. Cada actualización reconstruye la imagen, así que el estado se perdía
    en cada deploy: el aviso de SLA que ya se había mandado volvía a salir y el reporte del día
    se reenviaba. Ahora todo va al volumen (`ITHOS_DATA`), que es lo único que sobrevive.

  · **Cómo**. Se escribía directo sobre el archivo, que se trunca ANTES de empezar a escribir,
    así que si el proceso muere en el medio —un deploy, un reinicio— queda a medias. Y como la
    lectura tiene un `except` que devuelve vacío, el archivo roto se lee como "no hay nada" y el
    estado se pierde EN SILENCIO, que es la peor forma de perderlo. Se escribe atómico.
"""

import os
import json
import logging
import threading

log = logging.getLogger("estado")
_LOCK = threading.Lock()


def dir_datos():
    """Carpeta persistente. `ITHOS_DATA` es el volumen del contenedor; fuera de Docker, ~/.ithos."""
    d = (os.environ.get("ITHOS_DATA") or "").strip()
    if not d:
        d = os.path.join(os.path.expanduser("~"), ".ithos")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def ruta(prefijo, cliente):
    """Ruta del archivo de estado de una tarea para un cliente. El nombre se sanea: el nombre de la
    empresa lo escribe una persona y no puede terminar armando una ruta."""
    seguro = "".join(ch if ch.isalnum() else "_" for ch in str(cliente or "cliente"))[:60]
    return os.path.join(dir_datos(), f"{prefijo}_{seguro}.json")


def cargar(prefijo, cliente):
    """El estado guardado, o {} si todavía no hay."""
    try:
        with open(ruta(prefijo, cliente), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar(prefijo, cliente, datos):
    """Guarda el estado de forma ATÓMICA (escribe aparte y renombra)."""
    destino = ruta(prefijo, cliente)
    tmp = destino + ".tmp"
    with _LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False)
            os.replace(tmp, destino)
        except OSError as e:
            log.warning("No pude guardar el estado %s de %s: %s", prefijo, cliente, e)
            try:
                os.remove(tmp)
            except OSError:
                pass
