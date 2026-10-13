#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gestor de cuota de IA (por cliente) — MULTI-MOTOR y con datos REALES.

Rastrea las DOS IA gratis con su mecánica REAL (verificado en la doc oficial):

- PRIMARIA (Gemini free): NO expone "cuánto queda" por header, así que contamos localmente
  los usos del día contra el límite diario (RPD; gemini-2.5-flash = 250/día). El límite DIARIO
  se reinicia a medianoche hora del Pacífico (America/Los_Angeles).
    · 429 "PerMinute" = límite por MINUTO (transitorio, se recupera en segundos) -> NO es "sin
      cuota", no se avisa como agotada.
    · 429 "PerDay" = límite DIARIO agotado -> sí, hasta el reinicio.

- SECUNDARIA (Groq free): devuelve en CADA respuesta los headers reales
  x-ratelimit-remaining-requests (cuántas quedan en el día) y x-ratelimit-reset-requests
  (cuánto falta para reiniciar, ej. "2m59.56s"). Los usamos tal cual: dato REAL.

Avisos (callback notificar(nivel, mensaje) que el central/agente conectan a WhatsApp + voz):
  · "advertencia": cuando una IA está por quedarse sin consultas (quedan <= avisar_en). Texto
    corto con cuántas quedan (para gastar poco).
  · "critico": cuando una IA se agota -> manda el ESTADO COMPLETO de cada una con su fecha y
    hora REAL de reinicio.
Si el cliente pone su propia key PAGA (ilimitada=True), no se avisa.
"""

import logging
import os
import re
import json
import time
import threading
from datetime import datetime, timedelta

log = logging.getLogger("cuota")

try:
    from zoneinfo import ZoneInfo
    _PT = ZoneInfo("America/Los_Angeles")     # reset diario de Gemini
except Exception:  # noqa: BLE001
    _PT = None

ZONA_DEFAULT = "America/Argentina/Buenos_Aires"
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Nombres lindos por proveedor (para reportar la cadena REAL del cliente sin inventar).
NOMBRE_IA = {
    "gemini": "Gemini", "groq": "Groq", "cerebras": "Cerebras", "mistral": "Mistral",
    "openrouter": "OpenRouter", "deepseek": "DeepSeek", "local": "IA local",
    "deepseek_local": "DeepSeek local", "openai": "OpenAI", "chatgpt": "ChatGPT",
    "claude": "Claude", "grok": "Grok",
}
_ROLES = ["primaria", "secundaria", "terciaria", "cuaternaria"]


def nombre_ia(tipo):
    return NOMBRE_IA.get((tipo or "").lower(), str(tipo or "IA").capitalize())


def cadena_cfg(ia_cfg):
    """Lista ORDENADA de los proveedores de IA REALES del cliente (primaria + respaldos), tal
    como los arma la capa de IA (comun/ia.crear_ia). Es la ÚNICA fuente para reportar 'qué IAs
    tenés' sin cablear nada ni inventar. Respeta lo que el cliente configura (2, 3 o las que sean)."""
    ia = ia_cfg or {}
    orden = [(ia.get("proveedor") or "gemini").lower()]
    bloques = [ia.get("secundario"), ia.get("terciario")]
    if ia.get("proveedor_secundario") and not ia.get("secundario"):
        bloques[0] = {"proveedor": ia.get("proveedor_secundario")}
    for b in bloques[:2]:
        prov = ((b or {}).get("proveedor") or "").lower()
        if prov and prov not in orden:
            orden.append(prov)
    return orden


def _tiene_clave(ia_cfg, proveedor):
    """¿Hay una clave configurada para ese proveedor? Se busca en su bloque y en la raíz."""
    ia = ia_cfg or {}
    campo = f"{proveedor}_api_key"
    if (ia.get(campo) or "").strip():
        return True
    for b in (ia.get("secundario"), ia.get("terciario")):
        b = b or {}
        if (b.get("proveedor") or "").lower() == proveedor and (b.get(campo) or b.get("api_key") or ""):
            return True
    return proveedor in ("local", "ollama")      # los locales no llevan clave


def cadena_util(ia_cfg):
    """La cadena REAL, salteando los proveedores que no tienen clave cargada.

    Una cadena sirve para una cosa: que cuando la IA de arriba se queda sin cuota, la de abajo
    conteste. Un eslabón sin credencial no contesta nada —sólo agrega un viaje fallido y la
    latencia de descubrirlo— y, peor, hace creer que hay un respaldo donde no lo hay. Se avisa
    en el log, porque un respaldo caído es algo que alguien tiene que ir a arreglar."""
    util, descartados = [], []
    for prov in cadena_cfg(ia_cfg):
        (util if _tiene_clave(ia_cfg, prov) else descartados).append(prov)
    if descartados:
        log.warning("Cadena de IA: %s no tiene clave configurada, no cuenta como respaldo. "
                    "Queda: %s", ", ".join(descartados), " -> ".join(util) or "(ninguna)")
    return util or cadena_cfg(ia_cfg)


def _zona(zona):
    try:
        return ZoneInfo(zona or ZONA_DEFAULT)
    except Exception:  # noqa: BLE001
        return None


def _hora_humana(cuando):
    """Hora dicha como un HUMANO, con franja (queda claro AM/PM y se lee bien en voz):
    'las 4 de la mañana', 'las 2 de la tarde', 'las 9 de la noche', 'las 8 y 30 de la mañana'."""
    h, m = cuando.hour, cuando.minute
    franja = ("de la madrugada" if h < 6 else "de la mañana" if h < 12 else
              "del mediodía" if h == 12 else "de la tarde" if h < 20 else "de la noche")
    h12 = h % 12 or 12
    return f"las {h12} {franja}" if m == 0 else f"las {h12} y {m:02d} {franja}"


def _fmt_reset(dt_utc_epoch, zona=ZONA_DEFAULT):
    """Formatea un instante (epoch) como 'hoy/mañana DD/MM a las 4 de la mañana' (hora humana,
    con AM/PM claro) en la zona del cliente."""
    z = _zona(zona)
    ahora = datetime.now(z)
    cuando = datetime.fromtimestamp(dt_utc_epoch, z)
    dia = "hoy" if cuando.date() == ahora.date() else (
        "mañana" if cuando.date() == (ahora + timedelta(days=1)).date() else
        _DIAS[cuando.weekday()])
    return f"{dia} {cuando.strftime('%d/%m')} a {_hora_humana(cuando)}"


def _reset_gemini_epoch():
    """Epoch del próximo reinicio DIARIO de Gemini (medianoche del Pacífico)."""
    ahora = datetime.now(_PT) if _PT else datetime.now()
    reset = (ahora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return reset.timestamp()


def parse_duracion(s):
    """'2m59.56s' / '7.66s' / '1h2m3s' -> segundos (float). None si no se puede."""
    if s is None:
        return None
    s = str(s).strip()
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?", s)
    if not m or not any(m.groups()):
        try:
            return float(s)                    # a veces viene un número pelado (segundos)
        except Exception:  # noqa: BLE001
            return None
    h, mi, se = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + se


def _ruta_conteo(nombre_cliente):
    """Dónde se guarda el conteo de cuota de IA.

    Va al VOLUMEN persistente (`ITHOS_DATA`), igual que el resto del estado de las tareas de fondo.
    Antes se guardaba al lado de este `.py`, que en el servidor vive dentro de la imagen del
    contenedor: hoy sobrevive a los deploys sólo porque `comun/` está bind-mounteado, o sea por
    accidente y no por diseño. Si ese montaje cambiara, el contador volvería a CERO en cada deploy
    y ITHOS gastaría la cuota gratis creyendo que la tiene entera. De paso dejaba archivos de
    estado sueltos en el árbol del código: los tests escribían los suyos ahí y terminaban
    viajando al servidor.

    Si quedó un archivo viejo al lado del `.py` y todavía no hay uno nuevo, se MUEVE, así no se
    pierde el conteo del día en curso."""
    seguro = "".join(ch if ch.isalnum() else "_" for ch in str(nombre_cliente or "cliente"))
    viejo = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"cuota_{seguro}.json")
    try:
        from comun import estado as EST
    except ImportError:
        try:
            import estado as EST          # importado como módulo suelto (agente empaquetado)
        except ImportError:
            return viejo                  # sin el ayudante, se queda exactamente como estaba
    nuevo = EST.ruta("cuota", nombre_cliente)
    try:
        if os.path.exists(viejo) and not os.path.exists(nuevo):
            os.replace(viejo, nuevo)
            log.info("Cuota: el conteo de %s se movió al volumen persistente.", nombre_cliente)
    except OSError as e:  # noqa: BLE001
        log.warning("Cuota: no se pudo mover el conteo viejo (%s); sigo con el de siempre.", e)
        return viejo
    return nuevo


class GestorCuota:
    """Cuota de las DOS IA gratis (Gemini primaria + Groq secundaria) por cliente."""

    def __init__(self, nombre_cliente, limite_diario=250, avisar_en=15,
                 ilimitada=False, archivo=None, notificar=None, zona=ZONA_DEFAULT,
                 cadena=None):
        self.nombre = nombre_cliente
        self.limite_gemini = int(limite_diario)
        self.avisar_en = int(avisar_en)
        self.ilimitada = bool(ilimitada)       # el cliente tiene su propia key paga
        self.notificar = notificar             # callback(nivel, mensaje)
        self.zona = zona or ZONA_DEFAULT
        # Cadena REAL de IAs del cliente, en orden (primaria + respaldos). Se REPORTA tal cual;
        # nada cableado. Si no la pasan, back-compat: las 2 gratis (Gemini primaria, Groq respaldo).
        self.cadena = [str(t).lower() for t in (cadena or [])] or ["gemini", "groq"]
        self.archivo = archivo or _ruta_conteo(nombre_cliente)
        # Gemini (conteo local por día del Pacífico)
        self._dia = ""
        self.gem_usados = 0
        self.gem_agotada = False
        self._gem_avisado = False
        # Groq (headers reales)
        self.groq_restantes = None             # None = desconocido (aún no llamamos)
        self.groq_limite = None
        self.groq_reset_epoch = None
        self.groq_agotada = False
        self._groq_avisado = False
        self._lock = threading.Lock()          # thread-safe: varios canales/hilos registran a la vez
        self._cargar()

    # ---- persistencia (Gemini, por día del Pacífico) ----
    def _cargar(self):
        try:
            d = json.load(open(self.archivo, encoding="utf-8"))
            self._dia = d.get("dia", "")
            self.gem_usados = int(d.get("gem_usados", 0))
            self.gem_agotada = bool(d.get("gem_agotada", False))
            self._gem_avisado = bool(d.get("gem_avisado", False))
        except Exception:  # noqa: BLE001
            pass
        self._rotar()

    def _guardar(self):
        try:
            json.dump({"dia": self._dia, "gem_usados": self.gem_usados,
                       "gem_agotada": self.gem_agotada, "gem_avisado": self._gem_avisado},
                      open(self.archivo, "w", encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass

    def _rotar(self):
        hoy = (datetime.now(_PT) if _PT else datetime.now()).strftime("%Y-%m-%d")
        if hoy != self._dia:
            self._dia, self.gem_usados = hoy, 0
            self.gem_agotada = self._gem_avisado = False
            self._guardar()

    # ---- Gemini ----
    def registrar_gemini(self):
        """Un uso exitoso de Gemini. Avisa (texto corto) si quedan pocas. THREAD-SAFE: el
        incremento y el guardado van bajo lock (varios canales/hilos pueden registrar a la vez);
        el aviso se emite FUERA del lock para no bloquear en el envío por WhatsApp/voz."""
        if self.ilimitada:
            return
        msg = None
        with self._lock:
            self._rotar()
            self.gem_usados += 1
            rest = self.limite_gemini - self.gem_usados
            if 0 < rest <= self.avisar_en and not self._gem_avisado:
                self._gem_avisado = True
                _sig = self._siguiente_a("gemini")
                _cont = (f" Después sigo con *{nombre_ia(_sig)}* (la {self._rol(_sig)})."
                         if _sig else "")
                msg = (f"⚠️ Te quedan *{rest}* consultas de IA gratis en *Gemini* "
                       f"(la {self._rol('gemini')})." + _cont +
                       f" Gemini se reinicia {_fmt_reset(_reset_gemini_epoch(), self.zona)}.")
            self._guardar()
        if msg:
            self._emitir("advertencia", msg)

    def agotada_gemini(self):
        """429 por límite DIARIO de Gemini. THREAD-SAFE: marca+guarda bajo lock (una sola vez
        aunque varios hilos lo detecten); el aviso se emite fuera del lock."""
        if self.ilimitada:
            return
        msg = None
        with self._lock:
            self._rotar()
            if not self.gem_agotada:
                self.gem_agotada = True
                self._guardar()
                msg = self.estado_texto(prefijo="🔴 *Gemini* (primaria) se agotó.")
        if msg:
            self._emitir("critico", msg)

    # ---- Groq (headers reales) ----
    def registrar_groq(self, restantes=None, reset_seg=None, limite=None):
        """Actualiza con los headers REALES de Groq. Avisa si quedan pocas."""
        if self.ilimitada:
            return
        if limite is not None:
            self.groq_limite = int(limite)
        if reset_seg is not None:
            self.groq_reset_epoch = time.time() + float(reset_seg)
        if restantes is not None:
            self.groq_restantes = int(restantes)
            self.groq_agotada = self.groq_restantes <= 0
            if 0 < self.groq_restantes <= self.avisar_en and not self._groq_avisado:
                self._groq_avisado = True
                self._emitir("advertencia", f"⚠️ Te quedan *{self.groq_restantes}* consultas de "
                             f"IA gratis en *Groq* (la {self._rol('groq')})." + (
                                 f" Se reinicia {_fmt_reset(self.groq_reset_epoch, self.zona)}."
                                 if self.groq_reset_epoch else ""))
            elif self.groq_restantes > self.avisar_en:
                self._groq_avisado = False        # se recuperó -> puede volver a avisar

    def agotada_groq(self, retry_after=None):
        """429 de Groq (sin consultas). Avisa al canal UNA sola vez (antes quedaba mudo)."""
        if self.ilimitada:
            return
        self.groq_restantes = 0
        if retry_after is not None:
            self.groq_reset_epoch = time.time() + float(retry_after)
        msg = None
        if not self.groq_agotada:
            self.groq_agotada = True
            msg = self.estado_texto(prefijo=f"🔴 *Groq* (la {self._rol('groq')}) se agotó.")
        if msg:
            self._emitir("critico", msg)

    # ---- roles REALES desde la cadena del cliente (NADA hardcodeado) ----
    def _rol(self, prov):
        """Rol REAL de un proveedor en la cadena del cliente (primaria/secundaria/terciaria/…),
        leído de self.cadena. Nunca inventa 'secundaria': respeta lo que el cliente configuró."""
        p = (prov or "").lower()
        if p in self.cadena:
            i = self.cadena.index(p)
            return _ROLES[i] if i < len(_ROLES) else "respaldo"
        return "respaldo"

    def _siguiente_a(self, prov):
        """El proveedor que sigue en la cadena después de `prov` (o None si es el último)."""
        p = (prov or "").lower()
        if p in self.cadena:
            i = self.cadena.index(p)
            if i + 1 < len(self.cadena):
                return self.cadena[i + 1]
        return None

    # ---- estado / mensajes ----
    def _cola_gemini(self):
        r = _fmt_reset(_reset_gemini_epoch(), self.zona)
        if self.ilimitada:
            return "con tu clave paga, sin límite."
        if self.gem_agotada or (self.limite_gemini - self.gem_usados) <= 0:
            return f"agotada, se reinicia {r}."
        return f"quedan {max(0, self.limite_gemini - self.gem_usados)}, se reinicia {r}."

    def _cola_groq(self):
        if self.ilimitada:
            return "con tu clave paga, sin límite."
        if self.groq_restantes is None:
            return "disponible."
        r = f", se reinicia {_fmt_reset(self.groq_reset_epoch, self.zona)}" if self.groq_reset_epoch else ""
        if self.groq_restantes <= 0:
            return f"agotada{r}."
        return f"quedan {self.groq_restantes}{r}."

    def _linea_ia(self, tipo, rol):
        """Una línea REAL por IA de la cadena: nombre + rol + estado. Gemini y Groq con su cuota
        real; las demás (Cerebras, Mistral, etc.) 'disponible' (no exponen cuota por API gratis)."""
        etq = f"*{nombre_ia(tipo)}* ({rol})"
        if tipo == "gemini":
            return f"{etq}: {self._cola_gemini()}"
        if tipo == "groq":
            return f"{etq}: {self._cola_groq()}"
        return f"{etq}: {'con tu clave paga, sin límite.' if self.ilimitada else 'disponible.'}"

    def _linea_gemini(self):        # compat interno
        return self._linea_ia("gemini", "primaria")

    def _linea_groq(self):          # compat interno
        return self._linea_ia("groq", "secundaria")

    def estado_texto(self, prefijo="📊 *Estado de la IA*", zona=None):
        """Estado COMPLETO de la cadena REAL del cliente (cada IA con su rol y su reinicio real).
        Recorre self.cadena (lo que el cliente configuró), no una lista cableada."""
        if zona:
            self.zona = zona
        self._rotar()
        lineas = [self._linea_ia(t, _ROLES[i] if i < len(_ROLES) else "respaldo")
                  for i, t in enumerate(self.cadena)]
        agotadas = (self.gem_agotada and "gemini" in self.cadena and
                    self.groq_agotada and "groq" in self.cadena)
        cola = ("\nCon una clave de IA *paga* (se carga en el panel) no habría cortes."
                if agotadas and not self.ilimitada else "")
        return f"{prefijo}\n" + "\n".join(lineas) + cola

    def nota_inicio(self):
        """Nota CONCISA para el saludo de arranque sobre la cuota de la PRIMARIA (Gemini): el
        dueño configuró un límite/aviso y quiere saber su estado al conectar. Devuelve '' si la
        primaria está bien (por encima del umbral de aviso). Así el aviso de cuota SÍ llega,
        aunque la IA siga andando por el respaldo automático."""
        if self.ilimitada:
            return ""
        self._rotar()
        rest = self.limite_gemini - self.gem_usados
        r = _fmt_reset(_reset_gemini_epoch(), self.zona)
        if self.gem_agotada or rest <= 0:
            return (f"ℹ️ *Gemini* (tu IA primaria) está sin cuota por hoy; sigo respondiendo con el "
                    f"respaldo automático. Se reinicia {r}.")
        if rest <= self.avisar_en:
            return f"⚠️ Te quedan *{rest}* consultas de *Gemini* (primaria) hoy (se reinicia {r})."
        return ""

    def estado(self):
        """Dict para el panel/observabilidad. Incluye la CADENA real (orden de IAs del cliente)."""
        self._rotar()
        return {"cliente": self.nombre, "ilimitada": self.ilimitada,
                "cadena": list(self.cadena),
                "gemini": {"usados": self.gem_usados, "limite": self.limite_gemini,
                           "restantes": max(0, self.limite_gemini - self.gem_usados),
                           "agotada": self.gem_agotada},
                "groq": {"restantes": self.groq_restantes, "limite": self.groq_limite,
                         "agotada": self.groq_agotada,
                         "reset_epoch": self.groq_reset_epoch}}

    # -- compat con la API vieja (solo Gemini) --
    def registrar(self):
        self.registrar_gemini()

    def marcar_agotada(self):
        self.agotada_gemini()

    def _emitir(self, nivel, mensaje):
        if self.notificar:
            try:
                self.notificar(nivel, mensaje)
            except Exception:  # noqa: BLE001
                pass


def crear_gestor(cli, notificar=None):
    """Arma el GestorCuota del cliente desde su config (límite, aviso, zona). Un solo lugar
    para que demo y producción queden IGUALES."""
    ia = cli.get("ia") or {}
    return GestorCuota(
        cli.get("nombre") or "cliente",
        limite_diario=ia.get("limite_diario", 250),
        avisar_en=ia.get("avisar_en", 15),
        ilimitada=ia.get("ilimitada", False),
        notificar=notificar,
        zona=cli.get("zona_horaria", ZONA_DEFAULT),
        cadena=cadena_cfg(ia))          # la cadena REAL del cliente (2, 3 o las que configure)
