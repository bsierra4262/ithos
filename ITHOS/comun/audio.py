#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Captura de micrófono PROFESIONAL (como Gemini/ChatGPT): graba de forma DINÁMICA por
DETECCIÓN DE SILENCIO en vez de una duración fija. Así no corta las frases largas y no
graba silencio de más. Calibra el ruido de fondo solo, espera a que empieces a hablar y
corta cuando te callás.

FILTRO DE VOZ HUMANA (anti-ruido), en 3 niveles según lo disponible:
  1) Silero VAD v5 por ONNX (red neuronal, offline, SIN torch — solo onnxruntime + el modelo
     comun/silero_vad.onnx, ~2MB). Máxima precisión: descarta ruido de ambiente, música, tono,
     tecleo, etc. y deja SOLO la voz de una persona.
  2) webrtcvad (el de WebRTC/Google, liviano) si no está onnxruntime.
  3) heurística por energía (sin dependencias) como último recurso.
Si el audio no tiene voz humana, NO se transcribe (así ITHOS nunca "inventa" texto de un
ruido: transcribe SOLO lo que dijo alguien). Extras opcionales:  pip install onnxruntime
webrtcvad-wheels . (A futuro: identificación por VOZ del dueño para el modo admin.)

Usado por la demo (iniciar_demo.py) y por el agente en producción (agente/escucha.py).
"""

import logging

log = logging.getLogger("audio")

_SILERO = None    # (modelo, get_speech_timestamps) | False
_WEBRTC = None    # módulo webrtcvad | False


def filtrar_voz(muestras_int16, fs=16000, min_ms=250):
    """Devuelve SOLO los tramos con VOZ HUMANA; si no hay voz, vacío (para NO transcribir
    ruido — así ITHOS nunca inventa). Prioriza precisión y disponibilidad:
      1) Silero VAD (si está instalado: máxima precisión, offline).
      2) webrtcvad (liviano, el de WebRTC/Google — ideal para clientes masivos).
      3) heurística por energía (último recurso, sin dependencias)."""
    import numpy as np
    x16 = np.asarray(muestras_int16, dtype="int16").flatten()
    if x16.size == 0:
        return np.zeros(0, dtype="int16")
    for backend in (_voz_silero, _voz_webrtc):
        r = backend(x16, fs, min_ms)
        if r is not None:                              # el backend estaba disponible
            return r
    # 3) energía: descarta silencio puro (grabar_dinamico ya gatea, esto es de respaldo)
    return x16 if _rms(x16) > 120 else np.zeros(0, dtype="int16")


def _voz_silero(x16, fs, min_ms):
    """Silero VAD v5 por ONNX (red neuronal, offline, SIN torch — solo onnxruntime).
    Máxima precisión: distingue voz humana de ruido/música/tono. Modelo: comun/silero_vad.onnx."""
    global _SILERO
    if _SILERO is None:
        try:
            import os
            import onnxruntime as ort
            ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "silero_vad.onnx")
            opt = ort.SessionOptions()
            opt.log_severity_level = 4
            _SILERO = ort.InferenceSession(ruta, sess_options=opt,
                                           providers=["CPUExecutionProvider"])
            log.info("Filtro de voz: Silero VAD (ONNX).")
        except Exception:  # noqa: BLE001
            _SILERO = False
    if _SILERO is False or fs not in (8000, 16000):
        return None
    try:
        import numpy as np
        ventana = 512 if fs == 16000 else 256          # chunk que exige Silero v5
        ctx = 64 if fs == 16000 else 32                # Silero v5 antepone 64 muestras de contexto
        x = x16.astype("float32") / 32768.0
        estado = np.zeros((2, 1, 128), dtype="float32")
        contexto = np.zeros((1, ctx), dtype="float32")
        sr = np.array(fs, dtype="int64")
        voz = []
        for i in range(0, len(x) - ventana, ventana):
            chunk = x[i:i + ventana].reshape(1, -1).astype("float32")
            inp = np.concatenate([contexto, chunk], axis=1)   # (1, ctx+ventana)
            prob, estado = _SILERO.run(None, {"input": inp, "state": estado, "sr": sr})
            contexto = chunk[:, -ctx:]                 # contexto para el próximo chunk
            if float(prob[0][0]) >= 0.5:               # 0.5 = umbral estándar de Silero
                voz.append(x16[i:i + ventana])
        if not voz or len(voz) * ventana / fs * 1000 < min_ms:
            return np.zeros(0, dtype="int16")          # sin voz suficiente -> descartar
        return np.concatenate(voz).astype("int16")
    except Exception:  # noqa: BLE001
        return None


def _voz_webrtc(x16, fs, min_ms):
    global _WEBRTC
    if _WEBRTC is None:
        try:
            import webrtcvad
            _WEBRTC = webrtcvad
            log.info("Filtro de voz: webrtcvad.")
        except Exception:  # noqa: BLE001
            _WEBRTC = False
    if _WEBRTC is False or fs not in (8000, 16000, 32000, 48000):
        return None
    try:
        import numpy as np
        vad = _WEBRTC.Vad(3)                            # 0=laxo .. 3=agresivo (rechaza más ruido)
        paso = int(fs * 30 / 1000)                     # marcos de 30 ms
        marcos = [x16[i:i + paso] for i in range(0, len(x16) - paso, paso)]
        flags = [vad.is_speech(m.tobytes(), fs) for m in marcos]
        voz = [m for m, sp in zip(marcos, flags) if sp]
        # Exigir voz suficiente Y que sea una porción real del audio (no chispazos sueltos).
        if (not voz or len(voz) * 30 < min_ms
                or (marcos and len(voz) / len(marcos) < 0.35)):
            return np.zeros(0, dtype="int16")
        return np.concatenate(voz).astype("int16")
    except Exception:  # noqa: BLE001
        return None


def _rms(bloque):
    import numpy as np
    x = np.asarray(bloque, dtype="float32").flatten()
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x * x)))


def grabar_dinamico(fs=16000, max_seg=15.0, silencio_seg=1.3, inicio_max=6.0,
                    umbral_min=280.0):
    """Graba del micrófono hasta que hay ~silencio_seg de silencio (o se llega a max_seg).
    Devuelve un numpy int16 mono a `fs`. Si nunca se detecta voz, devuelve arreglo vacío.

    - Calibra el piso de ruido con los primeros ~0.3 s.
    - Espera a que empieces a hablar hasta `inicio_max` s.
    - Corta tras `silencio_seg` de silencio continuo una vez que empezaste a hablar.
    """
    import numpy as np
    import sounddevice as sd
    paso = 0.05                                   # bloques de 50 ms
    blk = int(fs * paso)
    stream = sd.InputStream(samplerate=fs, channels=1, dtype="int16", blocksize=blk)
    stream.start()
    frames = []
    try:
        # 1) Calibrar el ruido de fondo (0.3 s).
        cal = []
        for _ in range(int(0.3 / paso)):
            d, _ = stream.read(blk)
            cal.append(_rms(d))
        piso = (sum(cal) / len(cal)) if cal else 0.0
        umbral = max(piso * 2.8, umbral_min)      # hay voz si supera esto
        hablando = False
        sil = 0.0
        transcurrido = 0.0
        # 2) Bucle de captura.
        while True:
            d, _ = stream.read(blk)
            frames.append(np.array(d, dtype="int16").copy())
            energia = _rms(d)
            transcurrido += paso
            if not hablando:
                if energia > umbral:
                    hablando = True
                elif transcurrido >= inicio_max:
                    return np.zeros(0, dtype="int16")     # nunca habló
            else:
                if energia < umbral:
                    sil += paso
                    if sil >= silencio_seg:
                        break                              # se calló -> listo
                else:
                    sil = 0.0
            if transcurrido >= max_seg:
                break
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001
            pass
    if not frames:
        return np.zeros(0, dtype="int16")     # nunca habló (silencio) -> el caller sale
    # Devuelve el audio CRUDO (gateado por energía). El filtro de VOZ humana (Silero VAD) lo
    # aplica el que llama con filtrar_voz(), así puede distinguir "silencio" de "ruido".
    return np.concatenate(frames).flatten().astype("int16")


def decodificar(audio_bytes, mime="audio/ogg", fs=16000):
    """Decodifica un audio (ogg/opus de WhatsApp, mp3, etc.) a numpy int16 mono a `fs`,
    usando ffmpeg. Devuelve arreglo vacío si no se puede."""
    import shutil
    import subprocess
    import numpy as np
    if not shutil.which("ffmpeg"):
        return np.zeros(0, dtype="int16")
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "quiet", "-i", "pipe:0",
             "-ac", "1", "-ar", str(fs), "-f", "s16le", "pipe:1"],
            input=bytes(audio_bytes), capture_output=True, timeout=30)
        return np.frombuffer(p.stdout, dtype="int16")
    except Exception:  # noqa: BLE001
        return np.zeros(0, dtype="int16")


def a_wav_bytes(muestras_int16, fs=16000):
    """numpy int16 -> bytes WAV (PCM 16-bit mono)."""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(bytes(memoryview(muestras_int16).cast("B")))
    return buf.getvalue()
