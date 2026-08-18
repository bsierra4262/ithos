#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de las MEJORAS DEL HELPDESK pedidas por Brian (jul-2026). Todo SIN RED (GLPI falso), así
corre siempre y sirve de REGRESIÓN:

  NIVEL 1 · WAKE-WORD "Hey ITHOS" (punto 6): activa en español e inglés, en may/min, con tildes,
           con la palabra PARTIDA por el micrófono ('hey it hos'); NO activa con la charla normal
           del grupo ('hola a todos'); y el MICRÓFONO (agente) decide IGUAL que WhatsApp.
  NIVEL 2 · ESPERA "el cliente tiene que confirmar para AVANZAR" (punto 2): recordatorio UNA vez
           por DÍA HÁBIL, escalada al TÉCNICO ASIGNADO a los 5 días hábiles (una sola vez, aunque
           ITHOS se reinicie), nada si el cliente ya respondió o si el ticket está POSPUESTO.
  NIVEL 3 · @MENCIÓN AL ASIGNADO (puntos 3 y 4): mapeo técnico->teléfono, avisos de tickets y de
           SLA @mencionando SOLO al asignado, y los canales sin menciones reciben igual el aviso.

Uso:  python tests/probar_helpdesk_mejoras.py
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
os.environ["ITHOS_DATA"] = tempfile.mkdtemp(prefix="ithos_helpdesk_")   # agenda/datos aislados
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))
sys.path.insert(0, os.path.join(APP, "agente"))

import triage as T                          # noqa: E402
import ciclo as CI                          # noqa: E402  (el ciclo de vida vive acá)
import proactivo as PRO                     # noqa: E402
from comun import wake as W                 # noqa: E402
from comun import tickets as TK             # noqa: E402
from comun import notificadores as N        # noqa: E402
from comun import whatsapp as WA            # noqa: E402
import escucha as MIC                       # noqa: E402

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


# ============================================================ CONFIG DE PRUEBA (como clientes.json)
TECNICOS = [
    {"nombre": "Brian Sierra", "glpi_id": 7, "glpi_login": "bsierra",
     "telefonos": ["5491151629038", "5491156660181"]},
    {"nombre": "Alejandro Ayala", "glpi_id": 8, "glpi_login": "jayala",
     "telefonos": ["+54 9 11 5098-5151"]},
    {"_nota": "esta entrada es un comentario y NO es un técnico"},
]
CFG = {"tecnicos": TECNICOS, "nombre_cliente": "TEST S.A.",
       "zona_horaria": "America/Argentina/Buenos_Aires", "entity_id": 12}
# Para que el test NO dependa de la hora/día en que se corre, se usan dos horarios de atención:
# ABIERTO = siempre abierto (el recordatorio corresponde) · CERRADO = nunca (no corresponde).
CFG_ABIERTO = {**CFG, "horario_atencion": {"dias": [0, 1, 2, 3, 4, 5, 6],
                                           "desde": "00:00", "hasta": "23:59"}}
CFG_CERRADO = {**CFG, "horario_atencion": {"dias": [], "desde": "09:00", "hasta": "18:00"}}


# =========================================================================== NIVEL 1 · WAKE-WORD
def nivel1_wake():
    print("\nNIVEL 1 · wake-word 'Hey ITHOS' (texto del Gestor + micrófono del agente)")
    activan = [
        "Hey ITHOS, cerrá el ticket 651",                 # la LLAMADA: lo único que activa
        "hey ithos",
        "HEY ITHOS!",
        "Hey, Ithos: ¿cómo venimos?",                     # con puntuación
        "hey it hos como va",                             # el micrófono PARTE la palabra
        "hey i thos",
        "oye ithos, reporte",                             # español
        "ok ithos, reporte",                              # inglés/uso común
        "Hola ITHOS",
        "che ithos",
        "hey ethos que onda",                             # pronunciación inglesa mal transcripta
        "hey aitos",
        "Ey, íthos",                                      # con tilde
        "hey itos dame el sla",                           # mal transcripto, pero con la llamada
        "ey izos que paso",
        "ok ithus ayuda",
        "heyithos que hay",                               # llamada y marca pegadas
    ]
    no_activan = [
        "ITHOS que podes hacer ?",                        # nombrarlo suelto NO activa (lo pidió Brian)
        "ithos, dame el estado del 651",
        "preguntale a ITHOS por el ticket",
        "lo cargó ithos ayer",
        "hola a todos",
        "hey todos, buen día",
        "buenas, listos para el lunes?",
        "esos casos ya estan cerrados",
        "estos son los datos que pediste",
        "jarvis, hola",                                   # la marca es ITHOS: jarvis NO activa
        "llamá a Juan por el ticket",
    ]
    for t in activan:
        ok(W.menciona(t), f"activa: {t!r}")
    for t in no_activan:
        ok(not W.menciona(t), f"NO activa: {t!r}")
    ok(W.es_wake("hey ithos") and not W.es_wake("ithos solo"),
       "sólo la FRASE de llamada activa; la marca sola no")
    # El micrófono (Vosk, en el agente) tiene que decidir EXACTAMENTE igual que WhatsApp.
    iguales = all(MIC._menciona(t, "ithos") == W.menciona(t) for t in activan + no_activan)
    ok(iguales, "el micrófono del agente decide igual que WhatsApp (misma fuente: comun/wake.py)")
    ok(WA.menciona("Hey ITHOS, hola") and not WA.menciona("ITHOS, hola"),
       "en TODOS los canales (comun/whatsapp.menciona) rige la misma llamada")


# ============================================================== GLPI FALSO (para el ciclo, sin red)
class GLPIFalso:
    """Lo mínimo que usa gestionar_ciclo: tickets_recientes + request de followups/Ticket_User."""

    def __init__(self, tickets, followups, asignados=None):
        self.tickets = tickets
        self.followups = followups              # {tid: [followup]}
        self.asignados = asignados or {}        # {tid: [users_id]}
        self.pedidos = []

    def tickets_recientes(self, n=40):
        return list(self.tickets)

    def request(self, ruta, metodo="GET", datos=None):
        self.pedidos.append(ruta)
        if ruta.endswith("/ITILFollowup"):
            tid = int(ruta.split("/")[2])
            return list(self.followups.get(tid, []))
        if ruta.endswith("/Ticket_User"):
            tid = int(ruta.split("/")[2])
            return [{"users_id": u, "type": 2} for u in self.asignados.get(tid, [])]
        if ruta.startswith("/User/"):
            return {"firstname": "Cliente", "realname": "Test"}
        return []


class TriageFalso:
    """Registra QUÉ decidió el ciclo, sin tocar GLPI ni la IA."""

    def __init__(self, cfg):
        self.cfg_glpi = cfg
        self.llamadas = []

    def _reg(self, que, *a):
        self.llamadas.append((que, *a))
        return True

    # --- lo que puede pasar en el ciclo ---
    def recordar_espera(self, tid, motivo="confirmacion"):
        return self._reg("recordatorio", tid, motivo)

    def avisar_tecnico_sin_respuesta(self, tid, dias, motivo="confirmacion"):
        return self._reg("escalada", tid, dias, motivo)

    def poner_en_curso(self, tid):
        return self._reg("en_curso", tid)

    def pedir_confirmacion(self, tid):
        return self._reg("pedir_confirmacion", tid)

    def recordar_confirmacion(self, tid):
        return self._reg("recordar_confirmacion", tid)

    def nota_interna(self, tid, txt):
        return self._reg("nota_interna", tid)

    def marcar_resuelto(self, tid, solucion=""):
        return self._reg("resuelto", tid)

    def cerrar(self, tid):
        return self._reg("cerrar", tid)

    def reabrir(self, tid):
        return self._reg("reabrir", tid)

    # --- decisiones de IA: en el test no hay IA -> False/None (no inventa) ---
    def tecnico_resolvio(self, texto):
        return False

    def tecnico_pide_confirmacion(self, texto):
        return False

    def explica_procedimiento(self, texto):
        return None

    def cliente_confirma(self, texto):
        return None

    def hizo(self, que):
        return [x for x in self.llamadas if x[0] == que]


ITHOS_ID = T.ITHOS_ID
PEDIDO_COORD = ("Necesitamos coordinar un día para la visita. Quedamos a la espera de su "
                "respuesta. Soporte ITH.")
# 1ª respuesta del triage cuando FALTA un dato: el triage le agrega el cierre con el marcador de
# espera, así el ciclo sabe que el ticket quedó esperando al cliente (mismo recordatorio diario).
PRIMERA_RESPUESTA_CON_DATO = ("Estimado, para avanzar necesitamos el número de legajo del "
                              "colaborador. Quedamos a la espera de su respuesta. Soporte ITH.")


def _fu(fid, uid, texto, fecha):
    return {"id": fid, "users_id": uid, "content": texto,
            "date_creation": fecha.strftime("%Y-%m-%d %H:%M:%S")}


def _lunes_pasado(dias_atras):
    """Una fecha HÁBIL de referencia: retrocede `dias_atras` días hábiles desde el último lunes
    (así el test no depende del día en que se corre)."""
    hoy = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    while hoy.weekday() != 0:                  # el lunes de esta semana (o el anterior)
        hoy -= timedelta(days=1)
    d = hoy
    quedan = dias_atras
    while quedan > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            quedan -= 1
    return d


# ================================================= NIVEL 2 · ESPERA ESPERANDO CONFIRMACIÓN (punto 2)
def nivel2_espera_confirmacion():
    print("\nNIVEL 2 · espera 'el cliente tiene que confirmar para AVANZAR' (recordatorio + escalada)")

    # -- helper de días hábiles: el fin de semana NO cuenta --
    lun = datetime(2026, 7, 27, 10, 0)         # lunes
    ok(T.dias_habiles_entre(CFG, lun, lun + timedelta(days=1)) == 1, "días hábiles: lunes->martes = 1")
    ok(T.dias_habiles_entre(CFG, datetime(2026, 7, 31, 10, 0),
                            datetime(2026, 8, 3, 10, 0)) == 1,
       "días hábiles: viernes->lunes = 1 (el fin de semana no cuenta)")
    ok(T.dias_habiles_entre(CFG, lun, lun + timedelta(days=7)) == 5, "días hábiles: una semana = 5")
    ok(T.dias_habiles_entre(CFG, lun, lun) == 0, "días hábiles: mismo momento = 0")
    ok(T.dias_habiles_entre(CFG, lun, lun - timedelta(days=3)) == 0, "días hábiles: hacia atrás = 0")

    # -- detección de la espera pendiente (se lee de GLPI, no de la memoria) --
    ayer = datetime.now() - timedelta(days=1)
    fu_pendiente = [_fu(1, 7, "Hay que coordinar la reubicación", ayer),
                    _fu(2, ITHOS_ID, PEDIDO_COORD, ayer)]
    fu_respondido = fu_pendiente + [_fu(3, 99, "Dale, el jueves a la mañana", datetime.now())]
    ok(CI._espera_pendiente(fu_pendiente) is not None,
       "pendiente: ITHOS pidió confirmar y el cliente no contestó")
    ok(CI._espera_pendiente(fu_respondido) is None,
       "NO pendiente: el cliente ya contestó después del pedido")
    ok(CI._espera_pendiente([_fu(1, 7, "Avance interno", ayer)]) is None,
       "NO pendiente: no hubo pedido de confirmación")
    # Los DOS motivos por los que un ticket espera al cliente (Brian: "lo mismo haga pero cuando el
    # cliente deba confirmar algún DATO FALTANTE o en este caso confirmación"):
    fu_datos = [_fu(1, ITHOS_ID, PRIMERA_RESPUESTA_CON_DATO, ayer)]      # 1ª respuesta: falta el legajo
    esp = CI._espera_pendiente(fu_datos)
    ok(esp is not None and esp[2] == "datos",
       "pendiente por DATO FALTANTE (la 1ª respuesta pidió el legajo)", str(esp[2] if esp else None))
    esp2 = CI._espera_pendiente(fu_datos + [_fu(5, 8, "Coordinar la visita", ayer),
                                           _fu(6, ITHOS_ID, PEDIDO_COORD, ayer)])
    ok(esp2 is not None and esp2[2] == "confirmacion",
       "un pedido POSTERIOR del técnico se detecta como CONFIRMACIÓN, no como datos",
       str(esp2[2] if esp2 else None))
    ok("información que le solicitamos" in T._texto_recordatorio_espera("datos")
       and "confirmación" in T._texto_recordatorio_espera("confirmacion"),
       "el recordatorio dice QUÉ se espera (el dato o la confirmación)")
    ok(T._MARCA_ESPERA_CLIENTE in T._con_cierre_espera("Necesito el legajo.").lower(),
       "la 1ª respuesta que pide un dato queda marcada como ESPERA (para el recordatorio diario)")
    ok(T._con_cierre_espera(PEDIDO_COORD) == PEDIDO_COORD,
       "no se duplica el cierre si el texto ya lo trae")
    # Las notas INTERNAS (privadas) no cuentan como pedido al cliente: el cliente no las ve.
    ok(CI._espera_pendiente([{"id": 1, "users_id": ITHOS_ID, "content": PEDIDO_COORD,
                             "is_private": 1, "date_creation": ayer.strftime("%Y-%m-%d %H:%M:%S")}])
       is None, "una nota INTERNA no cuenta como pedido al cliente")

    ticket = {"id": 900, "status": 4, "entities_id": 12, "name": "Molinete fuera de servicio"}

    # -- 1) recordatorio: uno por día, SIEMPRE dentro del horario de atención del cliente --
    cli = GLPIFalso([ticket], {900: fu_pendiente}, {900: [7]})
    tri = TriageFalso(CFG_ABIERTO)
    T.gestionar_ciclo(cli, tri, 12, {})
    ok(len(tri.hizo("recordatorio")) == 1, "recordatorio diario enviado (en horario de atención)")
    tri_cerrado = TriageFalso(CFG_CERRADO)
    T.gestionar_ciclo(GLPIFalso([ticket], {900: fu_pendiente}, {900: [7]}), tri_cerrado, 12, {})
    ok(not tri_cerrado.hizo("recordatorio"),
       "FUERA de horario (noche / fin de semana) NO se le escribe al cliente")
    # el mismo día, otro ciclo: el aviso ya quedó en GLPI con fecha de HOY -> no se repite
    cli.followups[900] = fu_pendiente + [_fu(9, ITHOS_ID, PEDIDO_COORD, datetime.now())]
    tri2 = TriageFalso(CFG_ABIERTO)
    T.gestionar_ciclo(cli, tri2, 12, {})
    ok(not tri2.hizo("recordatorio"), "NO se manda un segundo recordatorio el mismo día")

    # -- 2) el cliente responde -> EN CURSO y ningún recordatorio --
    cli_r = GLPIFalso([ticket], {900: fu_respondido}, {900: [7]})
    tri_r = TriageFalso(CFG_ABIERTO)
    anuncios = T.gestionar_ciclo(cli_r, tri_r, 12, {})
    ok(bool(tri_r.hizo("en_curso")) and not tri_r.hizo("recordatorio"),
       "el cliente respondió -> EN CURSO (y se cortan los recordatorios)")
    ok(anuncios and anuncios[0].get("tel") == ["5491151629038", "5491156660181"],
       "el aviso lleva el teléfono del TÉCNICO ASIGNADO (@mención)",
       str(anuncios[0].get("tel") if anuncios else None))

    # -- 3) escalada al técnico asignado a los 5 días hábiles (una sola vez) --
    viejo = _lunes_pasado(6)
    fu_viejo = [_fu(1, 8, "Coordinar el reemplazo con el cliente", viejo),
                _fu(2, ITHOS_ID, PEDIDO_COORD, viejo)]
    cli_e = GLPIFalso([ticket], {900: fu_viejo}, {900: [8]})
    tri_e = TriageFalso(CFG_ABIERTO)
    est_e = {}
    anuncios = T.gestionar_ciclo(cli_e, tri_e, 12, est_e)
    esc = tri_e.hizo("escalada")
    ok(len(esc) == 1 and esc[0][2] >= T._DIAS_HABILES_ESCALADA,
       f"escalada al técnico a los >= {T._DIAS_HABILES_ESCALADA} días hábiles sin respuesta",
       str(esc))
    tel_esc = [a for a in anuncios if "sin respuesta" in a.get("wa", "")]
    ok(bool(tel_esc) and tel_esc[0]["tel"] == ["5491150985151"],
       "la escalada @menciona SOLO al técnico asignado (Alejandro)",
       str(tel_esc[0]["tel"] if tel_esc else None))
    ok("Asignado a: Alejandro Ayala" in tel_esc[0]["wa"] if tel_esc else False,
       "el aviso NOMBRA al asignado (para los canales sin @menciones)")
    T.gestionar_ciclo(cli_e, tri_e, 12, est_e)
    ok(len(tri_e.hizo("escalada")) == 1, "la escalada NO se repite en el ciclo siguiente")

    # -- 4) tras un REINICIO (estado en memoria vacío) tampoco se repite: el marcador está en GLPI --
    cli_e.followups[900] = fu_viejo + [_fu(5, ITHOS_ID, T._nota_escalada_espera(5, "confirmacion"),
                                           datetime.now())]
    tri_r2 = TriageFalso(CFG_ABIERTO)
    T.gestionar_ciclo(cli_e, tri_r2, 12, {})
    ok(not tri_r2.hizo("escalada"), "tras un reinicio no se re-escala (marcador leído de GLPI)")

    # -- 5) ticket POSPUESTO (reactivación agendada): no se molesta a nadie --
    from comun import agenda
    agenda.programar(CFG["nombre_cliente"], 900, (datetime.now() + timedelta(days=3)).timestamp(),
                     "el jueves 10:00")
    tri_p = TriageFalso(CFG_ABIERTO)
    T.gestionar_ciclo(GLPIFalso([ticket], {900: fu_viejo}, {900: [8]}), tri_p, 12, {})
    ok(not tri_p.hizo("recordatorio") and not tri_p.hizo("escalada"),
       "ticket POSPUESTO: ni recordatorio ni escalada (el técnico decidió esperar)")
    agenda.cancelar(CFG["nombre_cliente"], 900)

    # -- 6) ticket RESUELTO sin respuesta del cliente: recordatorio 1 vez por DÍA LABORAL, en horario
    #       (antes salía cada 24 h a cualquier hora, incluso de madrugada o un domingo) --
    resuelto = {"id": 901, "status": 5, "entities_id": 12, "name": "No podía fichar"}
    pedido_conf = ("Le informamos que su solicitud fue resuelta. Por favor, confírmenos si ya puede "
                   "fichar con normalidad para cerrar el ticket. Soporte ITH.")
    fu_conf = [_fu(1, ITHOS_ID, pedido_conf, datetime.now() - timedelta(days=2))]
    tri_c1 = TriageFalso(CFG_ABIERTO)
    T.gestionar_ciclo(GLPIFalso([resuelto], {901: fu_conf}), tri_c1, 12, {})
    ok(len(tri_c1.hizo("recordar_confirmacion")) == 1,
       "RESUELTO sin respuesta: recuerda la confirmación (1 vez, en horario)")
    tri_c2 = TriageFalso(CFG_CERRADO)
    T.gestionar_ciclo(GLPIFalso([resuelto], {901: fu_conf}), tri_c2, 12, {})
    ok(not tri_c2.hizo("recordar_confirmacion"),
       "RESUELTO fuera de horario: NO se le escribe al cliente")
    tri_c3 = TriageFalso(CFG_ABIERTO)
    T.gestionar_ciclo(GLPIFalso([resuelto], {901: [_fu(1, ITHOS_ID, pedido_conf, datetime.now())]}),
                      tri_c3, 12, {})
    ok(not tri_c3.hizo("recordar_confirmacion"),
       "RESUELTO: no se repite el recordatorio el mismo día")

    # -- 7) el recordatorio NO cambia el estado del ticket (sigue EN ESPERA, SLA pausado) --
    ok(all(not str(p).startswith("/Ticket/900") or "Ticket_User" in str(p) or
           "ITILFollowup" in str(p) for p in cli.pedidos),
       "el ciclo no escribe el estado del ticket al recordar (queda EN ESPERA, SLA pausado)")


# ================================================== NIVEL 3 · @MENCIÓN AL ASIGNADO (puntos 3 y 4)
class CanalConMencion:
    def __init__(self):
        self.menciones, self.textos = [], []

    def enviar(self, texto):
        self.textos.append(texto)
        return True

    def enviar_mencion(self, texto, telefonos):
        self.menciones.append((texto, list(telefonos)))
        return True


class CanalSinMencion:
    def __init__(self):
        self.textos = []

    def enviar(self, texto):
        self.textos.append(texto)
        return True


def nivel3_mencion():
    print("\nNIVEL 3 · @mención al TÉCNICO ASIGNADO en los avisos de tickets y de SLA")
    # -- mapeo técnico -> teléfono/nombre (por id de GLPI, por login y por nombre) --
    ok(TK.telefonos_asignados(CFG, [7]) == ["5491151629038", "5491156660181"],
       "teléfonos del asignado por glpi_id")
    ok(TK.telefonos_asignados(CFG, [8]) == ["5491150985151"],
       "teléfono normalizado a dígitos (+54 9 11 5098-5151)")
    ok(TK.telefonos_asignados(CFG, ["jayala"]) == ["5491150985151"], "también resuelve por login")
    ok(TK.telefonos_asignados(CFG, ["Brian Sierra"])[0] == "5491151629038",
       "también resuelve por nombre (otros sistemas de tickets)")
    ok(TK.telefonos_asignados(CFG, [999]) == [], "técnico no configurado -> sin @mención (no falla)")
    ok(TK.nombres_asignados(CFG, [7, 8]) == ["Brian Sierra", "Alejandro Ayala"],
       "nombres de los asignados")
    ok(len(TK.tecnicos(CFG)) == 2, "las entradas '_nota' de la config no se cuentan como técnicos")

    # -- el multicanal @menciona donde puede y NUNCA pierde el aviso donde no --
    con, sin = CanalConMencion(), CanalSinMencion()
    notif = N.Notificadores([con, sin])
    notif.enviar_mencion("⚠️ SLA en riesgo #900", ["5491151629038"])
    ok(con.menciones and con.menciones[0][1] == ["5491151629038"],
       "WhatsApp recibe la @mención con el teléfono del asignado")
    ok(sin.textos == ["⚠️ SLA en riesgo #900"],
       "un canal sin @menciones recibe igual el aviso (nunca se pierde)")
    notif2 = N.Notificadores([CanalConMencion()])
    ok(notif2.enviar_mencion("aviso", []) is True, "sin teléfonos: envío normal (no se pierde)")

    # -- alerta de SLA: un aviso por técnico, @mencionándolo; los sin asignar van aparte --
    riesgo = [{"id": 1, "asunto": "Molinete", "faltan_horas": 1.5, "vencido": False, "asignados": [7]},
              {"id": 2, "asunto": "Terminal", "faltan_horas": -2.0, "vencido": True, "asignados": [7]},
              {"id": 3, "asunto": "Interface", "faltan_horas": 0.5, "vencido": False, "asignados": [8]},
              {"id": 4, "asunto": "Sin dueño", "faltan_horas": 2.0, "vencido": False, "asignados": []}]
    grupos = PRO._por_tecnico({"tecnicos": TECNICOS}, riesgo)
    por_nombre = {n: (tels, [t["id"] for t in ts]) for n, tels, ts in grupos}
    ok(por_nombre.get("Brian Sierra", ("", []))[1] == [1, 2],
       "los tickets de Brian van en un solo aviso para él")
    ok(por_nombre.get("Alejandro Ayala", ("", []))[1] == [3], "los de Alejandro, en el suyo")
    ok(por_nombre.get("", ([], []))[0] == [] and por_nombre.get("", ([], []))[1] == [4],
       "los tickets sin asignado configurado van sin @mención")
    texto = PRO._texto_alerta([riesgo[0], riesgo[1]], "Brian Sierra")
    ok("Brian Sierra" in texto and "#1" in texto and "SLA VENCIDO" in texto,
       "el texto de la alerta nombra al asignado y detalla vencidos/por vencer")


# ============================== NIVEL 4 · "MIS TICKETS" SIN PEDIR DATOS (identifica por el número)
class AdaptadorFalso:
    """Adaptador de tickets simulado: responde `asignados_a` como el de GLPI."""

    def __init__(self, por_tecnico):
        self.por_tecnico = por_tecnico
        self.consultas = []

    def asignados_a(self, glpi_id):
        self.consultas.append(glpi_id)
        return self.por_tecnico.get(int(glpi_id), [])


def nivel4_mis_tickets():
    print("\nNIVEL 4 · 'los tickets asignados a mí' (identifica por el número, no pide legajo)")
    import comun.conversacion as CV

    adap = AdaptadorFalso({7: [{"id": 659, "asunto": "No puede fichar", "estado": "En espera"},
                               {"id": 660, "asunto": "Molinete trabado", "estado": "En curso"}],
                           8: []})
    from comun import tickets as _TK
    original = _TK.adaptador
    _TK.adaptador = lambda cfg: adap                      # sin red: adaptador simulado
    try:
        herr = CV.herramientas_tickets({**CFG, "nombre": "TEST S.A."})
        ok("tickets_asignados" in herr, "existe la acción de LECTURA 'tickets_asignados'")
        fn = herr["tickets_asignados"]["fn"]

        # 1) "mis tickets" desde el número de Brian: lo resuelve solo y NO pide nada
        r = fn({"persona": "yo", "_remitente": "5491156660181"})
        ok("659" in r and "660" in r and "En espera" in r,
           "responde los tickets del que escribe con su estado", r[:80])
        ok(not any(p in r.lower() for p in ("legajo", "nombre completo", "indicame tu")),
           "NO pide legajo ni nombre (ya está mapeado por el número)")
        ok(adap.consultas == [7], "consulta por el glpi_id del técnico correcto (Brian = 7)",
           str(adap.consultas))

        # 2) por nombre, y con el número en otro formato (+54 9 11 …)
        r2 = fn({"persona": "Alejandro Ayala", "_remitente": "5491151629038"})
        ok("no tiene tickets abiertos" in r2.lower(), "por NOMBRE también resuelve (Alejandro, sin tickets)")
        r3 = fn({"persona": "mis", "_remitente": "+54 9 11 5162-9038"})
        ok("659" in r3, "el número con prefijo/guiones también identifica a la persona")

        # 3) un número desconocido no inventa: ofrece los técnicos cargados
        r4 = fn({"persona": "yo", "_remitente": "5491100000000"})
        ok("Brian Sierra" in r4 and "Alejandro Ayala" in r4,
           "número no mapeado -> pregunta de quién, ofreciendo los técnicos cargados")

        # 4) el prompt le dice al modelo que use esta acción y que NO pida el legajo
        src = "".join(open(os.path.join(APP, "comun", f), encoding="utf-8").read()
                      for f in ("asistente.py", "herramientas.py"))
        ok("'tickets_asignados' args:{persona:'yo'" in src
           and "NUNCA le pidas su nombre" in src and "legajo ni su usuario" in src,
           "el prompt manda usar tickets_asignados y prohíbe pedir nombre/legajo")
    finally:
        _TK.adaptador = original


if __name__ == "__main__":
    print("=" * 78)
    print("MEJORAS DEL HELPDESK — wake-word 'Hey ITHOS' · espera con confirmación · @mención")
    print("=" * 78)
    nivel1_wake()
    nivel2_espera_confirmacion()
    nivel3_mencion()
    nivel4_mis_tickets()
    print("\n" + "=" * 78)
    if FALLAS:
        print(f"FALLARON {len(FALLAS)} chequeo(s):")
        for f in FALLAS:
            print("  · " + f)
        sys.exit(1)
    print("TODO OK — las 3 mejoras quedan verificadas y con test de regresión.")
