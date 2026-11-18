#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Padrón de ITHOS: la configuración de la empresa (clientes.json), identificada por su API key.
Se lee al arrancar el Gestor; si el archivo cambia (se guardó desde el panel), el Gestor se
reinicia para aplicarlo (ver `main._vigilar_config`).
"""

import os
import json
import threading

BASE = os.path.dirname(os.path.abspath(__file__))

import logging

log = logging.getLogger("registro")

# El token del usuario con el que ITHOS ESCRIBE en GLPI se llama `glpi_ithos_token`. Sin él el
# Gestor arranca SIN triage: eso no puede pasar en silencio. (Antes se "adoptaba" cualquier otro
# token de la config, pero con los tokens de los técnicos en la config ITHOS habría escrito con
# la cuenta de una persona: se dice en el log y se arregla la config.)
_TOKEN_AGENTE = "glpi_ithos_token"


def _normalizar(cliente):
    gl = cliente.get("integrador_glpi")
    if isinstance(gl, dict) and gl.get("glpi_url") and not gl.get(_TOKEN_AGENTE):
        log.error("Config de '%s': falta '%s' en integrador_glpi. ITHOS no va a triagear tickets "
                  "hasta que se cargue.", cliente.get("nombre", "?"), _TOKEN_AGENTE)
    return cliente


class Registro:
    def __init__(self, ruta=None):
        self.ruta = ruta or os.environ.get(
            "ITHOS_CLIENTES", os.path.join(BASE, "clientes.json"))
        self._por_key = {}
        self._mtime = None
        self._lock = threading.Lock()
        self.cargar()

    def _mtime_actual(self):
        try:
            return os.path.getmtime(self.ruta)
        except OSError:
            return None

    def cambio(self):
        """True si clientes.json cambió en disco desde que se cargó (alguien guardó desde el panel)."""
        m = self._mtime_actual()
        return m is not None and self._mtime is not None and m != self._mtime

    def cargar(self):
        """Lee el padrón de clientes del disco.

        Un fallo acá NO puede ser silencioso. Antes dejaba `_por_key` vacío sin decir nada, y un
        padrón vacío es un Gestor que levanta normalmente, acepta la conexión del agente y después
        no valida a NADIE: ningún cliente existe, ningún servicio arranca, y en el log no hay una
        sola línea que lo explique. Como `cargar()` corre una única vez al arrancar, eso deja el
        Gestor inútil hasta que alguien lo note a mano.

        Tampoco se pisa lo que ya estaba cargado: si alguna vez se recarga en caliente y la lectura
        falla, es preferible seguir atendiendo con el padrón anterior que quedarse sin ninguno."""
        with self._lock:
            self._mtime = self._mtime_actual()
            try:
                with open(self.ruta, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:  # noqa: BLE001
                log.error("No se pudo leer el padrón de clientes (%s): %s. El Gestor NO va a "
                          "atender a ningún cliente hasta que esto se resuelva.",
                          self.ruta, str(e)[:140])
                return                      # se conserva lo que hubiera cargado antes
            # Los secretos están CIFRADOS en disco: se descifran acá para que el Gestor los use.
            try:
                from comun import cifrado as CIF
                data = CIF.descifrar_datos(data)
            except Exception as e:  # noqa: BLE001
                # Sin descifrar, los tokens quedan como 'enc:v1:…' y todo falla más adelante con
                # errores que no se parecen en nada a la causa. Hay que decirlo acá.
                log.error("No se pudieron descifrar los secretos del padrón (%s). Revisá "
                          "ITHOS_MASTER_KEY: los tokens van a quedar ilegibles.", str(e)[:140])
            try:
                self._por_key = {c["api_key"]: _normalizar(c)
                                 for c in data.get("clientes", [])
                                 if c.get("activo", True)}
            except Exception as e:  # noqa: BLE001
                log.error("El padrón de clientes tiene un formato inesperado (%s): %s",
                          self.ruta, str(e)[:140])
                return
            log.info("Padrón de clientes cargado: %d activo(s).", len(self._por_key))

    def validar(self, api_key):
        """Devuelve la config del cliente si la api_key es válida, o None."""
        return self._por_key.get((api_key or "").strip())

    def todos(self):
        """Todos los clientes ACTIVOS. El Gestor les arranca los servicios de fondo al iniciar,
        sin esperar a que se conecte el agente de cada uno (ver `main.arrancar_servicios`)."""
        return list(self._por_key.values())
