#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cerebro de triage del Central: clasifica un ticket usando el ProveedorIA del
cliente (Gemini, local, etc.). No sabe ni le importa cuál es el proveedor.

Las REGLAS de negocio se cargan por cliente (aquí van las de SRT/ITH como default);
en el producto cada cliente puede tener su propio prompt/reglas.
"""

import json
import re

REGLAS_SRT = """Eres ITHOS, agente de triage de una mesa de ayuda. Clasificás
tickets de control de acceso (fichaje biométrico).

PRINCIPIOS: soporte de primer nivel, profesional y cordial. NUNCA rechaces ni
cierres un ticket ni pidas recargarlo: te hacés cargo, corregís internamente y
avanzás. Un ticket jamás se cierra sin resolución confirmada por el cliente.
Clasificá por la EVIDENCIA real del texto (qué falla y a quién), no por palabras
sueltas ni por el tono; entendé la intención aunque esté mal redactado. No inventes
datos: lo que no está, se pide.

CONTEXTO: el fichaje es por RECONOCIMIENTO FACIAL (rostro). No hay tarjetas ni
huella; hablá siempre de "reconocimiento facial"/"no reconoce el rostro".

CATEGORÍAS:
- MOLINETES: falla mecánica/hardware del molinete físico (trabado, no baja, ruidos).
- TERMINALES: falla el lector de reconocimiento facial o no permite fichar a un
  usuario (pantalla apagada/rota, no reconoce el rostro).
- HIK-CENTRAL: falla operativa del software de accesos (NO para fallos de fichada).
- INTERFACE: desarrollo interno Hik-Central↔Meta4 o reportes.
Clave: si un colaborador NO puede fichar, casi siempre es TERMINALES.

ALCANCE — LO PRIMERO QUE TENÉS QUE DECIDIR. Cambia todo lo demás: la prioridad, qué
datos hacen falta y quién lo atiende. Preguntate QUÉ es lo que falla:
- "individual": falla el fichaje de UNA persona concreta y el equipo anda para el
  resto (no la reconoce, no tiene acceso, no le figura la fichada).
- "grupo": le pasa a VARIAS personas identificables, pero el equipo sigue andando.
- "equipo": se rompió o dejó de andar UN lector/molinete/reloj de una sede que tiene
  otros: nadie puede fichar POR AHÍ, pero hay otro equipo como alternativa.
- "sede": la sede se quedó SIN fichaje (el equipo está apagado, muerto, sin señal o
  sin energía y no hay otro): NADIE de esa sede puede fichar.
- "masivo": varias sedes, el sistema entero o los reportes de todos.

⛔ REGLA QUE SE VIENE INCUMPLIENDO — LEELA DOS VECES: si lo que falla es el EQUIPO
("dejó de funcionar", "está apagado", "no anda", "se rompió", "no prende", "no toma
a nadie", "nadie puede fichar"), NO es un caso individual. Que el ticket no nombre a
ninguna persona NO significa que haya un solo afectado: significa que están afectados
TODOS los que fichan ahí. Es un problema de INSTALACIONES y es GRAVE. Tratarlo como
"un solo usuario" y dejarlo esperando un legajo es el peor error posible: deja una
sede entera sin fichar mientras el ticket duerme.

PRIORIDAD, según el alcance (no según el tono ni las mayúsculas del texto):
- individual -> "Baja" (o "Media" si es reincidente o traba una tarea). NUNCA Urgente.
- grupo      -> "Media".
- equipo     -> "Alta".
- sede       -> "Urgente" (la sede no puede fichar: no hay alternativa).
- masivo     -> "Urgente".

DATOS DEL AFECTADO (Nombre y Apellido + Número de Legajo): se piden SÓLO cuando hay
UNA persona afectada a la que identificar.

REGLAS FIJAS (cumplilas SIEMPRE, sin excepción):
- alcance="individual" y el texto NO trae el NÚMERO de legajo (un número, no sólo el
  nombre) -> necesita_info=true. Si trae el número -> necesita_info=false.
- alcance distinto de "individual" -> necesita_info=false SIEMPRE. No hay una persona
  a la que pedirle el legajo, y el técnico tiene que salir a trabajar YA: el ticket no
  puede quedar esperando al cliente. Si te sirve algún dato (desde cuándo, si el
  equipo tiene energía o red, si la sede tiene otro lector, quién está en el lugar),
  pedilo en la respuesta SIN frenar el ticket ni pedirlo como condición para avanzar.
- La prioridad sale de la tabla de arriba, no del texto.

RESPONSABLE:
- "jayala" (instalaciones/infra/redes): TODO lo que sea alcance "equipo", "sede" o
  "masivo" de hardware —terminal/lector/molinete/reloj caído, sin energía, sin red,
  instalación nueva—.
- "bsierra" (soporte/fichaje): los casos individuales o de grupo, y el software
  (Hik-Central, interface, reportes).

PRIMERA RESPUESTA: cordial, breve y profesional; si corregís categoría/prioridad
explicalo en positivo. Firmá "Soporte ITH" UNA sola vez, al final, y no agregues
ninguna otra fórmula de cierre ni repitas la despedida.
- Caso individual sin legajo: pedilo con amabilidad.
- Equipo/sede/masivo: NO pidas legajo. Reconocé el alcance real ("nadie puede fichar
  en esa sede"), decí que se deriva al equipo de instalaciones y que se está
  trabajando, y pedí en la misma línea lo que ayude a llegar preparado (desde cuándo,
  si tiene energía o red, si hay otro lector) SIN condicionar el avance.
SALUDO: saludá SIEMPRE al SOLICITANTE (quien ABRIÓ el ticket) por su nombre de pila,
que se te indica como "SOLICITANTE". JAMÁS uses el nombre de la persona AFECTADA que
aparezca en el asunto o el texto (p. ej. el empleado del legajo): esa NO es a quien le
respondés. Si no se indica solicitante, saludá con un "Hola," neutro, sin inventar un nombre.

NOTA INTERNA PARA TÉCNICOS (nota_tecnico): comentario PRIVADO que SOLO ven los técnicos del
equipo (el cliente NO lo ve). Usalo para darles feedback ÚTIL cuando el ticket viene MAL
CARGADO o falta algo: la categoría/prioridad que corregiste y por qué, un dato clave que
falta, o algo que el técnico debería revisar o tener en cuenta antes de trabajarlo. Breve y
concreto, tono de compañero de equipo. Si NO hay nada relevante que avisar, dejá "" (vacío).
NUNCA repitas ahí la primera respuesta ni le hables al cliente: es solo para el equipo.

ANTECEDENTES: si te paso casos parecidos ya trabajados de este mismo cliente, usalos
para entender qué terminó siendo un problema así y cómo se atendió. Son hechos reales:
NO inventes ni supongas nada que no esté ahí, y no los cites en la respuesta al
cliente. Si ninguno se parece de verdad, ignoralos.

Respondé SOLO este JSON:
{"alcance":"individual|grupo|equipo|sede|masivo",
 "categoria":"TERMINALES|MOLINETES|HIK-CENTRAL|INTERFACE|OTRA",
 "prioridad":"Baja|Media|Alta|Urgente","responsable":"bsierra|jayala",
 "necesita_info":true|false,"resumen":"una linea","primera_respuesta":"texto",
 "nota_tecnico":"nota interna breve para el equipo, o \"\" si no hay nada"}"""


def clasificar_ticket(ia, asunto, descripcion, reglas=REGLAS_SRT, solicitante="",
                      antecedentes=""):
    """Usa el ProveedorIA del cliente para clasificar. `solicitante` = nombre de pila de quien ABRIÓ
    el ticket, para saludarlo por su nombre (no a la persona afectada del texto). `antecedentes` =
    casos parecidos REALES del histórico del cliente, para clasificar con precedentes en vez de con
    la intuición del modelo. Devuelve dict o None."""
    sol = (f"SOLICITANTE (a quien saludás): {solicitante}\n\n" if solicitante else "")
    ant = (f"\n\nANTECEDENTES (casos reales ya trabajados de este cliente):\n{antecedentes}"
           if antecedentes else "")
    entrada = (f"{sol}ASUNTO: {asunto}\n\nDESCRIPCIÓN:\n{descripcion or '(sin descripción)'}{ant}")
    try:
        return json.loads(ia.chat(reglas, entrada, json_out=True))
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------------ coherencia
# El prompt no alcanza: un modelo puede leer bien el alcance y aun así dejar el ticket esperando
# un legajo, o bajarle la prioridad porque el texto no nombra a nadie. Estas reglas se aplican
# SIEMPRE sobre lo que devolvió, así el resultado no depende de que se acuerde de cumplirlas.
_PRIORIDAD_ORDEN = {"Baja": 1, "Media": 2, "Alta": 3, "Urgente": 4}
_PISO_PRIORIDAD = {"individual": "Baja", "grupo": "Media", "equipo": "Alta",
                   "sede": "Urgente", "masivo": "Urgente"}
ALCANCES = ("individual", "grupo", "equipo", "sede", "masivo")
ALCANCE_ORDEN = {a: i for i, a in enumerate(ALCANCES)}
ALCANCE_SERVICIO = ("equipo", "sede", "masivo")     # falla el servicio, no una persona

# El equipo dejó de dar servicio. No dice "no puedo fichar YO": dice que el aparato no está.
_RE_EQUIPO_CAIDO = re.compile(
    r"dej(?:o|ó|aron)\s+de\s+(?:funcionar|andar|operar)|no\s+(?:funciona|anda|responde|prende|"
    r"enciende)|est[aá]\s+apagad|se\s+apag[oó]|fuera\s+de\s+servicio|sin\s+servicio|"
    r"se\s+rompi[oó]|est[aá]\s+ca[ií]d|qued[oó]\s+ca[ií]d|no\s+hay\s+(?:se[nñ]al|energ[ií]a|red)",
    re.I)
# Nadie puede fichar ahí: el problema no tiene una víctima, las tiene a todas.
_RE_NADIE_FICHA = re.compile(
    r"nadie\s+(?:puede|podia|podía|pudo)\s+fich|no\s+pueden\s+fich|ninguno\s+puede\s+fich|"
    r"no\s+toma\s+a\s+nadie|todos\s+los\s+agentes|toda\s+la\s+sede|todo\s+el\s+personal", re.I)
# Está hablando del servicio de un lugar, no de un aparato entre varios.
_RE_SERVICIO_SEDE = re.compile(
    r"\bel\s+fichaje\b|\bel\s+sistema\b|sistema\s+biom[eé]trico|\bel\s+biom[eé]trico\b|"
    r"falla\s+general|se\s+cay[oó]\s+(?:todo|el\s+sistema)", re.I)
# Hay UNA persona identificada: el ticket sí es de alguien en concreto.
_RE_PERSONA = re.compile(r"legajo\s*n?[°º:.\s-]*\d{2,}|\bleg\.?\s*\d{2,}", re.I)
# La respuesta está pidiendo identificar a un afectado que en este ticket no existe.
_RE_PIDE_DATOS_PERSONA = re.compile(
    r"legajo|nombre\s+y\s+apellido|persona\s+afectada|agente\s+afectad", re.I)

# Respuesta para cuando el equipo dejó de dar servicio: reconoce el alcance real, avisa que ya se
# derivó y pide lo que sirve para llegar preparado, SIN condicionar el avance del ticket.
RESPUESTA_SERVICIO_CAIDO = (
    "recibimos el aviso de que el equipo de fichaje dejó de funcionar. Lo tomamos como una falla "
    "del servicio —mientras esté así no puede fichar nadie en esa ubicación—, por lo que el ticket "
    "queda con prioridad alta y derivado al equipo de instalaciones, que ya está trabajando en "
    "esto. Para llegar mejor preparados, si lo tienen a mano nos sirve saber desde cuándo dejó de "
    "funcionar, si el equipo tiene energía y conexión de red, y si en la sede hay otro lector "
    "disponible mientras tanto; no hace falta que nos respondan para que avancemos. Les "
    "confirmamos apenas tengamos novedades. Soporte ITH.")


def alcance_por_texto(asunto, descripcion):
    """Alcance MÍNIMO que se desprende del texto del ticket, o None si no hay señales claras.

    Es la red de seguridad: el modelo puede leer mal y decir "individual" sobre un equipo que se
    apagó —pasó de verdad—, y entonces ninguna regla que dependa de su respuesta lo salva. Acá se
    mira lo que dice el ticket: si el aparato dejó de dar servicio y NO hay una persona
    identificada, no puede tratarse como el caso de un usuario suelto."""
    t = f"{asunto or ''}\n{descripcion or ''}"
    if _RE_NADIE_FICHA.search(t):
        return "sede"
    if not _RE_EQUIPO_CAIDO.search(t):
        return None
    if _RE_PERSONA.search(t):
        return None                                  # hay un legajo: es el caso de esa persona
    return "sede" if _RE_SERVICIO_SEDE.search(t) else "equipo"


def coherente(a, asunto="", descripcion=""):
    """Corrige la clasificación para que no se contradiga a sí misma ni con el ticket. Devuelve
    (dict, correcciones).

    Si lo que falla es el equipo o la sede no hay una persona a la que pedirle el legajo: el ticket
    no puede quedar esperando al cliente, la prioridad no puede quedar por debajo del piso de su
    alcance, y lo atiende instalaciones. Es exactamente lo que falló cuando un biométrico quedó
    apagado en una sede: se trató como un usuario suelto, prioridad Baja, y el ticket quedó EN
    ESPERA pidiendo un legajo que no existía mientras la sede entera no podía fichar."""
    if not isinstance(a, dict):
        return a, []
    hechas = []
    alcance = str(a.get("alcance") or "").strip().lower()
    if alcance not in ALCANCES:
        alcance = "individual"                       # sin dato, el caso más conservador
    # El texto manda cuando es evidente: sólo puede SUBIR el alcance, nunca bajarlo.
    minimo = alcance_por_texto(asunto, descripcion)
    if minimo and ALCANCE_ORDEN[minimo] > ALCANCE_ORDEN[alcance]:
        hechas.append(f"alcance {alcance} -> {minimo}: el ticket dice que el equipo dejó de dar "
                      "servicio y no identifica a ninguna persona en particular")
        alcance = minimo
    a["alcance"] = alcance

    if alcance in ALCANCE_SERVICIO and a.get("necesita_info"):
        a["necesita_info"] = False
        hechas.append("no se pide legajo ni se deja en espera: lo que falla es el servicio, "
                      "no el fichaje de una persona")

    piso = _PISO_PRIORIDAD[alcance]
    prio = a.get("prioridad") if a.get("prioridad") in _PRIORIDAD_ORDEN else piso
    if _PRIORIDAD_ORDEN[prio] < _PRIORIDAD_ORDEN[piso]:
        a["prioridad"] = piso
        hechas.append(f"prioridad {prio} -> {piso} por el alcance ({alcance})")
    else:
        a["prioridad"] = prio

    # Equipamiento caído en una sede es instalaciones; el software y los casos sueltos, soporte.
    if alcance in ALCANCE_SERVICIO and a.get("categoria") in ("TERMINALES", "MOLINETES") \
            and a.get("responsable") != "jayala":
        a["responsable"] = "jayala"
        hechas.append("lo toma instalaciones: hay equipamiento caído en la sede")

    # Si corregimos el alcance, la respuesta que escribió el modelo quedó hablando de otro ticket:
    # sigue pidiendo el legajo de una persona que no existe. Eso NO puede salir al cliente.
    if alcance in ALCANCE_SERVICIO and _RE_PIDE_DATOS_PERSONA.search(a.get("primera_respuesta") or ""):
        a["primera_respuesta"] = RESPUESTA_SERVICIO_CAIDO
        hechas.append("se reemplazó la respuesta al cliente: pedía el legajo de una persona que "
                      "este ticket no tiene")
        # La nota al técnico venía del mismo razonamiento equivocado: la reemplaza la nota de
        # alcance, que sí explica por qué el ticket entra como entra.
        if _RE_PIDE_DATOS_PERSONA.search(a.get("nota_tecnico") or ""):
            a["nota_tecnico"] = ""
    return a, hechas
