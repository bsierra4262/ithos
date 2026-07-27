#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Icono de BANDEJA (system tray) del Agente ITHOS — estilo AMD/Discord. Mientras el agente corre
(headless `--run`), aparece el icono ITHOS en la barra de notificaciones: así sabés que está en
marcha (y no lo duplicás). Menú: abrir la configuración / detener y salir.

Corre en un hilo (no bloquea el agente). Si pystray no está o no hay bandeja (server sin escritorio),
simplemente no se muestra (el agente sigue igual).
"""
import os
import sys
import logging
import threading

log = logging.getLogger("agente.bandeja")


def _icono_img():
    from PIL import Image
    bases = [getattr(sys, "_MEIPASS", None),
             os.path.dirname(os.path.abspath(__file__)),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build")]
    for base in bases:
        if base:
            p = os.path.join(base, "ithos.png")
            if os.path.exists(p):
                try:
                    return Image.open(p)
                except Exception:  # noqa: BLE001
                    pass
    return Image.new("RGBA", (64, 64), (47, 227, 255, 255))   # respaldo: cuadrado cian


def iniciar(al_abrir, al_detener):
    """Muestra el icono en la bandeja. `al_abrir()` abre la config; `al_detener()` frena el agente.
    Devuelve el icon (o None si no se pudo). No bloquea (corre en un hilo daemon)."""
    try:
        import pystray
    except Exception as e:  # noqa: BLE001
        log.info("Sin bandeja (pystray no disponible): %s", e)
        return None

    def _abrir(icon=None, item=None):
        try:
            al_abrir()
        except Exception as e:  # noqa: BLE001
            log.warning("Bandeja: no pude abrir la config: %s", e)

    def _salir(icon, item):
        try:
            al_detener()
        finally:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass

    menu = pystray.Menu(
        pystray.MenuItem("ITHOS Agente — en marcha", None, enabled=False),
        pystray.MenuItem("Abrir configuración", _abrir, default=True),
        pystray.MenuItem("Detener y salir", _salir))
    try:
        icon = pystray.Icon("ithos_agente", _icono_img(), "ITHOS Agente (en marcha)", menu)
        threading.Thread(target=icon.run, name="bandeja", daemon=True).start()
        log.info("Icono de bandeja activo (ITHOS en marcha).")
        return icon
    except Exception as e:  # noqa: BLE001
        log.info("No se pudo iniciar la bandeja: %s", e)
        return None
