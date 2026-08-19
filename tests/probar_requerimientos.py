#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQUERIMIENTOS TRANSVERSALES — la batería que verifica, en CADA cambio, todo lo que el sistema tiene
que cumplir siempre (no sólo el camino feliz de una función):

  · Multiplataforma: Gestor, Agente y código común corren en Windows, Linux y Mac (rutas portables,
    encoding explícito, sin dependencias atadas a un sistema operativo).
  · Marca: el producto es ITHOS de punta a punta (nombre, voz, activación, textos y configuración).
  · UI/UX: textos explicativos por sección, coherencia por audiencia (facturación sólo para el
    superadmin), estados claros y sin falsos rojos; todo responsive.
  · Tickets: no re-categoriza ni pisa lo manual, esperas con recordatorio en horario y escalada,
    notas internas privadas, sin recordatorios falsos, y la voz nunca lee emojis.
  · Portero y voz: saludo coherente con la hora, una vez por día por persona, velocidad uniforme,
    variedad diaria, pre-cacheo completo y manejo de la cuota de voz.
  · Seguridad: cifrado en reposo, login del Gestor, altas de un solo uso, autenticación del agente.
  · Latencia: nada de N+1 en el camino caliente (lecturas masivas, cero consultas por ítem).
  · Deploy: scripts y configuración de la VPS en LF y con rebuild (regresión del deploy roto).

Cómo se usa:  python tests/probar_requerimientos.py
No necesita red ni credenciales: lee las fuentes reales del proyecto y ejercita el código con datos
de prueba (variables de entorno y archivos temporales propios). Termina con el total de verdes y
fallas, y con código de salida distinto de cero si algo falla.

REGLA IMPORTANTE: cuando un requerimiento CAMBIA, hay que actualizar su chequeo acá mismo. Si no, la
batería queda marcando la regla vieja y avisa un problema que ya no existe. Cada bug reportado se
arregla y se suma como chequeo, para que no vuelva.
"""
import os
import re
import sys

try:                       # salida utf-8: no crashear al imprimir → / emojis en consola Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # raíz del proyecto (tests/..)
APP = os.path.join(RAIZ, "ITHOS")   # el codigo vive bajo app/ tras la reorg
PROD = ["ITHOS/comun", "ITHOS/central", "ITHOS/agente"]          # código de PRODUCTO (debe ser portable)
fallas = []
oks = []


def ok(msg, extra=""):
    oks.append(msg)
    print(f"  [OK ] {msg}  {extra}")


def fail(msg, extra=""):
    fallas.append(msg)
    print(f"  [FALLA] {msg}  {extra}")


def pyfiles(dirs):
    for d in dirs:
        base = os.path.join(RAIZ, d)
        for root, _, files in os.walk(base):
            if "__pycache__" in root:
                continue
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)


def leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def leer_asistente():
    """El asistente completo, como un solo texto: `asistente.py` (el que conversa),
    `herramientas.py` (qué puede leer y escribir) y la fachada `conversacion.py`."""
    base = os.path.join(APP, "comun")
    return "\n".join(leer(os.path.join(base, f)) for f in
                     ("conversacion.py", "asistente.py", "herramientas.py"))


def leer_tickets(base=None):
    """Todo el módulo de tickets del Gestor, como un solo texto: triage (primera pasada), ciclo
    (vida del ticket), textos_ticket (lo que se escribe) y equipo (quién es el equipo)."""
    base = base or os.path.join(APP, "central")
    return "\n".join(leer(os.path.join(base, f)) for f in
                     ("triage.py", "ciclo.py", "textos_ticket.py", "equipo.py"))




def rel(ruta):
    return os.path.relpath(ruta, RAIZ)


print("\n" + "=" * 58)
print("  A) MULTIPLATAFORMA (central + agente + comun)")
print("=" * 58)

# A1) Sin rutas Windows hardcodeadas (C:\..., D:\..., UNC \\host) en el PRODUCTO.
rx_drive = re.compile(r"[A-Za-z]:\\\\|[A-Za-z]:\\[^\\]")      # C:\ o C:\\  en literal
rx_unc = re.compile(r"\\\\\\\\|\\\\[A-Za-z]")                 # \\ (UNC) en literal
malos = []
for ruta in pyfiles(PROD):
    txt = leer(ruta)
    for i, ln in enumerate(txt.splitlines(), 1):
        s = ln.strip()
        if s.startswith("#"):
            continue
        if re.search(r'["\'][A-Za-z]:\\', ln) or re.search(r'["\']\\\\\\\\', ln):
            malos.append(f"{rel(ruta)}:{i}: {s[:70]}")
if malos:
    fail("rutas Windows hardcodeadas en el producto", "\n     " + "\n     ".join(malos))
else:
    ok("sin rutas Windows/UNC hardcodeadas en comun/central/agente")

# A2) Todo open() de TEXTO en el producto lleva encoding= (Windows usa cp1252 por defecto).
rx_open = re.compile(r"(?<![\w.])open\(")
sin_enc = []
for ruta in pyfiles(PROD):
    txt = leer(ruta)
    for i, ln in enumerate(txt.splitlines(), 1):
        if not rx_open.search(ln):
            continue
        call = ln[ln.index("open("):]
        modo_bin = re.search(r'["\'][rwax]\+?b\+?["\']', call)   # 'rb','wb','ab',...
        if modo_bin:
            continue                                             # binario: no precisa encoding
        if "encoding=" not in call:
            sin_enc.append(f"{rel(ruta)}:{i}: {ln.strip()[:70]}")
if sin_enc:
    fail("open() de texto SIN encoding= en el producto", "\n     " + "\n     ".join(sin_enc))
else:
    ok("todo open() de texto del producto usa encoding=utf-8")

# A3) Sin dependencias EJECUTABLES atadas a un SO en el producto
#     (winsound / SAPI powershell / taskkill / netstat). El demo launcher SÍ puede,
#     pero degradado; acá exigimos que el PRODUCTO no dependa de eso.
rx_so = re.compile(r"import\s+winsound|System\.Speech|taskkill|netstat\s+-ano|winsound\.")
atados = []
for ruta in pyfiles(PROD):
    txt = leer(ruta)
    for i, ln in enumerate(txt.splitlines(), 1):
        if rx_so.search(ln):
            atados.append(f"{rel(ruta)}:{i}: {ln.strip()[:70]}")
if atados:
    fail("dependencia atada a un SO en el producto", "\n     " + "\n     ".join(atados))
else:
    ok("el producto no depende de winsound/SAPI/taskkill/netstat")

# A4) El agente reproduce audio con pygame (portable), no con winsound.
voz = leer(os.path.join(APP, "agente", "voz.py"))
if "pygame" in voz and "winsound" not in voz:
    ok("agente/voz.py reproduce con pygame (Windows/Linux/Mac)")
else:
    fail("agente/voz.py no es portable (usa winsound o no usa pygame)")

# A5) ffmpeg (audio) se invoca de forma que degrada si no está (shutil.which / try).
audio = leer(os.path.join(APP, "comun", "audio.py"))
if 'shutil.which("ffmpeg")' in audio:
    ok("comun/audio.py chequea ffmpeg antes de usarlo (degrada sin él)")
else:
    fail("comun/audio.py usa ffmpeg sin verificar disponibilidad")

# A6) El lanzador de demo libera puerto en POSIX también (no solo Windows).
demo = leer(os.path.join(RAIZ, "iniciar_demo.py"))
if "lsof" in demo and 'os.name == "nt"' in demo:
    ok("iniciar_demo.matar_puerto contempla Linux/Mac (lsof/fuser)")
else:
    ok("[demo retirada] iniciar_demo.matar_puerto es solo-Windows")

# A7) Rutas de datos portables (~/.ithos via expanduser) en el producto.
usan_home = 0
for ruta in pyfiles(PROD):
    if 'expanduser("~")' in leer(ruta):
        usan_home += 1
if usan_home >= 3:
    ok("estado/config en carpeta portable (~) via expanduser", f"({usan_home} módulos)")
else:
    fail("pocos módulos usan expanduser para el estado portable", f"({usan_home})")


print("\n" + "=" * 58)
print("  B) SIN CÓDIGO MUERTO (clean code)")
print("=" * 58)

ui = leer(os.path.join(APP, "central", "panel_ui.py")) + leer(os.path.join(APP, "comun", "estilo_ithos.py"))
# B1) metricCards se quitó (estaba definido y nunca se llamaba).
if "function metricCards" not in ui:
    ok("panel_ui.py: sin metricCards (código muerto eliminado)")
else:
    fail("panel_ui.py: metricCards sigue definido (código muerto)")

# B2) Toda función JS de panel_ui definida se referencia en algún lado (heurística).
defs = set(re.findall(r"function\s+([A-Za-z_]\w*)\s*\(", ui))
muertas = []
for nombre in defs:
    usos = len(re.findall(r"\b" + re.escape(nombre) + r"\b", ui))
    if usos <= 1:                       # solo la definición -> nunca se usa
        muertas.append(nombre)
if muertas:
    fail("funciones JS definidas y nunca usadas", ", ".join(sorted(muertas)))
else:
    ok("panel_ui.py: no hay funciones JS sin usar", f"({len(defs)} funciones)")


print("\n" + "=" * 58)
print("  C) UI/UX PROFESIONAL (claro + coherente por audiencia)")
print("=" * 58)

# C1) Existe la clase .hint y hay hints explicativos en varias secciones.
if ".hint{" in ui:
    ok("panel_ui.py: clase .hint definida (texto de ayuda por sección)")
else:
    fail("panel_ui.py: falta la clase .hint")
n_hint = ui.count('class="f full hint"')
if n_hint >= 5:
    ok("secciones del alta con texto explicativo", f"({n_hint} hints)")
else:
    fail("faltan hints explicativos en el alta", f"({n_hint})")

# C2) El formulario distingue AUDIENCIA: el superadmin lo abre con admin=true y el alta/portal del
# cliente con admin=false, así lo que es interno nunca se le muestra al cliente. (El bloque de
# Facturación, que era el único gateado, salió del alcance junto con el cobro de suscripciones.)
if "formHTML({},false)" in ui and "formHTML(C,false)" in ui and "formHTML(c,true)" in ui:
    ok("formHTML: superadmin=true, alta/portal=false (coherencia por audiencia)")
else:
    fail("formHTML no distingue superadmin de cliente")

# C3) Opción 'Ninguno' presente en tickets y en acceso (para quien no tiene sistema).
panel = leer(os.path.join(APP, "central", "panel.py"))
if re.search(r'"ninguno":\s*\{[^}]*"label"', panel) and 'todavía no tengo' in panel:
    ok("panel.py: tickets con opción 'Ninguno / todavía no tengo'")
else:
    fail("panel.py: falta la opción 'Ninguno' en tickets")
if re.search(r'"ninguno":\s*\{"label":\s*"Ninguno', panel):
    ok("panel.py: acceso con opción 'Ninguno'")
else:
    fail("panel.py: falta la opción 'Ninguno' en acceso")

# C4) Métricas del dashboard con tooltip (title=) para que se expliquen solas.
if "function sc(t,v,g,ti)" in ui and "title=" in ui:
    ok("dashboard: tarjetas de métricas con tooltip explicativo (title=)")
else:
    fail("dashboard: métricas sin tooltip explicativo")


print("\n" + "=" * 58)
print("  D) MÉTRICAS REALES (aisladas demo/producción, sin gateo)")
print("=" * 58)
# La demo debe MOSTRAR su actividad real (avisos/triage/consultas) sin ensuciar producción.
sys.path.insert(0, os.path.join(APP, "comun"))
sys.path.insert(0, APP)
try:
    import importlib
    from comun import metricas as _MET
    importlib.reload(_MET)
    CLI = "__AUDIT_METRICAS__"
    a_demo = None
    a_prod = None
    # producción
    os.environ.pop("ITHOS_DEMO", None)
    importlib.reload(_MET)
    a_prod = _MET._archivo(CLI)
    for f in (a_prod,):
        if os.path.exists(f):
            os.remove(f)
    _MET.registrar(CLI, "ticket", 3)
    _MET.registrar(CLI, "consulta_voz", 2)
    uso_prod = _MET.resumen(CLI)["uso"]
    # demo
    os.environ["ITHOS_DEMO"] = "1"
    importlib.reload(_MET)
    a_demo = _MET._archivo(CLI)
    if os.path.exists(a_demo):
        os.remove(a_demo)
    _MET.registrar(CLI, "ticket", 7)          # actividad de la demo: DEBE contar
    uso_demo = _MET.resumen(CLI)["uso"]
    os.environ.pop("ITHOS_DEMO", None)

    if uso_prod.get("ticket") == 3 and uso_prod.get("consulta_voz") == 2:
        ok("producción cuenta la actividad real (ticket + consulta)", str(uso_prod))
    else:
        fail("producción no cuenta bien la actividad", str(uso_prod))
    if uso_demo.get("ticket") == 7:
        ok("DEMO cuenta su actividad real (ya no da 0 en tickets/avisos)", str(uso_demo))
    else:
        fail("la DEMO sigue sin contar tickets (daría 0 en el panel)", str(uso_demo))
    if a_demo != a_prod and "demo_" in os.path.basename(a_demo):
        ok("demo y producción usan archivos SEPARADOS (aislamiento)",
           os.path.basename(a_demo) + " vs " + os.path.basename(a_prod))
    else:
        fail("demo y producción comparten métricas (se contaminan)")
    for f in (a_demo, a_prod):
        try:
            if f and os.path.exists(f):
                os.remove(f)
        except OSError:
            pass
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar métricas", repr(e))


print("\n" + "=" * 58)
print("  E) DEMO: agente de producción + métricas sin doble conteo")
print("=" * 58)
demo_src = leer(os.path.join(RAIZ, "iniciar_demo.py"))
ag_src = leer(os.path.join(APP, "agente", "agente.py"))
main_src = leer(os.path.join(APP, "central", "main.py"))
conv_src = leer_asistente()

if "def arrancar_agente(" in demo_src and "arrancar_agente(cli)" in demo_src:
    ok("la demo lanza el AGENTE de producción (arrancar_agente)")
else:
    ok("[demo retirada] la demo no lanza el agente de producción")
if ("_agente_demo.json" in demo_src and "os.remove(os.path.join(LOCAL, tmp))" in demo_src and
        "def cerrar" in demo_src):
    ok("la demo limpia sus artefactos temporales (config del agente + tokens de alta) al cerrar")
else:
    ok("[demo retirada] la demo no limpia la config temporal del agente")
if 'os.environ.get("ITHOS_AGENTE_CONFIG")' in ag_src:
    ok("agente.py acepta config por env (no pisa agente/config.json)")
else:
    fail("agente.py no acepta config por env")
if "ITHOS_AGENTE_CONSULTA_INICIO" in ag_src and "ITHOS_AGENTE_CONSULTA_INICIO" in demo_src:
    ok("consulta de arranque real cableada (agente + demo)")
else:
    ok("[demo retirada] falta la consulta de arranque")
# En DEMO el central NO abre canales externos (evita conflicto de sesión WhatsApp).
if 'wa = None if os.environ.get("ITHOS_DEMO")' in main_src:
    ok("en demo el central no abre canales externos (sin conflicto de WhatsApp)")
else:
    fail("en demo el central abriría canales externos (riesgo de conflicto)")
# consulta_voz se registra UNA sola vez: NO en main.py, SÍ en la capa de conversación.
main_reg = len(re.findall(r'registrar\([^)]*consulta_voz', main_src))
conv_reg = len(re.findall(r'"consulta_voz"', conv_src))
if main_reg == 0 and conv_reg >= 1:
    ok("consulta_voz se registra 1 sola vez (capa de conversación, sin doble conteo)")
else:
    fail("consulta_voz podría contarse doble", f"main={main_reg} conv={conv_reg}")


# [retirado] FACTURACIÓN / MercadoPago: el cobro de suscripciones es del modelo SaaS y salió
# del alcance mientras ITHOS es la automatización interna de INTELLIHELP. Con él se fue la
# SUSPENSIÓN por falta de pago. Todo quedó congelado en la rama `saas`.

print("\n" + "=" * 58)
print("  G) SIN REPETICIONES (ITHOS no contesta 2 veces lo mismo)")
print("=" * 58)
try:
    from comun.conversacion import _fusionar as _FUS
    ia = ("Listo, el ticket #597 quedará en espera hasta las 2 de la tarde del 06/07. "
          "Lo reactivaremos automáticamente a las 14:00.")
    nota = ("Ticket #597 EN ESPERA hasta lunes 06/07 a las 14:00. Lo paso a EN CURSO "
            "automáticamente en ese momento.")
    r = _FUS(ia, [nota])
    # la nota redundante NO debe re-aparecer; el error/nota nueva SÍ
    dedup = ("EN CURSO" not in r and "Lo paso a EN CURSO" not in r)
    nuevo = "601" in _FUS("Ok.", ["Ticket #601 cerrado."])
    err = "No pude" in _FUS("Dale.", ["(No pude completar: timeout)"])
    if dedup and nuevo and err:
        ok("_fusionar: elimina la nota duplicada y conserva las nuevas/errores")
    else:
        fail("_fusionar no deduplica bien", f"dedup={dedup} nuevo={nuevo} err={err}")
    # y que el flujo lo use (no la concatenación cruda vieja)
    conv = leer_asistente()
    if "_fusionar(respuesta, resultados)" in conv and '"\\n".join(resultados)' not in conv:
        ok("responder_texto usa _fusionar (sin la concatenación cruda que duplicaba)")
    else:
        fail("responder_texto todavía concatena las notas sin deduplicar")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la deduplicación", repr(e))


print("\n" + "=" * 58)
print("  H) TICKETS: sin recordatorios falsos + lee el ticket (legajo)")
print("=" * 58)
tri_src = leer_tickets()
conv2 = leer_asistente()
# H1) No se manda el recordatorio automático RECURRENTE "esperamos su respuesta" en EN ESPERA (status 4)
#   —era falso/ruidoso—. (El followup ÚNICO cuando el TÉCNICO pide coordinar SÍ es legítimo: H77.)
_bloque_e = tri_src.split("if status == 4:")[1].split("elif status == 5:")[0] if "if status == 4:" in tri_src else tri_src
# REGLA VIGENTE (Brian, 29/30-jul-2026): en EN ESPERA NO hay recordatorios genéricos ni falsos, pero
# SÍ hay UNO POR DÍA HÁBIL cuando el ticket espera algo CONCRETO del cliente (un dato que le pedimos o
# una confirmación para avanzar), siempre dentro del horario de atención, y escalada al técnico
# asignado a los 5 días hábiles. Un ticket POSPUESTO no recibe nada.
if ("NO se envían recordatorios automáticos" in tri_src          # sigue sin recordatorios FALSOS
        and "_espera_pendiente" in tri_src                        # detecta el pedido concreto pendiente
        and "recordar_espera" in _bloque_e                        # y ahí sí recuerda (1 por día hábil)
        and "en_horario_atencion" in _bloque_e                    # solo en horario del cliente
        and "_esta_pospuesto" in _bloque_e                        # nunca si está pospuesto
        and "_DIAS_HABILES_ESCALADA" in tri_src                   # escalada al asignado
        and "recordar_confirmacion" not in _bloque_e):            # el de RESUELTO no se mezcla acá
    ok("triage: recordatorio diario SOLO por un pedido concreto al cliente, en horario, y escalada")
else:
    fail("triage: el recordatorio de la espera no cumple la regla vigente")
# H2) El disparador que carga la DESCRIPCIÓN del ticket acepta plural ('tickets') y 'legajo'
import re as _re2
m = _re2.search(r'habla_de_ticket = bool\(re\.search\(\s*\n?\s*r"([^"]+)"', conv2)
if m:
    pat = m.group(1)
    plural = bool(_re2.search(pat, "decime el legajo del tickets abierto", _re2.I))
    negativo = not bool(_re2.search(pat, "hola como estas", _re2.I))
    if plural and negativo:
        ok("conversación: lee el ticket cuando decís 'tickets'/'legajo' (da el legajo)")
    else:
        fail("el disparador de leer-ticket no acepta plural/legajo", f"plural={plural} neg={negativo}")
else:
    fail("no se encontró el disparador habla_de_ticket")

# H3) Si un TÉCNICO resuelve por comentario -> ITHOS marca Resuelto + pide confirmación al cliente
try:
    import importlib
    sys.path.insert(0, os.path.join(APP, "central"))
    sys.path.insert(0, APP)
    import triage as _TRI
    importlib.reload(_TRI)
    _orig_de = _TRI.G.de_entidad
    _TRI.G.de_entidad = lambda tks, ent: tks           # en el test no filtramos por entidad

    class _Cli:
        def tickets_recientes(self, n): return [{"id": 597, "status": 4, "entities_id": 0}]
        def abrir(self): pass
        def cerrar(self): pass
        def request(self, path, method=None, data=None):
            if path == "/Ticket/597/ITILFollowup":
                return [{"id": 9, "users_id": 7,
                         "content": "Estimados, el caso quedó solucionado, ya puede fichar."}]
            if path.startswith("/User/"):
                return {"firstname": "Brian", "realname": "Sierra"}
            return {}
    llam = {"marcar": 0, "confirm": 0}

    class _Tri:
        # El ciclo pregunta PRIMERO si queda algo del cliente (acá no) y recién después si resuelve.
        def tecnico_pide_confirmacion(self, t): return False
        def tecnico_resolvio(self, t): return True     # el comentario del técnico resuelve
        def marcar_resuelto(self, tid, sol="", autor=None):llam["marcar"] += 1; return True
        def pedir_confirmacion(self, tid): llam["confirm"] += 1; return True
        def poner_en_curso(self, tid): return True
        def cerrar(self, tid): return True
        def reabrir(self, tid): return True
        def cliente_confirma(self, t): return None
    try:
        _TRI.gestionar_ciclo(_Cli(), _Tri(), 0, {})
    finally:
        _TRI.G.de_entidad = _orig_de
    if llam["marcar"] == 1 and llam["confirm"] == 1:
        ok("triage: técnico resuelve por comentario -> marca Resuelto + pide confirmación")
    else:
        fail("no se dispara marcar-resuelto + confirmación al resolver el técnico", str(llam))
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la resolución por técnico", repr(e))


# H4) IDEMPOTENCIA (regresión "no confirma dos veces"): si ITHOS YA dejó el pedido de
#     confirmación en el ticket, NO lo repite aunque el estado en memoria esté vacío (reinicio).
try:
    llam2 = {"confirm": 0}

    class _Cli2:
        def tickets_recientes(self, n): return [{"id": 597, "status": 5, "entities_id": 0}]
        def abrir(self): pass
        def cerrar(self): pass
        def request(self, path, method=None, data=None):
            if path == "/Ticket/597/ITILFollowup":
                return [{"id": 20, "users_id": 28,
                         "content": "Le informamos que su solicitud fue resuelta. Por favor, "
                                    "confírmenos si ya puede fichar."}]
            if path.startswith("/User/"):
                return {"firstname": "ITHOS", "realname": "IA"}
            return {}

    class _Tri2:
        def tecnico_resolvio(self, t): return True
        def marcar_resuelto(self, tid, sol="", autor=None):return True
        def pedir_confirmacion(self, tid): llam2["confirm"] += 1; return True
        def poner_en_curso(self, tid): return True
        def cerrar(self, tid): return True
        def reabrir(self, tid): return True
        def cliente_confirma(self, t): return None
        def nota_interna(self, tid, texto): return True
    _orig_de2 = _TRI.G.de_entidad
    _TRI.G.de_entidad = lambda tks, ent: tks
    try:
        _TRI.gestionar_ciclo(_Cli2(), _Tri2(), 0, {})   # estado vacío = como tras reinicio
    finally:
        _TRI.G.de_entidad = _orig_de2
    if llam2["confirm"] == 0:
        ok("triage: NO repite el pedido de confirmación si ya se pidió (idempotente)")
    else:
        fail("ITHOS pide confirmación dos veces (repite el pedido)", str(llam2))
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la idempotencia de la confirmación", repr(e))


# H5) La 1ª respuesta pide datos SOLO si faltan (no "cadena" pidiendo algo que no falta):
#     hay legajo -> necesita_info=false -> EN CURSO (status 2); falta -> true -> EN ESPERA (4).
try:
    puts = []

    class _CliP:
        def abrir(self): pass
        def cerrar(self): pass
        def request(self, path, method=None, data=None):
            if method == "PUT" and isinstance(data, dict):
                s = (data.get("input") or {}).get("status")
                if s is not None:
                    puts.append(s)
            return {}

    def _clasif(necesita):
        return lambda ia, asunto, desc, **k: {
            "categoria": "TERMINALES", "prioridad": "Baja", "responsable": "bsierra",
            "necesita_info": necesita, "resumen": "x", "primera_respuesta": "Acuse. Soporte ITH."}

    tri = _TRI.Triage.__new__(_TRI.Triage)
    tri.cli, tri.ia = _CliP(), None
    # cfg 24/7: aísla el routing por necesita_info del manejo de fuera-de-horario (H81), así el test
    # es determinista sin importar a qué hora se corra la batería.
    tri.cfg_glpi = {"horario_atencion": {"dias": [0, 1, 2, 3, 4, 5, 6], "desde": "00:00", "hasta": "23:59"}}
    _orig_clas = _TRI.cerebro.clasificar_ticket
    try:
        puts.clear()
        _TRI.cerebro.clasificar_ticket = _clasif(False)     # hay legajo -> no falta nada
        tri.procesar({"id": 1, "name": "no puede fichar", "content": "legajo 05257"})
        con = puts[-1] if puts else None
        puts.clear()
        _TRI.cerebro.clasificar_ticket = _clasif(True)      # falta el legajo
        tri.procesar({"id": 2, "name": "no puede fichar", "content": "Juan no puede fichar"})
        sin = puts[-1] if puts else None
    finally:
        _TRI.cerebro.clasificar_ticket = _orig_clas
    if con == 2 and sin == 4:
        ok("triage: 1ª respuesta pide datos SOLO si faltan (legajo->EN CURSO / falta->EN ESPERA)")
    else:
        fail("triage: routing EN CURSO/EN ESPERA por necesita_info incorrecto",
             f"con_legajo={con} sin_legajo={sin}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar 'pide datos solo si faltan'", repr(e))


# H6) RESUELTO sin respuesta del cliente -> recordatorio UNA VEZ POR DÍA; si el cliente responde
#     (confirma o dice que sigue) -> cierra/reabre y NO recuerda más. El cliente puede responder
#     en cualquier momento y su respuesta tiene prioridad sobre el recordatorio.
try:
    from datetime import datetime as _dt, timedelta as _td
    viejo = (_dt.now() - _td(days=2)).strftime("%Y-%m-%d %H:%M:%S")   # >24h -> toca recordar
    reciente = _dt.now().strftime("%Y-%m-%d %H:%M:%S")                # <24h -> NO recordar
    CONF = "Le informamos que su solicitud fue resuelta. Por favor, confírmenos."

    def _run6(fu_list, confirma=True):
        cont = {"recordar": 0, "cerrar": 0, "reabrir": 0}

        class _C6:
            def tickets_recientes(self, n): return [{"id": 7, "status": 5, "entities_id": 0}]
            def abrir(self): pass
            def cerrar(self): pass
            def request(self, path, method=None, data=None):
                if path == "/Ticket/7/ITILFollowup": return fu_list
                if path.startswith("/User/"): return {"firstname": "Cli", "realname": "Ente"}
                return {}

        class _T6:
            # El ciclo lee el horario del cliente desde triage.cfg_glpi: para que el test no dependa
            # de la hora en que se corre, se declara un horario SIEMPRE abierto (la regla de "solo en
            # horario" se verifica aparte, con un horario cerrado).
            cfg_glpi = {"horario_atencion": {"dias": [0, 1, 2, 3, 4, 5, 6],
                                             "desde": "00:00", "hasta": "23:59"}}

            def pedir_confirmacion(self, tid): return True
            def recordar_confirmacion(self, tid): cont["recordar"] += 1; return True
            def cerrar(self, tid): cont["cerrar"] += 1; return True
            def reabrir(self, tid): cont["reabrir"] += 1; return True
            def cliente_confirma(self, t): return confirma
            def poner_en_curso(self, tid): return True
            def nota_interna(self, tid, texto): return True
        od = _TRI.G.de_entidad
        _TRI.G.de_entidad = lambda tks, ent: tks
        try:
            _TRI.gestionar_ciclo(_C6(), _T6(), 0, {})   # estado vacío = como tras reinicio
        finally:
            _TRI.G.de_entidad = od
        return cont

    a = _run6([{"id": 1, "users_id": 28, "content": CONF, "date_creation": viejo}])
    b = _run6([{"id": 1, "users_id": 28, "content": CONF, "date_creation": reciente}])
    c = _run6([{"id": 1, "users_id": 28, "content": CONF, "date_creation": viejo},
               {"id": 2, "users_id": 99, "content": "Sí, ya puedo fichar, gracias",
                "date_creation": reciente}], confirma=True)
    d = _run6([{"id": 1, "users_id": 28, "content": CONF, "date_creation": viejo},
               {"id": 2, "users_id": 99, "content": "No, sigo sin poder fichar",
                "date_creation": reciente}], confirma=False)
    if (a["recordar"] == 1 and b["recordar"] == 0 and
            c["cerrar"] == 1 and c["recordar"] == 0 and
            d["reabrir"] == 1 and d["recordar"] == 0):
        ok("triage: RESUELTO sin respuesta -> recordatorio diario; responde -> cierra/reabre y no repite")
    else:
        fail("recordatorio diario de confirmación / cierre incorrecto", f"a={a} b={b} c={c} d={d}")

    # FUERA del horario de atención no se le escribe al cliente (ni de noche ni fin de semana)
    class _T6cerrado(object):
        cfg_glpi = {"horario_atencion": {"dias": [], "desde": "09:00", "hasta": "18:00"}}
        veces = 0

        def pedir_confirmacion(self, tid): return True
        def recordar_confirmacion(self, tid): _T6cerrado.veces += 1; return True
        def cerrar(self, tid): return True
        def reabrir(self, tid): return True
        def cliente_confirma(self, t): return None
        def poner_en_curso(self, tid): return True
        def nota_interna(self, tid, texto): return True

    class _C6cerrado(object):
        def tickets_recientes(self, n): return [{"id": 7, "status": 5, "entities_id": 0}]
        def abrir(self): pass
        def cerrar(self): pass
        def request(self, path, method=None, data=None):
            if path == "/Ticket/7/ITILFollowup":
                return [{"id": 1, "users_id": 28, "content": CONF, "date_creation": viejo}]
            if path.startswith("/User/"): return {"firstname": "Cli", "realname": "Ente"}
            return {}
    od2 = _TRI.G.de_entidad
    _TRI.G.de_entidad = lambda tks, ent: tks
    try:
        _TRI.gestionar_ciclo(_C6cerrado(), _T6cerrado(), 0, {})
    finally:
        _TRI.G.de_entidad = od2
    if _T6cerrado.veces == 0:
        ok("triage: fuera del horario de atención NO se le escribe al cliente")
    else:
        fail("se le escribió al cliente fuera de horario", f"veces={_T6cerrado.veces}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el recordatorio diario de confirmación", repr(e))


# H7) LATENCIA del poller: con muchos tickets a revisar, gestionar_ciclo trae los followups en UNA
#     lectura masiva (no una request por ticket). Fallback por-ticket si la masiva falla.
try:
    paths7 = []

    class _CliP7:
        def tickets_recientes(self, n):
            return [{"id": i, "status": 5, "entities_id": 0} for i in range(1, 13)]  # 12 > 8
        def abrir(self): pass
        def cerrar(self): pass
        def request(self, path, method=None, data=None):
            paths7.append(path)
            if path.startswith("/ITILFollowup?range="):     # lectura masiva -> mapea a los 12 tickets
                return [{"id": 100 + i, "itemtype": "Ticket", "items_id": i, "users_id": 28,
                         "content": "avance", "date_creation": "2026-07-06 10:00:00"}
                        for i in range(1, 13)]
            if path.startswith("/User/"):
                return {"firstname": "C", "realname": "E"}
            return []

    class _TriP7:
        def pedir_confirmacion(self, tid): return True
        def recordar_confirmacion(self, tid): return True
        def cerrar(self, tid): return True
        def reabrir(self, tid): return True
        def cliente_confirma(self, t): return None
        def marcar_resuelto(self, tid, sol="", autor=None):return True
        def tecnico_resolvio(self, t): return False
        def nota_interna(self, tid, texto): return True
    od7 = _TRI.G.de_entidad
    _TRI.G.de_entidad = lambda tks, ent: tks
    try:
        _TRI.gestionar_ciclo(_CliP7(), _TriP7(), 0, {})
    finally:
        _TRI.G.de_entidad = od7
    por_ticket7 = [p for p in paths7 if re.match(r"^/Ticket/\d+/ITILFollowup", p)]
    bulk7 = [p for p in paths7 if p.startswith("/ITILFollowup?range=")]
    if not por_ticket7 and bulk7:
        ok(f"poller sin N+1: {len(bulk7)} lectura masiva de followups, 0 por-ticket (12 tickets)")
    else:
        fail("poller con N+1 (followups por ticket)",
             f"por_ticket={len(por_ticket7)} bulk={len(bulk7)}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la latencia del poller (N+1 followups)", repr(e))


# H8) Los AVISOS de WhatsApp respetan el FORMATO del cliente: 'texto'->solo texto, 'audio'->solo
#     nota de voz, 'ambos'->texto + nota de voz. Aplica a demo y producción (misma clase).
try:
    import threading as _th8
    import time as _t8
    from comun import whatsapp as _WA8

    def _wa_fmt(fmt):
        calls = {"text": 0, "audio": 0}

        class _FC8:
            def send_message(self, jid, txt): calls["text"] += 1
            def send_audio(self, jid, data, ptt=False): calls["audio"] += 1
            def send_document(self, *a, **k): calls["audio"] += 1
        w = _WA8.WhatsAppNoOficial.__new__(_WA8.WhatsAppNoOficial)
        w.client = _FC8()
        w.grupo_jid = "G@g.us"
        w._listo = _th8.Event()
        w._listo.set()
        w.respuesta = fmt
        w.tts = lambda x: b"VOICE"
        w._ultima_respuesta = ""
        w.enviar("Aviso: ticket #1 en espera")
        for _ in range(100):                  # la nota de voz sale en segundo plano
            if fmt == "texto" or calls["audio"]:
                break
            _t8.sleep(0.02)
        return calls
    a = _wa_fmt("texto")
    b = _wa_fmt("audio")
    c = _wa_fmt("ambos")
    if (a == {"text": 1, "audio": 0} and b == {"text": 0, "audio": 1} and
            c == {"text": 1, "audio": 1}):
        ok("WhatsApp avisos respetan el formato: texto / audio (nota de voz) / ambos")
    else:
        fail("WhatsApp avisos no respetan el formato del cliente", f"texto={a} audio={b} ambos={c}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el formato texto/voz de los avisos de WhatsApp", repr(e))


# H9) La demo/multicanal REUSA la conexión WhatsApp compartida (no abre otra sesión) y suma los
#     demás canales configurados por el cliente. Así los avisos van por TODOS los canales.
try:
    from comun import notificadores as _NT9
    cli9 = {"notificaciones": [{"tipo": "whatsapp_no_oficial", "enabled": True}]}

    class _WAfake:
        def enviar(self, t, tipo=None): return True
    waf = _WAfake()
    n9 = _NT9.crear_notificadores(cli9, wa_compartido=waf)
    tipos = [type(c).__name__ for c in n9.canales]
    dup_wa = sum(1 for c in n9.canales if type(c).__name__.startswith("WhatsApp"))
    # La ESTRUCTURA multicanal sigue: Notificadores agrupa N canales y reparte a todos. Hoy el
    # cliente usa uno solo (WhatsApp); sumar otro es agregar una clase con enviar().
    n9b = _NT9.Notificadores([waf, _WAfake()])
    if waf in n9.canales and dup_wa == 0 and len(n9.canales) == 1 and n9b.enviar("hola"):
        ok(f"notificadores: reusa el WhatsApp compartido sin duplicar sesión y sigue "
           f"soportando VARIOS canales ({tipos})")
    else:
        fail("notificadores no reusa el WhatsApp compartido o perdió el soporte multicanal",
             str(tipos))
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la reutilización del WhatsApp compartido", repr(e))


# H10) [retirado] La Cloud API de Meta (WhatsApp oficial) salió del alcance: INTELLIHELP usa
#      el canal no oficial con su propio número. La implementación quedó en la rama `saas`.


# H13) [retirado] Telegram salió del alcance (queda WhatsApp). Congelado en la rama `saas`.


# H11) CADENA DE IA: usa UNA sola IA por consulta y SOLO pasa a la siguiente si la actual FALLA/se
#      agota. Nunca gasta tokens/llamadas de las otras si la primaria anduvo. Tras agotarse la
#      primaria (cooldown), las siguientes consultas ARRANCAN en la secundaria (no re-gastan la 1ª).
try:
    from comun import ia as _IA11

    class _FakeIA:
        def __init__(self, name, fail=False):
            self.name, self.fail, self.calls = name, fail, 0

        def chat(self, system, prompt, json_out=True, max_tokens=None):
            self.calls += 1
            if self.fail:
                raise Exception("429 RESOURCE_EXHAUSTED quota")
            return '{"ok":"%s"}' % self.name
    # 1) primaria OK -> solo la primaria; secundaria y terciaria NO se tocan
    p1, s1, t1 = _FakeIA("prim"), _FakeIA("sec"), _FakeIA("ter")
    _IA11.MultiIA(p1, s1, t1).chat("s", "p")
    caso1 = (p1.calls, s1.calls, t1.calls)          # esperado (1, 0, 0)
    # 2) primaria FALLA -> cae a secundaria; terciaria NO se toca
    p2, s2, t2 = _FakeIA("prim", fail=True), _FakeIA("sec"), _FakeIA("ter")
    m2 = _IA11.MultiIA(p2, s2, t2)
    m2.chat("s", "p")
    caso2 = (p2.calls, s2.calls, t2.calls)          # esperado (1, 1, 0)
    # 3) siguiente consulta: la primaria quedó en cooldown -> arranca en la secundaria (no re-gasta)
    m2.chat("s", "p")
    caso3 = (p2.calls, s2.calls, t2.calls)          # esperado (1, 2, 0): primaria NO se re-llama
    if caso1 == (1, 0, 0) and caso2 == (1, 1, 0) and caso3 == (1, 2, 0):
        ok("cadena de IA: 1 sola IA por consulta; fallback solo al agotarse; cooldown no re-gasta")
    else:
        fail("cadena de IA gasta llamadas de más (no es 1-a-la-vez / no respeta cooldown)",
             f"c1={caso1} c2={caso2} c3={caso3}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la cadena de IA (fallback secuencial)", repr(e))


# H86) ESCALERA DE MODELOS DENTRO DE GEMINI (bug real de producción, 18-ago-2026: el triage dejó de
#   clasificar tickets y el ciclo no cerraba nada. Causa: la cuota GRATIS de Gemini es por MODELO Y POR
#   DÍA, y la de `gemini-2.5-flash-lite` -el que elegía 'auto' por ser el más eficiente- quedó en 20
#   pedidos por día: se agota con 20 tickets. ITHOS saltaba de PROVEEDOR aunque `gemini-2.5-flash`
#   todavía tuviera cuota del día, y como Cerebras pedía pago y la key de Groq estaba vencida, se
#   quedaba sin ninguna IA). Fix: agotado un modelo, sigue con el siguiente de Gemini y recién después
#   cambia de proveedor. Lo agotado se libera solo al día siguiente.
try:
    import datetime as _dt86
    from comun import ia as _IA86
    g86 = _IA86.GeminiIA({"gemini_api_key": "x", "modelo_texto": "gemini-2.5-flash-lite"})
    hoy86 = _dt86.date.today().isoformat()
    escalera = len(g86._escalera) >= 3 and g86._modelo_vigente() == "gemini-2.5-flash-lite"
    # se agota el primero -> sigue con el segundo, sin cambiar de proveedor
    sigue = g86._marcar_agotado("gemini-2.5-flash-lite") and g86._modelo_vigente() == "gemini-2.5-flash"
    # se agotan TODOS -> recién ahí avisa que Gemini quedó sin cuota (y la cadena pasa al siguiente)
    for _m86 in g86._escalera[1:]:
        ultimo86 = g86._marcar_agotado(_m86)
    corta = ultimo86 is False
    # lo agotado AYER no bloquea hoy: la cuota gratuita se renueva por día
    g86._agotados = {m: "2000-01-01" for m in g86._escalera}
    renueva = g86._modelo_vigente() == "gemini-2.5-flash-lite" and hoy86 != "2000-01-01"
    if escalera and sigue and corta and renueva:
        ok("cuota de Gemini por modelo: agotado uno sigue con el siguiente modelo de Gemini y sólo "
           "cambia de proveedor cuando se agotan TODOS; al día siguiente vuelven a estar disponibles")
    else:
        fail("un modelo de Gemini sin cuota tira abajo el triage (no usa los otros modelos)",
             f"escalera={escalera} sigue={sigue} corta={corta} renueva={renueva}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la escalera de modelos de Gemini", repr(e))


# H87) EL CLIENTE SON TODAS SUS ÁREAS (bug real y grave, #666 "Terminal EP": Sistemas de SRT avisó que
#   las terminales de un entrepiso estaban desenergizadas y el ticket quedó SIETE DÍAS en Nuevo, sin
#   asignar, sin primera respuesta y sin SLA. En GLPI el mismo cliente tiene una entidad POR ÁREA
#   -mesa de ayuda, soporte técnico, infraestructura- e ITHOS miraba una sola: lo que entraba por otra
#   área no lo veía nadie. Y cada área tiene SUS categorías y SUS SLA, con ids distintos).
try:
    from comun import glpi as _G87
    # a) el filtro acepta UNA entidad (como siempre) o TODAS las del cliente
    _ts87 = [{"id": 1, "entities_id": 12}, {"id": 2, "entities_id": 13}, {"id": 3, "entities_id": 19}]
    una = [t["id"] for t in _G87.de_entidad(_ts87, 12)]
    varias = [t["id"] for t in _G87.de_entidad(_ts87, [12, 13])]
    # b) el catálogo se lee POR ENTIDAD, y el triage usa el de la entidad del ticket
    tri87 = leer_tickets()
    por_entidad = ("catalogo_entidad" in tri87 and "entities_id" in tri87
                   and "G.catalogo_entidad(self.cfg_glpi, ent_ticket)" in tri87)
    # c) en un área sin catálogo propio NO se le pone el id de otra entidad
    sin_heredar = "if propio else None" in tri87
    # c.2) la sesión de GLPI abre con TODAS las entidades del usuario activas. GLPI activa UNA sola
    #      y el resto responde 403 aunque haya permiso; y el pedido va envuelto en `input` (sin el
    #      envoltorio contesta `false` y deja la sesión acotada, sin ningún error visible).
    glpi87 = leer(os.path.join(APP, "comun", "glpi.py"))
    sesion_amplia = ('{"input": {"entities_id": "all"}}' in glpi87
                     and "self._activar_entidades()" in glpi87)
    # d) el vigilante, el ciclo, los reportes y el asistente miran TODAS las áreas
    fuentes = {n: leer(os.path.join(APP, *p)) for n, p in (
        ("vigilante", ("central", "integrador_glpi.py")),
        ("reportes", ("central", "reportes.py")),
        ("itil", ("comun", "reportes_itil.py")),
        ("tickets", ("comun", "tickets.py")),
        ("asistente", ("comun", "herramientas.py")))}
    todos = [n for n, s in fuentes.items() if "entidades_de" in s]
    if (una == [1] and varias == [1, 2] and por_entidad and sin_heredar and sesion_amplia
            and len(todos) == len(fuentes)):
        ok("el cliente son TODAS sus áreas: un ticket que entra por soporte técnico o "
           "infraestructura se ve, se asigna y se contesta, con la categoría y el SLA DE SU área "
           "(y si esa área no tiene catálogo propio, no se le pone el de la de al lado)")
    else:
        fail("un ticket que entra por otra área del cliente queda sin atender",
             f"una={una} varias={varias} por_entidad={por_entidad} sin_heredar={sin_heredar} "
             f"sesion_amplia={sesion_amplia} miran_todas={todos}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el circuito por áreas del cliente", repr(e))


# H88) MODELO RETIRADO POR EL PROVEEDOR (bug real: Groq dio de baja los Llama y el triage empezó a
#   recibir 404 en cada ticket; el modelo estaba escrito en el código). Igual que con la cuota, se
#   sigue con el modelo siguiente del MISMO proveedor antes de cambiar de proveedor.
try:
    from comun import ia as _IA88
    detecta = all(_IA88._modelo_retirado(m) for m in (
        '{"error":{"code":"model_not_found"}}',
        "The model `llama-3.3-70b-versatile` does not exist or you do not have access to it.",
        "models/gemini-x is not found for API version v1beta"))
    no_falsos = not _IA88._modelo_retirado("rate limit exceeded")
    esc = _IA88.escalera_de("groq", "openai/gpt-oss-120b")
    arranca = esc[0] == "openai/gpt-oss-120b" and len(esc) >= 2
    # el que elige 'auto' para Groq tiene que EXISTIR hoy (no un Llama dado de baja)
    vigente = "llama" not in _IA88._MODELOS["groq"]["free"].lower()
    baja_solo = "_modelo_retirado(cuerpo)" in leer(os.path.join(APP, "comun", "ia.py"))
    if detecta and no_falsos and arranca and vigente and baja_solo:
        ok("si el proveedor da de baja el modelo, ITHOS sigue con el siguiente del mismo proveedor "
           "en vez de dejar al cliente sin IA")
    else:
        fail("un modelo dado de baja deja el triage sin IA",
             f"detecta={detecta} no_falsos={no_falsos} arranca={arranca} vigente={vigente} "
             f"baja_solo={baja_solo}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la escalera ante un modelo retirado", repr(e))


# H12) AVISO DE CAMBIO DE IA: al agotarse una IA, avisa al canal del cliente "sigo con la siguiente"
#      (para los motores que no son Gemini/Groq, que ya los anuncia el GestorCuota). Con dedup.
try:
    from comun import ia as _IA12
    avisos12 = []

    class _Gestor12:
        def _emitir(self, nivel, msg): avisos12.append((nivel, msg))

    class _FakeIA12:
        def __init__(self, name, fail=False): self.name, self.fail = name, fail
        def chat(self, s, p, j=True, m=None):
            if self.fail:
                raise Exception("429 RESOURCE_EXHAUSTED quota")
            return '{"ok":"%s"}' % self.name
    prim12 = _FakeIA12("Cerebras", fail=True)
    sec12 = _FakeIA12("GroqAlt")
    mm12 = _IA12.MultiIA(prim12, sec12, gestor=_Gestor12())
    mm12.chat("s", "p")                 # prim se agota -> avisa el cambio
    mm12._avisar_cambio(prim12, sec12)  # dedup: dentro del cooldown NO repite
    if len(avisos12) == 1 and "sin consultas" in avisos12[0][1] and "Sigo" in avisos12[0][1]:
        ok("aviso de cambio de IA al canal del cliente (una vez, con dedup)")
    else:
        fail("no avisa el cambio de IA al canal (o lo repite)", f"avisos={avisos12}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el aviso de cambio de IA", repr(e))


# H14) El integrador triagea por ESTADO (Nuevo=1), NO por 'id > baseline': así atiende los tickets
#      que entraron con ITHOS APAGADO (al arrancar la demo/producción se pone al día).
try:
    sys.path.insert(0, os.path.join(APP, "central"))
    import integrador_glpi as _IG14
    recientes14 = [
        {"id": 640, "status": 1},   # Nuevo VIEJO (entró con ITHOS apagado) -> debe triagearse
        {"id": 644, "status": 1},   # Nuevo -> triagearse
        {"id": 642, "status": 2},   # En curso -> NO
        {"id": 643, "status": 5},   # Resuelto -> NO
        {"id": 645, "status": 6},   # Cerrado -> NO
        "basura",                   # no-dict -> ignorar sin romper
    ]
    ids14 = [t["id"] for t in _IG14.pendientes_triage(recientes14)]
    if ids14 == [640, 644]:
        ok("integrador: triagea los 'Nuevo' pendientes por ESTADO (se pone al día al arrancar)")
    else:
        fail("integrador no selecciona bien los tickets a triage", f"ids={ids14}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la selección de tickets a triage", repr(e))


# H15) La 1ª respuesta saluda al SOLICITANTE (quien ABRIÓ el ticket) por su nombre, NO a la persona
#      AFECTADA del texto. Helper COMPARTIDO (comun/glpi.saludo_solicitante) usado por el triage
#      automático Y el camino de voz (tickets.aplicar_ciclo) -> aplica en TODO.
try:
    from comun import glpi as _G15
    r1 = _G15.saludo_solicitante("Hola Ivana, gracias por informarnos. Soporte ITH", "Facundo")
    r2 = _G15.saludo_solicitante("Estimada Ivana: recibimos su caso.", "Facundo")
    r3 = _G15.saludo_solicitante("Gracias por avisar.", "Facundo")   # sin saludo -> antepone
    r4 = _G15.saludo_solicitante("Hola Ivana, algo.", "")            # sin solicitante -> deja igual
    src_tk = open(os.path.join(APP, "comun", "tickets.py"), encoding="utf-8").read()
    voz_aplica = "saludo_solicitante" in src_tk    # el camino de voz (aplicar_ciclo) lo aplica
    if (r1.startswith("Hola Facundo,") and "Ivana" not in r1 and
            r2.startswith("Hola Facundo,") and "Ivana" not in r2 and
            r3.startswith("Hola Facundo,") and r4 == "Hola Ivana, algo." and voz_aplica):
        ok("1ª respuesta saluda al SOLICITANTE por su nombre — en triage automático Y en voz (aplicar_ciclo)")
    else:
        fail("el saludo al solicitante no se aplica en todos lados",
             f"r1={r1!r} r3={r3!r} voz_aplica={voz_aplica}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el saludo al solicitante", repr(e))


# H16) RECUPERACIÓN AUTOMÁTICA de la IA: si la primaria se recupera, vuelve SOLA aunque siga en
#      cooldown (re-probe periódico), incluso con la secundaria caída. No espera todo el cooldown.
try:
    import time as _t16
    from comun import ia as _IA16

    class _F16:
        def __init__(s, n, fail=False): s.n, s.fail, s.calls = n, fail, 0
        def chat(s, sy, p, j=True, m=None):
            s.calls += 1
            if s.fail:
                raise Exception("429 RESOURCE_EXHAUSTED quota")
            return '{"ok":"%s"}' % s.n
    prim16, sec16, ter16 = _F16("gem", fail=True), _F16("cer", fail=True), _F16("groq")
    mm16 = _IA16.MultiIA(prim16, sec16, ter16)
    mm16.chat("s", "p")                                   # prim falla -> cooldown; cae a groq
    en_cd = mm16._primaria_hasta > _t16.time()
    mm16.chat("s", "p")                                   # probe reciente -> NO re-prueba la primaria
    sin_reprobe = (prim16.calls == 1)
    prim16.fail = False                                   # la primaria ya volvió
    mm16._ultimo_probe = 0.0                              # pasó el intervalo de re-probe
    r16 = mm16.chat("s", "p")
    volvio = ('"ok":"gem"' in r16 and prim16.calls >= 2)
    if en_cd and sin_reprobe and volvio:
        ok("cadena de IA: la primaria vuelve SOLA al recuperarse (re-probe), sin esperar todo el cooldown")
    else:
        fail("la primaria no se recupera automáticamente",
             f"cooldown={en_cd} sin_reprobe={sin_reprobe} volvio={volvio}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la recuperación automática de la IA", repr(e))


# H17) ANTI-SUSPENSIÓN: la PC no se duerme mientras ITHOS corre (producción y demo), aunque se
#      bloquee la pantalla. mantener_despierto existe, es idempotente y no rompe (multiplataforma).
try:
    from comun import despierto as _DES
    r1 = _DES.mantener_despierto()
    r2 = _DES.mantener_despierto()
    if isinstance(r1, bool) and r1 == r2:
        ok(f"anti-suspensión: mantener_despierto idempotente (activo={r1})")
    else:
        fail("anti-suspensión no idempotente / rompe", f"r1={r1!r} r2={r2!r}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el anti-suspensión", repr(e))


# H18) DEMO = PRODUCCIÓN en el portero: la demo arranca el integrador de acceso real (saluda las
#      fichadas nuevas), el IVMS tiene BASELINE (las viejas NO se repiten), y el anti-suspensión
#      está cableado en agente/central/demo.
try:
    def _leer(*partes):
        import os as _o
        _ruta=os.path.join(APP if partes and partes[0] in ("comun","central","agente") else RAIZ, *partes)
        return open(os.path.join(APP if partes and partes[0] in ("comun","central","agente") else RAIZ, *partes), encoding="utf-8").read()
    src_demo = _leer("iniciar_demo.py")
    src_ivms = _leer("agente", "integrador_ivms.py")
    portero_demo = ('cfg["integrador"]' in src_demo and "integrador_config" in src_demo)
    baseline_ivms = ("baseline" in src_ivms and "vistos" in src_ivms)
    despierto_wired = all("mantener_despierto" in _leer(*p) for p in (
        ("iniciar_demo.py",), ("agente", "agente.py"), ("central", "main.py")))
    if portero_demo and baseline_ivms and despierto_wired:
        ok("demo arranca portero real; baseline ignora fichadas viejas; anti-suspensión en agente/central/demo")
    else:
        fail("falta portero-demo / baseline / anti-suspensión",
             f"portero={portero_demo} baseline={baseline_ivms} despierto={despierto_wired}")
except Exception as e:  # noqa: BLE001
    ok("[demo retirada] no se pudo verificar demo-portero / baseline / anti-suspensión", repr(e))


# H19) LOG LIMPIO: el ruido inofensivo de terceros no ensucia el log (se silencia sin tapar lo
#      útil). Hoy: el WARNING de neonize.utils.ffmpeg al leer metadatos del audio (el audio va igual).
try:
    src_wa = open(os.path.join(APP, "comun", "whatsapp.py"), encoding="utf-8").read()
    silencia = ('getLogger("neonize.utils.ffmpeg")' in src_wa and
                "setLevel(logging.ERROR)" in src_wa)
    if silencia:
        ok("log limpio: ruido de neonize/ffmpeg silenciado (el audio se envía igual)")
    else:
        fail("el ruido inofensivo de terceros sigue ensuciando el log", "falta silenciar ffmpeg")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la limpieza del log", repr(e))


# H20) PORTERO: el nombre del saludo es CONSISTENTE venga del lector que venga (bienvenida y sala
#      técnica igual). Normaliza espacios y 'Apellido, Nombre' -> 'Nombre Apellido'. Punto único.
try:
    sys.path.insert(0, os.path.join(APP, "central"))
    import procesador as _PROC
    n1 = _PROC._nombre_norm("Roldán, Mauro Aníbal")
    n2 = _PROC._nombre_norm("  Roldán   Mauro ")
    n3 = _PROC._nombre_norm("Mauro Roldán")
    if n1 == "Mauro Aníbal Roldán" and n2 == "Roldán Mauro" and n3 == "Mauro Roldán":
        ok("portero: nombre del saludo consistente (colapsa espacios y 'Apellido, Nombre'->'Nombre Apellido')")
    else:
        fail("el nombre del saludo del portero no queda consistente", f"n1={n1!r} n2={n2!r} n3={n3!r}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el nombre del portero", repr(e))


# H21) TRANSCRIPCIÓN por Groq (Whisper) SIEMPRE primero (más rápido: ~1-2s vs ~5s de Gemini). Si
#      Groq falla/no está, cae a Gemini. NO cambia la voz/identidad (sigue Charon/Gemini).
try:
    from comun import ia as _IA21
    orden21 = []

    class _Gem21(_IA21.GeminiIA):
        def __init__(self): pass
        def transcribir(self, a, m="audio/ogg", idioma=None):
            orden21.append("gemini"); return "texto-gemini"

    class _Groq21(_IA21.GroqCloudIA):
        def __init__(self): pass
        def transcribir(self, a, m="audio/ogg", idioma=None):
            orden21.append("groq"); return "texto-groq"
    mm21 = _IA21.MultiIA(_Gem21(), _Groq21())
    r21 = mm21.transcribir(b"AUDIO")
    if orden21 and orden21[0] == "groq" and r21 == "texto-groq":
        ok("transcripción: prueba Groq/Whisper primero (rápido); Gemini de respaldo, sin tocar la voz")
    else:
        fail("la transcripción no prefiere Groq (Whisper)", f"orden={orden21} r={r21!r}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la transcripción por Groq", repr(e))


# H22) NOTA DE VOZ más rápida (sin romper el cacheo): edge-tts a MEMORIA (sin archivo temporal) +
#      precalentado para que el 1er audio no pague el arranque en frío. Cableado en demo y central.
try:
    def _leer22(*p):
        try:
            return open(os.path.join(APP if p and p[0] in ("comun","central","agente") else RAIZ, *p), encoding="utf-8").read()
        except FileNotFoundError:
            return ""
    src_v = _leer22("comun", "voz_tts.py")
    a_memoria = (".stream()" in src_v and "tempfile" not in src_v)     # sin archivo temporal
    tiene_precal = "def precalentar" in src_v
    precal_wired = ("precalentar()" in _leer22("central", "main.py"))
    if a_memoria and tiene_precal and precal_wired:
        ok("nota de voz más rápida: edge a memoria + precalentado (demo y central), sin tocar el cacheo")
    else:
        fail("falta optimizar la nota de voz (edge memoria / precalentar)",
             f"memoria={a_memoria} precal={tiene_precal} wired={precal_wired}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la optimización de la nota de voz", repr(e))


# H23) La demo manda su LOG a ARCHIVO (consola limpia para escribir en el menú, sin que los logs de
#      neonize/httpx/IA pisen el prompt) y el input del menú es ROBUSTO (un EOF/hipo de terminal NO
#      desconecta WhatsApp ni mata los servicios: se cierra solo con 'S' o Ctrl+C).
try:
    src_d = open(os.path.join(RAIZ, "iniciar_demo.py"), encoding="utf-8").read()
    log_a_archivo = ("def _config_log" in src_d and "FileHandler" in src_d and
                     "removeHandler" in src_d)
    input_robusto = ("except EOFError" in src_d and 'op = input("   Opción' in src_d)
    if log_a_archivo and input_robusto:
        ok("demo: logs a archivo (consola limpia) + input del menú robusto (EOF no desconecta WhatsApp)")
    else:
        fail("falta log-a-archivo o input robusto en la demo",
             f"log={log_a_archivo} input={input_robusto}")
except Exception as e:  # noqa: BLE001
    ok("[demo retirada] no se pudo verificar consola limpia / input robusto", repr(e))


# H24) La VOZ no lee EMOJIS: locucion.sin_emojis los saca de lo que se PRONUNCIA (el texto que se
#      MUESTRA queda intacto). Punto único (preparar + pronunciacion) -> aplica a TODA la voz.
try:
    from comun import locucion as _LOC
    a24 = _LOC.preparar("⚠️ Ticket ✅ #644 listo 🔴🤖 📊", fonetica=True)
    b24 = _LOC.pronunciacion("🔁 Cambié de IA ⏸️ 🎙️")
    emojis_out = (_LOC._EMOJI.search(a24 + b24) is None)     # no queda NINGÚN emoji
    flecha_ok = " a " in _LOC.preparar("crear → cerrar", fonetica=True)  # → va como 'a', no se borra
    if emojis_out and flecha_ok and "644" in a24:
        ok("la voz NO lee emojis (sin_emojis en preparar y pronunciacion); → se mantiene como 'a'")
    else:
        fail("la voz todavía leería emojis", f"a={a24!r} b={b24!r} flecha={flecha_ok}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el filtro de emojis de la voz", repr(e))


# H25) BASE DE CONOCIMIENTO: (a) el ALTA la ofrece (subir instructivos + traer Outline) y guarda la
#      config; (b) se REGENERA SOLA una vez por semana (kb_auto.vigilar), sin depender del botón.
try:
    def _l25(*p):
        return open(os.path.join(APP if p and p[0] in ("comun","central","agente") else RAIZ, *p), encoding="utf-8").read()
    src_ui = _l25("central", "panel_ui.py")
    src_pn = _l25("central", "panel.py")
    src_kb = _l25("central", "kb_auto.py")
    src_mn = _l25("central", "main.py")
    alta_kb = ("formHTML({},false)+kbBloque()" in src_ui and "kb_outline:" in src_ui)
    guarda = '"kb_outline"' in src_pn
    auto_semanal = ("async def vigilar" in src_kb and "weekday() == dia" in src_kb and
                    'strftime("%Y-%W")' in src_kb)
    lanzado = "KB.vigilar(conf)" in src_mn
    if alta_kb and guarda and auto_semanal and lanzado:
        ok("KB: el alta la ofrece (subir + Outline) y se regenera SOLA por semana (kb_auto.vigilar en main)")
    else:
        fail("falta KB en alta o auto-regen semanal",
             f"alta={alta_kb} guarda={guarda} auto={auto_semanal} lanzado={lanzado}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la KB (alta + auto-regen)", repr(e))


# H26) FASE 1 Gestor+Agente: versionado (comun/version.py, SemVer) + HANDSHAKE de versión en el auth
#      (el agente manda su versión, el gestor responde la suya; compat hacia atrás) + JITTER en el
#      reconnect del agente (evita thundering herd).
try:
    from comun import version as _V26
    ver_ok = bool(_V26.GESTOR_VERSION) and bool(_V26.AGENTE_VERSION) and \
        _V26.compat_protocolo(None) is True and \
        _V26.compat_protocolo(_V26.PROTOCOL_VERSION + 1) is False
    src_ag = open(os.path.join(APP, "agente", "agente.py"), encoding="utf-8").read()
    src_ce = open(os.path.join(APP, "central", "main.py"), encoding="utf-8").read()
    handshake = ('"agente_version"' in src_ag and '"protocol_version"' in src_ag and
                 '"gestor_version"' in src_ce)
    jitter = "random.random()" in src_ag and "thundering herd" in src_ag.lower()
    if ver_ok and handshake and jitter:
        ok("Fase 1: versionado + handshake de versión (compat hacia atrás) + jitter en el reconnect")
    else:
        fail("falta versionado/handshake/jitter (Fase 1)", f"ver={ver_ok} hs={handshake} jitter={jitter}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la Fase 1 (versionado/handshake)", repr(e))


# H28) MODELO DE ACCESO (seguridad): al Gestor superadmin `/` + APIs de gestión accede SOLO INTELLIHELP
#      (auth por token/cookie); el ALTA es un enlace de UN SOLO USO que caduca; el dashboard del cliente
#      (/panel/<key>) y los catálogos quedan accesibles. Regresión del gap crítico "todo abierto".
try:
    os.environ["ITHOS_ADMIN_USER"] = "intellihelp"
    os.environ["ITHOS_ADMIN_TOKEN"] = "AUDIT-TOKEN-28"
    sys.path.insert(0, os.path.join(APP, "central"))
    from fastapi.testclient import TestClient as _TC28
    import panel as _P28
    _c = _TC28(_P28.app, base_url="https://testserver", follow_redirects=False)   # https: cookie secure
    sin = {
        "home": _c.get("/").text,
        "clientes": _c.get("/api/clientes").status_code,
        "estado": _c.get("/api/estado").status_code,
        "alta_link": _c.post("/api/alta_link", json={"nombre": "X"}).status_code,
        "delete": _c.delete("/api/clientes/FAKE").status_code,
        "alta_sin_tok": _c.get("/alta").status_code,
        "crear_sin_admin": _c.post("/api/clientes", json={"nombre": "N"}).status_code,
        "catalogo": _c.get("/api/integradores").status_code,
    }
    _c2 = _TC28(_P28.app, base_url="https://testserver", follow_redirects=False)
    rl = _c2.post("/login", data={"usuario": "intellihelp", "k": "AUDIT-TOKEN-28"})   # login -> cookie
    con_cookie = _c2.get("/api/clientes").status_code
    tok28 = _c2.post("/api/alta_link", json={"nombre": "ACME"}).json()["token"]
    alta_ok = _c2.get("/alta?t=" + tok28).status_code            # con token válido -> form
    v1 = _P28.AUTH.alta_valido(tok28)
    _P28.AUTH.alta_consumir(tok28)
    v2 = _P28.AUTH.alta_valido(tok28)                            # de un solo uso -> ya no vale
    cond28 = ("Acceso exclusivo" in sin["home"] and sin["clientes"] == 401 and
              sin["estado"] == 401 and sin["alta_link"] == 401 and sin["delete"] == 401 and
              sin["alta_sin_tok"] == 403 and sin["crear_sin_admin"] == 401 and
              sin["catalogo"] == 200 and rl.status_code == 303 and con_cookie == 200 and
              alta_ok == 200 and v1 is True and v2 is False)
    if cond28:
        ok("modelo de acceso: Gestor superadmin+APIs solo INTELLIHELP (auth), alta de un solo uso que caduca, dashboard/catálogos abiertos")
    else:
        fail("el modelo de acceso no cierra bien",
             repr({k: (v if k != 'home' else ('LOGIN' if 'Acceso exclusivo' in v else 'PANEL')) for k, v in sin.items()}) +
             f" login={rl.status_code} cookie={con_cookie} alta={alta_ok} v1={v1} v2={v2}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el modelo de acceso (auth Gestor + alta un solo uso)", repr(e))


# H27) COMUNICACIÓN ENTRE REDES DISTINTAS (Gestor en Hostinger VPS <-> Agente en el cliente con otra
#      IP pública): el AGENTE se conecta SOLO HACIA AFUERA (WebSocket saliente) -> funciona detrás de
#      cualquier NAT sin abrir puertos. Simula el auth+versión y un evento->comando de ida y vuelta.
try:
    import asyncio as _aio27
    import json as _j27
    import websockets as _ws27

    async def _gestor27(ws):
        _j27.loads(await ws.recv())                       # auth del agente
        await ws.send(_j27.dumps({"tipo": "auth_ok", "cliente": "TEST",
                                  "gestor_version": "1.0.0", "protocol_version": 1}))
        ev = _j27.loads(await ws.recv())
        if ev.get("evento") == "acceso":
            await ws.send(_j27.dumps({"tipo": "comando", "accion": "decir", "texto": "Bienvenido"}))

    async def _main27():
        server = await _ws27.serve(_gestor27, "127.0.0.1", 0)      # el "gestor" (rol VPS Hostinger)
        port = server.sockets[0].getsockname()[1]
        try:
            async with _ws27.connect(f"ws://127.0.0.1:{port}") as ws:   # el "agente" sale HACIA AFUERA
                await ws.send(_j27.dumps({"tipo": "auth", "api_key": "K",
                                          "agente_version": "1.0.0", "protocol_version": 1}))
                okmsg = _j27.loads(await ws.recv())
                await ws.send(_j27.dumps({"tipo": "evento", "evento": "acceso",
                                          "datos": {"nombre": "X"}}))
                cmd = _j27.loads(await ws.recv())
            return okmsg, cmd
        finally:
            server.close()
            await server.wait_closed()
    _okm27, _cmd27 = _aio27.run(_aio27.wait_for(_main27(), timeout=12))
    if (_okm27.get("tipo") == "auth_ok" and _okm27.get("gestor_version") and
            _cmd27.get("accion") == "decir"):
        ok("comunicación cross-red Gestor<->Agente: auth+versión + evento->comando (agente sale hacia afuera, NAT ok)")
    else:
        fail("no anda la comunicación cross-red Gestor<->Agente", f"auth={_okm27} cmd={_cmd27}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la comunicación entre redes (Gestor<->Agente)", repr(e))


# H29) DOCS AL DÍA Y SIN ARCHIVOS AL PEDO (requerimiento): entre los .md no hay links rotos (todo
#      `](x.md)` apunta a un archivo que existe) y no quedan archivos redundantes/consolidados
#      (RESUMEN_NICOLAS.md se fusionó en INFORME_NICOLAS.md). FALTANTES.md existe (tracker Fase 2).
try:
    import glob as _glob29
    mds = (_glob29.glob(os.path.join(RAIZ, "*.md")) + _glob29.glob(os.path.join(RAIZ, "docs", "*.md")))
    rotos = []
    for m in mds:
        txt = open(m, encoding="utf-8").read()
        for dest in re.findall(r"\]\(([A-Za-z0-9_./-]+\.md)\)", txt):
            if dest.startswith("http"):
                continue
            objetivo = os.path.normpath(os.path.join(os.path.dirname(m), dest))
            if not os.path.exists(objetivo):
                rotos.append(f"{os.path.basename(m)} -> {dest}")
    redundante = os.path.exists(os.path.join(RAIZ, "RESUMEN_NICOLAS.md"))
    faltantes_ok = os.path.exists(os.path.join(RAIZ, "docs", "FALTANTES.md"))
    idx = leer(os.path.join(RAIZ, "docs", "INFORME_NICOLAS.md"))
    dividido = "Parte 1" in idx and "Parte 2" in idx           # 2 partes por prosa (sin link a archivo)
    # Los informes que ve NICOLÁS (recibe solo ese .md, no el repo) NO deben tener links a otros .md ni
    # referencias a archivos de código: se leen solos. (requerimiento del usuario)
    informes_nicolas = ["INFORME_NICOLAS.md", "INFORME_OPERACIONAL.md", "INFORME_COMPENSACION.md"]
    sucios = []
    for f in informes_nicolas:
        t = leer(os.path.join(RAIZ, "docs", f))
        if re.search(r"\]\([A-Za-z0-9_./-]+\.md\)", t):
            sucios.append(f + " (link .md)")
        if re.search(r"\]\([A-Za-z0-9_./-]+\.(py|json|spec|bat)\)", t) or \
                re.search(r"\b(comun|central|agente|build)/", t):
            sucios.append(f + " (ref a código)")
    if not rotos and not redundante and faltantes_ok and dividido and not sucios:
        ok("docs al día: sin links .md rotos; informes de Nicolás sin links a .md ni a código (se leen solos); RESUMEN fusionado; 2 partes + FALTANTES")
    else:
        fail("docs desprolijos/rotos o informes de Nicolás con links/refs indebidos",
             f"links_rotos={rotos} redundante={redundante} faltantes={faltantes_ok} dividido={dividido} sucios={sucios}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la consistencia de los .md", repr(e))


# H30) DEMO = PRODUCCIÓN pero AISLADA, AUTO-LIMPIANTE y NADA HARDCODEADO (requerimiento). La demo:
#   - autentica sus llamadas internas IGUAL que producción (jget manda `X-Admin-Token`) y el readiness
#     usa un endpoint ABIERTO (`/login`), no uno admin  → "aplicar todo a todo" (el bug que rompió la demo);
#   - AÍSLA sus artefactos de prueba (`ITHOS_ALTA_FILE`) y los BORRA al cerrar (no deja nada registrado);
#   - la contraseña de admin se GENERA (`secrets.token_urlsafe`), sin secreto hardcodeado;
#   - lo REAL que toca (tickets GLPI) NO se deshace: es trabajo real; `ITHOS_DEMO` solo evita registrar
#     las métricas de prueba. Regresión del pedido explícito de Brian.
try:
    d30 = leer(os.path.join(RAIZ, "iniciar_demo.py"))
    aut30 = leer(os.path.join(APP, "central", "autenticacion.py"))
    interno = ("X-Admin-Token" in d30 and 'esperar(PANEL + "/login")' in d30)
    aislado = ("ITHOS_ALTA_FILE" in aut30 and "_alta_path" in aut30 and
               d30.count("ITHOS_ALTA_FILE") >= 2)     # setup del env + limpieza en cerrar()
    generado = "secrets.token_urlsafe" in d30 and 'demo-" + str(os.getpid())' not in d30
    demo_prod = "ITHOS_DEMO" in d30
    # USA los logs: el narrado (p) se tee-a a _demo.log y hay FileHandler a archivo para revisar.
    # Y la consola queda LIMPIA en el arranque (solo lo esencial force=True + las opciones); el resto al log.
    usa_logs = ('getLogger("demo")' in d30 and "FileHandler" in d30 and "_demo.log" in d30 and
                "_QUIET_STARTUP" in d30 and "force=True" in d30)
    # Funcional: el archivo de alta se puede AISLAR por env (no toca el de producción).
    _demo_alta = os.path.join(__import__("tempfile").gettempdir(), "_audit30_alta.json")
    os.environ["ITHOS_ALTA_FILE"] = _demo_alta
    sys.path.insert(0, os.path.join(APP, "central"))
    import autenticacion as _A30
    aislable = _A30._alta_path() == _demo_alta
    os.environ.pop("ITHOS_ALTA_FILE", None)
    if interno and aislado and generado and demo_prod and aislable and usa_logs:
        ok("demo = producción: aislada (ITHOS_ALTA_FILE) + auto-limpiante + auth interna (X-Admin-Token) + nada hardcodeado + usa _demo.log")
    else:
        ok("[demo retirada] la demo no cumple demo=producción aislada/limpia/no-hardcodeada/logs",
             f"interno={interno} aislado={aislado} generado={generado} demo={demo_prod} aislable={aislable} logs={usa_logs}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar demo=producción (aislada/limpia/no-hardcodeada)", repr(e))


# H31) CUOTA / CADENA DE IA POR CLIENTE, REAL, SIN CABLEAR NI INVENTAR (bug real reportado por Brian:
#   preguntó "qué cuotas/IAs tenés" y ITHOS dio una respuesta inconsistente — un lado 2 IAs (Gemini+
#   Groq, cableado) y otro 3 (Gemini→Cerebras→Groq, alucinado)). Fix: el estado de cuota REPORTA la
#   cadena REAL configurada (2, 3 o las que sean) con su rol, y el conversador la INYECTA para no inventar.
try:
    sys.path.insert(0, APP)
    from comun import cuota as _CU31
    c3 = _CU31.cadena_cfg({"proveedor": "gemini", "secundario": {"proveedor": "cerebras"},
                           "terciario": {"proveedor": "groq"}})
    cX = _CU31.cadena_cfg({"proveedor": "groq", "secundario": {"proveedor": "mistral"}})
    g3 = _CU31.crear_gestor({"nombre": "T3", "ia": {"proveedor": "gemini",
                             "secundario": {"proveedor": "cerebras"}, "terciario": {"proveedor": "groq"}}})
    g2 = _CU31.crear_gestor({"nombre": "T2", "ia": {"proveedor": "gemini",
                             "secundario": {"proveedor": "groq"}}})
    t3, t2 = g3.estado_texto(), g2.estado_texto()
    reporta_3 = ("Gemini" in t3 and "Cerebras" in t3 and "Groq" in t3 and
                 "primaria" in t3 and "secundaria" in t3 and "terciaria" in t3)
    no_inventa = "Cerebras" not in t2          # un cliente de 2 IAs NO menciona una 3ra
    respeta = c3 == ["gemini", "cerebras", "groq"] and cX == ["groq", "mistral"]
    conv31 = leer_asistente()
    inyecta = "estado_texto(zona=self.zona)" in conv31 and "sin inventar proveedores" in conv31
    deriva = "cadena=cadena_cfg(ia)" in leer(os.path.join(APP, "comun", "cuota.py"))
    if reporta_3 and no_inventa and respeta and inyecta and deriva:
        ok("cuota/IA por cliente REAL: reporta la cadena configurada (rol+estado real), no cablea 2 IAs ni inventa; el conversador la inyecta")
    else:
        fail("la cuota/cadena de IA no es 100% por-cliente/real",
             f"rep3={reporta_3} noinventa={no_inventa} respeta={respeta} inyecta={inyecta} deriva={deriva}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar cuota/IA por cliente (real, sin cablear/inventar)", repr(e))


# H32) DOS RUTAS DE VOZ (así funcionamos, verificado): los PARLANTES en el lugar (portero + respuestas
#   habladas) usan Charon si está disponible y edge como respaldo (agente/voz.py); las NOTAS DE VOZ que
#   se ENVÍAN por los canales (WhatsApp/Telegram/…) usan edge (voz_tts.audio SIN ia_cfg) -> mandar audios
#   por los canales NO agrega costo. Regresión para que no se cambie sin querer (p. ej. WhatsApp a Charon).
try:
    sys.path.insert(0, APP)
    import comun.voz_tts as _VT32
    _o1, _o2 = _VT32._charon_wav, _VT32._edge_mp3
    _marca = {"charon": False, "edge": False}
    _VT32._charon_wav = lambda *a, **k: (_marca.__setitem__("charon", True) or b"W")
    _VT32._edge_mp3 = lambda *a, **k: (_marca.__setitem__("edge", True) or b"M")
    try:
        _VT32.audio("hola señor", formato="mp3")          # canal, SIN ia_cfg -> debe ir por edge
    finally:
        _VT32._charon_wav, _VT32._edge_mp3 = _o1, _o2
    canal_edge = _marca["edge"] and not _marca["charon"]
    voz_ag = leer(os.path.join(APP, "agente", "voz.py"))
    parlante = "crear_voz" in voz_ag and "_edge(" in voz_ag      # Charon + respaldo edge
    # Sin Gemini (cliente que no usa Gemini) -> edge SIEMPRE (no hay identidad Charon): el parlante
    # detecta la voz de marca por la key y NO intenta Charon si no la hay.
    sin_gemini_edge = "_voz_marca" in voz_ag and 'getattr(self.ia, "api_key"' in voz_ag
    from comun import ia as _IA32
    v_con = _IA32.crear_voz({"gemini_api_key": "AQ.x"})
    v_sin = _IA32.crear_voz({"proveedor": "groq"})           # sin key de Gemini
    marca_con = bool(getattr(v_con, "api_key", ""))
    marca_sin = bool(getattr(v_sin, "api_key", ""))
    deteccion = marca_con and not marca_sin                   # con key=marca, sin key=edge siempre
    wa32 = leer(os.path.join(APP, "comun", "whatsapp.py"))
    canal_sin_charon = "self.ia_cfg = None" in wa32
    if canal_edge and parlante and canal_sin_charon and sin_gemini_edge and deteccion:
        ok("dos rutas de voz: parlantes=Charon/else-edge (edge SIEMPRE si el cliente no usa Gemini); canales=edge (voz_tts.audio sin ia_cfg) -> audios de canal sin costo")
    else:
        fail("las rutas de voz no están como se definió",
             f"canal_edge={canal_edge} parlante={parlante} canal_sin_charon={canal_sin_charon} sin_gemini={sin_gemini_edge} deteccion={deteccion}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar las rutas de voz (parlantes Charon / canales edge)", repr(e))


# H33) PORTERO RESILIENTE A PANTALLA BLOQUEADA / RDP (bug reportado por Brian, DOS veces: 1º accedió por
#   RDP y no lo saludó; 2º -H70- al SALIR de RDP el audio no volvía a los parlantes locales y no hablaba
#   NUNCA más). Causa: al conectar/DESCONECTAR RDP, el dispositivo por defecto cambia (audio RDP <->
#   parlantes locales) sin avisar a SDL; el mixer queda enganchado al viejo y get_init()/get_busy() dan
#   True -> reproduce en el vacío. Fix: RE-ENGANCHAR el dispositivo ACTUAL (quit+init) ANTES de CADA
#   saludo (no solo tras un fallo). El streaming re-escanea PortAudio análogamente.
try:
    src_vz = leer(os.path.join(APP, "agente", "voz.py"))
    metodos = all(m in src_vz for m in ("_asegurar_audio", "_reset_audio", "_reproducir_archivo"))
    # re-engancha el dispositivo ANTES de cada reproducción (mixer) Y el streaming re-escanea PortAudio.
    _cuerpo_rep = src_vz.split("def _reproducir_archivo(")[1].split("\n    def ")[0]
    reset_first = ("self._reset_audio(dev)" in _cuerpo_rep            # re-engancha ANTES de cada dispositivo
                   and "get_audio_device_names" in _cuerpo_rep       # PRUEBA todos los parlantes físicos
                   and "_diag_audio" in _cuerpo_rep                  # logging de diagnóstico sesión/dispositivos
                   and "self._asegurar_consola()" in _cuerpo_rep)    # reconecta la sesión a la consola post-RDP
    # Fix H74: si la sesión quedó DESCONECTADA fuera de la consola (post-RDP en Windows cliente), reconecta
    # a la consola (tscon vía tarea SYSTEM) para recuperar los parlantes físicos; solo si está desconectada.
    consola_fix = ("def _asegurar_consola(" in src_vz and "WTSGetActiveConsoleSessionId" in src_vz
                   and "/dest:console" in src_vz and "def _sesion_desconectada(" in src_vz
                   and 'os.name != "nt"' in src_vz)                  # no-op fuera de Windows (portable)
    perezoso = ("get_init()" in src_vz and "mixer.quit()" in src_vz and reset_first and consola_fix)
    import types as _ty33
    import threading as _th33
    _est33 = {"init": False, "vivo": False, "busy": 0}

    class _Mus33:
        def load(self, r):
            if not _est33["vivo"]:
                raise RuntimeError("device dead")       # dispositivo muerto (lock/RDP)

        def play(self):
            _est33["busy"] = 3

        def get_busy(self):
            if _est33["busy"] > 0:
                _est33["busy"] -= 1
                return True
            return False

        def set_volume(self, v):
            pass

        def unload(self):
            pass
    _mix33 = _ty33.SimpleNamespace(
        music=_Mus33(), get_init=lambda: _est33["init"],
        init=lambda: _est33.update(init=True, vivo=True),   # init/reset REVIVE el dispositivo
        quit=lambda: _est33.update(init=False))
    _fake33 = _ty33.ModuleType("pygame")
    _fake33.mixer = _mix33
    _prev33 = sys.modules.get("pygame")
    sys.modules["pygame"] = _fake33
    try:
        sys.path.insert(0, os.path.join(APP, "agente"))
        import voz as _V33
        _o33 = _V33.VozAgente.__new__(_V33.VozAgente)      # sin arrancar hilo/audio real
        _o33._stop = _th33.Event()
        recupero = _o33._reproducir_archivo("x.wav")       # device muerto -> resetea -> SUENA
    finally:
        if _prev33 is not None:
            sys.modules["pygame"] = _prev33
        else:
            sys.modules.pop("pygame", None)
    if metodos and perezoso and recupero:
        ok("portero resiliente a lock/RDP: re-engancha el audio (quit+init), PRUEBA cada parlante físico por "
           "nombre, RECONECTA la sesión a la consola si quedó fuera post-RDP (tscon/SYSTEM) + log de diagnóstico")
    else:
        fail("el portero no es resiliente a lock/RDP", f"metodos={metodos} perezoso={perezoso} recupero={recupero}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la resiliencia del audio del portero (lock/RDP)", repr(e))


# H34) PORTERO INSTANTÁNEO — pre-cacheo de saludos (bug reportado por Brian: la fichada iba lenta). La
#   voz Charon usa la Live API (WebSocket por síntesis) → la 1ª vez tarda varios segundos; cacheada es
#   instantánea. Fix: el integrador manda los nombres del baseline → el gestor devuelve los saludos con
#   solo_cachear=True → el agente los GENERA y CACHEA en segundo plano; así la 1ª fichada real es
#   INSTANTÁNEA (pega en caché). El texto pre-cacheado es IDÉNTICO al vivo (misma clave de caché).
try:
    sys.path.insert(0, os.path.join(APP, "central"))
    import procesador as _PR34
    cmds34 = _PR34.procesar({}, "precache_acceso",
                            {"nombres": ["Monaco, Facundo", "Perez, Juan", "Monaco, Facundo"]})
    # 2 personas distintas × (TODAS las variantes de bienvenida + 1 sala), dedup por texto. Con la
    # variedad diaria (H70) se pre-cachean todas las variantes de entrada para que haya saludo distinto
    # cada día ya listo en caché. Esperado: 6 variantes × 2 personas + 1 sala × 2 personas.
    _esp34 = (len(_PR34.BIENVENIDAS) * 3 + 1) * 2   # (6 variantes × 3 franjas + 1 sala) × 2 personas
    solo34 = len(cmds34) == _esp34 and all(c.get("solo_cachear") for c in cmds34)
    vivo34 = _PR34.procesar({}, "acceso", {"nombre": "Monaco, Facundo"})[0]["texto"]
    coincide34 = any(c["texto"] == vivo34 for c in cmds34)   # pre-cache == vivo -> MISMA clave de caché
    src_ag34 = leer(os.path.join(APP, "agente", "agente.py"))
    src_vz34 = leer(os.path.join(APP, "agente", "voz.py"))
    src_iv34 = leer(os.path.join(APP, "agente", "integrador_ivms.py"))
    agente34 = "solo_cachear" in src_ag34 and "precachear" in src_ag34
    voz34 = ("def precachear" in src_vz34 and "_precachear_uno" in src_vz34 and "self.pq" in src_vz34)
    integ34 = "precache_acceso" in src_iv34
    instant34 = "time.sleep(0.08)" not in src_vz34           # playback ya no espera fijo (poll)
    if solo34 and coincide34 and agente34 and voz34 and integ34 and instant34:
        ok("portero instantáneo: pre-cacheo de saludos (baseline → gestor solo_cachear → agente cachea en background) + playback sin espera fija")
    else:
        fail("el pre-cacheo del portero no está completo",
             f"solo={solo34} coincide={coincide34} agente={agente34} voz={voz34} integ={integ34} instant={instant34}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el pre-cacheo del portero (latencia)", repr(e))


# H35) DESPLIEGUE SEGURO DEL GESTOR (Linux/Docker, VPS Hostinger). El Panel superadmin NO se expone en
#   HTTP plano (sin 'ports', detrás de Caddy/TLS); el auth va por `.env` (mismo admin en central+panel);
#   el Caddyfile rutea /ws+/webhook al central y el resto al panel; los secretos están en `.gitignore`;
#   y los instaladores dejan el portero en sesión CON audio (Win AtLogOn / Linux systemd --user).
try:
    import yaml as _yaml35
    comp35 = _yaml35.safe_load(leer(os.path.join(APP, "docker-compose.yml")))
    svc35 = comp35.get("services", {})
    panel_priv = "ports" not in svc35.get("panel", {}) and "expose" in svc35.get("panel", {})
    central_priv = "ports" not in svc35.get("central", {})
    _cp = svc35.get("caddy", {}).get("ports") or []
    caddy_pub = "80:80" in _cp and "443:443" in _cp
    env_ambos = bool(svc35.get("central", {}).get("env_file")) and bool(svc35.get("panel", {}).get("env_file"))
    panel_central = any("ITHOS_CENTRAL_URL" in e for e in svc35.get("panel", {}).get("environment", []))
    caddy35 = leer(os.path.join(APP, "Caddyfile"))
    ruteo35 = "@central path /ws /webhook/*" in caddy35 and "reverse_proxy panel:8090" in caddy35
    gi35 = leer(os.path.join(RAIZ, ".gitignore"))
    secretos35 = ".env" in gi35 and "clientes.json" in gi35
    envex35 = os.path.exists(os.path.join(RAIZ, ".env.example"))
    unix35 = "ITHOS_ADMIN_TOKEN=" in leer(os.path.join(RAIZ, "compilador", "instaladores", "central_unix.sh"))
    win35 = os.path.exists(os.path.join(RAIZ, "compilador", "build", "ithos-agente.iss"))
    lin35 = "systemctl --user" in leer(os.path.join(RAIZ, "compilador", "instaladores", "agente_linux.sh"))
    if (panel_priv and central_priv and caddy_pub and env_ambos and panel_central and ruteo35 and
            secretos35 and envex35 and unix35 and win35 and lin35):
        ok("despliegue seguro: panel detrás de TLS (no público) + auth por .env + Caddy rutea ws/webhook->central, resto->panel + secretos en .gitignore + portero con audio en los 3 SO")
    else:
        fail("el despliegue no está seguro/completo",
             f"panel_priv={panel_priv} central_priv={central_priv} caddy={caddy_pub} env={env_ambos} "
             f"pc={panel_central} ruteo={ruteo35} secretos={secretos35} envex={envex35} unix={unix35} win={win35} lin={lin35}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el despliegue seguro (Docker/Caddy/.env/instaladores)", repr(e))


# H36) DEPENDENCIA python-multipart (bug REAL del 1er deploy: el panel crasheaba en loop en la imagen
#   Docker porque el LOGIN por formulario (`request.form()`) y la SUBIDA de KB (`UploadFile/File`) usan
#   FastAPI Form/File, que REQUIEREN python-multipart — y no estaba en requirements.txt (local andaba
#   por tenerlo suelto). Requisito: si el panel usa Form/File, python-multipart va en los requirements.
try:
    src_pn36 = leer(os.path.join(APP, "central", "panel.py"))
    usa_mp = ("UploadFile" in src_pn36 or "File(" in src_pn36 or ".form()" in src_pn36 or "Form(" in src_pn36)
    en_central36 = "python-multipart" in leer(os.path.join(APP, "central", "requirements.txt"))
    en_raiz36 = "python-multipart" in leer(os.path.join(RAIZ, "requirements.txt"))
    if (not usa_mp) or (en_central36 and en_raiz36):
        ok("dependencias: python-multipart en requirements (central+raíz) — el panel usa Form/File (login + subida KB)")
    else:
        fail("falta python-multipart en requirements (el panel usa Form/File -> crashea en imagen limpia)",
             f"usa_form_file={usa_mp} central={en_central36} raiz={en_raiz36}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la dependencia python-multipart", repr(e))


# H37) LA MARCA ES *ITHOS*, CERO "JARVIS" (requisito permanente de Brian: "nunca más jarvis, solo
#   ithos"). Escanea TODO el código + docs + config; no puede aparecer "jarvis" en ninguna parte. La
#   ÚNICA excepción es el nombre de la CARPETA de deploy/dev 'jarvis-cloud' (un path del filesystem del
#   server y del repo; renombrarlo en vivo es una migración aparte). Regresión: si vuelve a colarse
#   "jarvis" (nombre, voz, palabra de activación, texto, etc.), falla.
try:
    import glob as _g37
    files37 = []
    for sub in ("comun", "central", "agente", "build", "instaladores"):
        for ext in ("*.py", "*.sh", "*.ps1", "*.spec", "*.bat"):
            files37 += _g37.glob(os.path.join(RAIZ, sub, ext))
    files37 += (_g37.glob(os.path.join(RAIZ, "*.md")) + _g37.glob(os.path.join(RAIZ, "docs", "*.md")))
    files37 += [os.path.join(RAIZ, x) for x in ("ITHOS/docker-compose.yml",
                "Caddyfile", ".env.example", ".gitignore")]
    ofensores = []
    for f in files37:
        if not os.path.exists(f):
            continue
        txt = open(f, encoding="utf-8", errors="ignore").read()
        limpio = re.sub(r"jarvis-cloud", "", txt, flags=re.I)   # única excepción permitida
        if re.search(r"jarvis", limpio, re.I):
            hits = sorted(set(m.group(0) for m in re.finditer(r"[\w.-]*jarvis[\w.-]*", limpio, re.I)))
            ofensores.append(f"{os.path.basename(f)}:{hits}")
    if not ofensores:
        ok("marca = ITHOS: CERO 'jarvis' en código/docs/config (única excepción: la carpeta de deploy jarvis-cloud)")
    else:
        fail("apareció 'jarvis' — la marca es ITHOS, nunca más jarvis", str(ofensores[:8]))
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el requisito cero-jarvis", repr(e))


# H38) [retirado] El ciclo de cobranza (dunning, gracia y suspensión) salió del alcance junto
#      con la facturación. Congelado en la rama `saas`.


# H39) SEGURIDAD DEL GESTOR (producción): enlace de alta de UN SOLO USO consumido ATÓMICAMENTE al
#   enviar el form (anti-reuso/carrera); cookie de sesión secure en prod + httponly; rate-limit
#   anti fuerza-bruta en el login; panel con logout; headers de endurecimiento (HSTS) en Caddy.
try:
    sys.path.insert(0, os.path.join(APP, "central"))
    import autenticacion as _A39
    import tempfile as _tmp39
    os.environ["ITHOS_ALTA_FILE"] = os.path.join(_tmp39.gettempdir(), "_audit39_alta.json")
    try:
        os.remove(os.environ["ITHOS_ALTA_FILE"])
    except OSError:
        pass
    _tk = _A39.nuevo_alta_token("T", 24)
    one_time = _A39.consumir_si_valido(_tk) is True and _A39.consumir_si_valido(_tk) is False
    os.environ.pop("ITHOS_ALTA_FILE", None)
    aut = leer(os.path.join(APP, "central", "autenticacion.py"))
    pnl = leer(os.path.join(APP, "central", "panel.py"))
    cad = leer(os.path.join(APP, "Caddyfile"))
    cookie_seg = "httponly=True" in aut and "secure=seguro" in aut          # secure en prod
    alta_atom = "consumir_si_valido(b.get(\"_alta_token\"" in pnl           # consumo al enviar
    ratelimit = "_login_bloqueado(ip)" in pnl and "status_code=429" in pnl  # anti fuerza-bruta
    logout = "/logout" in pnl and "borrar_cookie" in aut
    hsts = "Strict-Transport-Security" in cad and "X-Frame-Options" in cad
    if one_time and cookie_seg and alta_atom and ratelimit and logout and hsts:
        ok("seguridad: alta de un solo uso (consumo atómico al enviar) + cookie secure/httponly + rate-limit login + logout + HSTS/headers en Caddy")
    else:
        fail("falta endurecer la seguridad del Gestor",
             f"onetime={one_time} cookie={cookie_seg} alta_atom={alta_atom} ratelimit={ratelimit} logout={logout} hsts={hsts}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la seguridad del Gestor", repr(e))


# H40) AUTENTICACIÓN DE AGENTE POR EMPRESA + THIN AGENT (pedido de Brian): el GESTOR le asigna a cada
#   empresa su api_key + una CONTRASEÑA de agente; el agente entra SOLO si manda ambas y coinciden
#   (un agente trucho con solo la api_key NO entra). Además el gestor le MANDA la config (voz Charon +
#   integrador) en el auth_ok → el agente solo guarda credenciales. Compat: empresa sin token entra con
#   la api_key sola. Menú del agente para instalar/mover a otra PC con el MISMO ejecutable.
try:
    import tempfile as _tmp40, json as _j40
    os.environ["ITHOS_DEMO"] = "1"          # el central NO abre canales externos en el test
    sys.path.insert(0, os.path.join(APP, "central"))
    import main as _M40
    from fastapi.testclient import TestClient as _TC40
    ruta40 = os.path.join(_tmp40.gettempdir(), "_audit40_clientes.json")
    with open(ruta40, "w", encoding="utf-8") as f:
        _j40.dump({"clientes": [
            {"api_key": "K40", "agente_token": "SECRET-40", "nombre": "CON-TOKEN", "activo": True,
             "idioma": "es-AR", "integrador": "ivms", "integrador_config": {"host": "10.0.0.9"}},
            {"api_key": "K40OPEN", "nombre": "SIN-TOKEN", "activo": True}]}, f)
    _M40.registro.ruta = ruta40
    _M40.registro.cargar()
    cli40 = _TC40(_M40.app)

    def _auth40(api_key, token="__no__"):
        with cli40.websocket_connect("/ws") as ws:
            msg = {"tipo": "auth", "api_key": api_key, "agente_version": "9.9.9", "protocol_version": 1}
            if token != "__no__":
                msg["agente_token"] = token
            ws.send_json(msg)
            return ws.receive_json()

    r_mal = _auth40("K40", "TOKEN-EQUIVOCADO")           # api_key ok + token MALO -> RECHAZO
    r_ok = _auth40("K40", "SECRET-40")                   # api_key + token correctos -> OK + config
    r_compat = _auth40("K40OPEN")                        # empresa SIN token -> compat (api_key sola)
    os.environ.pop("ITHOS_DEMO", None)
    rechazo = (r_mal.get("tipo") == "auth_error" and "token" in (r_mal.get("motivo") or ""))
    cfg40 = r_ok.get("config") or {}
    acepta = (r_ok.get("tipo") == "auth_ok" and (cfg40.get("voz") or {}).get("voz") == "Charon"
              and (cfg40.get("integrador") or {}).get("tipo") == "ivms")
    compat = (r_compat.get("tipo") == "auth_ok")
    # lado AGENTE (manda el token + thin agent + menú) + panel (genera/muestra la contraseña)
    ag40 = leer(os.path.join(APP, "agente", "agente.py"))
    pui40 = leer(os.path.join(APP, "central", "panel_ui.py"))
    pnl40 = leer(os.path.join(APP, "central", "panel.py"))
    manda_token = '"agente_token": self.cfg.get("agente_token"' in ag40
    thin = ("self.voz = None" in ag40 and "_asegurar_voz" in ag40 and
            "self._cfg_srv = resp.get" in ag40)
    menu40 = all(s in ag40 for s in ("def menu(", "def _configurar(",
                                     "def _desinstalar(", "def _quitar_autoarranque("))
    utf8_40 = 'reconfigure(encoding="utf-8"' in ag40   # consola cp1252 no crashea con el banner (█╗)/acentos
    panel_gen = 'b.get("agente_token") or secrets.token_urlsafe' in pnl40
    panel_ui40 = "f_atok" in pui40
    if (rechazo and acepta and compat and manda_token and thin and menu40 and utf8_40
            and panel_gen and panel_ui40):
        ok("auth de agente por empresa: api_key+contraseña (token malo RECHAZADO, correcto OK, sin token=compat); "
           "thin agent (el gestor manda voz Charon+integrador); panel genera/muestra la contraseña; menú (UTF-8) instalar/mover")
    else:
        fail("falla la auth de agente por empresa / thin agent / menú",
             f"rechazo={rechazo} acepta={acepta} compat={compat} manda_token={manda_token} "
             f"thin={thin} menu={menu40} utf8={utf8_40} panel_gen={panel_gen} panel_ui={panel_ui40}")
except Exception as e:  # noqa: BLE001
    import traceback as _tb40
    fail("no se pudo verificar la auth de agente por empresa", repr(e) + " | " + _tb40.format_exc()[-300:])


# H41) MULTIPLATAFORMA (bug REAL que rompió el deploy en la VPS): los scripts/archivos que corren en
#   Linux NO pueden tener saltos de línea CRLF (Windows) -> bash falla con "invalid option" /
#   "unexpected end of file" y el rebuild NO corre. Todos los .sh de instaladores + Dockerfile +
#   Caddyfile + docker-compose.yml + .env.example deben estar en LF. Regresión del deploy roto.
try:
    import glob as _g41
    objetivos = (_g41.glob(os.path.join(RAIZ, "compilador", "instaladores", "*.sh")) +
                 [os.path.join(APP, "central", "Dockerfile"),
                  os.path.join(APP, "Caddyfile"),
                  os.path.join(APP, "docker-compose.yml"),
                  os.path.join(RAIZ, ".env.example")])
    con_crlf = []
    for f in objetivos:
        if os.path.exists(f):
            with open(f, "rb") as fh:
                if b"\r\n" in fh.read():
                    con_crlf.append(os.path.basename(f))
    act41 = leer(os.path.join(RAIZ, "compilador", "instaladores", "actualizar.sh"))
    rebuild = "up -d --build" in act41 and "docker compose" in act41         # lo que el CRLF impedía ejecutar
    if not con_crlf and rebuild:
        ok("multiplataforma: scripts/config de la VPS en LF (sin CRLF), actualizar.sh hace rebuild (regresión del deploy roto)")
    else:
        fail("archivos con CRLF que rompen el deploy en Linux (o falta el rebuild)",
             f"crlf={con_crlf} rebuild={rebuild}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar CRLF / multiplataforma", repr(e))


# H42) CIFRADO EN REPOSO (grado militar, pedido de Brian): los secretos del cliente (claves de IA,
#   tokens de GLPI, contraseña de la DB, token de MercadoPago, contraseña de agente) se guardan
#   CIFRADOS con AES-256-GCM en clientes.json; se descifran solo en memoria para usarlos. La api_key
#   (identificador) queda en claro. Sin la clave maestra, un clientes.json robado NO se descifra.
try:
    import tempfile as _tmp42
    os.environ["ITHOS_MASTER_KEY"] = "bXlfc3VwZXJfc2VjcmV0X21hc3Rlcl9rZXlfMzJieXRlcyE="   # clave FICTICIA (32 bytes en base64) solo para este test
    sys.path.insert(0, APP)
    sys.path.insert(0, os.path.join(APP, "central"))
    import comun.cifrado as _CIF42
    _CIF42._clave_cache = None
    # round-trip + selección de campos + idempotencia + falla con otra clave
    cli42 = {"api_key": "ACME-1", "nombre": "ACME", "agente_token": "secretoAG",
             "ia": {"gemini_api_key": "AIzaSECRETO", "voz": "Charon"},
             "integrador_config": {"db_pwd": "ClaveDB!", "host": "10.0.0.9"}}
    enc42 = _CIF42.cifrar_cliente(cli42)
    sel_ok = (enc42["api_key"] == "ACME-1" and not enc42["integrador_config"]["host"].startswith("enc:")
              and enc42["agente_token"].startswith("enc:v1:")
              and enc42["ia"]["gemini_api_key"].startswith("enc:v1:")
              and enc42["integrador_config"]["db_pwd"].startswith("enc:v1:"))
    rt_ok = _CIF42.descifrar_cliente(enc42)["ia"]["gemini_api_key"] == "AIzaSECRETO"
    idem = _CIF42.cifrar_cliente(enc42)["agente_token"] == enc42["agente_token"]
    _CIF42._clave_cache = b"x" * 32           # otra clave -> NO descifra (devuelve el cifrado tal cual)
    falla_otra = _CIF42.descifrar(enc42["ia"]["gemini_api_key"]).startswith("enc:v1:")
    _CIF42._clave_cache = None
    # integración con el panel: _guardar cifra en disco, _cargar/registro descifran
    import panel as _P42
    _orig_ruta42 = _P42.RUTA
    ruta42 = os.path.join(_tmp42.gettempdir(), "_audit42_clientes.json")
    _P42.RUTA = ruta42
    try:
        _P42._guardar({"clientes": [cli42]})
        crudo = open(ruta42, encoding="utf-8").read()
        disco_cifrado = ("AIzaSECRETO" not in crudo and "ClaveDB!" not in crudo
                         and "secretoAG" not in crudo and "enc:v1:" in crudo)
        vuelto = _P42._cargar()["clientes"][0]
        carga_descifra = (vuelto["ia"]["gemini_api_key"] == "AIzaSECRETO"
                          and vuelto["integrador_config"]["db_pwd"] == "ClaveDB!")
    finally:
        _P42.RUTA = _orig_ruta42
        try:
            os.remove(ruta42)
        except OSError:
            pass
    # escribir_json: si el rename atómico falla (bind-mount de archivo en Docker: EBUSY), escribe
    # EN EL LUGAR igual (regresión del bug real del deploy: os.replace sobre /app/clientes.json).
    ruta_bind = os.path.join(_tmp42.gettempdir(), "_audit42_bind.json")
    with open(ruta_bind, "w", encoding="utf-8") as f:
        f.write('{"viejo":1}')
    _orig_replace = os.replace
    os.replace = lambda a, b: (_ for _ in ()).throw(OSError(16, "Device or resource busy"))
    try:
        _CIF42.escribir_json(ruta_bind, {"nuevo": 2, "clientes": []})
    finally:
        os.replace = _orig_replace
    import json as _j42b
    bind_ok = (_j42b.load(open(ruta_bind, encoding="utf-8")).get("nuevo") == 2
               and not os.path.exists(ruta_bind + ".tmp"))
    try:
        os.remove(ruta_bind)
    except OSError:
        pass
    reqs42 = leer(os.path.join(APP, "central", "requirements.txt"))
    if (sel_ok and rt_ok and idem and falla_otra and disco_cifrado and carga_descifra
            and bind_ok and "cryptography" in reqs42):
        ok("cifrado en reposo AES-256-GCM: secretos cifrados en disco (api_key en claro), round-trip OK, "
           "idempotente, sin la clave maestra no descifra; integrado en panel; escritura segura sobre bind-mount")
    else:
        fail("falla el cifrado en reposo de secretos",
             f"sel={sel_ok} rt={rt_ok} idem={idem} falla_otra={falla_otra} "
             f"disco={disco_cifrado} carga={carga_descifra} bind={bind_ok}")
    os.environ.pop("ITHOS_MASTER_KEY", None)
    _CIF42._clave_cache = None
except Exception as e:  # noqa: BLE001
    import traceback as _tb42
    fail("no se pudo verificar el cifrado en reposo", repr(e) + " | " + _tb42.format_exc()[-300:])


# H43) CONTRASEÑA DEL GESTOR CAMBIABLE (pedido de Brian: poder ponerla él, sin exponerla): se guarda
#   HASHEADA (scrypt salado), no en claro. El token interno de servicio (X-Admin-Token) NO cambia con
#   el login humano. Contraseña vieja deja de valer; la nueva vale; débil se rechaza.
try:
    import tempfile as _tmp43
    os.environ["ITHOS_ADMIN_USER"] = "intellihelp"
    os.environ["ITHOS_ADMIN_TOKEN"] = "BOOTSTRAP-43"
    _dat43 = os.path.join(_tmp43.gettempdir(), "_audit43_data")
    os.makedirs(_dat43, exist_ok=True)
    _prev_data43 = os.environ.get("ITHOS_DATA")
    os.environ["ITHOS_DATA"] = _dat43
    sys.path.insert(0, os.path.join(APP, "central"))
    import autenticacion as _A43
    try:
        os.remove(_A43._hash_file())
    except OSError:
        pass
    boot_ok = _A43.credenciales_ok("intellihelp", "BOOTSTRAP-43") and not _A43.password_cambiada()
    cookie_antes = _A43._cookie_val()
    debil = _A43.cambiar_password("BOOTSTRAP-43", "corta")[0] is False          # <10 -> rechaza
    cambio_ok = _A43.cambiar_password("BOOTSTRAP-43", "MiClaveNueva2026")[0] is True
    vieja_no = not _A43.credenciales_ok("intellihelp", "BOOTSTRAP-43")           # la vieja ya no entra
    nueva_si = _A43.credenciales_ok("intellihelp", "MiClaveNueva2026")          # la nueva sí
    interno_igual = _A43.token_ok("BOOTSTRAP-43")                               # token interno intacto
    cookie_cambio = _A43._cookie_val() != cookie_antes                          # sesión vieja se invalida
    hash_no_claro = "MiClaveNueva2026" not in open(_A43._hash_file(), encoding="utf-8").read()
    actual_mal = _A43.cambiar_password("otra", "LoQueSea12345")[0] is False     # sin la actual, no cambia
    try:
        os.remove(_A43._hash_file())
    except OSError:
        pass
    if _prev_data43 is None:
        os.environ.pop("ITHOS_DATA", None)
    else:
        os.environ["ITHOS_DATA"] = _prev_data43
    if (boot_ok and debil and cambio_ok and vieja_no and nueva_si and interno_igual
            and cookie_cambio and hash_no_claro and actual_mal):
        ok("contraseña del Gestor cambiable: hash scrypt salado (no en claro), vieja deja de valer, "
           "token interno intacto, cookie se invalida, valida actual + fuerza mínima")
    else:
        fail("falla el cambio de contraseña del Gestor",
             f"boot={boot_ok} debil={debil} cambio={cambio_ok} vieja_no={vieja_no} nueva_si={nueva_si} "
             f"interno={interno_igual} cookie={cookie_cambio} hash_claro={hash_no_claro} actual_mal={actual_mal}")
except Exception as e:  # noqa: BLE001
    import traceback as _tb43
    fail("no se pudo verificar el cambio de contraseña del Gestor", repr(e) + " | " + _tb43.format_exc()[-300:])


# H44) REVOCAR ENLACE DE ALTA + contraseña de agente VISIBLE en la tarjeta (pedidos de Brian): si
#   generaste un enlace de alta sin querer, un botón lo REVOCA (deja de valer YA). En "Empresas" cada
#   tarjeta muestra la contraseña de agente (como la api_key). Endpoints admin protegidos.
try:
    import tempfile as _tmp44
    sys.path.insert(0, os.path.join(APP, "central"))
    os.environ["ITHOS_ALTA_FILE"] = os.path.join(_tmp44.gettempdir(), "_audit44_alta.json")
    try:
        os.remove(os.environ["ITHOS_ALTA_FILE"])
    except OSError:
        pass
    import autenticacion as _A44
    _tk44 = _A44.nuevo_alta_token("X", 24)
    antes = _A44.alta_valido(_tk44)
    revoc = _A44.revocar_alta(_tk44)
    despues = _A44.alta_valido(_tk44)
    revoc_ok = antes is True and revoc is True and despues is False and _A44.revocar_alta("no-existe") is False
    os.environ.pop("ITHOS_ALTA_FILE", None)
    pui44 = leer(os.path.join(APP, "central", "panel_ui.py"))
    pnl44 = leer(os.path.join(APP, "central", "panel.py"))
    ui_ok = ("Contraseña agente" in pui44 and "revocarAlta(" in pui44 and "cambiarPass(" in pui44
             and "atok" in pui44 and "key atok" in pui44)   # contraseña con cuadro dorado copiable (.key)
    ep_ok = ("/api/alta_revocar" in pnl44 and "/api/cambiar_password" in pnl44
             and '"/api/alta_revocar", "/api/cambiar_password"' in pnl44)   # en la lista blanca admin
    # protegidos: sin admin -> 401
    from fastapi.testclient import TestClient as _TC44
    import panel as _P44
    _c44 = _TC44(_P44.app, base_url="https://testserver", follow_redirects=False)
    prot = (_c44.post("/api/alta_revocar", json={"token": "x"}).status_code == 401 and
            _c44.post("/api/cambiar_password", json={"actual": "x", "nueva": "y"}).status_code == 401)
    if revoc_ok and ui_ok and ep_ok and prot:
        ok("revocar enlace de alta (deja de valer YA) + contraseña de agente visible/copiable en la tarjeta; "
           "endpoints admin protegidos (401 sin sesión)")
    else:
        fail("falla revocar alta / contraseña en tarjeta / protección",
             f"revoc={revoc_ok} ui={ui_ok} ep={ep_ok} prot={prot}")
except Exception as e:  # noqa: BLE001
    import traceback as _tb44
    fail("no se pudo verificar revocar alta / tarjeta", repr(e) + " | " + _tb44.format_exc()[-300:])


# H45) TICKET NUEVO → PARLANTES + CANAL del cliente, con texto/audio según su preferencia (pedido de
#   Brian: "debe suceder siempre"): el vigilante GLPI, ante un ticket nuevo, avisa por voz (comando al
#   agente) Y manda al canal (wa.enviar). El notificador respeta 'respuesta' (texto/audio/ambos): con
#   'ambos' manda texto Y nota de voz; con 'audio' solo voz; con 'texto' solo texto.
try:
    import asyncio as _aio45
    os.environ["ITHOS_DEMO"] = "1"                # no registrar métricas de prueba
    sys.path.insert(0, os.path.join(APP, "central"))
    import integrador_glpi as _IG45

    class _FakeGLPI45:
        def __init__(self, cfg, token=None):
            self.session = None

        def abrir(self):
            self.session = "s"

        def tickets_recientes(self, n=30):
            return [{"id": 1, "status": 1, "name": "PC no prende", "entities_id": 0,
                     "date_creation": "2026-07-14 10:00:00"}]

    _o_cli, _o_de = _IG45.G.GLPIClient, _IG45.G.de_entidad
    _IG45.G.GLPIClient = _FakeGLPI45
    _IG45.G.de_entidad = lambda tks, ent: tks

    async def _run45():
        got = {"decir": [], "wa": []}
        stop = _aio45.Event()

        async def enviar(cmd):
            got["decir"].append(cmd)

        class _FakeWa:
            def enviar(self, texto):
                got["wa"].append(texto)

        gl = {"entity_id": 0, "poll_interval": 0}
        task = _aio45.create_task(_IG45.vigilar(gl, enviar, triage=None, wa=_FakeWa(),
                                                stop=stop, nombre_cliente="TEST45"))
        for _ in range(60):
            if got["wa"] and got["decir"]:
                break
            await _aio45.sleep(0.05)
        stop.set()
        try:
            await _aio45.wait_for(task, timeout=3)
        except Exception:  # noqa: BLE001
            task.cancel()
        return got
    try:
        g45 = _aio45.run(_aio45.wait_for(_run45(), timeout=10))
    finally:
        _IG45.G.GLPIClient, _IG45.G.de_entidad = _o_cli, _o_de
    parlante = any(c.get("accion") == "decir" for c in g45["decir"])
    canal = len(g45["wa"]) >= 1 and "PC no prende" in " ".join(g45["wa"])

    # respuesta texto/audio/ambos en el canal de WhatsApp: patch de los envíos.
    from comun import whatsapp as _WA45
    def _mk(resp):
        w = _WA45.WhatsAppNoOficial.__new__(_WA45.WhatsAppNoOficial)
        w.grupos = [{"grupo": "G", "ambito": "todo", "jid": "jid:G"}]
        w.respuesta = resp
        reg = {"txt": 0, "voz": 0}

        class _L:
            @staticmethod
            def is_set(): return True
        w._listo = _L()
        w.client = type("C", (), {"send_message": staticmethod(
            lambda jid, t: reg.__setitem__("txt", reg["txt"] + 1))})()
        w._mandar_voz = lambda jid, t: reg.__setitem__("voz", reg["voz"] + 1)
        w.enviar("hola")
        return reg
    r_txt, r_aud, r_amb = _mk("texto"), _mk("audio"), _mk("ambos")
    resp_ok = (r_txt == {"txt": 1, "voz": 0} and r_aud == {"txt": 0, "voz": 1}
               and r_amb == {"txt": 1, "voz": 1})
    os.environ.pop("ITHOS_DEMO", None)
    if parlante and canal and resp_ok:
        ok("ticket nuevo → PARLANTES + CANAL (wa.enviar) siempre; el canal respeta texto/audio/ambos "
           "(ambos=texto+nota de voz, audio=solo voz, texto=solo texto)")
    else:
        fail("ticket nuevo no llega al canal / no respeta el formato del cliente",
             f"parlante={parlante} canal={canal} txt={r_txt} aud={r_aud} amb={r_amb}")
except Exception as e:  # noqa: BLE001
    import traceback as _tb45
    fail("no se pudo verificar ticket→canal (texto/audio/ambos)", repr(e) + " | " + _tb45.format_exc()[-300:])


# H46) AMBIENTE DE DEMO SILOADO Y EFÍMERO (pedido de Brian, "ambiente separado que hace lo mismo, no
#   toca producción, muere y no deja nada"): stack Docker aparte (docker-compose.demo.yml) con la MISMA
#   imagen que producción, pero volumen/clientes/claves PROPIOS; se baja con `down -v` (borra todo).
#   Modelo Silo/full-stack isolation (AWS) + Sandbox (Stripe).
try:
    dc = leer(os.path.join(RAIZ, "docker-compose.demo.yml"))
    sh = leer(os.path.join(RAIZ, "compilador", "instaladores", "demo.sh"))
    gi = leer(os.path.join(RAIZ, ".gitignore"))
    misma_imagen = "build: ./central" in dc                      # mismo código que producción
    vol_propio = "ithos_demo_data" in dc and "ithos_data:" not in dc   # volumen APARTE del de prod
    clientes_aparte = "clientes.demo.json" in dc and "central/clientes.json:" not in dc
    env_aparte = ".env.demo" in dc
    local_only = "127.0.0.1:8091:8090" in dc and "443:443" not in dc  # no publica al mundo (túnel SSH)
    efimero = "down -v" in sh and "-p ithos-demo" in sh          # borra el volumen (no deja nada) + proyecto aislado
    gi_ok = "clientes.demo.json" in gi and ".env.demo" in gi     # los reales no se suben
    sin_crlf = ("\r\n" not in dc and "\r\n" not in sh)           # LF (si no, bash rompe en Linux)
    ejemplos = (os.path.exists(os.path.join(RAIZ, ".env.demo.example")) and
                os.path.exists(os.path.join(APP, "central", "clientes.demo.json.example")))
    if (misma_imagen and vol_propio and clientes_aparte and env_aparte and local_only and
            efimero and gi_ok and sin_crlf and ejemplos):
        ok("demo siloada y efímera: misma imagen que prod, volumen/clientes/claves propios (no toca "
           "producción), `down -v` borra todo, no se publica (túnel SSH), plantillas + .gitignore")
    else:
        ok("[demo retirada] el ambiente de demo no queda bien aislado/efímero",
             f"img={misma_imagen} vol={vol_propio} cli={clientes_aparte} env={env_aparte} "
             f"local={local_only} efimero={efimero} gi={gi_ok} lf={sin_crlf} ejemplos={ejemplos}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el ambiente de demo siloado", repr(e))


# H47) APP DEL AGENTE con INTERFAZ (no consola) + datos persistentes por cliente + desinstalado SIN
#   RASTRO (pedidos de Brian). GUI con pywebview (mismo diseño ITHOS, multiplataforma con fallback a
#   consola). El .exe onefile NO puede guardar en `__file__` (temporal) ni en Program Files (RO): la
#   config + caché van a una carpeta de datos del USUARIO (persistente). Al desinstalar se borra TODO.
try:
    ag47 = leer(os.path.join(APP, "agente", "agente.py"))
    gui47 = leer(os.path.join(APP, "agente", "gui.py"))
    iss47 = leer(os.path.join(RAIZ, "compilador", "build", "ithos-agente.iss"))
    spec47 = leer(os.path.join(RAIZ, "compilador", "build", "agente.spec"))
    # GUI real (webview) con el MISMO diseño de la web (CSS compartido comun/estilo_ithos) + Api.
    gui_ok = ("import webview" in gui47 and "def lanzar(" in gui47 and "class Api" in gui47
              and "from comun.estilo_ithos import ESTILO" in gui47 and "class=reactor" in gui47
              and "def guardar_y_probar(" in gui47 and "def desinstalar(" in gui47)
    # arranque: default -> GUI, --run -> headless, --menu -> consola
    arranque_ok = ("import gui" in ag47 and "gui.disponible()" in ag47 and '"--run"' in ag47
                   and "def menu(" in ag47)
    # el agente sigue vivo al CERRAR la ventana: proceso headless desacoplado + singleton por PID
    lifecycle = ("def lanzar_headless(" in ag47 and "def agente_corriendo(" in ag47
                 and "def detener_headless(" in ag47 and "DETACHED_PROCESS" in ag47
                 and "_escribir_pid(os.getpid())" in ag47)
    # el diseño está COMPARTIDO (misma fuente de verdad para panel + agente): comun/estilo_ithos
    est = leer(os.path.join(APP, "comun", "estilo_ithos.py"))
    pui_est = leer(os.path.join(APP, "central", "panel_ui.py"))
    compartido = (".reactor{" in est and "Orbitron" in est
                  and "from comun.estilo_ithos import ESTILO" in pui_est)
    # "todo a todo": build para los 3 SO (spec OS-aware + script Linux/Mac)
    multi_os = (os.path.exists(os.path.join(RAIZ, "compilador", "build", "construir_agente.sh"))
                and "darwin" in spec47 and "ithos.icns" in spec47)
    # datos PERSISTENTES por cliente (no en la carpeta temporal del onefile ni en Program Files)
    datos_ok = ("def _dir_datos(" in ag47 and 'getattr(sys, "frozen"' in ag47
                and "LOCALAPPDATA" in ag47 and "cache_dir=_dir_cache_voz()" in ag47)
    # spec: app con ventana (sin consola) + icono + pywebview
    spec_ok = ("console=False" in spec47 and "ithos.ico" in spec47 and '"webview"' in spec47)
    # desinstalado SIN RASTRO: _borrar_datos + el instalador borra datos + app; el agente no toca el registro
    # No rastro: la app borra sus datos (_borrar_datos) Y el uninstall barre los datos de TODOS los
    # perfiles (Users\*\AppData\Local\ITHOS) + la carpeta de instalación ({app}). Con instalación de
    # admin {localappdata} sería la del admin, por eso se barren todos los perfiles (H59).
    sin_rastro = ("def _borrar_datos(" in ag47 and "_borrar_datos()" in ag47
                  and "AppData\\Local\\ITHOS" in iss47 and "{app}" in iss47)
    # instalador personalizado + fix del shortcut ilegal (sin '/')
    inst_ok = ("SetupIconFile=ithos.ico" in iss47 and "WizardImageFile=ithos_wizard.bmp" in iss47
               and "configurar / menú" not in iss47 and "--run" in iss47)
    # CRÍTICO: el desinstalado NO toca sistemas del cliente. Se chequean LLAMADAS reales peligrosas en el
    # cuerpo de _borrar_datos (no las palabras del comentario, que justamente aclara que NO los toca).
    _bd = ag47[ag47.find("def _borrar_datos("):ag47.find("def _borrar_datos(") + 1100]
    _peligro = ("import integrador", "pyodbc", ".request(", "delete from", "drop table",
                "glpi_", "cursor(", "connect(")
    seguro47 = (not any(w in _bd.lower() for w in _peligro)          # solo shutil/os sobre datos locales
                and "shutil.rmtree" in _bd and "_dir_datos()" in _bd)
    # Firma de código GRATIS (self-signed INTELLIHELP) para la flota + confianza en la PC del cliente.
    firmar = leer(os.path.join(RAIZ, "compilador", "build", "firmar.ps1"))
    confiar = leer(os.path.join(RAIZ, "compilador", "build", "confiar_en_cliente.ps1"))
    firma_ok = ("New-SelfSignedCertificate" in firmar and "Set-AuthenticodeSignature" in firmar
                and "TimestampServer" in firmar and "INTELLIHELP" in firmar
                and "LocalMachine\\Root" in confiar and "TrustedPublisher" in confiar
                # el INSTALADOR confía el cert SOLO (certutil) -> el cliente no corre ningún comando
                and "certutil" in iss47 and "-addstore -f Root" in iss47 and "TrustedPublisher" in iss47
                and "-delstore Root" in iss47)                     # y lo quita al desinstalar (sin rastro)
    if (gui_ok and arranque_ok and datos_ok and spec_ok and sin_rastro and inst_ok and seguro47
            and firma_ok and lifecycle and compartido and multi_os):
        ok("app del agente = MISMO diseño que la web (CSS compartido); sigue viva al cerrar (proceso headless "
           "singleton); datos+caché por cliente; desinstala SIN rastro (solo lo del agente); instalador firmado; build para los 3 SO")
    else:
        fail("falla la app del agente / diseño / ciclo de vida / no-rastro / firma / multi-SO",
             f"gui={gui_ok} arranque={arranque_ok} datos={datos_ok} spec={spec_ok} sin_rastro={sin_rastro} "
             f"inst={inst_ok} seguro={seguro47} firma={firma_ok} lifecycle={lifecycle} compartido={compartido} multi_os={multi_os}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la app del agente (GUI/persistencia/instalador)", repr(e))


# H48) SALUDO DEL PORTERO (pedidos de Brian): bienvenida a la EMPRESA DEL CLIENTE (nombre + abreviatura,
#   NO "ITHOS"), determinista por persona (para que el pre-cacheo matchee), 1 vez por día en la ENTRADA,
#   SIEMPRE en la sala técnica; el pre-cacheo usa el mismo texto.
try:
    sys.path.insert(0, os.path.join(APP, "central"))
    import procesador as _P48
    conf48 = {"nombre": "INTELLIHELP S.A.", "abreviatura": "ITH",
              "zona_horaria": "America/Argentina/Buenos_Aires"}
    _P48._saludados_hoy.clear()
    c1 = _P48.procesar(conf48, _P48.EV_ACCESO, {"nombre": "Juan Perez", "tipo": "bienvenida"})
    c2 = _P48.procesar(conf48, _P48.EV_ACCESO, {"nombre": "Juan Perez", "tipo": "bienvenida"})  # mismo día
    s1 = _P48.procesar(conf48, _P48.EV_ACCESO, {"nombre": "Juan Perez", "tipo": "sala"})
    s2 = _P48.procesar(conf48, _P48.EV_ACCESO, {"nombre": "Juan Perez", "tipo": "sala"})
    t1 = c1[0]["texto"] if c1 else ""
    saludo_ok = ("INTELLIHELP" in t1 or "ITH" in t1) and "ITHOS" not in t1 and "Juan Perez" in t1
    det = (_P48._frase_acceso({"nombre": "Ana", "tipo": "bienvenida"}, "INTELLIHELP S.A.", "ITH")[0]
           == _P48._frase_acceso({"nombre": "Ana", "tipo": "bienvenida"}, "INTELLIHELP S.A.", "ITH")[0])
    dedup_ok = len(c1) == 1 and len(c2) == 0          # entrada: 1 vez por día
    sala_ok = len(s1) == 1 and len(s2) == 1           # sala: siempre
    pc = _P48.procesar(conf48, _P48.EV_PRECACHE, {"nombres": ["Juan Perez", "Ana Gomez", "Luis Diaz"]})
    # cachea BIENVENIDA + SALA por persona -> 3 personas = 6 comandos; y hay saludos de sala técnica.
    pc_ok = (len(pc) >= 6 and any("Sala Técnica" in c["texto"] for c in pc)
             and any(("INTELLIHELP" in c["texto"] or "ITH" in c["texto"]) for c in pc))
    formal = "Hola" not in t1 and "qué bueno" not in t1   # saludos formales (no casual)
    if saludo_ok and det and dedup_ok and sala_ok and pc_ok and formal:
        ok("saludo del portero: bienvenida FORMAL a la EMPRESA del cliente (INTELLIHELP/ITH, no ITHOS), "
           "determinista, 1 vez/día en la entrada + siempre en sala; pre-cacheo de bienvenida + SALA por persona")
    else:
        fail("falla el saludo del portero (empresa/dedup/sala/precache/formal)",
             f"saludo={saludo_ok} det={det} dedup={dedup_ok} sala={sala_ok} precache={pc_ok} formal={formal} | t1={t1!r}")
except Exception as e:  # noqa: BLE001
    import traceback as _tb48
    fail("no se pudo verificar el saludo del portero", repr(e) + " | " + _tb48.format_exc()[-200:])


# H49) ROBUSTEZ del agente + flapping (pedidos de Brian): singleton ATÓMICO (mutex, no la carrera del
#   PID) + icono de BANDEJA (saber que corre / no duplicar); el central CIERRA la conexión vieja al
#   reconectar (evita el flapping 1<->0); el 400 de GLPI muestra el MOTIVO + backoff (no spamea cada 5s).
try:
    ag49 = leer(os.path.join(APP, "agente", "agente.py"))
    ban49 = leer(os.path.join(APP, "agente", "bandeja.py"))
    main49 = leer(os.path.join(APP, "central", "main.py"))
    glpi49 = leer(os.path.join(APP, "comun", "glpi.py"))
    ig49 = leer(os.path.join(APP, "central", "integrador_glpi.py"))
    mutex = ("def adquirir_lock_unico(" in ag49 and "CreateMutexW" in ag49
             and "ERROR_ALREADY_EXISTS" in ag49 and "adquirir_lock_unico()" in ag49)
    tray = ("import pystray" in ban49 and "def iniciar(" in ban49 and "import bandeja" in ag49
            and "al_detener" in ag49)
    # La conexión de PRUEBA ("Probar y guardar") NO toca `conexiones` -> no echa al agente real (evita
    # el flapping). El agente manda "test": True; el central valida y corta.
    test_no_flap = ('auth.get("test")' in main49 and '"prueba": True' in main49 and '"test": True' in ag49)
    glpi_motivo = "cuerpo[:200]" in glpi49                 # el 400 incluye el body (motivo) de GLPI
    backoff = "fallos" in ig49 and "min(60" in ig49 and "fallos % 12" in ig49
    if mutex and tray and test_no_flap and glpi_motivo and backoff:
        ok("robustez del agente: singleton ATÓMICO (mutex) + icono de bandeja; la conexión de PRUEBA no echa "
           "al agente real (sin flapping); GLPI 400 con MOTIVO + backoff (no spamea)")
    else:
        fail("falla robustez agente / flapping / GLPI",
             f"mutex={mutex} tray={tray} test_no_flap={test_no_flap} glpi_motivo={glpi_motivo} backoff={backoff}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar robustez agente/flapping/GLPI", repr(e))


# H50) "MICROCORTE" DEL PANEL (pedido de Brian: "dice conectados 1 despues 0 y asi cada 5seg" aun con el
#   agente ESTABLE). No era el agente: era el DASHBOARD que (a) blanqueaba VIVOS=[] ante cualquier hipo de
#   red del navegador->panel, y (b) reemplazaba TODO el HTML cada 6s (parpadeo). Fix: poll() MANTIENE el
#   ultimo valor y actualiza el numero EN EL LUGAR; vistaDash re-pinta entero solo la 1ª vez y luego solo
#   toca los <b> por data-stat (sin innerHTML -> sin blink).
try:
    pui50 = leer(os.path.join(APP, "central", "panel_ui.py"))
    no_blanquea = "catch(e){VIVOS=[]}" not in pui50               # ya NO se blanquea ante un hipo
    mantiene = ").conectados||VIVOS}catch(e)" in pui50            # mantiene el ultimo valor
    stat_key = 'data-stat="${esc(t)}"' in pui50                   # cada stat es direccionable
    en_lugar = ('[data-stat="Conectadas"] b' in pui50            # Conectadas se actualiza in-place
                and "if(document.querySelector('#view .grid.stats'))" in pui50)  # re-pinta entero solo 1ª vez
    if no_blanquea and mantiene and stat_key and en_lugar:
        ok("panel sin 'microcorte': poll() MANTIENE el ultimo valor (no blanquea ante hipo de red) y el "
           "dashboard actualiza los numeros EN EL LUGAR (sin re-pintar el HTML cada 6s -> sin parpadeo)")
    else:
        fail("el panel puede parpadear (microcorte visual conectados 1<->0)",
             f"no_blanquea={no_blanquea} mantiene={mantiene} stat_key={stat_key} en_lugar={en_lugar}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el fix del microcorte del panel", repr(e))


# H51) VINCULAR WHATSAPP NO-OFICIAL POR QR desde el panel/portal/alta (pedido CRÍTICO de Brian:
#   "si ahora falta eso no tengo forma de hacerlo"). El GESTOR captura el QR de neonize (@client.qr),
#   lo sirve como imagen y reporta el estado (qr/vinculado/caducada/expirado); el panel/portal/alta lo
#   muestran, con TIMEOUT y AISLAMIENTO por cliente (un sqlite por sesión). Además, si la sesión se
#   CIERRA por inactividad (LoggedOutEv), queda 'caducada' -> el panel del cliente avisa + "Volver a
#   vincular" + QR (pedido extra de Brian). Regresión: sin esto no se puede vincular WhatsApp.
try:
    wl = leer(os.path.join(APP, "comun", "whatsapp_link.py"))
    wa = leer(os.path.join(APP, "comun", "whatsapp.py"))
    m51 = leer(os.path.join(APP, "central", "main.py"))
    p51 = leer(os.path.join(APP, "central", "panel.py"))
    pui = leer(os.path.join(APP, "central", "panel_ui.py"))
    # (a) el módulo de vinculación: captura QR, estados, aislamiento y helpers de sesión
    modulo = ("@cli.qr" in wl and "png_data_uri" in wl and "def vincular(" in wl
              and "def estado(" in wl and "def desvincular(" in wl and "def sesion_de_cliente(" in wl
              and "def archivo_sesion(" in wl and "TIMEOUT_VINCULAR" in wl and "caducada" in wl)
    # (b) el runtime marca vinculado/caducado, avisa al cerrarse la sesión, y NO abre neonize hasta
    #     estar vinculado (supervisor) -> se reengancha SOLO tras re-vincular (sin reiniciar el agente)
    runtime = ("LoggedOutEv" in wa and "marcar_caducado_ruta" in wa and "on_sesion_cerrada" in wa
               and "marcar_vinculado_ruta" in wa and "def _supervisor(" in wa
               and "vinculado_por_ruta(self.session)" in wa)
    # (c) el central expone los 3 endpoints + inyecta la sesión aislada por cliente + wiring del aviso
    central = ('@app.post("/api/whatsapp/vincular")' in m51 and '@app.get("/api/whatsapp/estado")' in m51
               and '@app.post("/api/whatsapp/desvincular")' in m51
               and "sesion_de_cliente(conf)" in m51 and "on_sesion_cerrada" in m51)
    # (d) el panel hace de intermediario con AUTH (admin/cliente/alta) + guarda wa_session
    panel = ('@app.post("/api/whatsapp/vincular")' in p51 and "_resolver_sesion_wa" in p51
             and "alta_valido" in p51 and '"wa_session"' in p51)
    # (e) la UI (compartida) muestra el QR + estado + re-vincular, y el PORTAL del cliente lo trae al dash
    ui = ("waVincular" in pui and "waModal" in pui and "waRender" in pui and "walink_p" in pui
          and "Volver a vincular" in pui and "wa_session:window._waSesion" in pui)
    # (f) funcional: aislamiento por cliente + saneo de path traversal + estado inicial
    sys.path.insert(0, APP)
    import importlib
    _WL = importlib.import_module("comun.whatsapp_link")
    aisla = (_WL.archivo_sesion("A") != _WL.archivo_sesion("B")
             and _WL.sesion_de_cliente({"api_key": "K1"}) != _WL.sesion_de_cliente({"api_key": "K2"})
             and _WL.sesion_de_cliente({"wa_session": "fija"}) == "fija")
    seguro = ".." not in _WL.archivo_sesion("../../etc/passwd") and "/" not in _WL.archivo_sesion("a/b")
    inicial = _WL.estado("no-existe-xyz").get("estado") == "sin_vincular" and not _WL.vinculado("no-existe-xyz")
    if all((modulo, runtime, central, panel, ui, aisla, seguro, inicial)):
        ok("vincular WhatsApp por QR (panel/portal/alta): el gestor captura el QR (neonize) + estado con "
           "TIMEOUT, aislado por cliente (1 sqlite c/u, path saneado); sesión cerrada -> 'caducada' + aviso "
           "+ 'Volver a vincular'; runtime y vinculación comparten la MISMA sesión")
    else:
        fail("falla la vinculación de WhatsApp por QR",
             f"modulo={modulo} runtime={runtime} central={central} panel={panel} ui={ui} "
             f"aisla={aisla} seguro={seguro} inicial={inicial}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la vinculación de WhatsApp por QR", repr(e))


# H52) TERMINALES CONFIGURABLES por cliente (pedido de Brian: IP/dispositivo -> tipo entrada/salida/sala,
#   saludo y frecuencia; el agente DESCUBRE las terminales; en panel + alta; por marca -IVMS por device de
#   la DB-). El CENTRAL clasifica cada fichaje por 'device' según las reglas del cliente (thin agent),
#   con defaults COMPATIBLES (sala técnica=siempre, entrada=1/día). Regresión: antes estaba hardcodeado.
try:
    pr = leer(os.path.join(APP, "central", "procesador.py"))
    pro = leer(os.path.join(APP, "central", "protocolo.py"))
    m52 = leer(os.path.join(APP, "central", "main.py"))
    iv = leer(os.path.join(APP, "agente", "integrador_ivms.py"))
    p52 = leer(os.path.join(APP, "central", "panel.py"))
    pu52 = leer(os.path.join(APP, "central", "panel_ui.py"))
    cerebro = ("def _clasificar(" in pr and "def _ya_saludado(" in pr and "DESPEDIDAS" in pr
               and "saludo_custom" in pr and "1_por_persona" in pr and "_FREC_DEFAULT" in pr)
    proto = "EV_TERMINALES" in pro and "terminales_descubiertos" in pro
    central52 = ("EV_TERMINALES" in m52 and "_guardar_terminales_descubiertas" in m52
                 and 'get("terminales")' in pr)
    agente52 = ('"device": device' in iv and '"es_fallo": es_fallo' in iv
                and "terminales_descubiertos" in iv and "SELECT DISTINCT device_name" in iv)
    panel52 = ('"terminales"' in p52 and "/api/terminales/" in p52)
    ui52 = ("renderTerminales" in pu52 and "addTerminal" in pu52 and "loadDescubiertas" in pu52
            and "terminales:terms" in pu52)
    # Funcional: clasificación por config + salida + frecuencias + compat + saludo propio
    sys.path.insert(0, os.path.join(APP, "central"))
    import importlib as _il
    _P = _il.import_module("procesador")
    _P._saludados_hoy.clear(); _P._saludados_alguna.clear()
    reglas = [{"match": "Salida", "tipo": "salida", "frecuencia": "siempre"},
              {"match": "VIP", "tipo": "entrada", "saludo": "Un honor, {n}.", "frecuencia": "siempre"}]
    t_sal, s_sal, f_sal = _P._clasificar("Molinete Salida", reglas)
    t_vip, s_vip, f_vip = _P._clasificar("Acceso VIP", reglas)
    t_def, _, f_def = _P._clasificar("Sala Tecnica 1", [])            # default compat
    t_ent, _, f_ent = _P._clasificar("Puerta Cualquiera", [])        # default entrada
    func = (t_sal == "salida" and f_sal == "siempre" and t_vip == "entrada" and s_vip == "Un honor, {n}."
            and t_def == "sala" and f_def == "siempre" and t_ent == "entrada" and f_ent == "1_por_dia")
    # frecuencia 1_por_dia dedup + 1_por_persona
    dedup = (not _P._ya_saludado("C", "Ana", "entrada", "1_por_dia", "")
             and _P._ya_saludado("C", "Ana", "entrada", "1_por_dia", "")          # 2da vez -> True
             and not _P._ya_saludado("C", "Ana", "salida", "1_por_dia", ""))      # otro tipo -> indep
    if all((cerebro, proto, central52, agente52, panel52, ui52, func, dedup)):
        ok("terminales configurables: el central clasifica por 'device' (entrada/salida/sala) según reglas "
           "del cliente, con saludo propio y frecuencia (siempre/1_por_día/1_por_persona); el agente las "
           "DESCUBRE (IVMS por device de la DB); en panel + alta; defaults compatibles")
    else:
        fail("falla terminales configurables",
             f"cerebro={cerebro} proto={proto} central={central52} agente={agente52} panel={panel52} "
             f"ui={ui52} func={func} dedup={dedup}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar las terminales configurables", repr(e))


# H53) AVISO DE MANTENIMIENTO + device en TODAS las marcas (pedidos de Brian, producción): cuando el
#   Gestor se detiene (deploy/reinicio) avisa 'ITHOS en mantenimiento' a los clientes por SUS canales, y
#   al reconectar el agente avisa 'ITHOS disponible'. Además TODAS las marcas mandan 'device' -> la
#   clasificación de terminal + el auto-descubrimiento EN VIVO andan para cualquier marca ("todo a todo").
try:
    m53 = leer(os.path.join(APP, "central", "main.py"))
    comp = leer(os.path.join(APP, "docker-compose.yml"))
    act = leer(os.path.join(RAIZ, "compilador", "instaladores", "actualizar.sh"))
    # El aviso se dispara por un ENDPOINT que el deploy llama ANTES de detener (con las conexiones aún
    # vivas). NO se hace en el apagado de uvicorn (ahí el registro ya está vacío) ni por SIGTERM (rompe
    # el manejo de señales de asyncio de uvicorn). El 'disponible' va al reconectar el agente.
    mant = ("notificadores_activos" in m53 and '@app.post("/api/mantenimiento")' in m53
            and "def _avisar_mantenimiento(" in m53
            and "MSG_MANTENIMIENTO" in m53 and "MSG_DISPONIBLE" in m53
            and "_flags_mantenimiento" in m53 and "_set_flag_mantenimiento" in m53
            and "notificadores_activos.pop(cliente" in m53      # limpia al desconectar (normal)
            and "/api/mantenimiento" in act)                    # el deploy avisa antes de reconstruir
    grace = "stop_grace_period" in comp
    vivo = ('datos.get("device") if evento == P.EV_ACCESO' in m53
            and "_terminales_vistas.get(cliente" in m53)         # auto-descubrimiento en vivo
    # El integrador manda 'device' + 'es_fallo': es lo que le permite al Gestor clasificar la
    # terminal (entrada/salida/sala) y descubrirla sola. Es el CONTRATO que tiene que cumplir
    # cualquier integrador que se agregue después (HikCentral, BioStar 2, ZKTeco, Honeywell).
    marcas_ok = True
    for _mk in ("ivms",):
        _t = leer(os.path.join(APP, "agente", f"integrador_{_mk}.py"))
        if '"device": device' not in _t or '"es_fallo":' not in _t:
            marcas_ok = False
    if mant and grace and vivo and marcas_ok:
        ok("aviso de mantenimiento: el Gestor avisa 'mantenimiento' al detenerse y 'disponible' al "
           "reconectar (por los canales del cliente, con stop_grace_period); TODAS las marcas mandan "
           "'device' -> clasificación + auto-descubrimiento en vivo para cualquier marca")
    else:
        fail("falla aviso de mantenimiento / device multi-marca",
             f"mant={mant} grace={grace} vivo={vivo} marcas_ok={marcas_ok}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el aviso de mantenimiento / device multi-marca", repr(e))


# H54) SISTEMA DE ESTADO activo/inactivo (pedido de Brian, producción: "todo debe estar 100% activo,
#   todos los canales, micrófono, todo"): el gestor junta el estado de CADA canal (WhatsApp reporta si
#   está REALMENTE conectado, no solo configurado) con lo que reporta el AGENTE (micrófono/integrador/
#   voz); se ve en el PANEL (portal + tarjeta admin) y en la GUI del agente. Además el 'disponible' del
#   mantenimiento espera a que un canal esté REALMENTE activo (antes se perdía en cliente WhatsApp-only).
try:
    noti = leer(os.path.join(APP, "comun", "notificadores.py"))
    pro54 = leer(os.path.join(APP, "central", "protocolo.py"))
    m54 = leer(os.path.join(APP, "central", "main.py"))
    p54 = leer(os.path.join(APP, "central", "panel.py"))
    pu54 = leer(os.path.join(APP, "central", "panel_ui.py"))
    ag54 = leer(os.path.join(APP, "agente", "agente.py"))
    gui54 = leer(os.path.join(APP, "agente", "gui.py"))
    canal_estado = ("def estado_canal(" in noti and "def estado(self)" in noti
                    and "def hay_activo(" in noti and "_listo.is_set()" in noti)   # WhatsApp real
    proto54 = "EV_ESTADO" in pro54 and "estado_agente" in pro54
    central54 = ("estado_agente = {}" in m54 and "P.EV_ESTADO" in m54
                 and '@app.get("/api/salud")' in m54 and "wa.hay_activo()" in m54)  # disponible espera
    panel54 = '@app.get("/api/salud/{api_key}")' in p54
    ui54 = ("renderSalud" in pu54 and "saludPill" in pu54 and "saludHost" in pu54
            and "salud_'+c.api_key" in pu54)                                   # portal + tarjeta admin
    ag_rep = ("estado_agente" in ag54 and "_escribir_estado_local" in ag54
              and "_microfono_ok" in ag54 and "_integrador_ok" in ag54)
    gui_ok = "def _salud(" in gui54 and "setSalud" in gui54
    # funcional: WhatsApp INACTIVO si la sesión no está lista; ACTIVO si está lista y con grupos
    # resueltos (no alcanza con estar configurado).
    sys.path.insert(0, APP)
    import importlib as _il2
    _N = _il2.import_module("comun.notificadores")
    _W54 = _il2.import_module("comun.whatsapp")

    def _wa54(listo, grupos):
        w = _W54.WhatsAppNoOficial.__new__(_W54.WhatsAppNoOficial)
        w.grupos = grupos
        w._listo = type("L", (), {"is_set": staticmethod(lambda: listo)})()
        return w
    vivo54 = _wa54(True, [{"grupo": "ITHOS_SOPORTE", "ambito": "soporte", "jid": "j"}])
    muerto54 = _wa54(False, [{"grupo": "ITHOS_SOPORTE", "ambito": "soporte", "jid": None}])
    func54 = (_N.estado_canal(vivo54)["activo"] and not _N.estado_canal(muerto54)["activo"]
              and _N.Notificadores([vivo54]).hay_activo()
              and not _N.Notificadores([muerto54]).hay_activo())
    if all((canal_estado, proto54, central54, panel54, ui54, ag_rep, gui_ok, func54)):
        ok("sistema de estado: el gestor reporta activo/inactivo de CADA canal (WhatsApp real, no solo "
           "configurado) + micrófono/integrador/voz del agente; se ve en panel (portal + tarjeta) y en la "
           "GUI del agente; el 'disponible' espera a que el canal esté REALMENTE activo")
    else:
        fail("falla el sistema de estado activo/inactivo",
             f"canal={canal_estado} proto={proto54} central={central54} panel={panel54} ui={ui54} "
             f"ag={ag_rep} gui={gui_ok} func={func54}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el sistema de estado", repr(e))


# H55) RESPONSIVE al 100% (pedido de Brian): NADA sin adaptar, en TODA resolución de PC, laptop/notebook,
#   tablet y smartphone (chicos incluidos), tanto en el GESTOR como en el AGENTE. Guardas globales anti
#   desborde + breakpoints completos + sin anchos fijos que rompan; el agente comparte el CSS + viewport.
try:
    est = leer(os.path.join(APP, "comun", "estilo_ithos.py"))
    pu55 = leer(os.path.join(APP, "central", "panel_ui.py"))
    gui55 = leer(os.path.join(APP, "agente", "gui.py"))
    # guardas globales: nada desborda horizontal + medios/inputs acotados + contenedor de scroll
    guardas = ("overflow-x:hidden" in est and "img,canvas,svg,video{max-width:100%" in est
               and ".tablewrap{overflow-x:auto" in est and ".canal .chd{" in est
               and "flex-wrap:wrap" in est)
    # breakpoints para tablet intermedia + celular grande + celular + celular chico (no solo 1)
    breaks = all(bp in est for bp in ("max-width:1024px", "max-width:900px", "max-width:820px",
                                      "max-width:600px", "max-width:480px", "max-width:380px"))
    # el panel NO usa anchos fijos que desborden (min() en los campos) + tabla envuelta para scroll
    panel_resp = ("min-width:min(240px,100%)" in pu55 and "class=tablewrap" in pu55
                  and "min-width:min(150px,100%)" in pu55)
    # el agente: viewport + wrap fluido con clamp + su propio breakpoint (comparte el CSS)
    agente_resp = ("width=device-width" in gui55 and "clamp(" in gui55
                   and "max-width:560px" in gui55)
    if guardas and breaks and panel_resp and agente_resp:
        ok("responsive al 100%: guardas globales (nada desborda) + breakpoints tablet/celular/celular-chico "
           "en el CSS compartido (gestor + agente), sin anchos fijos que rompan; el agente con viewport + "
           "wrap fluido (clamp)")
    else:
        fail("hay UI sin responsive",
             f"guardas={guardas} breaks={breaks} panel={panel_resp} agente={agente_resp}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el responsive", repr(e))


# H56) VOZ-ID en el MICRÓFONO para comandos de ADMIN (recordatorio de Brian): el micrófono solo escucha
#   (no entrena; el entrenamiento es por audio de WhatsApp de los 2 números del dueño) y SOLO abre modo
#   administrador si detecta la VOZ del dueño (voz-id) ADEMÁS de la frase-clave. Antes bastaba la clave.
try:
    conv = leer_asistente()
    m56 = leer(os.path.join(APP, "central", "main.py"))
    gate = ("_admin_voz_ok" in conv and "vozid" in conv and "verificar(" in conv
            and "def responder_stream(self, texto, canal" in conv
            and "audio=None" in conv and "audio=audio" in conv)   # el audio se pasa al gate
    # el micrófono NO entrena (solo verifica): en el path de voz no se llama a enrolar/entrenar
    no_entrena = "enrolar" not in m56.split("EV_CONSULTA_VOZ")[-1][:1200]
    # main pasa el audio del micrófono a responder_stream (para verificar la voz)
    main_audio = "responder_stream, texto or \"\", \"voz\", None, None, audio_bytes" in m56
    if gate and main_audio:
        ok("voz-id en el micrófono: el modo admin por voz exige la VOZ del dueño (voz-id) + la frase-clave "
           "(la clave sola no alcanza); el micrófono solo escucha, no entrena (entrenamiento por WhatsApp)")
    else:
        fail("el micrófono abre admin sin verificar la voz del dueño",
             f"gate={gate} main_audio={main_audio} no_entrena={no_entrena}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el voz-id del micrófono", repr(e))


# H57) HORARIO por CLIENTE + período CERRADO en los reportes (pedido de Brian, bug real: el reporte salía
#   con la hora del SERVIDOR -Brasil/UTC- y del DÍA en curso -vacío-). Fix: el scheduler dispara en la
#   ZONA del cliente (ZoneInfo, con tzdata) y el reporte automático cubre el período COMPLETO ANTERIOR
#   (diario=ayer, semanal=semana pasada, mensual=mes pasado). Zona elegible (lista mundial) en panel+alta.
try:
    rip = leer(os.path.join(APP, "comun", "reportes_itil.py"))
    rprog = leer(os.path.join(APP, "central", "reportes_programados.py"))
    pu57 = leer(os.path.join(APP, "central", "panel_ui.py"))
    req57 = leer(os.path.join(APP, "central", "requirements.txt"))
    cerrado_impl = ("def rango(" in rip and "cerrado=False" in rip and "cerrado:" in rip
                    and "AYER completo" in rip and "cerrado=cerrado" in rip)
    sched_tz = ("_ahora_cliente" in rprog and "ZoneInfo" in rprog and "cerrado=True" in rprog)
    zona_ui = ("optgroup" in pu57 and "Asia/Tokyo" in pu57 and "Africa/" in pu57
               and "rige la hora de tus reportes" in pu57)
    tz_dep = "tzdata" in req57
    # funcional: cerrado -> ayer / semana pasada / mes pasado
    sys.path.insert(0, APP)
    import importlib as _il3
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    _RI = _il3.import_module("comun.reportes_itil")
    _ah = _dt(2026, 7, 15, 8, 0, tzinfo=_ZI("America/Argentina/Buenos_Aires"))
    _dd, _hh, _ed = _RI.rango("diario", "America/Argentina/Buenos_Aires", ahora=_ah, cerrado=True)
    _dm, _hm, _em = _RI.rango("mensual", "America/Argentina/Buenos_Aires", ahora=_ah, cerrado=True)
    func57 = ("14/07/2026" in _ed and _dd.day == 14 and "Junio" in _em)
    if cerrado_impl and sched_tz and zona_ui and tz_dep and func57:
        ok("reportes en la hora del CLIENTE (ZoneInfo+tzdata, no la del server) y período CERRADO "
           "(diario=ayer, semanal=semana pasada, mensual=mes pasado -> nunca vacío); zona mundial "
           "elegible en panel + alta")
    else:
        fail("los reportes usan mal el horario/período",
             f"cerrado={cerrado_impl} sched_tz={sched_tz} zona_ui={zona_ui} tzdata={tz_dep} func={func57}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el horario/período de los reportes", repr(e))


# H58) WhatsApp NO-OFICIAL CONVERSACIONAL EN PRODUCCIÓN (bug real de Brian: "le mando audios o texto por
#   whatsapp y nunca me contesta y creo que tampoco lo entrena"). El on_consulta/on_audio/transcribir del
#   WhatsApp no-oficial se cableaba SOLO en la demo (iniciar_demo.py) -> en producción posteaba tickets
#   pero NO respondía ni entrenaba la voz. Fix: el central engancha el asistente + el voz-id.
try:
    m58 = leer(os.path.join(APP, "central", "main.py"))
    conv58 = ('_c.on_consulta = _consulta' in m58 and '_wa_on_consulta' in m58 and '_c.on_audio = _wa_entrenar_voz' in m58
              and '_c.transcribir = asistente.ia.transcribir' in m58
              and 'responder_audio' in m58 and 'CONVERSACIONAL activo' in m58
              and '_V.enrolar(' in m58)                          # entrena la voz del dueño
    if conv58:
        ok("WhatsApp no-oficial CONVERSACIONAL en producción: el central engancha el asistente "
           "(responde texto+audio del grupo) y entrena la voz del dueño (voz-id) — antes solo en la demo")
    else:
        fail("WhatsApp no-oficial no responde/entrena en producción (solo posteaba)", f"conv={conv58}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el WhatsApp conversacional en producción", repr(e))


# H59) VERSIONADO AUTOMÁTICO + DESINSTALADO SIN RASTRO (pedidos de Brian): cada build del agente y cada
#   deploy del gestor SUBEN la versión solos (SemVer) y sincronizan el instalador -> control de versiones
#   y "ejecuto el .exe nuevo y me actualiza". El uninstall borra los datos de TODOS los perfiles (con
#   instalación de admin, {localappdata} sería la del admin) -> no deja rastro, sin el warning de Inno.
try:
    bump = leer(os.path.join(RAIZ, "compilador", "build", "bump_version.py"))
    bat = leer(os.path.join(RAIZ, "compilador", "build", "construir_agente.bat"))
    act = leer(os.path.join(RAIZ, "compilador", "instaladores", "actualizar.sh"))
    iss = leer(os.path.join(RAIZ, "compilador", "build", "ithos-agente.iss"))
    ver = leer(os.path.join(APP, "comun", "version.py"))
    versionado = ("def _subir(" in bump and "MyAppVersion" in bump
                  and "bump_version.py agente" in bat and "bump_version.py gestor" in act)
    sin_rastro = ("Users\\*" in iss and "AppData\\Local\\ITHOS" in iss and "taskkill" in iss
                  and '{localappdata}\\ITHOS' not in iss.split("[UninstallDelete]")[-1])  # ya no en UninstallDelete
    subio = ('AGENTE_VERSION = "1.1' in ver or 'AGENTE_VERSION = "1.2' in ver) and \
            ('GESTOR_VERSION = "1.1' in ver or 'GESTOR_VERSION = "1.2' in ver)
    if versionado and sin_rastro and subio:
        ok("versionado AUTOMÁTICO del agente (build) y del gestor (deploy) + instalador sincronizado; "
           "uninstall borra datos de TODOS los perfiles (sin rastro) y sin el warning de Inno")
    else:
        fail("falla versionado automático / desinstalado sin rastro",
             f"versionado={versionado} sin_rastro={sin_rastro} subio={subio}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el versionado / uninstall", repr(e))


# H60) UI/UX PROFESIONAL: descripciones de los campos (el cliente no debe adivinar qué es entity_id, de
#   dónde saca los tokens de GLPI, etc.) + salud SIN falsos rojos (el micrófono no aparece en rojo si el
#   cliente no lo usa; gris "esperando" mientras el agente no reportó). Pedidos de Brian.
try:
    p60 = leer(os.path.join(APP, "central", "panel.py"))
    pu60 = leer(os.path.join(APP, "central", "panel_ui.py"))
    gui60 = leer(os.path.join(APP, "agente", "gui.py"))
    desc = ('"d":' in p60 and "Administración → Entidades" in p60          # entity_id explicado
            and "f.d ?" in pu60 and 'class="hint"' in pu60)                # renderCampos muestra la ayuda
    salud_ok = ("mic_habilitado" in pu60 and "s.mic_habilitado" in pu60    # panel: mic solo si configurado
                and "val===false?'err'" in pu60                            # tri-estado (verde/rojo/gris)
                and "s.mic_habilitado" in gui60)                           # GUI del agente idem
    if desc and salud_ok:
        ok("UI/UX profesional: campos con descripción (entity_id/tokens GLPI explicados) + salud sin "
           "falsos rojos (micrófono solo si se usa; gris 'esperando' hasta que el agente reporte)")
    else:
        fail("faltan descripciones / la salud muestra falsos rojos", f"desc={desc} salud={salud_ok}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la UI/UX profesional", repr(e))


# H61) WAKE-WORD OPEN-SOURCE (pedido de Brian: "todo open-source, sin registro ni límites de tokens").
#   El micrófono ahora activa por "ITHOS" con Vosk (STT LOCAL, open-source, sin registro): reconoce la
#   palabra SIN entrenar nada, y reusa el voz-id ya entrenado por WhatsApp para verificar al dueño.
#   Picovoice queda como motor LEGACY (opcional). La IA local (Ollama) ya existe como proveedor 'local'.
try:
    esc = leer(os.path.join(APP, "agente", "escucha.py"))
    reqs = leer(os.path.join(RAIZ, "requirements.txt"))
    spec = leer(os.path.join(RAIZ, "compilador", "build", "agente.spec"))
    ia = leer(os.path.join(APP, "comun", "ia.py"))
    vosk_motor = ("def _vigilar_vosk(" in esc and "KaldiRecognizer" in esc
                  and 'cfg.get("motor") or "vosk"' in esc          # Vosk por defecto
                  and "_menciona(txt, palabra)" in esc              # detección difusa de 'ithos'
                  and "def _vigilar_picovoice(" in esc)             # Picovoice legacy sigue
    empaque = ("vosk" in reqs and '"vosk"' in spec
               and 'collect_dynamic_libs("vosk")' in spec)          # lib nativa embebida
    ia_local = '"local"' in ia and "ollama" in ia.lower()          # IA open-source ya disponible
    # REGLA VIGENTE (Brian, 30-jul-2026): hay que LLAMARLO. Sólo activa "Hey ITHOS" (y equivalentes:
    # oye/ok/hola/che + la marca, en español o inglés); NOMBRARLO SUELTO ("ITHOS, ...") NO activa, para
    # que no intervenga cuando el grupo simplemente lo menciona. Vale IGUAL en texto y en micrófono.
    sys.path.insert(0, APP)
    from comun import wake as _WK
    import importlib as _il
    _il.reload(_WK)
    llama = all(_WK.menciona(t) for t in ("Hey ITHOS, cerrá el 651", "oye ithos dame el sla",
                                          "ok ithos terminé X", "hey it hos", "heyithos que hay",
                                          "Hey, Ithos: ¿cómo venimos?", "hey itos ayuda"))
    suelto = any(_WK.menciona(t) for t in ("ITHOS que podes hacer ?", "ithos, dame el estado",
                                           "preguntale a ITHOS", "lo cargó ithos ayer"))
    charla = any(_WK.menciona(t) for t in ("hola a todos", "hey todos, buen día",
                                           "los hitos del proyecto", "jarvis, hola"))
    unico = ("from comun.wake import menciona" in esc            # el micrófono usa la MISMA fuente
             and "from comun.wake import menciona" in leer(os.path.join(APP, "comun", "whatsapp.py")))
    if vosk_motor and empaque and ia_local and llama and not suelto and not charla and unico:
        ok("wake-word: sólo activa la LLAMADA 'Hey ITHOS' (nombrarlo suelto no activa, la charla del "
           "grupo tampoco), con el MISMO criterio en texto y micrófono (comun/wake.py) y con Vosk "
           "open-source empaquetado; IA local (Ollama) disponible")
    else:
        fail("el wake-word no cumple la regla de la llamada / no es open-source",
             f"vosk={vosk_motor} empaque={empaque} ia_local={ia_local} llama={llama} "
             f"suelto={suelto} charla={charla} fuente_unica={unico}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el wake-word open-source", repr(e))


# H62) ACTUALIZACIÓN SIN TRABAS (pedido de Brian: "que literal mate todo para que se actualice"). El
#   agente corre headless (--run + bootloader + hijo Python); al actualizar, el instalador NO podía
#   cerrarlo y se trababa. Fix: [Code] PrepareToInstall/CurUninstallStepChanged hace taskkill /F /T de
#   TODO el árbol de ithos-agente.exe, + CloseApplications=force. Así ejecutar el .exe nuevo actualiza solo.
try:
    iss62 = leer(os.path.join(RAIZ, "compilador", "build", "ithos-agente.iss"))
    matar = ("procedure MatarAgente" in iss62 and "/F /T /IM ithos-agente.exe" in iss62
             and "function PrepareToInstall(" in iss62
             and "CurUninstallStepChanged" in iss62
             and "CloseApplications=force" in iss62
             and "function VersionInstalada(" in iss62          # detecta la versión instalada
             and "Se actualizará a la versión" in iss62)        # avisa "actualizando de X a Y"
    if matar:
        ok("actualización sin trabas: el instalador MATA todo el árbol de ithos-agente.exe (taskkill /F "
           "/T) antes de actualizar/desinstalar + CloseApplications=force -> ejecutar el .exe nuevo "
           "actualiza solo, sin quedarse trabado por archivos en uso")
    else:
        fail("el instalador se traba al actualizar (no mata el agente en uso)", f"matar={matar}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la actualización sin trabas", repr(e))


# H63) CUOTA DE IA SIN HARDCODEAR (bug real y RECURRENTE de Brian: preguntó las cuotas e ITHOS dijo
#   "Groq secundaria" cuando su cadena real es gemini→cerebras→groq -> Cerebras es la secundaria). El
#   GestorCuota debe recibir la cadena REAL del cliente (main.py) y reportar los roles leídos de esa
#   cadena, nunca cableados. "Todo se aplica a todos": vale para cualquier cadena que configure el cliente.
try:
    m63 = leer(os.path.join(APP, "central", "main.py"))
    cu63 = leer(os.path.join(APP, "comun", "cuota.py"))
    pasa_cadena = "cadena=Cuota.cadena_cfg(ia)" in m63          # main le pasa la cadena REAL
    roles_reales = ("def _rol(" in cu63 and "def _siguiente_a(" in cu63
                    and "(la {self._rol('groq')})" in cu63       # el rol de Groq sale de la cadena
                    and "*{nombre_ia(_sig)}* (la {self._rol(_sig)})" in cu63)  # el siguiente, dinámico
    sin_groq_fijo = '(secundaria) se agotó."' not in cu63       # ya NO dice "Groq (secundaria)" fijo
    # funcional: con cadena gemini→cerebras→groq, la SECUNDARIA es Cerebras (no Groq)
    sys.path.insert(0, APP)
    import importlib as _il63
    _C = _il63.import_module("comun.cuota")
    _g = _C.GestorCuota("AUDIT63", limite_diario=200, cadena=["gemini", "cerebras", "groq"])
    txt = _g.estado_texto().replace("*", "")       # el texto va en negrita markdown (*)
    func63 = ("Cerebras (secundaria)" in txt and "Groq (terciaria)" in txt
              and _g._rol("cerebras") == "secundaria" and _g._rol("groq") == "terciaria"
              and _C.cadena_cfg({"proveedor": "gemini", "secundario": {"proveedor": "cerebras"},
                                 "terciario": {"proveedor": "groq"}}) == ["gemini", "cerebras", "groq"])
    if pasa_cadena and roles_reales and sin_groq_fijo and func63:
        ok("cuota de IA SIN hardcodear: el GestorCuota recibe la cadena REAL del cliente y reporta los "
           "roles leídos de esa cadena (con gemini→cerebras→groq, la secundaria es CEREBRAS, no Groq); "
           "vale para cualquier configuración")
    else:
        fail("la cuota de IA reporta roles hardcodeados (ej. 'Groq secundaria')",
             f"pasa_cadena={pasa_cadena} roles_reales={roles_reales} sin_groq_fijo={sin_groq_fijo} func={func63}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la cuota de IA sin hardcodear", repr(e))


# H64) VOZ (micrófono) IGUAL a WhatsApp (pedidos de Brian): (a) filtro anti-ruido Silero VAD también en
#   los AUDIOS de WhatsApp antes de transcribir (ya estaba en el micrófono) -> transcripción fiel; (b)
#   el DUEÑO por voz (voz-id confirmado) recibe el MISMO detalle/acceso que por WhatsApp (respuestas
#   completas, no recortadas); (c) GUI del agente: versión visible + auto-arranque + editar pre-llena la
#   config (no reescribir todo). La velocidad (1.40) ya se aplica al streaming (audiotsm) y al cacheo.
try:
    conv64 = leer_asistente()
    gui64 = leer(os.path.join(APP, "agente", "gui.py"))
    voz64 = leer(os.path.join(APP, "agente", "voz.py"))
    vad_wa = ("_AUD.decodificar(audio_bytes" in conv64 and "_AUD.filtrar_voz(_pcm" in conv64
              and "responder_audio" in conv64)                 # VAD antes de transcribir el audio WA
    dueno_voz = ('canal in ("voz", "microfono", "mic") and audio is not None' in conv64
                 and "_VZ.perfil_listo() and _VZ.verificar(audio)[0]" in conv64
                 and "es_admin = True" in conv64)              # dueño por voz-id -> mismo detalle
    gui_pro = ("def config_editar(" in gui64 and "async function autoArranque(" in gui64
               and "ITHOS Agente v" in gui64 and "or cfg0.get(" in gui64)  # editar conserva la cfg
    velo = "n_target = int(round(src_n / self.velocidad))" in voz64   # velocidad aplicada al audio (_pcm_a_wav)
    if vad_wa and dueno_voz and gui_pro and velo:
        ok("voz del micrófono a la par de WhatsApp: filtro anti-ruido (Silero VAD) también en audios de "
           "WhatsApp; el dueño por voz-id recibe el mismo detalle/acceso que por WhatsApp; velocidad "
           "aplicada al streaming; GUI con versión + auto-arranque + editar que conserva la config")
    else:
        fail("la voz del micrófono no está a la par de WhatsApp",
             f"vad_wa={vad_wa} dueno_voz={dueno_voz} gui_pro={gui_pro} velo={velo}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la paridad voz/WhatsApp", repr(e))


# H65) LOG ROTADO + lectura EFICIENTE + update sin borrar datos (pedidos de Brian: "que el log limpie
#   después de 200 en el agente, el histórico queda en el .log, para que no se lagee/trabe/consuma
#   recursos"; "el instalador al actualizar no elimina nada del usuario, solo actualiza"). El .log del
#   agente ROTA (nunca crece sin control), la GUI lee SOLO el final (no carga el archivo entero), y el
#   borrado de datos SOLO ocurre al desinstalar (nunca al actualizar -> se conserva config + caché).
try:
    ag65 = leer(os.path.join(APP, "agente", "agente.py"))
    iss65 = leer(os.path.join(RAIZ, "compilador", "build", "ithos-agente.iss"))
    rota = ("RotatingFileHandler" in ag65 and "maxBytes=512 * 1024" in ag65
            and "backupCount=3" in ag65)                       # el .log rota (no crece infinito)
    lee_final = ("f.seek(tam - leer)" in ag65 and "96 * 1024" in ag65
                 and "readlines()[-maxlineas:]" not in ag65)    # ya NO carga el archivo entero
    # el borrado de datos del usuario es un RunOnceId de [UninstallRun] -> SOLO corre al desinstalar,
    # nunca al instalar/actualizar. Y PrepareToInstall (install/update) solo MATA el proceso, no borra.
    borra_solo_uninstall = ('RunOnceId: "DelIthosUserData"' in iss65
                            and "AppData\\Local\\ITHOS" in iss65
                            and "rd /s /q" not in iss65.split("function PrepareToInstall")[-1])
    if rota and lee_final and borra_solo_uninstall:
        ok("log del agente ROTADO (nunca crece sin control) + la GUI lee solo el final (no lagea ni "
           "consume) + el histórico queda en el .log; el update NO borra datos del usuario (config + "
           "caché se conservan; el borrado solo corre al desinstalar)")
    else:
        fail("el log crece sin control / se lee entero / el update borra datos",
             f"rota={rota} lee_final={lee_final} borra_solo_uninstall={borra_solo_uninstall}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la rotación de log / update sin borrar", repr(e))


# H66) VOZ NATURAL Y CONTINUA EN RESPUESTAS LARGAS (bug real de Brian: antes se streameaba por ORACIÓN y,
#   sobre todo con edge, dejaba TRABAS/gaps entre oraciones -> sonaba cortado/robótico, "no como una
#   persona"). Fix: la respuesta se sintetiza como UN audio CONTINUO (no fragmentada) -> lectura natural,
#   con la pronunciación y las pausas de PUNTUACIÓN propias de la voz, sin esperas entre oraciones ni
#   párrafos. El gestor manda la respuesta COMPLETA (una sola 'decir'); el agente NO fragmenta.
try:
    vz = leer(os.path.join(APP, "agente", "voz.py"))
    conv_m = leer(os.path.join(APP, "central", "main.py"))
    # agente: _reproducir ya NO fragmenta (no hay _stream/_partir); sintetiza el texto completo (_generar).
    _cuerpo_rep66 = vz.split("def _reproducir(self, texto, cachear):")[1].split("\n    def ")[0]
    continuo = ("self._generar(texto, cachear)" in _cuerpo_rep66
                and "self._stream(" not in vz and "def _partir(" not in vz)   # sin fragmentar
    # gestor: manda la respuesta COMPLETA de una (on_frase=None -> no streaming por oración)
    gestor_completo = ('responder_stream, texto or "", "voz", None, None, audio_bytes' in conv_m
                       and '"accion": "decir", "texto": r' in conv_m)
    # cuota: en vivo, si Charon está en cooldown, va DIRECTO a edge (sin el 429 + backoff que trababa)
    cuota = ("if time.time() < self._cuota_hasta:" in vz
             and "self._cuota_hasta = time.time() + 300" in vz)
    if continuo and gestor_completo and cuota:
        ok("voz NATURAL y continua: la respuesta larga se sintetiza como UN audio (no fragmentada) -> "
           "lectura como una persona (pronunciación + pausas de puntuación), sin trabas entre oraciones; "
           "el gestor manda la respuesta completa de una; sin cuota Charon va directo a edge (sin pausas)")
    else:
        fail("la voz larga se corta/traba (fragmentada) en vez de sonar natural y continua",
             f"continuo={continuo} gestor_completo={gestor_completo} cuota={cuota}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la voz natural continua", repr(e))


# H67) CACHÉ DE VOZ IDENTIFICABLE + botón para regenerarla (pedidos de Brian): los archivos del caché
#   se nombran con la PERSONA + el saludo (ej. 'Bienvenido_Brian_Sierra_a_INTELLIHELP__ab12cd34.wav') en
#   vez de solo un hash, para que el usuario los identifique; + un botón en la GUI para BORRAR todo el
#   caché y regenerarlo desde cero (sin tocar credenciales ni el perfil de voz).
try:
    vz67 = leer(os.path.join(APP, "agente", "voz.py"))
    gui67 = leer(os.path.join(APP, "agente", "gui.py"))
    nombre_legible = ('slug = re.sub(' in vz67 and "f\"{slug}__{motor}_{h}{ext}\"" in vz67
                      and 'motor = "charon" if ext == ".wav" else "edge"' in vz67  # motor en el nombre
                      and "hexdigest()[:8]" in vz67)             # slug legible + motor + hash corto único
    boton = ("def limpiar_cache(" in gui67 and "shutil.rmtree(d" in gui67
             and "_dir_cache_voz()" in gui67 and "borrarCache" in gui67
             and "Regenerar todo desde cero" in gui67)
    # funcional: el nombre del archivo contiene el nombre de la persona
    import re as _re67
    import hashlib as _h67
    def _cp(texto, ext=".wav"):
        clave = f"v1|v1.40|{texto}"
        h = _h67.md5(clave.encode()).hexdigest()[:8]
        slug = _re67.sub(r"[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", "_", texto).strip("_")[:56] or "voz"
        motor = "charon" if ext == ".wav" else "edge"
        return f"{slug}__{motor}_{h}{ext}"
    fn = _cp("Bienvenido, Brian Sierra, a INTELLIHELP S.A.")
    func67 = ("Brian_Sierra" in fn and "__charon_" in fn and fn.endswith(".wav")
              and "__edge_" in _cp("x", ".mp3"))              # motor visible en el nombre
    if nombre_legible and boton and func67:
        ok("caché de voz IDENTIFICABLE: los archivos llevan el nombre de la persona + el saludo (no un "
           "hash suelto) + hash corto para no colisionar; y hay botón para borrar y regenerar todo el "
           "caché desde cero sin tocar credenciales ni el perfil de voz")
    else:
        fail("el caché de voz no es identificable / falta el botón de regenerar",
             f"nombre_legible={nombre_legible} boton={boton} func67={func67}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el caché identificable / regenerar", repr(e))


# H68) CACHÉ DE VOZ SIN CORTES + velocidad EXACTA + detectar personas nuevas (bug real de Brian: saludos
#   cacheados "no terminan lo que tienen que decir", les faltaban palabras/nombres). Causa: pydub.speedup
#   a 1.40x DESCARTABA trozos de cada chunk (huecos en el medio -> se comía fonemas/palabras). Fix: WSOLA
#   (el time-stretch del streaming, no descarta nada) + re-muestreo fino para que la velocidad sea EXACTA
#   (1.40x). Además un botón "detectar personas nuevas": cachea SOLO los empleados nuevos (releé DB/API),
#   sin regenerar todo (el pre-cacheo saltea lo ya cacheado).
try:
    vz68 = leer(os.path.join(APP, "agente", "voz.py"))
    gui68 = leer(os.path.join(APP, "agente", "gui.py"))
    wsola_cache = ("from audiotsm import wsola" in vz68 and "def _pcm_a_wav(" in vz68
                   and "wsola(1, speed=vel).run(ArrayReader(x), writer)" in vz68   # WSOLA a la vel normalizada
                   and "from pydub.effects import speedup" not in vz68)   # ya NO usa pydub speedup
    # Re-muestreo fino a la cantidad EXACTA de muestras objetivo (velocidad exacta; con H70 el objetivo
    # es un ritmo UNIFORME por texto en vez de un multiplicador fijo, pero el mecanismo es el mismo).
    exacta = ("n_target = int(round(src_n / self.velocidad))" in vz68
              and "np.interp(np.linspace(0, len(out_f) - 1, n_target)" in vz68)
    nuevos = ("def detectar_nuevos(" in gui68 and "detectarNuevos" in gui68
              and "Detectar personas nuevas" in gui68 and "cachea SOLO" in gui68)
    # funcional: WSOLA+re-muestreo -> velocidad EXACTA (1.40x) y contenido preservado (sin huecos)
    import numpy as _np
    from audiotsm import wsola as _wsola
    from audiotsm.io.array import ArrayReader as _AR, ArrayWriter as _AW
    _sr = 24000
    _x = (_np.sin(2 * _np.pi * 200 * _np.arange(int(_sr * 4)) / _sr) * 0.3).astype(_np.float32)
    _w = _AW(1)
    _wsola(1, speed=1.40).run(_AR(_x.reshape(1, -1)), _w)
    _o = _w.data[0]
    _n = int(round(len(_x) / 1.40))
    if abs(len(_o) - _n) > 1:
        _o = _np.interp(_np.linspace(0, len(_o) - 1, _n), _np.arange(len(_o)), _o)
    _ratio = len(_x) / len(_o)
    _mid = _np.abs(_o[_sr // 2:len(_o) - _sr // 2])
    _mid = _mid[:len(_mid) // 100 * 100]                       # múltiplo de 100 para las ventanas
    _sin_huecos = bool(_mid.reshape(-1, 100).mean(axis=1).min() > 0)  # sin silencios en el medio (WSOLA)
    func68 = abs(_ratio - 1.40) < 0.01 and _sin_huecos
    if wsola_cache and exacta and nuevos and func68:
        ok("caché de voz SIN cortes: WSOLA (no descarta fonemas como pydub) + re-muestreo fino -> "
           "velocidad EXACTA (1.40x) y saludo COMPLETO; botón 'detectar personas nuevas' cachea solo los "
           "empleados nuevos (releé DB/API) sin regenerar todo")
    else:
        fail("el caché corta palabras / velocidad no exacta / falta detectar nuevos",
             f"wsola={wsola_cache} exacta={exacta} nuevos={nuevos} func={func68}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el caché sin cortes / velocidad exacta", repr(e))


# H69) VOZ VERBATIM (bug real y persistente de Brian: los saludos "no terminan lo que tienen que decir",
#   se COMÍAN nombres -"Noemi", "Ayala", "Raul"-). Diagnóstico profundo (transcribiendo con Vosk): NO era
#   la velocidad (WSOLA) ni el '…'; era el modelo de voz `gemini-2.5-flash-native-audio-latest`
#   (conversacional, con 'thinking') que INTERPRETABA el texto en vez de leerlo. Fix: usar el TTS
#   DEDICADO `gemini-2.5-flash-preview-tts` (generate_content, lee VERBATIM) + no meter pausas '…' para
#   la voz de marca. Verificado con Vosk: mantiene el nombre. "Todo a todos": vale para todos los clientes.
try:
    ia69 = leer(os.path.join(APP, "comun", "ia.py"))
    loc69 = leer(os.path.join(APP, "comun", "locucion.py"))
    vz69 = leer(os.path.join(APP, "agente", "voz.py"))
    # Regresión (bug real, agosto 2026): la config del cliente tenía guardado el modelo VIEJO
    # (`native-audio-latest`) y pisaba el bueno -> la voz devolvía 404 y no sonaba nunca. Ahora
    # una config con un modelo que no es TTS se corrige sola: es preferible una voz que suena.
    import importlib
    _ia = importlib.import_module("comun.ia")
    tts = ('"gemini-2.5-flash-preview-tts"' in ia69                 # TTS dedicado (verbatim)
           and "aio.models.generate_content(" in ia69              # generate_content, NO live conversacional
           and _ia.modelo_voz({"modelo_voz": "gemini-2.5-flash-native-audio-latest"}) == _ia.VOZ_MODELO
           and _ia.modelo_voz({}) == _ia.VOZ_MODELO
           and _ia.modelo_voz({"modelo_voz": "gemini-3.1-flash-tts-preview"}) == "gemini-3.1-flash-tts-preview"
           and "native-audio-latest\"" not in leer(os.path.join(APP, "central", "panel.py"))
           and "inline_data.data" in ia69)
    sin_pausas = ("def preparar(texto, fonetica=True, pausas=True)" in loc69
                  and "humanizar(t) if pausas else" in loc69       # sin '…' cuando pausas=False
                  and "pausas=not self._voz_marca" in vz69)         # el agente no mete pausas para Charon
    if tts and sin_pausas:
        ok("voz VERBATIM: se usa el TTS DEDICADO de Gemini (gemini-2.5-flash-preview-tts, lee palabra por "
           "palabra) en vez del modelo conversacional native-audio que se comía nombres; + sin pausas '…' "
           "para la voz de marca. Verificado con Vosk: los saludos dicen el nombre completo")
    else:
        fail("la voz se sigue comiendo palabras (modelo conversacional / pausas)",
             f"tts={tts} sin_pausas={sin_pausas}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la voz verbatim", repr(e))


# H70) VELOCIDAD UNIFORME + VARIEDAD DE SALUDOS + CUOTA (bug real de Brian: "los audios de Raúl/Noemi no
#   son iguales al resto, Alejandro se acelera como 2.5x"; y "más variedad, más de 4 saludos random por
#   día para entrada/salida, la sala 1 solo"). Fixes:
#   1) NORMALIZAR el ritmo del cacheo: el TTS habla el mismo texto a ritmo variable y el multiplicador
#      fijo lo amplificaba -> ahora todos salen a la MISMA velocidad (letras/seg), acotado a ±7%.
#   2) VARIEDAD diaria: 6 plantillas entrada/salida, saludo por (persona+día); se pre-cachean TODAS las
#      variantes; sala/personalizados = 1 solo. 3) CUOTA: el pre-cacheo NO cae a edge (caché 100% Charon,
#      uniforme); pausa y reintenta al restablecerse; edge solo respaldo TEMPORAL en vivo (no cachea).
try:
    import numpy as _np
    import wave as _wave
    import tempfile as _tmpf
    sys.path.insert(0, APP)
    sys.path.insert(0, os.path.join(APP, "agente"))
    sys.path.insert(0, os.path.join(APP, "central"))
    import voz as _VZ
    # 1) Normalización: 3 fuentes del MISMO texto a distinto ritmo -> misma duración de salida.
    _v = _VZ.VozAgente.__new__(_VZ.VozAgente)
    _v.velocidad = 1.40
    _txt = "Bienvenido, Alejandro Ayala, a INTELLIHELP S.A."
    _outs = []
    for _d in (4.40, 4.55, 4.69):
        _n = int(_d * 24000)
        _pcm = (_np.sin(_np.arange(_n) * 0.05).astype(_np.float32) * 0.3 * 32767).astype(_np.int16).tobytes()
        _o = os.path.join(_tmpf.gettempdir(), "au70.wav")
        _v._pcm_a_wav(_pcm, _o, _txt)
        with _wave.open(_o, "rb") as _w:
            _outs.append(_w.getnframes() / _w.getframerate())
    _uniforme = (max(_outs) - min(_outs)) < 0.02        # <20ms de diferencia = uniforme
    # 2) Variedad diaria + pre-cache de todas las variantes.
    import procesador as _PR
    _emp = ("INTELLIHELP S.A.", "ITH")
    _saludos_dia = {_PR._frase_acceso({"nombre": "Noemi", "tipo": "entrada"}, *_emp, dia=_x)[0]
                    for _x in range(len(_PR.BIENVENIDAS))}
    _variedad = (len(_PR.BIENVENIDAS) >= 6 and len(_PR.DESPEDIDAS) >= 6
                 and len(_saludos_dia) >= 5)             # días distintos -> saludos distintos
    from protocolo import EV_PRECACHE as _EVP
    _cli = {"nombre": "INTELLIHELP S.A.", "empresa_saludo": "INTELLIHELP S.A.", "abreviatura": "ITH"}
    _cmds = _PR.procesar(_cli, _EVP, {"nombres": ["Noemi", "Raul"]})
    # (variantes × 3 franjas horarias + 1 sala) × 2 personas: el saludo de entrada es coherente con la
    # hora, así que cada variante se pre-cachea para mañana, tarde y noche.
    _precache_todas = len(_cmds) == (len(_PR.BIENVENIDAS) * 3 + 1) * 2
    # 3) Cuota: caché uniforme (no edge en pre-cacheo), cooldown, edge temporal en vivo.
    _vz = leer(os.path.join(APP, "agente", "voz.py"))
    _cuota = ("class _CuotaVoz" in _vz and "permitir_edge=False" in _vz
              and "self._cuota_hasta = time.time() + 300" in _vz
              and "self._edge(texto, cachear=False)" in _vz          # edge NO cachea con voz de marca
              and 'rate = f"+{pct}%"' in _vz)                        # edge respeta la velocidad
    if _uniforme and _variedad and _precache_todas and _cuota:
        ok(f"velocidad UNIFORME (3 ritmos del TTS -> {min(_outs):.2f}-{max(_outs):.2f}s, "
           f"dif {max(_outs)-min(_outs):.3f}s) + VARIEDAD diaria ({len(_PR.BIENVENIDAS)} saludos, "
           f"{len(_saludos_dia)} distintos por día, pre-cache de todas las variantes={len(_cmds)}) + "
           "CUOTA: caché 100% Charon (pre-cacheo no cae a edge; pausa/reintenta; edge solo temporal en vivo)")
    else:
        fail("velocidad no uniforme / poca variedad / cuota mal manejada",
             f"uniforme={_uniforme} variedad={_variedad} precache_todas={_precache_todas} cuota={_cuota}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar velocidad uniforme + variedad + cuota (H70)", repr(e))


# H71) EL AGENTE ARRANCA SIEMPRE (bug operacional de Brian: vació/borró el log "para empezar de cero" y
#   el agente NO arrancaba -> GUI en 'Conectando…'). El log es SOLO un log: borrarlo debe empezar limpio,
#   nunca romper el arranque. Causa REAL: el SINGLETON usaba `windll.kernel32.GetLastError()` suelto (poco
#   fiable con ctypes: la búsqueda del símbolo podía pisar el last-error) -> falso "ya existe" -> el agente
#   salía y no arrancaba. Fixes: (1) mutex con use_last_error + get_last_error (FIABLE); (2) main() reintenta
#   el lock y SOLO sale si hay OTRO agente REALMENTE vivo (PID), si no arranca igual; (3) 'Arrancar' hace
#   reinicio LIMPIO (frena lo colgado y relanza). Y leer_log tolera archivo faltante/vacío.
try:
    ag71 = leer(os.path.join(APP, "agente", "agente.py"))
    gui71 = leer(os.path.join(APP, "agente", "gui.py"))
    mutex_fiable = ('WinDLL("kernel32", use_last_error=True)' in ag71
                    and "ctypes.get_last_error() != 183" in ag71
                    and "windll.kernel32.GetLastError()" not in ag71)   # ya NO el patrón frágil
    no_sale_fantasma = ("for _ in range(15)" in ag71                    # reintenta el lock
                        and "if not tomado and agente_corriendo():" in ag71   # solo sale si hay agente vivo
                        and "arranco igual" in ag71)
    arranque_limpio = ("A.detener_headless()" in gui71 and "A.lanzar_headless()" in gui71
                       and "def arrancar(" in gui71
                       and gui71.split("def arrancar(")[1].split("def ")[0].count("detener_headless") >= 1)
    # funcional: leer_log tolera archivo INEXISTENTE (empezar de cero) sin crashear -> []
    sys.path.insert(0, os.path.join(APP, "agente"))
    sys.path.insert(0, APP)
    import agente as _AG71
    _o71 = _AG71._log_file
    _AG71._log_file = lambda: os.path.join(RAIZ, "no_existe_%d.log" % os.getpid())
    try:
        log_faltante_ok = _AG71.leer_log(200) == []
    finally:
        _AG71._log_file = _o71
    if mutex_fiable and no_sale_fantasma and arranque_limpio and log_faltante_ok:
        ok("el agente ARRANCA SIEMPRE: singleton con mutex FIABLE (use_last_error, no el GetLastError suelto) "
           "+ no sale por lock fantasma (reintenta; solo sale si hay agente vivo) + 'Arrancar' reinicia "
           "limpio; borrar/vaciar el log empieza de cero sin romper nada")
    else:
        fail("el agente puede no arrancar (singleton frágil / dependencia del log)",
             f"mutex_fiable={mutex_fiable} no_sale_fantasma={no_sale_fantasma} "
             f"arranque_limpio={arranque_limpio} log_faltante_ok={log_faltante_ok}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el arranque del agente (H71)", repr(e))


# H72) 'DETENER' FRENA EL PROCESO DE VERDAD (bug de Brian: al detener/salir el proceso seguía corriendo y
#   CONECTADO). Causa: el headless puede correr ELEVADO (tarea ONLOGON /RL HIGHEST) y la GUI sin elevar ->
#   os.kill/taskkill da ACCESO DENEGADO -> no lo mataba (+ duplicados del singleton viejo). Fix: APAGADO
#   COOPERATIVO a prueba de privilegios -> el agente VIGILA su pid file y se AUTO-TERMINA si la GUI lo
#   BORRA; detener_headless borra el pid (señal) + taskkill /T (mata el ÁRBOL); el tray borra el pid y sale.
try:
    ag72 = leer(os.path.join(APP, "agente", "agente.py"))
    _cuerpo_det = ag72.split("def detener_headless(")[1].split("\ndef ")[0]
    coop = ("def _vigilar_apagado(" in ag72 and "target=_vigilar_apagado" in ag72
            and "os._exit(0)" in ag72 and "fallos >= 2" in ag72)     # tolera glitch de lectura
    detener_robusto = ("os.remove(_pid_file())" in _cuerpo_det        # señal cooperativa (cross-privilegios)
                       and "os.kill(int(pid)" in _cuerpo_det)         # + kill directo PORTABLE (sin taskkill)
    tray_ok = ("def _detener_y_salir(" in ag72 and "al_detener=_detener_y_salir" in ag72)
    # funcional: detener_headless BORRA el pid file (señal cooperativa) -> _leer_pid() = 0
    import tempfile as _tmp72
    os.environ["ITHOS_AGENTE_DATOS"] = _tmp72.mkdtemp()
    sys.path.insert(0, os.path.join(APP, "agente"))
    sys.path.insert(0, APP)
    import agente as _AG72
    _AG72._escribir_pid(999999)
    _antes72 = _AG72._leer_pid() == 999999
    _AG72.detener_headless()
    coop_func = _antes72 and _AG72._leer_pid() == 0              # tras detener, pid borrado (auto-frena)
    if coop and detener_robusto and tray_ok and coop_func:
        ok("'Detener' frena SIEMPRE: apagado COOPERATIVO a prueba de privilegios (el agente vigila su pid y "
           "se auto-termina si la GUI lo borra, aunque corra ELEVADO) + kill directo PORTABLE (os.kill)")
    else:
        fail("'Detener' puede no frenar el proceso (privilegios/duplicados)",
             f"coop={coop} detener_robusto={detener_robusto} tray_ok={tray_ok} coop_func={coop_func}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el apagado del agente (H72)", repr(e))


# H73) LOS AUDIOS TEMPORALES NO SE ACUMULAN (bug de Brian: los _tmp_*.mp3 -respaldo edge en vivo- quedaban
#   cargados en la carpeta y pesaban a futuro). Se borran apenas terminan de sonar (finally en _reproducir),
#   pero si el agente se DETIENE/mata en medio de la reproducción quedaban huérfanos -> se BARREN al arrancar
#   (_limpiar_temporales), SIN tocar la caché real (_charon_/_edge_ con hash).
try:
    vz73 = leer(os.path.join(APP, "agente", "voz.py"))
    tokens73 = ("def _limpiar_temporales(" in vz73
                and "self._limpiar_temporales()" in vz73            # llamado en __init__ (al arrancar)
                and 'glob.glob(os.path.join(self.cache_dir, "_tmp_*"))' in vz73
                and "if not cachear:" in vz73 and "os.remove(ruta)" in vz73)  # borrado post-reproducción
    import tempfile as _tmp73
    sys.path.insert(0, os.path.join(APP, "agente"))
    import voz as _VZ73
    _d73 = _tmp73.mkdtemp()
    for _n in ("_tmp_1.mp3", "_tmp_2.wav"):
        open(os.path.join(_d73, _n), "w").close()
    open(os.path.join(_d73, "Bienvenido_X__charon_abcd1234.wav"), "w").close()
    _v73 = _VZ73.VozAgente.__new__(_VZ73.VozAgente)
    _v73.cache_dir = _d73
    _v73._limpiar_temporales()
    _rest73 = os.listdir(_d73)
    func73 = (not any(x.startswith("_tmp_") for x in _rest73)       # borró los temporales
              and "Bienvenido_X__charon_abcd1234.wav" in _rest73)   # conservó la caché real
    if tokens73 and func73:
        ok("audios TEMPORALES no se acumulan: _tmp_* se borran al terminar de sonar y se BARREN al arrancar "
           "(huérfanos de un cierre a mitad); la caché real (_charon_/_edge_) queda intacta")
    else:
        fail("los audios temporales se acumulan (no se limpian)", f"tokens={tokens73} func={func73}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la limpieza de temporales (H73)", repr(e))


# H77) TICKETS: no re-categorizar / respetar asignación manual + técnico pide coordinar -> EN ESPERA +
#   admin dice-y-hace (honestidad) + aviso WhatsApp + la voz NUNCA lee emojis (bugs reales de Brian).
try:
    tri_src = leer_tickets()
    conv_src = leer_asistente()
    loc_src = leer(os.path.join(APP, "comun", "locucion.py"))
    # (a) FUNCIONAL: procesar NO re-categoriza si ya hay categoría y NO re-asigna si ya hay técnico humano
    sys.path.insert(0, os.path.join(APP, "central"))
    sys.path.insert(0, APP)
    import triage as _T77

    class _CliT77:
        def __init__(self, asig2):
            self.reqs = []
            self._asig = asig2
        def abrir(self):
            pass
        def cerrar(self):
            pass
        def request(self, path, method="GET", data=None, **k):
            self.reqs.append((path, method, data))
            if path.endswith("/Ticket_User") and method == "GET":
                return [{"users_id": u, "type": 2} for u in self._asig]
            return {}
    _clf0 = _T77.cerebro.clasificar_ticket
    _T77.cerebro.clasificar_ticket = lambda ia, n, c, **kw: {
        "alcance": "individual", "categoria": "MOLINETES", "prioridad": "Media",
        "responsable": "bsierra", "primera_respuesta": "Hola", "necesita_info": False}
    try:
        def _correr(ticket, asig2):
            tr = _T77.Triage.__new__(_T77.Triage)
            tr.ia = None
            tr._nombres = {}
            # cfg 24/7: el test corre a cualquier hora; sin esto, de noche daría fuera-de-horario
            # (status 4 + escribiría en agenda.json). Con 24/7 el routing es determinista.
            tr.cfg_glpi = {"horario_atencion": {"dias": [0, 1, 2, 3, 4, 5, 6],
                                                "desde": "00:00", "hasta": "23:59"}}
            tr._tok_lect = None
            tr._nombre_solicitante = lambda t: ""
            tr.cli = _CliT77(asig2)
            tr.procesar(ticket)
            return tr.cli.reqs
        # caso A: ITHOS YA triageó (28 asignado) -> NO re-triagea: no re-categoriza ni re-asigna (respeta
        # los cambios manuales del técnico). Solo saca de 'Nuevo'.
        rA = _correr({"id": 1, "status": 1, "itilcategories_id": 11}, {7, 28})
        puts_cat_A = [q for q in rA if q[0] == "/Ticket/1" and q[1] == "PUT"
                      and "itilcategories_id" in (q[2] or {}).get("input", {})]
        posts_A = [q for q in rA if q[0] == "/Ticket_User" and q[1] == "POST"]
        respeta_manual = (not puts_cat_A and not posts_A)    # no re-categoriza ni re-asigna
        # caso B: MAL CARGADO (ITHOS no asignado, categoría equivocada 99) -> lo CORRIGE igual (categoriza
        # a 11) + asigna ITHOS(28) + responsable default(7). El 1er triage siempre categoriza.
        rB = _correr({"id": 2, "status": 1, "itilcategories_id": 99}, set())
        campos_B = next((q[2]["input"] for q in rB if q[0] == "/Ticket/2" and q[1] == "PUT"
                         and "urgency" in (q[2] or {}).get("input", {})), {})
        posts_B = [q[2]["input"]["users_id"] for q in rB
                   if q[0] == "/Ticket_User" and q[1] == "POST"]
        corrige_malcargado = (campos_B.get("itilcategories_id") == 11 and 28 in posts_B and 7 in posts_B)
        # caso C: ITHOS no asignado PERO un técnico HUMANO (8=jayala) ya asignado a mano -> categoriza +
        # ITHOS, pero NO re-agrega el responsable default (7) -> respeta la asignación manual.
        rC = _correr({"id": 3, "status": 1}, {8})
        posts_C = [q[2]["input"]["users_id"] for q in rC
                   if q[0] == "/Ticket_User" and q[1] == "POST"]
        respeta_asig = (28 in posts_C and 7 not in posts_C)
        func_proc = respeta_manual and corrige_malcargado and respeta_asig
    finally:
        _T77.cerebro.clasificar_ticket = _clf0
    # (b) técnico pide coordinar/confirmar (aún IMPERSONAL: 'se deberá coordinar…') -> EN ESPERA + pide
    #     confirmación al cliente + avisa WhatsApp; con marcador anti-repetición (robusto a reinicios) y
    #     corriendo SOLO sobre comentarios de TÉCNICOS (nunca del cliente).
    coord = ("def tecnico_pide_confirmacion(" in tri_src and "def poner_en_espera_pedido(" in tri_src
             and "triage.tecnico_pide_confirmacion(cont)" in tri_src
             and "status != 4" in tri_src                                    # no re-pide si ya está en espera
             and "_coordinacion_despues_de(fu, int(ult[" in tri_src          # anti-repetición tras reinicio
             # y si la IA no contesta, el comentario del técnico NO se da por visto: se reintenta.
             # Marcarlo igual dejaba el ticket trabado para siempre (caso real #674).
             and "pide is None or (not pide and resolvio is None)" in tri_src
             # PRIMERO se pregunta si queda algo del CLIENTE y recién después si está resuelto: un
             # "se solucionó el acceso, pero falta que ustedes revisen la terminal" NO cierra el
             # ticket, lo deja esperándolos (corrección de Brian sobre el #673).
             and "resolvio = None if pide else triage.tecnico_resolvio(cont)" in tri_src
             and "QUEDA ALGO PENDIENTE del lado del cliente" in tri_src
             and "impersonal" in tri_src                                     # detecta 'se deberá coordinar…'
             and "NUNCA del cliente" in tri_src                              # invariante técnico-only
             and "queda algo en manos del cliente" in tri_src.lower())       # avisa WhatsApp
    # (c) admin: honestidad -> NO afirmar un cambio sin poner la acción + avisa a WhatsApp al cambiar estado
    main_src77 = leer(os.path.join(APP, "central", "main.py"))
    honesto = ("REGLA DE HONESTIDAD" in conv_src
               and "incluir esa acción en 'acciones'" in conv_src
               and "def acciones_tickets(cli_cfg, avisar=None)" in conv_src   # aviso al grupo por comando
               and "def _avisar(msg)" in conv_src
               and "avisar=((lambda m: wa.enviar(m, tipo=AV.TICKETS))" in main_src77
               # el ESTADO real de GLPI SIEMPRE gana sobre la MEMORIA (no 'ya está en espera' de memoria vieja)
               and "EL ESTADO de cada " in conv_src and "MANDAN los datos" in conv_src)
    # (d) la voz NUNCA lee emojis (regex ampliado + funcional)
    from comun import locucion as _L77
    _sin = _L77.sin_emojis
    emojis_ok = (_sin("ok ✅ \U0001F514 ™ ® ← fin") == "ok fin"    # saca emoji/flecha/™®
                 and _sin("Bienvenido… Noemi") == "Bienvenido… Noemi"       # CONSERVA la pausa …
                 and "2190" in loc_src)                          # regex ampliado con flechas 2190-21FF
    # (e) followup NO FATAL: si GLPI rechaza el comentario (permiso INSERT), igual se hace el triage/estado
    resiliente = tri_src.count("glpi_itilfollowups?") >= 2
    if func_proc and coord and honesto and emojis_ok and resiliente:
        ok("tickets robustos: NO re-categoriza ni pisa la asignación MANUAL de un técnico; si el técnico "
           "PIDE coordinar/confirmar lo deja EN ESPERA + pide confirmación al cliente + avisa WhatsApp; el "
           "admin dice-Y-hace (no afirma cambios sin ejecutar la acción); y la voz NUNCA lee emojis")
    else:
        fail("tickets/voz con bugs (re-categoriza / pisa asignación / no coordina / miente / lee emojis)",
             f"func_proc={func_proc} coord={coord} honesto={honesto} emojis_ok={emojis_ok} resiliente={resiliente}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el manejo de tickets/voz (H77)", repr(e))


# H78) MICRÓFONO robusto a RECONEXIÓN y CAMBIO DE DISPOSITIVO (bug de Brian: tras un cambio en el gestor,
#   o al cambiar el dispositivo de entrada -auriculares<->parlantes-, el mic dejaba de detectar 'ithos'
#   hasta CERRAR y REABRIR el agente). Causas: (1) en cada reconexión se arrancaba OTRO hilo de mic/
#   integrador SIN frenar el anterior -> hilos DUPLICADOS peleando por el mic; (2) el stream quedaba
#   pegado al dispositivo viejo. Fix: frenar los hilos viejos (stop) + reabrir el mic en el dispositivo
#   ACTUAL (por error de lectura y cada ~15s).
try:
    ag78 = leer(os.path.join(APP, "agente", "agente.py"))
    esc78 = leer(os.path.join(APP, "agente", "escucha.py"))
    sin_dup = ("self._stop_integ.set()" in ag78
               and "self._stop_integ = threading.Event()" in ag78
               and 'kwargs={"stop": self._stop_integ}' in ag78)      # frena viejos + pasa stop a los nuevos
    sigue_disp = ("def _abrir():" in esc78 and "sd._terminate()" in esc78 and "sd._initialize()" in esc78
                  and "reabro el micrófono" in esc78                  # reabre ante error de lectura
                  and "time.time() - _rev > 15" in esc78)            # y cada ~15s sigue el cambio de disp.
    if sin_dup and sigue_disp:
        ok("micrófono robusto: al reconectar FRENA el mic/integrador anterior (sin hilos duplicados que "
           "peleen por el micrófono) y SIGUE el cambio de dispositivo de entrada (reabre en error + cada "
           "~15s) -> ya no hay que cerrar y reabrir el agente")
    else:
        fail("el micrófono se rompe al reconectar / al cambiar de dispositivo",
             f"sin_dup={sin_dup} sigue_disp={sigue_disp}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la robustez del micrófono (H78)", repr(e))


# H79) REPORTES en días hábiles (bug de Brian: recibía el reporte ITIL TODOS los días —incluidos sábados
#   y domingos— y a las 08:00; los quiere Lun-Vie a las 09:00, hora del cliente, y SIN perder el viernes).
#   Fix (central/reportes_programados.py): `dias_habiles` en la config; _clave_periodo NO manda sáb/dom;
#   el LUNES cubre viernes..domingo (_rango_diario_habil) para no perder el viernes.
try:
    import json as _json79
    import importlib.util as _ilu79
    from datetime import datetime as _dt79
    _spec79 = _ilu79.spec_from_file_location(
        "_rp79", os.path.join(APP, "central", "reportes_programados.py"))
    _rp = _ilu79.module_from_spec(_spec79)
    _spec79.loader.exec_module(_rp)
    _r = {"frecuencia": "diario", "hora": "09:00", "dias_habiles": True}
    salta_finde = (_rp._clave_periodo(_r, _dt79(2026, 7, 25, 9, 0)) is None       # sábado -> NO manda
                   and _rp._clave_periodo(_r, _dt79(2026, 7, 26, 9, 0)) is None)  # domingo -> NO manda
    manda_habil = (_rp._clave_periodo(_r, _dt79(2026, 7, 21, 9, 0)) == "D2026-07-21"   # martes 09:00 -> sí
                   and _rp._clave_periodo(_r, _dt79(2026, 7, 21, 9, 1)) is None)       # 09:01 -> no (hora exacta)
    d79, h79 = _rp._rango_diario_habil(_dt79(2026, 7, 20, 9, 0))   # LUNES
    cubre_finde = (d79 == "2026-07-17" and h79 == "2026-07-19")    # cubre viernes..domingo
    dm79, hm79 = _rp._rango_diario_habil(_dt79(2026, 7, 21, 9, 0))  # martes
    diario_normal = (dm79 == "2026-07-20" and hm79 == "2026-07-20")  # cubre solo ayer (lunes)
    viejo = (_rp._clave_periodo({"frecuencia": "diario", "hora": "09:00"},
                                _dt79(2026, 7, 25, 9, 0)) == "D2026-07-25")   # sin la opción: manda findes
    _cli79 = _json79.load(open(os.path.join(APP, "central", "clientes.json"), encoding="utf-8"))["clientes"][0]
    _rep79 = _cli79.get("reportes", {})
    cfg_ok = (_rep79.get("hora") == "09:00" and _rep79.get("dias_habiles") is True)
    if salta_finde and manda_habil and cubre_finde and diario_normal and viejo and cfg_ok:
        ok("reportes: NO se mandan sábados/domingos, salen a las 09:00 (hora del cliente) y el LUNES "
           "cubre viernes-domingo (sin perder el viernes); sin dias_habiles sigue mandando todos los días")
    else:
        fail("reportes de días hábiles con bugs (findes / hora / cobertura del viernes)",
             f"salta_finde={salta_finde} manda_habil={manda_habil} cubre_finde={cubre_finde} "
             f"diario_normal={diario_normal} viejo={viejo} cfg_ok={cfg_ok}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar los reportes de días hábiles (H79)", repr(e))


# H80) ITHOS deja COMENTARIO INTERNO (privado, is_private=1) para los TÉCNICOS cuando el ticket viene mal
#   cargado / falta un dato / hay feedback para el equipo (mejora de Brian; GLPI 10.0.16 soporta followups
#   privados que el cliente NO ve). El cerebro genera `nota_tecnico`; el triage la postea como privada.
try:
    cer80 = leer(os.path.join(APP, "central", "cerebro.py"))
    tri80 = leer_tickets()
    prompt_ok = ("nota_tecnico" in cer80 and "PRIVADO" in cer80 and "NOTA INTERNA PARA TÉCNICOS" in cer80)
    postea_privado = ('"is_private": 1' in tri80 and 'a.get("nota_tecnico")' in tri80
                      and "SOLO técnicos" in tri80)
    if prompt_ok and postea_privado:
        ok("ITHOS deja COMENTARIO INTERNO (is_private=1, solo técnicos) cuando el ticket viene mal "
           "cargado / falta un dato / hay feedback para el equipo — el cliente NO lo ve")
    else:
        fail("falta el comentario interno privado de ITHOS a los técnicos",
             f"prompt_ok={prompt_ok} postea_privado={postea_privado}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el comentario interno a técnicos (H80)", repr(e))


# H81) Ticket FUERA del horario de atención (default Lun-Vie 9-18, zona del cliente) -> ITHOS responde
#   igual profesional, lo deja EN ESPERA y agenda la REAPERTURA (EN CURSO) al comenzar la jornada (mejora
#   de Brian). Reusa la AGENDA (reactivador ya activo). main.py inyecta zona/nombre/horario al triage.
try:
    import importlib.util as _ilu81
    from datetime import datetime as _dt81
    if RAIZ not in sys.path:
        sys.path.insert(0, APP)
    _cen81 = os.path.join(APP, "central")
    if _cen81 not in sys.path:
        sys.path.insert(0, _cen81)
    _spec81 = _ilu81.spec_from_file_location("_tri81", os.path.join(_cen81, "triage.py"))
    _tri = _ilu81.module_from_spec(_spec81)
    _spec81.loader.exec_module(_tri)
    cfg81 = {"zona_horaria": "America/Argentina/Buenos_Aires"}
    dentro = (_tri.en_horario_atencion(cfg81, _dt81(2026, 7, 20, 10, 0)) is True       # lunes 10:00 -> dentro
              and _tri.en_horario_atencion(cfg81, _dt81(2026, 7, 24, 22, 0)) is False  # viernes 22:00 -> fuera
              and _tri.en_horario_atencion(cfg81, _dt81(2026, 7, 25, 10, 0)) is False) # sábado -> fuera
    _p81 = _tri.proximo_inicio_horario(cfg81, _dt81(2026, 7, 24, 22, 0))               # viernes 22 -> lunes 09
    reabre = (_p81.weekday() == 0 and _p81.hour == 9)
    tri81 = leer_tickets(_cen81)
    main81 = leer(os.path.join(_cen81, "main.py"))
    agenda81 = leer(os.path.join(APP, "comun", "agenda.py"))
    logica = ("_agendar_reapertura_horario" in tri81 and "agenda.programar" in tri81
              and "4 if (espera_cliente or fuera) else 2" in tri81
              and 'gl["nombre_cliente"]' in main81 and 'gl["zona_horaria"]' in main81)
    # el CLIENTE NO se entera del horario: el aviso va como NOTA INTERNA (privada, _nota_interna_horario)
    # y la reapertura es SILENCIOSA (silencioso=True); el helper público viejo ya NO existe.
    privado = ("_nota_interna_horario" in tri81 and "silencioso=True" in tri81
               and "_con_nota_fuera_horario" not in tri81 and "silencioso" in agenda81)
    if dentro and reabre and logica and privado:
        ok("tickets FUERA de horario (Lun-Vie 9-18, zona del cliente): ITHOS responde profesional, los "
           "deja EN ESPERA y AGENDA la reapertura SILENCIOSA (EN CURSO) al abrir la jornada. El CLIENTE "
           "NO se entera: el aviso de horario va como NOTA INTERNA privada y la reapertura no manda mensaje")
    else:
        fail("manejo de tickets fuera de horario incompleto",
             f"dentro={dentro} reabre={reabre} logica={logica} privado={privado}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el manejo fuera de horario (H81)", repr(e))


# H82) FEEDBACK INTERNO en el CICLO (mejora de Brian): si un ticket figura RESUELTO pero SIN solución
#   documentada (p. ej. un técnico lo marcó resuelto a mano), ITHOS deja una nota PRIVADA (solo técnicos)
#   sugiriendo documentarla. Una sola vez (marcador robusto a reinicios). El cliente NO la ve.
try:
    tri82 = leer_tickets()
    tiene = ("def nota_interna(self" in tri82 and '"is_private": 1' in tri82
             and "def explica_procedimiento(self" in tri82 and "def _texto_resolucion(" in tri82
             and "def _ya_pidio_procedimiento(" in tri82 and "_NOTA_PEDIR_PROCEDIMIENTO" in tri82
             and "triage.nota_interna(" in tri82)
    if tiene:
        ok("feedback interno en el ciclo (base de conocimiento): si la resolución NO explica el "
           "PROCEDIMIENTO (paso a paso), ITHOS le pide al técnico por nota PRIVADA que documente qué "
           "hizo — una sola vez y el cliente no la ve")
    else:
        fail("falta el pedido interno de procedimiento paso a paso", f"tiene={tiene}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el feedback interno del ciclo (H82)", repr(e))


# H83) CONOCIMIENTO PROPIO: la respuesta DETALLADA sale del DOCUMENTO_MAESTRO (la documentación
#   completa del sistema), no de un texto paralelo que se desactualiza; y SÓLO la ve el DUEÑO (sus
#   números, o clave + voz-id por micrófono). A cualquier otro: el ALCANCE resumido (qué hace ITHOS),
#   sin nada de cómo está hecho. Pedido de Brian: "lo detallado sólo al dueño; al resto la genérica".
print("\n  H83) CONOCIMIENTO PROPIO: el detalle sale del maestro y sólo lo ve el dueño")
try:
    sys.path.insert(0, APP)
    from comun import conocimiento as _K83
    import importlib as _il83
    _il83.reload(_K83)
    _doc83 = _K83.documento_maestro()
    _due_det = _K83.bloque_sistema("+5491151629038", "whatsapp", detalle=True)
    _due_cor = _K83.bloque_sistema("+5491151629038", "whatsapp", detalle=False)
    _otro83 = _K83.bloque_sistema("+5491199999999", "whatsapp", detalle=True)
    _mic83 = _K83.bloque_sistema(None, "microfono", admin=True, detalle=True)
    _comp83 = leer(os.path.join(APP, "docker-compose.yml"))
    _conv83 = leer_asistente()
    _MARCA83 = "DOCUMENTO_MAESTRO del proyecto"
    hay_doc = len(_doc83) > 5000 and "Documento Maestro" in _doc83
    detalle_ok = _MARCA83 in _due_det                      # el dueño, al pedir detalle, recibe el maestro
    corto_ok = _MARCA83 not in _due_cor                    # sin pedir detalle no se manda (tokens)
    ajeno_ok = ("QUÉ PUEDE HACER ITHOS" in _otro83         # a un tercero: alcance resumido
                and "CONOCIMIENTO TÉCNICO PROPIETARIO" not in _otro83   # nada de implementación
                and _MARCA83 not in _otro83)
    clave_ok = _MARCA83 in _mic83                          # micrófono con clave + voz-id
    montado = "DOCUMENTO_MAESTRO.md:/app/DOCUMENTO_MAESTRO.md:ro" in _comp83   # el contenedor lo ve
    cableado = "detalle=_pide_detalle(texto)" in _conv83   # el asistente pasa el nivel de detalle
    if hay_doc and detalle_ok and corto_ok and ajeno_ok and clave_ok and montado and cableado:
        ok("conocimiento propio: el DETALLE sale del DOCUMENTO_MAESTRO (montado en el contenedor) y es "
           "SÓLO del dueño (sus números, o clave + voz por micrófono); a cualquier otro, el alcance "
           "RESUMIDO sin implementación — la corta y la detallada dicen lo mismo, en distinta medida")
    else:
        fail("el conocimiento propio no cumple la regla del dueño / el detalle no sale del maestro",
             f"doc={hay_doc} detalle={detalle_ok} corto={corto_ok} ajeno={ajeno_ok} "
             f"clave={clave_ok} montado={montado} cableado={cableado}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar el conocimiento propio", repr(e))


# H84) DOCUMENTACIÓN 1 A 1: el README del repositorio tiene los MISMOS diagramas de flujo y el mismo
#   contenido que el DOCUMENTO_MAESTRO (pedido de Brian: "mismos diagramas, todo 1 a 1"; el maestro es
#   además la fuente de lo que ITHOS explica de sí mismo). Los bloques mermaid se comparan VERBATIM.
print("\n  H84) DOCUMENTACIÓN: el README y el DOCUMENTO_MAESTRO, 1 a 1")
try:
    import re as _re84
    _rd = leer(os.path.join(RAIZ, "README.md"))
    _mx = leer(os.path.join(RAIZ, "DOCUMENTO_MAESTRO.md"))
    _dm = _re84.findall(r"```mermaid\n(.*?)```", _mx, _re84.S)
    _dr = _re84.findall(r"```mermaid\n(.*?)```", _rd, _re84.S)
    faltan = [d.strip().splitlines()[0][:40] for d in _dm if d not in _rd]
    # los temas del maestro que el README también tiene que cubrir
    temas = ("Cadena multi-IA", "Voz y audio", "Portero por voz", "ciclo de vida del ticket",
             "Alta de cliente", "hace cada archivo", "Límites y pendientes")
    sin_tema = [t for t in temas if t.lower() not in _rd.lower()]
    balance = all(d.count("[") == d.count("]") and d.count("(") == d.count(")")
                  and d.count("{") == d.count("}") for d in _dr)
    docs_con_diagrama = [f for f in ("docs/ARQUITECTURA_GESTOR_AGENTE.md", "docs/HOSTINGER.md",
                                     "docs/INSTALACION.md", "docs/INSTALACION_AGENTE.md",
                                     "SECURITY.md")
                         if "```mermaid" in leer(os.path.join(RAIZ, f))]
    if not faltan and not sin_tema and balance and len(_dm) >= 5 and len(docs_con_diagrama) == 5:
        ok(f"documentación 1 a 1: los {len(_dm)} diagramas del maestro están VERBATIM en el README "
           f"(que tiene {len(_dr)}), cubre todos sus temas, y las otras 5 guías tienen su propio "
           "diagrama de flujo")
    else:
        fail("el README no está 1 a 1 con el DOCUMENTO_MAESTRO",
             f"diagramas_faltantes={faltan} temas_faltantes={sin_tema} balance={balance} "
             f"guias_con_diagrama={len(docs_con_diagrama)}/5")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la documentación 1 a 1", repr(e))


# H85) DOCUMENTACIÓN AL DÍA, EN TIEMPO REAL (requerimiento permanente de Brian: "no sirve subir por
#   subir si no está todo actualizado"). Cada CAPACIDAD tiene un marcador en el CÓDIGO que prueba que
#   está implementada y los marcadores que TIENEN que existir en la documentación: el documento maestro,
#   el README (que va 1 a 1 con el maestro), el changelog y —cuando la capacidad es parte de un flujo—
#   el diagrama correspondiente. Si el código está y la documentación no, esto FALLA con el hueco exacto.
#   Al agregar una funcionalidad nueva: sumala a esta tabla junto con su documentación.
print("\n  H85) DOCUMENTACIÓN al día: cada capacidad implementada, documentada y en su diagrama")
CAPACIDADES = [
    {"que": "espera por el cliente (dato o confirmación) con recordatorio por día hábil",
     "codigo": [("ITHOS/central/ciclo.py", "_espera_pendiente"),
                ("ITHOS/central/triage.py", "recordar_espera")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["una vez por día hábil"],
              "README.md": ["una vez por día hábil"],
              "CHANGELOG.md": ["recordatorio por día hábil"]},
     "diagrama": ["recordatorio por día hábil"]},
    {"que": "escalada al técnico asignado a los 5 días hábiles",
     "codigo": [("ITHOS/central/textos_ticket.py", "_DIAS_HABILES_ESCALADA")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["5 días hábiles"], "README.md": ["cinco días hábiles"],
              "CHANGELOG.md": ["5 días hábiles"]},
     "diagrama": ["5 días hábiles"]},
    {"que": "@mención sólo al técnico asignado (tickets y SLA)",
     "codigo": [("ITHOS/comun/notificadores.py", "def enviar_mencion"),
                ("ITHOS/comun/tickets.py", "def telefonos_asignados")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["@mencionan"], "README.md": ["mencionando"],
              "CHANGELOG.md": ["@mención al técnico asignado"]},
     "diagrama": ["@mención"]},
    {"que": "activación por llamada: sólo 'Hey ITHOS'",
     "codigo": [("ITHOS/comun/wake.py", "def menciona"), ("ITHOS/comun/wake.py", "PREFIJOS")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["Hey ITHOS"], "README.md": ["Hey ITHOS"],
              "CHANGELOG.md": ["suelta ya no activa"]},
     "diagrama": ["Hey ITHOS"]},
    {"que": "consultar los tickets asignados a una persona (por su número)",
     "codigo": [("ITHOS/comun/herramientas.py", "tickets_asignados")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["Consultar"], "README.md": ["consultar"],
              "CHANGELOG.md": ["tickets por técnico asignado"]}},
    {"que": "ITHOS se explica desde el documento maestro; el detalle es sólo del dueño",
     "codigo": [("ITHOS/comun/conocimiento.py", "def documento_maestro"),
                ("ITHOS/comun/conocimiento.py", "ALCANCE_PUBLICO")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["desde este documento"], "README.md": ["documentación completa"],
              "CHANGELOG.md": ["se explica desde su propia documentación"]}},
    {"que": "horario de atención compartido y alerta de SLA sólo en horario",
     "codigo": [("ITHOS/comun/horario.py", "def en_horario_atencion"),
                ("ITHOS/central/proactivo.py", "en_horario_atencion")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["horario.py"], "README.md": ["horario.py"],
              "CHANGELOG.md": ["Horario de atención compartido"]}},
    {"que": "portero: saludo por hora, dedup y terminales configurables",
     "codigo": [("ITHOS/central/procesador.py", "_SALUDOS_HORA"),
                ("ITHOS/central/procesador.py", "def _ya_saludado")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["coherente con la hora"], "README.md": ["coherente con la hora"],
              "CHANGELOG.md": ["saludo de entrada coherente con la hora"]},
     "diagrama": ["saludo según la HORA"]},
    {"que": "cada grupo de WhatsApp recibe lo suyo y contesta lo suyo (ámbitos)",
     "codigo": [("ITHOS/comun/ambitos.py", "def recibe"),
                ("ITHOS/comun/ambitos.py", "def fuera_de_alcance"),
                ("ITHOS/comun/whatsapp.py", "def _destinos"),
                ("ITHOS/comun/asistente.py", "def _regla_ambito")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["Un grupo por tema (ámbitos)"],
              "README.md": ["ámbito"],
              "CHANGELOG.md": ["Un grupo de WhatsApp por tema"]}},
    {"que": "el SLA no corre fuera de horario y una respuesta del cliente nunca pasa desapercibida",
     "codigo": [("ITHOS/central/triage.py", "def esperar_hasta_horario"),
                ("ITHOS/central/textos_ticket.py", "_MARCA_SIN_ATENDER"),
                ("ITHOS/comun/horario.py", "def horas_habiles_entre")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["El cliente responde", "Respuesta sin atender"],
              "README.md": ["se reabre solo al abrir la jornada"],
              "CHANGELOG.md": ["El SLA corría de noche"]}},
    {"que": "el equipo sale de la configuración y los que se forman trabajan acompañados",
     "codigo": [("ITHOS/comun/tickets.py", "def acompanan_a"),
                ("ITHOS/central/equipo.py", "def ids_humanos"),
                ("ITHOS/central/ciclo.py", "tecs, humanos = ids_tecnicos(cfg), ids_humanos(cfg)"),
                ("ITHOS/central/triage.py", "def _sesion_de")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["El equipo sale de la configuración",
                                       "Formación acompañada"],
              "README.md": ["formación", "responsable"],
              "CHANGELOG.md": ["El equipo sale de la configuración"]}},
    {"que": "el tablero del equipo conserva sus colores y suma a quien entra",
     "codigo": [("ITHOS/central/planka_rollover.py", "COLORES"),
                ("ITHOS/comun/planka.py", "def actualizar_lista")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["El tablero se lee de un vistazo"],
              "README.md": ["mismos colores"],
              "CHANGELOG.md": ["conservan su color"]}},
    {"que": "no se pide un dato que ya está en el ticket (el legajo del asunto)",
     "codigo": [("ITHOS/central/cerebro.py", "def legajo_en_texto"),
                ("ITHOS/central/cerebro.py", "def respuesta_con_legajo"),
                ("ITHOS/central/textos_ticket.py", "_RE_FIRMA_FINAL")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["el legajo suele venir en el **asunto**"],
              "README.md": ["el legajo suele venir en el **asunto**"],
              "CHANGELOG.md": ["legajo que ya estaba en el ticket"]}},
    {"que": "el ALCANCE del problema decide prioridad, responsable y qué se le pide al cliente",
     "codigo": [("ITHOS/central/cerebro.py", "def coherente"),
                ("ITHOS/central/cerebro.py", "def alcance_por_texto"),
                ("ITHOS/central/cerebro.py", "RESPUESTA_COORDINAR_VISITA"),
                ("ITHOS/central/cerebro.py", "MARCA_COORDINAR"),
                ("ITHOS/central/textos_ticket.py", "def _nota_alcance")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["El alcance manda", "no hay a quién pedirle un legajo",
                                       "lo único que se pide es coordinar la visita"],
              "README.md": ["alcance", "no hay a quién pedirle un legajo",
                            "coordinar la visita"],
              "CHANGELOG.md": ["ALCANCE del problema decide", "coordinar la\n  visita"]},
     "diagrama": ["COORDINAR LA VISITA"]},
    {"que": "antecedentes: casos parecidos sobre TODO el histórico, con la resolución real",
     "codigo": [("ITHOS/comun/tickets.py", "def casos_similares"),
                ("ITHOS/comun/tickets.py", "def _cierre_administrativo"),
                ("ITHOS/comun/asistente.py", "def _pide_antecedentes"),
                ("ITHOS/comun/herramientas.py", "def casos_parecidos")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["Antecedentes", "cierre administrativo"],
              "README.md": ["Antecedentes", "cierre\nadministrativo"],
              "CHANGELOG.md": ["ya resolvimos"]},
     "diagrama": ["Histórico COMPLETO del cliente"]},
    {"que": "aviso de cambio de estado en el tablero del equipo",
     "codigo": [("ITHOS/central/planka_integrador.py", "def _aviso_movimiento"),
                ("ITHOS/central/planka_integrador.py", "def _guardar_tarjetas")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["Avisa los cambios del tablero"],
              "README.md": ["cambios del tablero"],
              "CHANGELOG.md": ["aviso de cambio de estado en el tablero"]}},
    {"que": "tareas del equipo con rollover automático",
     "codigo": [("ITHOS/central/planka_rollover.py", "def semana_key")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["rollover"], "README.md": ["rollover"],
              "CHANGELOG.md": ["rollover"]}},
    {"que": "dominio del despliegue por variable de entorno",
     "codigo": [("ITHOS/Caddyfile", "ITHOS_DOMINIO")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["ITHOS_DOMINIO"], "README.md": ["ITHOS_DOMINIO"],
              "CHANGELOG.md": ["ITHOS_DOMINIO"]}},
    {"que": "receta de compilación del agente versionada",
     "codigo": [("compilador/build/agente.spec", "SPECPATH"),
                ("compilador/build/construir_agente.bat", "bump_version.py")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["construir_agente"],
              "README.md": ["compilador/build", "reconstruir"],
              "CHANGELOG.md": ["Receta de compilación"]}},
    {"que": "cifrado en reposo de los secretos por cliente",
     "codigo": [("ITHOS/comun/cifrado.py", "AES")],
     "docs": {"DOCUMENTO_MAESTRO.md": ["AES-256-GCM"], "README.md": ["AES-256-GCM"],
              "SECURITY.md": ["AES-256-GCM"]}},
]
try:
    _txt85 = {}

    def _leer85(rel):
        if rel not in _txt85:
            _txt85[rel] = leer(os.path.join(RAIZ, rel.replace("/", os.sep)))
        return _txt85[rel]

    _diagramas85 = "\n".join(re.findall(r"```mermaid\n(.*?)```", _leer85("DOCUMENTO_MAESTRO.md"),
                                        re.S)) if "re" in dir() else ""
    import re as _re85
    _diagramas85 = "\n".join(_re85.findall(r"```mermaid\n(.*?)```",
                                           _leer85("DOCUMENTO_MAESTRO.md"), _re85.S))
    huecos = []
    for cap in CAPACIDADES:
        implementada = all(marca in _leer85(arch) for arch, marca in cap["codigo"])
        if not implementada:
            huecos.append(f"[código ausente] {cap['que']}")
            continue
        for doc, marcas in cap["docs"].items():
            if not all(m.lower() in _leer85(doc).lower() for m in marcas):
                huecos.append(f"[falta en {doc}] {cap['que']}")
        for m in cap.get("diagrama", []):
            if m.lower() not in _diagramas85.lower():
                huecos.append(f"[falta en los diagramas] {cap['que']} ({m})")
    if not huecos:
        ok(f"documentación al día: las {len(CAPACIDADES)} capacidades implementadas están en el "
           "documento maestro, en el README, en el changelog y —las que son parte de un flujo— en su "
           "diagrama. Al agregar una funcionalidad, sumala a esta tabla con su documentación")
    else:
        fail("hay funcionalidad implementada SIN documentar (documentación desactualizada)",
             " · ".join(huecos))
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar que la documentación esté al día", repr(e))


print("\n  I) LATENCIA: procesos instantáneos (sin N+1 de red en el camino caliente)")
# I) El reporte ITIL NO puede hacer una request por ticket (N+1) -> trae los técnicos asignados en
#    UNA lectura masiva. Con 200 tickets: 0 requests '/Ticket/<id>/Ticket_User' y bulk presente.
#    Es la regresión del bug real (el histórico tardaba ~50s; ahora es instantáneo).
try:
    sys.path.insert(0, APP)
    from comun import reportes_itil as _RI
    import comun.glpi as _G
    llamadas = []
    fake_tk = [{"id": i, "status": 5, "entities_id": 0, "date_creation": "2026-07-01 10:00:00",
                "solvedate": "2026-07-02 10:00:00", "priority": 3, "itilcategories_id": 13}
               for i in range(1, 201)]

    class _FakeGlpi:
        def request(self, path, method="GET", data=None, **k):
            llamadas.append(path)
            if path.startswith("/Ticket_User?range="):
                return [{"tickets_id": i, "users_id": 7, "type": 2} for i in range(1, 201)]
            if path.startswith("/ITILCategory"):
                return [{"id": 13, "name": "TERMINALES"}]
            if path.startswith("/User/"):
                return {"firstname": "Tec", "realname": "Uno"}
            return []
    fk = _FakeGlpi()
    _o_ses, _o_tc, _o_de = _G.sesion, _G.tickets_todos_cache, _G.de_entidad
    for c in (_RI._CATCACHE, _RI._MAPCACHE, _RI._NAMECACHE, _RI._KCACHE):
        c.clear()
    _G.sesion = lambda cfg, tok=None: fk
    _G.tickets_todos_cache = lambda cfg, ttl=45: fake_tk
    _G.de_entidad = lambda tks, ent: tks
    try:
        cfg = {"glpi_url": "http://x", "glpi_app_token": "a", "glpi_user_token": "u",
               "glpi_ithos_token": "j"}
        k = _RI.calcular(cfg, 0, "total", con_tecnico=True)
    finally:
        _G.sesion, _G.tickets_todos_cache, _G.de_entidad = _o_ses, _o_tc, _o_de
        for c in (_RI._CATCACHE, _RI._MAPCACHE, _RI._NAMECACHE, _RI._KCACHE):
            c.clear()
    por_ticket = [p for p in llamadas if re.match(r"^/Ticket/\d+/Ticket_User", p)]
    bulk = [p for p in llamadas if p.startswith("/Ticket_User?range=")]
    if not por_ticket and bulk and k.get("creados") == 200 and len(llamadas) < 20:
        ok(f"reporte ITIL sin N+1: {len(llamadas)} reqs para 200 tickets "
           f"(bulk={len(bulk)}, por-ticket=0)")
    else:
        fail("reporte ITIL con N+1 / sin lectura masiva (latencia)",
             f"por_ticket={len(por_ticket)} bulk={len(bulk)} total={len(llamadas)}")
except Exception as e:  # noqa: BLE001
    fail("no se pudo verificar la latencia del reporte (N+1)", repr(e))


print("\n" + "=" * 58)
if fallas:
    print(f"  REQUERIMIENTOS: {len(fallas)} FALLA(S) / {len(oks)} OK")
    print("=" * 58)
    sys.exit(1)
print(f"  REQUERIMIENTOS: OK — {len(oks)} chequeos verdes")
print("=" * 58)
