#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TODO lo que ITHOS escribe en un ticket, y los MARCADORES con los que después lo reconoce.

Está junto a propósito: son los textos que lee el cliente y el técnico, los que más se ajustan, y
cada uno lleva adentro una frase estable que el ciclo usa para saber qué se pidió y si ya se pidió.
Si se cambia un texto hay que conservar esa frase, o el ciclo deja de reconocerlo.
"""

import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)
from equipo import NOMBRES   # noqa: E402

# Firmas estables (subcadenas) de los textos de `pedir_confirmacion` y `recordar_confirmacion`.
# Si se cambian esos textos, mantener estas subcadenas dentro para que la detección siga andando.
_MARCA_CONFIRMACION = "su solicitud fue resuelta"
_MARCA_RECORDATORIO = "le recordamos que su ticket figura como resuelto"
# Marcador estable de que ITHOS le PIDIÓ ALGO AL CLIENTE y espera su respuesta. Cubre los DOS casos
# en que el ticket queda EN ESPERA por el cliente: (a) falta un DATO que le pedimos en la primera
# respuesta, y (b) tiene que CONFIRMAR/COORDINAR algo para que podamos avanzar. En los dos casos el
# ciclo le recuerda una vez por día hábil hasta que responda (y el SLA queda pausado en 'En espera').
_MARCA_ESPERA_CLIENTE = "a la espera de su respuesta"
_MARCA_PROCEDIMIENTO = "documentá paso a paso"   # nota interna que pide el procedimiento
_MARCA_RECORDATORIO_ESPERA = "le recordamos que su ticket está a la espera"
_MARCA_ESCALADA_ESPERA = "sigue sin respuesta del cliente"
_MARCA_SIN_ATENDER = "el cliente respondió y todavía no le contestamos"
_DIAS_HABILES_ESCALADA = 5        # días HÁBILES sin respuesta -> avisar al TÉCNICO ASIGNADO
_HORAS_SIN_ATENDER = 2            # horas HÁBILES sin contestarle al cliente -> avisar al técnico
# TODOS los recordatorios al cliente (espera por datos, espera por confirmación y confirmación de un
# ticket resuelto) salen UNO POR DÍA HÁBIL y SIEMPRE dentro del horario de atención del cliente
# (default Lun-Vie 09:00-18:00 en SU zona, `en_horario_atencion`): a la misma hora, nunca de noche
# ni un fin de semana. La hora es la de apertura: el primer ciclo del día que cae en horario.
_CIERRE_ESPERA = " Quedamos a la espera de su respuesta. Soporte ITH."

_ALCANCE_TXT = {
    "individual": "afecta al fichaje de UNA persona",
    "grupo": "afecta a VARIAS personas identificadas",
    "equipo": "hay un equipo caído: nadie ficha por ahí, aunque la sede tiene otro",
    "sede": "la SEDE se quedó sin fichaje: NADIE puede fichar ahí",
    "masivo": "afecta a varias sedes o al sistema completo",
}

# El modelo suele despedirse con su propia fórmula ("Quedo a la espera de tu respuesta. Soporte
# ITH"). Si sólo buscáramos el texto exacto del marcador, esa despedida no coincide y el cierre se
# agrega igual: el cliente termina leyendo la misma frase dos veces seguidas. Se reconoce cualquier
# variante (quedo/quedamos, tu/su, aguardo…) y se REEMPLAZA por la canónica, que es la que el ciclo
# necesita para saber que el ticket espera al cliente.
_RE_DESPEDIDA_ESPERA = re.compile(
    r"\s*(?:qued(?:o|amos)|estar(?:é|emos)|aguard(?:o|amos))\s+"
    r"(?:atentos?\s+)?a\s+la\s+espera\s+de\s+(?:tu|su|la)\s+"
    r"(?:respuesta|confirmaci[oó]n|respuesta\s+o\s+confirmaci[oó]n)\s*\.?"
    r"(?:\s*(?:atentamente\s*,?\s*)?(?:soporte\s+ith|saludos)\s*\.?)?\s*$",
    re.I)
# La firma del final ("Gracias, Soporte ITH", "Saludos, Soporte ITH", o el "Soporte ITH" solo).
# El cierre que agregamos ya termina firmado, así que sin sacar esto el cliente lee la firma DOS
# veces seguidas — que es exactamente lo que estaba pasando.
_RE_FIRMA_FINAL = re.compile(
    r"\s*(?:(?:muchas\s+)?gracias|saludos(?:\s+cordiales)?|atentamente|"
    r"desde\s+ya\s+(?:muchas\s+)?gracias)?\s*[,.;]?\s*(?:soporte\s+ith)\s*\.?\s*$", re.I)


def _nota_alcance(a, correcciones):
    """Nota PRIVADA que explica al técnico por qué el ticket entra con esa prioridad y en sus
    manos. Sale sólo cuando hubo que corregir la clasificación."""
    alc = a.get("alcance", "individual")
    visita = ("" if not a.get("requiere_visita") else
              " Hay que ir al lugar: se le pidió al cliente que confirme qué día y en qué franja "
              "horaria podemos pasar, así que el ticket queda EN ESPERA de esa coordinación (se le "
              "recuerda una vez por día hábil).")
    return ("Nota interna (el cliente no la ve): por lo que dice el ticket, "
            f"{_ALCANCE_TXT.get(alc, alc)}. Queda con prioridad {a.get('prioridad')} y asignado a "
            f"{NOMBRES.get(a.get('responsable'), a.get('responsable'))}.{visita} Ajustes "
            "aplicados: " + "; ".join(correcciones) + ".")


def _nota_respuesta_fuera_horario(dt, motivo=""):
    """Nota PRIVADA: el cliente respondió fuera del horario, así que el ticket espera al lunes en
    vez de dejar corriendo el SLA. El cliente NO ve esto."""
    cuando = dt.strftime("%d/%m a las %H:%M") if dt else "el próximo día hábil"
    extra = f" Dijo: «{motivo.strip()[:200]}»." if motivo else ""
    return ("Nota interna (el cliente no la ve): el cliente respondió FUERA del horario de atención."
            + extra + " Para que el SLA no corra de noche ni un fin de semana contra un equipo que "
            f"no está trabajando, el ticket queda EN ESPERA y vuelve solo a EN CURSO {cuando}. "
            "No hace falta hacer nada: se reabre automáticamente.")


def _nota_sin_atender(desde, horas):
    """Nota PRIVADA de supervisión: el cliente contestó y el técnico no respondió."""
    cuando = desde.strftime("%d/%m a las %H:%M") if desde else "hace un rato"
    return (f"Nota interna (el cliente no la ve): {_MARCA_SIN_ATENDER}. Respondió el {cuando} y ya "
            f"pasaron {horas} horas hábiles sin que le contestemos. Es un ticket con la pelota de "
            "nuestro lado: respondele o dejá asentado qué se está haciendo, para que no quede "
            "esperando sin noticias.")


def _nota_interna_horario(dt):
    """Nota PRIVADA (solo técnicos) avisando que el ticket entró fuera de horario y cuándo reabre solo.
    El CLIENTE NO ve esto: solo ve la respuesta profesional normal (sin avisos de horario)."""
    cuando = dt.strftime("%d/%m a las %H:%M") if dt else "el próximo día hábil"
    return ("Nota interna (el cliente no la ve): el ticket ingresó FUERA del horario de atención, así "
            f"que queda EN ESPERA y se reabrirá solo (EN CURSO) {cuando}.")


def _con_cierre_espera(texto):
    """Deja la 1ª respuesta terminando con el cierre de ESPERA, UNA sola vez. Se usa cuando FALTA
    un dato del cliente: así el ciclo reconoce que el ticket espera SU respuesta y le recuerda una
    vez por día hábil, igual que con el pedido de confirmación."""
    t = (texto or "").strip()
    if _MARCA_ESPERA_CLIENTE in t.lower():
        return t
    t = _RE_DESPEDIDA_ESPERA.sub("", t).strip()      # sacamos la despedida propia del modelo
    t = _RE_FIRMA_FINAL.sub("", t).strip()           # y su firma: el cierre ya trae la nuestra
    return (t + _CIERRE_ESPERA).strip()


def _texto_recordatorio_espera(motivo):
    """Recordatorio PÚBLICO al cliente, según QUÉ estamos esperando ('datos' o 'confirmacion').
    Incluye a propósito el marcador de espera (_MARCA_ESPERA_CLIENTE) para que el propio ciclo lo
    reconozca como el último aviso, y el de RECORDATORIO para distinguirlo del pedido original."""
    if motivo == "datos":
        cuerpo = ("de la información que le solicitamos para poder avanzar. Cuando pueda, "
                  "respóndanos con ese dato y continuamos con la gestión.")
    else:
        cuerpo = ("de su confirmación para poder avanzar. Cuando pueda, respóndanos para "
                  "coordinar y continuamos con la gestión.")
    return f"{_MARCA_RECORDATORIO_ESPERA.capitalize()} {cuerpo}{_CIERRE_ESPERA}"


def _nota_escalada_espera(dias, motivo):
    que = ("la información que le pedimos" if motivo == "datos"
           else "el pedido de coordinación/confirmación")
    return ("Nota interna (el cliente no la ve): hace " + str(dias) + " días hábiles que este ticket "
            f"está EN ESPERA y sigue sin respuesta del cliente a {que}. Le mandamos un recordatorio "
            "por día hábil. Conviene contactarlo por otra vía (teléfono), posponerlo con fecha o "
            "cerrarlo si ya no corresponde.")


def frase_triage(res, t):
    return (f"Ticket número {t.get('id')} procesado. Prioridad {res['prioridad']}, "
            f"nivel {res['nivel']}. Asignado a {res['responsable_nombre']}. "
            f"Primera respuesta enviada.")


def mensaje_triage(res, t):
    return (f"✅ *Ticket #{t.get('id')} procesado por ITHOS*\n"
            f"Categoría: {res.get('categoria')} · Prioridad: {res['prioridad']} "
            f"({res['nivel']})\nAsignado a: {res['responsable_nombre']} (+ ITHOS)\n"
            f"Primera respuesta enviada.")


_NOTA_PEDIR_PROCEDIMIENTO = (
    "Nota interna (el cliente no la ve): para nuestra base de conocimiento, por favor documentá "
    "PASO A PASO qué hiciste para resolver este ticket (el procedimiento), no solo que quedó resuelto. "
    "Así queda el registro y nos sirve para resolver más rápido los casos futuros.")


