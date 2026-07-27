#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notificador de WhatsApp (por cliente). Dos modos, elegibles por config:

  tipo="oficial" (DEFAULT para clientes): WhatsApp Business Cloud API de Meta.
      Manda a NÚMEROS individuales (no grupos). Config:
      {"tipo":"oficial","phone_number_id":"...","access_token":"...",
       "destinatarios":["5491111111111", ...]}

  tipo="no_oficial" (uso interno): automatiza WhatsApp Web con tu número (neonize).
      Manda a un GRUPO. Config: {"tipo":"no_oficial","grupo":"SOPORTE_ALERTAS",
      "session":"wa_session.sqlite3"}. Vincular una vez (QR).

Ambos exponen enviar(texto) -> bool. crear_whatsapp(cfg) devuelve el que corresponda.
"""

import os
import re
import json
import time
import shutil
import logging
import threading
import urllib.request

log = logging.getLogger("whatsapp")
BASE = os.path.dirname(os.path.abspath(__file__))

# Silenciar un WARNING RUIDOSO e INOFENSIVO de neonize al leer los metadatos del audio
# ("tags field: 'NoneType' object is not iterable"): NO afecta el envío de la nota de voz (el
# audio sale igual). Se baja a ERROR para no ensuciar el log ni asustar. No toca lo útil.
logging.getLogger("neonize.utils.ffmpeg").setLevel(logging.ERROR)

# Datos PERSISTENTES (sesión de WhatsApp) en una carpeta ESTABLE del usuario, NO dentro
# del proyecto: así mover/copiar la carpeta NO pierde la vinculación (no re-pide QR).
# Configurable con la variable de entorno ITHOS_DATA.
DATA = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
try:
    os.makedirs(DATA, exist_ok=True)
except Exception:  # noqa: BLE001
    DATA = BASE


def _ruta_sesion(nombre):
    """Ruta ESTABLE de la sesión; migra una vinculación previa que esté dentro del
    proyecto (comun/) para no volver a escanear el QR."""
    destino = os.path.join(DATA, nombre)
    if not os.path.exists(destino):
        import glob as _glob
        for viejo in _glob.glob(os.path.join(BASE, nombre) + "*"):
            try:
                shutil.copy2(viejo, os.path.join(DATA, os.path.basename(viejo)))
            except Exception:  # noqa: BLE001
                pass
    return destino


# Prefijo para distinguir lo que manda el BOT (por tu número) de lo que escribís vos.
PREFIJO_ITHOS = "\U0001F916 *ITHOS:* "


def formato_wa(texto):
    """Normaliza al formato de WhatsApp (por si la IA usa markdown):
    **negrita** -> *negrita* ; quita # de títulos ; viñetas '* '/'- ' -> '• '."""
    t = texto or ""
    t = re.sub(r"(?m)^\s*#+\s*", "", t)              # títulos markdown
    t = re.sub(r"(?m)^\s*[*\-]\s+", "• ", t)         # viñetas de lista -> •
    t = re.sub(r"\*\*(.+?)\*\*", r"*\1*", t)         # **negrita** -> *negrita* (WhatsApp)
    t = re.sub(r"`+", "", t)                          # sin bloques de código
    return t.strip()


def formato_plano(texto):
    """Para Email: mantiene las viñetas legibles (•) pero saca los símbolos de
    *negrita*/_cursiva_/~tachado~ (el correo plano no los renderiza)."""
    t = formato_wa(texto or "")           # -> viñetas • y *negrita*
    t = re.sub(r"\*(.+?)\*", r"\1", t)     # sacar negrita
    t = re.sub(r"_(.+?)_", r"\1", t)       # sacar cursiva
    t = re.sub(r"~(.+?)~", r"\1", t)       # sacar tachado
    return t.strip()


def con_prefijo(texto):
    t = formato_wa(texto or "")
    return t if t.startswith(PREFIJO_ITHOS) else PREFIJO_ITHOS + t


def menciona(texto, palabra="ithos"):
    """True si el texto nombra la palabra de activación *ITHOS*, TOLERANDO mala transcripción del
    audio ('itos', 'itho', 'izos', 'hitos', 'istos'…). Antes se exigía la palabra EXACTA y por eso
    a veces (3er audio, etc.) ITHOS no respondía: la transcripción salía apenas distinta. Ahora
    acepta variantes parecidas. La marca es ITHOS: 'ithos' ya NO activa."""
    import re
    import difflib
    p = (palabra or "ithos").lower()
    variantes = ("itos", "itho", "izos", "hitos", "istos", "itzos", "ithus", "iros")
    for w in re.findall(r"[a-záéíóúñ]+", (texto or "").lower()):
        if p in w or w == p or w in variantes \
                or difflib.SequenceMatcher(None, w, p).ratio() >= 0.75:
            return True
    return False


def _num_de_jid(j):
    """Devuelve (numero, es_telefono) de un JID de neonize. es_telefono=False si es LID."""
    if j is None:
        return "", False
    user = str(getattr(j, "User", "") or "")
    srv = str(getattr(j, "Server", "") or "").lower()
    es_tel = srv in ("s.whatsapp.net", "c.us", "") and user.isdigit()
    return user, es_tel


def _numero_remitente(src):
    """TELÉFONO real de quien envió el mensaje, o "" si solo hay LID (id opaco). WhatsApp
    puede ocultar el número con LID: el teléfono viene en el JID cuyo server es
    s.whatsapp.net (Sender o SenderAlt). Solo devolvemos un número de teléfono válido: si
    no hay, quien llama decide el respaldo (p. ej. dueño de la sesión si IsFromMe)."""
    for attr in ("Sender", "SenderAlt"):
        num, es_tel = _num_de_jid(getattr(src, attr, None))
        if es_tel:
            return num
    return ""


def _multipart_media(campos, archivo):
    """multipart/form-data para subir media a la Cloud API de Meta. archivo=(campo, nombre, mime, bytes)."""
    import uuid
    b = "----ithoswa" + uuid.uuid4().hex
    out = b""
    for k, v in campos.items():
        out += (f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    campo, nombre, mime, datos = archivo
    out += (f"--{b}\r\nContent-Disposition: form-data; name=\"{campo}\"; filename=\"{nombre}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + datos + f"\r\n--{b}--\r\n".encode()
    return b, out


class WhatsAppOficial:
    """WhatsApp Business Cloud API (Meta). Manda a números individuales. Respeta el FORMATO del
    cliente ('texto' | 'audio' | 'ambos'): texto y/o NOTA DE VOZ. La nota de voz sigue la doc
    oficial: se sube el audio con POST /{phone_id}/media y se envía un mensaje type=audio con el
    media id. Doc: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media y
    .../messages (audio messages)."""

    def __init__(self, cfg):
        self.phone_id = cfg.get("phone_number_id", "")
        self.token = cfg.get("access_token", "")
        self.destinatarios = cfg.get("destinatarios", [])
        self.version = cfg.get("api_version", "v20.0")
        self.respuesta = (cfg.get("respuesta") or "ambos").lower()   # 'texto' | 'audio' | 'ambos'
        self.tts = None      # callable(texto)->bytes de audio (opcional); si no, voz_tts (edge mp3)

    def enviar(self, texto):
        ok = False
        if self.respuesta in ("texto", "ambos"):
            ok = self._enviar_texto(texto) or ok
        if self.respuesta in ("audio", "ambos"):
            self._mandar_voz(texto)          # nota de voz en segundo plano (sube media + type:audio)
            ok = True
        return ok

    def _enviar_texto(self, texto):
        ok = False
        for num in self.destinatarios:
            payload = {"messaging_product": "whatsapp", "to": str(num),
                       "type": "text", "text": {"body": con_prefijo(texto)}}
            req = urllib.request.Request(
                f"https://graph.facebook.com/{self.version}/{self.phone_id}/messages",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"}, method="POST")
            try:
                urllib.request.urlopen(req, timeout=15)
                ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("WhatsApp oficial: no se pudo enviar a %s: %s", num, e)
        return ok

    def _mandar_voz(self, texto):
        """Genera el audio (tts propio o voz_tts edge MP3), lo SUBE a Meta y manda un mensaje de
        audio a cada destinatario. En SEGUNDO PLANO (no bloquea). Si algo falla y el formato es
        'audio' puro, cae a texto para no dejar sin aviso."""
        def _run(_t=texto):
            try:
                voz = self.tts(_t) if self.tts else None
                if not voz:
                    from comun import voz_tts
                    voz = voz_tts.audio(_t, formato="mp3")     # audio/mpeg: formato soportado por Meta
                media_id = self._subir_media(voz, "audio/mpeg", "ithos.mp3") if voz else None
                if not media_id:
                    if self.respuesta == "audio":
                        self._enviar_texto(_t)
                    return
                for num in self.destinatarios:
                    self._enviar_audio(num, media_id)
            except Exception as e:  # noqa: BLE001
                log.warning("WhatsApp oficial nota de voz: %s", e)
        threading.Thread(target=_run, name="wa-of-voz", daemon=True).start()

    def _subir_media(self, datos, mime, nombre):
        """POST /{phone_id}/media -> media id (doc oficial). None si falla."""
        try:
            b, cuerpo = _multipart_media({"messaging_product": "whatsapp", "type": mime},
                                         ("file", nombre, mime, datos))
            req = urllib.request.Request(
                f"https://graph.facebook.com/{self.version}/{self.phone_id}/media",
                data=cuerpo, method="POST",
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": f"multipart/form-data; boundary={b}"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return (json.loads(r.read().decode("utf-8") or "{}") or {}).get("id")
        except Exception as e:  # noqa: BLE001
            log.warning("WhatsApp oficial: no se pudo subir el audio: %s", e)
            return None

    def _enviar_audio(self, num, media_id):
        """POST /{phone_id}/messages con type=audio y el media id (doc oficial)."""
        try:
            payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
                       "to": str(num), "type": "audio", "audio": {"id": media_id}}
            req = urllib.request.Request(
                f"https://graph.facebook.com/{self.version}/{self.phone_id}/messages",
                data=json.dumps(payload).encode("utf-8"), method="POST",
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("WhatsApp oficial: no se pudo enviar el audio a %s: %s", num, e)
            return False


class WhatsAppNoOficial:
    """neonize (WhatsApp Web con tu número). Manda a un grupo. Vincular con QR una vez.

    CONVERSACIONAL (opcional): si asignás `on_consulta(tipo, contenido, mime[, remitente])->str`,
    ITHOS escucha los mensajes entrantes (audio o texto) y responde por WhatsApp.
    Si además asignás `tts(texto)->wav_bytes`, responde también con una NOTA DE VOZ.
    Reusa la sesión ya vinculada (no vuelve a pedir QR)."""

    def __init__(self, cfg):
        self.session = _ruta_sesion(cfg.get("session", "wa_session.sqlite3"))
        self.grupo_nombre = cfg.get("grupo", "")
        self.grupo_jid = None
        self.client = None
        self.on_consulta = None      # callable(tipo, contenido, mime[, remitente]) -> str
        self.on_audio = None         # callable(audio_bytes, mime, remitente) -> None (voz-id)
        self.transcribir = None      # callable(audio_bytes, mime) -> str (para gatear audios)
        self.ia_cfg = None           # notas de voz de WhatsApp/canales = edge-tts (rápido, gratis).
        #                              La voz de MARCA (Charon) es para los PARLANTES (agente/voz.py),
        #                              no para las notas que se ENVÍAN por WhatsApp.
        self.tts = None              # callable(texto) -> wav_bytes (nota de voz)
        self.on_sesion_cerrada = None  # callable() -> None: la sesión de WhatsApp se cerró/caducó
        #                                (avisar por los OTROS canales; el panel muestra "re-vincular")
        self._desde = time.time()    # solo responder mensajes POSTERIORES a esto
        # En GRUPOS, por seguridad solo responde cuando lo MENCIONAN ("ithos"),
        # para no meterse en la charla de todos. En un chat/grupo DEDICADO al bot,
        # poné "responder_siempre": true. Palabra de activación configurable.
        self.responder_siempre = bool(cfg.get("responder_siempre", False))
        self.palabra = (cfg.get("activacion_palabra") or "ithos").lower()
        # Formato de respuesta elegido por el cliente (panel): 'texto' | 'audio' | 'ambos'.
        self.respuesta = (cfg.get("respuesta") or "ambos").lower()
        self.mi_numero = ""          # teléfono DUEÑO de la sesión (para mensajes IsFromMe)
        self._ultima_respuesta = ""  # para detectar el ECO de la propia nota de voz de ITHOS
        self._listo = threading.Event()
        threading.Thread(target=self._supervisor, name="whatsapp-sup", daemon=True).start()

    def _supervisor(self):
        """No abre neonize hasta que la sesión esté VINCULADA (por QR desde el panel). Así el runtime
        no pelea con el cliente de vinculación por el mismo sqlite ni 'emite un QR a la nada'. Cuando la
        sesión se cierra/caduca, connect() retorna y volvemos a esperar el re-vínculo -> se reengancha
        SOLO sin reiniciar nada (cumple el pedido: sesión caducada -> re-vincular -> vuelve a andar)."""
        try:
            from comun import whatsapp_link as _WL
        except Exception:  # noqa: BLE001
            _WL = None
        while True:
            if _WL is not None:
                while not _WL.vinculado_por_ruta(self.session):
                    self._listo.clear()
                    time.sleep(4)
            self._run()               # crea el cliente y connect() BLOQUEA hasta que se cierre la sesión
            self._listo.clear()
            time.sleep(3)             # sesión cerrada: pausa y a esperar el re-vínculo (marca 'caducada')

    def _run(self):
        try:
            from neonize.client import NewClient
            from neonize.events import ConnectedEv, MessageEv, LoggedOutEv  # noqa: F401
        except Exception as e:  # noqa: BLE001
            log.error("WhatsApp no-oficial deshabilitado (falta neonize): %s", e)
            return
        self.client = NewClient(self.session)

        @self.client.event(ConnectedEv)
        def _on(client, _):  # noqa: ANN001
            # La sesión está viva: dejá la marca en 'vinculado' para que el panel del cliente lo
            # muestre en verde (misma marca que usa la vinculación por QR).
            try:
                from comun import whatsapp_link as _WL
                _WL.marcar_vinculado_ruta(self.session, self.mi_numero)
            except Exception:  # noqa: BLE001
                pass
            threading.Thread(target=self._resolver, daemon=True).start()

        @self.client.event(LoggedOutEv)
        def _out(client, _ev):  # noqa: ANN001
            # WhatsApp cerró la sesión (inactividad, o el cliente la quitó desde el teléfono).
            # Marcamos 'caducada' -> el panel del cliente muestra "sesión caducada" + "Volver a
            # vincular" + QR. Y avisamos por los OTROS canales (por WhatsApp ya no se puede).
            log.warning("WhatsApp: sesión CERRADA/caducada (%s). Hay que re-vincular.",
                        self.grupo_nombre or "sin grupo")
            self._listo.clear()
            try:
                from comun import whatsapp_link as _WL
                _WL.marcar_caducado_ruta(self.session, self.mi_numero)
            except Exception:  # noqa: BLE001
                pass
            if self.on_sesion_cerrada:
                threading.Thread(target=self._safe, args=(self.on_sesion_cerrada,),
                                 daemon=True).start()
            # Cortar para que connect() retorne y el supervisor vuelva a esperar el re-vínculo.
            for metodo in ("disconnect", "stop"):
                try:
                    fn = getattr(client, metodo, None)
                    if fn:
                        fn()
                        break
                except Exception:  # noqa: BLE001
                    continue

        @self.client.event(MessageEv)
        def _msg(client, ev):  # noqa: ANN001
            if self.on_consulta:
                threading.Thread(target=self._on_mensaje, args=(client, ev),
                                 daemon=True).start()
        try:
            self.client.connect()     # BLOQUEA hasta que se cierre la sesión (logout/disconnect)
        except Exception as e:  # noqa: BLE001
            log.warning("WhatsApp: conexión terminada (%s)", e)

    def _on_mensaje(self, client, ev):
        """Mensaje entrante -> ITHOS responde (texto + nota de voz opcional)."""
        try:
            src = ev.Info.MessageSource
            # Timestamp del mensaje (soporta datetime / protobuf / int). Si NO se puede
            # confirmar que es un mensaje NUEVO (posterior a la conexión), se IGNORA.
            # Esto evita responder el HISTORIAL/backlog que WhatsApp entrega al conectar.
            ts = getattr(ev.Info, "Timestamp", None)
            tsec = 0
            try:
                if hasattr(ts, "timestamp"):        # datetime
                    tsec = ts.timestamp()
                elif hasattr(ts, "seconds"):        # protobuf Timestamp
                    tsec = ts.seconds
                elif ts is not None:
                    tsec = float(ts)
            except Exception:  # noqa: BLE001
                tsec = 0
            if tsec < self._desde - 5:              # viejo o desconocido -> NO responder
                return
            chat = src.Chat
            # SOLO el grupo configurado: ignora DMs, otros grupos, estados/broadcast.
            # Así ITHOS NUNCA le escribe a un contacto ni sube estados: solo ESE grupo.
            if not self._es_mi_grupo(chat):
                return
            # Número REAL de quien escribe (para autorizar el conocimiento propietario).
            # WhatsApp usa LID (id opaco) y esconde el teléfono: hay que buscar el JID de
            # teléfono (server s.whatsapp.net) entre Sender/SenderAlt. Si el mensaje es
            # PROPIO (IsFromMe) y no se pudo, se usa el número DUEÑO de la sesión.
            remitente = _numero_remitente(src)
            if not remitente and getattr(src, "IsFromMe", False):
                remitente = self.mi_numero
            msg = ev.Message
            es_audio = msg.HasField("audioMessage")
            texto = "" if es_audio else (msg.conversation or (
                msg.extendedTextMessage.text if msg.HasField("extendedTextMessage") else ""))
            # No responderse a sí mismo (lo que ya mandó el bot con 🤖 ITHOS:).
            if src.IsFromMe and (texto or "").startswith(PREFIJO_ITHOS):
                return
            mencion_req = not self.responder_siempre    # en el grupo, exigir "ithos"
            audio_data = audio_mime = None
            sin_transcribir = False                      # no se pudo transcribir (¿sin IA?)
            if es_audio:                                 # transcribir para poder gatear
                try:
                    audio_data = client.download_any(msg)
                    audio_mime = msg.audioMessage.mimetype or "audio/ogg"
                except Exception:  # noqa: BLE001
                    return
                if self.transcribir:
                    try:
                        texto = self.transcribir(audio_data, audio_mime) or ""
                    except Exception:  # noqa: BLE001
                        texto = ""
                        sin_transcribir = True           # sin IA -> igual respondemos el aviso
                elif mencion_req:
                    return                               # sin transcribir no verifico mención
            # ECO de la PROPIA nota de voz de ITHOS: como el bot manda el audio por MI número
            # (no-oficial), vuelve como IsFromMe. Si transcribe casi igual a lo último que dije,
            # es mi eco -> IGNORAR (no responder = sin loop; no entrenar = no ensucio mi perfil
            # de voz con la voz de la IA). Mi voz REAL (otro contenido) no matchea y sí entrena.
            if es_audio and getattr(src, "IsFromMe", False) and self._parecido(
                    texto, self._ultima_respuesta):
                return
            # Exigir la palabra "ithos" (en el texto o en el audio transcripto). EXCEPCIÓN:
            # si no se pudo transcribir (probablemente sin cuota de IA), respondemos igual para
            # avisar el estado (no nos quedamos mudos).
            if mencion_req and not sin_transcribir and not menciona(texto, self.palabra):
                return
            # Voz-ID: si el audio es del DUEÑO, suma una muestra de su voz (entrenamiento).
            # (Ya descartamos el eco de la IA arriba, así que solo entra tu voz real.)
            if es_audio and audio_data and self.on_audio:
                threading.Thread(target=self._safe, args=(
                    self.on_audio, audio_data, audio_mime, remitente), daemon=True).start()
            if es_audio and not texto:                   # audio sin transcribir -> tal cual
                resp = self._llamar(self.on_consulta, "audio", audio_data, audio_mime, remitente)
            else:
                if not (texto or "").strip():
                    return
                resp = self._llamar(self.on_consulta, "texto", texto, None, remitente)
            if not resp:
                return
            self._ultima_respuesta = resp                # para filtrar el eco de esta nota de voz
            # Formato elegido por el cliente: 'texto' | 'audio' | 'ambos'. OPTIMIZADO: el
            # TEXTO se manda PRIMERO (instantáneo) y la NOTA DE VOZ después (tarda en generarse).
            # (El eco de la propia nota de voz ya se filtra arriba, así que es seguro mandar
            # audio incluso a mensajes propios / en la sesión del dueño.)
            if self.respuesta in ("texto", "ambos"):
                client.send_message(chat, con_prefijo(resp))    # SOLO al grupo (chat)
            if self.respuesta in ("audio", "ambos"):
                # El audio se genera+manda en SEGUNDO PLANO: en respuestas largas la TTS + la subida
                # tardan; así el TEXTO sale instantáneo y ITHOS queda LIBRE para el próximo mensaje
                # (no bloquea el handler). El audio llega apenas está listo, sin trabar nada.
                def _mandar_audio(_resp=resp):
                    try:
                        voz = self.tts(_resp) if self.tts else None   # override propio (si lo asignaron)
                        if not voz:
                            # MP3 nativo de edge: magic lo detecta 'audio/mpeg' y ffmpeg saca duración
                            # -> send_audio arma un AUDIO REPRODUCIBLE inline (con play), no un archivo.
                            from comun import voz_tts
                            voz = voz_tts.audio(_resp, formato="mp3")
                        if not voz:
                            log.warning("WhatsApp audio: no se pudo GENERAR (edge devolvió vacío).")
                            if self.respuesta == "audio":
                                client.send_message(chat, con_prefijo(_resp))   # respaldo texto
                            return
                        try:
                            client.send_audio(chat, voz, ptt=False)   # audioMessage reproducible
                            log.info("WhatsApp audio (reproducible) enviado (%d bytes).", len(voz))
                        except Exception as e_a:  # noqa: BLE001
                            log.info("WhatsApp audio inline falló (%s); mando como documento.",
                                     str(e_a)[:80])
                            client.send_document(chat, voz, filename="Respuesta de ITHOS.mp3",
                                                 mimetype="audio/mpeg", title="Respuesta de ITHOS")
                    except Exception as e:  # noqa: BLE001
                        log.warning("WhatsApp audio: fallo al ENVIAR: %s", e)
                threading.Thread(target=_mandar_audio, name="wa-audio", daemon=True).start()
        except Exception as e:  # noqa: BLE001
            log.warning("WhatsApp conversacional: %s", e)

    @staticmethod
    def _parecido(a, b):
        """True si dos textos son casi iguales (para detectar el ECO de la propia nota de
        voz de ITHOS: su transcripción se parece a lo último que dijo)."""
        na = re.sub(r"[^0-9a-záéíóúñ ]", "", (a or "").lower()).strip()
        nb = re.sub(r"[^0-9a-záéíóúñ ]", "", (b or "").lower()).strip()
        if len(na) < 6 or len(nb) < 6:
            return False
        import difflib
        n = min(len(na), len(nb), 200)
        return difflib.SequenceMatcher(None, na[:n], nb[:n]).ratio() >= 0.55

    @staticmethod
    def _safe(fn, *args):
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            log.warning("callback de audio (voz-id): %s", e)

    @staticmethod
    def _llamar(fn, tipo, contenido, mime, remitente):
        """Llama on_consulta pasándole el remitente si lo acepta (4º arg); si no, sin él."""
        try:
            import inspect
            params = len(inspect.signature(fn).parameters)
        except Exception:  # noqa: BLE001
            params = 3
        return fn(tipo, contenido, mime, remitente) if params >= 4 else fn(tipo, contenido, mime)

    def _es_mi_grupo(self, chat):
        """True SOLO si el chat es el grupo configurado (ignora DMs, otros grupos y
        estados/broadcast). Garantiza que ITHOS no le escriba a ningún contacto."""
        if self.grupo_jid is None or chat is None:
            return False
        try:
            if str(getattr(chat, "Server", "")).lower() == "broadcast":
                return False
            cu, gu = getattr(chat, "User", None), getattr(self.grupo_jid, "User", None)
            if cu is not None and gu is not None:
                return cu == gu
            return str(chat) == str(self.grupo_jid)
        except Exception:  # noqa: BLE001
            return str(chat) == str(self.grupo_jid)

    def _resolver(self):
        time.sleep(5)
        # Número DUEÑO de la sesión (para autorizar mensajes propios aunque WhatsApp use LID).
        try:
            me = self.client.get_me()
            for obj in (me, getattr(me, "JID", None), getattr(me, "PushName", None)):
                num, _ = _num_de_jid(obj)
                if num:
                    self.mi_numero = num
                    break
        except Exception:  # noqa: BLE001
            pass
        for _ in range(15):
            try:
                for g in self.client.get_joined_groups():
                    if g.GroupName.Name == self.grupo_nombre:
                        self.grupo_jid = g.JID
                        self._listo.set()
                        log.info("WhatsApp no-oficial listo (grupo %s%s).", self.grupo_nombre,
                                 f", dueño {self.mi_numero}" if self.mi_numero else "")
                        return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3)

    def enviar(self, texto):
        """Aviso al grupo, respetando el FORMATO elegido por el cliente ('texto' | 'audio' |
        'ambos'): manda texto y/o una NOTA DE VOZ. Igual criterio que las respuestas entrantes,
        así los avisos suenan igual en demo y en producción."""
        if not self._listo.is_set() or self.grupo_jid is None:
            return False
        ok = False
        if self.respuesta in ("texto", "ambos"):
            try:
                self.client.send_message(self.grupo_jid, con_prefijo(texto))
                ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("WhatsApp no-oficial: no se pudo enviar texto: %s", e)
        if self.respuesta in ("audio", "ambos"):
            self._mandar_voz(self.grupo_jid, texto)    # nota de voz en segundo plano
            ok = True
        return ok

    def enviar_mencion(self, texto, telefonos):
        """Manda un aviso al grupo @MENCIONANDO a los `telefonos` (los notifica si están en el grupo).
        Siempre TEXTO (una mención no tiene sentido como nota de voz). Si no se puede construir la
        mención (versión de neonize), cae a texto plano con '@numero'. Usado por el integrador de Planka."""
        if not self._listo.is_set() or self.grupo_jid is None:
            return False
        nums = [re.sub(r"\D", "", str(t)) for t in (telefonos or []) if t]
        prefijo = " ".join(f"@{n}" for n in nums)               # el texto DEBE tener @numero para renderizar
        cuerpo = con_prefijo(((prefijo + " " + texto).strip()) if prefijo else texto)
        jids = [f"{n}@s.whatsapp.net" for n in nums]
        try:
            msg = self._msg_con_menciones(cuerpo, jids)
            if msg is not None:
                self.client.send_message(self.grupo_jid, msg)
                return True
        except Exception as e:  # noqa: BLE001
            log.info("WhatsApp mención (proto) falló (%s); mando texto plano.", str(e)[:80])
        try:
            self.client.send_message(self.grupo_jid, cuerpo)     # cuerpo ya trae el prefijo
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("WhatsApp enviar_mencion: %s", e)
            return False

    @staticmethod
    def _msg_con_menciones(texto, jids):
        """Construye un Message de neonize con contextInfo.mentionedJID. None si la versión/proto no lo
        permite (el caller cae a texto plano). Probamos las rutas de proto conocidas de neonize."""
        for mod in ("neonize.proto.waE2E.WAWebProtobufsE2E_pb2", "neonize.proto.def_pb2",
                    "neonize.proto.Neonize_pb2"):
            try:
                m = __import__(mod, fromlist=["Message", "ExtendedTextMessage", "ContextInfo"])
                return m.Message(extendedTextMessage=m.ExtendedTextMessage(
                    text=texto, contextInfo=m.ContextInfo(mentionedJID=list(jids))))
            except Exception:  # noqa: BLE001
                continue
        return None

    def _mandar_voz(self, chat, texto):
        """Manda `texto` como NOTA DE VOZ en SEGUNDO PLANO (no bloquea): la genera con el tts propio
        o con voz_tts (edge MP3). Si el formato es 'audio' puro y no se pudo generar/enviar, cae a
        texto para no dejar al cliente sin el aviso."""
        self._ultima_respuesta = texto                 # filtra el eco de la propia nota de voz

        def _run(_t=texto):
            try:
                voz = self.tts(_t) if self.tts else None
                if not voz:
                    from comun import voz_tts
                    voz = voz_tts.audio(_t, formato="mp3")
                if not voz:
                    log.warning("WhatsApp nota de voz: no se pudo generar (edge vacío).")
                    if self.respuesta == "audio":
                        try:
                            self.client.send_message(chat, con_prefijo(_t))
                        except Exception:  # noqa: BLE001
                            pass
                    return
                try:
                    self.client.send_audio(chat, voz, ptt=False)   # audioMessage reproducible
                except Exception as e_a:  # noqa: BLE001
                    log.info("WhatsApp nota de voz inline falló (%s); pruebo como documento.",
                             str(e_a)[:80])
                    try:
                        self.client.send_document(chat, voz, filename="ithos.mp3",
                                                  mimetype="audio/mpeg", title="Nota de voz")
                    except Exception:  # noqa: BLE001
                        if self.respuesta == "audio":
                            try:
                                self.client.send_message(chat, con_prefijo(_t))
                            except Exception:  # noqa: BLE001
                                pass
            except Exception as e:  # noqa: BLE001
                log.warning("WhatsApp nota de voz: %s", e)
        threading.Thread(target=_run, name="wa-voz-aviso", daemon=True).start()

    def enviar_documento(self, nombre, datos, mime="application/pdf", caption=""):
        """Manda un archivo (PDF/CSV) al grupo como documento."""
        if not self._listo.is_set() or self.grupo_jid is None:
            return False
        try:
            self.client.send_document(self.grupo_jid, datos, caption=caption or None,
                                      filename=nombre, mimetype=mime, title=nombre)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("WhatsApp documento: %s", e)
            return False


def crear_whatsapp(cfg):
    if not cfg or not cfg.get("enabled"):
        return None
    if (cfg.get("tipo") or "oficial").lower() == "no_oficial":
        return WhatsAppNoOficial(cfg)
    return WhatsAppOficial(cfg)
