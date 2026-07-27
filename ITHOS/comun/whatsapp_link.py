"""Vinculación de WhatsApp NO-OFICIAL por QR (server-side: corre en el GESTOR).

El cliente vincula SU WhatsApp escaneando un QR desde el panel o el alta, sin tocar la terminal:

    1) POST vincular(sesion)  -> arranca neonize para ESA sesión y captura el QR (imagen)
    2) GET  estado(sesion)    -> {estado, qr(dataURI PNG), expira_en, numero}
    3) el cliente escanea con su teléfono  (WhatsApp > Dispositivos vinculados > Vincular)
    4) estado -> 'vinculado'  (neonize deja la sesión guardada en wa_<sesion>.sqlite3)
    5) el runtime (comun/whatsapp.py) REUSA ese MISMO archivo -> ya puede enviar/responder

Multi-tenant: cada cliente tiene SU sesión (un archivo sqlite distinto), nunca se cruzan.
La vinculación CADUCA sola por timeout si nadie escanea: no deja procesos ni QR colgados.
Al vincularse, el cliente de vinculación SE SUELTA (disconnect) para que el runtime pueda tomar
la sesión sin pelearse por el mismo archivo (dos clientes de whatsmeow sobre el mismo sqlite se
expulsan). El emparejamiento (device + llaves) ya quedó persistido en el sqlite al escanear.

Seguridad: este módulo NO expone nada por sí solo; el panel (con auth de admin o token de alta)
es el único que llama a estas funciones. El id de sesión es opaco y aleatorio por cliente.
"""
from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger("ithos.whatsapp_link")

# Un QR de WhatsApp Web rota cada ~20 s; neonize vuelve a llamar al callback en cada rotación, así que
# el QR mostrado se refresca solo. Si NADIE escanea en este tiempo, se cancela la vinculación.
TIMEOUT_VINCULAR = 180          # 3 min sin escanear -> 'expirado' (no deja el cliente colgado)
GRACIA_TRAS_VINCULAR = 6        # tras emparejar, deja asentar y suelta la sesión para el runtime

_lock = threading.Lock()
_sesiones: dict[str, "_Vinculacion"] = {}


def sesion_de_cliente(conf: dict) -> str:
    """Id de sesión ESTABLE de un cliente (multi-tenant). Única fuente de verdad para el runtime
    (comun/whatsapp.py, vía main.py) y para la vinculación por QR (panel/alta): si no coinciden, lo
    vinculado no sirve para enviar. Usa el `wa_session` del cliente (lo fija el frontend al vincular
    en el alta, antes de que exista la api_key); si no hay, lo deriva de la api_key/nombre."""
    sid = conf.get("wa_session")
    if sid:
        return str(sid)
    import hashlib
    seed = str(conf.get("api_key") or conf.get("nombre") or "")
    return "k" + hashlib.sha1(seed.encode()).hexdigest()[:12]


def archivo_sesion(sesion_id: str) -> str:
    """Nombre de archivo sqlite ESTABLE y saneado para una sesión (por cliente).
    El runtime (comun/whatsapp.crear_whatsapp con cfg['session']) usa EXACTAMENTE este nombre,
    así lo vinculado acá sirve para enviar. No inventar otro nombre en otro lado."""
    s = "".join(ch for ch in str(sesion_id or "") if ch.isalnum() or ch in "-_")[:48] or "default"
    return f"wa_{s}.sqlite3"


def _ruta_sqlite(sesion_id: str) -> str:
    from comun import whatsapp as WA
    return WA._ruta_sesion(archivo_sesion(sesion_id))


def _ruta_marca(sesion_id: str) -> str:
    """Marcador PERSISTENTE de 'ya vinculado' (sobrevive reinicios del central y sirve para
    reportar el estado sin abrir un cliente neonize en cada consulta)."""
    return _ruta_sqlite(sesion_id) + ".vinculado.json"


def _leer_json(ruta: str) -> dict:
    import json
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _escribir_marca(ruta_marca: str, *, vinculado: bool, numero: str = "", caducada: bool = False):
    import json
    try:
        with open(ruta_marca, "w", encoding="utf-8") as f:
            json.dump({"vinculado": vinculado, "caducada": caducada,
                       "numero": numero, "ts": int(time.time())}, f)
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo guardar la marca de vinculación: %s", e)


def _leer_marca(sesion_id: str) -> dict:
    return _leer_json(_ruta_marca(sesion_id))


def _guardar_marca(sesion_id: str, numero: str) -> None:
    _escribir_marca(_ruta_marca(sesion_id), vinculado=True, numero=numero)


def _ya_vinculado(sesion_id: str) -> bool:
    """Verdad persistida: hay marca de vinculado Y el sqlite de la sesión existe."""
    return bool(_leer_marca(sesion_id).get("vinculado")) and os.path.exists(_ruta_sqlite(sesion_id))


# --- marca por RUTA de sesión (la usa el RUNTIME de comun/whatsapp.py) --------------------------
# El runtime conoce su ARCHIVO de sesión, no el id opaco. Estas helpers actualizan la MISMA marca
# ('<sqlite>.vinculado.json') para que el estado del panel sea siempre la verdad: al conectar la deja
# 'vinculado'; al cerrarse la sesión (WhatsApp la caduca por inactividad / se desvincula desde el
# teléfono) la deja 'caducada' -> el panel muestra "sesión caducada" + botón "Volver a vincular".
def _marca_de_ruta(session_path: str) -> str:
    return f"{session_path}.vinculado.json"


def marcar_vinculado_ruta(session_path: str, numero: str = "") -> None:
    # No pisar con vacío el número que ya guardó la vinculación por QR (el runtime marca al conectar,
    # cuando todavía no resolvió su propio número).
    prev = _leer_json(_marca_de_ruta(session_path))
    _escribir_marca(_marca_de_ruta(session_path), vinculado=True,
                    numero=numero or prev.get("numero", ""))


def marcar_caducado_ruta(session_path: str, numero: str = "") -> None:
    """La sesión se cerró/caducó: la marca queda 'caducada' (no se borra el sqlite: el cliente
    re-vincula desde el panel y whatsmeow reusa lo que pueda / pide QR nuevo)."""
    prev = _leer_json(_marca_de_ruta(session_path))
    _escribir_marca(_marca_de_ruta(session_path), vinculado=False, caducada=True,
                    numero=numero or prev.get("numero", ""))


def vinculado_por_ruta(session_path: str) -> bool:
    """¿La sesión de ESTE archivo está vinculada? La usa el RUNTIME (comun/whatsapp.py) para NO abrir
    neonize hasta que el cliente vinculó por QR (evita pelear con el cliente de vinculación por el mismo
    sqlite y evita 'emitir QR a la nada'). Manda la marca; sin marca (sesión LEGACY previa a esto), se
    asume vinculada si el sqlite existe y tiene tamaño de sesión real (una sesión emparejada pesa
    cientos de KB; una vacía, mucho menos)."""
    marca = _leer_json(_marca_de_ruta(session_path))
    if marca:
        return bool(marca.get("vinculado"))
    try:
        return os.path.exists(session_path) and os.path.getsize(session_path) > 50_000
    except OSError:
        return False


class _Vinculacion:
    """Un intento de vinculación en curso (cliente neonize efímero + estado del QR)."""

    def __init__(self, sesion_id: str):
        self.id = sesion_id
        self.estado = "iniciando"        # iniciando | qr | vinculado | expirado | error
        self.qr = ""                     # data URI PNG (solo cuando estado == 'qr')
        self.numero = ""
        self.error = ""
        self.inicio = time.time()
        self.qr_ts = 0.0
        self.client = None
        self._fin = threading.Event()
        threading.Thread(target=self._run, name=f"wa-link-{sesion_id}", daemon=True).start()
        threading.Thread(target=self._watchdog, name=f"wa-link-wd-{sesion_id}", daemon=True).start()

    # -- ciclo de vida ------------------------------------------------------
    def _run(self):
        try:
            from neonize.client import NewClient
            from neonize.events import ConnectedEv  # noqa: F401
            import segno  # noqa: F401
        except Exception as e:  # noqa: BLE001
            self.estado, self.error = "error", f"falta neonize/segno en el gestor: {e}"
            log.error("WhatsApp vinculación deshabilitada: %s", e)
            return
        import segno
        from neonize.client import NewClient
        from neonize.events import ConnectedEv

        ruta = _ruta_sqlite(self.id)
        # uuid único por sesión -> permite varios clientes en el MISMO proceso sin pisarse.
        cli = NewClient(ruta, uuid=f"link-{self.id}")
        self.client = cli

        @cli.qr
        def _on_qr(client, data):  # noqa: ANN001
            try:
                code = data.decode() if isinstance(data, (bytes, bytearray)) else str(data)
                self.qr = segno.make_qr(code).png_data_uri(scale=6, border=2)
                self.qr_ts = time.time()
                if self.estado != "vinculado":
                    self.estado = "qr"
                log.info("[WA-LINK %s] QR nuevo (esperando escaneo)", self.id)
            except Exception as e:  # noqa: BLE001
                log.warning("[WA-LINK %s] no se pudo generar el QR: %s", self.id, e)

        @cli.event(ConnectedEv)
        def _on_conn(client, _):  # noqa: ANN001
            # Conectado = emparejado (o reconexión con sesión ya guardada). Lo marcamos vinculado,
            # persistimos y SOLTAMOS la sesión para que el runtime la use sin conflicto.
            if self.estado == "vinculado":
                return
            self.estado, self.qr = "vinculado", ""
            try:
                me = client.get_me()
                self.numero = getattr(getattr(me, "JID", None), "User", "") or ""
            except Exception:  # noqa: BLE001
                self.numero = ""
            _guardar_marca(self.id, self.numero)
            log.info("[WA-LINK %s] VINCULADO%s", self.id, f" (+{self.numero})" if self.numero else "")
            threading.Thread(target=self._soltar, daemon=True).start()

        try:
            cli.connect()   # bloquea hasta que se corte la conexión (disconnect/stop)
        except Exception as e:  # noqa: BLE001
            if self.estado != "vinculado":
                self.estado, self.error = "error", str(e)
                log.warning("[WA-LINK %s] connect(): %s", self.id, e)
        finally:
            self._fin.set()

    def _soltar(self):
        """Tras emparejar, deja asentar unos segundos y libera el cliente (para el runtime)."""
        time.sleep(GRACIA_TRAS_VINCULAR)
        self._cerrar()

    def _watchdog(self):
        """Si nadie escanea a tiempo, cancela: cierra el cliente y marca 'expirado'."""
        while not self._fin.is_set():
            if self.estado in ("vinculado", "error", "expirado"):
                return
            if time.time() - self.inicio > TIMEOUT_VINCULAR:
                self.estado = "expirado"
                log.info("[WA-LINK %s] expiró (nadie escaneó en %ss)", self.id, TIMEOUT_VINCULAR)
                self._cerrar()
                return
            self._fin.wait(2)

    def _cerrar(self):
        cli = self.client
        if not cli:
            return
        for metodo in ("disconnect", "stop"):
            try:
                fn = getattr(cli, metodo, None)
                if fn:
                    fn()
                    break
            except Exception:  # noqa: BLE001
                continue
        self._fin.set()

    # -- reporte ------------------------------------------------------------
    def snapshot(self) -> dict:
        restante = max(0, int(TIMEOUT_VINCULAR - (time.time() - self.inicio)))
        d = {"estado": self.estado, "numero": self.numero, "expira_en": restante}
        if self.estado == "qr":
            d["qr"] = self.qr
        if self.estado == "error":
            d["error"] = self.error
        return d


# ============================ API PÚBLICA ====================================
def vincular(sesion_id: str) -> dict:
    """Inicia (o reusa) la vinculación por QR de una sesión. Devuelve el estado inicial.
    Si ya está vinculada, no arranca nada: informa 'vinculado'."""
    sesion_id = (sesion_id or "").strip()
    if not sesion_id:
        return {"estado": "error", "error": "falta el id de sesión"}
    with _lock:
        if _ya_vinculado(sesion_id):
            return {"estado": "vinculado", "numero": _leer_marca(sesion_id).get("numero", "")}
        v = _sesiones.get(sesion_id)
        # Reusar si hay un intento vivo (mostrando QR o arrancando). Si terminó (vinculado/expirado/
        # error), arrancar uno nuevo.
        if v is None or v.estado in ("expirado", "error"):
            v = _Vinculacion(sesion_id)
            _sesiones[sesion_id] = v
        return v.snapshot()


def estado(sesion_id: str) -> dict:
    """Estado actual de una sesión (para el poll del panel/alta)."""
    sesion_id = (sesion_id or "").strip()
    if not sesion_id:
        return {"estado": "error", "error": "falta el id de sesión"}
    with _lock:
        v = _sesiones.get(sesion_id)
        if v is not None and v.estado not in ("expirado",):
            snap = v.snapshot()
            # Un intento vivo pisa a la marca vieja SALVO que ya haya vinculado.
            if snap["estado"] != "iniciando" or not _ya_vinculado(sesion_id):
                return snap
        marca = _leer_marca(sesion_id)
        if _ya_vinculado(sesion_id):
            return {"estado": "vinculado", "numero": marca.get("numero", "")}
        # Estuvo vinculada y se cerró (inactividad / desvinculada desde el teléfono): 'caducada'
        # para que el panel muestre el aviso + botón "Volver a vincular" + QR.
        if marca.get("caducada"):
            return {"estado": "caducada", "numero": marca.get("numero", "")}
        return {"estado": "sin_vincular"}


def desvincular(sesion_id: str) -> dict:
    """Corta la sesión y borra SOLO sus archivos (sqlite + marca). No toca nada más.
    El dispositivo puede seguir figurando en el teléfono del cliente: para sacarlo del todo,
    que lo quite desde WhatsApp > Dispositivos vinculados."""
    sesion_id = (sesion_id or "").strip()
    if not sesion_id:
        return {"ok": False, "error": "falta el id de sesión"}
    with _lock:
        v = _sesiones.pop(sesion_id, None)
    if v is not None:
        try:
            cli = v.client
            if cli is not None:
                try:
                    cli.logout()      # avisa a WhatsApp que se desvincula (best-effort)
                except Exception:  # noqa: BLE001
                    pass
            v._cerrar()
        except Exception:  # noqa: BLE001
            pass
    for ruta in (_ruta_sqlite(sesion_id), _ruta_marca(sesion_id)):
        for p in (ruta, ruta + "-wal", ruta + "-shm", ruta + "-journal"):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception as e:  # noqa: BLE001
                log.warning("No se pudo borrar %s: %s", p, e)
    return {"ok": True, "estado": "sin_vincular"}


def vinculado(sesion_id: str) -> bool:
    """True si la sesión ya está vinculada (marca persistida + sqlite presente)."""
    return _ya_vinculado((sesion_id or "").strip())
