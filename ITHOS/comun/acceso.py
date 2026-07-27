#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adaptador GENÉRICO de sistemas de CONTROL DE ACCESO (portero/fichajes). Igual que
comun/tickets.py pero para acceso: ITHOS habla con esta interfaz común, así lo de
anomalías por horario funciona para HikCentral, BioStar 2, etc. sin código a medida.

Interfaz común:
  soporta_anomalias() -> bool   (True solo si el sistema hace control de horario y
                                 expone su config por API; así se AUTOCONFIGURA solo)
  horarios()          -> [ {persona|door, dias, desde, hasta} ]  (leído por API, sin
                                 que el cliente configure nada a mano)
  anomalias(desde)    -> [ {nombre, cuando, motivo} ]  (fichajes fuera de horario /
                                 denegados por horario, según lo que informa el sistema)

Diseño por pedido del usuario:
  - IVMS / ZKTeco / Honeywell: NO hacen control de horario -> soporta_anomalias()=False.
    (En NUESTRA empresa usamos IVMS y no tomamos control horario: nunca se activa.)
  - HikCentral / BioStar 2: SÍ. Toman su configuración de horarios por su propia API
    automáticamente (sin configurar nada). El detector queda OFF por defecto igual;
    se prende por cliente cuando ese cliente quiere.

TODO por cliente: se construye desde el cfg AISLADO de la empresa.
"""

import os
import sys
import json
import logging
import urllib.request

log = logging.getLogger("acceso")
_AGENTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agente")


class _Base:
    tipo = "generico"

    def soporta_anomalias(self):
        return False

    def horarios(self):
        return []

    def anomalias(self, desde=None):
        return []


class _SinHorario(_Base):
    """IVMS / ZKTeco / Honeywell: no hay control de horario -> nunca genera anomalías."""

    def __init__(self, tipo, cfg):
        self.tipo = tipo
        self.cfg = cfg or {}


class _HikCentral(_Base):
    """HikCentral Professional OpenAPI (Artemis). Autoconfigura horarios por API.
    Reusa la firma HMAC del integrador del agente."""

    tipo = "hikcentral"
    # Endpoints típicos (ajustar a la versión del cliente):
    EP_HORARIOS = "/artemis/api/attendance/v1/schedule/list"
    EP_EVENTOS = "/artemis/api/acs/v1/door/events"

    def __init__(self, cfg):
        self.cfg = cfg or {}

    def _post(self, path, payload):
        if _AGENTE not in sys.path:
            sys.path.insert(0, _AGENTE)
        import integrador_hikcentral as H
        return H._post(self.cfg["host"], path, self.cfg["app_key"],
                       self.cfg["app_secret"], payload, self.cfg.get("verify_ssl", False))

    def soporta_anomalias(self):
        return bool(self.cfg.get("host") and self.cfg.get("app_key"))

    def horarios(self):
        try:
            r = self._post(self.EP_HORARIOS, {"pageNo": 1, "pageSize": 200})
            filas = (r.get("data") or {}).get("list") or []
            return [{"persona": f.get("personName"), "dias": f.get("weekDays"),
                     "desde": f.get("startTime"), "hasta": f.get("endTime")} for f in filas]
        except Exception as e:  # noqa: BLE001
            log.info("HikCentral horarios (API a ajustar): %s", e)
            return []

    def anomalias(self, desde=None):
        """Fichajes que el propio HikCentral marca como fuera de horario / denegados
        por franja. Se apoya en el eventType del evento (self-config, sin cargar
        horarios a mano). Degrada a [] si la API no está disponible."""
        import time as _t
        from datetime import datetime, timedelta

        def _iso(dt):
            off = -_t.timezone
            s = "+" if off >= 0 else "-"
            off = abs(off)
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + f"{s}{off // 3600:02d}:{(off % 3600) // 60:02d}"
        try:
            fin = datetime.now()
            ini = fin - timedelta(minutes=self.cfg.get("ventana_min", 15))
            r = self._post(self.EP_EVENTOS, {"pageNo": 1, "pageSize": 100,
                                             "startTime": _iso(ini), "endTime": _iso(fin)})
            evs = (r.get("data") or {}).get("list") or []
        except Exception as e:  # noqa: BLE001
            log.info("HikCentral anomalías (API a ajustar): %s", e)
            return []
        out = []
        for ev in evs:
            et = str(ev.get("eventType") or ev.get("eventTypeName") or "").lower()
            if any(k in et for k in ("schedule", "time zone", "timezone", "franja",
                                     "invalid time", "fuera de horario", "denied")):
                out.append({"nombre": str(ev.get("personName") or "?"),
                            "cuando": ev.get("eventTime"),
                            "motivo": "fichaje fuera de horario / denegado por franja"})
        return out


class _BioStar2(_Base):
    """Suprema BioStar 2 REST. Autoconfigura horarios por API. Reusa login/req del
    integrador del agente."""

    tipo = "biostar2"

    def __init__(self, cfg):
        self.cfg = cfg or {}
        self._session = None

    def _mod(self):
        if _AGENTE not in sys.path:
            sys.path.insert(0, _AGENTE)
        import integrador_biostar2 as B
        return B

    def _sess(self, B):
        if not self._session:
            self._session = B._login(self.cfg["host"], self.cfg["login_id"],
                                     self.cfg["password"], self.cfg.get("verify_ssl", False))
        return self._session

    def soporta_anomalias(self):
        return bool(self.cfg.get("host") and self.cfg.get("login_id"))

    def horarios(self):
        try:
            B = self._mod()
            s = self._sess(B)
            _, r = B._req(self.cfg["host"], "/api/schedules", "GET",
                          session=s, verify=self.cfg.get("verify_ssl", False))
            filas = (r.get("ScheduleCollection") or {}).get("rows") or r.get("schedules") or []
            return [{"nombre": f.get("name"), "dias": f.get("days"),
                     "desde": f.get("start_time"), "hasta": f.get("end_time")} for f in filas]
        except Exception as e:  # noqa: BLE001
            log.info("BioStar2 horarios (API a ajustar): %s", e)
            return []

    def anomalias(self, desde=None):
        try:
            B = self._mod()
            s = self._sess(B)
            consulta = {"Query": {"limit": 50,
                                  "orders": [{"desc": True, "column": "datetime"}]}}
            _, r = B._req(self.cfg["host"], "/api/events/search", "POST",
                          data=consulta, session=s, verify=self.cfg.get("verify_ssl", False))
            evs = (r.get("EventCollection") or {}).get("rows") or r.get("events") or []
        except Exception as e:  # noqa: BLE001
            self._session = None
            log.info("BioStar2 anomalías (API a ajustar): %s", e)
            return []
        out = []
        for ev in evs:
            et = str(ev.get("event_type_id") or ev.get("type_name") or "").lower()
            if any(k in et for k in ("schedule", "time zone", "timezone", "franja",
                                     "invalid", "denied", "fuera de horario")):
                usr = ev.get("user") or {}
                out.append({"nombre": str(usr.get("name") or ev.get("user_id") or "?"),
                            "cuando": ev.get("datetime"),
                            "motivo": "fichaje fuera de horario / denegado por franja"})
        return out


class _ZKTeco(_Base):
    """ZKTeco (ZKBio CVSecurity / BioTime). Detecta accesos denegados por franja horaria
    (time zone inválida) leyendo las transacciones por su API REST."""

    tipo = "zkteco"
    PLATAFORMAS = {"zkbiosecurity": ("/api-token-auth/", "Token", "/acc/api/transactions/"),
                   "zkbiotime": ("/jwt-api-token-auth/", "JWT", "/iclock/api/transactions/")}

    def __init__(self, cfg):
        self.cfg = cfg or {}
        plat = (self.cfg.get("plataforma") or "zkbiosecurity").lower()
        self.login, self.pref, self.tx = self.PLATAFORMAS.get(
            plat, self.PLATAFORMAS["zkbiosecurity"])
        self.tx = self.cfg.get("transacciones_path", self.tx)
        self._token = None

    def soporta_anomalias(self):
        return bool(self.cfg.get("host") and self.cfg.get("username"))

    def _j(self, url, headers=None, data=None, method="GET"):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "{}")

    def anomalias(self, desde=None):
        host = self.cfg["host"].rstrip("/")
        try:
            if not self._token:
                self._token = self._j(host + self.login, {"Content-Type": "application/json"},
                                       {"username": self.cfg["username"],
                                        "password": self.cfg["password"]}, "POST").get("token")
            r = self._j(f"{host}{self.tx}?page_size=50&ordering=-id",
                        {"Authorization": f"{self.pref} {self._token}"})
        except Exception as e:  # noqa: BLE001
            self._token = None
            log.info("ZKTeco anomalías (API a ajustar): %s", e)
            return []
        out = []
        for ev in (r.get("data") or r.get("results") or []):
            est = str(ev.get("event_name") or ev.get("verify_type_name") or "").lower()
            if any(k in est for k in ("time zone", "timezone", "franja", "invalid", "denied",
                                      "fuera de horario")):
                out.append({"nombre": str(ev.get("name") or ev.get("emp_name") or "?"),
                            "cuando": ev.get("event_time") or ev.get("punch_time"),
                            "motivo": "acceso denegado por franja horaria"})
        return out


class _Honeywell(_Base):
    """Honeywell Pro-Watch API Service. Detecta accesos denegados por franja/time zone."""

    tipo = "honeywell"

    def __init__(self, cfg):
        self.cfg = cfg or {}

    def soporta_anomalias(self):
        return bool(self.cfg.get("host") and (self.cfg.get("usuario") or self.cfg.get("api_key")))

    def anomalias(self, desde=None):
        import ssl
        import base64
        c = self.cfg
        host = c["host"].rstrip("/")
        if (c.get("auth") or "basic").lower() == "bearer":
            h = {"Authorization": f"Bearer {c.get('api_key', '')}"}
        else:
            tok = base64.b64encode(f"{c.get('usuario', '')}:{c.get('password', '')}".encode()).decode()
            h = {"Authorization": "Basic " + tok}
        ctx = None
        if not c.get("verify_ssl", False):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            req = urllib.request.Request(host + c.get("eventos_path", "/api/Events") + "?limit=50",
                                         headers=h)
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                d = json.loads(r.read().decode() or "{}")
        except Exception as e:  # noqa: BLE001
            log.info("Honeywell anomalías (API a ajustar): %s", e)
            return []
        evs = d.get("events") or d.get("Events") or d.get("value") or d.get("data") or []
        out = []
        for ev in evs:
            desc = str(ev.get("EventDescription") or ev.get("description") or "").lower()
            if any(k in desc for k in ("time zone", "schedule", "franja", "invalid", "denied",
                                       "fuera de horario")):
                out.append({"nombre": str(ev.get("CardholderName") or ev.get("personName") or "?"),
                            "cuando": ev.get("Timestamp") or ev.get("timestamp"),
                            "motivo": "acceso denegado por franja horaria"})
        return out


def adaptador(cli_cfg):
    """Devuelve el adaptador de acceso del cliente (según su 'integrador'). Los sistemas
    con control horario (HikCentral, BioStar 2, ZKTeco, Honeywell) exponen anomalías por
    su API; IVMS (fichajes en SQL, sin franjas) no hace control horario."""
    tipo = (cli_cfg.get("integrador") or "").lower()
    cfg = cli_cfg.get("integrador_config") or {}
    if tipo == "hikcentral":
        return _HikCentral(cfg)
    if tipo == "biostar2":
        return _BioStar2(cfg)
    if tipo == "zkteco":
        return _ZKTeco(cfg)
    if tipo == "honeywell":
        return _Honeywell(cfg)
    return _SinHorario(tipo or "generico", cfg)     # ivms / otro (sin control horario)
