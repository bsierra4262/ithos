#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ITHOS — cifrado EN REPOSO de los datos sensibles del cliente (grado militar).

Los secretos de cada empresa (claves de IA, tokens de GLPI, contraseñas de la base de fichajes,
token de MercadoPago, contraseña de agente, tokens de canales, etc.) NO se guardan en claro en
`clientes.json`: se cifran con **AES-256-GCM** (cifrado autenticado, el mismo estándar que se usa
para datos clasificados) usando una **clave maestra separada de los datos**.

Modelo de amenaza (honesto): esto es **cifrado en reposo**, no "zero-access" estilo ProtonMail. El
Gestor DEBE poder usar los secretos 24/7 (llamar a Gemini, entrar a GLPI, leer la DB, cobrar), así
que el proceso en ejecución los descifra en memoria. Lo que garantiza es que si te roban el archivo
`clientes.json` o un backup **sin la clave maestra**, no pueden descifrar nada (AES-256-GCM sin la
clave es computacionalmente inviable).

Clave maestra (`ITHOS_MASTER_KEY`, en el `.env` del server, NUNCA en el repo/backup de datos):
  · base64 de 32 bytes (ideal, generá con `openssl rand -base64 32`), o
  · una passphrase cualquiera (se deriva a 32 bytes con SHA-256).
Si no está seteada, se genera y persiste una clave en un archivo aparte (solo para dev/demo, con
aviso): en producción SIEMPRE conviene fijar `ITHOS_MASTER_KEY` en el `.env`.
"""
import os
import base64
import hashlib
import logging

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("cifrado")

PREFIJO = "enc:v1:"                      # marca de valor cifrado (para no doble-cifrar ni fallar en claro)
BASE = os.path.dirname(os.path.abspath(__file__))

# Claves cuyos VALORES son secretos y hay que cifrar (por nombre, en cualquier nivel del cliente).
_SENSIBLE_SUBSTR = ("token", "password", "passwd", "pwd", "secret",
                    "api_key", "apikey", "access_key", "clave", "client_secret")
# En la RAÍZ del cliente, `api_key` es el IDENTIFICADOR (lookup + URL del dashboard): NO se cifra.
_SALTAR_RAIZ = {"api_key"}

_clave_cache = None


def _archivo_clave() -> str:
    return (os.environ.get("ITHOS_DATA") or BASE) + os.sep + "_gestor_master.key"


def _clave() -> bytes:
    """32 bytes de clave maestra. De `ITHOS_MASTER_KEY` (recomendado) o de un archivo persistente."""
    global _clave_cache
    if _clave_cache is not None:
        return _clave_cache
    env = (os.environ.get("ITHOS_MASTER_KEY") or "").strip()
    if env:
        try:
            raw = base64.b64decode(env)
            _clave_cache = raw if len(raw) == 32 else hashlib.sha256(env.encode("utf-8")).digest()
        except (ValueError, TypeError):
            _clave_cache = hashlib.sha256(env.encode("utf-8")).digest()
        return _clave_cache
    # Fallback (dev/demo): clave persistida en un archivo. En prod, fijá ITHOS_MASTER_KEY en el .env.
    ruta = _archivo_clave()
    try:
        with open(ruta, "rb") as f:
            _clave_cache = base64.b64decode(f.read().strip())
        if len(_clave_cache) == 32:
            return _clave_cache
    except (OSError, ValueError):
        pass
    _clave_cache = AESGCM.generate_key(bit_length=256)
    try:
        with open(ruta, "wb") as f:
            f.write(base64.b64encode(_clave_cache))
        try:
            os.chmod(ruta, 0o600)          # best-effort (no-op en Windows)
        except OSError:
            pass
        log.warning("ITHOS_MASTER_KEY no está seteada: usé una clave generada en %s. "
                    "En PRODUCCIÓN fijá ITHOS_MASTER_KEY en el .env (aparte de los datos).", ruta)
    except OSError:
        log.warning("ITHOS_MASTER_KEY no está seteada y no pude persistir la clave; se usa una "
                    "clave efímera (los datos cifrados no se van a poder descifrar tras reiniciar).")
    return _clave_cache


def cifrar(texto: str) -> str:
    """Cifra un string con AES-256-GCM. Idempotente: si ya está cifrado, lo devuelve igual."""
    if not isinstance(texto, str) or texto == "" or texto.startswith(PREFIJO):
        return texto
    aes = AESGCM(_clave())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, texto.encode("utf-8"), None)
    return PREFIJO + base64.b64encode(nonce + ct).decode("ascii")


def descifrar(valor: str) -> str:
    """Descifra un valor con prefijo `enc:v1:`. Si NO está cifrado, lo devuelve tal cual (compat)."""
    if not isinstance(valor, str) or not valor.startswith(PREFIJO):
        return valor
    try:
        raw = base64.b64decode(valor[len(PREFIJO):])
        aes = AESGCM(_clave())
        return aes.decrypt(raw[:12], raw[12:], None).decode("utf-8")
    except Exception as e:  # noqa: BLE001
        log.error("No se pudo descifrar un valor (¿ITHOS_MASTER_KEY cambió?): %s", e)
        return valor


def _es_sensible(clave: str) -> bool:
    c = str(clave).lower()
    return any(s in c for s in _SENSIBLE_SUBSTR)


def _procesar(obj, fn, raiz=False):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if raiz and k in _SALTAR_RAIZ:
                out[k] = v
            elif isinstance(v, (dict, list)):
                out[k] = _procesar(v, fn, raiz=False)
            elif isinstance(v, str) and _es_sensible(k):
                out[k] = fn(v)
            else:
                out[k] = v
        return out
    if isinstance(obj, list):
        return [_procesar(x, fn, raiz=False) for x in obj]
    return obj


def cifrar_cliente(c: dict) -> dict:
    """Devuelve una COPIA del cliente con los campos sensibles cifrados (para escribir a disco)."""
    return _procesar(c, cifrar, raiz=True)


def descifrar_cliente(c: dict) -> dict:
    """Devuelve una COPIA del cliente con los campos sensibles descifrados (para usar en memoria)."""
    return _procesar(c, descifrar, raiz=True)


def cifrar_datos(data: dict) -> dict:
    """Cifra los secretos de todos los clientes de `data` (dict con 'clientes'). No muta el original."""
    d = dict(data or {})
    d["clientes"] = [cifrar_cliente(c) for c in (data or {}).get("clientes", [])]
    return d


def descifrar_datos(data: dict) -> dict:
    """Descifra los secretos de todos los clientes de `data`. No muta el original."""
    d = dict(data or {})
    d["clientes"] = [descifrar_cliente(c) for c in (data or {}).get("clientes", [])]
    return d


def escribir_json(ruta: str, obj) -> None:
    """Escribe JSON de forma segura. Intenta rename ATÓMICO (mismo FS); si el destino es un
    **bind-mount de un solo archivo** (Docker), el rename da EBUSY/ EXDEV → cae a escribir EN EL
    LUGAR (truncar + escribir), que es la única forma sobre un mount de archivo."""
    import json
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, ruta)                    # atómico cuando se puede
    except OSError:
        with open(tmp, encoding="utf-8") as r, open(ruta, "w", encoding="utf-8") as w:
            w.write(r.read())                    # bind-mount de archivo: escribir en el lugar
        try:
            os.remove(tmp)
        except OSError:
            pass


def migrar_archivo(ruta: str) -> int:
    """Cifra en el lugar los secretos de un clientes.json que todavía esté en claro (idempotente:
    lo ya cifrado no se toca). Devuelve la cantidad de empresas procesadas."""
    import json
    with open(ruta, encoding="utf-8") as f:
        data = json.load(f)
    cif = cifrar_datos(data)
    escribir_json(ruta, cif)
    return len(cif.get("clientes", []))


if __name__ == "__main__":     # uso: python -m comun.cifrado <ruta_clientes.json>
    import sys
    destino = sys.argv[1] if len(sys.argv) > 1 else "clientes.json"
    n = migrar_archivo(destino)
    print(f"Cifrado en reposo aplicado a {n} empresa(s) en {destino}")
