#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mantener el sistema DESPIERTO mientras ITHOS corre (producción y demo).

Aunque se BLOQUEE la pantalla, el proceso sigue: eso no lo detiene el bloqueo. El problema es la
SUSPENSIÓN del sistema (dormir), que sí pausa todo (voz, portero, micrófono, polling). Esto evita
esa suspensión mientras ITHOS está activo. La pantalla puede apagarse igual (no la forzamos).

Multiplataforma y best-effort (no rompe si no se puede):
  · Windows -> SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) desde un hilo vivo.
  · macOS   -> `caffeinate -i -s` (evita el idle/system sleep).
  · Linux   -> `systemd-inhibit ... sleep infinity` (bloquea sleep) si está disponible.
"""

import sys
import shutil
import logging
import threading
import subprocess

log = logging.getLogger("despierto")
_ACTIVO = False
_LOCK = threading.Lock()


def _windows():
    import ctypes
    import time
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001

    def _loop():
        # ES_CONTINUOUS mantiene el estado hasta el próximo llamado; se re-aplica cada tanto por
        # robustez (y el hilo queda vivo, que es lo que sostiene el estado).
        while True:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            except Exception:  # noqa: BLE001
                return
            time.sleep(50)
    threading.Thread(target=_loop, name="despierto", daemon=True).start()
    return True


def _mac():
    subprocess.Popen(["caffeinate", "-i", "-s"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _linux():
    if not shutil.which("systemd-inhibit"):
        return False
    subprocess.Popen(
        ["systemd-inhibit", "--what=sleep:idle", "--why=ITHOS activo",
         "--mode=block", "sleep", "infinity"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def mantener_despierto():
    """Evita que el sistema se SUSPENDA mientras ITHOS corre. Se puede llamar varias veces (una
    sola surte efecto). Devuelve True si quedó activo. Nunca lanza excepción."""
    global _ACTIVO
    with _LOCK:
        if _ACTIVO:
            return True
        try:
            if sys.platform.startswith("win"):
                ok = _windows()
            elif sys.platform == "darwin":
                ok = _mac()
            else:
                ok = _linux()
        except Exception as e:  # noqa: BLE001
            log.info("No se pudo evitar la suspensión (sigue igual): %s", e)
            ok = False
        _ACTIVO = bool(ok)
        if ok:
            log.info("Anti-suspensión activo: el sistema no se duerme mientras ITHOS corre.")
        return _ACTIVO
