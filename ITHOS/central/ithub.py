#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS Gestor — ingreso con ITHub (sesión única de INTELLIHELP, OpenID Connect).

Con ITHub configurado (`ITHUB_CLIENT_ID` y `ITHUB_CLIENT_SECRET` en `ITHOS/.env`), el panel deja de
pedir usuario y contraseña: /login manda a ITHub, ITHub ya validó la cuenta de Google y el dominio,
decide si la persona tiene acceso al Gestor y con qué rol (claim `rol`), y vuelve a /ithub-callback
con un código. Si ya había sesión en ITHub, se entra sin ver ninguna pantalla.

  · Ida (/ithub-login): state, nonce y verificador de PKCE (S256) viajan en una cookie CIFRADA de
    10 minutos (AES-256-GCM): el panel no tiene sesiones en el servidor y así no hace falta.
  · Vuelta (/ithub-callback): se canjea el código servidor a servidor (con el secreto, Basic) y se
    valida el id_token entero: RS256 con la clave del `kid` (JWKS de ITHub, en caché una hora; si el
    kid no está se vuelve a bajar), iss, aud, exp (60 s de tolerancia) y nonce. Entra sólo el rol
    `admin`: el Gestor no tiene otro.
  · Sesión: cookie cifrada `gestor_ithub` con quién es, el `sid` de ITHub y el id_token (para salir
    sin que ITHub pregunte). Vence a las 8 horas, como la del administrador.
  · Aviso de cierre (/ithub-logout, back-channel logout): ITHub manda un logout_token firmado cuando
    la sesión única se cierra o le sacan el Gestor a alguien. Se anota el `sid` (o el `sub`) en
    `ITHOS_DATA/_ithub_cierres.json` y la cookie con ese sid deja de valer en el pedido siguiente.
  · Salida (/logout): cierra la sesión local, anota su sid y manda a /oauth/logout de ITHub, que
    cierra la sesión única en todas las apps.

Sin la config, nada de esto se activa y el panel sigue con el login de siempre. El usuario y la
contraseña del administrador quedan como ACCESO DE EMERGENCIA (/login?manual=1): ITHub vive en otro
servidor y, si se cae, el Gestor no puede quedar sin nadie que entre.

Contrato completo: md/INTEGRAR-APLICACION.md del repo ITHub-Portal. Sin dependencias nuevas: la
firma se verifica con `cryptography` (ya está por el cifrado en reposo) y HTTP con urllib.
"""
import os
import json
import time
import base64
import hashlib
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE = os.path.dirname(os.path.abspath(__file__))
COOKIE = "gestor_ithub"              # sesión abierta con ITHub
COOKIE_TX = "gestor_ithub_tx"        # ida y vuelta del ingreso (state, nonce, PKCE)
EVENTO_LOGOUT = "http://schemas.openid.net/event/backchannel-logout"
JWKS_TTL = 3600
TX_TTL = 600
MAX_EDAD_SESION = 8 * 3600
TOLERANCIA = 60
ROLES_GESTOR = ("admin",)            # el Gestor tiene un solo rol: el que administra todo


class ErrorITHub(Exception):
    """Motivo corto de un rechazo (va al log del contenedor, nunca a la pantalla)."""


# ---------------------------------------------------------------------- configuración
def cfg() -> dict:
    e = os.environ
    dominio = (e.get("ITHOS_DOMINIO") or "").strip()
    base = (e.get("ITHUB_URL_BASE") or (f"https://{dominio}" if dominio else "")).strip().rstrip("/")
    return {
        "issuer": (e.get("ITHUB_ISSUER") or "https://ithub.intellihelp.tech").strip().rstrip("/"),
        "client_id": (e.get("ITHUB_CLIENT_ID") or "").strip(),
        "client_secret": (e.get("ITHUB_CLIENT_SECRET") or "").strip(),
        "base": base,
    }


def habilitado() -> bool:
    """¿El ingreso es por ITHub? Hace falta client_id, client_secret y la URL pública del Gestor."""
    c = cfg()
    return bool(c["client_id"] and c["client_secret"] and c["base"])


def redirect_uri() -> str:
    return cfg()["base"] + "/ithub-callback"


def url_login() -> str:
    """Pantalla de ingreso del Gestor: es la `post_logout_redirect_uri` registrada en ITHub."""
    return cfg()["base"] + "/login"


# ---------------------------------------------------------------------- utilidades
def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64url_dec(t: str) -> bytes:
    t = str(t or "")
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


def _clave_cookies() -> bytes:
    """Clave AES-256 de las cookies de ITHub, derivada del secreto de ITHub y del token interno
    del Gestor. Rotar cualquiera de los dos invalida todas las sesiones abiertas con ITHub."""
    import autenticacion as AUTH
    base = f"ithos-gestor-ithub:{cfg()['client_secret']}:{AUTH.admin_token()}"
    return hashlib.sha256(base.encode("utf-8")).digest()


def _sellar(datos: dict, contexto: bytes) -> str:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_clave_cookies()).encrypt(nonce, json.dumps(datos, separators=(",", ":")).encode(),
                                          contexto)
    return b64url(nonce + ct)


def _abrir(valor: str, contexto: bytes):
    try:
        raw = b64url_dec(valor)
        if len(raw) < 13:
            return None
        return json.loads(AESGCM(_clave_cookies()).decrypt(raw[:12], raw[12:], contexto))
    except (InvalidTag, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------- ida a ITHub
def nueva_transaccion() -> tuple:
    """Devuelve (url de /oauth/authorize, valor de la cookie de ida) con state, nonce y PKCE."""
    c = cfg()
    tx = {"s": secrets.token_hex(16), "n": secrets.token_hex(16), "v": b64url(secrets.token_bytes(48)),
          "t": int(time.time())}
    reto = b64url(hashlib.sha256(tx["v"].encode("ascii")).digest())
    url = c["issuer"] + "/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": c["client_id"],
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": tx["s"],
        "nonce": tx["n"],
        "code_challenge": reto,
        "code_challenge_method": "S256",
    })
    return url, _sellar(tx, b"tx")


def leer_transaccion(valor: str):
    tx = _abrir(valor or "", b"tx")
    if not isinstance(tx, dict) or time.time() - int(tx.get("t", 0)) > TX_TTL:
        return None
    return tx


# ---------------------------------------------------------------------- HTTP con ITHub
def _http(url: str, post: dict = None, timeout: int = 10) -> tuple:
    """Pedido a ITHub. Devuelve (código, json). Sin conexión, (0, {}). Nunca loguea el secreto."""
    c = cfg()
    datos = None
    cab = {"Accept": "application/json", "User-Agent": "ITHOS-Gestor"}
    if post is not None:
        datos = urllib.parse.urlencode(post).encode()
        cred = f"{urllib.parse.quote(c['client_id'], safe='')}:{urllib.parse.quote(c['client_secret'], safe='')}"
        cab["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
        cab["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=datos, headers=cab, method="POST" if post is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError):
        return 0, {}


def canjear_codigo(code: str, verificador: str) -> dict:
    _, r = _http(cfg()["issuer"] + "/oauth/token", {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "code_verifier": verificador,
    })
    return r if isinstance(r, dict) else {}


# ---------------------------------------------------------------------- claves públicas
_JWKS = {"claves": {}, "t": 0.0, "ultimo_intento": 0.0}
_LOCK = threading.Lock()


def _jwks_archivo() -> str:
    d = (os.environ.get("ITHOS_DATA") or "").strip()
    return os.path.join(d or BASE, "_ithub_jwks.json")


def jwks(kid: str = "") -> dict:
    """Claves de ITHub por kid (en memoria y en ITHOS_DATA, una hora). Si el kid pedido no está
    (ITHub rotó la clave) se vuelven a bajar, como mucho una vez por minuto: un token con un kid
    inventado no puede hacer que el Gestor le pegue a ITHub en cada pedido."""
    ahora = time.time()
    with _LOCK:
        if not _JWKS["claves"]:
            try:
                with open(_jwks_archivo(), encoding="utf-8") as f:
                    g = json.load(f)
                _JWKS["claves"], _JWKS["t"] = dict(g.get("claves") or {}), float(g.get("t") or 0)
            except (OSError, ValueError, AttributeError):
                pass
        fresca = ahora - _JWKS["t"] < JWKS_TTL
        if _JWKS["claves"] and fresca and (not kid or kid in _JWKS["claves"]):
            return dict(_JWKS["claves"])
        if ahora - _JWKS["ultimo_intento"] < 60 and _JWKS["claves"]:
            return dict(_JWKS["claves"])
        _JWKS["ultimo_intento"] = ahora
        codigo, r = _http(cfg()["issuer"] + "/oauth/jwks")
        claves = {}
        for k in (r.get("keys") or []) if codigo == 200 and isinstance(r, dict) else []:
            if isinstance(k, dict) and k.get("kty") == "RSA" and k.get("kid") and k.get("n") and k.get("e"):
                claves[str(k["kid"])] = {"kty": "RSA", "kid": str(k["kid"]), "n": k["n"], "e": k["e"]}
        if claves:
            _JWKS["claves"], _JWKS["t"] = claves, ahora
            try:
                tmp = _jwks_archivo() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"claves": claves, "t": ahora}, f)
                os.replace(tmp, _jwks_archivo())
            except OSError:
                pass
        return dict(_JWKS["claves"])


def clave_publica(jwk: dict):
    n = int.from_bytes(b64url_dec(jwk.get("n", "")), "big")
    e = int.from_bytes(b64url_dec(jwk.get("e", "")), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


# ---------------------------------------------------------------------- validación de JWT
def validar_jwt(jwt: str, nonce: str = None, es_logout: bool = False, claves: dict = None) -> dict:
    """Valida un JWT de ITHub (id_token o logout_token) y devuelve sus claims.

    Comprueba: RS256, firma con la clave del kid, iss = issuer, aud = nuestro client_id, exp (60 s
    de tolerancia) y, si se pasa, el nonce. Un logout_token además tiene que traer el evento de
    back-channel logout, no puede traer nonce y tiene que nombrar un sid o un sub.
    `claves` es para los tests; None = las de ITHub.
    """
    partes = str(jwt or "").split(".")
    if len(partes) != 3:
        raise ErrorITHub("formato")
    h, p, s = partes
    try:
        cab = json.loads(b64url_dec(h))
        c = json.loads(b64url_dec(p))
        firma = b64url_dec(s)
    except (ValueError, TypeError):
        raise ErrorITHub("formato")
    if not isinstance(cab, dict) or not isinstance(c, dict):
        raise ErrorITHub("formato")
    if cab.get("alg") != "RS256":
        raise ErrorITHub("alg")
    kid = str(cab.get("kid") or "")
    claves = jwks(kid) if claves is None else claves
    if kid not in claves:
        raise ErrorITHub("kid")
    try:
        clave_publica(claves[kid]).verify(firma, f"{h}.{p}".encode("ascii"), padding.PKCS1v15(),
                                          hashes.SHA256())
    except (InvalidSignature, ValueError):
        raise ErrorITHub("firma")
    conf = cfg()
    aud = c.get("aud")
    aud_ok = conf["client_id"] in aud if isinstance(aud, list) else aud == conf["client_id"]
    if c.get("iss") != conf["issuer"] or not aud_ok or not conf["client_id"]:
        raise ErrorITHub("iss/aud")
    try:
        exp = int(c.get("exp") or 0)
    except (TypeError, ValueError):
        exp = 0
    if exp < time.time() - TOLERANCIA:
        raise ErrorITHub("vencido")
    if es_logout:
        eventos = c.get("events")
        if (not isinstance(eventos, dict) or EVENTO_LOGOUT not in eventos or "nonce" in c
                or not (c.get("sid") or c.get("sub"))):
            raise ErrorITHub("logout_token")
    elif nonce is not None and not secrets.compare_digest(str(nonce), str(c.get("nonce") or "")):
        raise ErrorITHub("nonce")
    return c


def rol_gestor(claims: dict) -> str:
    """El rol del token si es uno del Gestor ('admin'); si no, ''."""
    rol = str(claims.get("rol") or "")
    return rol if rol in ROLES_GESTOR else ""


# ---------------------------------------------------------------------- sesión con ITHub
def valor_sesion(claims: dict, id_token: str) -> str:
    return _sellar({
        "e": int(time.time()),
        "sid": str(claims.get("sid") or ""),
        "sub": str(claims.get("sub") or ""),
        "email": str(claims.get("email") or ""),
        "nombre": str(claims.get("name") or ""),
        "rol": rol_gestor(claims),
        "idt": id_token,
    }, b"sesion")


def sesion(request):
    """La sesión de ITHub del pedido (dict) si es válida: descifra, no vencida, rol del Gestor y
    sin aviso de cierre de ITHub. Si no, None."""
    if not habilitado():
        return None
    s = _abrir(request.cookies.get(COOKIE, ""), b"sesion")
    if not isinstance(s, dict):
        return None
    try:
        emitida = int(s.get("e") or 0)
    except (TypeError, ValueError):
        return None
    ahora = time.time()
    if emitida > ahora + TOLERANCIA or ahora - emitida > MAX_EDAD_SESION:
        return None
    if s.get("rol") not in ROLES_GESTOR:
        return None
    if cerrada(s.get("sid", ""), s.get("sub", ""), emitida):
        return None
    return s


def sesion_ok(request) -> bool:
    return sesion(request) is not None


def set_cookie_sesion(response, valor: str) -> None:
    response.set_cookie(COOKIE, valor, httponly=True, samesite="lax", secure=True,
                        max_age=MAX_EDAD_SESION)


def set_cookie_tx(response, valor: str) -> None:
    response.set_cookie(COOKIE_TX, valor, httponly=True, samesite="lax", secure=True, max_age=TX_TTL)


def url_salida(id_token: str = "") -> str:
    """Salida de ITHub: cierra la sesión única y vuelve al login del Gestor. Con el id_token como
    pista, ITHub no pregunta."""
    c = cfg()
    q = {"post_logout_redirect_uri": url_login(), "client_id": c["client_id"]}
    if id_token:
        q["id_token_hint"] = id_token
    return c["issuer"] + "/oauth/logout?" + urllib.parse.urlencode(q)


# ---------------------------------------------------------------------- cierres (back-channel)
def _cierres_archivo() -> str:
    d = (os.environ.get("ITHOS_DATA") or "").strip()
    return os.path.join(d or BASE, "_ithub_cierres.json")


def _leer_cierres() -> dict:
    try:
        with open(_cierres_archivo(), encoding="utf-8") as f:
            d = json.load(f)
        return {"sid": dict(d.get("sid") or {}), "sub": dict(d.get("sub") or {})}
    except (OSError, ValueError, AttributeError):
        return {"sid": {}, "sub": {}}


def cerrar(sid: str = "", sub: str = "") -> None:
    """Anota el cierre: con `sid`, esa sesión de ITHub; con sólo `sub`, toda sesión de esa persona
    abierta hasta ahora. Se limpia lo de más de dos días (una sesión dura como mucho 8 horas)."""
    ahora = int(time.time())
    with _LOCK:
        d = _leer_cierres()
        if sid:
            d["sid"][sid] = ahora
        elif sub:
            d["sub"][sub] = ahora
        for k in ("sid", "sub"):
            d[k] = {x: t for x, t in d[k].items() if ahora - int(t) < 2 * 86400}
        try:
            tmp = _cierres_archivo() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, _cierres_archivo())
        except OSError:
            pass


def cerrada(sid: str, sub: str, emitida: int) -> bool:
    d = _leer_cierres()
    if sid and sid in d["sid"]:
        return True
    t = d["sub"].get(sub) if sub else None
    return t is not None and emitida <= int(t)
