#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test del ROLLOVER de Planka (semanal/mensual + arrastre).

  NIVEL 1 (unitario, SIN red): cálculo de semanas ISO, nombres de mes/board, gaplessness.
  NIVEL 2 (integración, contra la Planka real): crea proyecto/boards/listas, arrastra lo no
          terminado, y prueba el integrador Julio->Agosto. TODO en proyectos 'ZZ_TEST_*' que se
          BORRAN en finally (jamás toca 'Julio'). Sin secretos hardcodeados: las credenciales
          salen de env (PLANKA_URL/PLANKA_KEY/PLANKA_ITHOS) o de central/clientes.json.

Uso:   python tests/probar_planka_rollover.py
"""
import os
import sys
import json
import tempfile
from datetime import date, datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # jarvis-cloud/
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)                                                     # from comun import ...
sys.path.insert(0, os.path.join(APP, "central"))                           # import planka_rollover / integrador
# aislar el estado del período en un temp (no ensuciar ~/.ithos)
os.environ["ITHOS_DATA"] = tempfile.mkdtemp(prefix="ithos_test_")

from comun import planka as PK          # noqa: E402
import planka_rollover as RO            # noqa: E402
import planka_integrador as PI          # noqa: E402

_fallos = []


def chk(cond, msg):
    print(("  [OK]   " if cond else "  [FALLA] ") + msg)
    if not cond:
        _fallos.append(msg)


# =====================================================================  NIVEL 1: fechas (sin red)
def nivel1():
    print("\n=== NIVEL 1 · cálculo de semanas (sin red) ===")
    chk(RO.nombre_mes(2026, 8) == "Agosto 2026", "nombre_mes(2026,8) == 'Agosto 2026'")
    chk(RO.nombre_mes(2027, 1) == "Enero 2027", "nombre_mes(2027,1) == 'Enero 2027'")

    sem = RO.semanas_del_mes(2026, 8)
    lunes = [s["lunes"] for s in sem]
    chk(all(l.weekday() == 0 for l in lunes), "todos los inicios son LUNES")
    chk(all(l.month == 8 for l in lunes), "todos los lunes son de Agosto")
    chk(all((lunes[i + 1] - lunes[i]).days == 7 for i in range(len(lunes) - 1)),
        "lunes consecutivos separados 7 días")
    chk(lunes[0].day <= 7, "la 1ra semana arranca el primer lunes del mes")
    chk((lunes[0] - timedelta(days=7)).month != 8, "no hay lunes de Agosto antes de la 1ra semana")
    chk(all(s["viernes"] == s["lunes"] + timedelta(days=4) for s in sem), "viernes = lunes + 4")
    chk(sem[0]["nombre"].startswith("Semana 1 · "), f"nombre 1ra semana ok ({sem[0]['nombre']})")
    print(f"      Agosto 2026 -> {len(sem)} semanas: " + ", ".join(s["nombre"] for s in sem))

    # mes que arranca en lunes (para cubrir el borde): Junio 2026 arranca lunes 1
    j = RO.semanas_del_mes(2026, 6)
    chk(j[0]["lunes"] == date(2026, 6, 1), "mes que arranca lunes: 1ra semana = día 1")

    # spill: un día de principios de mes cae en la semana de su lunes (mes anterior)
    d = date(2026, 9, 1)
    chk(RO.mes_key(d) == RO._lunes(d).strftime("%Y-%m"), "mes_key sigue al lunes de la semana")

    # semana_key estable dentro de la semana, cambia entre semanas
    lun = date(2026, 8, 10)
    chk(RO.semana_key(lun) == RO.semana_key(lun + timedelta(days=4)), "semana_key igual lun..vie")
    chk(RO.semana_key(lun) != RO.semana_key(lun + timedelta(days=7)), "semana_key cambia a la semana siguiente")

    # GAPLESS + consistencia: cada día cae en exactamente una semana de su mes
    d = date(2026, 7, 27)
    fin = date(2026, 10, 5)
    malos = 0
    while d <= fin:
        y, m, s = RO.semana_actual(d)
        pool = RO.semanas_del_mes(y, m)
        if s["lunes"] != RO._lunes(d) or not any(x["lunes"] == s["lunes"] for x in pool):
            malos += 1
        d += timedelta(days=1)
    chk(malos == 0, f"gapless: cada día (27/07–05/10) cae en su semana ({malos} inconsistencias)")


# =====================================================================  NIVEL 2: integración (red)
def _conn():
    """(url, key, ithos_id) de env o de central/clientes.json. None si no hay."""
    u, k, i = os.environ.get("PLANKA_URL"), os.environ.get("PLANKA_KEY"), os.environ.get("PLANKA_ITHOS")
    if u and k:
        return u, k, (i or "")
    try:
        d = json.load(open(os.path.join(APP, "central", "clientes.json"), encoding="utf-8"))
        for c in d.get("clientes", []):
            p = c.get("planka") or {}
            if p.get("url") and p.get("api_key"):
                return p["url"], p["api_key"], str(p.get("ithos_user_id") or "")
    except Exception:
        pass
    return None


def _borrar_tests(pk):
    """Borra TODO proyecto cuyo nombre empiece con 'ZZ_TEST' (boards primero, como exige Planka)."""
    try:
        items, inc = pk.proyectos()
    except Exception:
        return
    boards = inc.get("boards", []) if isinstance(inc, dict) else []
    for p in items:
        if str(p.get("name", "")).startswith("ZZ_TEST"):
            for b in boards:
                if str(b.get("projectId")) == str(p.get("id")):
                    try:
                        pk.borrar_board(b["id"])
                    except Exception:
                        pass
            try:
                pk._req(f"/api/projects/{p['id']}", "DELETE")
            except Exception:
                pass


def _cards_por_board(pk, board_id):
    """{clave_lista: [nombres]} del board."""
    inc = pk.board(board_id)
    id2clave = {str(l["id"]): RO.clave_lista(l.get("name")) for l in inc.get("lists", [])}
    out = {}
    for c in inc.get("cards", []):
        cl = id2clave.get(str(c.get("listId")))
        if cl:
            out.setdefault(cl, []).append(c.get("name"))
    return out


def nivel2():
    print("\n=== NIVEL 2 · integración contra Planka real (proyectos ZZ_TEST, se borran) ===")
    cn = _conn()
    if not cn:
        print("  [SKIP] sin credenciales (PLANKA_URL/PLANKA_KEY o clientes.json). Integración omitida.")
        return
    url, key, ithos = cn
    pk = PK.Planka(url, key)
    _borrar_tests(pk)                                   # por si quedó basura de una corrida anterior
    creados = []
    try:
        roll = RO.Rollover(pk, ithos)

        # --- idempotencia: crear proyecto/board/listas dos veces devuelve lo mismo
        pid1 = roll.asegurar_proyecto("ZZ_TEST_ROLLOVER")
        pid2 = roll.asegurar_proyecto("ZZ_TEST_ROLLOVER")
        creados.append(pid1)
        chk(pid1 and pid1 == pid2, "asegurar_proyecto idempotente")
        bidA = roll.asegurar_board(pid1, "Semana A", RO.POS)
        chk(bidA and bidA == roll.asegurar_board(pid1, "Semana A", RO.POS), "asegurar_board idempotente")
        la = roll.asegurar_listas(bidA)
        chk(set(la.keys()) == {"por_hacer", "haciendo", "en_espera", "hecho"},
            f"asegurar_listas crea las 4 claves ({sorted(la.keys())})")
        chk(roll.asegurar_listas(bidA) == la, "asegurar_listas idempotente (no duplica)")

        # --- ARRASTRE: cards en A (una en Hecho) -> B; solo lo no-Hecho se mueve, en su misma lista
        bidB = roll.asegurar_board(pid1, "Semana B", 2 * RO.POS)
        lb = roll.asegurar_listas(bidB)
        pk.crear_tarjeta(la["por_hacer"], "Tarea PENDIENTE")
        pk.crear_tarjeta(la["haciendo"], "Tarea EN CURSO")
        pk.crear_tarjeta(la["en_espera"], "Tarea TRABADA")
        pk.crear_tarjeta(la["hecho"], "Tarea TERMINADA")
        mov = roll.arrastrar(bidA, bidB)
        chk(mov == 3, f"arrastrar movió 3 (las no terminadas), no 4 ({mov})")
        ca, cb = _cards_por_board(pk, bidA), _cards_por_board(pk, bidB)
        chk(ca.get("hecho") == ["Tarea TERMINADA"], "la TERMINADA quedó en el board viejo (historial)")
        chk("Tarea PENDIENTE" in cb.get("por_hacer", []), "PENDIENTE llegó a 'Por hacer' del nuevo")
        chk("Tarea EN CURSO" in cb.get("haciendo", []), "EN CURSO llegó a 'Haciendo' (misma lista)")
        chk("Tarea TRABADA" in cb.get("en_espera", []), "TRABADA llegó a 'En espera' (misma lista)")
        chk(not ca.get("por_hacer") and not ca.get("haciendo") and not ca.get("en_espera"),
            "el board viejo quedó sin pendientes (se arrastraron)")

        # --- asegurar_semana end-to-end (con nombre de mes TEMPORAL para no crear el mes real)
        _orig = RO.nombre_mes
        RO.nombre_mes = lambda a, m: f"ZZ_TEST_MES {a}-{m:02d}"
        try:
            roll2 = RO.Rollover(pk, ithos)
            info = roll2.asegurar_semana(datetime(2026, 8, 10, 11, 0))     # 10/08 = Semana 2
            creados.append(info["project_id"])
            chk(info["board_id"], "asegurar_semana devolvió board de la semana actual")
            chk("Semana 2" in info["semana"], f"la semana actual del 10/08 es la 2 ({info['semana']})")
            _it, inc = pk.proyectos()
            nb = sum(1 for b in inc.get("boards", []) if str(b.get("projectId")) == str(info["project_id"]))
            chk(nb == len(RO.semanas_del_mes(2026, 8)),
                f"creó un board por cada semana del mes ({nb})")
        finally:
            RO.nombre_mes = _orig

        # --- INTEGRADOR Julio(legacy) -> Agosto: arrastra lo pendiente al cambiar de mes
        legacy_p = roll.asegurar_proyecto("ZZ_TEST_LEGACY")
        creados.append(legacy_p)
        legacy_b = roll.asegurar_board(legacy_p, "MENSUAL", RO.POS)
        ll = roll.asegurar_listas(legacy_b)
        pk.crear_tarjeta(ll["haciendo"], "Pendiente de Julio")
        cfg = {"url": url, "api_key": key, "ithos_user_id": ithos,
               "project_id": legacy_p, "board_id": legacy_b, "mes_legacy": "2026-07", "usuarios": []}
        integ = PI.PlankaIntegrador(cfg, ia=None)
        RO.nombre_mes = lambda a, m: f"ZZ_TEST_AGO {a}-{m:02d}"
        try:
            integ._asegurar_periodo(datetime(2026, 7, 28, 10, 0))          # Julio: sigue en el board legacy
            chk(integ.board_id == legacy_b, "en Julio el integrador usa el board mensual (legacy)")
            integ._asegurar_periodo(datetime(2026, 8, 10, 10, 0))          # Agosto: rota + arrastra
            chk(integ.board_id not in (legacy_b, None), "en Agosto el integrador cambió al board semanal")
            destino = _cards_por_board(pk, integ.board_id)
            chk("Pendiente de Julio" in destino.get("haciendo", []),
                "el integrador ARRASTRÓ la tarea pendiente de Julio a Agosto (misma lista)")
            origen = _cards_por_board(pk, legacy_b)
            chk("Pendiente de Julio" not in origen.get("haciendo", []),
                "la tarea ya no está en el board de Julio (se movió, no se duplicó)")
            for b in pk.proyectos()[1].get("boards", []):
                if b.get("name", "").startswith("ZZ_TEST_AGO"):
                    creados.append("_")  # marca: hay proyecto ZZ_TEST_AGO (se limpia por prefijo)
                    break
        finally:
            RO.nombre_mes = _orig
    finally:
        _borrar_tests(pk)                               # limpieza TOTAL por prefijo
        # verificación de limpieza
        try:
            items, _ = pk.proyectos()
            quedan = [p.get("name") for p in items if str(p.get("name", "")).startswith("ZZ_TEST")]
            chk(not quedan, f"limpieza: no quedaron proyectos de prueba ({quedan})")
            print("      proyectos actuales:", [p.get("name") for p in items])
        except Exception as e:
            print("  [WARN] no pude verificar limpieza:", e)


if __name__ == "__main__":
    nivel1()
    nivel2()
    print("\n" + ("=" * 60))
    if _fallos:
        print(f"RESULTADO: {len(_fallos)} FALLO(S):")
        for f in _fallos:
            print("   -", f)
        sys.exit(1)
    print("RESULTADO: TODO OK ✅")
