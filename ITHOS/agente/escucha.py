#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Escucha por palabra clave "ITHOS" (como "OK Google") en el micrófono del cliente. Al detectar
"ITHOS", graba el pedido, lo manda al central (evento consulta_voz) y el central responde/resuelve
(la respuesta vuelve como voz). El AUDIO también sirve para el voz-id (que ITHOS verifique que sos vos
para los comandos de administrador; el perfil de voz ya se entrenó con tus audios de WhatsApp).

DOS motores (config microfono -> "motor"):
  · "vosk"  (POR DEFECTO, OPEN-SOURCE, sin registro ni límites): reconoce la palabra "ITHOS" con un
     modelo de voz LOCAL (Vosk/Kaldi). No hay que entrenar nada: reconoce "ithos" de fábrica y tolera
     la mala pronunciación (mismo criterio difuso que WhatsApp). El modelo se toma de `vosk_model`
     (carpeta) o se baja el pequeño en español la 1ª vez (una sola vez, sin registro).
  · "picovoice" (LEGACY): Porcupine con access key + modelo ithos.ppn de console.picovoice.ai (registro).

Config (agente/config.json -> microfono):
  {"enabled": true, "motor": "vosk", "vosk_model": "C:/ruta/modelo (opcional)",
   "activacion_palabra": "ithos", "max_seg_pedido": 15, "silencio_seg": 1.3}
"""

import io
import os
import time
import json
import wave
import base64
import struct
import logging

log = logging.getLogger("agente.escucha")


def _rms(frame):
    if not frame:
        return 0.0
    return (sum(x * x for x in frame) / len(frame)) ** 0.5


def _solo_voz(frames_int16, sr):
    """Deja SOLO la voz humana (Silero VAD, comun/audio.py). Descarta ruido de ambiente;
    si no hay voz devuelve [] (no se manda nada al central: ITHOS no inventa)."""
    if not frames_int16:
        return []
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from comun import audio as AUD
        return list(AUD.filtrar_voz(frames_int16, fs=sr))
    except Exception:  # noqa: BLE001
        return frames_int16


def _grabar_dinamico(stream, sr, fl, max_seg, silencio_seg, umbral_min):
    """Graba del stream ya abierto hasta ~silencio_seg de silencio (o max_seg). Devuelve
    una lista de int16. Captura la frase completa aunque sea larga."""
    paso = fl / sr
    frames = []
    hablando = False
    sil = 0.0
    transcurrido = 0.0
    while transcurrido < max_seg:
        d, _ = stream.read(fl)
        pcm = list(struct.unpack_from("h" * fl, d))
        frames.extend(pcm)
        transcurrido += paso
        e = _rms(pcm)
        if not hablando:
            if e > umbral_min:
                hablando = True
        else:
            if e < umbral_min:
                sil += paso
                if sil >= silencio_seg:
                    break
            else:
                sil = 0.0
    return frames if hablando else []


def _wav_b64(frames_int16, sr):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack("h" * len(frames_int16), *frames_int16))
    return base64.b64encode(buf.getvalue()).decode()


def _menciona(texto, palabra):
    """Detección DIFUSA de la palabra de activación (tolera 'itos/itus/ithus' de la mala
    pronunciación), igual criterio que WhatsApp. Con fallback simple si no está el módulo."""
    try:
        from comun.whatsapp import menciona
        return menciona(texto, palabra)
    except Exception:  # noqa: BLE001
        t = " " + (texto or "").lower() + " "
        return any(v in t for v in (f" {palabra} ", " itos ", " itus ", " ithus ", " izos "))


def _cargar_modelo_vosk(cfg):
    """Modelo Vosk LOCAL (open-source, sin registro). De `vosk_model` (carpeta) o baja el pequeño en
    el idioma pedido la 1ª vez (una sola vez). Devuelve el Model o None si no se pudo."""
    from vosk import Model
    mp = cfg.get("vosk_model")
    if mp and os.path.isdir(mp):
        return Model(mp)
    # Sin carpeta propia: Vosk baja el modelo PEQUEÑO del idioma (a su caché) una sola vez, sin registro.
    return Model(lang=(cfg.get("idioma_vosk") or "es"))


def vigilar(cfg, enviar_evento, stop=None):
    """Punto de entrada: elige el motor (Vosk open-source por defecto; Picovoice legacy)."""
    motor = (cfg.get("motor") or "vosk").lower()
    if motor in ("picovoice", "porcupine"):
        return _vigilar_picovoice(cfg, enviar_evento, stop)
    return _vigilar_vosk(cfg, enviar_evento, stop)


def _vigilar_vosk(cfg, enviar_evento, stop=None):
    """Wake-word "ITHOS" 100% LOCAL y open-source (Vosk). No entrena nada: reconoce "ithos" de fábrica.
    Al detectarla, graba el pedido (corta al silencio) y lo manda al central con el AUDIO (para el
    voz-id, ya entrenado por WhatsApp). Sin registro, sin límites, sin internet salvo la 1ª descarga."""
    try:
        from vosk import KaldiRecognizer
        import sounddevice as sd
    except Exception as e:  # noqa: BLE001
        log.error("Escucha por voz deshabilitada (falta vosk/sounddevice): %s", e)
        return
    try:
        model = _cargar_modelo_vosk(cfg)
    except Exception as e:  # noqa: BLE001
        log.error("No se pudo cargar el modelo Vosk (open-source): %s", e)
        return
    palabra = (cfg.get("activacion_palabra") or "ithos").lower()
    sr = 16000
    fl = int(cfg.get("block", 4000))                 # ~0.25 s por bloque
    max_seg = cfg.get("max_seg_pedido", 15)
    silencio_seg = cfg.get("silencio_seg", 1.3)
    umbral_min = cfg.get("umbral_voz", 280.0)
    rec = KaldiRecognizer(model, sr)

    def _abrir():
        """Re-escanea PortAudio para tomar el dispositivo de entrada ACTUAL (tras cambiarlo: auriculares
        <-> parlantes/otro mic) y abre el stream. El micrófono es el ÚNICO que usa sounddevice en el
        agente, así que re-inicializar PortAudio acá no rompe nada (el audio de SALIDA va por pygame)."""
        try:
            sd._terminate()
            sd._initialize()
        except Exception:  # noqa: BLE001
            pass
        s = sd.RawInputStream(samplerate=sr, blocksize=fl, channels=1, dtype="int16")
        s.start()
        try:
            nom = sd.query_devices(kind="input").get("name")
        except Exception:  # noqa: BLE001
            nom = "?"
        return s, nom

    stream, dev = _abrir()
    log.info("[MIC] dispositivo de entrada: '%s'", dev)
    log.info("Escucha por voz OPEN-SOURCE (Vosk) activa. Decí '%s' y después tu pedido.", palabra)
    _rev = time.time()
    try:
        while stop is None or not stop.is_set():
            # Cada ~15s reabrimos el mic en el dispositivo por defecto ACTUAL -> SIGUE el cambio de
            # dispositivo de entrada (auriculares<->parlantes/otro mic) SIN reiniciar el agente. El
            # corte es ~0.3s (imperceptible para el wake-word).
            if time.time() - _rev > 15:
                _rev = time.time()
                try:
                    stream.stop()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
                stream, ndev = _abrir()
                if ndev != dev:
                    log.info("[MIC] dispositivo de entrada ahora: '%s'", ndev)
                dev = ndev
                rec.Reset()
                continue
            try:
                data, _ = stream.read(fl)
            except Exception as e:  # noqa: BLE001   # dispositivo perdido/cambiado -> reabrir
                log.info("[MIC] lectura falló (%s); reabro el micrófono...", str(e)[:60])
                try:
                    stream.stop()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.3)
                stream, dev = _abrir()
                rec.Reset()
                continue
            b = bytes(data)
            if rec.AcceptWaveform(b):
                txt = json.loads(rec.Result()).get("text", "")
            else:
                txt = json.loads(rec.PartialResult()).get("partial", "")
            if txt and _menciona(txt, palabra):
                log.info("Activación por voz detectada ('%s'). Grabando el pedido...", palabra)
                rec.Reset()
                frames = _grabar_dinamico(stream, sr, fl, max_seg, silencio_seg, umbral_min)
                frames = _solo_voz(frames, sr)       # filtro anti-ruido (Silero VAD)
                if frames:
                    enviar_evento({"evento": "consulta_voz",
                                   "datos": {"audio_b64": _wav_b64(frames, sr),
                                             "mime": "audio/wav"}})
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001
            pass


def _vigilar_picovoice(cfg, enviar_evento, stop=None):
    try:
        import pvporcupine
        import sounddevice as sd
    except Exception as e:  # noqa: BLE001
        log.error("Escucha por voz deshabilitada (falta pvporcupine/sounddevice): %s", e)
        return
    # Preferimos el MODELO PROPIO "ithos.ppn" (keyword_paths). Si no está, caemos a una
    # palabra INCLUIDA de respaldo ("computer") con aviso, hasta que se cargue el ithos.ppn.
    rutas = cfg.get("keyword_paths") or None
    palabras = cfg.get("keywords") or [cfg.get("keyword", "computer")]
    if not rutas:
        log.warning("Sin 'keyword_paths' (ithos.ppn): activo por palabra de respaldo %s. "
                    "Para activar por 'ITHOS', entrená el modelo en console.picovoice.ai "
                    "y poné su .ppn en keyword_paths.", palabras)
    try:
        kw = {"access_key": cfg["picovoice_key"]}
        if rutas:
            kw["keyword_paths"] = rutas
        else:
            kw["keywords"] = palabras
        porcupine = pvporcupine.create(**kw)
    except Exception as e:  # noqa: BLE001
        log.error("No se pudo iniciar Porcupine: %s", e)
        return
    etiquetas = [os.path.splitext(os.path.basename(p))[0] for p in rutas] if rutas else palabras
    sr, fl = porcupine.sample_rate, porcupine.frame_length
    # Grabación DINÁMICA: corta al detectar silencio (no una duración fija que trunca las
    # frases largas). Parámetros configurables por si el ambiente es ruidoso.
    max_seg = cfg.get("max_seg_pedido", 15)
    silencio_seg = cfg.get("silencio_seg", 1.3)
    umbral_min = cfg.get("umbral_voz", 280.0)
    stream = sd.RawInputStream(samplerate=sr, blocksize=fl, channels=1, dtype="int16")
    stream.start()
    log.info("Escuchando palabra(s) clave: %s ...", ", ".join(etiquetas))
    try:
        while stop is None or not stop.is_set():
            data, _ = stream.read(fl)
            pcm = struct.unpack_from("h" * fl, data)
            if porcupine.process(pcm) >= 0:
                log.info("Palabra clave detectada. Grabando (corto al detectar silencio)...")
                frames = _grabar_dinamico(stream, sr, fl, max_seg, silencio_seg, umbral_min)
                frames = _solo_voz(frames, sr)     # filtro anti-ruido (Silero VAD)
                if frames:
                    enviar_evento({"evento": "consulta_voz",
                                   "datos": {"audio_b64": _wav_b64(frames, sr),
                                             "mime": "audio/wav"}})
    finally:
        try:
            stream.stop()
            stream.close()
            porcupine.delete()
        except Exception:  # noqa: BLE001
            pass
