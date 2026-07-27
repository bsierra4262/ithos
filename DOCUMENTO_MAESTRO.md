# ITHOS — Documento Maestro

> Índice único del proyecto. Se mantiene actualizado a medida que evoluciona el sistema.
> ITHOS es un asistente de IA **multi-cliente (SaaS)** para operaciones: control de acceso por voz,
> mesa de ayuda inteligente sobre GLPI, comunicación multicanal (WhatsApp), facturación y gestión de
> tareas del equipo (Planka). Marca comercial: **ITHOS** (INTELLIHELP S.A.).

---

## 1. Qué hace

| Módulo | Qué resuelve |
|---|---|
| **Portero por voz** | Anuncia por los parlantes los fichajes/accesos leídos de IVMS (SQL Server), con voz natural (Charon). |
| **Mesa de ayuda (GLPI)** | Clasifica, prioriza, asigna, responde y gestiona el ciclo de vida de los tickets con IA. |
| **WhatsApp conversacional** | Escucha el grupo del cliente (activación por "ithos", texto o audio) y responde/actúa. |
| **Reportes ITIL** | Resumen automático (volumen, SLA, MTTR) en la zona horaria y días hábiles del cliente. |
| **Facturación** | Ciclo SaaS con MercadoPago: cobro, dunning, gracia y suspensión. |
| **Tareas del equipo (Planka)** | Mantiene el tablero Kanban del equipo 100% actualizado desde WhatsApp. |

Cada cliente configura y activa lo que usa (todo por `clientes.json`, sin tocar código).

---

## 2. Arquitectura

- **GESTOR (central)** — el cerebro. Se hostea (VPS Hostinger, Docker). Expone WebSocket para los agentes,
  webhooks (MercadoPago/WhatsApp), el panel superadmin + dashboard del cliente + alta. Crítico, 24/7.
- **AGENTE** — liviano, en el equipo del cliente. Ejecuta lo que el Gestor manda (voz por los parlantes,
  integrador de acceso IVMS, micrófono). Empaquetado como `.exe` firmado (Windows) o script (Linux/Mac).
- **Cadena multi-IA** — una IA por consulta; pasa a la siguiente solo al agotarse (Gemini → Cerebras → Groq),
  configurable por cliente. Voz = TTS dedicado de Gemini (Charon, verbatim) para los parlantes; edge-tts
  para las notas de voz de WhatsApp.

```
Cliente (equipo)                         VPS Hostinger (Docker)
┌──────────────┐   WSS (agente_token)   ┌──────────────────────────────┐
│  AGENTE .exe │◄──────────────────────►│  central (8080)  panel (8090) │
│  voz + IVMS  │                        │  caddy (80/443, TLS/WSS)      │
└──────────────┘                        └──────────────────────────────┘
        ▲                                          │
        │ parlantes / micrófono                    ▼  GLPI · MercadoPago · WhatsApp · Planka
```

---

## 3. Estructura del repositorio

```
jarvis-cloud/                 (raíz)
├── ITHOS/                    ← TODO el software (deployable, autocontenido)
│   ├── comun/                (código compartido: IA, GLPI, WhatsApp, Planka, voz, etc.)
│   ├── central/              (el Gestor: main, panel, triage, integradores, reportes)
│   ├── agente/               (el Agente: voz, escucha, integradores de acceso, GUI)
│   ├── docker-compose.yml    (despliegue del Gestor)
│   └── Caddyfile             (TLS/WSS automático)
├── docs/                     ← documentación (.md)
├── tests/                    ← baterías de prueba (probar_*.py)
├── compilador/               ← build/ (PyInstaller, Inno, firma) + instaladores/ + dist/
├── DOCUMENTO_MAESTRO.md      ← este archivo
├── README.md · requirements.txt · .env.example · .gitignore
```

**Reproducible y sin secretos:** el repo NO incluye credenciales. Para desplegar se copian los templates
(`ITHOS/central/clientes.ejemplo.json` → `clientes.json`, `.env.example` → `.env`) y se completan con
**secretos nuevos**. Todo lo sensible/dato-por-cliente está en `.gitignore`.

---

## 4. Mesa de ayuda GLPI — lógica del triage

- **Primer triage**: clasifica categoría/prioridad/SLA, asigna a ITHOS + responsable, saluda al **solicitante**
  por su nombre, y responde. Corrige un ticket mal cargado; pide el dato faltante (legajo) si hace falta.
- **Respeta lo manual**: una vez triado por ITHOS, NO re-categoriza ni pisa una reasignación del técnico.
- **Coordinación → En espera**: si el técnico pide **coordinar/confirmar** algo con el cliente (aún redactado
  impersonal, "se deberá coordinar la reubicación"), ITHOS deja el ticket **En espera** (frena el SLA), le pide
  confirmación al cliente y avisa por WhatsApp.
- **Comentarios internos (privados)**: ITHOS deja notas `is_private` (solo técnicos) cuando el ticket viene mal
  cargado, o pide al técnico que documente el **procedimiento paso a paso** si resolvió sin explicar cómo
  (alimenta la base de conocimiento).
- **Fuera de horario**: un ticket que entra fuera del horario de atención (Lun-Vie 9-18, zona del cliente) se
  deja En espera y se reabre solo al comenzar la jornada — sin que el cliente se entere (nota interna).
- **SLA de SRT**: calendarios Lun-Vie 09:00-18:00 (fines de semana excluidos).

---

## 5. Tareas del equipo — Planka (solo INTELLIHELP)

Integración `ITHOS/central/planka_integrador.py` (cliente `ITHOS/comun/planka.py`, auth header `X-API-Key`):

- **09:00** — resumen por persona (@mención con sus tarjetas: Por hacer / Haciendo / En espera).
- **10:00-18:00, cada hora** (Lun-Vie) — "¿cómo vas?" por las tarjetas activas (skip las movidas hace <1h).
- **Mover / crear por WhatsApp**: "ithos, terminé X" → a Hecho; "ithos, cargá tal tarea para Carlos en
  haciendo" → crea la tarjeta asignada. Intérprete **conservador**: si es ambiguo, no adivina.
- **Escucha proactiva** + trigger **"ithos"** obligatorio en todo mensaje (audio o texto).
- **Rollover automático** (`ITHOS/central/planka_rollover.py`): de Agosto en adelante, un **proyecto por
  mes** ("Agosto 2026") con un **board por semana** (lun-vie), cada uno con las 4 listas. Al cambiar de
  semana/mes ITHOS crea lo que falte y **arrastra lo no terminado** (todo lo que no esté en "Hecho") al
  nuevo período, en su misma lista; lo terminado queda de historial. Julio y meses anteriores no se tocan
  (`mes_legacy`). Idempotente y **sobrevive reinicios** (persiste la semana/board en curso).

---

## 6. Facturación (SaaS)

Ciclo con MercadoPago: cobro por plan, **dunning** por email/canales, **7 días hábiles de gracia** y luego
**SUSPENSIÓN** que congela la IA/ITHOS hasta pagar (el propietario nunca se corta). El alta es un enlace
temporal de un solo uso; solo INTELLIHELP accede al Gestor.

---

## 7. Despliegue

**Gestor (VPS Linux, Docker):**
```bash
cp ITHOS/central/clientes.ejemplo.json ITHOS/central/clientes.json   # completar con datos reales
cp .env.example ITHOS/.env                                           # ITHOS_ADMIN_USER/TOKEN, ITHOS_MASTER_KEY
cd ITHOS && docker compose -p jarvis-cloud up -d --build             # -p conserva los volúmenes de datos
```
Caddy resuelve TLS/WSS automático; el agente del cliente se conecta a `wss://TU-DOMINIO/ws`.

**Agente (equipo del cliente):** instalador único (Windows: Inno firmado `compilador/build/ithos-agente.iss`;
Linux/Mac: `compilador/instaladores/agente_*.sh`). Datos/caché en `%LOCALAPPDATA%/ITHOS`; desinstala sin rastro.

---

## 8. Calidad

- **Baterías** en `tests/` (ciclo de vida de tickets, sistema, producción) + una batería de requerimientos
  transversales (multiplataforma, sin código muerto, latencia sin N+1, etc.).
- Cada bug reportado se arregla **y** se suma como test de regresión.
- Código nivel senior (clean code, PEP 8), portable (Windows/Linux/Mac), UTF-8 explícito, rutas con `pathlib`.

---

*Última actualización: se mantiene al día con cada cambio del sistema.*
