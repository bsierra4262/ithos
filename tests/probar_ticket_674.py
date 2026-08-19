#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de dos fallas reales del ticket #674 ("No ficha", 19-ago-2026), sin red.

El ticket era el caso de UNA agente que no puede fichar a la mañana. Pasaron dos cosas mal:

  1. Salió con prioridad MEDIA. Todos los tickets iguales que ITHOS había triageado salieron
     Baja (#657, #658, #659, #662, #664, #665, #667). La prioridad era sólo un PISO, así que si
     el modelo decía "Media" nadie lo corregía: dos tickets del mismo tipo con prioridades
     distintas, y los reportes de SLA midiendo ruido.

  2. El técnico escribió "El inconveniente quedó solucionado" y el ticket SE QUEDÓ En curso. La
     causa: interpretar ese comentario necesita la IA, y en ese momento la cadena estaba caída.
     El ciclo daba el comentario POR VISTO igual, así que cuando la IA volvió diez minutos
     después ya no lo miraba más. El ticket quedaba trabado para siempre.

Uso:  python tests/probar_ticket_674.py
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
sys.path.insert(0, os.path.join(APP, "central"))

import cerebro                        # noqa: E402
import ciclo as CI                    # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


ASUNTO = "No ficha"
DESC = ("La Agente Nakamura Maria Paula Legajo 14363. Todos los días tiene problemas para fichar, "
        "siempre a su ingreso da ERROR, prueba mas tarde y si funciona.")

print("\n=== 1 · La prioridad la decide el ALCANCE, no el ánimo del modelo ===")
# Tal cual lo devolvió el modelo en el ticket real: caso de una persona, pero prioridad Media.
salida, corr = cerebro.coherente(
    {"alcance": "individual", "categoria": "TERMINALES", "prioridad": "Media",
     "responsable": "bsierra", "necesita_info": False,
     "primera_respuesta": "Hola Pablo, con el legajo 14363 ya lo estamos trabajando."},
    ASUNTO, DESC)
ok(salida["prioridad"] == "Baja",
   "el caso de UNA persona sale Baja, no Media", salida["prioridad"])
ok(any("prioridad" in c for c in corr), "y queda registrado por qué se corrigió", str(corr))

# El mismo ticket, dos veces, no puede salir distinto.
iguales = {cerebro.coherente(
    {"alcance": "individual", "categoria": "TERMINALES", "prioridad": p,
     "responsable": "bsierra", "necesita_info": False, "primera_respuesta": "Hola."},
    ASUNTO, DESC)[0]["prioridad"] for p in ("Baja", "Media", "Alta", "Urgente")}
ok(iguales == {"Baja"},
   "diga lo que diga el modelo, dos tickets iguales salen con la MISMA prioridad", str(iguales))

# Y lo que ya andaba tiene que seguir andando: el alcance grande no se baja.
for alcance, esperada in (("grupo", "Media"), ("equipo", "Alta"),
                          ("sede", "Urgente"), ("masivo", "Urgente")):
    r, _ = cerebro.coherente(
        {"alcance": alcance, "categoria": "MOLINETES", "prioridad": "Baja",
         "responsable": "bsierra", "necesita_info": False, "primera_respuesta": "Hola."})
    ok(r["prioridad"] == esperada, f"alcance '{alcance}' -> {esperada}", r["prioridad"])

print("\n=== 2 · Sin IA, el comentario del técnico NO se da por visto ===")


class _TriageFalso:
    """La IA contesta o no, según se le diga. Cuenta qué le pidieron."""

    def __init__(self, ia_viva):
        self.ia_viva = ia_viva
        self.cfg_glpi = {"horario_atencion": {"dias": [0, 1, 2, 3, 4, 5, 6],
                                              "desde": "00:00", "hasta": "23:59"},
                         "tecnicos": [{"glpi_id": 7, "nombre": "Brian Sierra"}]}
        self.resueltos = []

    def tecnico_resolvio(self, texto):
        return True if self.ia_viva else None

    def tecnico_pide_confirmacion(self, texto):
        return False if self.ia_viva else None

    def marcar_resuelto(self, tid, solucion="", autor=None):
        self.resueltos.append(tid)
        return True

    def pedir_confirmacion(self, tid):
        return True


TICKET = {"id": 674, "status": 2, "entities_id": 12, "name": ASUNTO, "content": DESC}
COMENTARIO = [{"id": 900, "users_id": 7, "is_private": 0,
               "content": "El inconveniente quedó solucionado. Empezamos revisando sus fichadas "
                          "en tiempo real desde la base de datos.",
               "date_creation": "2026-08-19 13:19:03"}]


class _ClienteFalso:
    session = "s"

    def request(self, path, *a, **k):
        if path.endswith("/ITILFollowup"):
            return COMENTARIO
        if path.startswith("/Ticket/674"):
            return TICKET
        return []

    def tickets_recientes(self, n=30):
        return [TICKET]

    def abrir(self):
        pass

    def cerrar(self):
        pass


# a) la IA está CAÍDA: no pasa nada, pero el comentario queda PENDIENTE
caido = _TriageFalso(ia_viva=False)
estado = {}
list(CI.gestionar_ciclo(_ClienteFalso(), caido, 12, estado))
ok(not caido.resueltos, "con la IA caída no se toca el ticket (no se inventa nada)")
ok(estado.get("674", {}).get("ultimo_tec_fu") is None,
   "y el comentario NO se marca como visto: se reintenta después",
   str(estado.get(674)))

# b) vuelve la IA, MISMO estado en memoria: ahora sí lo resuelve
vivo = _TriageFalso(ia_viva=True)
list(CI.gestionar_ciclo(_ClienteFalso(), vivo, 12, estado))
ok(vivo.resueltos == [674],
   "cuando la IA vuelve, el mismo comentario se procesa y el ticket pasa a Resuelto",
   str(vivo.resueltos))
ok(estado.get("674", {}).get("ultimo_tec_fu") == 900,
   "y recién ahí se da por visto")

# c) con la IA viva, un comentario ya procesado no se re-procesa
vivo2 = _TriageFalso(ia_viva=True)
list(CI.gestionar_ciclo(_ClienteFalso(), vivo2, 12, estado))
ok(not vivo2.resueltos, "y no se vuelve a marcar resuelto en cada vuelta del ciclo")

print("\n=== 3 · Si el técnico contesta DESPUÉS del cliente, el ticket sale igual de la espera ===")
# Caso real #651: el cliente contestó "sí, pueden correrlo", el técnico le respondió siete minutos
# después, y el ticket se quedó EN ESPERA dieciséis días. La referencia de "¿contestó el cliente?"
# era el último comentario de un TÉCNICO, así que la respuesta del técnico tapaba la del cliente.
# Y en espera el SLA no corre: no chilla nada, no se entera nadie.
PEDIDO = {"id": 500, "users_id": 28, "is_private": 0,
          "content": "Para avanzar necesitamos su confirmación. " + CI._MARCA_ESPERA_CLIENTE,
          "date_creation": "2026-07-26 21:41:00"}
CLIENTE = {"id": 501, "users_id": 26, "is_private": 0,
           "content": "Hola si pueden correrlo para su correcto funcionamiento",
           "date_creation": "2026-08-03 15:18:00"}
TECNICO = {"id": 502, "users_id": 8, "is_private": 0,
           "content": "Dale perfecto, vamos a proceder a encargar el selenoide para repararlo",
           "date_creation": "2026-08-03 15:25:00"}
TECS = {28, 7, 8}

ok(CI._respondio_a([PEDIDO, CLIENTE], lambda f: CI._es_pedido_al_cliente(f, TECS), TECS) is not None,
   "el cliente contestó el pedido -> se detecta")
ok(CI._respondio_a([PEDIDO, CLIENTE, TECNICO],
                   lambda f: CI._es_pedido_al_cliente(f, TECS), TECS) == CLIENTE,
   "y se SIGUE detectando aunque el técnico haya contestado después (el #651)")
ok(CI._respondio_a([PEDIDO], lambda f: CI._es_pedido_al_cliente(f, TECS), TECS) is None,
   "si el cliente todavía no contestó, no se inventa una respuesta")
ok(CI._respondio_a([PEDIDO, TECNICO],
                   lambda f: CI._es_pedido_al_cliente(f, TECS), TECS) is None,
   "un comentario del TÉCNICO no cuenta como respuesta del cliente")
# La misma referencia vale para la confirmación de un ticket ya resuelto.
CONF = {"id": 600, "users_id": 28, "is_private": 0,
        "content": "Le informamos que su solicitud fue resuelta. " + CI._MARCA_CONFIRMACION,
        "date_creation": "2026-08-19 14:30:00"}
DICE_OK = {"id": 601, "users_id": 26, "is_private": 0, "content": "Sí, ya puede fichar. Gracias!",
           "date_creation": "2026-08-19 15:00:00"}
POSTERIOR = {"id": 602, "users_id": 7, "is_private": 0, "content": "Buenísimo, lo cerramos.",
             "date_creation": "2026-08-19 15:02:00"}
ok(CI._respondio_a([CONF, DICE_OK, POSTERIOR], CI._es_aviso_confirmacion, TECS) == DICE_OK,
   "en un ticket RESUELTO pasa lo mismo: la confirmación del cliente no la tapa el técnico")

print("\n=== 4 · Un 'quedó solucionado' SIEMPRE se detecta ===")
# Caso real (#673): el técnico escribió un comentario largo que ARRANCA con "El inconveniente
# quedó solucionado" y sigue con todo el diagnóstico, terminando en algo que todavía falla. Dos
# cosas lo tapaban:
#   · GLPI guarda el comentario con las etiquetas ESCAPADAS ('&#60;p&#62;'), así que sacar '<...>'
#     no sacaba nada: a la IA le llegaban 24.000 caracteres de CSS del editor, sin ver el texto.
#   · aun leyéndolo limpio, el modelo pesaba el final y lo llamaba "avance".
COMENTARIO_REAL = (
    "&#60;p style=\"box-sizing: border-box; color: #8892a8; font-size: 14px;\"&#62;"
    "El inconveniente quedó solucionado. Empezamos revisando sus fichadas en tiempo real desde la "
    "base de datos; ejecutamos la consulta HikINOut query.sql. Detectamos que la terminal de la "
    "misma sede está desconectada, impidiendo sincronizar la información.&#60;/p&#62;")
limpio = CI._texto_plano(COMENTARIO_REAL)
ok("El inconveniente quedó solucionado" in limpio,
   "el comentario se desescapa antes de limpiarlo: la IA ve el TEXTO, no el CSS")
ok("box-sizing" not in limpio and "font-size" not in limpio,
   "y no le queda nada del estilo del editor", limpio[:60])

ok(cerebro.dice_resuelto(limpio),
   "un 'quedó solucionado' se detecta aunque el comentario siga con el detalle técnico")
for texto in ("Listo, ya está solucionado.", "Se solucionó el problema con el lector.",
              "Lo solucionamos cambiando el cable.", "El problema resuelto, ya puede fichar.",
              "Ya quedó operativo el molinete.", "Se resolvió, era el PIN mal cargado."):
    ok(cerebro.dice_resuelto(texto), f"detecta: {texto}")
for texto in ("No quedó solucionado, sigue igual.", "Todavía no se resolvió, falta el repuesto.",
              "Cuando quede solucionado les avisamos.", "Sin solucionar por ahora.",
              "Se deberá coordinar la reubicación del molinete.",
              "Le pedimos el legajo del agente para poder avanzar."):
    ok(not cerebro.dice_resuelto(texto), f"NO se confunde con: {texto}")


import triage as TR                     # noqa: E402


class _SinIA(_TriageFalso):
    """Sin IA disponible: lo que el técnico AFIRMA tiene que alcanzar igual."""

    def __init__(self):
        super().__init__(ia_viva=True)

    tecnico_resolvio = TR.Triage.tecnico_resolvio
    ia = property(lambda self: (_ for _ in ()).throw(RuntimeError("IA caída")))


ok(_SinIA().tecnico_resolvio(limpio) is True,
   "lo que el técnico afirma se detecta aunque la IA no esté")
ok(_SinIA().tecnico_resolvio("Seguimos revisando los logs, sin novedades.") is None,
   "y sin afirmación explícita ni IA, no se inventa nada")

print("\n=== 5 · Si queda algo EN MANOS DEL CLIENTE, es ESPERA aunque diga 'solucionado' ===")
# Correción de Brian: "se solucionó el acceso, pero necesitamos que ELLOS escalen lo de la terminal
# para que quede 100%". Eso NO es un cierre: es un seguimiento. Queda En espera, el cliente
# responde, vuelve a En curso, y así hasta que de verdad no falte nada. Por eso el ciclo pregunta
# PRIMERO si queda algo del cliente y sólo después si está resuelto.
CICLO_SRC = open(os.path.join(APP, "central", "ciclo.py"), encoding="utf-8").read()
orden = CICLO_SRC.index("pide = triage.tecnico_pide_confirmacion(cont)")
luego = CICLO_SRC.index("resolvio = None if pide else triage.tecnico_resolvio(cont)")
ok(orden < luego, "se pregunta primero por el cliente y recién después por la resolución")
ok("resolvio = None if pide else" in CICLO_SRC,
   "y si queda algo del cliente, ni se evalúa cerrarlo")


class _ConPendiente(_TriageFalso):
    """El comentario dice 'solucionado' PERO deja algo para el cliente."""

    def __init__(self):
        super().__init__(ia_viva=True)
        self.en_espera = []

    def tecnico_pide_confirmacion(self, texto):
        return True                    # queda algo del lado del cliente

    def poner_en_espera_pedido(self, tid, comentario):
        self.en_espera.append(tid)
        return True


PEND = [{"id": 910, "users_id": 7, "is_private": 0,
         "content": "El acceso quedó solucionado. Para cerrarlo necesitamos que escalen con "
                    "Sistemas la revisión de la terminal, que está desconectada.",
         "date_creation": "2026-08-19 14:49:00"}]


class _ClientePend(_ClienteFalso):
    def request(self, path, *a, **k):
        if path.endswith("/ITILFollowup"):
            return PEND
        return super().request(path, *a, **k)


pend = _ConPendiente()
list(CI.gestionar_ciclo(_ClientePend(), pend, 12, {}))
ok(pend.en_espera == [674] and not pend.resueltos,
   "queda EN ESPERA del cliente y NO se marca resuelto, aunque diga 'quedó solucionado'",
   f"espera={pend.en_espera} resueltos={pend.resueltos}")

print("\n=== 6 · El mensaje le dice al cliente QUÉ TIENE QUE HACER ===")
# No alcanza con informarle y quedarse esperando: si la terminal es de él y está desconectada, hay
# que pedirle que lo escale a SU área de sistemas y que verifiquen energía y conexión de red.
TRI_SRC = open(os.path.join(APP, "central", "triage.py"), encoding="utf-8").read()
prompt = TRI_SRC[TRI_SRC.index("def _mensaje_pedir_confirmacion"):]
prompt = prompt[:prompt.index("return (")]
for exige, que in (
        ("QUÉ NECESITAMOS DE ÉL", "pide algo concreto, no sólo avisa"),
        ("ESCALE al área de sistemas", "si el equipo es del cliente, que lo escale a SU área"),
        ("ENERGIZADO", "que verifiquen que esté energizado"),
        ("CONEXIÓN DE RED", "y que tenga conexión de red"),
        ("no se puede dar por cerrado", "y por qué el caso todavía no se cierra"),
        ("no uses tecnicismos internos", "sin nombres de consultas ni jerga interna")):
    ok(exige.lower() in prompt.lower(), que)

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)} chequeo(s):")
    for f in FALLAS:
        print("  ·", f)
    sys.exit(1)
print("TODO OK · la prioridad es la del alcance y ningún ticket queda trabado por una IA caída")
