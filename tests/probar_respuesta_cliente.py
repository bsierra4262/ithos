#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de QUÉ PASA CUANDO EL CLIENTE RESPONDE, sin red (la mesa de ayuda es de mentira).

Regresión de un caso real (#661): el cliente contestó un viernes a las 16:57, el ciclo dejó el
ticket EN CURSO y el SLA corrió sábado y domingo contra un equipo que no estaba trabajando; el
lunes el ticket ya nacía vencido. Además nadie se enteró de que había contestado, y el técnico
asignado tampoco supo que tenía una respuesta esperando.

Lo que se verifica:

  1. Responde FUERA de horario (noche, sábado o domingo): el ticket NO queda en curso — queda EN
     ESPERA y se agenda su reapertura sola para el próximo día hábil a la hora de apertura.
  2. Responde DENTRO de horario: sigue en curso, como siempre.
  3. CADA respuesta del cliente se avisa por los canales, con lo que dijo y cómo queda el ticket.
  4. Si pasan horas HÁBILES sin que le contestemos, el técnico asignado recibe el aviso de que le
     respondieron y no contestó — una sola vez por día y sin repetirlo tras un reinicio.
  5. Las horas se cuentan sólo dentro del horario de atención (el fin de semana no suma).

Uso:  python tests/probar_respuesta_cliente.py
"""

import os
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))

import triage as TR                    # noqa: E402
import ciclo as CI                     # noqa: E402  (el ciclo de vida vive acá)
from comun import horario as H         # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


CFG = {"zona_horaria": "America/Argentina/Buenos_Aires", "nombre_cliente": "TEST",
       "horario_atencion": {"dias": [0, 1, 2, 3, 4], "desde": "09:00", "hasta": "18:00"}}
ITHOS, TECNICO, CLIENTE = 28, 7, 26

print("\n=== 1 · Las horas se cuentan sólo dentro del horario de atención ===")
ok(H.horas_habiles_entre(CFG, datetime(2026, 7, 31, 17, 30),
                         datetime(2026, 8, 3, 9, 30)) == 1.0,
   "viernes 17:30 → lunes 09:30 = 1 hora hábil (el fin de semana no cuenta)")
ok(H.horas_habiles_entre(CFG, datetime(2026, 8, 1, 10, 0),
                         datetime(2026, 8, 2, 18, 0)) == 0.0,
   "todo un fin de semana = 0 horas hábiles")
ok(H.horas_habiles_entre(CFG, datetime(2026, 8, 3, 9, 0),
                         datetime(2026, 8, 3, 12, 0)) == 3.0,
   "un lunes de 09:00 a 12:00 = 3 horas hábiles")
lunes9 = H.proximo_inicio_horario(CFG, datetime(2026, 8, 1, 20, 0))     # sábado a la noche
ok(lunes9.weekday() == 0 and lunes9.hour == 9,
   "desde un sábado, el próximo horario de atención es el lunes a las 09:00",
   str(lunes9))


class TriageFalso:
    """Anota lo que el ciclo le manda hacer, sin tocar la mesa de ayuda."""

    def __init__(self):
        self.cfg_glpi = CFG
        self.en_curso, self.esperas, self.avisos_tecnico, self.notas = [], [], [], []

    def poner_en_curso(self, tid):
        self.en_curso.append(tid)
        return True

    def esperar_hasta_horario(self, tid, motivo=""):
        dt = H.proximo_inicio_horario(CFG, AHORA[0])
        self.esperas.append({"tid": tid, "hasta": dt, "motivo": motivo})
        return dt

    def avisar_tecnico_sin_atender(self, tid, desde, horas):
        self.avisos_tecnico.append({"tid": tid, "horas": horas})
        return True

    def nota_interna(self, tid, texto):
        self.notas.append(texto)
        return True

    # el resto del ciclo no se toca en este test
    def __getattr__(self, _n):
        return lambda *a, **k: False


class GLPIFalso:
    def __init__(self, fu, tickets):
        self.fu, self.tickets = fu, tickets

    def tickets_recientes(self, n=40):
        return self.tickets

    def request(self, path, metodo="GET", data=None, **k):
        if "ITILFollowup" in path:
            return self.fu
        if "/User/" in path:
            return {"firstname": "Facundo", "realname": "Monaco"}
        return {}

    def abrir(self):
        pass

    def cerrar(self):
        pass


AHORA = [None]          # el "ahora" que ve el ciclo en cada escenario


def correr(status, fu, ahora):
    """Corre el ciclo sobre UN ticket y devuelve (triage_falso, anuncios)."""
    AHORA[0] = ahora
    # El reloj se parchea en `ciclo`, que es donde corre gestionar_ciclo.
    H_orig, L_orig = CI.en_horario_atencion, CI._ahora_local
    CI.en_horario_atencion = lambda cfg, a=None: H_orig(cfg, ahora)
    CI._ahora_local = lambda cfg, a=None: ahora.replace(tzinfo=None)
    tri = TriageFalso()
    ticket = {"id": 661, "status": status, "name": "Zárate", "entities_id": 12}
    try:
        anuncios = CI.gestionar_ciclo(GLPIFalso(fu, [ticket]), tri, 12, {})
    finally:
        CI.en_horario_atencion, CI._ahora_local = H_orig, L_orig
    return tri, anuncios


PEDIDO = {"id": 100, "users_id": ITHOS, "is_private": 0,
          "content": "Necesitamos coordinar la visita. Quedamos a la espera de su respuesta.",
          "date_creation": "2026-07-31 16:18:00"}
RESPUESTA = {"id": 101, "users_id": CLIENTE, "is_private": 0,
             "content": "El lunes lo coordinamos con los jefes, muchas gracias",
             "date_creation": "2026-07-31 16:57:00"}

print("\n=== 2 · El cliente responde un VIERNES a la tarde, ya fuera de horario ===")
tri, anuncios = correr(4, [PEDIDO, RESPUESTA], datetime(2026, 7, 31, 19, 30))
ok(not tri.en_curso, "el ticket NO se pasa a EN CURSO (el SLA no puede correr el fin de semana)")
ok(len(tri.esperas) == 1, "queda EN ESPERA")
ok(tri.esperas and tri.esperas[0]["hasta"].weekday() == 0
   and tri.esperas[0]["hasta"].hour == 9,
   "y se reabre solo el LUNES a las 09:00",
   str(tri.esperas[0]["hasta"]) if tri.esperas else "")
ok(anuncios and "fuera de horario" in anuncios[0]["wa"],
   "se avisa por el grupo que respondió fuera de horario")
ok(anuncios and "coordinamos con los jefes" in anuncios[0]["wa"],
   "y el aviso dice QUÉ contestó el cliente", (anuncios or [{}])[0].get("wa", "")[:120])

print("\n=== 3 · El mismo ticket, ya EN CURSO, un DOMINGO (el caso que se rompió) ===")
tri, anuncios = correr(2, [PEDIDO, RESPUESTA], datetime(2026, 8, 2, 12, 0))
ok(len(tri.esperas) == 1,
   "un ticket EN CURSO con el cliente respondido también se frena hasta el lunes")
ok(tri.esperas and tri.esperas[0]["hasta"].weekday() == 0,
   "reapertura el lunes", str(tri.esperas[0]["hasta"]) if tri.esperas else "")
ok(not tri.avisos_tecnico,
   "y NO se le reclama nada al técnico un domingo (no está trabajando)")

print("\n=== 4 · Dentro de horario: sigue en curso y se avisa ===")
tri, anuncios = correr(4, [PEDIDO, RESPUESTA], datetime(2026, 8, 3, 9, 30))
ok(tri.en_curso == [661], "el ticket vuelve a EN CURSO")
ok(not tri.esperas, "no se frena")
ok(anuncios and "respondió" in anuncios[0]["wa"], "y se avisa por el grupo")

print("\n=== 5 · Le contestaron y el técnico no responde ===")
tri, anuncios = correr(2, [PEDIDO, RESPUESTA], datetime(2026, 8, 3, 11, 30))
ok(len(tri.avisos_tecnico) == 1,
   "pasadas las horas hábiles, el técnico recibe el aviso de que no contestó")
ok(tri.avisos_tecnico and tri.avisos_tecnico[0]["horas"] >= 2,
   "con cuántas horas HÁBILES lleva esperando",
   str(tri.avisos_tecnico[0]["horas"]) if tri.avisos_tecnico else "")
ok(any("sigue sin respuesta nuestra" in a["wa"] for a in anuncios),
   "y también se avisa por el grupo")

tri, anuncios = correr(2, [PEDIDO, RESPUESTA], datetime(2026, 8, 3, 9, 30))
ok(not tri.avisos_tecnico,
   "recién respondió: todavía no se le reclama nada al técnico")

# El aviso ya quedó asentado en el ticket: tras un reinicio no se repite.
YA_AVISADO = {"id": 102, "users_id": ITHOS, "is_private": 1,
              "content": "Nota interna: " + CI._MARCA_SIN_ATENDER + ". Respondió el 31/07.",
              "date_creation": "2026-08-03 11:00:00"}
tri, _ = correr(2, [PEDIDO, RESPUESTA, YA_AVISADO], datetime(2026, 8, 3, 15, 0))
ok(not tri.avisos_tecnico,
   "y no se repite tras un reinicio (el aviso ya está escrito en el ticket)")

print("\n=== 6 · Un TÉCNICO NUEVO no es el cliente ===")
# Regresión: entró gente nueva al equipo y el ciclo seguía reconociendo sólo a los técnicos que
# estaban escritos en el código. Una técnica resolvió el ticket a las 18:30 y el ciclo lo leyó como
# "el cliente respondió fuera de horario": lo dejó EN ESPERA hasta el otro día en vez de marcarlo
# resuelto y pedirle la confirmación al cliente.
LAURA = 30
CFG_EQUIPO = dict(CFG, tecnicos=[
    {"nombre": "Brian Sierra", "glpi_id": 7, "glpi_login": "bsierra"},
    {"nombre": "Laura Zaltron", "glpi_id": LAURA, "glpi_login": "lzaltron"},
    {"nombre": "Lisandro Campos", "glpi_id": 31, "glpi_login": "lcampos"}])
ok(LAURA in TR.ids_humanos(CFG_EQUIPO) and LAURA in TR.ids_tecnicos(CFG_EQUIPO),
   "el equipo sale de la config: la técnica nueva cuenta como soporte",
   str(sorted(TR.ids_humanos(CFG_EQUIPO))))
ok(LAURA not in TR.TECNICOS_HUMANOS,
   "y no estaba en el equipo fijo del código (por eso fallaba)")

RESOLUCION = {"id": 103, "users_id": LAURA, "is_private": 0,
              "content": "El inconveniente quedó solucionado. Revisamos sus fichadas en la base "
                         "de datos y desde el 24/7 no ficha.",
              "date_creation": "2026-08-05 18:30:00"}
tecs = TR.ids_tecnicos(CFG_EQUIPO)
base = max((int(f["id"]) for f in [PEDIDO, RESPUESTA, RESOLUCION]
            if int(f.get("users_id") or 0) in tecs), default=0)
nuevos = [f for f in [PEDIDO, RESPUESTA, RESOLUCION]
          if int(f["id"]) > base and int(f.get("users_id") or 0) not in tecs]
ok(base == RESOLUCION["id"] and not nuevos,
   "lo que escribe la técnica NO se toma como una respuesta del cliente", str(nuevos))
sin_config = [f for f in [PEDIDO, RESPUESTA, RESOLUCION]
              if int(f["id"]) > max((int(x["id"]) for x in [PEDIDO, RESPUESTA, RESOLUCION]
                                     if int(x.get("users_id") or 0) in TR.TECNICOS), default=0)
              and int(f.get("users_id") or 0) not in TR.TECNICOS]
ok(any(f["id"] == RESOLUCION["id"] for f in sin_config),
   "con el equipo fijo del código sí se la tomaba por cliente (el bug)",
   str([f["id"] for f in sin_config]))
ok(CI._ultimo_id_cliente([PEDIDO, RESPUESTA, RESOLUCION], tecs) == RESPUESTA["id"],
   "la última vez que habló el CLIENTE sigue siendo su propio mensaje")

print("\n=== 7 · La resolución es la del técnico, no una que escriba ITHOS ===")
# Cuando el técnico resuelve por comentario, su explicación YA está en el ticket: copiarla como
# "solución" la deja repetida. Sólo se pasa a Resuelto y se le pide confirmación al cliente.
# Y si alguna vez SÍ se documenta una solución, queda a nombre de quien resolvió (no de admin).
CFG_TOKENS = dict(CFG_EQUIPO, glpi_lzaltron_token="tok-laura", glpi_bsierra_token="tok-brian")
usados = []


class SesionFalsa:
    def __init__(self, token):
        self.token = token

    def request(self, path, metodo="GET", data=None, **k):
        if path == "/ITILSolution" and metodo == "POST":
            usados.append((self.token, (data or {}).get("input", {}).get("content", "")))
        return {}

    def abrir(self):
        pass

    def cerrar(self):
        pass


G_orig = TR.G.sesion
TR.G.sesion = lambda cfg, token=None: SesionFalsa(token)
tri = TR.Triage.__new__(TR.Triage)
tri.cfg_glpi = CFG_TOKENS
tri.cli = SesionFalsa("tok-ithos")
try:
    tri.marcar_resuelto(662, "El inconveniente quedó solucionado. Revisamos las fichadas…",
                        autor=LAURA)
    ok(usados and usados[0][0] == "tok-laura",
       "la solución la carga LAURA con su propio usuario", str(usados[:1])[:70])
    ok(usados and "Revisamos las fichadas" in usados[0][1],
       "y el texto es el procedimiento que ella escribió, no una frase genérica")
    usados.clear()
    tri.marcar_resuelto(663, "listo", autor=8)      # Alejandro no tiene token configurado
    ok(usados and usados[0][0] == "tok-ithos",
       "si el técnico no tiene token, la carga ITHOS como siempre", str(usados[:1])[:60])
    usados.clear()
    tri.marcar_resuelto(664)                        # el caso del ciclo: sin texto
    ok(not usados,
       "sin texto NO se escribe ninguna solución: la del técnico ya está en el ticket")
finally:
    TR.G.sesion = G_orig

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("TODO OK · el SLA no corre el fin de semana y nadie se entera tarde de una respuesta")
