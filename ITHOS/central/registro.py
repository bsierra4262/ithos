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
                self._por_key = {c["api_key"]: c
                                 for c in data.get("clientes", [])
                                 if c.get("activo", True)}
            except Exception:  # noqa: BLE001
                self._por_key = {}

    def validar(self, api_key):
        """Devuelve la config del cliente si la api_key es válida, o None."""
        return self._por_key.get((api_key or "").strip())

    def total(self):
        return len(self._por_key)
