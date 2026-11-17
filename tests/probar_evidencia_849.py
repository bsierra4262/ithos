#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: si el cliente dice que algo RESUELTO sigue fallando, ITHOS pide la evidencia (ticket #849), sin red.

QUÉ PASÓ. El técnico resolvió el #849 de raíz: la persona no estaba sincronizada en la terminal, se
le sacó el PIN y se le volvió a dar acceso. Cuando ITHOS pidió la confirmación, el cliente contestó
«No puede fichar aún» y nada más. Antes, ITHOS reabría el ticket y lo dejaba En curso: había que
volver a revisar a ciegas algo que ya se había revisado, sin saber en qué terminal, de qué lado del
molinete ni cuándo había sido el intento.

LA REGLA. ITHOS le pide la evidencia concreta —foto o video del error en la terminal, qué terminal y
qué lado del molinete, fecha y hora— y el ticket queda EN ESPERA de eso: la pelota es del cliente,
el SLA no corre y el recordatorio diario le habla de "la información que le solicitamos".

Uso:  python tests/probar_evidencia_849.py
"""

import os
import sys
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))

import ciclo as CI                 # noqa: E402
import textos_ticket as TX         # noqa: E402
import triage as TRI               # noqa: E402

FALLAS = []


def ok(cond, msg):
    print(("  OK   " if cond else "  FALLA ") + msg)
    if not cond:
        FALLAS.append(msg)


print("\n=== 1 · Ticket de fichaje: pide imagen del error, terminal, lado del molinete y cuándo ===")
t = TX.texto_pedido_evidencia("Facundo", "Legajo 13722 Berretta Silvia Patricia. "
                              "La persona no puede realizar el fichaje biométrico")
print("   ", t)
ok(t.startswith("Hola Facundo, "), "saluda al solicitante por su nombre")
ok("foto o un video" in t and "mensaje de error" in t, "pide foto o video donde se vea el error")
ok("terminal" in t and "molinete" in t and "entrada o salida" in t,
   "pide en qué terminal y de qué lado del molinete")
ok("fecha y la hora" in t, "pide fecha y hora del intento")
ok(TX._MARCA_ESPERA_CLIENTE in t.lower(), "termina con el cierre de espera (el ciclo lo reconoce)")
ok(TX._MARCA_EVIDENCIA in t.lower(), "lleva la firma del pedido de evidencia")

print("\n=== 2 · Otro tipo de ticket: evidencia genérica, sin hablar de molinetes ===")
g = TX.texto_pedido_evidencia("", "No abre el sistema de liquidación")
ok(g.startswith("Hola, "), "sin nombre, saluda igual sin inventar uno")
ok("molinete" not in g and "captura" in g, "pide captura o video, no habla de terminales")

print("\n=== 3 · El ciclo: «No puede fichar aún» -> pide evidencia, NO cierra ni deja En curso ===")
CONF = "Le informamos que su solicitud fue resuelta. Por favor, confírmenos si ya puede fichar."
ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
llamadas = []


class _Cli:
    def tickets_recientes(self, n):
        return [{"id": 849, "status": 5, "entities_id": 0, "name": "Legajo 13722",
                 "content": "no puede realizar el fichaje biométrico", "users_id_recipient": 26}]

    def abrir(self): pass
    def cerrar(self): pass

    def request(self, path, method=None, data=None):
        if path.startswith("/Ticket/849/ITILFollowup"):
            return [{"id": 1, "users_id": 28, "content": CONF, "date_creation": ahora},
                    {"id": 2, "users_id": 26, "content": "<p>No puede fichar aún</p>",
                     "date_creation": ahora}]
        if path.startswith("/User/"):
            return {"firstname": "Facundo", "realname": "Monaco"}
        return {}


class _Tri:
    cfg_glpi = {"horario_atencion": {"dias": [0, 1, 2, 3, 4, 5, 6], "desde": "00:00", "hasta": "23:59"}}

    def cliente_confirma(self, texto): llamadas.append(("confirma", texto)); return False
    def pedir_evidencia(self, tid, ticket=None): llamadas.append(("evidencia", tid, ticket)); return True
    def cerrar(self, tid): llamadas.append(("cerrar", tid)); return True
    def recordar_confirmacion(self, tid): llamadas.append(("recordar", tid)); return True
    def pedir_confirmacion(self, tid): return True
    def poner_en_curso(self, tid): llamadas.append(("en_curso", tid)); return True
    def nota_interna(self, tid, texto): return True


_orig = CI.G.de_entidad
CI.G.de_entidad = lambda tks, ent: tks
try:
    CI.gestionar_ciclo(_Cli(), _Tri(), 0, {})
finally:
    CI.G.de_entidad = _orig
tipos = [c[0] for c in llamadas]
ok(("confirma", "No puede fichar aún") in llamadas, "la IA lee lo que contestó el cliente")
ok("evidencia" in tipos, "pide la evidencia")
ev = next((c for c in llamadas if c[0] == "evidencia"), None)
ok(bool(ev) and (ev[2] or {}).get("name") == "Legajo 13722",
   "le pasa el ticket, para saludar al solicitante y elegir qué evidencia pedir")
ok("cerrar" not in tipos and "en_curso" not in tipos, "no cierra ni lo deja En curso")

print("\n=== 4 · triage.pedir_evidencia: comentario público + EN ESPERA ===")
hecho = []


class _CliT:
    def abrir(self): pass
    def cerrar(self): pass
    def request(self, path, method=None, data=None):
        hecho.append((path, method, data))
        return {}


tri = TRI.Triage.__new__(TRI.Triage)
tri.cli = _CliT()
tri._nombre_solicitante = lambda ticket: "Facundo"
ok(tri.pedir_evidencia(849, {"name": "Legajo 13722", "content": "no puede fichar"}) is True,
   "devuelve True cuando GLPI acepta el cambio")
fu = [d for p, m, d in hecho if p == "/ITILFollowup"]
st = [d for p, m, d in hecho if p == "/Ticket/849" and m == "PUT"]
ok(bool(fu) and "molinete" in fu[0]["input"]["content"] and not fu[0]["input"].get("is_private"),
   "deja el pedido como comentario PÚBLICO (lo tiene que ver el cliente)")
ok(bool(st) and st[0]["input"]["status"] == 4, "pasa el ticket a EN ESPERA (status 4)")

print("\n=== 5 · El recordatorio habla de la información pedida, no de una confirmación ===")
viejo = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
fus = [{"id": 1, "users_id": 28, "is_private": 0, "content": CONF, "date_creation": viejo},
       {"id": 2, "users_id": 26, "is_private": 0, "content": "No puede fichar aún", "date_creation": viejo},
       {"id": 3, "users_id": 28, "is_private": 0, "content": t, "date_creation": viejo}]
pend = CI._espera_pendiente(fus)
ok(bool(pend) and pend[2] == "datos", "queda esperando al cliente, motivo 'datos'")
fus.append({"id": 4, "users_id": 26, "is_private": 0, "content": "Adjunto la foto",
            "date_creation": viejo})
ok(CI._espera_pendiente(fus) is None, "cuando el cliente manda la evidencia, deja de esperar")

print()
if FALLAS:
    print(f"FALLARON {len(FALLAS)}")
    sys.exit(1)
print("TODO OK")
