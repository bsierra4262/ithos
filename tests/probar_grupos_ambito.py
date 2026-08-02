#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test del RUTEO POR GRUPO, sin red: cada aviso va a su grupo y en cada grupo se contesta lo suyo.

Un solo grupo para todo se vuelve inservible: las alertas de tickets tapan las tareas del equipo,
las cosas del sistema le llegan a gente a la que no le sirven, y quien sólo quiere preguntar algo
termina leyendo alertas todo el día. Por eso cada grupo tiene un ÁMBITO.

Lo que se verifica:

  1. La tabla de ámbitos dice lo que tiene que decir (qué recibe y qué contesta cada uno).
  2. Los avisos SALEN sólo a los grupos que corresponden: los de tickets y SLA al de soporte, los
     del tablero al de tareas, los del sistema y la voz al del dueño — y el de consultas NO recibe
     ninguna alerta.
  3. Las @menciones al técnico asignado siguen la misma regla.
  4. Un mensaje que entra sabe de QUÉ grupo viene, y ahí se decide qué se puede contestar.
  5. Una configuración vieja (un `grupo` suelto) sigue funcionando igual: un grupo que recibe todo.

Uso:  python tests/probar_grupos_ambito.py
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)

from comun import ambitos as AMB          # noqa: E402
from comun import notificadores as NOT     # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


CFG = {"grupos": [{"grupo": "ITHOS", "ambito": "consultas"},
                  {"grupo": "ITHOS_SOPORTE", "ambito": "soporte"},
                  {"grupo": "ITHOS_TRELLO", "ambito": "tareas"},
                  {"grupo": "ITHOS_DEMO", "ambito": "sistema"}]}

print("\n=== 1 · Qué recibe y qué contesta cada grupo ===")
ok(not AMB.AMBITOS["consultas"]["recibe"],
   "el grupo de CONSULTAS no recibe ninguna alerta")
ok(AMB.responde("consultas") == AMB.TODO,
   "pero puede consultar cualquier cosa (todas las capacidades)")
ok(AMB.recibe("soporte", AMB.TICKETS) and AMB.recibe("soporte", AMB.SLA),
   "el de SOPORTE recibe los avisos de tickets y de SLA")
ok(not AMB.recibe("soporte", AMB.PLANKA) and not AMB.recibe("soporte", AMB.SISTEMA),
   "y no se llena con el tablero ni con cosas del sistema")
ok(AMB.responde("soporte") == AMB.TICKETS, "en SOPORTE sólo se contestan tickets")
ok(AMB.recibe("tareas", AMB.PLANKA) and not AMB.recibe("tareas", AMB.TICKETS),
   "el del TABLERO recibe sólo lo de Planka")
ok(AMB.responde("tareas") == AMB.PLANKA, "y ahí sólo se habla de tareas")
ok(AMB.recibe("sistema", AMB.SISTEMA) and AMB.recibe("sistema", AMB.VOZ),
   "el del dueño recibe los avisos del sistema y el entrenamiento de voz")
ok(not AMB.recibe("sistema", AMB.TICKETS),
   "y no le entran los tickets (para eso está el de soporte)")
ok(AMB.responde("sistema") == AMB.TODO, "pero puede preguntar de todo")
ok(all(AMB.recibe("todo", t) for t in AMB.AVISOS) and AMB.responde("todo") == AMB.TODO,
   "un cliente con un solo grupo lo recibe todo, como antes")
ok(AMB.normalizar("no_existe") == "todo" and AMB.normalizar(None) == "todo",
   "un ámbito mal escrito no rompe nada: cae en el de compatibilidad")

print("\n=== 2 · Cada aviso sale SOLO a su grupo ===")


class CanalFalso:
    """El canal de WhatsApp real, con los grupos ya resueltos y sin cliente de verdad."""

    def __init__(self, cfg):
        self.grupos = [dict(g, jid=f"jid:{g['grupo']}") for g in AMB.grupos_de(cfg)]
        self.respuesta = "texto"
        self.enviados = []                       # [(grupo, texto)]

        class _Listo:
            @staticmethod
            def is_set():
                return True
        self._listo = _Listo()

        class _Cli:
            @staticmethod
            def send_message(jid, texto):
                pass
        self.client = _Cli()

    # se reusan los métodos REALES de ruteo
    from comun.whatsapp import WhatsAppNoOficial as _W
    _destinos = _W._destinos
    enviar = _W.enviar
    enviar_mencion = _W.enviar_mencion
    _mandar_voz = staticmethod(lambda *a, **k: None)
    _msg_con_menciones = staticmethod(lambda *a, **k: None)


def enviados_a(cfg, tipo, mencion=False):
    canal = CanalFalso(cfg)
    vistos = []
    canal.client.send_message = lambda jid, texto: vistos.append(str(jid))
    if mencion:
        canal.enviar_mencion("hola", ["5491150985151"], tipo=tipo)
    else:
        canal.enviar("hola", tipo=tipo)
    return sorted(v.replace("jid:", "") for v in vistos)


ok(enviados_a(CFG, AMB.TICKETS) == ["ITHOS_SOPORTE"],
   "un aviso de ticket va SÓLO al grupo de soporte", str(enviados_a(CFG, AMB.TICKETS)))
ok(enviados_a(CFG, AMB.SLA) == ["ITHOS_SOPORTE"],
   "el SLA y los reportes, también al de soporte")
ok(enviados_a(CFG, AMB.PLANKA) == ["ITHOS_TRELLO"],
   "el tablero avisa sólo en su grupo", str(enviados_a(CFG, AMB.PLANKA)))
ok(enviados_a(CFG, AMB.SISTEMA) == ["ITHOS_DEMO"],
   "los reinicios y avisos del sistema, sólo al grupo del dueño")
ok(enviados_a(CFG, AMB.VOZ) == ["ITHOS_DEMO"],
   "el entrenamiento de la voz, también")
ok("ITHOS" not in sum((enviados_a(CFG, t) for t in AMB.AVISOS), []),
   "el grupo de CONSULTAS no recibe NINGUNA alerta")

print("\n=== 3 · Las @menciones al técnico siguen la misma regla ===")
ok(enviados_a(CFG, AMB.TICKETS, mencion=True) == ["ITHOS_SOPORTE"],
   "mencionar al asignado por un ticket va al grupo de soporte")
ok(enviados_a(CFG, AMB.PLANKA, mencion=True) == ["ITHOS_TRELLO"],
   "y mencionarlo por una tarea, al del tablero")

print("\n=== 4 · Al entrar, el mensaje sabe de qué grupo viene ===")
canal = CanalFalso(CFG)
por_nombre = {g["grupo"]: g for g in canal.grupos}
ok(len(canal.grupos) == 4, "los cuatro grupos quedan configurados")
ok(por_nombre["ITHOS_SOPORTE"]["ambito"] == "soporte"
   and por_nombre["ITHOS_TRELLO"]["ambito"] == "tareas",
   "cada uno con su ámbito")
recibidos = []
for g in canal.grupos:
    recibidos.append((g["grupo"], AMB.responde(g["ambito"])))
ok(("ITHOS", AMB.TODO) in recibidos and ("ITHOS_SOPORTE", AMB.TICKETS) in recibidos
   and ("ITHOS_TRELLO", AMB.PLANKA) in recibidos and ("ITHOS_DEMO", AMB.TODO) in recibidos,
   "y con eso se decide qué se contesta en cada uno", str(recibidos))
fuera = AMB.fuera_de_alcance(AMB.PLANKA, canal.grupos)
ok("sólo manejo" in fuera and "ITHOS" in fuera,
   "si preguntan otra cosa en el grupo del tablero, se los deriva al de consultas", fuera)

print("\n=== 5 · Una configuración vieja sigue andando ===")
viejo = {"grupo": "Jarvis_DEMO"}
ok(AMB.grupos_de(viejo) == [{"grupo": "Jarvis_DEMO", "ambito": "todo"}],
   "un `grupo` suelto se toma como un grupo que recibe todo")
ok(sorted(set(sum((enviados_a(viejo, t) for t in AMB.AVISOS), []))) == ["Jarvis_DEMO"],
   "y le siguen llegando todos los avisos, como antes")

print("\n=== 6 · El panel muestra los grupos y su ámbito ===")
CanalFalso.__name__ = "WhatsAppNoOficial"        # el estado del canal se resuelve por el nombre
est = NOT.estado_canal(CanalFalso(CFG))
ok(est["activo"] and "ITHOS_SOPORTE (soporte)" in est["detalle"],
   "el estado del canal dice qué grupo cubre qué", est["detalle"])

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("TODO OK · cada grupo recibe lo suyo y contesta lo suyo")
