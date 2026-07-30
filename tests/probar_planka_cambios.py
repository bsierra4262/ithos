#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de los AVISOS DE CAMBIO DE ESTADO del tablero del equipo (Planka), sin red:

  1. Si alguien mueve una tarjeta A MANO en el tablero, ITHOS lo avisa al grupo diciendo de qué
     estado viene, a cuál pasó y quién la tiene asignada.
  2. Si no cambió nada, no dice nada (no molesta).
  3. Lo que mueve ITHOS por WhatsApp NO se vuelve a avisar (ya se lo confirmó a quien lo pidió).
  4. El estado SOBREVIVE a un reinicio del Gestor: los movimientos hechos mientras estuvo apagado
     se avisan igual al volver, en vez de tomarlos como punto de partida y callarlos.
  5. El seguimiento posterior ("¿cómo venís?") habla del estado ACTUAL: nunca pregunta por una
     tarea que la persona ya pasó a Hecho.

Regresión de un caso real: se movieron varias tarjetas a Hecho, ITHOS no avisó nada y siguió
preguntando por ellas.

Uso:  python tests/probar_planka_cambios.py
"""

import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
os.environ["ITHOS_DATA"] = tempfile.mkdtemp(prefix="ithos_planka_")   # estado aislado del test
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))

import planka_integrador as PI          # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


USUARIOS = [{"nombre": "Brian Sierra", "planka_id": "111", "telefono": "5491156660181"},
            {"nombre": "Alejandro Ayala", "planka_id": "222", "telefono": "5491150985151"}]
CFG = {"url": "https://tablero.ejemplo", "api_key": "x", "ithos_user_id": "999",
       "board_id": "b1", "project_id": "p1", "usuarios": USUARIOS}


class PlankaFalso:
    """El tablero: devuelve lo que le pongamos, sin red."""

    def __init__(self, tarjetas):
        self.tarjetas = tarjetas          # {cid: {"nombre","list","miembros"}}
        self.movidas = []

    def board(self, _bid):
        return {"lists": [{"id": "L1", "name": "Por hacer"}, {"id": "L2", "name": "Haciendo"},
                          {"id": "L3", "name": "En revisión / Esperando"}, {"id": "L4", "name": "Hecho"}]}

    def mover_tarjeta(self, cid, lid):
        self.movidas.append((cid, lid))


def integrador(tarjetas):
    """Un integrador con el tablero falso y el snapshot servido de `tarjetas`."""
    pi = PI.PlankaIntegrador(CFG, ia=None)
    pi.pk = PlankaFalso(tarjetas)
    pi._snapshot = lambda: {cid: {"nombre": t["nombre"], "list": t["list"],
                                  "miembros": set(t.get("miembros", []))}
                            for cid, t in pi.pk.tarjetas.items()}
    pi._asegurar_periodo = lambda ahora: None      # el rollover no es parte de este test
    return pi


def correr(pi):
    """Un tick; devuelve los mensajes que ITHOS habría mandado al grupo."""
    enviados = []
    pi._tick(lambda texto, tels=(): enviados.append((texto, list(tels))))
    return enviados


def main():
    print("=" * 78)
    print("TABLERO DEL EQUIPO — avisos de cambio de estado")
    print("=" * 78)

    tarjetas = {
        "c1": {"nombre": "CREAR USUARIOS EN EL AD", "list": "haciendo", "miembros": ["111"]},
        "c2": {"nombre": "INICIALIZAR LOS TELEFONOS", "list": "haciendo", "miembros": ["222"]},
        "c3": {"nombre": "CREAR INSTRUCTIVOS", "list": "por_hacer", "miembros": []},
    }
    pi = integrador(tarjetas)

    # 1) primer recorrido: es el punto de partida, no se avisa nada
    ok(not correr(pi), "el primer recorrido es el punto de partida (no avisa nada)")

    # 2) sin cambios: silencio
    ok(not correr(pi), "sin cambios en el tablero, no dice nada")

    # 3) alguien mueve DOS tarjetas a mano -> avisa, con estado anterior, nuevo y asignado
    pi.pk.tarjetas["c1"]["list"] = "hecho"
    pi.pk.tarjetas["c2"]["list"] = "en_espera"
    msgs = correr(pi)
    texto = "\n".join(t for t, _ in msgs)
    ok(len(msgs) == 1, "los cambios van en UN solo aviso, no uno por tarjeta", f"{len(msgs)} mensajes")
    ok("CREAR USUARIOS EN EL AD" in texto and "INICIALIZAR LOS TELEFONOS" in texto,
       "el aviso nombra las tarjetas que se movieron")
    ok("Haciendo" in texto and "Hecho" in texto and "En espera" in texto,
       "dice de qué estado viene y a cuál pasó", texto.replace("\n", " | ")[:110])
    ok("Brian Sierra" in texto and "Alejandro Ayala" in texto,
       "dice quién tiene asignada cada tarjeta")

    # 4) ya avisado: no se repite
    ok(not correr(pi), "un cambio ya avisado no se repite en el recorrido siguiente")

    # 5) lo que mueve ITHOS por WhatsApp no se re-avisa (ya se lo confirmó a quien lo pidió)
    pi._clave_a_id = {"por_hacer": "L1", "haciendo": "L2", "en_espera": "L3", "hecho": "L4"}
    c = {"nombre": tarjetas["c3"]["nombre"], "list": "por_hacer", "miembros": set()}
    resp = pi._mover_card(USUARIOS[0], "c3", c, "haciendo")
    pi.pk.tarjetas["c3"]["list"] = "haciendo"          # el tablero refleja el movimiento
    ok(resp and "Haciendo" in resp, "al moverla por WhatsApp, ITHOS lo confirma en la respuesta")
    ok(not correr(pi), "lo que movió ITHOS no se vuelve a avisar como cambio del tablero")

    # 6) REINICIO del Gestor: el estado se recuerda y los movimientos de mientras se avisan igual
    pi.pk.tarjetas["c3"]["list"] = "hecho"             # alguien la termina con ITHOS apagado
    pi2 = integrador(pi.pk.tarjetas)                   # "arranca de nuevo" (lee el estado del disco)
    msgs = correr(pi2)
    texto = "\n".join(t for t, _ in msgs)
    ok(bool(msgs) and "CREAR INSTRUCTIVOS" in texto and "Hecho" in texto,
       "tras un reinicio avisa lo que se movió mientras estuvo apagado",
       texto.replace("\n", " | ")[:110])

    # 7) el seguimiento habla del estado ACTUAL: no pregunta por lo que ya está en Hecho
    snap = pi2._snapshot()
    pregunta = pi2.seguimiento(USUARIOS[0], snap, pi2._ahora()) or ""
    ok("CREAR USUARIOS EN EL AD" not in pregunta,
       "el '¿cómo venís?' ya no pregunta por una tarea que se pasó a Hecho")

    print("\n" + "=" * 78)
    if FALLAS:
        print(f"FALLARON {len(FALLAS)} chequeo(s):")
        for f in FALLAS:
            print("  · " + f)
        sys.exit(1)
    print("TODO OK — los cambios del tablero se avisan y sobreviven a un reinicio.")


if __name__ == "__main__":
    main()
