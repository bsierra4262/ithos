#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGENDA de tickets pospuestos (snooze inteligente). ITHOS puede dejar un ticket EN ESPERA
hasta un día/hora ('dejámelo pendiente hasta el lunes a la tarde') y lo REACTIVA solo
(EN CURSO) cuando llega ese momento.

- interpretar_cuando(texto, zona) -> (datetime, descripción) o (None, motivo) si falta la hora
  (para que ITHOS pida la hora exacta). 'a la tarde'=13:00, 'a la mañana'=09:00,
  'mediodía'=12:00, 'a la noche'=20:00; también hora explícita ('a las 15:30', '3 pm').
- programar / procesar: persiste en ~/.ithos/agenda.json y reactiva los vencidos.
"""

import os
import re
import json
import time
import logging
import threading
from datetime import datetime, timedelta

log = logging.getLogger("agenda")

# Tope de vida de una entrada vencida. Es la red de seguridad: pase lo que pase, una reactivación
# NO se reintenta para siempre. Sin esto, un ticket que ya no existe hacía que el reactivador le
# pegara a GLPI cada minuto, sin fin: 354 escrituras fallidas por hora y un log de 115 MB.
_TOPE_REINTENTOS_DIAS = 7


def _es_permanente(e):
    """True si el error dice que el ticket YA NO EXISTE: reintentarlo no va a cambiar nada.

    Se distingue del fallo PASAJERO (GLPI caído, red, timeout), que sí hay que reintentar. El
    cliente conserva el código HTTP y el motivo que devolvió GLPI, así que alcanza con mirarlos."""
    codigo = int(getattr(e, "code", 0) or 0)
    return codigo == 404 or "ERROR_ITEM_NOT_FOUND" in str(e)

DATA = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
try:
    os.makedirs(DATA, exist_ok=True)
except Exception:  # noqa: BLE001
    DATA = os.path.dirname(os.path.abspath(__file__))
_ARCHIVO = os.path.join(DATA, "agenda.json")
_LOCK = threading.Lock()

ZONA_DEFAULT = "America/Argentina/Buenos_Aires"
_DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3,
         "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6}
_DIAS_NOMBRE = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
# Franjas del día -> hora por defecto (como pidió el dueño: 'a la tarde' = 13:00).
_FRANJAS = [("mediod[ií]a", 12), ("madrugada", 6), ("(a|por|en|de) la ma[ñn]ana", 9),
            ("ma[ñn]ana temprano", 9), ("(a|por|en|de) la tarde", 13),
            ("(a|por|en|de) la noche", 20), ("mediatarde", 16)]


def _zona(zona):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(zona or ZONA_DEFAULT)
    except Exception:  # noqa: BLE001
        return None


def _hora_explicita(t):
    """Devuelve (hora, minuto) si el texto trae una hora concreta; si no, None."""
    # 'a las 15:30', '15 horas', '15hs'
    m = re.search(r"\b(?:a\s+las?\s+)?(\d{1,2})(?::(\d{2}))?\s*(?:h(?:s|oras?)?)\b", t)
    if not m:
        m = re.search(r"\b(?:a\s+las?\s+)(\d{1,2})(?::(\d{2}))?\b", t)
    # '3 pm', '3pm', '1 de la tarde'
    ampm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|a\.m\.|pm|p\.m\.|de la tarde|de la noche|de la ma[ñn]ana)\b", t)
    if ampm and 0 <= int(ampm.group(1)) <= 12:      # reloj 12h: 0..12; fuera de rango NO es válido
        h = int(ampm.group(1)) % 12
        mi = int(ampm.group(2) or 0)
        suf = ampm.group(3)
        if "pm" in suf or "p.m" in suf or "tarde" in suf or "noche" in suf:
            h += 12
        return h % 24, mi
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        if 0 <= h <= 23:
            return h, mi
    return None


def interpretar_cuando(texto, zona=ZONA_DEFAULT):
    """(datetime_aware, 'lunes 07/07 a las 13:00')  ó  (None, motivo) si no hay hora clara."""
    t = " " + re.sub(r"\s+", " ", (texto or "").lower().strip()) + " "
    z = _zona(zona)
    ahora = datetime.now(z)
    base = None                                   # fecha objetivo (date)
    # 1) día
    if "pasado mañana" in t or "pasado manana" in t:
        base = ahora.date() + timedelta(days=2)
    else:
        dia_sem = None
        for nombre, idx in _DIAS.items():
            if re.search(r"\b" + nombre + r"\b", t):
                dia_sem = idx
                break
        if dia_sem is not None:
            delta = (dia_sem - ahora.weekday()) % 7
            base = ahora.date() + timedelta(days=delta)   # próxima ocurrencia (hoy si coincide)
        elif re.search(r"\bhoy\b", t):
            base = ahora.date()
        elif re.search(r"\bma[ñn]ana\b", t) and not re.search(r"(a|por|en|de) la ma[ñn]ana", t):
            base = ahora.date() + timedelta(days=1)       # 'mañana' = día siguiente
    # 2) hora
    hm = _hora_explicita(t)
    if hm is None:
        for patron, h in _FRANJAS:                        # franja ('a la tarde' -> 13)
            if re.search(patron, t):
                hm = (h, 0)
                break
    if base is None and hm is None:
        return None, "no entendí la fecha ni la hora"
    if base is None:                                      # dieron hora pero no día -> hoy (o mañana si ya pasó)
        base = ahora.date()
    if hm is None:                                        # día sin hora -> hay que preguntar
        return None, "falta la hora"
    z_dt = datetime(base.year, base.month, base.day, hm[0], hm[1], tzinfo=z)
    if z_dt <= ahora:                                     # ya pasó -> siguiente semana/día
        z_dt += timedelta(days=7 if re.search(r"\b(" + "|".join(_DIAS) + r")\b", t) else 1)
    desc = f"{_DIAS_NOMBRE[z_dt.weekday()]} {z_dt.strftime('%d/%m')} a las {z_dt.strftime('%H:%M')}"
    return z_dt, desc


# ----------------------------------------------------------------- persistencia
def _escribir_atomico(ruta, datos):
    """Escribe JSON sin dejarlo a medias: a un temporal y recién ahí se renombra.

    Escribir directo sobre el archivo lo TRUNCA antes de empezar: si el proceso muere en el
    medio —un deploy, un reinicio— queda cortado, y como todas las lecturas tienen un `except` que
    devuelve vacío, el archivo roto se lee como "no hay nada" y el estado se pierde EN SILENCIO."""
    import json as _j
    import os as _o
    tmp = str(ruta) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            _j.dump(datos, f, ensure_ascii=False)
        _o.replace(tmp, ruta)
    except OSError:
        try:
            _o.remove(tmp)
        except OSError:
            pass
        raise


def _cargar():
    try:
        return json.load(open(_ARCHIVO, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _guardar(items):
    try:
        _escribir_atomico(_ARCHIVO, items)
    except Exception:  # noqa: BLE001
        pass


def programar(cliente, tid, epoch, desc="", silencioso=False):
    """Agenda (o reemplaza) la reactivación de un ticket. silencioso=True -> al reactivar pasa a EN
    CURSO SIN mensaje público al cliente (se usa para la reapertura por FUERA DE HORARIO, así el
    cliente no se entera del corte). silencioso=False (default, snooze pedido) -> avisa al cliente."""
    with _LOCK:
        items = [x for x in _cargar()
                 if not (x.get("cliente") == cliente and str(x.get("tid")) == str(tid))]
        items.append({"cliente": cliente, "tid": str(tid), "epoch": float(epoch),
                      "desc": desc, "silencioso": bool(silencioso), "creado": time.time()})
        _guardar(items)


def cancelar(cliente, tid):
    with _LOCK:
        _guardar([x for x in _cargar()
                  if not (x.get("cliente") == cliente and str(x.get("tid")) == str(tid))])


def pendientes(cliente=None):
    return [x for x in _cargar() if cliente is None or x.get("cliente") == cliente]


def iniciar_reactivador(cli_cfg, avisar=None, intervalo=60):
    """Lanza un hilo (daemon) que cada `intervalo`s pasa a EN CURSO los tickets pospuestos cuyo
    día/hora ya llegó, y opcionalmente avisa(mensaje). Mismo código en demo y producción."""
    from comun import tickets as _T
    nombre = cli_cfg.get("nombre") or "cliente"
    adap = _T.adaptador(cli_cfg)

    def reactivar(entry):
        tid = entry.get("tid") if isinstance(entry, dict) else entry
        try:
            adap.cambiar_estado(tid, "en_curso")
            # silencioso=True (reapertura por fuera de horario): NO se le manda mensaje al cliente,
            # solo pasa a EN CURSO. El equipo igual recibe el aviso interno (avisar) en el loop.
            if not (isinstance(entry, dict) and entry.get("silencioso")):
                try:
                    adap.responder(tid, "Retomamos su solicitud según lo agendado. Continuamos con "
                                   "la gestión. Saludos, Soporte ITH.")
                except Exception:  # noqa: BLE001
                    pass
            return True
        except Exception as e:  # noqa: BLE001
            if _es_permanente(e):
                # El ticket ya no está (lo purgaron). Reintentar no lo va a traer de vuelta: se
                # descarta la entrada. Antes se reintentaba cada minuto para siempre.
                log.warning("Agenda: el ticket #%s ya no existe en el sistema de tickets; "
                            "descarto la reactivación programada.", tid)
                return "descartar"
            return False

    def loop():
        while True:
            try:
                for h in procesar(reactivar, cliente=nombre):
                    if avisar:
                        try:
                            avisar(f"▶️ Ticket #{h['tid']} reactivado (estaba pendiente hasta "
                                   f"{h.get('desc', 'lo agendado')}). Ahora EN CURSO.")
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                pass
            time.sleep(intervalo)

    threading.Thread(target=loop, name="agenda", daemon=True).start()


def procesar(reactivar_fn, cliente=None, ahora=None):
    """Reactiva los tickets cuyo momento ya llegó. Devuelve la lista de entradas reactivadas.

    `reactivar_fn(entry)` recibe la ENTRADA completa (dict con cliente/tid/desc/silencioso) y
    devuelve:
      · `True`        -> se reactivó: la entrada se saca de la agenda;
      · `"descartar"` -> NO se va a poder nunca (el ticket ya no existe): también se saca;
      · cualquier otra cosa -> fallo PASAJERO: se reintenta en la vuelta siguiente.

    Antes sólo había dos casos y todo lo que no fuera éxito se reintentaba, sin límite. Tres
    tickets que habían sido purgados en GLPI quedaron así para siempre: el reactivador les pegaba
    cada minuto, lo que daba 354 escrituras fallidas por hora, 21.596 advertencias por día y un
    log de 115 MB. Un reintento sin condición de salida no es tolerancia a fallos, es un bucle.

    Y el archivo se guardaba sólo `if hechos`, así que una entrada descartada ni siquiera se
    habría podido borrar: ahora se guarda también cuando se descarta algo."""
    ahora = ahora or time.time()
    hechos, descartados = [], []
    with _LOCK:
        items = _cargar()
    quedan, vencidos = [], []
    for x in items:
        if (cliente is None or x.get("cliente") == cliente) and float(x.get("epoch", 0)) <= ahora:
            vencidos.append(x)
        else:
            quedan.append(x)
    for x in vencidos:
        try:
            r = reactivar_fn(x)
        except Exception:  # noqa: BLE001
            r = False
        if r is True:
            hechos.append(x)
        elif r == "descartar":
            descartados.append(x)
        elif float(x.get("epoch", 0)) < ahora - _TOPE_REINTENTOS_DIAS * 86400:
            # Red de seguridad, por si el motivo del fallo no se puede reconocer: una entrada
            # vencida hace más de una semana ya no se reintenta más. Si el ticket sigue vivo y
            # hace falta, el técnico lo retoma a mano; lo que no puede pasar es el bucle eterno.
            log.warning("Agenda: la reactivación del ticket #%s lleva más de %d días fallando; "
                        "la descarto para no seguir reintentando.",
                        x.get("tid"), _TOPE_REINTENTOS_DIAS)
            descartados.append(x)
        else:
            quedan.append(x)               # fallo pasajero -> reintentar después
    if hechos or descartados:
        with _LOCK:
            _guardar(quedan)
    return hechos
