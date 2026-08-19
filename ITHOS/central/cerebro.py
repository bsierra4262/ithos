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

⛔ EL LEGAJO CASI SIEMPRE VIENE EN EL ASUNTO, aunque no diga la palabra "legajo".
El asunto se escribe "<legajo> <apellido y nombre>": en «00084 Zuker Sebastián» el
legajo ES 00084, y en «Legajo 01347 Rojas, Natalia» es 01347. Si el asunto empieza con
un número, ESE es el legajo y YA LO TENÉS: no lo pidas. Pedir un dato que está a la
vista en el ticket es el peor error que podés cometer: deja el ticket parado esperando
algo que el cliente ya escribió. LEÉ EL ASUNTO antes de decidir que falta algo.

REGLAS FIJAS (cumplilas SIEMPRE, sin excepción):
- alcance="individual" y NI el asunto NI la descripción traen el NÚMERO de legajo (un
  número, no sólo el nombre) -> necesita_info=true. Si el número está en cualquiera de
  los dos -> necesita_info=false.
- alcance distinto de "individual" -> necesita_info=false SIEMPRE. No hay una persona
  a la que pedirle el legajo.
- La prioridad sale de la tabla de arriba, no del texto.

VISITA AL LUGAR (requiere_visita): un equipo caído —terminal, lector, molinete o reloj
que dejó de funcionar, quedó apagado, sin energía o sin red— NO se arregla por mail:
hay que ir. En esos casos requiere_visita=true.

⛔ Las instalaciones las hicimos NOSOTROS: ya sabemos dónde está cada equipo, cómo está
montado y con qué red trabaja. NO preguntes nada de eso —ni la ubicación, ni si tiene
energía, ni si hay otro lector—: queda pésimo, es información que ya tenemos y encima
lo vemos nosotros al llegar. Lo ÚNICO que hay que pedirle al cliente es COORDINAR LA
VISITA: qué día y en qué franja horaria podemos pasar, y con quién nos encontramos.
Con eso el ticket queda EN ESPERA de su confirmación —es él quien tiene que decirnos
cuándo podemos ir— y se le recuerda una vez por día hábil hasta que responda. Eso NO
es "falta un dato del afectado": es una coordinación (necesita_info sigue en false).

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
- Equipo caído (requiere_visita): NO pidas legajo NI datos del equipo. Reconocé el
  alcance real ("mientras esté así no puede fichar nadie en esa sede"), decí que lo
  toma el equipo de instalaciones y que para resolverlo hay que ir al lugar, y pedí
  COORDINAR LA VISITA: qué día y en qué franja horaria pueden recibirnos, y con quién
  nos encontramos. Cerrá diciendo que apenas confirmen se agenda.
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
 "necesita_info":true|false,"requiere_visita":true|false,
 "resumen":"una linea","primera_respuesta":"texto",
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
# La prioridad QUE LE CORRESPONDE a cada alcance. No es un piso: es la que va. Dos tickets del
# mismo tipo tienen que salir con la misma prioridad siempre, o los reportes no miden nada.
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
# El legajo escrito con todas las letras ("Legajo 01347", "leg. 5808").
_RE_LEGAJO_EXPLICITO = re.compile(r"legajo\s*n?[°º:.\s-]*(\d{2,})|\bleg\.?\s*(\d{2,})", re.I)
# El asunto arranca con el legajo y sigue el nombre ("00084 Zuker Sebastián"): así los carga el
# cliente y NO escribe la palabra "legajo". El número igual está: pedirlo es pedir lo que ya tenemos.
_RE_LEGAJO_ASUNTO = re.compile(r"^\s*(\d{3,6})\s*[-–.]?\s+[^\W\d_]", re.UNICODE)


# El técnico dice, con todas las letras, que el ticket QUEDÓ RESUELTO. Esto NO se somete a
# interpretación: si lo escribió, es una resolución. Hizo falta porque un comentario que arranca
# con "El inconveniente quedó solucionado" y sigue con el detalle de todo lo que se revisó —incluido
# algo que todavía falla— el modelo lo leía como un avance, y el ticket se quedaba En curso.
_RE_DICE_RESUELTO = re.compile(
    r"(?:qued[oó]|queda|est[aá]|ya\s+est[aá]|fue|lo\s+dejamos|lo\s+dejo)\s+"
    r"(?:solucionad|resuelt|arreglad|normalizad|operativ|funcionando)|"
    r"(?:se|lo|la)\s+(?:solucion[oó]|resolvi[oó]|arregl[oó]|normaliz[oó])|"
    r"(?:solucionamos|resolvimos|arreglamos|normalizamos)\b|"
    r"\b(?:inconveniente|problema|incidente|tema)\s+(?:solucionad|resuelt|arreglad)|"
    r"^\s*(?:solucionado|resuelto|listo)\b", re.I | re.M)
# Lo mismo pero NEGADO o a futuro: "no quedó solucionado", "todavía no se resolvió", "cuando
# quede solucionado", "para que quede resuelto". Estas frases NO cierran nada.
_RE_NO_RESUELTO = re.compile(
    r"(?:no|a[uú]n\s+no|todav[ií]a\s+no|sin|nunca|cuando|para\s+que|si)\s+"
    r"(?:\w+\s+){0,3}?(?:qued[oó]|queda|quede|est[aá]|se)?\s*"
    r"(?:solucionad|resuelt|arreglad|solucion[oó]|resolvi[oó]|arregl[oó])", re.I)


def dice_resuelto(texto):
    """True si el TÉCNICO afirma que el ticket quedó resuelto, sin depender de la IA.

    Es una red determinística, no un reemplazo del modelo: se usa ANTES de preguntarle, para que
    un "quedó solucionado" explícito SIEMPRE se detecte, por largo que sea el comentario y por más
    detalle técnico que venga después."""
    t = str(texto or "")
    if not t.strip():
        return False
    # Si la única mención está negada o es a futuro, no cuenta.
    negados = {m.group(0).lower() for m in _RE_NO_RESUELTO.finditer(t)}
    for m in _RE_DICE_RESUELTO.finditer(t):
        frase = m.group(0).lower()
        if not any(frase in n for n in negados):
            return True
    return False


def legajo_en_texto(asunto, descripcion=""):
    """El número de legajo que YA está en el ticket, o None. Mira el asunto y la descripción."""
    m = _RE_LEGAJO_ASUNTO.match(str(asunto or ""))
    if m:
        return m.group(1)
    for texto in (asunto, descripcion):
        m = _RE_LEGAJO_EXPLICITO.search(str(texto or ""))
        if m:
            return m.group(1) or m.group(2)
    return None
# La respuesta está pidiendo identificar a un afectado que en este ticket no existe.
_RE_PIDE_DATOS_PERSONA = re.compile(
    r"legajo|nombre\s+y\s+apellido|persona\s+afectada|agente\s+afectad", re.I)
# La respuesta está preguntando cosas que YA sabemos: nosotros instalamos ese equipo.
_RE_PREGUNTA_OBVIA = re.compile(
    r"tiene\s+(?:energ[ií]a|corriente|luz|red|conexi[oó]n)|est[aá]\s+conectad|"
    r"hay\s+otro\s+lector|d[oó]nde\s+est[aá]\s+(?:ubicad|instalad)|qu[eé]\s+modelo", re.I)
# La respuesta SÍ está pidiendo coordinar la visita (que es lo único que hay que pedir).
_RE_PIDE_COORDINAR = re.compile(
    r"coordinar\s+la\s+visita|qu[eé]\s+d[ií]a\s+y|podemos\s+pasar|coordinar\s+(?:una\s+)?visita|"
    r"franja\s+horaria", re.I)

# Frase estable para que el ciclo sepa que lo que se está esperando es una COORDINACIÓN (y no un
# dato que falta): así el recordatorio diario le habla de confirmar el día, no de "la información".
MARCA_COORDINAR = "coordinar la visita"

# Respuesta cuando el equipo se cayó y hay que ir al lugar. Las instalaciones las hicimos nosotros:
# no se pregunta dónde está, si tiene energía ni si hay otro lector —eso ya lo sabemos y lo vemos al
# llegar—. Lo único que hace falta del cliente es CUÁNDO podemos pasar.
def respuesta_con_legajo(legajo):
    """Acuse cuando el dato YA estaba en el ticket: se avisa que se está trabajando, sin pedir
    nada. Nombrar el legajo deja claro que lo leímos y que no hace falta que lo repitan."""
    return (f"recibimos el ticket. Con el legajo {legajo} tenemos lo necesario para revisarlo, "
            "así que ya lo estamos trabajando: verificamos el caso del agente y les confirmamos "
            "apenas tengamos el resultado. No hace falta que nos manden nada más.")


RESPUESTA_SERVICIO_CAIDO = (
    "recibimos el aviso y lo tomamos como una falla del servicio: mientras esté así no puede "
    "fichar nadie en esa ubicación, por lo que el ticket queda con prioridad alta y a cargo del "
    "equipo correspondiente, que ya está trabajando en esto. Les confirmamos apenas tengamos "
    "novedades.")

RESPUESTA_COORDINAR_VISITA = (
    "recibimos el aviso de que el equipo de fichaje dejó de funcionar. Lo tomamos como una falla "
    "del servicio —mientras esté así no puede fichar nadie en esa ubicación—, así que el ticket "
    "queda con prioridad alta y a cargo de nuestro equipo de instalaciones.\n\n"
    "Para resolverlo necesitamos ir hasta el lugar, por lo que sólo nos falta coordinar la visita: "
    "por favor indíquennos qué día y en qué franja horaria podemos pasar, y con quién nos "
    "encontramos al llegar. Apenas nos confirmen, la agendamos con el técnico.")


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

    # ---------------------------------------------------------------- el dato pedido vs. el estado
    # Dos caras del mismo error, y las dos se vieron en producción:
    #   a) PEDIR algo que el ticket YA TRAE (el legajo, que suele venir en el asunto). El modelo a
    #      veces marca necesita_info=false —correcto— pero igual escribe "pasame el legajo": el
    #      cliente lee un pedido que nadie va a contestar. Por eso NO se mira necesita_info acá: si
    #      el dato está y la respuesta lo pide, la respuesta se reemplaza.
    #   b) PEDIR algo de verdad y NO dejar el ticket esperando. Si le pedimos un dato al cliente, el
    #      ticket tiene que quedar EN ESPERA: con el SLA corriendo contra nosotros mientras la pelota
    #      es del cliente, el ticket nace vencido.
    legajo = legajo_en_texto(asunto, descripcion)
    pide_datos = bool(_RE_PIDE_DATOS_PERSONA.search(a.get("primera_respuesta") or ""))
    if alcance == "individual" and legajo and (pide_datos or a.get("necesita_info")):
        a["necesita_info"] = False
        hechas.append(f"el legajo ({legajo}) ya estaba en el ticket: no se pide y el ticket avanza")
        if pide_datos:
            a["primera_respuesta"] = respuesta_con_legajo(legajo)
            pide_datos = False
        if _RE_PIDE_DATOS_PERSONA.search(a.get("nota_tecnico") or ""):
            a["nota_tecnico"] = ""
    elif alcance == "individual" and pide_datos and not a.get("necesita_info"):
        # Le estamos pidiendo un dato que NO está: el ticket espera al cliente y el SLA se pausa.
        a["necesita_info"] = True
        hechas.append("la respuesta le pide un dato al cliente, así que el ticket queda EN ESPERA "
                      "y el SLA no corre mientras la pelota es de él")

    # La prioridad la decide el ALCANCE, no el ánimo del modelo. Antes esto era sólo un PISO, y un
    # ticket de una persona salía Baja un día y Media al otro según cómo lo redactaran: dos tickets
    # iguales con prioridades distintas, y los reportes de SLA midiendo ruido. Ahora es exacta.
    debe = _PISO_PRIORIDAD[alcance]
    prio = a.get("prioridad") if a.get("prioridad") in _PRIORIDAD_ORDEN else debe
    if prio != debe:
        hechas.append(f"prioridad {prio} -> {debe} por el alcance ({alcance})")
    a["prioridad"] = debe

    # Equipamiento caído en una sede es instalaciones; el software y los casos sueltos, soporte.
    if alcance in ALCANCE_SERVICIO and a.get("categoria") in ("TERMINALES", "MOLINETES") \
            and a.get("responsable") != "jayala":
        a["responsable"] = "jayala"
        hechas.append("lo toma instalaciones: hay equipamiento caído en la sede")

    # ¿Hay que ir al lugar? Un equipo caído no se arregla por mail.
    visita = bool(a.get("requiere_visita"))
    if alcance in ALCANCE_SERVICIO and a.get("categoria") in ("TERMINALES", "MOLINETES") \
            and not visita:
        visita = True
        hechas.append("hace falta ir al lugar: hay equipamiento caído")
    a["requiere_visita"] = visita

    # La respuesta que escribió el modelo puede estar hablando de otro ticket: pedir el legajo de
    # una persona que no existe, o preguntar cosas que ya sabemos porque instalamos nosotros el
    # equipo. Y si hay que ir, lo único que falta pedir —la coordinación— no puede faltar.
    r = a.get("primera_respuesta") or ""
    motivo = ""
    if alcance in ALCANCE_SERVICIO and _RE_PIDE_DATOS_PERSONA.search(r):
        motivo = "pedía el legajo de una persona que este ticket no tiene"
    elif visita and _RE_PREGUNTA_OBVIA.search(r):
        motivo = "preguntaba datos del equipo que ya tenemos (la instalación la hicimos nosotros)"
    elif visita and not _RE_PIDE_COORDINAR.search(r):
        motivo = "no pedía coordinar la visita, que es lo único que hace falta del cliente"
    if motivo:
        a["primera_respuesta"] = RESPUESTA_COORDINAR_VISITA if visita else RESPUESTA_SERVICIO_CAIDO
        hechas.append("se reemplazó la respuesta al cliente: " + motivo)
        # La nota al técnico venía del mismo razonamiento: la reemplaza la nota de alcance, que sí
        # explica por qué el ticket entra como entra.
        if _RE_PIDE_DATOS_PERSONA.search(a.get("nota_tecnico") or ""):
            a["nota_tecnico"] = ""
    return a, hechas
