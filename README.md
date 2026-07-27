<p align="center">
  <img src="docs/banner.svg" alt="ITHOS" width="100%">
</p>

<p align="center">
  <b>Asistente de IA multi-cliente para operaciones: control de acceso por voz, mesa de ayuda inteligente y gestión del equipo.</b><br>
  Anuncia los accesos por los parlantes con voz natural, clasifica y resuelve tickets de soporte con IA, conversa por WhatsApp, factura la suscripción y mantiene el tablero del equipo al día — cada cliente aislado en su propio inquilino.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/FastAPI-WebSocket-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/IA-Gemini%20·%20Cerebras%20·%20Groq%20·%20local-0A7CFF" alt="Cadena multi-IA">
  <img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker ready">
  <img src="https://img.shields.io/badge/multi--tenant-SaaS-663399" alt="Multi-tenant SaaS">
  <img src="https://img.shields.io/badge/plataformas-Windows%20·%20Linux%20·%20macOS-444" alt="Multiplataforma">
  <img src="https://img.shields.io/badge/licencia-propietaria-663399" alt="Licencia propietaria">
</p>

---

## Índice

- [Descripción](#descripción)
- [Características](#características)
- [Arquitectura](#arquitectura)
- [Stack técnico](#stack-técnico)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Puesta en marcha](#puesta-en-marcha)
- [Configurar un cliente](#configurar-un-cliente)
- [Tests](#tests)
- [Seguridad](#seguridad)
- [Licencia](#licencia)
- [Autor](#autor)

## Descripción

**ITHOS** es un asistente de IA que opera sobre los sistemas que una empresa ya usa. Anuncia
por los parlantes cada fichaje/acceso leído del control biométrico con voz natural; clasifica,
prioriza, asigna, responde y cierra los tickets de la mesa de ayuda; escucha y responde por
WhatsApp (y otros canales) con una palabra de activación; emite reportes ITIL; cobra la
suscripción; y mantiene el tablero de tareas del equipo actualizado.

El producto es **SaaS multi-inquilino** y se divide en dos planos. El **Gestor** (plano de
control) es el cerebro: se hospeda en la nube, razona y orquesta, expone el panel de
administración y los webhooks, y nunca se comparte entre clientes. El **Agente** (plano de
datos) es liviano, corre en el equipo del cliente y sólo ejecuta lo que el Gestor le indica
—hablar por los parlantes, escuchar el micrófono, leer el control de acceso local—. Ambos se
comunican por WebSocket autenticado. Cada empresa es un inquilino aislado: su propia memoria,
su configuración, sus secretos cifrados y su facturación; un cliente nunca ve el contexto de
otro.

> Demo y despliegue de referencia (privados): gestionados por INTELLIHELP.

## Características

- **Portero por voz.** Anuncia los accesos leídos del control biométrico (IVMS / HikCentral / BioStar 2 / ZKTeco / Honeywell) por los parlantes, con voz natural y verbatim (TTS dedicado de Gemini, *Charon*).
- **Mesa de ayuda con IA.** Clasifica, prioriza, asigna, responde y gestiona el ciclo de vida de los tickets. Respeta la intervención manual del técnico, deja notas internas privadas, pide procedimientos para la base de conocimiento y gestiona el SLA por calendario y horario.
- **Cadena multi-IA.** Una IA por consulta; salta a la siguiente sólo al agotarse (Gemini → Cerebras → Groq, configurable). Aviso al cliente cuando una está por agotarse o cambia. Opción **100 % local** (Ollama) para datos que no salen de la red del cliente.
- **WhatsApp conversacional.** Escucha el grupo del cliente (activación por «ithos», texto o audio) y responde o ejecuta acciones reales sobre los tickets. Multicanal: WhatsApp oficial y no oficial, Telegram, Email y Matrix.
- **Tareas del equipo (Planka).** Mantiene el tablero Kanban al día desde WhatsApp: resumen diario, seguimiento horario, alta y movimiento de tarjetas por voz o texto, y **rollover mensual/semanal automático** con arrastre de lo pendiente.
- **Reportes ITIL.** Resumen automático (volumen, SLA, MTTR) por período cerrado, en la zona horaria y los días hábiles del cliente. Lecturas masivas, sin consultas por ítem.
- **Facturación SaaS (MercadoPago).** Suscripción recurrente por cliente, precio en USD cobrado en pesos al dólar oficial, *gross-up* de comisión, *dunning*, gracia y suspensión que congela la IA hasta regularizar.
- **Multi-inquilino y multiplataforma.** Aislamiento por cliente, secretos cifrados en reposo (AES-256-GCM), y Gestor + Agente ejecutables en Windows, Linux y macOS.

## Arquitectura

```mermaid
flowchart LR
    subgraph Cliente["Equipo del cliente"]
        AG["Agente (.exe firmado)<br/>voz · micrófono · control de acceso"]
        HW["Parlantes · Micrófono<br/>IVMS / HikCentral / BioStar 2 / ZKTeco"]
        AG --- HW
    end

    subgraph Nube["Nube — VPS (Docker)"]
        CA["Gestor / central<br/>FastAPI + WebSocket"]
        PA["Panel + Dashboard<br/>+ Alta"]
        CY["Caddy<br/>TLS / WSS"]
        CA --- PA
        CY --- CA
    end

    AG <-->|"WSS · api_key + token"| CY
    CA -->|"cadena multi-IA"| IA["Gemini · Cerebras · Groq · local"]
    CA <--> GLPI["Mesa de ayuda<br/>GLPI / Zendesk / Jira / …"]
    CA <--> WA["WhatsApp · Telegram · Email · Matrix"]
    CA <--> PL["Planka — tareas del equipo"]
    CA <--> MP["MercadoPago — facturación"]
```

Cada capa degrada de forma controlada: si la IA primaria agota su cuota, la cadena salta al
respaldo sin cortar el servicio; si un canal falla, el resto sigue operando; la voz cae a un
motor gratuito sólo como respaldo temporal. El Gestor concentra la lógica y el Agente
permanece liviano, de modo que un cliente que exige privacidad total puede correr la IA en su
propia red sin cambiar la orquestación.

## Stack técnico

| Capa | Tecnología |
| --- | --- |
| Gestor (control-plane) | Python 3.11+, FastAPI, WebSocket (front-controller propio, sin framework pesado) |
| Agente (data-plane) | Python, interfaz `pywebview`, empaquetado como `.exe` firmado (Inno Setup) |
| Inteligencia | Cadena multi-IA: Gemini · Cerebras · Groq · local (Ollama) — enchufable por cliente |
| Voz | TTS dedicado de Gemini (*Charon*, verbatim) para los parlantes; `edge-tts` de respaldo |
| Datos por cliente | SQLite aislado por inquilino; secretos cifrados en reposo (AES-256-GCM) |
| Mensajería | WhatsApp (Cloud API y no oficial vía `neonize`), Telegram (Bot API), Email (IMAP/SMTP), Matrix |
| Integraciones | GLPI · Zendesk · Freshservice · Jira · osTicket · IVMS · HikCentral · BioStar 2 · ZKTeco · Honeywell · Planka · MercadoPago |
| Empaquetado | Docker (Gestor + Panel + Caddy con TLS/WSS automático); instalador Inno firmado (Agente) |

## Estructura del proyecto

```
ITHOS/                    # todo el software, autocontenido y desplegable
├─ comun/                 # código compartido: IA, voz, GLPI/tickets, WhatsApp, Planka,
│                         #   facturación, cifrado, memoria, métricas, reportes ITIL
├─ central/               # el Gestor: main (WebSocket), panel, triage, cerebro,
│                         #   integradores, reportes programados, clientes.json
├─ agente/                # el Agente: voz, escucha, integradores de acceso, GUI
├─ docker-compose.yml     # despliegue del Gestor (central + panel + caddy)
└─ Caddyfile              # TLS / WSS automático
docs/                     # documentación (instalación, arquitectura, informes) y banner
tests/                    # baterías de regresión (probar_*.py)
compilador/               # build (PyInstaller, Inno, firma) · instaladores · dist
DOCUMENTO_MAESTRO.md      # índice técnico del proyecto
```

La configuración real (`central/clientes.json`, `.env`) y todo dato por cliente **no se
versionan**: el repositorio incluye únicamente plantillas (`central/clientes.ejemplo.json`,
`.env.example`) con marcadores. El despliegue se completa con secretos nuevos.

## Puesta en marcha

### Gestor (VPS Linux, Docker)

```bash
cp ITHOS/central/clientes.ejemplo.json ITHOS/central/clientes.json   # completar con datos reales
cp .env.example ITHOS/.env                                           # ITHOS_ADMIN_USER/TOKEN, ITHOS_MASTER_KEY
cd ITHOS && docker compose -p jarvis-cloud up -d --build             # -p conserva los volúmenes de datos
```

Caddy resuelve TLS/WSS automático; el Agente del cliente se conecta a `wss://TU-DOMINIO/ws`.
El detalle completo del despliegue está en [docs/INSTALACION.md](docs/INSTALACION.md) y
[docs/HOSTINGER.md](docs/HOSTINGER.md).

### Agente (equipo del cliente)

Instalador único por plataforma (Windows: Inno firmado, en `compilador/`; Linux/macOS: script
en `compilador/instaladores/`). Los datos y la caché se guardan en `%LOCALAPPDATA%/ITHOS`; la
desinstalación no deja rastro. Ver [docs/INSTALACION_AGENTE.md](docs/INSTALACION_AGENTE.md) y
[docs/ARQUITECTURA_GESTOR_AGENTE.md](docs/ARQUITECTURA_GESTOR_AGENTE.md).

## Configurar un cliente

Sin tocar código: se copia un bloque de `central/clientes.ejemplo.json`, se pegan los valores
reales (API key del agente, credenciales de IA, del sistema de tickets, del control de acceso
y de los canales) y se reinicia el Gestor. El acceso al Gestor (panel de administración y
APIs de gestión) queda restringido a INTELLIHELP con usuario y contraseña; cada cliente sólo
accede a su propio dashboard, y el alta es un enlace temporal de un solo uso.

## Tests

Baterías de regresión en [`tests/`](tests/): ciclo de vida de tickets, batería de sistema,
batería de producción, una batería de requerimientos transversales (multiplataforma, latencia
sin N+1, ausencia de código muerto, seguridad) y pruebas de integración contra las APIs reales
(por ejemplo, el rollover de Planka). Regla del proyecto: **cada defecto detectado incorpora
un test de regresión** para impedir su reaparición.

```bash
python tests/probar_todo.py
python tests/probar_planka_rollover.py
```

## Seguridad

- Los secretos (credenciales de IA, tokens de tickets, claves de canales, `ITHOS_MASTER_KEY`)
  viven en `clientes.json` o en variables de entorno; **nunca se versionan**. El repositorio
  incluye sólo plantillas con marcadores.
- Los secretos de cada cliente se **cifran en reposo** (AES-256-GCM) con una clave maestra
  separada.
- El acceso al Gestor exige usuario y contraseña (hasheada con *scrypt*); las llamadas
  internas usan cabecera de token; el alta es un enlace de un solo uso que caduca.
- Cookies `secure`/`httponly`, *rate-limit* de login, HSTS en Caddy y suspensión por impago
  que congela la IA (nunca al propietario).
- Política de reporte de vulnerabilidades en [SECURITY.md](SECURITY.md).

## Licencia

Software **propietario**, desarrollado **íntegramente por Brian Sierra**. Todos los derechos
reservados. Uso interno de la organización; se prohíbe su redistribución o uso fuera de ese
marco sin autorización expresa y por escrito del autor. El autor conserva su derecho moral de
reconocimiento de autoría (Ley 11.723 art. 52; Convenio de Berna art. 6 bis). Ver
[LICENSE](LICENSE).

## Autor

**Brian Sierra** — diseño, desarrollo e implementación completos: arquitectura Gestor/Agente,
cadena multi-IA y voz, mesa de ayuda con triage, integraciones de tickets y control de acceso,
mensajería multicanal, facturación SaaS, gestión del equipo (Planka), empaquetado y despliegue.
