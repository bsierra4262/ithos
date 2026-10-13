#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PRUEBA DE PRODUCCIÓN — el flujo REAL del central (como en vivo):
  El vigilante mira GLPI, DETECTA un ticket nuevo, avisa por voz, lo CLASIFICA con
  IA, y COMPONE los mensajes de WhatsApp (aviso + triage). Todo real contra el GLPI
  de INTELLIHELP. Al final purga el ticket de prueba.

Por defecto WhatsApp está en modo MOSTRAR (imprime el mensaje exacto con el prefijo
🤖 ITHOS, sin enviarlo al grupo). Para enviarlo DE VERDAD al grupo:
    set ITHOS_WA_REAL=1   (PowerShell: $env:ITHOS_WA_REAL=1)

Correr:  python probar_produccion.py
"""

import os
import sys
import json
import asyncio

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "ITHOS", "central"))
sys.path.insert(0, os.path.join(BASE, "ITHOS"))

import integrador_glpi                 # noqa: E402
import triage as T                     # noqa: E402
from comun import glpi as G            # noqa: E402
from comun import whatsapp as WA       # noqa: E402


def p(s=""):
    print(str(s).encode("ascii", "replace").decode(), flush=True)


VOCES, WAMSGS = [], []


async def enviar_comando(cmd):
    if cmd.get("accion") == "decir":
        p(f"   [VOZ ITHOS] {cmd.get('texto')}")
        VOCES.append(cmd.get("texto"))


class WAMostrar:
    """Muestra el mensaje EXACTO que saldría por WhatsApp (con prefijo 🤖 ITHOS)."""
    def enviar(self, texto):
        m = WA.con_prefijo(texto)
        p(f"   [WhatsApp -> grupo] {m.replace(chr(10), ' | ')}")
        WAMSGS.append(m)
        return True


async def main():
    cfg = next(c for c in json.load(open(os.path.join(BASE, "ITHOS", "central", "clientes.json"),
                                          encoding="utf-8"))["clientes"]
               if "INTELLIHELP" in c["nombre"])
    gl = dict(cfg["integrador_glpi"])
    gl["poll_interval"] = 3
    entidad = int(gl["entity_id"])

    wa = (WA.crear_whatsapp({**cfg["notificaciones"][0], "enabled": True, "tipo": "no_oficial"})
          if os.environ.get("ITHOS_WA_REAL") == "1" else WAMostrar())
    if os.environ.get("ITHOS_WA_REAL") == "1":
        p("   (WhatsApp REAL: conectando... esperá unos segundos)")
        await asyncio.sleep(8)

    triage = T.Triage(gl, cfg["ia"])            # IA con respaldo (Gemini -> Groq)
    stop = asyncio.Event()

    p("=" * 60)
    p("  PRUEBA DE PRODUCCIÓN — vigilante GLPI en vivo (INTELLIHELP)")
    p("=" * 60)
    tarea = asyncio.create_task(integrador_glpi.vigilar(
        gl, enviar_comando, triage=triage, wa=wa, stop=stop, nombre_cliente=cfg["nombre"]))

    p("1) Vigilante en marcha; fijando baseline de tickets...")
    await asyncio.sleep(6)

    # Crear un ticket REAL (como lo cargaría un cliente), sin legajo
    cli = G.GLPIClient(gl, token=gl["glpi_test_token"])
    cli.abrir()
    asunto = "No puede fichar un colaborador en planta"
    desc = ("Buen día, un colaborador no logra fichar en el molinete de planta, "
            "el lector no reconoce el rostro. ¿Pueden verlo? Gracias.")
    tid = cli.request("/Ticket", "POST", {"input": {
        "name": asunto, "content": desc, "entities_id": entidad,
        "urgency": 3, "impact": 3, "priority": 3}})["id"]
    p(f"\n2) CLIENTE crea un ticket REAL en GLPI: #{tid}")
    p("   (el vigilante debería detectarlo, avisar, clasificar y componer WhatsApp)\n")

    # Espera ADAPTATIVA, no 16 segundos fijos. Cuando la IA primaria está sin cuota del día, la
    # cadena recorre su escalera de modelos antes de pasar al respaldo, y eso se come la ventana:
    # el ticket SÍ se atiende en producción —el poller sigue dando vueltas—, pero el test cortaba
    # antes y declaraba que no había pasado nada. Ahora corta apenas hay resultado.
    for _ in range(30):              # hasta ~90 s, pero sale en cuanto llega lo que se espera
        if VOCES and WAMSGS:
            break
        await asyncio.sleep(3)
    stop.set()
    await tarea

    # Verificar y limpiar
    tk = cli.request(f"/Ticket/{tid}")
    est = {1: "Nuevo", 2: "En curso", 4: "En espera", 5: "Resuelto", 6: "Cerrado"}
    p("\n" + "=" * 60)
    p("  RESULTADO")
    p("=" * 60)
    p(f"  Ticket #{tid}: categoría={tk.get('itilcategories_id')} prioridad={tk.get('priority')} "
      f"estado={est.get(int(tk.get('status', 0)), '?')}")
    p(f"  Avisos por VOZ generados: {len(VOCES)}")
    p(f"  Mensajes de WhatsApp compuestos: {len(WAMSGS)}")
    ok = len(VOCES) >= 1 and len(WAMSGS) >= 1
    # Si no salió nada, hay que distinguir DOS cosas que se ven igual y no lo son: que el código
    # esté roto, o que se haya agotado la cuota gratis de IA del día. Lo segundo no es un defecto,
    # así que no puede hacer fallar la prueba: una alarma que suena por algo esperable se vuelve
    # ruido y se termina ignorando, que es justo lo que no queremos.
    sin_cuota = False
    if not ok:
        try:
            triage.ia.chat("Respondé exactamente: ok", "ok", json_out=False)
        except Exception as e:  # noqa: BLE001
            m = str(e).lower()
            sin_cuota = any(t in m for t in ("429", "resource_exhausted", "rate limit",
                                             "rate_limited", "quota"))
    if ok:
        p("\n  PRODUCCION OK: llego, clasifico y compuso los mensajes.")
    elif sin_cuota:
        p("\n  PENDIENTE: la cuota de IA del dia esta agotada en TODA la cadena; no se puede "
          "validar el triage hoy. No es una falla del codigo.")
    else:
        p("\n  REVISAR: no se generaron avisos y la IA responde. Hay algo roto.")
    admin = G.GLPIClient(gl)          # token admin (el del cliente no puede purgar)
    admin.abrir()
    admin.request(f"/Ticket/{tid}?force_purge=1", "DELETE")
    p(f"  [-] Ticket #{tid} purgado.")
    admin.cerrar()
    cli.cerrar()
    # La prueba tiene que FALLAR cuando falla: antes imprimía el tilde o la cruz y salía con
    # código 0 igual, así que una corrida mala se veía exactamente igual que una buena para
    # cualquiera que la ejecutara en un bucle.
    return 0 if (ok or sin_cuota) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
