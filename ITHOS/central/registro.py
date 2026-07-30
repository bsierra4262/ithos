#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registro de clientes (multi-tenant). Cada cliente se identifica por su API key.
Agregar un cliente = agregar una entrada en clientes.json (cero código).

Diseñado para migrar a una DB (Postgres) sin cambiar el resto: solo esta clase.
"""

import os
import json
import threading

BASE = os.path.dirname(os.path.abspath(__file__))

# La marca es ITHOS: el token del usuario que ESCRIBE en el sistema de tickets se llama
# `glpi_ithos_token`. Las configuraciones viejas lo tenían con el nombre anterior y, al no
# encontrarlo, el Gestor arrancaba SIN triage (silenciosamente). Se acepta el nombre viejo como
# COMPATIBILIDAD al leer (no se reescribe el archivo del cliente).
_COMPAT_TOKEN = {"glpi_ithos_token": "glpi_jarvis_token"}


def _normalizar(cliente):
    """Compatibilidad de nombres de config, para que un clientes.json viejo funcione igual."""
    for bloque in ("integrador_glpi", "tickets"):
        cfg = cliente.get(bloque)
        if not isinstance(cfg, dict):
            continue
        for nuevo, viejo in _COMPAT_TOKEN.items():
            if not cfg.get(nuevo) and cfg.get(viejo):
                cfg[nuevo] = cfg[viejo]
    return cliente


class Registro:
    def __init__(self, ruta=None):
        self.ruta = ruta or os.environ.get(
            "ITHOS_CLIENTES", os.path.join(BASE, "clientes.json"))
        self._por_key = {}
        self._lock = threading.Lock()
        self.cargar()

    def cargar(self):
        with self._lock:
            try:
                with open(self.ruta, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Los secretos están CIFRADOS en disco: se descifran acá para que el Gestor los use.
                try:
                    from comun import cifrado as CIF
                    data = CIF.descifrar_datos(data)
                except Exception:  # noqa: BLE001
                    pass
                self._por_key = {c["api_key"]: _normalizar(c)
                                 for c in data.get("clientes", [])
                                 if c.get("activo", True)}
            except Exception:  # noqa: BLE001
                self._por_key = {}

    def validar(self, api_key):
        """Devuelve la config del cliente si la api_key es válida, o None."""
        return self._por_key.get((api_key or "").strip())

    def total(self):
        return len(self._por_key)
