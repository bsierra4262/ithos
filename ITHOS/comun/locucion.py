# -*- coding: utf-8 -*-
"""
Preparación del TEXTO para la LOCUCIÓN (voz), compartida por el agente (producción)
y la demo. Hace 3 cosas:
  1. sin_markdown(): saca asteriscos, numerales, viñetas (para que la voz no lea
     "asterisco", "numeral", etc.).
  2. pronunciacion(): ajusta marcas/siglas/nombres en inglés a su fonética en
     español (para las voces gratis edge/SAPI que los leen mal).
  3. humanizar(): agrega pausas naturales.
El texto que se MUESTRA (pantalla, GLPI, WhatsApp) queda intacto; esto solo cambia
lo que se PRONUNCIA. Para voces como Gemini/Charon, usar solo sin_markdown().
"""

import re

# (patrón, cómo suena) — el orden importa: lo más específico primero. AMPLIABLE.
PRONUNCIA = [
    # Empresa / entidades
    (r"INTELLIHELP\s*S\.?\s*A\.?", "Inteli jélp"),
    (r"\bINTELLIHELP\b", "Inteli jélp"),
    (r"\bSRT\s+TEST\b", "Ése Érre Té, Test"),
    (r"\bSRT\b", "Ése Érre Té"),
    (r"\bITH\b", "I Té Áche"),
    # Siglas técnicas (deletreadas)
    (r"\bGLPI\b", "Ge Éle Pe I"),
    (r"\bIVMS\b", "I Ve Éme Ése"),
    (r"\bHikCentral\b", "Jik Céntral"),
    (r"\bBioStar\s*2?\b", "Báio Star dos"),
    (r"\bZKTeco\b", "Zeta Ka Téco"),
    (r"\bHoneywell\b", "Jóni Güel"),
    (r"\bSLA\b", "Ése Éle A"),
    (r"\bTTO\b", "Te Te O"),
    (r"\bTTR\b", "Te Te Érre"),
    (r"\bAPI\b", "A Pe I"),
    (r"\bITIL\b", "Itil"),
    (r"\bKVM\b", "Ka Ve Éme"),
    (r"\bHTTPS\b", "Áche Te Te Pe Ése"),
    (r"\bWSS\b", "Doble Ve Ése Ése"),
    (r"\bSQL\b", "Ése Cu Éle"),
    (r"\bQR\b", "Cu Érre"),
    (r"\bURL\b", "U Érre Éle"),
    (r"\bID\b", "I Dé"),
    (r"\bPC\b", "Pe Cé"),
    # Multiplicador de velocidad 'x' (NO 'equis'): x1.25 -> "por uno punto veinticinco"
    (r"\bx\s*1[.,]25\b", "por uno punto veinticinco"),
    (r"\bx\s*1[.,]5\b", "por uno punto cinco"),
    (r"\bx\s*(\d+)[.,](\d+)\b", r"por \1 punto \2"),   # otro x<decimal> -> "por N punto M"
    (r"(?<=[\s(])x(?=\d)", "por "),                     # x2, x3 (multiplicador) -> "por "
    # Modelos de IA exactos (compuestos: ANTES de los genéricos Gemini/Groq de abajo)
    (r"\bgpt-?oss-?120b\b", "Ge Pe Te óss, ciento veinte bé"),
    (r"\bgemini-?2\.5-?flash-?lite\b", "Gémini dos punto cinco, flash láit"),
    (r"\bgemini-?2\.5-?flash\b", "Gémini dos punto cinco flash"),
    (r"\bflash-?lite\b", "flash láit"),
    (r"\bllama-?3\.3-?70b\b", "Yáma tres punto tres, setenta bé"),
    (r"\bCerebras\b", "Sérebras"),
    (r"\bfallback\b", "fólbak"),
    (r"\bTPM\b", "Te Pe Éme"),
    (r"\bTPD\b", "Te Pe Dé"),
    (r"\bRPD\b", "Érre Pe Dé"),
    (r"\bRPM\b", "Érre Pe Éme"),
    (r"\bopus\b", "ópus"),
    (r"\bsonnet\b", "sónet"),
    (r"\bhaiku\b", "jáiku"),
    # HORAS HH:MM dichas como humano (no 'cero cuatro cero cero'): 04:00 -> '4 en punto',
    # 14:30 -> '14 y 30'. La franja AM/PM la agrega _fmt_reset ('las 4 de la mañana').
    (r"\b0*(\d{1,2}):00\b", r"\1 en punto"),
    (r"\b0*(\d{1,2}):(\d{2})(?::\d{2})?\b", r"\1 y \2"),
    # Símbolos y unidades comunes
    (r"%", " por ciento"),
    (r"(?<=\d)\s*°", " grados"),
    (r"\bversi[oó]n\b", "versión"),
    (r"\bvs\.?\b", "versus"),
    (r"\bOK\b", "o káy"),
    (r"\bemails?\b", "iméils"),
    (r"\bapps?\b", "aps"),
    (r"\blinks?\b", "línks"),
    (r"\bstatus\b", "státus"),
    (r"\bticketing\b", "tíketin"),
    (r"\bworkflow\b", "guórkflou"),
    (r"\bdeploy\b", "diplói"),
    (r"\bcommit\b", "cómit"),
    (r"\bqueue\b", "kiú"),
    (r"\bthread\b", "zréd"),
    (r"\blog(s)?\b", r"lóg\1"),
    (r"\bproxy\b", "próxi"),
    (r"\bnginx\b", "énllin éx"),
    # Más términos frecuentes (inglés/tech/negocio/marcas) dichos como se pronuncian de verdad
    (r"\bupdate\b", "apdéit"), (r"\bupgrade\b", "apgréid"), (r"\bdownload\b", "daunlóud"),
    (r"\bupload\b", "aplóud"), (r"\brelease\b", "rilís"), (r"\bfeature\b", "fícher"),
    (r"\bbug(s)?\b", r"bág\1"), (r"\bpatch\b", "pách"), (r"\bmerge\b", "merch"),
    (r"\bbranch\b", "bránch"), (r"\brepo\b", "rípo"), (r"\bGitHub\b", "Guit Jáb"),
    (r"\bGitLab\b", "Guit Láb"), (r"\bKubernetes\b", "Kubernétis"), (r"\bcontainer\b", "contéiner"),
    (r"\bmicroservice(s)?\b", r"maicro sérvis\1"), (r"\bserverless\b", "sérverles"),
    (r"\blambda\b", "lámda"), (r"\bworker(s)?\b", r"guórker\1"), (r"\bcron\b", "cron"),
    (r"\bscheduler\b", "skédiuler"), (r"\bpipeline\b", "páiplain"), (r"\blatency\b", "léitensi"),
    (r"\bscalable\b", "eskéilabl"), (r"\bREST\b", "rést"), (r"\bGraphQL\b", "Graf Cu Éle"),
    (r"\bSSL\b", "Ése Ése Éle"), (r"\bTLS\b", "Te Éle Ése"), (r"\bAWS\b", "A Doble Ve Ése"),
    (r"\bAzure\b", "Áshur"), (r"\bNvidia\b", "Envídia"), (r"\bIntel\b", "Íntel"),
    (r"\bAmazon\b", "Ámazon"), (r"\bMeta\b", "Méta"), (r"\bFacebook\b", "Féisbuk"),
    (r"\bInstagram\b", "Ínstagram"), (r"\bYouTube\b", "Iútiub"), (r"\bLinkedIn\b", "Línkedin"),
    (r"\bclient\b", "cláient"), (r"\bbrowser\b", "bráuser"), (r"\bcookie(s)?\b", r"cúki\1"),
    (r"\bsession\b", "séshion"), (r"\bdebug\b", "dibág"), (r"\bmeeting\b", "mítin"),
    (r"\bmanager\b", "mánayer"), (r"\breport(s)?\b", r"ripórt\1"), (r"\bsetup\b", "sétap"),
    (r"\bserver(s)?\b", r"sérver\1"), (r"\brequest(s)?\b", r"rikuést\1"),
    (r"\bresponse(s)?\b", r"rispóns\1"), (r"\bdefault\b", "difólt"), (r"\bwrapper\b", "guáper"),
    # Marcas / productos / tecnologías
    (r"\bWhatsApp Business\b", "Guasáp bísnes"),
    (r"\bWhatsApp\b", "Guasáp"),
    (r"\bHelpdesk\b", "Jélp désk"),
    (r"\bWindows Server\b", "Güíndous Sérver"),
    (r"\bWindows\b", "Güíndous"),
    (r"\bGoogle\b", "Gúgl"),
    (r"\bGemini\b", "Gémini"),
    (r"\bGroq\b", "Grók"),
    (r"\bGrok\b", "Grók"),
    (r"\bClaude\b", "Clód"),
    (r"\bChatGPT\b", "Chat Ye Pe Té"),
    (r"\bOpenAI\b", "Óupen A I"),
    (r"\bDeepSeek\b", "Dip Sík"),
    (r"\bOllama\b", "Oyáma"),
    (r"\bZendesk\b", "Séndesk"),
    (r"\bFreshservice\b", "Frésh sérvis"),
    (r"\bosTicket\b", "O Ése Tíket"),
    (r"\bTeams\b", "Tíms"),
    (r"\bSlack\b", "Slák"),
    (r"\bTelegram\b", "Télegram"),
    (r"\bPicovoice\b", "Píco vóis"),
    (r"\bPorcupine\b", "Pórkiupain"),
    (r"\bCharon\b", "Cáron"),
    (r"\btickets\b", "tíkets"),
    (r"\bticket\b", "tíket"),
    (r"\bsoftware\b", "sóftgüer"),
    (r"\bhardware\b", "járdgüer"),
    (r"\blogin\b", "lógin"),
    (r"\bemail\b", "iméil"),
    (r"\be-mail\b", "iméil"),
    (r"\bmail\b", "méil"),
    (r"\bonline\b", "onláin"),
    (r"\boffline\b", "ofláin"),
    (r"\bbackup\b", "bákap"),
    (r"\bhosting\b", "jóstin"),
    (r"\bHostinger\b", "Jóstinguer"),
    (r"\bcloud\b", "cláud"),
    (r"\bDocker\b", "Dóker"),
    (r"\bCaddy\b", "Cádi"),
    (r"\bLinux\b", "Línux"),
    (r"\bUbuntu\b", "Ubúntu"),
    (r"\bSQL Server\b", "Ése Cu Éle Sérver"),
    (r"\bPython\b", "Páiton"),
    (r"\bWhisper\b", "Güísper"),
    (r"\bMicrosoft\b", "Máicrosoft"),
    (r"\bAnthropic\b", "Anzrópic"),
    (r"\bxAI\b", "Équis A I"),
    (r"\bAndroid\b", "Ándroid"),
    (r"\biOS\b", "Ái O Ése"),
    (r"\biPhone\b", "Áifon"),
    # Más siglas
    (r"\bRR\.?\s?HH\.?\b", "Recursos Humanos"),
    (r"\bDNI\b", "De Éne I"),
    (r"\bVPN\b", "Ve Pe Éne"),
    (r"\bDNS\b", "De Éne Ése"),
    (r"\bIP\b", "I Pe"),
    (r"\bUSB\b", "U Ése Be"),
    (r"\bGPU\b", "Ge Pe U"),
    (r"\bCPU\b", "Ce Pe U"),
    (r"\bRAM\b", "Ram"),
    (r"\bSSD\b", "Ése Ése Dé"),
    (r"\bWi-?Fi\b", "Guái Fai"),
    (r"\bNFC\b", "Éne Éfe Ce"),
    (r"\bRFID\b", "Érre Éfe I Dé"),
    (r"\bPDF\b", "Pe Dé Éfe"),
    (r"\bJSON\b", "Yeisón"),
    (r"\bHTML\b", "Áche Te Éme Éle"),
    (r"\bCRM\b", "Ce Érre Éme"),
    (r"\bERP\b", "É Érre Pe"),
    (r"\bSaaS\b", "Sas"),
    (r"\bVPS\b", "Ve Pe Ése"),
    (r"\bLAN\b", "Lan"),
    (r"\bTOTP\b", "Te O Te Pe"),
    (r"\bOTP\b", "O Te Pe"),
    # Nombres propios
    (r"\bBrian\b", "Bráian"),
    (r"\bNicolas\b", "Nicolás"),
    (r"\bAyala\b", "Ayála"),
    (r"\bBaldelli\b", "Baldélli"),
    # Productos/plataformas de acceso y tickets
    (r"\bHikvision\b", "Jikvíchon"),
    (r"\bHikCentral\b", "Jik Céntral"),
    (r"\bZKBio\s*CVSecurity\b", "Zeta Ka Báio Ce Ve Sekiúriti"),
    (r"\bZKBio(Time| CVSecurity)?\b", "Zeta Ka Báio"),
    (r"\bBioTime\b", "Báio Táim"),
    (r"\bArtemis\b", "Ártemis"),
    (r"\bSuprema\b", "Supréma"),
    (r"\bPro-?Watch\b", "Pro Guóch"),
    (r"\bWIN-?PAK\b", "Güin Pak"),
    (r"\bMAXPRO\b", "Max Pro"),
    (r"\bMercadoPago\b", "Mercádo Págo"),
    (r"\bMercadoLibre\b", "Mercádo Líbre"),
    (r"\bBNA\b", "Be Éne A"),
    (r"\bBanco Naci[oó]n\b", "Bánco Nación"),
    (r"\bFastAPI\b", "Fást A Pe I"),
    (r"\bWebSocket\b", "Güéb Sóket"),
    (r"\bwebhook\b", "güébjuk"),
    (r"\bendpoint\b", "éndpoint"),
    (r"\btokens\b", "tókens"),
    (r"\btoken\b", "tóken"),
    (r"\bLlama\b", "Yáma"),
    (r"\bWhisper\b", "Güísper"),
    (r"\bSilero\b", "Siléro"),
    (r"\bONNX\b", "O Éne Éne Équis"),
    (r"\bedge-?tts\b", "Éch Te Te Ése"),
    (r"\bSAPI\b", "Sápi"),
    (r"\bODBC\b", "O De Be Ce"),
    (r"\bHMAC\b", "Áche Mac"),
    (r"\bJWT\b", "Yot"),
    (r"\bMySQL\b", "Mái Ése Cu Éle"),
    (r"\bPyMySQL\b", "Pái Mái Ése Cu Éle"),
    (r"\bIMAP\b", " Imap"),
    (r"\bSMTP\b", "Ése Éme Te Pe"),
    (r"\bSSML\b", "Ése Ése Éme Éle"),
    # Términos de negocio / técnicos comunes
    (r"\bdashboard\b", "dásbord"),
    (r"\bfeedback\b", "fídbak"),
    (r"\bframework\b", "fréimguork"),
    (r"\bstreaming\b", "strímin"),
    (r"\bmachine learning\b", "machín lérnin"),
    (r"\bdeep learning\b", "díp lérnin"),
    (r"\bembedding\b", "embédin"),
    (r"\bembeddings\b", "embédins"),
    (r"\bdataset\b", "déitaset"),
    (r"\bscript\b", "scrípt"),
    (r"\bprompt\b", "prómpt"),
    (r"\bchatbot\b", "chátbot"),
    (r"\bbot\b", "bot"),
    (r"\bfrontend\b", "fronténd"),
    (r"\bbackend\b", "bakénd"),
    (r"\bmiddleware\b", "mídelguer"),
    (r"\bcache\b", "cash"),
    (r"\bfirewall\b", "fáiaguol"),
    (r"\bgateway\b", "guéitguei"),
    (r"\bcluster\b", "cláster"),
    (r"\bDevOps\b", "Dev Óps"),
    (r"\bfailover\b", "féilóver"),
    (r"\buptime\b", "áptaim"),
    (r"\bdowntime\b", "dáuntaim"),
    (r"\btimeout\b", "táimaut"),
    (r"\brollback\b", "rólbak"),
    (r"\bhotfix\b", "jótfix"),
    (r"\bstartup\b", "stártap"),
    (r"\bonboarding\b", "onbórdin"),
    (r"\bmultitenant\b", "multi ténant"),
    (r"\bmulti-?tenant\b", "multi ténant"),
    (r"\btriage\b", "triách"),
    (r"\bpolling\b", "pólin"),
    (r"\bMFA\b", "Éme Éfe A"),
    (r"\b2FA\b", "Dos Éfe A"),
    (r"\bOAuth\b", "O Óz"),
    (r"\bSSO\b", "Ése Ése O"),
    (r"\bKPI\b", "Ka Pe I"),
    (r"\bROI\b", "Érre O I"),
    (r"\bMTTR\b", "Éme Te Te Érre"),
    (r"\bB2B\b", "Be Dos Be"),
    (r"\bB2C\b", "Be Dos Ce"),
]

_PAUSA_INICIO = ("Atención", "Aviso", "Importante", "Bienvenido", "Bienvenida",
                 "Buenas", "Buen día", "Hola")


def sin_markdown(texto):
    """Saca markdown para que la voz NO lea 'asterisco', 'numeral', etc."""
    t = texto or ""
    t = re.sub(r"`+", "", t)                       # code
    t = re.sub(r"(?m)^\s*#+\s*", "", t)            # títulos #
    t = re.sub(r"\*+", "", t)                      # * ** (negrita/itálica/viñeta)
    t = re.sub(r"(?m)^\s*[-•]\s+", "", t)          # viñetas - •
    t = re.sub(r"_(.+?)_", r"\1", t)               # _itálica_
    t = re.sub(r"~(.+?)~", r"\1", t)               # ~tachado~
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


# Extensiones de archivo -> cómo se DICEN (entendible al escuchar, ej. "ia punto pi").
_EXT_HABLADA = {
    "py": " punto pi", "json": " punto yeisón", "onnx": " punto o ene ene equis",
    "md": " punto eme de", "txt": " punto texto", "sql": " punto ese cu ele",
    "sqlite3": " base de datos", "sqlite": " base de datos", "js": " punto yota ese",
    "ts": " punto te ese", "html": " punto hache te eme ele", "css": " punto ce ese ese",
    "sh": " punto ese hache", "bat": " punto bat", "ps1": " punto pe ese uno",
    "ini": " punto ini", "cfg": " punto config", "yml": " punto yaml", "yaml": " punto yaml",
    "env": " punto env", "log": " punto log",
}


_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emojis: pictogramas, emoticones, transporte, símbolos ext-A, banderas
    "\U00002600-\U000027BF"   # símbolos varios + dingbats (☀ ⚠ ✅ ✔ ✍ ➡ …)
    "\U00002300-\U000023FF"   # técnicos (⏸ ⏱ ⌚ …)
    "\U00002B00-\U00002BFF"   # flechas/estrellas (⭐ ⬅ …)
    "\U00002190-\U000021FF"   # flechas (← ↑ ↓ ↔ …); → y -> ya los pasa sin_tecnicismos antes
    "\U00002460-\U000024FF"   # alfanuméricos encerrados (Ⓜ …)
    "\U0000FE00-\U0000FE0F"   # selectores de variación (el ️ de ⚠️)
    "\U00002122\U000000A9\U000000AE"                       # ™ © ®
    "\U00003030\U0000303D\U00003297\U00003299"            # marcas CJK usadas como emoji (〰 ㊗ ㊙ …)
    "\U00002139\U0000203C\U00002049\U000020E3\U0000200D"  # ℹ ‼ ⁉ ⃣ y ZWJ de secuencias
    "]+", flags=re.UNICODE)


def sin_emojis(texto):
    """Saca los EMOJIS/pictogramas de lo que se PRONUNCIA: la voz NO debe leerlos (ni su nombre ni
    un símbolo raro). El texto que se MUESTRA (WhatsApp/pantalla/GLPI) queda INTACTO. Punto único,
    aplica a TODA la voz (agente portero/respuestas + notas de WhatsApp, Charon y edge)."""
    t = _EMOJI.sub(" ", texto or "")
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def sin_tecnicismos(texto):
    """Hace 'hablable' la notación técnica: no dice 'barra diagonal' ni 'punto pe y', pero SÍ
    dice las cosas de forma ENTENDIBLE al escuchar (ej. 'ia.py' -> 'ia punto pi', '+' -> 'más',
    lo entre paréntesis como aside con pausas). Solo afecta lo que se PRONUNCIA."""
    t = texto or ""
    # 'ITHOS' -> 'ITHOS' (fluido, no deletreado letra por letra). ANTES de tocar los puntos.
    t = re.sub(r"\bJ\.?A\.?R\.?V\.?I\.?S\.?", "ITHOS", t, flags=re.IGNORECASE)
    # Números con separador de MILES -> sin separador: así edge dice 'un millón' / 'treinta mil'
    # (no 'uno punto cero cero cero…'). Agrupa de a 3 dígitos; NO toca decimales '2.5' ni versiones.
    t = re.sub(r"\b\d{1,3}(?:[.,]\d{3})+\b",
               lambda m: m.group(0).replace(".", "").replace(",", ""), t)
    t = t.replace("→", " a ").replace("->", " a ").replace("=>", " a ")
    t = t.replace("&", " y ")
    t = t.replace("·", ", ").replace("•", ", ")       # separadores -> pausa (la voz no los lee)
    t = re.sub(r"(?<=\w)\+(?=\w)", " más ", t)        # a+b -> a más b
    t = re.sub(r"\s\+\s", " más ", t)                 # " + " -> " más "
    # Extensiones de archivo -> forma hablada entendible (ia.py -> "ia punto pi")
    t = re.sub(r"\.([A-Za-z0-9]+)\b",
               lambda m: _EXT_HABLADA.get(m.group(1).lower(), "." + m.group(1)), t)
    t = re.sub(r"[`~|*#]", " ", t)                    # backticks, pipes, markdown suelto
    t = t.replace("/", " ").replace("\\", " ")        # barras -> espacio (no 'barra diagonal')
    t = t.replace("_", " ")                           # snake_case -> palabras
    # Paréntesis -> aside con pausas (que se entienda que es una aclaración)
    t = t.replace("(", "… ").replace(")", " …")
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def pronunciacion(texto):
    t = sin_emojis(texto or "")            # la voz NO lee emojis (también en el camino de streaming)
    for pat, rep in PRONUNCIA:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    return t


def humanizar(texto):
    """Pausas y respiración para una locución NATURAL (no un chorro sin puntuación):
    pausa por ítem de lista/renglón, punto y aparte, dos puntos y guiones."""
    t = (texto or "").strip()
    for w in _PAUSA_INICIO:
        if t.startswith(w + ".") or t.startswith(w + ","):
            t = w + "… " + t[len(w) + 1:].lstrip()
            break
        if t.startswith(w + " "):
            t = w + "… " + t[len(w) + 1:]
            break
    t = re.sub(r"\n{2,}", " …… ", t)              # punto y aparte -> pausa larga
    t = t.replace("\n", " … ")                     # cada renglón / ítem de lista -> pausa
    t = re.sub(r":(\s)", r": … ", t)               # después de dos puntos -> pausa (no en 10:59)
    t = re.sub(r";", ", ", t)                       # punto y coma -> coma
    t = t.replace(" — ", "… ").replace(" – ", "… ").replace(" - ", "… ")
    t = re.sub(r"\bTicket número\b", "Ticket, número", t)
    t = re.sub(r"\bAsignado a\b", "Asignado a,", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def preparar(texto, fonetica=True, pausas=True):
    """Pipeline completo para TTS. fonetica=True para voces gratis (edge/SAPI);
    fonetica=False para Gemini/Charon (pronuncia bien los nombres, solo limpia markdown).
    pausas=False para Gemini/Charon: NO inserta pausas con '…'. Gemini CORTA la palabra que sigue a
    un '…' (bug real: 'Bienvenido… Noemi' -> se comía 'Noemi'); Charon ya prosodia solo y no las
    necesita. Las voces gratis (edge/SAPI) sí las quieren para no sonar robóticas -> pausas=True."""
    t = sin_tecnicismos(texto)             # 1º rutas/símbolos (antes de que el markdown coma los _)
    t = sin_emojis(t)                      # la voz NO lee emojis (punto único, aplica a toda la voz)
    t = sin_markdown(t)
    if fonetica:
        t = pronunciacion(t)
    return humanizar(t) if pausas else re.sub(r"[ \t]{2,}", " ", t).strip()
