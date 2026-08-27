#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CICLO DE VIDA del ticket: qué hacer con uno que YA fue triado.

En cada vuelta lee los seguimientos y decide según lo que pasó:

  · el TÉCNICO resolvió por comentario   -> Resuelto + pedirle confirmación al cliente
  · el técnico pide COORDINAR algo       -> En espera + transmitirle el pedido al cliente
  · el CLIENTE respondió                 -> En curso, o En espera hasta el próximo día hábil si
                                            escribió fuera de horario (el SLA no corre de noche
                                            ni un fin de semana contra un equipo que no está)
  · el cliente NO responde               -> un recordatorio por día hábil y, a los 5, aviso al
                                            técnico asignado
  · le respondimos tarde                 -> aviso al técnico de que hace horas hábiles que el
                                            cliente espera

La verdad se lee SIEMPRE de la mesa de ayuda, no de la memoria: así sobrevive a un reinicio del
Gestor y nunca manda dos veces lo mismo.
"""

import os
import re
import sys
import logging
from datetime import datetime

_AQUI = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_AQUI, ".."), _AQUI):   # ITHOS/ y ITHOS/central/
    if _p not in sys.path:
        sys.path.insert(0, _p)
from comun import glpi as G         # noqa: E402
from comun.horario import (ahora_local as _ahora_local, en_horario_atencion,  # noqa: E402
                           dias_habiles_entre, horas_habiles_entre)
import cerebro                      # noqa: E402
from equipo import (TECNICOS, TECNICOS_HUMANOS, ids_humanos, ids_tecnicos,   # noqa: E402
                    _asignados_humanos, _nombres_por_id)
from textos_ticket import (_MARCA_CONFIRMACION, _MARCA_RECORDATORIO,       # noqa: E402
                           _MARCA_ESPERA_CLIENTE, _MARCA_PROCEDIMIENTO,
                           _MARCA_RECORDATORIO_ESPERA, _MARCA_ESCALADA_ESPERA,
                           _MARCA_SIN_ATENDER, _DIAS_HABILES_ESCALADA, _HORAS_SIN_ATENDER,
                           _NOTA_PEDIR_PROCEDIMIENTO)

log = logging.getLogger("ciclo")


def _nombre_usuario(cliente, uid):
    try:
        u = cliente.request(f"/User/{uid}")
        if isinstance(u, list):
            u = u[0] if u else {}
        n = f"{u.get('firstname') or ''} {u.get('realname') or ''}".strip()
        return n or u.get("name") or f"usuario {uid}"
    except Exception:  # noqa: BLE001
        return f"usuario {uid}"


def _es_aviso_confirmacion(f):
    """True si el followup `f` es un aviso de ITHOS pidiendo/recordando la confirmación."""
    if int(f.get("users_id") or 0) not in TECNICOS:
        return False
    c = str(f.get("content", "")).lower()
    return _MARCA_CONFIRMACION in c or _MARCA_RECORDATORIO in c


def _ya_pidio_confirmacion(fu):
    """True si ITHOS ya dejó el pedido (o un recordatorio) de confirmación en el ticket. Lee la
    verdad del propio GLPI (no el estado en memoria), así NO se repite el pedido tras un reinicio."""
    return any(_es_aviso_confirmacion(f) for f in fu)


def _es_pedido_al_cliente(f, tecs=None):
    """True si el followup `f` es un pedido PÚBLICO de ITHOS al cliente (un dato que falta o una
    confirmación para avanzar) y por lo tanto el ticket está esperando SU respuesta. Las notas
    internas (is_private) NO cuentan: el cliente no las ve.
    `tecs`: ids del lado de soporte (por config del cliente); sin él, el equipo por defecto."""
    if int(f.get("users_id") or 0) not in (tecs or TECNICOS) or int(f.get("is_private") or 0):
        return False
    return _MARCA_ESPERA_CLIENTE in str(f.get("content", "")).lower()


def _respondio_a(fu, es_pedido, tecs=None):
    """El comentario con el que el CLIENTE respondió al último pedido de ITHOS, o None.

    Se mide contra EL PEDIDO, no contra el último comentario de un técnico. Parece un detalle y no
    lo es: cuando un técnico contesta DESPUÉS del cliente —que es lo normal y lo que uno quiere—,
    la referencia se corría sola por delante de la respuesta y el ticket quedaba esperando para
    siempre algo que ya había llegado. Pasó de verdad: en el #651 el cliente contestó "sí, pueden
    correrlo", el técnico le respondió siete minutos después, y el ticket siguió EN ESPERA
    dieciséis días sin que nadie se enterara (en espera el SLA no corre, así que no chilla nada).

    `es_pedido`: qué cuenta como pedido de ITHOS (un dato que falta, o una confirmación)."""
    pedidos = [int(f.get("id") or 0) for f in fu if es_pedido(f)]
    if not pedidos:
        return None
    ultimo = max(pedidos)
    posteriores = sorted((f for f in fu
                          if int(f.get("id") or 0) > ultimo
                          and int(f.get("users_id") or 0) not in (tecs or TECNICOS)),
                         key=lambda f: int(f.get("id") or 0))
    return posteriores[-1] if posteriores else None


def _coordinacion_despues_de(fu, tec_fu_id, tecs=None):
    """True si ITHOS ya dejó un pedido al cliente POSTERIOR al comentario `tec_fu_id`. Así el
    pedido NO se repite para el MISMO comentario del técnico tras un reinicio (el estado en memoria
    se pierde), pero SÍ se puede volver a pedir si el técnico deja un comentario NUEVO más adelante.
    Lee la verdad del propio GLPI, no la memoria."""
    return any(_es_pedido_al_cliente(f, tecs) and int(f.get("id") or 0) > int(tec_fu_id or 0)
               for f in fu)


def _texto_plano(html):
    """Un comentario de GLPI en texto legible: para citarlo en un aviso y, sobre todo, para
    dárselo a la IA.

    GLPI guarda el contenido con las etiquetas ESCAPADAS ('&#60;p&#62;' por '<p>'), y el editor
    mete además un `style` gigante en cada párrafo. Si no se desescapa primero, sacar '<...>' no
    saca nada y lo que queda son miles de caracteres de CSS con el texto real perdido adentro.
    Por eso el desescapado va SIEMPRE antes de limpiar las etiquetas."""
    import html as _html
    t = _html.unescape(_html.unescape(str(html or "")))
    t = re.sub(r"<\s*br\s*/?>|</\s*p\s*>", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def _ya_aviso_sin_atender(fu, desde_id):
    """True si YA se dejó el aviso de 'te contestaron y no respondiste' DESPUÉS del mensaje del
    cliente. Se lee del propio GLPI para no repetirlo tras un reinicio del Gestor."""
    return any(int(f.get("is_private") or 0) and int(f.get("id") or 0) > int(desde_id or 0)
               and _MARCA_SIN_ATENDER in str(f.get("content", "")).lower() for f in fu)


def _ultimo_id_cliente(fu, tecs=None):
    """Mayor id de followup de un NO técnico = la última vez que HABLÓ el cliente (0 si nunca)."""
    return max((int(f.get("id") or 0) for f in fu
                if int(f.get("users_id") or 0) not in (tecs or TECNICOS)), default=0)


def _espera_pendiente(fu, tecs=None):
    """(fecha del PRIMER pedido, fecha del ÚLTIMO aviso, motivo) si el ticket está esperando una
    respuesta DEL CLIENTE y todavía no contestó. None si no aplica. `motivo`:
      · 'datos'        -> le pedimos un DATO que falta (la primera respuesta del triage), o
      · 'confirmacion' -> tiene que CONFIRMAR/COORDINAR algo para que podamos avanzar.
    Pendiente = hay un pedido PÚBLICO de ITHOS POSTERIOR a lo último que dijo el cliente. Se lee del
    propio GLPI (no de la memoria) -> sobrevive reinicios y no manda recordatorios falsos: si el
    cliente ya respondió, el ciclo lo pasa a EN CURSO y esto deja de dar True."""
    avisos = [f for f in fu if _es_pedido_al_cliente(f, tecs)]
    if not avisos:
        return None
    if max(int(f.get("id") or 0) for f in avisos) <= _ultimo_id_cliente(fu, tecs):
        return None                          # el cliente ya contestó después del pedido
    fechas = sorted(d for d in (_parse_fecha(f.get("date_creation") or f.get("date"))
                                for f in avisos) if d)
    if not fechas:
        return None
    # El motivo lo define el ÚLTIMO pedido (es lo que estamos esperando AHORA): si ese pedido es la
    # PRIMERA respuesta del ticket (el primer followup público de ITHOS), falta un DATO; cualquier
    # pedido posterior es una COORDINACIÓN/confirmación planteada por el técnico.
    # `fechas[0]` (el PRIMER pedido) es la referencia para la escalada: mide cuánto lleva el ticket
    # trabado esperando al cliente, aunque en el medio le hayamos pedido otra cosa.
    publicos = [int(f.get("id") or 0) for f in fu
                if int(f.get("users_id") or 0) in (tecs or TECNICOS)
                and not int(f.get("is_private") or 0)]
    ultimo_pedido = max(int(f.get("id") or 0) for f in avisos)
    motivo = "datos" if publicos and ultimo_pedido == min(publicos) else "confirmacion"
    # Excepción: la 1ª respuesta puede estar pidiendo COORDINAR una visita en vez de un dato que
    # falta. Se reconoce por su frase estable, así el recordatorio le habla de confirmar el día y
    # no de "la información que le solicitamos", que no le pedimos.
    texto_ultimo = next((str(f.get("content", "")) for f in avisos
                         if int(f.get("id") or 0) == ultimo_pedido), "")
    if cerebro.MARCA_COORDINAR in texto_ultimo.lower():
        motivo = "confirmacion"
    return fechas[0], fechas[-1], motivo


def _ya_escalo_espera(fu):
    """True si ITHOS ya avisó al técnico (nota interna) que el cliente no responde. Lee GLPI, no la
    memoria -> no se repite la escalada tras un reinicio."""
    return any(int(f.get("users_id") or 0) in TECNICOS
               and _MARCA_ESCALADA_ESPERA in str(f.get("content", "")).lower() for f in fu)


def _esta_pospuesto(cfg, tid):
    """True si el ticket tiene una REACTIVACIÓN programada (lo pospusieron a un día/hora): entonces
    NO se le recuerda nada al cliente hasta esa fecha (el técnico decidió esperar)."""
    try:
        from comun import agenda
        cliente = cfg.get("nombre_cliente") or "cliente"
        return any(str(x.get("tid")) == str(tid) for x in agenda.pendientes(cliente))
    except Exception:  # noqa: BLE001
        return False


def _ya_pidio_procedimiento(fu):
    """True si ITHOS ya pidió (por nota interna) el procedimiento paso a paso (no repetir tras un
    reinicio). Lee la verdad de GLPI, no la memoria."""
    return any(int(f.get("users_id") or 0) in TECNICOS
               and _MARCA_PROCEDIMIENTO in str(f.get("content", "")).lower() for f in fu)


def _solucion_resuelta(cliente, tid):
    """Qué hizo el cliente con la SOLUCIÓN desde la mesa de ayuda: 'aceptada', 'rechazada' o None.

    En GLPI el solicitante confirma o rechaza APRETANDO UN BOTÓN sobre la solución, no escribiendo.
    Mientras no la toca, la solución queda 'pendiente' (2) y esto devuelve None. Sin mirar esto, un
    cliente que rechaza y no escribe nada quedaba esperando para siempre: la solución figuraba
    rechazada y el ticket seguía en Resuelto sin que el equipo se enterara."""
    try:
        sol = cliente.request(f"/Ticket/{tid}/ITILSolution")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(sol, list) or not sol:
        return None
    ultima = sorted(sol, key=lambda s: int(s.get("id") or 0))[-1]
    return {1: "aceptada", 3: "rechazada"}.get(int(ultima.get("status") or 0))


def _espera_confirmacion(cliente, tid):
    """True si lo que el ticket espera del cliente es que CONFIRME que quedó resuelto.

    Se reconoce por tener una SOLUCIÓN cargada y todavía pendiente de su aprobación. Es lo que
    separa las dos esperas: si le pedimos un dato, cuando contesta el ticket vuelve a En curso;
    si le pedimos la confirmación, lo que contesta cierra el ticket o lo reabre."""
    try:
        sol = cliente.request(f"/Ticket/{tid}/ITILSolution")
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(sol, list) or not sol:
        return False
    ultima = sorted(sol, key=lambda s: int(s.get("id") or 0))[-1]
    return int(ultima.get("status") or 0) == 2          # 2 = pendiente del cliente


def _texto_resolucion(cliente, tid, fu, humanos=None):
    """Junta el texto de la RESOLUCIÓN para que la IA juzgue si explica el procedimiento: la
    ITILSolution documentada (si hay) + el último comentario de un técnico HUMANO. '' si no hay nada."""
    partes = []
    try:
        sol = cliente.request(f"/Ticket/{tid}/ITILSolution")
        if isinstance(sol, list):
            for s in sol:
                c = _texto_plano(s.get("content"))
                if c:
                    partes.append(c)
    except Exception:  # noqa: BLE001
        pass
    tec = [f for f in fu if int(f.get("users_id") or 0) in (humanos or TECNICOS_HUMANOS)]
    if tec:
        c = _texto_plano(tec[-1].get("content"))
        if c:
            partes.append(c)
    return "  ".join(partes).strip()


def _parse_fecha(s):
    """Parsea una fecha de GLPI ('YYYY-MM-DD HH:MM:SS') a datetime naive. None si no se puede."""
    txt = str(s or "")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(txt, fmt)
        except (ValueError, TypeError):
            pass
    return None


def _ultimo_aviso_confirmacion(fu):
    """Fecha del último aviso de confirmación de ITHOS (pedido o recordatorio), o None. Se usa
    para el recordatorio DIARIO de forma robusta ante reinicios (no depende del estado en memoria)."""
    fechas = [_parse_fecha(f.get("date_creation") or f.get("date"))
              for f in fu if _es_aviso_confirmacion(f)]
    fechas = [d for d in fechas if d]
    return max(fechas) if fechas else None


def _followups_por_ticket(cliente, tam=2000):
    """{ticket_id: [followups]} en UNA sola lectura masiva de ITILFollowup (paginada). Evita el
    N+1 del poller (una request por ticket). Devuelve None si la lectura masiva falla o no es una
    lista -> el llamador cae al modo por-ticket (mismo resultado, más lento pero correcto)."""
    mapa, inicio, vistos = {}, 0, 0
    while True:
        try:
            chunk = cliente.request(f"/ITILFollowup?range={inicio}-{inicio + tam - 1}")
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(chunk, list):
            return None
        for f in chunk:
            if isinstance(f, dict):
                vistos += 1
                if str(f.get("itemtype")) == "Ticket":
                    mapa.setdefault(int(f.get("items_id") or 0), []).append(f)
        if len(chunk) < tam:                 # última página incompleta -> no hay más
            break
        inicio += tam
        if inicio > 1000000:                 # tope de seguridad
            break
    # Red de seguridad: si vimos followups pero NINGUNO mapeó a un Ticket (campos inesperados),
    # NO confiamos en el modo masivo -> None para caer al modo por-ticket (correcto y seguro).
    if vistos and not mapa:
        return None
    return mapa


def gestionar_ciclo(cliente, triage, entidad, estado):
    """Sync (se corre en thread). Gestiona el ciclo de vida de los tickets abiertos:
      - status 4 (EN ESPERA de info): el cliente responde -> EN CURSO; si no, recordatorio.
      - status 4 esperando que el cliente CONFIRME/COORDINE para avanzar: recordatorio DIARIO en
        días hábiles y, a los 5 días hábiles sin respuesta, aviso al TÉCNICO ASIGNADO.
      - status 5 (RESUELTO): ITHOS pide confirmación; si el cliente confirma -> CERRADO;
        si dice que sigue -> REABIERTO; si no responde -> recordatorio de confirmación.
    NUNCA cierra sin confirmación real del cliente. Devuelve anuncios {texto, wa, tel}: `tel` son
    los teléfonos del TÉCNICO ASIGNADO para @mencionarlo en WhatsApp (solo a él).
    Baseline = último followup de un técnico; un followup posterior de un NO técnico
    es una respuesta del cliente (robusto ante reinicios)."""
    anuncios = []
    cfg = getattr(triage, "cfg_glpi", None) or {}
    # QUIÉNES son "del lado de soporte" en ESTE cliente: sale de su config (`tecnicos`). Sin esto,
    # un técnico nuevo no se reconoce y todo lo que escribe se lee como si fuera el CLIENTE.
    tecs, humanos = ids_tecnicos(cfg), ids_humanos(cfg)
    try:
        tickets = G.de_entidad(cliente.tickets_recientes(40), entidad)
    except Exception:  # noqa: BLE001
        return anuncios

    _cache_asig = {}

    def asignado(tid):
        """(telefonos, nombres) del TÉCNICO ASIGNADO al ticket, para @mencionarlo SOLO a él. Se
        resuelve una vez por ticket y SOLO cuando hay algo que anunciar (nada de N+1 por ciclo)."""
        tid = int(tid)
        if tid not in _cache_asig:
            from comun import tickets as TK
            ids = _asignados_humanos(cliente, tid)
            _cache_asig[tid] = (TK.telefonos_asignados(cfg, ids),
                                TK.nombres_asignados(cfg, ids) or _nombres_por_id(ids))
        return _cache_asig[tid]

    def anunciar(tid, texto, wa):
        """Suma un anuncio del ticket con la @mención al asignado (y su nombre en el texto, para los
        canales sin menciones: Telegram/email/Teams)."""
        tels, nombres = asignado(tid)
        if nombres:
            wa = f"{wa}\n👤 Asignado a: {', '.join(nombres)}"
        anuncios.append({"texto": texto, "wa": wa, "tel": tels})

    # Con MUCHOS tickets a revisar (abiertos + resueltos), traer TODOS los followups en UNA lectura
    # masiva evita el N+1 (una request por ticket). Con pocos (caso común) el modo por-ticket ya es
    # instantáneo. Si la lectura masiva falla, fu_map=None y se cae al modo por-ticket (mismo dato).
    relevantes = [t for t in tickets if int(t.get("status", 1)) in (1, 2, 4, 5)]
    fu_map = _followups_por_ticket(cliente) if len(relevantes) > 8 else None

    for t in tickets:
        tid = str(t.get("id"))
        status = int(t.get("status", 1))
        if status not in (1, 2, 4, 5):        # abiertos + resuelto (los cerrados no se tocan)
            estado.pop(tid, None)
            continue
        if fu_map is not None:
            fu = fu_map.get(int(t["id"]), [])
        else:
            try:
                fu = [f for f in cliente.request(f"/Ticket/{t['id']}/ITILFollowup")
                      if isinstance(f, dict)]
            except Exception:  # noqa: BLE001
                continue
        st = estado.setdefault(tid, {})
        base = max((int(f["id"]) for f in fu
                    if int(f.get("users_id") or 0) in tecs), default=0)
        nuevos = [f for f in fu if int(f["id"]) > base
                  and int(f.get("users_id") or 0) not in tecs]

        # ¿Un TÉCNICO HUMANO resolvió el ticket con un comentario? -> marcarlo Resuelto y pedirle
        # confirmación al cliente (mismo flujo que si lo pasaran a 'Resuelto' a mano). Solo en
        # tickets abiertos (no resueltos/cerrados) y una sola vez por comentario nuevo del técnico.
        if status in (1, 2, 4) and not _ya_pidio_confirmacion(fu):
            tec_fus = [f for f in fu if int(f.get("users_id") or 0) in humanos]
            ult = tec_fus[-1] if tec_fus else None
            if ult and int(ult["id"]) > int(st.get("ultimo_tec_fu", 0)):
                # GLPI guarda el comentario con las etiquetas ESCAPADAS ('&#60;p&#62;' por '<p>'),
                # así que sacar '<...>' a secas no saca NADA: a la IA le llegaban miles de
                # caracteres de CSS del editor y ni veía el texto. Pasó de verdad: un "quedó
                # solucionado" no se detectó porque el comentario eran 24.000 caracteres de estilos.
                cont = _texto_plano(ult.get("content"))
                # Interpretar el comentario del técnico necesita la IA. Si NO está disponible
                # (devuelve None), el comentario NO se da por visto: se reintenta en el próximo
                # ciclo. Antes se marcaba igual y el ticket quedaba trabado para siempre — pasó de
                # verdad: un técnico escribió "quedó solucionado" justo cuando la cadena de IA
                # estaba caída, y el ticket se quedó En curso aunque la IA volviera diez minutos
                # después.
                # INVARIANTE: `cont` es SIEMPRE el comentario de un TÉCNICO HUMANO (viene de
                # `tec_fus`), NUNCA del cliente. Si el CLIENTE escribe "coordinemos una reunión",
                # eso es una RESPUESTA suya y no dispara nada de esto.
                # ORDEN IMPORTANTE: primero se pregunta si queda algo EN MANOS DEL CLIENTE y recién
                # después si está resuelto. Un comentario puede decir "el acceso quedó solucionado"
                # y en la misma línea pedirle al cliente que escale algo para cerrarlo del todo:
                # eso NO es un cierre, es una ESPERA. Mientras la pelota sea del cliente el ticket
                # queda En espera; cuando responde vuelve a En curso, y así hasta que de verdad no
                # falte nada. Al revés se cerraba de más.
                pide = triage.tecnico_pide_confirmacion(cont)
                resolvio = None if pide else triage.tecnico_resolvio(cont)
                if pide is None or (not pide and resolvio is None):
                    continue                  # la IA no contestó: lo vemos en el próximo ciclo
                st["ultimo_tec_fu"] = int(ult["id"])
                if pide:
                    # Sólo si NO estaba ya en espera y NO se lo pedimos ya por ESTE comentario.
                    if status != 4 and not _coordinacion_despues_de(fu, int(ult["id"]), tecs) \
                            and triage.poner_en_espera_pedido(t["id"], cont):
                        anunciar(
                            t["id"],
                            f"En el ticket número {t['id']} el técnico dejó algo pendiente de "
                            "parte del cliente. Lo dejé en espera y le pedí que responda.",
                            f"⏳ *Ticket #{t['id']}* — queda algo en manos del cliente. En ESPERA "
                            "de su respuesta.")
                    continue                  # ya lo procesamos en este ciclo
                if resolvio:
                    # El técnico resolvió -> el ticket queda ESPERANDO QUE EL CLIENTE CONFIRME: se
                    # carga la solución con el texto del técnico (la carga ITHOS, que es quien hace
                    # el pasaje), se le pide que confirme y el ticket va a EN ESPERA con la
                    # solución pendiente de su aprobación. El estado dice lo que de verdad pasa, el
                    # SLA no corre mientras espera, y el cliente puede cerrarlo o decir que sigue
                    # igual. Si no contesta, se le recuerda una vez por día hábil.
                    if triage.a_confirmacion_del_cliente(t["id"], cont):
                        st["confirm_pedido"] = True
                        anunciar(
                            t["id"],
                            f"El técnico resolvió el ticket número {t['id']}. Quedó en espera de "
                            "que el cliente confirme para cerrarlo.",
                            f"✅ *Ticket #{t['id']}* — resuelto por el técnico. En ESPERA de que "
                            "el cliente confirme para cerrarlo.")
                    continue                  # ya lo procesamos en este ciclo

        if status == 4:                       # EN ESPERA
            # Un ticket en espera puede estar esperando DOS cosas distintas, y no se resuelven
            # igual: un DATO que le pedimos (o coordinar algo) -> cuando contesta vuelve a En
            # curso; o la CONFIRMACIÓN de que quedó resuelto -> ahí se cierra o se reabre. Se
            # distinguen por si hay una SOLUCIÓN pendiente de su aprobación.
            veredicto = _solucion_resuelta(cliente, t["id"])
            if veredicto == "aceptada":        # apretó "Aprobar" en la mesa de ayuda
                if triage.cerrar(t["id"]):
                    anunciar(t["id"],
                             f"El cliente aprobó la solución del ticket número {t['id']}. "
                             "Ticket cerrado.",
                             f"✅ *Ticket #{t['id']}* — el cliente aprobó la solución. Cerrado.")
                estado.pop(tid, None)
                continue
            if veredicto == "rechazada":       # apretó "Rechazar"
                if triage.reabrir(t["id"]):
                    anunciar(t["id"],
                             f"El cliente rechazó la solución del ticket número {t['id']}. "
                             "Vuelve a estar en curso.",
                             f"🔁 *Ticket #{t['id']}* — el cliente *rechazó* la solución. En curso "
                             "otra vez: hay que revisarlo.")
                estado.pop(tid, None)
                continue
            # ¿Contestó el cliente al pedido que lo dejó en espera? Se mide contra EL PEDIDO, no
            # contra el último comentario de un técnico: si el técnico le responde después —lo
            # normal—, el ticket tiene que salir de la espera igual.
            # OJO: el pedido a buscar DEPENDE de qué se esperaba. El pedido de confirmación y el
            # pedido de un dato son mensajes distintos, con marcas distintas; buscar el que no es
            # daba "el cliente no contestó" con la respuesta ahí escrita, y el ticket no se movía.
            espera_conf = _espera_confirmacion(cliente, t["id"])
            es_pedido = (_es_aviso_confirmacion if espera_conf
                         else (lambda f: _es_pedido_al_cliente(f, tecs)))
            respuesta = _respondio_a(fu, es_pedido, tecs)
            if respuesta and espera_conf:
                # Lo que esperábamos era que dijera si quedó resuelto: contestó ESCRIBIENDO en vez
                # de usar los botones. Vale igual.
                autor = _nombre_usuario(cliente, respuesta.get("users_id"))
                dijo = _texto_plano(respuesta.get("content"))
                conf = triage.cliente_confirma(dijo)
                if conf is None:
                    continue                   # la IA no está: se reintenta en el próximo ciclo
                if conf and triage.cerrar(t["id"]):
                    anunciar(t["id"],
                             f"El cliente {autor} confirmó que el ticket número {t['id']} quedó "
                             "resuelto. Ticket cerrado.",
                             f"✅ *Ticket #{t['id']}* — {autor} confirmó. Cerrado.")
                elif not conf and triage.reabrir(t["id"]):
                    anunciar(t["id"],
                             f"El cliente {autor} indica que el ticket número {t['id']} sigue sin "
                             "resolverse. Vuelve a estar en curso.",
                             f"🔁 *Ticket #{t['id']}* — {autor} dice que sigue. En curso otra vez.\n"
                             f"_{dijo[:300]}_")
                estado.pop(tid, None)
                continue
            if respuesta:                      # el cliente respondió
                autor = _nombre_usuario(cliente, respuesta.get("users_id"))
                dijo = _texto_plano(respuesta.get("content"))
                # FUERA DE HORARIO: no se pasa a EN CURSO. Si se pasara, el SLA correría toda la
                # noche o todo el fin de semana contra un equipo que no está trabajando y el lunes
                # el ticket nacería vencido. Queda EN ESPERA y se reabre solo al abrir la jornada.
                if not en_horario_atencion(cfg):
                    dt = triage.esperar_hasta_horario(t["id"], dijo)
                    cuando = dt.strftime("%A %d/%m a las %H:%M") if dt else "el próximo día hábil"
                    anunciar(t["id"],
                             f"El cliente {autor} respondió el ticket número {t['id']} fuera del "
                             f"horario de atención. Lo dejé en espera y se retoma {cuando}.",
                             f"🔔 *Ticket #{t['id']}* — {autor} respondió (fuera de horario):\n"
                             f"_{dijo[:300]}_\n⏸️ Queda en espera para que el SLA no corra; se "
                             f"retoma solo *{cuando}*.")
                elif triage.poner_en_curso(t["id"]):
                    anunciar(t["id"],
                             f"El cliente {autor} respondió el ticket número "
                             f"{t['id']}. Vuelve a estar en curso.",
                             f"🔔 *Ticket #{t['id']}* — {autor} respondió. En curso otra vez.\n"
                             f"_{dijo[:300]}_")
                estado.pop(tid, None)
            else:
                # NO se envían recordatorios automáticos genéricos ("esperamos su respuesta"): eran
                # ruido y muchas veces FALSOS (el ticket puede estar pospuesto o en gestión por
                # soporte). ÚNICA excepción, porque acá SÍ le pedimos algo CONCRETO: el ticket está
                # esperando que el CLIENTE responda —un DATO que le pedimos o una CONFIRMACIÓN para
                # poder avanzar— y el SLA queda pausado en 'En espera'. Entonces sí:
                #   · un recordatorio POR DÍA HÁBIL, a la misma hora (la de apertura), hasta que
                #     responda (cuando responde, el 'if nuevos' de arriba lo pasa a EN CURSO), y
                #   · a los 5 días hábiles sin respuesta, aviso al TÉCNICO ASIGNADO (nota interna
                #     privada + WhatsApp @mencionándolo) para que decida.
                # Si el ticket está POSPUESTO (reactivación agendada), no se molesta a nadie.
                espera = _espera_pendiente(fu, tecs)
                if espera and not _esta_pospuesto(cfg, t["id"]):
                    primero, ultimo, motivo = espera
                    ahora = _ahora_local(cfg)
                    # El recordatorio sale DENTRO del horario de atención del cliente (default
                    # Lun-Vie 09:00-18:00, su zona): nunca de noche ni un fin de semana. Uno por día.
                    if en_horario_atencion(cfg) and ultimo.date() < ahora.date():
                        if triage.recordar_espera(t["id"], motivo):
                            log.info("Ciclo #%s: recordatorio diario al cliente (%s; en espera "
                                     "desde %s).", t["id"], motivo, primero.date())
                    habiles = dias_habiles_entre(cfg, primero, ahora)
                    if (habiles >= _DIAS_HABILES_ESCALADA and not st.get("escalado_espera")
                            and not _ya_escalo_espera(fu)):
                        st["escalado_espera"] = True
                        triage.avisar_tecnico_sin_respuesta(t["id"], habiles, motivo)
                        que = ("la información que le pedimos" if motivo == "datos"
                               else "el pedido de coordinación")
                        anunciar(t["id"],
                                 f"El ticket número {t['id']} lleva {habiles} días hábiles en "
                                 f"espera y el cliente no respondió.",
                                 f"⌛ *Ticket #{t['id']}* — {habiles} días hábiles sin respuesta del "
                                 f"cliente a {que}. Requiere una definición: contactarlo, "
                                 "posponerlo o cerrarlo.")

        elif status in (1, 2) and nuevos:     # NUEVO / EN CURSO y el cliente escribió algo
            # La pelota está de NUESTRO lado. Dos cosas que antes no pasaban y dolían:
            #  1) Si escribió FUERA del horario, el ticket quedaba EN CURSO y el SLA corría toda la
            #     noche o el fin de semana entero contra un equipo que no está: el lunes ya nacía
            #     vencido. Ahora queda EN ESPERA y se reabre solo al abrir la jornada.
            #  2) Nadie se enteraba de que el cliente había escrito. Ahora se avisa por los canales
            #     con lo que dijo, y si pasan horas HÁBILES sin que le contestemos, el técnico
            #     asignado recibe el aviso —una vez por día hábil— hasta que lo atienda.
            autor = _nombre_usuario(cliente, nuevos[-1].get("users_id"))
            dijo = _texto_plano(nuevos[-1].get("content"))
            ultimo_id = int(nuevos[-1].get("id") or 0)
            if not en_horario_atencion(cfg):
                if int(st.get("espera_horario", 0)) != ultimo_id:
                    st["espera_horario"] = ultimo_id
                    dt = triage.esperar_hasta_horario(t["id"], dijo)
                    cuando = dt.strftime("%d/%m a las %H:%M") if dt else "el próximo día hábil"
                    anunciar(t["id"],
                             f"El cliente {autor} respondió el ticket número {t['id']} fuera del "
                             f"horario de atención. Lo dejé en espera y se retoma {cuando}.",
                             f"🔔 *Ticket #{t['id']}* — {autor} escribió (fuera de horario):\n"
                             f"_{dijo[:300]}_\n⏸️ En espera para que el SLA no corra; se retoma "
                             f"solo *{cuando}*.")
            else:
                if int(st.get("avisada_respuesta", 0)) != ultimo_id:
                    st["avisada_respuesta"] = ultimo_id
                    anunciar(t["id"],
                             f"El cliente {autor} escribió en el ticket número {t['id']}.",
                             f"🔔 *Ticket #{t['id']}* — {autor} escribió:\n_{dijo[:300]}_\n"
                             "El ticket está EN CURSO, esperando nuestra respuesta.")
                desde = _parse_fecha(nuevos[-1].get("date_creation") or nuevos[-1].get("date"))
                horas = horas_habiles_entre(cfg, desde, _ahora_local(cfg)) if desde else 0
                hoy = _ahora_local(cfg).date()
                if horas >= _HORAS_SIN_ATENDER and st.get("aviso_sin_atender") != hoy \
                        and not _ya_aviso_sin_atender(fu, ultimo_id):
                    st["aviso_sin_atender"] = hoy
                    triage.avisar_tecnico_sin_atender(t["id"], desde, horas)
                    anunciar(t["id"],
                             f"En el ticket número {t['id']} el cliente respondió hace "
                             f"{int(horas)} horas hábiles y todavía no le contestamos.",
                             f"⚠️ *Ticket #{t['id']}* — {autor} respondió hace *{int(horas)} h "
                             "hábiles* y sigue sin respuesta nuestra. La pelota es nuestra: "
                             "contestale o dejá asentado qué se está haciendo.")

        elif status == 5:                     # RESUELTO = esperando que el cliente confirme
            # El cliente tiene DOS formas de contestar, y las dos cuentan:
            #   · los BOTONES de la mesa de ayuda (aprueba o rechaza la solución), o
            #   · escribiendo un comentario.
            # Esto mira los botones. Si sólo miráramos los comentarios, un cliente que aprieta
            # "Rechazar" y no escribe nada quedaría esperando para siempre: la solución figura
            # rechazada y el ticket seguiría en Resuelto, sin que nadie del equipo se entere.
            veredicto = _solucion_resuelta(cliente, t["id"])
            if veredicto == "aceptada":
                if triage.cerrar(t["id"]):
                    anunciar(t["id"],
                             f"El cliente aprobó la solución del ticket número {t['id']}. "
                             "Ticket cerrado.",
                             f"✅ *Ticket #{t['id']}* — el cliente aprobó la solución. Cerrado.")
                estado.pop(tid, None)
                continue
            if veredicto == "rechazada":
                if triage.reabrir(t["id"]):
                    anunciar(t["id"],
                             f"El cliente rechazó la solución del ticket número {t['id']}. "
                             "Vuelve a estar en curso.",
                             f"🔁 *Ticket #{t['id']}* — el cliente *rechazó* la solución. En curso "
                             "otra vez: hay que revisarlo.")
                estado.pop(tid, None)
                continue
            # Feedback INTERNO al equipo (para la BASE DE CONOCIMIENTO): si la resolución NO explica el
            # PROCEDIMIENTO (no hay solución, o es un 'listo/solucionado' vago sin explicar cómo), ITHOS
            # le pide al técnico por nota PRIVADA que documente PASO A PASO qué hizo. Se revisa una vez
            # por sesión (st) y una sola vez por ticket (marcador en GLPI). El cliente NO lo ve.
            if not st.get("rev_solucion"):
                st["rev_solucion"] = True
                if not _ya_pidio_procedimiento(fu):
                    resol = _texto_resolucion(cliente, t["id"], fu, humanos)
                    explica = triage.explica_procedimiento(resol) if resol else False
                    if explica is False:      # False EXPLÍCITO (no None -> IA caída): no explica -> pedir
                        triage.nota_interna(t["id"], _NOTA_PEDIR_PROCEDIMIENTO)
            if not st.get("confirm_pedido") and _ya_pidio_confirmacion(fu):
                st["confirm_pedido"] = True    # ya se pidió antes (p. ej. reinicio) -> no repetir
            if not st.get("confirm_pedido"):
                if triage.pedir_confirmacion(t["id"]):
                    st["confirm_pedido"] = True
            # ¿Contestó al pedido de confirmación? Igual que en la espera: se mide contra EL PEDIDO
            # de ITHOS, para que un comentario del técnico posterior no tape la respuesta.
            elif (dijo_cliente := _respondio_a(fu, _es_aviso_confirmacion, tecs)):
                autor = _nombre_usuario(cliente, dijo_cliente.get("users_id"))
                texto = str(dijo_cliente.get("content", ""))
                conf = triage.cliente_confirma(texto)
                if conf is None:
                    continue  # IA no disponible ahora -> reintentar próximo ciclo
                if conf:
                    if triage.cerrar(t["id"]):
                        anunciar(t["id"],
                                 f"El cliente {autor} confirmó la solución del "
                                 f"ticket número {t['id']}. Ticket cerrado.",
                                 f"✅ *Ticket #{t['id']}* — {autor} confirmó. Cerrado.")
                else:
                    if triage.reabrir(t["id"]):
                        anunciar(t["id"],
                                 f"El cliente {autor} indica que el ticket número "
                                 f"{t['id']} sigue sin resolverse. Reabierto.",
                                 f"🔁 *Ticket #{t['id']}* — {autor} reporta que sigue. Reabierto.")
                estado.pop(tid, None)
            else:
                # RESUELTO, confirmación ya pedida y SIN respuesta del cliente todavía: recordatorio
                # UNA VEZ POR DÍA HÁBIL, a la misma hora y DENTRO del horario de atención (no de
                # noche ni un fin de semana), para que confirme o avise que sigue. La respuesta del
                # cliente (elif de arriba) SIEMPRE tiene prioridad y corta los recordatorios; al
                # cerrar (status 6) el ticket sale del ciclo y no se recuerda más.
                ult = _ultimo_aviso_confirmacion(fu)
                if (ult and en_horario_atencion(cfg)
                        and ult.date() < _ahora_local(cfg).date()):
                    triage.recordar_confirmacion(t["id"])
    return anuncios
