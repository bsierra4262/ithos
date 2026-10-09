#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de la falla real del 9-oct-2026: ITHOS escribió 19.555 recordatorios duplicados.

QUÉ PASÓ. La API de GLPI devuelve **50 ítems** cuando no se le pasa `range`, y lo hace sin avisar:
no hay error ni bandera de "hay más". El ciclo pedía `/Ticket/<id>/ITILFollowup` a secas, así que
mientras un ticket tenía menos de 50 seguimientos todo andaba bien —el #666 recibió UN recordatorio
por día durante 52 días, que es lo diseñado—, pero el día que cruzó los 50 la API empezó a devolver
siempre los 50 MÁS VIEJOS. Desde ahí:

  · `_espera_pendiente()` calculaba el "último aviso" sobre una ventana congelada en el pasado,
  · el guard `ultimo.date() < ahora.date()` quedaba SIEMPRE en True,
  · y salía un recordatorio en CADA vuelta del ciclo (cada 5 segundos).

Cada recordatorio nuevo empujaba la ventana más lejos: se realimentaba solo. En seis horas escribió
1.269 comentarios en el #666; el #597 había llegado a 10.525. El cliente los ve todos.

Y no era sólo el recordatorio: TODAS las funciones del ciclo leen esa misma lista (si el cliente
respondió, si ya se pidió la confirmación, si ya se escaló). Pasados los 50 seguimientos, ITHOS
dejaba de ver lo que contestaba el cliente y el ticket no podía avanzar nunca más.

Lo segundo que falló: `_followup()` se comía el error cuando GLPI rechazaba la escritura, y
`recordar_espera()` devolvía True igual. El ciclo registraba "recordatorio enviado" sin haber
escrito nada, y como el ticket no cambiaba, lo reintentaba para siempre. Pasó: GLPI estuvo caído
tres horas y el log mostró 187 recordatorios "enviados" por hora que nunca existieron.

Uso:  python tests/probar_bucle_recordatorios.py
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

import ciclo as CI                      # noqa: E402
from comun import glpi as G             # noqa: E402
from textos_ticket import _texto_recordatorio_espera   # noqa: E402

FALLAS = []
ITHOS_UID = 28                          # el usuario con el que ITHOS escribe
TECS = {7, 8, ITHOS_UID}


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


def followup(fid, cuando, texto, uid=ITHOS_UID, privado=0):
    return {"id": fid, "users_id": uid, "is_private": privado, "content": texto,
            "date_creation": cuando.strftime("%Y-%m-%d %H:%M:%S")}


# Un ticket REAL como el #666: el pedido original y después un recordatorio por día, 60 días.
# Son 61 seguimientos: más de los 50 que devuelve GLPI por omisión.
HOY = datetime(2026, 10, 9, 15, 0, 0)
PEDIDO = followup(1000, HOY - timedelta(days=60),
                  "Para avanzar necesitamos que nos confirme el día. Quedamos a la espera de su "
                  "respuesta. Soporte ITH.")
TICKET_LARGO = [PEDIDO] + [
    followup(1000 + d, HOY - timedelta(days=60 - d), _texto_recordatorio_espera("confirmacion"))
    for d in range(1, 61)]


class GLPIFalso:
    """Imita a GLPI: si no le pasás `range`, devuelve sólo los 50 primeros. Sin avisar."""

    TOPE_SIN_RANGE = 50

    def __init__(self, fu):
        self.fu = fu
        self.pedidos = []

    def request(self, path, *a, **k):
        self.pedidos.append(path)
        if "ITILFollowup" not in path:
            return {}
        if "range=" not in path:
            return self.fu[:self.TOPE_SIN_RANGE]
        rango = path.split("range=")[1].split("&")[0]
        ini, fin = (int(x) for x in rango.split("-"))
        return self.fu[ini:fin + 1]


print("\n=== 1 · Leer los seguimientos COMPLETOS, no los 50 que da GLPI por omisión ===")
cli = GLPIFalso(TICKET_LARGO)
crudo = cli.request("/Ticket/666/ITILFollowup")
ok(len(crudo) == 50, "GLPI (simulado) devuelve sólo 50 si no se pide range", f"{len(crudo)} ítems")
completo = G.followups(cli, 666)
ok(len(completo) == len(TICKET_LARGO),
   "followups() PAGINA y los trae todos", f"{len(completo)} de {len(TICKET_LARGO)}")
ok(int(completo[-1]["id"]) == int(TICKET_LARGO[-1]["id"]),
   "y el último que trae es el ÚLTIMO de verdad (no uno viejo)")

print("\n=== 2 · Con la lista truncada el guard diario se rompe (el bug) ===")
esp_truncado = CI._espera_pendiente(crudo, TECS)
esp_completo = CI._espera_pendiente(completo, TECS)
ok(esp_truncado is not None and esp_completo is not None, "ambas listas dan una espera pendiente")
ultimo_trunc, ultimo_full = esp_truncado[1], esp_completo[1]
ok(ultimo_trunc.date() < HOY.date(),
   "con 50 seguimientos el 'último aviso' queda en el PASADO", str(ultimo_trunc.date()))
ok(ultimo_trunc.date() < ultimo_full.date(),
   "la lista completa ve un aviso MÁS NUEVO que la truncada",
   f"{ultimo_trunc.date()} vs {ultimo_full.date()}")
# Esto es el bucle: con la lista truncada el guard deja pasar un recordatorio en CADA vuelta.
ok(ultimo_full.date() == HOY.date(),
   "con la lista COMPLETA el guard ve el recordatorio de HOY y NO manda otro")

print("\n=== 3 · El ciclo manda UN recordatorio por día, no uno por vuelta ===")


class TriageFalso:
    def __init__(self):
        self.enviados = 0

    def recordar_espera(self, tid, motivo="confirmacion"):
        self.enviados += 1
        return True


def vueltas_del_ciclo(fu, cuantas=20):
    """Corre el guard del ciclo `cuantas` veces seguidas sobre el MISMO ticket, como hace el
    poller cada 5 segundos, y cuenta cuántos recordatorios saldrían."""
    tri, lista = TriageFalso(), list(fu)
    for _ in range(cuantas):
        esp = CI._espera_pendiente(lista, TECS)
        if not esp:
            break
        _primero, ultimo, motivo = esp
        if ultimo.date() < HOY.date() and CI._puede_recordar(lista, 666, TECS):
            if tri.recordar_espera(666, motivo):
                # Lo que de verdad pasa: el recordatorio QUEDA en el ticket.
                lista.append(followup(9000 + tri.enviados, HOY,
                                      _texto_recordatorio_espera(motivo)))
    return tri.enviados


salen = vueltas_del_ciclo(completo, cuantas=20)
ok(salen == 0, "ya hay uno de hoy en el ticket -> no sale ninguno más", f"{salen} enviados")

# Un ticket SANO: el pedido y tres recordatorios, el último AYER. Debe salir UNO solo, por más
# vueltas que dé el poller (que da una cada 5 segundos).
sano = [followup(3000, HOY - timedelta(days=4),
                 "Necesitamos que nos confirme el día. Quedamos a la espera de su respuesta. "
                 "Soporte ITH.")]
sano += [followup(3000 + d, HOY - timedelta(days=4 - d), _texto_recordatorio_espera("confirmacion"))
         for d in (1, 2, 3)]
salen_ayer = vueltas_del_ciclo(sano, cuantas=20)
ok(salen_ayer == 1,
   "si el último fue AYER sale exactamente UNO en 20 vueltas", f"{salen_ayer} enviados")

print("\n=== 4 · Tope absoluto: una red por si el espaciado vuelve a fallar ===")
ok(CI._cuantos_recordatorios(completo, TECS) == 60,
   "cuenta bien los recordatorios del ticket", str(CI._cuantos_recordatorios(completo, TECS)))
ok(not CI._puede_recordar(completo, 666, TECS),
   f"con 60 recordatorios (tope {CI._TOPE_RECORDATORIOS}) NO se le escribe más al cliente")
pocos = [PEDIDO] + [followup(2000 + i, HOY - timedelta(days=5 - i % 5),
                             _texto_recordatorio_espera("datos")) for i in range(3)]
ok(CI._puede_recordar(pocos, 666, TECS), "un ticket sano (3 recordatorios) sigue pudiendo recordar")

print("\n=== 5 · Si GLPI rechaza la escritura, NO se puede decir que se envió ===")
import triage as T                       # noqa: E402


class CliRechaza:
    session = "x"

    def abrir(self):
        return self

    def cerrar(self):
        pass

    def request(self, path, *a, **k):
        raise RuntimeError("ERROR_GLPI_ADD: insert rechazado")


tri = T.Triage.__new__(T.Triage)          # sin __init__: no queremos abrir IA ni red
tri.cli = CliRechaza()
ok(tri._followup(666, "hola") is False, "_followup() devuelve False cuando GLPI rechaza")
ok(tri.recordar_espera(666) is False,
   "recordar_espera() NO dice que mandó algo que no se escribió")
ok(tri.recordar_confirmacion(666) is False, "recordar_confirmacion() tampoco")
ok(tri.pedir_confirmacion(666) is False, "pedir_confirmacion() tampoco")


class CliAcepta(CliRechaza):
    def request(self, path, *a, **k):
        return {"id": 1}


tri.cli = CliAcepta()
ok(tri.recordar_espera(666) is True, "y cuando GLPI SÍ acepta, devuelve True")

print("\n" + "=" * 58)
if FALLAS:
    print(f"  FALLAS: {len(FALLAS)}")
    for f in FALLAS:
        print("   -", f)
    print("=" * 58)
    sys.exit(1)
print("  BUCLE DE RECORDATORIOS: OK — todos los chequeos verdes")
print("=" * 58)
