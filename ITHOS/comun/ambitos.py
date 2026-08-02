#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ÁMBITOS: qué se avisa y qué se contesta en CADA grupo.

Un solo grupo para todo se vuelve inservible: los avisos de tickets tapan las tareas del equipo,
las cosas del sistema le llegan a gente que no le sirven, y quien sólo quiere preguntar algo
termina leyendo alertas todo el día. Así que cada grupo tiene un ÁMBITO, y el ámbito define dos
cosas independientes:

  · qué AVISOS recibe (puede no recibir ninguno), y
  · sobre qué puede CONSULTAR la gente ahí.

Se configura por cliente, en el canal de WhatsApp:

    "grupos": [
      {"grupo": "ITHOS",         "ambito": "consultas"},
      {"grupo": "ITHOS_SOPORTE", "ambito": "soporte"},
      {"grupo": "ITHOS_TRELLO",  "ambito": "tareas"},
      {"grupo": "ITHOS_DEMO",    "ambito": "sistema"}
    ]

Un cliente que quiera todo junto no configura nada: con un `"grupo"` suelto se usa el ámbito
`todo` y se comporta como antes.
"""

# Tipos de aviso que produce el sistema. Cada aviso nace con el suyo y va SÓLO a donde corresponde.
TICKETS = "tickets"          # triage, ciclo de vida, respuestas del cliente, cambios de estado
SLA = "sla"                  # SLA en riesgo/vencido y reportes ITIL
PLANKA = "planka"            # tablero del equipo: resumen, seguimiento, movimientos
SISTEMA = "sistema"          # el Gestor o el agente arrancan/se reinician, cuotas de IA, cobranza
VOZ = "voz"                  # entrenamiento de la voz del dueño
AVISOS = (TICKETS, SLA, PLANKA, SISTEMA, VOZ)

# Temas que se pueden consultar. 'todo' = sin restricción (el asistente completo).
TODO = "todo"

AMBITOS = {
    "consultas": {
        "recibe": (),                       # NINGÚN aviso: es un grupo para preguntar, no para leer alertas
        "responde": TODO,                   # pero puede TODO lo que ITHOS sabe hacer
        "descripcion": "consultas de cualquier tema (no recibe alertas)",
    },
    "soporte": {
        "recibe": (TICKETS, SLA),
        "responde": TICKETS,                # sólo tickets: otra cosa se deriva
        "descripcion": "alertas y consultas de los tickets de soporte",
    },
    "tareas": {
        "recibe": (PLANKA,),
        "responde": PLANKA,                 # sólo el tablero del equipo
        "descripcion": "el tablero de tareas del equipo",
    },
    "sistema": {
        "recibe": (SISTEMA, VOZ),
        "responde": TODO,
        "descripcion": "avisos del sistema y entrenamiento de la voz",
    },
    "todo": {                               # compatibilidad: un solo grupo para todo
        "recibe": AVISOS,
        "responde": TODO,
        "descripcion": "todo junto",
    },
}

DEFECTO = "todo"


def normalizar(ambito):
    """El ámbito pedido, o el de compatibilidad si no se reconoce (nunca rompe por un typo)."""
    a = str(ambito or "").strip().lower()
    return a if a in AMBITOS else DEFECTO


def recibe(ambito, tipo):
    """¿Un grupo con este ámbito tiene que recibir un aviso de este tipo?"""
    return tipo in AMBITOS[normalizar(ambito)]["recibe"]


def responde(ambito):
    """Sobre qué tema puede consultar la gente en ese grupo ('todo' = sin restricción)."""
    return AMBITOS[normalizar(ambito)]["responde"]


def grupos_de(cfg):
    """Los grupos configurados del canal, normalizados a [{'grupo','ambito'}].

    Acepta la forma nueva (`grupos`) y la vieja (`grupo` suelto, un único grupo que recibe todo),
    así una configuración anterior sigue funcionando igual sin tocarla."""
    out = []
    for g in ((cfg or {}).get("grupos") or []):
        nombre = (g.get("grupo") or "").strip() if isinstance(g, dict) else str(g).strip()
        if nombre:
            out.append({"grupo": nombre,
                        "ambito": normalizar(g.get("ambito") if isinstance(g, dict) else None)})
    if not out and (cfg or {}).get("grupo"):
        out.append({"grupo": str(cfg["grupo"]).strip(), "ambito": DEFECTO})
    return out


def llamar(fn, *args, tipo=None):
    """Llama a un canal pasándole el TIPO de aviso SÓLO si lo entiende. Los canales que no separan
    por grupos (Telegram, email, un objeto de prueba) reciben el aviso igual que siempre: agregar
    la clasificación no puede romper a quien no la usa."""
    try:
        import inspect
        if tipo is not None and "tipo" in inspect.signature(fn).parameters:
            return fn(*args, tipo=tipo)
    except Exception:  # noqa: BLE001
        pass
    return fn(*args)


def donde_preguntar(tema, grupos):
    """Nombre del grupo donde SÍ se puede consultar ese tema, para poder derivar a la persona en
    lugar de dejarla sin respuesta. None si no hay ninguno configurado."""
    for g in (grupos or []):
        r = responde(g.get("ambito"))
        if r == tema or r == TODO:
            return g.get("grupo")
    return None


def fuera_de_alcance(tema_grupo, grupos):
    """Texto para cuando preguntan algo que en ESE grupo no se contesta. Dice adónde ir, así nadie
    se queda esperando una respuesta que no va a llegar."""
    otro = donde_preguntar(TODO, grupos)
    de_que = {TICKETS: "los tickets de soporte",
              PLANKA: "las tareas del equipo"}.get(tema_grupo, "este tema")
    destino = f" Para otras consultas escribime en *{otro}*." if otro else ""
    return f"En este grupo sólo manejo {de_que}.{destino}"
