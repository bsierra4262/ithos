#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Métricas de uso (tickets gestionados, avisos, consultas) para el panel. Registra eventos livianos en un
JSON en la carpeta de DATOS (ITHOS_DATA, el volumen persistente) y da un resumen del mes.
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
    """En ITHOS_DATA (antes se escribía dentro de la carpeta del CÓDIGO). Si todavía hay uno en la
    ubicación vieja y no en la nueva, se lo trae una vez: no se pierde lo acumulado."""
    seguro = "".join(ch if ch.isalnum() else "_" for ch in cliente)
    nombre = f"metricas_{seguro}.json"
    datos = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
    ruta, vieja = os.path.join(datos, nombre), os.path.join(BASE, nombre)
    try:
        os.makedirs(datos, exist_ok=True)
        if not os.path.exists(ruta) and os.path.exists(vieja):
            import shutil
            shutil.copy2(vieja, ruta)
    except OSError:
        return vieja
    return ruta


def registrar(cliente, tipo, n=1):
    """tipo: 'ticket' | 'anuncio' | 'consulta_voz' (todas las consultas, por voz o chat).
    TODA la actividad REAL cuenta y se ve en el panel."""
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
