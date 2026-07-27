#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Memoria de ITHOS POR CLIENTE (multi-tenant). Cada empresa tiene su PROPIA base de
datos, aislada: un cliente NUNCA ve el contexto de otro. Guarda:
  - historial de conversación (lo que se habló, por canal),
  - hechos APRENDIDOS (preferencias, datos, atajos) que crecen con el uso.

DB: SQLite por cliente en comun/memoria_<cliente>.sqlite3 (liviana, sin servidor).
"""

import os
import time
import sqlite3
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
_LOCK = threading.Lock()

# La memoria (aprendizaje por cliente) vive en una carpeta ESTABLE del usuario, no
# dentro del proyecto: sobrevive a mover/copiar la carpeta. Env ITHOS_DATA la cambia.
DATA = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
try:
    os.makedirs(DATA, exist_ok=True)
except Exception:  # noqa: BLE001
    DATA = BASE


def _archivo(cliente):
    seguro = "".join(ch if ch.isalnum() else "_" for ch in (cliente or "cliente"))
    nombre = f"memoria_{seguro}.sqlite3"
    destino = os.path.join(DATA, nombre)
    viejo = os.path.join(BASE, nombre)          # migrar memoria previa del proyecto
    if not os.path.exists(destino) and os.path.exists(viejo):
        try:
            import shutil
            shutil.copy2(viejo, destino)
        except Exception:  # noqa: BLE001
            pass
    return destino


class Memoria:
    """Memoria aislada de UN cliente. Instanciá una por empresa."""

    def __init__(self, cliente):
        self.cliente = cliente
        self.ruta = _archivo(cliente)
        self._init()

    def _con(self):
        c = sqlite3.connect(self.ruta, timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init(self):
        with _LOCK, self._con() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS conversacion(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, canal TEXT,
                rol TEXT, texto TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS hechos(
                clave TEXT PRIMARY KEY, valor TEXT, ts REAL)""")

    # -- Conversación -------------------------------------------------------
    def agregar(self, rol, texto, canal="chat"):
        if not (texto or "").strip():
            return
        with _LOCK, self._con() as c:
            c.execute("INSERT INTO conversacion(ts,canal,rol,texto) VALUES(?,?,?,?)",
                      (time.time(), canal, rol, texto[:4000]))

    def historial(self, n=8):
        """Últimos n turnos (más viejo primero) para dar contexto al modelo."""
        with _LOCK, self._con() as c:
            filas = c.execute(
                "SELECT rol,texto FROM conversacion ORDER BY id DESC LIMIT ?",
                (n,)).fetchall()
        return list(reversed(filas))

    def historial_texto(self, n=8):
        return "\n".join(f"{'Usuario' if r == 'user' else 'ITHOS'}: {t}"
                         for r, t in self.historial(n))

    # -- Hechos aprendidos --------------------------------------------------
    def recordar(self, clave, valor):
        with _LOCK, self._con() as c:
            c.execute("INSERT INTO hechos(clave,valor,ts) VALUES(?,?,?) "
                      "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor, ts=excluded.ts",
                      (clave[:120], str(valor)[:2000], time.time()))

    def olvidar(self, clave):
        with _LOCK, self._con() as c:
            c.execute("DELETE FROM hechos WHERE clave=?", (clave,))

    def hechos(self):
        with _LOCK, self._con() as c:
            return dict(c.execute("SELECT clave,valor FROM hechos ORDER BY ts DESC").fetchall())

    def hechos_texto(self, n=20):
        h = list(self.hechos().items())[:n]
        return "\n".join(f"- {k}: {v}" for k, v in h)

    def resumen(self):
        with _LOCK, self._con() as c:
            conv = c.execute("SELECT COUNT(*) FROM conversacion").fetchone()[0]
            hec = c.execute("SELECT COUNT(*) FROM hechos").fetchone()[0]
        return {"cliente": self.cliente, "turnos": conv, "hechos": hec}
