#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Capa de IA ENCHUFABLE (compartida por central y agente).

Se elige por cliente SIN tocar el central:
  - "gemini" (default): nube de Google (texto + voz Charon).
  - "local": 100% en la red del cliente (Ollama + TTS local) para privacidad total.
  - "deepseek": texto por API DeepSeek (barata) + voz por Gemini.

Métodos:
  chat(system, prompt, json_out)  -> texto (triage/respuestas)
  voz_pcm(texto)                  -> PCM 16-bit/24kHz/mono completo (para caché)
  voz_stream(texto)               -> async generator de chunks PCM (baja latencia)
"""

import os
import logging

log = logging.getLogger("ia")

# Instrucción para que la voz sea ITHOS, literal, en el idioma del cliente.
_ACENTOS = {
    "es-AR": "en ESPAÑOL LATINOAMERICANO con acento neutro; NUNCA acento de España",
    "es-ES": "en ESPAÑOL de España",
    "en": "in ENGLISH with a neutral accent",
    "pt-BR": "em PORTUGUÊS do Brasil",
    "fr": "en FRANÇAIS",
    "it": "in ITALIANO",
}


# La voz sale del TTS DEDICADO de Gemini: lee el texto VERBATIM, palabra por palabra.
# El modelo 'native-audio' es CONVERSACIONAL —no genera audio por `generateContent`, así que
# hoy devuelve 404— y además interpretaba el texto y se comía nombres. Una config vieja que lo
# tenga guardado se corrige sola acá: es preferible una voz que suena a una que no.
VOZ_MODELO = "gemini-2.5-flash-preview-tts"


def modelo_voz(cfg):
    """El modelo de voz del cliente, siempre que sea un TTS de verdad."""
    m = str((cfg or {}).get("modelo_voz") or "").strip()
    return m if m.endswith("-tts") or "-tts-" in m else VOZ_MODELO


def _sys_voz(idioma="es-AR"):
    acento = _ACENTOS.get(idioma, _ACENTOS["es-AR"])
    return ("Eres ITHOS Pronuncia EXACTAMENTE el texto que te envía el usuario, "
            "palabra por palabra, sin agregar ni cambiar nada. Voz grave, serena, "
            f"elegante. Habla SIEMPRE {acento}.")


# MULTI-IDIOMA: la transcripción usa el idioma CONFIGURADO por cada cliente (soporta todos
# los idiomas). El vocabulario de dominio son NOMBRES PROPIOS iguales en cualquier idioma,
# así mejora la precisión sin atar a un idioma. La clave de admin va incluida.
HINT_TRANSCRIPCION = (
    "ITHOS, ticket, SLA, GLPI, Zendesk, Jira, Freshservice, HikCentral, BioStar, "
    "fichaje, Brian Sierra, Ayala, Kanerito4262.")

# Nombres de idioma para instruir a Gemini (los más comunes; el resto usa el código ISO,
# que los modelos entienden igual). Sirve para CUALQUIER idioma del mundo.
_IDIOMAS = {
    "es": "español", "en": "English", "pt": "português", "fr": "français",
    "it": "italiano", "de": "Deutsch", "zh": "中文", "ja": "日本語", "ko": "한국어",
    "ru": "русский", "ar": "العربية", "hi": "हिन्दी", "nl": "Nederlands",
    "pl": "polski", "tr": "Türkçe", "id": "Bahasa Indonesia", "vi": "Tiếng Việt",
}


def codigo_idioma(idioma):
    """'es-AR' -> 'es', 'pt-BR' -> 'pt', 'en' -> 'en'. '' si no se sabe (auto-detección)."""
    base = str(idioma or "").replace("_", "-").split("-")[0].strip().lower()
    return base if base.isalpha() and len(base) == 2 else ""


# --------------------------------------------------------------- selección de modelo
# Estrategia (Brian): en GRATIS, el modelo con MÁS cuota/velocidad (no el más avanzado que
# consume/limita más), compensado con PROMPTS PROFESIONALES para que rinda como uno grande.
# En PAGO, el más capaz pero COST-EFFECTIVE (no el flagship, para no dispararle el costo).
# Mapa por PROVEEDOR (todos los que se conectan por API):
#   'free' = el modelo con MÁS cuota/velocidad de su tier gratis.
#   'pago' = el más CAPAZ pero COST-EFFECTIVE (NO el flagship carísimo — sería incoherente).
# OpenRouter da acceso por UNA API a casi todos los modelos del mundo (incluye ':free').
_MODELOS = {
    "gemini":     {"free": "gemini-2.5-flash-lite",                    "pago": "gemini-2.5-flash"},
    "groq":       {"free": "openai/gpt-oss-120b",                      "pago": "openai/gpt-oss-120b"},
    "cerebras":   {"free": "gpt-oss-120b",                             "pago": "gpt-oss-120b"},
    "mistral":    {"free": "mistral-small-latest",                     "pago": "mistral-medium-latest"},
    "openrouter": {"free": "meta-llama/llama-3.3-70b-instruct:free",   "pago": "openai/gpt-4o-mini"},
    "deepseek":   {"free": "deepseek-chat",                            "pago": "deepseek-chat"},
    "local":      {"free": "qwen2.5:14b",                              "pago": "qwen2.5:14b"},
    "deepseek_local": {"free": "deepseek-r1",                          "pago": "deepseek-r1"},
    # Proveedores SIN tier gratis por API -> siempre el cost-effective (no el flagship).
    "openai":     {"free": "gpt-4o-mini",     "pago": "gpt-4o-mini"},
    "chatgpt":    {"free": "gpt-4o-mini",     "pago": "gpt-4o-mini"},
    "claude":     {"free": "claude-3-5-haiku-latest", "pago": "claude-sonnet-4-5"},
    "grok":       {"free": "grok-2-latest",   "pago": "grok-2-latest"},
}
# Estos no tienen cuota gratis real por API: se tratan como PAGO (modelo cost-effective).
_SIEMPRE_PAGO = {"openai", "chatgpt", "claude", "grok"}

# ESCALERA DE MODELOS por proveedor: a cuáles se corre ITHOS cuando el que está usando no sirve,
# ANTES de cambiar de proveedor. Dos motivos reales, los dos vistos en producción:
#   · se agotó la cuota del DÍA de ese modelo (la cuota gratis se cuenta por modelo), y
#   · el proveedor RETIRÓ el modelo (Groq dio de baja los Llama y quedó respondiendo 404).
# Van del más económico al más capaz.
_ESCALERA_GEMINI = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview"]
_ESCALERAS = {
    "gemini": _ESCALERA_GEMINI,
    "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"],
    "cerebras": ["gpt-oss-120b", "gemma-4-31b"],
    "mistral": ["mistral-small-latest", "ministral-8b-latest", "ministral-3b-latest"],
}


def escalera_de(proveedor, modelo):
    """Los modelos a probar para ese proveedor, empezando por el elegido."""
    resto = _ESCALERAS.get((proveedor or "").lower(), [])
    return [modelo] + [m for m in resto if m != modelo]


def _modelo_retirado(msg):
    """True si el proveedor dice que ese modelo ya no existe (lo dio de baja)."""
    m = str(msg).lower()
    return ("model_not_found" in m or "does not exist" in m
            or "is not found for api version" in m or "model_decommissioned" in m)


def es_pago(cfg):
    """Override MANUAL explícito de plan pago (casi nunca hace falta: se detecta solo)."""
    cfg = cfg or {}
    return bool(cfg.get("ilimitada")) or str(cfg.get("plan", "")).lower() in (
        "pago", "paid", "premium", "pro")


def _planes_archivo():
    base = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
    return os.path.join(base, "planes_ia.json")


def _plan_cache_leer():
    import json
    try:
        return json.load(open(_planes_archivo(), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _plan_cache_guardar(d):
    import json
    try:
        os.makedirs(os.path.dirname(_planes_archivo()), exist_ok=True)
        json.dump(d, open(_planes_archivo(), "w", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass


def _probe_plan(prov, key):
    """Detección BARATA (sin gastar tokens de chat) del tier de la API. Devuelve 'pago'/'free'.
    OpenRouter expone is_free_tier en /auth/key. Lo no detectable barato -> 'free' (gastar lo
    mínimo: el modelo eficiente igual funciona en free y en pago)."""
    try:
        if prov == "openrouter" and key:
            import json as _j
            import urllib.request
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = (_j.load(r) or {}).get("data", {}) or {}
                return "free" if d.get("is_free_tier", True) else "pago"
    except Exception:  # noqa: BLE001
        pass
    return "free"


def detectar_plan(proveedor, cfg):
    """AUTOMÁTICO: decide si la API del proveedor es PAGA o GRATIS, sin que el cliente elija
    nada y (donde se puede) SIN gastar tokens. Cachea 24 h por clave. Reglas:
      · override manual (ilimitada/plan) -> pago.
      · OpenAI/Claude/Grok/DeepSeek: no tienen tier gratis por API -> pago.
      · si el modelo free y el pago son el MISMO -> no hace falta detectar (free).
      · OpenRouter: se consulta /auth/key (is_free_tier) — gratis, sin tokens.
      · el resto (Gemini/Mistral/Cerebras/local): no hay forma barata/fiable de saberlo ->
        'free' (usamos el modelo EFICIENTE; gasta lo mínimo y funciona igual en free o pago)."""
    import time
    cfg = cfg or {}
    prov = (proveedor or "").lower()
    if es_pago(cfg):
        return "pago"
    if prov in _SIEMPRE_PAGO or prov == "deepseek":
        return "pago"
    tabla = _MODELOS.get(prov, {})
    if tabla.get("free") == tabla.get("pago"):      # mismo modelo -> detectar no cambia nada
        return "free"
    key = cfg.get(f"{prov}_api_key") or cfg.get("api_key") or ""
    import hashlib
    ck = prov + ":" + hashlib.sha1((key or "").encode()).hexdigest()[:12]
    cache = _plan_cache_leer()
    ent = cache.get(ck)
    if ent and time.time() - float(ent.get("ts", 0)) < 86400:
        return ent.get("plan", "free")
    plan = _probe_plan(prov, key)
    cache[ck] = {"plan": plan, "ts": time.time()}
    _plan_cache_guardar(cache)
    return plan


def elegir_modelo(cfg, proveedor, defecto):
    """Modelo para CUALQUIER proveedor. Si el cliente fijó 'modelo_texto' (y no es 'auto'),
    ese. Si es 'auto' (default): se DETECTA solo el plan por API (paga/gratis) y se usa el
    óptimo — GRATIS: el de más cuota; PAGO: el más capaz pero cost-effective."""
    cfg = cfg or {}
    m = (cfg.get("modelo_texto") or "").strip()
    if m and m.lower() != "auto":
        return m
    prov = (proveedor or "").lower()
    plan = detectar_plan(prov, cfg)
    tabla = _MODELOS.get(prov, {})
    return tabla.get("pago" if plan == "pago" else "free") or defecto


def nombre_idioma(idioma):
    c = codigo_idioma(idioma)
    return _IDIOMAS.get(c, c or "")


class ProveedorIA:
    def chat(self, system, prompt, json_out=True, max_tokens=None):
        raise NotImplementedError

    def voz_pcm(self, texto):
        raise NotImplementedError

    async def voz_stream(self, texto):
        raise NotImplementedError
        yield b""  # pragma: no cover


class GeminiIA(ProveedorIA):
    def __init__(self, cfg, gestor=None):
        self.api_key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        self.modelo_texto = elegir_modelo(cfg, "gemini", "gemini-2.5-flash")
        # Voz = TTS DEDICADO (lee VERBATIM, palabra por palabra). ANTES se usaba el modelo
        # 'native-audio' (conversacional, con 'thinking') que INTERPRETABA el texto y SE COMÍA palabras
        # -nombres- (bug real: 'Bienvenido, Noemi' -> decía 'Bienvenido a...' sin 'Noemi'). El TTS
        # dedicado lo lee tal cual. Verificado con Vosk: mantiene el nombre.
        self.modelo_voz = modelo_voz(cfg)
        self.voz = cfg.get("voz", "Charon")
        self.idioma = cfg.get("idioma", "es-AR")
        self.gestor = gestor          # GestorCuota (avisa cuando se agota la gratuita)
        self._cli = None
        # Si hay una IA de respaldo (MultiIA), fallar RÁPIDO ante 429 (no reintentar
        # con esperas largas): así el respaldo (Groq) toma el control al instante.
        self.sin_reintento_429 = False
        # ESCALERA DE MODELOS. La cuota gratis de Gemini es POR MODELO Y POR DÍA, y son muy
        # distintas entre sí (flash-lite quedó en 20 pedidos por día: se agota con 20 tickets).
        # Antes, agotado el modelo elegido, ITHOS saltaba de proveedor aunque OTRO modelo de
        # Gemini todavía tuviera cuota del día. Ahora baja por esta escalera primero, y recién
        # cuando se agotan TODOS pasa a la IA siguiente de la cadena.
        self._escalera = [self.modelo_texto] + [m for m in _ESCALERA_GEMINI
                                                if m != self.modelo_texto]
        self._agotados = {}           # modelo -> día en que se quedó sin cuota (se libera solo)

    def _cliente(self):
        if self._cli is None:
            from google import genai
            self._cli = genai.Client(api_key=self.api_key)
        return self._cli

    def _modelo_vigente(self):
        """El primer modelo de la escalera que todavía tiene cuota HOY. La cuota gratuita se
        renueva por día, así que un modelo agotado ayer vuelve a estar disponible solo."""
        import datetime
        hoy = datetime.date.today().isoformat()
        for m in self._escalera:
            if self._agotados.get(m) != hoy:
                return m
        return self._escalera[0]

    def _marcar_agotado(self, modelo):
        """Anota que ese modelo se quedó sin cuota hoy. True si queda otro para seguir."""
        import datetime
        self._agotados[modelo] = datetime.date.today().isoformat()
        siguiente = self._modelo_vigente()
        if self._agotados.get(siguiente) == self._agotados[modelo]:
            return False                              # no queda ninguno con cuota hoy
        log.info("Gemini: '%s' sin cuota diaria -> sigo con '%s'.", modelo, siguiente)
        return True

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        import re
        import time
        from google.genai import types
        # Texto conversacional: temperatura MÁS baja (menos confabulación de datos/versiones) y
        # tope de tokens acotado (no volcar de más ante algo puntual; igual alcanza para detalle).
        conf = types.GenerateContentConfig(
            system_instruction=system, temperature=0.2 if json_out else 0.1)
        if json_out:
            conf.response_mime_type = "application/json"
        else:
            conf.max_output_tokens = max_tokens or 1600
        for intento in range(5):
            try:
                r = self._cliente().models.generate_content(
                    model=self._modelo_vigente(), contents=prompt, config=conf)
                if self.gestor:
                    self.gestor.registrar_gemini()   # cuenta el uso; avisa si quedan pocos
                return r.text
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                # Carrera del cliente httpx ("client has been closed"): recrear y reintentar.
                if "has been closed" in msg and intento < 4:
                    self._cli = None
                    time.sleep(0.3)
                    continue
                es_429 = "429" in msg or "RESOURCE_EXHAUSTED" in msg
                # Límite DIARIO agotado: reintentar el MISMO modelo no sirve. Pero la cuota es
                # por modelo: si queda otro con cuota hoy, se sigue con ese en el acto.
                if es_429 and ("PerDay" in msg or "RequestsPerDay" in msg):
                    if self._marcar_agotado(self._modelo_vigente()):
                        continue                     # queda otro modelo de Gemini con cuota
                    if self.gestor:
                        self.gestor.agotada_gemini()
                    raise
                # Con respaldo: no esperar, fallar ya para que el respaldo responda.
                if es_429 and self.sin_reintento_429:
                    raise
                if es_429 and intento < 4:       # límite por minuto -> esperar y reintentar
                    m = re.search(r"retryDelay['\":\s]+(\d+(?:\.\d+)?)", msg)
                    espera = min((float(m.group(1)) + 1) if m else 8, 30)
                    time.sleep(espera)
                    continue
                raise
        return ""

    def transcribir(self, audio_bytes, mime="audio/ogg", idioma=None):
        """Transcribe un audio a texto en el idioma del CLIENTE (multi-idioma) + vocabulario
        del dominio, para máxima precisión (nivel Gemini/ChatGPT)."""
        from google.genai import types
        lang = nombre_idioma(idioma or self.idioma)
        en = f"en {lang} " if lang else ""
        instr = (
            f"Transcribí EXACTAMENTE este audio {en}palabra por palabra, SIN traducir, "
            "resumir ni corregir. Devolvé SOLO el texto transcripto, sin comillas ni "
            "comentarios. Mantené los números como dígitos (ej. 4262) y respetá los nombres "
            "propios. Nombres propios frecuentes: " + HINT_TRANSCRIPCION)
        # Misma escalera que el texto: transcribir un audio también consume la cuota del día.
        for _ in range(len(self._escalera)):
            modelo = self._modelo_vigente()
            try:
                r = self._cliente().models.generate_content(
                    model=modelo,
                    contents=[types.Part.from_bytes(data=audio_bytes, mime_type=mime), instr])
                break
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if ("PerDay" in msg or "RequestsPerDay" in msg) and self._marcar_agotado(modelo):
                    continue
                raise
        if self.gestor:
            self.gestor.registrar()
        return (r.text or "").strip()

    def _live_config(self):
        from google.genai import types
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=_sys_voz(self.idioma),
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voz))))

    async def voz_stream(self, texto):
        """Genera la voz con el TTS DEDICADO de Gemini (lee VERBATIM). El TTS devuelve el audio COMPLETO
        (no es streaming real como el Live API, pero mantiene la interfaz: un solo yield). Se usa igual
        para el cacheo (junta todo) y para la reproducción en vivo. El TTS NO acepta system_instruction
        (da 500): el acento/tono los da la voz Charon; leemos el texto tal cual (sin comerse palabras)."""
        from google.genai import types
        resp = await self._cliente().aio.models.generate_content(
            model=self.modelo_voz, contents=texto,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voz)))))
        try:
            data = resp.candidates[0].content.parts[0].inline_data.data
        except (AttributeError, IndexError, TypeError):
            data = None
        if data:
            yield data

    def voz_pcm(self, texto):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            async def _full():
                pcm = bytearray()
                async for chunk in self.voz_stream(texto):
                    pcm.extend(chunk)
                return bytes(pcm)
            return loop.run_until_complete(_full())
        finally:
            loop.close()


class LocalIA(ProveedorIA):
    """IA 100% local (privacidad total). Texto: Ollama. Voz: TTS local (a implementar).
    Hardware: 7-8B => CPU+16GB o GPU 8GB; 14-32B => GPU 16-24GB; voz XTTS => GPU 8-12GB.
    """

    def __init__(self, cfg):
        self.url = cfg.get("ollama_url", "http://127.0.0.1:11434")
        self.modelo_texto = elegir_modelo(cfg, "local", "qwen2.5:14b")

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        import json
        import urllib.request
        payload = {"model": self.modelo_texto, "stream": False,
                   "options": {"temperature": 0.2 if json_out else 0.1},
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": prompt}]}
        if json_out:
            payload["format"] = "json"
        else:
            payload["options"]["num_predict"] = max_tokens or 1600   # detalle sin volcar de más
        req = urllib.request.Request(
            self.url + "/api/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)["message"]["content"]

    def voz_pcm(self, texto):
        raise NotImplementedError("TTS local (Piper/XTTS) — a implementar por cliente")


class DeepSeekIA(ProveedorIA):
    def __init__(self, cfg):
        self.api_key = cfg.get("deepseek_api_key", "")
        self.modelo_texto = elegir_modelo(cfg, "deepseek", "deepseek-chat")
        self._gem = GeminiIA(cfg)

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        import json
        import urllib.request
        payload = {"model": self.modelo_texto, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}]}
        if json_out:
            payload["temperature"] = 0.2
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["temperature"] = 0.1          # texto: menos confabulación de datos/versiones
            payload["max_tokens"] = max_tokens or 1600   # detalle sin volcar de más; cap dinámico
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)["choices"][0]["message"]["content"]

    def transcribir(self, audio_bytes, mime="audio/ogg", idioma=None):
        return self._gem.transcribir(audio_bytes, mime, idioma=idioma)

    def voz_pcm(self, texto):
        return self._gem.voz_pcm(texto)

    async def voz_stream(self, texto):
        async for c in self._gem.voz_stream(texto):
            yield c


class ClaudeIA(ProveedorIA):
    """Texto por la API de Anthropic (Claude). Voz: Charon (Gemini)."""

    def __init__(self, cfg):
        self.api_key = cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.modelo = elegir_modelo(cfg, "claude", "claude-sonnet-4-5")
        self._gem = GeminiIA(cfg)

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        import json
        import urllib.request
        if json_out:
            prompt = prompt + "\n\nRespondé SOLO con JSON válido, sin texto extra."
        body = {"model": self.modelo, "system": system,
                "temperature": 0.2 if json_out else 0.1,    # texto: menos confabulación
                "max_tokens": 1024 if json_out else (max_tokens or 1600),   # cap dinámico
                "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        return d["content"][0]["text"]

    def transcribir(self, audio_bytes, mime="audio/ogg", idioma=None):
        return self._gem.transcribir(audio_bytes, mime, idioma=idioma)

    def voz_pcm(self, texto):
        return self._gem.voz_pcm(texto)

    async def voz_stream(self, texto):
        async for c in self._gem.voz_stream(texto):
            yield c


class OpenAIIA(ProveedorIA):
    """Texto por la API de OpenAI (GPT). Voz: Charon (Gemini)."""

    def __init__(self, cfg):
        self.api_key = cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
        self.modelo = elegir_modelo(cfg, "openai", "gpt-4o-mini")
        self._gem = GeminiIA(cfg)

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        import json
        import urllib.request
        payload = {"model": self.modelo, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if json_out:
            payload["temperature"] = 0.2
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["temperature"] = 0.1          # texto: menos confabulación de datos/versiones
            payload["max_tokens"] = max_tokens or 1600   # detalle sin volcar de más; cap dinámico
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["choices"][0]["message"]["content"]

    def transcribir(self, audio_bytes, mime="audio/ogg", idioma=None):
        return self._gem.transcribir(audio_bytes, mime, idioma=idioma)

    def voz_pcm(self, texto):
        return self._gem.voz_pcm(texto)

    async def voz_stream(self, texto):
        async for c in self._gem.voz_stream(texto):
            yield c


class GrokIA(ProveedorIA):
    """Texto por la API de xAI (Grok), compatible OpenAI. Voz: Charon (Gemini)."""

    def __init__(self, cfg):
        self.api_key = cfg.get("grok_api_key") or os.environ.get("XAI_API_KEY", "")
        self.modelo = elegir_modelo(cfg, "grok", "grok-2-latest")
        self._gem = GeminiIA(cfg)

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        import json
        import urllib.request
        payload = {"model": self.modelo, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if json_out:
            payload["temperature"] = 0.2
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["temperature"] = 0.1          # texto: menos confabulación de datos/versiones
            payload["max_tokens"] = max_tokens or 1600   # detalle sin volcar de más; cap dinámico
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["choices"][0]["message"]["content"]

    def transcribir(self, audio_bytes, mime="audio/ogg", idioma=None):
        return self._gem.transcribir(audio_bytes, mime, idioma=idioma)

    def voz_pcm(self, texto):
        return self._gem.voz_pcm(texto)

    async def voz_stream(self, texto):
        async for c in self._gem.voz_stream(texto):
            yield c


class _OpenAICompat(ProveedorIA):
    """Base para proveedores compatibles con la API de OpenAI (mismo formato de chat).
    La VOZ siempre es Charon (Gemini). Subclases definen URL, key y proveedor del modelo."""
    URL = ""
    PROV = ""
    DEFECTO = "gpt-4o-mini"
    _EXTRA = {}

    def __init__(self, cfg):
        self.api_key = cfg.get(f"{self.PROV}_api_key") or os.environ.get(
            f"{self.PROV.upper()}_API_KEY", "")
        self.modelo = elegir_modelo(cfg, self.PROV, self.DEFECTO)
        self._escalera = escalera_de(self.PROV, self.modelo)
        self._gem = GeminiIA(cfg)

    # UA de navegador: Cerebras/otros están detrás de Cloudflare y bloquean el UA de Python.
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
    MAX_KEY = "max_tokens"        # Cerebras usa 'max_completion_tokens' (lo pisa su subclase)

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        import json
        import urllib.error
        import urllib.request
        payload = {"messages": [
            {"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if json_out:
            payload["temperature"] = 0.2
            payload["response_format"] = {"type": "json_object"}
            payload[self.MAX_KEY] = 2000       # el JSON del agente es corto -> no pasar el TPM
        else:
            # Texto conversacional: temperatura MÁS baja (menos confabulación de datos/versiones) y
            # un tope de tokens acotado para no volcar documentación de más ante algo puntual (igual
            # alcanza para una respuesta detallada cuando la piden).
            payload["temperature"] = 0.1
            payload[self.MAX_KEY] = max_tokens or 1600
        # Si el proveedor dio de baja el modelo, se sigue con el siguiente de su escalera en vez de
        # dejar al cliente sin IA (pasó de verdad: Groq retiró los Llama y todo devolvía 404).
        for modelo in self._escalera:
            req = urllib.request.Request(
                self.URL, data=json.dumps({**payload, "model": modelo}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": self._UA,
                         "Authorization": f"Bearer {self.api_key}", **self._EXTRA})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    if modelo != self.modelo:
                        log.info("%s: '%s' ya no está; sigo con '%s'.",
                                 self.PROV, self.modelo, modelo)
                        self.modelo = modelo          # no volver a probar el retirado
                        self._escalera = escalera_de(self.PROV, modelo)
                    return json.load(r)["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                cuerpo = e.read().decode("utf-8", "replace")
                if _modelo_retirado(cuerpo) and modelo != self._escalera[-1]:
                    continue
                raise RuntimeError(f"HTTP {e.code} {self.PROV}: {cuerpo[:300]}") from e
        return ""

    def transcribir(self, audio_bytes, mime="audio/ogg", idioma=None):
        return self._gem.transcribir(audio_bytes, mime, idioma=idioma)

    def voz_pcm(self, texto):
        return self._gem.voz_pcm(texto)

    async def voz_stream(self, texto):
        async for c in self._gem.voz_stream(texto):
            yield c


class OpenRouterIA(_OpenAICompat):
    """OpenRouter: UNA API para CASI TODOS los modelos del mundo (incluye modelos ':free').
    Ideal para el plan gratis con mucha variedad. Voz: Charon (Gemini)."""
    URL = "https://openrouter.ai/api/v1/chat/completions"
    PROV = "openrouter"
    DEFECTO = "meta-llama/llama-3.3-70b-instruct:free"
    _EXTRA = {"HTTP-Referer": "https://intellihelp.tech", "X-Title": "ITHOS"}


class MistralIA(_OpenAICompat):
    """Mistral AI (La Plateforme). Compatible OpenAI. Voz: Charon.

    Su plan gratis son 10 dólares de crédito POR MES, que se renuevan —a diferencia del de
    Cerebras, que eran 5 una sola vez y vencían—. Igual es crédito: si se agota, la cadena sigue
    con el proveedor siguiente.

    Los modelos se piden por su alias `-latest`, que Mistral va moviendo a la versión vigente: así
    una versión con fecha que se retire no nos deja tirados. Los nombres se verificaron contra la
    API en vivo (`/v1/models`), NO contra la documentación: la doc listaba nombres que la API no
    reconoce."""
    URL = "https://api.mistral.ai/v1/chat/completions"
    PROV = "mistral"
    DEFECTO = "mistral-small-latest"


class DeepSeekLocalIA(_OpenAICompat):
    """DeepSeek corriendo 100% LOCAL (privacidad total), SIN Ollama: contra un servidor local
    compatible con OpenAI (LM Studio, vLLM, llama.cpp --server, text-generation-webui). El
    cliente BAJA el modelo DeepSeek (ej. deepseek-r1) en ese servidor y ITHOS le pega por HTTP
    local. La URL es configurable ('deepseek_local_url'); por defecto LM Studio (127.0.0.1:1234).
    Voz: Charon (Gemini). Es distinto del proveedor 'local' (Ollama) y del 'deepseek' (nube)."""
    PROV = "deepseek_local"
    DEFECTO = "deepseek-r1"
    _UA = "ITHOS"        # es local: no hay Cloudflare que exija UA de navegador

    def __init__(self, cfg):
        # Servidor local OpenAI-compatible (LM Studio:1234 · vLLM:8000 · llama.cpp:8080).
        self.URL = (cfg.get("deepseek_local_url") or os.environ.get("DEEPSEEK_LOCAL_URL")
                    or "http://127.0.0.1:1234/v1/chat/completions")
        super().__init__(cfg)
        self.api_key = self.api_key or "local"   # los servers locales aceptan cualquier key


class CerebrasIA(_OpenAICompat):
    """Cerebras (api.cerebras.ai) — ultrarrápido, compatible OpenAI (usa 'max_completion_tokens').
    Voz: Charon. Key en cloud.cerebras.ai.

    OJO: acá lo GRATIS es un SALDO, no una cuota que se renueva. El "Free Trial" son 5 dólares de
    crédito que además VENCEN a los 30 días; los límites que muestra la consola (2.400 pedidos y
    1.000.000 de tokens por día) son el tope de VELOCIDAD de ese tier, no una franquicia diaria.
    Agotado o vencido el crédito, la API corta con `402 payment_required` en TODOS los modelos —da
    igual cuál se elija, los dos descuentan del mismo saldo— aunque la clave siga siendo válida
    (listar modelos devuelve 200). Se destraba comprando crédito en la consola; el código no
    necesita ningún cambio. Le pasó a la cuenta de INTELLIHELP en agosto de 2026."""
    URL = "https://api.cerebras.ai/v1/chat/completions"
    PROV = "cerebras"
    DEFECTO = "gpt-oss-120b"
    MAX_KEY = "max_completion_tokens"


class GroqCloudIA(ProveedorIA):
    """Texto por Groq Cloud (GRATIS, muy rápido, compatible OpenAI; corre Llama).
    API key gratis en https://console.groq.com . Voz: Charon (Gemini)."""

    # UA de navegador: Groq está detrás de Cloudflare y bloquea el UA de Python.
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

    def __init__(self, cfg, gestor=None):
        self.api_key = cfg.get("groq_api_key") or os.environ.get("GROQ_API_KEY", "")
        self.modelo = elegir_modelo(cfg, "groq", _ESCALERAS["groq"][0])
        self._escalera = escalera_de("groq", self.modelo)
        self.idioma = cfg.get("idioma", "es-AR")
        self.gestor = gestor
        self._gem = GeminiIA(cfg)

    def _cuota_headers(self, r):
        """Lee los headers REALES de cuota de Groq y se los pasa al gestor (dato exacto:
        cuántas consultas quedan hoy y cuánto falta para reiniciar)."""
        if not self.gestor:
            return
        try:
            from comun import cuota as _C
            h = r.headers
            rest = h.get("x-ratelimit-remaining-requests")
            lim = h.get("x-ratelimit-limit-requests")
            reset = _C.parse_duracion(h.get("x-ratelimit-reset-requests"))
            self.gestor.registrar_groq(
                restantes=int(rest) if rest is not None else None,
                reset_seg=reset,
                limite=int(lim) if lim is not None else None)
        except Exception:  # noqa: BLE001
            pass

    def _pedir(self, payload, timeout=60):
        import json
        import urllib.request
        import urllib.error
        # Si Groq dio de baja el modelo, se sigue con el siguiente de su escalera. Pasó de verdad:
        # retiró los Llama y el triage quedó recibiendo 404 en cada ticket.
        for modelo in self._escalera:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=json.dumps({**payload, "model": modelo}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": self._UA,
                         "Authorization": f"Bearer {self.api_key}"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    self._cuota_headers(r)
                    if modelo != self.modelo:
                        log.info("Groq: '%s' ya no está; sigo con '%s'.", self.modelo, modelo)
                        self.modelo = modelo          # no volver a probar el retirado
                        self._escalera = escalera_de("groq", modelo)
                    return json.load(r)["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:  # noqa: BLE001
                cuerpo = ""
                try:
                    cuerpo = e.read().decode("utf-8", "ignore")
                except Exception:  # noqa: BLE001
                    pass
                if _modelo_retirado(cuerpo) and modelo != self._escalera[-1]:
                    continue
                if e.code == 429 and self.gestor:
                    try:
                        self.gestor.agotada_groq(retry_after=_a_float(e.headers.get("retry-after")))
                    except Exception:  # noqa: BLE001
                        pass
                # Re-lanzar con el CUERPO ('requests per day' vs 'per minute') para clasificar bien.
                raise RuntimeError(f"HTTP {e.code} Groq: {cuerpo or e.reason}") from e
        return ""

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        # Groq (OpenAI-compat) exige la palabra "json" en los mensajes si se pide json_object.
        if json_out and "json" not in (system + prompt).lower():
            prompt = prompt + "\n\nRespondé SOLO en formato JSON válido."
        payload = {"messages": [           # el modelo lo pone `_pedir` (puede bajar por la escalera)
            {"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if json_out:
            payload["temperature"] = 0.2
            payload["response_format"] = {"type": "json_object"}
            # Cap de completion: el JSON del agente es corto. Sin esto, Groq reserva un
            # completion enorme y 'entrada + completion' supera el TPM del free -> 413
            # 'request too large' (y el agente no respondía nada).
            payload["max_tokens"] = 1500
        else:
            payload["temperature"] = 0.1          # texto: menos confabulación de datos/versiones
            payload["max_tokens"] = max_tokens or 1600   # detalle sin volcar de más; cap dinámico
        return self._pedir(payload)

    def chat_stream(self, system, prompt):
        """Genera la respuesta en STREAMING (SSE): va largando el texto a medida que sale.
        Sirve para que la voz arranque casi al instante en respuestas largas."""
        import json
        import urllib.request
        payload = {"model": self.modelo, "temperature": 0.1, "stream": True,
                   "max_tokens": 1600, "messages": [
                       {"role": "system", "content": system},
                       {"role": "user", "content": prompt}]}
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "User-Agent": self._UA,
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=90) as r:
            for linea in r:
                linea = linea.decode("utf-8", "ignore").strip()
                if not linea.startswith("data:"):
                    continue
                dato = linea[5:].strip()
                if dato == "[DONE]":
                    break
                try:
                    delta = json.loads(dato)["choices"][0]["delta"].get("content", "")
                except Exception:  # noqa: BLE001
                    continue
                if delta:
                    yield delta

    def transcribir(self, audio_bytes, mime="audio/ogg", idioma=None):
        """Transcribe audio con Whisper de Groq (GRATIS). Multi-idioma: usa el idioma del
        CLIENTE (o auto-detecta) + vocabulario del dominio + modelo grande para máxima
        precisión."""
        import json
        import uuid
        import urllib.request
        ext = "ogg" if "ogg" in mime else ("mp3" if "mp3" in mime else "wav")
        b = uuid.uuid4().hex
        def campo(n, v):
            return (f'--{b}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n').encode()
        # language (idioma del cliente; si no se sabe, Whisper autodetecta) + prompt
        # (nombres propios) + temperature 0 => transcripción fiel en cualquier idioma.
        body = (campo("model", "whisper-large-v3")
                + campo("temperature", "0")
                + campo("prompt", HINT_TRANSCRIPCION)
                + campo("response_format", "json"))
        lang = codigo_idioma(idioma or self.idioma)
        if lang:
            body += campo("language", lang)
        body += (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="audio.{ext}"\r\n'
                 f'Content-Type: {mime}\r\n\r\n').encode() + audio_bytes + f'\r\n--{b}--\r\n'.encode()
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/audio/transcriptions", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": self._UA,
                     "Content-Type": f"multipart/form-data; boundary={b}"})
        with urllib.request.urlopen(req, timeout=90) as r:
            return (json.load(r).get("text") or "").strip()

    def voz_pcm(self, texto):
        return self._gem.voz_pcm(texto)

    async def voz_stream(self, texto):
        async for c in self._gem.voz_stream(texto):
            yield c


def _a_float(x):
    try:
        return float(x)
    except Exception:  # noqa: BLE001
        return None


def _es_sin_cuota(e):
    m = str(e)
    return "429" in m or "RESOURCE_EXHAUSTED" in m or "insufficient_quota" in m or "rate limit" in m.lower()


def es_por_dia(e):
    """True si el 429 es por el límite DIARIO (agotado hasta el reinicio): Gemini 'PerDay',
    Groq 'requests per day (RPD)', u OpenAI 'insufficient_quota' (facturación)."""
    m = str(e).lower()
    return ("perday" in m or "per day" in m or "requestsperday" in m or "requests per day" in m
            or "rpd" in m or "insufficient_quota" in m)


def es_por_minuto(e):
    """True si es un límite por MINUTO / rate-limit transitorio (se recupera en segundos), NO
    falta de cuota diaria. Ante un 429 sin detalle, asumimos por-minuto (no asustar en vano)."""
    m = str(e).lower()
    if es_por_dia(e):
        return False
    # Señales DIRECTAS de límite por minuto (simétrico a es_por_dia): Groq 'TPM/RPM',
    # Gemini 'PerMinute'. Así se clasifica bien aunque el SDK no incluya la palabra 'rate limit'.
    if ("per minute" in m or "per-minute" in m or "perminute" in m
            or "tpm" in m or "rpm" in m):
        return True
    return ("429" in m or "resource_exhausted" in m or "rate limit" in m
            or "too many requests" in m or "rate_limit" in m)


def _transitorio(e):
    """Error TEMPORAL del proveedor (no es falta de cuota): sobrecarga/indisponible/timeout.
    Conviene caer al respaldo por un ratito (no es que se agotó la cuota)."""
    m = str(e).lower()
    return ("503" in m or "unavailable" in m or "high demand" in m or "overloaded" in m
            or "internal error" in m or "500" in m or "timed out" in m or "timeout" in m
            or "connection" in m)


def _retry_delay(e):
    """Segundos a esperar antes de reintentar la primaria, sacados del error si están
    (Gemini suele mandar 'retryDelay: 42s'). None si no se puede saber."""
    import re
    s = str(e)
    m = (re.search(r"retry.?delay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)", s, re.I)
         or re.search(r"retry in (\d+(?:\.\d+)?)\s*s", s, re.I))
    if m:
        try:
            return float(m.group(1)) + 2
        except Exception:  # noqa: BLE001
            pass
    return None


# Cada cuánto se RE-PRUEBA la primaria aunque esté en cooldown, para detectar que ya volvió
# (recuperación automática rápida sin esperar todo el cooldown). Los 429 son baratos.
_REPROBE_PRIMARIA = 120

_NOMBRE_IA = {
    "GeminiIA": "Gemini", "GroqCloudIA": "Groq", "CerebrasIA": "Cerebras", "ClaudeIA": "Claude",
    "OpenAIIA": "ChatGPT", "GrokIA": "Grok", "DeepSeekIA": "DeepSeek", "MistralIA": "Mistral",
    "OpenRouterIA": "OpenRouter", "LocalIA": "IA local", "DeepSeekLocalIA": "DeepSeek local"}


def _nombre_ia(prov):
    """Nombre amistoso del motor de IA (para los avisos al cliente)."""
    n = type(prov).__name__
    return _NOMBRE_IA.get(n, n.replace("IA", "") or n)


class MultiIA(ProveedorIA):
    """Multi-IA con RESPALDO EN CADENA: usa la primaria y, si se queda SIN CUOTA (429)
    o falla, salta sola a la secundaria y, si también falla, a la terciaria.
    Identidad del cliente: Gemini primaria -> Cerebras secundaria -> Groq terciaria.
    La voz siempre es Charon (Gemini)."""

    def __init__(self, primaria, secundaria=None, terciaria=None, gestor=None):
        self.primaria = primaria
        self.secundaria = secundaria
        self.terciaria = terciaria
        # Cadena de respaldo, en orden, con las IAs que existan (2 o 3+).
        self.cadena = [p for p in (primaria, secundaria, terciaria) if p]
        self.gestor = gestor          # para marcar bien qué motor se agotó (estado real)
        self._primaria_hasta = 0.0    # epoch: hasta cuándo NO consultar la primaria (sin cuota)
        self._ultimo_probe = 0.0      # epoch: última vez que se PROBÓ la primaria (re-probe periódico)
        self._aviso_cambio_hasta = {}  # id(prov) -> epoch: dedup del aviso "cambié de IA" al canal
        self.ultimo_proveedor = None  # nombre del motor que respondió por ÚLTIMA vez (observabilidad real)
        # La primaria falla rápido ante 429 -> el respaldo responde al instante.
        if hasattr(primaria, "sin_reintento_429"):
            primaria.sin_reintento_429 = True

    def _marcar_agotada(self, prov, e):
        """Refleja en el gestor qué motor se quedó SIN CUOTA DIARIA (así el estado no dice
        'Groq: disponible' cuando en realidad se agotó su cuota diaria de tokens). Se guía por
        el TIPO real del proveedor (Gemini/Groq), no por su posición en la cadena."""
        if not self.gestor or not es_por_dia(e):
            return
        try:
            if isinstance(prov, GeminiIA):
                self.gestor.agotada_gemini()
            elif isinstance(prov, GroqCloudIA):
                self.gestor.agotada_groq()
        except Exception:  # noqa: BLE001
            pass

    def _usar_primaria(self):
        import time
        if len(self.cadena) == 1:
            return True
        ahora = time.time()
        if ahora >= self._primaria_hasta:
            return True
        # RE-PROBE periódico: aunque la primaria siga en cooldown, se la vuelve a probar cada
        # _REPROBE_PRIMARIA seg. Así, si la primaria (ej. Gemini) ya volvió y la secundaria está
        # caída, se vuelve a usar la primaria SOLA -> la recuperación es automática, no espera todo
        # el cooldown. Si sigue sin cuota, falla rápido y el respaldo responde igual.
        return (ahora - self._ultimo_probe) >= _REPROBE_PRIMARIA

    def _marcar_sin_cuota(self, e):
        import time
        import logging
        # Cooldown REAL según el motivo:
        #  · límite por DÍA agotado  -> largo (10 min y re-chequea; el gestor sabe el reinicio real).
        #  · límite por MINUTO / 503 -> corto (lo que diga retryDelay, o pocos segundos).
        if es_por_dia(e):
            espera, motivo = 600, "sin cuota diaria"
        else:
            espera = _retry_delay(e) or (20 if _transitorio(e) else 40)
            motivo = "con alta demanda" if _transitorio(e) else "con límite por minuto"
        primera = time.time() >= self._primaria_hasta
        self._primaria_hasta = time.time() + espera
        if primera:                          # avisar UNA sola vez (no en cada mensaje)
            logging.getLogger("ia").warning(
                "IA primaria %s -> uso la secundaria por ~%ss.", motivo, int(espera))

    def _fallback(self, e):
        return self.secundaria and (_es_sin_cuota(e) or _transitorio(e))

    def _orden(self):
        """Orden de intento: la primaria primero salvo que esté en cooldown (ahí va al final).
        SIEMPRE incluye a TODA la cadena, así NUNCA declaramos 'sin cuota' sin probarlas todas."""
        if len(self.cadena) <= 1 or self._usar_primaria():
            return list(self.cadena)
        return self.cadena[1:] + self.cadena[:1]   # primaria en cooldown -> al final

    def _avisar_cambio(self, agotada, siguiente):
        """Avisa al canal del cliente (vía gestor -> notificar) que una IA se quedó sin cuota y que
        se pasa AUTOMÁTICAMENTE a la siguiente, para que el cliente vea cómo va todo. Dedup: una vez
        por IA cada ~5 min. Gemini y Groq ya los anuncia el GestorCuota (por cuota); acá se avisan
        LOS DEMÁS motores de la cadena (Cerebras, Claude, etc.), así se cubre CUALQUIER IA."""
        if not self.gestor or isinstance(agotada, (GeminiIA, GroqCloudIA)):
            return
        import time
        ahora = time.time()
        key = id(agotada)
        if ahora < self._aviso_cambio_hasta.get(key, 0):
            return
        self._aviso_cambio_hasta[key] = ahora + 300
        try:
            self.gestor._emitir(
                "advertencia",
                f"🔁 *{_nombre_ia(agotada)}* se quedó sin consultas por ahora. "
                f"Sigo automáticamente con *{_nombre_ia(siguiente)}*.")
        except Exception:  # noqa: BLE001
            pass

    def chat(self, system, prompt, json_out=True, max_tokens=None):
        import time
        ultimo = None
        orden = self._orden()
        for i, prov in enumerate(orden):
            if prov is self.primaria:
                self._ultimo_probe = time.time()      # registramos el intento (re-probe periódico)
            try:
                r = prov.chat(system, prompt, json_out, max_tokens)
                self.ultimo_proveedor = type(prov).__name__   # verdad: quién respondió
                if prov is self.primaria:
                    self._primaria_hasta = 0.0        # anduvo -> limpiar cooldown
                return r
            except Exception as e:  # noqa: BLE001
                ultimo = e
                if prov is self.primaria:
                    self._marcar_sin_cuota(e)
                self._marcar_agotada(prov, e)         # estado real por motor
                siguiente = orden[i + 1] if i + 1 < len(orden) else None
                if siguiente is not None and _es_sin_cuota(e):
                    self._avisar_cambio(prov, siguiente)   # avisá al cliente el cambio de IA
                continue                              # probar la siguiente IA antes de rendirse
        # Si el ÚLTIMO error NO es cuota diaria (fue por-minuto / alta demanda momentánea),
        # un reintento corto del RESPALDO con más cuota suele salvarlo (se recupera en segundos).
        respaldo = self.cadena[1] if len(self.cadena) > 1 else None
        if ultimo is not None and respaldo and not es_por_dia(ultimo):
            time.sleep(min(_retry_delay(ultimo) or 3, 6))
            try:
                r = respaldo.chat(system, prompt, json_out, max_tokens)
                self.ultimo_proveedor = type(respaldo).__name__
                return r
            except Exception as e:  # noqa: BLE001
                ultimo = e
                self._marcar_agotada(respaldo, e)
        raise ultimo if ultimo else RuntimeError("sin IA disponible")

    def chat_stream(self, system, prompt):
        """Streaming con respaldo EN CADENA: prueba en orden las IAs con chat_stream; si una
        falla SIN haber emitido nada, pasa a la siguiente; si ya emitió, no re-emite. Último
        recurso: chat normal (una sola pieza), que a su vez tiene toda la cadena de respaldo."""
        import time
        orden = self._orden()
        for i, prov in enumerate(orden):
            if not hasattr(prov, "chat_stream"):
                continue
            if prov is self.primaria:
                self._ultimo_probe = time.time()     # re-probe periódico de la primaria
            emitido = False
            try:
                for ch in prov.chat_stream(system, prompt):
                    emitido = True
                    yield ch
                if prov is self.primaria:
                    self._primaria_hasta = 0.0
                return
            except Exception as e:  # noqa: BLE001
                if prov is self.primaria:
                    self._marcar_sin_cuota(e)
                self._marcar_agotada(prov, e)
                if emitido:                    # ya salió texto -> no duplicar
                    raise
                siguiente = orden[i + 1] if i + 1 < len(orden) else None
                if siguiente is not None and _es_sin_cuota(e):
                    self._avisar_cambio(prov, siguiente)   # avisá el cambio de IA (igual que chat)
                continue                       # nada emitido -> probar la siguiente
        yield self.chat(system, prompt, json_out=False)   # último recurso: sin streaming

    def transcribir(self, audio_bytes, mime="audio/ogg", idioma=None):
        """Transcribe RÁPIDO. Motores reales DISTINTOS: Gemini (nativo) y Groq (Whisper nativo);
        Cerebras/DeepSeek-local/etc. delegan su transcribe en Gemini -> son redundantes y solo
        malgastan un intento contra la Gemini agotada. Probamos cada motor UNA vez."""
        motores, vistos = [], set()
        for prov in self._orden():
            if not hasattr(prov, "transcribir"):
                continue
            clave = "groq" if isinstance(prov, GroqCloudIA) else "gemini"   # motor real
            if clave in vistos:
                continue
            vistos.add(clave)
            motores.append((clave, prov))
        # VELOCIDAD: preferimos Groq (Whisper nativo) SIEMPRE para transcribir, porque es MUCHO más
        # rápido que la transcripción de Gemini (~1-2s vs ~5s) y es gratis. Si Groq no está o se
        # agotó, cae a Gemini. NO cambia la voz/identidad (sigue Charon/Gemini); solo el audio->texto.
        motores.sort(key=lambda m: 0 if m[0] == "groq" else 1)
        import time
        ultimo = None
        for _clave, prov in motores:
            if prov is self.primaria:
                self._ultimo_probe = time.time()     # re-probe periódico de la primaria
            try:
                return prov.transcribir(audio_bytes, mime, idioma=idioma)
            except Exception as e:  # noqa: BLE001
                ultimo = e
                if prov is self.primaria and self._fallback(e):
                    self._marcar_sin_cuota(e)
                continue
        raise ultimo or RuntimeError("ninguna IA pudo transcribir el audio")

    def _voz_backend(self):
        # La voz es SIEMPRE Charon (Gemini). Busca un Gemini real en la cadena; si no, usa el
        # Gemini que cada proveedor delega en self._gem para la voz.
        for prov in self.cadena:
            if isinstance(prov, GeminiIA):
                return prov
        for prov in self.cadena:
            gem = getattr(prov, "_gem", None)
            if gem is not None:
                return gem
        return self.primaria

    def voz_pcm(self, texto):
        return self._voz_backend().voz_pcm(texto)

    async def voz_stream(self, texto):
        async for c in self._voz_backend().voz_stream(texto):
            yield c


def _single(cfg, gestor=None):
    cfg = cfg or {}
    prov = (cfg.get("proveedor") or "gemini").lower()
    if prov == "local":
        return LocalIA(cfg)
    if prov == "deepseek":
        return DeepSeekIA(cfg)
    if prov == "claude":
        return ClaudeIA(cfg)
    if prov in ("openai", "chatgpt"):
        return OpenAIIA(cfg)
    if prov == "grok":
        return GrokIA(cfg)
    if prov == "openrouter":
        return OpenRouterIA(cfg)
    if prov == "cerebras":
        return CerebrasIA(cfg)
    if prov == "mistral":
        return MistralIA(cfg)
    if prov in ("deepseek_local", "deepseek-local", "deepseeklocal"):
        return DeepSeekLocalIA(cfg)
    if prov == "groq":
        return GroqCloudIA(cfg, gestor=gestor)
    return GeminiIA(cfg, gestor=gestor)


def _respaldo(cfg, bloque, ya_usados, gestor=None):
    """Construye una IA de respaldo desde un sub-bloque (cfg['secundario']/['terciario']).
    Devuelve (proveedorIA, nombre) o (None, None) si no aplica o repite un proveedor ya usado.
    Cada respaldo se evalúa por SÍ MISMO: NO hereda el 'pago' ni el modelo de la primaria."""
    b = bloque or {}
    prov = (b.get("proveedor") or "").lower()
    if not prov or prov in ya_usados:
        return None, None
    subcfg = {**cfg, **b, "proveedor": prov}       # hereda gemini_api_key (voz)
    for k in ("secundario", "terciario"):
        subcfg.pop(k, None)
    if "ilimitada" not in b:
        subcfg.pop("ilimitada", None)
    if "plan" not in b:
        subcfg.pop("plan", None)
    if "modelo_texto" not in b:
        subcfg["modelo_texto"] = "auto"            # que 'auto' elija el mejor modelo de ESA key
    return _single(subcfg, gestor=gestor), prov


def crear_ia(cfg, gestor=None):
    """Proveedor de IA de TEXTO, elegible por cliente. La VOZ siempre es Charon.
    Respaldo automático EN CADENA: primaria -> cfg['secundario'] -> cfg['terciario'] (cuando
    la primaria se queda sin cuota, salta sola a la siguiente). Compat: cfg['proveedor_secundario'].
    Config de esta empresa: Gemini primaria -> Cerebras secundaria -> Groq terciaria.
    ROBUSTO a config editada a mano: si falta el secundario pero hay terciario, igual se usa;
    ignora bloques vacíos o que repiten un proveedor ya en la cadena."""
    cfg = cfg or {}
    primaria = _single(cfg, gestor=gestor)
    usados = {(cfg.get("proveedor") or "gemini").lower()}
    # Bloques de respaldo en orden; compat 'proveedor_secundario' si no hay 'secundario'.
    bloques = [cfg.get("secundario"), cfg.get("terciario")]
    if cfg.get("proveedor_secundario") and not cfg.get("secundario"):
        bloques[0] = {"proveedor": cfg.get("proveedor_secundario")}
    respaldos = []
    for b in bloques:
        obj, nom = _respaldo(cfg, b, usados, gestor=gestor)
        if obj:
            respaldos.append(obj)
            usados.add(nom)
    if not respaldos:
        return primaria
    return MultiIA(primaria, *respaldos[:2], gestor=gestor)   # hasta 3 IAs en cadena


# ---------------------------------------------------------------------------
# VOZ = identidad de ITHOS. Es SIEMPRE Charon (Gemini), tanto en nube como
# para clientes con texto local. Solo un cliente que exija que NADA salga de su
# red usaría voz local (clon de Charon con XTTS), aceptando calidad algo menor.
# ---------------------------------------------------------------------------
VOZ_IDENTIDAD = "Charon"


class LocalVoz(ProveedorIA):
    """Voz local (clon XTTS de la voz ITHOS) para privacidad total. Premium,
    a implementar; necesita GPU ~8-12GB. No idéntica a Charon pero misma identidad."""

    def __init__(self, cfg):
        self.cfg = cfg

    def voz_pcm(self, texto):
        raise NotImplementedError("Voz local (clon XTTS de ITHOS) — a implementar")

    async def voz_stream(self, texto):
        raise NotImplementedError
        yield b""


def crear_texto(cfg, gestor=None):
    """Proveedor de razonamiento (triage/respuestas). Pluggable por cliente."""
    return crear_ia(cfg, gestor=gestor)


def crear_voz(cfg, gestor=None):
    """Proveedor de VOZ. SIEMPRE Charon por defecto (identidad ITHOS), aunque el
    texto sea local. Voz local (clon) solo si el cliente lo exige explícitamente."""
    cfg = dict(cfg or {})
    cfg.setdefault("voz", VOZ_IDENTIDAD)
    if (cfg.get("proveedor") or "gemini").lower() == "local":
        return LocalVoz(cfg)
    return GeminiIA(cfg, gestor=gestor)
