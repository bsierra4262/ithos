#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adaptador GENÉRICO de sistemas de CONTROL DE ACCESO (portero/fichajes). Igual que
comun/tickets.py pero para acceso: ITHOS habla con esta interfaz común, así lo de
anomalías por horario no depende de la marca del equipo.

Interfaz común:
  soporta_anomalias() -> bool   (True sólo si el sistema hace control de horario y
                                 expone su config por API; así se AUTOCONFIGURA solo)
  horarios()          -> [ {persona|door, dias, desde, hasta} ]  (leído por API, sin
                                 que el cliente configure nada a mano)
  anomalias(desde)    -> [ {nombre, cuando, motivo} ]  (fichajes fuera de horario /
                                 denegados por horario, según lo que informa el sistema)

Hoy corre IVMS, que NO hace control de horario: nunca genera anomalías. Sumar un
sistema que sí lo haga es escribir una clase con esta interfaz y una rama en
`adaptador()`, más su integrador del lado del agente.
"""

import logging

log = logging.getLogger("acceso")


class _Base:
    tipo = "generico"

    def soporta_anomalias(self):
        return False

    def horarios(self):
        return []

    def anomalias(self, desde=None):
        return []


class _SinHorario(_Base):
    """IVMS: los fichajes están en SQL y no hay franjas horarias -> nunca hay anomalías."""

    def __init__(self, tipo, cfg):
        self.tipo = tipo
        self.cfg = cfg or {}


def adaptador(cli_cfg):
    """El adaptador de acceso del cliente, según su 'integrador'."""
    tipo = (cli_cfg.get("integrador") or "").lower()
    cfg = cli_cfg.get("integrador_config") or {}
    return _SinHorario(tipo or "generico", cfg)
