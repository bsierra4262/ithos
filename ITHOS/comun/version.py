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


# --------------------------------------------------------------- qué hay DESPLEGADO de verdad
# El servidor no es un checkout de git (el paquete se descomprime sobre la carpeta), así que no hay
# forma de preguntarle "¿qué commit estás corriendo?". Sin eso, diagnosticar es adivinar: cuando algo
# falla en producción, lo primero que hay que saber es SI el arreglo llegó. El deploy deja un archivo
# con la revisión y acá se lee; si no está, se dice que no se sabe, que es la verdad.
_ARCHIVO_REVISION = "REVISION"


def revision_desplegada():
    """Revisión (commit corto + fecha) del código que está corriendo, o 'desconocida'."""
    import os
    for base in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),        # ITHOS/
                 os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                 "/app"):
        try:
            with open(os.path.join(base, _ARCHIVO_REVISION), encoding="utf-8") as f:
                rev = f.read().strip()
            if rev:
                return rev
        except OSError:
            continue
    return "desconocida"
