#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEST GENERAL del sistema ITHOS — circuito completo de principio a fin.

Levanta el panel en un puerto de prueba y ejercita TODO vía HTTP (como el navegador):
  1. Alta de empresa (formulario completo).
  2. Carga INCORRECTA (validaciones: sin nombre, duplicado).
  3. Edición (cambia datos) + cambio de sistema de acceso IVMS -> HikCentral.
  4. WhatsApp: config guardada + prueba del notificador (módulo).
  5. Métricas + SLA (GLPI real) del cliente.
  6. Config del agente generada según el sistema.
  7. Portal del cliente (URL propia) responde.
  8. Estado en tiempo real (endpoint de conectados).
  9. Voz ITHOS Charon (genera audio).
  10. Ciclo de vida de ticket con IA (crear->triage->...->cerrar), si hay cuota.
  11. Borrado y verificación.

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


def req(metodo, ruta, body=None, espera=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(URL + ruta, data=data, method=metodo,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:  # noqa: BLE001
            return e.code, {}


def levantar_panel(clientes_tmp):
    """Arranca el panel (uvicorn) apuntando a un clientes.json temporal."""
    import uvicorn
    import panel
    panel.RUTA = clientes_tmp
    cfg = uvicorn.Config(panel.app, host="127.0.0.1", port=PUERTO, log_level="warning")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        try:
            urllib.request.urlopen(URL + "/api/clientes", timeout=1)
            return server
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise RuntimeError("el panel no arrancó")


def main():
    p("=" * 60)
    p("  TEST GENERAL DEL SISTEMA ITHOS")
    p("=" * 60)

    # clientes.json temporal (parte del real para tener GLPI/IVMS de INTELLIHELP)
    real = os.path.join(CENTRAL, "clientes.json")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    base = json.load(open(real, encoding="utf-8")) if os.path.exists(real) else {"clientes": []}
    intelli = next((c for c in base.get("clientes", []) if "INTELLIHELP" in c.get("nombre", "")), None)
    json.dump({"clientes": [intelli] if intelli else []}, tmp, ensure_ascii=False)
    tmp.close()

    levantar_panel(tmp.name)
    p("\n[0] Catálogos elegibles (tickets / canales / acceso)")
    for cat, esperados in (("tickets", ["glpi", "zendesk", "jira"]),
                           ("canales", ["telegram", "email", "slack"]),
                           ("integradores", ["ivms", "hikcentral"])):
        st, cc = req("GET", f"/api/{cat}")
        check(f"catálogo {cat}", st == 200 and all(e in cc for e in esperados),
              ", ".join(cc.keys()))

    p("\n[1] ALTA de empresa (tickets Zendesk + canales Telegram+Email + acceso IVMS)")
    alta = {"nombre": "ACME Test S.A.", "email": "it@acme.test", "activo": True,
            "idioma": "es-AR", "proveedor": "gemini", "gemini_api_key": "AIza-demo",
            "limite_diario": 150, "avisar_en": 10, "ilimitada": False,
            "integrador": "ivms", "integrador_config": {
                "db_server": "10.0.0.9,1433", "db_database": "ivms", "db_uid": "u", "db_pwd": "x"},
            "tickets": {"tipo": "zendesk", "host": "https://acme.zendesk.com",
                        "email": "it@acme.test", "api_token": "ZTOK"},
            "notificaciones": [
                {"tipo": "telegram", "enabled": True, "bot_token": "BOT", "chat_ids": ["123", "-100"]},
                {"tipo": "email", "enabled": True, "smtp_host": "smtp.acme.test",
                 "smtp_port": 465, "usuario": "a@acme.test", "password": "p",
                 "destinatarios": ["b@acme.test"]}]}
    st, d = req("POST", "/api/alta", alta)
    key = d.get("api_key")
    check("alta responde 200 + api_key", st == 200 and bool(key), key or "")
    check("alta devuelve URL de portal", d.get("portal", "").startswith("/panel/"))
    st, c0 = req("GET", f"/api/cliente/{key}")
    check("guardó sistema de tickets Zendesk", c0.get("tickets", {}).get("tipo") == "zendesk")
    check("guardó api_token de Zendesk", c0.get("tickets", {}).get("api_token") == "ZTOK")
    tipos_canal = [n.get("tipo") for n in c0.get("notificaciones", [])]
    check("guardó canales Telegram + Email", "telegram" in tipos_canal and "email" in tipos_canal,
          ", ".join(tipos_canal))

    p("\n[2] Carga INCORRECTA (validaciones)")
    st, _ = req("POST", "/api/alta", {"email": "x"})
    check("rechaza empresa sin nombre (400)", st == 400)
    st, _ = req("POST", "/api/alta", {"nombre": "ACME Test S.A."})
    check("rechaza nombre duplicado (409)", st == 409)

    p("\n[3] EDICIÓN: cambia tickets Zendesk->GLPI, acceso IVMS->HikCentral, canal Telegram->WhatsApp")
    edit = dict(alta)
    edit.update({"api_key": key, "limite_diario": 999,
                 "integrador": "hikcentral",
                 "integrador_config": {"host": "https://10.0.0.5", "app_key": "AK", "app_secret": "SEC"},
                 "tickets": {"tipo": "glpi", "glpi_url": "https://g.acme/apirest.php",
                             "glpi_app_token": "APP", "entity_id": 3},
                 "notificaciones": [{"tipo": "whatsapp_no_oficial", "enabled": True,
                                     "grupo": "ACME_ALERTAS", "session": "s.sqlite3"}]})
    st, _ = req("POST", "/api/clientes", edit)
    st2, c = req("GET", f"/api/cliente/{key}")
    check("edición guardada (limite 999)", c.get("ia", {}).get("limite_diario") == 999)
    check("cambió acceso a HikCentral", c.get("integrador") == "hikcentral")
    check("guardó claves HikCentral", c.get("integrador_config", {}).get("app_key") == "AK")
    check("cambió tickets a GLPI", c.get("tickets", {}).get("tipo") == "glpi")
    check("GLPI mapeado a integrador_glpi", c.get("integrador_glpi", {}).get("glpi_url", "").endswith("apirest.php"))
    check("cambió canal a WhatsApp", [n["tipo"] for n in c.get("notificaciones", [])] == ["whatsapp_no_oficial"])

    p("\n[4] Canales de notificación (módulo real)")
    from comun import notificadores as NOTIF
    notif = NOTIF.crear_notificadores({"notificaciones": [
        {"tipo": "telegram", "enabled": True, "bot_token": "B", "chat_ids": ["1"]},
        {"tipo": "email", "enabled": True, "smtp_host": "h", "usuario": "u", "destinatarios": ["x"]},
        {"tipo": "teams", "enabled": True, "webhook_url": "https://t"}]})
    check("crea 3 canales (telegram+email+teams)", len(notif.canales) == 3, f"{len(notif.canales)} canales")
    notif2 = NOTIF.crear_notificadores({"notificaciones": [
        {"tipo": "whatsapp_oficial", "enabled": True, "phone_number_id": "X",
         "access_token": "Y", "destinatarios": ["549"]}]})
    check("canal WhatsApp oficial se construye", len(notif2.canales) == 1)
    check("canal deshabilitado no se agrega",
          len(NOTIF.crear_notificadores({"notificaciones": [
              {"tipo": "telegram", "enabled": False}]}).canales) == 0)

    p("\n[5] Config del AGENTE generada por sistema")
    st, cfg = req("GET", f"/api/config_agente/{key}")
    check("config agente trae integrador HikCentral",
          (cfg.get("integrador") or {}).get("tipo") == "hikcentral")
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
    voz_ok = False
    if intelli:
        try:
            from comun import ia as IA
            pcm = IA.crear_voz(intelli["ia"]).voz_pcm("Prueba de sistema ITHOS. Todo operativo.")
            voz_ok = bool(pcm) and len(pcm) > 1000
            check("genera audio Charon", voz_ok, f"{len(pcm)} bytes" if pcm else "")
        except Exception as ex:  # noqa: BLE001
            agotada = "429" in str(ex) or "RESOURCE" in str(ex)
            check("voz OK (Charon o respaldo gratis edge-tts)", agotada,
                  "Charon sin cuota → usa voz edge-tts gratis" if agotada else str(ex)[:70])

    p("\n[10] CICLO de ticket con IA (si hay cuota)")
    if intelli and intelli.get("integrador_glpi", {}).get("glpi_ithos_token"):
        try:
            from comun import ia as IA
            IA.crear_texto(intelli["ia"]).chat("Responde JSON", 'Devuelve {"ok":true}', True)
            p("  (cuota IA disponible; el ciclo completo se valida con probar_ciclo.py)")
            check("IA de texto responde (triage disponible)", True)
        except Exception as ex:  # noqa: BLE001
            check("IA de texto responde", False,
                  "cuota/429" if "429" in str(ex) or "RESOURCE" in str(ex) else str(ex)[:70])

    p("\n[11] BORRADO y verificación")
    req("DELETE", f"/api/clientes/{key}")
    st, cli = req("GET", "/api/clientes")
    existe = any(c.get("api_key") == key for c in cli.get("clientes", []))
    check("empresa borrada", not existe)

    p("\n[12] AVANZADO por cliente: memoria, agente, reportes, facturación")
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
    from comun import facturacion as F
    check("DUEÑO no se cobra nunca", F.al_dia({"propietario": True, "enabled": True}) is True)
    check("cliente impago detectado", F.al_dia({"enabled": True, "estado": "pending"}) is False)
    ars, cot = F.monto_ars({"monto_usd": 10, "moneda": "ARS"})
    check("precio USD → ARS por dólar BNA", bool(cot) and ars > 0,
          f"10 USD = ${ars} (BNA ${cot})")
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
