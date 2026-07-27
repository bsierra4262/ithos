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
        c = self._c()
        try:
            ts = self._ent(c.tickets_recientes(60))
        finally:
            c.cerrar()
        q = (texto or "").lower()
        return [{"id": t["id"], "asunto": t.get("name", "")}
                for t in ts if q in str(t.get("name", "")).lower()
                or q in str(t.get("content", "")).lower()][:8]

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
        venció y siguen sin resolver. Devuelve [{id,asunto,faltan_horas,vencido}]."""
        from datetime import datetime
        c = self._c()
        try:
            ts = self._ent(c.tickets_recientes(60))
        finally:
            c.cerrar()
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
        return out

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

    def en_riesgo_sla(self, horas=4):
        return []

    def sla(self):
        return {"error": self._na("SLA")}

    def sla_texto(self):
        return self._na("reporte de SLA")


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
