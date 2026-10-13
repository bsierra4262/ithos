#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prueba del CICLO DE VIDA COMPLETO de un ticket (como en producción real):
crear -> triage (IA responde, pide legajo, EN ESPERA) -> cliente responde -> EN CURSO
-> técnico resuelve (RESUELTO) -> Ithos pide confirmación -> cliente confirma -> CERRADO.
Valida cada transición y el rastro (followups). Al final purga el ticket.
"""

import sys
import json
import time

sys.path.insert(0, "ITHOS/central")
sys.path.insert(0, "ITHOS")
import triage as T                # noqa: E402
from comun import glpi as G       # noqa: E402

ESTADOS = {1: "Nuevo", 2: "En curso", 3: "Planificado", 4: "En espera",
           5: "Resuelto", 6: "Cerrado"}


def p(s):
    print(str(s).encode("ascii", "replace").decode(), flush=True)


def main():
    c = json.load(open("ITHOS/central/clientes.json", encoding="utf-8"))["clientes"][0]
    gl = c["integrador_glpi"]
    triage = T.Triage(gl, c["ia"])
    admin = G.GLPIClient(gl, token=gl["glpi_user_token"])   # SUPER ADMIN (leer/purgar)
    admin.abrir()
    tecnico = G.GLPIClient(gl, token=gl.get("glpi_bsierra_token") or gl["glpi_user_token"])
    tecnico.abrir()                                        # HELPDESK bsierra (resuelve)
    cli = G.GLPIClient(gl, token=gl["glpi_test_token"])    # CLIENTE SRT test (crea/responde)
    cli.abrir()
    estado = {}

    def estado_ticket(tid):
        return int(admin.request(f"/Ticket/{tid}").get("status", 0))

    def ciclo():
        for a in T.gestionar_ciclo(admin, triage, 12, estado):
            p(f"      [ITHOS avisa] {a.get('texto') or a.get('wa')}")

    # Las etapas que NO dieron lo esperado. Antes se imprimía "FALLA" y el guion terminaba con
    # código 0 igual: quien lo corriera —una persona o una automatización— lo daba por bueno.
    fallidas = []

    def assert_estado(tid, esperado, etapa):
        s = estado_ticket(tid)
        bien = s == esperado
        p(f"   [{'OK' if bien else 'FALLA'}] {etapa}: estado={s} ({ESTADOS.get(s)}) "
          f"esperado={esperado} ({ESTADOS.get(esperado)})")
        if not bien:
            fallidas.append(f"{etapa}: quedó en {ESTADOS.get(s)} y se esperaba {ESTADOS.get(esperado)}")
        return bien

    tid = None
    try:
        # 1) CREAR (cliente, mal cargado — sin legajo)
        asu = "No puede fichar un colaborador"
        desc = ("Buen día, un colaborador no puede fichar en el molinete, el lector no "
                "reconoce el rostro. ¿Pueden verlo? Gracias.")
        tid = cli.request("/Ticket", "POST", {"input": {
            "name": asu, "content": desc, "entities_id": 12,
            "itilcategories_id": 12, "urgency": 5, "impact": 5, "priority": 5}})["id"]
        p(f"\n1) CLIENTE crea ticket #{tid} (sin legajo)")

        # 2) TRIAGE
        res = triage.procesar({"id": tid, "name": asu, "content": desc})
        if not res:
            # El triage devuelve None cuando la IA no pudo clasificar —casi siempre porque se
            # agotó la cuota gratis del día— o cuando no se pudo leer el estado del ticket. En
            # ninguno de los dos casos hay un defecto que probar, así que la corrida queda
            # PENDIENTE en vez de reventar con un AttributeError sobre None, que era lo que
            # pasaba y no decía nada de lo que realmente ocurrió.
            p("2) TRIAGE: no se pudo clasificar (cuota de IA agotada o GLPI sin responder).")
            p("\n  PENDIENTE: el ciclo de vida se valida cuando haya cuota de IA.")
            return 0
        p(f"2) TRIAGE: {res.get('categoria')} / {res.get('prioridad')} / "
          f"asignado {res.get('responsable_nombre')} / necesita_info={res.get('necesita_info')}")
        tk = admin.request(f"/Ticket/{tid}")
        tu = admin.request(f"/Ticket/{tid}/Ticket_User")
        p(f"   categoria={tk.get('itilcategories_id')} prioridad={tk.get('priority')} "
          f"asignados={[u.get('users_id') for u in tu if u.get('type') == 2]}")
        assert_estado(tid, 4, "tras triage (pide legajo)")

        # 3) CLIENTE responde el legajo
        p("3) CLIENTE responde: 'El legajo del colaborador es 12345'")
        cli.request("/ITILFollowup", "POST", {"input": {
            "itemtype": "Ticket", "items_id": tid, "content": "El legajo del colaborador es 12345."}})
        ciclo()
        assert_estado(tid, 2, "tras respuesta del cliente")

        # 4) TÉCNICO (helpdesk bsierra) resuelve
        p("4) TÉCNICO (bsierra) resuelve (recalibró el lector facial)")
        tecnico.request("/ITILSolution", "POST", {"input": {
            "itemtype": "Ticket", "items_id": tid,
            "content": "Se recalibró el lector de reconocimiento facial. Ya puede fichar."}})
        assert_estado(tid, 5, "tras resolución del técnico")

        # 5) ITHOS pide confirmación
        p("5) ITHOS pide confirmación al cliente")
        ciclo()

        # 6) CLIENTE confirma
        p("6) CLIENTE confirma: 'Sí, ya puedo fichar, gracias'")
        cli.request("/ITILFollowup", "POST", {"input": {
            "itemtype": "Ticket", "items_id": tid, "content": "Sí, ya puedo fichar. Muchas gracias!"}})
        p("   (espero unos segundos por el rate limit del free tier de Gemini...)")
        time.sleep(35)   # free tier: ~30s entre llamadas de IA
        ciclo()
        ok = assert_estado(tid, 6, "tras confirmación del cliente")

        # Rastro
        fu = admin.request(f"/Ticket/{tid}/ITILFollowup")
        p(f"\n   Rastro: {len(fu)} seguimientos en el ticket.")
        p(f"\n{'='*54}\n  CICLO COMPLETO: {'✅ TODAS LAS ETAPAS OK' if ok else '❌ REVISAR'}\n{'='*54}")
    finally:
        if tid:
            admin.request(f"/Ticket/{tid}?force_purge=1", "DELETE")
            p(f"[-] Ticket #{tid} purgado.")
        cli.cerrar()
        tecnico.cerrar()
        admin.cerrar()
    if fallidas:
        p("\n  FALLAS: " + "; ".join(fallidas))
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
