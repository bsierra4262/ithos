#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS de las NOTAS DE VOZ que se ENVÍAN por WhatsApp: **edge-tts** (rápido, gratis, sin cuota).
La voz de MARCA **Charon** es para los PARLANTES (respuestas habladas + portero → agente/voz.py), que
la guardan y la reutilizan. Las notas de WhatsApp NO usan Charon a propósito: Charon gasta cuota de
Gemini, y cada nota es un texto nuevo que no se puede reutilizar; si la cuota se agota, los
parlantes se quedan sin la voz de marca.
Aplica la misma limpieza/pronunciación/pausas (comun/locucion.py). Devuelve MP3 (lo que pide
WhatsApp) u OGG/opus si se pide y hay ffmpeg.
"""

import shutil
import subprocess
import logging
import threading

log = logging.getLogger("voz_tts")
VOZ = "es-MX-JorgeNeural"


# El audio sale COMPLETO, igual que el texto (sin límite artificial): el largo lo decide la
# respuesta (corta por defecto, larga solo si piden detalle). Este techo es SOLO anti-patológico
# (un runaway de miles de palabras que colgaría a edge-tts); en respuestas reales nunca corta.
_MAX_VOZ = 20000


def resumir_para_voz(texto, limite=_MAX_VOZ):
    """Acorta un texto largo a algo escuchable: corta en el último fin de frase antes del
    límite y agrega que el detalle completo está por escrito. Textos cortos van tal cual."""
    import re
    t = (texto or "").strip()
    if len(t) <= limite:
        return t
    corte = t[:limite]
    m = list(re.finditer(r"[.!?…]\s", corte))
    if m and m[-1].end() > limite * 0.4:
        corte = corte[:m[-1].end()]
    return corte.rstrip() + " Te dejé el detalle completo por escrito, señor."


def audio(texto, velocidad=1.25, formato="ogg"):
    """Nota de voz ITHOS con edge-tts (ya aplica la velocidad en el rate). Respuestas muy largas
    se resumen (la voz no lee 4000 palabras). formato 'ogg' (opus) o 'mp3'. Bytes o None."""
    texto = resumir_para_voz(texto)
    mp3 = _edge_mp3(texto, velocidad=velocidad)
    if not mp3:
        return None
    return _a_ogg(mp3, 1.0) if (formato == "ogg" and shutil.which("ffmpeg")) else mp3


_PRECALENTADO = False


def precalentar():
    """Calienta la ruta de la nota de voz (edge-tts) EN SEGUNDO PLANO: hace una síntesis mínima y la
    descarta, así el PRIMER audio real no paga el arranque en frío (import + DNS/TLS a edge). Una
    sola vez, best-effort, no bloquea ni rompe."""
    global _PRECALENTADO
    if _PRECALENTADO:
        return
    _PRECALENTADO = True

    def _run():
        try:
            _edge_mp3("Listo.", velocidad=1.25)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_run, name="precalentar-voz", daemon=True).start()


def _edge_mp3(texto, velocidad=1.25, voz=VOZ):
    try:
        import asyncio
        import edge_tts
    except Exception:  # noqa: BLE001
        return None
    from comun import locucion
    t = locucion.preparar(texto or "", fonetica=True)
    if not t.strip():
        return None
    pct = int(round((velocidad - 1) * 20))
    rate = f"+{pct}%" if pct >= 0 else f"{pct}%"

    async def _go():
        # STREAM a MEMORIA (sin archivo temporal en disco -> más rápido y sin I/O): junta los
        # chunks de audio a medida que llegan de edge.
        buf = bytearray()
        async for chunk in edge_tts.Communicate(t, voz, rate=rate, pitch="-12Hz").stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                buf += chunk["data"]
        return bytes(buf)

    loop = asyncio.new_event_loop()
    try:
        data = loop.run_until_complete(_go())
        return data or None
    except Exception:  # noqa: BLE001
        return None
    finally:
        loop.close()


def _a_ogg(audio_bytes, velocidad=1.0):
    """Convierte audio (mp3) a OGG/opus con ffmpeg, ajustando la velocidad si hace falta."""
    filtros = ["-filter:a", f"atempo={velocidad}"] if abs(velocidad - 1.0) > 0.01 else []
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "quiet", "-i", "pipe:0",
             *filtros, "-c:a", "libopus", "-b:a", "32k",
             # metadata a nivel FORMATO y STREAM: evita el warning 'tags NoneType' de neonize
             # (lee format.tags y stream.tags) al mandar la nota de voz.
             "-metadata", "title=ITHOS", "-metadata", "encoder=ITHOS",
             "-metadata:s:a:0", "title=ITHOS", "-metadata:s:a:0", "language=spa",
             "-f", "ogg", "pipe:1"],
            input=audio_bytes, capture_output=True, timeout=40)
        return p.stdout or audio_bytes
    except Exception:  # noqa: BLE001
        return audio_bytes
