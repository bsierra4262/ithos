#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reportes y analytics de tickets por cliente (sobre GLPI). Sin IA.
Calcula: cantidad por estado/categoría/prioridad y CUMPLIMIENTO de SLA (resueltos
dentro del tiempo de resolución). Devuelve dict + texto legible.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from comun import glpi as G   # noqa: E402

ESTADOS = {1: "Nuevo", 2: "En curso", 3: "Planificado", 4: "En espera",
           5: "Resuelto", 6: "Cerrado"}


def _fecha(s):
    if not s:                       # None / "" / 0 -> sin fecha (evita strptime en masa a escala)
        return None
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return None


def generar(cfg_glpi, entidad, n=None):
    # n=None (default) -> TODOS los tickets reales del cliente (sin límite). Si se pasa un n, se
    # usa la muestra reciente (para usos rápidos puntuales).
    tickets = G.de_entidad(
        G.tickets_todos_cache(cfg_glpi) if not n else G.tickets_cache(cfg_glpi, n), entidad)
    por_estado, por_cat, por_prio = {}, {}, {}
    total = len(tickets)
    cumplidos = incumplidos = medidos = 0
    for t in tickets:
        est = ESTADOS.get(int(t.get("status", 0)), "?")
        por_estado[est] = por_estado.get(est, 0) + 1
        por_cat[t.get("itilcategories_id")] = por_cat.get(t.get("itilcategories_id"), 0) + 1
        por_prio[t.get("priority")] = por_prio.get(t.get("priority"), 0) + 1
        # SLA: resuelto dentro del time_to_resolve
        solve = _fecha(t.get("solvedate") or t.get("closedate"))
        ttr = _fecha(t.get("time_to_resolve"))
        if solve and ttr:
            medidos += 1
            if solve <= ttr:
                cumplidos += 1
            else:
                incumplidos += 1
    cumplimiento = round(100 * cumplidos / medidos, 1) if medidos else None
    rep = {"total": total, "por_estado": por_estado, "por_prioridad": por_prio,
           "sla_cumplidos": cumplidos, "sla_incumplidos": incumplidos,
           "sla_cumplimiento_pct": cumplimiento}
    texto = (f"Reporte de tickets ({total} analizados):\n"
             f"  Por estado: {por_estado}\n"
             f"  Cumplimiento de SLA: {cumplimiento}% "
             f"({cumplidos} en tiempo / {incumplidos} fuera de tiempo)")
    return rep, texto
