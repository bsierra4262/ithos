#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clientes REALES de otros sistemas de tickets (además de GLPI), según la documentación
OFICIAL vigente de cada fabricante (2025/2026). Cada clase implementa la MISMA interfaz
común que el adaptador GLPI de comun/tickets.py, así ITHOS (KB, acciones, SLA,
proactivo) funciona idéntico en todos:

  abiertos() · resueltos(n) · estado(id) · responder(id,texto) · crear(asunto,cont) ·
  cambiar_estado(id,estado) · cambiar_prioridad(id,prio) · asignar(id,tec) · buscar(txt)
  · en_riesgo_sla(horas) · sla() · sla_texto()

Referencias oficiales:
  - Zendesk Support API v2: developer.zendesk.com/api-reference/ticketing/tickets/tickets
  - Jira Cloud REST v3 (search/jql nuevo): developer.atlassian.com/cloud/jira/platform/rest/v3
  - Freshservice API v2: api.freshservice.com
  - osTicket API: docs.osticket.com (la API oficial SOLO crea tickets)

Se configuran por cliente (bloque "tickets" en clientes.json). No hay ambiente de
prueba: implementado 1:1 con la doc oficial y patrones públicos de integración.
"""

import json
import base64
import logging
import urllib.parse
import urllib.request
from datetime import datetime

log = logging.getLogger("tickets_otros")

# Estado normalizado (español) para mostrar y para abiertos()/resueltos().
ABIERTO, EN_CURSO, EN_ESPERA, RESUELTO, CERRADO = (
    "Abierto", "En curso", "En espera", "Resuelto", "Cerrado")


def _http(url, headers, method="GET", data=None, timeout=25):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode() or "{}"
            return json.loads(txt) if txt.strip().startswith(("{", "[")) else {}
    except urllib.error.HTTPError as e:  # noqa: PERF203
        detalle = ""
        try:
            detalle = e.read().decode()[:200]
        except Exception:  # noqa: BLE001
            pass
        log.warning("%s %s -> HTTP %s %s", method, url, e.code, detalle)
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("%s %s -> %s", method, url, e)
        raise


def _basic(user, pwd):
    return "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()


def _horas_hasta(iso):
    """Horas (float) desde ahora hasta un timestamp ISO/epoch. None si no se puede."""
    if iso in (None, "", 0):
        return None
    try:
        if isinstance(iso, (int, float)) or str(iso).isdigit():
            dt = datetime.utcfromtimestamp(float(iso) / (1000 if float(iso) > 1e12 else 1))
        else:
            s = str(iso).replace("Z", "").replace("T", " ")[:19]
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return (dt - datetime.utcnow()).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        return None


def _adf_text(node):
    """Extrae texto plano de un nodo ADF (Atlassian Document Format) de Jira."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return "".join(_adf_text(c) for c in node.get("content", []))
    if isinstance(node, list):
        return "".join(_adf_text(c) for c in node)
    return ""


def _adf(texto):
    """Arma un documento ADF simple (un párrafo) para comentarios/descripción de Jira."""
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": texto or " "}]}]}


def _resumen_estados(conteo):
    hoy = datetime.now().strftime("%d/%m/%Y")
    total = sum(conteo.values())
    ab = conteo.get(ABIERTO, 0) + conteo.get(EN_CURSO, 0) + conteo.get(EN_ESPERA, 0)
    return (f"Reporte de tickets — {hoy} ({total} analizados):\n"
            f"  Abiertos: {ab}  ·  Resueltos: {conteo.get(RESUELTO, 0)}  ·  "
            f"Cerrados: {conteo.get(CERRADO, 0)}\n  Detalle: {conteo}")


class _BaseTickets:
    """Interfaz común de tickets con defaults SEGUROS para las operaciones del CIRCUITO ITIL
    que hoy resuelve GLPI de forma nativa (categorizar, SLA, ciclo completo, 'sin procesar').
    Cada sistema (Zendesk/Jira/Freshservice/osTicket) hereda y sobrescribe lo que su API
    soporta; lo que todavía no, responde con la VERDAD en vez de romper con AttributeError.
    Así ITHOS invoca la MISMA interfaz en todos los sistemas sin código a medida ni crashes."""

    def _no_soportado(self, que):
        sistema = getattr(self, "tipo", None) or type(self).__name__
        return (f"({que}: por ahora se hace en GLPI; en {sistema} puedo leer, responder, "
                f"cambiar estado/prioridad y asignar).")

    def sin_procesar(self, n=60):
        return []                                       # sin heurística propia -> nada que marcar

    def categorizar(self, tid, categoria):
        return self._no_soportado("categorizar")

    def cambiar_sla(self, tid, prioridad=None):
        return self._no_soportado("cambiar el SLA")

    def aplicar_ciclo(self, tid, categoria=None, prioridad="media", responsable="bsierra",
                      primera_respuesta="", necesita_info=False):
        return self._no_soportado("el circuito ITIL completo")


# =============================================================================== Zendesk
class Zendesk(_BaseTickets):
    """Zendesk Support API v2. Auth básica '{email}/token:{api_token}'."""

    tipo = "Zendesk"

    ESTADO = {"new": ABIERTO, "open": EN_CURSO, "pending": EN_ESPERA, "hold": EN_ESPERA,
              "solved": RESUELTO, "closed": CERRADO}
    PRIO = {"baja": "low", "media": "normal", "alta": "high", "urgente": "urgent"}
    EST_SET = {"cerrado": "solved", "reabrir": "open", "en_espera": "hold",
               "en_curso": "open"}

    def __init__(self, cfg):
        self.base = cfg["host"].rstrip("/")
        self.h = {"Authorization": _basic(f"{cfg['email']}/token", cfg["api_token"]),
                  "Content-Type": "application/json", "Accept": "application/json"}

    def _get(self, path):
        return _http(self.base + path, self.h)

    def _put(self, path, data):
        return _http(self.base + path, self.h, "PUT", data)

    def _post(self, path, data):
        return _http(self.base + path, self.h, "POST", data)

    def _norm(self, t):
        return {"id": t.get("id"), "asunto": t.get("subject", ""),
                "estado": self.ESTADO.get(t.get("status"), t.get("status", "?"))}

    def abiertos(self):
        d = self._get("/api/v2/search.json?query=" + urllib.parse.quote(
            "type:ticket status<solved") + "&sort_by=created_at&sort_order=desc")
        return [self._norm(t) for t in d.get("results", [])]

    def resueltos(self, n=80):
        d = self._get("/api/v2/search.json?query=" + urllib.parse.quote(
            "type:ticket status:solved") + "&sort_by=created_at&sort_order=desc")
        out = []
        for t in d.get("results", [])[:n]:
            sol = ""
            try:
                cs = self._get(f"/api/v2/tickets/{t['id']}/comments.json").get("comments", [])
                pub = [c for c in cs if c.get("public")]
                if len(pub) > 1:
                    sol = pub[-1].get("body", "")
            except Exception:  # noqa: BLE001
                pass
            out.append({"id": t["id"], "asunto": t.get("subject", ""),
                        "problema": t.get("description", ""), "solucion": sol})
        return out

    def estado(self, tid):
        t = self._get(f"/api/v2/tickets/{tid}.json").get("ticket", {})
        return f"#{tid}: {t.get('subject')} — {self.ESTADO.get(t.get('status'), '?')}"

    def detalle(self, tid):
        """Ticket COMPLETO: asunto, estado, prioridad, descripción y comentarios públicos."""
        t = self._get(f"/api/v2/tickets/{tid}.json").get("ticket", {})
        cs = []
        try:
            cs = self._get(f"/api/v2/tickets/{tid}/comments.json").get("comments", [])
        except Exception:  # noqa: BLE001
            pass
        partes = [f"Ticket #{tid}: {t.get('subject', '')}",
                  f"Estado: {self.ESTADO.get(t.get('status'), '?')} | Prioridad: {t.get('priority', '?')}",
                  f"DESCRIPCIÓN: {t.get('description', '') or '(vacía)'}"]
        for i, c in enumerate([c for c in cs if c.get("public")][-8:], 1):
            partes.append(f"Comentario {i}: {str(c.get('body', ''))[:400]}")
        return "\n".join(partes)

    def permisos(self):
        return {"ok": True, "perfil": "Zendesk (agente)",
                "puede": {"leer": True, "crear": True, "actualizar": True, "asignar": True,
                          "responder": True},
                "resumen": "En Zendesk puedo: leer, crear, actualizar, responder y asignar "
                           "tickets (según el rol del token). El cierre definitivo lo hace Zendesk."}

    def responder(self, tid, texto):
        self._put(f"/api/v2/tickets/{tid}.json",
                  {"ticket": {"comment": {"body": texto, "public": True}}})
        return f"💬 Respondí al cliente en el ticket #{tid} (Zendesk)."

    def crear(self, asunto, contenido):
        r = self._post("/api/v2/tickets.json",
                       {"ticket": {"subject": asunto, "comment": {"body": contenido}}})
        return f"🆕 Ticket #{r.get('ticket', {}).get('id')} creado (Zendesk)."

    def cambiar_estado(self, tid, estado):
        self._put(f"/api/v2/tickets/{tid}.json",
                  {"ticket": {"status": self.EST_SET.get(estado, "open")}})
        return f"Ticket #{tid} → {estado} (Zendesk)."

    def cambiar_prioridad(self, tid, prio):
        self._put(f"/api/v2/tickets/{tid}.json",
                  {"ticket": {"priority": self.PRIO.get(str(prio).lower(), "normal")}})
        return f"Ticket #{tid} → prioridad {prio} (Zendesk)."

    def asignar(self, tid, tecnico):
        uid = tecnico if str(tecnico).isdigit() else None
        if not uid:
            u = self._get("/api/v2/users/search.json?query=" + urllib.parse.quote(str(tecnico)))
            us = u.get("users", [])
            uid = us[0]["id"] if us else None
        if not uid:
            return f"No encontré al agente '{tecnico}' en Zendesk."
        self._put(f"/api/v2/tickets/{tid}.json", {"ticket": {"assignee_id": uid}})
        return f"👤 Ticket #{tid} asignado a {tecnico} (Zendesk)."

    def buscar(self, texto):
        d = self._get("/api/v2/search.json?query=" + urllib.parse.quote(
            f"type:ticket {texto}"))
        return [{"id": t.get("id"), "asunto": t.get("subject", "")}
                for t in d.get("results", [])[:8]]

    def en_riesgo_sla(self, horas=4):
        """Zendesk expone el próximo vencimiento de SLA por métricas del ticket. Se
        piden los abiertos con el sideload de metric_sets y se mira next SLA breach."""
        d = self._get("/api/v2/search.json?query=" + urllib.parse.quote(
            "type:ticket status<solved") + "&include=metric_sets")
        metric = {m["id"]: m for m in d.get("metric_sets", []) or []}
        out = []
        for t in d.get("results", []):
            ms = metric.get(t.get("id")) or {}
            brk = t.get("due_at") or ms.get("solved_at")
            faltan = _horas_hasta(brk)
            if faltan is not None and faltan <= horas:
                out.append({"id": t["id"], "asunto": t.get("subject", ""),
                            "faltan_horas": round(faltan, 1), "vencido": faltan < 0,
                            # asignados: para @mencionar SOLO al agente del ticket (mapeo 'tecnicos')
                            "asignados": [t["assignee_id"]] if t.get("assignee_id") else []})
        return out

    def _conteo(self):
        d = self._get("/api/v2/tickets.json?page[size]=100&sort=-created_at")
        c = {}
        for t in d.get("tickets", []):
            e = self.ESTADO.get(t.get("status"), "?")
            c[e] = c.get(e, 0) + 1
        return c

    def sla(self):
        return {"por_estado": self._conteo()}

    def sla_texto(self):
        return _resumen_estados(self._conteo())


# =========================================================================== Freshservice
class Freshservice(_BaseTickets):
    """Freshservice API v2. Auth básica api_key:X. Estados 2/3/4/5, prioridad 1/2/3/4."""

    tipo = "Freshservice"
    ESTADO = {2: ABIERTO, 3: EN_ESPERA, 4: RESUELTO, 5: CERRADO}
    EST_SET = {"cerrado": 5, "reabrir": 2, "en_espera": 3, "en_curso": 2}
    PRIO = {"baja": 1, "media": 2, "alta": 3, "urgente": 4}

    def __init__(self, cfg):
        self.base = cfg["host"].rstrip("/")
        self.h = {"Authorization": _basic(cfg["api_key"], "X"),
                  "Content-Type": "application/json"}
        self.requester = cfg.get("requester_email", cfg.get("email", ""))

    def _get(self, path):
        return _http(self.base + path, self.h)

    def _post(self, path, data):
        return _http(self.base + path, self.h, "POST", data)

    def _put(self, path, data):
        return _http(self.base + path, self.h, "PUT", data)

    def _filtrar(self, query):
        d = self._get("/api/v2/tickets/filter?query=" + urllib.parse.quote(f'"{query}"'))
        return d.get("tickets", [])

    def abiertos(self):
        ts = self._filtrar("status:2 OR status:3")
        return [{"id": t["id"], "asunto": t.get("subject", ""),
                 "estado": self.ESTADO.get(t.get("status"), "?")} for t in ts]

    def resueltos(self, n=80):
        ts = self._filtrar("status:4 OR status:5")[:n]
        out = []
        for t in ts:
            sol = ""
            try:
                full = self._get(f"/api/v2/tickets/{t['id']}?include=conversations")
                convs = full.get("ticket", {}).get("conversations", [])
                pub = [c for c in convs if not c.get("private")]
                if pub:
                    sol = pub[-1].get("body_text") or pub[-1].get("body", "")
            except Exception:  # noqa: BLE001
                pass
            out.append({"id": t["id"], "asunto": t.get("subject", ""),
                        "problema": t.get("description_text") or t.get("description", ""),
                        "solucion": sol})
        return out

    def estado(self, tid):
        t = self._get(f"/api/v2/tickets/{tid}").get("ticket", {})
        return f"#{tid}: {t.get('subject')} — {self.ESTADO.get(t.get('status'), '?')}"

    def detalle(self, tid):
        full = self._get(f"/api/v2/tickets/{tid}?include=conversations").get("ticket", {})
        partes = [f"Ticket #{tid}: {full.get('subject', '')}",
                  f"Estado: {self.ESTADO.get(full.get('status'), '?')} | Prioridad: {full.get('priority', '?')}",
                  f"DESCRIPCIÓN: {full.get('description_text') or full.get('description', '') or '(vacía)'}"]
        for i, c in enumerate([c for c in full.get("conversations", []) if not c.get("private")][-8:], 1):
            partes.append(f"Conversación {i}: {str(c.get('body_text') or c.get('body', ''))[:400]}")
        return "\n".join(partes)

    def permisos(self):
        return {"ok": True, "perfil": "Freshservice (agente)",
                "puede": {"leer": True, "crear": True, "actualizar": True, "asignar": True,
                          "responder": True},
                "resumen": "En Freshservice puedo: leer, crear, actualizar, responder y asignar "
                           "tickets (según el rol de la API key)."}

    def responder(self, tid, texto):
        self._post(f"/api/v2/tickets/{tid}/reply", {"body": texto})
        return f"💬 Respondí al cliente en el ticket #{tid} (Freshservice)."

    def crear(self, asunto, contenido):
        r = self._post("/api/v2/tickets", {
            "subject": asunto, "description": contenido, "email": self.requester,
            "priority": 2, "status": 2})
        return f"🆕 Ticket #{r.get('ticket', {}).get('id')} creado (Freshservice)."

    def cambiar_estado(self, tid, estado):
        self._put(f"/api/v2/tickets/{tid}", {"status": self.EST_SET.get(estado, 2)})
        return f"Ticket #{tid} → {estado} (Freshservice)."

    def cambiar_prioridad(self, tid, prio):
        self._put(f"/api/v2/tickets/{tid}", {"priority": self.PRIO.get(str(prio).lower(), 2)})
        return f"Ticket #{tid} → prioridad {prio} (Freshservice)."

    def asignar(self, tid, tecnico):
        rid = tecnico if str(tecnico).isdigit() else None
        if not rid:
            ag = self._get("/api/v2/agents?email=" + urllib.parse.quote(str(tecnico)))
            ags = ag.get("agents", [])
            rid = ags[0]["id"] if ags else None
        if not rid:
            return f"No encontré al agente '{tecnico}' en Freshservice (probá con su email)."
        self._put(f"/api/v2/tickets/{tid}", {"responder_id": rid})
        return f"👤 Ticket #{tid} asignado a {tecnico} (Freshservice)."

    def buscar(self, texto):
        q = (texto or "").lower()
        d = self._get("/api/v2/tickets?per_page=100&order_by=created_at&order_type=desc")
        return [{"id": t["id"], "asunto": t.get("subject", "")}
                for t in d.get("tickets", []) if q in str(t.get("subject", "")).lower()][:8]

    def en_riesgo_sla(self, horas=4):
        out = []
        for t in self._filtrar("status:2 OR status:3"):
            faltan = _horas_hasta(t.get("due_by"))
            if faltan is not None and faltan <= horas:
                out.append({"id": t["id"], "asunto": t.get("subject", ""),
                            "faltan_horas": round(faltan, 1), "vencido": faltan < 0,
                            # asignados: para @mencionar SOLO al agente del ticket (mapeo 'tecnicos')
                            "asignados": [t["responder_id"]] if t.get("responder_id") else []})
        return out

    def _conteo(self):
        d = self._get("/api/v2/tickets?per_page=100&order_by=created_at&order_type=desc")
        c = {}
        for t in d.get("tickets", []):
            e = self.ESTADO.get(t.get("status"), "?")
            c[e] = c.get(e, 0) + 1
        return c

    def sla(self):
        return {"por_estado": self._conteo()}

    def sla_texto(self):
        return _resumen_estados(self._conteo())


# ================================================================================== Jira
class Jira(_BaseTickets):
    """Jira Cloud REST API v3. Auth básica email:api_token. Búsqueda por el NUEVO
    endpoint POST /rest/api/3/search/jql (el viejo /search fue removido en 2025).
    Estados por 'transitions'. SLA de JSM por /rest/servicedeskapi cuando aplica."""

    tipo = "Jira"
    PRIO = {"baja": "Low", "media": "Medium", "alta": "High", "urgente": "Highest"}
    TRANS = {"cerrado": ("done", "closed", "resolve", "resuelto", "finaliz", "cerrar"),
             "reabrir": ("reopen", "reabrir", "to do", "backlog"),
             "en_espera": ("hold", "espera", "pending", "waiting"),
             "en_curso": ("progress", "curso", "start")}

    def __init__(self, cfg):
        self.base = cfg["host"].rstrip("/")
        self.h = {"Authorization": _basic(cfg["email"], cfg["api_token"]),
                  "Content-Type": "application/json", "Accept": "application/json"}
        self.proyecto = cfg.get("project_key", "")

    def _get(self, path):
        return _http(self.base + path, self.h)

    def _post(self, path, data):
        return _http(self.base + path, self.h, "POST", data)

    def _put(self, path, data):
        return _http(self.base + path, self.h, "PUT", data)

    def _buscar_jql(self, jql, n=50):
        campos = ["summary", "status", "priority", "assignee", "duedate", "description"]
        d = self._post("/rest/api/3/search/jql",
                       {"jql": jql, "maxResults": n, "fields": campos})
        return d.get("issues", [])

    def _proj(self):
        return f"project = {self.proyecto} AND " if self.proyecto else ""

    def abiertos(self):
        js = self._buscar_jql(self._proj() + "statusCategory != Done ORDER BY created DESC")
        return [{"id": i["key"], "asunto": i["fields"].get("summary", ""),
                 "estado": (i["fields"].get("status") or {}).get("name", "?")} for i in js]

    def resueltos(self, n=80):
        js = self._buscar_jql(self._proj() + "statusCategory = Done ORDER BY updated DESC", n)
        out = []
        for i in js:
            sol = ""
            try:
                cs = self._get(f"/rest/api/3/issue/{i['key']}/comment").get("comments", [])
                if cs:
                    sol = _adf_text(cs[-1].get("body"))
            except Exception:  # noqa: BLE001
                pass
            out.append({"id": i["key"], "asunto": i["fields"].get("summary", ""),
                        "problema": _adf_text(i["fields"].get("description")),
                        "solucion": sol})
        return out

    def estado(self, tid):
        i = self._get(f"/rest/api/3/issue/{tid}?fields=summary,status")
        f = i.get("fields", {})
        return f"#{tid}: {f.get('summary')} — {(f.get('status') or {}).get('name', '?')}"

    def detalle(self, tid):
        i = self._get(f"/rest/api/3/issue/{tid}?fields=summary,status,priority,description")
        f = i.get("fields", {})
        cs = []
        try:
            cs = self._get(f"/rest/api/3/issue/{tid}/comment").get("comments", [])
        except Exception:  # noqa: BLE001
            pass
        partes = [f"Ticket {tid}: {f.get('summary', '')}",
                  f"Estado: {(f.get('status') or {}).get('name', '?')} | "
                  f"Prioridad: {(f.get('priority') or {}).get('name', '?')}",
                  f"DESCRIPCIÓN: {_adf_text(f.get('description')) or '(vacía)'}"]
        for j, c in enumerate(cs[-8:], 1):
            partes.append(f"Comentario {j}: {_adf_text(c.get('body'))[:400]}")
        return "\n".join(partes)

    def permisos(self):
        return {"ok": True, "perfil": "Jira (usuario)",
                "puede": {"leer": True, "crear": True, "actualizar": True, "asignar": True,
                          "responder": True},
                "resumen": "En Jira puedo: leer, crear, comentar, cambiar prioridad, asignar y "
                           "transicionar estados (según los permisos del proyecto y del usuario)."}

    def responder(self, tid, texto):
        self._post(f"/rest/api/3/issue/{tid}/comment", {"body": _adf(texto)})
        return f"💬 Respondí en el ticket {tid} (Jira)."

    def crear(self, asunto, contenido):
        r = self._post("/rest/api/3/issue", {"fields": {
            "project": {"key": self.proyecto}, "summary": asunto,
            "description": _adf(contenido), "issuetype": {"name": "Task"}}})
        return f"🆕 Ticket {r.get('key')} creado (Jira)."

    def cambiar_estado(self, tid, estado):
        claves = self.TRANS.get(estado, ())
        trs = self._get(f"/rest/api/3/issue/{tid}/transitions").get("transitions", [])
        elegido = next((t for t in trs if any(
            k in (t.get("name", "") + (t.get("to") or {}).get("name", "")).lower()
            for k in claves)), None)
        if not elegido:
            disp = ", ".join(t.get("name", "") for t in trs)
            return f"No hay transición para '{estado}' en {tid}. Disponibles: {disp}"
        self._post(f"/rest/api/3/issue/{tid}/transitions",
                   {"transition": {"id": elegido["id"]}})
        return f"Ticket {tid} → {elegido.get('name')} (Jira)."

    def cambiar_prioridad(self, tid, prio):
        self._put(f"/rest/api/3/issue/{tid}",
                  {"fields": {"priority": {"name": self.PRIO.get(str(prio).lower(), "Medium")}}})
        return f"Ticket {tid} → prioridad {prio} (Jira)."

    def asignar(self, tid, tecnico):
        acc = tecnico if str(tecnico).startswith(("5", "6", "7")) and ":" in str(tecnico) else None
        if not acc:
            us = self._get("/rest/api/3/user/search?query=" + urllib.parse.quote(str(tecnico)))
            acc = us[0]["accountId"] if us else None
        if not acc:
            return f"No encontré al usuario '{tecnico}' en Jira."
        self._put(f"/rest/api/3/issue/{tid}/assignee", {"accountId": acc})
        return f"👤 Ticket {tid} asignado a {tecnico} (Jira)."

    def buscar(self, texto):
        safe = str(texto).replace('"', '')
        js = self._buscar_jql(self._proj() + f'text ~ "{safe}" ORDER BY updated DESC', 8)
        return [{"id": i["key"], "asunto": i["fields"].get("summary", "")} for i in js]

    def en_riesgo_sla(self, horas=4):
        out = []
        for i in self._buscar_jql(self._proj() + "statusCategory != Done ORDER BY created DESC"):
            faltan = None
            try:                                        # SLA de Jira Service Management
                sla = self._get(f"/rest/servicedeskapi/request/{i['key']}/sla")
                for v in sla.get("values", []):
                    oc = v.get("ongoingCycle") or {}
                    rem = (oc.get("remainingTime") or {}).get("millis")
                    if rem is not None:
                        faltan = rem / 3600000.0
                        break
            except Exception:  # noqa: BLE001
                faltan = _horas_hasta(i["fields"].get("duedate"))
            if faltan is not None and faltan <= horas:
                asg = i["fields"].get("assignee") or {}
                out.append({"id": i["key"], "asunto": i["fields"].get("summary", ""),
                            "faltan_horas": round(faltan, 1), "vencido": faltan < 0,
                            # asignados: para @mencionar SOLO al usuario del issue (mapeo 'tecnicos')
                            "asignados": [x for x in (asg.get("accountId"),
                                                      asg.get("emailAddress"),
                                                      asg.get("displayName")) if x]})
        return out

    def _conteo(self):
        c = {}
        for i in self._buscar_jql(self._proj() + "ORDER BY created DESC", 100):
            cat = ((i["fields"].get("status") or {}).get("statusCategory") or {}).get("name", "?")
            e = {"Done": RESUELTO, "In Progress": EN_CURSO, "To Do": ABIERTO}.get(cat, cat)
            c[e] = c.get(e, 0) + 1
        return c

    def sla(self):
        return {"por_estado": self._conteo()}

    def sla_texto(self):
        return _resumen_estados(self._conteo())


# ============================================================================== osTicket
class OsTicket(_BaseTickets):
    """osTicket. Su API OFICIAL solo CREA tickets (POST /api/tickets.json con X-API-Key).
    Para LEER/actualizar no hay API oficial: requiere acceso a la base MySQL o un plugin.
    Si se configura 'db_*' (MySQL), se leen los tickets por DB (requiere PyMySQL)."""

    tipo = "osTicket"

    def __init__(self, cfg):
        self.base = cfg["host"].rstrip("/")
        self.api_key = cfg.get("api_key", "")
        self.db = {k: cfg[k] for k in ("db_host", "db_user", "db_pwd", "db_name")
                   if k in cfg} if cfg.get("db_host") else None
        self.correo = cfg.get("email", "ithos@intellihelp.tech")

    # ---- lo único de la API oficial: crear ----
    def crear(self, asunto, contenido):
        h = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        r = _http(self.base + "/api/tickets.json", h, "POST", {
            "alert": True, "autorespond": True, "source": "API", "name": "ITHOS",
            "email": self.correo, "subject": asunto, "message": contenido})
        return f"🆕 Ticket creado en osTicket ({r if r else 'OK'})."

    # ---- lectura opcional por DB (si hay credenciales MySQL) ----
    def _sql(self, query, args=()):
        if not self.db:
            return []
        try:
            import pymysql
        except Exception:  # noqa: BLE001
            log.warning("osTicket: falta PyMySQL para leer por DB.")
            return []
        cx = pymysql.connect(host=self.db["db_host"], user=self.db["db_user"],
                             password=self.db["db_pwd"], database=self.db["db_name"],
                             cursorclass=pymysql.cursors.DictCursor)
        try:
            with cx.cursor() as cur:
                cur.execute(query, args)
                return cur.fetchall()
        finally:
            cx.close()

    def abiertos(self):
        filas = self._sql(
            "SELECT t.ticket_id id, t.number num, cd.subject asunto, s.name estado "
            "FROM ost_ticket t JOIN ost_ticket__cdata cd ON cd.ticket_id=t.ticket_id "
            "JOIN ost_ticket_status s ON s.id=t.status_id WHERE s.state='open' "
            "ORDER BY t.created DESC LIMIT 40")
        return [{"id": f["num"] or f["id"], "asunto": f["asunto"] or "",
                 "estado": ABIERTO} for f in filas]

    def resueltos(self, n=80):
        filas = self._sql(
            "SELECT t.ticket_id id, cd.subject asunto, "
            "(SELECT th.body FROM ost_thread_entry th JOIN ost_thread tr "
            " ON tr.id=th.thread_id WHERE tr.object_id=t.ticket_id AND th.type='R' "
            " ORDER BY th.created DESC LIMIT 1) solucion "
            "FROM ost_ticket t JOIN ost_ticket__cdata cd ON cd.ticket_id=t.ticket_id "
            "JOIN ost_ticket_status s ON s.id=t.status_id WHERE s.state IN('closed','resolved') "
            "ORDER BY t.closed DESC LIMIT %s", (n,))
        return [{"id": f["id"], "asunto": f["asunto"] or "",
                 "problema": f["asunto"] or "", "solucion": f["solucion"] or ""} for f in filas]

    def _na(self, que):
        return f"({que} no disponible en osTicket sin acceso a su base de datos)"

    def estado(self, tid):
        return self._na("estado")

    def detalle(self, tid):
        """Ticket completo desde la base MySQL (si está configurada); si no, avisa."""
        if not self.db:
            return self._na("lectura del ticket")
        filas = self._sql(
            "SELECT cd.subject asunto, s.name estado, "
            "(SELECT GROUP_CONCAT(th.body ORDER BY th.created SEPARATOR '\\n---\\n') "
            " FROM ost_thread_entry th JOIN ost_thread tr ON tr.id=th.thread_id "
            " WHERE tr.object_id=t.ticket_id) hilo "
            "FROM ost_ticket t JOIN ost_ticket__cdata cd ON cd.ticket_id=t.ticket_id "
            "JOIN ost_ticket_status s ON s.id=t.status_id "
            "WHERE t.number=%s OR t.ticket_id=%s LIMIT 1", (str(tid), str(tid)))
        if not filas:
            return f"No encontré el ticket #{tid} en osTicket."
        f = filas[0]
        return (f"Ticket #{tid}: {f.get('asunto', '')}\nEstado: {f.get('estado', '?')}\n"
                f"HILO:\n{(f.get('hilo') or '(sin mensajes)')[:1500]}")

    def permisos(self):
        tiene = "leer/actualizar por su base de datos" if self.db else "SOLO crear (API oficial)"
        return {"ok": True, "perfil": "osTicket",
                "puede": {"crear": True, "leer": bool(self.db)},
                "resumen": f"En osTicket puedo {tiene}. La API oficial solo permite crear; para "
                           "leer/cerrar/responder hace falta acceso a su base MySQL."}

    def responder(self, tid, texto):
        return self._na("responder por API")

    def cambiar_estado(self, tid, estado):
        return self._na("cambiar estado")

    def cambiar_prioridad(self, tid, prio):
        return self._na("cambiar prioridad")

    def asignar(self, tid, tecnico):
        return self._na("asignar")

    def buscar(self, texto):
        q = (texto or "").lower()
        return [t for t in self.abiertos() if q in str(t.get("asunto", "")).lower()][:8]

    def en_riesgo_sla(self, horas=4):
        return []

    def sla(self):
        return {"por_estado": {ABIERTO: len(self.abiertos())}}

    def sla_texto(self):
        return _resumen_estados({ABIERTO: len(self.abiertos())})


def crear_cliente_tickets(cfg):
    tipo = (cfg.get("tipo") or "").lower()
    clase = {"zendesk": Zendesk, "freshservice": Freshservice, "jira": Jira,
             "osticket": OsTicket}.get(tipo)
    if not clase:
        return None
    try:
        return clase(cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo crear cliente %s: %s", tipo, e)
        return None
