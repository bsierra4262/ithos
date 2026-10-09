#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Métricas de uso por cliente (para facturar/medir). Registra eventos livianos en un
JSON por cliente y da un resumen (tickets procesados, anuncios, usos de IA, etc.).
"""

import os
import json
import threading
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
_LOCK = threading.Lock()


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


def _archivo(cliente):
    # DEMO/PRUEBA escribe y lee su PROPIO archivo (metricas_demo_*), AISLADO de producción:
    # así la actividad real de la demo se VE en su panel sin contaminar los números reales del
    # cliente en producción (entornos separados). El panel usa el mismo env que quien registra,
    # por lo que cada entorno muestra lo suyo.
    entorno = "demo_" if os.environ.get("ITHOS_DEMO") else ""
    seguro = "".join(ch if ch.isalnum() else "_" for ch in cliente)
    return os.path.join(BASE, f"metricas_{entorno}{seguro}.json")


def registrar(cliente, tipo, n=1):
    """tipo: 'ticket' | 'anuncio' | 'ia_texto' | 'ia_voz' | 'consulta_voz' | 'whatsapp' | ...
    TODA la actividad REAL cuenta y se ve en el panel del entorno correspondiente. En DEMO se
    guarda en un archivo aparte (ver _archivo): la demo muestra lo que hace ITHOS de verdad
    (avisos, triage de tickets, consultas) sin ensuciar las métricas de producción."""
    mes = datetime.now().strftime("%Y-%m")
    with _LOCK:
        try:
            d = json.load(open(_archivo(cliente), encoding="utf-8"))
        except Exception:  # noqa: BLE001
            d = {}
        d.setdefault(mes, {})
        d[mes][tipo] = d[mes].get(tipo, 0) + n
        try:
            _escribir_atomico(_archivo(cliente), d)
        except Exception:  # noqa: BLE001
            pass


def resumen(cliente, mes=None):
    mes = mes or datetime.now().strftime("%Y-%m")
    try:
        d = json.load(open(_archivo(cliente), encoding="utf-8"))
        return {"cliente": cliente, "mes": mes, "uso": d.get(mes, {})}
    except Exception:  # noqa: BLE001
        return {"cliente": cliente, "mes": mes, "uso": {}}
