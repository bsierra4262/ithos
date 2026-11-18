#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEST GENERAL del sistema ITHOS — lo que usa INTELLIHELP, de punta a punta.

ITHOS es una herramienta INTERNA: un Gestor, una empresa (INTELLIHELP), un agente. Esta prueba
levanta el panel en un puerto local sobre una COPIA de la configuración y ejercita, como el
navegador del administrador:
  0. Acceso: sin login no se entra a nada; las rutas de la etapa de venta (alta, portal, métricas
     por cliente, config del agente) ya no existen.
  1. Catálogos: ofrecen sólo lo implementado (GLPI, WhatsApp, IVMS, Gemini/Groq/IA local).
  2. Guardar la configuración como lo hace el formulario: aplica el cambio y CONSERVA lo que el
     formulario no maneja (secretos vacíos, técnicos, reparto, Planka).
  3. Validaciones: sin nombre no guarda; config ilegible no se pisa.
  4. Grupos de WhatsApp reales y sus ámbitos (ITHOS, ITHOS_SOPORTE, ITHOS_TRELLO, ITHOS_SISTEMA).
  5. Equipo desde la config (mesa, instalaciones, escalamiento, cuenta de ITHOS en GLPI).
  6. Estado y actividad del panel.
  7. SLA y reporte ITIL de GLPI real (sólo LECTURA), con CSV y PDF.
  8. Voz de las notas de WhatsApp (edge-tts, gratis: no gasta cuota de Gemini).
  9. IA de texto disponible (o sin cuota gratis del día, que no es un defecto).
  10. Memoria aislada y acciones del asistente sobre tickets.

No escribe nada en GLPI ni en WhatsApp, no toca el clientes.json real y no usa la voz Charon
(su cuota es la de los parlantes de la oficina). Los datos de memoria/métricas van a una
carpeta temporal. Corre así:
    python tests/probar_sistema.py
"""

import copy
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENTRAL = os.path.join(BASE, "ITHOS", "central")
sys.path.insert(0, CENTRAL)
sys.path.insert(0, os.path.join(BASE, "ITHOS"))

# Datos temporales ANTES de importar módulos que fijan su carpeta al cargarse (memoria, métricas).
_DATA_TMP = tempfile.mkdtemp(prefix="ithos_sistema_")
os.environ["ITHOS_DATA"] = _DATA_TMP

PUERTO = 8097
URL = f"http://127.0.0.1:{PUERTO}"
OKS = {"ok": 0, "fail": 0}


def p(s):
    print(str(s).encode("ascii", "replace").decode(), flush=True)


def check(nombre, cond, detalle=""):
    OKS["ok" if cond else "fail"] += 1
    p(f"  [{'OK  ' if cond else 'FALLA'}] {nombre}{(' - ' + detalle) if detalle else ''}")
    return cond


def _admin_token():
    import autenticacion as AUTH
    return AUTH.admin_token()


def req(metodo, ruta, body=None, admin=True, crudo=False):
    """Una llamada al panel como la haría el navegador del administrador."""
    data = json.dumps(body).encode() if body is not None else None
    cab = {"Content-Type": "application/json"}
    if admin:
        cab["X-Admin-Token"] = _admin_token()
    r = urllib.request.Request(URL + ruta, data=data, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            cuerpo = resp.read()
            if crudo:
                return resp.status, cuerpo, resp.headers.get("Content-Type", "")
            return resp.status, json.loads(cuerpo or b"{}")
    except urllib.error.HTTPError as e:
        if crudo:
            return e.code, e.read(), ""
        try:
            return e.code, json.load(e)
        except Exception:  # noqa: BLE001
            return e.code, {}


def levantar_panel(clientes_tmp):
    """Arranca el panel (uvicorn) apuntando a una copia temporal de clientes.json."""
    import uvicorn
    import panel
    panel.RUTA = clientes_tmp
    panel.CENTRAL_URL = "http://127.0.0.1:9"     # sin Gestor local: se prueba el fallback
    cfg = uvicorn.Config(panel.app, host="127.0.0.1", port=PUERTO, log_level="warning")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        try:
            st, _ = req("GET", "/api/clientes")
            if st == 200:
                return panel
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError("el panel no arrancó")


def _formulario_de(cli):
    """Lo que manda el formulario del panel al guardar: los secretos van VACÍOS (el navegador no
    los recibe de vuelta) y no incluye técnicos, reparto ni Planka."""
    gl = cli.get("integrador_glpi") or {}
    ia = cli.get("ia") or {}
    return {
        "api_key": cli["api_key"], "nombre": cli["nombre"], "activo": True,
        "idioma": cli.get("idioma", "es-AR"), "zona_horaria": cli.get("zona_horaria"),
        "proveedor": ia.get("proveedor", "gemini"), "gemini_api_key": "",
        "limite_diario": 321, "avisar_en": ia.get("avisar_en", 15),
        "integrador": cli.get("integrador", "ivms"),
        "integrador_config": {k: ("" if k == "db_pwd" else v)
                              for k, v in (cli.get("integrador_config") or {}).items()},
        "tickets": {"tipo": "glpi", "glpi_url": gl.get("glpi_url", ""), "glpi_app_token": "",
                    "glpi_user_token": "", "glpi_ithos_token": "",
                    "entity_id": gl.get("entity_id", 0)},
        "notificaciones": copy.deepcopy(cli.get("notificaciones") or []),
        "reportes": cli.get("reportes") or {}, "proactivo": cli.get("proactivo") or {},
    }


def main():
    p("=" * 60)
    p("  TEST GENERAL DEL SISTEMA ITHOS (herramienta interna)")
    p("=" * 60)

    real = os.path.join(CENTRAL, "clientes.json")
    if not os.path.exists(real):
        p("  falta ITHOS/central/clientes.json (la config de INTELLIHELP): no hay qué probar")
        sys.exit(1)
    from comun import cifrado as CIF
    with open(real, encoding="utf-8") as f:
        base = CIF.descifrar_datos(json.load(f))
    intelli = next((c for c in base.get("clientes", []) if "INTELLIHELP" in c.get("nombre", "")), None)
    if not intelli:
        p("  la config no tiene a INTELLIHELP")
        sys.exit(1)
    tmp = os.path.join(_DATA_TMP, "clientes.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"clientes": [intelli]}, f, ensure_ascii=False)
    key = intelli["api_key"]
    panel = levantar_panel(tmp)

    p("\n[0] ACCESO: todo detrás del login, sin rutas de la etapa de venta")
    for ruta in ("/api/clientes", f"/api/cliente/{key}", "/api/estado", "/api/resumen"):
        st, _ = req("GET", ruta, admin=False)
        check(f"sin login {ruta} -> 401", st == 401, f"HTTP {st}")
    st, html, _ = req("GET", "/", admin=False, crudo=True)
    check("la portada sin login muestra el formulario de ingreso",
          b"password" in html.lower() and b"api/clientes" not in html)
    for metodo, ruta in (("POST", "/api/alta"), ("POST", "/api/alta_link"),
                         ("GET", f"/panel/{key}"), ("GET", "/alta"),
                         ("GET", f"/api/config_agente/{key}"), ("GET", f"/api/metricas/{key}"),
                         ("DELETE", f"/api/clientes/{key}")):
        st, _ = req(metodo, ruta, body={} if metodo == "POST" else None)
        check(f"{metodo} {ruta} ya no existe", st in (404, 405), f"HTTP {st}")

    p("\n[1] CATÁLOGOS: sólo lo implementado")
    for cat, esperados in (("tickets", ["glpi"]), ("canales", ["whatsapp_no_oficial"]),
                           ("integradores", ["ivms"]),
                           ("ia_proveedores", ["gemini", "groq", "local"])):
        st, cc = req("GET", f"/api/{cat}")
        check(f"catálogo {cat}", st == 200 and sorted(cc) == sorted(esperados), ", ".join(cc))
    from comun import tickets as TK
    from comun import notificadores as NOTIF
    check("GLPI tiene adaptador real", TK.adaptador({"tickets": {"tipo": "glpi"}}).tipo == "glpi")
    check("canal deshabilitado no se arma",
          len(NOTIF.crear_notificadores({"notificaciones": [
              {"tipo": "whatsapp_no_oficial", "enabled": False}]}).canales) == 0)

    p("\n[2] GUARDAR la configuración desde el formulario")
    antes = copy.deepcopy(intelli)
    st, d = req("POST", "/api/clientes", _formulario_de(intelli))
    check("guardar responde ok con la misma api_key", st == 200 and d.get("api_key") == key,
          f"HTTP {st}")
    st, c = req("GET", f"/api/cliente/{key}")
    gl, gl0 = c.get("integrador_glpi") or {}, antes.get("integrador_glpi") or {}
    check("aplicó el cambio (límite diario 321)", (c.get("ia") or {}).get("limite_diario") == 321)
    check("los tokens de GLPI vacíos NO borraron los guardados",
          all(gl.get(k) == gl0.get(k) for k in ("glpi_app_token", "glpi_user_token",
                                                 "glpi_ithos_token")))
    check("la clave de Gemini vacía NO borró la guardada",
          (c.get("ia") or {}).get("gemini_api_key") == (antes.get("ia") or {}).get("gemini_api_key"))
    check("la contraseña de la base de fichadas se conserva",
          (c.get("integrador_config") or {}).get("db_pwd")
          == (antes.get("integrador_config") or {}).get("db_pwd"))
    check("técnicos, reparto y Planka intactos",
          c.get("tecnicos") == antes.get("tecnicos") and c.get("reparto") == antes.get("reparto")
          and c.get("planka") == antes.get("planka"))
    check("la cuenta de ITHOS en GLPI intacta", gl.get("ithos_user_id") == gl0.get("ithos_user_id"))
    check("el agente conserva su contraseña", c.get("agente_token") == antes.get("agente_token"))
    with open(tmp, encoding="utf-8") as f:
        crudo = f.read()
    tok = gl0.get("glpi_ithos_token") or ""
    check("en disco los secretos quedan cifrados", bool(tok) and tok not in crudo
          and "enc:v1:" in crudo)
    st, todo = req("GET", "/api/clientes")
    check("sigue habiendo UNA empresa", len(todo.get("clientes", [])) == 1)

    p("\n[3] VALIDACIONES")
    st, _ = req("POST", "/api/clientes", {"api_key": key, "nombre": "  "})
    check("sin nombre no guarda (400)", st == 400, f"HTTP {st}")
    with open(tmp, encoding="utf-8") as f:
        sano = f.read()
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("{roto")
    panel._cache_cfg["mtime"] = None
    st, _ = req("POST", "/api/clientes", _formulario_de(intelli))
    with open(tmp, encoding="utf-8") as f:
        quedo = f.read()
    check("con la config ilegible no guarda (500) y no la pisa", st == 500 and quedo == "{roto",
          f"HTTP {st}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(sano)
    panel._cache_cfg["mtime"] = None

    p("\n[4] GRUPOS DE WHATSAPP y sus ámbitos (config real)")
    from comun import ambitos as AMB
    wa = next((n for n in intelli.get("notificaciones", [])
               if n.get("tipo") == "whatsapp_no_oficial"), {})
    gs = {g["grupo"]: g["ambito"] for g in AMB.grupos_de(wa)}
    check("están los 4 grupos", gs == {"ITHOS": "consultas", "ITHOS_SOPORTE": "soporte",
                                       "ITHOS_TRELLO": "tareas", "ITHOS_SISTEMA": "sistema"},
          ", ".join(f"{g}:{a}" for g, a in gs.items()))
    check("ITHOS (consultas) no recibe avisos",
          not any(AMB.recibe("consultas", t) for t in AMB.AVISOS))
    check("ITHOS_SOPORTE recibe tickets y SLA",
          AMB.recibe("soporte", AMB.TICKETS) and AMB.recibe("soporte", AMB.SLA))
    check("ITHOS_TRELLO recibe Planka", AMB.recibe("tareas", AMB.PLANKA))
    check("ITHOS_SISTEMA recibe sistema y voz",
          AMB.recibe("sistema", AMB.SISTEMA) and AMB.recibe("sistema", AMB.VOZ))
    check("un tema fuera de lugar se deriva a otro grupo",
          bool(AMB.fuera_de_alcance(AMB.PLANKA, AMB.grupos_de(wa))))

    p("\n[5] EQUIPO desde la config")
    import equipo as EQ
    EQ.configurar(intelli)
    check("cuenta de ITHOS en GLPI", EQ.ITHOS_ID == 28, str(EQ.ITHOS_ID))
    check("mesa de ayuda", EQ.MESA == (intelli.get("reparto") or {}).get("mesa"), ", ".join(EQ.MESA))
    check("instalaciones y escalamiento", bool(EQ.instalaciones()) and bool(EQ.escalamiento()),
          f"{EQ.instalaciones()} / {EQ.escalamiento()}")
    check("cada login del reparto es un técnico cargado",
          all(x in EQ.RESPONSABLES for x in EQ.MESA + [EQ.instalaciones(), EQ.escalamiento()]))

    p("\n[6] ESTADO y actividad")
    st, e = req("GET", "/api/estado")
    check("estado responde aunque el Gestor no conteste", st == 200 and "conectados" in e)
    st, r = req("GET", "/api/resumen")
    check("actividad del mes", st == 200 and "uso_total" in r)
    st, s = req("GET", f"/api/salud/{key}")
    check("salud responde con fallback", st == 200 and "agente_conectado" in s)

    p("\n[7] SLA y REPORTE ITIL (GLPI real, sólo lectura)")
    st, sla = req("GET", f"/api/sla/{key}")
    check("SLA calcula", st == 200 and not sla.get("error")
          and sla.get("sla_cumplimiento_pct") is not None,
          sla.get("error") or f"{sla.get('sla_cumplimiento_pct')}% de {sla.get('total')}")
    st, ri = req("GET", f"/api/reporte_itil/{key}?periodo=mensual")
    check("reporte ITIL mensual", st == 200 and "kpis" in ri and bool(ri.get("texto")),
          ri.get("error", ""))
    st, cuerpo, tipo = req("GET", f"/api/reporte_itil/{key}/csv?periodo=mensual", crudo=True)
    check("CSV descarga", st == 200 and "csv" in tipo and len(cuerpo) > 50, f"{len(cuerpo)} bytes")
    st, cuerpo, tipo = req("GET", f"/api/reporte_itil/{key}/pdf?periodo=mensual", crudo=True)
    check("PDF descarga", st == 200 and cuerpo[:4] == b"%PDF", f"{len(cuerpo)} bytes")

    p("\n[8] VOZ de las notas de WhatsApp (edge-tts, gratis)")
    from comun import voz_tts as VT
    try:
        ogg = VT.audio("Prueba de sistema ITHOS. Todo operativo.")
        check("genera la nota de voz", bool(ogg) and len(ogg) > 1000,
              f"{len(ogg)} bytes" if ogg else "sin audio")
    except Exception as ex:  # noqa: BLE001
        check("genera la nota de voz", False, str(ex)[:70])

    p("\n[9] IA de texto (el triage la necesita)")
    try:
        from comun import ia as IA
        IA.crear_texto(intelli["ia"]).chat("Responde JSON", 'Devuelve {"ok":true}', True)
        check("IA de texto responde", True)
    except Exception as ex:  # noqa: BLE001
        # Agotar la cuota GRATIS del día no es un defecto: si diera FALLA, la suite estaría roja
        # todas las tardes y una falla de verdad pasaría desapercibida.
        m = str(ex).lower()
        agotada = any(t in m for t in ("429", "resource_exhausted", "rate limit",
                                       "rate_limited", "quota"))
        check("IA de texto disponible (o sin cuota gratis del día)", agotada, str(ex)[:70])

    p("\n[10] MEMORIA y acciones del asistente")
    from comun import memoria as MEM
    m = MEM.Memoria("TEST_QA")
    m.agregar("user", "hola ithos")
    m.recordar("dato", "valor")
    check("memoria guarda historial y hechos",
          "hola ithos" in m.historial_texto() and m.hechos().get("dato") == "valor")
    check("memoria aislada (otra conversación no la ve)", not MEM.Memoria("OTRO_QA").hechos())
    check("la memoria va a la carpeta de datos, no al código",
          os.path.abspath(MEM._archivo("TEST_QA")).startswith(os.path.abspath(_DATA_TMP)))
    from comun import herramientas as H
    acc = H.acciones_tickets(intelli)
    check("acciones sobre tickets (cerrar/asignar/responder/crear/reabrir)",
          set(acc) >= {"cerrar_ticket", "asignar_ticket", "responder_ticket",
                       "crear_ticket", "reabrir_ticket"}, ", ".join(sorted(acc))[:90])

    p("\n" + "=" * 60)
    p(f"  RESULTADO: {OKS['ok']} OK · {OKS['fail']} FALLAS")
    p("=" * 60)
    sys.exit(1 if OKS["fail"] else 0)


if __name__ == "__main__":
    main()
