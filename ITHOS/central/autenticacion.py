#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS Gestor — autenticación del superadmin + enlaces de alta de un solo uso.

MODELO DE ACCESO (requerimiento permanente):
  · Al GESTOR (panel superadmin `/` + APIs de gestión) accede SOLO INTELLIHELP S.A.
    (la empresa propietaria). Se protege con un TOKEN de admin (cookie de sesión).
  · El CLIENTE accede SOLO a su dashboard `/panel/<api_key>` (la api_key es su credencial).
  · El ALTA `/alta` es un enlace TEMPORAL de un solo uso (token que caduca y se consume).

El token de admin se toma de `ITHOS_ADMIN_TOKEN` (env). Si no está, se genera uno y se
persiste en `_gestor_admin.token` (y conviene fijar uno propio en producción).
"""
import os
import json
import time
import threading
import hmac
import base64
import hashlib
import secrets

BASE = os.path.dirname(os.path.abspath(__file__))
_TOKEN_FILE = os.path.join(BASE, "_gestor_admin.token")
COOKIE = "gestor_admin"


def _hash_file() -> str:
    """Archivo con el HASH de la contraseña de login (cuando el admin la cambió desde el panel).
    Persiste en ITHOS_DATA si está (volumen), para sobrevivir a rebuilds del contenedor."""
    d = (os.environ.get("ITHOS_DATA") or "").strip()
    return os.path.join(d or BASE, "_gestor_admin.hash")


def _alta_path() -> str:
    """Archivo de tokens de alta. En la demo se aísla con `ITHOS_ALTA_FILE` (env) para no
    tocar los de producción y poder borrarlo al cerrar (la demo no deja nada registrado)."""
    return (os.environ.get("ITHOS_ALTA_FILE") or "").strip() or os.path.join(BASE, "_alta_tokens.json")


# --------------------------------------------------------- usuario + contraseña
def admin_user() -> str:
    """Usuario del superadmin: del env `ITHOS_ADMIN_USER`, o 'intellihelp' por defecto."""
    return (os.environ.get("ITHOS_ADMIN_USER") or "intellihelp").strip()


def admin_token() -> str:
    """Contraseña de admin: del env `ITHOS_ADMIN_TOKEN`, o generada y persistida una vez."""
    t = (os.environ.get("ITHOS_ADMIN_TOKEN") or "").strip()
    if t:
        return t
    try:
        with open(_TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(24)
    try:
        with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(t)
    except OSError:
        pass
    return t


# --------------------------------------------- contraseña de login (hash salado, cambiable)
# La contraseña de LOGIN se puede cambiar desde el panel; se guarda como HASH salado (scrypt), nunca
# en claro. Si todavía no se cambió, se usa ITHOS_ADMIN_TOKEN (bootstrap del .env). El token interno
# de servicio (X-Admin-Token entre panel y central) SIGUE siendo ITHOS_ADMIN_TOKEN (no lo toca el
# usuario): así el login humano es cambiable sin romper las llamadas internas.
def _hash_password(clave: str, salt: bytes = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(clave.encode("utf-8"), salt=salt, n=16384, r=8, p=1,
                        dklen=32, maxmem=64 * 1024 * 1024)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def _verificar_hash(clave: str, registro: str) -> bool:
    try:
        _alg, n, r, p, salt_b64, dk_b64 = registro.split("$")
        salt = base64.b64decode(salt_b64)
        esperado = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(clave.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
                            dklen=len(esperado), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(dk, esperado)
    except Exception:  # noqa: BLE001
        return False


def _leer_hash() -> str:
    try:
        with open(_hash_file(), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def password_cambiada() -> bool:
    """True si el admin ya fijó su propia contraseña (hay hash guardado)."""
    return bool(_leer_hash())


def _secreto_login() -> str:
    """El secreto vigente para el login/cookie: el hash guardado (si lo hay) o el token del .env."""
    return _leer_hash() or admin_token()


MAX_EDAD_SESION = 8 * 3600          # una sesión del panel dura, como mucho, 8 horas


def _corte_file() -> str:
    """Marca de 'lo emitido ANTES de este instante ya no vale' (la fija /logout)."""
    d = (os.environ.get("ITHOS_DATA") or "").strip()
    return os.path.join(d or BASE, "_gestor_sesiones.corte")


def _corte_sesiones() -> float:
    try:
        with open(_corte_file(), encoding="utf-8") as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0.0


def _firmar(emitida: int) -> str:
    base = f"ithos-gestor:{admin_user()}:{_secreto_login()}:{emitida}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _cookie_val() -> str:
    """Cookie de sesión FIRMADA y con fecha de emisión.

    Antes era un SHA-256 fijo de usuario+secreto: el MISMO valor para todas las sesiones y para
    siempre. Así no se podía vencer ni revocar nada —`max_age` sólo le pide al navegador que la
    olvide; el servidor la seguía aceptando— y `/logout` apenas borraba la copia del navegador:
    una cookie copiada servía hasta cambiar la contraseña. Ahora lleva CUÁNDO se emitió, firmada:
    el servidor la vence a las 8 horas y `/logout` invalida todas las anteriores. Sigue valiendo
    lo de antes: al cambiar la contraseña, las sesiones viejas se caen solas."""
    emitida = int(time.time())
    return f"{emitida}.{_firmar(emitida)}"


def token_ok(k) -> bool:
    """True si `k` es el TOKEN INTERNO de servicio (X-Admin-Token). No cambia con el login humano."""
    return bool(k) and hmac.compare_digest(str(k), admin_token())


def credenciales_ok(usuario, clave) -> bool:
    """True si usuario + contraseña de LOGIN coinciden. Usa el hash guardado si el admin ya cambió su
    contraseña; si no, el ITHOS_ADMIN_TOKEN de bootstrap (comparación en tiempo constante)."""
    if not usuario or not clave or not hmac.compare_digest(str(usuario), admin_user()):
        return False
    reg = _leer_hash()
    if reg:
        return _verificar_hash(str(clave), reg)
    return hmac.compare_digest(str(clave), admin_token())


def cambiar_password(actual: str, nueva: str):
    """Cambia la contraseña de login (la fija el admin, nadie más la ve). Devuelve (ok, mensaje)."""
    if not credenciales_ok(admin_user(), actual):
        return False, "La contraseña actual no es correcta."
    nueva = (nueva or "").strip()
    if len(nueva) < 10:
        return False, "La nueva contraseña debe tener al menos 10 caracteres."
    if nueva == (actual or ""):
        return False, "La nueva contraseña no puede ser igual a la actual."
    try:
        with open(_hash_file(), "w", encoding="utf-8") as f:
            f.write(_hash_password(nueva))
        try:
            os.chmod(_hash_file(), 0o600)      # best-effort (no-op en Windows)
        except OSError:
            pass
        return True, "Contraseña actualizada. Volvé a entrar con la nueva."
    except OSError as e:
        return False, f"No se pudo guardar la contraseña: {e}"


def cookie_ok(request) -> bool:
    """True si la cookie es válida: firma correcta, NO vencida y posterior al último /logout."""
    emitida_txt, _, firma = request.cookies.get(COOKIE, "").partition(".")
    try:
        emitida = int(emitida_txt)
    except (TypeError, ValueError):
        return False
    if not hmac.compare_digest(firma, _firmar(emitida)):
        return False
    ahora = time.time()
    if emitida > ahora + 60 or ahora - emitida > MAX_EDAD_SESION:
        return False                               # emitida en el futuro, o vencida
    return emitida >= _corte_sesiones()            # revocada por un /logout posterior


def header_ok(request) -> bool:
    """True si trae la cabecera `X-Admin-Token` con la contraseña (llamadas internas/API)."""
    return token_ok(request.headers.get("X-Admin-Token", ""))


def es_admin(request) -> bool:
    """Admin por cookie de sesión (navegador) o por cabecera (llamadas programáticas)."""
    return cookie_ok(request) or header_ok(request)


def set_cookie(response) -> None:
    # secure=True (cookie SOLO por HTTPS) en producción; en la demo (http://localhost) no, si no el
    # navegador no la manda y el login entra en loop. httponly: no accesible por JS (anti-XSS).
    seguro = not os.environ.get("ITHOS_DEMO")
    response.set_cookie(COOKIE, _cookie_val(), httponly=True, samesite="lax",
                        secure=seguro, max_age=MAX_EDAD_SESION)


def borrar_cookie(response) -> None:
    """Cierra la sesión DE VERDAD: borra la cookie del navegador y deja asentado en el servidor que
    todo lo emitido hasta ahora deja de valer. Sin esto, una cookie copiada antes del 'cerrar
    sesión' seguía entrando."""
    try:
        # En SEGUNDOS ENTEROS, igual que la marca de la cookie: si el corte se guardara con
        # decimales sería SIEMPRE mayor que la cookie emitida en ese mismo segundo, y el login
        # inmediatamente posterior al logout quedaría rechazado.
        with open(_corte_file(), "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass
    response.delete_cookie(COOKIE)


# --------------------------------------------------- enlaces de alta de un solo uso
# Un enlace de alta vale UNA sola vez. Leer-modificar-escribir sin candado es una carrera: dos
# envíos a la vez (el doble clic de siempre) leían los dos "sin usar" y los dos pasaban. Y una
# escritura no atómica deja el archivo a medias si el proceso muere en el medio: al leerlo se cae
# al `except` y se pierden TODOS los enlaces vigentes, en silencio.
_ALTA_LOCK = threading.Lock()


def _alta_cargar() -> dict:
    try:
        with open(_alta_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _alta_guardar(d: dict) -> None:
    try:
        from comun import cifrado as CIF
        CIF.escribir_json(_alta_path(), d)         # atómica: la misma que usa clientes.json
    except Exception:  # noqa: BLE001
        try:
            with open(_alta_path(), "w", encoding="utf-8") as f:
                json.dump(d, f)
        except OSError:
            pass


def nuevo_alta_token(nombre: str = "", horas: int = 48) -> str:
    """Crea un token de alta de un solo uso que caduca en `horas`. De paso limpia los viejos."""
    with _ALTA_LOCK:
        ahora = time.time()
        d = {k: v for k, v in _alta_cargar().items()
             if not v.get("usado") and v.get("exp", 0) > ahora}
        t = secrets.token_urlsafe(18)
        d[t] = {"nombre": nombre, "exp": ahora + horas * 3600, "usado": False}
        _alta_guardar(d)
        return t


def alta_valido(t) -> bool:
    x = _alta_cargar().get(str(t or ""))
    return bool(x) and not x.get("usado") and time.time() < x.get("exp", 0)


def alta_consumir(t) -> None:
    with _ALTA_LOCK:
        d = _alta_cargar()
        if t in d:
            d[t]["usado"] = True
            _alta_guardar(d)


def revocar_alta(t) -> bool:
    """Revoca (elimina) un token de alta generado: si te equivocaste al generarlo, deja de valer YA.
    Devuelve True si existía y se sacó."""
    with _ALTA_LOCK:
        tid = str(t or "")
        d = _alta_cargar()
        if tid in d:
            del d[tid]
            _alta_guardar(d)
            return True
        return False


def consumir_si_valido(t) -> bool:
    """ATÓMICO: si el token de alta es válido y NO usado, lo marca usado y devuelve True (una sola
    vez). Si ya se usó / venció / no existe → False. Se llama al ENVIAR el formulario: el enlace
    queda consumido en el acto (no se puede reusar) y evita la carrera del doble submit.

    El candado es lo que lo hace atómico DE VERDAD: sin él, dos envíos simultáneos leían los dos
    el mismo "sin usar" y los dos pasaban, que es exactamente lo que este enlace no puede permitir."""
    with _ALTA_LOCK:
        tid = str(t or "")
        d = _alta_cargar()
        x = d.get(tid)
        if not x or x.get("usado") or time.time() >= x.get("exp", 0):
            return False
        d[tid]["usado"] = True
        _alta_guardar(d)
        return True


# ------------------------------------------------------------------- login HTML
LOGIN_HTML = """<!doctype html><html lang=es><meta charset=utf-8>
<title>ITHOS Gestor - Acceso</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>body{background:#0a0e14;color:#cfe8ff;font-family:system-ui,'Segoe UI',sans-serif;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.box{background:#0f1622;border:1px solid #1d3a5f;border-radius:14px;padding:32px 28px;width:340px;
box-shadow:0 8px 40px #0008}h1{font-size:19px;margin:0 0 4px;color:#e8f4ff}
p{color:#7fa8cf;font-size:13px;margin:0 0 18px}
input{width:100%;box-sizing:border-box;padding:11px 12px;border-radius:9px;border:1px solid #24466e;
background:#0a121e;color:#e8f4ff;font-size:14px;outline:none}
input:focus{border-color:#1f6feb}input+input{margin-top:10px}
button{width:100%;margin-top:12px;padding:11px;border:0;
border-radius:9px;background:#1f6feb;color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:hover{background:#2b7bf5}.err{color:#ff8a8a;font-size:12.5px;margin-top:10px;min-height:16px}
</style>
<form class=box method=post action="/login">
<h1>ITHOS Gestor</h1><p>Acceso exclusivo de INTELLIHELP S.A.</p>
<input type=text name=usuario placeholder="Usuario" autofocus autocomplete=username>
<input type=password name=k placeholder="Contraseña" autocomplete=current-password>
<button type=submit>Entrar</button>
<div class=err>%ERR%</div></form></html>"""

ALTA_INVALIDO_HTML = """<!doctype html><html lang=es><meta charset=utf-8>
<title>ITHOS - Enlace de alta</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>body{background:#0a0e14;color:#cfe8ff;font-family:system-ui,'Segoe UI',sans-serif;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;text-align:center}
.box{background:#0f1622;border:1px solid #5f1d1d;border-radius:14px;padding:34px 30px;max-width:420px}
h1{font-size:19px;margin:0 0 10px;color:#ffd0d0}p{color:#9fb8cf;font-size:14px;line-height:1.5;margin:0}
</style><div class=box><h1>Enlace de alta invalido o vencido</h1>
<p>Este enlace de alta ya se uso o caduco. Pedile a <b>INTELLIHELP S.A.</b> un nuevo
enlace temporal para dar de alta tu empresa.</p></div></html>"""
