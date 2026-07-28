#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test del SALUDO del portero (dispositivos de ENTRADA):
  · coherencia con la hora (Buenos días / Buenas tardes / Buenas noches),
  · saludo SOLO en la 1ª fichada del día (la 2ª queda en silencio),
  · el saludo por hora es SOLO para entrada (la salida no lo usa).
Todo sin red. Uso: python tests/probar_portero_saludo.py
"""
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ITHOS")
os.environ["ITHOS_DATA"] = tempfile.mkdtemp(prefix="ithos_portero_")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))

import procesador as P                 # noqa: E402
from protocolo import EV_ACCESO        # noqa: E402

_fallos = []


def chk(cond, msg):
    print(("  [OK]   " if cond else "  [FALLA] ") + msg)
    if not cond:
        _fallos.append(msg)


def _texto(cmd):
    return cmd.get("texto") if isinstance(cmd, dict) else str(cmd)


print("=== Saludo del portero (sin red) ===")

# 1) coherencia con la hora
chk(P._saludo_hora("", 8) == "Buenos días", "08:00 -> Buenos días")
chk(P._saludo_hora("", 12) == "Buenas tardes", "12:00 -> Buenas tardes")
chk(P._saludo_hora("", 19) == "Buenas tardes", "19:00 -> Buenas tardes")
chk(P._saludo_hora("", 21) == "Buenas noches", "21:00 -> Buenas noches")
chk(P._saludo_hora("", 3) == "Buenas noches", "03:00 -> Buenas noches")

# 2) la ENTRADA arranca con el saludo por hora; la SALIDA no lo usa
te, _ = P._frase_acceso({"nombre": "Juan Perez", "tipo": "entrada"}, "ITH", saludo_h="Buenas tardes", variante=0)
chk("Buenas tardes" in te and "Juan Perez" in te, f"entrada incluye el saludo por hora y el nombre ({te})")
ts, _ = P._frase_acceso({"nombre": "Juan Perez", "tipo": "salida"}, "ITH", saludo_h="Buenas tardes", variante=0)
chk("Buenas tardes" not in ts, f"la salida NO usa el saludo por hora ({ts})")

# 3) dedup: 1ª fichada saluda, 2ª (mismo día, misma persona, entrada) queda en silencio
cli = {"nombre": "TestCli", "zona_horaria": ""}
datos = {"nombre": "Ana Lopez", "device": "Entrada Principal"}
c1 = P.procesar(cli, EV_ACCESO, datos)
chk(len(c1) == 1, "1ª fichada -> saluda")
chk(any(s in (_texto(c1[0]) or "") for s in ("Buenos días", "Buenas tardes", "Buenas noches")),
    f"el saludo de entrada es coherente con la hora ({_texto(c1[0])})")
c2 = P.procesar(cli, EV_ACCESO, datos)
chk(len(c2) == 0, "2ª fichada del día -> NO saluda (silencio)")
c3 = P.procesar(cli, EV_ACCESO, datos)
chk(len(c3) == 0, "3ª fichada del día -> sigue en silencio")

# 4) persiste: recargar el estado desde disco mantiene el dedup (simula reinicio del central)
P._saludados_hoy.clear()
P._cargar_saludados()
c4 = P.procesar(cli, EV_ACCESO, datos)
chk(len(c4) == 0, "tras 'reiniciar' (recargar de disco) sigue sin re-saludar a quien ya fichó")

# 5) otra persona el mismo día SÍ recibe su saludo
c5 = P.procesar(cli, EV_ACCESO, {"nombre": "Otro Nombre", "device": "Entrada Principal"})
chk(len(c5) == 1, "otra persona el mismo día -> saluda")

print("\n" + ("=" * 55))
if _fallos:
    print(f"RESULTADO: {len(_fallos)} FALLO(S):")
    for f in _fallos:
        print("   -", f)
    sys.exit(1)
print("RESULTADO: TODO OK ✅")
