#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canal de WhatsApp (por cliente). Automatiza WhatsApp Web con el número propio (neonize) y manda a
GRUPOS, cada uno con su ÁMBITO: qué avisos recibe y qué se puede consultar ahí (comun/ambitos.py).

Config:
  {"tipo":"whatsapp_no_oficial", "session":"wa_session.sqlite3",
   "grupos":[{"grupo":"ITHOS_SOPORTE","ambito":"soporte"}, ...]}
Se vincula una vez por QR (comun/whatsapp_link.py) y la sesión queda guardada.

Expone enviar(texto, tipo=None), enviar_mencion(...) y enviar_documento(...).
crear_whatsapp(cfg) devuelve el canal listo.
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


def con_prefijo(texto):
    t = formato_wa(texto or "")
    return t if t.startswith(PREFIJO_ITHOS) else PREFIJO_ITHOS + t


def menciona(texto, palabra="ithos"):
    """True si el texto nombra la palabra de activación *ITHOS* o la LLAMA ("Hey ITHOS"), tolerando
    la mala transcripción del audio ('itos', 'itho', 'izos', 'hitos', 'istos'…), la palabra PARTIDA
    en dos ('hey it hos') y la pronunciación inglesa ('hey ethos'). La lógica vive en comun/wake.py
    (única fuente de verdad, compartida con el MICRÓFONO del agente). La marca es ITHOS."""
    from comun.wake import menciona as _wake_menciona
    return _wake_menciona(texto, palabra)


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


class WhatsAppNoOficial:
    """neonize (WhatsApp Web con tu número). Manda a un grupo. Vincular con QR una vez.

    CONVERSACIONAL (opcional): si asignás `on_consulta(tipo, contenido, mime[, remitente])->str`,
    ITHOS escucha los mensajes entrantes (audio o texto) y responde por WhatsApp.
    Si además asignás `tts(texto)->wav_bytes`, responde también con una NOTA DE VOZ.
    Reusa la sesión ya vinculada (no vuelve a pedir QR)."""

    grupos = []          # se completan en __init__; acá para quien arme la instancia sin pasar por él
    grupo_nombre = ""

    def __init__(self, cfg):
        from comun import ambitos as _AMB
        self.session = _ruta_sesion(cfg.get("session", "wa_session.sqlite3"))
        # VARIOS grupos, cada uno con su ÁMBITO: qué avisos recibe y qué se puede consultar ahí
        # (comun/ambitos.py). Con un `grupo` suelto se comporta como antes: un grupo que recibe todo.
        self.grupos = [dict(g, jid=None) for g in _AMB.grupos_de(cfg)]
        self.grupo_nombre = self.grupos[0]["grupo"] if self.grupos else ""
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
            # SOLO los grupos configurados: ignora DMs, otros grupos, estados/broadcast.
            # Así ITHOS NUNCA le escribe a un contacto ni sube estados: solo ESOS grupos.
            grupo = self._es_mi_grupo(chat)
            if grupo is None:
                return
            # El ÁMBITO del grupo define sobre qué se puede consultar acá (tickets, tablero, todo).
            ambito = grupo.get("ambito")
            # Número REAL de quien escribe (para autorizar el conocimiento propietario).
            # WhatsApp usa LID (id opaco) y esconde el teléfono: hay que buscar el JID de
            # teléfono (server s.whatsapp.net) entre Sender/SenderAlt. Si el mensaje es
            # PROPIO (IsFromMe) y no se pudo, se usa el número DUEÑO de la sesión.
            remitente = _numero_remitente(src)
            if not remitente and getattr(src, "IsFromMe", False):
                remitente = self.mi_numero
            # Nombre visible de quien escribe (PushName): permite identificarlo cuando WhatsApp oculta
            # el teléfono con un LID (respaldo por nombre en integraciones como Planka).
            try:
                nombre_rem = (getattr(ev.Info, "PushName", "") or getattr(src, "PushName", "") or "").strip()
            except Exception:  # noqa: BLE001
                nombre_rem = ""
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
                resp = self._llamar(self.on_consulta, "audio", audio_data, audio_mime,
                                    remitente, nombre_rem, ambito)
            else:
                if not (texto or "").strip():
                    return
                resp = self._llamar(self.on_consulta, "texto", texto, None,
                                    remitente, nombre_rem, ambito)
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
    def _llamar(fn, tipo, contenido, mime, remitente, nombre="", ambito=None):
        """Llama on_consulta con el remitente (4º), el nombre/PushName (5º) y el ÁMBITO del grupo
        (6º) si los acepta; si no, con menos argumentos."""
        try:
            import inspect
            params = len(inspect.signature(fn).parameters)
        except Exception:  # noqa: BLE001
            params = 3
        if params >= 6:
            return fn(tipo, contenido, mime, remitente, nombre, ambito)
        if params >= 5:
            return fn(tipo, contenido, mime, remitente, nombre)
        if params >= 4:
            return fn(tipo, contenido, mime, remitente)
        return fn(tipo, contenido, mime)

    @property
    def grupo_jid(self):
        """El primer grupo resuelto. Se conserva para el estado del canal y la compatibilidad."""
        for g in self.grupos:
            if g.get("jid") is not None:
                return g["jid"]
        return None

    @grupo_jid.setter
    def grupo_jid(self, jid):
        """Compatibilidad: fijar el jid a mano (la demo, los tests) apunta al primer grupo. Si no
        hay ninguno configurado, se crea uno que recibe todo."""
        if not self.grupos:
            from comun import ambitos as _AMB
            self.grupos = [{"grupo": self.grupo_nombre or "", "ambito": _AMB.DEFECTO, "jid": None}]
        self.grupos[0]["jid"] = jid

    def _mismo_jid(self, chat, jid):
        if jid is None or chat is None:
            return False
        try:
            if str(getattr(chat, "Server", "")).lower() == "broadcast":
                return False
            cu, gu = getattr(chat, "User", None), getattr(jid, "User", None)
            if cu is not None and gu is not None:
                return cu == gu
            return str(chat) == str(jid)
        except Exception:  # noqa: BLE001
            return str(chat) == str(jid)

    def _es_mi_grupo(self, chat):
        """El grupo configurado al que pertenece el chat, o None si no es ninguno (un DM, otro
        grupo, un estado). Garantiza que ITHOS sólo hable en los grupos que le indicaron."""
        for g in self.grupos:
            if self._mismo_jid(chat, g.get("jid")):
                return g
        return None

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
                unidos = {g.GroupName.Name: g.JID for g in self.client.get_joined_groups()}
                for g in self.grupos:
                    if g.get("jid") is None and g["grupo"] in unidos:
                        g["jid"] = unidos[g["grupo"]]
                faltan = [g["grupo"] for g in self.grupos if g.get("jid") is None]
                if any(g.get("jid") is not None for g in self.grupos):
                    self._listo.set()
                    log.info("WhatsApp no-oficial listo (%s%s).",
                             ", ".join(f"{g['grupo']}→{g['ambito']}" for g in self.grupos
                                       if g.get("jid") is not None),
                             f", dueño {self.mi_numero}" if self.mi_numero else "")
                    if faltan:
                        log.warning("WhatsApp: no encontré estos grupos (¿el número está adentro?): %s",
                                    ", ".join(faltan))
                    return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3)

    def _destinos(self, tipo):
        """Los grupos que tienen que recibir un aviso de este tipo. Un grupo de consultas no
        recibe ninguno; el de soporte, los de tickets y SLA; el del tablero, los de Planka."""
        from comun import ambitos as _AMB
        return [g for g in self.grupos
                if g.get("jid") is not None and _AMB.recibe(g["ambito"], tipo)]

    def enviar(self, texto, tipo=None):
        """Aviso a los grupos que corresponden según el TIPO (tickets, sla, planka, sistema, voz),
        respetando el FORMATO elegido por el cliente ('texto' | 'audio' | 'ambos'). Sin tipo va a
        todos los grupos que reciban algo — un aviso sin clasificar no se pierde."""
        from comun import ambitos as _AMB
        if not self._listo.is_set():
            return False
        destinos = self._destinos(tipo) if tipo else [
            g for g in self.grupos if g.get("jid") is not None
            and _AMB.AMBITOS[_AMB.normalizar(g["ambito"])]["recibe"]]
        ok = False
        for g in destinos:
            if self.respuesta in ("texto", "ambos"):
                try:
                    self.client.send_message(g["jid"], con_prefijo(texto))
                    ok = True
                except Exception as e:  # noqa: BLE001
                    log.warning("WhatsApp no-oficial (%s): no se pudo enviar texto: %s",
                                g["grupo"], e)
            if self.respuesta in ("audio", "ambos"):
                self._mandar_voz(g["jid"], texto)      # nota de voz en segundo plano
                ok = True
        return ok

    def enviar_mencion(self, texto, telefonos, tipo=None):
        """Aviso @MENCIONANDO a los `telefonos` (los notifica si están en el grupo), a los grupos
        que corresponden según el TIPO. Siempre TEXTO (una mención no tiene sentido como nota de
        voz). Si no se puede construir la mención (versión de neonize), cae a texto plano."""
        if not self._listo.is_set():
            return False
        destinos = self._destinos(tipo) if tipo else [g for g in self.grupos if g.get("jid")]
        if not destinos:
            return False
        nums = [re.sub(r"\D", "", str(t)) for t in (telefonos or []) if t]
        prefijo = " ".join(f"@{n}" for n in nums)               # el texto DEBE tener @numero para renderizar
        cuerpo = con_prefijo(((prefijo + " " + texto).strip()) if prefijo else texto)
        jids = [f"{n}@s.whatsapp.net" for n in nums]
        ok = False
        for g in destinos:
            try:
                msg = self._msg_con_menciones(cuerpo, jids)
                if msg is not None:
                    self.client.send_message(g["jid"], msg)
                    ok = True
                    continue
            except Exception as e:  # noqa: BLE001
                log.info("WhatsApp mención (proto) falló (%s); mando texto plano.", str(e)[:80])
            try:
                self.client.send_message(g["jid"], cuerpo)      # cuerpo ya trae el prefijo
                ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("WhatsApp enviar_mencion (%s): %s", g["grupo"], e)
        return ok

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
    """El canal de WhatsApp del cliente. Hoy sólo el NO OFICIAL (neonize, con el número propio y
    los grupos por ámbito). Si algún día hace falta la Cloud API de Meta, se agrega acá otra clase
    con la misma interfaz (`enviar`, `enviar_mencion`, `enviar_documento`)."""
    if not cfg or not cfg.get("enabled"):
        return None
    return WhatsAppNoOficial(cfg)
