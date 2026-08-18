#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canales de notificación (por cliente). Un cliente puede tener VARIOS canales; hoy el que usa
INTELLIHELP es WhatsApp (ver comun/whatsapp.py), con sus grupos por ámbito (comun/ambitos.py).

Config: lista en "notificaciones", cada uno {"tipo": ...}. Todos exponen `enviar(texto)`; los que
saben separar por grupo aceptan además `tipo=` (el tipo de aviso).
crear_notificadores(cfg) -> objeto con enviar(texto) que manda a TODOS los canales del cliente.

Sumar otro canal (Telegram, email, Teams/Slack, Matrix…) es escribir una clase con `enviar()` y
agregarla en `crear_notificadores`: el resto del software no se entera. Las implementaciones que
teníamos quedaron congeladas en la rama `saas`.
"""

import logging

log = logging.getLogger("notificadores")



def estado_canal(c):
    """Estado ACTIVO/INACTIVO de un canal, para el dashboard de salud (gestor + agente). El WhatsApp
    no-oficial reporta si la sesión está REALMENTE conectada (_listo + grupo resuelto); el resto, si
    está bien configurado. Así el cliente ve de un vistazo si algún canal quedó sin arrancar."""
    nombre = c.__class__.__name__
    try:
        if nombre == "WhatsAppNoOficial":
            listos = [g for g in getattr(c, "grupos", []) if g.get("jid") is not None]
            activo = (getattr(c, "_listo", None) is not None and c._listo.is_set() and listos)
            detalle = ", ".join(f"{g['grupo']} ({g['ambito']})" for g in listos)
            return {"tipo": "whatsapp_no_oficial", "activo": bool(activo),
                    "detalle": detalle if activo else "sin conectar / re-vincular"}
    except Exception:  # noqa: BLE001
        pass
    return {"tipo": nombre.lower(), "activo": False, "detalle": ""}


class Notificadores:
    """Agrupa todos los canales del cliente. enviar() manda a todos."""

    def __init__(self, canales):
        self.canales = canales

    def estado(self):
        """Lista de {tipo, activo, detalle} de cada canal (dashboard de salud)."""
        return [estado_canal(c) for c in self.canales]

    def canal_activo(self, tipo):
        """True si HAY algún canal de ese tipo y está activo (p. ej. para decidir cuándo avisar)."""
        return any(e["activo"] for e in self.estado() if e["tipo"] == tipo)

    def hay_activo(self):
        """True si al menos un canal está activo (para saber si el aviso llegará a algún lado)."""
        return any(e["activo"] for e in self.estado())

    @staticmethod
    def _con_tipo(fn, args, tipo):
        """Le pasa el TIPO al canal si lo entiende (sólo WhatsApp separa por grupos)."""
        from comun import ambitos as _AMB
        return _AMB.llamar(fn, *args, tipo=tipo)

    def enviar(self, texto, tipo=None):
        """Manda el aviso a los canales del cliente. `tipo` (tickets / sla / planka / sistema / voz)
        decide a QUÉ GRUPO de WhatsApp va: el de soporte no se llena de tareas del equipo y el de
        consultas no recibe alertas. Ver comun/ambitos.py."""
        ok = False
        for c in self.canales:
            try:
                ok = self._con_tipo(c.enviar, (texto,), tipo) or ok
            except Exception:  # noqa: BLE001
                pass
        return ok

    def enviar_mencion(self, texto, telefonos, tipo=None):
        """Aviso @MENCIONANDO a `telefonos` (el TÉCNICO ASIGNADO) en los canales que lo soportan
        (WhatsApp). Los canales que NO tienen menciones (Telegram/email/Teams/Element) reciben el
        MISMO texto sin @ — el aviso nunca se pierde y el texto ya dice a quién está asignado.
        Sin teléfonos, es un envío normal."""
        if not telefonos:
            return self.enviar(texto, tipo=tipo)
        ok = False
        for c in self.canales:
            fn = getattr(c, "enviar_mencion", None)
            try:
                ok = (self._con_tipo(fn, (texto, telefonos), tipo) if fn
                      else self._con_tipo(c.enviar, (texto,), tipo)) or ok
            except Exception:  # noqa: BLE001
                pass
        return ok

    def enviar_documento(self, nombre, datos, mime="application/pdf", caption=""):
        """Manda un archivo (PDF/CSV) por los canales que lo soporten (los que no, ignoran)."""
        ok = False
        for c in self.canales:
            fn = getattr(c, "enviar_documento", None)
            if not fn:
                continue
            try:
                ok = fn(nombre, datos, mime, caption) or ok
            except Exception:  # noqa: BLE001
                pass
        return ok


def crear_notificadores(cfg_cliente, wa_compartido=None):
    """Arma el notificador multicanal con TODOS los canales que el cliente configuró.
    `wa_compartido`: si se pasa una conexión WhatsApp ya abierta (p. ej. la de la demo), se REUSA
    y NO se crea otra —así no se abren dos sesiones del mismo número—; los canales que no sean
    WhatsApp se agregan igual. Sin él (producción), se crea la conexión WhatsApp propia."""
    canales = []
    if wa_compartido is not None:
        canales.append(wa_compartido)       # reusa la conexión WhatsApp ya abierta (demo)
    # WhatsApp (compat: bloque 'whatsapp' suelto). Solo si NO hay uno compartido.
    wa_cfg = cfg_cliente.get("whatsapp")
    if wa_compartido is None and wa_cfg and wa_cfg.get("enabled"):
        from comun import whatsapp
        wa = whatsapp.crear_whatsapp(wa_cfg)
        if wa:
            canales.append(wa)
    # Lista de canales que configuró el cliente. Acá se enchufa un canal nuevo: una clase con
    # `enviar(texto)` y una rama más en este `for`.
    for n in cfg_cliente.get("notificaciones", []):
        if not n.get("enabled", True):
            continue
        tipo = (n.get("tipo") or "").lower()
        if tipo in ("whatsapp", "whatsapp_no_oficial"):
            if wa_compartido is not None:   # ya usamos el WhatsApp compartido -> no duplicar sesión
                continue
            from comun import whatsapp
            wa = whatsapp.crear_whatsapp({**n, "enabled": True, "tipo": "no_oficial"})
            if wa:
                canales.append(wa)
    return Notificadores(canales)
