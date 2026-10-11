#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test del tema de ITH para GLPI (docs/glpi/tema_ith.css).

QUÉ PASÓ. El tema se veía bien en la barra pero se rompía apenas uno entraba a cualquier otro
lado. Brian lo resumió en una frase que es, de hecho, la regla del tema:

    "nunca debe pasar que algún color no se vea al seleccionar, porque oscuro con oscuro no se
     ve, y claro con claro tampoco"

Tres fallas reales, las tres por el mismo motivo —pintar el FONDO y olvidarse del TEXTO—:

  1. El botón de perfil quedaba VERDE con el texto BLANCO (1.9:1, ilegible). El control es un
     `button.nav-link` con dos `div` adentro, y el segundo es `.text-muted-menu`, que trae color
     PROPIO: pintar sólo el contenedor no alcanza, porque el hijo no hereda. Por eso cada regla
     de selección se repite con ` *`.

  2. Los nombres ya visitados en la lista de usuarios salían en el violeta por omisión del
     navegador (#551A8B), que sobre el fondo de auror_dark da 1.3:1. El primer intento usó
     `color: inherit`, y NO funciona: por privacidad los navegadores descartan en `:visited` los
     valores que dependen del entorno y sólo respetan un color explícito. La forma correcta es
     darle a `:link` y a `:visited` el MISMO valor explícito.

  3. El hover sólo cubría `.nav-link` de la barra: los desplegables, el selector de perfil y
     entidad, las pestañas, las listas, el paginador y los select2 no estaban contemplados.

Y dos invariantes que no se pueden perder:
  · GLPI pasa el CSS por `strip_tags()`, así que un `<` se come todo lo que sigue.
  · El logo tiene que apuntar a los archivos `ith-*.png`, que son los que una actualización de
    GLPI no puede pisar (los `logo-GLPI-*.png` los reescribe cada versión mayor).

Uso:  python tests/probar_tema_glpi.py
"""

import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMA = os.path.join(RAIZ, "docs", "glpi", "tema_ith.css")

FALLAS = []

# Los colores de la paleta auror_dark, que es la que GLPI tiene puesta por defecto y la que
# heredan todos los usuarios (glpi_configs.palette = 'auror_dark').
VERDE = "#9acc31"
TINTA = "#161922"
BARRA = "#502f76"
FONDO_AUROR = "#1f2936"
SUPERFICIE_AUROR = "#232e3c"
ENLACE_AUROR = "#b6c3e0"
TEXTO_AUROR = "#9ca8c0"
VISITADO_NAVEGADOR = "#551a8b"


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


def contraste(frente, fondo):
    """Relación de contraste de la WCAG 2.1 entre dos colores en hexadecimal."""
    def luminancia(hexa):
        hexa = hexa.lstrip("#")
        canales = [int(hexa[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        canales = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
        return 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2]

    claro, oscuro = sorted((luminancia(frente), luminancia(fondo)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def reglas(css):
    """Devuelve la lista de (selectores, cuerpo) del CSS, sin comentarios."""
    limpio = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", limpio)]


with open(TEMA, encoding="utf-8") as fh:
    CSS = fh.read()
REGLAS = reglas(CSS)

print("\n=== 1 · GLPI pasa el CSS por strip_tags(): un '<' se come el resto ===")
ok("<" not in CSS, "el tema no tiene ningún '<'")
ok(CSS.count("{") == CSS.count("}"), "las llaves cierran",
   f"{CSS.count('{')} abren / {CSS.count('}')} cierran")

print("\n=== 2 · Lo seleccionado se ve: fondo verde SIEMPRE con tinta oscura ===")
# Toda regla que pinte el fondo de verde tiene que fijar el color del texto en la MISMA regla.
verdes = [(sel, cuerpo) for sel, cuerpo in REGLAS
          if re.search(r"background-color:\s*var\(--ith-verde\)", cuerpo)]
ok(len(verdes) >= 2, "hay reglas que pintan el fondo de verde", f"{len(verdes)}")
for sel, cuerpo in verdes:
    tiene_color = re.search(r"(^|;|\s)color:", cuerpo) is not None
    ok(tiene_color, f"la regla que pinta de verde también fija el texto ({sel.split(',')[0].strip()[:42]})")

print("\n=== 3 · Y lo fija también para los HIJOS (el bug del botón de perfil) ===")
# El control de perfil es un button con divs adentro; uno es .text-muted-menu, con color propio.
# Si la selección no alcanza a los descendientes, el hijo queda con su color y no se lee.
sel_hijos = [sel for sel, cuerpo in REGLAS
             if "*" in sel and re.search(rf"color:\s*var\(--ith-tinta\)", cuerpo)]
ok(bool(sel_hijos), "existe la regla que pinta los DESCENDIENTES de lo seleccionado")
hijos = " ".join(sel_hijos)
for control, desc in [(".nav-link:hover *", "la barra"),
                      (".dropdown-item:hover *", "los desplegables"),
                      (".dropdown-item.active *", "el desplegable seleccionado"),
                      (".nav-tabs .nav-link.active *", "las pestañas"),
                      (".list-group-item.active *", "las listas"),
                      (".select2-results__option--highlighted *", "los select2")]:
    ok(control in hijos, f"alcanza a los hijos en {desc}", control)
ok("--tblr-muted: var(--ith-tinta)" in CSS,
   "los subtítulos apagados (.text-muted-menu) también toman la tinta")

print("\n=== 4 · Enlaces visitados: mismo color que los no visitados ===")
# `color: inherit` NO sirve en :visited — el navegador lo descarta por privacidad.
visitados = [(sel, cuerpo) for sel, cuerpo in REGLAS if ":visited" in sel]
ok(bool(visitados), "el tema trata los enlaces visitados", f"{len(visitados)} reglas")
for sel, cuerpo in visitados:
    valor = re.search(r"color:\s*([^;]+)", cuerpo)
    valor = valor.group(1).strip() if valor else ""
    primero = sel.split(",")[0].strip()[:34]
    ok(valor not in ("inherit", "currentColor", "unset", "initial", ""),
       f"el color es explícito, no heredado ({primero})", valor or "no hay color")
    # y la MISMA regla tiene que cubrir también :link, para que no haya diferencia visible
    ok(":link" in sel, f"la misma regla cubre :link y :visited ({primero})")

print("\n=== 5 · Contraste real sobre la paleta auror_dark (la que está puesta) ===")
for frente, fondo, minimo, nombre in [
        (TINTA, VERDE, 4.5, "tinta sobre el verde de selección"),
        ("#ffffff", BARRA, 4.5, "blanco sobre la barra violeta"),
        (ENLACE_AUROR, SUPERFICIE_AUROR, 4.5, "enlace de tabla sobre la superficie"),
        (TEXTO_AUROR, SUPERFICIE_AUROR, 4.5, "texto de desplegable sobre la superficie")]:
    v = contraste(frente, fondo)
    ok(v >= minimo, f"{nombre}", f"{v:.2f}:1 (mínimo {minimo})")

print("\n--- y los dos colores que CAUSABAN el bug siguen siendo ilegibles (por eso se fueron) ---")
ok(contraste("#ffffff", VERDE) < 4.5,
   "blanco sobre verde era ilegible", f"{contraste('#ffffff', VERDE):.2f}:1")
ok(contraste(VISITADO_NAVEGADOR, FONDO_AUROR) < 4.5,
   "el violeta de visitado del navegador era ilegible",
   f"{contraste(VISITADO_NAVEGADOR, FONDO_AUROR):.2f}:1")
ok("#ffffff" not in [re.search(r"color:\s*([^;!]+)", c).group(1).strip()
                     for s, c in verdes if re.search(r"color:\s*([^;!]+)", c)],
   "ninguna regla verde dejó el texto en blanco")

print("\n=== 6 · El logo sobrevive a la próxima actualización de GLPI ===")
# GLPI reescribe sus propios logo-GLPI-*.png en cada versión mayor; los ith-*.png no los conoce.
for var in ["--glpi-logo-light", "--glpi-logo-dark", "--glpi-logo-light-reduced",
            "--glpi-logo-dark-reduced", "--glpi-logo-light-login", "--glpi-logo-dark-login"]:
    m = re.search(rf"{re.escape(var)}:\s*url\(\"([^\"]+)\"\)", CSS)
    ok(m is not None and "/pics/logos/ith-" in m.group(1),
       f"{var} apunta a un archivo propio de ITH", m.group(1) if m else "no está")
ok(re.search(r"#page\.page-anonymous \.glpi-logo", CSS) is not None,
   "el logo del login se fuerza con #page (gana por especificidad, no por orden)")

print("\n=== 7 · Lo que el tema NO debe pintar (el error que ya se cometió una vez) ===")
# Pintar los enlaces del contenido dejó las etiquetas de las tarjetas del tablero -que son
# enlaces- en violeta sobre naranja. Las reglas de color tienen que estar acotadas.
sueltos = [sel for sel, cuerpo in REGLAS
           if re.search(r"(^|,)\s*a(:[a-z-]+)?\s*(,|$)", sel) and "color:" in cuerpo]
ok(not sueltos, "no hay ninguna regla que pinte TODOS los enlaces de la página",
   "; ".join(sueltos)[:80] if sueltos else "")
# Se miran los SELECTORES, no el texto crudo: nombrar algo en un comentario para explicar por qué
# NO se toca es justamente lo contrario de tocarlo.
selectores = " ".join(sel for sel, _ in REGLAS)
for prohibido, motivo in [(".card .card-body a", "las tarjetas del tablero eligen su propio texto"),
                          (".secondary-bar", "el tema original pedía no tocarla")]:
    ok(prohibido not in selectores, f"ningún selector toca {prohibido}", motivo)

print("\n=== 8 · El favicon también es de ITH, y la regla está en el orden correcto ===")
# Un favicon NO se puede cambiar por CSS: head.html.twig lo declara fijo como /pics/favicon.ico,
# y ese archivo lo reescribe cada versión mayor de GLPI. Por eso se desvía con el .htaccess.
HTACCESS = os.path.join(RAIZ, "docs", "glpi", "public.htaccess")
ICONO = os.path.join(RAIZ, "docs", "glpi", "ith-favicon.ico")
ok(os.path.exists(ICONO), "el ícono propio de ITH está versionado en el repo")
if os.path.exists(ICONO):
    with open(ICONO, "rb") as fh:
        cabecera = fh.read(6)
    # Un .ico real empieza con 00 00 01 00 y después la cantidad de tamaños que trae.
    tamanos = int.from_bytes(cabecera[4:6], "little") if len(cabecera) >= 6 else 0
    ok(cabecera[:4] == b"\x00\x00\x01\x00", "es un .ico de verdad")
    ok(tamanos >= 4, "trae varios tamaños (16px para la pestaña, 256px para accesos directos)",
       f"{tamanos} tamaños")

with open(HTACCESS, encoding="utf-8") as fh:
    HT = fh.read()
reescritura = HT.find("pics/logos/ith-favicon.ico")
chequeo_archivo = HT.find("REQUEST_FILENAME} -f")
enrutador = HT.find("RewriteRule ^ index.php")
ok(reescritura != -1, "el .htaccess desvía el favicon al archivo propio de ITH")
ok(0 <= reescritura < chequeo_archivo,
   "y lo hace ANTES del chequeo de archivo existente",
   "si fuera después, Apache serviría el favicon de GLPI y la regla nunca correría")
ok(0 < chequeo_archivo < enrutador,
   "el enrutador de GLPI sigue siendo la última regla (si no, la aplicación no arranca)")
for ajuste in ["session.cookie_secure 1", "session.cookie_httponly 1", "session.cookie_samesite Lax"]:
    ok(ajuste in HT, f"no se perdió el endurecimiento de la cookie: {ajuste}")

print("\n" + "=" * 62)
if FALLAS:
    print(f"  FALLAS: {len(FALLAS)}")
    for f in FALLAS:
        print("   -", f)
    print("=" * 62)
    sys.exit(1)
print("  TEMA DE GLPI: OK — todos los chequeos verdes")
print("=" * 62)
