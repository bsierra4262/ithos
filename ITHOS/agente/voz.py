#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de voz del AGENTE (corre en la maquina del cliente, con parlantes).

Recibe TEXTO del central y lo reproduce con la voz ITHOS (Charon, identidad fija).
No bloquea: hilo propio con cola y UN event loop dedicado (patron del monolito).
  cachear=True  -> genera una vez, guarda WAV a velocidad, reproduce archivo (instant).
  cachear=False -> STREAMING + WSOLA (baja latencia). Respaldo edge-tts si falla.
"""

import os
import re
import sys
import wave
import time
import queue
import hashlib
import asyncio
import logging
import threading

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, ".."))
from comun import ia as IA  # noqa: E402

log = logging.getLogger("agente.voz")


class _CuotaVoz(Exception):
    """La voz de MARCA (Charon/Gemini) agotó su cuota diaria de TTS. Se usa para PAUSAR el pre-cacheo
    (reintenta al restablecerse) SIN caer a otra voz -> la caché queda 100% uniforme con la voz de marca."""


def _es_error_cuota(e):
    s = str(e)
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "quota" in s.lower()


# Ritmo NATURAL aproximado de la voz a 1.0x, en letras habladas por segundo (medido con Charon sobre
# saludos reales ~8.3). Se usa para NORMALIZAR el ritmo del cacheo: todos los saludos suenan a la misma
# velocidad aunque el TTS hable el mismo texto más rápido/lento entre generaciones. Ver _pcm_a_wav (H70).
_LETRAS_POR_SEG = 8.3


class VozAgente:
    def __init__(self, cfg_voz, cache_dir=None, velocidad=1.25, salt="v1", streaming=True):
        self.ia = IA.crear_voz(cfg_voz)          # Charon (identidad ITHOS) o voz local si se exige
        # ¿Hay voz de MARCA disponible? Charon = Gemini y NECESITA una key de Gemini. Si el cliente
        # NO usa Gemini (ni hay key), no hay identidad Charon -> usamos edge SIEMPRE (sin intentar
        # Charon y fallar en cada frase, que agrega latencia). La voz local cuenta como identidad propia.
        self._voz_marca = bool(getattr(self.ia, "api_key", "")) or \
            isinstance(self.ia, getattr(IA, "LocalVoz", ()))
        if not self._voz_marca:
            log.info("Sin key de Gemini: la voz usa edge-tts siempre (sin identidad Charon de marca).")
        self.velocidad = float(velocidad or 1.0)
        self.salt = salt
        self.streaming = streaming
        self.cache_dir = cache_dir or os.path.join(BASE, "voz_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._limpiar_temporales()               # borra _tmp_* huérfanos de corridas anteriores
        self.q = queue.Queue(maxsize=4)
        self.pq = queue.Queue()                  # cola de PRE-CACHEO (baja prioridad, tiempo ocioso)
        self._cuota_hasta = 0.0                  # si Charon agota cuota, no insistir hasta este instante
        self._stop = threading.Event()
        self._reproduciendo = False
        self.loop = asyncio.new_event_loop()     # UN loop dedicado (worker)
        # El audio se inicializa PEREZOSO (antes de cada reproducción): si al arrancar la PC está
        # bloqueada / entrada por RDP / el agente arranca headless, puede no haber dispositivo de
        # audio todavía. En vez de fallar para siempre, se reintenta al reproducir (ver _asegurar_audio).
        self._asegurar_audio()                   # intento inicial (best-effort, no fatal)
        threading.Thread(target=self._run, name="voz", daemon=True).start()

    def _asegurar_audio(self):
        """Garantiza el mixer inicializado. Reintenta si al arrancar no había dispositivo (PC
        bloqueada, RDP, arranque headless): así, cuando el audio vuelve, el portero SUENA igual."""
        try:
            import pygame
            if pygame.mixer.get_init():
                return True
            pygame.mixer.init()
            return bool(pygame.mixer.get_init())
        except Exception as e:  # noqa: BLE001
            log.warning("Audio no disponible aún (se reintenta al reproducir): %s", e)
            return False

    def _reset_audio(self, devicename=None):
        """Reinicia el mixer para RE-TOMAR un dispositivo. Necesario cuando el dispositivo cambió o se
        perdió (bloqueo de pantalla, conexión/desconexión de RDP): el handle viejo queda muerto y no
        suena; con quit()+init() se re-engancha. Si se pasa `devicename`, abre ESE dispositivo por nombre
        (para forzar los parlantes físicos cuando el 'default' quedó en el audio de RDP muerto)."""
        try:
            import pygame
            try:
                pygame.mixer.quit()
            except Exception:  # noqa: BLE001
                pass
            if devicename:
                pygame.mixer.init(devicename=devicename)
            else:
                pygame.mixer.init()
            return bool(pygame.mixer.get_init())
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo reiniciar el audio ('%s'): %s", devicename or "default", e)
            return False

    def _tocar(self, ruta):
        """Carga y reproduce en el mixer ACTUAL (sin reiniciar nada). True si SONÓ (get_busy). Es el
        núcleo del camino RÁPIDO: cero overhead para que el saludo sea INSTANTÁNEO."""
        import pygame
        try:
            pygame.mixer.music.load(ruta)
            pygame.mixer.music.set_volume(1.0)
            pygame.mixer.music.play()
            arranco = False
            for _ in range(20):                       # hasta ~200ms solo si NO arranca
                if pygame.mixer.music.get_busy():
                    arranco = True
                    break
                time.sleep(0.01)
            if not arranco:
                return False
            while pygame.mixer.music.get_busy() and not self._stop.is_set():
                time.sleep(0.05)
            pygame.mixer.music.unload()
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("[VOZ] _tocar falló: %s", e)
            return False

    def _reproducir_archivo(self, ruta):
        """Reproduce un WAV/MP3. CAMINO RÁPIDO (99% de las veces, portero en la consola): si el mixer ya
        está vivo, toca DIRECTO -> instantáneo, sin reinicializar ni diagnosticar. CAMINO RESILIENTE (solo
        si el rápido falla: pantalla bloqueada / RDP / dispositivo cambiado): recién ahí re-engancha el
        dispositivo, reconecta la consola si quedó fuera (post-RDP) y prueba CADA parlante físico."""
        import pygame
        if pygame.mixer.get_init() and self._tocar(ruta):
            return True                               # RÁPIDO: sonó directo
        # -- RESILIENTE (raro): recuperar el dispositivo --
        log.info("[VOZ] el audio no sonó directo; recupero el dispositivo (lock/RDP)...")
        self._diag_audio("fallo")
        self._asegurar_consola()                      # si quedó fuera de consola (post-RDP), la reconecta
        dispositivos = [None]                         # default + cada salida física por nombre
        try:
            from pygame._sdl2 import audio as _sa
            for d in _sa.get_audio_device_names(False):
                if d and d not in dispositivos:
                    dispositivos.append(d)
        except Exception:  # noqa: BLE001
            pass
        for dev in dispositivos:
            if self._stop.is_set():
                return False
            if self._reset_audio(dev) and self._tocar(ruta):
                log.info("[VOZ] recuperado: sonó por '%s'.", dev or "default")
                return True
        log.error("[VOZ] NO se pudo reproducir por ningún dispositivo: %s", os.path.basename(ruta))
        self._diag_audio("final-fallo")
        return False

    def _diag_audio(self, momento=""):
        """Log DETALLADO del estado del audio + la SESIÓN de Windows para diagnosticar por qué no suena.
        Causa típica al DESCONECTAR RDP: la sesión del proceso queda DESCONECTADA de la consola FÍSICA y
        el audio de una sesión desconectada NO llega a los parlantes reales (no es el mixer, es la sesión).
        Se loguea en cada reproducción (INFO -> queda en agente.log) para ver el estado exacto al fichar."""
        partes = []
        if os.name == "nt":
            try:
                import ctypes
                k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
                sid = ctypes.c_ulong(0)
                k32.ProcessIdToSessionId(k32.GetCurrentProcessId(), ctypes.byref(sid))
                consola = k32.WTSGetActiveConsoleSessionId()        # sesión pegada a la consola física
                remota = bool(u32.GetSystemMetrics(0x1000))         # SM_REMOTESESSION
                en_consola = (sid.value == consola)
                partes.append(f"sesion={sid.value} "
                              f"consola_fisica={'NINGUNA' if consola == 0xFFFFFFFF else consola} "
                              f"en_consola={en_consola} rdp_actual={remota}")
                if not en_consola:
                    partes.append("AVISO: la sesion NO esta en la consola fisica -> el audio quiza NO "
                                  "llegue a los parlantes reales (sesion desconectada por RDP)")
            except Exception as e:  # noqa: BLE001
                partes.append(f"sesion_err={e!r}")
        try:
            import pygame
            partes.append(f"mixer_init={pygame.mixer.get_init()}")
            try:
                from pygame._sdl2 import audio as _sa
                nombres = list(_sa.get_audio_device_names(False))    # dispositivos de SALIDA que ve SDL
                partes.append(f"salidas({len(nombres)})={nombres}")
            except Exception as e:  # noqa: BLE001
                partes.append(f"sdl2_devices_err={e!r}")
        except Exception as e:  # noqa: BLE001
            partes.append(f"pygame_err={e!r}")
        log.info("[VOZ][DIAG:%s] %s", momento, " | ".join(partes))

    def _sesion_desconectada(self, sid):
        """True si la sesión `sid` está DESCONECTADA (WTSDisconnected): nadie la está viendo (ni consola
        ni RDP activo). Solo entonces conviene reconectarla a la consola (no si alguien la usa por RDP)."""
        try:
            import ctypes
            from ctypes import wintypes
            w = ctypes.windll.wtsapi32
            buf, n = ctypes.c_void_p(), wintypes.DWORD()
            if not w.WTSQuerySessionInformationW(0, sid, 8, ctypes.byref(buf), ctypes.byref(n)):
                return False                          # 8 = WTSConnectState
            estado = ctypes.cast(buf, ctypes.POINTER(ctypes.c_int)).contents.value
            w.WTSFreeMemory(buf)
            return estado == 4                        # 4 = WTSDisconnected
        except Exception:  # noqa: BLE001
            return False

    def _asegurar_consola(self):
        """FIX del audio tras desconectar RDP (H74). En Windows cliente solo hay 1 sesión interactiva: al
        conectar RDP la sesión se va del console y al DESCONECTAR queda DESCONECTADA -> sin los parlantes
        físicos (el mixer ni inicializa). Solución: si el agente quedó DESCONECTADO y fuera de la consola,
        RECONECTA su sesión a la consola con `tscon`. Como tscon necesita privilegios de SISTEMA, el agente
        (admin) crea+corre una tarea ONE-SHOT como SYSTEM. Solo si está DESCONECTADA (no si alguien la usa
        por RDP). Best-effort + cooldown 60s. No-op fuera de Windows."""
        if os.name != "nt":
            return
        if time.time() < getattr(self, "_consola_hasta", 0):
            return
        try:
            import ctypes
            import subprocess
            k32 = ctypes.windll.kernel32
            sid = ctypes.c_ulong(0)
            k32.ProcessIdToSessionId(k32.GetCurrentProcessId(), ctypes.byref(sid))
            consola = k32.WTSGetActiveConsoleSessionId()
            if consola == 0xFFFFFFFF or sid.value == consola:
                return                                # ya está en la consola física -> nada que hacer
            if not self._sesion_desconectada(sid.value):
                return                                # activa (alguien la usa por RDP) -> no la muevo
            self._consola_hasta = time.time() + 60    # no insistir en cada saludo
            tn = "ITHOS_Reconectar_Consola"
            log.info("[VOZ] sesión %s DESCONECTADA fuera de la consola (consola=%s); reconecto vía tarea "
                     "SYSTEM (tscon)...", sid.value, consola)
            nw = 0x08000000                           # CREATE_NO_WINDOW
            # tscon vive en System32 (siempre en el PATH del sistema) -> lo llamamos por nombre, sin ruta
            # hardcodeada (portable). 1) Directo (el agente es admin /RL HIGHEST): a veces alcanza.
            rd = subprocess.run(["tscon", str(sid.value), "/dest:console"],
                                capture_output=True, text=True, timeout=10, creationflags=nw)
            log.info("[VOZ] tscon directo rc=%s %s", rd.returncode,
                     ((rd.stderr or "") + (rd.stdout or "")).strip()[:120])
            if rd.returncode != 0:                    # 2) Fallback: tarea ONE-SHOT como SYSTEM (SeTcbPrivilege)
                rc = subprocess.run(["schtasks", "/Create", "/F", "/TN", tn, "/RU", "SYSTEM", "/RL",
                                     "HIGHEST", "/SC", "ONCE", "/ST", "00:00",
                                     "/TR", f"tscon {sid.value} /dest:console"],
                                    capture_output=True, text=True, timeout=10, creationflags=nw)
                log.info("[VOZ] schtasks /Create rc=%s %s", rc.returncode,
                         ((rc.stderr or "") + (rc.stdout or "")).strip()[:120])
                rr = subprocess.run(["schtasks", "/Run", "/TN", tn],
                                    capture_output=True, text=True, timeout=10, creationflags=nw)
                log.info("[VOZ] schtasks /Run rc=%s %s", rr.returncode,
                         ((rr.stderr or "") + (rr.stdout or "")).strip()[:120])
            time.sleep(2.5)                            # dar tiempo al tscon + a que aparezcan los parlantes
        except Exception as e:  # noqa: BLE001
            log.warning("[VOZ] no pude reconectar la consola: %s", e)

    def decir(self, texto, cachear=True):
        log.debug("[VOZ] %s", texto)
        try:
            self.q.put_nowait((texto, cachear))
        except queue.Full:
            try:
                self.q.get_nowait()
                self.q.put_nowait((texto, cachear))
            except queue.Empty:
                pass

    def detener(self):
        self._stop.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass

    def _run(self):
        asyncio.set_event_loop(self.loop)        # el loop es el "actual" del worker
        while not self._stop.is_set():
            try:
                item = self.q.get(timeout=0.5)   # PRIORIDAD: saludos EN VIVO
            except queue.Empty:
                self._precachear_uno()           # sin saludos pendientes -> pre-cachear (ocioso)
                continue
            if item is None:
                break
            texto, cachear = item
            log.debug("[VOZ] worker toma saludo (cachear=%s): %s", cachear, (texto or "")[:60])
            self._reproduciendo = True
            try:
                self._reproducir(texto, cachear)
            except Exception as e:  # noqa: BLE001
                log.warning("Fallo al hablar: %s", e)
            finally:
                self._reproduciendo = False

    # -- Pre-cacheo de saludos (para que la fichada sea INSTANTÁNEA) --
    def precachear(self, texto):
        """Encola un saludo para GENERAR+CACHEAR en segundo plano (sin reproducir). Así la 1ª
        fichada de cada persona ya está lista en la caché -> reproducción instantánea. Solo si
        falta en la caché (no re-genera lo ya hecho)."""
        t = self._preparar(texto)
        if t and self._cache(t) is None:
            try:
                self.pq.put_nowait(t)
            except queue.Full:
                pass

    def _precachear_uno(self):
        """Genera y cachea UN saludo pendiente en el tiempo ocioso del worker (mismo loop, sin
        pisar los saludos en vivo, que tienen prioridad)."""
        if time.time() < self._cuota_hasta:      # cuota de voz agotada: no insistir hasta que vuelva
            return
        try:
            texto = self.pq.get_nowait()
        except queue.Empty:
            return
        if not texto or self._cache(texto) is not None or not self._voz_marca:
            return
        try:
            log.debug("[VOZ] pre-cacheando en segundo plano: %s", texto[:60])
            # permitir_edge=False: si se agota la cuota de Charon, NO se cachea con edge (voz mezclada).
            self._generar(texto, cachear=True, permitir_edge=False)
        except _CuotaVoz:
            # Cuota agotada: pauso el pre-cacheo ~30 min y NO pierdo el pendiente (se re-encola). El
            # roster se reenvía periódicamente, así que igual reintenta al restablecerse la cuota.
            self._cuota_hasta = time.time() + 300
            try:
                self.pq.put_nowait(texto)
            except queue.Full:
                pass
            log.info("[VOZ] cuota de la voz de marca agotada; pauso el pre-cacheo ~5 min y reintento (vuelve a Charon al restablecerse).")
        except Exception as e:  # noqa: BLE001
            log.debug("Pre-cache falló (%s): %s", texto[:30], e)

    def _preparar(self, texto):
        # Limpia markdown + pausas (compartido con la demo). La fonética (marcas/nombres en inglés)
        # se aplica solo para la voz local edge (ver _edge). MISMO punto para reproducir y pre-cachear
        # -> la clave de caché coincide (si no, el pre-cacheo no serviría).
        try:
            from comun import locucion
            # Voz de MARCA (Gemini/Charon): SIN pausas con '…' (Gemini se come la palabra que sigue al
            # '…' -> nombres cortados). Voz gratis (edge): con pausas para que no suene robótica.
            return locucion.preparar(texto, fonetica=False, pausas=not self._voz_marca)
        except Exception:  # noqa: BLE001
            return texto

    def _reproducir(self, texto, cachear):
        texto = self._preparar(texto)
        # La respuesta se sintetiza como UN audio CONTINUO (no fragmentada por oración): así suena
        # NATURAL, como una persona leyendo -> con la pronunciación y las pausas de PUNTUACIÓN propias
        # de la voz, SIN trabas ni esperas entre oraciones o párrafos. (Antes se streameaba por
        # fragmentos y, sobre todo con edge, dejaba gaps entre oraciones -> sonaba cortado/robótico.)
        ruta = self._cache(texto) if cachear else None
        if ruta is not None:
            log.debug("[VOZ] cache HIT (instantáneo): %s", texto[:60])
        else:
            if cachear:
                log.debug("[VOZ] cache MISS -> genero y guardo: %s", texto[:60])
            ruta = self._generar(texto, cachear)
        if ruta is None:
            return
        try:
            self._reproducir_archivo(ruta)           # resiliente a bloqueo de pantalla / RDP
        finally:
            if not cachear:
                try:
                    os.remove(ruta)
                except OSError:
                    pass


    async def _collect_async(self, texto):
        # Colecta el PCM completo desde voz_stream sobre self.loop (sin crear otro
        # loop -> evita el conflicto de event loop de google-genai en el worker).
        pcm = bytearray()
        async for chunk in self.ia.voz_stream(texto):
            pcm.extend(chunk)
        return bytes(pcm)

    # -- Cache / generacion a archivo --
    def _cache_path(self, texto, ext):
        # La VELOCIDAD es parte de la identidad del audio: si no, un WAV cacheado a 1.0x (build viejo)
        # se reusaría al cambiar a 1.25x y sonaría lento. Con la velocidad en la clave, cada velocidad
        # tiene su propia caché (los WAV viejos quedan huérfanos, no se reusan).
        clave = f"{self.salt}|v{self.velocidad:.2f}|{texto}"
        h = hashlib.md5(clave.encode("utf-8")).hexdigest()[:8]
        # Nombre LEGIBLE (persona + qué saludo, sacado del texto) en vez de solo un hash, para que el
        # usuario identifique cada audio en la carpeta. Incluye el MOTOR (charon = voz de marca .wav /
        # edge = respaldo gratis .mp3) para identificar de un vistazo con qué voz se generó cada saludo.
        # El hash corto al final evita colisiones (misma velocidad + texto -> mismo archivo, determinista).
        slug = re.sub(r"[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", "_", texto).strip("_")[:56] or "voz"
        motor = "charon" if ext == ".wav" else "edge"
        return os.path.join(self.cache_dir, f"{slug}__{motor}_{h}{ext}")

    def _cache(self, texto):
        for ext in (".wav", ".mp3"):
            p = self._cache_path(texto, ext)
            if os.path.exists(p) and os.path.getsize(p) > 0:
                return p
        return None

    def _tmp(self, ext):
        return os.path.join(self.cache_dir, f"_tmp_{int(time.time()*1000)}{ext}")

    def _limpiar_temporales(self):
        """Borra los audios TEMPORALES (_tmp_*) que hayan quedado de una corrida anterior. Un temporal
        (respaldo edge en vivo) se borra apenas termina de sonar (ver _reproducir), pero si el agente se
        DETIENE/mata en medio de la reproducción (os._exit del apagado, o un crash), el finally no corre y
        el archivo queda huérfano. Los temporales NUNCA deben persistir entre corridas -> los barremos al
        arrancar para que la carpeta de caché no se llene y pese de más a futuro."""
        import glob
        try:
            for f in glob.glob(os.path.join(self.cache_dir, "_tmp_*")):
                try:
                    os.remove(f)
                except OSError:
                    pass
        except Exception:  # noqa: BLE001
            pass

    def _generar(self, texto, cachear, permitir_edge=True):
        # Sin voz de marca (cliente sin Gemini) -> edge directo, sin intentar Charon en cada frase.
        if self._voz_marca:
            # Cuota de Charon en COOLDOWN (ya se sabe agotada): NO intentamos Charon (evita el 429 + su
            # backoff, que trababa la voz). En pre-cacheo avisamos para pausar; en VIVO, edge directo.
            if time.time() < self._cuota_hasta:
                if not permitir_edge:
                    raise _CuotaVoz("cuota en cooldown")
                return self._edge(texto, cachear=False)
            try:
                pcm = self.loop.run_until_complete(self._collect_async(texto))
                if pcm:
                    p = self._cache_path(texto, ".wav") if cachear else self._tmp(".wav")
                    self._pcm_a_wav(pcm, p, texto)
                    return p
            except Exception as e:  # noqa: BLE001
                if _es_error_cuota(e):
                    self._cuota_hasta = time.time() + 300   # agotada -> las próximas van directo a edge
                    # En el PRE-CACHEO no caemos a edge (dejaría un saludo con OTRA voz cacheado = voces
                    # mezcladas): avisamos para pausar y reintentar cuando vuelva la cuota (o tier pago).
                    if not permitir_edge:
                        raise _CuotaVoz(str(e))
                log.warning("Voz de marca falló (uso edge temporal): %s", e)
            # Con voz de marca activa, edge es respaldo TEMPORAL en vivo: NO se cachea, para que la
            # caché quede 100% con la voz de marca (uniforme). Al volver la marca, se cachea con Charon.
            return self._edge(texto, cachear=False)
        return self._edge(texto, cachear)

    def _pcm_a_wav(self, pcm, ruta, texto=None):
        if abs(self.velocidad - 1.0) > 0.01:
            try:
                # WSOLA (time-stretch de calidad, el MISMO del streaming): acelera SIN descartar nada.
                # ANTES se usaba pydub.speedup, que a 1.40x tiraba trozos de cada chunk y se COMÍA
                # palabras/fonemas (saludos cortados). WSOLA conserva todo el contenido. Regresión H68.
                import numpy as np
                from audiotsm import wsola
                from audiotsm.io.array import ArrayReader, ArrayWriter
                x = (np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0).reshape(1, -1)
                src_n = x.shape[1]
                # Muestras objetivo. El TTS habla el MISMO texto a ritmo VARIABLE entre generaciones
                # (a veces más rápido); un multiplicador fijo amplifica esa varianza -> un saludo suena
                # más rápido que otro. Fix (H70): NORMALIZAR a un ritmo UNIFORME (mismas letras/seg para
                # todos), acotado a ±7% de la velocidad configurada para no distorsionar. Así TODOS los
                # saludos suenan a la misma velocidad. Sin texto -> velocidad fija (compat).
                n_target = int(round(src_n / self.velocidad))
                if texto:
                    letras = sum(1 for c in texto if c.isalnum()) or 1
                    n_obj = int(round(letras / (_LETRAS_POR_SEG * self.velocidad) * 24000))
                    n_min = int(round(src_n / (self.velocidad * 1.07)))   # +7% (tope más rápido)
                    n_max = int(round(src_n / (self.velocidad * 0.93)))   # -7% (tope más lento)
                    n_target = max(n_min, min(n_max, n_obj))
                vel = src_n / max(1, n_target)          # velocidad implícita (tono ~intacto)
                writer = ArrayWriter(1)
                wsola(1, speed=vel).run(ArrayReader(x), writer)
                out_f = writer.data[0]
                # WSOLA conserva TODO el contenido (no come palabras) pero por el framing queda ~2-5%
                # corrido. Ajuste FINO: re-muestreo a la cantidad EXACTA de muestras -> duración exacta.
                if n_target > 1 and len(out_f) > 1 and abs(len(out_f) - n_target) > 1:
                    out_f = np.interp(np.linspace(0, len(out_f) - 1, n_target),
                                      np.arange(len(out_f)), out_f)
                out = (np.clip(out_f, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                with wave.open(ruta, "wb") as wv:
                    wv.setnchannels(1)
                    wv.setsampwidth(2)
                    wv.setframerate(24000)
                    wv.writeframes(out)
                log.info("[VOZ] audio a ritmo uniforme ~%.2fx (WSOLA, sin cortes) -> %s",
                         vel, os.path.basename(ruta))
                return
            except Exception as e:  # noqa: BLE001
                # Si audiotsm/numpy fallan, el audio saldría a 1.0x (LENTO): lo dejamos avisado.
                log.warning("[VOZ] NO pude acelerar a %.2fx (WSOLA: %s). Sale a 1.0x (lento).",
                            self.velocidad, e)
        with wave.open(ruta, "wb") as wv:
            wv.setnchannels(1)
            wv.setsampwidth(2)
            wv.setframerate(24000)
            wv.writeframes(pcm)

    def _edge(self, texto, cachear):
        try:
            import edge_tts
            try:                       # fonética (marcas/nombres) para la voz gratis
                from comun import locucion
                texto = locucion.pronunciacion(texto)
            except Exception:  # noqa: BLE001
                pass
            p = self._cache_path(texto, ".mp3") if cachear else self._tmp(".mp3")
            # Edge respeta la MISMA velocidad que Charon (uniforme entre voces). Edge es DETERMINISTA
            # (mismo texto -> mismo ritmo) y su `rate` conserva el tono, así que no necesita normalizar:
            # basta pasar el % de la velocidad configurada (1.20x -> "+20%").
            pct = int(round((self.velocidad - 1.0) * 100))
            rate = f"+{pct}%" if pct >= 0 else f"{pct}%"
            comm = edge_tts.Communicate(texto, "es-MX-JorgeNeural",
                                        rate=rate, pitch="-12Hz")
            self.loop.run_until_complete(comm.save(p))
            return p if os.path.exists(p) and os.path.getsize(p) > 0 else None
        except Exception as e:  # noqa: BLE001
            log.warning("edge-tts fallo: %s", e)
            return None
