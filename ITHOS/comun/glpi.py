#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente REST de GLPI (compartido). Portado del monolito. Sin dependencias (urllib).
Se usa desde el integrador, corra en el central o en el agente.
"""

import re
import json
import threading
import urllib.request
import urllib.error


class GLPIClient:
    def __init__(self, cfg, token=None):
        self.cfg = cfg
        self.base = cfg["glpi_url"].rstrip("/")
        self.app_token = cfg["glpi_app_token"]
        self.user_token = token or cfg["glpi_user_token"]
        self.session = None
        self._lock = threading.Lock()          # para reabrir la sesión sin carreras

    def request(self, path, method="GET", data=None, timeout=20, _reintento_sesion=True):
        headers = {"App-Token": self.app_token, "Content-Type": "application/json"}
        if self.session:
            headers["Session-Token"] = self.session
        else:
            headers["Authorization"] = f"user_token {self.user_token}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        # Reintento ante errores TRANSITORIOS (5xx / red / timeout). Los 4xx (permiso/no
        # encontrado) NO se reintentan. EXCEPCIÓN: si la SESIÓN expiró (401), se REABRE y
        # reintenta una vez (así las sesiones persistentes del pool se auto-renuevan solas).
        import time as _t
        ultimo = None
        for intento in range(3):
            req = urllib.request.Request(self.base + path, data=body,
                                         headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                code = int(getattr(e, "code", 0) or 0)
                cuerpo = ""
                try:
                    cuerpo = e.read().decode("utf-8", "ignore")   # GLPI explica el error en el body
                except Exception:  # noqa: BLE001
                    pass
                if code in (401, 403) and self.session and _reintento_sesion and path != "/initSession":
                    if code == 401 or "SESSION_TOKEN" in cuerpo or "ERROR_SESSION" in cuerpo:
                        self.session = None                # expiró -> reabrir y reintentar 1 vez
                        try:
                            self.abrir()
                        except Exception:  # noqa: BLE001
                            raise
                        return self.request(path, method, data, timeout, _reintento_sesion=False)
                if 500 <= code < 600 and intento < 2:
                    ultimo = e
                    _t.sleep(0.6 * (intento + 1))
                    continue
                # 4xx (o 5xx agotado): incluye el MOTIVO de GLPI (body) + la ruta -> diagnóstico claro.
                raise urllib.error.HTTPError(
                    self.base + path, code, f"{e.reason} en {path} — {cuerpo[:200]}".strip(),
                    e.headers, None)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:  # noqa: PERF203
                if intento < 2:
                    ultimo = e
                    _t.sleep(0.6 * (intento + 1))
                    continue
                raise
        if ultimo:
            raise ultimo
        return {}

    def abrir(self):
        self.session = None
        self.session = self.request("/initSession", _reintento_sesion=False)["session_token"]
        return self

    def cerrar(self):
        # Las sesiones del POOL NO se matan (se reutilizan): así el patrón 'finally: cerrar()'
        # que hay por todo el código queda como no-op y la sesión sigue viva para la próxima.
        if getattr(self, "_pooled", False) or not self.session:
            return
        try:
            self.request("/killSession", _reintento_sesion=False)
        except Exception:  # noqa: BLE001
            pass
        self.session = None

    # Context manager: 'with GLPIClient(cfg).abrir() as c:' garantiza el cierre (mata la
    # sesión al terminar, aunque haya error) -> no se acumulan sesiones en GLPI.
    def __enter__(self):
        if not self.session:
            self.abrir()
        return self

    def __exit__(self, *_exc):
        self.cerrar()
        return False

    def tickets_recientes(self, n=30):
        return self.request(f"/Ticket?range=0-{n - 1}&sort=id&order=DESC")

    def todos_tickets(self, tam=1000):
        """TODOS los tickets del cliente, SIN límite artificial: pagina de a `tam` hasta que no
        quedan más. Así el total y los reportes (incluidos los rangos semanal/mensual) muestran
        SIEMPRE los datos REALES, por muchos tickets que tenga (GLPI capa el range por request)."""
        out, inicio = [], 0
        while True:
            chunk = self.request(f"/Ticket?range={inicio}-{inicio + tam - 1}&sort=id&order=DESC")
            if not isinstance(chunk, list) or not chunk:
                break
            out.extend(chunk)
            if len(chunk) < tam:            # última página incompleta -> no hay más
                break
            inicio += tam
            if inicio > 500000:             # tope de seguridad (evita un bucle infinito por error)
                break
        return out


# ---------------------------------------------------------------- POOL de sesiones
# Se mantiene UNA sesión VIVA por (URL, token/rol) y se REUSA siempre (no se abre/cierra en
# cada llamada -> más rápido y no se agotan sesiones). Si expira, request() la reabre sola.
# Como mucho hay ~4 sesiones (super admin, helpdesk, ithos, cliente), reutilizadas.
_POOL = {}
_POOL_LOCK = threading.Lock()


def sesion(cfg, token=None):
    """Devuelve un GLPIClient con la sesión VIVA para ese token (del pool, reutilizada)."""
    tok = token or cfg.get("glpi_ithos_token") or cfg.get("glpi_user_token")
    key = (cfg.get("glpi_url"), tok)
    with _POOL_LOCK:
        c = _POOL.get(key)
        if c is None:
            c = GLPIClient(cfg, token=tok)
            c._pooled = True                   # no se mata en cerrar(): se reutiliza
            _POOL[key] = c
        if not c.session:
            c.abrir()
        return c


def de_entidad(tickets, entidad):
    return [t for t in tickets if isinstance(t, dict)
            and int(t.get("entities_id", -1)) == entidad]


# Caché CORTO de la lista de tickets: el SLA, el reporte ITIL y el panorama la pedían cada uno
# por su lado (lento). Con esto una consulta reciente se reusa (una sola sesión/lectura).
_TCACHE = {}


def tickets_cache(cfg, n=300, ttl=45):
    """tickets_recientes(n) con caché de `ttl` segundos por (URL, n). Abre y CIERRA la sesión."""
    import time
    key = (cfg.get("glpi_url"), int(n))
    ent = _TCACHE.get(key)
    if ent and time.time() - ent[0] < ttl:
        return ent[1]
    ts = sesion(cfg, cfg.get("glpi_ithos_token")).tickets_recientes(n)   # sesión viva del pool
    _TCACHE[key] = (time.time(), ts)
    return ts


def tickets_todos_cache(cfg, ttl=45):
    """TODOS los tickets (paginados, sin límite) con caché de `ttl` seg por URL. Para reportes
    y stats que deben mostrar el total REAL, no una muestra."""
    import time
    key = (cfg.get("glpi_url"), "TODOS")
    ent = _TCACHE.get(key)
    if ent and time.time() - ent[0] < ttl:
        return ent[1]
    ts = sesion(cfg, cfg.get("glpi_ithos_token")).todos_tickets()   # sesión viva del pool
    _TCACHE[key] = (time.time(), ts)
    return ts


def frase_ticket(t):
    """Anuncio hablado del ticket: número, asunto y hora de creación."""
    asunto = str(t.get("name", "")).strip()
    fecha = str(t.get("date_creation") or t.get("date") or "")
    m = re.search(r"\s(\d{1,2}):(\d{2})", fecha)
    cola = (f" Creado a las {int(m.group(1))} horas y {int(m.group(2))} minutos."
            if m else "")
    return f"Atención. Ticket número {t.get('id')}. {asunto}.{cola}"


def mensaje_ticket(t):
    """Mensaje de WhatsApp del ticket."""
    asunto = str(t.get("name", "")).strip()
    fecha = str(t.get("date_creation") or t.get("date") or "").strip()
    return (f"\U0001F3AB *Nuevo ticket #{t.get('id')}*\n{asunto}\n\U0001F550 {fecha}")


def nombre_pila(cliente, uid):
    """Nombre de PILA del usuario `uid`, leído con `cliente` (que debe poder leer /User; el token de
    ithos NO puede, usar el de lectura/admin). '' si no se puede resolver."""
    try:
        u = cliente.request(f"/User/{int(uid or 0)}")
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(u, list):
        u = u[0] if u else {}
    if not isinstance(u, dict):
        return ""
    completo = (str(u.get("firstname") or "").strip() or str(u.get("realname") or "").strip()
                or str(u.get("name") or "").strip())
    return completo.split()[0] if completo else ""


def saludo_solicitante(texto, nombre):
    """Garantiza que la 1ª respuesta salude al SOLICITANTE (quien ABRIÓ el ticket) por su nombre de
    pila, NUNCA a la persona AFECTADA que aparezca en el texto. Si el texto empieza con un saludo
    ('Hola X,' / 'Estimado X:'), reemplaza ese saludo por 'Hola {nombre},'; si no, lo antepone. Sin
    nombre, deja el texto igual. Compartido por el triage automático y el camino de voz (aplicar_ciclo)."""
    texto = (texto or "").strip()
    if not nombre:
        return texto
    m = re.match(r"^\s*(hola|estimad[oa]s?|buenas|buen[oa]s?\s+d[ií]as?|buen d[ií]a)\b[^\n,:;.!]*",
                 texto, re.I)
    if m:
        resto = texto[m.end():].lstrip(" ,:;").lstrip()
        return f"Hola {nombre}, {resto}" if resto else f"Hola {nombre}."
    return f"Hola {nombre}, {texto}"
