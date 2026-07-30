#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Capa CONVERSACIONAL UNIVERSAL. Hace que TODOS los canales puedan RECIBIR y RESPONDER,
no solo WhatsApp: Telegram, Email y WhatsApp oficial (Cloud API), además del WhatsApp
no-oficial (que ya es conversacional en comun/whatsapp.py). Todos comparten:
  - la misma mención de activación ("ITHOS, ...") o responder_siempre por canal,
  - el mismo asistente (comun/conversacion.py) con contexto/acciones por cliente,
  - el mismo REMITENTE -> mismo gateo de conocimiento propietario (comun/conocimiento.py).

Así, TODO lo que se implemente vale para todos los canales y para los DOS modos de
WhatsApp (oficial y no-oficial). El envío usa el formato correcto por canal
(comun/whatsapp.formato_wa para chats, formato_plano para email).

Uso:
  g = GestorCanales(cli_cfg, asistente, hablar=cb_voz_opcional)
  g.iniciar()   # arranca los listeners de los canales conversacionales configurados
"""

import ssl
import time
import json
import email
import imaplib
import smtplib
import logging
import threading
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.header import decode_header

log = logging.getLogger("canales")


def _mencionado(texto, palabra, responder_siempre):
    """¿Este mensaje es para ITHOS? Hay que LLAMARLO ("Hey ITHOS, ..."): nombrarlo suelto no alcanza.
    Mismo criterio en todos los canales y en el micrófono (comun/wake.py). `responder_siempre` es para
    un canal dedicado (p. ej. un chat privado con ITHOS), donde no hace falta la llamada."""
    if responder_siempre:
        return True
    from comun.wake import menciona               # la LLAMADA (tolera mala transcripción del audio)
    return menciona(texto, palabra)


# ================================================================================ Telegram
class TelegramConversacional:
    """Bot de Telegram (Bot API). Escucha por long-polling getUpdates y responde con
    sendMessage. Voz: descarga el archivo y lo transcribe con la IA del asistente.
    Config (en notificaciones[]): {"tipo":"telegram","bot_token":"...","chat_ids":[...],
    "activacion_palabra":"ithos","responder_siempre":false}."""

    def __init__(self, cfg, asistente, hablar=None, ia_cfg=None):
        self.token = cfg.get("bot_token", "")
        self.permitidos = {str(c) for c in cfg.get("chat_ids", [])}
        self.palabra = (cfg.get("activacion_palabra") or "ithos").lower()
        self.responder_siempre = bool(cfg.get("responder_siempre", False))
        self.respuesta = (cfg.get("respuesta") or "texto").lower()   # texto|audio|ambos
        self.ia_cfg = ia_cfg          # nota de voz: Charon (Gemini) primero, si no edge
        self.asis = asistente
        self.hablar = hablar
        self._offset = None

    def _api(self, metodo, params=None, timeout=30):
        url = f"https://api.telegram.org/bot{self.token}/{metodo}"
        data = urllib.parse.urlencode(params or {}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")

    def _descargar(self, file_id):
        info = self._api("getFile", {"file_id": file_id}).get("result", {})
        ruta = info.get("file_path")
        if not ruta:
            return None
        url = f"https://api.telegram.org/file/bot{self.token}/{ruta}"
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()

    def iniciar(self):
        if not self.token:
            return
        threading.Thread(target=self._loop, name="telegram-in", daemon=True).start()
        log.info("Telegram conversacional activo.")

    def _loop(self):
        while True:
            try:
                params = {"timeout": 25}
                if self._offset:
                    params["offset"] = self._offset
                ups = self._api("getUpdates", params, timeout=35).get("result", [])
                for u in ups:
                    self._offset = u["update_id"] + 1
                    threading.Thread(target=self._manejar, args=(u,), daemon=True).start()
            except Exception as e:  # noqa: BLE001
                log.warning("Telegram getUpdates: %s", e)
                time.sleep(5)

    def _manejar(self, u):
        try:
            m = u.get("message") or u.get("channel_post")
            if not m:
                return
            chat_id = str((m.get("chat") or {}).get("id"))
            if self.permitidos and chat_id not in self.permitidos:
                return                                   # solo los chats habilitados
            frm = m.get("from") or {}
            remitente = frm.get("username") or str(frm.get("id") or "")
            texto = m.get("text") or m.get("caption") or ""
            # Voz -> transcribir con la IA del asistente
            voz = m.get("voice") or m.get("audio")
            if voz and not texto and getattr(self.asis, "ia", None):
                try:
                    audio = self._descargar(voz.get("file_id"))
                    texto = self.asis.ia.transcribir(audio, voz.get("mime_type", "audio/ogg")) or ""
                except Exception:  # noqa: BLE001
                    texto = ""
            if not _mencionado(texto, self.palabra, self.responder_siempre):
                return
            resp = self.asis.responder_texto(texto, canal="telegram", remitente=remitente)
            if not resp:
                return
            from comun import whatsapp as _wa
            # Formato elegido por el cliente: texto / audio (nota de voz) / ambos.
            # OPTIMIZADO: el texto va primero (instantáneo) y la nota de voz después.
            if self.respuesta in ("texto", "ambos"):
                self._api("sendMessage", {"chat_id": chat_id, "text": _wa.formato_wa(resp),
                                          "parse_mode": "Markdown"})
            audio_ok = False
            if self.respuesta in ("audio", "ambos"):
                try:
                    from comun import voz_tts
                    ogg = voz_tts.audio(resp, formato="ogg")            # edge 100% gratis (rápido)
                    if ogg:
                        self._enviar_voz(chat_id, ogg)   # sendVoice
                        audio_ok = True
                except Exception as e:  # noqa: BLE001
                    log.warning("Telegram nota de voz: %s", e)
            if self.respuesta == "audio" and not audio_ok:   # pidió solo audio y no salió
                self._api("sendMessage", {"chat_id": chat_id, "text": _wa.formato_wa(resp),
                                          "parse_mode": "Markdown"})
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram manejar: %s", e)

    def _enviar_voz(self, chat_id, ogg_bytes):
        """Envía una NOTA DE VOZ a Telegram (sendVoice, multipart)."""
        import uuid
        b = uuid.uuid4().hex
        cuerpo = (f"--{b}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n"
                  f"{chat_id}\r\n").encode()
        cuerpo += (f"--{b}\r\nContent-Disposition: form-data; name=\"voice\"; "
                   f"filename=\"voz.ogg\"\r\nContent-Type: audio/ogg\r\n\r\n").encode()
        cuerpo += ogg_bytes + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/sendVoice", data=cuerpo,
            headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        urllib.request.urlopen(req, timeout=30)


# =================================================================================== Email
class EmailConversacional:
    """Buzón de Email (IMAP entrante + SMTP saliente). Lee los no leídos y responde al
    remitente. Config (en notificaciones[]): {"tipo":"email","imap_host":"imap.gmail.com",
    "smtp_host":"smtp.gmail.com","smtp_port":465,"usuario":"...","password":"...",
    "responder_siempre":true,"activacion_palabra":"ithos","poll_seg":20}."""

    def __init__(self, cfg, asistente, hablar=None):
        self.cfg = cfg
        self.imap_host = cfg.get("imap_host", "imap.gmail.com")
        self.imap_port = int(cfg.get("imap_port", 993))
        self.smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
        self.smtp_port = int(cfg.get("smtp_port", 465))
        self.usuario = cfg.get("usuario", "")
        self.passwd = cfg.get("password", "")
        self.palabra = (cfg.get("activacion_palabra") or "ithos").lower()
        self.responder_siempre = bool(cfg.get("responder_siempre", True))  # correo: por defecto sí
        self.poll = int(cfg.get("poll_seg", 20))
        self.asis = asistente

    def iniciar(self):
        if not (self.usuario and self.passwd):
            return
        threading.Thread(target=self._loop, name="email-in", daemon=True).start()
        log.info("Email conversacional activo (%s).", self.usuario)

    def _loop(self):
        while True:
            try:
                self._revisar()
            except Exception as e:  # noqa: BLE001
                log.warning("Email revisar: %s", e)
            time.sleep(self.poll)

    @staticmethod
    def _texto(msg):
        if msg.is_multipart():
            for p in msg.walk():
                if p.get_content_type() == "text/plain" and "attachment" not in str(
                        p.get("Content-Disposition")):
                    try:
                        return p.get_payload(decode=True).decode(
                            p.get_content_charset() or "utf-8", "ignore")
                    except Exception:  # noqa: BLE001
                        pass
            return ""
        try:
            return msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", "ignore")
        except Exception:  # noqa: BLE001
            return str(msg.get_payload())

    @staticmethod
    def _asunto(msg):
        try:
            partes = decode_header(msg.get("Subject", ""))
            return "".join(p.decode(e or "utf-8") if isinstance(p, bytes) else p
                           for p, e in partes)
        except Exception:  # noqa: BLE001
            return msg.get("Subject", "")

    def _revisar(self):
        M = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        try:
            M.login(self.usuario, self.passwd)
            M.select("INBOX")
            _, datos = M.search(None, "UNSEEN")
            for num in datos[0].split():
                _, dat = M.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(dat[0][1])
                remitente = email.utils.parseaddr(msg.get("From", ""))[1]
                asunto = self._asunto(msg)
                cuerpo = self._texto(msg)
                texto = f"{asunto}\n{cuerpo}".strip()
                M.store(num, "+FLAGS", "\\Seen")
                if not _mencionado(texto, self.palabra, self.responder_siempre):
                    continue
                resp = self.asis.responder_texto(texto, canal="email", remitente=remitente)
                if resp:
                    self._responder(remitente, asunto, resp)
        finally:
            try:
                M.logout()
            except Exception:  # noqa: BLE001
                pass

    def _responder(self, para, asunto, texto):
        from comun import whatsapp as _wa
        msg = MIMEText(_wa.formato_plano(texto), "plain", "utf-8")
        msg["Subject"] = "Re: " + (asunto or "Consulta")
        msg["From"] = self.usuario
        msg["To"] = para
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port,
                              context=ssl.create_default_context()) as s:
            s.login(self.usuario, self.passwd)
            s.sendmail(self.usuario, [para], msg.as_string())


# ================================================================ WhatsApp oficial (webhook)
class WhatsAppOficialConversacional:
    """WhatsApp Business Cloud API (modo OFICIAL). El ENTRANTE llega por webhook de Meta,
    así que el servidor central debe exponer el endpoint y llamar a procesar(payload).
    Este objeto sabe verificar el webhook y responder al número que escribió."""

    def __init__(self, cfg, asistente, hablar=None, ia_cfg=None):
        self.cfg = cfg
        self.asis = asistente
        self.palabra = (cfg.get("activacion_palabra") or "ithos").lower()
        self.responder_siempre = bool(cfg.get("responder_siempre", True))
        self.verify_token = cfg.get("verify_token", "ithos")
        self.respuesta = (cfg.get("respuesta") or "texto").lower()   # texto|audio|ambos
        self.ia_cfg = ia_cfg          # nota de voz: Charon (Gemini) primero, si no edge

    def verificar(self, params):
        """Handshake GET del webhook de Meta (hub.challenge)."""
        if params.get("hub.verify_token") == self.verify_token:
            return params.get("hub.challenge", "")
        return None

    def procesar(self, payload):
        """Procesa el webhook entrante y responde. Devuelve la respuesta (o None)."""
        try:
            entry = (payload.get("entry") or [{}])[0]
            value = ((entry.get("changes") or [{}])[0]).get("value", {})
            msgs = value.get("messages") or []
            if not msgs:
                return None
            m = msgs[0]
            remitente = m.get("from", "")
            if m.get("type") == "text":
                texto = (m.get("text") or {}).get("body", "")
            elif m.get("type") == "audio" and getattr(self.asis, "ia", None):
                texto = ""      # (descarga de media de Meta: requiere token; se puede sumar)
            else:
                texto = ""
            if not _mencionado(texto, self.palabra, self.responder_siempre):
                return None
            resp = self.asis.responder_texto(texto, canal="whatsapp", remitente=remitente)
            if resp:
                self._responder(remitente, resp)
            return resp
        except Exception as e:  # noqa: BLE001
            log.warning("WhatsApp oficial webhook: %s", e)
            return None

    def _responder(self, numero, texto):
        # Formato elegido por el cliente: texto / audio / ambos. Texto primero (instantáneo),
        # nota de voz después (tarda: genera + sube media).
        from comun import whatsapp as _wa
        if self.respuesta in ("texto", "ambos"):
            self._enviar(numero, {"type": "text", "text": {"body": _wa.con_prefijo(texto)}})
        audio_ok = False
        if self.respuesta in ("audio", "ambos"):
            try:
                from comun import voz_tts
                ogg = voz_tts.audio(texto, formato="ogg")           # edge 100% gratis (rápido)
                mid = self._subir_media(ogg) if ogg else None
                if mid:
                    self._enviar(numero, {"type": "audio", "audio": {"id": mid}})
                    audio_ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("WhatsApp oficial audio: %s", e)
        if self.respuesta == "audio" and not audio_ok:       # pidió solo audio y no salió
            self._enviar(numero, {"type": "text", "text": {"body": _wa.con_prefijo(texto)}})

    def _enviar(self, numero, contenido):
        cfg = self.cfg
        payload = {"messaging_product": "whatsapp", "to": str(numero), **contenido}
        req = urllib.request.Request(
            f"https://graph.facebook.com/{cfg.get('api_version', 'v20.0')}/"
            f"{cfg['phone_number_id']}/messages",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {cfg['access_token']}",
                     "Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:  # noqa: BLE001
            log.warning("WhatsApp oficial enviar: %s", e)

    def _subir_media(self, ogg_bytes):
        """Sube una nota de voz a WhatsApp Cloud API (POST /media) y devuelve su media id."""
        import uuid
        cfg = self.cfg
        b = uuid.uuid4().hex
        def campo(n, v):
            return (f"--{b}\r\nContent-Disposition: form-data; name=\"{n}\"\r\n\r\n{v}\r\n").encode()
        cuerpo = campo("messaging_product", "whatsapp") + campo("type", "audio/ogg")
        cuerpo += (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; "
                   f"filename=\"voz.ogg\"\r\nContent-Type: audio/ogg\r\n\r\n").encode()
        cuerpo += ogg_bytes + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(
            f"https://graph.facebook.com/{cfg.get('api_version', 'v20.0')}/"
            f"{cfg['phone_number_id']}/media", data=cuerpo,
            headers={"Authorization": f"Bearer {cfg['access_token']}",
                     "Content-Type": f"multipart/form-data; boundary={b}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("id")


# ================================================================================ Element/Matrix
class ElementConversacional:
    """Element (Matrix) — chat de equipo OPEN-SOURCE (tipo Slack). ITHOS escucha, responde y
    EJECUTA acciones adentro (leer/cerrar/asignar/posponer tickets, reportes) igual que en
    WhatsApp: el canal es solo el transporte; las acciones son las mismas del agente.
    API oficial client-server de Matrix v3 (HTTP long-poll /sync + envío m.room.message).
    Config (en notificaciones[]): {"tipo":"element","homeserver":"https://matrix.org",
    "access_token":"...","room_ids":["!sala:server"],"activacion_palabra":"ithos",
    "responder_siempre":false,"respuesta":"texto"}. El access_token se saca del bot en Element."""

    def __init__(self, cfg, asistente, hablar=None, ia_cfg=None):
        self.base = (cfg.get("homeserver") or "https://matrix.org").rstrip("/")
        self.token = cfg.get("access_token", "")
        self.salas = {str(r) for r in (cfg.get("room_ids") or [])}   # vacío = todas donde esté
        self.palabra = (cfg.get("activacion_palabra") or "ithos").lower()
        self.responder_siempre = bool(cfg.get("responder_siempre", False))
        self.respuesta = (cfg.get("respuesta") or "texto").lower()
        self.ia_cfg = ia_cfg
        self.asis = asistente
        self.hablar = hablar
        self._since = None
        self._yo = ""            # user-id del bot (para no responderse a sí mismo)

    def _req(self, metodo, path, params=None, body=None, timeout=40):
        url = self.base + "/_matrix/client/v3" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=metodo, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")

    def iniciar(self):
        if not self.token:
            return
        threading.Thread(target=self._loop, name="element-in", daemon=True).start()
        log.info("Element (Matrix) conversacional activo.")

    def _loop(self):
        try:
            self._yo = self._req("GET", "/account/whoami").get("user_id", "")
            self._since = self._req("GET", "/sync", {"timeout": 0}).get("next_batch")  # solo lo NUEVO
        except Exception as e:  # noqa: BLE001
            log.warning("Element sync inicial: %s", e)
        while True:
            try:
                params = {"timeout": 25000, "since": self._since} if self._since else {"timeout": 25000}
                d = self._req("GET", "/sync", params, timeout=40)
                self._since = d.get("next_batch", self._since)
                for sala, cont in ((d.get("rooms") or {}).get("join") or {}).items():
                    if self.salas and sala not in self.salas:
                        continue
                    for ev in ((cont.get("timeline") or {}).get("events") or []):
                        if ev.get("type") == "m.room.message":
                            threading.Thread(target=self._manejar, args=(sala, ev),
                                             daemon=True).start()
            except Exception as e:  # noqa: BLE001
                log.warning("Element /sync: %s", e)
                time.sleep(5)

    def _manejar(self, sala, ev):
        try:
            remitente = ev.get("sender", "")
            if remitente and remitente == self._yo:      # no responderse a sí mismo
                return
            cont = ev.get("content") or {}
            texto = cont.get("body", "") if cont.get("msgtype") in ("m.text", "m.notice", None) else ""
            if not _mencionado(texto, self.palabra, self.responder_siempre):
                return
            resp = self.asis.responder_texto(texto, canal="element", remitente=remitente)
            if resp:
                self._enviar(sala, resp)
        except Exception as e:  # noqa: BLE001
            log.warning("Element manejar: %s", e)

    def _enviar(self, sala, texto):
        """Manda un mensaje a la sala (m.room.message). PUT con txn id único (idempotente)."""
        from comun import whatsapp as _wa
        txn = str(int(time.time() * 1000))
        try:
            self._req("PUT", f"/rooms/{urllib.parse.quote(sala)}/send/m.room.message/{txn}",
                      body={"msgtype": "m.text", "body": _wa.formato_plano(texto)})
        except Exception as e:  # noqa: BLE001
            log.warning("Element enviar: %s", e)


class GestorCanales:
    """Arranca los listeners conversacionales de los canales configurados del cliente.
    WhatsApp no-oficial ya es conversacional aparte (comun/whatsapp.py)."""

    def __init__(self, cli_cfg, asistente, hablar=None):
        self.cfg = cli_cfg
        self.asis = asistente
        self.hablar = hablar
        self.webhooks = {}      # tipo -> objeto (para que el central enganche el webhook)

    def iniciar(self):
        # Autoriza al DUEÑO también por email/telegram si se listan en "autorizados".
        try:
            from comun import conocimiento
            conocimiento.agregar_autorizados(self.cfg.get("autorizados", []))
        except Exception:  # noqa: BLE001
            pass
        ia_cfg = self.cfg.get("ia")     # nota de voz con Charon (Gemini) primero, si no edge
        for n in self.cfg.get("notificaciones", []):
            if not n.get("enabled", True):
                continue
            tipo = (n.get("tipo") or "").lower()
            try:
                if tipo == "telegram":
                    TelegramConversacional(n, self.asis, self.hablar, ia_cfg=ia_cfg).iniciar()
                elif tipo == "email":
                    EmailConversacional(n, self.asis, self.hablar).iniciar()
                elif tipo in ("element", "matrix"):
                    ElementConversacional(n, self.asis, self.hablar, ia_cfg=ia_cfg).iniciar()
                elif tipo in ("whatsapp_oficial", "whatsapp"):
                    self.webhooks["whatsapp_oficial"] = WhatsAppOficialConversacional(
                        n, self.asis, self.hablar, ia_cfg=ia_cfg)
            except Exception as e:  # noqa: BLE001
                log.warning("Canal %s no se pudo iniciar: %s", tipo, e)
        return self
