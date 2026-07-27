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
    cfg = next(c for c in json.load(open(os.path.join(BASE, "central", "clientes.json"),
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

    await asyncio.sleep(16)          # dejar detectar + triage + seguimiento
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
    p(f"\n  {'✅ PRODUCCIÓN OK: llegó, clasificó y compuso los mensajes.' if ok else '❌ REVISAR: no se generaron avisos.'}")
    admin = G.GLPIClient(gl)          # token admin (el del cliente no puede purgar)
    admin.abrir()
    admin.request(f"/Ticket/{tid}?force_purge=1", "DELETE")
    p(f"  [-] Ticket #{tid} purgado.")
    admin.cerrar()
    cli.cerrar()


if __name__ == "__main__":
    asyncio.run(main())
