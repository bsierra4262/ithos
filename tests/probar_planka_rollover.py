#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test del ROLLOVER de Planka (semanas por bloques del mes + cierre mensual + arrastre + miembros).

  NIVEL 1 (unitario, SIN red): bloques de semana dentro del mes, nombres, gaplessness, bordes.
  NIVEL 2 (integración, contra la Planka real): crea proyecto/semanas/MENSUAL, agrega al equipo como
          miembro, asigna, arrastra, y consolida el mes al cerrar (Julio->Agosto->Septiembre). TODO en
          proyectos 'ZZ_TEST_*' que se BORRAN en finally (jamás toca 'Julio'). Sin secretos hardcodeados:
          credenciales de env (PLANKA_URL/PLANKA_KEY/PLANKA_ITHOS/PLANKA_TEAM) o de central/clientes.json.

Uso:   python tests/probar_planka_rollover.py
"""
import os
import sys
import json
import tempfile
from datetime import date, datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))
os.environ["ITHOS_DATA"] = tempfile.mkdtemp(prefix="ithos_test_")

from comun import planka as PK          # noqa: E402
import planka_rollover as RO            # noqa: E402
import planka_integrador as PI          # noqa: E402

_fallos = []


def chk(cond, msg):
    print(("  [OK]   " if cond else "  [FALLA] ") + msg)
    if not cond:
        _fallos.append(msg)


# =====================================================================  NIVEL 1: bloques (sin red)
def nivel1():
    print("\n=== NIVEL 1 · semanas por bloques del mes (sin red) ===")
    chk(RO.nombre_mes(2026, 8) == "Agosto 2026", "nombre_mes(2026,8) == 'Agosto 2026'")
    chk(RO.ultimo_dia(2026, 2) == 28 and RO.ultimo_dia(2026, 8) == 31, "ultimo_dia (feb=28, ago=31)")

    sem = RO.semanas_del_mes(2026, 8)
    chk(len(sem) == 5, f"Agosto tiene 5 bloques ({len(sem)})")
    chk(sem[0]["desde"] == date(2026, 8, 1) and sem[-1]["hasta"] == date(2026, 8, 31),
        "el 1er bloque arranca el 1 y el último termina el 31 (cierre limpio)")
    chk(all(s["desde"].month == 8 and s["hasta"].month == 8 for s in sem),
        "ningún bloque cruza a otro mes")
    chk(all((sem[i + 1]["desde"] - sem[i]["desde"]).days == 7 for i in range(len(sem) - 1)),
        "bloques separados 7 días")
    chk(sem[0]["nombre"] == "Semana 1 · 01–07/08", f"nombre del 1er bloque ({sem[0]['nombre']})")
    print("      Agosto 2026 -> " + ", ".join(s["nombre"] for s in sem))

    chk(len(RO.semanas_del_mes(2026, 2)) == 4, "Febrero (28d) = 4 bloques")
    chk(RO.semanas_del_mes(2026, 9)[-1]["hasta"] == date(2026, 9, 30), "Septiembre (30d) cierra el 30")

    chk(RO.semana_actual(date(2026, 8, 10))[2]["num"] == 2, "10/08 cae en la Semana 2")
    chk(RO.semana_actual(date(2026, 8, 31))[2]["num"] == 5, "31/08 cae en la Semana 5")
    chk(RO.semana_key(date(2026, 8, 10)) == "2026-08-W2", "semana_key(10/08) == '2026-08-W2'")
    chk(RO.semana_key(date(2026, 8, 8)) == RO.semana_key(date(2026, 8, 14)),
        "semana_key estable dentro del bloque")
    chk(RO.semana_key(date(2026, 8, 14)) != RO.semana_key(date(2026, 8, 15)),
        "semana_key cambia al bloque siguiente")
    chk(RO.mes_key(date(2026, 9, 1)) == "2026-09", "mes_key(01/09) == '2026-09' (sin cruce)")

    # GAPLESS: cada día de agosto cae en un bloque que lo contiene
    malos = 0
    for dd in range(1, 32):
        _y, _m, s = RO.semana_actual(date(2026, 8, dd))
        if not (s["desde"].day <= dd <= s["hasta"].day):
            malos += 1
    chk(malos == 0, f"gapless: cada día de agosto cae en su bloque ({malos} fuera)")


# =====================================================================  NIVEL 2: integración (red)
def _conn():
    u, k, i = os.environ.get("PLANKA_URL"), os.environ.get("PLANKA_KEY"), os.environ.get("PLANKA_ITHOS")
    team = [x for x in (os.environ.get("PLANKA_TEAM") or "").split(",") if x.strip()]
    if u and k:
        return u, k, (i or ""), team
    try:
        d = json.load(open(os.path.join(APP, "central", "clientes.json"), encoding="utf-8"))
        for c in d.get("clientes", []):
            p = c.get("planka") or {}
            if p.get("url") and p.get("api_key"):
                team = [str(x.get("planka_id")) for x in p.get("usuarios", []) if x.get("planka_id")]
                return p["url"], p["api_key"], str(p.get("ithos_user_id") or ""), team
    except Exception:
        pass
    return None


def _borrar_tests(pk):
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
    url, key, ithos, equipo = cn
    pk = PK.Planka(url, key)
    _borrar_tests(pk)
    try:
        _orig = RO.nombre_mes
        RO.nombre_mes = lambda a, m: f"ZZ_TEST {a}-{m:02d}"
        try:
            roll = RO.Rollover(pk, ithos, equipo)

            # --- asegurar_mes: proyecto + 5 semanas + MENSUAL + 4 listas cada uno
            info = roll.asegurar_mes(2026, 8)
            chk(len(info["semanas"]) == 5, f"asegurar_mes creó 5 boards de semana ({len(info['semanas'])})")
            chk(bool(info["mensual_board_id"]), "creó el board MENSUAL")
            btest = info["semanas"][2]
            chk(set(roll.asegurar_listas(btest)) == {"por_hacer", "haciendo", "en_espera", "hecho"},
                "cada semana tiene las 4 listas")
            info2 = roll.asegurar_mes(2026, 8)
            chk(info2["semanas"] == info["semanas"] and info2["mensual_board_id"] == info["mensual_board_id"],
                "asegurar_mes idempotente (no duplica boards)")

            # --- el EQUIPO quedó como miembro del board: se puede asignar (si no, daría 404)
            if equipo:
                lst = roll.asegurar_listas(btest)
                card = pk.crear_tarjeta(lst["por_hacer"], "Tarea para miembro")
                ok = pk.asignar(card["id"], equipo[0])
                inc = pk.board(btest)
                asignado = any(str(m.get("cardId")) == str(card["id"]) and str(m.get("userId")) == equipo[0]
                               for m in inc.get("cardMemberships", []))
                chk(ok and asignado, "se puede ASIGNAR a un miembro del equipo (quedó miembro del board)")
            else:
                print("  [SKIP] sin PLANKA_TEAM: no verifico asignación de equipo")

            # --- cierre de mes: copiar_a_mensual archiva TODO el mes en MENSUAL
            l2 = roll.asegurar_listas(btest)
            pk.crear_tarjeta(l2["haciendo"], "Archivo EN CURSO")
            pk.crear_tarjeta(l2["hecho"], "Archivo TERMINADA")
            copiadas = roll.copiar_a_mensual(2026, 8)
            mens = _cards_por_board(pk, info["mensual_board_id"])
            total_mens = sum(len(v) for v in mens.values())
            chk(copiadas >= 2 and total_mens == copiadas,
                f"copiar_a_mensual archivó {copiadas} tarjeta(s) en MENSUAL (hechas + pendientes)")
            chk("Archivo TERMINADA" in mens.get("hecho", []) and "Archivo EN CURSO" in mens.get("haciendo", []),
                "el archivo MENSUAL conserva la lista de cada tarjeta")
        finally:
            RO.nombre_mes = _orig

        # --- INTEGRADOR: Julio(legacy) -> Agosto (arrastra) -> Septiembre (cierra Agosto en MENSUAL)
        roll0 = RO.Rollover(pk, ithos, equipo)
        legacy_p = roll0.asegurar_proyecto("ZZ_TEST_LEGACY")
        legacy_b = roll0.asegurar_board(legacy_p, "MENSUAL", RO.POS)
        ll = roll0.asegurar_listas(legacy_b)
        pk.crear_tarjeta(ll["haciendo"], "Pendiente de Julio")
        cfg = {"url": url, "api_key": key, "ithos_user_id": ithos, "project_id": legacy_p,
               "board_id": legacy_b, "mes_legacy": "2026-07",
               "usuarios": [{"planka_id": e, "nombre": f"User {e[-3:]}", "telefono": ""} for e in equipo]}
        integ = PI.PlankaIntegrador(cfg, ia=None)
        RO.nombre_mes = lambda a, m: f"ZZ_TEST_M {a}-{m:02d}"
        try:
            integ._asegurar_periodo(datetime(2026, 7, 28, 10, 0))       # Julio: board legacy
            chk(integ.board_id == legacy_b, "en Julio usa el board mensual heredado")
            integ._asegurar_periodo(datetime(2026, 8, 10, 10, 0))       # Agosto: rota + arrastra
            ago_b = integ.board_id
            chk(ago_b not in (legacy_b, None), "en Agosto cambió al board semanal (bloque)")
            chk("Pendiente de Julio" in _cards_por_board(pk, ago_b).get("haciendo", []),
                "arrastró la tarea de Julio a Agosto (misma lista)")
            pk.crear_tarjeta(integ._clave_a_id["hecho"], "Terminada en Agosto")   # algo hecho en agosto
            integ._asegurar_periodo(datetime(2026, 9, 5, 10, 0))        # Septiembre: cierra Agosto + arrastra
            sep_b = integ.board_id
            chk(sep_b not in (legacy_b, ago_b, None), "en Septiembre cambió a otro board (nuevo mes)")
            # Agosto quedó consolidado en su MENSUAL
            ago_info = roll0.asegurar_mes(2026, 8)
            arch = _cards_por_board(pk, ago_info["mensual_board_id"])
            chk("Terminada en Agosto" in arch.get("hecho", []) and "Pendiente de Julio" in arch.get("haciendo", []),
                "al cerrar Agosto, MENSUAL archivó TODO el mes (hecho + pendiente)")
            # lo pendiente se arrastró a Septiembre; lo hecho NO
            sep = _cards_por_board(pk, sep_b)
            chk("Pendiente de Julio" in sep.get("haciendo", []),
                "lo pendiente siguió a Septiembre (misma lista)")
            chk("Terminada en Agosto" not in sum(sep.values(), []),
                "lo terminado NO se arrastró a Septiembre (quedó de historial)")
        finally:
            RO.nombre_mes = _orig
    finally:
        _borrar_tests(pk)
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
