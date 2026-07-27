#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Facturación / SUSCRIPCIONES por cliente (SaaS) con MercadoPago (Argentina y LatAm).
Usa la API REST de MercadoPago (sin dependencias extra). Cada cliente tiene su plan y
su estado de pago; el cobro es una SUSCRIPCIÓN recurrente (preapproval).

Config por cliente (clientes.json -> "facturacion"):
  {"enabled": true, "plan": "Mensual", "monto": 15000, "moneda": "ARS",
   "email": "cliente@empresa.com", "mp_access_token": "APP_USR-...",
   "preapproval_id": "", "estado": ""}
El mp_access_token puede ser el NUESTRO (cobramos nosotros) — se puede poner uno global.

Flujo: crear_suscripcion() -> devuelve init_point (link de pago) -> el cliente paga ->
MercadoPago avisa por webhook -> estado_suscripcion() confirma "authorized".
"""

import os
import json
import time
import hmac
import hashlib
import logging
import urllib.request

log = logging.getLogger("facturacion")
API = "https://api.mercadopago.com"
# Estado de facturación por cliente (persistido por el webhook). Ruta portable (Win/Linux/Mac).
_DATA = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_COT = {"venta": None, "ts": 0}


def _req(metodo, ruta, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + ruta, data=data, method=metodo, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def cotizacion_bna():
    """Dólar OFICIAL (Banco Nación) — venta. Se cachea 1 hora. Fuente: dolarapi."""
    if _COT["venta"] and time.time() - _COT["ts"] < 3600:
        return _COT["venta"]
    for url in ("https://dolarapi.com/v1/dolares/oficial",
                "https://api.bluelytics.com.ar/v2/latest"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            d = json.load(urllib.request.urlopen(req, timeout=15))
            venta = d.get("venta") or d.get("oficial", {}).get("value_sell")
            if venta:
                _COT.update(venta=float(venta), ts=time.time())
                return float(venta)
        except Exception:  # noqa: BLE001
            continue
    return _COT["venta"] or 0.0


def desglose_precio(fact):
    """Cuánto COBRAR para que, tras la comisión de MercadoPago, nos quede el NETO deseado.
      neto_usd     = lo que queremos recibir (el precio real del plan).
      comision_pct = lo que retiene MP por transacción (configurable: cambia según medio de pago
                     y plazo de acreditación; ponerlo con la tarifa real del simulador de MP).
      bruto_usd    = neto / (1 - comision/100)   -> así después de la comisión nos queda el neto.
    Todo se pasa a PESOS al dólar oficial BNA del día."""
    neto = float(fact.get("monto_usd", fact.get("monto", 0)) or 0)
    pct = float(fact.get("comision_pct", 0) or 0)
    bruto = neto / (1 - pct / 100) if 0 < pct < 100 else neto
    es_ars = (fact.get("moneda") or "ARS").upper() == "ARS"
    cot = cotizacion_bna() if (es_ars and bruto) else 1.0
    ars = round(bruto * cot) if (es_ars and cot) else round(bruto)
    return {"neto_usd": round(neto, 2), "comision_pct": pct, "bruto_usd": round(bruto, 2),
            "cotizacion_bna": cot, "ars": ars}


def monto_ars(fact):
    """(compat) Devuelve (ars_a_cobrar, cotización) — YA con la comisión de MP sumada (gross-up),
    para que el neto que nos queda sea el precio real del plan."""
    d = desglose_precio(fact)
    return d["ars"], d["cotizacion_bna"]


def crear_suscripcion(fact, cliente, back_url=None):
    """Crea una suscripción recurrente y devuelve {id, init_point (link para pagar)}.
    El precio se define en USD y se cobra en PESOS al dólar oficial del BNA.
    back_url: adónde vuelve el pagador tras autorizar. MP exige una URL https válida; si no se
    pasa una, se usa la del cliente (fact['back_url']) o una pública válida por defecto."""
    token = fact.get("mp_access_token", "")
    if not token:
        return {"error": "falta el access token de MercadoPago"}
    dp = desglose_precio(fact)
    ars, cot = dp["ars"], dp["cotizacion_bna"]
    bu = back_url or fact.get("back_url") or "https://www.mercadopago.com.ar"
    body = {
        "reason": f"ITHOS — {cliente} ({fact.get('plan', 'Mensual')})",
        "auto_recurring": {
            "frequency": 1, "frequency_type": "months",
            "transaction_amount": float(ars),      # incluye la comisión de MP (gross-up)
            "currency_id": fact.get("moneda", "ARS")},
        "payer_email": fact.get("email", ""),
        "back_url": bu, "status": "pending",
    }
    try:
        d = _req("POST", "/preapproval", token, body)
        return {"id": d.get("id"), "init_point": d.get("init_point"),
                "estado": d.get("status"), "monto_ars": ars, "cotizacion_bna": cot,
                "monto_usd": dp["neto_usd"], "monto_usd_bruto": dp["bruto_usd"],
                "comision_pct": dp["comision_pct"]}
    except Exception as e:  # noqa: BLE001
        log.warning("MercadoPago crear_suscripcion: %s", e)
        return {"error": str(e)[:160]}


def estado_suscripcion(fact):
    """Consulta el estado real de la suscripción (authorized / paused / cancelled)."""
    token = fact.get("mp_access_token", "")
    pid = fact.get("preapproval_id", "")
    if not token or not pid:
        return {"estado": fact.get("estado", "sin_suscripcion")}
    try:
        d = _req("GET", f"/preapproval/{pid}", token)
        return {"estado": d.get("status"), "monto": d.get("auto_recurring", {}).get("transaction_amount"),
                "proximo_cobro": d.get("next_payment_date")}
    except Exception as e:  # noqa: BLE001
        return {"estado": "error", "detalle": str(e)[:120]}


def al_dia(fact):
    """True si está paga/activa, si no tiene facturación, o si es el DUEÑO (propietario:
    nuestra empresa NUNCA se cobra)."""
    if not fact or fact.get("propietario") or not fact.get("enabled"):
        return True
    return (fact.get("estado") or estado_suscripcion(fact).get("estado")) == "authorized"


# ------------------------------------------ ciclo de suscripción: dunning + gracia + suspensión
import datetime as _dt   # noqa: E402

GRACIA_DIAS_HABILES = 7   # días HÁBILES de gracia tras un impago antes de CONGELAR el servicio


def _dias_habiles(desde_ts, hasta_ts):
    """Días HÁBILES (lun-vie) entre dos epochs. No cuenta feriados (simplificación conservadora)."""
    if not desde_ts or not hasta_ts or hasta_ts <= desde_ts:
        return 0
    d, d1, n = _dt.date.fromtimestamp(desde_ts), _dt.date.fromtimestamp(hasta_ts), 0
    while d < d1:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def suspendido(fact):
    """True si la suscripción está SUSPENDIDA por falta de pago: TODO congelado (IA + ITHOS sin
    acceso) hasta renovar. El propietario (nuestra empresa) NUNCA se suspende."""
    return bool(fact) and bool(fact.get("suspendido")) and not fact.get("propietario")


def evaluar(fact, ahora=None):
    """Evalúa el ciclo de pago del cliente y devuelve (accion, cambios):
       · 'ok'        -> al día (o propietario/sin facturación). Reactiva si estaba suspendido.
       · 'avisar'    -> impago DENTRO de la gracia: hay que mandarle el link de pago.
       · 'suspender' -> pasaron los días hábiles de gracia sin pagar: CONGELAR.
    'cambios' son los campos de 'facturacion' a persistir (impago_desde, suspendido)."""
    ahora = ahora or time.time()
    if not fact or fact.get("propietario") or not fact.get("enabled"):
        return "ok", {}
    if al_dia(fact):
        cambios = {}
        if fact.get("impago_desde"):
            cambios["impago_desde"] = None       # volvió a estar al día -> limpiar
        if fact.get("suspendido"):
            cambios["suspendido"] = False         # reactivación automática
        return "ok", cambios
    impago = fact.get("impago_desde") or ahora
    cambios = {"impago_desde": impago}
    if _dias_habiles(impago, ahora) >= GRACIA_DIAS_HABILES:
        if not fact.get("suspendido"):
            cambios["suspendido"] = True
        return "suspender", cambios
    return "avisar", cambios


def dias_gracia_restantes(fact, ahora=None):
    imp = fact.get("impago_desde")
    if not imp:
        return GRACIA_DIAS_HABILES
    return max(0, GRACIA_DIAS_HABILES - _dias_habiles(imp, ahora or time.time()))


def link_pago(fact, cliente):
    """Link de pago para renovar/regularizar la suscripción. Reusa el init_point guardado o crea uno."""
    if fact.get("init_point"):
        return fact["init_point"]
    return (crear_suscripcion(fact, cliente) or {}).get("init_point", "")


def texto_aviso_pago(cliente, fact, link, suspender=False, dias_rest=None):
    """Mensaje de cobranza para mandar por email/canales (con el link de pago)."""
    try:
        monto = ("$" + format(desglose_precio(fact)["ars"], ",.0f").replace(",", ".") + " ARS")
    except Exception:  # noqa: BLE001
        monto = ""
    if suspender:
        return (f"⛔ ITHOS — suscripción SUSPENDIDA de {cliente}. Pasaron los {GRACIA_DIAS_HABILES} días "
                f"hábiles de gracia sin registrarse el pago: el servicio quedó CONGELADO (IA e ITHOS sin "
                f"acceso) hasta renovar.\nRenová acá para reactivar: {link}" + (f"\nMonto: {monto}." if monto else ""))
    cola = f" Te quedan {dias_rest} días hábiles antes de que se congele el servicio." if dias_rest is not None else ""
    return (f"⚠️ ITHOS — tu suscripción de {cliente} está pendiente de pago.{cola}\n"
            f"Pagá acá para no perder el servicio: {link}" + (f"\nMonto: {monto}." if monto else ""))


# --------------------------------------------------------------------- webhook
# Notificaciones (webhooks) de MercadoPago: MP avisa por HTTP cuando cambia una suscripción o
# entra un pago recurrente, así el estado se actualiza SOLO (sin poll). Doc oficial:
# developers → your-integrations → notifications → webhooks.

def validar_firma(secret, x_signature, x_request_id, data_id):
    """Valida la firma 'x-signature' del webhook (HMAC-SHA256), según la doc oficial de MP:
       manifest = "id:{data.id};request-id:{x-request-id};ts:{ts};"  y  HMAC(secret) == v1.
    Si no hay 'secret' configurado, NO se valida (True). Comparación en tiempo constante."""
    if not secret:
        return True
    if not x_signature:
        return False
    try:
        partes = dict(p.split("=", 1) for p in x_signature.split(",") if "=" in p)
        ts, v1 = partes.get("ts", "").strip(), partes.get("v1", "").strip()
        if not ts or not v1:
            return False
        did = str(data_id or "")
        if did and not did.isdigit():      # data.id alfanumérico -> MP lo pide en minúscula
            did = did.lower()
        manifest = f"id:{did};request-id:{x_request_id or ''};ts:{ts};"
        calc = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(calc, v1)
    except Exception:  # noqa: BLE001
        return False


def procesar_notificacion(fact, tipo, data_id):
    """Consulta a MP el recurso notificado y devuelve el estado ACTUALIZADO de la suscripción.
    tipo: 'subscription_preapproval' | 'subscription_authorized_payment' | 'preapproval' | ...
    Devuelve {} si no aplica o no se puede consultar."""
    token = fact.get("mp_access_token", "")
    if not token or not data_id:
        return {}
    try:
        if tipo in ("subscription_preapproval", "preapproval"):
            d = _req("GET", f"/preapproval/{data_id}", token)
            return {"preapproval_id": d.get("id"), "estado": d.get("status"),
                    "next_payment_date": d.get("next_payment_date"),
                    "payer_email": d.get("payer_email"),   # email REAL del pagador (lo confirma MP)
                    "monto": (d.get("auto_recurring") or {}).get("transaction_amount")}
        if tipo == "subscription_authorized_payment":
            d = _req("GET", f"/authorized_payments/{data_id}", token)
            return {"preapproval_id": d.get("preapproval_id"),
                    "ultimo_pago_estado": d.get("status"),
                    "ultimo_pago_fecha": d.get("date_created")}
    except Exception as e:  # noqa: BLE001
        log.warning("procesar_notificacion (%s): %s", tipo, e)
    return {}


def _estado_path(cliente):
    seguro = "".join(ch if ch.isalnum() else "_" for ch in (cliente or "cliente"))
    return os.path.join(_DATA, f"facturacion_{seguro}.json")


def cargar_estado(cliente):
    try:
        return json.load(open(_estado_path(cliente), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def guardar_estado(cliente, datos):
    """Persiste (merge) el estado de facturación del cliente que trae el webhook."""
    try:
        os.makedirs(_DATA, exist_ok=True)
        st = cargar_estado(cliente)
        st.update({k: v for k, v in (datos or {}).items() if v is not None})
        st["actualizado"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_estado_path(cliente), "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        return st
    except Exception as e:  # noqa: BLE001
        log.warning("guardar_estado %s: %s", cliente, e)
        return {}
