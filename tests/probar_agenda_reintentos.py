#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: una reactivación programada no se puede reintentar para siempre.

EL BUG. `procesar()` tenía dos casos nada más: o la reactivación salía bien y la entrada se
borraba, o fallaba y volvía a la agenda —sin límite y sin mirar POR QUÉ había fallado—. Eso está
bien para un fallo pasajero (GLPI caído, red, un timeout), pero no para uno permanente.

Y pasó: tres tickets (#725, #727, #730) quedaron agendados para el 12-oct y después fueron
purgados de GLPI. La entrada nunca se pudo completar, así que el reactivador les escribía cada
minuto, para siempre. Dos semanas después:

  · 354 escrituras fallidas por hora contra la API de GLPI, exactas, como un reloj;
  · 21.596 advertencias de PHP por día (GLPI tiene su propio bug: en la rama «Item not found»
    hace `continue` ANTES de guardar el resultado, así que después lee una colección vacía);
  · un `php-errors.log` de 115 MB.

Un reintento sin condición de salida no es tolerancia a fallos, es un bucle.

LA REGLA. Se distingue el fallo PERMANENTE (el ticket ya no existe: se descarta) del PASAJERO (se
reintenta). Y además hay un tope de días: pase lo que pase, y aunque el motivo del fallo no se
pueda reconocer, ninguna entrada se reintenta indefinidamente.

Uso:  python tests/probar_agenda_reintentos.py
"""

import os
import sys
import time
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)

import tempfile                              # noqa: E402

# La agenda elige su archivo al importarse: se la apunta a una carpeta temporal ANTES de importar,
# así el test nunca toca la agenda real.
os.environ["ITHOS_DATA"] = tempfile.mkdtemp(prefix="ithos_agenda_")
from comun import agenda as AG               # noqa: E402

FALLAS = []
AHORA = time.time()


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


def agenda_con(*entradas):
    AG._guardar(list(entradas))


def entrada(tid, hace_dias=1.0):
    return {"cliente": "ACME", "tid": str(tid), "epoch": AHORA - hace_dias * 86400,
            "desc": "prueba", "silencioso": True}


def no_existe(tid):
    """El error EXACTO que devuelve GLPI cuando el ticket fue purgado."""
    return urllib.error.HTTPError(
        f"https://glpi/apirest.php/Ticket/{tid}", 404,
        'Not Found en /Ticket/%s — ["ERROR_ITEM_NOT_FOUND","Elemento no encontrado"]' % tid,
        None, None)


def caido():
    """Un fallo PASAJERO: GLPI no responde."""
    return urllib.error.HTTPError("https://glpi/apirest.php/Ticket/1", 503,
                                  "Service Unavailable", None, None)


print("\n=== 1 · Reconocer el fallo PERMANENTE y distinguirlo del pasajero ===")
ok(AG._es_permanente(no_existe(725)) is True, "404 / ERROR_ITEM_NOT_FOUND es permanente")
ok(AG._es_permanente(caido()) is False, "un 503 NO es permanente: hay que reintentarlo")
ok(AG._es_permanente(TimeoutError("se acabó el tiempo")) is False, "un timeout tampoco")
ok(AG._es_permanente(ConnectionError("sin red")) is False, "quedarse sin red tampoco")

print("\n=== 2 · El ticket purgado se DESCARTA, no se reintenta para siempre ===")
agenda_con(entrada(725), entrada(727), entrada(730))
intentos = []


def reactivar_purgado(e):
    intentos.append(e["tid"])
    try:
        raise no_existe(e["tid"])
    except Exception as ex:  # noqa: BLE001
        return "descartar" if AG._es_permanente(ex) else False


hechos = AG.procesar(reactivar_purgado, cliente="ACME", ahora=AHORA)
ok(len(intentos) == 3, "se intentó una vez con cada uno", f"{intentos}")
ok(hechos == [], "ninguno se dio por reactivado (no se reactivaron)")
ok(AG.pendientes("ACME") == [], "y los tres salieron de la agenda",
   str([x.get("tid") for x in AG.pendientes("ACME")]))

intentos.clear()
AG.procesar(reactivar_purgado, cliente="ACME", ahora=AHORA)
ok(intentos == [], "en la vuelta siguiente YA NO se vuelve a intentar: el bucle se corta",
   f"{intentos}")

print("\n=== 3 · Un fallo PASAJERO sí se reintenta (no se pierde el trabajo) ===")
agenda_con(entrada(800, hace_dias=0.5))
veces = []


def reactivar_caido(e):
    veces.append(e["tid"])
    return False                             # GLPI no responde ahora


AG.procesar(reactivar_caido, cliente="ACME", ahora=AHORA)
ok([x.get("tid") for x in AG.pendientes("ACME")] == ["800"],
   "el ticket sigue agendado tras un fallo pasajero")
AG.procesar(reactivar_caido, cliente="ACME", ahora=AHORA)
ok(len(veces) == 2, "y se vuelve a intentar en la vuelta siguiente", f"{len(veces)} intentos")

print("\n=== 4 · Y cuando GLPI vuelve, se reactiva y se saca de la agenda ===")
AG.procesar(lambda e: True, cliente="ACME", ahora=AHORA)
ok(AG.pendientes("ACME") == [], "reactivado -> fuera de la agenda")

print("\n=== 5 · Red de seguridad: nada se reintenta más allá del tope ===")
# Aunque el motivo del fallo NO se pueda reconocer (devuelve False siempre), una entrada vencida
# hace más de `_TOPE_REINTENTOS_DIAS` se descarta igual. Es la garantía de que no hay bucle eterno.
viejo = AG._TOPE_REINTENTOS_DIAS + 1
agenda_con(entrada(900, hace_dias=viejo), entrada(901, hace_dias=1))
AG.procesar(lambda e: False, cliente="ACME", ahora=AHORA)
quedan = sorted(x.get("tid") for x in AG.pendientes("ACME"))
ok(quedan == ["901"],
   f"el de hace {viejo} días se descarta; el de ayer sigue esperando", f"quedan={quedan}")
ok(AG._TOPE_REINTENTOS_DIAS > 0, "el tope está definido", f"{AG._TOPE_REINTENTOS_DIAS} días")

print("\n=== 6 · El archivo se guarda también cuando SOLO se descarta ===")
# Antes se guardaba `if hechos`, así que un descarte sin ninguna reactivación exitosa no se
# habría llegado a persistir nunca y la entrada volvía a aparecer al reiniciar.
agenda_con(entrada(910))
AG.procesar(lambda e: "descartar", cliente="ACME", ahora=AHORA)
ok(AG._cargar() == [], "el descarte quedó escrito en disco, no sólo en memoria",
   str(AG._cargar()))

print("\n" + "=" * 66)
if FALLAS:
    print(f"  FALLAS: {len(FALLAS)}")
    for f in FALLAS:
        print("   -", f)
    print("=" * 66)
    sys.exit(1)
print("  AGENDA SIN BUCLES: OK — todos los chequeos verdes")
print("=" * 66)
