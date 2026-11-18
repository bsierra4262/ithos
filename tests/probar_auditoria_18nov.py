#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regresión de los bugs que encontró la auditoría completa del 18-nov-2026 (cuando ITHOS pasó a ser
una herramienta interna). Cada chequeo falla con el bug y pasa con el arreglo.

Correr:  python tests/probar_auditoria_18nov.py
"""

import inspect
import os
import sys
import tempfile
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "ITHOS")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "central"))
_TMP = tempfile.mkdtemp(prefix="ithos_18nov_")
os.environ["ITHOS_DATA"] = _TMP

FALLAS = []


def ok(cond, nombre, detalle=""):
    print(("  OK   " if cond else "  FALLA") + f" · {nombre}" + (f" — {detalle}" if detalle else ""))
    if not cond:
        FALLAS.append(nombre)


def leer(*p):
    return open(os.path.join(APP, *p), encoding="utf-8").read()


print("\n=== El PDF del reporte va al grupo de su tipo (no al de consultas) ===")
from comun import whatsapp as WA          # noqa: E402
w = WA.WhatsAppNoOficial.__new__(WA.WhatsAppNoOficial)
w.grupos = [{"grupo": "ITHOS", "ambito": "consultas", "jid": "J-CONSULTAS"},
            {"grupo": "ITHOS_SOPORTE", "ambito": "soporte", "jid": "J-SOPORTE"}]
w._listo = threading.Event()
w._listo.set()
enviados = []
w.client = type("C", (), {"send_document": lambda self, jid, *a, **k: enviados.append(jid)})()
w.enviar_documento("r.pdf", b"%PDF", "application/pdf", "Reporte", tipo="sla")
ok(enviados == ["J-SOPORTE"], "el PDF con tipo 'sla' va SÓLO al grupo de soporte", str(enviados))
ok("tipo=AMB.SLA" in leer("central", "reportes_programados.py").split("enviar_documento", 1)[1],
   "y el reporte programado lo manda con ese tipo")

print("\n=== La verificación por voz del dueño, ante la duda, NIEGA ===")
from comun import vozid as V              # noqa: E402
_p, _v = V.perfil_listo, V._voiceprint
V.perfil_listo = lambda: True
V._voiceprint = lambda *a, **k: None
ok(V.verificar(b"\x00" * 3200)[0] is False, "audio sin voz utilizable -> NO es el dueño")
V._voiceprint = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("roto"))
ok(V.verificar(b"\x00" * 3200)[0] is False, "un error al analizar -> NO es el dueño")
V.perfil_listo = lambda: False
ok(V.verificar(b"\x00" * 3200)[0] is False, "sin perfil entrenado -> NO es el dueño")
V.perfil_listo, V._voiceprint = _p, _v

print("\n=== La voz por micrófono no rompe cuando falla la IA ===")
from comun import asistente as AS         # noqa: E402
src = inspect.getsource(AS.Asistente.responder_stream)
ok("except Exception as e:" in src and "_es_429(e)" in src,
   "el error del streaming se captura con nombre (antes: NameError en el respaldo)")

print("\n=== El detalle de un ticket trae TODOS los seguimientos ===")
from comun import tickets as TK           # noqa: E402
ok("pagina_todo(c, f\"/Ticket/{tid}/ITILFollowup\")" in inspect.getsource(TK._GLPI.detalle),
   "detalle() pagina (sin rango GLPI devuelve sólo los 50 más viejos)")

print("\n=== El equipo sale de la configuración, no del código ===")
eq_src = leer("central", "equipo.py")
ok(not any(x in eq_src for x in ('"lzaltron"', '"lcampos"', '"jayala"', '"bsierra"', "ITHOS_ID = 28")),
   "equipo.py no tiene personas ni la cuenta de ITHOS escritas")
ok(not hasattr(TK, "_TECNICOS"), "tickets.py no tiene la tabla fija de técnicos")
import equipo as EQ                       # noqa: E402
EQ.configurar({"tecnicos": [{"nombre": "Ana Uno", "glpi_login": "auno", "glpi_id": 41},
                            {"nombre": "Beto Dos", "glpi_login": "bdos", "glpi_id": 42}],
               "integrador_glpi": {"ithos_user_id": 99},
               "reparto": {"mesa": ["auno"], "instalaciones": "bdos", "escalamiento": "auno"}})
ok(EQ.ITHOS_ID == 99 and EQ.RESPONSABLES == {"auno": 41, "bdos": 42} and EQ.MESA == ["auno"]
   and EQ.instalaciones() == "bdos" and EQ.TECNICOS == {41, 42, 99},
   "configurar() arma personas, roles y la cuenta de ITHOS desde la config")
EQ._cargar_de_config()                    # deja el equipo real para el resto de los tests
ok(TK._uid_tecnico({"tecnicos": [{"nombre": "Laura Zaltron", "glpi_login": "lzaltron", "glpi_id": 30}]},
                   "lzaltron") == 30, "aplicar_ciclo/asignar resuelven a Laura por la config")
ok("_uid_tecnico(self.equipo, responsable)" in inspect.getsource(TK._GLPI.aplicar_ciclo),
   "aplicar_ciclo asigna con el equipo de la config (antes: sólo Brian y Alejandro)")

print("\n=== La búsqueda de técnico por nombre no acepta pedazos sueltos ===")
from comun import herramientas as HE      # noqa: E402
tec = [{"nombre": "Laura Zaltron", "glpi_id": 30}, {"nombre": "Alejandro Ayala", "glpi_id": 8}]
ok(HE._resolver_tecnico("la", None, tec) is None, "'la' no es Laura")
ok((HE._resolver_tecnico("laura", None, tec) or {}).get("glpi_id") == 30, "'laura' sí")
ok((HE._resolver_tecnico("ale", None, tec) or {}).get("glpi_id") == 8, "'ale' es Alejandro (comienzo de 3+ letras)")

print("\n=== La nota interna del triage dice la PERSONA, no 'mesa' ===")
ok('a["responsable"] = resp_login' in leer("central", "triage.py"),
   "después de elegir al de menos carga, el responsable es esa persona")

print("\n=== Una reactivación programada en el medio no se pierde ===")
from comun import agenda as AG            # noqa: E402
AG.programar("EMP", 101, time.time() - 5, "vencido")


def _reactivar(x):
    AG.programar("EMP", 202, time.time() + 3600, "nuevo, programado mientras se reactivaba")
    return True


AG.procesar(_reactivar, cliente="EMP")
tids = sorted(int(x.get("tid")) for x in AG.pendientes("EMP"))
ok(tids == [202], "queda el programado en el medio y sale el reactivado", str(tids))

print("\n=== Servicios del Gestor ===")
main_src = leer("central", "main.py")
ok("notificadores_activos.pop(cliente" not in main_src,
   "el WhatsApp no se 'olvida' al desconectarse el agente (salud y aviso de mantenimiento)")
ok('srv.get("inicio_avisado")' in main_src, "el aviso 'ITHOS en línea' sale UNA vez por arranque")
ok("registro.cambio()" in main_src and "os._exit(0)" in main_src,
   "lo guardado en el panel se aplica (el Gestor se reinicia solo)")
ok("mantener_despierto" not in main_src, "el Gestor (Docker) no intenta evitar la suspensión")
ok("ahora_zona(conf)" in leer("central", "kb_auto.py"), "la KB semanal corre en la hora de la empresa")
ok("NO lo borro para no perder" in leer("central", "planka_rollover.py"),
   "el cierre de año de Planka no borra un mes sin archivarlo")

print("\n=== Reporte ITIL honesto ===")
ri = leer("comun", "reportes_itil.py")
ok("reaperturas" not in ri, "sin el indicador de reaperturas que siempre daba 0")
ok("takeintoaccount_delay_stat" in ri, "la 1ª respuesta la mide GLPI (no la resolución)")

print("\n=== Sólo las IA que usamos ===")
from comun import ia as IA                # noqa: E402
ok(not any(hasattr(IA, n) for n in ("ClaudeIA", "OpenAIIA", "GrokIA", "DeepSeekIA", "MistralIA",
                                    "OpenRouterIA", "CerebrasIA", "DeepSeekLocalIA", "LocalVoz")),
   "fuera los 8 proveedores sin uso y la voz local sin terminar")
ok(type(IA._single({"proveedor": "claude", "gemini_api_key": "x"})).__name__ == "GeminiIA",
   "un proveedor que no existe cae a Gemini (y lo dice en el log)")

print()
if FALLAS:
    print(f"  AUDITORÍA 18-NOV: {len(FALLAS)} FALLA(S)")
    sys.exit(1)
print("  AUDITORÍA 18-NOV: OK — todos los bugs encontrados quedan cubiertos")
