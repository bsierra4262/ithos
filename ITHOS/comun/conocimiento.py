#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conocimiento TÉCNICO PROPIETARIO de ITHOS (INTELLIHELP) + control de acceso a él.

Contiene: qué versión de cada software soporta (desde/hasta), qué permite hacer con cada
sistema y sus LIMITACIONES, y CÓMO ESTÁ PROGRAMADO todo. Sirve para que ITHOS pueda
responder cualquier duda sobre su propio funcionamiento e implementación.

⚠️ Es INFORMACIÓN PROPIETARIA: solo se responde a los números autorizados del dueño.
A cualquier otro remitente, ITHOS contesta que no puede dar esos detalles porque es un
sistema propietario de INTELLIHELP. El soporte normal (tickets, SLA, portero) NO se
restringe: eso lo responde a cualquiera.
"""

import os
import re

# TELÉFONOS del DUEÑO (los ÚNICOS autorizados por WhatsApp, oficial y no-oficial).
# Se comparan por los ÚLTIMOS 10 dígitos: robusto a +54 / 549 / 54 / espacios / guiones /
# JID de WhatsApp. NADIE MÁS. Si un cliente inicia su propia sesión con su número, su
# número NO está acá -> nunca es tratado como dueño.
#   +54 9 11 5162-9038  y  +54 9 11 5666-0181
TELEFONOS_DUENO = ["+5491151629038", "+5491156660181"]
AUTORIZADOS_10 = {re.sub(r"\D", "", n)[-10:] for n in TELEFONOS_DUENO}

# Identidades del DUEÑO que no son un teléfono (se comparan en minúsculas).
AUTORIZADOS_ID = {"bsierra4262@gmail.com"}


# Canales cuya identidad NO es un teléfono: ahí un valor numérico es un ID (p. ej. el user-id
# de Telegram), NO un teléfono, y se compara VERBATIM contra las identidades autorizadas —
# NUNCA por 'últimos 10 dígitos'. Así un id numérico no puede coincidir por azar con el
# teléfono del dueño (namespacing: teléfonos ↔ AUTORIZADOS_10, identidades ↔ AUTORIZADOS_ID).
_CANALES_NO_TELEFONO = {"telegram", "email", "correo", "teams", "slack", "discord", "webchat"}


def _clave(remitente, canal=""):
    """Normaliza un remitente a (clave, es_telefono). es_telefono=True SOLO si es un teléfono
    en un canal telefónico (se compara por últimos 10 dígitos, robusto a +54/549/espacios).
    Email, @usuario o un id numérico de un canal no-telefónico -> identidad verbatim."""
    s = str(remitente or "").strip().lower()
    if not s:
        return "", False
    if "@" in s and not s.replace("@", "").isdigit():   # email o @usuario_telegram
        return s.lstrip("@"), False
    d = re.sub(r"\D", "", s)
    es_canal_tel = (canal or "").lower() not in _CANALES_NO_TELEFONO
    if d and len(d) >= 8 and es_canal_tel:              # teléfono -> últimos 10
        return d[-10:], True
    return s.lstrip("@"), False                         # id no telefónico -> verbatim


def esta_autorizado(remitente=None, canal=""):
    """True SOLO si el remitente es una identidad del DUEÑO. La autorización es por
    IDENTIDAD (teléfono / email / usuario), NUNCA por el canal ni por 'IsFromMe': que un
    mensaje sea de la sesión no alcanza; el número tiene que ser uno de los del dueño. Así,
    si un cliente usa su propia sesión de WhatsApp (su número), NO es dueño. Vale igual para
    WhatsApp oficial y no-oficial, Telegram y Email.
    SEGURIDAD (namespacing): un teléfono SOLO se compara contra el set de teléfonos y un id
    no telefónico (Telegram/email) SOLO contra el set de identidades. Así un id numérico NO
    puede autorizarse por coincidir con los últimos 10 dígitos del teléfono del dueño."""
    k, es_tel = _clave(remitente, canal)
    if not k:
        return False
    return (k in AUTORIZADOS_10) if es_tel else (k in AUTORIZADOS_ID)


# ===================================================================== CLAVE DE ADMIN
# Contraseña estilo Iron Man: sirve para DESTRABAR el modo administrador por UNA sola
# consulta, aun sin identificación (ej. por micrófono, que cualquiera puede usar). Al decir
# la frase con este código, ITHOS acepta la próxima pregunta como admin y después CIERRA
# la sesión (vuelve a usuario estándar). Frase de ejemplo:
#   "ITHOS, código de seguridad de acceso Kanerito4262, autorización de administrador."
# ⚠️ A futuro se suma IDENTIFICACIÓN POR VOZ: si sabe la clave pero NO es la voz del dueño,
# no la acepta.
def clave_admin() -> str:
    """La frase-clave de administrador. Sale de `ITHOS_CLAVE_ADMIN` (el .env del servidor).

    Estaba escrita acá adentro, en el código: la MISMA para todos los clientes, versionada junto
    al repositorio y —peor— metida en el vocabulario que se le manda al transcriptor en CADA audio,
    o sea viajando a un tercero todo el tiempo. Una contraseña no se versiona ni se comparte entre
    empresas. Se deja el valor histórico como respaldo para no dejar a nadie afuera al actualizar;
    fijando la variable de entorno queda fuera del código."""
    import os
    return (os.environ.get("ITHOS_CLAVE_ADMIN") or _CLAVE_HISTORICA).strip().lower()


_CLAVE_HISTORICA = "kanerito4262"      # respaldo: compatibilidad con lo ya desplegado
# Qué tan parecida puede sonar la palabra para aceptarla. El micrófono transcribe mal y hay que
# tolerarlo, pero 0.68 sobre ocho letras deja pasar tres caracteres distintos: "canelito",
# "panerito" o "kanerita" entraban. Se sube, y además el NÚMERO pasa a ser obligatorio (abajo).
_RATIO_KANERITO = 0.86

_RE_FRASE_ADMIN = re.compile(
    r"(ithos|ithos|c[oó]digo de seguridad|de acceso|autorizaci[oó]n de administrador|"
    r"autoridad( de)?|modo administrador|administrador|seguridad|acceso|kanerito\s*4262)",
    re.I)


def _norm_txt(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def detectar_clave_admin(texto):
    """True si el texto trae la CLAVE de administrador COMPLETA.

    Tolera espacios, mayúsculas y una transcripción imperfecta de la PALABRA —el micrófono se come
    letras y eso hay que aguantarlo—, pero el NÚMERO es obligatorio siempre.

    Antes alcanzaba con algo que sonara parecido a la palabra MÁS una frase genérica como
    "administrador" o "acceso". Dicho de otro modo: media contraseña y una palabra de uso común.
    Y como la tolerancia fonética estaba en 0.68 sobre ocho letras, "canelito", "panerito" o
    "kanerita" pasaban. La parte difícil de adivinar de una contraseña es justamente la que no se
    puede aflojar."""
    import difflib
    clave = clave_admin()
    n = _norm_txt(texto)
    if clave and clave in n:                       # exacta: palabra + número, pegados o no
        return True
    palabra = re.sub(r"[0-9]", "", clave)
    digitos = re.sub(r"[^0-9]", "", clave)
    if not digitos or digitos not in n:
        return False                               # sin el número NO hay clave, se diga lo que se diga
    return any(difflib.SequenceMatcher(None, w, palabra).ratio() >= _RATIO_KANERITO
               for w in re.findall(r"[a-zá-ú]+", (texto or "").lower()))


# Consulta TÉCNICA = pregunta sobre ITHOS MISMO (cómo está hecho/programado, sus versiones,
# su código, sus módulos, qué sistemas soporta). NO confundir con una consulta OPERATIVA de
# soporte (trabajar sobre un ticket: categorizar, asignar, SLA, primera respuesta, el "circuito").
# Antes el patrón era tan amplio ('qué hace', 'api', 'servidor', 'función'…) que un pedido
# operativo del DUEÑO caía en el modo técnico y ITHOS: (a) volcaba toda su arquitectura y
# (b) NO ejecutaba ninguna acción. Ahora es ESTRICTO y además se descarta si el texto es
# claramente operativo (menciona un ticket, categoría, SLA, asignar, circuito, un #número…).
_RE_TECNICA = re.compile(
    r"c[oó]mo (est[aá]s|fuiste|te)\s*\w*\s*(program|hech|armad|constru|dise[ñn]|hicieron|armaron)"
    r"|c[oó]mo (funcion[aá]s|trabaj[aá]s)\b"
    r"|tu (c[oó]digo|arquitectura|implementaci[oó]n|programaci[oó]n|stack|c[oó]digo fuente|"
    r"estructura interna|funcionamiento interno|dise[ñn]o interno)"
    r"|tus (m[oó]dulos|archivos|dependencias|versiones|librer[ií]as)"
    r"|qu[eé] (versi[oó]n|versiones)\b"
    r"|qu[eé] (tecnolog[ií]a|framework|librer[ií]a|lenguaje|modelos? de ia|dependencias?)"
    r"|qu[eé] sistemas (de )?(tickets|acceso|control)"
    r"|de qu[eé] se encarga (cada|el m[oó]dulo|el archivo|tu)"
    r"|\.py\b|\bcomun/|\bcentral/|\bagente/"
    r"|historial de cambios|changelog"
    r"|explic[aá](me)? (tu |el m[oó]dulo|c[oó]mo est[aá]s|c[oó]mo funcion)"
    r"|tu funcionamiento interno", re.I)

# Señales de que la consulta es OPERATIVA (trabajo sobre tickets) -> NO es técnica.
_RE_OPERATIVA = re.compile(
    r"\bticket|\bcaso\b|incidente|fichaj|legajo|molinete|categor[ií]|asign|"
    r"cerr[aá]|reabr|respond[eé]|primera respuesta|en espera|prioridad|escal|"
    r"circuito|\bciclo\b|\bsla\b|#\d{2,7}|\b\d{3,7}\b", re.I)


def es_consulta_tecnica(texto):
    """True SOLO si la consulta es sobre la IMPLEMENTACIÓN de ITHOS mismo (cómo está
    programado, versiones, código, módulos, qué sistemas soporta) y NO es un pedido operativo
    de soporte. Así un pedido del dueño ('ponelo en espera y hacé el circuito') NO cae en el
    modo técnico (que solo devuelve texto), sino en el agente (que EJECUTA acciones)."""
    t = texto or ""
    return bool(_RE_TECNICA.search(t)) and not _RE_OPERATIVA.search(t)


def quitar_frase_admin(texto):
    """Saca la frase/clave de administrador (incluidas variantes fonéticas del audio y el
    código numérico) y deja SOLO la consulta real, si la hay."""
    import difflib
    t = _RE_FRASE_ADMIN.sub(" ", texto or "")
    palabra = re.sub(r"[0-9]", "", clave_admin())
    digitos = re.sub(r"[^0-9]", "", clave_admin())
    limpio = []
    for w in re.split(r"\s+", t):
        wl = re.sub(r"[^0-9a-zá-ú]", "", w.lower())
        if not wl:
            continue
        if wl == digitos:                             # el número del código
            continue
        if wl.isalpha() and difflib.SequenceMatcher(None, wl, palabra).ratio() >= _RATIO_KANERITO:
            continue                                  # palabra parecida a 'kanerito'
        limpio.append(w)
    return re.sub(r"\s+", " ", " ".join(limpio)).strip(" ,.-¿?¡!")


MENSAJE_RESTRINGIDO = (
    "Esa información es sobre el funcionamiento interno del sistema y es *propietaria de "
    "INTELLIHELP*, así que no puedo compartirla. Con gusto te ayudo con el soporte: "
    "tickets, estados, SLA y demás.")


# ==================================================== ALCANCE PÚBLICO (para cualquiera)
# Lo que ITHOS SÍ puede contar a cualquiera: QUÉ hace, sin nada de CÓMO está hecho. Es el resumen
# del DOCUMENTO_MAESTRO (sección "Qué hace"), así la respuesta corta y la detallada dicen lo MISMO,
# una resumida y la otra completa. Se mantiene al día junto con el maestro.
ALCANCE_PUBLICO = """QUÉ PUEDE HACER ITHOS (esto se puede contar a cualquiera; el CÓMO está hecho, no):
- Portero por voz: anuncia por los parlantes cada fichada del control de acceso, con saludo acorde a
  la hora, sin repetirle a la misma persona en el día.
- Mesa de ayuda con IA: clasifica, prioriza, fija el SLA, asigna, responde y lleva el ciclo completo
  del ticket hasta que el cliente confirma; si la espera depende del cliente, le recuerda una vez por
  día hábil y avisa al técnico asignado si no responde. Si dice que el problema sigue, le pide la
  evidencia (foto o video del error, dónde y cuándo).
- Asistente por WhatsApp, además del micrófono: responde y ejecuta acciones
  reales sobre los tickets (cerrar, responder, poner en espera, posponer, asignar, buscar, reportes).
- Reportes ITIL: volumen, SLA, MTTR, backlog y desglose por técnico o categoría, automáticos o a
  demanda, en PDF y CSV, en la zona horaria y los días hábiles del cliente.
- Base de conocimiento propia que se regenera sola con los casos resueltos.
- Tareas del equipo: mantiene el tablero al día desde WhatsApp (resumen diario y seguimiento).
- Todo por cliente y aislado: cada empresa tiene su configuración, sus datos y su facturación."""


def documento_maestro():
    """El DOCUMENTO_MAESTRO.md del proyecto (la documentación COMPLETA del sistema), para que la
    respuesta DETALLADA al dueño salga de ahí y no de un texto paralelo que se desactualiza.
    Devuelve '' si no está disponible (entonces se usa sólo CONTEXTO_TECNICO). Se lee una vez."""
    global _MAESTRO
    if _MAESTRO is None:
        _MAESTRO = ""
        aqui = os.path.dirname(os.path.abspath(__file__))               # ITHOS/comun
        for ruta in (os.path.join(os.sep + "app", "DOCUMENTO_MAESTRO.md"),   # contenedor (montado)
                     os.path.join(aqui, "..", "..", "DOCUMENTO_MAESTRO.md"),  # repo (desarrollo)
                     os.path.join(aqui, "..", "DOCUMENTO_MAESTRO.md")):
            try:
                if os.path.exists(ruta):
                    with open(ruta, encoding="utf-8") as f:
                        _MAESTRO = f.read()
                    break
            except OSError:                                              # noqa: PERF203
                continue
    return _MAESTRO


_MAESTRO = None      # caché del documento maestro (se lee una sola vez)


# ============================================================================ CONTEXTO
CONTEXTO_TECNICO = """CONOCIMIENTO TÉCNICO PROPIETARIO DE ITHOS (INTELLIHELP) — usalo para explicar con precisión
qué hace el sistema, cómo está armado y sus límites. El detalle completo es el DOCUMENTO_MAESTRO (se
suma cuando piden detalle). Si algo no figura acá ni ahí, decí que ese dato no lo tenés.

# ARQUITECTURA
- GESTOR (ITHOS/central): FastAPI + WebSocket en Docker, en la VPS de INTELLIHELP (Hostinger KVM 2,
  ithos.intellihelp.tech), con Caddy (HTTPS) y Ollama (IA local). Es el cerebro: tickets, IA,
  WhatsApp, reportes, tablero del equipo y panel.
- AGENTE (ITHOS/agente): app liviana en la PC del cliente (instalador firmado). Lee las fichadas,
  habla por los parlantes y escucha el micrófono; la configuración se la manda el Gestor.
- Multi-cliente: cada empresa aislada (configuración, memoria, base de conocimiento y secretos
  cifrados con AES-256-GCM). No hay ambiente de demo: se prueba en producción con pruebas aisladas.

# INTEGRACIONES (son estas y no otras)
- Mesa de ayuda: GLPI 12, por su API REST (comun/glpi.py y el adaptador comun/tickets.py). Un
  cliente son varias entidades de GLPI, una por área, con su catálogo y su SLA.
- Control de acceso: IVMS (Hikvision), leyendo su base SQL Server de fichadas
  (agente/integrador_ivms.py). No hace control de horario.
- Canal: WhatsApp (no oficial, neonize), con un grupo por tema; se vincula por QR.
- Tablero del equipo: Planka (sólo INTELLIHELP).
- GLPI lleva además un plugin propio, ithosconfirma: un cartel antes de aprobar una solución.

# IA
- La cadena la define la configuración de CADA cliente (ia.proveedor -> secundario -> terciario),
  armada en comun/ia.py (MultiIA): una sola IA por consulta y, recién cuando se agota, la siguiente.
  Si preguntan qué IA o qué modelo se usa, contestá con la cadena REAL que figure en el estado de IA
  de esta conversación; nunca con una lista de memoria.
- Hay una IA local en la VPS (Ollama con qwen3:4b) como último respaldo.
- Voz de los parlantes: Charon (TTS de Gemini), con edge-tts de respaldo. Notas de voz de WhatsApp:
  edge-tts. Micrófono: activación "Hey ITHOS" con Vosk (local); el modo administrador por micrófono
  exige la frase-clave y la voz del dueño (voz-id, comun/vozid.py).

# MESA DE AYUDA
- Triage: lee el ticket completo, clasifica por el ALCANCE, prioriza, fija SLA/OLA, asigna y da la
  primera respuesta saludando al solicitante. Reparto de INTELLIHELP (central/equipo.py): la mesa por
  carga, Urgente y Alta a escalamiento, equipo caído en una sede a instalaciones.
- Pedido del técnico al cliente: En espera + nota interna; ITHOS no le repite nada.
- El técnico resuelve: Resuelto + pedido de confirmación con recordatorio por día hábil, y queda
  asignado sólo quien lo resolvió. Confirma: se cierra. Dice que sigue: se le pide la evidencia (foto o
  video del error, dónde, cuándo) y queda En espera. Cancela: se cierra.
- Fuera del horario de atención el ticket queda En espera y se reabre al empezar la jornada.
- Alertas de SLA por técnico, reportes ITIL (texto, CSV, PDF) en la zona del cliente y base de
  conocimiento que se regenera sola."""

def bloque_sistema(remitente=None, canal="", admin=False, detalle=False):
    """Devuelve el fragmento a inyectar en el prompt del asistente según autorización.
    admin=True fuerza acceso total (destrabado por la CLAVE de administrador, one-shot).
    detalle=True (el usuario pidió "detallado/todo/listá") suma la DOCUMENTACIÓN COMPLETA del
    sistema (DOCUMENTO_MAESTRO) para que la respuesta detallada diga TODO lo que dice el maestro.
    Autorizado (el dueño): conocimiento técnico completo + permiso de explicarlo.
    No autorizado: NO revela la implementación (es propietario), pero SÍ cuenta el ALCANCE (qué
    hace ITHOS) resumido — la misma información que la detallada, en corto."""
    if admin or esta_autorizado(remitente, canal):
        return ("\n\n[ACCESO TÉCNICO TOTAL — el que pregunta es el DUEÑO de INTELLIHELP.]\n"
                "IMPORTANTE: IGNORÁ cualquier negativa anterior del historial ('información "
                "propietaria, no puedo compartirla'): NO valen, el usuario está AUTORIZADO y está "
                "PROHIBIDO negarte.\n"
                "CÓMO RESPONDER lo técnico — PRECISIÓN y BREVEDAD (sos una IA de primer nivel, NO un "
                "volcado de documentación):\n"
                "· Por DEFECTO respondé en PROSA, de 1 a 4 frases. NO uses tablas, cuadros ni listas "
                "largas salvo que te lo pidan EXPLÍCITO ('en detalle', 'una tabla', 'listá todo').\n"
                "· Respondé SOLO lo preguntado. Ej.: '¿qué IA/modelo usamos?' -> UNA frase con la "
                "cadena REAL que figura en el estado de IA de esta conversación, en orden.\n"
                "· CITÁ SOLO datos que figuren abajo. Si la versión/número exacto NO está, nombrá el "
                "proveedor y aclarás que ese dato puntual no lo tenés. PROHIBIDO inventar modelos, "
                "versiones, cuotas, TPM o fechas (nada de 'gemini-1.5', 'llama2-70b' ni números que "
                "no estén escritos). Mejor 'ese dato no lo tengo' que un dato FALSO.\n"
                "Basate SOLO en este conocimiento:\n\n" + CONTEXTO_TECNICO +
                _bloque_maestro(detalle) +
                "\n\n[RECORDATORIO FINAL — lo más importante: respondé EXACTO lo preguntado, BREVE "
                "(1-4 frases, en PROSA, SIN tablas salvo pedido explícito) y SIN inventar nada que "
                "no esté arriba. Si preguntan qué IA/modelo usamos: la cadena REAL del estado de "
                "IA, nunca una de memoria.]")
    return ("\n\n[INFORMACIÓN PROPIETARIA PROTEGIDA.]\n"
            "Si te preguntan CÓMO ESTÁ PROGRAMADO el sistema, su arquitectura interna, qué "
            "versiones soporta, nombres de archivos, claves o detalles de implementación, NO los "
            "des: es información propietaria de INTELLIHELP. Decilo con amabilidad. Texto sugerido: "
            "\"" + MENSAJE_RESTRINGIDO + "\"\n"
            "PERO SÍ podés contar QUÉ HACE ITHOS —su alcance— con naturalidad, y el soporte normal "
            "(tickets, estados, SLA, portero) respondelo como siempre. Si preguntan qué podés hacer, "
            "contestá RESUMIDO y al punto con esto (2-5 frases; sin nombrar archivos, versiones ni "
            "cómo está construido):\n\n" + ALCANCE_PUBLICO)


def _bloque_maestro(detalle):
    """Cuando el DUEÑO pide DETALLE, se suma la documentación COMPLETA del sistema (el
    DOCUMENTO_MAESTRO del repositorio). Así 'contame todo en detalle' responde con lo mismo que
    dice el maestro —completo y al día— y la respuesta corta es ese mismo contenido resumido, sin
    dos fuentes que se contradigan. Si el documento no está disponible, no se agrega nada."""
    if not detalle:
        return ""
    doc = documento_maestro()
    if not doc:
        return ""
    return ("\n\n[DOCUMENTACIÓN COMPLETA DEL SISTEMA (DOCUMENTO_MAESTRO del proyecto) — el usuario "
            "pidió DETALLE: usala como fuente principal y respondé con TODO lo que corresponda al "
            "tema preguntado, ordenado y sin inventar nada que no esté acá.]\n\n" + doc)
