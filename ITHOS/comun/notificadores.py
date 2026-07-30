#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canales de notificación (por cliente). Un cliente puede tener VARIOS canales.
Config: lista en "notificaciones", cada uno {"tipo": ...}. Todos exponen enviar(texto).

Tipos: whatsapp (oficial/no-oficial, ver comun/whatsapp.py), telegram, email, teams, slack.
crear_notificadores(cfg) -> objeto con enviar(texto) que manda a TODOS los canales.
"""

import ssl
import time
import json
import uuid
import smtplib
import logging
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

log = logging.getLogger("notificadores")


def _multipart(campos, archivo):
    """Arma un cuerpo multipart/form-data. campos: dict. archivo: (campo, nombre, mime, bytes)."""
    b = "----ithos" + uuid.uuid4().hex
    out = b""
    for k, v in campos.items():
        out += (f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    campo, nombre, mime, datos = archivo
    out += (f"--{b}\r\nContent-Disposition: form-data; name=\"{campo}\"; filename=\"{nombre}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + datos + f"\r\n--{b}--\r\n".encode()
    return b, out


class Telegram:
    def __init__(self, cfg):
        self.token = cfg.get("bot_token", "")
        self.chats = cfg.get("chat_ids", [])
        # Formato elegido por el cliente ('texto' | 'audio' | 'ambos'); default texto (no sorprende
        # a quien ya usa Telegram sólo por texto). Si pide audio, se manda NOTA DE VOZ (sendVoice).
        self.respuesta = (cfg.get("respuesta") or "texto").lower()

    def enviar(self, texto):
        ok = False
        if self.respuesta in ("texto", "ambos"):
            ok = self._enviar_texto(texto) or ok
        if self.respuesta in ("audio", "ambos"):
            self._enviar_voz(texto)            # nota de voz en segundo plano
            ok = True
        return ok

    def _enviar_texto(self, texto):
        from comun import whatsapp as _wa
        texto = _wa.formato_wa(texto)      # Telegram usa *negrita* y _cursiva_ (Markdown)
        ok = False
        for chat in self.chats:
            try:
                data = json.dumps({"chat_id": chat, "text": texto,
                                   "parse_mode": "Markdown"}).encode()
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    data=data, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=15)
                ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("Telegram: %s", e)
        return ok

    def _enviar_voz(self, texto):
        """Nota de voz por Telegram (Bot API sendVoice, OGG/opus). En SEGUNDO PLANO. Si no hay
        ffmpeg (el audio no queda en opus), cae a sendAudio (MP3). Doc:
        https://core.telegram.org/bots/api#sendvoice y #sendaudio."""
        import threading

        def _run(_t=texto):
            try:
                import shutil
                from comun import voz_tts
                voz = voz_tts.audio(_t, formato="ogg")
                if not voz:
                    return
                if shutil.which("ffmpeg"):
                    metodo, campo, nombre, mime = "sendVoice", "voice", "ithos.ogg", "audio/ogg"
                else:                              # sin ffmpeg el audio es MP3 -> sendAudio
                    metodo, campo, nombre, mime = "sendAudio", "audio", "ithos.mp3", "audio/mpeg"
                for chat in self.chats:
                    try:
                        b, cuerpo = _multipart({"chat_id": str(chat)},
                                               (campo, nombre, mime, voz))
                        req = urllib.request.Request(
                            f"https://api.telegram.org/bot{self.token}/{metodo}", data=cuerpo,
                            headers={"Content-Type": f"multipart/form-data; boundary={b}"})
                        urllib.request.urlopen(req, timeout=40)
                    except Exception as e:  # noqa: BLE001
                        log.warning("Telegram nota de voz: %s", e)
            except Exception as e:  # noqa: BLE001
                log.warning("Telegram nota de voz: %s", e)
        threading.Thread(target=_run, name="tg-voz", daemon=True).start()

    def enviar_documento(self, nombre, datos, mime="application/pdf", caption=""):
        ok = False
        for chat in self.chats:
            try:
                b, cuerpo = _multipart({"chat_id": str(chat), "caption": caption[:1000]},
                                       ("document", nombre, mime, datos))
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{self.token}/sendDocument",
                    data=cuerpo, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
                urllib.request.urlopen(req, timeout=40)
                ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("Telegram documento: %s", e)
        return ok


class Email:
    def __init__(self, cfg):
        self.host = cfg.get("smtp_host", "smtp.gmail.com")
        self.port = int(cfg.get("smtp_port", 465))
        self.user = cfg.get("usuario", "")
        self.passwd = cfg.get("password", "")
        self.destinatarios = cfg.get("destinatarios", [])
        self.asunto = cfg.get("asunto", "Alerta ITHOS")

    def enviar(self, texto):
        try:
            from comun import whatsapp as _wa
            texto = _wa.formato_plano(texto)   # Email: viñetas legibles, sin */_ de negrita
            msg = MIMEText(texto, "plain", "utf-8")
            msg["Subject"] = self.asunto
            msg["From"] = self.user
            msg["To"] = ", ".join(self.destinatarios)
            with smtplib.SMTP_SSL(self.host, self.port,
                                  context=ssl.create_default_context()) as s:
                s.login(self.user, self.passwd)
                s.sendmail(self.user, self.destinatarios, msg.as_string())
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Email: %s", e)
            return False

    def enviar_documento(self, nombre, datos, mime="application/pdf", caption=""):
        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.base import MIMEBase
            from email import encoders
            msg = MIMEMultipart()
            msg["Subject"] = self.asunto
            msg["From"] = self.user
            msg["To"] = ", ".join(self.destinatarios)
            msg.attach(MIMEText(caption or "Adjuntamos el reporte.", "plain", "utf-8"))
            parte = MIMEBase(*mime.split("/", 1)) if "/" in mime else MIMEBase("application", "octet-stream")
            parte.set_payload(datos)
            encoders.encode_base64(parte)
            parte.add_header("Content-Disposition", f'attachment; filename="{nombre}"')
            msg.attach(parte)
            with smtplib.SMTP_SSL(self.host, self.port,
                                  context=ssl.create_default_context()) as s:
                s.login(self.user, self.passwd)
                s.sendmail(self.user, self.destinatarios, msg.as_string())
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Email documento: %s", e)
            return False


class Webhook:
    """Teams / Slack: incoming webhook. Slack usa {'text':...}, Teams {'text':...}."""

    def __init__(self, cfg):
        self.url = cfg.get("webhook_url", "")

    def enviar(self, texto):
        try:
            req = urllib.request.Request(
                self.url, data=json.dumps({"text": texto}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Webhook: %s", e)
            return False


class ElementNotif:
    """Element / Matrix: manda avisos proactivos a las salas configuradas (API client-server v3,
    m.room.message). Complementa al canal CONVERSACIONAL (comun/canales.py ElementConversacional)."""

    def __init__(self, cfg):
        self.base = (cfg.get("homeserver") or "https://matrix.org").rstrip("/")
        self.token = cfg.get("access_token", "")
        self.salas = [str(r) for r in (cfg.get("room_ids") or [])]

    def enviar(self, texto):
        ok = False
        for sala in self.salas:
            try:
                txn = str(int(time.time() * 1000))
                url = (self.base + "/_matrix/client/v3/rooms/" + urllib.parse.quote(sala)
                       + "/send/m.room.message/" + txn)
                req = urllib.request.Request(
                    url, data=json.dumps({"msgtype": "m.text", "body": texto}).encode(),
                    method="PUT", headers={"Authorization": f"Bearer {self.token}",
                                           "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=15)
                ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("Element notif: %s", e)
        return ok


def estado_canal(c):
    """Estado ACTIVO/INACTIVO de un canal, para el dashboard de salud (gestor + agente). El WhatsApp
    no-oficial reporta si la sesión está REALMENTE conectada (_listo + grupo resuelto); el resto, si
    está bien configurado. Así el cliente ve de un vistazo si algún canal quedó sin arrancar."""
    nombre = c.__class__.__name__
    try:
        if nombre == "WhatsAppNoOficial":
            activo = (getattr(c, "_listo", None) is not None and c._listo.is_set()
                      and getattr(c, "grupo_jid", None) is not None)
            return {"tipo": "whatsapp_no_oficial", "activo": bool(activo),
                    "detalle": (f"grupo {c.grupo_nombre}" if activo else "sin conectar / re-vincular")}
        if nombre == "WhatsAppOficial":
            return {"tipo": "whatsapp_oficial",
                    "activo": bool(getattr(c, "token", "") and getattr(c, "phone_id", "")),
                    "detalle": ""}
        if nombre == "Telegram":
            return {"tipo": "telegram", "activo": bool(c.token and c.chats),
                    "detalle": f"{len(c.chats)} chat(s)"}
        if nombre == "Email":
            return {"tipo": "email", "activo": bool(c.user and c.passwd and c.destinatarios),
                    "detalle": c.user}
        if nombre == "Webhook":
            return {"tipo": "webhook", "activo": bool(c.url), "detalle": ""}
        if nombre == "ElementNotif":
            return {"tipo": "element", "activo": bool(c.token and c.salas),
                    "detalle": f"{len(c.salas)} sala(s)"}
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

    def enviar(self, texto):
        ok = False
        for c in self.canales:
            try:
                ok = c.enviar(texto) or ok
            except Exception:  # noqa: BLE001
                pass
        return ok

    def enviar_mencion(self, texto, telefonos):
        """Aviso @MENCIONANDO a `telefonos` (el TÉCNICO ASIGNADO) en los canales que lo soportan
        (WhatsApp). Los canales que NO tienen menciones (Telegram/email/Teams/Element) reciben el
        MISMO texto sin @ — el aviso nunca se pierde y el texto ya dice a quién está asignado.
        Sin teléfonos, es un envío normal."""
        if not telefonos:
            return self.enviar(texto)
        ok = False
        for c in self.canales:
            fn = getattr(c, "enviar_mencion", None)
            try:
                ok = (fn(texto, telefonos) if fn else c.enviar(texto)) or ok
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
    # Lista de canales (el cliente elige cuáles usar: whatsapp, telegram, email, ...)
    for n in cfg_cliente.get("notificaciones", []):
        if not n.get("enabled", True):
            continue
        tipo = (n.get("tipo") or "").lower()
        if tipo == "telegram":
            canales.append(Telegram(n))
        elif tipo == "email":
            canales.append(Email(n))
        elif tipo in ("teams", "slack", "webhook"):
            canales.append(Webhook(n))
        elif tipo in ("element", "matrix"):
            canales.append(ElementNotif(n))
        elif tipo in ("whatsapp", "whatsapp_oficial", "whatsapp_no_oficial"):
            if wa_compartido is not None:   # ya usamos el WhatsApp compartido -> no duplicar sesión
                continue
            from comun import whatsapp
            # Mapea el tipo del catálogo al modo que espera crear_whatsapp.
            modo = "oficial" if tipo == "whatsapp_oficial" else \
                   ("no_oficial" if tipo == "whatsapp_no_oficial" else n.get("modo", "no_oficial"))
            wa = whatsapp.crear_whatsapp({**n, "enabled": True, "tipo": modo})
            if wa:
                canales.append(wa)
    return Notificadores(canales)
