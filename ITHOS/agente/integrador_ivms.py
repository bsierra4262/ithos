#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrador IVMS (agente). IVMS no tiene API -> lee la base SQL Server de fichajes
en la red del cliente y, por cada fichaje NUEVO, manda un evento "acceso" al central.
El central arma la frase (bienvenida / sala técnica / alerta) y devuelve el comando
de voz; el agente lo reproduce (cacheado = instantáneo).

Config (agente/config.json -> integrador):
  {"tipo":"ivms","db_server":"192.168.0.100,1433","db_database":"ivms_db",
   "db_uid":"...","db_pwd":"...","poll_interval":2,"max_rows":50}
"""

import time
import logging

log = logging.getLogger("integrador.ivms")

DRIVERS = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
           "ODBC Driver 13 for SQL Server", "SQL Server Native Client 11.0",
           "SQL Server"]


def _driver(pyodbc):
    disp = list(pyodbc.drivers())
    for d in DRIVERS:
        if d in disp:
            return d
    return disp[0] if disp else "SQL Server"


def _conectar(cfg, pyodbc):
    drv = _driver(pyodbc)
    partes = [f"DRIVER={{{drv}}}", f"SERVER={cfg['db_server']}",
              f"DATABASE={cfg['db_database']}", f"UID={cfg['db_uid']}",
              f"PWD={cfg['db_pwd']}"]
    if "18" in drv:
        partes += ["Encrypt=no", "TrustServerCertificate=yes"]
    conn = pyodbc.connect(";".join(partes) + ";", timeout=cfg.get("db_timeout", 5))
    log.info("IVMS conectado a SQL Server (driver %s).", drv)
    return conn


def _es_fallo(id_emp, nombre):
    return (id_emp in ("0", "", "None", "NULL")
            or nombre.lower() in ("none", "unknown", "desconocido", "error"))


def _evento_de_fila(r):
    id_emp = str(r.empleado_id).strip()
    nombre = str(r.nombre_persona).strip() if r.nombre_persona else ""
    device = str(r.device_name).strip() if r.device_name else ""
    clave = f"{id_emp}|{str(r.fecha_hora)}|{device}".lower()
    es_fallo = _es_fallo(id_emp, nombre)
    # El CENTRAL clasifica la terminal (entrada/salida/sala) por 'device' según la config del cliente
    # (thin agent). Mandamos el device crudo + si fue fallo. 'tipo' va de respaldo (compat central viejo).
    if es_fallo:
        tipo = "alerta"
    elif "sala tecnica" in device.lower():
        tipo = "sala"
    else:
        tipo = "bienvenida"
    return clave, {"nombre": nombre, "device": device, "es_fallo": es_fallo, "tipo": tipo}


def _entero(valor, por_defecto, minimo, maximo):
    """Un entero de la config, acotado. Nunca levanta: si viene cualquier cosa, el valor por defecto."""
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return por_defecto
    return max(minimo, min(maximo, n))


def vigilar(cfg, enviar_evento, stop=None):
    """Poll de la DB. enviar_evento({'evento':'acceso','datos':{...}}). Baseline en
    el arranque (no anuncia el histórico)."""
    try:
        import pyodbc
    except Exception as e:  # noqa: BLE001
        log.error("IVMS deshabilitado (falta pyodbc): %s", e)
        return
    intervalo = cfg.get("poll_interval", 2)
    # Los `TOP` se arman con un ENTERO validado, no pegando el valor de la config dentro del SQL.
    # `max_rows` y `max_precache` se editan desde el panel y llegan como texto: interpolar eso en
    # la consulta es dejar abierta la puerta a que lo que entre por un formulario termine
    # ejecutándose contra la base del cliente. Un `int()` acotado cierra el tema de raíz.
    max_filas = _entero(cfg.get("max_rows"), 50, 1, 5000)
    consulta = (f"SELECT TOP {max_filas} empleado_id, nombre_persona, "
                f"fecha_hora, device_name FROM fichajes ORDER BY fecha_hora DESC")
    conn = None
    vistos = {}          # dict, no set: conserva el orden -> se descartan las MÁS VIEJAS
    baseline = False
    poll_n = 0
    ultimo_reciente = None
    while stop is None or not stop.is_set():
        try:
            if conn is None:
                conn = _conectar(cfg, pyodbc)
                cur = conn.cursor()
            cur.execute(consulta)
            filas = cur.fetchall()
            poll_n += 1
            # Diagnóstico SILENCIOSO (nivel debug, no llena el log): solo cuando CAMBIA la fichada más
            # reciente de la DB. Los eventos reales (NUEVA fichada) sí van a INFO más abajo.
            reciente = str(filas[0].fecha_hora) if filas else None
            if baseline and reciente != ultimo_reciente:
                log.debug("IVMS: fichada más reciente en DB: %s (%d filas)", reciente or "(vacío)", len(filas))
                ultimo_reciente = reciente
            if not baseline:
                for r in filas:                          # baseline: marca las fichadas actuales
                    clave, _ = _evento_de_fila(r)         # (para NO re-anunciar el histórico)
                    vistos[clave] = None
                baseline = True
                log.info("IVMS baseline: %d fichajes marcados. Esperando nuevos...", len(vistos))
                # ROSTER COMPLETO para pre-cachear: TODAS las personas conocidas (no solo las recientes),
                # así la 1ª fichada de CUALQUIERA sale instantánea. Se cachea en 2do plano (ocioso).
                nombres = []
                try:
                    max_pre = _entero(cfg.get("max_precache"), 1000, 1, 20000)
                    cur.execute(f"SELECT DISTINCT TOP {max_pre} nombre_persona "
                                f"FROM fichajes WHERE nombre_persona IS NOT NULL ORDER BY nombre_persona")
                    for row in cur.fetchall():
                        n = (str(row[0]).strip() if row[0] else "")
                        if n and not _es_fallo("x", n) and n not in nombres:
                            nombres.append(n)
                except Exception as e:  # noqa: BLE001
                    log.warning("IVMS: no pude leer el roster (%s); pre-cacheo con los recientes.", e)
                    for r in filas:
                        _, datos = _evento_de_fila(r)
                        n = (datos.get("nombre") or "").strip()
                        if n and datos.get("tipo") in ("bienvenida", "sala") and n not in nombres:
                            nombres.append(n)
                if nombres:
                    enviar_evento({"evento": "precache_acceso", "datos": {"nombres": nombres}})
                    log.info("IVMS: pre-cacheo pedido para %d saludos (roster completo).", len(nombres))
                # DESCUBRIMIENTO de terminales: IVMS no da IP, pero la DB tiene el device_name de cada
                # lector -> listamos los distintos para que el cliente los mapee (entrada/salida/sala)
                # desde el panel. Se manda una vez al arrancar.
                try:
                    cur.execute("SELECT DISTINCT device_name FROM fichajes "
                                "WHERE device_name IS NOT NULL ORDER BY device_name")
                    terms = [str(x[0]).strip() for x in cur.fetchall() if x[0] and str(x[0]).strip()]
                    if terms:
                        enviar_evento({"evento": "terminales_descubiertos",
                                       "datos": {"terminales": terms}})
                        log.info("IVMS: %d terminales descubiertas -> %s",
                                 len(terms), ", ".join(terms[:8]))
                except Exception as e:  # noqa: BLE001
                    log.warning("IVMS: no pude listar terminales (%s).", e)
            else:
                for r in reversed(filas):        # cronológico ascendente
                    clave, datos = _evento_de_fila(r)
                    if clave in vistos:
                        continue
                    vistos[clave] = None
                    if len(vistos) > 6000:
                        # Se descartan las fichadas MÁS VIEJAS. Antes era `set(list(vistos))[-5000:]`
                        # y un set NO tiene orden: lo que se tiraba era arbitrario, así que podía
                        # descartar una fichada reciente y volver a anunciarla por los parlantes.
                        # Un dict conserva el orden de inserción, que acá es el cronológico.
                        for vieja in list(vistos)[:len(vistos) - 5000]:
                            vistos.pop(vieja, None)
                    log.info("IVMS: NUEVA fichada -> nombre='%s' device='%s' tipo=%s -> enviada al gestor",
                             datos.get("nombre"), datos.get("device"), datos.get("tipo"))
                    enviar_evento({"evento": "acceso", "datos": datos})
            time.sleep(intervalo)
        except Exception as e:  # noqa: BLE001
            log.warning("IVMS error: %s", e)
            try:
                if conn:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass
            conn = None
            time.sleep(cfg.get("reconnect_delay", 5))
