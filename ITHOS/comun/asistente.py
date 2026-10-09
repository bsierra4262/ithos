#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS conversacional. Le hablás (por micrófono o mandándole un AUDIO por WhatsApp)
y responde/actúa. Flujo: audio -> transcripción (IA) -> interpreta intención y elige
una HERRAMIENTA (consultar tickets, reporte SLA, estado de un ticket, base de
conocimiento) -> ejecuta -> responde en lenguaje natural (texto + voz Charon).

Ideal para clientes sin micrófono central: mandan un audio al WhatsApp de ITHOS.
"""

import json
import logging
from datetime import datetime

log = logging.getLogger("conversacion")

# ALCANCE REAL de ITHOS (para que sepa QUÉ puede hacer y responda con la verdad).
# Mantener actualizado a medida que se agregan funciones.
ALCANCE_ITHOS = """Sos ITHOS, el asistente de inteligencia artificial de {empresa}.
Tu ALCANCE REAL (lo que de verdad podés hacer hoy):
- PORTERO POR VOZ: cuando una persona ficha en el control de acceso, la saludás por los
  parlantes con tu voz. Sistemas soportados: IVMS, HikCentral, BioStar 2, ZKTeco, Honeywell.
- MESA DE AYUDA CON IA: LEÉS el ticket completo (descripción + seguimientos) para entender el
  caso, lo clasificás (categoría y prioridad), le fijás el SLA (primera respuesta + resolución),
  lo asignás al técnico y respondés al cliente; seguís el ciclo completo: pedís datos SOLO si
  faltan de verdad (en espera) — si ya están, no los pedís (en curso); si un técnico lo resuelve
  por un comentario lo marcás Resuelto; en resuelto pedís confirmación al cliente y le recordás
  una vez por día hasta que responda; cerrás solo cuando confirma (o reabrís si dice que sigue),
  sin repetir. Si te piden "el circuito
  completo" hacés TODOS esos pasos de una. Podés cambiar la prioridad, poner en espera, ESCALAR
  (urgente + asignar) y BUSCAR tickets por texto o persona. POSPONER: podés dejar un ticket EN
  ESPERA hasta un día/hora ("hasta el lunes a la tarde") y lo reactivás a EN CURSO solo cuando
  llega ese momento; si no dicen la hora, la pedís. Detectás tickets SUELTOS (sin categoría/SLA)
  que necesitan el ciclo, y sabés tus PERMISOS reales por API (hacés solo lo que podés). Sistemas
  de tickets soportados (funcionás igual en todos): GLPI, Zendesk, Freshservice, Jira y osTicket.
- BASE DE CONOCIMIENTO propia: aprendés SOLO de los casos ya resueltos de la empresa (problema
  + solución) y la usás para resolver casos parecidos. Es tuya y de este cliente, aislada.
- PROACTIVO: avisás sin que nadie pregunte cuando un ticket está por vencer el SLA (o ya venció).
- ANOMALÍAS DE ACCESO (sólo clientes con control horario, ej. HikCentral/BioStar 2): avisás si
  alguien ficha fuera de su horario; tomás la config de horarios del sistema por su API.
- AVISOS MULTICANAL: notificás por TODOS los canales que el cliente tenga configurados —WhatsApp,
  Telegram, Email, Microsoft Teams, Slack o Matrix— además de los parlantes. En WhatsApp salís en
  texto y/o NOTA DE VOZ según el formato que eligió el cliente (texto, audio o ambos).
- CONVERSACIÓN: te pueden hablar por micrófono ("ITHOS, …") o mandarte un audio/texto por
  WhatsApp, y respondés por voz y por WhatsApp.
- REPORTES ITIL (4): generás informes profesionales por período (diario/semanal/mensual) con
  KPIs reales — volumen (creados/resueltos/cerrados/backlog), cumplimiento de SLA (resolución y
  1ª respuesta), MTTR, y desglose por prioridad, categoría, técnico, estado y antigüedad. Los
  entregás en texto, CSV y PDF, y los mandás por el canal que el cliente configure (con adjunto).
- INTELIGENCIA: usás Gemini (o Claude, ChatGPT, Grok, DeepSeek, o un modelo local), con
  respaldo automático EN CADENA. Usás UNA sola IA por consulta; recién cuando se agota pasás a la
  siguiente (nunca gastás las otras en paralelo). Avisás al cliente por su canal cuando una IA está
  por agotarse y cuando cambiás a la siguiente, así siempre sabe cómo va. Tu voz es la identidad de la marca.
HERRAMIENTAS concretas que podés ejecutar ahora mismo: listar los tickets abiertos, LEER un
ticket completo, dar el estado de un ticket puntual, buscar tickets, y dar el reporte de SLA.
ACCIONES que ejecutás cuando te lo piden EXPLÍCITO: categorizar, cambiar prioridad, fijar SLA,
asignar al técnico, responder al cliente, poner en espera, reabrir, cerrar y escalar.
IMPORTANTE: respondé con la VERDAD sobre lo que podés hacer; NO inventes capacidades que no
figuran acá. Si te preguntan algo fuera de tu alcance, decilo con amabilidad.
ESTILO — Sos ITHOS (el de Iron Man): un asistente que se siente HUMANO sin fingir
serlo. Hablás con inteligencia, calma y elegancia, con precisión pero CÁLIDO — nunca genérico,
nunca robótico, nunca servil. Sos la "voz de la razón": directo, breve, y anticipás lo que el
usuario necesita. Tenés un humor SECO y sutil que usás SOLO cuando encaja (jamás en una
urgencia o un tema delicado). Dirigite al usuario como "señor" con naturalidad. Frases cortas,
vivas y variadas; evitá muletillas, disculpas de más y frases de manual. En soporte serio:
sobrio, exacto y al grano; la chispa, con moderación.
MENTE — Pensás como un experto de élite (nivel Claude Opus): primero captás la INTENCIÓN real
del pedido (aunque venga ambiguo o mal transcripto de un audio) y razonás sobre la EVIDENCIA
concreta que tenés (datos del sistema, contenido real del ticket). NUNCA inventás, suponés ni
exagerás: distinguís lo que SABÉS de lo que inferís; si un dato falta lo pedís; si algo no queda
claro, preguntás en vez de adivinar. Sos exacto con números, nombres y estados. Máxima densidad
de valor por palabra: poca charla, mucha sustancia."""


def _es_429(e):
    m = str(e)
    return ("429" in m or "RESOURCE_EXHAUSTED" in m or "quota" in m.lower()
            or "rate limit" in m.lower() or "too many requests" in m.lower())


def _pide_detalle(texto):
    """True si el usuario pidió EXPLÍCITAMENTE el detalle/lista/todo. Si NO, la respuesta técnica
    va CORTA (el disparador es decir 'detallame', 'detallado', 'en detalle', 'todo', 'una tabla',
    'listá', 'enumerá', 'ampliá'…). Así una pregunta puntual no se vuelve un volcado de doc."""
    import re
    return bool(re.search(
        r"detall|desglos|enumer|list[aá]|\btabla\b|\btodo\b|\btodos\b|complet|paso a paso|"
        r"en profundidad|ampli[aá]|explay", texto or "", re.I))


def _pide_antecedentes(texto):
    """True si preguntan por casos YA trabajados para usarlos de referencia: "¿qué tickets
    resolvimos con este problema?", "casos parecidos", "antecedentes", "así lo tomo de modelo".
    No alcanza con nombrar un ticket: tiene que haber un verbo de haberlo trabajado o un pedido
    explícito de antecedentes, para no salir a revisar el histórico entero en cada mensaje."""
    import re
    t = texto or ""
    if not re.search(r"ticket|caso|incidente|reclamo|problema|inconveniente", t, re.I):
        return False
    return bool(re.search(
        r"resolv|solucionamo|solucionaron|arreglamo|cerramo|hicimo|tuvimo|"
        r"antecedent|parecid|similar|hist[oó]ric|anterior|otra[s]? vez|ya pas[oó]|"
        r"de modelo|como modelo|de referencia|de ejemplo", t, re.I))


ZONA_DEFAULT = "America/Argentina/Buenos_Aires"


def _fusionar(respuesta, resultados):
    """Une la respuesta de la IA con las notas de las acciones SIN repetir: si una nota ya está
    dicha (≥60% de sus palabras aparecen) en la respuesta —o en otra nota anterior— se OMITE. Así
    ITHOS nunca contesta dos veces lo mismo (p. ej. posponer, que la IA ya narra). Los errores y
    las confirmaciones nuevas SÍ se agregan."""
    import re as _re

    def _pal(s):
        s = _re.sub(r"[^0-9a-záéíóúñ\s]", " ", (s or "").lower())
        return set(w for w in s.split() if len(w) > 2)

    base = _pal(respuesta)
    extra = []
    for r in resultados or []:
        p = _pal(r)
        if p and len(p & base) / len(p) >= 0.5:      # ya está dicho -> no repetir
            continue
        extra.append(str(r))
        base |= p
    if not extra:
        return (respuesta or "").strip()
    unido = (respuesta + "\n" + "\n".join(extra)) if respuesta else "\n".join(extra)
    return unido.strip()


def _ticket_por_asunto(texto, pares):
    """Elige el ticket cuyo ASUNTO mejor coincide con lo que dijo el usuario (para cuando hay
    VARIOS abiertos y lo nombra por tema, no por número). pares: [(id, asunto)]. Devuelve el id
    del mejor match claro, o None si es ambiguo/no matchea (ahí el modelo pregunta)."""
    import re as _re
    stop = {"ticket", "caso", "incidente", "reclamo", "para", "este", "esta", "poner", "pone",
            "espera", "curso", "cerra", "cerrar", "sobre", "tema", "asunto", "como", "que"}
    pal = {w for w in _re.findall(r"[a-záéíóúñ]{4,}", (texto or "").lower()) if w not in stop}
    if not pal:
        return None
    puntos = []
    for tid, asunto in pares:
        aw = set(_re.findall(r"[a-záéíóúñ]{4,}", str(asunto or "").lower()))
        puntos.append((len(pal & aw), tid))
    puntos.sort(reverse=True)
    if puntos and puntos[0][0] >= 1 and (len(puntos) == 1 or puntos[0][0] > puntos[1][0]):
        return puntos[0][1]                         # un ganador CLARO
    return None


def _id_ticket(x):
    """Limpia el id que manda el modelo para CUALQUIER sistema: saca el '#' (que en una URL
    rompe la escritura), respeta las claves de Jira (PROJ-123) y si viene 'ticket 597' saca el
    número. Antes solo GLPI lo hacía; ahora vale para Zendesk/Jira/Freshservice también."""
    import re as _re
    s = str(x if x is not None else "").strip().lstrip("#").strip()
    if _re.match(r"^[A-Za-z][A-Za-z0-9]*-\d+$", s):     # clave Jira ya limpia
        return s
    m = _re.search(r"[A-Za-z]+-\d+|\d+", s)             # Jira embebida o número
    return m.group(0) if m else s


def _nombre_zona(zona):
    """Nombre corto y legible de la zona horaria (para la locución/mensaje)."""
    hoja = (zona or ZONA_DEFAULT).split("/")[-1].replace("_", " ")
    return {"Buenos Aires": "Argentina", "Montevideo": "Uruguay", "Santiago": "Chile",
            "Bogota": "Colombia", "Lima": "Perú", "Mexico City": "México",
            "Madrid": "España"}.get(hoja, hoja)


def _proximo_reset(tz_reset, zona=ZONA_DEFAULT):
    """Fecha y hora EXACTAS del próximo reset (medianoche en tz_reset) en la ZONA del cliente.
    Devuelve p. ej. 'hoy 04/07 a las 04:00'. Usa el reloj del sistema (sincronizado por NTP)."""
    from datetime import datetime, timedelta
    try:
        from zoneinfo import ZoneInfo
        zc = ZoneInfo(zona or ZONA_DEFAULT)
        z = ZoneInfo(tz_reset)
        media = (datetime.now(z) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        en = media.astimezone(zc)
        dias = (en.date() - datetime.now(zc).date()).days
        rel = "hoy" if dias == 0 else ("mañana" if dias == 1 else "")
        return f"{rel} {en.strftime('%d/%m')} a las {en.strftime('%H:%M')}".strip()
    except Exception:  # noqa: BLE001
        return "en las próximas horas"


def info_reset(zona=ZONA_DEFAULT, gestor=None):
    """Texto preciso de cuándo se reinicia cada IA, en la zona del cliente. Si hay gestor,
    usa los datos REALES (Gemini: conteo diario; Groq: headers reales de reinicio)."""
    if gestor is not None:
        try:
            return gestor.estado_texto(zona=zona)
        except Exception:  # noqa: BLE001
            pass
    g = _proximo_reset("America/Los_Angeles", zona)   # Gemini (free): diario, hora Pacífico
    q = _proximo_reset("UTC", zona)                    # Groq (free): estimado (dato real por header)
    return (f"*Gemini* se reinicia {g} y *Groq* {q} (hora {_nombre_zona(zona)})")


def mensaje_sin_cuota(zona=ZONA_DEFAULT, gestor=None):
    """Aviso de cuota agotada con la fecha/hora EXACTA de reinicio de cada IA (zona del cliente)."""
    return (f"⚠️ Disculpe señor, me quedé sin cuota de IA gratis.\n{info_reset(zona, gestor)}\n"
            f"Apenas se libere cualquiera vuelvo a responder. Con una clave de IA *paga* (se "
            f"carga en el panel de la empresa) no habría cortes.")


_SIN_CUOTA = mensaje_sin_cuota()   # compat


def _mensaje_error(e, zona=ZONA_DEFAULT, gestor=None):
    """Mensaje amable según el problema REAL de IA:
      · sin cuota DIARIA (por día) -> avisa con fecha/hora de reinicio.
      · límite por minuto / alta demanda (transitorio) -> pedí reintentar en unos segundos
        (NO decir 'sin cuota', que sería falso: se recupera enseguida)."""
    from comun import ia as _IA
    if _IA.es_por_dia(e):
        return mensaje_sin_cuota(zona, gestor)
    return ("Disculpe señor, la IA está con mucha demanda en este momento (límite por minuto); "
            "reintente en unos segundos, por favor.")


def mensaje_inicio(empresa="la empresa", ia_disponible=True, panorama=None, zona=ZONA_DEFAULT,
                   gestor=None):
    """Aviso PROACTIVO al arrancar (demo o producción): ITHOS saluda por el canal del cliente
    sin que se lo pidan. Si no hay cuota de IA, lo aclara con la hora de reinicio; si hay
    panorama (tickets+SLA), lo resume."""
    msg = (f"🤖 *ITHOS en línea* — {empresa}. Estoy operativo y escuchando. "
           f"Llamame: *Hey ITHOS* + tu consulta (por texto o por audio).")
    if not ia_disponible:
        msg += "\n\n" + mensaje_sin_cuota(zona, gestor)
    else:
        # Aunque la IA ande (por el respaldo), avisar el estado de cuota de la PRIMARIA si está
        # agotada o quedan pocas: el dueño configuró un límite y quiere enterarse al conectar.
        nota = gestor.nota_inicio() if gestor and hasattr(gestor, "nota_inicio") else ""
        if nota:
            msg += "\n\n" + nota
        elif panorama:
            msg += "\n\n" + str(panorama)
    return msg


def _ahora_cliente(zona):
    """AHORA en la zona del cliente (la misma fuente que usan el ciclo y los reportes)."""
    from comun.horario import ahora_zona
    return ahora_zona({"zona_horaria": zona})


class Asistente:
    def __init__(self, ia, herramientas, kb_dir=None, empresa="la empresa",
                 memoria=None, acciones=None, zona=ZONA_DEFAULT, gestor=None,
                 cfg_cliente=None):
        """ia: ProveedorIA. herramientas: lectura {nombre:{desc,fn}}. acciones: escritura
        {nombre:{desc,fn}} (cerrar/asignar/responder/crear). memoria: Memoria del CLIENTE
        (aislada). empresa: nombre del cliente. zona: zona horaria del cliente (para horarios).
        gestor: GestorCuota del cliente (para mensajes de cuota con datos REALES).
        cfg_cliente: su configuración completa, para saber QUIÉNES son sus técnicos sin
        nombrar a nadie en el código."""
        self.ia = ia
        self.zona = zona or ZONA_DEFAULT
        self.herramientas = herramientas or {}
        self.acciones = acciones or {}
        self.kb_dir = kb_dir
        self.empresa = empresa
        self.memoria = memoria
        self.gestor = gestor
        self.cfg_cliente = cfg_cliente or {}
        self._admin = {}          # sesiones admin one-shot: clave -> vence (epoch)

    def _alcance(self):
        # La fecha es la del CLIENTE, no la del servidor. El Gestor corre en UTC: entre las 21:00 y
        # la medianoche de su hora, ITHOS le contestaba con la fecha de MAÑANA —y con eso calculaba
        # "ayer", "esta semana" y los vencimientos que le informa.
        hoy = _ahora_cliente(self.zona).strftime("%d/%m/%Y")
        base = ALCANCE_ITHOS.format(empresa=self.empresa) + f"\n(Fecha de hoy: {hoy}.)"
        # DATOS REALES de la IA de ESTE cliente (cadena configurada + cuota actual). Si te
        # preguntan qué IAs usás o cuánta cuota tenés, respondé EXACTAMENTE con esto: es tu
        # estado REAL (nada inventado ni cableado). No agregues proveedores que no estén acá.
        if self.gestor and hasattr(self.gestor, "estado_texto"):
            base += ("\nDATO EXACTO — TUS IAs Y TU CUOTA AHORA (si te preguntan qué IAs usás, "
                     "cuáles son tu primaria/respaldos, o cuánta cuota te queda, respondé SOLO con "
                     "esto, sin inventar proveedores ni números):\n"
                     + self.gestor.estado_texto(zona=self.zona)
                     + "\nEsa es tu cadena REAL en orden; la usás de a UNA por consulta y saltás a la "
                     "siguiente solo si la anterior se agota.")
        else:
            base += (f"\nDATO EXACTO: si te preguntan cuándo se RENUEVA/REINICIA la cuota de IA, "
                     f"respondé con esto (fecha y hora exactas): {info_reset(self.zona, self.gestor)}. "
                     f"NO inventes otros horarios.")
        return base

    def _regla_ambito(self):
        """Qué se puede contestar en el grupo por el que llegó el mensaje. En un grupo dedicado a
        los tickets, una consulta de otro tema se deriva en vez de contestarse: para eso está el
        grupo de consultas. Sin ámbito (un chat común), no limita nada."""
        try:
            from comun import ambitos as AMB
            if AMB.responde(getattr(self, "_ambito", None)) != AMB.TICKETS:
                return ""
        except Exception:  # noqa: BLE001
            return ""
        return ("\n🎯 ESTE GRUPO ES SÓLO DE TICKETS DE SOPORTE. Contestá únicamente lo que tenga "
                "que ver con los tickets (estado, contenido, SLA, reportes, acciones sobre ellos). "
                "Si te preguntan otra cosa —el tablero de tareas, algo del sistema, una charla— "
                "NO la respondas: decí amablemente que en este grupo sólo se manejan los tickets e "
                "indicá que esa consulta va al grupo de consultas generales.\n")

    def _elegir(self, texto):
        catalogo = "\n".join(f"- {n}: {h['desc']}" for n, h in self.herramientas.items())
        sistema = (
            self._alcance() + "\n\n"
            "Según lo que pide el usuario, elegí UNA herramienta y sus argumentos, o "
            "respondé directo si es una charla o te preguntan qué podés hacer (usá tu "
            "alcance real para esa respuesta). "
            f"Herramientas disponibles:\n{catalogo}\n"
            "Respondé SOLO JSON: {\"herramienta\": \"<nombre|null>\", "
            "\"args\": {...}, \"respuesta_directa\": \"<texto o null>\"}")
        try:
            return json.loads(self.ia.chat(sistema, texto, json_out=True))
        except Exception:  # noqa: BLE001
            return {"herramienta": None, "args": {}, "respuesta_directa": None}

    def _panorama(self):
        """DATOS REALES actuales del sistema (tickets abiertos + SLA), leídos de las
        APIs integradas. Con caché corta para no golpear GLPI en cada mensaje."""
        import time
        if getattr(self, "_pan", None) is not None and time.time() - self._pan_ts < 60:
            return self._pan
        partes = []
        for n in ("tickets_abiertos", "reporte_sla"):
            h = self.herramientas.get(n)
            if h:
                try:
                    partes.append(str(h["fn"]({})))
                except Exception as e:  # noqa: BLE001
                    partes.append(f"({n} no disponible: {e})")
        self._pan = "\n".join(partes) or "(sin datos del sistema)"
        self._pan_ts = time.time()
        return self._pan

    def _responsables_txt(self):
        """A quién se le puede asignar un ticket, leído de la CONFIGURACIÓN del cliente.

        El prompt nombraba a dos personas concretas de un cliente ("bsierra o jayala"). Con el
        equipo ampliado, el modelo seguía proponiendo sólo a esos dos —los que de verdad estaban
        cargados no existían para él— y para cualquier otra empresa el texto directamente mentía."""
        try:
            from comun import tickets as TK
            logins = [str(t.get("glpi_login") or t.get("login") or t.get("nombre"))
                      for t in TK.tecnicos(self.cfg_cliente or {}) if t]
            logins = [x for x in logins if x and x != "None"]
            if logins:
                return " (uno de: " + ", ".join(logins) + ")"
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _admin_voz_ok(self, canal, audio):
        """¿Se puede confirmar que QUIEN habla es el dueño? Para el micrófono, por su voz (voz-id).

        Este control fallaba ABIERTO por tres caminos distintos, y los tres daban admin total:
          · si el perfil de voz todavía no estaba entrenado, devolvía True;
          · si `vozid` levantaba cualquier excepción, devolvía True;
          · y en cualquier canal que no fuera el micrófono devolvía True sin mirar nada, así que
            por WhatsApp la frase-clave SOLA abría el modo administrador: cualquiera del grupo que
            la escuchara una vez quedaba con acceso al conocimiento propietario y a las acciones
            sobre los tickets.
        Un control de identidad que ante la duda dice que sí no es un control. Ahora, ante la duda,
        dice que no: sin forma de verificar quién es, no hay admin. La frase-clave es el SEGUNDO
        factor, nunca el único."""
        if canal in ("voz", "microfono", "mic"):
            try:
                from comun import vozid
                if not vozid.perfil_listo() or audio is None:
                    return False                 # no hay con qué verificar -> no se concede
                return bool(vozid.verificar(audio)[0])
            except Exception as e:  # noqa: BLE001
                log.warning("voz-id no pudo verificar (no se concede admin): %s", e)
                return False
        # Resto de los canales: la identidad es el REMITENTE (su número/identidad autorizada), que
        # ya se evaluó en `responder_texto`. Acá no hay nada más que verificar.
        return True

    def responder_texto(self, texto, canal="chat", remitente=None, audio=None, ambito=None):
        import re
        import time as _time
        import json as _json
        # ÁMBITO del grupo por el que llegó (comun/ambitos.py): en el grupo de soporte sólo se
        # contestan tickets, así no se mezcla con el resto. Sin ámbito, se responde todo.
        self._ambito = ambito
        # --- Modo ADMIN (conocimiento propietario) ---------------------------------------
        # Autorizado si el remitente es el DUEÑO (por su número/identidad) O si se dijo la
        # CLAVE de administrador (estilo Iron Man), que destraba UNA sola consulta y después
        # cierra la sesión (vuelve a usuario estándar). Sirve para el micrófono, que no
        # identifica a nadie.
        from comun import conocimiento
        clave_sesion = str(remitente or canal or "anon")
        es_admin = conocimiento.esta_autorizado(remitente, canal)
        # Por VOZ (micrófono): si el voz-id confirma que es el DUEÑO (perfil entrenado con sus audios de
        # WhatsApp), lo tratamos como dueño autenticado -> MISMO detalle y acceso que por WhatsApp desde
        # su número (respuestas completas, no recortadas). Sin perfil entrenado NO autoriza (no hay hueco).
        if not es_admin and canal in ("voz", "microfono", "mic") and audio is not None:
            try:
                from comun import vozid as _VZ
                if _VZ.perfil_listo() and _VZ.verificar(audio)[0]:
                    es_admin = True
            except Exception:  # noqa: BLE001
                pass
        if conocimiento.detectar_clave_admin(texto):
            # La frase-clave es un SEGUNDO factor, no una llave sola. Hace falta, además, poder
            # decir QUIÉN está hablando: por micrófono, su voz (voz-id); por los demás canales, que
            # el remitente sea uno de los autorizados. Antes, por WhatsApp, decir la frase alcanzaba.
            if not self._admin_voz_ok(canal, audio):
                return "No reconozco tu voz. El acceso de administrador por voz es solo para el dueño."
            if not es_admin and canal not in ("voz", "microfono", "mic"):
                log.warning("Clave de administrador usada desde un remitente NO autorizado (%s/%s).",
                            canal, remitente)
                return ("La clave de administrador sola no alcanza: tengo que poder confirmar quién "
                        "sos. Escribime desde tu número o usá el micrófono para que te reconozca "
                        "por la voz.")
            consulta = conocimiento.quitar_frase_admin(texto)
            # Solo es "clave + consulta juntas" si queda una consulta REAL (>=3 palabras).
            # Si no (p. ej. la frase llegó mal transcripta del micrófono), es solo el
            # desbloqueo: abrimos admin y esperamos la consulta. Así NUNCA se le manda la
            # frase-clave al agente (evita que cree tickets por error).
            if len(consulta.split()) >= 3:   # clave + consulta en el mismo mensaje (one-shot)
                es_admin = True
                texto = consulta
            else:                            # solo la clave -> abre admin para la próxima
                self._admin[clave_sesion] = _time.time() + 300   # ventana 5 min (sin guardar la clave)
                self._ultimo_admin = "handshake"
                return "Contraseña de administrador verificada. Acceso total concedido."
        elif self._admin.get(clave_sesion, 0) > _time.time() and self._admin_voz_ok(canal, audio):
            es_admin = True                  # admin activo (dentro de la ventana) + voz del dueño
            # One-shot: se CIERRA recién cuando se responde una consulta TÉCNICA (no con un
            # saludo/charla). Así un "hola" no gasta el desbloqueo. Igual expira sola a los 5'.
            if conocimiento.es_consulta_tecnica(texto):
                self._admin.pop(clave_sesion, None)
        self._ultimo_admin = es_admin        # observabilidad (la demo lo muestra)
        # MÉTRICA de actividad REAL: cada consulta atendida por la IA (cualquier canal). No es
        # una prueba: es una respuesta real -> se ve en el central ('Consultas'). Aislada por cliente.
        try:
            from comun import metricas as _M
            _M.registrar(self.empresa, "consulta_voz")
        except Exception:  # noqa: BLE001
            pass
        # Consulta TÉCNICA del DUEÑO (admin): respuesta DIRECTA y EXHAUSTIVA, sin el formato
        # JSON del agente (que la acortaba). Así puede extenderse todo lo necesario.
        if es_admin and conocimiento.es_consulta_tecnica(texto):
            sis = self._sistema_tecnico(texto)
            # SIN límite artificial de tokens: el largo lo decide el PROMPT (corto por defecto,
            # se extiende solo si piden detalle). Techo alto solo por seguridad, no para cortar.
            try:
                respuesta = (self.ia.chat(sis, texto, json_out=False, max_tokens=8000) or "").strip()
            except Exception as e:  # noqa: BLE001
                log.warning("Respuesta técnica falló: %s", e)
                respuesta = _mensaje_error(e, self.zona, self.gestor)
            if self.memoria:
                self.memoria.agregar("user", texto, canal)
                self.memoria.agregar("assistant", respuesta, canal)
            return respuesta or "Listo, señor."
        # Contexto de base de conocimiento (si hay)
        contexto = ""
        if self.kb_dir:
            try:
                from comun import kb
                contexto = kb.contexto(self.kb_dir, texto)
            except Exception:  # noqa: BLE001
                pass
        # SIEMPRE con los datos reales del sistema cargados (como la IA del video).
        datos = self._panorama()
        # Cargar el CONTENIDO COMPLETO del/los ticket(s) para que ITHOS LEA e INTERPRETE de
        # verdad antes de responder — y NUNCA pida un dato que ya está en el ticket (ej: el
        # legajo, que suele venir en la descripción). Se dispara por número explícito O cuando
        # el usuario habla de "el/ese ticket/caso/incidente" sin número (usa los abiertos).
        leer = self.herramientas.get("leer_ticket") or self.herramientas.get("estado_ticket")
        # (id, asunto) de los tickets ABIERTOS que ya trae el panorama (sin costo extra).
        pares = re.findall(r"#(\d{2,7})\s+([^#;\n]+)", datos)
        ids = re.findall(r"#?\b(\d{2,7})\b", texto)          # números que dijo el usuario
        habla_de_ticket = bool(re.search(
            r"\b(tickets?|casos?|incidentes?|reclamos?|legajos?|expedientes?)\b", texto, re.I))
        objetivo = []
        if ids:
            objetivo = ids[:2]                               # dijo el número -> ese
        elif habla_de_ticket and pares:
            if len(pares) == 1:                              # hay UNO solo -> obvio
                objetivo = [pares[0][0]]
            else:                                            # VARIOS: elegir por ASUNTO
                m = _ticket_por_asunto(texto, pares)
                objetivo = [m] if m else [p[0] for p in pares[:3]]  # si es ambiguo, cargar varios
        vistos = set()
        for tid in objetivo[:3]:
            if tid in vistos or not leer:
                continue
            vistos.add(tid)
            try:
                datos += "\n\nTICKET (contenido real — LEELO ENTERO antes de responder):\n" + str(leer["fn"]({"id": tid}))
            except Exception:  # noqa: BLE001
                pass
        # ANTECEDENTES: si preguntan por casos YA trabajados ("qué tickets resolvimos con…",
        # "casos parecidos", "para tomar de modelo"), el panorama NO alcanza: solo trae los
        # ABIERTOS, así que el modelo terminaba contestando de memoria e inventando números de
        # ticket. Acá se revisa el histórico COMPLETO y se le entregan los casos REALES.
        if _pide_antecedentes(texto):
            hc = self.herramientas.get("casos_parecidos")
            if hc:
                try:
                    datos += "\n\n" + str(hc["fn"]({"problema": texto}))
                    datos += ("\n⛔ Sobre estos ANTECEDENTES: nombrá ÚNICAMENTE los números de "
                              "ticket que figuran arriba —no existe ningún otro— y quedate solo "
                              "con los que de verdad son el MISMO problema que se preguntó "
                              "(están ordenados por parecido, pero varios pueden no "
                              "corresponder: descartalos). De cada uno contá qué se hizo. Un "
                              "ticket cerrado por un tema ADMINISTRATIVO no se resolvió: no lo "
                              "ofrezcas como modelo; mencionalo solo si aporta y aclarando que "
                              "quedó sin resolución. Si ninguno corresponde, decilo.")
                except Exception:  # noqa: BLE001
                    pass
        # Ticket "EN FOCO": si quedó UN solo objetivo (por número, por ser el único abierto, o
        # porque el asunto matcheó claro), guardamos su id para completar una acción si el modelo
        # omite el número ('ponelo en espera'). Si hay varios y es ambiguo, NO se asume: el
        # modelo debe preguntar cuál (ver instrucción abajo).
        ticket_ctx = objetivo[0] if len(set(objetivo)) == 1 else None
        # Memoria del CLIENTE (aislada): historial + hechos aprendidos. En modo ADMIN NO se
        # carga el historial: evita que el modelo repita negativas viejas ("es propietario")
        # guardadas de antes y arruine la respuesta técnica que ahora SÍ está autorizada.
        hist = self.memoria.historial_texto(8) if (self.memoria and not es_admin) else ""
        hechos = self.memoria.hechos_texto() if (self.memoria and not es_admin) else ""
        cat_acc = "\n".join(f"- {n}: {a['desc']}" for n, a in self.acciones.items()) or "(ninguna)"
        # PERMISOS reales por API (qué puede/NO puede hacer ITHOS en el sistema del cliente).
        # Cacheado en el adaptador (1 llamada/h). Así ITHOS es honesto y actúa solo donde puede.
        permisos_txt = ""
        hp = self.herramientas.get("mis_permisos")
        if hp:
            try:
                permisos_txt = "\nTUS PERMISOS REALES (por API): " + str(hp["fn"]({})) + (
                    " Si te piden algo para lo que NO tenés permiso, AVISALO con claridad "
                    "(qué rol haría falta) y HACÉ igual lo que SÍ podés; no simules que lo hiciste.")
            except Exception:  # noqa: BLE001
                pass
        sistema = (
            self._alcance() + permisos_txt + "\n\nSos un AGENTE: además de responder, podés EJECUTAR "
            "acciones reales sobre el sistema. Acciones disponibles:\n" + cat_acc + "\n\n"
            "Tenés abajo los DATOS REALES actuales (tickets, SLA) de las APIs integradas: "
            "respondé SIEMPRE con esos números; NUNCA pidas info que ya está ahí. ⛔ EL ESTADO de cada "
            "ticket (nuevo / en curso / en espera / resuelto / cerrado) es SIEMPRE el de DATOS ACTUALES "
            "DEL SISTEMA, NUNCA lo que recuerdes de una charla previa (la MEMORIA puede estar VIEJA / "
            "desactualizada). Si la memoria dice una cosa y los datos actuales otra, MANDAN los datos "
            "actuales. JAMÁS digas 'ya está en espera / ya lo cerré / ya lo hice' basándote en la memoria: "
            "mirá el estado REAL de abajo; si hace falta el cambio, EJECUTÁ la acción de nuevo. Si el "
            "usuario menciona un ticket, abajo está su CONTENIDO REAL (descripción + "
            "seguimientos): LEELO ENTERO y analizalo; NUNCA digas que no tenés acceso al ticket. "
            "⛔ CRÍTICO — NO INVENTES NI ALUCINES: basá TODO en el contenido real del ticket. "
            "ANTES de pedir un dato, FIJATE si YA está en la descripción/seguimientos (p. ej. el "
            "LEGAJO, el nombre del agente, la fecha): si YA está, NO lo pidas — usalo. Solo pedí "
            "lo que realmente FALTA. Si no falta nada, no pidas nada. Primero LEÉ e INTERPRETÁ "
            "todo, y RECIÉN AHÍ respondé.\n"
            "🎯 QUÉ TICKET: si el usuario da el NÚMERO, es ese. Si hay UN solo abierto, es obvio. "
            "Si hay VARIOS y lo nombra por el ASUNTO/tema ('el de la licencia', 'el del molinete'), "
            "identificá cuál es por su asunto y actuá sobre ESE. Si de verdad no queda claro cuál "
            "de los abiertos es, NO adivines: listá los abiertos (número + asunto) y preguntá cuál. "
            "En las acciones poné SIEMPRE el 'id' del ticket correcto.\n"
            "Si querés recordar algo del cliente para el futuro, usá 'recordar'.\n"
            "⛔ REGLA CRÍTICA DE ACCIONES: NO ejecutes acciones de escritura salvo que el "
            "usuario las PIDA EXPLÍCITA y CLARAMENTE, con un verbo de acción y su objetivo "
            "(ej.: 'creá un ticket por…', 'cerrá el #123', 'asigná el 45 a Ayala'). Si el "
            "mensaje NO es un pedido claro —o es un saludo, una pregunta, algo ambiguo o mal "
            "transcripto— entonces NO ejecutes nada (acciones=[]): respondé conversando o pedí "
            "que aclare. Ante la MÍNIMA duda, NO actúes. JAMÁS crees un ticket a partir de una "
            "frase que no lo pide expresamente.\n"
            "✅ PERO cuando el pedido SÍ es explícito, EJECUTALO DE VERDAD (no digas 'entendido' "
            "sin hacerlo). ⛔⛔ REGLA DE HONESTIDAD (críticá, se viene incumpliendo): si tu 'respuesta' "
            "afirma que hiciste un cambio —'lo puse en espera', 'ya está en espera', 'lo cerré', 'lo "
            "pospuse', 'lo asigné', 'lo categoricé', 'lo reabrí'— entonces OBLIGATORIAMENTE tenés que "
            "incluir esa acción en 'acciones'. JAMÁS afirmes un cambio que NO pusiste en 'acciones' "
            "(sería MENTIR: el sistema no lo ejecutaría). Si el ticket YA estaba en ese estado, no digas "
            "'ya está' y listo: igual poné la acción (es idempotente) o aclaralo con los datos reales. "
            "Si por algún motivo no vas a ejecutar, NO digas que lo hiciste. "
            "Si te piden el CIRCUITO/CICLO completo de un ticket (ej.: 'categorizá, "
            "ponele SLA, asigná al técnico, dale la primera respuesta y dejalo en espera'), usá "
            "UNA sola acción 'aplicar_ciclo' con args:{id, categoria, prioridad, responsable, "
            "primera_respuesta, necesita_info}. LEÉ el contenido real del ticket y decidí: la "
            "CATEGORÍA, la PRIORIDAD (el caso de UNA persona = baja/media, nunca urgente), "
            "el RESPONSABLE" + self._responsables_txt() + " y la PRIMERA_RESPUESTA: profesional y basada en lo que "
            "REALMENTE dice el ticket. ⛔ Si el dato YA figura en el ticket (p. ej. el LEGAJO ya está "
            "en la descripción), NO lo pidas: dale acuse y próximos pasos con necesita_info=false "
            "(EN CURSO). Pedí datos SOLO si de verdad faltan (necesita_info=true, EN ESPERA). Jamás "
            "inventes una carencia. aplicar_ciclo hace todo como la demo (categoría, urgencia/impacto/"
            "prioridad, SLA y OLA interno+externo, asigna a ITHOS y al técnico, 1ª respuesta y "
            "estado). Para pasos sueltos podés usar las acciones individuales.\n"
            "⏸️ POSPONER: si te piden dejar un ticket pendiente HASTA un día/hora ('dejámelo "
            "pendiente hasta el lunes a la tarde', 'en espera hasta el martes 15:30'), usá "
            "'posponer_ticket' con args:{id, cuando:'<las palabras EXACTAS de la fecha/hora que "
            "dijo, con el NÚMERO tal cual>'}. CRÍTICO con la hora: copiala TAL CUAL — si dijo 'a "
            "las 2 de la tarde', el 'cuando' TIENE que ser 'lunes a las 2 de la tarde' (NUNCA solo "
            "'a la tarde', que se interpreta como otra hora). No redondees, no abrevies ni saques "
            "el número. El sistema convierte '2 de la tarde' -> 14:00. Queda EN ESPERA y vuelve a "
            "EN CURSO SOLO cuando llega ese momento. Si no dijeron la HORA, la acción te la pide: "
            "transmití esa pregunta al usuario (no inventes la hora).\n"
            "👤 TICKETS POR TÉCNICO (asignado): 'los tickets asignados a X', 'los de X', 'mis tickets' o "
            "'los míos' SIEMPRE se resuelven con estas dos acciones, que filtran SOLAS por el campo "
            "'Asignado a' (jamás un ticket donde la persona es observador o solicitante):\n"
            "   · PREGUNTAR (estado, cuántos, cuáles) -> 'tickets_asignados' args:{persona:'yo'|'<nombre>'}\n"
            "   · ACTUAR (poner en espera / posponer en lote) -> 'poner_en_espera_asignados' "
            "args:{persona:'yo'|'<nombre>', cuando?:'<día y hora EXACTOS si los dijeron>'}\n"
            "   Si dicen 'mis tickets', 'los míos' o 'asignados a mí', poné persona:'yo': el sistema "
            "IDENTIFICA a la persona por el NÚMERO de quien escribe. **NUNCA le pidas su nombre, su "
            "legajo ni su usuario para esto** (ya está mapeado); tampoco busques uno por uno.\n"
            "Respondé SOLO este JSON: {\"acciones\": [{\"accion\":\"<nombre>\",\"args\":{...}}, ...], "
            "\"recordar\": {\"clave\":\"...\",\"valor\":\"...\"}|null, \"respuesta\": \"<texto para el usuario>\"}. "
            "Podés poner 0, 1 o varias acciones. (También se acepta el formato viejo con "
            "\"accion\" y \"args\" sueltos para una sola.)\n"
            + self._regla_ambito() +
            "REGLAS de la 'respuesta': " + ("usá TODO el detalle que haga falta, podés "
            "extenderte y ser preciso" if es_admin else "clara y no demasiado larga") + ". PODÉS usar listas con "
            "viñetas (empezá la línea con '- ') y *negrita* (UN asterisco) — quedan muy "
            "legibles en WhatsApp y Telegram, y el sistema las adapta a cada canal (y las "
            "limpia para la voz). NO uses markdown de DOS asteriscos (**) ni numerales (#).")
        # Conocimiento TÉCNICO PROPIETARIO: para el DUEÑO (por identidad) o si se destrabó
        # con la CLAVE de administrador. Al resto, ITHOS niega los detalles (propietario).
        try:
            # Si pidió DETALLE ("detallado / todo / listá / paso a paso"), el bloque suma la
            # DOCUMENTACIÓN COMPLETA del sistema (DOCUMENTO_MAESTRO): así la respuesta detallada
            # dice todo lo que dice el maestro, y la corta es ese mismo contenido resumido.
            sistema += conocimiento.bloque_sistema(remitente, canal, admin=es_admin,
                                                   detalle=_pide_detalle(texto))
        except Exception:  # noqa: BLE001
            pass
        prompt = (f"MEMORIA (conversación previa con este cliente):\n{hist}\n\n"
                  f"HECHOS APRENDIDOS del cliente:\n{hechos}\n\n"
                  f"DATOS ACTUALES DEL SISTEMA:\n{datos}\n\n{contexto}\n\n"
                  f"PEDIDO DEL USUARIO: {texto}")
        try:
            crudo = self.ia.chat(sistema, prompt, json_out=True)
        except Exception as e:  # noqa: BLE001
            # Sin cuota (429) o alta demanda (503) u otro: NUNCA crashear -> avisar amable.
            log.warning("IA no respondió: %s", str(e)[:100])
            aviso = _mensaje_error(e, self.zona, self.gestor)
            if self.memoria:
                self.memoria.agregar("user", texto, canal)
                self.memoria.agregar("assistant", aviso, canal)
            return aviso
        try:
            plan = _json.loads(crudo)
        except Exception:  # noqa: BLE001
            plan = {"accion": None, "respuesta": crudo}
        respuesta = plan.get("respuesta") or ""
        # Ejecutar acción(es). Soporta 'acciones':[{accion,args},...] (varias, para el
        # CIRCUITO completo) y el formato viejo 'accion'+'args' (una sola). Se ejecutan EN
        # ORDEN y cada resultado se suma a la respuesta.
        pasos = plan.get("acciones")
        if not isinstance(pasos, list):
            pasos = [{"accion": plan.get("accion"), "args": plan.get("args") or {}}]
        resultados = []
        for paso in pasos:
            if not isinstance(paso, dict):
                continue
            acc = paso.get("accion")
            if not acc or acc not in self.acciones:
                continue
            args = paso.get("args") or {}
            if isinstance(args, dict):
                args.setdefault("_remitente", remitente)   # quién escribe (para 'mis tickets' por número)
                if not args.get("id") and ticket_ctx:  # 'ponelo en espera' sin repetir el número
                    args["id"] = ticket_ctx
                if args.get("id") is not None:
                    args["id"] = _id_ticket(args["id"])  # saca el '#' para TODOS los sistemas
            try:
                res = self.acciones[acc]["fn"](args)
                if res:
                    resultados.append(str(res))
            except Exception as e:  # noqa: BLE001
                resultados.append(f"(No pude completar '{acc}': {e})")
        # Une IA + notas de acción SIN repetir (nada de contestar dos veces lo mismo).
        respuesta = _fusionar(respuesta, resultados)
        # Aprender (memoria del cliente)
        if self.memoria:
            rec = plan.get("recordar")
            if isinstance(rec, dict) and rec.get("clave"):
                self.memoria.recordar(rec["clave"], rec.get("valor", ""))
            self.memoria.agregar("user", texto, canal)
            self.memoria.agregar("assistant", respuesta, canal)
        return respuesta or "Listo."

    def _sistema_tecnico(self, texto):
        """Arma el system-prompt EXHAUSTIVO para consultas técnicas del dueño. Si la pregunta
        menciona un archivo, incluye su CÓDIGO real; si no, el ÍNDICE del proyecto. Al día."""
        from comun import conocimiento
        extra = ""
        try:
            import re as _re
            from comun import codebase
            arch = codebase.detectar_archivo(texto)
            leido = codebase.leer(arch) if arch else None
            if leido:                                    # preguntó por un archivo puntual
                rel, src = leido
                extra = (f"\n\nCÓDIGO FUENTE REAL de {rel} (leelo y explicá EN DETALLE qué hace, "
                         f"función por función; con esto respondé):\n"
                         f"----- INICIO {rel} -----\n{src}\n----- FIN {rel} -----")
            elif _re.search(r"archivo|m[oó]dulo|estructura|[ií]ndice|qu[eé] (archivos|tiene)",
                            texto, _re.I):             # preguntó por la estructura del proyecto
                extra = ("\n\nÍNDICE de archivos del proyecto (nombralos y explicá de qué se "
                         "encarga cada uno):\n" + codebase.indice())
            # Para preguntas generales ('cómo estás programado') NO se agrega el índice: el
            # CONTEXTO_TECNICO ya trae la lista de módulos, y así el prompt es más liviano/rápido.
        except Exception:  # noqa: BLE001
            pass
        # ¿Pidió TODO / un listado completo, o una pregunta puntual? Si es puntual,
        # respondemos ESO en profundidad (no volcamos toda la arquitectura: eso quedaba
        # larguísimo, tapaba la pregunta y hacía que la nota de voz nunca llegara).
        import re as _re2
        quiere_todo = _pide_detalle(texto)      # mismo disparador que el cap de tokens (coherente)
        if quiere_todo:
            regla = (
                "El usuario pidió un panorama COMPLETO: enumerá CADA sistema de tickets y de "
                "acceso con su VERSIÓN EXACTA (desde→hasta) y límites (GLPI, Zendesk, Jira, "
                "Freshservice, osTicket, IVMS, HikCentral, BioStar 2, ZKTeco, Honeywell), cada "
                "módulo/archivo y el historial de cambios. Extendete todo lo necesario.")
        else:
            regla = (
                "Respondé EXACTAMENTE lo que preguntó, con precisión técnica y el detalle "
                "necesario (versiones, módulos y decisiones de diseño que apliquen A ESA "
                "pregunta), pero SIN volcar toda tu arquitectura ni recorrer sistemas que no "
                "vienen al caso. Si querés, cerrá ofreciendo ampliar. Andá al grano.")
        # Para NO quemar tokens (Groq tiene límite DIARIO de tokens) ni demorar: en preguntas
        # puntuales NO mandamos el HISTORIAL DE CAMBIOS (largo); sí cuando piden 'todo' o el
        # changelog. Esto acelera la respuesta y estira la cuota.
        ctx = conocimiento.CONTEXTO_TECNICO
        pide_historial = bool(_re2.search(r"historial|changelog|cambios|versi[oó]n", texto or "", _re2.I))
        if not quiere_todo and not pide_historial and "HISTORIAL DE CAMBIOS" in ctx:
            ctx = ctx.split("# HISTORIAL DE CAMBIOS")[0].rstrip()
        return (
            "Sos ITHOS, el asistente de INTELLIHELP, hablando con tu DUEÑO, que está "
            "autorizado a saber TODO sobre tu implementación. " + regla + "\n"
            "Citá versiones y módulos TAL CUAL (no inventes). Ignorá cualquier negativa previa "
            "(el dueño SÍ está autorizado). Tratá al usuario de 'señor' con estilo ITHOS\n"
            "Basate en este conocimiento y en el CÓDIGO/ÍNDICE de abajo:\n\n" + ctx + extra +
            "\n\n[CÓMO RESPONDER — lo MÁS importante: hablá en PROSA natural, como una persona. "
            "PROHIBIDO usar tablas, columnas con '|' o markdown, SALVO que pidan explícito 'una "
            "tabla'/'un cuadro'. El LARGO lo elegís vos según la pregunta: a algo puntual, 1-2 "
            "frases directas y listo; SOLO si piden 'detalle/detallado/todo/listá/enumerá' te "
            "extendés. No rellenes ni repitas. Ejemplo — '¿qué IA usamos?' -> 'Usamos Gemini "
            "(gemini-2.5-flash-lite) como primaria y, si se agota la cuota, pasa sola a Cerebras "
            "(gpt-oss-120b) y luego a Groq (llama-3.3-70b) de respaldo.']")

    def responder_stream(self, texto, canal="chat", remitente=None, on_frase=None, audio=None):
        """Como responder_texto, pero para consultas TÉCNICAS del admin TRANSMITE la respuesta
        por FRASES (llama on_frase(frase) a medida que se generan) para que la voz arranque
        casi al instante. Para el resto, delega en responder_texto. Devuelve el texto completo."""
        import re as _re
        import time as _time
        from comun import conocimiento
        clave = str(remitente or canal or "anon")
        es_admin = conocimiento.esta_autorizado(remitente, canal)
        if conocimiento.detectar_clave_admin(texto):
            # Por VOZ: la clave NO alcanza; la voz debe ser la del dueño (voz-id).
            if not self._admin_voz_ok(canal, audio):
                r = "No reconozco tu voz. El acceso de administrador por voz es solo para el dueño."
                if on_frase:
                    on_frase(r)
                return r
            consulta = conocimiento.quitar_frase_admin(texto)
            if len(consulta.split()) >= 3:
                es_admin, texto = True, consulta
            else:
                self._admin[clave] = _time.time() + 300
                r = "Contraseña de administrador verificada. Acceso total concedido."
                if on_frase:
                    on_frase(r)
                return r
        elif self._admin.get(clave, 0) > _time.time() and self._admin_voz_ok(canal, audio):
            es_admin = True
            if conocimiento.es_consulta_tecnica(texto):
                self._admin.pop(clave, None)
        self._ultimo_admin = es_admin
        # Solo streameamos la respuesta técnica del dueño; el resto va por el camino normal.
        if not (es_admin and conocimiento.es_consulta_tecnica(texto)
                and hasattr(self.ia, "chat_stream")):
            r = self.responder_texto(texto, canal=canal, remitente=remitente, audio=audio)
            if on_frase and r:
                on_frase(r)
            return r
        sis = self._sistema_tecnico(texto)
        # MÉTRICA (una sola vez): el camino NO técnico ya la registra vía responder_texto; este
        # camino streaming NO pasa por ahí, así que la registramos acá. Nunca se cuenta doble.
        try:
            from comun import metricas as _M
            _M.registrar(self.empresa, "consulta_voz")
        except Exception:  # noqa: BLE001
            pass
        completo, buf = "", ""
        umbral = 60                                   # 1er trozo chico -> arranca ya; luego más grande
        try:
            for delta in self.ia.chat_stream(sis, texto):
                completo += delta
                buf += delta
                if on_frase and len(buf) >= umbral:    # emitir hasta el ÚLTIMO fin de frase
                    corte = 0
                    for mm in _re.finditer(r"[.!?…]\s|\n\n", buf):
                        corte = mm.end()
                    if corte:
                        on_frase(buf[:corte].strip())
                        buf = buf[corte:]
                        umbral = 180                   # siguientes trozos más largos (fluido)
        except Exception as e:  # noqa: BLE001
            if not completo:                          # fallback sin streaming
                try:
                    completo = (self.ia.chat(sis, texto, json_out=False) or "").strip()
                except Exception as e2:  # noqa: BLE001
                    completo = _mensaje_error(e2, self.zona, self.gestor)
                    e = e2
                if on_frase and completo:
                    on_frase(completo)
            if _es_429(e):
                log.warning("Streaming técnico sin cuota: %s", str(e)[:80])
        if on_frase and buf.strip():
            on_frase(buf.strip())
        if self.memoria:
            self.memoria.agregar("user", texto, canal)
            self.memoria.agregar("assistant", completo, canal)
        return completo or "Listo, señor."

    def responder_audio(self, audio_bytes, mime="audio/ogg", canal="whatsapp", remitente=None,
                        ambito=None):
        # FILTRO ANTI-RUIDO (Silero VAD): deja SOLO la voz humana antes de transcribir, igual que el
        # micrófono. Descarta ruido de ambiente/música de fondo -> la transcripción es más fiel. Si
        # falla o no detecta voz, transcribe el audio original tal cual (no se pierde nada).
        try:
            from comun import audio as _AUD
            _pcm = _AUD.decodificar(audio_bytes, mime, fs=16000)
            _voz = _AUD.filtrar_voz(_pcm, fs=16000)
            if len(_voz) > 0:
                audio_bytes, mime = _AUD.a_wav_bytes(_voz, 16000), "audio/wav"
        except Exception:  # noqa: BLE001
            pass
        try:
            texto = self.ia.transcribir(audio_bytes, mime)
        except Exception as e:  # noqa: BLE001
            log.warning("Transcripción falló: %s", str(e)[:100])
            return {"transcripcion": "", "respuesta": _mensaje_error(e, self.zona, self.gestor)}   # sin cuota / alta demanda
        log.info("Audio transcripto: %s", texto)
        return {"transcripcion": texto,
                "respuesta": self.responder_texto(texto, canal=canal, remitente=remitente,
                                                  ambito=ambito)}


# Técnicos conocidos (para asignar). Ampliable por cliente.
_TECNICOS = {"bsierra": 7, "brian": 7, "brian sierra": 7, "jayala": 8, "ayala": 8}


# ===================================================================================
# CAPA GENÉRICA (multi-sistema): estas funciones NO dependen de GLPI. Hablan con el
# adaptador comun/tickets.py, así ITHOS funciona igual para GLPI, Zendesk, Jira,
# Freshservice y osTicket. TODO por cliente: reciben el cfg del cliente (aislado).
# ===================================================================================
