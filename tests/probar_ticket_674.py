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

    def a_confirmacion_del_cliente(self, tid, solucion):
        """El pasaje completo: resuelto -> en espera de que el cliente confirme."""
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
        if "/ITILFollowup" in path:
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
        if "/ITILFollowup" in path:
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

ESTADO_SOL_ = {"aceptada": 1, "pendiente": 2, "rechazada": 3}


class _ClienteSol_:
    """Mesa de ayuda de mentira con una solución en cierto estado."""

    session = "s"

    def __init__(self, estado_sol, status=4):
        self.estado_sol, self.status = estado_sol, status

    def request(self, path, *a, **k):
        if "/ITILSolution" in path:
            return [{"id": 7, "users_id": 28, "status": ESTADO_SOL_[self.estado_sol],
                     "content": "Se recalibró el lector."}]
        if "/ITILFollowup" in path:
            return [{"id": 800, "users_id": 28, "is_private": 0,
                     "content": "Confírmenos si ya puede fichar. " + CI._MARCA_CONFIRMACION
                                + " " + CI._MARCA_ESPERA_CLIENTE,
                     "date_creation": "2026-08-26 11:36:00"},
                    {"id": 801, "users_id": 27, "is_private": 0,
                     "content": "Sí, ya puede fichar. Gracias!",
                     "date_creation": "2026-08-26 12:00:00"}]
        return []

    def tickets_recientes(self, n=30):
        return [{"id": 678, "status": self.status, "entities_id": 12, "name": "No puede fichar"}]

    def abrir(self):
        pass

    def cerrar(self):
        pass


class _SinSolucion(_ClienteSol_):
    def __init__(self):
        super().__init__("pendiente")

    def request(self, path, *a, **k):
        if "/ITILSolution" in path:
            return []
        return super().request(path, *a, **k)


print("\n=== 7 · Resuelto por el técnico -> EN ESPERA de que el cliente confirme ===")
# Pedido de Brian: si le estamos pidiendo la confirmación, el estado tiene que decir eso. El pasaje
# lo hace ITHOS entero: carga la solución con el texto del técnico (no se replica con el usuario de
# él, que lo dejaría duplicado), pide la confirmación y deja el ticket EN ESPERA con la solución
# PENDIENTE. Ese último paso importa: al pasar a En espera la mesa de ayuda saca la solución de
# pendiente y el cliente se queda sin los botones, así que hay que volver a dejarla pendiente.
TRI_SRC2 = open(os.path.join(APP, "central", "triage.py"), encoding="utf-8").read()
paso = TRI_SRC2[TRI_SRC2.index("def a_confirmacion_del_cliente"):]
paso = paso[:paso.index("def marcar_resuelto")]
# Queda en RESUELTO, no en espera: es el único estado en el que la mesa de ayuda le dibuja al
# cliente los botones de APROBAR / RECHAZAR (comprobado con el perfil real del cliente). En espera
# describiría mejor la situación pero lo deja sin botones, y esos botones son el modo natural de
# cerrar. No se pierde el SLA: al resolver queda la fecha de solución y el reloj para.
ok('"status": 5' in paso, "el ticket queda RESUELTO (es donde el cliente ve los botones)")
ok('"status": 2' in paso, "y la solución queda PENDIENTE de su aprobación")
ok("!= 5" in paso and "!= 2" in paso,
   "y se COMPRUEBA que haya quedado así, no se da por hecho")
ok("self.pedir_confirmacion(tid)" in paso, "y se le pide al cliente que confirme")
ok("triage.a_confirmacion_del_cliente(t[\"id\"], cont)" in CICLO_SRC,
   "el ciclo hace todo el pasaje de una")
ok("marcar_resuelto(t[\"id\"], cont, int(ult" not in CICLO_SRC,
   "y NO se replica la solución con el usuario del técnico (quedaba duplicada)")

print("\n=== 7.b · El cliente tiene QUÉ aprobar o rechazar ===")
# En GLPI el solicitante aprueba o rechaza LA SOLUCIÓN. Un ticket que pasa a Resuelto SIN cargar
# ninguna lo deja sin nada que tocar: ve el ticket resuelto y no tiene cómo confirmar el cierre ni
# decir que sigue igual. Pasó en producción con los tres tickets resueltos (#674, #677, #678).
resuelto = _TriageFalso(ia_viva=True)
resuelto.pasajes = []


def _pasaje(tid, solucion):
    resuelto.pasajes.append((tid, solucion))
    return True


resuelto.a_confirmacion_del_cliente = _pasaje
list(CI.gestionar_ciclo(_ClienteFalso(), resuelto, 12, {}))
ok(len(resuelto.pasajes) == 1, "se hace el pasaje una sola vez")
tid_m, sol_m = resuelto.pasajes[0]
ok(bool(sol_m), "se carga la SOLUCIÓN (sin ella el cliente no puede aprobar ni rechazar)")
ok("quedó solucionado" in sol_m.lower(),
   "y la solución son LAS PALABRAS DEL TÉCNICO, no una que redacte ITHOS", sol_m[:60])

print("\n=== 7.b.2 · Lo que hace el EQUIPO no deja el ticket esperando al cliente ===")
# Caso real (#651): el técnico escribió "vamos a proceder a encargar el selenoide" —lo encarga el
# EQUIPO— e ITHOS le escribió al cliente "necesitamos que gestione la compra". Salió al cliente.
# La pregunta no es si falta algo, es QUIÉN lo hace; y CUÁNDO: lo que se coordinará "cuando llegue
# la pieza" todavía no le pide nada a nadie.
prompt_pide = TRI_SRC2[TRI_SRC2.index("def tecnico_pide_confirmacion"):]
prompt_pide = prompt_pide[:prompt_pide.index("except Exception")]
ok("MIRÁ QUIÉN HACE LA ACCIÓN" in prompt_pide,
   "se decide por quién hace la acción, no por si la tarea está pendiente")
ok("vamos a encargar el repuesto" in prompt_pide,
   "lo que encarga o gestiona el equipo es trabajo NUESTRO (el ticket sigue en curso)")
ok("Y MIRÁ CUÁNDO" in prompt_pide and "cuando llegue la pieza" in prompt_pide,
   "y lo que se coordinará más adelante todavía no le pide nada al cliente")

print("\n=== 7.c · En espera puede estar esperando DOS cosas distintas ===")
# Un dato que le pedimos -> cuando contesta vuelve a En curso. La confirmación de que quedó
# resuelto -> lo que contesta CIERRA el ticket o lo REABRE. Se distinguen por si hay una solución
# pendiente de su aprobación.
ok(CI._espera_confirmacion(CI._soluciones(_ClienteSol_("pendiente"), 678, {})) is True,
   "con una solución pendiente, lo que se espera es la CONFIRMACIÓN")
ok(CI._espera_confirmacion(CI._soluciones(_ClienteSol_("aceptada"), 678, {})) is False,
   "ya aprobada, no se espera confirmación")
ok(CI._espera_confirmacion(CI._soluciones(_SinSolucion(), 678, {})) is False,
   "y sin solución cargada, lo que se espera es un DATO (vuelve a En curso)")

print("\n=== 8 · El SLA no corre cuando la pelota no es nuestra ===")
TK_SRC = open(os.path.join(APP, "comun", "tickets.py"), encoding="utf-8").read()
riesgo = TK_SRC[TK_SRC.index("def en_riesgo_sla"):]
riesgo = riesgo[:riesgo.index("def _asignados_de")]
ok('int(t.get("status", 0)) not in (1, 2)' in riesgo,
   "sólo se alerta por Nuevo y En curso: En espera y Resuelto quedan afuera")
ok("EN ESPERA (4)" in riesgo and "PAUSADO" in riesgo,
   "y queda explicado por qué (el SLA está pausado, la pelota es del cliente)")
ok("RESUELTO (5)" in riesgo,
   "un ticket resuelto esperando confirmación tampoco genera alerta de SLA")

print("\n=== 9 · Planka: el seguimiento cada 3 horas, no cada una ===")
PL_SRC = open(os.path.join(APP, "central", "planka_integrador.py"), encoding="utf-8").read()
ok('self.cfg.get("seguimiento_cada_horas", 3)' in PL_SRC,
   "el '¿cómo venís?' sale cada 3 horas por defecto (configurable)")
ok("(ahora.hour - desde) % cada == 0" in PL_SRC,
   "y respeta la franja horaria, contando desde la hora de inicio")
ok("no por acá" in PL_SRC,
   "lo instantáneo (tarjeta nueva, asignación, movimiento) sigue avisándose en el momento")

print("\n=== 10 · El cliente contesta con los BOTONES, no sólo escribiendo ===")
# En GLPI el solicitante aprueba o rechaza LA SOLUCIÓN apretando un botón. Si sólo miráramos los
# comentarios, un cliente que aprieta "Rechazar" y no escribe nada quedaría esperando para siempre:
# la solución figura rechazada y el ticket seguiría en Resuelto sin que el equipo se entere.
ESTADO_SOL = {"aceptada": 1, "pendiente": 2, "rechazada": 3}


class _ClienteSol:
    """Mesa de ayuda de mentira con un ticket RESUELTO y una solución en cierto estado."""

    session = "s"

    def __init__(self, estado_sol):
        self.estado_sol = estado_sol

    def request(self, path, *a, **k):
        if "/ITILSolution" in path:
            return [{"id": 7, "users_id": 7, "status": ESTADO_SOL[self.estado_sol],
                     "content": "Se recalibró el lector."}]
        if "/ITILFollowup" in path:
            return [{"id": 800, "users_id": 28, "is_private": 0,
                     "content": "Le informamos que su solicitud fue resuelta. "
                                + CI._MARCA_CONFIRMACION,
                     "date_creation": "2026-08-26 11:36:00"}]
        return []

    def tickets_recientes(self, n=30):
        return [{"id": 678, "status": 5, "entities_id": 12, "name": "No puede fichar"}]

    def abrir(self):
        pass

    def cerrar(self):
        pass


class _TriageBotones(_TriageFalso):
    def __init__(self):
        super().__init__(ia_viva=True)
        self.cerrados, self.reabiertos = [], []

    def cerrar(self, tid):
        self.cerrados.append(tid)
        return True

    def reabrir(self, tid):
        self.reabiertos.append(tid)
        return True

    def pedir_confirmacion(self, tid):
        return True

    def explica_procedimiento(self, texto):
        return True

    def cliente_confirma(self, texto):
        return None            # por comentario no dice nada: tiene que decidir el BOTÓN

    def recordar_confirmacion(self, tid):
        return True            # si todavía no contestó, se le recuerda (no se toca el ticket)


ok(CI._solucion_resuelta(CI._soluciones(_ClienteSol("pendiente"), 678, {})) is None,
   "mientras el cliente no toca nada, la solución sigue pendiente y no se hace nada")
ok(CI._solucion_resuelta(CI._soluciones(_ClienteSol("aceptada"), 678, {})) == "aceptada", "se lee la aprobación")
ok(CI._solucion_resuelta(CI._soluciones(_ClienteSol("rechazada"), 678, {})) == "rechazada", "y el rechazo")

aprob = _TriageBotones()
list(CI.gestionar_ciclo(_ClienteSol("aceptada"), aprob, 12, {}))
ok(aprob.cerrados == [678] and not aprob.reabiertos,
   "si aprueba con el botón, el ticket se CIERRA", str(aprob.cerrados))

rech = _TriageBotones()
list(CI.gestionar_ciclo(_ClienteSol("rechazada"), rech, 12, {}))
ok(rech.reabiertos == [678] and not rech.cerrados,
   "si rechaza con el botón, vuelve a EN CURSO (no queda esperando para siempre)",
   str(rech.reabiertos))

quieto = _TriageBotones()
list(CI.gestionar_ciclo(_ClienteSol("pendiente"), quieto, 12, {}))
ok(not quieto.cerrados and not quieto.reabiertos,
   "y si todavía no contestó, el ticket no se toca")

print("")
print("=== 11 . La confirmacion vale aunque la mesa de ayuda reabra el ticket ===")
# Caso real (#674, #677, #678): al responder el cliente, GLPI pasa el ticket de En espera a EN
# CURSO solo. Como la logica de confirmacion vivia dentro del "si esta en espera", su "listo,
# quedo solucionado" llegaba con el ticket ya reabierto y se leia como un comentario mas: tres
# tickets con el cliente confirmando y ninguno se cerro. Ahora lo que manda es que haya una
# SOLUCION esperando aprobacion, no el estado.


class _Confirma(_TriageBotones):
    def cliente_confirma(self, texto):
        return True

    def avisar_tecnico_sin_atender(self, tid, desde, horas):
        return True

    def poner_en_curso(self, tid):
        return True


class _SigueIgual(_Confirma):
    def cliente_confirma(self, texto):
        return False


for _est, _nombre in ((2, "En curso"), (4, "En espera"), (5, "Resuelto")):
    _t = _Confirma()
    list(CI.gestionar_ciclo(_ClienteSol_("pendiente", status=_est), _t, 12, {}))
    ok(_t.cerrados == [678],
       f"el cliente confirma con el ticket en {_nombre} -> se CIERRA", str(_t.cerrados))

for _est, _nombre in ((2, "En curso"), (4, "En espera")):
    _t = _SigueIgual()
    list(CI.gestionar_ciclo(_ClienteSol_("pendiente", status=_est), _t, 12, {}))
    ok(_t.reabiertos == [678] and not _t.cerrados,
       f"y si dice que sigue, con el ticket en {_nombre} -> vuelve a EN CURSO",
       str(_t.reabiertos))

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)} chequeo(s):")
    for f in FALLAS:
        print("  ·", f)
    sys.exit(1)
print("TODO OK · la prioridad es la del alcance y ningún ticket queda trabado por una IA caída")
