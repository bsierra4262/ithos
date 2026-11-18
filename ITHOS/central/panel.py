#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS — Panel de control (estética Iron Man HUD). Herramienta INTERNA de INTELLIHELP.

Todo el panel exige el login del administrador: estado en vivo del agente y de WhatsApp,
métricas, SLA, reportes ITIL, base de conocimiento y la configuración de ITHOS.

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
    """IP REAL del que llama, para contar intentos de login.

    OJO con `X-Forwarded-For`: lo puede escribir el cliente. Si se toma el PRIMER valor —lo
    habitual— cualquiera manda uno distinto en cada intento y el anti fuerza-bruta no cuenta nunca
    dos veces lo mismo: deja de existir. Detrás de UN proxy de confianza (nuestro Caddy, el único
    que publica puertos) la IP real es la ÚLTIMA de la lista: la que agregó el proxy. Lo que haya
    antes lo puso el cliente y no vale nada."""
    xff = request.headers.get("x-forwarded-for", "")
    directa = request.client.host if request.client else ""
    if xff:
        partes = [p.strip() for p in xff.split(",") if p.strip()]
        if partes:
            return partes[-1]
    return directa or "?"


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
from comun import ia as IA_VOZ    # noqa: E402  (sólo para el modelo de voz vigente)
from comun.ambitos import AMBITOS  # noqa: E402
import reportes as R              # noqa: E402
import autenticacion as AUTH      # noqa: E402
from panel_ui import HTML        # noqa: E402


# ============================ MODELO DE ACCESO (seguridad) ====================
# ITHOS es una herramienta INTERNA: todo el panel exige la sesión del administrador. Lo único
# abierto es la puerta de entrada (login/logout). Es una lista de EXCEPCIONES, y el resto queda
# cerrado: así una ruta nueva nace PRIVADA aunque nadie se acuerde de protegerla.
_PUBLICAS_EXACTAS = {"/login", "/logout"}


def _requiere_admin(method: str, path: str) -> bool:
    """DENEGAR POR DEFECTO: todo exige la sesión del administrador salvo el login."""
    return path not in _PUBLICAS_EXACTAS


@app.middleware("http")
async def _auth_mw(request: Request, call_next):
    path, method = request.url.path, request.method
    # NO hay auto-login por query string. Existía un `?k=<ITHOS_ADMIN_TOKEN>` que entraba sin
    # formulario: la contraseña del Gestor terminaba escrita en los logs de
    # acceso de Caddy, en el historial del navegador y en la cabecera `Referer` de cualquier
    # recurso externo. Se entra por el formulario, que manda la contraseña en el cuerpo del POST.
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


@app.post("/api/cambiar_password")
async def cambiar_password(request: Request):
    """(Superadmin) cambia la contraseña de login del Gestor. La fija el admin; nadie más la ve."""
    b = await request.json()
    ok, msg = AUTH.cambiar_password(b.get("actual", ""), b.get("nueva", ""))
    return JSONResponse({"ok": ok, "mensaje": msg}, status_code=200 if ok else 400)


# --- Catálogo de sistemas de control de acceso (para el formulario dinámico) --
# Sólo se ofrece lo que el software SABE hacer hoy: si figurara acá algo sin
# integrador del lado del agente, elegirlo no haría nada y el cliente no se
# enteraría. Sumar uno es escribir su `integrador_<x>.py` y agregarlo acá.
INTEGRADORES = {
    "ivms": {"label": "IVMS — Hikvision (SQL Server)", "campos": [
        {"k": "db_server", "l": "Servidor SQL (host,puerto)", "ph": "192.168.0.100,1433"},
        {"k": "db_database", "l": "Base de datos", "ph": "ivms_db"},
        {"k": "db_uid", "l": "Usuario", "ph": "ithos"},
        {"k": "db_pwd", "l": "Contraseña", "t": "password"},
        {"k": "max_rows", "l": "Máx. filas por consulta", "ph": "50"}]},
}

# --- Catálogo de PROVEEDORES DE IA (texto/razonamiento) ----------------------
# La cadena de ITHOS: Gemini (gratis), Groq (gratis) y la IA local del servidor (Ollama, sin cuota).
# La VOZ es SIEMPRE Charon (Gemini): se usa gemini_api_key aparte.
IA_PROVEEDORES = {
    "gemini": {"label": "Google Gemini (gratis)", "campos": [
        {"k": "modelo_texto", "l": "Modelo (auto = más eficiente en cuota gratis)", "ph": "auto"}]},
    "groq": {"label": "Groq (gratis, muy rápido)", "campos": [
        {"k": "groq_api_key", "l": "API key de Groq (gratis en console.groq.com)", "t": "password"},
        {"k": "modelo_texto", "l": "Modelo (auto = el más capaz)", "ph": "auto"}]},
    "local": {"label": "IA local del servidor (Ollama, sin cuota)", "campos": [
        {"k": "ollama_url", "l": "URL de Ollama", "ph": "http://ollama:11434"},
        {"k": "modelo_texto", "l": "Modelo de Ollama", "ph": "qwen3:4b"}]},
}


# --- Catálogo de sistemas de TICKETS (cada cliente elige el suyo) -------------
# Igual que arriba: acá va lo que tiene adaptador en `comun/tickets.py`. Sumar
# otra mesa de ayuda es escribir su adaptador con la misma interfaz y listarla.
TICKETS = {
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
        {"k": "entity_id", "l": "Entidad de GLPI (entity_id)", "t": "number", "ph": "0",
         "d": "El número (ID) de la entidad de GLPI donde están tus tickets. Lo ves en GLPI: "
              "Administración → Entidades (columna ID, o en la URL al abrir la entidad). Si tenés una "
              "sola entidad, normalmente es 0."}]},
}

# --- Catálogo de CANALES de notificación (uno o varios por cliente) ----------
# WhatsApp con el número propio, con un GRUPO POR TEMA (ámbito): cada grupo
# declara qué avisos recibe y sobre qué se le puede consultar ahí.
CANALES = {
    "whatsapp_no_oficial": {"label": "WhatsApp (número propio · grupos por tema)", "campos": [
        {"k": "grupos", "l": "Grupos y de qué es cada uno", "t": "grupos",
         "opciones": [[k, f"{k} — {v['descripcion']}"] for k, v in AMBITOS.items()],
         "d": "Un grupo por tema, así las alertas de tickets no tapan las consultas ni las tareas "
              "del equipo. Cada grupo recibe SÓLO los avisos de su ámbito y contesta SÓLO sobre "
              "eso; lo que se pregunta fuera de su tema se deriva al grupo que sí lo maneja."},
        {"k": "grupo", "l": "Grupo único (sólo si no usás grupos por tema)", "ph": "SOPORTE_ALERTAS",
         "d": "Compatibilidad: si dejás esto y ningún grupo arriba, todo va a un solo grupo."},
        {"k": "respuesta", "l": "Responder con", "t": "select",
         "opciones": ["ambos", "texto", "audio"]}]},
}


_cache_cfg = {"mtime": None, "data": None}


class ConfigIlegible(Exception):
    """clientes.json no se pudo leer o descifrar: NO se puede guardar encima."""


def _cargar(estricto=False):
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
    except Exception as e:  # noqa: BLE001
        # Para MOSTRAR, una lectura fallida es una pantalla vacía. Para GUARDAR no: escribir sobre
        # "lo que se pudo leer" (nada) dejaría el padrón sin la empresa. Quien guarda pide estricto.
        if estricto:
            raise ConfigIlegible(str(e)) from e
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


def _armar_ia(b):
    """Bloque de IA: proveedor primario + respaldo EN CADENA opcional (secundario y terciario),
    cada uno con su modelo y su clave. La VOZ es siempre Charon (gemini_api_key).
    Config de INTELLIHELP: Gemini primaria -> Groq secundaria -> IA local terciaria."""
    iap = b.get("ia_config") or {}
    ias = b.get("ia_config_2") or {}
    iat = b.get("ia_config_3") or {}
    ia = {
        "proveedor": b.get("proveedor", "gemini"),
        "gemini_api_key": (b.get("gemini_api_key") or "").strip(),   # voz Charon + gemini texto
        # 'auto' = ITHOS elige el modelo más EFICIENTE EN CUOTA GRATIS por defecto (o el más
        # capaz cost-effective si el plan es pago). El cliente puede fijar uno específico.
        "modelo_texto": iap.get("modelo_texto") or "auto",
        # TTS DEDICADO: lee el texto VERBATIM. El modelo 'native-audio' es conversacional
        # (no genera audio por `generateContent`) y además se comía nombres al interpretarlos.
        "modelo_voz": IA_VOZ.VOZ_MODELO,
        "voz": "Charon",
        "limite_diario": int(b.get("limite_diario") or 200),
        "avisar_en": int(b.get("avisar_en") or 15),
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
    """Construye el registro a partir del formulario. Lo que el formulario no maneja (velocidad de
    la voz, intervalo de GLPI, sesión de WhatsApp, técnicos, Planka…) NO va acá: se conserva lo
    guardado al fusionar (`_fusionar_cliente`); los valores por omisión los pone `_nuevo_cliente`."""
    tk = b.get("tickets") or {}
    # GLPI vive en 'integrador_glpi' (lo usa el central para triage/SLA). Los tokens van UNA vez,
    # acá: el bloque 'tickets' sólo dice qué sistema es.
    integrador_glpi = {
        "glpi_url": (tk.get("glpi_url") or "").strip(),
        "glpi_app_token": (tk.get("glpi_app_token") or "").strip(),
        "glpi_user_token": (tk.get("glpi_user_token") or "").strip(),   # administrador
        "glpi_ithos_token": (tk.get("glpi_ithos_token") or "").strip(),  # usuario de ITHOS
        "entity_id": int(tk.get("entity_id") or 0),
    }
    tickets = {"tipo": "glpi"}
    # Canal de avisos elegido (WhatsApp, con sus grupos).
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
        "nombre": (b.get("nombre") or "").strip(),
        "activo": bool(b.get("activo", True)),
        "voz": "Charon",
        "idioma": b.get("idioma", "es-AR"),
        "zona_horaria": b.get("zona_horaria", "America/Argentina/Buenos_Aires"),
        "ia": _armar_ia(b),
        "integrador": b.get("integrador", "ivms"),
        "integrador_config": b.get("integrador_config", {}) or {},
        # Reglas de TERMINALES (control de acceso): mapean cada lector/puerta a un tipo (entrada/salida/
        # sala), su saludo y su frecuencia. El central clasifica cada fichaje por 'device' con esto.
        "terminales": [t for t in (b.get("terminales") or []) if (t.get("match") or "").strip()],
        "tickets": tickets,
        "integrador_glpi": integrador_glpi,
        "notificaciones": canales,
        "reportes": b.get("reportes", {}) or {},        # reportes proactivos por cliente
        "proactivo": b.get("proactivo", {}) or {},      # alerta SLA por vencer (por cliente)
        # Wiki Outline para la base de conocimiento. Sólo con valores reales (url/token).
        "kb_outline": {k: v for k, v in (b.get("kb_outline") or {}).items() if v},
    }


def _nuevo_cliente(b, api_key):
    """Registro de una empresa NUEVA: el formulario más los valores por omisión de lo que el
    formulario no maneja."""
    cli = _armar_cliente(b, api_key)
    cli["velocidad"] = 1.2
    cli["integrador_glpi"]["poll_interval"] = 60   # 5 s era pegarle a GLPI 17.280 veces por día
    return cli


def _fusionar_cliente(previo: dict, nuevo: dict) -> dict:
    """Mezcla lo que mandó el formulario SOBRE lo que ya estaba guardado.

    POR QUÉ NO SE PISA Y LISTO: `_armar_cliente` arma el registro con los campos del formulario, y
    el formulario no tiene todos los campos. Guardar su salida tal cual BORRABA todo lo que se
    configura por fuera de esa pantalla —el bloque `tecnicos` del cliente, los tokens de GLPI de
    cada técnico, `planka`, `empresa_saludo`, `abreviatura`, `horario_atencion`, `microfono`—. Una
    edición inocente para cambiar un correo dejaba al equipo sin sus tokens y al ciclo leyendo los
    comentarios de los técnicos como si fueran del cliente.

    Reglas:
      · lo que el formulario NO trae, se CONSERVA tal como estaba;
      · un secreto que llega VACÍO no pisa al guardado: sólo se reemplaza cuando mandan uno nuevo;
      · las listas sí se reemplazan enteras (son la edición completa de esa lista: canales,
        terminales), porque quitar un elemento tiene que poder quitarlo."""
    from comun import cifrado as CIF
    if not isinstance(previo, dict):
        return nuevo
    out = copy.deepcopy(previo)
    for k, v in (nuevo or {}).items():
        if isinstance(v, dict):
            out[k] = _fusionar_cliente(out.get(k) if isinstance(out.get(k), dict) else {}, v)
        elif isinstance(v, str) and CIF._es_sensible(k) and k != "api_key":
            if v:
                out[k] = v                   # secreto NUEVO de verdad
            # vacío -> se conserva el que ya estaba
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- vistas HTML
@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


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
        if integ not in (None, "") else ""
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


# ================= WhatsApp NO-OFICIAL: vincular por QR =================
# El panel (con la sesión del administrador) resuelve api_key -> id de sesión; el trabajo real
# (neonize + QR) corre en el CENTRAL, que es donde vive WhatsApp.
def _central_get(path):
    with urllib.request.urlopen(CENTRAL_URL + path, timeout=8) as r:
        return json.load(r)


def _central_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(CENTRAL_URL + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)


def _resolver_sesion_wa(api_key):
    """(sesion, None) si la empresa existe; (None, JSONResponse) si no."""
    from comun import whatsapp_link as WL
    c = _cliente_por_key((api_key or "").strip())
    if not c:
        return None, JSONResponse({"error": "empresa no encontrada"}, status_code=404)
    return WL.sesion_de_cliente(c), None


@app.post("/api/whatsapp/vincular")
async def wa_vincular_panel(request: Request):
    b = await request.json()
    sesion, err = _resolver_sesion_wa(b.get("api_key"))
    if err:
        return err
    try:
        return _central_post("/api/whatsapp/vincular", {"sesion": sesion})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"estado": "error", "error": f"no se pudo iniciar: {e}"}, status_code=502)


@app.get("/api/whatsapp/estado")
async def wa_estado_panel(api_key: str = ""):
    s, err = _resolver_sesion_wa(api_key)
    if err:
        return err
    try:
        return _central_get(f"/api/whatsapp/estado?sesion={urllib.parse.quote(s)}")
    except Exception:  # noqa: BLE001
        return {"estado": "desconocido"}           # transitorio: el front reintenta


@app.post("/api/whatsapp/desvincular")
async def wa_desvincular_panel(request: Request):
    b = await request.json()
    sesion, err = _resolver_sesion_wa(b.get("api_key"))
    if err:
        return err
    try:
        return _central_post("/api/whatsapp/desvincular", {"sesion": sesion})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/resumen")
def resumen():
    """Actividad del mes (tickets gestionados, avisos, consultas) para el panel general."""
    uso = {}
    for c in _cargar().get("clientes", []):
        for k, v in M.resumen(c.get("nombre", "")).get("uso", {}).items():
            uso[k] = uso.get(k, 0) + v
    return {"uso_total": uso}


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


@app.post("/api/clientes")
async def upsert(request: Request):
    """Guarda la configuración de la empresa (o crea una si no hay api_key)."""
    b = await request.json()
    if not (b.get("nombre") or "").strip():
        return JSONResponse({"error": "falta el nombre de la empresa"}, status_code=400)
    try:
        data = _cargar(estricto=True)
    except ConfigIlegible as e:
        return JSONResponse({"error": "no se pudo leer la configuración guardada; no se guardó nada "
                                      f"para no pisarla ({str(e)[:80]})"}, status_code=500)
    api_key = b.get("api_key") or None
    if not api_key:
        slug = "".join(ch for ch in b["nombre"].upper() if ch.isalnum())[:8] or "CLI"
        api_key = f"{slug}-{secrets.token_hex(6)}"
    previo = next((c for c in data.get("clientes", []) if c.get("api_key") == api_key), None)
    # Se FUSIONA sobre lo guardado: el formulario no tiene todos los campos y pisarlo entero
    # borraba la configuración que se hace por fuera de esa pantalla (ver `_fusionar_cliente`).
    cli = (_fusionar_cliente(previo, _armar_cliente(b, api_key)) if previo
           else _nuevo_cliente(b, api_key))
    data["clientes"] = [c for c in data.get("clientes", []) if c.get("api_key") != api_key]
    data["clientes"].append(cli)
    _guardar(data)
    return {"ok": True, "api_key": api_key}
