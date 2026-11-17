#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Elige el MEJOR modelo local para la máquina, midiéndolo con lo que ITHOS hace de verdad.

POR QUÉ EXISTE. La IA local es el último eslabón de la cadena —la que atiende cuando Gemini y Groq
se quedan sin cuota— y la que usan las pruebas. Pedido de Brian: tenerla SIEMPRE en el mejor modelo
que esa máquina pueda correr. Eso no se decide por fama ni por el tamaño: cambian los modelos,
cambia la VPS, y lo que importa es si clasifica bien un ticket con el prompt real y en cuánto
tiempo. Esto lo mide, y es un solo comando.

QUÉ MIDE, con la MISMA clase `LocalIA` que usa producción (no una imitación):
  · el triage completo (`cerebro.clasificar_ticket`, prompt real) sobre tickets reales de SRT:
    categoría, alcance, y que salude a quien abrió el ticket y no a la persona afectada;
  · las preguntas de sí/no del ciclo de vida (¿resolvió?, ¿confirma?, ¿cancela?);
  · el tiempo y la memoria que ocupa el modelo cargado.

Lo que se aprendió midiendo, para no repetirlo: en la VPS de hoy (2 vCPU, 7,8 GB, sin GPU ni swap)
sólo `qwen3:4b` clasificó bien (3/3 y 3/3, ~100 s). `llama3.2:3b` confunde el alcance,
`granite4:7b-a1b-h` saluda al afectado y queda al tope de memoria, y `gemma4:e2b` devuelve vacío.
`gemma4:e4b` ni se probó: pesa 6,6 GB y no entra sin arriesgar al Gestor.

CÓMO SE CORRE. Adentro del Gestor, que es donde están ITHOS y la red de Docker que llega a Ollama:

    docker cp tests/medir_ia_local.py jarvis-cloud-central-1:/tmp/medir.py
    docker exec jarvis-cloud-ollama-1 ollama pull <modelo-candidato>
    docker exec -e MODELOS="qwen3:4b,<modelo-candidato>" jarvis-cloud-central-1 python /tmp/medir.py

Gana el que clasifica todo bien; entre los que empatan, el más rápido. El ganador se pone en la
config del cliente (`ia.terciario.modelo_texto`) y los perdedores se borran con `ollama rm`, que
cada uno ocupa varios GB.

Sale con código 1 si NINGÚN modelo sirve: en ese caso la IA local no aporta y conviene sacarla.
"""

import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# Adentro del contenedor el código vive en /app; desde el repo, en ITHOS/ y ITHOS/central/.
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ("/app", os.path.join(_RAIZ, "ITHOS"), os.path.join(_RAIZ, "ITHOS", "central")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import cerebro                                    # noqa: E402
from comun.ia import LocalIA                      # noqa: E402

URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")

# Tickets REALES de SRT con lo que tendría que salir. El solicitante es Pablo: si el modelo saluda
# a la persona del asunto (el empleado del legajo), está mal aunque acierte todo lo demás.
TICKETS = [
    ("Legajo 14616 Facundo Martin Gutierrez Monaco",
     "El agente no puede fichar, la terminal no le reconoce el rostro.",
     "individual", "TERMINALES"),
    ("Molinete trabado en sede central",
     "El molinete de ingreso quedo trabado, no baja la traba y nadie de la sede puede pasar.",
     "sede", "MOLINETES"),
    ("Legajo 07209 - Sereno, Giselle Paula",
     "Al fichar la primera vez aparece un nombre que no le pertenece. Varios agentes "
     "manifiestan lo mismo.",
     "grupo", "TERMINALES"),
]
AFECTADOS = ("facundo", "giselle", "sereno", "monaco")

SI_NO = [
    ("resolvio", "Un TÉCNICO dejó un comentario. ¿Dice que el problema YA quedó RESUELTO? "
                 "Respondé SOLO JSON: {\"resuelto\": true|false}",
     "El inconveniente quedó solucionado, le volvimos a dar acceso en la terminal.",
     "resuelto", True),
    ("confirma", "¿El CLIENTE confirma que su problema se solucionó? "
                 "Respondé SOLO JSON: {\"confirma\": true|false}",
     "listo afirmativamente!", "confirma", True),
    ("cancela", "¿El CLIENTE está dando de baja el pedido? ANTE LA DUDA false. "
                "Respondé SOLO JSON: {\"cancela\": true|false}",
     "Ya se soluciono, gracias", "cancela", False),
]


def _memoria():
    """Memoria del contenedor de Ollama ahora, si se puede saber (sólo con acceso a docker)."""
    try:
        return subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}",
             "jarvis-cloud-ollama-1"], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:  # noqa: BLE001
        return "?"


def medir(modelo):
    ia = LocalIA({"ollama_url": URL, "modelo_texto": modelo, "proveedor": "local"})
    r = {"modelo": modelo, "cat": 0, "alc": 0, "saludo": 0, "sino": 0, "seg": []}
    print(f"\n=== {modelo} ===")
    for asunto, desc, alc_ok, cat_ok in TICKETS:
        t0 = time.time()
        try:
            a = cerebro.clasificar_ticket(ia, asunto, desc, solicitante="Pablo") or {}
        except Exception as e:  # noqa: BLE001
            print(f"  triage   FALLA {time.time() - t0:5.0f}s -> {str(e)[:80]}")
            continue
        seg = time.time() - t0
        r["seg"].append(seg)
        c, al = a.get("categoria"), a.get("alcance")
        saludo = str(a.get("primera_respuesta") or "").lower()[:40]
        bien_saludo = "pablo" in saludo and not any(x in saludo for x in AFECTADOS)
        r["cat"] += c == cat_ok
        r["alc"] += al == alc_ok
        r["saludo"] += bien_saludo
        print(f"  triage  {seg:5.0f}s  categoria={c!s:<11}{'ok' if c == cat_ok else 'MAL':<4}"
              f"alcance={al!s:<11}{'ok' if al == alc_ok else 'MAL':<4}"
              f"saludo={'ok' if bien_saludo else 'MAL'}")
    for nombre, sistema, texto, clave, esperado in SI_NO:
        t0 = time.time()
        try:
            v = json.loads(ia.chat(sistema, texto, json_out=True)).get(clave)
            r["sino"] += v is esperado
            print(f"  {nombre:<8}{time.time() - t0:5.0f}s  {v!s:<6}{'ok' if v is esperado else 'MAL'}")
        except Exception as e:  # noqa: BLE001
            print(f"  {nombre:<8} FALLA -> {str(e)[:80]}")
    r["mem"] = _memoria()
    r["prom"] = sum(r["seg"]) / len(r["seg"]) if r["seg"] else float("inf")
    n = len(TICKETS)
    print(f"  -> categoria {r['cat']}/{n} · alcance {r['alc']}/{n} · saludo {r['saludo']}/{n} · "
          f"si/no {r['sino']}/{len(SI_NO)} · triage {r['prom']:.0f}s · memoria {r['mem']}")
    return r


def main():
    modelos = [m.strip() for m in os.environ.get("MODELOS", "qwen3:4b").split(",") if m.strip()]
    resultados = [medir(m) for m in modelos]
    n = len(TICKETS)
    # Sirve el que clasifica TODO bien: un triage que erra el alcance asigna mal y pide lo que no
    # corresponde, y eso es peor que tardar. Las preguntas de sí/no no descalifican: una respuesta
    # dudosa no decide nada (ver triage._si_o_no), sólo se reintenta.
    sirven = [r for r in resultados if r["cat"] == n and r["alc"] == n and r["saludo"] == n]
    print("\n" + "=" * 70)
    if not sirven:
        print("  NINGUNO SIRVE: ningún modelo clasificó bien los tres tickets.")
        print("  En esta máquina la IA local no aporta; conviene sacarla.")
        print("=" * 70)
        sys.exit(1)
    mejor = min(sirven, key=lambda r: r["prom"])
    print(f"  GANA {mejor['modelo']}: clasifica todo bien y es el más rápido de los que lo logran "
          f"({mejor['prom']:.0f}s por triage).")
    print("=" * 70)


if __name__ == "__main__":
    main()
