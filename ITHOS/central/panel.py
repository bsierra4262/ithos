#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS — Panel de control (estética Iron Man HUD).

SUPERADMIN (/) — vos: gestionás TODAS las empresas (crear/editar/activar/borrar),
ves su config completa (IA, GLPI, WhatsApp, sistema de acceso), el estado de
conexión EN TIEMPO REAL, y las métricas de tu propia empresa. Cada empresa tiene
una URL de PORTAL propia para dársela al cliente.

PORTAL DEL CLIENTE (/panel/{api_key}) — el cliente: ve SU SLA, SUS métricas, SU
config (IA/WhatsApp/acceso) y puede corregirla. No ve a los demás.

ALTA (/alta) — formulario COMPLETO: toma toda la config (GLPI + IA + WhatsApp +
sistema de acceso con sus claves) y la incrusta en el sistema.

Correr:  uvicorn panel:app --host 0.0.0.0 --port 8090
"""

import os
import sys
import copy
import json
import time
import secrets
import urllib.request
import urllib.parse

# --- Anti fuerza-bruta en el login (rate-limit en memoria, por IP) ---
_LOGIN_FALLOS = {}          # ip -> [epochs de intentos fallidos recientes]
_LOGIN_MAX = 8              # máx. intentos fallidos
_LOGIN_VENTANA = 300        # en 5 minutos -> después se bloquea temporalmente


def _ip_cliente(request):
    xff = request.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else "") or (request.client.host if request.client else "?")


def _login_bloqueado(ip):
    ahora = time.time()
    f = [t for t in _LOGIN_FALLOS.get(ip, []) if ahora - t < _LOGIN_VENTANA]
    _LOGIN_FALLOS[ip] = f
    return len(f) >= _LOGIN_MAX


def _login_fallo(ip):
    _LOGIN_FALLOS.setdefault(ip, []).append(time.time())

from typing import List

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, ".."))
RUTA = os.path.join(BASE, "clientes.json")
CENTRAL_URL = os.environ.get("ITHOS_CENTRAL_URL", "http://127.0.0.1:8080")
app = FastAPI(title="ITHOS Gestor")

from comun import metricas as M   # noqa: E402
import reportes as R              # noqa: E402
import autenticacion as AUTH      # noqa: E402
from panel_ui import HTML, HTML_ALTA, portal_html   # noqa: E402


# ============================ MODELO DE ACCESO (seguridad) ====================
# Al GESTOR (superadmin `/` + APIs de gestión) accede SOLO INTELLIHELP (cookie de
# admin). El CLIENTE solo a su dashboard `/panel/<api_key>` (la api_key es su
# credencial). El ALTA `/alta` es un enlace temporal de un solo uso (token que caduca).
def _requiere_admin(method: str, path: str) -> bool:
    if path == "/":
        return True
    if path in ("/api/estado", "/api/resumen", "/api/generar_key", "/api/alta_link",
                "/api/alta_revocar", "/api/cambiar_password"):
        return True
    if path == "/api/clientes" and method == "GET":
        return True
    if path.startswith("/api/clientes/") and method == "DELETE":
        return True
    return False


@app.middleware("http")
async def _auth_mw(request: Request, call_next):
    path, method = request.url.path, request.method
    # Auto-login por ?k=<token> (enlace de acceso / la demo lo usa para entrar sola).
    if path in ("/", "/login") and AUTH.token_ok(request.query_params.get("k", "")):
        resp = RedirectResponse("/", status_code=303)
        AUTH.set_cookie(resp)
        return resp
    if path == "/login":                       # el form de login siempre pasa
        return await call_next(request)
    if _requiere_admin(method, path) and not AUTH.es_admin(request):
        if path == "/":                        # HTML → mostrar login
            return HTMLResponse(AUTH.LOGIN_HTML.replace("%ERR%", ""))
        return JSONResponse({"error": "no autorizado — acceso solo de INTELLIHELP"},
                            status_code=401)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
def login_form():
    return AUTH.LOGIN_HTML.replace("%ERR%", "")


@app.post("/login")
async def login(request: Request):
    ip = _ip_cliente(request)
    if _login_bloqueado(ip):
        return HTMLResponse(AUTH.LOGIN_HTML.replace(
            "%ERR%", "Demasiados intentos. Esperá unos minutos."), status_code=429)
    form = await request.form()
    if AUTH.credenciales_ok(form.get("usuario", ""), form.get("k", "")):
        _LOGIN_FALLOS.pop(ip, None)                 # login OK -> limpia el contador
        resp = RedirectResponse("/", status_code=303)
        AUTH.set_cookie(resp)
        return resp
    _login_fallo(ip)
    return HTMLResponse(AUTH.LOGIN_HTML.replace("%ERR%", "Usuario o contraseña incorrectos"),
                        status_code=401)


@app.get("/logout")
def logout():
    """Cierra la sesión del superadmin (borra la cookie) y vuelve al login."""
    resp = RedirectResponse("/login", status_code=303)
    AUTH.borrar_cookie(resp)
    return resp


@app.post("/api/alta_link")
async def alta_link(request: Request):
    """(Superadmin) genera un enlace de alta TEMPORAL de un solo uso para un cliente."""
    b = await request.json()
    try:
        horas = int(b.get("horas", 48) or 48)
    except (TypeError, ValueError):
        horas = 48
    t = AUTH.nuevo_alta_token((b.get("nombre") or "").strip(), horas)
    return {"ok": True, "url": f"/alta?t={t}", "token": t, "horas": horas}


@app.post("/api/alta_revocar")
async def alta_revocar(request: Request):
    """(Superadmin) revoca un enlace de alta generado (si te equivocaste, deja de valer YA)."""
    b = await request.json()
    quitado = AUTH.revocar_alta(b.get("token", ""))
    return {"ok": quitado}


@app.post("/api/cambiar_password")
async def cambiar_password(request: Request):
    """(Superadmin) cambia la contraseña de login del Gestor. La fija el admin; nadie más la ve."""
    b = await request.json()
    ok, msg = AUTH.cambiar_password(b.get("actual", ""), b.get("nueva", ""))
    return JSONResponse({"ok": ok, "mensaje": msg}, status_code=200 if ok else 400)


# --- Catálogo de sistemas de control de acceso (para el formulario dinámico) --
INTEGRADORES = {
    "ninguno": {"label": "Ninguno / sólo tickets", "campos": []},
    "ivms": {"label": "IVMS — Hikvision (SQL Server)", "campos": [
        {"k": "db_server", "l": "Servidor SQL (host,puerto)", "ph": "192.168.0.100,1433"},
        {"k": "db_database", "l": "Base de datos", "ph": "ivms_db"},
        {"k": "db_uid", "l": "Usuario", "ph": "ithos"},
        {"k": "db_pwd", "l": "Contraseña", "t": "password"},
        {"k": "max_rows", "l": "Máx. filas por consulta", "ph": "50"}]},
    "hikcentral": {"label": "HikCentral — Artemis OpenAPI", "campos": [
        {"k": "host", "l": "Host / URL", "ph": "https://10.0.0.5"},
        {"k": "app_key", "l": "App Key"},
        {"k": "app_secret", "l": "App Secret", "t": "password"}]},
    "biostar2": {"label": "BioStar 2 — Suprema", "campos": [
        {"k": "host", "l": "Host / URL", "ph": "https://10.0.0.6"},
        {"k": "login_id", "l": "Usuario"},
        {"k": "password", "l": "Contraseña", "t": "password"}]},
    "zkteco": {"label": "ZKTeco — ZKBioSecurity", "campos": [
        {"k": "host", "l": "Host / URL", "ph": "http://10.0.0.7"},
        {"k": "username", "l": "Usuario"},
        {"k": "password", "l": "Contraseña", "t": "password"}]},
    "honeywell": {"label": "Honeywell — Pro-Watch", "campos": [
        {"k": "host", "l": "Host / URL"},
        {"k": "api_key", "l": "API key / token", "t": "password"}]},
}

# --- Catálogo de PROVEEDORES DE IA (texto/razonamiento) ----------------------
# La VOZ es SIEMPRE Charon (Gemini): se usa gemini_api_key aparte.
IA_PROVEEDORES = {
    "gemini": {"label": "Google Gemini (GRATIS)", "campos": [
        {"k": "modelo_texto", "l": "Modelo (auto = más eficiente en cuota gratis)", "ph": "auto"}]},
    "cerebras": {"label": "Cerebras — GRATIS (Llama 70B, 1M tokens/día, ultrarrápido) ★", "campos": [
        {"k": "cerebras_api_key", "l": "API key de Cerebras (gratis, sin tarjeta, en cloud.cerebras.ai)", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo (auto = el más capaz)", "ph": "auto"}]},
    "groq": {"label": "Groq — GRATIS (Llama, muy rápido)", "campos": [
        {"k": "groq_api_key", "l": "API key de Groq (gratis en console.groq.com)", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo", "ph": "meta-llama/llama-4-scout-17b-16e-instruct"}]},
    "claude": {"label": "Anthropic Claude (pago)", "campos": [
        {"k": "anthropic_api_key", "l": "API key de Anthropic", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo", "ph": "claude-sonnet-4-5"}]},
    "openai": {"label": "OpenAI · ChatGPT (pago)", "campos": [
        {"k": "openai_api_key", "l": "API key de OpenAI", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo", "ph": "gpt-4o"}]},
    "grok": {"label": "xAI · Grok (pago)", "campos": [
        {"k": "grok_api_key", "l": "API key de xAI", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo", "ph": "grok-2-latest"}]},
    "deepseek": {"label": "DeepSeek (pago, barato)", "campos": [
        {"k": "deepseek_api_key", "l": "API key de DeepSeek", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo", "ph": "deepseek-chat"}]},
    "openrouter": {"label": "OpenRouter — casi TODOS los modelos (tiene GRATIS)", "campos": [
        {"k": "openrouter_api_key", "l": "API key de OpenRouter (openrouter.ai)", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo (auto = elige por plan)", "ph": "auto"}]},
    "mistral": {"label": "Mistral AI (tiene GRATIS)", "campos": [
        {"k": "mistral_api_key", "l": "API key de Mistral", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo (auto = elige por plan)", "ph": "auto"}]},
    "local": {"label": "Local / privado — Ollama (cualquier modelo de Ollama)", "campos": [
        {"k": "ollama_url", "l": "URL de Ollama", "ph": "http://127.0.0.1:11434"},
        {"k": "modelo_texto", "l": "Modelo de Ollama (el que tengas bajado: llama3.1, qwen2.5, deepseek-r1, phi3…)", "ph": "qwen2.5:14b"}]},
    "deepseek_local": {"label": "DeepSeek LOCAL (privado, sin Ollama · LM Studio/vLLM)", "campos": [
        {"k": "deepseek_local_url", "l": "URL del servidor local OpenAI-compatible (LM Studio 1234 · vLLM 8000 · llama.cpp 8080)", "ph": "http://127.0.0.1:1234/v1/chat/completions"},
        {"k": "modelo_texto", "l": "Modelo DeepSeek bajado en el servidor", "ph": "deepseek-r1"}]},
}


# --- Catálogo de sistemas de TICKETS (cada cliente elige el suyo) -------------
TICKETS = {
    "ninguno": {"label": "Ninguno / todavía no tengo (solo voz y avisos)", "campos": []},
    "glpi": {"label": "GLPI", "campos": [
        {"k": "glpi_url", "l": "URL de la API de GLPI",
         "ph": "https://glpi.tuempresa.com/apirest.php",
         "d": "La dirección de tu GLPI terminada en /apirest.php. Activá la API en GLPI: Configurar → "
              "General → API, y tildá «Habilitar la API REST»."},
        {"k": "glpi_app_token", "l": "App-Token (token de la aplicación)",
         "d": "En GLPI: Configurar → General → API → «Agregar cliente de API». Copiá el «Token de "
              "aplicación (app_token)» que te genera."},
        {"k": "glpi_user_token", "l": "Token del ADMINISTRADOR (acceso total)",
         "d": "Token de un usuario con permisos totales (crear categorías, asignar, cerrar). En su "
              "perfil de GLPI: arriba a la derecha → Preferencias → pestaña API → «Token de API "
              "remota» (Regenerar si está vacío)."},
        {"k": "glpi_ithos_token", "l": "Token de ITHOS (usuario del agente)",
         "d": "Token de un usuario dedicado a ITHOS (rol técnico/helpdesk). Con este token ITHOS "
              "clasifica, asigna y responde los tickets. Se saca igual: Preferencias → API → Token."},
        {"k": "glpi_bsierra_token", "l": "Token del TÉCNICO (helpdesk que resuelve)",
         "d": "Token del usuario técnico que resuelve los tickets. Opcional: si no lo ponés, ITHOS "
              "usa el de administrador."},
        {"k": "glpi_test_token", "l": "Token del CLIENTE (crea/responde tickets)",
         "d": "Token de un usuario con rol de cliente/solicitante (crea y responde tickets). Opcional; "
              "sirve para probar el circuito completo."},
        {"k": "entity_id", "l": "Entidad de GLPI (entity_id)", "t": "number", "ph": "0",
         "d": "El número (ID) de la entidad de GLPI donde están tus tickets. Lo ves en GLPI: "
              "Administración → Entidades (columna ID, o en la URL al abrir la entidad). Si tenés una "
              "sola entidad, normalmente es 0."}]},
    "zendesk": {"label": "Zendesk", "campos": [
        {"k": "host", "l": "Host / URL", "ph": "https://empresa.zendesk.com"},
        {"k": "email", "l": "Email"},
        {"k": "api_token", "l": "API token", "t": "password"}]},
    "freshservice": {"label": "Freshservice", "campos": [
        {"k": "host", "l": "Host / URL", "ph": "https://empresa.freshservice.com"},
        {"k": "api_key", "l": "API key", "t": "password"}]},
    "jira": {"label": "Jira Service Management", "campos": [
        {"k": "host", "l": "Host / URL", "ph": "https://empresa.atlassian.net"},
        {"k": "email", "l": "Email"},
        {"k": "api_token", "l": "API token", "t": "password"},
        {"k": "project_key", "l": "Project key", "ph": "SOP"}]},
    "osticket": {"label": "osTicket", "campos": [
        {"k": "host", "l": "Host / URL", "ph": "https://soporte.empresa.com"},
        {"k": "api_key", "l": "API key", "t": "password"}]},
}

# --- Catálogo de CANALES de notificación (uno o varios por cliente) ----------
CANALES = {
    "whatsapp_no_oficial": {"label": "WhatsApp (no oficial · grupo)", "campos": [
        {"k": "grupo", "l": "Nombre del grupo", "ph": "SOPORTE_ALERTAS"},
        {"k": "session", "l": "Archivo de sesión", "ph": "wa_session.sqlite3"},
        {"k": "respuesta", "l": "Responder con", "t": "select",
         "opciones": ["ambos", "texto", "audio"]}]},
    "whatsapp_oficial": {"label": "WhatsApp (oficial · Cloud API)", "campos": [
        {"k": "phone_number_id", "l": "Phone Number ID"},
        {"k": "access_token", "l": "Access Token", "t": "password"},
        {"k": "destinatarios", "l": "Números (coma)", "t": "list", "ph": "5491111, 5492222"},
        {"k": "respuesta", "l": "Responder con", "t": "select",
         "opciones": ["ambos", "texto", "audio"]}]},
    "telegram": {"label": "Telegram", "campos": [
        {"k": "bot_token", "l": "Bot token", "t": "password"},
        {"k": "chat_ids", "l": "Chat IDs (coma)", "t": "list", "ph": "12345678, -1009999"},
        {"k": "respuesta", "l": "Responder con", "t": "select",
         "opciones": ["texto", "audio", "ambos"]}]},
    "email": {"label": "Email (SMTP)", "campos": [
        {"k": "smtp_host", "l": "Servidor SMTP", "ph": "smtp.gmail.com"},
        {"k": "smtp_port", "l": "Puerto", "t": "number", "ph": "465"},
        {"k": "usuario", "l": "Usuario"},
        {"k": "password", "l": "Contraseña", "t": "password"},
        {"k": "destinatarios", "l": "Destinatarios (coma)", "t": "list"},
        {"k": "asunto", "l": "Asunto", "ph": "Alerta ITHOS"}]},
    "teams": {"label": "Microsoft Teams (webhook)", "campos": [
        {"k": "webhook_url", "l": "Webhook URL"}]},
    "slack": {"label": "Slack (webhook)", "campos": [
        {"k": "webhook_url", "l": "Webhook URL"}]},
    "element": {"label": "Matrix — Element/FluffyChat/SchildiChat/Cinny (open-source, tipo Slack · OPERABLE)", "campos": [
        {"k": "homeserver", "l": "Homeserver Matrix (sirve para CUALQUIER cliente Matrix)", "ph": "https://matrix.org"},
        {"k": "access_token", "l": "Access token del bot (en Element: Ajustes → Avanzado → Token de acceso)", "t": "password"},
        {"k": "room_ids", "l": "Salas (IDs, coma) — vacío = todas donde esté", "t": "list", "ph": "!abc:matrix.org"},
        {"k": "activacion_palabra", "l": "Palabra de activación", "ph": "ithos"},
        {"k": "respuesta", "l": "Responder con", "t": "select",
         "opciones": ["texto", "audio", "ambos"]}]},
}


_cache_cfg = {"mtime": None, "data": None}


def _cargar():
    # Los secretos van CIFRADOS en disco (AES-256-GCM). Se descifran en memoria para trabajar con ellos.
    # OPTIMIZACIÓN: se CACHEA por mtime del archivo -> si no cambió, NO se re-descifra (descifrar AES el
    # config entero en CADA request laggeaba el dashboard). Se devuelve una COPIA para que el caller pueda
    # mutar sin ensuciar la caché. Cross-proceso seguro: si otro contenedor reescribe, cambia el mtime.
    try:
        m = os.path.getmtime(RUTA)
        if _cache_cfg["mtime"] == m and _cache_cfg["data"] is not None:
            return copy.deepcopy(_cache_cfg["data"])
        from comun import cifrado as CIF
        data = CIF.descifrar_datos(json.load(open(RUTA, encoding="utf-8")))
        _cache_cfg["mtime"], _cache_cfg["data"] = m, data
        return copy.deepcopy(data)
    except Exception:  # noqa: BLE001
        return {"clientes": []}


def _guardar(data):
    # Se cifran los campos sensibles ANTES de escribir (grado militar, clave maestra aparte de los datos).
    # escribir_json cae a escritura EN EL LUGAR si clientes.json es un bind-mount de archivo (Docker),
    # donde el rename atómico da EBUSY.
    from comun import cifrado as CIF
    CIF.escribir_json(RUTA, CIF.cifrar_datos(data))
    _cache_cfg["mtime"] = None            # invalida la caché -> el próximo _cargar re-descifra lo nuevo


def _cliente_por_key(api_key):
    for c in _cargar().get("clientes", []):
        if c.get("api_key") == api_key:
            return c
    return None


def _tipo_integrador(c):
    integ = c.get("integrador")
    if isinstance(integ, dict):
        return integ.get("tipo", "ninguno")
    return integ or "ninguno"


def _armar_ia(b):
    """Bloque de IA: proveedor primario + respaldo EN CADENA opcional (secundario y terciario),
    cada uno con su modelo y su clave. La VOZ es siempre Charon (gemini_api_key).
    Config de esta empresa: Gemini primaria -> Cerebras secundaria -> Groq terciaria."""
    iap = b.get("ia_config") or {}
    ias = b.get("ia_config_2") or {}
    iat = b.get("ia_config_3") or {}
    ia = {
        "proveedor": b.get("proveedor", "gemini"),
        "gemini_api_key": (b.get("gemini_api_key") or "").strip(),   # voz Charon + gemini texto
        # 'auto' = ITHOS elige el modelo más EFICIENTE EN CUOTA GRATIS por defecto (o el más
        # capaz cost-effective si el plan es pago). El cliente puede fijar uno específico.
        "modelo_texto": iap.get("modelo_texto") or "auto",
        "modelo_voz": "gemini-2.5-flash-native-audio-latest",
        "voz": "Charon",
        "voz_motor": b.get("voz_motor", "charon"),                   # charon (Gemini) | edge (multiplataforma) | windows (solo Windows)
        "limite_diario": int(b.get("limite_diario") or 200),
        "avisar_en": int(b.get("avisar_en") or 15),
        "ilimitada": bool(b.get("ilimitada", False)),
    }
    for k, v in iap.items():                # claves del proveedor primario
        if k != "modelo_texto" and v:
            ia[k] = v
    sec_prov = b.get("proveedor_secundario", "")
    if sec_prov:                            # IA secundaria (respaldo) como bloque propio
        ia["secundario"] = {"proveedor": sec_prov,
                            **{k: v for k, v in ias.items() if v}}
    ter_prov = b.get("proveedor_terciario", "")
    if ter_prov:                            # IA terciaria (2º respaldo) como bloque propio
        ia["terciario"] = {"proveedor": ter_prov,
                           **{k: v for k, v in iat.items() if v}}
    return ia


def _armar_cliente(b, api_key):
    """Construye el registro de cliente a partir del formulario (alta o edición).
    Sistema de tickets y canales de notificación son ELEGIBLES por el cliente."""
    tk = b.get("tickets") or {}
    tk_tipo = tk.get("tipo") or "glpi"
    # GLPI conserva 'integrador_glpi' (lo usa el central para triage/SLA).
    integrador_glpi = {"ubicacion": "central"}
    if tk_tipo == "glpi":
        integrador_glpi.update({
            "glpi_url": (tk.get("glpi_url") or "").strip(),
            "glpi_app_token": (tk.get("glpi_app_token") or "").strip(),
            "glpi_user_token": (tk.get("glpi_user_token") or "").strip(),   # super admin
            "glpi_ithos_token": (tk.get("glpi_ithos_token") or "").strip(),  # agente
            "glpi_bsierra_token": (tk.get("glpi_bsierra_token") or "").strip(),  # helpdesk
            "glpi_test_token": (tk.get("glpi_test_token") or "").strip(),    # cliente
            "entity_id": int(tk.get("entity_id") or 0),
            "poll_interval": 5,
        })
    tickets = {"tipo": tk_tipo, **{k: v for k, v in tk.items() if k != "tipo"}}
    # Canales de notificación elegidos (whatsapp/telegram/email/teams/slack).
    canales = []
    for n in b.get("notificaciones", []) or []:
        if not n.get("tipo"):
            continue
        canales.append({**n, "enabled": bool(n.get("enabled", True))})
    return {
        "api_key": api_key,
        # Contraseña de AGENTE por empresa (la asigna el Gestor): el agente se autentica con
        # api_key + este token. Se genera una vez (fuerte) y se preserva en las ediciones.
        "agente_token": b.get("agente_token") or secrets.token_urlsafe(24),
        # Sesión de WhatsApp no-oficial AISLADA por cliente. El frontend la fija al vincular por QR
        # (incluso en el alta, antes de que exista la api_key); se preserva en las ediciones para no
        # perder la vinculación. Si el cliente nunca vinculó, queda vacío y se deriva de la api_key.
        "wa_session": b.get("wa_session") or "",
        "nombre": (b.get("nombre") or "").strip(),
        "email": (b.get("email") or "").strip(),
        "activo": bool(b.get("activo", True)),
        "voz": "Charon",
        "idioma": b.get("idioma", "es-AR"),
        "zona_horaria": b.get("zona_horaria", "America/Argentina/Buenos_Aires"),
        "velocidad": 1.25,
        "ia": _armar_ia(b),
        "integrador": b.get("integrador", "ninguno"),
        "integrador_config": b.get("integrador_config", {}) or {},
        # Reglas de TERMINALES (control de acceso): mapean cada lector/puerta a un tipo (entrada/salida/
        # sala), su saludo y su frecuencia. El central clasifica cada fichaje por 'device' con esto.
        "terminales": [t for t in (b.get("terminales") or []) if (t.get("match") or "").strip()],
        "tickets": tickets,
        "integrador_glpi": integrador_glpi,
        "notificaciones": canales,
        "reportes": b.get("reportes", {}) or {},        # reportes proactivos por cliente
        "proactivo": b.get("proactivo", {}) or {},      # alerta SLA por vencer (por cliente)
        "anomalias": b.get("anomalias", {}) or {},      # anomalías de horario (OFF por defecto)
        "facturacion": b.get("facturacion", {}) or {},  # suscripción SaaS por cliente
        # Wiki Outline para la base de conocimiento (si el cliente la cargó en el alta/portal). Solo
        # se guarda con valores reales (url/token) -> la KB puede importar de ahí sin re-cargarla.
        "kb_outline": {k: v for k, v in (b.get("kb_outline") or {}).items() if v},
    }


# ---------------------------------------------------------------- vistas HTML
@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


@app.get("/alta", response_class=HTMLResponse)
def alta(request: Request):
    # El alta es un enlace TEMPORAL de un solo uso: sin token válido no se muestra.
    if not AUTH.alta_valido(request.query_params.get("t", "")):
        return HTMLResponse(AUTH.ALTA_INVALIDO_HTML, status_code=403)
    return HTML_ALTA


@app.get("/panel/{api_key}", response_class=HTMLResponse)
def portal(api_key: str):
    c = _cliente_por_key(api_key)
    if not c:
        return HTMLResponse("<h1>Portal no encontrado</h1>", status_code=404)
    return portal_html(api_key, c.get("nombre", ""))


# ------------------------------------------------------------------- API core
@app.get("/api/integradores")
def integradores():
    return INTEGRADORES


@app.get("/api/ia_proveedores")
def catalogo_ia():
    return IA_PROVEEDORES


@app.get("/api/tickets")
def catalogo_tickets():
    return TICKETS


@app.get("/api/canales")
def catalogo_canales():
    return CANALES


@app.get("/api/clientes")
def listar():
    return _cargar()


@app.get("/api/cliente/{api_key}")
def uno(api_key: str):
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "no encontrado"}, status_code=404)
    return c


@app.get("/api/terminales/{api_key}")
def terminales_descubiertas(api_key: str):
    """Terminales que el AGENTE descubrió (las persiste el central en el volumen compartido). Sirve
    para que el cliente las mapee (entrada/salida/sala) sin adivinar los nombres."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "no encontrado"}, status_code=404)
    slug = "".join(ch for ch in str(c.get("nombre", "")) if ch.isalnum() or ch in "-_")[:40] or "cli"
    ruta = os.path.join(os.environ.get("ITHOS_DATA", "/data"), f"terminales_{slug}.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"terminales": []}


@app.get("/api/salud/{api_key}")
def salud(api_key: str):
    """Salud del cliente (agente + canales + micrófono + integrador) para el dashboard. En producción
    todo debe estar 100% activo; acá se ve si algo quedó sin arrancar."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "no encontrado"}, status_code=404)
    try:
        s = _central_get("/api/salud?cliente=" + urllib.parse.quote(c.get("nombre", "")))
    except Exception:  # noqa: BLE001
        s = {"agente_conectado": False, "canales": [], "microfono": False, "integrador": False}
    # Contexto desde la CONFIG (el panel la tiene): qué DEBERÍA estar activo, para mostrar el badge y su
    # color aunque el agente todavía no haya reportado su estado.
    integ = c.get("integrador")
    s["integrador_cfg"] = (integ if isinstance(integ, str) else (integ or {}).get("tipo", "")) \
        if integ not in (None, "", "ninguno") else ""
    if s.get("mic_habilitado") is None:                          # fallback si el agente no lo reportó
        s["mic_habilitado"] = bool((c.get("microfono") or {}).get("enabled"))
    return s


_ultimo_conectados = {"conectados": []}


@app.get("/api/estado")
def estado():
    """Agentes conectados AHORA (consulta al central). RESILIENTE: reintenta y, si el poll falla
    transitoriamente, devuelve el ÚLTIMO estado conocido (no parpadea a 0 por un hipo de red). Solo
    baja a 0 cuando el central REALMENTE dice que no hay agentes."""
    global _ultimo_conectados
    for _ in range(2):
        try:
            with urllib.request.urlopen(CENTRAL_URL + "/api/conectados", timeout=5) as r:
                _ultimo_conectados = json.load(r)
                return _ultimo_conectados
        except Exception:  # noqa: BLE001
            continue
    return _ultimo_conectados            # transitorio -> mantené el último estado (evita el flapping)


# ================= WhatsApp NO-OFICIAL: vincular por QR (panel + portal + alta) =================
# El panel hace de intermediario con AUTH y resuelve api_key -> id de sesión; el trabajo real
# (neonize + QR) corre en el CENTRAL. Autorización: SUPERADMIN (cookie), o el PROPIO CLIENTE (su
# api_key es su credencial, igual que su portal/autoedición), o el ALTA (token temporal válido).
def _central_get(path):
    with urllib.request.urlopen(CENTRAL_URL + path, timeout=8) as r:
        return json.load(r)


def _central_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(CENTRAL_URL + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)


def _resolver_sesion_wa(request, api_key, sesion, alta_token):
    """(sesion, None) si autorizado; (None, JSONResponse) si no. api_key = credencial del cliente."""
    from comun import whatsapp_link as WL
    api_key = (api_key or "").strip()
    if api_key:
        c = _cliente_por_key(api_key)
        if not c:
            return None, JSONResponse({"error": "cliente no encontrado"}, status_code=404)
        return WL.sesion_de_cliente(c), None       # admin o el propio cliente (sabe su api_key)
    sesion = (sesion or "").strip()
    if sesion:                                      # flujo de ALTA (todavía no hay api_key)
        if not (AUTH.es_admin(request) or AUTH.alta_valido(alta_token or "")):
            return None, JSONResponse({"error": "no autorizado"}, status_code=401)
        return sesion, None
    return None, JSONResponse({"error": "falta api_key o sesión"}, status_code=400)


@app.post("/api/whatsapp/vincular")
async def wa_vincular_panel(request: Request):
    b = await request.json()
    sesion, err = _resolver_sesion_wa(request, b.get("api_key"), b.get("sesion"),
                                      b.get("_alta_token"))
    if err:
        return err
    try:
        return _central_post("/api/whatsapp/vincular", {"sesion": sesion})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"estado": "error", "error": f"no se pudo iniciar: {e}"}, status_code=502)


@app.get("/api/whatsapp/estado")
async def wa_estado_panel(request: Request, api_key: str = "", sesion: str = "", t: str = ""):
    s, err = _resolver_sesion_wa(request, api_key, sesion, t)
    if err:
        return err
    try:
        return _central_get(f"/api/whatsapp/estado?sesion={urllib.parse.quote(s)}")
    except Exception:  # noqa: BLE001
        return {"estado": "desconocido"}           # transitorio: el front reintenta


@app.post("/api/whatsapp/desvincular")
async def wa_desvincular_panel(request: Request):
    b = await request.json()
    sesion, err = _resolver_sesion_wa(request, b.get("api_key"), b.get("sesion"),
                                      b.get("_alta_token"))
    if err:
        return err
    try:
        return _central_post("/api/whatsapp/desvincular", {"sesion": sesion})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/resumen")
def resumen():
    data = _cargar().get("clientes", [])
    activos = sum(1 for c in data if c.get("activo"))
    por_integ, uso_total = {}, {}
    for c in data:
        t = _tipo_integrador(c)
        por_integ[t] = por_integ.get(t, 0) + 1
        u = M.resumen(c.get("nombre", "")).get("uso", {})
        for k, v in u.items():
            uso_total[k] = uso_total.get(k, 0) + v
    return {"total": len(data), "activos": activos, "inactivos": len(data) - activos,
            "por_integrador": por_integ, "uso_total": uso_total}


@app.post("/api/generar_key")
async def generar_key(request: Request):
    body = await request.json()
    nombre = (body.get("nombre") or "CLI").strip()
    slug = "".join(ch for ch in nombre.upper() if ch.isalnum())[:10] or "CLI"
    return {"api_key": f"{slug}-{secrets.token_hex(6)}"}


@app.get("/api/metricas/{api_key}")
def ver_metricas(api_key: str):
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    return M.resumen(c["nombre"])


@app.get("/api/probar_suscripcion/{api_key}")
def probar_suscripcion(api_key: str):
    """Genera una suscripción de PRUEBA en MercadoPago (preapproval) con el Access Token
    guardado del cliente y devuelve el link de pago (init_point). Solo superadmin lo usa."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    fact = dict(c.get("facturacion") or {})
    if not fact.get("mp_access_token"):
        return {"error": "Falta el Access token de MercadoPago. Cargalo arriba y tocá Guardar empresa primero."}
    fact["email"] = fact.get("email") or c.get("email", "")   # por defecto, el email de contacto
    if not fact["email"]:
        return {"error": "Falta el email del pagador (poné el Email de contacto de la empresa)."}
    from comun import facturacion as F
    r = F.crear_suscripcion(fact, c.get("nombre", ""))
    if r.get("id"):     # persistir el preapproval_id para poder consultar el estado después
        F.guardar_estado(c.get("nombre", ""), {"preapproval_id": r["id"],
                                               "estado": r.get("estado", "pending")})
    return r


@app.get("/api/sla/{api_key}")
def ver_sla(api_key: str):
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    gl = c.get("integrador_glpi") or {}
    if not gl.get("glpi_url") or not gl.get("glpi_app_token"):
        return JSONResponse({"error": "sin GLPI configurado"}, status_code=200)
    try:
        rep, _ = R.generar(gl, int(gl.get("entity_id", 0)))   # SIN límite -> total REAL (no 200)
        return rep
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:120]}, status_code=200)


@app.get("/api/config_agente/{api_key}")
def config_agente(api_key: str):
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    tipo = _tipo_integrador(c)
    integ_cfg = c.get("integrador_config") or {}
    ia = c.get("ia") or {}
    return {
        "central_url": "wss://TU-DOMINIO/ws",
        "api_key": c.get("api_key"),
        "velocidad": c.get("velocidad", 1.25),
        "integrador": {"tipo": tipo, **integ_cfg} if tipo != "ninguno" else None,
        "ia": {"voz": {"proveedor": "gemini", "voz": "Charon",
                       "gemini_api_key": ia.get("gemini_api_key", ""),
                       "modelo_voz": ia.get("modelo_voz", "gemini-2.5-flash-native-audio-latest"),
                       "idioma": c.get("idioma", "es-AR")}},
    }


# --------------------------------------------------------------- alta/edición
@app.post("/api/suscripcion/{api_key}")
def crear_suscripcion(api_key: str):
    """Genera el link de pago (MercadoPago) para la suscripción del cliente."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    from comun import facturacion as F
    fact = dict(c.get("facturacion") or {})
    fact["email"] = fact.get("email") or c.get("email", "")   # por defecto, el email de contacto
    r = F.crear_suscripcion(fact, c.get("nombre", ""))
    if r.get("id"):                       # guardar el preapproval_id en el cliente
        data = _cargar()
        for cc in data["clientes"]:
            if cc.get("api_key") == api_key:
                cc.setdefault("facturacion", {})["preapproval_id"] = r["id"]
                cc["facturacion"]["estado"] = r.get("estado", "pending")
        _guardar(data)
    return r


@app.get("/api/facturacion/{api_key}")
def ver_facturacion(api_key: str):
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    from comun import facturacion as F
    # INSTANTÁNEO: si el webhook ya dejó el estado, lo devolvemos sin llamar a MP (0 latencia).
    # Solo si no hay estado persistido consultamos en vivo (fallback).
    persistido = F.cargar_estado(c.get("nombre", ""))
    if persistido.get("estado"):
        return persistido
    return F.estado_suscripcion(c.get("facturacion") or {})


@app.get("/api/reporte_ahora/{api_key}")
def reporte_ahora(api_key: str):
    """Genera y devuelve el texto del reporte del cliente (para probar/enviar ya)."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    gl = c.get("integrador_glpi") or {}
    if not gl.get("glpi_url"):
        return JSONResponse({"error": "sin GLPI"}, status_code=200)
    try:
        import reportes_programados as RP
        return {"reporte": RP.texto_reporte(gl, int(gl.get("entity_id", 0)))}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:120]}, status_code=200)


@app.get("/api/reporte_itil/{api_key}")
def reporte_itil(api_key: str, periodo: str = "mensual", tecnico: int = 0,
                 desde: str = "", hasta: str = ""):
    """KPIs ITIL del cliente (JSON + texto) para el período. tecnico=1 incluye por-técnico
    (más lento). periodo='personalizado' + desde/hasta ('YYYY-MM-DD') = rango a mano.
    Para descargar CSV/PDF usar /api/reporte_itil/{key}/{csv|pdf}."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    gl = c.get("integrador_glpi") or {}
    if not gl.get("glpi_url"):
        return JSONResponse({"error": "sin GLPI configurado"}, status_code=200)
    try:
        from comun import reportes_itil as RI
        k = RI.calcular(gl, int(gl.get("entity_id", 0)), periodo,
                        c.get("zona_horaria", "America/Argentina/Buenos_Aires"),
                        con_tecnico=bool(tecnico), desde=desde or None, hasta=hasta or None)
        k["empresa"] = c.get("nombre", "")
        return {"kpis": k, "texto": RI.resumen_texto(k, c.get("nombre", ""))}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:160]}, status_code=200)


@app.get("/api/reporte_itil/{api_key}/{formato}")
def reporte_itil_archivo(api_key: str, formato: str, periodo: str = "mensual",
                         desde: str = "", hasta: str = ""):
    """Descarga el reporte ITIL en CSV o PDF. periodo='personalizado' + desde/hasta = rango a mano."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    gl = c.get("integrador_glpi") or {}
    if not gl.get("glpi_url"):
        return JSONResponse({"error": "sin GLPI configurado"}, status_code=200)
    try:
        from comun import reportes_itil as RI
        emp = c.get("nombre", "")
        k = RI.calcular(gl, int(gl.get("entity_id", 0)), periodo,
                        c.get("zona_horaria", "America/Argentina/Buenos_Aires"), con_tecnico=True,
                        desde=desde or None, hasta=hasta or None)
        k["empresa"] = emp
        seguro = "".join(ch if ch.isalnum() else "_" for ch in emp) or "reporte"
        base = f"reporte_ITIL_{seguro}_{periodo}"
        if formato == "csv":
            return Response(RI.csv_bytes(k, emp), media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})
        if formato == "pdf":
            pdf = RI.pdf_bytes(k, emp)
            if not pdf:
                return JSONResponse({"error": "PDF no disponible (falta reportlab)"}, status_code=200)
            return Response(pdf, media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{base}.pdf"'})
        return JSONResponse({"error": "formato debe ser csv o pdf"}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:160]}, status_code=200)


@app.post("/api/kb_subir/{api_key}")
async def kb_subir(api_key: str, archivos: List[UploadFile] = File(...)):
    """Sube VARIOS archivos juntos (PDF/TXT/MD/DOCX de instructivos/manuales) a la KB del
    cliente. ITHOS extrae el texto y lo suma a lo que ya aprendió de los tickets."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    try:
        import kb_auto
        files = [(f.filename, await f.read()) for f in archivos]
        cargados, total = kb_auto.subir_archivos(c.get("nombre", "cliente"), files)
        return {"ok": True, "cargados": cargados, "total": total,
                "instructivos": kb_auto.listar_instructivos(c.get("nombre", "cliente"))}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:160]}, status_code=200)


@app.post("/api/kb_outline/{api_key}")
async def kb_outline(api_key: str, request: Request):
    """Importa documentos de OUTLINE (wiki open-source) a la KB del cliente. Body: {url, token}.
    Se puede guardar la config en el cliente ('kb_outline': {url, token}) o pasarla en el body."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    try:
        b = await request.json()
    except Exception:  # noqa: BLE001
        b = {}
    cfg = c.get("kb_outline") or {}
    url = (b.get("url") or cfg.get("url") or "").strip()
    token = (b.get("token") or cfg.get("token") or "").strip()
    if not url or not token:
        return JSONResponse({"error": "faltan la URL de Outline y el API token"}, status_code=200)
    try:
        import kb_auto
        traidos, total = kb_auto.importar_outline(c.get("nombre", "cliente"), url, token)
        return {"ok": True, "traidos": traidos, "total": total,
                "instructivos": kb_auto.listar_instructivos(c.get("nombre", "cliente"))}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:160]}, status_code=200)


@app.get("/api/kb_generar/{api_key}")
def kb_generar(api_key: str):
    """Regenera la base de conocimiento del cliente desde SU sistema de tickets (el que
    sea) leyendo los casos resueltos. Por cliente (aislada)."""
    c = _cliente_por_key(api_key)
    if not c:
        return JSONResponse({"error": "cliente no encontrado"}, status_code=404)
    try:
        import kb_auto
        n = kb_auto.generar(c, c.get("nombre", "cliente"))
        return {"ok": True, "casos": n, "kb_dir": kb_auto.kb_dir(c.get("nombre", "cliente"))}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:160]}, status_code=200)


@app.post("/api/alta")
async def alta_completa(request: Request):
    """Alta COMPLETA (el cliente carga todo): incrusta la config en el sistema.

    Requiere un token de alta de un solo uso (el enlace temporal que le dio INTELLIHELP).
    """
    b = await request.json()
    nombre = (b.get("nombre") or "").strip()
    if not nombre:
        return JSONResponse({"error": "falta el nombre de la empresa"}, status_code=400)
    # ONE-TIME: se consume el enlace AL ENVIAR el formulario (atómico). Desde acá ya NO se puede
    # reusar aunque falle algo después: el enlace temporal caducó en el acto.
    if not AUTH.consumir_si_valido(b.get("_alta_token", "")):
        return JSONResponse({"error": "enlace de alta inválido, ya usado o vencido"}, status_code=403)
    data = _cargar()
    data.setdefault("clientes", [])
    if any(c.get("nombre", "").lower() == nombre.lower() for c in data["clientes"]):
        return JSONResponse({"error": "ya existe una empresa con ese nombre (pedí un enlace nuevo)"},
                            status_code=409)
    slug = "".join(ch for ch in nombre.upper() if ch.isalnum())[:8] or "CLI"
    api_key = f"{slug}-{secrets.token_hex(6)}"
    cli = _armar_cliente(b, api_key)
    data["clientes"].append(cli)
    _guardar(data)
    return {"ok": True, "api_key": api_key, "nombre": nombre, "activo": cli["activo"],
            "portal": f"/panel/{api_key}"}


@app.post("/api/clientes")
async def upsert(request: Request):
    """Alta/edición desde el panel (superadmin) o autoedición (portal cliente).

    Seguridad: el SUPERADMIN (cookie) puede crear/editar cualquiera. El CLIENTE, sin
    cookie, SOLO puede editar su propia empresa (debe mandar su api_key existente); no
    puede crear empresas nuevas (eso va por el enlace de alta o por el superadmin).
    """
    b = await request.json()
    if not (b.get("nombre") or "").strip():
        return JSONResponse({"error": "falta el nombre de la empresa"}, status_code=400)
    api_key = b.get("api_key") or None
    data = _cargar()
    es_admin = AUTH.es_admin(request)
    existe = bool(api_key) and any(c.get("api_key") == api_key
                                   for c in data.get("clientes", []))
    if not es_admin and not existe:
        return JSONResponse({"error": "no autorizado — acceso solo de INTELLIHELP"},
                            status_code=401)
    if not api_key:
        slug = "".join(ch for ch in b["nombre"].upper() if ch.isalnum())[:8] or "CLI"
        api_key = f"{slug}-{secrets.token_hex(6)}"
    cli = _armar_cliente(b, api_key)
    data["clientes"] = [c for c in data.get("clientes", []) if c.get("api_key") != api_key]
    data["clientes"].append(cli)
    _guardar(data)
    return {"ok": True, "api_key": api_key, "total": len(data["clientes"]),
            "portal": f"/panel/{api_key}"}


@app.delete("/api/clientes/{api_key}")
def borrar(api_key: str):
    data = _cargar()
    data["clientes"] = [c for c in data.get("clientes", []) if c.get("api_key") != api_key]
    _guardar(data)
    return {"ok": True}
