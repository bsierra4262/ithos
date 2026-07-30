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

import re

# TELÉFONOS del DUEÑO (los ÚNICOS autorizados por WhatsApp, oficial y no-oficial).
# Se comparan por los ÚLTIMOS 10 dígitos: robusto a +54 / 549 / 54 / espacios / guiones /
# JID de WhatsApp. NADIE MÁS. Si un cliente inicia su propia sesión con su número, su
# número NO está acá -> nunca es tratado como dueño.
#   +54 9 11 5162-9038  y  +54 9 11 5666-0181
TELEFONOS_DUENO = ["+5491151629038", "+5491156660181"]
AUTORIZADOS_10 = {re.sub(r"\D", "", n)[-10:] for n in TELEFONOS_DUENO}

# Identidades del DUEÑO en OTROS canales (email / usuario o id de Telegram). Se pueden
# ampliar por config (agregar_autorizados) o con el bloque "autorizados" del cliente.
# Se comparan en minúsculas. Email del dueño por defecto (para que funcione sin configurar).
AUTORIZADOS_ID = {"bsierra4262@gmail.com"}


def agregar_autorizados(items):
    """Suma identidades del dueño para cualquier canal (emails, usuarios/ids de Telegram,
    o teléfonos). Los teléfonos se guardan por sus últimos 10 dígitos."""
    for it in (items or []):
        s = str(it).strip().lower()
        if not s:
            continue
        d = re.sub(r"\D", "", s)
        if d and len(d) >= 8 and "@" not in s:      # parece teléfono
            AUTORIZADOS_10.add(d[-10:])
        else:                                        # email / usuario de Telegram
            AUTORIZADOS_ID.add(s.lstrip("@"))


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


def remitente_dueno():
    """Número del dueño para la CONSOLA/MICRÓFONO LOCAL de la demo (corre en la máquina del
    dueño). No se usa en producción: el portero del cliente no manda remitente."""
    return TELEFONOS_DUENO[0]


# ===================================================================== CLAVE DE ADMIN
# Contraseña estilo Iron Man: sirve para DESTRABAR el modo administrador por UNA sola
# consulta, aun sin identificación (ej. por micrófono, que cualquiera puede usar). Al decir
# la frase con este código, ITHOS acepta la próxima pregunta como admin y después CIERRA
# la sesión (vuelve a usuario estándar). Frase de ejemplo:
#   "ITHOS, código de seguridad de acceso Kanerito4262, autorización de administrador."
# ⚠️ A futuro se suma IDENTIFICACIÓN POR VOZ: si sabe la clave pero NO es la voz del dueño,
# no la acepta.
CLAVE_ADMIN = "kanerito4262"
_RATIO_KANERITO = 0.68   # similitud mínima para aceptar una variante fonética de 'kanerito'

_RE_FRASE_ADMIN = re.compile(
    r"(ithos|ithos|c[oó]digo de seguridad|de acceso|autorizaci[oó]n de administrador|"
    r"autoridad( de)?|modo administrador|administrador|seguridad|acceso|kanerito\s*4262)",
    re.I)


def _norm_txt(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def detectar_clave_admin(texto):
    """True si el texto trae la CLAVE de administrador. Tolera espacios/mayúsculas y, para el
    MICRÓFONO, transcripciones imperfectas: acepta una variante fonética de 'kanerito' cuando
    la acompaña el número del código O la frase de seguridad ('código de seguridad de acceso'
    / 'autorización de administrador'). Así no falla si el audio pierde el número."""
    import difflib
    n = _norm_txt(texto)
    if CLAVE_ADMIN in n:                           # exacto: kanerito4262
        return True
    palabra = re.sub(r"[0-9]", "", CLAVE_ADMIN)    # 'kanerito'
    digitos = re.sub(r"[^0-9]", "", CLAVE_ADMIN)   # '4262'
    tiene_palabra = any(
        difflib.SequenceMatcher(None, w, palabra).ratio() >= _RATIO_KANERITO
        for w in re.findall(r"[a-zá-ú]+", (texto or "").lower()))
    if not tiene_palabra:
        return False
    tiene_digitos = bool(digitos) and digitos in n
    tiene_frase = any(k in n for k in ("seguridaddeacceso", "codigodeseguridad",
                                       "autorizacion", "administrador", "codigodeacceso"))
    return tiene_digitos or tiene_frase            # palabra-clave + (número O frase)


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
    palabra = re.sub(r"[0-9]", "", CLAVE_ADMIN)       # 'kanerito'
    digitos = re.sub(r"[^0-9]", "", CLAVE_ADMIN)      # '4262'
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


# ============================================================================ CONTEXTO
CONTEXTO_TECNICO = """CONOCIMIENTO TÉCNICO PROPIETARIO DE ITHOS (INTELLIHELP) — usalo
para explicar con precisión qué soporta el sistema, con qué versiones, qué permite cada
integración y sus límites, y cómo está programado.

# IA QUE USÁS AHORA (cadena real de este cliente) — RESPUESTA EXACTA si preguntan qué modelo/IA
# usás; NO inventes otra cosa: PRIMARIA = Gemini, modelo `gemini-2.5-flash-lite`. Si se agota su
# cuota, pasa SOLA a la SECUNDARIA = Cerebras, modelo `gpt-oss-120b`; y como TERCIARIA = Groq,
# modelo `llama-3.3-70b`. La VOZ es Charon (Gemini) o edge-tts (gratis). La config está en
# `central/clientes.json` (bloque "ia"), armada en `comun/ia.py` (clase MultiIA).
# NO existen 'Gemini 1.5 Flash', 'IA_PRINCIPAL', 'config.json' con esos nombres, 'MultiIA.call()'
# ni 'GEMINI_API_KEY' como variable de entorno: si no figura acá, no lo afirmes.

# SISTEMAS DE TICKETS (elegible por cliente; adaptador comun/tickets.py + tickets_otros.py)
- GLPI (nativo, 100% probado en INTELLIHELP): API REST por /apirest.php. Compatible GLPI
  9.4 → 10.x (la API REST existe desde 9.1). Permite: listar abiertos, estado, crear,
  responder (ITILFollowup), cerrar (status 6), reabrir, poner en espera, cambiar prioridad,
  asignar (Ticket_User), escalar, buscar; base de conocimiento desde ITILSolution o el
  último seguimiento; SLA por time_to_resolve. Requiere App-Token + User-Token.
- Zendesk: Support API v2 (vigente). Permite comentario público, estado (new/open/pending/
  hold/solved/closed), prioridad (low/normal/high/urgent), asignar por assignee_id, buscar,
  SLA por métricas. LÍMITE: "closed" lo pone Zendesk solo (nosotros dejamos "solved"); el
  SLA fino requiere el add-on de SLA.
- Jira: Jira Cloud REST v3. IMPORTANTE: el buscador viejo /rest/api/3/search fue REMOVIDO
  por Atlassian (oct-2025); usamos el nuevo POST /rest/api/3/search/jql (con nextPageToken
  y fields explícitos). Estados por TRANSICIONES (dependen del workflow del proyecto).
  Comentarios en ADF. SLA por Jira Service Management (/rest/servicedeskapi). LÍMITE: Jira
  Server/Data Center usan API v2 y username (no accountId); nuestra implementación apunta a
  Cloud.
- Freshservice: API v2. Estados 2=Abierto, 3=Pendiente, 4=Resuelto, 5=Cerrado; prioridad
  1=Baja..4=Urgente. Permite reply público, nota privada, estado, prioridad, asignar
  (responder_id), SLA por due_by. LÍMITE: crear pide el email del solicitante; la búsqueda
  libre es del lado del cliente.
- osTicket: compatible 1.14 → 1.18. Su API OFICIAL SOLO CREA tickets (header X-API-Key).
  Leer/cerrar/responder NO tienen API oficial: requieren acceso a la base MySQL (se activa
  con db_host/db_user/db_pwd/db_name y PyMySQL). LÍMITE: sin DB, solo alta de tickets.

# CONTROL DE ACCESO (elegible por cliente; agente/integrador_*.py + comun/acceso.py)
- IVMS (el nuestro; IVMS-4200 con base SQL Server de fichajes): NO tiene API; leemos la
  tabla `fichajes` por ODBC. Permite el portero por voz en cada fichaje. NO hace control de
  horario/franjas, por eso NO genera anomalías.
- HikCentral Professional: OpenAPI (gateway Artemis), firma HMAC-SHA256. Compatible v2.4 →
  v2.6.1+ (el endpoint de eventos puede variar por versión). Permite el portero (door/events
  con ventana startTime/endTime y paginación) y detectar denegación por franja horaria
  (anomalías). Requiere AppKey + AppSecret de partner.
- BioStar 2 (Suprema): New Local API v2.x (probado hasta 2.9.6). Login → cabecera
  bs-session-id. Permite eventos (/api/events/search) y horarios (/api/schedules) para
  anomalías; hay una TA API aparte para asistencia. LÍMITE: la sesión expira (1h por defecto).
- ZKTeco: DOS plataformas. ZKBio CVSecurity (acceso): auth Token, /acc/api/transactions/.
  BioTime 8.5 (asistencia): auth JWT (/jwt-api-token-auth/), /iclock/api/transactions/.
  Permiten portero + anomalías por "invalid time zone".
- Honeywell Pro-Watch: API Service (REST puerto 8734, Basic auth con un usuario que tenga
  la "Web password"). Compatible Pro-Watch 4.5 → 6.5.x. Permite eventos y cardholders;
  anomalías por descripción "time zone/denied". LÍMITE: la API varía por versión/on-prem.

# QUÉ HACE ITHOS (TODO por cliente, aislado; una empresa nunca ve la de otra)
Portero por voz. Mesa de ayuda con IA (triage: LEE el ticket completo —descripción +
seguimientos—, clasifica, prioriza, fija SLA, asigna y responde; ciclo completo hasta que el
cliente confirma). Acciones del agente: leer_ticket, categorizar, asignar_sla, cambiar
prioridad, poner en espera, escalar, asignar, responder, cerrar, reabrir, crear, buscar (SIN
alta de usuarios, a propósito). Puede ejecutar VARIAS acciones en un mismo pedido (el
"circuito completo" de un ticket de una sola vez). Base de conocimiento automática por cliente desde los casos resueltos. Proactivo:
avisa SLA por vencer. Anomalías de horario (HikCentral/BioStar2/ZKTeco/Honeywell; OFF por
defecto; IVMS no aplica). Reportes diario/semanal/mensual. Avisos por WhatsApp/Telegram/
Email/Teams/Slack — y CONVERSA por todos esos canales, no solo avisa. MULTI-IDIOMA: cada
cliente elige su idioma y ITHOS interpreta/responde en ese idioma (todos los idiomas).
PERSONALIDAD estilo ITHOS de Iron Man (inteligente, cálido, humor seco y sutil).
Memoria por cliente. Facturación SaaS con MercadoPago: precio en USD que se cobra en pesos al
dólar oficial del BNA; INTELLIHELP es dueño y NO se cobra.

# CÓMO ESTÁ PROGRAMADO
- Multi-tenant (multi-cliente). `central/` = cerebro (FastAPI + WebSocket, valida API key,
  registro en clientes.json). `agente/` = corre en el sitio del cliente e integra el control
  de acceso. `comun/` = módulos compartidos por ambos.
- IA enchufable (comun/ia.py): Gemini, Claude, ChatGPT, Grok, Groq (gratis) o local (Ollama),
  con MultiIA que hace FALLBACK automático al agotarse la cuota (falla rápido en 429). Voz
  Charon (Gemini) con respaldo GRATIS edge-tts (es-MX-JorgeNeural, grave/pausada, x1.25) y
  Windows SAPI como último recurso; diccionario de pronunciación en comun/locucion.py.
- TRANSCRIPCIÓN (voz->texto) multi-idioma en comun/ia.py: Whisper large-v3 (Groq, gratis) o
  Gemini, con idioma del cliente + vocabulario del dominio => alta precisión, cualquier idioma.
- Captura de micrófono PROFESIONAL (comun/audio.py): grabación DINÁMICA por detección de
  silencio (no duración fija) + FILTRO DE VOZ HUMANA en 3 niveles: Silero VAD v5 por ONNX
  (red neuronal, offline, sin torch, modelo comun/silero_vad.onnx) → webrtcvad → energía.
  Descarta ruido de ambiente/música/tono/tecleo y transcribe SOLO lo que dijo una persona (si
  no hay voz, no transcribe: ITHOS nunca inventa). Usado por la demo (conversación CONTINUA)
  y por agente/escucha.py (tras la palabra clave).
- IDENTIFICACIÓN POR VOZ del dueño (comun/vozid.py, ACTIVA): cada audio del dueño por WhatsApp
  (de su número) suma una muestra de su voz (solo-voz, filtrada por VAD) en ~/.ithos/voz_dueno/.
  La HUELLA DE VOZ es un voiceprint MFCC en numpy puro (MFCC 13 sin c0 + delta, resumido con
  media+desvío = 48 valores) — SIN torch ni modelos pesados. El PERFIL es el promedio de las
  muestras y se RE-ENTRENA solo con cada audio nuevo (mejora con el uso). verificar() compara
  por coseno NORMALIZADO por una COHORTE de voces distintas (T-norm, comun/voz_cohorte.npy):
  mide cuánto MÁS se parece a la voz del dueño que a un panel de otras voces. Calibrado con la
  voz real del dueño (z≈3–6) vs 14 voces distintas (z<0) => umbral 1.0 con margen amplio.
  Objetivo: el modo admin del MICRÓFONO (sin identidad) exige clave + voz coincidente; en
  WhatsApp/Telegram la identidad ya es el número. Si aún no hay perfil, verificar() no bloquea.
- Adaptadores GENÉRICOS: comun/tickets.py (tickets) y comun/acceso.py (acceso). Todo lo que
  hace ITHOS habla con estos adaptadores, por eso funciona igual en cualquier sistema.
- Asistente-agente (comun/conversacion.py): SIEMPRE carga el panorama real (tickets + SLA)
  antes de responder, ejecuta acciones, usa la KB (central/kb_auto.py) y la memoria
  (comun/memoria.py), todo por cliente. Loop JSON {accion, args, recordar, respuesta}.
  REGLA: NUNCA ejecuta acciones de escritura (crear/cerrar/etc.) salvo pedido EXPLÍCITO y
  claro; ante la duda no actúa (no crea tickets de una frase que no lo pide).
- CANALES conversacionales (comun/canales.py): además de WhatsApp, ITHOS escucha y responde
  en Telegram (Bot API), Email (IMAP/SMTP) y WhatsApp oficial (webhook /webhook/whatsapp).
  Misma mención, mismo remitente, mismo gateo. Vale para los DOS modos de WhatsApp.
- ACTIVACIÓN / WAKE-WORD (comun/wake.py, ÚNICA fuente de verdad del texto y del micrófono): hay
  que LLAMARLO — "Hey ITHOS, ..." (también "oye/ok/hola/che ithos"), en español o inglés, may/min,
  con tildes o puntuación. NOMBRARLO SUELTO NO ACTIVA: "ITHOS, ..." o "preguntale a ITHOS" se
  ignoran, para no intervenir cuando el grupo simplemente lo menciona. Tolera que Vosk PARTA la
  palabra ("hey it hos"), la pegue ("heyithos") o la transcriba con pronunciación inglesa
  ("hey ethos"). Vale igual en WhatsApp, Telegram, Email, Matrix, Planka y micrófono.
- @MENCIÓN AL TÉCNICO ASIGNADO: los avisos de un ticket y la alerta de SLA en riesgo/vencido
  @mencionan SOLO al asignado, por su teléfono del bloque `tecnicos` del cliente (mapeo por id
  de GLPI, id/login/email o nombre según el sistema de tickets). La alerta de SLA va agrupada
  por técnico; los canales sin menciones reciben el mismo aviso con el nombre del asignado.
- ESPERA POR EL CLIENTE (central/triage.py) en sus DOS casos: falta un DATO que le pedimos en la 1ª
  respuesta, o tiene que CONFIRMAR/coordinar algo. Mientras el ticket está En espera por eso, ITHOS
  recuerda UNA vez por DÍA HÁBIL, siempre DENTRO del horario de atención (Lun-Vie 09-18, zona del
  cliente) y a la misma hora; si el cliente responde, vuelve a En curso solo; a los 5 días hábiles
  sin respuesta avisa al TÉCNICO ASIGNADO (nota interna privada + WhatsApp @mención). Un ticket
  POSPUESTO (reactivación agendada) no recibe recordatorios ni escalada. Misma cadencia para el
  recordatorio de confirmación de un ticket RESUELTO.
- CONOCIMIENTO PROPIETARIO + autorización (comun/conocimiento.py): este contexto solo se
  revela al DUEÑO, identificado por sus 2 números (o email/usuario), SOLO por identidad
  (nunca por canal ni IsFromMe; un cliente con su propia sesión nunca es dueño). Para el
  micrófono (sin identidad) hay una CLAVE de admin (CLAVE_ADMIN) que destraba UNA consulta
  (one-shot) y tolera transcripciones imperfectas; a futuro se suma identificación por voz.
- Proactivo central/proactivo.py; anomalías central/anomalias.py; reportes programados
  central/reportes_programados.py; facturación comun/facturacion.py (dólar BNA vía
  dolarapi/bluelytics, suscripción preapproval de MercadoPago).
- WhatsApp (comun/whatsapp.py, neonize): responde SOLO en el grupo configurado, únicamente
  si lo mencionan ("ITHOS"), por texto y por audio (transcribe y valida la mención); NUNCA
  escribe a contactos ni sube estados; ignora el historial viejo. Detecta el número real del
  remitente aunque WhatsApp use LID (lo saca de SenderAlt; respaldo por dueño de la sesión).
- Persistencia estable en ~/.ithos (sesión de WhatsApp, memoria, KB): portable, no vuelve a
  pedir QR al mover la carpeta. Todo con rutas relativas (nada absoluto).
- La DEMO (iniciar_demo.py) y PRODUCCIÓN (central/main.py) usan los MISMOS módulos: misma
  funcionalidad. La demo es efímera (muere al detenerla).

# HISTORIAL DE CAMBIOS (lo que se fue construyendo; se mantiene al día con cada cambio)
1. Base multi-tenant: central FastAPI + WebSocket + agentes por cliente (registro por API key
   en clientes.json). Portero por voz (IVMS, SQL de fichajes) y mesa de ayuda GLPI con triage.
2. Panel HUD superadmin: todo elegible por cliente (sistema de tickets, canales, sistema de
   acceso, proveedor de IA con multi-IA y fallback automático).
3. Capa de IA enchufable + voz Charon con respaldo GRATIS edge-tts (es-MX-JorgeNeural) y SAPI.
4. Seguridad WhatsApp: responde SOLO en el grupo configurado, solo si lo mencionan, nunca a
   contactos ni estados, ignora el historial viejo (se corrigió un incidente de backlog).
5. Agente que EJECUTA con panorama real siempre cargado + memoria por cliente + KB automática
   por cliente (casos resueltos). Reportes proactivos (diario/semanal/mensual).
6. Facturación SaaS MercadoPago: precio USD cobrado en pesos al dólar BNA; INTELLIHELP dueño
   (no se cobra). Copia local portátil (Pictures) que se sincroniza a la red.
7. MULTI-SISTEMA real por API oficial vigente: adaptadores genéricos comun/tickets.py
   (GLPI/Zendesk/Jira/Freshservice/osTicket) y comun/acceso.py (IVMS/HikCentral/BioStar2/
   ZKTeco/Honeywell). Jira migrado al nuevo /rest/api/3/search/jql. Más acciones del agente
   (prioridad, en espera, escalar, buscar) SIN alta de usuarios. Proactivo de SLA y anomalías
   de horario (OFF por defecto; HikCentral/BioStar2/ZKTeco/Honeywell por API; IVMS no aplica).
8. CONOCIMIENTO PROPIETARIO + autorización por identidad (2 números del dueño), en TODOS los
   canales; CLAVE de admin (one-shot, se cierra al responder una consulta técnica) para el
   micrófono; se ignora el historial de negativas en modo admin.
9. Conversación en TODOS los canales (comun/canales.py): Telegram, Email, WhatsApp oficial
   (webhook) además del no-oficial.
10. VOZ profesional: transcripción multi-idioma (Whisper large-v3 / Gemini, idioma del cliente
    + vocabulario), grabación DINÁMICA por silencio, y FILTRO DE VOZ HUMANA (Silero VAD v5 por
    ONNX, con webrtcvad de respaldo) para no transcribir ruido. Persona estilo ITHOS
11. IDENTIFICACIÓN POR VOZ del dueño (comun/vozid.py, ACTIVA): voiceprint MFCC en numpy puro
    (sin torch/modelos pesados) + verificación por T-norm contra una cohorte de voces
    (comun/voz_cohorte.npy). El perfil se RE-ENTRENA solo con cada audio nuevo. Calibrado con la
    voz real del dueño (z≈3–6) vs otras voces (z<0): umbral 1.0. Refuerza el modo admin del
    micrófono (clave + voz). Empezó con las muestras ya juntadas y mejora con el uso.
12. AUTOCONOCIMIENTO del código (comun/codebase.py): en modo admin, ITHOS puede LEER el código
    fuente real de cualquier archivo y explicarlo función por función, y conoce el índice
    completo del proyecto (siempre al día, porque lo lee en el momento). La respuesta técnica
    del dueño usa una ruta directa (sin JSON) para poder ser exhaustiva y muy larga.
13. VOZ que se lee natural (comun/locucion.py): limpia rutas/símbolos técnicos para no
    deletrear 'barra diagonal', 'punto pe i', etc. Cacheo de cuota de la IA primaria (no la
    reconsulta hasta que se reactive). Palabra clave 'ITHOS' también en el micrófono.
14. RESPUESTAS INSTANTÁNEAS: streaming del modelo (comun/ia.py chat_stream) + voz en PIPELINE
    por frases -> ITHOS empieza a hablar en ~1-2s aunque la respuesta sea muy larga.
15. RESPUESTA por TEXTO / AUDIO / AMBOS, elegible por el cliente (config 'respuesta' por canal),
    tanto en las respuestas conversacionales como en los AVISOS, en todos los canales que pueden
    mandar voz: WhatsApp no-oficial (neonize send_audio) y oficial (Cloud API: sube media con
    POST /media y manda type=audio) y Telegram (sendVoice OGG/opus; sendAudio MP3 si no hay ffmpeg;
    default 'texto'). Teams/Slack/Email/Matrix son de solo texto en los avisos. Regresión: audit5
    H8 (WA no-oficial), H10 (WA oficial), H13 (Telegram). La NOTA DE VOZ (comun/voz_tts.py) usa la MISMA cadena que la voz
    local: Charon (Gemini) primero si hay cuota, si no edge-tts; convierte a OGG/opus con ffmpeg.
    Optimizado: el TEXTO se manda primero (instantáneo) y la nota de voz después. Por WhatsApp
    la respuesta va A WhatsApp (texto y/o audio, según config) — NO por los parlantes locales.
    En la sesión no-oficial (número del dueño) se detecta
    el ECO de la propia nota de voz de ITHOS (comun/whatsapp.py _parecido) para no responderse
    en loop ni ensuciar el entrenamiento de voz con la voz de la IA.
16. CUOTA DE IA con datos REALES (comun/cuota.py, multi-motor): distingue el 429 por MINUTO
    (rate-limit transitorio, se recupera en segundos -> NO es 'sin cuota', se cae al respaldo un
    ratito) del 429 por DÍA (cuota diaria agotada). PRIMARIA (Gemini free): no expone 'cuánto
    queda' por header, así que se CUENTA localmente contra el límite diario (RPD ~250; reinicia a
    medianoche del Pacífico). SECUNDARIA (Groq free): usa los HEADERS REALES que Groq manda en
    cada respuesta (x-ratelimit-remaining-requests = cuántas quedan; x-ratelimit-reset-requests =
    cuánto falta) -> dato exacto. AVISA (texto corto, para gastar poco) cuando queda poca cuota
    en CUALQUIERA de las dos ('te quedan N consultas en Gemini/Groq'); al AGOTARSE manda el
    ESTADO COMPLETO de cada una con su FECHA y HORA REAL de reinicio en la zona del cliente. El
    aviso sale por el canal elegido (WhatsApp/Telegram/…) y por los parlantes (voz). ITHOS NO
    crashea nunca y funciona aun sin ninguna IA (voz por edge). El gestor es COMPARTIDO por
    triage + asistente, en demo y producción (cuota.crear_gestor). AVISO PROACTIVO de INICIO:
    apenas arranca, ITHOS saluda solo por los canales (conversacion.mensaje_inicio). NOTA DE
    VOZ: Charon (Gemini) para respuestas cortas, edge para largas; texto primero, audio después.
17. INTELIGENCIA OPERATIVA (crítico): (a) el modo TÉCNICO (que solo explica arquitectura) se
    dispara SOLO ante preguntas sobre ITHOS mismo (cómo está programado, versiones, módulos,
    código); un pedido OPERATIVO ('ponelo en espera y hacé el circuito') va al AGENTE que
    EJECUTA — antes se confundía y volcaba la arquitectura sin hacer nada (conocimiento.
    es_consulta_tecnica ahora estricto + guardia operativa). (b) LEE el ticket completo por API
    (descripción + seguimientos + categoría/prioridad/SLA) y lo analiza; ya no dice 'no tengo
    acceso' (tickets._GLPI.detalle, acción leer_ticket, auto-carga al mencionar un #). (c)
    Ejecuta VARIAS acciones en un turno (plan 'acciones':[...]) para el circuito completo:
    categorizar_ticket → cambiar_prioridad → asignar_sla → asignar_ticket → responder_ticket →
    poner_en_espera. (d) asignar_sla fija las fechas límite TTO/TTR según prioridad. (e) la
    respuesta técnica va AL GRANO (responde lo preguntado); solo vuelca todo si piden 'completo/
    listado/todo'. (f) la nota de voz resume las respuestas largas (no lee 4000 palabras).
18. AGENTE REAL SOBRE GLPI (crítico, verificado en vivo): (a) NORMALIZA el id ('#597' → '597'):
    antes el '#' en la URL pegaba a '/Ticket/' y la escritura se perdía en silencio (nada se
    aplicaba). (b) CATEGORÍA: el token de ITHOS no puede listar categorías (403), así que se
    leen con el glpi_user_token y se elige la de la ENTIDAD del ticket (TERMINALES existe con
    distinto id por entidad). (c) 'aplicar_ciclo' = el MISMO ciclo de la demo en UNA acción:
    categoría + urgencia/impacto/prioridad + SLA y OLA por definición (llena TTO/TTR EXTERNO e
    INTERNO) + asigna a ITHOS(28) y al técnico + 1ª respuesta + estado. (d) LEE e INTERPRETA el
    ticket completo ANTES de responder y NUNCA pide un dato que ya está (p. ej. el legajo en la
    descripción); carga el contenido aunque no pongan el número (por 'el ticket' / abiertos).
    (e) PERMISOS por API (tickets._GLPI.permisos vía getActiveProfile): ITHOS sabe y dice qué
    puede/NO puede, y actúa solo donde tiene permiso; interfaz genérica para Jira/Zendesk. (f)
    'tickets_sin_procesar' detecta tickets SUELTOS (cualquier estado, sin categoría/SLA) que
    necesitan el ciclo. (g) CUOTA: MultiIA prueba las DOS IA antes de declarar 'sin cuota' (no
    más falsos 'sin cuota'); el prompt técnico se recortó para no quemar el límite diario de
    tokens de Groq (TPD).
19. POSPONER INTELIGENTE (comun/agenda.py): 'dejámelo pendiente hasta el lunes a la tarde' ->
    lo deja EN ESPERA y lo REACTIVA solo (EN CURSO) cuando llega ese día/hora. Interpreta
    fecha/hora en la zona del cliente ('a la tarde'=13:00, 'a la mañana'=09:00, mediodía=12:00,
    'a la noche'=20:00, u hora explícita); si NO queda clara la hora, la PIDE (no agenda a
    ciegas). Persistente (~/.ithos/agenda.json) y con reactivador en hilo (demo y producción,
    agenda.iniciar_reactivador); al reactivar avisa por el canal. Acción: posponer_ticket.
20. REPORTES ITIL 4 (comun/reportes_itil.py): informes profesionales por período (diario/
    semanal/mensual) con KPIs REALES (solo lo medible, nada estimado): volumen (creados/
    resueltos/cerrados/backlog), cumplimiento de SLA de resolución (TTR) y 1ª respuesta (TTO),
    MTTR, aging del backlog, y desglose por PRIORIDAD, CATEGORÍA, TÉCNICO, ESTADO y SECTOR
    (entidad). Salidas: texto (por canal), CSV y PDF con diseño (reportlab). Portal: pestaña
    Métricas con KPIs + descarga CSV/PDF (/api/reporte_itil/{key}[/csv|/pdf]?periodo=), tanto en
    el panel superadmin como en el PORTAL DEL CLIENTE: cualquiera puede sacar a mano el reporte
    diario/semanal/mensual y descargarlo, tenga o no configurado el envío automático. Agente:
    herramienta reporte_itil (pedirlo por voz/chat). Programados: se mandan solos con la
    frecuencia/hora/formato que el cliente elige, por su canal, con adjunto (reportes_programados.
    enviar_reporte). Envío de documentos por WhatsApp (neonize), Telegram y Email (adjunto).
21. AUDITORÍA / ROBUSTEZ (revisión de todo el proyecto): (a) SESIONES GLPI: se cierran siempre
    (context manager en glpi.GLPIClient) y el reporte ITIL usa 2 sesiones en vez de ~300 (abría
    una por técnico) — no se agotan las sesiones. (b) GLPIClient reintenta ante errores
    TRANSITORIOS (5xx / red / timeout), no ante 4xx. (c) NORMALIZACIÓN de id en TODOS los
    sistemas (no solo GLPI): saca el '#' que rompía la URL y respeta las claves de Jira
    (conversacion._id_ticket, aplicado en el bucle de acciones). (d) SELECCIÓN DE MODELO por
    plan (ia.elegir_modelo): en GRATIS usa el de MÁS límite/velocidad (Gemini flash-lite: 1000
    req/día vs 250; Groq 70b estable para el JSON) compensado con prompts profesionales; en PAGO
    (key propia/ilimitada) el más CAPAZ. Config 'modelo_texto':'auto' lo elige solo.
22. SELECCIÓN DE MODELO para TODOS los proveedores con API (ia._MODELOS + elegir_modelo):
    Gemini, Groq, Mistral, Cohere, OpenRouter, DeepSeek, Ollama local, OpenAI, Claude, Grok.
    GRATIS = el de MÁS cuota/velocidad; PAGO = el más capaz pero COST-EFFECTIVE (NO el flagship
    carísimo: Gemini flash no pro, OpenAI gpt-4o-mini no gpt-4o, Claude sonnet no opus). Se
    agregaron proveedores OpenRouter (una API → casi todos los modelos del mundo, con ':free')
    y Mistral (tier gratis). LEER TICKET universal: 'detalle' (leer_ticket) ahora anda en GLPI,
    Zendesk, Freshservice, Jira y osTicket (por su DB); permisos por sistema también. La voz-id
    entrena en la demo del dueño y ya queda lista para producción (perfil persistente).
23. DETECCIÓN AUTOMÁTICA de plan (ia.detectar_plan): con 'modelo_texto':'auto' (el DEFAULT de
    todos), ITHOS decide SOLO si la API es PAGA o GRATIS y elige el modelo — el cliente NO
    tiene que saber ni seleccionar nada. Sin gastar tokens cuando se puede: OpenRouter se
    consulta por /auth/key (is_free_tier); OpenAI/Claude/Grok/DeepSeek no tienen tier gratis
    (pago); si el modelo free y pago son el mismo (Groq), no detecta; lo no detectable barato
    (Gemini/Mistral/Cohere/local) asume GRATIS y usa el modelo eficiente (gasta lo mínimo, anda
    igual en free o pago). Cachea 24 h (~/.ithos/planes_ia.json). Se detecta POR PROVEEDOR: la
    secundaria ya NO hereda el 'pago' de la primaria (se juzga por su propia key). El check
    'Forzar plan pago' del panel es un override opcional; por defecto es todo automático.
24. FIXES + KB: (a) PDF del reporte ITIL con diseño PROFESIONAL (se arregló la superposición
    valor/etiqueta por el leading). (b) MENCIÓN de 'ITHOS' DIFUSA en WhatsApp/Telegram
    (whatsapp.menciona): tolera 'yarvis/jervis/harvis' de la mala transcripción — antes al 3er
    audio a veces no contestaba nada porque no matcheaba exacto. (c) VELOCIDAD: caché corto de
    la lista de tickets (glpi.tickets_cache) -> el SLA y los reportes repetidos son instantáneos.
    (d) BASE DE CONOCIMIENTO: se pueden subir MUCHOS archivos juntos (PDF/Word/TXT/DOCX) desde el
    portal del cliente y el panel (kb_auto.subir_archivos, endpoint /api/kb_subir); ITHOS
    extrae el texto (pypdf) y lo combina con lo aprendido de los tickets. La KB se regenera sola
    (umbral 2 h, o forzada tras resolver). El portal y el panel tienen la sección 'Base de
    conocimiento' (subir + regenerar).
25. SESIONES GLPI PERSISTENTES (pool) + TOKENS POR ROL: glpi.sesion() mantiene UNA sesión VIVA
    por token/rol y la REUSA siempre (no abre/cierra en cada llamada -> rápido, no agota); si
    expira (401) se REABRE sola. Roles (como los pasó Brian): SUPER ADMIN (glpi_user_token —
    acceso total: leer categorías/usuarios, borrar), ITHOS (glpi_ithos_token — el agente, clon
    del helpdesk, escribe), HELPDESK (glpi_bsierra_token — el técnico que resuelve), CLIENTE
    (glpi_test_token — crea/responde). El adaptador usa el token correcto por operación (p. ej.
    la categoría del ticket la lee el super admin, así 'detalle' ya muestra la categoría real).
    Las pruebas del ciclo usan CADA rol con su token (cliente crea, bsierra resuelve, admin
    purga). Formulario GLPI del panel pide los 4 tokens con su rol; otros sistemas piden lo que
    ese sistema necesita.
26. TICKET EN FOCO + INTELIGENCIA MULTI-TICKET: si el usuario dice 'este ticket ponelo en
    espera' SIN el número, la acción usa el ticket en contexto (antes el modelo a veces omitía
    el id y no se aplicaba). Si hay VARIOS abiertos y lo nombra por ASUNTO ('el de la licencia',
    'el del molinete'), ITHOS identifica cuál por el asunto (conversacion._ticket_por_asunto,
    sin costo extra); si es ambiguo, lista los abiertos y pregunta. El posponer y el reactivador
    viven en comun/ -> IDÉNTICOS en demo y producción. La nota de voz OGG/opus genera un warning
    benigno de neonize ('format.tags None', propio del contenedor) pero el audio se manda igual.
    Tope de muestras de voz (25) para que el perfil no derive.
27. PROMPTS nivel élite (Opus) con MÍNIMOS tokens: se agregó un NÚCLEO 'MENTE' compacto al
    alcance (se usa en cada mensaje): captar la INTENCIÓN real (aunque venga mal transcripto),
    razonar sobre la EVIDENCIA concreta, no inventar/suponer, distinguir lo que se SABE de lo que
    se infiere, pedir/preguntar ante la duda, ser exacto con números/nombres/estados, máxima
    densidad de valor por palabra. Se quitaron repeticiones dispersas (neutro/menos tokens, más
    filoso). Triage (cerebro) clasifica por EVIDENCIA, y la detección de confirmación interpreta
    la intención real. Auditoría del proyecto: 12/12 OK (registro, IA, cuota, canales, GLPI+SLA,
    IVMS, métricas, KB, portero, triage, conversación, ciclo).
28. CUOTA — ESTADO REAL (verificado con la API oficial de Groq): Groq da headers reales
    (remaining-requests / tokens) PERO su límite de TOKENS POR DÍA (TPD, 100k para 70b) NO viene
    en los headers; al 429 por TPD ahora se marca 'Groq agotada' en el gestor (antes el mensaje
    decía 'sin cuota' y a la vez 'Groq disponible' — contradictorio). MultiIA marca por motor
    cuál se agotó (gestor) y, si el último error es por-MINUTO/alta demanda (no diario),
    REINTENTA la secundaria una vez tras una pausa corta (se recupera en segundos) en vez de
    declarar 'sin cuota'. El 8b-instant NO sirve para el agente (413 'request too large': su TPM
    es 6000 y el contexto lo supera) -> secundaria free = 70b (TPM 12000). La cuota que se ve
    'agotada' en pruebas es por los prompts grandes del testing; en uso normal casi no se toca.
29. NOTA DE VOZ por WhatsApp/canales = EDGE (100% GRATIS) directo: antes intentaba Charon
    (Gemini) y, si estaba agotado, reintentaba ~40s y la nota llegaba tardísimo o nunca. Ahora
    edge genera en ~2-3s y siempre anda (comun/whatsapp.py y canales.py). La voz de la IA sigue
    SIN entrenar el perfil (filtro de eco). GROQ 413 'request too large' arreglado: se capa
    max_tokens del JSON del agente (1500) para no pasar el TPM. CEREBRAS agregado como proveedor
    (ia.CerebrasIA): el FREE con límites MÁS ALTOS — ~1.000.000 tokens/día y ~30.000 TPM (10x/2.5x
    Groq), 30 RPM, Llama 3.3 70B (muy capaz) y ultrarrápido; key gratis sin tarjeta en
    cloud.cerebras.ai. Verificado con doc oficial 2026 (ningún free tier es 100% sin límite por
    minuto, pero Cerebras es el que más margen da). Elegible en el panel.
30. CEREBRAS integrado y verificado con la key real por API: modelos gpt-oss-120b / zai-glm-4.7 /
    gemma-4-31b; se usa gpt-oss-120b (120B, muy capaz) — circuito completo OK, consulta simple
    ~0.5s. Límites reales: 1.000.000 tokens/día, 30.000 TPM, 2400 req/día. La clase usa User-Agent
    de navegador (Cloudflare bloquea el UA de Python) y 'max_completion_tokens' (no 'max_tokens').
    La lógica elegir_modelo + detectar_plan (más capaz gratis / capaz cost-effective si es pago,
    detectado por la key) vale para TODOS los proveedores. El JSON del agente capea tokens (2000).
31. IDENTIDAD DE IA de INTELLIHELP = CADENA DE 3 (respaldo automático en orden): Gemini PRIMARIA
    (identidad/voz Charon; con plan PAGO de Google queda de primaria todo el día con el modelo
    capaz) -> Cerebras SECUNDARIA (el free con más margen, 1M/día) -> Groq TERCIARIA. MultiIA ahora
    encadena N proveedores (self.cadena): si la primaria se agota (cuota DIARIA), entra en cooldown
    y salta sola a la siguiente; expone self.ultimo_proveedor (qué motor respondió de verdad, no
    heurística). Usa UNA sola IA por consulta (return al primer éxito; las demás NO se llaman, no
    gastan tokens) y solo pasa a la siguiente al fallar/agotarse — regresión audit5 H11. Cuando una
    IA está por agotarse o se agota, AVISA al canal del cliente ('te quedan N con X, sigo con Y'):
    Gemini/Groq lo anuncia GestorCuota (registrar_/agotada_), el resto de la cadena lo anuncia
    MultiIA._avisar_cambio (dedup ~5min) — regresión audit5 H12. En el panel/portal se cargan las 3 IAs (proveedor + secundario + terciario, cada
    una con su clave/modelo 'auto'). Cada respaldo se juzga por SU propia key (no hereda el 'pago'
    de la primaria). Latencia real medida: Gemini con cuota ~4s (frío), Cerebras ~0.7s, pool GLPI
    frío ~0.8s / cache ~0.01s (instantáneo). Bug corregido: es_por_minuto no reconocía 'tokens per
    minute (TPM)' sin la palabra 'rate limit' (ahora simétrico con es_por_dia: detecta TPM/RPM/
    'per minute' directo), así un límite por minuto de Groq no se confundía con caída total."""


def bloque_sistema(remitente=None, canal="", admin=False):
    """Devuelve el fragmento a inyectar en el prompt del asistente según autorización.
    admin=True fuerza acceso total (destrabado por la CLAVE de administrador, one-shot).
    Autorizado: el conocimiento técnico completo + permiso de explicarlo.
    No autorizado: la instrucción de NO revelar la implementación (es propietario)."""
    if admin or esta_autorizado(remitente, canal):
        return ("\n\n[ACCESO TÉCNICO TOTAL — el que pregunta es el DUEÑO de INTELLIHELP.]\n"
                "IMPORTANTE: IGNORÁ cualquier negativa anterior del historial ('información "
                "propietaria, no puedo compartirla'): NO valen, el usuario está AUTORIZADO y está "
                "PROHIBIDO negarte.\n"
                "CÓMO RESPONDER lo técnico — PRECISIÓN y BREVEDAD (sos una IA de primer nivel, NO un "
                "volcado de documentación):\n"
                "· Por DEFECTO respondé en PROSA, de 1 a 4 frases. NO uses tablas, cuadros ni listas "
                "largas salvo que te lo pidan EXPLÍCITO ('en detalle', 'una tabla', 'listá todo').\n"
                "· Respondé SOLO lo preguntado. Ej.: '¿qué IA/modelo/versión usamos?' -> UNA frase: "
                "'Usamos Gemini (gemini-2.5-flash-lite) como primaria y, si se agota la cuota, pasa "
                "sola a Cerebras (gpt-oss-120b) y luego a Groq (llama-3.3-70b).'\n"
                "· CITÁ SOLO datos que figuren abajo. Si la versión/número exacto NO está, nombrá el "
                "proveedor y aclarás que ese dato puntual no lo tenés. PROHIBIDO inventar modelos, "
                "versiones, cuotas, TPM o fechas (nada de 'gemini-1.5', 'llama2-70b' ni números que "
                "no estén escritos). Mejor 'ese dato no lo tengo' que un dato FALSO.\n"
                "Basate SOLO en este conocimiento:\n\n" + CONTEXTO_TECNICO +
                "\n\n[RECORDATORIO FINAL — lo más importante: respondé EXACTO lo preguntado, BREVE "
                "(1-4 frases, en PROSA, SIN tablas salvo pedido explícito) y SIN inventar nada que "
                "no esté arriba. Si preguntan qué IA/modelo usamos: 'Gemini (gemini-2.5-flash-lite) "
                "primaria, y de respaldo Cerebras (gpt-oss-120b) y Groq (llama-3.3-70b).']")
    return ("\n\n[INFORMACIÓN PROPIETARIA PROTEGIDA.]\n"
            "Si te preguntan CÓMO ESTÁ PROGRAMADO el sistema, su arquitectura, qué versiones "
            "de software soporta, detalles técnicos internos o de implementación, NO los des. "
            "Respondé, con amabilidad, que es información propietaria de INTELLIHELP y no "
            "podés compartirla. El soporte normal (tickets, estados, SLA, portero) SÍ "
            "respondelo con normalidad. Texto sugerido para negarte: \"" + MENSAJE_RESTRINGIDO + "\"")
