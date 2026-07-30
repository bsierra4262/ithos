#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WAKE-WORD de ITHOS — una sola fuente de verdad para TODOS los caminos de activación:
  · TEXTO (Gestor): WhatsApp (oficial y no-oficial), Telegram, Email, Element  -> comun/whatsapp.menciona
  · VOZ (agente): micrófono con Vosk (STT local)                              -> agente/escucha.py
  · Planka: el mismo gateo para mover/crear tarjetas del equipo

REGLA (definida por Brian): hay que **LLAMARLO**, no sólo nombrarlo.
    ✅ "Hey ITHOS, ¿qué tickets hay?"      ✅ "oye ithos, cerrá el 651"      ✅ "ok ithos, terminé X"
    ❌ "ITHOS, ¿qué tickets hay?"          ❌ "che, avisale a ithos"          ❌ "los hitos del proyecto"
Nombrarlo suelto NO activa: en un grupo de trabajo se lo menciona todo el tiempo ("preguntale a ITHOS",
"lo cargó ITHOS") y no corresponde que intervenga. La frase de llamada es inequívoca.

Qué se acepta como llamada, en español o en inglés, en MAYÚSCULAS o minúsculas, con o sin tildes:
  "hey ithos" · "hei/he/ey/eh/ei ithos" · "oye/oí/oiga ithos" · "hola/holis ithos" · "ok/okey/okay ithos"
  "che ithos" · "escuchá/escuchame ithos" · pegado: "heyithos" · partido por el STT: "hey it hos"
  mal transcripto: "hey itos / hitos / izos / ithus" · pronunciación inglesa: "hey ethos / aitos / aizos"

SIN dependencias (sólo stdlib): lo importan el Gestor y el AGENTE empaquetado.
La marca es ITHOS. 'jarvis' no activa nada (ver memoria del proyecto).
"""

import re
import difflib
import unicodedata

PALABRA = "ithos"

# Variantes de la marca por mala transcripción/pronunciación. Sólo cuentan DESPUÉS de la llamada
# ("hey ..."), así que pueden ser generosas sin activar de más en la charla del grupo.
VARIANTES = ("itos", "itho", "izos", "hitos", "istos", "itzos", "ithus", "iros", "ritos", "mitos",
             "ethos", "etos", "eitos", "aitos", "aizos", "eithos", "aithos", "itous", "tos", "hos")

# "Hey" y sus equivalentes en español/inglés + cómo suele transcribirlos el STT.
PREFIJOS = ("hey", "hei", "he", "ey", "eh", "ei", "oye", "oi", "oiga", "escucha", "escuchame",
            "escucha", "che", "hola", "holis", "ok", "okey", "okay", "oka")

_RATIO = 0.75            # similitud mínima (difflib) para aceptar un token como la marca
_RATIO_JUNTOS = 0.8      # más exigente al PEGAR dos tokens ("it"+"hos"): evita azares
_VENTANA = 3             # cuántos tokens después del "hey" se miran (tolera "hey, che, ithos")


def _normalizar(texto):
    """minúsculas, sin tildes/diacríticos y sin puntuación: 'Hey, ÍTHOS!' -> 'hey ithos'."""
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")     # saca tildes/diéresis
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ñ]+", " ", t)).strip()


def _tokens(texto):
    return _normalizar(texto).split()


def _parecido(a, b, ratio=_RATIO):
    return difflib.SequenceMatcher(None, a, b).ratio() >= ratio


def es_marca(tok, palabra=PALABRA):
    """True si el token es la marca o una variante reconocible de ella."""
    return bool(tok) and (tok == palabra or palabra in tok or tok in VARIANTES
                          or _parecido(tok, palabra))


def es_prefijo(tok):
    """True si el token es una llamada ('hey', 'oye', 'ok', 'hola', 'che'…)."""
    return bool(tok) and (tok in PREFIJOS or any(_parecido(tok, p, 0.85) for p in PREFIJOS))


def _pegado(tok, palabra):
    """'heyithos' / 'okithos': la llamada y la marca en un solo token."""
    for p in PREFIJOS:
        if tok.startswith(p) and len(tok) > len(p) and es_marca(tok[len(p):], palabra):
            return True
    return False


def menciona(texto, palabra=PALABRA):
    """True SÓLO si el texto LLAMA a ITHOS: una palabra de llamada seguida de la marca
    ("Hey ITHOS…", "oye ithos…", "ok ithos…"). Nombrarlo suelto ("ITHOS", "avisale a ithos") NO
    activa. Tolera la mala transcripción del audio, la marca partida en dos ("hey it hos"), la
    pronunciación inglesa ("hey ethos") y la forma pegada ("heyithos")."""
    palabra = (palabra or PALABRA).lower()
    toks = _tokens(texto)
    for i, t in enumerate(toks):
        if _pegado(t, palabra):
            return True
        if not es_prefijo(t):
            continue
        sig = toks[i + 1:i + 1 + _VENTANA]
        if any(es_marca(s, palabra) for s in sig):
            return True
        for a, b in zip(sig, sig[1:]):              # "it hos" / "i thos" pegados
            if _parecido(a + b, palabra, _RATIO_JUNTOS):
                return True
    return False


# `es_wake` queda como alias explícito: la activación ES la frase de llamada.
es_wake = menciona
