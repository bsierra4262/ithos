#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sube AUTOMÁTICAMENTE la versión (SemVer) del AGENTE o del GESTOR en comun/version.py y sincroniza
la versión del instalador Inno. Así el número SIEMPRE sube solo en cada build/deploy y llevamos el
control de versiones sin tocarlo a mano.

Uso:
    python build/bump_version.py agente [patch|minor|major]   # lo llama el build del .exe
    python build/bump_version.py gestor [patch|minor|major]   # lo llama el deploy (actualizar.sh)
"""
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VER = os.path.join(RAIZ, "ITHOS", "comun", "version.py")
ISS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ithos-agente.iss")


def _subir(v, parte):
    maj, mnr, pat = (int(x) for x in v.split(".")[:3])
    if parte == "major":
        return f"{maj + 1}.0.0"
    if parte == "minor":
        return f"{maj}.{mnr + 1}.0"
    return f"{maj}.{mnr}.{pat + 1}"


def main():
    cual = (sys.argv[1] if len(sys.argv) > 1 else "agente").upper()
    parte = (sys.argv[2] if len(sys.argv) > 2 else "patch").lower()
    clave = "AGENTE_VERSION" if "AGENTE" in cual else "GESTOR_VERSION"

    with open(VER, encoding="utf-8") as f:
        txt = f.read()
    m = re.search(rf'{clave}\s*=\s*"(\d+\.\d+\.\d+)"', txt)
    if not m:
        print(f"No se encontró {clave} en {VER}")
        return 1
    nueva = _subir(m.group(1), parte)
    txt = re.sub(rf'({clave}\s*=\s*")\d+\.\d+\.\d+(")', rf"\g<1>{nueva}\g<2>", txt, count=1)
    with open(VER, "w", encoding="utf-8") as f:
        f.write(txt)

    # El instalador Inno sigue la versión del AGENTE (para que "ejecutar el .exe nuevo" actualice solo).
    if "AGENTE" in cual and os.path.exists(ISS):
        with open(ISS, encoding="utf-8") as f:
            iss = f.read()
        iss = re.sub(r'(#define MyAppVersion ")\d+\.\d+\.\d+(")', rf"\g<1>{nueva}\g<2>", iss, count=1)
        with open(ISS, "w", encoding="utf-8") as f:
            f.write(iss)

    print(f"{clave}: {m.group(1)} -> {nueva}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
