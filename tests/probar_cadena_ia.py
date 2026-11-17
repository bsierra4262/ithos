#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de la cadena de IA: que los errores digan su causa real, y la IA local (sin red, sin cuota).

TRES BUGS, LOS TRES VISTOS EN PRODUCCIÓN EL 17-NOV-2026:

  1. UN ESCALÓN QUE NO EXISTE TAPABA LA CUOTA. La escalera de Gemini terminaba en
     `gemini-3-flash-preview`, que Google no tiene («not found for API version v1»). Cuando los dos
     modelos reales se quedaban sin la cuota del día, el error que salía para afuera era el 404 de
     ese tercero —no el de la cuota—, así que el gestor nunca se enteraba de que Gemini estaba
     agotada. Hacía días que el log decía «gemini-3-flash-preview 404» y la causa era otra.
     Y el comentario de la escalera decía que saltaba los modelos retirados, pero el código de
     Gemini sólo sabía saltar la cuota.

  2. TODO ERROR ERA «LÍMITE POR MINUTO». Lo que no era cuota diaria se etiquetaba así, incluidos un
     400 (petición o clave inválida) y un 404 (modelo inexistente): errores que no se arreglan
     esperando se reintentaban cada 40 s en silencio, y el motivo real no quedaba en ningún lado.
     En producción hubo un 400 al arrancar y no hay forma de saber qué fue.

  3. LA IA LOCAL NO PODÍA CONTESTAR. Sin `think: false` los modelos que "razonan" se comían el
     tiempo pensando; sin `num_ctx` el prompt de triage se truncaba y el modelo devolvía la
     plantilla del JSON; y con 180 s de timeout la primera consulta del día moría siempre.

Uso:  python tests/probar_cadena_ia.py
"""

import io
import json
import logging
import os
import sys
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "ITHOS"))

from comun import ia as IA              # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


CUOTA_DIA = ("429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
             "generate_content_free_tier_requests, limit: 20, quotaId: GenerateRequestsPerDayPerModel")
NO_EXISTE = ("404 NOT_FOUND. models/gemini-3-flash-preview is not found for API version v1, "
             "or is not supported for generateContent.")
CLAVE_MALA = "400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key. API_KEY_INVALID"

print("\n=== 1 · Qué error se arregla esperando y cuál no ===")
for err, esperado, que in (
        (CLAVE_MALA, True, "clave inválida (400)"),
        (NO_EXISTE, True, "modelo inexistente (404)"),
        ("403 PERMISSION_DENIED", True, "sin permiso (403)"),
        ("401 UNAUTHENTICATED", True, "sin autenticar (401)"),
        (CUOTA_DIA, False, "cuota del día: esa tiene su propio camino"),
        ("503 UNAVAILABLE. The model is overloaded", False, "sobrecarga (503): sí se arregla esperando"),
        ("429 Too Many Requests: rate limit per minute", False, "límite por minuto"),
        ("se pasó de 1400 tokens", False, "un '1400' suelto no es un 400")):
    ok(IA._es_permanente(err) is esperado, f"{que} -> permanente={esperado}")

print("\n=== 2 · Un error permanente deja escrito su MOTIVO REAL ===")


class _Multi(IA.MultiIA):
    def __init__(self):                  # sin proveedores reales: sólo se prueba el cooldown
        self._primaria_hasta = 0.0


buf = io.StringIO()
h = logging.StreamHandler(buf)
logging.getLogger("ia").addHandler(h)
try:
    m = _Multi()
    m._marcar_sin_cuota(RuntimeError(CLAVE_MALA))
    escrito = buf.getvalue()
finally:
    logging.getLogger("ia").removeHandler(h)
ok("API key not valid" in escrito, "el log dice la causa real", escrito.strip()[:90])
ok("límite por minuto" not in escrito, "y ya no la disfraza de 'límite por minuto'")
ok(m._primaria_hasta - __import__("time").time() > 300,
   "y no se reintenta cada 40 s: esperar no lo arregla")

print("\n=== 3 · La escalera de Gemini: el escalón muerto se fue ===")
ok("gemini-3-flash-preview" not in IA._ESCALERA_GEMINI,
   "gemini-3-flash-preview ya no está (Google no lo tiene)", str(IA._ESCALERA_GEMINI))


class _ModelosFalsos:
    """Google de mentira: cada modelo contesta lo que se le diga (texto u error)."""

    def __init__(self, guion):
        self.guion, self.pedidos = guion, []

    def generate_content(self, model, contents, config):
        self.pedidos.append(model)
        r = self.guion[model]
        if isinstance(r, Exception):
            raise r

        class _R:
            text = r
        return _R()


class _Gestor:
    def __init__(self):
        self.agotada = 0

    def agotada_gemini(self):
        self.agotada += 1

    def registrar_gemini(self):
        pass


def gemini_con(guion, escalera):
    g = IA.GeminiIA.__new__(IA.GeminiIA)
    g.modelo_texto = escalera[0]
    g._escalera = list(escalera)
    g._agotados = {}
    g.gestor = _Gestor()
    g.sin_reintento_429 = True
    falsos = _ModelosFalsos(guion)

    class _Cli:
        models = falsos
    g._cli = _Cli()
    return g, falsos


# El caso REAL de producción: los dos modelos sin cuota y un tercero que no existe.
g, f = gemini_con({"flash-lite": RuntimeError(CUOTA_DIA), "flash": RuntimeError(CUOTA_DIA),
                   "fantasma": RuntimeError(NO_EXISTE)}, ["flash-lite", "flash", "fantasma"])
try:
    g.chat("s", "p", json_out=False)
    sale = None
except Exception as e:  # noqa: BLE001
    sale = str(e)
ok(sale is not None and "PerDay" in sale,
   "con cuota agotada y un escalón inexistente, sale el error de CUOTA (la causa)", str(sale)[:60])
ok(g.gestor.agotada == 1, "y el gestor se entera de que Gemini se agotó (antes no)")

# Un modelo retirado al principio no debe frenar a los que sí andan.
g, f = gemini_con({"retirado": RuntimeError(NO_EXISTE), "flash": "OK"}, ["retirado", "flash"])
ok(g.chat("s", "p", json_out=False) == "OK",
   "un modelo que no existe se saltea y contesta el siguiente", str(f.pedidos))

print("\n=== 4 · La IA local: los tres ajustes sin los que no contesta ===")
enviados = []


class _Resp:
    def __init__(self, cuerpo):
        self.cuerpo = cuerpo

    def read(self):
        return self.cuerpo

    def __enter__(self):
        return io.BytesIO(self.cuerpo)

    def __exit__(self, *a):
        return False


def _urlopen_falso(req, timeout=None):
    enviados.append((json.loads(req.data.decode()), timeout))
    return _Resp(json.dumps({"message": {"content": '{"ok": true}'}}).encode())


_orig = IA.urllib.request.urlopen if hasattr(IA, "urllib") else None
import urllib.request as _ur             # noqa: E402
_ur_orig = _ur.urlopen
_ur.urlopen = _urlopen_falso
try:
    loc = IA.LocalIA({"ollama_url": "http://ollama:11434", "modelo_texto": "qwen3:4b"})
    loc.chat("sistema", "ticket", json_out=True)
finally:
    _ur.urlopen = _ur_orig
cuerpo, tope = enviados[-1]
ok(cuerpo.get("think") is False, "think=false: el modelo no se come el tiempo razonando")
ok(cuerpo["options"].get("num_ctx", 0) >= 8192,
   "num_ctx 8192: el prompt de triage (~2.500 tokens + ticket) no se trunca")
ok(cuerpo["options"].get("num_predict"), "y hay tope de salida también en modo JSON")
ok(tope and tope >= 300, "timeout de 300 s: la primera consulta del día (con carga) llega", str(tope))
ok(loc.modelo_texto == "qwen3:4b", "el modelo por defecto es el que ganó la medición")

# Un modelo que no "piensa" rechaza la opción: se reintenta sin ella, y no se vuelve a mandar.
enviados.clear()
llamadas = {"n": 0}


def _urlopen_sin_think(req, timeout=None):
    cuerpo = json.loads(req.data.decode())
    enviados.append(cuerpo)
    llamadas["n"] += 1
    if "think" in cuerpo:
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", None,
                                     io.BytesIO(b'{"error":"model does not support thinking"}'))
    return _Resp(json.dumps({"message": {"content": "OK"}}).encode())


_ur.urlopen = _urlopen_sin_think
try:
    loc2 = IA.LocalIA({"ollama_url": "http://ollama:11434", "modelo_texto": "llama3.2:3b"})
    r1 = loc2.chat("s", "p", json_out=False)
    r2 = loc2.chat("s", "p", json_out=False)
finally:
    _ur.urlopen = _ur_orig
ok(r1 == "OK" and r2 == "OK", "un modelo sin 'think' igual contesta")
ok("think" not in enviados[-1] and llamadas["n"] == 3,
   "y después del primer rechazo ya no se manda la opción (no se paga el error cada vez)",
   f"{llamadas['n']} llamadas")

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("  CADENA DE IA: OK — cada error dice su causa y la IA local contesta")
print("=" * 78)
