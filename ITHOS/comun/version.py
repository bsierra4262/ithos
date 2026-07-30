#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Versiones de ITHOS (SemVer). El GESTOR (el cerebro, que hosteamos nosotros) y el AGENTE (la app
liviana del cliente) se versionan POR SEPARADO. PROTOCOL_VERSION es el contrato de mensajes entre
ambos: se sube el número solo ante un cambio INCOMPATIBLE del protocolo (compatibilidad hacia atrás).

SemVer MAJOR.MINOR.PATCH: MAJOR = cambio incompatible, MINOR = feature compatible, PATCH = arreglo.
Ver ARQUITECTURA_GESTOR_AGENTE.md.
"""

GESTOR_VERSION = "1.1.0"        # el cerebro / control-plane (lo hosteamos nosotros)
AGENTE_VERSION = "1.1.29"        # la app liviana del cliente (data-plane / executor)
PROTOCOL_VERSION = 1            # contrato de mensajes agente <-> gestor (entero; +1 si rompe compat)
AGENTE_MIN_VERSION = "1.0.0"    # agente MÍNIMO que el gestor soporta (para el aviso de auto-update)


def _tupla(v):
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except (TypeError, ValueError):
        return (0, 0, 0)


def compat_protocolo(protocolo):
    """True si un agente que habla `protocolo` (entero) es compatible con ESTE gestor. Compat hacia
    atrás: se aceptan protocolos <= el del gestor; sin versión (agente viejo) también se acepta."""
    if protocolo in (None, ""):
        return True
    try:
        return int(protocolo) <= PROTOCOL_VERSION
    except (TypeError, ValueError):
        return True


def agente_desactualizado(agente_version):
    """True si el agente del cliente es MÁS VIEJO que el mínimo soportado -> conviene actualizar
    (lo usa el aviso de auto-update; en fase 1 solo informa, no obliga)."""
    if not agente_version:
        return False
    return _tupla(agente_version) < _tupla(AGENTE_MIN_VERSION)
