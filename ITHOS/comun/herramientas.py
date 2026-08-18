#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QUÉ puede hacer ITHOS sobre el sistema de tickets del cliente: la lista de capacidades que se le
ofrece al modelo, en dos grupos separados a propósito.

  · HERRAMIENTAS (lectura): estado, contenido del ticket, reportes, antecedentes del histórico,
    tickets por técnico asignado.
  · ACCIONES (escritura): cerrar, reabrir, poner en espera, posponer con fecha, responder,
    asignar, categorizar, fijar SLA, crear.

Las de escritura NUNCA se ejecutan sin un pedido explícito, y cuando cambian el estado de un
ticket avisan por los canales del equipo.

Todo pasa por la interfaz común de `comun/tickets.py`: acá no hay nada atado a un sistema puntual.
"""

import logging

log = logging.getLogger("herramientas")


def herramientas_glpi(cfg_glpi, entidad):
    """Herramientas típicas de soporte sobre GLPI (sin IA)."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from comun import glpi as G

    def tickets_abiertos(args):
        cli = G.GLPIClient(cfg_glpi)
        cli.abrir()
        try:
            ts = G.de_entidad(cli.tickets_recientes(40), G.entidades_de(cfg_glpi))
        finally:
            cli.cerrar()
        abiertos = [t for t in ts if int(t.get("status", 0)) in (1, 2, 4)]
        return (f"Hay {len(abiertos)} tickets abiertos. "
                + "; ".join(f"#{t['id']} {str(t.get('name'))[:40]}" for t in abiertos[:5]))

    def estado_ticket(args):
        tid = args.get("id")
        cli = G.GLPIClient(cfg_glpi)
        cli.abrir()
        try:
            t = cli.request(f"/Ticket/{tid}")
        finally:
            cli.cerrar()
        est = {1: "Nuevo", 2: "En curso", 4: "En espera", 5: "Resuelto", 6: "Cerrado"}
        return f"Ticket #{tid}: {t.get('name')} — estado {est.get(int(t.get('status', 0)), '?')}"

    def reporte_sla(args):
        from central import reportes  # noqa
        _, texto = reportes.generar(cfg_glpi, entidad, n=100)
        return texto

    return {
        "tickets_abiertos": {"desc": "Lista los tickets abiertos.", "fn": tickets_abiertos},
        "estado_ticket": {"desc": "Estado de un ticket por id. args: {id}.", "fn": estado_ticket},
        "reporte_sla": {"desc": "Cumplimiento de SLA y estadísticas.", "fn": reporte_sla},
    }


def acciones_glpi(cfg_glpi, entidad, token=None):
    """Acciones de ESCRITURA sobre GLPI que el agente puede EJECUTAR. token: usar el
    de ITHOS o de un técnico (para que quede a su nombre)."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from comun import glpi as G

    def _cli():
        c = G.GLPIClient(cfg_glpi, token=token) if token else G.GLPIClient(cfg_glpi)
        c.abrir()
        return c

    def _put_estado(tid, estado):
        c = _cli()
        try:
            c.request(f"/Ticket/{tid}", "PUT", {"input": {"status": estado}})
        finally:
            c.cerrar()

    def cerrar(args):
        _put_estado(args.get("id"), 6)
        return f"✅ Ticket #{args.get('id')} cerrado."

    def reabrir(args):
        _put_estado(args.get("id"), 2)
        return f"🔁 Ticket #{args.get('id')} reabierto."

    def asignar(args):
        tid = args.get("id")
        uid = _TECNICOS.get(str(args.get("responsable", "")).lower().strip())
        if not uid:
            return f"No reconozco al técnico '{args.get('responsable')}'."
        c = _cli()
        try:
            c.request("/Ticket_User", "POST",
                      {"input": {"tickets_id": tid, "users_id": uid, "type": 2}})
        except Exception:  # noqa: BLE001
            pass
        finally:
            c.cerrar()
        return f"👤 Ticket #{tid} asignado a {args.get('responsable')}."

    def responder(args):
        tid = args.get("id")
        c = _cli()
        try:
            c.request("/ITILFollowup", "POST", {"input": {
                "itemtype": "Ticket", "items_id": tid, "content": args.get("texto", "")}})
        finally:
            c.cerrar()
        return f"💬 Respondí al cliente en el ticket #{tid}."

    def crear(args):
        c = _cli()
        try:
            r = c.request("/Ticket", "POST", {"input": {
                "name": args.get("asunto", "Nuevo ticket"),
                "content": args.get("contenido", ""), "entities_id": entidad}})
        finally:
            c.cerrar()
        return f"🆕 Ticket #{r.get('id')} creado."

    return {
        "cerrar_ticket": {"desc": "Cerrar un ticket. args:{id}", "fn": cerrar},
        "reabrir_ticket": {"desc": "Reabrir un ticket. args:{id}", "fn": reabrir},
        "asignar_ticket": {"desc": "Asignar a un técnico (bsierra/jayala). args:{id,responsable}", "fn": asignar},
        "responder_ticket": {"desc": "Responder al cliente en un ticket. args:{id,texto}", "fn": responder},
        "crear_ticket": {"desc": "Crear un ticket nuevo. args:{asunto,contenido}", "fn": crear},
    }


def herramientas_tickets(cli_cfg):
    """Herramientas de LECTURA sobre el sistema de tickets del CLIENTE (el que sea).
    Por cliente: cli_cfg es la config aislada de esa empresa."""
    from comun import tickets as T
    adap = T.adaptador(cli_cfg)
    _nombre = cli_cfg.get("nombre") or "cliente"
    _zona = cli_cfg.get("zona_horaria", "America/Argentina/Buenos_Aires")

    def _dt_local(epoch):
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            return datetime.fromtimestamp(float(epoch), ZoneInfo(_zona))
        except Exception:  # noqa: BLE001
            return datetime.fromtimestamp(float(epoch))

    def _programacion(tid):
        """Si el ticket tiene una REACTIVACIÓN programada (posponer), la describe; si no, ''. Así
        al dar estado/leer, ITHOS dice la VERDAD sobre si hay algo agendado (antes decía que no)."""
        try:
            from comun import agenda, tickets as _T
            n = _T._norm_id(tid)
            for p in agenda.pendientes(_nombre):
                if str(p.get("tid")) == str(n):
                    return (" · PROGRAMADO: vuelve a EN CURSO el "
                            f"{_dt_local(p.get('epoch', 0)).strftime('%d/%m a las %H:%M')}.")
        except Exception:  # noqa: BLE001
            pass
        return ""

    def tickets_abiertos(args):
        ab = adap.abiertos()
        return (f"Hay {len(ab)} tickets abiertos. "
                + "; ".join(f"#{t['id']} {str(t.get('asunto'))[:40]}" for t in ab[:5]))

    def estado_ticket(args):
        return (adap.estado(args.get("id")) or "") + _programacion(args.get("id"))

    def leer_ticket(args):
        """Lee el ticket COMPLETO (descripción + seguimientos + categoría/prioridad/SLA)."""
        fn = getattr(adap, "detalle", None)
        base = fn(args.get("id")) if fn else adap.estado(args.get("id"))
        return (base or "") + _programacion(args.get("id"))

    def reactivaciones_programadas(args):
        """Tickets con una REACTIVACIÓN programada (pospuestos a día/hora). Responde 'qué hay
        programado/agendado' con la VERDAD, leyendo la agenda real."""
        from comun import agenda
        ps = sorted(agenda.pendientes(_nombre), key=lambda x: x.get("epoch", 0))
        if not ps:
            return ("No hay ninguna reactivación programada: ningún ticket quedó pospuesto a una "
                    "fecha/hora.")
        return "Reactivaciones programadas: " + "; ".join(
            f"#{p['tid']} vuelve a EN CURSO el {_dt_local(p.get('epoch', 0)).strftime('%d/%m %H:%M')}"
            for p in ps)

    def mis_permisos(args):
        """Qué puede y qué NO puede hacer ITHOS en el sistema de tickets del cliente (por API)."""
        fn = getattr(adap, "permisos", None)
        return (fn() or {}).get("resumen", "No pude leer mis permisos.") if fn else "(permisos no disponibles)"

    def tickets_sin_procesar(args):
        """Tickets SUELTOS en cualquier estado (sin categoría o sin SLA): el ciclo sin aplicar."""
        fn = getattr(adap, "sin_procesar", None)
        res = fn() if fn else []
        if not res:
            return "No hay tickets sueltos: todos los vigentes tienen categoría y SLA."
        return "Tickets que necesitan el ciclo (sueltos): " + "; ".join(
            f"#{t['id']} [{t['estado']}] falta {'/'.join(t['falta'])}" for t in res[:10])

    def reporte_sla(args):
        return adap.sla_texto()

    def reporte_itil(args):
        """Reporte ITIL (diario/semanal/mensual) con KPIs reales. Para GLPI usa el motor ITIL;
        otros sistemas, el resumen de SLA del adaptador."""
        periodo = (args.get("periodo") or args.get("frecuencia") or "mensual").lower()
        gl = cli_cfg.get("integrador_glpi") or {}
        if gl.get("glpi_url"):
            try:
                from comun import reportes_itil as RI
                k = RI.calcular(gl, int(gl.get("entity_id", 0)), periodo,
                                cli_cfg.get("zona_horaria", "America/Argentina/Buenos_Aires"),
                                con_tecnico=bool(args.get("por_tecnico", True)))
                return RI.resumen_texto(k, cli_cfg.get("nombre", ""))
            except Exception as e:  # noqa: BLE001
                return f"No pude generar el reporte ITIL: {e}"
        return adap.sla_texto()

    def buscar_tickets(args):
        res = adap.buscar(args.get("texto") or args.get("q") or args.get("persona") or "")
        if not res:
            return "No encontré tickets que coincidan."
        return "Encontré: " + "; ".join(
            f"#{t['id']} {str(t.get('asunto'))[:40]}" for t in res)

    def casos_parecidos(args):
        """ANTECEDENTES: revisa TODO el histórico ya trabajado (cerrados y en espera) y trae los
        tickets del MISMO problema con lo que REALMENTE se hizo en cada uno. Es la evidencia con
        la que se responde "¿qué casos como este tuvimos y cómo los resolvimos?": sin esto la
        respuesta sale de la memoria del modelo y ahí es donde aparecen números inventados."""
        descripcion = (args.get("problema") or args.get("texto") or args.get("q") or "").strip()
        fn = getattr(adap, "casos_similares", None)
        if not fn:
            return "(este sistema de tickets todavía no permite revisar el histórico completo)."
        if not descripcion:
            return "(no me quedó claro qué problema buscar en el histórico)."
        try:
            casos = fn(descripcion)
        except Exception as e:  # noqa: BLE001
            return f"(no pude revisar el histórico de tickets: {e})"
        if not casos:
            return ("ANTECEDENTES: revisé el histórico COMPLETO de tickets cerrados y en espera y "
                    "NO hay ninguno con este problema. Decilo así, sin nombrar ningún número.")
        lineas = [f"ANTECEDENTES — {len(casos)} ticket(s) del histórico COMPLETO que podrían ser "
                  "el mismo problema (ordenados por parecido). Estos son los ÚNICOS números que "
                  "existen para esta consulta:"]
        for c in casos:
            if c["resuelto_de_verdad"]:
                res = "lo que hizo soporte: " + _una_linea(c["resolucion"], 320)
            elif c["cierre_administrativo"]:
                res = ("SIN resolución técnica: se cerró por un tema administrativo (la categoría "
                       "estaba mal cargada). NO sirve como modelo de cómo se resolvió.")
            else:
                res = "SIN resolución documentada: no quedó registrado qué se hizo."
            lineas.append(f"#{c['id']} [{c['estado']}] {str(c['asunto'])[:60]}\n"
                          f"   problema: {_una_linea(c['problema'], 320)}\n   {res}")
        return "\n".join(lineas)

    def tickets_asignados(args):
        """Los tickets ABIERTOS de un técnico con su ESTADO — SOLO los del campo "Asignado a", nunca
        donde la persona es observador o solicitante. 'persona' puede ser el nombre del técnico o
        'yo'/'mis': en ese caso se resuelve por el NÚMERO de quien escribe (config `tecnicos`), así
        NUNCA hay que pedirle el nombre ni el legajo a alguien que ya está mapeado."""
        tecnicos = cli_cfg.get("tecnicos") or []
        t = _resolver_tecnico(args.get("persona") or args.get("tecnico"), args.get("_remitente"),
                              tecnicos)
        if not t:
            if not tecnicos:
                return ("(este cliente todavía no tiene técnicos configurados: no puedo filtrar por "
                        "asignado hasta que se carguen en la configuración).")
            nombres = ", ".join(x["nombre"] for x in tecnicos if x.get("nombre"))
            return f"¿De qué técnico? Los que tengo cargados son: {nombres}."
        fn = getattr(adap, "asignados_a", None)
        if not fn:
            return "(este sistema de tickets no soporta filtrar por asignado todavía)."
        try:
            tickets = fn(t.get("glpi_id") or t.get("id"))
        except Exception as e:  # noqa: BLE001
            return f"No pude leer los tickets asignados a {t['nombre']}: {e}"
        nom = t["nombre"].split()[0]
        if not tickets:
            return f"{nom} no tiene tickets abiertos asignados."
        detalle = "; ".join(f"#{k['id']} {str(k.get('asunto'))[:40]} — {k.get('estado')}"
                            for k in tickets)
        return f"{nom} tiene {len(tickets)} ticket(s) abiertos asignados: {detalle}."

    return {
        "tickets_asignados": {"desc": "Tickets ABIERTOS con su ESTADO de un técnico — SOLO del campo 'Asignado a' (no observador ni solicitante). Usala SIEMPRE para 'mis tickets', 'los míos', 'los tickets asignados a mí' o 'los de X'. Con persona:'yo' identifica por el NÚMERO de quien escribe: NO le pidas el nombre ni el legajo. args:{persona:'yo'|'Brian Sierra'|'Alejandro Ayala'}", "fn": tickets_asignados},
        "tickets_abiertos": {"desc": "Lista los tickets abiertos.", "fn": tickets_abiertos},
        "estado_ticket": {"desc": "Estado corto (asunto+estado) de un ticket. args:{id}.", "fn": estado_ticket},
        "leer_ticket": {"desc": "LEE el ticket completo (descripción + seguimientos) para analizarlo. args:{id}.", "fn": leer_ticket},
        "reporte_sla": {"desc": "Cumplimiento de SLA y estadísticas.", "fn": reporte_sla},
        "reporte_itil": {"desc": "Reporte ITIL con KPIs (volumen, SLA, MTTR, por prioridad/categoría/técnico, backlog). args:{periodo:diario|semanal|mensual}.", "fn": reporte_itil},
        "buscar_tickets": {"desc": "Busca tickets por texto o persona. args:{texto}.", "fn": buscar_tickets},
        "casos_parecidos": {"desc": "ANTECEDENTES: revisa TODO el histórico (cerrados y en espera) y trae los tickets del MISMO problema con lo que realmente hizo soporte en cada uno. Usala SIEMPRE que pregunten '¿qué tickets tuvimos/resolvimos con X problema?', 'casos parecidos', 'antecedentes' o pidan tomar casos de modelo. args:{problema:'<el problema tal como lo describieron>'}", "fn": casos_parecidos},
        "mis_permisos": {"desc": "Qué puede/NO puede hacer ITHOS en este sistema (permisos por API).", "fn": mis_permisos},
        "tickets_sin_procesar": {"desc": "Detecta tickets SUELTOS (cualquier estado) sin categoría o SLA, que necesitan el ciclo.", "fn": tickets_sin_procesar},
        "reactivaciones_programadas": {"desc": "Lista los tickets con una REACTIVACIÓN programada (pospuestos a un día/hora). USALA para responder 'qué hay programado/agendado' o si un ticket tiene reactivación.", "fn": reactivaciones_programadas},
    }


def _una_linea(texto, tope):
    """Deja el texto en una sola línea y acotado, para que entre prolijo en el contexto."""
    import re as _re
    t = _re.sub(r"\s+", " ", str(texto or "")).strip()
    return (t[:tope] + "…") if len(t) > tope else t


def _resolver_tecnico(persona, remitente, tecnicos):
    """Resuelve a QUÉ técnico se refiere: por NOMBRE ('Brian Sierra', 'ale') o, si dice 'yo/mis/mío'
    o no aclara, por el NÚMERO de quien escribe (remitente, robusto a +54/549 y LID). None si no matchea.
    Los técnicos salen de cli_cfg['tecnicos'] = [{nombre, glpi_id, glpi_login, telefonos:[...]}]."""
    import re as _re
    tecnicos = tecnicos or []
    p = _re.sub(r"\s+", " ", (persona or "").strip().lower())
    if (not p or p in ("yo", "mi", "mí", "mis", "mios", "míos", "los mios", "los míos",
                       "para mi", "para mí", "a mi", "a mí", "mio", "mío")) and remitente:
        tel = _re.sub(r"\D", "", str(remitente))
        for t in tecnicos:
            for n in (t.get("telefonos") or []):
                n = _re.sub(r"\D", "", str(n))
                if n and (tel == n or (len(tel) >= 10 and tel[-10:] == n[-10:])):
                    return t
    if p:
        for t in tecnicos:
            nom = _re.sub(r"\s+", " ", (t.get("nombre") or "").strip().lower())
            if nom and (p == nom or p in nom or nom.split()[0] == p.split()[0] or (len(p) >= 3 and p in nom)):
                return t
    return None


def acciones_tickets(cli_cfg, avisar=None):
    """Acciones de ESCRITURA que el agente puede EJECUTAR sobre el sistema de tickets
    del CLIENTE (el que sea). Por cliente. SIN alta de usuarios (a propósito).
    `avisar(mensaje)`: callback OPCIONAL para notificar a los canales (WhatsApp/Telegram/email) cuando
    una acción CAMBIA EL ESTADO del ticket (en espera / cerrado / reabierto / pospuesto). Así el equipo
    se entera igual que con los avisos automáticos del ciclo. Best-effort (nunca rompe la acción)."""
    from comun import tickets as T
    adap = T.adaptador(cli_cfg)
    _nombre = cli_cfg.get("nombre") or "cliente"
    _zona = cli_cfg.get("zona_horaria", "America/Argentina/Buenos_Aires")

    def _avisar(msg):
        if avisar and msg:
            try:
                avisar(msg)
            except Exception:  # noqa: BLE001
                pass

    def cerrar(args):
        r = adap.cambiar_estado(args.get("id"), "cerrado")
        _avisar(f"✅ *Ticket #{_id_ticket(args.get('id'))}* — cerrado por soporte.")
        return r

    def reabrir(args):
        r = adap.cambiar_estado(args.get("id"), "reabrir")
        _avisar(f"🔁 *Ticket #{_id_ticket(args.get('id'))}* — reabierto por soporte.")
        return r

    def en_espera(args):
        r = adap.cambiar_estado(args.get("id"), "en_espera")
        _avisar(f"⏸️ *Ticket #{_id_ticket(args.get('id'))}* — puesto EN ESPERA por soporte.")
        return r

    def asignar(args):
        return adap.asignar(args.get("id"), args.get("responsable", ""))

    def responder(args):
        return adap.responder(args.get("id"), args.get("texto", ""))

    def crear(args):
        return adap.crear(args.get("asunto", "Nuevo ticket"), args.get("contenido", ""))

    def prioridad(args):
        return adap.cambiar_prioridad(args.get("id"), args.get("prioridad", "media"))

    def categorizar(args):
        fn = getattr(adap, "categorizar", None)
        if not fn:
            return "(categorizar no soportado en este sistema)"
        return fn(args.get("id"), args.get("categoria") or args.get("categoría") or "")

    def asignar_sla(args):
        fn = getattr(adap, "cambiar_sla", None)
        if not fn:
            return "(SLA no soportado en este sistema)"
        return fn(args.get("id"), args.get("prioridad"))

    def aplicar_ciclo(args):
        fn = getattr(adap, "aplicar_ciclo", None)
        if not fn:
            return "(ciclo completo no soportado en este sistema)"
        return fn(args.get("id"), categoria=args.get("categoria") or args.get("categoría"),
                  prioridad=args.get("prioridad", "media"),
                  responsable=args.get("responsable", "bsierra"),
                  primera_respuesta=args.get("primera_respuesta") or args.get("texto", ""),
                  necesita_info=bool(args.get("necesita_info")))

    def escalar(args):
        tid = args.get("id")
        r1 = adap.cambiar_prioridad(tid, "urgente")
        r2 = adap.asignar(tid, args["responsable"]) if args.get("responsable") else ""
        return f"⬆️ Escalado. {r1} {r2}".strip()

    def posponer(args):
        """Deja el ticket EN ESPERA hasta un día/hora y lo REACTIVA (EN CURSO) solo cuando
        llega. Si no queda clara la HORA, la pide (no agenda a ciegas)."""
        from comun import agenda, tickets as _T
        tid = _T._norm_id(args.get("id"))
        cuando = args.get("cuando") or args.get("hasta") or args.get("fecha") or ""
        dt, desc = agenda.interpretar_cuando(cuando, _zona)
        if not dt:
            if desc == "falta la hora":
                return (f"Para el ticket #{tid}: ¿a qué HORA exacta lo dejo pendiente ese día? "
                        "Decime la hora (por ej. 13:00) y lo agendo.")
            return (f"No me quedó claro hasta cuándo dejar pendiente el #{tid}. Decime el día y "
                    "la hora (por ej. 'lunes a las 13:00').")
        adap.cambiar_estado(tid, "en_espera")
        agenda.programar(_nombre, tid, dt.timestamp(), desc)
        if args.get("texto"):
            try:
                adap.responder(tid, args["texto"])
            except Exception:  # noqa: BLE001
                pass
        _avisar(f"⏸️ *Ticket #{tid}* — EN ESPERA hasta {desc} (se reactiva solo).")
        return (f"⏸️ Ticket #{tid} EN ESPERA hasta {desc}. Lo paso a EN CURSO automáticamente "
                "en ese momento.")

    def en_espera_asignados(args):
        """Pone EN ESPERA (o pospone si dan 'cuando') TODOS los tickets ABIERTOS ASIGNADOS a un
        técnico — SOLO los de 'Asignado a', nunca donde es observador/solicitante. Filtra en CÓDIGO
        (no depende de la IA). 'persona' = nombre del técnico o 'yo' (por el número de quien escribe)."""
        tecnicos = cli_cfg.get("tecnicos") or []
        t = _resolver_tecnico(args.get("persona") or args.get("tecnico"), args.get("_remitente"), tecnicos)
        if not t:
            return ("No me quedó claro de qué técnico son los tickets. Decime el nombre "
                    "(por ej. Brian Sierra / Alejandro Ayala) y lo hago.")
        fn = getattr(adap, "asignados_a", None)
        if not fn:
            return "(este sistema de tickets no soporta filtrar por asignado todavía)."
        try:
            tickets = fn(t.get("glpi_id"))
        except Exception as e:  # noqa: BLE001
            return f"No pude leer los tickets asignados a {t['nombre']}: {e}"
        nom = t["nombre"].split()[0]
        if not tickets:
            return f"{nom} no tiene tickets abiertos asignados. No toqué nada."
        cuando = args.get("cuando") or args.get("hasta") or args.get("fecha") or ""
        dt = None
        desc = ""
        if cuando:
            from comun import agenda
            dt, desc = agenda.interpretar_cuando(cuando, _zona)
            if not dt:
                return (f"¿Hasta qué día y HORA dejo pendientes los {len(tickets)} ticket(s) de {nom}? "
                        "Decime el día y la hora (por ej. 'mañana 10:00').")
        hechos = []
        for tk in tickets:
            tid = tk["id"]
            try:
                adap.cambiar_estado(tid, "en_espera")
                if dt:
                    from comun import agenda
                    agenda.programar(_nombre, tid, dt.timestamp(), desc)
                hechos.append(f"#{tid}")
            except Exception:  # noqa: BLE001
                pass
        cola = f" hasta {desc} (se reactivan solos)" if dt else ""
        lista = ", ".join(hechos)
        _avisar(f"⏸️ *{len(hechos)} ticket(s)* de {t['nombre']} — EN ESPERA{cola}: {lista}.")
        return f"⏸️ Puse EN ESPERA {len(hechos)} ticket(s) asignados a {t['nombre']}{cola}: {lista}."

    return {
        "cerrar_ticket": {"desc": "Cerrar un ticket. args:{id}", "fn": cerrar},
        "reabrir_ticket": {"desc": "Reabrir un ticket. args:{id}", "fn": reabrir},
        "poner_en_espera": {"desc": "Poner en espera (esperando datos del cliente). args:{id}", "fn": en_espera},
        "asignar_ticket": {"desc": "Asignar a un técnico (bsierra/jayala). args:{id,responsable}", "fn": asignar},
        "responder_ticket": {"desc": "Responder al cliente en un ticket (primera respuesta / seguimiento). args:{id,texto}", "fn": responder},
        "categorizar_ticket": {"desc": "Poner la categoría del ticket. args:{id,categoria}", "fn": categorizar},
        "asignar_sla": {"desc": "Fijar el SLA/OLA (interno y externo) según prioridad. args:{id,prioridad?}", "fn": asignar_sla},
        "aplicar_ciclo": {"desc": "CICLO COMPLETO igual a la demo en UNA acción: categoría + prioridad + SLA/OLA + asigna ITHOS y técnico + 1ª respuesta (pide datos faltantes) + estado. args:{id,categoria,prioridad,responsable,primera_respuesta,necesita_info}", "fn": aplicar_ciclo},
        "crear_ticket": {"desc": "Crear un ticket nuevo. args:{asunto,contenido}", "fn": crear},
        "cambiar_prioridad": {"desc": "Cambiar prioridad. args:{id,prioridad:baja|media|alta|urgente}", "fn": prioridad},
        "escalar_ticket": {"desc": "Escalar (urgente + asignar). args:{id,responsable?}", "fn": escalar},
        "posponer_ticket": {"desc": "Dejar EN ESPERA hasta un día/hora y REACTIVAR solo al llegar. Si falta la hora, la pide. args:{id,cuando:'lunes a la tarde'|'martes 15:30',texto?}", "fn": posponer},
        "poner_en_espera_asignados": {"desc": "Pone EN ESPERA (o pospone hasta un día/hora si dan 'cuando') TODOS los tickets ASIGNADOS a un técnico — SOLO los del campo 'Asignado a', nunca donde la persona es observador o solicitante. Usala SIEMPRE para 'los tickets asignados a X', 'los de X', 'mis tickets' o 'los míos'. args:{persona:'Brian Sierra'|'Alejandro Ayala'|'yo', cuando?:'mañana 10:00'}", "fn": en_espera_asignados},
    }
