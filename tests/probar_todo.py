#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PRUEBA TOTAL de ITHOS Cloud — ejercita TODO el programa de principio a fin y
reporta OK / FALLA / PENDIENTE(cuota IA) por componente. Autónomo (lee sus configs).

Uso:  python probar_todo.py
"""

import sys
import json
import importlib
import threading
import time
import os
import glob

sys.path.insert(0, "ITHOS/central")
sys.path.insert(0, "ITHOS/agente")
sys.path.insert(0, "ITHOS")

R = []


def check(nombre, fn):
    try:
        R.append((nombre, "OK", str(fn() or "")[:70]))
    except Exception as e:  # noqa: BLE001
        m = str(e)
        est = "PENDIENTE (cuota IA)" if ("429" in m or "RESOURCE_EXHAUSTED" in m) else "FALLA"
        R.append((nombre, est, m[:90]))


def p(s):
    print(str(s).encode("ascii", "replace").decode(), flush=True)


CFG = json.load(open("ITHOS/central/clientes.json", encoding="utf-8"))["clientes"][0]
GL = CFG["integrador_glpi"]
IA_CFG = CFG["ia"]
ENT = int(GL["entity_id"])


def ia_disponible():
    """Sondeo de cuota con el proveedor robusto (maneja 'client closed')."""
    from comun import ia as IA
    try:
        IA.crear_texto(IA_CFG).chat("Responde solo: OK", "hola", json_out=False)
        return True
    except Exception as e:  # noqa: BLE001
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            return False
        raise


def t_registro():
    from registro import Registro
    return f"{Registro(ruta='ITHOS/central/clientes.json').total()} clientes"


def t_ia_factory():
    from comun import ia as IA
    vz = IA.crear_voz(IA_CFG)
    # El TTS DEDICADO, no el conversacional 'native-audio': ese se comía los nombres propios y por
    # eso se cambió (H68/H69). Este test tenía congelado el modelo VIEJO y contradecía a la batería.
    assert vz.voz == "Charon", vz.voz
    assert vz.modelo_voz == "gemini-2.5-flash-preview-tts", vz.modelo_voz
    return f"texto + voz(Charon, {vz.modelo_voz})"


def t_cuota():
    # El archivo va a una carpeta temporal del sistema, NO al árbol del código: un test no tiene
    # por qué dejar estado al lado de los .py (terminaba viajando al servidor en el deploy), y la
    # ruta relativa de antes dependía de desde dónde se corriera el test.
    import tempfile
    from comun.cuota import GestorCuota
    av = []
    with tempfile.TemporaryDirectory(prefix="ithos_cuota_") as tmp:
        g = GestorCuota("T", limite_diario=2, avisar_en=1,
                        archivo=os.path.join(tmp, "cuota_t.json"),
                        notificar=lambda n, m: av.append(n))
        g.registrar(); g.registrar(); g.marcar_agotada()
        est = g.estado()
    assert len(av) == 2
    return f"avisos={len(av)} gemini_agotada={est['gemini']['agotada']}"


def t_notificadores():
    """Hoy el ÚNICO canal implementado es WhatsApp (el panel sólo ofrece ese). Telegram/Teams/
    Email quedaron en la rama `saas`: un canal que no existe NO se inventa acá, se ignora en
    silencio, y el test lo deja escrito para que la diferencia no se vuelva a perder de vista."""
    from comun import notificadores
    n = notificadores.crear_notificadores({"notificaciones": [
        {"tipo": "telegram", "bot_token": "x", "chat_ids": []},
        {"tipo": "teams", "webhook_url": "x"}, {"tipo": "email", "usuario": "x"}]})
    assert len(n.canales) == 0, f"canales inesperados: {n.canales}"
    assert n.hay_activo() is False
    return "sin canales (telegram/teams/email no implementados)"


def t_glpi_reportes():
    import reportes
    rep, _ = reportes.generar(GL, ENT, n=60)
    return f"SLA={rep['sla_cumplimiento_pct']}% total={rep['total']}"


def t_ivms():
    ag = json.load(open("ITHOS/agente/config.json", encoding="utf-8"))
    cfg = ag.get("integrador")
    if not cfg or cfg.get("tipo") != "ivms":
        return "sin integrador ivms — omitido"
    import logging, io
    m = importlib.import_module("integrador_ivms")
    buf = io.StringIO(); h = logging.StreamHandler(buf)
    m.log.addHandler(h); m.log.setLevel(logging.INFO)
    stop = threading.Event()
    th = threading.Thread(target=m.vigilar, args=(cfg, lambda ev: None, stop), daemon=True)
    th.start(); time.sleep(7); stop.set(); time.sleep(0.3)
    m.log.removeHandler(h)
    out = buf.getvalue().lower()
    if "conectado" in out or "baseline" in out:
        return "conecto a la DB + baseline"
    raise Exception("IVMS no conecto: " + out[:50])


def t_metricas():
    from comun import metricas
    metricas.registrar("T", "ticket", 2)
    u = metricas.resumen("T")["uso"]
    [os.remove(f) for f in glob.glob("ITHOS/comun/metricas_T.json")]
    assert u.get("ticket") == 2
    return "registro+resumen"


def t_kb():
    from comun import kb
    os.makedirs("ITHOS/comun/_kb", exist_ok=True)
    open("ITHOS/comun/_kb/d.txt", "w", encoding="utf-8").write(
        "El molinete se reinicia apagando 10 segundos.")
    ctx = kb.contexto("ITHOS/comun/_kb", "reiniciar molinete")
    os.remove("ITHOS/comun/_kb/d.txt"); os.rmdir("ITHOS/comun/_kb")
    assert "molinete" in ctx
    return "RAG por palabras"


def t_procesador():
    """El portero saluda a quien entra.

    OJO con el estado: el saludo tiene anti-repetición (a la misma persona no se la saluda dos
    veces el mismo día) y eso se guarda en disco. Si el test usa el archivo real, saluda la
    PRIMERA vez y después devuelve vacío para siempre: pasaba una vez y fallaba el resto del día.
    Como la suite además salía con código 0 aunque hubiera fallas, nadie se enteraba. Por eso el
    estado va a una carpeta temporal: el test arranca siempre desde cero.

    No alcanza con cambiarle la ruta: `_cargar_saludados()` corre AL IMPORTAR el módulo y deja lo
    ya saludado en diccionarios en memoria, así que hay que vaciar los dos y después devolverlos
    como estaban."""
    import tempfile
    import procesador
    from protocolo import EV_ACCESO
    original = procesador._ESTADO_SALUDOS
    hoy, alguna = dict(procesador._saludados_hoy), dict(procesador._saludados_alguna)
    with tempfile.TemporaryDirectory(prefix="ithos_portero_") as tmp:
        procesador._ESTADO_SALUDOS = os.path.join(tmp, "portero_saludados.json")
        procesador._saludados_hoy.clear()
        procesador._saludados_alguna.clear()
        try:
            c = procesador.procesar(CFG, EV_ACCESO,
                                    {"nombre": "Brian Sierra", "tipo": "bienvenida"})
        finally:
            procesador._ESTADO_SALUDOS = original
            procesador._saludados_hoy.clear(); procesador._saludados_hoy.update(hoy)
            procesador._saludados_alguna.clear(); procesador._saludados_alguna.update(alguna)
    assert c, "el portero no devolvió ningún comando"
    assert c[0]["accion"] == "decir", f"acción inesperada: {c[0].get('accion')}"
    assert "Brian" in c[0]["texto"], f"no nombra a quien entra: {c[0]['texto'][:60]}"
    return c[0]["texto"][:40]


def t_triage_ia():
    import triage as T
    import cerebro
    a = cerebro.clasificar_ticket(T.Triage(GL, IA_CFG).ia,
                                  "no puede fichar", "no reconoce el rostro")
    assert a and a.get("categoria")
    return f"{a.get('categoria')}/{a.get('prioridad')}"


def t_conversacional_ia():
    from comun import conversacion
    from comun import ia as IA
    asis = conversacion.Asistente(IA.crear_texto(IA_CFG),
                                  conversacion.herramientas_glpi(GL, ENT))
    return asis.responder_texto("cuantos tickets abiertos hay?")[:55]


def t_ciclo_ia():
    import runpy
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "probar_ciclo.py"),
                   run_name="__main__")
    return "ciclo completo ejecutado (ver arriba)"


p("\n============= PRUEBA TOTAL ITHOS CLOUD =============")
check("1. Registro de clientes", t_registro)
check("2. Fabrica de IA (voz Charon)", t_ia_factory)
check("3. Gestor de cuota + avisos", t_cuota)
check("4. Notificadores (Telegram/Teams/Email)", t_notificadores)
check("5. GLPI + Reportes SLA (real)", t_glpi_reportes)
check("6. Integrador IVMS (DB real)", t_ivms)
check("7. Metricas de uso", t_metricas)
check("8. Base de conocimiento", t_kb)
check("9. Procesador acceso->voz", t_procesador)

p("\n>> Sondeando cuota de IA...")
try:
    hay_ia = ia_disponible()
except Exception as e:  # noqa: BLE001
    hay_ia = False
    p(f"   (probe error: {str(e)[:60]})")
if hay_ia:
    p("   Cuota disponible: corriendo pruebas de IA...")
    check("10. Triage con IA", t_triage_ia)
    check("11. Conversacional con IA", t_conversacional_ia)
    check("12. Ciclo de vida completo (IA)", t_ciclo_ia)
else:
    for n in ("10. Triage con IA", "11. Conversacional con IA",
              "12. Ciclo de vida completo (IA)"):
        R.append((n, "PENDIENTE (cuota IA)", "cuota agotada; se valida al resetear"))

p("\n---------------- RESULTADOS ----------------")
ok = fail = pend = 0
for nombre, estado, det in R:
    p(f"  [{estado:>18}] {nombre}  {det}")
    ok += estado == "OK"; fail += estado == "FALLA"; pend += "PENDIENTE" in estado
p(f"\n  TOTAL: {ok} OK - {pend} pendientes(cuota) - {fail} FALLAS")
p("=" * 52)

# El suite tiene que FALLAR cuando falla. Antes imprimía el conteo y salía con código 0 siempre:
# cualquier automatización —y cualquiera que lo corriera en un bucle— lo daba por bueno, así que
# una falla real podía quedarse ahí sin que nadie se enterara. Los PENDIENTES por cuota de IA no
# cuentan: eso no es un defecto del código, es que la cuota gratis del día se agotó.
sys.exit(1 if fail else 0)
