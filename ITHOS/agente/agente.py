#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente ITHOS — la app LIVIANA que se instala en el equipo del cliente (parlantes/mic + control de
acceso local). Se conecta al GESTOR (el cerebro, que hosteamos) por WebSocket con su API key, detecta
EVENTOS locales (fichajes) y EJECUTA los COMANDOS que le manda el gestor (voz ITHOS). No tiene lógica
pesada: toda la inteligencia vive en el gestor. Solo sale hacia afuera (el cliente no abre puertos).

Config: agente/config.json. Integrador de acceso: ivms (el que usa INTELLIHELP).
Correr:  python agente.py            # se conecta y queda escuchando
         python agente.py --demo     # además manda un fichaje de prueba
"""

import os
import sys
import json
import time
import asyncio
import logging
import threading

import websockets

from voz import VozAgente

# Consola en UTF-8: la consola de Windows por defecto es cp1252 y NO puede mostrar los caracteres del
# banner (█╗) ni acentos → crashea con UnicodeEncodeError. Forzamos UTF-8 con reemplazo (no rompe nunca).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class _SilenciarRuido(logging.Filter):
    """Silencia warnings ruidosos e INOFENSIVOS de terceros (no ocultan errores nuestros)."""
    _RUIDO = ("non-data parts", "there are non-data parts")   # google-genai con Charon (audio + 'thought')

    def filter(self, record):
        try:
            return not any(r in record.getMessage() for r in self._RUIDO)
        except Exception:  # noqa: BLE001
            return True


def _instalar_filtro_ruido(handler):
    handler.addFilter(_SilenciarRuido())


for _h in logging.getLogger().handlers:      # filtra el ruido en la salida por consola
    _instalar_filtro_ruido(_h)

BASE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("agente")


def _dir_datos():
    """Carpeta PERSISTENTE y ESCRIBIBLE del agente (config + caché de voz). En el .exe instalado NO
    puede ser la del ejecutable: Program Files es de solo lectura y en onefile `__file__` es una carpeta
    TEMPORAL que se borra al salir. Por eso, cuando está congelado (o `ITHOS_AGENTE_DATOS`), va a la
    carpeta de datos del USUARIO (multiplataforma). Se borra ENTERA al desinstalar → no deja rastro."""
    forzado = os.environ.get("ITHOS_AGENTE_DATOS")
    if forzado:
        d = forzado
    elif getattr(sys, "frozen", False):
        if os.name == "nt":
            raiz = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        elif sys.platform == "darwin":
            raiz = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
        else:
            raiz = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        d = os.path.join(raiz, "ITHOS")
    else:
        d = BASE                             # en desarrollo: agente/ (config.json local)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _dir_cache_voz():
    return os.path.join(_dir_datos(), "voz_cache")


def cargar_config():
    with open(_config_path(), "r", encoding="utf-8") as f:
        return json.load(f)


# ── Agente en 2do plano (headless) desacoplado de la ventana ──────────────────
# La app (GUI) lanza el agente como proceso `--run` DESACOPLADO: sigue vivo aunque cierres la ventana
# (el portero no puede parar). Singleton: 1 solo agente por PC (el lock es el PID vivo).
def _pid_file():
    return os.path.join(_dir_datos(), "agente.pid")


def _log_file():
    return os.path.join(_dir_datos(), "agente.log")


def _estado_file():
    return os.path.join(_dir_datos(), "estado.json")


def _escribir_estado_local(datos):
    """El agente headless deja su SALUD en un archivo que la GUI lee (conectado/micrófono/integrador/
    voz). Así la app muestra si todo arrancó bien sin depender del gestor."""
    import json as _json
    try:
        with open(_estado_file(), "w", encoding="utf-8") as f:
            _json.dump(datos, f)
    except Exception:  # noqa: BLE001
        pass


def _leer_pid():
    try:
        return int(open(_pid_file(), encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return 0


def _pid_vivo(pid):
    if not pid or int(pid) <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except Exception:  # noqa: BLE001
        return False


def agente_corriendo():
    """PID del agente headless si está vivo, o 0 (para la GUI: saber si el portero está en marcha)."""
    pid = _leer_pid()
    return pid if (pid and pid != os.getpid() and _pid_vivo(pid)) else 0


def _escribir_pid(pid):
    try:
        with open(_pid_file(), "w", encoding="utf-8") as f:
            f.write(str(pid))
    except OSError:
        pass


def _vigilar_apagado():
    """Apagado COOPERATIVO a prueba de PRIVILEGIOS. El headless (portero) puede correr ELEVADO (tarea
    ONLOGON /RL HIGHEST), y la GUI suele correr SIN elevar -> la GUI NO puede matarlo directamente
    (acceso denegado) y quedaba corriendo/conectado. Solución: el propio agente VIGILA su pid file; si la
    GUI lo BORRA (o lo toma otro pid), el agente se AUTO-TERMINA. Así 'Detener' SIEMPRE frena el proceso,
    sin importar el nivel de privilegios. Corre en un hilo daemon (chequeo liviano cada 2s). Bug H72."""
    mi_pid = os.getpid()
    fallos = 0
    while True:
        time.sleep(2)
        if _leer_pid() != mi_pid:          # pid file borrado (detener) o tomado por otro agente
            fallos += 1
            if fallos >= 2:                # 2 lecturas seguidas distintas -> real (no un glitch de lectura)
                log.info("Pedido de detención (pid file borrado/cambiado): el agente se cierra.")
                os._exit(0)
        else:
            fallos = 0                     # volvió a coincidir -> era transitorio


_lock_unico = None      # se mantiene vivo por la vida del proceso (no cerrar)


def adquirir_lock_unico():
    """Lock ATÓMICO de instancia única: 1 agente por PC, SIN la carrera del PID file (dos --run que
    arranquen a la vez no pueden tomarlo los dos). Windows: mutex nombrado. Unix: flock. Devuelve
    True si ESTE proceso tomó el lock (puede correr); False si ya hay otro agente."""
    global _lock_unico
    try:
        if os.name == "nt":
            import ctypes
            # use_last_error=True: ctypes guarda el last-error JUSTO tras CreateMutexW, así
            # ctypes.get_last_error() es FIABLE. (ctypes.windll...GetLastError() suelto podía leer un
            # valor pisado por la búsqueda del símbolo -> falso "ya existe" -> el agente salía y no
            # arrancaba nunca, quedando la GUI en 'Conectando…'. Bug operacional H71.)
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _lock_unico = k32.CreateMutexW(None, False, "ITHOS_Agente_Unico")
            return ctypes.get_last_error() != 183                    # 183 = ERROR_ALREADY_EXISTS
        import fcntl
        _lock_unico = open(os.path.join(_dir_datos(), "agente.lock"), "w", encoding="utf-8")
        fcntl.flock(_lock_unico, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except Exception:  # noqa: BLE001
        return False                                                 # ya tomado -> otro agente corre


def lanzar_headless():
    """Arranca el agente en 2do plano (proceso `--run` DESACOPLADO). No muere al cerrar la ventana."""
    import subprocess
    if agente_corriendo():
        return True
    args = [sys.executable, "--run"] if getattr(sys, "frozen", False) \
        else [sys.executable, os.path.join(BASE, "agente.py"), "--run"]
    # CLAVE (onefile): el hijo NO debe heredar las variables del bootloader de PyInstaller
    # (_MEIPASS2 / _PYI_*), o usaría el MISMO bundle temporal del padre y se caería cuando el padre
    # (la GUI) cierre y borre ese _MEI. Limpiándolas, el hijo extrae su PROPIO bundle → independiente.
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("_MEI") or k.startswith("_PYI"))}
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True, "env": env}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)
    return True


def detener_headless():
    """Frena el agente en 2do plano de forma ROBUSTA y a prueba de PRIVILEGIOS:
      1) BORRA el pid file -> el agente VIGILA su pid (ver _vigilar_apagado) y se AUTO-TERMINA aunque
         corra elevado y la GUI no pueda matarlo directamente (garantía cross-privilegios).
      2) Además intenta matarlo YA (rápido) si hay permiso, con os.kill (portable: Windows/Unix)."""
    import signal
    pid = _leer_pid()
    try:
        os.remove(_pid_file())               # 1) señal COOPERATIVA (cross-privilegios): se auto-frena en ~4s
    except OSError:
        pass
    # 2) intento directo INSTANTÁNEO si hay permiso (mismo nivel). os.kill es PORTABLE: en Windows hace
    #    TerminateProcess, en Unix manda SIGTERM. El agente no lanza subprocesos (portero/voz/mic/integrador
    #    son HILOS del proceso principal), así que matar el proceso corta la conexión y todo. Si NO hay
    #    permiso (headless elevado, GUI sin elevar), el borrado del pid (paso 1) lo frena igual.
    if pid and _pid_vivo(pid):
        try:
            os.kill(int(pid), getattr(signal, "SIGTERM", 15))
        except Exception:  # noqa: BLE001
            pass


def leer_log(maxlineas=200):
    """Últimas `maxlineas` del log del agente headless (para la GUI). Lee SOLO el FINAL del archivo (no
    lo carga entero) para no lagear ni consumir recursos aunque el .log tenga historia. La GUI muestra
    únicamente lo reciente; el histórico completo queda en el archivo (rotado)."""
    try:
        ruta = _log_file()
        tam = os.path.getsize(ruta)
        leer = min(tam, 96 * 1024)                    # solo los últimos ~96KB (sobra para 200 líneas)
        with open(ruta, "rb") as f:
            f.seek(tam - leer)
            data = f.read().decode("utf-8", errors="replace")
        return data.splitlines(keepends=True)[-maxlineas:]
    except OSError:
        return []


def _lanzar_gui():
    """Abre la ventana de configuración (proceso GUI separado). El agente sigue corriendo aparte."""
    import subprocess
    args = [sys.executable] if getattr(sys, "frozen", False) \
        else [sys.executable, os.path.join(BASE, "agente.py")]
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("_MEI") or k.startswith("_PYI"))}
    kw = {"close_fds": True, "env": env}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)


class Agente:
    def __init__(self, cfg):
        self.cfg = cfg
        self._cfg_srv = {}               # config que MANDA el gestor (thin agent): voz+integrador+mic
        self._stop_integ = None          # Event para FRENAR integrador+micrófono al reconectar (sin duplicar)
        self.voz = None                  # se crea con la config del gestor al autenticar
        # Compat: si la config LOCAL ya trae la voz (la demo arma la config completa), se crea acá.
        _voz_local = (cfg.get("ia") or {}).get("voz")
        if _voz_local:
            self.voz = VozAgente(_voz_local, velocidad=cfg.get("velocidad", 1.25),
                                 cache_dir=_dir_cache_voz())
        self._saludo_hecho = False       # consulta de arranque (demo): se manda una sola vez

    def _asegurar_voz(self, srv):
        """Crea la voz con lo que MANDA el gestor (la key de Charon del cliente) si no existe aún."""
        if self.voz is None:
            vc = srv.get("voz") or (self.cfg.get("ia") or {}).get("voz") or {}
            self.voz = VozAgente(vc, velocidad=srv.get("velocidad", self.cfg.get("velocidad", 1.25)),
                                 cache_dir=_dir_cache_voz())

    def ejecutar(self, cmd):
        if self.voz is None:
            log.warning("[CMD] llegó '%s' pero la voz NO está inicializada (sin key/parlantes).",
                        cmd.get("accion"))
            return
        if cmd.get("accion") == "decir":
            if cmd.get("solo_cachear"):          # pre-cacheo: genera y guarda, NO reproduce
                self.voz.precachear(cmd.get("texto", ""))
            else:
                # Traza el camino fichada -> gestor -> comando -> voz (para diagnosticar audio/RDP).
                log.info("[CMD] DECIR (del gestor): %s", (cmd.get("texto", "") or "")[:70])
                self.voz.decir(cmd.get("texto", ""), cachear=cmd.get("cachear", True))
        else:
            log.warning("Comando desconocido: %s", cmd)

    def _arrancar_integrador(self, ws, loop):
        """Arranca el integrador de acceso local (según config) en un hilo. Cada
        evento se manda al central por el WebSocket."""
        # El integrador y el micrófono los MANDA el gestor (thin agent); con fallback a la config local.
        # Al RECONECTAR (cambio en el gestor / 1012 service restart), FRENAR el integrador y el micrófono
        # ANTERIORES antes de arrancar los nuevos: si no, quedan HILOS DUPLICADOS peleando por el mismo
        # micrófono/DB y el mic deja de detectar (bug real: había que cerrar y reabrir el agente). H73b.
        if self._stop_integ is not None:
            self._stop_integ.set()
        self._stop_integ = threading.Event()
        self._integrador_ok = False
        self._integrador_tipo = ""
        self._microfono_ok = False
        _mic0 = self._cfg_srv.get("microfono") or self.cfg.get("microfono") or {}
        self._microfono_cfg = bool(_mic0.get("enabled"))   # ¿el cliente USA micrófono? (para el estado)
        integ = self._cfg_srv.get("integrador") or self.cfg.get("integrador")
        if not integ or not integ.get("tipo"):
            return
        tipo = integ["tipo"].lower()
        self._integrador_tipo = tipo

        def enviar_evento(ev):
            asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps({"tipo": "evento", **ev})), loop)

        # Un integrador nuevo (HikCentral, BioStar 2, ZKTeco, Honeywell…) es un módulo con la misma
        # interfaz que integrador_ivms: se agrega acá y el resto del agente no cambia.
        try:
            if tipo == "ivms":
                import integrador_ivms as mod
            else:
                log.warning("Integrador desconocido: %s", tipo)
                return
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo cargar el integrador %s: %s", tipo, e)
            return
        threading.Thread(target=mod.vigilar, args=(integ, enviar_evento),
                         kwargs={"stop": self._stop_integ},
                         name=f"integrador-{tipo}", daemon=True).start()
        self._integrador_ok = True
        log.info("Integrador de acceso '%s' arrancado.", tipo)
        # Escucha por palabra clave "ITHOS" (micrófono central), si está habilitada.
        mic = self._cfg_srv.get("microfono") or self.cfg.get("microfono")
        if mic and mic.get("enabled"):
            try:
                import escucha
                threading.Thread(target=escucha.vigilar, args=(mic, enviar_evento),
                                 kwargs={"stop": self._stop_integ},
                                 name="escucha", daemon=True).start()
                self._microfono_ok = True
            except Exception as e:  # noqa: BLE001
                log.error("No se pudo iniciar la escucha por voz: %s", e)

    async def _sesion(self, demo=False):
        async with websockets.connect(self.cfg["central_url"], ping_interval=20,
                                      ping_timeout=20, max_queue=32) as ws:
            from comun import version as VER
            await ws.send(json.dumps({"tipo": "auth", "api_key": self.cfg["api_key"],
                                      "agente_token": self.cfg.get("agente_token", ""),
                                      "agente_version": VER.AGENTE_VERSION,
                                      "protocol_version": VER.PROTOCOL_VERSION}))
            resp = json.loads(await ws.recv())
            if resp.get("tipo") != "auth_ok":
                log.error("Auth falló: %s", resp)
                return False
            g_ver = resp.get("gestor_version", "?")
            self._gestor_version = g_ver            # para mostrar la versión del Gestor en la GUI
            self._empresa_nombre = resp.get("cliente", "")
            log.info("Conectado al GESTOR v%s como '%s' (agente v%s)",
                     g_ver, resp.get("cliente"), VER.AGENTE_VERSION)
            # ¿El gestor pide un agente más nuevo que el nuestro? -> avisar (el auto-update es fase 2).
            if VER._tupla(VER.AGENTE_VERSION) < VER._tupla(resp.get("agente_min_version") or "0"):
                log.warning("Hay una versión más nueva del AGENTE disponible (mínima que pide el "
                            "gestor: %s). Conviene actualizar.", resp.get("agente_min_version"))
            # El gestor MANDA la config de la empresa (voz Charon + integrador + micrófono): el agente
            # solo guardó api_key + contraseña; el resto lo asigna el gestor.
            self._cfg_srv = resp.get("config") or {}
            self._asegurar_voz(self._cfg_srv)
            loop = asyncio.get_running_loop()
            self._arrancar_integrador(ws, loop)

            # Reporte de SALUD al gestor (para el dashboard: en producción todo debe estar 100% activo).
            async def _reportar_estado():
                # Micrófono/integrador arrancan en hilos; damos unos segundos y reportamos, luego cada 30s.
                await asyncio.sleep(6)
                while True:
                    salud = {"microfono": bool(getattr(self, "_microfono_ok", False)),
                             "mic_habilitado": bool(getattr(self, "_microfono_cfg", False)),
                             "integrador": bool(getattr(self, "_integrador_ok", False)),
                             "integrador_tipo": getattr(self, "_integrador_tipo", ""),
                             "voz": bool(getattr(self, "voz", None))}
                    _escribir_estado_local({**salud, "conectado": True, "ts": int(time.time()),
                                            "gestor_version": getattr(self, "_gestor_version", ""),
                                            "empresa": getattr(self, "_empresa_nombre", "")})
                    try:
                        await ws.send(json.dumps({"tipo": "evento", "evento": "estado_agente",
                                                  "datos": salud}))
                    except Exception:  # noqa: BLE001
                        return
                    await asyncio.sleep(30)
            tarea_estado = asyncio.create_task(_reportar_estado())
            if demo:
                await ws.send(json.dumps({"tipo": "evento", "evento": "acceso",
                                          "datos": {"nombre": "Brian Sierra",
                                                    "tipo": "bienvenida"}}))
            # Consulta de arranque REAL (opcional, la usa la demo): ITHOS responde con datos
            # reales y queda registrada como consulta. Solo una vez (no en cada reconexión).
            saludo = os.environ.get("ITHOS_AGENTE_CONSULTA_INICIO")
            if saludo and not self._saludo_hecho:
                self._saludo_hecho = True
                await ws.send(json.dumps({"tipo": "evento", "evento": "consulta_voz",
                                          "datos": {"texto": saludo}}))
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("tipo") == "comando":
                        self.ejecutar(msg)
            finally:
                tarea_estado.cancel()
        return True

    async def correr(self, demo=False):
        """Se conecta y se RECONECTA solo al GESTOR (backoff exponencial + JITTER) si se cae, sin
        quedar colgado ni duplicar procesos. El jitter evita que TODOS los agentes reconecten a la
        vez tras una caída (thundering herd)."""
        import random
        espera = 2
        while True:
            try:
                await self._sesion(demo=demo)
                espera = 2                       # reconexión limpia -> reset backoff
            except (OSError, websockets.WebSocketException) as e:
                log.warning("Conexión con el gestor perdida (%s). Reintento en ~%ss...", e, espera)
            except Exception as e:  # noqa: BLE001
                log.warning("Error de sesión: %s. Reintento en ~%ss...", e, espera)
            if demo:
                return                            # el modo demo es una sola pasada
            # backoff con JITTER (±30%): con conexión mínima reconecta enseguida; sin ella, espera
            # progresivamente hasta 30s, repartido para no golpear todos juntos al volver la red.
            await asyncio.sleep(max(0.5, espera * (0.7 + random.random() * 0.6)))
            espera = min(espera * 2, 30)          # tope 30s


# ─────────────────────────────────────────────────────────────────────────────
#  MENÚ del agente (instalar / configurar / estado / desinstalar-mover a otra PC)
#  Mismo .exe para todas las empresas: identifica por api_key + contraseña de agente
#  (las asigna el GESTOR en el alta). El resto de la config la manda el gestor.
# ─────────────────────────────────────────────────────────────────────────────
CENTRAL_URL_DEFECTO = "wss://ithos.intellihelp.tech/ws"


def _config_path():
    return os.environ.get("ITHOS_AGENTE_CONFIG") or os.path.join(_dir_datos(), "config.json")


def _leer_cfg():
    try:
        with open(_config_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _guardar_cfg(cfg):
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# Estilo de consola coherente con la app (ANSI; se desactiva solo si la terminal no lo soporta).
_CY, _GR, _VE, _RO, _AM, _RS, _NE = (
    "\033[38;5;44m", "\033[38;5;245m", "\033[38;5;42m",
    "\033[38;5;203m", "\033[38;5;220m", "\033[0m", "\033[1m")


def _color_ok():
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(txt, col):
    return (col + txt + _RS) if _color_ok() else txt


def _banner():
    os.system("cls" if os.name == "nt" else "clear")
    logo = ["  ██╗████████╗██╗  ██╗ ██████╗ ███████╗",
            "  ██║╚══██╔══╝██║  ██║██╔═══██╗██╔════╝",
            "  ██║   ██║   ███████║██║   ██║███████╗",
            "  ██║   ██║   ██╔══██║██║   ██║╚════██║",
            "  ██║   ██║   ██║  ██║╚██████╔╝███████║",
            "  ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝"]
    print()
    for ln in logo:
        print(_c(ln, _CY))
    print(_c("     Agente · asistente de acceso por voz", _GR))
    print(_c("     INTELLIHELP S.A.", _GR))
    print()


def _mask(s):
    s = str(s or "")
    return (s[:4] + "…" + s[-4:]) if len(s) > 10 else ("•" * len(s))


def _estado_linea():
    cfg = _leer_cfg()
    if cfg.get("api_key") and cfg.get("agente_token"):
        print(_c("  ● Configurado", _VE) + _c(
            f"   empresa/api_key: {_mask(cfg['api_key'])}   contraseña: {_mask(cfg['agente_token'])}", _GR))
        print(_c(f"     Gestor: {cfg.get('central_url', CENTRAL_URL_DEFECTO)}", _GR))
    else:
        print(_c("  ○ Sin configurar", _AM) + _c("   (opción 1 para conectar este equipo a una empresa)", _GR))
    print()


def _pedir(label, actual=""):
    extra = _c(f" [{_mask(actual)}]", _GR) if actual else ""
    v = input(_c(f"  {label}{extra}: ", _NE)).strip()
    return v or actual


def _configurar():
    _banner()
    print(_c("  CONFIGURAR / CONECTAR ESTE EQUIPO A UNA EMPRESA", _NE))
    print(_c("  Pegá la api_key y la contraseña de agente que te dio INTELLIHELP en el alta.", _GR))
    print()
    cfg = _leer_cfg()
    api_key = _pedir("API key de la empresa", cfg.get("api_key", ""))
    token = _pedir("Contraseña de agente", cfg.get("agente_token", ""))
    url = _pedir("Gestor (Enter = por defecto)", cfg.get("central_url", CENTRAL_URL_DEFECTO))
    if not api_key or not token:
        print(_c("\n  Falta la api_key o la contraseña. No se guardó nada.", _RO))
        input(_c("\n  Enter para volver…", _GR))
        return
    _guardar_cfg({"central_url": url or CENTRAL_URL_DEFECTO, "api_key": api_key, "agente_token": token})
    print(_c("\n  ✓ Guardado. Probando conexión con el Gestor…", _VE))
    ok = False
    try:
        ok = asyncio.run(_probar_conexion({"central_url": url or CENTRAL_URL_DEFECTO,
                                           "api_key": api_key, "agente_token": token}))
    except Exception as e:  # noqa: BLE001
        print(_c(f"  No se pudo probar ahora: {e}", _AM))
    if ok:
        print(_c("  ✓ Autenticado correctamente. Ya podés arrancar el agente (opción 2).", _VE))
    input(_c("\n  Enter para volver…", _GR))


async def _probar_conexion(cfg):
    """Handshake corto: conecta, autentica y corta. True si el Gestor aceptó api_key + contraseña."""
    from comun import version as VER
    async with websockets.connect(cfg["central_url"], ping_interval=None,
                                  open_timeout=12, close_timeout=3) as ws:
        await ws.send(json.dumps({"tipo": "auth", "api_key": cfg["api_key"],
                                  "agente_token": cfg.get("agente_token", ""),
                                  "test": True,     # PRUEBA: el gestor valida y corta, NO toca al agente real
                                  "agente_version": VER.AGENTE_VERSION,
                                  "protocol_version": VER.PROTOCOL_VERSION}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
        if resp.get("tipo") == "auth_ok":
            return True
        print(_c(f"  Rechazado por el Gestor: {resp.get('motivo', resp)}", _RO))
        return False


def _quitar_autoarranque():
    """Quita el arranque automático del SO (best-effort, multiplataforma)."""
    import subprocess
    try:
        if os.name == "nt":
            subprocess.run(["schtasks", "/Delete", "/TN", "ITHOS Agente", "/F"],
                           capture_output=True, check=False)
        elif sys.platform == "darwin":
            plist = os.path.expanduser("~/Library/LaunchAgents/com.ithos.agente.plist")
            subprocess.run(["launchctl", "unload", plist], capture_output=True, check=False)
            if os.path.exists(plist):
                os.remove(plist)
        else:
            subprocess.run(["systemctl", "--user", "disable", "--now", "ithos-agente"],
                           capture_output=True, check=False)
            subprocess.run(["systemctl", "disable", "--now", "ithos-agente"],
                           capture_output=True, check=False)
    except Exception:  # noqa: BLE001
        pass


def _borrar_datos():
    """Borra SOLO lo del AGENTE en esta PC: su config (credenciales) + su caché de voz. No deja rastro.

    CRÍTICO (seguridad): NO toca NADA del cliente. No borra tickets de GLPI (viven en el servidor del
    cliente; el agente solo consulta por API), ni la base de fichadas (IVMS/SQL Server, que el agente
    solo LEE), ni el trabajo hecho (tickets triageados/respondidos quedan intactos). Solo archivos
    locales del ejecutable. En desarrollo NO toca la carpeta del proyecto (solo config.json + voz_cache)."""
    import shutil
    forzado = os.environ.get("ITHOS_AGENTE_CONFIG")
    if forzado:                                  # dev/demo con config alternativa: borra solo ese archivo
        try:
            os.remove(forzado)
        except OSError:
            pass
        return
    d = _dir_datos()
    if getattr(sys, "frozen", False) or os.environ.get("ITHOS_AGENTE_DATOS"):
        shutil.rmtree(d, ignore_errors=True)     # instalado: la carpeta es solo del agente -> entera
    else:                                        # desarrollo: solo los archivos del agente
        for p in (os.path.join(d, "config.json"), os.path.join(d, "voz_cache")):
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def _desinstalar():
    _banner()
    print(_c("  DESINSTALAR / MOVER A OTRA PC", _NE))
    print(_c("  Borra la configuración (api_key + contraseña) de ESTE equipo y quita el arranque", _GR))
    print(_c("  automático. Después podés instalar el agente en otra PC con el MISMO ejecutable.", _GR))
    print(_c("  (No borra nada en el Gestor: la empresa sigue dada de alta.)", _GR))
    print()
    r = input(_c("  Escribí ELIMINAR para confirmar: ", _AM)).strip()
    if r != "ELIMINAR":
        print(_c("  Cancelado. No se tocó nada.", _GR))
        input(_c("\n  Enter para volver…", _GR))
        return
    _quitar_autoarranque()
    _borrar_datos()          # borra config + caché: no deja rastro en la PC
    print(_c("\n  ✓ Listo. Este equipo quedó limpio. Instalá el agente en la otra PC y usá la", _VE))
    print(_c("    opción 1 con la misma api_key + contraseña.", _VE))
    input(_c("\n  Enter para volver…", _GR))


def _arrancar():
    cfg = _leer_cfg()
    if not cfg.get("api_key") or not cfg.get("agente_token"):
        _banner()
        print(_c("  Primero configurá el equipo (opción 1).", _AM))
        input(_c("\n  Enter para volver…", _GR))
        return
    cfg.setdefault("central_url", CENTRAL_URL_DEFECTO)
    _banner()
    print(_c("  ▶ Agente en marcha. Ctrl+C para volver al menú.", _VE))
    print()
    ag = Agente(cfg)
    try:
        asyncio.run(ag.correr(demo=False))
    except KeyboardInterrupt:
        pass


def menu():
    while True:
        _banner()
        _estado_linea()
        print(_c("  1) ", _CY) + "Configurar / conectar este equipo a una empresa")
        print(_c("  2) ", _CY) + "Arrancar el agente ahora")
        print(_c("  3) ", _CY) + "Desinstalar / mover a otra PC")
        print(_c("  4) ", _CY) + "Salir")
        print()
        op = input(_c("  Opción: ", _NE)).strip()
        if op == "1":
            _configurar()
        elif op == "2":
            _arrancar()
        elif op == "3":
            _desinstalar()
        elif op in ("4", "s", "S", "q", "Q", ""):
            print(_c("  Hasta luego.", _GR))
            return


def main():
    # Modos de arranque:
    #   · (sin args)  -> APLICACIÓN con interfaz (GUI ITHOS). Si no hay entorno gráfico -> menú de
    #                    consola (server Linux headless); si está configurado y es headless -> corre.
    #   · --run       -> corre el agente HEADLESS (lo usa la tarea/servicio 24/7). Nunca abre ventana.
    #   · --menu      -> menú de consola (fallback por SSH/sin GUI).
    #   · --demo      -> una pasada de prueba (lo usa la demo).
    cfg = _leer_cfg()
    configurado = bool(cfg.get("api_key") and cfg.get("agente_token"))
    headless = "--run" in sys.argv or "--demo" in sys.argv
    interactivo = sys.stdin is not None and sys.stdin.isatty()

    if not headless:
        # App de escritorio (misma UI/UX que ITHOS). Si no se puede, cae al menú de consola.
        if "--menu" not in sys.argv:
            try:
                import gui
                if gui.disponible():
                    gui.lanzar()
                    return
            except Exception as e:  # noqa: BLE001
                log.warning("No se pudo abrir la app gráfica (%s). Uso el menú de consola.", e)
        if interactivo:
            menu()
            return
        # Sin GUI y sin terminal: si está configurado, corré; si no, avisá (no bloquear en input()).
        if not configurado:
            log.error("Agente sin configurar. Abrí 'ITHOS Agente' para conectarlo.")
            return
    if not cfg.get("api_key") and "--demo" not in sys.argv:
        log.error("Agente sin configurar. Abrí 'ITHOS Agente' para conectarlo.")
        return
    # Modo servicio (--run): SINGLETON (1 agente por PC) + PID + log a archivo (la GUI lo lee). Si ya
    # hay uno vivo (p. ej. la tarea de arranque), este sale sin duplicar.
    if "--run" in sys.argv:
        if not adquirir_lock_unico():        # SINGLETON atómico: 1 agente por PC (sin carrera de PID)
            # El lock puede estar EN TRANSICIÓN (el agente anterior recién se cerró y el SO todavía no
            # liberó el mutex) o COLGADO. Reintentamos unos segundos; y solo salimos si hay OTRO agente
            # REALMENTE vivo (PID). Si el lock quedó colgado sin agente, arrancamos igual: es mejor
            # arrancar que quedar mudo con la GUI en 'Conectando…'. El PID es el singleton de respaldo.
            tomado = False
            for _ in range(15):              # ~3s de gracia para que el SO suelte el mutex del anterior
                time.sleep(0.2)
                if adquirir_lock_unico():
                    tomado = True
                    break
            if not tomado and agente_corriendo():
                log.info("Ya hay un agente en marcha (pid %s). Salgo (singleton).", agente_corriendo())
                return
            if not tomado:
                log.warning("Lock singleton colgado sin agente vivo; arranco igual (respaldo por PID).")
        _escribir_pid(os.getpid())           # el pid file queda para que la GUI sepa estado / detenga
        # Vigila el pid file: si la GUI lo borra (Detener), el agente se AUTO-TERMINA aunque corra
        # elevado y la GUI no pueda matarlo (apagado cooperativo a prueba de privilegios). Ver H72.
        threading.Thread(target=_vigilar_apagado, name="apagado", daemon=True).start()
        try:
            from logging.handlers import RotatingFileHandler
            # Log ROTADO: el archivo NUNCA crece sin control (evita lag/consumo del agente al leerlo). El
            # activo (.log) queda chico y el histórico va a .log.1/.log.2 (se conserva, no se pierde nada).
            fh = RotatingFileHandler(_log_file(), maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
            _instalar_filtro_ruido(fh)
            logging.getLogger().addHandler(fh)
        except Exception:  # noqa: BLE001
            pass
        import atexit
        atexit.register(lambda: os.remove(_pid_file()) if os.path.exists(_pid_file()) else None)
        # Icono de BANDEJA (system tray, estilo AMD/Discord): mientras corre, se ve el icono ITHOS ->
        # sabés que está en marcha y no lo duplicás. Menú: abrir config / detener y salir. Si no hay
        # escritorio (server Linux), no se muestra y el agente sigue igual.
        def _detener_y_salir():
            # Borra el pid file -> cualquier OTRA instancia (duplicado del singleton viejo) que vigile
            # su pid se auto-frena; y este proceso (el del tray) sale ya.
            try:
                os.remove(_pid_file())
            except OSError:
                pass
            os._exit(0)
        try:
            import bandeja
            bandeja.iniciar(al_abrir=_lanzar_gui, al_detener=_detener_y_salir)
        except Exception:  # noqa: BLE001
            pass
    # Evita que el equipo se SUSPENDA: el agente (portero/voz/mic) tiene que seguir corriendo
    # aunque se bloquee la pantalla o el sistema quiera dormir. Best-effort, multiplataforma.
    try:
        sys.path.insert(0, os.path.join(BASE, ".."))
        from comun.despierto import mantener_despierto
        mantener_despierto()
    except Exception:  # noqa: BLE001
        pass
    ag = Agente(cargar_config())
    try:
        asyncio.run(ag.correr(demo="--demo" in sys.argv))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
