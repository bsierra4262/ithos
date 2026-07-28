#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cerebro del Central: convierte un EVENTO de un agente en una lista de COMANDOS.

Fase 1 (esqueleto): arma las frases de forma determinista (sin IA todavía).
Fase 2: acá se enchufa Gemini (voz/triage) y el resto de la lógica que ya tenemos.
El Central NO reproduce audio: solo decide qué debe decir/hacer el agente.
"""

import os
import json
import random
from datetime import datetime

from protocolo import EV_ACCESO, EV_TICKET, EV_PRECACHE, AC_DECIR, comando

ALERTAS = [
    "Acceso denegado.",
    "Error de autenticación.",
    "Identificación no válida.",
    "Entrada restringida.",
]

# Plantillas de BIENVENIDA (entrada). {s} = saludo COHERENTE con la hora (Buenos días / Buenas tardes /
# Buenas noches, según la zona del cliente), {n} = nombre de la persona, {emp} = empresa del CLIENTE. El
# saludo en vivo se elige por (persona + DÍA): cada día un saludo distinto (variedad diaria), determinista
# para ese día -> coincide con una variante pre-cacheada -> cache hit -> instantáneo. Se pre-cachean TODAS
# las variantes en las 3 franjas horarias.
BIENVENIDAS = [
    "{s}, {n}. Bienvenido a {emp}.",
    "{s}, {n}. Un placer tenerlo de vuelta en {emp}.",
    "{s}, {n}. Qué gusto tenerlo de regreso en {emp}.",
    "{s}, {n}. Que tenga una buena jornada en {emp}.",
    "{s}, {n}. Bienvenido nuevamente a {emp}.",
    "{s}, {n}. Un placer recibirlo en {emp}.",
]

# Plantillas de SALIDA (terminal de salida). Misma lógica de variedad diaria que la bienvenida.
DESPEDIDAS = [
    "Hasta luego, {n}. Buen viaje.",
    "Que tenga una buena jornada, {n}.",
    "Hasta pronto, {n}.",
    "Nos vemos, {n}. Que le vaya bien.",
    "Buen regreso a casa, {n}.",
    "Que descanse, {n}. Nos vemos mañana.",
]

# Frecuencia por defecto según el tipo de terminal (si la regla no la fija).
_FREC_DEFAULT = {"entrada": "1_por_dia", "salida": "1_por_dia", "sala": "siempre"}

# Dedup: la ENTRADA/SALIDA se dicen 1 vez por día por persona (no cada fichada); la SALA se repite
# siempre. Estado en memoria del gestor por (cliente, tipo): {(cliente,tipo): (fecha, set|contador)}.
_saludados_hoy = {}
_saludados_alguna = {}   # frecuencia '1_por_persona' (una sola vez de por vida): {cliente: set(nombre|tipo)}

# El dedup PERSISTE en disco: si el central se reinicia durante el día, NO vuelve a saludar a quien ya
# fichó (la 2ª fichada del día sigue en silencio). Se guarda en ITHOS_DATA.
_DATA = os.environ.get("ITHOS_DATA") or os.path.join(os.path.expanduser("~"), ".ithos")
try:
    os.makedirs(_DATA, exist_ok=True)
except OSError:
    _DATA = os.path.dirname(os.path.abspath(__file__))
_ESTADO_SALUDOS = os.path.join(_DATA, "portero_saludados.json")

# Saludo coherente con la hora (zona del cliente).
_SALUDOS_HORA = ["Buenos días", "Buenas tardes", "Buenas noches"]


def _saludo_hora(tz, hora=None):
    """'Buenos días' (05-11), 'Buenas tardes' (12-19) o 'Buenas noches' (20-04) en la zona del cliente."""
    if hora is None:
        try:
            from zoneinfo import ZoneInfo
            hora = (datetime.now(ZoneInfo(tz)) if tz else datetime.now()).hour
        except Exception:  # noqa: BLE001
            hora = datetime.now().hour
    if 5 <= hora < 12:
        return "Buenos días"
    if 12 <= hora < 20:
        return "Buenas tardes"
    return "Buenas noches"


def _cargar_saludados():
    try:
        d = json.load(open(_ESTADO_SALUDOS, encoding="utf-8"))
        for k, v in (d.get("hoy") or {}).items():
            cli, _, tipo = k.partition("\t")
            _saludados_hoy[(cli, tipo)] = (v.get("fecha"), set(v.get("nombres") or []))
        for cli, lst in (d.get("alguna") or {}).items():
            _saludados_alguna[cli] = set(lst or [])
    except (OSError, ValueError):
        pass


def _guardar_saludados():
    try:
        hoy = {f"{cli}\t{tipo}": {"fecha": f, "nombres": sorted(nombres)}
               for (cli, tipo), (f, nombres) in _saludados_hoy.items()}
        alguna = {cli: sorted(s) for cli, s in _saludados_alguna.items()}
        json.dump({"hoy": hoy, "alguna": alguna},
                  open(_ESTADO_SALUDOS, "w", encoding="utf-8"), ensure_ascii=False)
    except OSError:
        pass


_cargar_saludados()


def _conf(cliente):
    return cliente if isinstance(cliente, dict) else {}


def _empresa_abrev(cliente):
    """Nombre y abreviatura de la empresa DEL CLIENTE para el saludo (no 'ITHOS')."""
    c = _conf(cliente)
    empresa = (c.get("empresa_saludo") or c.get("nombre") or
               (cliente if isinstance(cliente, str) else "") or "la empresa").strip()
    abrev = (c.get("abreviatura") or "").strip()
    return empresa, abrev


def _hoy(tz):
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d") if tz else datetime.now().strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return datetime.now().strftime("%Y-%m-%d")


def _dia_ordinal(tz):
    """Número de día ABSOLUTO en la zona del cliente (cambia cada día). Se usa para rotar el saludo:
    (base_persona + día) % nº_plantillas -> distinto saludo cada día, igual para todos ese día."""
    try:
        from zoneinfo import ZoneInfo
        d = datetime.now(ZoneInfo(tz)) if tz else datetime.now()
    except Exception:  # noqa: BLE001
        d = datetime.now()
    return d.toordinal()


def _ya_saludado(cliente_id, nombre, tipo, frecuencia, tz):
    """True si NO hay que saludar a esa persona ahora (según la frecuencia de ESE tipo de terminal):
      - 'siempre'        -> nunca dedup (siempre saluda).
      - '1_por_dia'      -> una vez por día por persona (se resetea al cambiar el día).
      - '1_por_persona'  -> una sola vez de por vida (no se resetea).
    Entrada y salida se cuentan por SEPARADO (clave por tipo)."""
    if frecuencia == "siempre" or not nombre:
        return False
    if frecuencia == "1_por_persona":
        vistos = _saludados_alguna.setdefault(cliente_id, set())
        k = f"{tipo}|{nombre}"
        if k in vistos:
            return True
        vistos.add(k)
        _guardar_saludados()
        return False
    # '1_por_dia' (default): dedup por día, por tipo
    hoy = _hoy(tz)
    ck = (cliente_id, tipo)
    fecha, nombres = _saludados_hoy.get(ck, (None, set()))
    if fecha != hoy:                       # cambió el día -> se resetea solo
        nombres = set()
        _saludados_hoy[ck] = (hoy, nombres)
    if nombre in nombres:
        return True                        # ya lo saludamos hoy -> la 2ª fichada queda en silencio
    nombres.add(nombre)
    _guardar_saludados()
    return False


def _clasificar(device, terminales, es_fallo=False, tipo_agente=None):
    """Decide (tipo, saludo_custom, frecuencia) de un fichaje según las REGLAS del cliente.
    `terminales`: lista de reglas {match, tipo, saludo, frecuencia}; gana la 1ª cuyo `match` esté
    contenido (sin distinguir mayúsculas) en el identificador del dispositivo (device_name en IVMS;
    nombre/IP del lector en las marcas con API). Sin regla que matchee -> defaults COMPATIBLES con el
    comportamiento previo (sala técnica = sala/siempre; resto = entrada/1_por_día). Si el agente ya
    mandó un `tipo` (agente viejo, sin device), se respeta."""
    if es_fallo:
        return "alerta", "", "siempre"
    dev = (device or "").lower()
    for t in terminales or []:
        m = (t.get("match") or "").strip().lower()
        if m and m in dev:
            tipo = (t.get("tipo") or "entrada").lower()
            tipo = "entrada" if tipo == "bienvenida" else tipo
            frec = (t.get("frecuencia") or _FREC_DEFAULT.get(tipo, "1_por_dia"))
            return tipo, (t.get("saludo") or "").strip(), frec
    if device:                                  # hay device pero ninguna regla: defaults por nombre
        if "sala tecnica" in dev or "sala técnica" in dev:
            return "sala", "", "siempre"
        return "entrada", "", "1_por_dia"
    # agente viejo sin device: usar el tipo que mandó (compat total)
    tipo = (tipo_agente or "entrada").lower()
    tipo = "entrada" if tipo == "bienvenida" else tipo
    return tipo, "", _FREC_DEFAULT.get(tipo, "1_por_dia")


def _nombre_norm(nombre):
    """Nombre CONSISTENTE para el saludo (venga del lector que venga): colapsa espacios y, si viene
    'Apellido, Nombre' (formato biométrico habitual), lo pasa a 'Nombre Apellido'. Así el portero
    saluda igual en la bienvenida y en la sala técnica. Punto ÚNICO para TODOS los integradores."""
    n = " ".join(str(nombre or "").split())
    if "," in n:
        ap, _, nom = n.partition(",")
        nom, ap = " ".join(nom.split()), " ".join(ap.split())
        if nom and ap:
            return f"{nom} {ap}"
    return n


def _frase_acceso(datos, empresa="la empresa", abrev="", saludo_custom="", dia=0, variante=None, saludo_h="Hola"):
    """Frase del portero. `dia` rota el saludo día a día (entrada/salida); `variante` fuerza una plantilla
    concreta (se usa al pre-cachear TODAS las variantes); `saludo_h` es el saludo coherente con la hora
    (Buenos días/tardes/noches) que va en la ENTRADA. La SALA y los saludos personalizados por terminal
    son ÚNICOS (sin variedad diaria). El nombre de la empresa es estable por persona."""
    nombre = _nombre_norm(datos.get("nombre", ""))
    tipo = datos.get("tipo", "entrada")
    tipo = "entrada" if tipo == "bienvenida" else tipo
    if tipo == "alerta":
        return random.choice(ALERTAS), True     # la alerta puede variar (no se cachea)
    opciones_emp = [e for e in (empresa, abrev) if e] or ["la empresa"]
    base = sum(ord(c) for c in nombre) if nombre else 0
    emp = opciones_emp[base % len(opciones_emp)]
    # Saludo PERSONALIZADO por terminal (si el cliente lo cargó): admite {n}=nombre, {emp}=empresa, {s}=hora.
    if saludo_custom:
        try:
            return saludo_custom.format(n=nombre, emp=emp, nombre=nombre, empresa=emp, s=saludo_h), True
        except Exception:  # noqa: BLE001 (plantilla mal escrita -> usar texto tal cual)
            return saludo_custom, True
    if tipo == "sala":
        return f"Acceso autorizado, {nombre}. Entrando a la Sala Técnica.", True
    # ENTRADA / SALIDA: variedad. En vivo -> plantilla por (persona + día); al pre-cachear -> `variante`
    # explícita (0..N-1). Determinista para ese día => coincide con la variante pre-cacheada (cache hit).
    # La ENTRADA además arranca con el saludo coherente con la hora ({s}); la SALIDA no lo usa.
    plantillas = DESPEDIDAS if tipo == "salida" else BIENVENIDAS
    i = variante if variante is not None else (base + dia)
    return plantillas[i % len(plantillas)].format(n=nombre, emp=emp, s=saludo_h), True


def _textos_precache(n, tipo, empresa, abrev, variante):
    """Textos a pre-cachear para (persona, tipo, variante). La ENTRADA se cachea en las 3 franjas horarias
    (Buenos días / Buenas tardes / Buenas noches) para que sea instantánea a cualquier hora; el resto, una."""
    if tipo == "entrada":
        return [_frase_acceso({"nombre": n, "tipo": tipo}, empresa, abrev, variante=variante, saludo_h=s)[0]
                for s in _SALUDOS_HORA]
    return [_frase_acceso({"nombre": n, "tipo": tipo}, empresa, abrev, variante=variante)[0]]


def procesar(cliente, evento, datos):
    """Devuelve una lista de comandos (dicts) para el agente."""
    datos = datos or {}
    empresa, abrev = _empresa_abrev(cliente)
    terminales = _conf(cliente).get("terminales") or []
    if evento == EV_ACCESO:
        # El central clasifica el fichaje según las reglas del cliente (por device). El agente manda el
        # device crudo; un agente viejo (sin device) manda 'tipo' y se respeta (compat).
        tipo, saludo_custom, frecuencia = _clasificar(
            datos.get("device"), terminales, es_fallo=bool(datos.get("es_fallo")),
            tipo_agente=datos.get("tipo"))
        if tipo == "alerta":
            texto, cachear = _frase_acceso({**datos, "tipo": "alerta"}, empresa, abrev)
            return [comando(AC_DECIR, texto=texto, cachear=cachear)]
        nombre = _nombre_norm(datos.get("nombre", ""))
        cid = _conf(cliente).get("nombre") or (cliente if isinstance(cliente, str) else "cli")
        tz = _conf(cliente).get("zona_horaria", "")
        if _ya_saludado(cid, nombre, tipo, frecuencia, tz):
            return []                           # según la frecuencia de esta terminal -> no repetir
        texto, cachear = _frase_acceso({**datos, "tipo": tipo}, empresa, abrev, saludo_custom,
                                       dia=_dia_ordinal(tz), saludo_h=_saludo_hora(tz))
        return [comando(AC_DECIR, texto=texto, cachear=cachear)]
    if evento == EV_PRECACHE:
        # Pre-cacheo: mandamos con solo_cachear=True los saludos que ITHOS podría decir, para que la 1ª
        # fichada real de cada uno sea INSTANTÁNEA. Para ENTRADA/SALIDA se cachean TODAS las variantes
        # (así hay variedad diaria disponible desde el día 1); para SALA y saludos personalizados, 1 sola.
        nombres = datos.get("nombres") or []
        # Qué tipos con VARIEDAD (entrada siempre; salida solo si hay una terminal de salida configurada).
        tipos_var = {"entrada"}
        otros = [("sala", "")]                   # SALA y personalizados: saludo ÚNICO (sin variedad)
        for t in terminales:
            tp = (t.get("tipo") or "entrada").lower()
            tp = "entrada" if tp == "bienvenida" else tp
            saludo_custom = (t.get("saludo") or "").strip()
            if saludo_custom:
                otros.append((tp, saludo_custom))
            elif tp in ("entrada", "salida"):
                tipos_var.add(tp)
            else:
                otros.append((tp, ""))
        vistos, cmds = set(), []

        def _agregar(texto):
            if texto and texto not in vistos:
                vistos.add(texto)
                cmds.append(comando(AC_DECIR, texto=texto, cachear=True, solo_cachear=True))

        # ORDEN pensado para CUOTA limitada (Charon gratis = 10/día): COBERTURA primero, VARIEDAD después.
        # PASE 1 (cobertura): cada persona con su saludo ESENCIAL -> entrada var 0 + salida var 0 + sala +
        #   personalizados. Así, con poca cuota, TODOS tienen ya su saludo uniforme (entrada y sala).
        for n in nombres:
            for tipo in ("entrada", "salida"):
                if tipo in tipos_var:
                    for texto in _textos_precache(n, tipo, empresa, abrev, 0):
                        _agregar(texto)
            for tipo, saludo_custom in otros:
                texto, _ = _frase_acceso({"nombre": n, "tipo": tipo}, empresa, abrev, saludo_custom)
                _agregar(texto)
        # PASE 2 (variedad): las variantes EXTRA (1..N-1) de entrada/salida, plantilla por plantilla
        #   (todas las personas con el saludo 2, después el 3, ...). La variedad diaria se completa luego.
        for tipo, plantillas in (("entrada", BIENVENIDAS), ("salida", DESPEDIDAS)):
            if tipo not in tipos_var:
                continue
            for i in range(1, len(plantillas)):
                for n in nombres:
                    for texto in _textos_precache(n, tipo, empresa, abrev, i):
                        _agregar(texto)
        return cmds
    if evento == EV_TICKET:
        asunto = str(datos.get("asunto", "")).strip()
        return [comando(AC_DECIR,
                        texto=f"Atención. Ticket nuevo. {asunto}.",
                        cachear=False)]
    return []
