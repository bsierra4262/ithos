#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puerta de entrada del asistente conversacional.

El código vive en dos módulos, cada uno con su tema:
  · `comun/asistente.py`     — el que conversa: contexto real, decisión, respuesta y ejecución.
  · `comun/herramientas.py`  — qué puede leer y qué puede escribir sobre el sistema de tickets.

Se re-exporta desde acá para que quien importe `comun.conversacion` siga funcionando igual.
"""

from comun.asistente import *          # noqa: F401,F403
from comun.asistente import (Asistente, mensaje_inicio, mensaje_sin_cuota, info_reset,  # noqa: F401
                             ZONA_DEFAULT, _fusionar, _pide_detalle, _pide_antecedentes,
                             _id_ticket, _ticket_por_asunto, _mensaje_error)
from comun.herramientas import (herramientas_tickets, acciones_tickets,                 # noqa: F401
                                herramientas_glpi, acciones_glpi, _resolver_tecnico,
                                _una_linea)
