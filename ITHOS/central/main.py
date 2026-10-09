#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS Central — cerebro multi-cliente en la nube.

Toda la configuración por cliente vive en clientes.json (copy-paste, sin código).
Cada cliente: su API key de IA, GLPI, WhatsApp, límite de cuota, voz, etc.

WebSocket (/ws): los agentes se autentican con su API key, reciben COMANDOS (voz).
Por cliente con GLPI "central": vigila + triagea sus tickets y empuja la voz al
agente. Si la cuota gratuita de IA se agota, avisa por voz + WhatsApp con el tiempo
estimado de reseteo.
"""

import sys
import os
import hmac
import json
import asyncio
import logging

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request  # noqa: E402

import protocolo as P            # noqa: E402
import procesador                # noqa: E402
import integrador_glpi           # noqa: E402
from registro import Registro    # noqa: E402
from comun import cuota as Cuota        # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ithos-central")

from comun import version as _VER          # noqa: E402
app = FastAPI(title="ITHOS Gestor", version=_VER.GESTOR_VERSION)
# Evita que el equipo se suspenda mientras el central corre (la pantalla puede bloquearse igual).
try:
    from comun.despierto import mantener_despierto
    mantener_despierto()
except Exception:  # noqa: BLE001
    pass
# Calienta edge-tts para que la 1ª nota de voz salga rápida (no paga el arranque en frío).
try:
    from comun import voz_tts as _VTTS
    _VTTS.precalentar()
except Exception:  # noqa: BLE001
    pass
registro = Registro()
conexiones = {}


def _dir_datos():
    return os.environ.get("ITHOS_DATA") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..")


def _ruta_terminales(cliente):
    slug = "".join(ch for ch in str(cliente) if ch.isalnum() or ch in "-_")[:40] or "cli"
    return os.path.join(_dir_datos(), f"terminales_{slug}.json")


_terminales_vistas = {}   # cliente -> set(device) ya persistidas (evita reescribir el archivo)


def _guardar_terminales_descubiertas(cliente, terminales):
    """MERGE (unión) de terminales descubiertas en el volumen compartido con el panel. Acumula tanto la
    discovery MASIVA (IVMS lista los device de la DB al arrancar) como las que aparecen EN VIVO por cada
    fichaje (cualquier marca) -> así el cliente las mapea (entrada/salida/sala) sin adivinar los nombres."""
    import time as _t
    ruta = _ruta_terminales(cliente)
    prev = _terminales_vistas.get(cliente)
    if prev is None:
        prev = set()
        try:
            with open(ruta, encoding="utf-8") as f:
                prev = {str(t).strip() for t in json.load(f).get("terminales", []) if str(t).strip()}
        except Exception:  # noqa: BLE001
            pass
    nuevas = {str(t).strip() for t in terminales if str(t).strip()}
    todas = prev | nuevas
    _terminales_vistas[cliente] = todas
    if todas == prev:
        return                                    # nada nuevo -> no reescribir
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"terminales": sorted(todas), "ts": int(_t.time())}, f)
    log.info("Terminales de %s: +%d (total %d) -> %s", cliente, len(nuevas - prev), len(todas),
             ", ".join(sorted(nuevas - prev)[:8]))


# =============================== MANTENIMIENTO ===============================
# Cuando el Gestor se detiene (deploy/reinicio/mantenimiento), avisamos al cliente por SUS canales que
# ITHOS entra en mantenimiento y que vuelve enseguida; al reconectar el agente, le avisamos que ya está
# disponible. Así el cliente nunca cree que se rompió. (Producción: pedido de Brian.)
notificadores_activos = {}   # cliente -> objeto de canales (para avisar en el shutdown, best-effort)

MSG_MANTENIMIENTO = ("ITHOS entra en mantenimiento por unos minutos. A la brevedad estará reconectado "
                     "y funcionando con normalidad. Disculpá las molestias.")
MSG_DISPONIBLE = "ITHOS ya está disponible y funcionando con normalidad. Gracias por la espera."


def _ruta_mantenimiento():
    return os.path.join(_dir_datos(), "mantenimiento.json")


def _flags_mantenimiento():
    try:
        with open(_ruta_mantenimiento(), encoding="utf-8") as f:
            return set(json.load(f).get("pendientes", []))
    except Exception:  # noqa: BLE001
        return set()


def _set_flag_mantenimiento(cliente, activo):
    """Marca (persistente) que a un cliente hay que avisarle 'disponible' cuando su agente reconecte."""
    flags = _flags_mantenimiento()
    if activo:
        flags.add(cliente)
    else:
        flags.discard(cliente)
    try:
        with open(_ruta_mantenimiento(), "w", encoding="utf-8") as f:
            json.dump({"pendientes": sorted(flags)}, f)
    except Exception as e:  # noqa: BLE001
        log.warning("mantenimiento flag: %s", e)


def _avisar_mantenimiento():
    """Avisa 'ITHOS en mantenimiento' a los clientes conectados por SUS canales (WhatsApp/email/Telegram/
    ...) y deja pendiente el aviso de 'disponible' para cuando su agente reconecte. Se llama ANTES de
    detener/reiniciar el Gestor (endpoint /api/mantenimiento, lo invoca el deploy actualizar.sh). No se
    hace en el apagado de uvicorn porque ahí las conexiones ya se cerraron y el registro quedó vacío."""
    avisados = 0
    for cliente, wa in list(notificadores_activos.items()):
        try:
            if wa:
                wa.enviar(MSG_MANTENIMIENTO, tipo=AV.SISTEMA)   # a TODOS sus canales
                avisados += 1
        except Exception:  # noqa: BLE001
            pass
        _set_flag_mantenimiento(cliente, True)
    log.info("Mantenimiento: avisado a %d cliente(s) por sus canales.", avisados)
    return avisados


@app.post("/api/mantenimiento")
def api_mantenimiento():
    """(Interno, red de Docker) Se llama JUSTO ANTES de detener/reiniciar el Gestor para avisarle al
    cliente. No se expone al público (Caddy solo rutea /ws y /webhook al central)."""
    return {"ok": True, "avisados": _avisar_mantenimiento()}


# =============================== SALUD / ESTADO =============================
# En producción TODO debe estar 100% activo (todos los canales + micrófono + integrador). El gestor
# junta el estado de los CANALES (los maneja él) con lo que reporta el AGENTE (micrófono/integrador/voz)
# -> el panel y la GUI del agente lo muestran, así se ve si algo quedó sin arrancar.
estado_agente = {}   # cliente -> {microfono, integrador, integrador_tipo, voz, ts}


@app.get("/api/salud")
def salud_cliente(cliente: str = ""):
    """Estado de salud de un cliente: agente conectado, estado de cada canal (WhatsApp/email/...),
    micrófono e integrador. Lo consume el panel (proxy /api/salud/<api_key>)."""
    wa = notificadores_activos.get(cliente)
    canales = []
    try:
        canales = wa.estado() if wa else []
    except Exception:  # noqa: BLE001
        canales = []
    est = estado_agente.get(cliente, {})
    conectado = cliente in conexiones
    return {"agente_conectado": conectado,
            "canales": canales,
            "microfono": est.get("microfono") if conectado else False,
            "mic_habilitado": est.get("mic_habilitado"),
            "integrador": est.get("integrador") if conectado else False,
            "integrador_tipo": est.get("integrador_tipo", ""),
            "voz": est.get("voz") if conectado else False,
            "ts": est.get("ts")}


@app.get("/")
def salud():
    # La versión sale de comun/version.py (la que sube sola en cada deploy), no de un número
    # escrito a mano que se queda viejo: este endpoint decía "0.5" con el Gestor en 1.1.x.
    return {"servicio": "ITHOS Central", "version": _VER.GESTOR_VERSION,
            "protocolo": _VER.PROTOCOL_VERSION,
            "revision": _VER.revision_desplegada(),
            "clientes_registrados": registro.total(),
            "clientes_conectados": sorted(conexiones.keys())}


@app.get("/api/conectados")
def conectados():
    """Estado en tiempo real: qué agentes están conectados ahora mismo."""
    return {"conectados": sorted(conexiones.keys())}


# ---- Vinculación de WhatsApp NO-OFICIAL por QR (la usa el PANEL/ALTA con su propia auth) --------
# Corren ACÁ (el central) porque es donde vive neonize. El panel hace de intermediario (auth admin/
# cliente/token de alta) y resuelve api_key -> id de sesión. Estos endpoints NO se publican solos:
# Caddy solo rutea /ws y /webhook al central; el resto va al panel, que llama a esto por la red
# interna. Aun así validan que la sesión sea un id acotado.
def _sesion_valida(s: str) -> str:
    s = "".join(ch for ch in str(s or "") if ch.isalnum() or ch in "-_")[:48]
    return s


@app.post("/api/whatsapp/vincular")
async def wa_vincular(request: Request):
    from fastapi.responses import JSONResponse
    from comun import whatsapp_link as WL
    sesion = _sesion_valida((await request.json()).get("sesion", ""))
    if not sesion:
        return JSONResponse({"estado": "error", "error": "falta la sesión"}, status_code=400)
    return WL.vincular(sesion)


@app.get("/api/whatsapp/estado")
def wa_estado(sesion: str = ""):
    from comun import whatsapp_link as WL
    sesion = _sesion_valida(sesion)
    if not sesion:
        return {"estado": "error", "error": "falta la sesión"}
    return WL.estado(sesion)


@app.post("/api/whatsapp/desvincular")
async def wa_desvincular(request: Request):
    from fastapi.responses import JSONResponse
    from comun import whatsapp_link as WL
    sesion = _sesion_valida((await request.json()).get("sesion", ""))
    if not sesion:
        return JSONResponse({"ok": False, "error": "falta la sesión"}, status_code=400)
    return WL.desvincular(sesion)




@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    cliente = None
    tarea = None
    tareas_extra = []
    loop = asyncio.get_running_loop()
    try:
        auth = json.loads(await websocket.receive_text())
        if auth.get("tipo") != P.AUTH:
            await websocket.send_json({"tipo": P.AUTH_ERROR, "motivo": "falta auth"})
            return
        conf = registro.validar(auth.get("api_key"))
        if not conf:
            await websocket.send_json({"tipo": P.AUTH_ERROR, "motivo": "api_key inválida"})
            return
        # Autenticación del AGENTE por EMPRESA: además de la api_key, si el cliente tiene un
        # 'agente_token' (contraseña de agente que le pasamos en el alta), el agente DEBE mandarlo
        # y coincidir (comparación en tiempo constante). Así un agente trucho con solo la api_key
        # NO entra. Compat: clientes sin agente_token siguen entrando con la api_key sola.
        _atok = conf.get("agente_token")
        if _atok and not hmac.compare_digest(str(auth.get("agente_token", "")), str(_atok)):
            await websocket.send_json({"tipo": P.AUTH_ERROR, "motivo": "token de agente inválido"})
            log.warning("Agente RECHAZADO (token inválido) para %s", conf.get("nombre"))
            return
        # Conexión de PRUEBA (el botón "Probar y guardar" de la app): valida las credenciales y corta,
        # SIN registrarse en `conexiones` ni arrancar nada. Así NO molesta al agente real que ya está
        # conectado (antes esta prueba lo echaba y causaba el flapping 1<->0). El agente singleton
        # (mutex) garantiza que la conexión real es una sola: no hace falta cerrar "la vieja".
        if auth.get("test"):
            await websocket.send_json({"tipo": P.AUTH_OK, "cliente": conf["nombre"], "prueba": True})
            return
        cliente = conf["nombre"]
        conexiones[cliente] = websocket
        # Handshake de VERSIÓN (Gestor <-> Agente): leemos la versión/protocolo del agente y
        # devolvemos la del gestor. Compat hacia atrás: un agente viejo (sin versión) igual entra.
        from comun import version as VER
        ag_ver = auth.get("agente_version") or "?"
        ag_proto = auth.get("protocol_version")
        # El GESTOR le MANDA al agente TODA su config (thin agent): la voz (Charon con la key del
        # cliente), el integrador de acceso local y el micrófono. Así el agente solo guarda api_key +
        # contraseña; el resto lo asigna el gestor por empresa.
        _ia = conf.get("ia") or {}
        _voz = _ia.get("voz")
        _voz_cfg = _voz if isinstance(_voz, dict) else {
            "proveedor": _ia.get("proveedor", "gemini"), "voz": _voz or "Charon",
            "gemini_api_key": _ia.get("gemini_api_key", "")}
        _integ = conf.get("integrador")
        _integ_dict = ({"tipo": _integ, **(conf.get("integrador_config") or {})}
                       if isinstance(_integ, str) and _integ not in ("", "ninguno")
                       else (_integ if isinstance(_integ, dict) else None))
        await websocket.send_json({
            "tipo": P.AUTH_OK, "cliente": cliente,
            "gestor_version": VER.GESTOR_VERSION, "protocol_version": VER.PROTOCOL_VERSION,
            "agente_min_version": VER.AGENTE_MIN_VERSION,
            "config": {"voz": _voz_cfg, "idioma": conf.get("idioma", "es-AR"),
                       "velocidad": conf.get("velocidad", 1.25), "integrador": _integ_dict,
                       "microfono": conf.get("microfono") or {}}})
        log.info("Agente conectado: %s (agente v%s, protocolo %s; gestor v%s%s)",
                 cliente, ag_ver, ag_proto, VER.GESTOR_VERSION,
                 "" if VER.compat_protocolo(ag_proto) else " · PROTOCOLO INCOMPATIBLE, actualizar agente")

        async def enviar(cmd):
            await websocket.send_json({"tipo": P.COMANDO, **cmd})

        # Canales de notificación del cliente (los que ELIGIÓ: whatsapp/telegram/
        # email/teams/slack). Un solo objeto que manda a todos.
        from comun import notificadores as NOTIF
        from comun import ambitos as AV      # tipos de aviso -> a qué grupo va cada uno
        # Sesión de WhatsApp ESTABLE y AISLADA por cliente (multi-tenant): el runtime usa EXACTAMENTE
        # el mismo archivo que la vinculación por QR del panel/alta. Sin esto, dos clientes chocarían
        # sobre 'wa_session.sqlite3' y lo vinculado no serviría para enviar.
        try:
            from comun import whatsapp_link as _WL
            _archivo_wa = _WL.archivo_sesion(_WL.sesion_de_cliente(conf))
            if isinstance(conf.get("whatsapp"), dict):
                conf["whatsapp"]["session"] = _archivo_wa
            for _n in conf.get("notificaciones", []) or []:
                if (_n.get("tipo") or "").lower() in ("whatsapp", "whatsapp_no_oficial"):
                    _n["session"] = _archivo_wa
        except Exception:  # noqa: BLE001
            pass
        # En DEMO, el proceso de la demo maneja los canales externos (WhatsApp/Telegram/Email)
        # de forma interactiva; el central NO los abre para no chocar con la MISMA sesión
        # (p.ej. dos clientes neonize sobre el mismo WhatsApp). Sigue haciendo tickets/voz/consultas.
        wa = None if os.environ.get("ITHOS_DEMO") else NOTIF.crear_notificadores(conf)
        # Si la sesión de WhatsApp NO-OFICIAL se cierra/caduca (inactividad), avisamos por los OTROS
        # canales + por voz, y el panel del cliente mostrará "sesión caducada" + "Volver a vincular".
        if wa and not os.environ.get("ITHOS_DEMO"):
            def _aviso_wa_cerrada():
                msg = ("Se cerró la sesión de WhatsApp de ITHOS (probablemente por inactividad). "
                       "Entrá al panel y tocá 'Volver a vincular' para escanear el QR de nuevo.")
                log.warning("[WA %s] sesión cerrada: avisando por otros canales", cliente)
                try:
                    # El canal WhatsApp está caído (limpiamos _listo en el logout), así que enviar()
                    # salta WhatsApp y entrega por los OTROS canales (email/telegram/etc).
                    wa.enviar(msg, tipo=AV.SISTEMA)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    asyncio.run_coroutine_threadsafe(
                        enviar({"accion": "decir", "texto": msg, "cachear": False}), loop)
                except Exception:  # noqa: BLE001
                    pass
            try:
                for _c in getattr(wa, "canales", []):
                    if _c.__class__.__name__ == "WhatsAppNoOficial":
                        _c.on_sesion_cerrada = _aviso_wa_cerrada
            except Exception:  # noqa: BLE001
                pass

        # MANTENIMIENTO: registramos los canales del cliente (para avisar 'mantenimiento' si el Gestor se
        # detiene) y, si venimos de un mantenimiento (flag pendiente), le avisamos que YA está disponible.
        if wa and not os.environ.get("ITHOS_DEMO"):
            notificadores_activos[cliente] = wa
            if cliente in _flags_mantenimiento():
                # 'Disponible' se avisa cuando algún canal esté REALMENTE activo (WhatsApp tarda ~10s en
                # conectar): si lo mandáramos ya, en un cliente WhatsApp-only se perdería. Espera hasta 30s.
                async def _avisar_disponible():
                    for _ in range(30):
                        try:
                            if wa.hay_activo():
                                break
                        except Exception:  # noqa: BLE001
                            pass
                        await asyncio.sleep(1)
                    try:
                        await asyncio.to_thread(lambda: wa.enviar(MSG_DISPONIBLE, tipo=AV.SISTEMA))
                        log.info("Mantenimiento: avisado 'disponible' a %s.", cliente)
                    except Exception:  # noqa: BLE001
                        pass
                    _set_flag_mantenimiento(cliente, False)
                tareas_extra.append(asyncio.create_task(_avisar_disponible()))

        # Aviso de cuota: por voz (el agente cae a edge si Gemini está caído) + canales.
        def notificar_cuota(nivel, mensaje):
            log.warning("[CUOTA %s] %s: %s", nivel, cliente, mensaje)
            if wa:
                try:
                    wa.enviar(mensaje, tipo=AV.SISTEMA)
                except Exception:  # noqa: BLE001
                    pass
            try:
                asyncio.run_coroutine_threadsafe(
                    enviar({"accion": "decir", "texto": mensaje, "cachear": False}), loop)
            except Exception:  # noqa: BLE001
                pass

        # IA + gestor de cuota del cliente (compartidos por triage y asistente).
        gestor = ia_texto = asistente = None
        ia = conf.get("ia")
        gl = conf.get("integrador_glpi")
        if ia:
            gestor = Cuota.GestorCuota(
                cliente, limite_diario=ia.get("limite_diario", 250),
                avisar_en=ia.get("avisar_en", 15),
                ilimitada=ia.get("ilimitada", False), notificar=notificar_cuota,
                zona=conf.get("zona_horaria", "America/Argentina/Buenos_Aires"),
                cadena=Cuota.cadena_cfg(ia))    # cadena REAL del cliente (gemini→cerebras→groq…), NO hardcodeada
            from comun import ia as IA
            ia_texto = IA.crear_texto({**ia, "idioma": conf.get("idioma", "es-AR")},
                                      gestor=gestor)
            # Asistente conversacional (voz/ITHOS + audio de WhatsApp). Multi-sistema:
            # herramientas/acciones sobre el sistema de tickets del cliente (el que sea)
            # + KB automática por cliente (aislada). Se arma si el cliente tiene tickets.
            tiene_tickets = bool((conf.get("tickets") or {}).get("tipo") or
                                 (gl and gl.get("glpi_ithos_token")))
            if tiene_tickets:
                from comun import conversacion
                from comun import memoria as MEM
                herr = conversacion.herramientas_tickets(conf)
                # avisar: cuando el admin cambia el estado de un ticket por voz/chat (en espera/cerrar/
                # reabrir/posponer), se notifica al grupo de WhatsApp/canales (igual que el ciclo automático).
                acc = conversacion.acciones_tickets(
                    conf, avisar=((lambda m: wa.enviar(m, tipo=AV.TICKETS)) if wa else None))
                kb_dir = conf.get("kb_dir")
                try:
                    import kb_auto
                    kb_dir = kb_dir or kb_auto.kb_dir(cliente)
                    kb_auto.refrescar_async(conf, cliente)   # regenera en background
                except Exception:  # noqa: BLE001
                    pass
                asistente = conversacion.Asistente(
                    ia_texto, herr, kb_dir=kb_dir, empresa=cliente,
                    memoria=MEM.Memoria(cliente), acciones=acc,
                    zona=conf.get("zona_horaria", "America/Argentina/Buenos_Aires"),
                    gestor=gestor)

                # Conversación en TODOS los canales del cliente (Telegram/Email/WhatsApp
                # oficial), además del WhatsApp no-oficial. Misma mención, remitente y gateo.
                def _voz(txt):
                    try:
                        asyncio.run_coroutine_threadsafe(
                            enviar({"accion": "decir", "texto": txt, "cachear": False}), loop)
                    except Exception:  # noqa: BLE001
                        pass
                if not os.environ.get("ITHOS_DEMO"):     # en demo los canales los maneja la demo
                    # WhatsApp NO-OFICIAL conversacional: engancha el asistente para que RESPONDA los
                    # mensajes/audios del grupo (antes SOLO posteaba tickets/reportes) y ENTRENE la voz
                    # del dueño (voz-id). Esto solo estaba en la demo -> en producción no contestaba.
                    def _wa_on_consulta(tipo, contenido, mime=None, remitente=None, ambito=None):
                        try:
                            if tipo == "audio" and hasattr(asistente, "responder_audio"):
                                r = asistente.responder_audio(contenido, mime or "audio/ogg",
                                                              canal="whatsapp", remitente=remitente,
                                                              ambito=ambito)
                                return r.get("respuesta", "") if isinstance(r, dict) else (r or "")
                            return asistente.responder_texto(contenido, canal="whatsapp",
                                                             remitente=remitente, ambito=ambito)
                        except Exception as e:  # noqa: BLE001
                            log.warning("WhatsApp consulta %s: %s", cliente, e)
                            return ""

                    def _wa_entrenar_voz(audio_bytes, mime, remitente):
                        # Solo los NÚMEROS del dueño entrenan la voz (voz-id). El grupo no.
                        try:
                            from comun import conocimiento as _K
                            if not _K.esta_autorizado(remitente, "whatsapp"):
                                return
                            from comun import audio as _AUD, vozid as _V
                            pcm = _AUD.decodificar(audio_bytes, mime, fs=16000)
                            if len(pcm) == 0:
                                return
                            n, _suf, recien = _V.enrolar(pcm, fs=16000)
                            log.info("[voz-id %s] muestra %d/%d de la voz del dueño", cliente, n,
                                     _V.MIN_MUESTRAS)
                            if recien:
                                try:
                                    wa.enviar("Ya tengo suficientes muestras de tu voz. Reconocimiento "
                                              "por voz ACTIVO: de acá en más verifico que seas vos.",
                                              tipo=AV.VOZ)
                                except Exception:  # noqa: BLE001
                                    pass
                        except Exception as e:  # noqa: BLE001
                            log.warning("voz-id %s: %s", cliente, e)

                    # PLANKA (solo INTELLIHELP): el asistente de WhatsApp primero intenta MOVER una
                    # tarjeta del tablero del equipo; si el mensaje no es sobre tareas, sigue el
                    # asistente normal. El trigger "ithos" ya lo aplicó el handler del grupo.
                    _planka = None
                    if conf.get("planka") and ia_texto:
                        try:
                            import planka_integrador as _PKI
                            _planka = _PKI.PlankaIntegrador(
                                conf["planka"], ia_texto,   # el OBJETO de IA (tiene .chat), no el dict de config
                                zona=conf.get("zona_horaria", "America/Argentina/Buenos_Aires"))
                        except Exception as e:  # noqa: BLE001
                            log.warning("Planka integrador %s: %s", cliente, e)

                    def _consulta(tipo, contenido, mime, remitente=None, nombre=None, ambito=None,
                                  _orig=_wa_on_consulta, _pk=_planka):
                        # Cada grupo tiene su ÁMBITO: en el del tablero sólo se habla de tareas, en el
                        # de soporte sólo de tickets, y en el de consultas se puede todo. Así nadie
                        # recibe lo que no le sirve ni pregunta donde no le van a contestar.
                        from comun import ambitos as AMB
                        tema = AMB.responde(ambito)
                        # Planka primero: identifica al remitente por teléfono o, si WhatsApp lo ocultó
                        # con un LID, por nombre (PushName). Si no es sobre el tablero, sigue el asistente.
                        if (_pk is not None and tipo == "texto" and contenido
                                and (remitente or nombre) and tema in (AMB.PLANKA, AMB.TODO)):
                            try:
                                r = _pk.interpretar(remitente, contenido, nombre)
                                if r:
                                    return r
                            except Exception as e:  # noqa: BLE001
                                log.warning("Planka interpretar %s: %s", cliente, e)
                        if tema == AMB.PLANKA:
                            # Grupo del tablero: si el mensaje no era una orden de tareas, se dice
                            # dónde preguntar en vez de contestar cualquier cosa.
                            return AMB.fuera_de_alcance(AMB.PLANKA, getattr(_wa_canal, "grupos", []))
                        return _orig(tipo, contenido, mime, remitente, ambito)

                    _wa_canal = None
                    try:
                        for _c in getattr(wa, "canales", []):
                            if _c.__class__.__name__ == "WhatsAppNoOficial":
                                _wa_canal = _c
                                _c.on_consulta = _consulta             # Planka primero, luego el asistente
                                _c.on_audio = _wa_entrenar_voz         # entrena la voz del dueño
                                _c.transcribir = asistente.ia.transcribir  # gatea audios por "ithos"
                                _c.ia_cfg = conf.get("ia")             # nota de voz Charon->edge
                                log.info("WhatsApp no-oficial CONVERSACIONAL activo para %s.", cliente)
                    except Exception as e:  # noqa: BLE001
                        log.warning("No se pudo activar WhatsApp conversacional %s: %s", cliente, e)
                    if _planka is not None and _wa_canal is not None:
                        tareas_extra.append(asyncio.create_task(
                            _planka.vigilar(lambda t, tels: _wa_canal.enviar_mencion(
                                t, tels, tipo=AV.PLANKA))))
                        log.info("Planka integrador ARRANCADO para %s.", cliente)

        # Integrador GLPI + triage (lado central).
        if gl and gl.get("ubicacion", "central") == "central":
            tri = None
            if gl.get("glpi_ithos_token") and ia:
                import triage as T
                # El triage necesita la ZONA y el HORARIO de atención del cliente (tickets fuera de
                # horario -> En espera + reapertura automática) y el NOMBRE (para agendar la reapertura).
                gl["zona_horaria"] = conf.get("zona_horaria", "America/Argentina/Buenos_Aires")
                gl["nombre_cliente"] = conf.get("nombre", "cliente")
                if conf.get("horario_atencion"):
                    gl["horario_atencion"] = conf["horario_atencion"]
                # TÉCNICOS del cliente: para @MENCIONAR por WhatsApp al que quedó ASIGNADO (solo a
                # él) en los avisos del ticket y en la escalada por falta de respuesta del cliente.
                if conf.get("tecnicos"):
                    gl["tecnicos"] = conf["tecnicos"]
                tri = T.Triage(gl, ia, gestor=gestor)
            tarea = asyncio.create_task(
                integrador_glpi.vigilar(gl, enviar, triage=tri, wa=wa,
                                        nombre_cliente=cliente))

        # Reportes proactivos (diario/semanal/mensual) por los canales del cliente.
        if conf.get("reportes", {}).get("enabled") and gl:
            import reportes_programados as RP
            tareas_extra.append(asyncio.create_task(RP.vigilar_reportes(conf, wa)))

        # Proactivo: alerta de SLA por vencer (por cliente, por sus canales). OFF por defecto.
        if conf.get("proactivo", {}).get("sla_enabled"):
            import proactivo as PRO
            tareas_extra.append(asyncio.create_task(PRO.vigilar_sla(conf, wa)))

        # Base de conocimiento: se regenera SOLA una vez por semana (después de la semana laboral),
        # sin que el cliente tenga que apretar el botón. ON por defecto (se apaga con kb.auto=false).
        try:
            import kb_auto as KB
            tareas_extra.append(asyncio.create_task(KB.vigilar(conf)))
        except Exception:  # noqa: BLE001
            pass

        # Anomalías de acceso por horario (por cliente). OFF por defecto; solo si el
        # sistema de acceso hace control horario (HikCentral/BioStar2, autoconfig por API).
        if conf.get("anomalias", {}).get("enabled"):
            import anomalias as ANO
            tareas_extra.append(asyncio.create_task(ANO.vigilar_anomalias(conf, wa)))

        # AVISO PROACTIVO de INICIO: apenas conecta el agente, ITHOS saluda solo por los
        # canales del cliente (WhatsApp/Telegram/Email), sin que se lo pidan.
        async def _aviso_inicio():
            await asyncio.sleep(12)          # dar tiempo a que WhatsApp se vincule
            try:
                from comun import conversacion as CV
                texto_inicio = CV.mensaje_inicio(
                    cliente, ia_disponible=True,
                    zona=conf.get("zona_horaria", "America/Argentina/Buenos_Aires"), gestor=gestor)
                await asyncio.to_thread(lambda: wa.enviar(texto_inicio, tipo=AV.SISTEMA))
            except Exception:  # noqa: BLE001
                pass
        if wa:
            tareas_extra.append(asyncio.create_task(_aviso_inicio()))

        # Reactivador de tickets POSPUESTOS: pasa a EN CURSO los que llegaron a su día/hora.
        try:
            from comun import agenda as AGENDA
            AGENDA.iniciar_reactivador(conf, avisar=lambda m: notificar_cuota("info", m))
        except Exception:  # noqa: BLE001
            pass

        while True:
            msg = json.loads(await websocket.receive_text())
            if msg.get("tipo") != P.EVENTO:
                continue
            evento, datos = msg.get("evento"), msg.get("datos", {})
            # "ITHOS, ..." (voz por micrófono) o audio de WhatsApp:
            if evento == P.EV_CONSULTA_VOZ and asistente:
                import base64
                # La métrica 'consulta_voz' la registra la capa de conversación (responder_stream/
                # responder_texto), UNA sola vez por consulta y para TODOS los canales. No la
                # duplicamos acá (antes se contaba doble en el camino no-técnico).
                try:
                    texto = datos.get("texto", "")
                    # El audio del micrófono se usa para (a) transcribir y (b) VERIFICAR la voz del
                    # dueño (voz-id): el modo admin por voz exige tu voz + la frase-clave.
                    audio_bytes = base64.b64decode(datos["audio_b64"]) if datos.get("audio_b64") else None
                    if audio_bytes:
                        texto = await asyncio.to_thread(
                            asistente.ia.transcribir, audio_bytes, datos.get("mime", "audio/wav"))
                    # Generamos la respuesta COMPLETA y la decimos de UNA (on_frase=None -> no streaming
                    # por oración). El agente la sintetiza como UN audio CONTINUO -> lectura NATURAL, con
                    # pausas de puntuación y SIN trabas/esperas entre oraciones o párrafos.
                    r = await asyncio.to_thread(
                        asistente.responder_stream, texto or "", "voz", None, None, audio_bytes)
                    if r and r.strip():
                        await enviar({"accion": "decir", "texto": r, "cachear": False})
                except Exception as e:  # noqa: BLE001
                    log.warning("Consulta de voz falló: %s", e)
                continue
            # DESCUBRIMIENTO de terminales: el agente lista los lectores/puertas que encontró (por DB o
            # API según la marca). Lo persistimos en el volumen compartido para que el PANEL las muestre
            # y el cliente las mapee (entrada/salida/sala + saludo + frecuencia). No dispara voz.
            if evento == P.EV_TERMINALES:
                try:
                    _guardar_terminales_descubiertas(cliente, datos.get("terminales") or [])
                except Exception as e:  # noqa: BLE001
                    log.warning("No se pudieron guardar las terminales descubiertas: %s", e)
                continue
            # El agente reporta su salud (micrófono/integrador/voz) -> lo guardamos para el dashboard.
            if evento == P.EV_ESTADO:
                import time as _t2
                estado_agente[cliente] = {
                    "microfono": bool(datos.get("microfono")),
                    "mic_habilitado": bool(datos.get("mic_habilitado")),
                    "integrador": bool(datos.get("integrador")),
                    "integrador_tipo": str(datos.get("integrador_tipo", "")),
                    "voz": bool(datos.get("voz")), "ts": int(_t2.time())}
                continue
            # Auto-descubrimiento EN VIVO: cada fichaje con 'device' suma esa terminal (cualquier marca,
            # sin código específico). Solo toca disco cuando aparece una terminal NUEVA.
            _dev = datos.get("device") if evento == P.EV_ACCESO else None
            if _dev and _dev not in _terminales_vistas.get(cliente, ()):
                try:
                    _guardar_terminales_descubiertas(cliente, [_dev])
                except Exception:  # noqa: BLE001
                    pass
            for cmd in procesador.procesar(conf, evento, datos):
                await websocket.send_json(cmd)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("Error en sesión %s: %s", cliente, e)
    finally:
        if tarea:
            tarea.cancel()
        for t in tareas_extra:
            t.cancel()
        if cliente and conexiones.get(cliente) is websocket:
            del conexiones[cliente]
            notificadores_activos.pop(cliente, None)   # ya no está para avisarle en el shutdown
            estado_agente.pop(cliente, None)           # su salud ya no aplica (desconectado)
            log.info("Agente desconectado: %s", cliente)
