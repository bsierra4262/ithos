#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canal de avisos del cliente: su WhatsApp (ver comun/whatsapp.py), con un grupo por tema
(comun/ambitos.py).

Config: lista en "notificaciones", cada una {"tipo": "whatsapp_no_oficial", ...}. `enviar(texto,
tipo=...)` manda el aviso al grupo que corresponde a ese tipo.
crear_notificadores(cfg) -> el objeto que usa el Gestor para avisar.
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
        (WhatsApp). Un canal sin menciones recibe el MISMO texto sin @ —el texto ya dice a quién
        está asignado—. Sin teléfonos, es un envío normal."""
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

    def enviar_documento(self, nombre, datos, mime="application/pdf", caption="", tipo=None):
        """Manda un archivo (PDF/CSV) por los canales que lo soporten, al grupo de su TIPO."""
        ok = False
        for c in self.canales:
            fn = getattr(c, "enviar_documento", None)
            if not fn:
                continue
            try:
                ok = self._con_tipo(fn, (nombre, datos, mime, caption), tipo) or ok
            except Exception:  # noqa: BLE001
                pass
        return ok


def crear_notificadores(cfg_cliente):
    """Arma el notificador con el WhatsApp que el cliente configuró."""
    canales = []
    for n in cfg_cliente.get("notificaciones", []):
        if not n.get("enabled", True):
            continue
        tipo = (n.get("tipo") or "").lower()
        if tipo in ("whatsapp", "whatsapp_no_oficial"):
            from comun import whatsapp
            wa = whatsapp.crear_whatsapp({**n, "enabled": True})
            if wa:
                canales.append(wa)
    return Notificadores(canales)
