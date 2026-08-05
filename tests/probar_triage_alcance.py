#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test del ALCANCE del problema en el triage, sin red: la mesa de ayuda y la IA son de mentira.

Regresión de un caso real (#661, "EL FICHAJE DE ZARATE DEJO DE FUNCIONAR"): el biométrico de una
sede quedó apagado —nadie podía fichar ahí— y ITHOS lo trató como el caso de un usuario suelto:
prioridad Baja, asignado a soporte y el ticket EN ESPERA pidiendo "el nombre y el legajo de la
persona afectada", que no existía. Encima se despidió dos veces en el mismo mensaje.

Lo que se verifica:

  1. Las reglas distinguen QUÉ falla: el fichaje de una persona, o el servicio de una sede entera.
  2. Aunque el modelo se equivoque, la corrección es determinística: un ticket de alcance
     equipo/sede/masivo NUNCA queda esperando un legajo, no baja del piso de prioridad de su
     alcance y lo toma instalaciones.
  3. El caso individual sigue funcionando igual que siempre (no se rompió lo que andaba).
  4. La primera respuesta se despide UNA sola vez.
  5. El triage completo, de punta a punta, aplica todo eso sobre el ticket.

Uso:  python tests/probar_triage_alcance.py
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
import triage as TR                   # noqa: E402
from comun import glpi as G           # noqa: E402
from comun import ia as IA            # noqa: E402
from comun import tickets as TK       # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


TICKET_661 = {
    "id": 661,
    "name": "EL FICHAJE DE ZARATE DEJO DE FUNCIONAR",
    "status": 1,
    "users_id_recipient": 26,
    "content": ("Buenas tardes, nos avisan de Zarate que el fichaje biométrico ha dejado de "
                "funcionar, copio el mail recibido a continuación: Estimados buenas tardes, "
                "informo que el sistema biométrico dejó de funcionar. Ahora se encuentra "
                "apagado. Aguardo indicaciones."),
}

print("\n=== 1 · Las reglas explican QUÉ falla, no sólo a quién ===")
R = cerebro.REGLAS_SRT
ok("alcance" in R.lower(), "el triage tiene que decidir el ALCANCE del problema")
for palabra in ("individual", "grupo", "equipo", "sede", "masivo"):
    ok(f'"{palabra}"' in R, f"contempla el alcance '{palabra}'")
ok("NO es un caso individual" in R,
   "deja escrito que un equipo caído no es el problema de una sola persona")
ok("necesita_info=false SIEMPRE" in R,
   "y que en ese caso no se pide legajo ni se frena el ticket")

print("\n=== 2 · La corrección NO depende de que el modelo se acuerde ===")
# Exactamente lo que devolvió el modelo en el ticket real: alcance de sede, tratado como individual.
malo = {"alcance": "sede", "categoria": "TERMINALES", "prioridad": "Baja",
        "responsable": "bsierra", "necesita_info": True,
        "primera_respuesta": "¿Podrías indicarme el legajo de la persona afectada?"}
fijo, corr = cerebro.coherente(dict(malo))
ok(fijo["necesita_info"] is False,
   "una sede sin fichaje NO queda esperando el legajo de nadie")
ok(fijo["prioridad"] == "Urgente", "la prioridad sube al piso de su alcance", fijo["prioridad"])
ok(fijo["responsable"] == "jayala", "lo toma instalaciones", fijo["responsable"])
ok(fijo["requiere_visita"] is True, "un equipo caído no se arregla por mail: hay que ir al lugar")
ok(cerebro.MARCA_COORDINAR in fijo["primera_respuesta"].lower(),
   "y lo que se le pide al cliente es COORDINAR LA VISITA", fijo["primera_respuesta"][:80])
ok(not cerebro._RE_PREGUNTA_OBVIA.search(fijo["primera_respuesta"]),
   "sin preguntarle cosas que ya sabemos: la instalación la hicimos nosotros")
ok(len(corr) >= 3 and any("legajo" in c for c in corr) and any("prioridad" in c for c in corr)
   and any("instalaciones" in c for c in corr),
   "y queda registrado por qué se corrigió", str(corr))

texto_661 = (TICKET_661["name"], TICKET_661["content"])
ok(cerebro.alcance_por_texto(*texto_661) == "sede",
   "el texto solo ya delata que la sede se quedó sin fichaje")
ok(cerebro.alcance_por_texto("Legajo 05808 Martínez", "El agente del legajo 5808 no puede fichar, "
                             "el lector no lo reconoce") is None,
   "un caso con legajo NO se escala: es de esa persona")
ok(cerebro.alcance_por_texto("Molinete", "El molinete de Morón está trabado") is None,
   "sin señal de que dejó de dar servicio, no se toca el alcance")
ok(cerebro.alcance_por_texto("Fichaje", "nadie puede fichar en la sede desde ayer") == "sede",
   "'nadie puede fichar' es una sede caída")
# El modelo dijo 'individual' sobre el ticket real: el texto tiene que ganar.
enganio, corr_e = cerebro.coherente(
    {"alcance": "individual", "categoria": "TERMINALES", "prioridad": "Baja",
     "responsable": "bsierra", "necesita_info": True,
     "primera_respuesta": "¿Me pasás el nombre y el legajo de la persona afectada?",
     "nota_tecnico": "Se solicita legajo."}, *texto_661)
ok(enganio["alcance"] == "sede",
   "si el modelo lee mal el ticket, el TEXTO lo corrige", enganio["alcance"])
ok("legajo" not in (enganio["primera_respuesta"] or "").lower(),
   "y la respuesta que iba a salir pidiendo el legajo se reemplaza")
ok(cerebro.MARCA_COORDINAR in (enganio["primera_respuesta"] or "").lower(),
   "por el pedido de coordinar la visita")
# Aunque el modelo acierte el alcance, si su respuesta pregunta lo que ya sabemos, se reemplaza.
obvia, corr_o = cerebro.coherente(
    {"alcance": "sede", "categoria": "TERMINALES", "prioridad": "Urgente",
     "responsable": "jayala", "necesita_info": False, "requiere_visita": True,
     "primera_respuesta": "¿El equipo tiene energía y conexión de red? ¿Hay otro lector?"},
    *texto_661)
ok(cerebro.MARCA_COORDINAR in obvia["primera_respuesta"].lower()
   and any("ya tenemos" in c for c in corr_o),
   "preguntar por la energía o la red de un equipo que instalamos nosotros no sale al cliente",
   str(corr_o))
ok(not enganio["nota_tecnico"],
   "la nota al técnico basada en ese error también se descarta")

equipo, _ = cerebro.coherente({"alcance": "equipo", "categoria": "MOLINETES",
                               "prioridad": "Baja", "responsable": "bsierra",
                               "necesita_info": True})
ok(equipo["prioridad"] == "Alta" and equipo["responsable"] == "jayala"
   and equipo["necesita_info"] is False, "un molinete caído: Alta, instalaciones y sin espera")

masivo, _ = cerebro.coherente({"alcance": "masivo", "categoria": "HIK-CENTRAL",
                               "prioridad": "Media", "responsable": "bsierra",
                               "necesita_info": False})
ok(masivo["prioridad"] == "Urgente", "una falla masiva es Urgente")
ok(masivo["responsable"] == "bsierra",
   "pero si el problema es del software, lo sigue tomando soporte")

print("\n=== 3 · El caso de una persona no cambió ===")
indiv, corr_i = cerebro.coherente({"alcance": "individual", "categoria": "TERMINALES",
                                   "prioridad": "Baja", "responsable": "bsierra",
                                   "necesita_info": True})
ok(indiv["necesita_info"] is True, "si falta el legajo de UNA persona, se sigue pidiendo")
ok(indiv["prioridad"] == "Baja" and indiv["responsable"] == "bsierra" and not corr_i,
   "y no se toca nada más")
subido, _ = cerebro.coherente({"alcance": "individual", "categoria": "TERMINALES",
                               "prioridad": "Media", "responsable": "bsierra",
                               "necesita_info": True})
ok(subido["prioridad"] == "Media", "un caso individual reincidente puede ser Media (es un piso)")
sin_dato, _ = cerebro.coherente({"categoria": "TERMINALES", "prioridad": "Baja",
                                 "responsable": "bsierra", "necesita_info": True})
ok(sin_dato["alcance"] == "individual", "sin alcance declarado se asume el caso más conservador")

print("\n=== 3.1 · El legajo que YA está en el ticket no se pide ===")
# Caso real (#662): el asunto es «00084 Zuker Sebastián» — el legajo está ahí aunque no diga la
# palabra "legajo". ITHOS lo pidió igual y dejó el ticket EN ESPERA por un dato que ya tenía.
ok(cerebro.legajo_en_texto("00084 Zuker Sebastián", "no puede fichar hace días") == "00084",
   "el asunto «00084 Zuker Sebastián» ya trae el legajo")
ok(cerebro.legajo_en_texto("Legajo 01347 Rojas, Natalia", "") == "01347",
   "y el que lo dice con todas las letras, también")
ok(cerebro.legajo_en_texto("Fichadas sin figurar", "tenemos problemas con el proceso") is None,
   "un ticket sin legajo sigue sin tenerlo (no se inventa)")
ok(cerebro.legajo_en_texto("EL FICHAJE DE ZARATE DEJO DE FUNCIONAR", "está apagado") is None,
   "y un equipo caído tampoco tiene legajo")

con_legajo, corr_l = cerebro.coherente(
    {"alcance": "individual", "categoria": "TERMINALES", "prioridad": "Baja",
     "responsable": "bsierra", "necesita_info": True,
     "primera_respuesta": "¿Podrías proporcionarme su número de legajo? Gracias, Soporte ITH",
     "nota_tecnico": "Se solicita el legajo del afectado."},
    "00084 Zuker Sebastián", "la persona detallada en el título no puede fichar hace días")
ok(con_legajo["necesita_info"] is False,
   "el ticket NO queda en espera: el dato ya estaba", str(corr_l))
ok("00084" in con_legajo["primera_respuesta"]
   and "legajo?" not in con_legajo["primera_respuesta"],
   "y la respuesta lo nombra en vez de pedirlo", con_legajo["primera_respuesta"][:80])
ok(not con_legajo["nota_tecnico"], "la nota que decía 'se solicita el legajo' se descarta")

sin_legajo, _ = cerebro.coherente(
    {"alcance": "individual", "categoria": "TERMINALES", "prioridad": "Baja",
     "responsable": "bsierra", "necesita_info": True,
     "primera_respuesta": "¿Me pasás el legajo?"}, "Sin acceso", "Juan no puede fichar")
ok(sin_legajo["necesita_info"] is True,
   "si de verdad falta el legajo, se sigue pidiendo como siempre")

print("\n=== 4 · La respuesta se despide UNA sola vez ===")
doble = ("Hola Facundo, para poder ayudarte, ¿podrías indicarme el legajo? "
         "Quedo a la espera de tu respuesta. Soporte ITH")
uno = TR._con_cierre_espera(doble)
ok(uno.lower().count("a la espera de") == 1, "no repite la despedida del modelo", uno[-70:])
ok(TR._MARCA_ESPERA_CLIENTE in uno.lower(),
   "y conserva el marcador que el ciclo necesita para recordar")
ok(TR._con_cierre_espera("Hola. Necesito el legajo.").lower().count("a la espera de") == 1,
   "si el modelo no se despide, el cierre se agrega igual")
firmado = TR._con_cierre_espera("Hola Facundo, necesito el dato. Gracias, Soporte ITH")
ok(firmado.lower().count("soporte ith") == 1,
   "y tampoco firma dos veces cuando el modelo ya firmó", firmado[-60:])

print("\n=== 5 · El triage completo, de punta a punta ===")


class IAFalsa:
    """Devuelve la MISMA clasificación equivocada del caso real."""

    def __init__(self, *a, **k):
        self.entrada = ""

    def chat(self, sistema, prompt, json_out=False, **k):
        self.entrada = prompt
        return ('{"alcance":"individual","categoria":"TERMINALES","prioridad":"Baja",'
                '"responsable":"bsierra","necesita_info":true,"resumen":"x",'
                '"primera_respuesta":"Hola Facundo, indicame el nombre y el legajo de la persona '
                'afectada. Quedo a la espera de tu respuesta. Soporte ITH",'
                '"nota_tecnico":"Se solicita legajo."}')


class GLPIFalso:
    """Anota lo que el triage escribiría en la mesa de ayuda."""

    def __init__(self, *a, **k):
        self.puts, self.followups, self.asignados = [], [], []

    def abrir(self):
        pass

    def cerrar(self):
        pass

    def request(self, path, metodo="GET", data=None, **k):
        cuerpo = (data or {}).get("input", {})
        if path.endswith("/Ticket_User") and metodo == "GET":
            return []
        if path == "/Ticket_User":
            self.asignados.append(cuerpo)
        elif path == "/ITILFollowup":
            self.followups.append(cuerpo)
        elif metodo == "PUT":
            self.puts.append(cuerpo)
        return {}


class AdaptadorFalso:
    def casos_similares(self, descripcion, tope=25, estados=(4, 5, 6), excluir=()):
        ok(661 not in {int(x) for x in excluir} or True, "")  # (se verifica abajo)
        AdaptadorFalso.excluidos = {int(x) for x in excluir}
        return [{"id": 459, "asunto": "Biométrico nuevos", "estado": "Cerrado",
                 "problema": "En 4 de las 5 comisiones los lectores no pasan las fichadas.",
                 "resolucion": "Se reconfiguraron los lectores en sitio.",
                 "resuelto_de_verdad": True, "cierre_administrativo": False, "relevancia": 0.6}]


falso = GLPIFalso()
G.GLPIClient = lambda *a, **k: falso
G.sesion = lambda *a, **k: falso
G.nombre_pila = lambda *a, **k: "Facundo"
IA.crear_texto = lambda *a, **k: IAFalsa()
TK.adaptador = lambda cfg: AdaptadorFalso()

t = TR.Triage({"glpi_url": "https://falsa", "glpi_ithos_token": "x", "entity_id": 12,
               "horario_atencion": {"dias": [0, 1, 2, 3, 4], "desde": "00:00", "hasta": "23:59"}},
              {"proveedor": "falso"})
res = t.procesar(dict(TICKET_661))

ok(res is not None, "el triage procesó el ticket")
ok(res and res.get("prioridad") == "Urgente",
   "el ticket entra como Urgente aunque el modelo dijo Baja", str(res and res.get("prioridad")))
ok(res and res.get("responsable_login") == "jayala",
   "y asignado a instalaciones (Alejandro Ayala)", str(res and res.get("responsable_login")))
ok(res and res.get("necesita_info") is False, "no queda esperando un dato del afectado")
ok(res and res.get("requiere_visita") is True, "queda marcado que hay que ir al lugar")
estados = [p.get("status") for p in falso.puts if "status" in p]
ok(estados and estados[-1] == 4,
   "el ticket queda EN ESPERA de que el cliente confirme cuándo podemos pasar", str(estados))
prio = [p for p in falso.puts if "priority" in p]
ok(prio and prio[0]["priority"] == 5 and prio[0]["urgency"] == 5 and prio[0]["impact"] == 5,
   "urgencia, impacto y prioridad quedan en Urgente (no en Baja)", str(prio[:1]))
ok(any(u.get("users_id") == 8 for u in falso.asignados),
   "Alejandro Ayala queda asignado al ticket", str(falso.asignados))

publicas = [f["content"] for f in falso.followups if not f.get("is_private")]
privadas = [f["content"] for f in falso.followups if f.get("is_private")]
ok(len(publicas) == 1, "se manda UNA sola respuesta al cliente")
ok(publicas and "legajo" not in publicas[0].lower() or not publicas,
   "la respuesta al cliente ya no pide un legajo que no existe", (publicas or [""])[0][:90])
ok(publicas and cerebro.MARCA_COORDINAR in publicas[0].lower(),
   "le pide coordinar la visita: qué día y en qué horario podemos pasar")
ok(publicas and not cerebro._RE_PREGUNTA_OBVIA.search(publicas[0]),
   "y no le pregunta lo que ya sabemos (ubicación, energía, red, otro lector)")
ok(publicas and TR._MARCA_ESPERA_CLIENTE in publicas[0].lower(),
   "con el marcador de espera, así se le recuerda una vez por día hábil")
ok(publicas and publicas[0].lower().count("a la espera de") <= 1,
   "y no se despide dos veces", (publicas or [""])[0][-70:])
ok(any("prioridad" in p.lower() and "nadie puede fichar" in p.lower() for p in privadas),
   "el técnico recibe por nota privada por qué el ticket entra así", str(privadas)[:160])
ok(any("hay que ir al lugar" in p.lower() for p in privadas),
   "y que el ticket espera la coordinación de la visita")
ok(not any("solicita legajo" in p.lower() for p in privadas),
   "y no le queda la nota vieja pidiendo un legajo", str(privadas)[:160])
ok(getattr(AdaptadorFalso, "excluidos", None) == {661},
   "los antecedentes no incluyen al propio ticket")
ok("ANTECEDENTES" in t.ia.entrada and "#459" in t.ia.entrada,
   "el triage clasifica viendo los casos reales ya trabajados")

print("\n" + "=" * 78)
if FALLAS:
    print(f"FALLARON {len(FALLAS)}: " + "; ".join(FALLAS))
    sys.exit(1)
print("TODO OK · un equipo caído nunca más se trata como el caso de un usuario suelto")
