#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ingreso con ITHub (sesión única de INTELLIHELP, OpenID Connect) en el panel del Gestor.

Firma los tokens con una clave RSA generada en el momento y reemplaza el JWKS y el canje del código
de ITHub: no necesita red ni ninguna cuenta. Ejercita las rutas reales del panel con TestClient.

  · Sin la config, el login de siempre (nada de ITHub a la vista).
  · /login -> /ithub-login -> /oauth/authorize con state, nonce y PKCE S256.
  · id_token: firma, alg, kid, iss, aud, exp y nonce; sólo entra el rol `admin`.
  · Vuelta: state contra la cookie cifrada, access_denied, sesión abierta.
  · Aviso de cierre (back-channel): 400 con basura, 200 con un logout_token válido y la sesión cae.
  · Salir: manda a /oauth/logout de ITHub con id_token_hint y una copia de la cookie deja de entrar.
  · El acceso de emergencia del administrador (?manual=1) sigue funcionando.

Uso:  python tests/probar_ithub.py
"""
import os
import sys
import json
import time
import tempfile
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))

_TMP = tempfile.mkdtemp(prefix="ithos_ithub_")
os.environ["ITHOS_DATA"] = _TMP
os.environ["ITHOS_ADMIN_USER"] = "intellihelp"
os.environ["ITHOS_ADMIN_TOKEN"] = "contrasena-de-prueba-ithub-2026"
for _v in ("ITHUB_CLIENT_ID", "ITHUB_CLIENT_SECRET", "ITHUB_ISSUER", "ITHUB_URL_BASE"):
    os.environ.pop(_v, None)
os.environ["ITHOS_DOMINIO"] = "gestor.ejemplo.test"

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


def seccion(t):
    print(f"\n=== {t} ===")


from cryptography.hazmat.primitives import hashes                # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from fastapi.testclient import TestClient                          # noqa: E402

import ithub as ITHUB      # noqa: E402
import panel as P          # noqa: E402

ISS = "https://ithub.intellihelp.tech"
CLAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTRA = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(priv, kid):
    pn = priv.public_key().public_numbers()
    a = lambda n: ITHUB.b64url(n.to_bytes((n.bit_length() + 7) // 8, "big"))  # noqa: E731
    return {"kty": "RSA", "kid": kid, "n": a(pn.n), "e": a(pn.e)}


CLAVES = {"k1": _jwk(CLAVE, "k1")}


def firmar(claims, priv=CLAVE, kid="k1", alg="RS256"):
    cab = ITHUB.b64url(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    cue = ITHUB.b64url(json.dumps(claims).encode())
    firma = priv.sign(f"{cab}.{cue}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{cab}.{cue}.{ITHUB.b64url(firma)}"


def claims(**extra):
    ahora = int(time.time())
    c = {"iss": ISS, "aud": "ithos", "sub": "12", "sid": "sid-abc", "email": "bsierra@intellihelp.tech",
         "name": "Brian Sierra", "rol": "admin", "roles": ["admin"], "nonce": "n1",
         "iat": ahora, "exp": ahora + 300}
    c.update(extra)
    return {k: v for k, v in c.items() if v is not None}


def logout_token(**extra):
    ahora = int(time.time())
    c = {"iss": ISS, "aud": "ithos", "sub": "12", "sid": "sid-abc", "iat": ahora, "exp": ahora + 120,
         "jti": "j1", "events": {ITHUB.EVENTO_LOGOUT: {}}}
    c.update(extra)
    return firmar({k: v for k, v in c.items() if v is not None})


def rechaza(jwt, motivo, **kw):
    try:
        ITHUB.validar_jwt(jwt, claves=CLAVES, **kw)
        return False
    except ITHUB.ErrorITHub as e:
        return str(e) == motivo


# ITHub de mentira: el JWKS sale de CLAVES y el canje devuelve lo que diga _CANJE.
_CANJE = {}
_PEDIDOS = []


def _http_falso(url, post=None, timeout=10):
    _PEDIDOS.append((url, post))
    if url.endswith("/oauth/jwks"):
        return 200, {"keys": list(CLAVES.values())}
    if url.endswith("/oauth/token"):
        return 200, dict(_CANJE)
    return 404, {}


ITHUB._http = _http_falso


def cliente():
    return TestClient(P.app, base_url="https://testserver", follow_redirects=False)


# ---------------------------------------------------------------------------------------------
seccion("I1 · sin la config, el login de siempre")
c = cliente()
ok(not ITHUB.habilitado(), "sin ITHUB_CLIENT_ID/SECRET el ingreso único está apagado")
r = c.get("/login")
ok(r.status_code == 200 and "Contraseña" in r.text and "ITHub" not in r.text,
   "/login muestra el formulario de usuario y contraseña, sin ITHub", str(r.status_code))
r = c.get("/")
ok(r.status_code == 200 and "Acceso exclusivo" in r.text, "la portada sin sesión muestra el login")
ok(c.get("/ithub-login").headers.get("location") == "/login", "/ithub-login sin config vuelve al login")
ok(c.post("/ithub-logout", data={"logout_token": logout_token()}).status_code == 400,
   "el aviso de cierre sin config responde 400")
for ruta in ("/ithub-login", "/ithub-callback", "/ithub-logout"):
    ok(P._requiere_admin("GET", ruta) is False, f"{ruta} es pública (abre o cierra la sesión)")

# ---------------------------------------------------------------------------------------------
os.environ["ITHUB_CLIENT_ID"] = "ithos"
os.environ["ITHUB_CLIENT_SECRET"] = "ith_secreto_de_prueba_0123456789"

seccion("I2 · validación del id_token")
ok(ITHUB.habilitado(), "con client_id + client_secret + dominio, el ingreso es por ITHub")
ok(ITHUB.redirect_uri() == "https://gestor.ejemplo.test/ithub-callback", "redirect_uri desde ITHOS_DOMINIO",
   ITHUB.redirect_uri())
v = ITHUB.validar_jwt(firmar(claims()), nonce="n1", claves=CLAVES)
ok(v.get("email") == "bsierra@intellihelp.tech", "un id_token bien firmado y vigente se acepta")
ok(ITHUB.validar_jwt(firmar(claims(aud=["otra", "ithos"])), nonce="n1", claves=CLAVES)["sub"] == "12",
   "aud como lista que nos incluye se acepta")
ok(rechaza(firmar(claims(), priv=OTRA), "firma", nonce="n1"), "firmado con otra clave: firma")
ok(rechaza(firmar(claims(), kid="k9"), "kid", nonce="n1"), "kid desconocido: kid")
ok(rechaza(firmar(claims(), alg="HS256"), "alg", nonce="n1"), "alg distinto de RS256: alg")
_cab = ITHUB.b64url(json.dumps({"alg": "none", "kid": "k1"}).encode())
ok(rechaza(f"{_cab}.{ITHUB.b64url(json.dumps(claims()).encode())}.", "alg", nonce="n1"),
   "alg none sin firma: alg")
ok(rechaza(firmar(claims(iss="https://otro.test")), "iss/aud", nonce="n1"), "otro emisor: iss/aud")
ok(rechaza(firmar(claims(aud="crm")), "iss/aud", nonce="n1"), "token de otra app: iss/aud")
ok(rechaza(firmar(claims(exp=int(time.time()) - 120)), "vencido", nonce="n1"), "vencido hace 2 min: vencido")
ok(rechaza(firmar(claims()), "nonce", nonce="otro"), "nonce que no es el de la ida: nonce")
ok(rechaza("basura", "formato"), "texto cualquiera: formato")
_t = firmar(claims()).split(".")
_mod = ITHUB.b64url(json.dumps(claims(rol="admin", email="otro@x.test")).encode())
ok(rechaza(f"{_t[0]}.{_mod}.{_t[2]}", "firma", nonce="n1"), "claims cambiados con la firma original: firma")
ok(ITHUB.rol_gestor(claims()) == "admin" and ITHUB.rol_gestor(claims(rol="usuario")) == "",
   "sólo el rol admin es del Gestor")
ok(rechaza(firmar(claims(events={ITHUB.EVENTO_LOGOUT: {}})), "logout_token", es_logout=True),
   "un id_token (con nonce) no sirve como aviso de cierre")
ok(rechaza(logout_token(events=None), "logout_token", es_logout=True), "logout_token sin el evento: rechazado")

seccion("I3 · claves públicas de ITHub")
ITHUB._JWKS.update({"claves": {}, "t": 0.0, "ultimo_intento": 0.0})
_PEDIDOS.clear()
ok("k1" in ITHUB.jwks("k1"), "el JWKS se baja de /oauth/jwks")
ITHUB.jwks("k1")
ok(sum(1 for u, _ in _PEDIDOS if u.endswith("/jwks")) == 1, "y queda en caché (no se vuelve a pedir)")
for _ in range(5):
    ITHUB.jwks("kid-inventado")
ok(sum(1 for u, _ in _PEDIDOS if u.endswith("/jwks")) == 1,
   "un kid inventado no hace pedir el JWKS en cada pedido (como mucho uno por minuto)",
   str(sum(1 for u, _ in _PEDIDOS if u.endswith("/jwks"))))
ITHUB._JWKS["ultimo_intento"] -= 61                 # pasó el minuto: ITHub pudo rotar la clave
ITHUB.jwks("kid-inventado")
ok(sum(1 for u, _ in _PEDIDOS if u.endswith("/jwks")) == 2,
   "pasado el minuto, un kid que no está hace bajar el JWKS otra vez (rotación de clave)")
ok(os.path.exists(os.path.join(_TMP, "_ithub_jwks.json")), "la caché queda en ITHOS_DATA")

seccion("I4 · /login va a ITHub con state, nonce y PKCE")
c = cliente()
r = c.get("/login")
ok(r.status_code == 302 and r.headers.get("location") == "/ithub-login", "/login -> 302 /ithub-login",
   f"{r.status_code} {r.headers.get('location')}")
ok(c.get("/").headers.get("location") == "/login", "la portada sin sesión -> /login")
r = c.get("/ithub-login")
loc = r.headers.get("location", "")
qs = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))
ok(r.status_code == 302 and loc.startswith(ISS + "/oauth/authorize?"), "/ithub-login -> 302 /oauth/authorize")
ok(qs.get("code_challenge_method") == "S256" and len(qs.get("code_challenge", "")) == 43,
   "con PKCE S256")
ok(qs.get("client_id") == "ithos" and qs.get("response_type") == "code"
   and qs.get("redirect_uri") == "https://gestor.ejemplo.test/ithub-callback"
   and qs.get("scope") == "openid email profile" and qs.get("state") and qs.get("nonce"),
   "client_id, redirect_uri, scope, state y nonce")
tx_cookie = c.cookies.get(ITHUB.COOKIE_TX)
tx = ITHUB.leer_transaccion(tx_cookie)
ok(tx and tx["s"] == qs["state"] and tx["n"] == qs["nonce"], "state y nonce quedan en la cookie de ida")
ok(tx_cookie and qs["state"] not in tx_cookie and tx["v"] not in tx_cookie,
   "la cookie de ida está cifrada (no se lee el verificador)")
ok("Secure" in r.headers.get("set-cookie", "") and "HttpOnly" in r.headers.get("set-cookie", ""),
   "cookie de ida secure + httponly")
ok(ITHUB.leer_transaccion(tx_cookie[:-4] + "AAAA") is None, "una cookie de ida alterada no vale")
r = c.get("/login?manual=1")
ok(r.status_code == 200 and "Ingresar con ITHub" in r.text and "Acceso de emergencia" in r.text,
   "/login?manual=1 muestra el botón de ITHub y el acceso de emergencia")
r = c.get("/login?aviso=<script>")
ok("<script>" not in r.text, "un aviso desconocido no se refleja en la página")

seccion("I5 · la vuelta abre la sesión")
_CANJE.clear()
_CANJE.update({"id_token": firmar(claims(nonce=tx["n"])), "token_type": "Bearer"})
_PEDIDOS.clear()
r = c.get("/ithub-callback", params={"code": "c0d1g0", "state": "otro-state"})
ok(r.status_code == 302 and "aviso=state" in r.headers.get("location", ""), "state distinto: vuelve con aviso")
ok(not any(u.endswith("/oauth/token") for u, _ in _PEDIDOS), "y ni siquiera canjea el código")
c.cookies.set(ITHUB.COOKIE_TX, tx_cookie)
r = c.get("/ithub-callback", params={"error": "access_denied", "state": qs["state"]})
ok("aviso=denegado" in r.headers.get("location", ""), "access_denied: aviso de que no tiene ITHOS en ITHub")
r = c.get("/login?manual=1&aviso=denegado")
ok("no tiene acceso a ITHOS" in r.text, "y el login lo explica")
c.cookies.set(ITHUB.COOKIE_TX, tx_cookie)
_CANJE["id_token"] = firmar(claims(nonce=tx["n"], rol="usuario"))
r = c.get("/ithub-callback", params={"code": "c0d1g0", "state": qs["state"]})
ok("aviso=rol" in r.headers.get("location", "") and c.cookies.get(ITHUB.COOKIE) is None,
   "un rol que no es admin no entra")
c.cookies.set(ITHUB.COOKIE_TX, tx_cookie)
_CANJE["id_token"] = firmar(claims(nonce="no-es-el-de-la-ida"))
r = c.get("/ithub-callback", params={"code": "c0d1g0", "state": qs["state"]})
ok("aviso=token" in r.headers.get("location", ""), "un id_token con otro nonce no entra")
c.cookies.set(ITHUB.COOKIE_TX, tx_cookie)
_CANJE["id_token"] = firmar(claims(nonce=tx["n"]))
_PEDIDOS.clear()
r = c.get("/ithub-callback", params={"code": "c0d1g0", "state": qs["state"]})
ok(r.status_code == 303 and r.headers.get("location") == "/", "id_token válido: entra al panel")
post = next((p for u, p in _PEDIDOS if u.endswith("/oauth/token")), {}) or {}
ok(post.get("code_verifier") == tx["v"] and post.get("grant_type") == "authorization_code"
   and post.get("redirect_uri") == ITHUB.redirect_uri(), "el canje manda el verificador de PKCE")
sesion_cookie = c.cookies.get(ITHUB.COOKIE)
ok(bool(sesion_cookie) and "bsierra" not in sesion_cookie, "la cookie de sesión está cifrada")
ok(c.get("/api/clientes").status_code == 200, "con la sesión de ITHub el panel responde")
ok(c.get("/login").headers.get("location") == "/", "con sesión, /login va directo al panel")
ok(cliente().get("/api/clientes").status_code == 401, "sin cookie, sigue 401")

seccion("I6 · aviso de cierre (back-channel logout)")
c2 = cliente()
ok(c2.post("/ithub-logout", data={"logout_token": "basura"}).status_code == 400, "token basura: 400")
ok(c2.post("/ithub-logout", data={"logout_token": logout_token(aud="crm")}).status_code == 400,
   "logout_token de otra app: 400")
ok(c2.post("/ithub-logout", data={"logout_token": logout_token(sid="otro-sid")}).status_code == 200,
   "logout_token válido de otra sesión: 200")
ok(c.get("/api/clientes").status_code == 200, "y la sesión propia sigue")
r = c2.post("/ithub-logout", data={"logout_token": logout_token()})
ok(r.status_code == 200 and r.headers.get("cache-control") == "no-store", "logout_token válido: 200")
ok(c.get("/api/clientes").status_code == 401, "la sesión con ese sid cae en el pedido siguiente")

seccion("I7 · salir cierra la sesión única")
c3 = cliente()
c3.cookies.set(ITHUB.COOKIE, ITHUB.valor_sesion(claims(sid="sid-nuevo"), "IDTOKEN.de.prueba"))
ok(c3.get("/api/clientes").status_code == 200, "sesión nueva vale")
copia = c3.cookies.get(ITHUB.COOKIE)
r = c3.get("/logout")
loc = r.headers.get("location", "")
qs = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))
ok(loc.startswith(ISS + "/oauth/logout?") and qs.get("id_token_hint") == "IDTOKEN.de.prueba"
   and qs.get("post_logout_redirect_uri") == "https://gestor.ejemplo.test/login",
   "/logout -> /oauth/logout de ITHub con id_token_hint y vuelta al login")
c4 = cliente()
c4.cookies.set(ITHUB.COOKIE, copia)
ok(c4.get("/api/clientes").status_code == 401, "una copia de la cookie anterior ya no entra")
vieja = ITHUB._sellar({"e": int(time.time()) - ITHUB.MAX_EDAD_SESION - 5, "sid": "s9", "sub": "1",
                       "rol": "admin", "idt": ""}, b"sesion")
c4.cookies.set(ITHUB.COOKIE, vieja)
ok(c4.get("/api/clientes").status_code == 401, "una sesión de más de 8 horas no vale")
c4.cookies.set(ITHUB.COOKIE, ITHUB._sellar({"e": int(time.time()), "sid": "s8", "sub": "1",
                                             "rol": "usuario", "idt": ""}, b"sesion"))
ok(c4.get("/api/clientes").status_code == 401, "una sesión sin rol admin no vale")

seccion("I8 · acceso de emergencia del administrador")
c5 = cliente()
r = c5.post("/login", data={"usuario": "intellihelp", "k": "contrasena-de-prueba-ithub-2026"})
ok(r.status_code == 303 and c5.get("/api/clientes").status_code == 200,
   "con ITHub configurado, usuario y contraseña del administrador siguen entrando")
r = c5.get("/logout")
ok(r.headers.get("location") == "/login?manual=1", "y al salir vuelve al acceso manual (no a ITHub)")
r = cliente().post("/login", data={"usuario": "intellihelp", "k": "mala"})
ok(r.status_code == 401 and "Usuario o contraseña incorrectos" in r.text, "contraseña mala: 401")
ok(cliente().get("/", headers={"X-Admin-Token": os.environ["ITHOS_ADMIN_TOKEN"]}).status_code == 200,
   "la cabecera X-Admin-Token (llamadas internas) no cambia")

print("\n" + "=" * 62)
if FALLAS:
    print(f"  INGRESO CON ITHUB: {len(FALLAS)} FALLA(S)")
    print("=" * 62)
    sys.exit(1)
print("  INGRESO CON ITHUB: OK — todos los chequeos verdes")
print("=" * 62)
