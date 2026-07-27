#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS COMPARTIDO para las NOTAS DE VOZ que se ENVÍAN por los canales (WhatsApp oficial/no-oficial,
Telegram, etc.). Estas notas usan **edge-tts** (rápido, gratis, sin cuota): los canales llaman a
`audio()` SIN `ia_cfg`. La voz de MARCA **Charon** es para los PARLANTES (respuestas habladas en el
lugar + portero → `agente/voz.py`), NO para las notas que se mandan por chat.
    · edge-tts (GRATIS)  -> notas de voz de los canales (default, sin API key).
    · Charon (Gemini)    -> disponible como opción si un caller pasa `ia_cfg` y el texto es corto;
                            hoy los canales no lo hacen (priorizan velocidad y costo cero).
Aplica la misma limpieza/pronunciación/pausas (comun/locucion.py) y devuelve OGG/opus
(formato de nota de voz de WhatsApp y Telegram); sin ffmpeg devuelve lo que tenga (mp3/wav).
"""

import shutil
import subprocess
import logging
import threading

log = logging.getLogger("voz_tts")
VOZ = "es-MX-JorgeNeural"


# Charon (Gemini TTS) es lindo pero LENTO en textos largos; para notas largas conviene edge
# (rápido, gratis, sin cuota). Umbral de caracteres para preferir Charon.
_MAX_CHARON = 700
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


def audio(texto, ia_cfg=None, idioma="es-AR", velocidad=1.25, formato="ogg"):
    """Nota de voz ITHOS. Charon (Gemini) para respuestas CORTAS (calidad de marca); para
    LARGAS usa edge (rápido, para que la nota llegue enseguida). Si Charon falla, cae a edge.
    Respuestas muy largas se resumen (la voz no lee 4000 palabras).
    formato 'ogg' (opus) o 'mp3'. Devuelve bytes o None."""
    texto = resumir_para_voz(texto)
    # 1) Charon (Gemini) — solo si hay config y el texto no es muy largo (si no, sería lento).
    if ia_cfg and len(texto or "") <= _MAX_CHARON:
        wav = _charon_wav(texto, ia_cfg)
        if wav:
            return _a_ogg(wav, velocidad) if (formato == "ogg" and shutil.which("ffmpeg")) else wav
    # 2) edge-tts (rápido y gratis). Ya aplica la velocidad en el rate.
    mp3 = _edge_mp3(texto, idioma=idioma, velocidad=velocidad)
    if not mp3:
        return None
    return _a_ogg(mp3, 1.0) if (formato == "ogg" and shutil.which("ffmpeg")) else mp3


_PRECALENTADO = False


def precalentar():
    """Calienta la ruta de la nota de voz (edge-tts) EN SEGUNDO PLANO: hace una síntesis mínima y la
    descarta, así el PRIMER audio real no paga el arranque en frío (import + DNS/TLS a edge). Una
    sola vez, best-effort, no bloquea ni rompe. Aplica a demo y producción."""
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


def _charon_wav(texto, ia_cfg):
    """PCM de Charon (Gemini) -> WAV bytes (24kHz mono). None si no hay cuota / falla."""
    try:
        import io
        import wave
        from comun import ia as IA
        from comun import locucion
        pcm = IA.crear_voz(ia_cfg).voz_pcm(locucion.preparar(texto, fonetica=False))
        if not pcm:
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        log.info("Charon no disponible para la nota de voz (%s). Uso edge.", str(e)[:80])
        return None


def _edge_mp3(texto, idioma="es-AR", velocidad=1.25, voz=VOZ):
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
    """Convierte audio (wav/mp3) a OGG/opus con ffmpeg, ajustando velocidad si hace falta
    (Charon viene a velocidad normal; edge ya viene acelerado)."""
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
