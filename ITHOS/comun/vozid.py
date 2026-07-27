#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Identificación por VOZ del dueño (biometría de voz). Objetivo: que el modo administrador
no dependa solo de la CLAVE — aunque alguien sepa la contraseña, si NO es la voz del dueño,
no entra.

Flujo (como lo pidió Brian):
  1) ENTRENAMIENTO: cada audio del dueño por WhatsApp (de su número autorizado) suma una
     muestra de su voz (solo la parte con voz, ya filtrada por VAD). Se guardan en
     ~/.ithos/voz_dueno/.
  2) Cuando hay MUESTRAS suficientes, se arma el PERFIL de voz (embedding promedio) y queda
     "terminado". A partir de ahí, verificar() compara una voz nueva contra el perfil.
  3) El modo admin puede exigir, además de la clave, que la voz coincida (verificar()).

Embeddings por speaker-embedding ONNX (sin torch) si hay un modelo disponible
(comun/voz_embed.onnx). Mientras no esté el modelo/perfil, verificar() NO bloquea
(devuelve match=True) para no romper nada: primero juntamos tu voz.
"""

import os
import glob
import json
import wave
import logging

log = logging.getLogger("vozid")

DATA = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
# Perfil de voz ROBUSTO (casi perfecto): junta MUCHAS más muestras. MIN = a partir de cuántos audios
# buenos ya se puede verificar (empieza a exigir tu voz para admin); MAX = hasta cuántas sigue afinando
# el perfil promedio (más muestras = discrimina mejor tu voz de otras, sin derivar).
MIN_MUESTRAS = 12         # empieza a verificar tras 12 audios buenos (más confiable que 6)
MAX_MUESTRAS = 40         # sigue entrenando/afinando hasta 40 muestras -> perfil muy robusto
# Umbrales calibrados con muestras REALES del dueño vs 14 voces distintas (edge-tts):
#   T-norm (con cohorte): tu voz z≈2.3–3.9 ; otras z≈-3.5–-1.4  -> umbral 1.0 separa con margen.
#   coseno crudo (sin cohorte): tu voz ≥0.97 ; otras ≤0.93      -> umbral 0.95.
UMBRAL_Z = 1.0           # score T-norm mínimo (normalizado por cohorte) para aceptar la voz
UMBRAL_RAW = 0.95        # coseno crudo mínimo si no hay cohorte disponible
UMBRAL = UMBRAL_RAW      # compat
_DUR_MIN_SEG = 1.2        # descartar audios demasiado cortos para entrenar


def _dir():
    d = os.path.join(DATA, "voz_dueno")
    os.makedirs(d, exist_ok=True)
    return d


def _perfil_path():
    return os.path.join(_dir(), "perfil.json")


def cantidad():
    return len(glob.glob(os.path.join(_dir(), "muestra_*.wav")))


def perfil_listo():
    return os.path.exists(_perfil_path())


def suficiente():
    return cantidad() >= MIN_MUESTRAS


def _guardar_wav(ruta, muestras_int16, fs):
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(bytes(memoryview(muestras_int16).cast("B")))


def _leer_wav(ruta):
    import numpy as np
    with wave.open(ruta, "rb") as w:
        fs = w.getframerate()
        d = np.frombuffer(w.readframes(w.getnframes()), dtype="int16")
    return d, fs


def enrolar(wav_bytes_o_muestras, fs=16000):
    """Suma una muestra de la voz del dueño (para el entrenamiento). Acepta bytes WAV o un
    numpy int16 (ya filtrado a solo-voz). Devuelve (cantidad, suficiente, recien_completo)."""
    import numpy as np
    from comun import audio as AUD
    try:
        if isinstance(wav_bytes_o_muestras, (bytes, bytearray)):
            import io
            with wave.open(io.BytesIO(bytes(wav_bytes_o_muestras)), "rb") as w:
                fs = w.getframerate()
                x = np.frombuffer(w.readframes(w.getnframes()), dtype="int16")
        else:
            x = np.asarray(wav_bytes_o_muestras, dtype="int16")
        voz = AUD.filtrar_voz(x, fs=fs)                 # solo la voz humana
        if len(voz) < _DUR_MIN_SEG * fs:
            return cantidad(), suficiente(), False       # muy corto, no sirve
        antes = cantidad()
        if antes >= MAX_MUESTRAS:                         # perfil ya estable: no crecer infinito
            return antes, True, False                    # (evita drift y que finalizar se ponga lento)
        _guardar_wav(os.path.join(_dir(), f"muestra_{antes + 1:02d}.wav"), voz, fs)
        n = cantidad()
        recien_suficiente = antes < MIN_MUESTRAS <= n    # justo cruzó el mínimo
        # RE-ENTRENA en cada muestra nueva: el perfil MEJORA solo a medida que llegan audios.
        if suficiente():
            finalizar()
        return n, suficiente(), recien_suficiente
    except Exception as e:  # noqa: BLE001
        log.warning("enrolar voz: %s", e)
        return cantidad(), suficiente(), False


def finalizar():
    """(Re)arma el PERFIL de voz: el voiceprint PROMEDIO de todas las muestras. Se llama en
    cada muestra nueva, así el perfil MEJORA solo. True si quedó listo."""
    import numpy as np
    vps = []
    for ruta in sorted(glob.glob(os.path.join(_dir(), "muestra_*.wav"))):
        d, fs = _leer_wav(ruta)
        v = _voiceprint(d, fs)
        if v is not None:
            vps.append(v)
    if not vps:
        return False
    perfil = np.mean(np.stack(vps), axis=0)
    json.dump({"perfil": perfil.tolist(), "muestras": len(vps), "v": 2},
              open(_perfil_path(), "w", encoding="utf-8"))
    log.info("Perfil de voz del dueño actualizado (%d muestras).", len(vps))
    return True


def _a_int16(wav_bytes_o_muestras, fs):
    """Normaliza la entrada a (numpy int16, fs). Acepta int16, WAV bytes u OGG/MP3 bytes."""
    import numpy as np
    if not isinstance(wav_bytes_o_muestras, (bytes, bytearray)):
        return np.asarray(wav_bytes_o_muestras, dtype="int16"), fs
    b = bytes(wav_bytes_o_muestras)
    try:                                                 # ¿WAV?
        import io
        with wave.open(io.BytesIO(b), "rb") as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype="int16"), w.getframerate()
    except Exception:  # noqa: BLE001
        from comun import audio as AUD                   # OGG/opus (WhatsApp) o MP3 -> ffmpeg
        return AUD.decodificar(b, "audio/ogg", fs=fs), fs


def verificar(wav_bytes_o_muestras, fs=16000):
    """Devuelve (es_el_dueño, score). Compara el voiceprint de la voz nueva contra el perfil
    del dueño, normalizado por una COHORTE de voces distintas (T-norm) para que sea robusto.
    Si aún no hay perfil, NO bloquea (True) — así seguimos juntando tu voz sin romper nada."""
    import numpy as np
    if not perfil_listo():
        return True, 1.0
    try:
        x, fs = _a_int16(wav_bytes_o_muestras, fs)
        v = _voiceprint(x, fs)
        if v is None:
            return True, 1.0
        perfil = np.asarray(json.load(open(_perfil_path(), encoding="utf-8"))["perfil"], dtype="float32")
        s = _cos(v, perfil)
        coh = _cohorte()
        if coh is not False and len(coh):                # T-norm: ¿cuánto MÁS se parece a vos
            cs = np.array([_cos(v, c) for c in coh])     # que a un panel de otras voces?
            z = float((s - cs.mean()) / (cs.std() + 1e-9))
            return z >= UMBRAL_Z, z
        return s >= UMBRAL_RAW, float(s)                 # sin cohorte: coseno crudo
    except Exception as e:  # noqa: BLE001
        log.warning("verificar voz: %s", e)
        return True, 1.0


# =============================================================== VOICEPRINT (MFCC, numpy puro)
# Huella de voz SIN modelos pesados ni torch: MFCC (13, se dropea c0=volumen) + su delta, y se
# resume cada audio con media+desvío por dimensión (48 valores). El parecido se mide por
# coseno, normalizado por una COHORTE de voces distintas (comun/voz_cohorte.npy) => robusto.
_COHORTE = None      # matriz (N,48) de voiceprints de OTRAS voces | False si no está el archivo


def _cohorte():
    global _COHORTE
    if _COHORTE is None:
        try:
            import numpy as np
            ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voz_cohorte.npy")
            _COHORTE = np.load(ruta).astype("float32") if os.path.exists(ruta) else False
            if _COHORTE is not False:
                log.info("Cohorte de voces cargada (%d) para verificación robusta.", len(_COHORTE))
        except Exception:  # noqa: BLE001
            _COHORTE = False
    return _COHORTE


def _cos(a, b):
    import numpy as np
    return float(np.dot(a, b) / ((np.linalg.norm(a) + 1e-9) * (np.linalg.norm(b) + 1e-9)))


def _hz2mel(f):
    import numpy as np
    return 2595.0 * np.log10(1 + f / 700.0)


def _mel2hz(m):
    return 700.0 * (10 ** (m / 2595.0) - 1)


def _mel_fb(n_mels, nfft, fs):
    import numpy as np
    pts = np.linspace(_hz2mel(0), _hz2mel(fs / 2), n_mels + 2)
    bins = np.floor((nfft + 1) * _mel2hz(pts) / fs).astype(int)
    fb = np.zeros((n_mels, nfft // 2 + 1))
    for i in range(1, n_mels + 1):
        l, c, r = bins[i - 1], bins[i], bins[i + 1]
        for k in range(l, c):
            if c > l:
                fb[i - 1, k] = (k - l) / (c - l)
        for k in range(c, r):
            if r > c:
                fb[i - 1, k] = (r - k) / (r - c)
    return fb


def _dct(logmel, n_mfcc):
    import numpy as np
    n_mels = logmel.shape[1]
    k = np.arange(n_mfcc)[:, None]
    n = np.arange(n_mels)[None, :]
    basis = np.cos(np.pi * k * (2 * n + 1) / (2 * n_mels))
    basis[0, :] *= 1 / np.sqrt(n_mels)
    basis[1:, :] *= np.sqrt(2.0 / n_mels)
    return logmel @ basis.T


def _mfcc(x_int16, fs, n_mfcc=13, n_mels=26, nfft=512, win=0.025, hop=0.010):
    import numpy as np
    x = np.asarray(x_int16, dtype=np.float32)
    fl, st = int(round(win * fs)), int(round(hop * fs))
    if x.size < fl * 2:
        return None
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])           # pre-énfasis
    nf = 1 + (len(x) - fl) // st
    if nf < 3:
        return None
    idx = np.arange(fl)[None, :] + st * np.arange(nf)[:, None]
    fr = x[idx] * np.hamming(fl)
    ps = (np.abs(np.fft.rfft(fr, nfft)) ** 2) / nfft     # espectro de potencia
    mel = ps @ _mel_fb(n_mels, nfft, fs).T
    mel = np.where(mel <= 0, 1e-10, mel)
    return _dct(np.log(mel), n_mfcc)


def _delta(m):
    import numpy as np
    d = np.zeros_like(m)
    d[1:-1] = (m[2:] - m[:-2]) / 2.0
    d[0] = m[1] - m[0]
    d[-1] = m[-1] - m[-2]
    return d


def _voiceprint(muestras_int16, fs):
    """Huella de voz (48 valores) desde MFCC+delta. None si el audio es muy corto."""
    import numpy as np
    m = _mfcc(muestras_int16, fs)
    if m is None:
        return None
    m = m[:, 1:]                                          # dropea c0 (energía/volumen)
    F = np.concatenate([m, _delta(m)], axis=1)
    return np.concatenate([F.mean(0), F.std(0)]).astype("float32")
