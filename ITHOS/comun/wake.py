#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WAKE-WORD de ITHOS — una sola fuente de verdad para TODOS los caminos de activación:
  · TEXTO (Gestor): WhatsApp (oficial y no-oficial), Telegram, Email, Element  -> comun/whatsapp.menciona
  · VOZ (agente): micrófono con Vosk (STT local)                              -> agente/escucha.py
  · Planka: el trigger "ithos" del grupo del equipo                           -> mismo gateo

Qué activa (en español o en inglés, en MAYÚSCULAS o minúsculas, con o sin tildes/puntuación):
  "ithos, ..."            (la marca sola, como siempre)
  "Hey ITHOS, ..."        ("hey" / "hey" en inglés, "ey", "oye", "hola", "ok", "che", "escuchá")
  "hey it hos, ..."       (la transcripción del micrófono PARTE la palabra en dos)
  "hey ethos / aitos ..." (pronunciación INGLESA de ITHOS mal transcripta por un modelo español)

Diseño (por qué así):
  · SIN dependencias (solo stdlib): lo importan el Gestor y el AGENTE empaquetado.
  · ADITIVO: todo lo que activaba antes sigue activando (las variantes difusas 'itos/hitos/izos'
    valen solas). El "Hey ITHOS" suma formas que ANTES NO entraban (tokens partidos, variantes
    inglesas, tildes), nunca resta -> no rompe la activación ya probada por WhatsApp.
  · La marca es ITHOS. 'jarvis' NO activa (ver memoria del proyecto: nunca más esa palabra).
"""

import re
import difflib
import unicodedata

PALABRA = "ithos"

# Variantes de la mala transcripción/pronunciación de "ITHOS" que valen POR SÍ SOLAS (es lo que
# venía funcionando en WhatsApp; se mantiene tal cual para no romper la activación por audio).
VARIANTES = ("itos", "itho", "izos", "hitos", "istos", "itzos", "ithus", "iros")

# Variantes de la pronunciación INGLESA de ITHOS ("ai-zos", "e-thos") que quedan LEJOS de la
# palabra escrita: valen solo ACOMPAÑADAS de un prefijo de llamada ("hey ...", "oye ..."), donde la
# intención es inequívoca. A propósito NO se listan palabras comunes del español ("todos", "otros",
# "estos"…): con "hey" adelante son charla normal del grupo y activarían de más.
VARIANTES_CON_PREFIJO = ("ethos", "etos", "eitos", "aitos", "aizos", "eithos", "aithos", "itous")

# "Hey" y sus equivalentes en español/inglés + cómo suele transcribirlos el STT.
PREFIJOS = ("hey", "hei", "he", "ey", "eh", "ei", "oye", "oi", "oiga", "escucha",
            "escuchame", "che", "hola", "holis", "ok", "okey", "okay", "oka")

_RATIO = 0.75            # similitud mínima (difflib) para aceptar un token como la marca
_RATIO_JUNTOS = 0.8      # más exigente al PEGAR dos tokens ("it"+"hos"): evita azares


def _normalizar(texto):
    """minúsculas, sin tildes/diacríticos y sin puntuación: 'Hey, ÍTHOS!' -> 'hey ithos'."""
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")     # saca tildes/diéresis
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ñ]+", " ", t)).strip()


def _tokens(texto):
    return _normalizar(texto).split()


def _parecido(a, b, ratio=_RATIO):
    return difflib.SequenceMatcher(None, a, b).ratio() >= ratio


def _es_marca(tok, palabra=PALABRA):
    """True si el token ES la marca (o una variante que vale sola)."""
    return bool(tok) and (tok == palabra or palabra in tok or tok in VARIANTES
                          or _parecido(tok, palabra))


def _es_marca_con_prefijo(tok, palabra=PALABRA):
    """True si el token vale COMO marca cuando viene después de un 'hey' (suma las variantes de la
    pronunciación inglesa). NO baja el umbral difuso: así "hola a todos" o "che, listos?" NO activan."""
    return bool(tok) and (_es_marca(tok, palabra) or tok in VARIANTES_CON_PREFIJO)


def _es_prefijo(tok):
    return bool(tok) and (tok in PREFIJOS or any(_parecido(tok, p, 0.85) for p in PREFIJOS))


def es_wake(texto, palabra=PALABRA):
    """True si el texto llama a ITHOS con la FRASE de activación ("Hey ITHOS, ...", "oye ithos",
    "ok ithos", en español o inglés). Tolera que el micrófono PARTA la palabra ('hey it hos').
    Se usa para el log/diagnóstico y como parte de `menciona`."""
    toks = _tokens(texto)
    palabra = (palabra or PALABRA).lower()
    for i, t in enumerate(toks):
        if not _es_prefijo(t):
            continue
        sig = toks[i + 1:i + 4]                     # hasta 3 tokens después del "hey"
        if any(_es_marca_con_prefijo(s, palabra) for s in sig):
            return True
        for a, b in zip(sig, sig[1:]):              # "it hos" / "i thos" pegados
            if _parecido(a + b, palabra, _RATIO_JUNTOS):
                return True
    return False


def menciona(texto, palabra=PALABRA):
    """True si el texto NOMBRA a ITHOS (marca sola) o lo LLAMA ("Hey ITHOS"). Único gateo de
    activación de todos los canales y del micrófono. TOLERA la mala transcripción del audio
    ('itos', 'itho', 'izos', 'hitos'…) igual que antes, y ahora también la palabra PARTIDA en dos
    y la pronunciación inglesa cuando viene con "hey" adelante."""
    palabra = (palabra or PALABRA).lower()
    toks = _tokens(texto)
    if any(_es_marca(t, palabra) for t in toks):
        return True
    for a, b in zip(toks, toks[1:]):                # "it hos" sin "hey" adelante
        if _parecido(a + b, palabra, _RATIO_JUNTOS):
            return True
    return es_wake(texto, palabra)
