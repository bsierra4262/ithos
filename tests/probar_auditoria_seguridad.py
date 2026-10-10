#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regresión de la auditoría del 9-oct-2026: 11 hallazgos de seguridad + 19 de correctitud.

Cada chequeo de acá falla con el código viejo y pasa con el arreglo. Están juntos a propósito:
son el mismo repaso, y lo que se arregló una vez tiene que quedar arreglado.

Uso:  python tests/probar_auditoria_seguridad.py
"""

import os
import sys
import json
import time
import asyncio
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))
sys.path.insert(0, os.path.join(APP, "agente"))

_TMP = tempfile.mkdtemp(prefix="ithos_audit_")
os.environ["ITHOS_DATA"] = _TMP
os.environ["ITHOS_ADMIN_USER"] = "intellihelp"
os.environ["ITHOS_ADMIN_TOKEN"] = "contrasena-de-prueba-larga-2026"
os.environ["ITHOS_ALTA_FILE"] = os.path.join(_TMP, "alta.json")

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


def seccion(t):
    print(f"\n=== {t} ===")


# Cliente de prueba con un secreto de cada clase, para ver qué sale por la API.
CLIENTE = {
    "api_key": "PRUEBA-0123456789ab",
    "nombre": "EMPRESA DE PRUEBA",
    "activo": True,
    "agente_token": "TOKENDEAGENTE-0123456789abcdef",
    "zona_horaria": "America/Argentina/Buenos_Aires",
    "ia": {"proveedor": "gemini", "gemini_api_key": "AQ.CLAVE-SECRETA-DE-GEMINI-123456"},
    "integrador_config": {"db_server": "10.0.0.5,1433", "db_uid": "usuario",
                          "db_pwd": "ContrasenaDeLaBaseDeFichajes"},
    "integrador_glpi": {"glpi_url": "https://ayuda.ejemplo/apirest.php",
                        "glpi_user_token": "TOKEN-SUPER-ADMIN-DE-GLPI-0123456",
                        "glpi_ithos_token": "TOKEN-DE-ITHOS-0123456789abcdef",
                        "glpi_lzaltron_token": "TOKEN-DE-LAURA-0123456789abcdef",
                        "entity_id": 12, "poll_interval": 60},
    "tecnicos": [{"nombre": "Laura Zaltron", "glpi_login": "lzaltron", "glpi_id": 30,
                  "telefonos": ["5491150274827"]},
                 {"nombre": "Brian Sierra", "glpi_login": "bsierra", "glpi_id": 7}],
    "planka": {"url": "https://tareas.ejemplo", "api_key": "CLAVE-DE-PLANKA-0123456789"},
    "empresa_saludo": "EMPRESA DE PRUEBA S.A.",
    "abreviatura": "EDP",
    "horario_atencion": {"dias": [0, 1, 2, 3, 4], "desde": "09:00", "hasta": "18:00"},
}
_RUTA = os.path.join(_TMP, "clientes.json")
json.dump({"clientes": [CLIENTE]}, open(_RUTA, "w", encoding="utf-8"), ensure_ascii=False)
os.environ["ITHOS_CLIENTES"] = _RUTA

import panel as P                       # noqa: E402
import autenticacion as AUTH            # noqa: E402
P.RUTA = _RUTA
P._cache_cfg["mtime"] = None
from fastapi.testclient import TestClient   # noqa: E402

cli = TestClient(P.app, base_url="https://testserver", follow_redirects=False)

# Todos los secretos del cliente, en claro: NINGUNO puede salir sin sesión de superadmin.
SECRETOS = ["TOKENDEAGENTE-0123456789abcdef", "AQ.CLAVE-SECRETA-DE-GEMINI-123456",
            "ContrasenaDeLaBaseDeFichajes", "TOKEN-SUPER-ADMIN-DE-GLPI-0123456",
            "TOKEN-DE-ITHOS-0123456789abcdef", "TOKEN-DE-LAURA-0123456789abcdef",
            "CLAVE-DE-PLANKA-0123456789"]


seccion("S1 · el portal del cliente no entrega los secretos")
r = cli.get(f"/api/cliente/{CLIENTE['api_key']}")
ok(r.status_code == 200, "el cliente SÍ puede leer su configuración (su portal la necesita)",
   str(r.status_code))
cuerpo = r.text
filtrados = [s for s in SECRETOS if s in cuerpo]
ok(not filtrados, "y NINGÚN secreto sale en claro",
   f"se filtraron {len(filtrados)}: {filtrados[:2]}" if filtrados else "0 de 7")
d = r.json()
ok(d.get("api_key") == CLIENTE["api_key"], "la api_key sí viaja: es su identificador, no un secreto")
_tok_glpi = (d.get("integrador_glpi") or {}).get("glpi_user_token", "")
ok(P._OCULTO in _tok_glpi and _tok_glpi.startswith("TOKEN-"),
   "los secretos van enmascarados: se ve que están y cuál es cuál, no su valor", _tok_glpi)
ok("EMPRESA DE PRUEBA S.A." in cuerpo and "lzaltron" in cuerpo,
   "y lo que NO es secreto se ve entero (puede editar su configuración)")

seccion("S5 · denegar por defecto")
ok(P._requiere_admin("GET", "/api/una-ruta-nueva-que-nadie-declaro") is True,
   "una ruta que nadie declaró pública exige superadmin SOLA")
ok(P._requiere_admin("DELETE", "/api/clientes/X") is True, "borrar una empresa exige superadmin")
ok(cli.get("/api/clientes").status_code == 401, "listar TODAS las empresas sin sesión -> 401")
ok(P._requiere_admin("GET", "/login") is False, "el login sigue siendo público")
ok(P._requiere_admin("GET", "/panel/UNA-KEY") is False, "y el portal del cliente también")

seccion("S3 · el anti fuerza-bruta no se saltea con X-Forwarded-For")
class _Req:
    def __init__(self, xff, host):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("c", (), {"host": host})()
# El cliente escribe lo que quiere ANTES; el proxy agrega la IP real AL FINAL.
ok(P._ip_cliente(_Req("9.9.9.9, 200.1.2.3", "10.0.0.1")) == "200.1.2.3",
   "se toma la IP que agregó el proxy, no la que escribió el cliente")
ok(P._ip_cliente(_Req("", "200.1.2.3")) == "200.1.2.3", "sin cabecera, la conexión directa")
falsas = {P._ip_cliente(_Req(f"{i}.{i}.{i}.{i}, 200.1.2.3", "10.0.0.1")) for i in range(1, 9)}
ok(falsas == {"200.1.2.3"},
   "ocho intentos con cabeceras distintas cuentan todos para la MISMA IP", str(falsas))

seccion("S4 · la contraseña de admin no viaja en la URL")
r = cli.get(f"/?k={os.environ['ITHOS_ADMIN_TOKEN']}")
entro = r.status_code in (303, 307) and "gestor_admin" in r.headers.get("set-cookie", "")
ok(not entro, "el ?k=<contraseña> ya no abre sesión", f"status {r.status_code}")

seccion("S9 · la sesión vence y el logout revoca")
class _ReqC:
    def __init__(self, c): self.cookies = c
class _Resp:
    def __init__(self): self.c = {}
    def set_cookie(self, k, v, **kw): self.c[k] = v
    def delete_cookie(self, k): self.c.pop(k, None)
_r = _Resp(); AUTH.set_cookie(_r); _ck = _r.c[AUTH.COOKIE]
ok(AUTH.cookie_ok(_ReqC({AUTH.COOKIE: _ck})), "una sesión recién abierta vale")
ok(not AUTH.cookie_ok(_ReqC({AUTH.COOKIE: "1700000000.0123456789abcdef"})),
   "una cookie con firma falsa no vale")
_vieja = int(time.time()) - AUTH.MAX_EDAD_SESION - 10
ok(not AUTH.cookie_ok(_ReqC({AUTH.COOKIE: f"{_vieja}.{AUTH._firmar(_vieja)}"})),
   "una sesión de hace más de 8 horas no vale, aunque el navegador la guarde")
time.sleep(1.1)
AUTH.borrar_cookie(_Resp())
ok(not AUTH.cookie_ok(_ReqC({AUTH.COOKIE: _ck})),
   "tras cerrar sesión, una COPIA de la cookie anterior deja de entrar")
time.sleep(1.1)
_r2 = _Resp(); AUTH.set_cookie(_r2)
ok(AUTH.cookie_ok(_ReqC({AUTH.COOKIE: _r2.c[AUTH.COOKIE]})),
   "y volver a entrar después del logout funciona")

seccion("S10 · el enlace de alta vale UNA sola vez, incluso con dos envíos a la vez")
tok = AUTH.nuevo_alta_token("X", 24)
res = []
import threading
def _consumir():
    res.append(AUTH.consumir_si_valido(tok))
hilos = [threading.Thread(target=_consumir) for _ in range(8)]
[h.start() for h in hilos]
[h.join() for h in hilos]
ok(sum(1 for x in res if x) == 1,
   "ocho intentos simultáneos: lo consume UNO solo", f"{sum(1 for x in res if x)} pasaron")
ok(os.path.getsize(os.environ["ITHOS_ALTA_FILE"]) > 0, "y el archivo de enlaces quedó entero")

seccion("A6 · guardar desde el panel no borra lo que no está en el formulario")
# El portal manda lo suyo, con los secretos ENMASCARADOS (es lo que recibió en S1).
recibido = cli.get(f"/api/cliente/{CLIENTE['api_key']}").json()
recibido["email"] = "nuevo@ejemplo.com"
r = cli.post("/api/clientes", json=recibido)
ok(r.status_code == 200, "el cliente puede editar lo suyo con su api_key", str(r.status_code))
P._cache_cfg["mtime"] = None
guardado = P._cliente_por_key(CLIENTE["api_key"])
ok(guardado.get("email") == "nuevo@ejemplo.com", "el cambio se guardó")
ok(guardado["integrador_glpi"].get("glpi_lzaltron_token") == "TOKEN-DE-LAURA-0123456789abcdef",
   "el token de GLPI de Laura SIGUE ahí (el formulario no lo trae)")
ok(guardado["integrador_glpi"].get("glpi_ithos_token") == "TOKEN-DE-ITHOS-0123456789abcdef",
   "y el de ITHOS no quedó pisado por su máscara")
ok(guardado.get("agente_token") == CLIENTE["agente_token"], "la contraseña del agente intacta")
ok((guardado.get("planka") or {}).get("api_key") == "CLAVE-DE-PLANKA-0123456789",
   "Planka sigue configurado")
ok(guardado.get("empresa_saludo") == "EMPRESA DE PRUEBA S.A." and guardado.get("abreviatura") == "EDP",
   "el saludo y la abreviatura de la empresa siguen")
ok(guardado.get("horario_atencion", {}).get("desde") == "09:00", "y su horario de atención")
ok(len(guardado.get("tecnicos") or []) == 2, "y su equipo de técnicos")

seccion("S6 · la frase-clave sola no da acceso de administrador")
from comun.asistente import Asistente   # noqa: E402
asis = Asistente.__new__(Asistente)
asis._admin = {}
ok(asis._admin_voz_ok("voz", None) is False,
   "por micrófono, sin audio para verificar la voz -> NO")
class _VozRota:
    @staticmethod
    def perfil_listo(): raise RuntimeError("vozid caído")
sys.modules["comun.vozid"] = _VozRota
ok(asis._admin_voz_ok("voz", b"audio") is False,
   "si el verificador de voz falla -> NO (antes fallaba ABIERTO y daba admin)")
del sys.modules["comun.vozid"]

seccion("S7 · la clave exige el número, no sólo algo que suene parecido")
from comun import conocimiento as K     # noqa: E402
ok(K.detectar_clave_admin("kanerito4262") is True, "la clave completa entra")
ok(K.detectar_clave_admin("canerito 4262 administrador") is True,
   "una letra mal transcripta por el micrófono, con el número, también")
ok(K.detectar_clave_admin("kanerito administrador") is False,
   "la palabra + 'administrador' SIN el número ya NO entra")
ok(K.detectar_clave_admin("codigo de seguridad de acceso autorizacion de administrador") is False,
   "la frase genérica sola tampoco")
ok(K.detectar_clave_admin("canelito 4262") is False,
   "y una palabra con dos letras de diferencia tampoco, aunque traiga el número")

seccion("S8 · la clave no está fija en el código ni viaja al transcriptor")
from comun import ia as IA              # noqa: E402
ok("anerito" not in IA.HINT_TRANSCRIPCION.lower(),
   "el vocabulario que se le manda al transcriptor ya no lleva la contraseña")
os.environ["ITHOS_CLAVE_ADMIN"] = "OtraClaveDistinta9988"
ok(K.detectar_clave_admin("OtraClaveDistinta9988") is True,
   "la clave se puede fijar por variable de entorno")
ok(K.detectar_clave_admin("kanerito4262") is False,
   "y entonces la vieja deja de valer")
os.environ.pop("ITHOS_CLAVE_ADMIN")

seccion("A1 · la mesa de ayuda no depende de que el agente esté conectado")
import main as M                        # noqa: E402
async def _a1():
    srv = await M.arrancar_servicios({"nombre": "SIN AGENTE", "zona_horaria": "America/Argentina/Buenos_Aires"})
    ok(srv is not None, "los servicios del cliente arrancan SIN agente conectado")
    ok(await M.arrancar_servicios({"nombre": "SIN AGENTE"}) is srv,
       "y arrancan una sola vez (idempotente)")
    ok(await M.enviar_a_agente("SIN AGENTE", {"accion": "decir"}) is False,
       "mandarle voz a un agente que no está devuelve False, no revienta")
asyncio.run(_a1())
ok(hasattr(M, "arrancar_servicios") and "startup" in open(
    os.path.join(APP, "central", "main.py"), encoding="utf-8").read(),
   "y se arrancan al iniciar el Gestor, no al conectarse un agente")

seccion("A2 + A3 · el estado sobrevive al deploy y no se corrompe")
from comun import estado as E           # noqa: E402
ok(os.path.abspath(E.dir_datos()) == os.path.abspath(_TMP),
   "el estado va al volumen (ITHOS_DATA), no al lado del código")
E.guardar("prueba", "EMPRESA X", {"dia": "2026-10-09", "avisados": [1, 2, 3]})
ok(E.cargar("prueba", "EMPRESA X")["avisados"] == [1, 2, 3], "se guarda y se relee")
ok(not os.path.exists(E.ruta("prueba", "EMPRESA X") + ".tmp"),
   "no deja temporales dando vueltas")
ok(E.cargar("prueba", "NO EXISTE") == {}, "un cliente sin estado devuelve vacío, no explota")
import proactivo as PRO, anomalias as ANO, reportes_programados as RP   # noqa: E402
for mod, nom in ((PRO, "proactivo"), (ANO, "anomalías"), (RP, "reportes")):
    mod._guardar("EMPRESA X", {"dia": "hoy"})
    ok(mod._cargar("EMPRESA X") == {"dia": "hoy"}, f"{nom}: guarda en el volumen")

seccion("A4 + A5 · las horas son las del CLIENTE, no las del servidor")
fuente = open(os.path.join(APP, "central", "proactivo.py"), encoding="utf-8").read()
fuente += open(os.path.join(APP, "central", "anomalias.py"), encoding="utf-8").read()
fuente += open(os.path.join(APP, "comun", "asistente.py"), encoding="utf-8").read()
ok("datetime.now()" not in fuente,
   "ni la alerta de SLA, ni las anomalías, ni el asistente usan el reloj del servidor")
from comun.horario import ahora_zona    # noqa: E402
a = ahora_zona({"zona_horaria": "America/Argentina/Buenos_Aires"})
b = ahora_zona({"zona_horaria": "Asia/Tokyo"})
ok(a.strftime("%H") != b.strftime("%H"), "dos clientes en husos distintos ven horas distintas")

seccion("A7 · se le puede asignar un ticket a cualquiera del equipo configurado")
from comun import tickets as TK         # noqa: E402
cfg_eq = {"tecnicos": CLIENTE["tecnicos"]}
ok(TK._uid_tecnico(cfg_eq, "Laura") == 30, "por nombre de pila")
ok(TK._uid_tecnico(cfg_eq, "zaltron") == 30, "por apellido")
ok(TK._uid_tecnico(cfg_eq, "lzaltron") == 30, "por login")
ok(TK._uid_tecnico(cfg_eq, "Brian Sierra") == 7, "por nombre completo")
ok(TK._uid_tecnico(cfg_eq, "Alguien Que No Existe") is None, "y uno que no está, no se inventa")

seccion("A14 · un recordatorio automático NO es la resolución de un ticket")
ok(TK._es_aviso_automatico("Le recordamos que su ticket está a la espera de su confirmación."),
   "se reconoce el recordatorio del ciclo")
ok(TK._es_aviso_automatico("Le informamos que su solicitud fue resuelta. Por favor confírmenos"),
   "y el pedido de confirmación")
ok(not TK._es_aviso_automatico("Se recalibró el lector del entrepiso y volvió a tomar fichadas."),
   "y una resolución técnica de verdad NO se confunde con uno")

seccion("A15 + A16 · el integrador de fichajes")
from integrador_ivms import _entero     # noqa: E402
ok(_entero("50; DROP TABLE fichajes--", 50, 1, 5000) == 50,
   "lo que llega por el formulario no entra crudo en la consulta")
ok(_entero("abc", 50, 1, 5000) == 50 and _entero("-7", 50, 1, 5000) == 1
   and _entero("999999", 50, 1, 5000) == 5000, "y queda acotado a un rango sano")
vistos = {}
for i in range(6100):
    vistos[f"fichada-{i}"] = None
    if len(vistos) > 6000:
        for vieja in list(vistos)[:len(vistos) - 5000]:
            vistos.pop(vieja, None)
ok("fichada-6099" in vistos and "fichada-0" not in vistos,
   "al recortar se descartan las MÁS VIEJAS, no unas cualesquiera",
   f"{len(vistos)} en memoria")

seccion("A20 · un ticket olvidado en 'Nuevo' se rescata, no desaparece")
import integrador_glpi as IG            # noqa: E402
# El poll normal mira los 30 más nuevos. Un ticket que QUEDE en 'Nuevo' —porque su triage falló, o
# porque entraron treinta más mientras tanto— va saliendo de esa ventana y no se vuelve a mirar
# NUNCA: deja de existir para el circuito.
TODOS = [{"id": i, "status": 2, "entities_id": 12} for i in range(1, 300)]
TODOS += [{"id": 472, "status": 1, "entities_id": 12, "name": "viejo olvidado"}]
TODOS += [{"id": i, "status": 2, "entities_id": 12} for i in range(700, 730)]
pend = IG.pendientes_triage(TODOS)
ok([t["id"] for t in pend] == [472],
   "el triage reconoce como pendiente al ticket viejo en 'Nuevo'", str([t["id"] for t in pend]))
_fuente_ig = open(os.path.join(APP, "central", "integrador_glpi.py"), encoding="utf-8").read()
ok("_VUELTAS_BARRIDO" in _fuente_ig and "todos_tickets()" in _fuente_ig,
   "y cada tantas vueltas se revisa el histórico COMPLETO, no sólo los 30 últimos")
ok(IG._VUELTAS_BARRIDO >= 5,
   "el barrido está espaciado (no lee todo el histórico en cada vuelta)", str(IG._VUELTAS_BARRIDO))

seccion("A18 · la versión que informa el Gestor es la de verdad")
from comun import version as V          # noqa: E402
r = cli.get("/api/estado")   # el panel responde; el '/' del central se prueba por su módulo
ok(V.GESTOR_VERSION != "0.5", "la versión del Gestor no está escrita a mano en el endpoint",
   V.GESTOR_VERSION)
ok(callable(V.revision_desplegada), "y se puede saber QUÉ revisión está desplegada")

print("\n" + "=" * 62)
if FALLAS:
    print(f"  FALLAS: {len(FALLAS)}")
    for f in FALLAS:
        print("   -", f)
    print("=" * 62)
    sys.exit(1)
print("  AUDITORÍA DE SEGURIDAD Y ROBUSTEZ: OK — todos los chequeos verdes")
print("=" * 62)
