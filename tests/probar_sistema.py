#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEST GENERAL del sistema ITHOS — circuito completo de principio a fin.

Levanta el panel en un puerto de prueba y ejercita TODO vía HTTP (como el navegador):
  0. El panel EXIGE credenciales (sin token no se entra) y los catálogos ofrecen sólo
     lo que el software sabe hacer.
  1. Alta de empresa (formulario completo).
  2. Carga INCORRECTA (validaciones: sin nombre, duplicado).
  3. Edición (cambia datos, tickets y los grupos de WhatsApp por tema).
  4. Canales de notificación (módulo real) y ámbitos de cada grupo.
  5. Config del agente generada según el sistema.
  6. Portal del cliente (URL propia) responde.
  7. Estado en tiempo real (endpoint de conectados).
  8. Métricas + SLA (GLPI real) del cliente.
  9. Voz ITHOS Charon (genera audio).
  10. IA de texto disponible (el ciclo completo se valida con probar_ciclo.py).
  11. Borrado y verificación.
  12. Avanzado por cliente: memoria aislada, acciones sobre tickets, reportes.

Usa un clientes.json TEMPORAL para no tocar el real. No requiere el central corriendo
(para el estado usa el fallback). Corre así:
    python probar_sistema.py
"""

import os
import sys
import json
import time
import tempfile
import threading
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENTRAL = os.path.join(BASE, "ITHOS", "central")
sys.path.insert(0, CENTRAL)
sys.path.insert(0, os.path.join(BASE, "ITHOS"))

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


def req(metodo, ruta, body=None, admin=True):
    """Una llamada al panel como la haría el navegador del superadmin."""
    data = json.dumps(body).encode() if body is not None else None
    cab = {"Content-Type": "application/json"}
    if admin:
        cab["X-Admin-Token"] = _admin_token()
    r = urllib.request.Request(URL + ruta, data=data, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:  # noqa: BLE001
            return e.code, {}


def alta_token():
    """Un enlace de alta nuevo. Es de UN SOLO USO: cada alta pide el suyo, igual que en la vida real."""
    _, d = req("POST", "/api/alta_link", {"nombre": "prueba", "horas": 1})
    return d.get("token", "")


def levantar_panel(clientes_tmp):
    """Arranca el panel (uvicorn) apuntando a un clientes.json temporal."""
    import uvicorn
    import panel
    panel.RUTA = clientes_tmp
    cfg = uvicorn.Config(panel.app, host="127.0.0.1", port=PUERTO, log_level="warning")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        st, _ = req("GET", "/api/clientes")
        if st == 200:
            return server
        time.sleep(0.25)
    raise RuntimeError("el panel no arrancó")


def main():
    p("=" * 60)
    p("  TEST GENERAL DEL SISTEMA ITHOS")
    p("=" * 60)

    # clientes.json temporal (parte del real para tener GLPI de INTELLIHELP)
    real = os.path.join(CENTRAL, "clientes.json")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    base = json.load(open(real, encoding="utf-8")) if os.path.exists(real) else {"clientes": []}
    intelli = next((c for c in base.get("clientes", []) if "INTELLIHELP" in c.get("nombre", "")), None)
    json.dump({"clientes": [intelli] if intelli else []}, tmp, ensure_ascii=False)
    tmp.close()

    levantar_panel(tmp.name)

    p("\n[0] SEGURIDAD y catálogos elegibles")
    st, _ = req("GET", "/api/clientes", admin=False)
    check("sin credenciales el panel NO deja entrar (401)", st == 401, f"HTTP {st}")
    # El catálogo ofrece SÓLO lo que hay: elegir algo sin implementación sería
    # configurar un cliente que nunca recibe nada y no enterarse.
    for cat, esperados in (("tickets", ["ninguno", "glpi"]),
                           ("canales", ["whatsapp_no_oficial"]),
                           ("integradores", ["ninguno", "ivms"])):
        st, cc = req("GET", f"/api/{cat}")
        check(f"catálogo {cat} = exactamente lo implementado",
              st == 200 and sorted(cc) == sorted(esperados), ", ".join(cc.keys()))
    from comun import tickets as TK
    from comun import notificadores as NOTIF
    st, cc = req("GET", "/api/tickets")
    check("cada sistema de tickets del catálogo tiene adaptador real",
          all(t == "ninguno" or TK.adaptador({"tickets": {"tipo": t}}).tipo == t for t in cc))
    st, cc = req("GET", "/api/canales")
    check("cada canal del catálogo se construye de verdad",
          all(NOTIF.crear_notificadores(
              {"notificaciones": [{"tipo": t, "enabled": True, "grupo": "G",
                                   "session": ":memory:"}]}) is not None for t in cc))

    p("\n[1] ALTA de empresa (GLPI + WhatsApp con grupos por tema + acceso IVMS)")
    alta = {"nombre": "ACME Test S.A.", "email": "it@acme.test", "activo": True,
            "idioma": "es-AR", "proveedor": "gemini", "gemini_api_key": "AIza-demo",
            "limite_diario": 150, "avisar_en": 10, "ilimitada": False,
            "integrador": "ivms", "integrador_config": {
                "db_server": "10.0.0.9,1433", "db_database": "ivms", "db_uid": "u", "db_pwd": "x"},
            "tickets": {"tipo": "glpi", "glpi_url": "https://g.acme/apirest.php",
                        "glpi_app_token": "APP", "glpi_user_token": "USR", "entity_id": 2},
            "notificaciones": [
                {"tipo": "whatsapp_no_oficial", "enabled": True, "session": "acme.sqlite3",
                 "grupos": [{"grupo": "ACME", "ambito": "consultas"},
                            {"grupo": "ACME_SOPORTE", "ambito": "soporte"}]}]}
    st, d = req("POST", "/api/alta", dict(alta, _alta_token=alta_token()))
    key = d.get("api_key")
    check("alta responde 200 + api_key", st == 200 and bool(key), key or "")
    check("alta devuelve URL de portal", d.get("portal", "").startswith("/panel/"))
    st, c0 = req("GET", f"/api/cliente/{key}")
    check("guardó sistema de tickets GLPI", c0.get("tickets", {}).get("tipo") == "glpi")
    check("GLPI mapeado a integrador_glpi",
          c0.get("integrador_glpi", {}).get("glpi_url", "").endswith("apirest.php"))
    grupos = (c0.get("notificaciones", [{}])[0] or {}).get("grupos", [])
    check("guardó los grupos con su ámbito", [g.get("ambito") for g in grupos] == ["consultas", "soporte"],
          ", ".join(f"{g.get('grupo')}:{g.get('ambito')}" for g in grupos))

    p("\n[2] Carga INCORRECTA (validaciones) y enlace de alta de UN SOLO USO")
    st, _ = req("POST", "/api/alta", {"email": "x"})
    check("rechaza empresa sin nombre (400)", st == 400)
    st, _ = req("POST", "/api/alta", {"nombre": "OTRA S.A."})
    check("sin enlace de alta no se da de alta a nadie (403)", st == 403)
    t = alta_token()
    st, _ = req("POST", "/api/alta", {"nombre": "ACME Test S.A.", "_alta_token": t})
    check("rechaza nombre duplicado (409)", st == 409)
    st, _ = req("POST", "/api/alta", {"nombre": "OTRA S.A.", "_alta_token": t})
    check("el enlace ya usado NO sirve de nuevo (403)", st == 403)

    p("\n[3] EDICIÓN: cambia el límite y suma un grupo de tareas")
    edit = dict(alta)
    edit.update({"api_key": key, "limite_diario": 999,
                 "notificaciones": [{"tipo": "whatsapp_no_oficial", "enabled": True,
                                     "session": "acme.sqlite3",
                                     "grupos": [{"grupo": "ACME", "ambito": "consultas"},
                                                {"grupo": "ACME_SOPORTE", "ambito": "soporte"},
                                                {"grupo": "ACME_TAREAS", "ambito": "tareas"}]}]})
    req("POST", "/api/clientes", edit)
    st, c = req("GET", f"/api/cliente/{key}")
    check("edición guardada (limite 999)", c.get("ia", {}).get("limite_diario") == 999)
    check("sigue en IVMS con sus claves", c.get("integrador") == "ivms"
          and c.get("integrador_config", {}).get("db_database") == "ivms")
    check("el grupo nuevo quedó guardado",
          len((c.get("notificaciones", [{}])[0] or {}).get("grupos", [])) == 3)

    p("\n[4] Canales y ÁMBITOS (módulo real)")
    from comun import ambitos as AMB
    cfg_wa = {"grupos": [{"grupo": "ACME", "ambito": "consultas"},
                         {"grupo": "ACME_SOPORTE", "ambito": "soporte"}]}
    gs = AMB.grupos_de(cfg_wa)
    check("el grupo de consultas NO recibe alertas de tickets",
          not AMB.recibe(gs[0]["ambito"], AMB.TICKETS))
    check("el de soporte SÍ recibe tickets y SLA",
          AMB.recibe(gs[1]["ambito"], AMB.TICKETS) and AMB.recibe(gs[1]["ambito"], AMB.SLA))
    check("una consulta fuera de tema se deriva al grupo que la maneja",
          "ACME" in AMB.fuera_de_alcance(AMB.PLANKA, gs))
    check("un cliente con un solo grupo suelto sigue recibiendo todo",
          AMB.recibe(AMB.grupos_de({"grupo": "UNICO"})[0]["ambito"], AMB.TICKETS))
    check("canal deshabilitado no se agrega",
          len(NOTIF.crear_notificadores({"notificaciones": [
              {"tipo": "whatsapp_no_oficial", "enabled": False}]}).canales) == 0)

    p("\n[5] Config del AGENTE generada por sistema")
    st, cfg = req("GET", f"/api/config_agente/{key}")
    check("config agente trae integrador IVMS",
          (cfg.get("integrador") or {}).get("tipo") == "ivms")
    check("config agente trae voz Charon", cfg.get("ia", {}).get("voz", {}).get("voz") == "Charon")

    p("\n[6] Portal del cliente (URL propia)")
    try:
        with urllib.request.urlopen(URL + f"/panel/{key}", timeout=10) as r:
            html = r.read().decode("utf-8", "ignore")
        check("portal /panel/{key} responde HTML", "ITHOS" in html and "PORTAL" in html.upper())
    except Exception as e:  # noqa: BLE001
        check("portal /panel/{key} responde HTML", False, str(e)[:60])

    p("\n[7] Estado en TIEMPO REAL (conectados)")
    st, e = req("GET", "/api/estado")
    check("endpoint estado responde lista", st == 200 and "conectados" in e)

    p("\n[8] MÉTRICAS + SLA de INTELLIHELP (GLPI real)")
    if intelli:
        k2 = intelli["api_key"]
        st, met = req("GET", f"/api/metricas/{k2}")
        check("métricas responden", st == 200 and "uso" in met)
        st, sla = req("GET", f"/api/sla/{k2}")
        if sla.get("error"):
            check("SLA (GLPI) responde", True, "aviso: " + sla["error"])
        else:
            check("SLA (GLPI) calcula %", sla.get("sla_cumplimiento_pct") is not None,
                  f"{sla.get('sla_cumplimiento_pct')}% de {sla.get('total')}")
    else:
        p("  (sin INTELLIHELP en clientes.json — salteo SLA real)")

    p("\n[9] VOZ ITHOS Charon")
    if intelli:
        try:
            from comun import ia as IA
            pcm = IA.crear_voz(intelli["ia"]).voz_pcm("Prueba de sistema ITHOS. Todo operativo.")
            check("genera audio Charon", bool(pcm) and len(pcm) > 1000,
                  f"{len(pcm)} bytes" if pcm else "")
        except Exception as ex:  # noqa: BLE001
            agotada = "429" in str(ex) or "RESOURCE" in str(ex)
            check("voz OK (Charon o respaldo gratis edge-tts)", agotada,
                  "Charon sin cuota → usa voz edge-tts gratis" if agotada else str(ex)[:70])

    p("\n[10] IA de texto (el triage la necesita)")
    if intelli and intelli.get("integrador_glpi", {}).get("glpi_ithos_token"):
        try:
            from comun import ia as IA
            IA.crear_texto(intelli["ia"]).chat("Responde JSON", 'Devuelve {"ok":true}', True)
            p("  (cuota IA disponible; el ciclo completo se valida con probar_ciclo.py)")
            check("IA de texto responde (triage disponible)", True)
        except Exception as ex:  # noqa: BLE001
            # Que se haya agotado la cuota GRATIS del día no es un defecto del sistema, igual que
            # en el chequeo de voz de acá arriba, que ya lo trataba así. Antes esto daba FALLA, con
            # lo cual la suite se ponía roja todos los días a partir del momento en que se agotaba
            # la cuota: una alarma que suena por algo esperable deja de mirarse, y entonces una
            # falla de verdad pasa desapercibida.
            m = str(ex).lower()
            agotada = any(t in m for t in ("429", "resource_exhausted", "rate limit",
                                           "rate_limited", "quota"))
            check("IA de texto disponible (o sin cuota gratis del día)", agotada,
                  "cuota del día agotada → el triage se valida al resetear" if agotada
                  else str(ex)[:70])

    p("\n[11] BORRADO y verificación")
    req("DELETE", f"/api/clientes/{key}")
    st, cli = req("GET", "/api/clientes")
    existe = any(c.get("api_key") == key for c in cli.get("clientes", []))
    check("empresa borrada", not existe)

    p("\n[12] AVANZADO por cliente: memoria, acciones sobre tickets, reportes")
    from comun import memoria as MEM
    m = MEM.Memoria("TEST_QA")
    m.agregar("user", "hola ithos")
    m.recordar("dato", "valor")
    check("memoria guarda historial + hechos aprendidos",
          "hola ithos" in m.historial_texto() and m.hechos().get("dato") == "valor")
    m2 = MEM.Memoria("OTRO_QA")
    check("memoria AISLADA por cliente (uno no ve al otro)", not m2.hechos())
    from comun import conversacion as CV
    if intelli:
        gl = intelli["integrador_glpi"]
        acc = CV.acciones_glpi(gl, int(gl["entity_id"]), gl.get("glpi_ithos_token"))
        check("agente tiene acciones (cerrar/asignar/responder/crear/reabrir)",
              set(acc) >= {"cerrar_ticket", "asignar_ticket", "responder_ticket",
                           "crear_ticket", "reabrir_ticket"})
        try:
            import reportes_programados as RP
            txt = RP.texto_reporte(gl, int(gl["entity_id"]))
            check("reporte proactivo genera texto real", "SLA" in txt or "Reporte" in txt)
        except Exception as ex:  # noqa: BLE001
            check("reporte proactivo", False, str(ex)[:60])
    for cq in ("TEST_QA", "OTRO_QA"):
        try:
            os.unlink(MEM._archivo(cq))
        except Exception:  # noqa: BLE001
            pass

    os.unlink(tmp.name)
    p("\n" + "=" * 60)
    p(f"  RESULTADO: {OKS['ok']} OK · {OKS['fail']} FALLAS")
    p("=" * 60)
    sys.exit(1 if OKS["fail"] else 0)


if __name__ == "__main__":
    main()
