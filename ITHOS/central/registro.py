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

import logging

log = logging.getLogger("registro")

# El token del usuario con el que ITHOS ESCRIBE en el sistema de tickets se llama `glpi_ithos_token`.
# Una configuración vieja puede traerlo con OTRO nombre (el de la marca anterior) y, al no
# encontrarlo, el Gestor arrancaba SIN triage y en silencio. Compatibilidad al leer: si falta, se
# adopta el otro token de usuario que traiga la config (los de rol conocido NO se toman: son de
# lectura/admin/pruebas). No se reescribe el archivo del cliente.
_TOKEN_AGENTE = "glpi_ithos_token"
_TOKENS_CONOCIDOS = {_TOKEN_AGENTE, "glpi_app_token", "glpi_user_token",
                     "glpi_superadmin_token", "glpi_bsierra_token", "glpi_test_token"}


def _normalizar(cliente):
    """Compatibilidad de nombres de config, para que un clientes.json viejo funcione igual."""
    for bloque in ("integrador_glpi", "tickets"):
        cfg = cliente.get(bloque)
        if not isinstance(cfg, dict) or cfg.get(_TOKEN_AGENTE):
            continue
        for clave, valor in cfg.items():
            if (clave.startswith("glpi_") and clave.endswith("_token")
                    and clave not in _TOKENS_CONOCIDOS and valor):
                cfg[_TOKEN_AGENTE] = valor
                log.warning("Config de '%s': '%s' tiene el nombre anterior de la marca; se usa como "
                            "%s. Renombralo para evitar sorpresas.",
                            cliente.get("nombre", "?"), clave, _TOKEN_AGENTE)
                break
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

    def todos(self):
        """Todos los clientes ACTIVOS. El Gestor les arranca los servicios de fondo al iniciar,
        sin esperar a que se conecte el agente de cada uno (ver `main.arrancar_servicios`)."""
        return list(self._por_key.values())
