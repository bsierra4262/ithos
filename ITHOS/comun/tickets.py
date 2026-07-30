#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adaptador GENÉRICO de sistemas de tickets. Todo lo que hace ITHOS (KB, acciones del
agente, reportes, proactivo) habla con ESTA interfaz común, así funciona igual para
GLPI, Zendesk, Freshservice, Jira, osTicket, etc. Cada sistema se enchufa por su
adaptador. GLPI está 100% implementado; los demás usan comun/tickets_otros.py (se
completan/activan por cliente).

Interfaz común (todos exponen lo que puedan; lo no soportado avisa):
  abiertos() -> [ {id, asunto, estado} ]
  resueltos(n) -> [ {id, asunto, problema, solucion} ]   (para la base de conocimiento)
  estado(id) -> str
  responder(id, texto) -> str
  crear(asunto, contenido) -> id
  cambiar_estado(id, 'cerrado'|'reabrir'|'en_espera'|'en_curso') -> str
  cambiar_prioridad(id, 'baja'|'media'|'alta'|'urgente') -> str
  asignar(id, tecnico) -> str
  buscar(texto) -> [ {id, asunto} ]
  sla() -> dict
"""

_TECNICOS = {"bsierra": 7, "brian": 7, "brian sierra": 7, "jayala": 8, "ayala": 8}
_PRIO = {"baja": 2, "media": 3, "alta": 4, "urgente": 5}
_PRIO_TXT = {1: "Muy baja", 2: "Baja", 3: "Media", 4: "Alta", 5: "Muy alta", 6: "Mayor"}
_ESTADO = {"cerrado": 6, "reabrir": 2, "en_curso": 2, "en_espera": 4, "resuelto": 5}
_ESTADO_TXT = {1: "Nuevo", 2: "En curso", 3: "Planificado", 4: "En espera",
               5: "Resuelto", 6: "Cerrado"}
# SLA por prioridad -> (horas para PRIMERA RESPUESTA/TTO, horas para RESOLUCIÓN/TTR).
# Respaldo si el cliente NO tiene definiciones SLA/OLA en GLPI (se fijan las fechas a mano).
_SLA_HORAS = {"urgente": (1, 4), "alta": (2, 8), "media": (4, 24), "baja": (8, 72)}

# CICLO IGUAL A LA DEMO (triage): en GLPI el SLA/OLA se aplica por IDs de DEFINICIÓN, y GLPI
# calcula solo el TTO/TTR EXTERNO y el INTERNO (TTO interno / TTR interno). El nivel sale de la
# prioridad. Estos IDs son los de SRT/ITH; se pueden pisar por cliente en integrador_glpi.
_NIVEL_SLA_DEFAULT = {
    "LEVE":      {"slas_id_tto": 1, "slas_id_ttr": 6, "olas_id_tto": 1, "olas_id_ttr": 2},
    "GRAVE":     {"slas_id_tto": 2, "slas_id_ttr": 3, "olas_id_tto": 4, "olas_id_ttr": 3},
    "MUY GRAVE": {"slas_id_tto": 4, "slas_id_ttr": 5, "olas_id_tto": 5, "olas_id_ttr": 6},
}
_NIVEL_POR_PRIO = {"baja": "LEVE", "media": "LEVE", "alta": "GRAVE", "urgente": "MUY GRAVE"}


def _norm_id(tid):
    """Deja SOLO el número del ticket. Clave: el modelo suele mandar '#597' y en una URL el
    '#' es separador de fragmento -> '/Ticket/#597' pega a '/Ticket/' (¡sin id!) y la escritura
    se pierde en silencio. Con esto '#597', ' 597 ', 'ticket 597' -> '597'."""
    import re as _re
    m = _re.search(r"\d+", str(tid if tid is not None else ""))
    return m.group(0) if m else str(tid or "")


# Palabras que no describen el CASO. Van dos grupos: las de relleno del idioma y —igual de
# importante— el vocabulario con que se PREGUNTA por un ticket ("los que ya resolvimos…").
# Si no se descartan, "resolvimos" o "cerramos" terminan pesando más que el problema en sí y la
# búsqueda trae los tickets donde alguien escribió esa palabra en un comentario cualquiera.
_STOP = {"que", "los", "las", "del", "para", "por", "con", "una", "unos", "unas", "pero", "como",
         "este", "esta", "esto", "esos", "esas", "eso", "sus", "les", "the", "and", "sin", "más",
         "mas", "muy", "son", "fue", "hay", "todo", "todos", "toda", "todas", "ese", "esa",
         "decime", "deci", "dame", "quiero", "necesito", "tickets", "ticket", "ithos", "hey",
         "resolvimos", "resolver", "resolvieron", "resuelto", "resueltos", "resuelta", "resueltas",
         "solucionamos", "solucionaron", "cerramos", "cerraron", "cerrado", "cerrados",
         "tuvimos", "hicimos", "pasaron", "buscame", "busca", "buscar", "mostrame", "traeme",
         "similar", "similares", "parecido", "parecidos", "mismo", "misma", "caso", "casos",
         "modelo", "ejemplo", "ejemplos", "anteriores", "anterior", "antes", "cuales", "cual",
         "donde", "cuando", "sobre", "acerca", "tema", "temas", "algun", "alguno", "alguna"}


def _normalizar(s):
    """minúsculas y sin tildes, para comparar texto escrito de cualquier manera."""
    import re as _re
    import unicodedata as _ud
    t = _ud.normalize("NFD", str(s or "").lower())
    t = "".join(ch for ch in t if _ud.category(ch) != "Mn")
    return _re.sub(r"\s+", " ", _re.sub(r"[^a-z0-9ñ]+", " ", t))


def _palabras(s):
    """Los términos con contenido de una consulta (sin muletillas ni palabras de relleno)."""
    vistas, out = set(), []
    for w in _normalizar(s).split():
        if len(w) >= 4 and w not in _STOP and w not in vistas:
            vistas.add(w)
            out.append(w)
    return out


def _raiz(palabra):
    """Raíz aproximada, para que 'fichadas', 'fichada' y 'fichaje' se reconozcan como lo mismo.
    Sin diccionario ni dependencias: recorta la palabra a su comienzo (mínimo 4 letras)."""
    return palabra[:max(4, min(6, len(palabra) - 3))]


def _contiene(palabra, heno, heno_junto):
    """¿El texto habla de esta palabra? Tolera el plural/la conjugación (por la raíz) y que el
    producto esté escrito separado o junto ('hik central' ↔ 'hikcentral')."""
    if palabra in heno or palabra in heno_junto:
        return True
    r = _raiz(palabra)
    return r in heno or r in heno_junto


# Cierres que NO son una solución técnica: el ticket se cerró por un tema administrativo (la
# categoría estaba mal, era duplicado, el cliente no contestó). Como modelo de resolución no
# sirven —un experto de mesa de ayuda no los ofrece como "así lo resolvimos"—, así que no se
# presentan como solución; el caso sí puede mostrarse, aclarando que quedó sin resolución real.
_ADMINISTRATIVO = (
    "colocar como corresponde las categor", "cambio de la categoria correspondiente",
    "la categoria no corresponde", "categoria no era correcta", "categoria incorrecta",
    "se cerrara inmediatamente", "cambiar la categoria", "mal cargad", "mal ingresad",
    "ticket duplicad", "es duplicado", "cerrado por falta de respuesta",
    "sin respuesta del cliente", "reingresar el ticket", "vuelva a generar el ticket",
)


def _cierre_administrativo(texto):
    t = _normalizar(texto)
    return any(_normalizar(m) in t for m in _ADMINISTRATIVO)


# Histórico ya leído, por cliente: {(url, entidad, estados): (cuándo, documentos)}.
_CORPUS = {}
_CORPUS_TTL = 600            # 10 minutos


def _sin_html(s):
    """Texto plano legible desde el HTML que guarda GLPI en descripciones/seguimientos.
    GLPI suele DOBLE-escapar (guarda '&#60;p&#62;' por '<p>'), así que desescapamos dos
    veces, convertimos <br>/<p> en saltos y sacamos el resto de las etiquetas."""
    import re as _re
    import html as _html
    t = _html.unescape(_html.unescape(str(s or "")))     # &#60; -> < ; &amp;lt; -> < ...
    t = _re.sub(r"<\s*br\s*/?>|</\s*p\s*>", "\n", t, flags=_re.I)
    t = _re.sub(r"<[^>]+>", " ", t)                       # resto de etiquetas
    return _re.sub(r"[ \t]+", " ", t).strip()


class _GLPI:
    def __init__(self, cli_cfg):
        self.gl = cli_cfg.get("integrador_glpi") or {}
        self.ent = int(self.gl.get("entity_id", 0))
        # TOKENS por ROL (como los pasó Brian): ITHOS = el agente (clon del helpdesk), escribe;
        # SUPER ADMIN = acceso total (leer catálogo de categorías/usuarios, borrar); HELPDESK =
        # el técnico (bsierra). Cada uno mantiene su PROPIA sesión viva en el pool y se reutiliza.
        self.tok = self.gl.get("glpi_ithos_token")                      # agente (escribe)
        self.tok_admin = (self.gl.get("glpi_superadmin_token")
                          or self.gl.get("glpi_user_token") or self.tok)  # super admin (total)
        self.tok_helpdesk = self.gl.get("glpi_bsierra_token") or self.tok  # técnico helpdesk
        self.ithos_id = int(self.gl.get("ithos_user_id", 28))
        self.niveles_sla = self.gl.get("niveles_sla") or _NIVEL_SLA_DEFAULT

    def _c(self, token=None):
        # SESIÓN VIVA reutilizada del pool (no abre/cierra por llamada -> rápido, no agota).
        from comun import glpi as G
        return G.sesion(self.gl, token or self.tok)

    def _c_admin(self):
        return self._c(self.tok_admin)

    def _ent(self, ts):
        from comun import glpi as G
        return G.de_entidad(ts, self.ent)

    def abiertos(self):
        c = self._c()
        try:
            ts = self._ent(c.tickets_recientes(40))
        finally:
            c.cerrar()
        return [{"id": t["id"], "asunto": t.get("name", ""),
                 "estado": _ESTADO_TXT.get(int(t.get("status", 0)), "?")}
                for t in ts if int(t.get("status", 0)) in (1, 2, 4)]

    def resueltos(self, n=80):
        c = self._c()
        out = []
        try:
            ts = self._ent(c.tickets_recientes(n))
            for t in ts:
                if int(t.get("status", 0)) not in (5, 6):
                    continue
                sol = self._solucion(c, t["id"])
                if not sol:
                    continue
                out.append({"id": t["id"], "asunto": t.get("name", ""),
                            "problema": t.get("content", ""), "solucion": sol})
        finally:
            c.cerrar()
        return out

    def _solucion(self, c, tid):
        try:
            s = c.request(f"/Ticket/{tid}/ITILSolution")
            if s:
                return s[-1].get("content", "")
            f = c.request(f"/Ticket/{tid}/ITILFollowup")
            if f:
                return f[-1].get("content", "")
        except Exception:  # noqa: BLE001
            pass
        return ""

    def estado(self, tid):
        tid = _norm_id(tid)
        c = self._c()
        try:
            t = c.request(f"/Ticket/{tid}")
        finally:
            c.cerrar()
        return f"#{tid}: {t.get('name')} — {_ESTADO_TXT.get(int(t.get('status', 0)), '?')}"

    def asignados_a(self, glpi_id):
        """Tickets ABIERTOS (nuevo/en curso/en espera) donde el usuario es el TÉCNICO ASIGNADO
        ('Asignado a' = Ticket_User type=2, campo de búsqueda 5 en GLPI). NO incluye los tickets
        donde la persona es solicitante u observador. Devuelve [{id, asunto, estado}]."""
        try:
            gid = int(glpi_id)
        except (TypeError, ValueError):
            return []
        c = self._c()
        try:
            q = ("/search/Ticket?criteria[0][field]=5&criteria[0][searchtype]=equals"
                 f"&criteria[0][value]={gid}"
                 "&forcedisplay[0]=2&forcedisplay[1]=1&forcedisplay[2]=12&range=0-300")
            r = c.request(q)
        finally:
            c.cerrar()
        out = []
        for d in (r.get("data") or []):
            try:
                est = int(d.get("12") or 0)
            except (TypeError, ValueError):
                est = 0
            if est in (1, 2, 4):                       # abierto: nuevo / en curso / en espera
                out.append({"id": int(d.get("2")), "asunto": str(d.get("1") or ""),
                            "estado": _ESTADO_TXT.get(est, "?")})
        return out

    def responder(self, tid, texto):
        tid = _norm_id(tid)
        c = self._c()
        try:
            c.request("/ITILFollowup", "POST", {"input": {
                "itemtype": "Ticket", "items_id": tid, "content": texto}})
        finally:
            c.cerrar()
        return f"💬 Respondí al cliente en el ticket #{tid}."

    def crear(self, asunto, contenido):
        c = self._c()
        try:
            r = c.request("/Ticket", "POST", {"input": {
                "name": asunto, "content": contenido, "entities_id": self.ent}})
        finally:
            c.cerrar()
        return f"🆕 Ticket #{r.get('id')} creado."

    def cambiar_estado(self, tid, estado):
        tid = _norm_id(tid)
        c = self._c()
        try:
            c.request(f"/Ticket/{tid}", "PUT",
                      {"input": {"status": _ESTADO.get(estado, 2)}})
        finally:
            c.cerrar()
        return f"Ticket #{tid} → {estado}."

    def cambiar_prioridad(self, tid, prio):
        tid = _norm_id(tid)
        n = _PRIO.get(str(prio).lower(), 3)
        c = self._c()
        try:                                               # urgencia+impacto+prioridad (como la demo)
            c.request(f"/Ticket/{tid}", "PUT",
                      {"input": {"urgency": n, "impact": n, "priority": n}})
        finally:
            c.cerrar()
        return f"Ticket #{tid} → prioridad {prio}."

    def asignar(self, tid, tecnico):
        tid = _norm_id(tid)
        uid = _TECNICOS.get(str(tecnico).lower().strip())
        if not uid:
            return f"No reconozco al técnico '{tecnico}'."
        c = self._c()
        # Como la demo: además del técnico, ITHOS queda asignado al ticket.
        for u in (self.ithos_id, uid):
            try:
                c.request("/Ticket_User", "POST",
                          {"input": {"tickets_id": tid, "users_id": u, "type": 2}})
            except Exception:  # noqa: BLE001
                pass
        c.cerrar()
        return f"👤 Ticket #{tid} asignado a {tecnico} (+ ITHOS)."

    def buscar(self, texto):
        """Búsqueda simple por texto sobre TODO el histórico (no sólo los últimos): acepta que
        coincida la frase completa o la mayoría de sus palabras, para que 'no puede fichar Juan'
        encuentre el ticket aunque esté redactado distinto."""
        c = self._c()
        try:
            ts = self._ent(c.todos_tickets())
        finally:
            c.cerrar()
        pal = _palabras(texto)
        if not pal:
            return []
        out = []
        for t in ts:
            heno = _normalizar(f"{t.get('name', '')} {_sin_html(t.get('content', ''))}")
            junto = heno.replace(" ", "")
            aciertos = sum(1 for w in pal if _contiene(w, heno, junto))
            if aciertos >= max(1, int(len(pal) * 0.6)):
                out.append((aciertos, t))
        out.sort(key=lambda x: (-x[0], -int(x[1].get("id", 0))))
        return [{"id": t["id"], "asunto": t.get("name", "")} for _, t in out[:8]]

    def casos_similares(self, descripcion, tope=25, estados=(4, 5, 6)):
        """CASOS PARECIDOS sobre TODO el histórico del cliente, con su RESOLUCIÓN REAL: la
        materia prima para responder "¿qué tickets tuvimos como este y cómo los resolvimos?".

        Recorre TODOS los tickets del cliente en los estados pedidos (por defecto En espera,
        Resuelto y Cerrado —lo ya trabajado—), no los últimos N, y lee de UNA sola vez las
        soluciones y los seguimientos de todos ellos (sin una consulta por ticket).

        Para puntuar no alcanza con buscar la frase tal cual: nadie redacta el ticket con las
        mismas palabras con que después se pregunta. Cada término de la consulta se busca por su
        raíz —así "fichadas" encuentra "la fichada"— y también contra el texto sin espacios —así
        "HikCentral" encuentra "hik central"—; cada término pesa según lo distintivo que sea
        (uno que aparece en casi todos los tickets casi no suma), y una coincidencia en el
        PROBLEMA vale más que una en un comentario posterior.

        De cada candidato devuelve el problema y la `resolucion` REAL, que es la que escribió
        SOPORTE: la solución documentada o, si no la hay, la última respuesta del técnico. Un
        comentario del propio solicitante no es una resolución, y un cierre ADMINISTRATIVO
        —«se cierra porque la categoría está mal», duplicado, sin respuesta— tampoco: en esos
        casos `resuelto_de_verdad=False` (y `cierre_administrativo=True` si se cerró así). El
        caso sigue sirviendo como antecedente, pero jamás se presenta como "así lo resolvimos"."""
        import math
        pal = _palabras(descripcion)
        if not pal:
            return []
        docs = self._corpus(estados)
        if not docs:
            return []

        # 2) Cuánto distingue cada término: el que está en todos los tickets casi no aporta. Y el
        # que no aparece en NINGUNO se descarta: es una palabra de la pregunta, no del caso, y si
        # se dejara —siendo la más "rara", la de mayor peso— subiría tanto el puntaje ideal que
        # ningún ticket real llegaría al umbral.
        peso = {}
        for w in pal:
            n = sum(1 for d in docs
                    if _contiene(w, d["h_prob"], d["j_prob"])
                    or _contiene(w, d["h_resto"], d["j_resto"]))
            if n:
                peso[w] = math.log((len(docs) + 1) / (n + 1)) + 1.0
        if not peso:
            return []
        pal = list(peso)
        maximo = sum(peso.values())

        # 3) Puntaje. Lo que define el caso es el PROBLEMA: que la palabra aparezca en un
        # comentario posterior apenas desempata (en un comentario se habla de cualquier cosa).
        candidatos = []
        for d in docs:
            puntos = 0.0
            for w in pal:
                if _contiene(w, d["h_prob"], d["j_prob"]):
                    puntos += peso[w]
                elif _contiene(w, d["h_resto"], d["j_resto"]):
                    puntos += peso[w] * 0.15
            if puntos < maximo * 0.30:
                continue
            # La resolución la escribe SOPORTE: la solución documentada o, si no hay, la última
            # respuesta del técnico. Lo que comenta el solicitante es parte del problema, no de
            # la solución, y un cierre administrativo no resuelve nada.
            resolucion = " ".join(s for s in d["sols"] if not _cierre_administrativo(s)).strip()
            if not resolucion:
                utiles = [f for f in d["fus_soporte"] if not _cierre_administrativo(f)]
                resolucion = utiles[-1].strip() if utiles else ""
            administrativo = not resolucion and any(
                _cierre_administrativo(x) for x in d["fus"] + d["sols"])
            t = d["t"]
            candidatos.append({
                "id": d["id"], "asunto": t.get("name", ""),
                "estado": _ESTADO_TXT.get(int(t.get("status", 0)), "?"),
                "problema": d["problema"][:800],
                "resolucion": resolucion[:800],
                "resuelto_de_verdad": bool(resolucion),
                "cierre_administrativo": administrativo,
                "relevancia": round(puntos / maximo, 3)})
        candidatos.sort(key=lambda x: (-x["relevancia"], -x["id"]))
        return candidatos[:tope]

    def _corpus(self, estados):
        """El histórico del cliente ya leído y normalizado, listo para buscar. Leerlo entero
        (tickets + seguimientos + soluciones) son varias vueltas a la mesa de ayuda, así que se
        reutiliza unos minutos: quien pregunta dos cosas seguidas no espera dos veces. El
        histórico cerrado no cambia de un minuto al otro; lo vigente se consulta por otras vías."""
        import time
        clave = (self.gl.get("glpi_url"), self.ent, tuple(sorted(estados)))
        guardado = _CORPUS.get(clave)
        if guardado and time.time() - guardado[0] < _CORPUS_TTL:
            return guardado[1]

        c = self._c()
        try:
            ts = [t for t in self._ent(c.todos_tickets())
                  if int(t.get("status", 0)) in estados]
            sol_map = self._soluciones_masivo(c)
            fu_map = self._followups_masivo(c)
        finally:
            c.cerrar()

        docs = []
        for t in ts:
            tid = int(t.get("id", 0))
            problema = _sin_html(t.get("content", ""))
            solicitante = int(t.get("users_id_recipient") or 0)
            crudos = [f for f in fu_map.get(tid, []) if str(f.get("texto", "")).strip()]
            fus = [_sin_html(f["texto"]) for f in crudos]
            # Lo que escribió SOPORTE: todo lo que NO viene de quien abrió el ticket. Los
            # tickets viejos entraron por correo y GLPI los guardó sin autor (0): ahí no se
            # puede descartar por id, así que se dejan —el intercambio con el técnico está en
            # ese hilo— y lo que no aporta lo saca el filtro de cierres administrativos.
            fus_soporte = [_sin_html(f["texto"]) for f in crudos
                           if f["autor"] != solicitante]
            sols = [_sin_html(s["texto"]) for s in sol_map.get(tid, [])
                    if str(s.get("texto", "")).strip()]
            h_prob = _normalizar(f"{t.get('name', '')} {problema}")
            h_resto = _normalizar(" ".join(fus + sols))
            docs.append({"t": t, "id": tid, "problema": problema, "fus": fus,
                         "fus_soporte": fus_soporte, "sols": sols,
                         "h_prob": h_prob, "j_prob": h_prob.replace(" ", ""),
                         "h_resto": h_resto, "j_resto": h_resto.replace(" ", "")})
        _CORPUS[clave] = (time.time(), docs)
        return docs

    def _soluciones_masivo(self, c, tam=1000):
        """{ticket_id: [{texto, autor}]} leyendo TODAS las soluciones de una (sin N+1)."""
        return self._paginado(c, "/ITILSolution", tam)

    def _followups_masivo(self, c, tam=1000):
        """{ticket_id: [{texto, autor}]} con TODOS los seguimientos PÚBLICOS de una (sin N+1).
        Los privados son notas internas entre técnicos: no son la respuesta al cliente."""
        return self._paginado(c, "/ITILFollowup", tam, publicos=True)

    def _paginado(self, c, recurso, tam, publicos=False):
        """Lee un recurso entero paginando, quedándose con el texto y QUIÉN lo escribió. Avanza
        por lo que DEVUELVE la página, no por lo que se pidió: GLPI puede acotar el rango por
        configuración y, si diéramos el salto por sentado, el histórico quedaría cortado a la
        mitad sin que se note."""
        mapa, inicio = {}, 0
        while True:
            try:
                chunk = c.request(f"{recurso}?range={inicio}-{inicio + tam - 1}")
            except Exception:  # noqa: BLE001
                break
            if not isinstance(chunk, list) or not chunk:
                break
            for it in chunk:
                if not isinstance(it, dict) or str(it.get("itemtype")) != "Ticket":
                    continue
                if publicos and int(it.get("is_private") or 0):
                    continue
                mapa.setdefault(int(it.get("items_id") or 0), []).append(
                    {"texto": str(it.get("content", "")), "autor": int(it.get("users_id") or 0)})
            inicio += len(chunk)
            if inicio > 200000:                 # tope de seguridad (evita un bucle infinito)
                break
        return mapa

    def sin_procesar(self, n=60):
        """Revisa TODOS los tickets vigentes (Nuevo/En curso/En espera) y detecta los SUELTOS:
        los que les falta categoría o SLA (el ciclo del agente sin aplicar). Devuelve la lista."""
        c = self._c()
        try:
            ts = self._ent(c.tickets_recientes(n))
        finally:
            c.cerrar()
        out = []
        for t in ts:
            if int(t.get("status", 0)) not in (1, 2, 4):
                continue
            falta = []
            if not int(t.get("itilcategories_id") or 0):
                falta.append("categoría")
            if not t.get("time_to_resolve"):
                falta.append("SLA")
            if falta:
                out.append({"id": t["id"], "asunto": t.get("name", ""),
                            "estado": _ESTADO_TXT.get(int(t.get("status", 0)), "?"),
                            "falta": falta})
        return out

    def detalle(self, tid):
        """LEE el ticket COMPLETO para poder ANALIZARLO: asunto, estado, prioridad, categoría,
        fechas/SLA, DESCRIPCIÓN y todos los SEGUIMIENTOS. Así ITHOS entiende el caso de verdad
        (antes solo tenía asunto+estado y por eso decía 'no tengo acceso al contenido')."""
        tid = _norm_id(tid)
        c = self._c()
        try:
            t = c.request(f"/Ticket/{tid}") or {}
            try:
                fups = c.request(f"/Ticket/{tid}/ITILFollowup") or []
            except Exception:  # noqa: BLE001
                fups = []
            cat = ""
            cid = int(t.get("itilcategories_id") or 0)
            if cid:
                try:                                       # la categoría la lee el super admin
                    cat = (self._c_admin().request(f"/ITILCategory/{cid}") or {}).get("completename", "")
                except Exception:  # noqa: BLE001
                    cat = ""
        finally:
            c.cerrar()
        if not t:
            return f"No encontré el ticket #{tid}."
        est = _ESTADO_TXT.get(int(t.get("status", 0)), "?")
        prio = _PRIO_TXT.get(int(t.get("priority", 0)), "?")
        partes = [
            f"Ticket #{tid}: {t.get('name', '')}",
            f"Estado: {est} | Prioridad: {prio} | Categoría: {cat or '(sin categoría)'}",
            f"Abierto: {t.get('date_creation', '')} | Vence/TTR: "
            f"{t.get('time_to_resolve') or '(sin SLA)'} | 1ª resp./TTO: "
            f"{t.get('time_to_own') or '(sin SLA)'}",
            f"DESCRIPCIÓN: {_sin_html(t.get('content')) or '(vacía)'}"]
        for i, f in enumerate((fups or [])[-8:], 1):
            txt = _sin_html(f.get("content"))
            if txt:
                partes.append(f"Seguimiento {i} ({f.get('date', '')}): {txt}")
        return "\n".join(partes)

    def permisos(self):
        """Lee el PERFIL ACTIVO del token de ITHOS en GLPI (/getActiveProfile) y traduce qué
        PUEDE y qué NO puede hacer, para que ITHOS lo diga con la verdad y actúe solo donde
        tiene permiso. Cacheado 1h (una llamada, no molesta). Bits GLPI: READ=1, UPDATE=2,
        CREATE=4, DELETE=8, PURGE=16."""
        import time as _t
        if getattr(self, "_perm", None) and _t.time() - self._perm_ts < 3600:
            return self._perm
        R, U, C, D = 1, 2, 4, 8          # bits GLPI que usamos (PURGE=16 no se evalúa)
        c = self._c()
        try:
            prof = (c.request("/getActiveProfile") or {}).get("active_profile", {}) or {}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "perfil": "?", "resumen": f"No pude leer mis permisos ({e})."}
        finally:
            c.cerrar()
        tk = int(prof.get("ticket", 0) or 0)
        fu = int(prof.get("followup", 0) or 0)
        cat = int(prof.get("itilcategory", 0) or 0)
        puede = {
            "leer": bool(tk & R), "crear": bool(tk & C), "actualizar": bool(tk & U),
            "cerrar": bool(tk & U), "asignar": bool(tk & U), "eliminar": bool(tk & D),
            # responder = crear seguimientos (o, si no, actualizar el ticket)
            "responder": bool(fu & C) or bool(tk & U),
            # categorizar/priorizar/SLA = actualizar el ticket (la LECTURA del catálogo la
            # resolvemos con el token de lectura aunque el perfil de ITHOS no la tenga)
            "categorizar": bool(tk & U), "prioridad": bool(tk & U), "sla": bool(tk & U),
            "leer_catalogo_categorias": bool(cat & R),
        }
        si = [k for k in ("leer", "crear", "actualizar", "asignar", "responder", "cerrar") if puede[k]]
        no = [k for k in ("crear", "actualizar", "asignar", "responder", "cerrar", "eliminar") if not puede[k]]
        resumen = (f"Perfil GLPI de ITHOS: '{prof.get('name', '?')}'. PUEDO: {', '.join(si) or '—'}."
                   + (f" NO puedo: {', '.join(no)}." if no else "")
                   + ("" if puede["leer_catalogo_categorias"] else
                      " (El catálogo de categorías no lo puede listar mi rol; lo resuelvo con el token de lectura.)"))
        self._perm = {"ok": True, "perfil": prof.get("name", "?"), "puede": puede, "resumen": resumen}
        self._perm_ts = _t.time()
        return self._perm

    def _cats(self):
        """Lista de categorías GLPI. El token de ITHOS NO puede leerlas (403); el SUPER ADMIN
        SÍ -> sesión admin del pool (reutilizada)."""
        try:
            return self._c_admin().request("/ITILCategory?range=0-999") or []
        except Exception:  # noqa: BLE001
            return []

    def _cat_id(self, nombre, entidad=None):
        """ID de la categoría por nombre. Como 'TERMINALES' existe en VARIAS entidades con
        distinto id, prioriza la de la ENTIDAD del ticket (si se pasa)."""
        n = str(nombre or "").strip().lower()
        if not n:
            return 0
        cats = self._cats()
        match = [x for x in cats if str(x.get("name", "")).strip().lower() == n
                 or str(x.get("completename", "")).strip().lower() == n]
        if not match:                                      # parcial (por si viene la ruta completa)
            match = [x for x in cats if n in str(x.get("completename", "")).lower()
                     or n in str(x.get("name", "")).lower()]
        if not match:
            return 0
        if entidad is not None:                            # preferir la de la entidad del ticket
            for x in match:
                if int(x.get("entities_id", -1)) == int(entidad):
                    return int(x.get("id", 0))
        return int(match[0].get("id", 0))

    def categorizar(self, tid, categoria):
        tid = _norm_id(tid)
        c = self._c()
        try:
            ent = int((c.request(f"/Ticket/{tid}") or {}).get("entities_id", self.ent))
        except Exception:  # noqa: BLE001
            ent = self.ent
        finally:
            c.cerrar()
        cid = self._cat_id(categoria, ent)
        if not cid:
            return f"No pude resolver la categoría '{categoria}'."
        c = self._c()
        try:
            c.request(f"/Ticket/{tid}", "PUT", {"input": {"itilcategories_id": cid}})
        finally:
            c.cerrar()
        return f"🏷️ Ticket #{tid} categorizado como '{categoria}'."

    def cambiar_sla(self, tid, prioridad=None):
        """Fija el SLA IGUAL QUE LA DEMO: aplica las DEFINICIONES SLA/OLA (slas_id_tto/ttr +
        olas_id_tto/ttr) según el nivel derivado de la prioridad. GLPI calcula solo el TTO/TTR
        EXTERNO y el INTERNO (TTO interno / TTR interno). Si el cliente no tiene definiciones
        SLA/OLA, cae a fijar las fechas a mano. Si no se pasa prioridad, la lee del ticket."""
        from datetime import datetime, timedelta
        tid = _norm_id(tid)
        c = self._c()
        try:
            if not prioridad:
                t = c.request(f"/Ticket/{tid}") or {}
                prioridad = {2: "baja", 3: "media", 4: "alta", 5: "urgente"}.get(
                    int(t.get("priority", 3)), "media")
            nivel = _NIVEL_POR_PRIO.get(str(prioridad).lower(), "LEVE")
            campos = dict(self.niveles_sla.get(nivel, {}))
            if campos:                                     # definiciones SLA/OLA (como la demo)
                c.request(f"/Ticket/{tid}", "PUT", {"input": campos})
                detalle = f"nivel {nivel} (SLA+OLA interno y externo)"
            else:                                          # respaldo: fechas a mano (solo externo)
                tto_h, ttr_h = _SLA_HORAS.get(str(prioridad).lower(), _SLA_HORAS["media"])
                ahora = datetime.now()
                fmt = "%Y-%m-%d %H:%M:%S"
                c.request(f"/Ticket/{tid}", "PUT", {"input": {
                    "time_to_own": (ahora + timedelta(hours=tto_h)).strftime(fmt),
                    "time_to_resolve": (ahora + timedelta(hours=ttr_h)).strftime(fmt)}})
                detalle = f"1ª respuesta {tto_h}h, resolución {ttr_h}h"
        finally:
            c.cerrar()
        return f"⏱️ SLA del #{tid}: {detalle} (prioridad {prioridad})."

    def aplicar_ciclo(self, tid, categoria=None, prioridad="media", responsable="bsierra",
                      primera_respuesta="", necesita_info=False):
        """CICLO COMPLETO igual a la demo, en una sola pasada: categoría + urgencia/impacto/
        prioridad + SLA/OLA (interno y externo) + asigna ITHOS y el técnico + 1ª RESPUESTA
        (que pide los datos que falten) + estado (EN ESPERA si falta info, si no EN CURSO)."""
        tid = _norm_id(tid)
        n = _PRIO.get(str(prioridad).lower(), 3)
        nivel = _NIVEL_POR_PRIO.get(str(prioridad).lower(), "LEVE")
        hechos = []
        c = self._c()
        try:
            t = c.request(f"/Ticket/{tid}") or {}
            ent = int(t.get("entities_id", self.ent))
            campos = {"urgency": n, "impact": n, "priority": n}
            cid = self._cat_id(categoria, ent) if categoria else 0
            if cid:
                campos["itilcategories_id"] = cid
                hechos.append(f"categoría {categoria}")
            campos.update(self.niveles_sla.get(nivel, {}))
            if self.niveles_sla.get(nivel):
                hechos.append(f"SLA/OLA nivel {nivel}")
            c.request(f"/Ticket/{tid}", "PUT", {"input": campos})
            hechos.append(f"prioridad {prioridad}")
            uid = _TECNICOS.get(str(responsable).lower().strip())
            for u in (self.ithos_id, uid):
                if u:
                    try:
                        c.request("/Ticket_User", "POST",
                                  {"input": {"tickets_id": tid, "users_id": u, "type": 2}})
                    except Exception:  # noqa: BLE001
                        pass
            hechos.append(f"asignado a {responsable} (+ ITHOS)")
            if primera_respuesta:
                from comun import glpi as G
                # El saludo SIEMPRE es para el SOLICITANTE (quien abrió el ticket), no para la
                # persona afectada del texto. Igual que el triage automático (aplicar en todo).
                sol = G.nombre_pila(self._c_admin(), t.get("users_id_recipient"))
                primera_respuesta = G.saludo_solicitante(primera_respuesta, sol)
                c.request("/ITILFollowup", "POST", {"input": {
                    "itemtype": "Ticket", "items_id": tid, "content": primera_respuesta}})
                hechos.append("1ª respuesta enviada")
            c.request(f"/Ticket/{tid}", "PUT",
                      {"input": {"status": 4 if necesita_info else 2}})
            hechos.append("en espera de datos" if necesita_info else "en curso")
        finally:
            c.cerrar()
        return f"✅ Ciclo aplicado al #{tid}: " + ", ".join(hechos) + "."

    @staticmethod
    def _fecha(s):
        from datetime import datetime
        try:
            return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:  # noqa: BLE001
            return None

    def en_riesgo_sla(self, horas=4):
        """Tickets ABIERTOS cuyo SLA (time_to_resolve) vence dentro de `horas` o ya
        venció y siguen sin resolver. Devuelve [{id,asunto,faltan_horas,vencido,asignados}].
        `asignados` = user-ids del campo "Asignado a" (para @mencionar SOLO al técnico del ticket)."""
        from datetime import datetime
        c = self._c()
        try:
            ts = self._ent(c.tickets_recientes(60))
            ahora, out = datetime.now(), []
            for t in ts:
                if int(t.get("status", 0)) not in (1, 2, 4):
                    continue
                ttr = self._fecha(t.get("time_to_resolve"))
                if not ttr:
                    continue
                faltan = (ttr - ahora).total_seconds() / 3600.0
                if faltan <= horas:
                    out.append({"id": t["id"], "asunto": t.get("name", ""),
                                "faltan_horas": round(faltan, 1), "vencido": faltan < 0})
            asig = self._asignados_de(c, [t["id"] for t in out])
            for t in out:
                t["asignados"] = asig.get(int(t["id"]), [])
        finally:
            c.cerrar()
        return out

    def _asignados_de(self, c, tids):
        """{ticket_id: [user-ids ASIGNADOS]} ("Asignado a" = Ticket_User type=2). Con POCOS tickets
        pregunta por ticket; con MUCHOS hace UNA sola lectura masiva de Ticket_User (anti N+1).
        Nunca es fatal: si GLPI no deja leerlo, devuelve vacío y el aviso va sin @mención."""
        tids = [int(x) for x in (tids or [])]
        if not tids:
            return {}
        if len(tids) > 8:
            masivo = self._asignados_masivo(c)
            if masivo is not None:
                return {tid: masivo.get(tid, []) for tid in tids}
        out = {}
        for tid in tids:
            try:
                us = c.request(f"/Ticket/{tid}/Ticket_User")
                out[tid] = sorted({int(u.get("users_id") or 0) for u in us
                                   if isinstance(u, dict) and int(u.get("type") or 0) == 2}
                                  - {0, self.ithos_id})
            except Exception:  # noqa: BLE001
                out[tid] = []
        return out

    def _asignados_masivo(self, c, tam=2000):
        """{ticket_id: [user-ids asignados]} en UNA lectura paginada de /Ticket_User. None si falla
        (el llamador cae al modo por-ticket: mismo resultado, más lento pero correcto)."""
        mapa, inicio = {}, 0
        while True:
            try:
                chunk = c.request(f"/Ticket_User?range={inicio}-{inicio + tam - 1}")
            except Exception:  # noqa: BLE001
                return None
            if not isinstance(chunk, list):
                return None
            for u in chunk:
                if not isinstance(u, dict) or int(u.get("type") or 0) != 2:
                    continue
                uid = int(u.get("users_id") or 0)
                if uid and uid != self.ithos_id:
                    mapa.setdefault(int(u.get("tickets_id") or 0), []).append(uid)
            if len(chunk) < tam:
                break
            inicio += tam
            if inicio > 1000000:                        # tope de seguridad
                break
        return {k: sorted(set(v)) for k, v in mapa.items()}

    def sla(self):
        rep, _ = self._reportes()
        return rep

    def sla_texto(self):
        _, texto = self._reportes()
        return texto

    def _reportes(self):
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "central"))
        import reportes as R
        # SIN límite: trae TODOS los tickets reales del cliente (paginados), así el 'total' y el
        # desglose por estado son SIEMPRE reales (no una muestra capada con un total falso).
        return R.generar(self.gl, self.ent)


class _Nulo:
    """Fallback si el tipo de tickets no está soportado o falta configuración."""

    def __init__(self, tipo):
        self.tipo = tipo or "desconocido"

    def _na(self, que):
        return f"({que} no disponible: sistema de tickets '{self.tipo}' sin configurar)"

    def abiertos(self):
        return []

    def resueltos(self, n=80):
        return []

    def estado(self, tid):
        return self._na("estado")

    def detalle(self, tid):
        return self._na("lectura de ticket")

    def sin_procesar(self, n=60):
        return []

    def categorizar(self, tid, categoria):
        return self._na("categorizar")

    def cambiar_sla(self, tid, prioridad=None):
        return self._na("SLA")

    def aplicar_ciclo(self, tid, categoria=None, prioridad="media", responsable="bsierra",
                      primera_respuesta="", necesita_info=False):
        return self._na("ciclo completo")

    def permisos(self):
        return {"ok": True, "perfil": "?", "puede": {},
                "resumen": f"Permisos del sistema '{self.tipo}': asumo estándar (a confirmar por API)."}

    def responder(self, tid, texto):
        return self._na("responder")

    def crear(self, asunto, contenido):
        return self._na("crear ticket")

    def cambiar_estado(self, tid, estado):
        return self._na("cambiar estado")

    def cambiar_prioridad(self, tid, prio):
        return self._na("cambiar prioridad")

    def asignar(self, tid, tecnico):
        return self._na("asignar")

    def buscar(self, texto):
        return []

    def casos_similares(self, descripcion, tope=20, estados=(4, 5, 6)):
        return []

    def en_riesgo_sla(self, horas=4):
        return []

    def sla(self):
        return {"error": self._na("SLA")}

    def sla_texto(self):
        return self._na("reporte de SLA")


# ===================================================================== TÉCNICOS DEL CLIENTE
# Config por cliente: "tecnicos": [{nombre, glpi_id, glpi_login, telefonos:[...]}]. Se usa para
#   · reconocer "mis tickets" por el número de quien escribe (comun/conversacion.py), y
#   · @MENCIONAR al TÉCNICO ASIGNADO en los avisos de WhatsApp (tickets y SLA).
# Vale para CUALQUIER sistema de tickets: el id del técnico se busca por 'glpi_id' (GLPI) o por
# 'id'/'login'/'email'/'nombre' (Zendesk, Freshservice, Jira, osTicket), así el mismo bloque de
# config sirve para todos sin tocar código.


def tecnicos(cli_cfg):
    """Lista de técnicos configurados del cliente (sin las entradas de solo-comentario '_nota')."""
    out = []
    for t in ((cli_cfg or {}).get("tecnicos") or []):
        if isinstance(t, dict) and (t.get("nombre") or t.get("glpi_id") or t.get("id")):
            out.append(t)
    return out


def _claves_tecnico(t):
    """Todas las formas de identificar a un técnico, normalizadas a str minúscula."""
    vals = [t.get("glpi_id"), t.get("id"), t.get("glpi_login"), t.get("login"),
            t.get("email"), t.get("nombre")]
    return {str(v).strip().lower() for v in vals if v not in (None, "")}


def tecnico_por_id(cli_cfg, uid):
    """El técnico configurado cuyo id/login/email/nombre coincide con `uid` (el asignado que
    devuelve el sistema de tickets). None si no está configurado."""
    clave = str(uid if uid is not None else "").strip().lower()
    if not clave:
        return None
    for t in tecnicos(cli_cfg):
        if clave in _claves_tecnico(t):
            return t
    return None


def telefonos_asignados(cli_cfg, uids):
    """Teléfonos (solo dígitos, sin repetir) de los técnicos ASIGNADOS `uids`. Vacío si ninguno
    está configurado -> el aviso se manda sin @mención (nunca se pierde el aviso)."""
    import re as _re
    out = []
    for uid in (uids or []):
        t = tecnico_por_id(cli_cfg, uid)
        for tel in ((t or {}).get("telefonos") or []):
            n = _re.sub(r"\D", "", str(tel))
            if n and n not in out:
                out.append(n)
    return out


def nombres_asignados(cli_cfg, uids):
    """Nombres de los técnicos asignados (para que el aviso diga a QUIÉN, incluso en los canales
    que no soportan @mención: Telegram, email, Teams…)."""
    out = []
    for uid in (uids or []):
        t = tecnico_por_id(cli_cfg, uid)
        nom = (t or {}).get("nombre")
        if nom and nom not in out:
            out.append(nom)
    return out


def adaptador(cli_cfg):
    """Devuelve el adaptador del sistema de tickets del cliente. GLPI nativo; los demás
    (Zendesk/Jira/Freshservice/osTicket) por sus clientes REALES en tickets_otros.py,
    que implementan la MISMA interfaz común."""
    tipo = ((cli_cfg.get("tickets") or {}).get("tipo")) or "glpi"
    if tipo == "glpi":
        return _GLPI(cli_cfg)
    from comun import tickets_otros as TO
    cli = TO.crear_cliente_tickets(cli_cfg.get("tickets") or {})
    return cli or _Nulo(tipo)
