# ITHOS Cloud — Gestor (cerebro) + Agentes (multi-cliente)

Producto SaaS: el **Gestor** (el cerebro en la nube, que hosteamos nosotros/INTELLIHELP; solo
razona y orquesta) y **agentes** livianos instalados en cada cliente que tocan el hardware local
(parlantes, micrófono, control de acceso) y **ejecutan** lo que el Gestor les manda. Se hablan por
**WebSocket**. Arquitectura, versionado, empaquetado (ejecutable/servicio), auto‑update por red y
modelo de acceso: ver **[ARQUITECTURA_GESTOR_AGENTE.md](docs/ARQUITECTURA_GESTOR_AGENTE.md)** y
**[INSTALACION_AGENTE.md](docs/INSTALACION_AGENTE.md)**. *(La carpeta interna sigue llamándose `central/`.)*

```
CLIENTE (su red)                         NUBE (Hostinger VPS)
 Agente  ── evento (fichaje/ticket) ─▶   Central (FastAPI + WebSocket)
   │      ◀── comando (decir/…) ──────     · valida API key (multi-cliente)
 parlantes/mic, IVMS/HikCentral/BioStar    · IA en cadena (Gemini→Cerebras→Groq) + voz Charon
```

## Estructura
- `central/` — servidor. `main.py` (WebSocket), `registro.py` (clientes por API
  key), `procesador.py` (evento→comando), `protocolo.py` (mensajes), `clientes.json`.
- `agente/` — cliente. `agente.py` (se conecta, manda eventos, ejecuta comandos),
  `config.json` (central_url + api_key + integrador).

## Agregar un cliente (cero código)
Sumá una entrada en `central/clientes.json` con su `api_key` y config. Nada más.

## Probar TODO en una PC (sin KVM) — un comando
```bash
pip install -r central/requirements.txt -r agente/requirements.txt   # 1a vez
python iniciar_demo.py
```
Arranca el Gestor + Panel, **abre las 3 páginas** (panel superadmin, portal del cliente,
alta), corre el ciclo completo con INTELLIHELP (portero por voz, tickets con IA,
métricas/SLA, “ITHOS ¿…?” por voz, WhatsApp) y **queda vivo hasta que ponés `S`** para
cerrar todo. Ver detalle en [INSTALACION.md](docs/INSTALACION.md).

### Modelo de acceso (seguridad)
Al **Gestor** (panel superadmin `/` + APIs de gestión) entra **solo INTELLIHELP**, con **usuario + contraseña**:
`ITHOS_ADMIN_USER` (default `intellihelp`) y `ITHOS_ADMIN_TOKEN` (la contraseña; en producción fijá una fuerte).
Las llamadas internas/programáticas usan la cabecera `X-Admin-Token`. El **cliente** solo accede a su **dashboard**
`/panel/<api_key>`. El **alta** (`/alta`) es un **enlace temporal de un solo uso** por cliente (token que caduca,
generado desde el panel). La **demo** lo refleja: **genera** la contraseña en cada corrida (no hay nada hardcodeado),
la **muestra** por consola, se autologuea sola y genera un enlace de alta temporal; sus artefactos quedan aislados
y se borran al cerrar.

O manual:  `cd central && uvicorn main:app --port 8080`  +  `cd agente && python agente.py --demo`.
O con Docker:  `docker compose up --build`.

## Roadmap
**✅ Base (hecho y probado — 12/12 tests OK):** esqueleto multi-cliente + WebSocket +
registro por API key; voz Gemini Charon (caché + streaming); GLPI + triage IA con
ciclo de vida completo (pide datos solo si faltan; si un técnico resuelve por comentario
lo marca Resuelto; pide confirmación al cliente con recordatorio diario y cierra al
confirmar, sin repetir); **avisos multicanal** (WhatsApp + Telegram + Teams + Slack +
Email + Matrix) en **texto y/o nota de voz** según el formato del cliente (WhatsApp
no‑oficial y oficial, Telegram sendVoice); integradores IVMS/HikCentral/BioStar2/ZKTeco/Honeywell;
**cadena multi‑IA** que usa una sola IA por consulta y salta a la siguiente solo al agotarse,
avisando al cliente cuando una está por agotarse o cambia; reportes ITIL **instantáneos**
(sin N+1); base de conocimiento; multi-idioma; conversacional (micrófono
+ audio de WhatsApp); deploy Docker en KVM 2 con **HTTPS/WSS** (Caddy); instaladores.

**✅ Corto plazo (hecho):**
- **Dashboard de métricas/SLA por cliente** en el panel (`/` → botón *Métricas/SLA*).
- **Más wake-words**: varias palabras (ithos, computer, hey google…) + palabra a
  medida vía `.ppn` (`keyword_paths`).
- **Onboarding autoservicio**: `/alta` — el cliente se registra solo y obtiene su API key.

**✅ Ya hecho (antes "planificado"):**
- **Facturación / suscripciones (MercadoPago)** — cobro mensual recurrente por cliente,
  precio en USD → pesos al dólar BNA, **gross‑up de comisión**, webhook opcional. **Probado
  end‑to‑end en sandbox** (autorizado). Ver `comun/facturacion.py` y [INFORME_NICOLAS.md](docs/INFORME_NICOLAS.md).
- **ITHOS proactivo** — avisa **SLA por vencer** (`central/proactivo.py`) y **anomalías de
  acceso por horario** (`central/anomalias.py`), sin que le pregunten. OFF por defecto.
- **Canal Matrix/Element** (open‑source, tipo Slack) y **base de conocimiento desde Outline**;
  **DeepSeek local** (sin Ollama). Multi‑IA en cadena con respaldo automático.
- **Multiplataforma**: central Y agente en Windows, Linux y Mac.

**🔜 Planificado:** **App móvil** (panel + push + hablarle a ITHOS desde el celu).

**💡 Futuro / ideas:** clon de voz local (XTTS) para máxima privacidad; más idiomas;
auto‑escalado del Central; marketplace de integradores; Slack/Teams conversacionales
(reciben y ejecutan, no solo avisan).

## Capa de IA enchufable (escalabilidad + clientes privados)

`central/ia.py` define `ProveedorIA` (métodos `chat` y `voz_pcm`). El resto del
sistema lo usa sin saber cuál es. Se elige **por cliente** en `clientes.json → ia`:

| Proveedor | Texto | Voz | Uso |
|---|---|---|---|
| `gemini` (default) | **gemini‑2.5‑flash‑lite** | Charon (Live) | nube, KVM 2 alcanza |
| `cerebras` / `groq` | Llama 70B (GRATIS) | Charon | **respaldo automático** de Gemini |
| `local` / `deepseek_local` | Ollama / DeepSeek local (sin Ollama) | edge‑tts | **cliente privado**: todo en su red |
| `claude` / `openai` / `grok` / `deepseek` / `mistral` / `openrouter` | su API | Charon | pagos / mezcla |

> Se eligen **hasta 3 en cadena** por cliente (primaria → 2ª → 3ª). Si la primaria se queda
> sin cuota, ITHOS **salta solo** al respaldo (ej. `gemini → cerebras → groq`, las 3 gratis).

**Cliente que quiere todo privado (datos no salen de su red):**
1. Le indicamos el **hardware** según su requerimiento (ver dimensionado en la clase
   `LocalIA` de `ia.py`): CPU+RAM para modelos chicos, GPU para modelos grandes/voz.
2. En su servidor instala **Ollama** (+ TTS local) y su **agente**.
3. En su config: `"ia": {"proveedor": "local", ...}`.
4. **El Central sigue orquestando igual** — solo cambia dónde corre la IA. Los datos
   sensibles (tickets/fichajes) se procesan en la máquina del cliente, no en la nube.

Probado: `central/cerebro.py` (`clasificar_ticket`) triagea vía `ProveedorIA` con
Gemini real (categoría/prioridad/responsable/primera respuesta correctas).

---

# 🧩 Alta de clientes y agentes SIN saber programar (copy-paste)

Todo se configura en archivos, **sin tocar código**. Cualquiera puede hacerlo.

## ➕ Agregar un cliente nuevo
1. Abrí `central/clientes.json`.
2. Copiá un bloque de cliente completo (desde `{` hasta `}`) y pegalo dentro de
   `"clientes": [ ... ]`, separado por una coma.
3. Cambiá **solo** los valores (usá `central/clientes.ejemplo.json` como modelo):
   - `api_key`: inventá una clave única (la usará el agente de ese cliente para conectarse).
   - `nombre`: nombre del cliente.
   - `ia.gemini_api_key`: la API key de Gemini (gratis en https://aistudio.google.com/apikey).
   - `integrador_glpi.*`: la URL y tokens del GLPI del cliente.
   - `whatsapp.*`: a quién avisar.
4. Guardá. Reiniciá el central. **Listo, cero código.**

## 💳 Cliente que compra su propia API key de Google (paga)
En su bloque, dentro de `"ia"`:
```json
"gemini_api_key": "LA-KEY-PAGA-DEL-CLIENTE",
"ilimitada": true
```
`ilimitada: true` desactiva los avisos de cuota (su plan pago no se agota como el gratis).

## ⚠️ Avisos de cuota (free tier)
Con el plan **gratuito** de Gemini, el sistema avisa solo (por **voz ITHOS + WhatsApp**):
- Cuando quedan pocos usos (`avisar_en`, por defecto 15): *"la cuota está por agotarse, quedan N usos"*.
- Cuando se agota: *"la cuota se agotó, vuelve en Xh Ym, ~HH:MM hora Argentina"*.
Ajustás el límite en `ia.limite_diario` y el aviso en `ia.avisar_en`.

## 🤖 Configurar el agente (en la PC del cliente)
1. Abrí `agente/config.json`.
2. Cambiá:
   - `central_url`: la dirección del central (ej. `wss://tu-servidor:8080/ws`).
   - `api_key`: la MISMA que pusiste en el cliente en `clientes.json`.
   - `ia.voz.gemini_api_key`: la API key de Gemini (para la voz Charon).
3. Guardá y ejecutá `python agente.py`. Se conecta solo.

> La **voz siempre es ITHOS (Charon)**. Si un cliente exige todo local/privado, se
> le pone `"proveedor": "local"` en su IA de texto y su modelo local; la voz sigue
> siendo Charon (identidad de la marca).

---

# 🆕 Funciones agregadas (v0.4)

## Hablarle a ITHOS
- **Micrófono central (palabra clave "ITHOS")**: como "OK Google". El agente escucha,
  al decir *"ITHOS"* graba tu pedido, lo manda al central y responde/resuelve por voz.
  Config del agente: `"microfono": {"enabled": true, "picovoice_key": "...", "keywords": ["ithos","computer"]}`
  (key gratis en console.picovoice.ai). Para una palabra a medida (ej. "Che ITHOS")
  entrenala en Picovoice y pasá el `.ppn` en `"keyword_paths"`.
- **Audio por WhatsApp** (para quien no tiene micrófono central): le mandás un audio,
  ITHOS lo transcribe, interpreta y responde/actúa.
- **Herramientas** que ITHOS puede usar al hablarle: tickets abiertos, estado de un
  ticket, reporte de SLA (`comun/conversacion.py`). Se agregan más fácil.

## Base de conocimiento (`comun/kb.py`)
Poné documentos `.txt`/`.md` del cliente en una carpeta (`"kb_dir"` en su config) y
ITHOS responde usándolos como contexto.

## Reportes / Analytics (`central/reportes.py`)
Estadísticas por estado/prioridad y **% de cumplimiento de SLA** por cliente.

## Multi-idioma
`"idioma"` por cliente (`es-AR`, `es-ES`, `en`, `pt-BR`, `fr`, `it`): la voz y las
respuestas salen en ese idioma.

## Más canales de aviso (`comun/notificadores.py`) — ELEGIBLE por cliente
WhatsApp (oficial/no-oficial), Telegram, Email, Teams, Slack. Cada empresa elige uno o
varios en el panel (se guardan en la lista `"notificaciones"`); el central manda las
alertas a TODOS los canales activos. Si no quieren WhatsApp, usan Telegram/Email/etc.

## Conversación en TODOS los canales (`comun/canales.py`)
No solo se AVISA por cada canal: ITHOS también **escucha y responde** en todos —WhatsApp
**oficial** (Cloud API, por webhook) y **no-oficial** (grupo), **Telegram** (Bot API) y
**Email** (IMAP/SMTP)— con la **misma activación** ("ITHOS, …"), el **mismo asistente**
(contexto/acciones por cliente) y el **mismo gateo** de autorización por remitente. Todo lo
que se implementa vale para los dos modos de WhatsApp y para el resto de canales por igual.
El webhook de WhatsApp oficial se expone en `/webhook/whatsapp` (verificación + entrante).

## Más sistemas de tickets (`comun/tickets_otros.py`) — ELEGIBLE por cliente
GLPI, Zendesk, Freshservice, Jira y osTicket, **todos implementados de verdad** contra la
API OFICIAL vigente (2025/2026) de cada fabricante — no son maquetas. Interfaz común
(`comun/tickets.py`): listar/estado/responder/crear/cerrar/reabrir/en espera/prioridad/
asignar/buscar/SLA. Notas por si sirven al configurarlos:
- **Jira Cloud**: usa el NUEVO `POST /rest/api/3/search/jql` (Atlassian removió el viejo
  `/search` en oct-2025); estados por *transitions*; SLA por Jira Service Management.
- **Zendesk**: `search.json` + `PUT /tickets/{id}` (comentario público, estado, prioridad).
- **Freshservice**: filtros por estado (2/3/4/5), `reply`/`notes`, SLA por `due_by`.
- **osTicket**: su API oficial **solo crea** tickets; para leer/cerrar hace falta acceso a
  su base MySQL (se activa poniendo `db_host/db_user/db_pwd/db_name`).
Se elige en el panel y los campos se adaptan solos al sistema.

## Más control de acceso (`agente/integrador_*.py` + `comun/acceso.py`)
IVMS (DB SQL), HikCentral (OpenAPI/Artemis, HMAC), BioStar 2 (New Local API), ZKTeco
(ZKBio CVSecurity *y* BioTime 8.5) y Honeywell (Pro-Watch API Service). El portero en
tiempo real vive en `agente/integrador_*`; la detección de **anomalías de horario** vive
en `comun/acceso.py` y anda por API en HikCentral/BioStar 2/ZKTeco/Honeywell (OFF por
defecto). IVMS no hace control horario.

## Panel web no-code (`central/panel.py`)
`uvicorn panel:app --port 8090` → alta/edición/borrado de clientes desde el navegador,
sin tocar archivos. Copy-paste del bloque JSON. Incluye:
- **Dashboard de métricas + cumplimiento de SLA por cliente** (botón *Métricas/SLA*).
- **Alta autoservicio** en `/alta`: el cliente se registra solo y recibe su API key.

## Instaladores multi-OS (`instaladores/`) y guía (`INSTALACION.md`)
Central (cerebro):
- `central_windows.ps1` — **Windows nativo** (sin Docker): tareas programadas +
  Caddy para HTTPS/WSS. Ideal para KVM/PC Windows.
- `central_unix.sh` — **Linux y macOS** (Docker + Caddy TLS).

Agente (cliente):
- `agente_windows.ps1` (Tarea Programada) · `agente_linux.sh` (systemd) ·
  `agente_mac.sh` (LaunchAgent). Arrancan solos y se reconectan.

Prueba local (todo en tu PC, ver diseño + voz):
- `probar_local.ps1` (Windows) · `probar_local.sh` (Linux/Mac).

## Medición de uso (`comun/metricas.py`)
Cuenta tickets/anuncios/usos de IA por cliente y mes (para facturar la suscripción).

---

# 🧠 Funciones AVANZADAS (agente, memoria, reportes, SaaS) — todo POR CLIENTE

Cada empresa es un **inquilino aislado** (multi-tenant): su propia memoria, su config,
sus reportes y su facturación. Un cliente **nunca** ve el contexto de otro.

## Memoria por cliente (`comun/memoria.py`)
Cada empresa tiene su **base de datos propia** (`memoria_<empresa>.sqlite3`): historial de
conversación + hechos aprendidos. ITHOS recuerda lo hablado y las preferencias de **ese**
cliente, y su DB crece con el uso.

## Todo es MULTI-SISTEMA y POR CLIENTE (`comun/tickets.py`, `comun/acceso.py`)
Cada empresa elige **su** sistema de tickets (GLPI, Zendesk, Freshservice, Jira, osTicket)
y **su** control de acceso (IVMS, HikCentral, BioStar 2, ZKTeco, Honeywell). ITHOS habla
con un **adaptador genérico**, así **todas las funciones de abajo andan igual en cualquier
sistema** — no hay nada atado a un proveedor. GLPI e IVMS están 100% probados; los demás se
enchufan por su adaptador al activar ese cliente. Cada cosa se resuelve con el **cfg aislado**
del cliente.

## Agente que EJECUTA (no solo consulta) (`comun/conversacion.py`)
Por voz o WhatsApp, ITHOS puede **hacer acciones reales** en el sistema de tickets (el que
sea): `cerrar_ticket`, `reabrir_ticket`, `poner_en_espera`, `asignar_ticket` (a un técnico),
`responder_ticket`, `crear_ticket`, `cambiar_prioridad`, `escalar_ticket` (urgente + asignar)
y `buscar_tickets` (por texto o persona). Ej.: *"ITHOS, cerrá el #597"*, *"escalá el 601 a
Ayala"* o *"buscá los tickets de Pamela"*. Además **siempre tiene los datos reales cargados**
(tickets + SLA) y responde con los números, sin pedir info que ya tiene. *(No hace alta de
usuarios, a propósito.)*

## Conocimiento técnico PROPIETARIO + autorización (`comun/conocimiento.py`)
ITHOS tiene cargado TODO el contexto técnico del producto: **qué versión de cada software
soporta (desde/hasta), qué permite hacer cada sistema y sus limitaciones, y cómo está
programado** (arquitectura, módulos, decisiones). Así responde cualquier duda sobre su
propio funcionamiento. **Pero es información PROPIETARIA de INTELLIHELP**: solo la explica a
los **números del dueño**. A cualquier otro remitente responde, con amabilidad, que no puede
compartir esos detalles por ser un sistema propietario — el soporte normal (tickets, SLA,
portero) sí lo responde a todos. La autorización es SOLO por **identidad** (número/email/
usuario), nunca por el canal ni por “IsFromMe”: si un cliente usa su propia sesión, su número
no está en la lista y **nunca** queda como dueño. Compara los **últimos 10 dígitos** (robusto
a `+54/549`, espacios, guiones y al **LID** con que WhatsApp oculta el teléfono).

**Clave de administrador (estilo Iron Man):** para el micrófono —que no identifica a nadie—
hay una **frase-clave** que destraba el modo admin por **UNA sola consulta** y después cierra
la sesión (vuelve a usuario estándar). El código vive en `comun/conocimiento.py`
(`CLAVE_ADMIN`). A futuro se suma **identificación por voz**: aunque alguien sepa la clave, si
no es la voz del dueño, no la acepta.

## Base de conocimiento AUTOMÁTICA por cliente (`central/kb_auto.py`)
ITHOS **arma solo** la base de conocimiento de cada empresa leyendo sus **casos resueltos**
(problema + solución) del sistema de tickets del cliente, y la usa para resolver casos
parecidos. Es **aislada** (una empresa nunca ve la de otra), vive en `~/.ithos/kb_<cliente>/`
y se **regenera sola una vez por semana** (después de la semana laboral, `kb_auto.vigilar`), sin
que el cliente tenga que apretar nada — o a mano con el botón *Regenerar base de conocimiento*
(`GET /api/kb_generar/{key}`). Desde el **alta** o el portal se pueden **subir instructivos**
(PDF/Word/texto, `/api/kb_subir`) o **importar la wiki de Outline** (`/api/kb_outline`), que se
combinan con lo aprendido de los tickets.

## Reportes proactivos (`central/reportes_programados.py`)
Cada empresa configura en el panel: **diario / semanal / mensual**, a qué **hora** y qué
día. ITHOS **manda solo** el resumen (tickets + SLA) por **sus canales** de notificación.

## ITHOS proactivo · SLA por vencer (`central/proactivo.py`)
Sin que nadie pregunte, ITHOS **avisa cuando un ticket está por vencer el SLA** (o ya venció)
por **los canales del cliente**. Se configura por empresa (avisar cuando falten *N* horas,
cada cuánto revisa). **OFF por defecto.** Anti-spam: un aviso por ticket por día.

## Anomalías de acceso por horario (`central/anomalias.py`, `comun/acceso.py`)
Para clientes que **sí** hacen control horario (**HikCentral / BioStar 2**), ITHOS avisa si
alguien **ficha fuera de su horario / es denegado por franja**. Toma la **configuración de
horarios del sistema por su propia API** — el cliente **no configura nada**. **OFF por
defecto** y **nunca se activa solo**. En sistemas sin control horario (**IVMS**, como el
nuestro; ZKTeco, Honeywell) **no aplica** aunque se prenda.

## SaaS · Facturación con MercadoPago (`comun/facturacion.py`)
Suscripción recurrente por empresa (API **preapproval**). **El precio se define en USD (NETO)**
y se cobra en **pesos al dólar oficial del BNA** del día. **Gross‑up de comisión:** ITHOS infla
el precio (`bruto = neto / (1 − comisión%)`) para que, tras la comisión de MP, quede el neto — el
% es configurable (tu tarifa real; hoy 6,29% al instante). El email de facturación sale del **alta
del cliente** y, tras el pago, MP **confirma el email real** por webhook. **INTELLIHELP = "propietario"
→ NO se cobra nunca.** **Probado end‑to‑end en sandbox (autorizado).**

- **No hace falta URL pública ni webhook — tampoco en producción.** El pago se hace en la página de
  MercadoPago; el estado se ve con **Consultar estado** (poll). El webhook (aviso automático) es
  **opcional** (queda el endpoint por si algún día hay dominio).
- Endpoints: `GET /api/probar_suscripcion/{key}` y `POST /api/suscripcion/{key}` (link),
  `GET /api/facturacion/{key}` (estado), `POST /webhook/mercadopago/{key}` (opcional, firma HMAC).

### Configurar MercadoPago (para cobrar)
1. [MercadoPago Developers](https://www.mercadopago.com.ar/developers/panel/app) → creá una app
   (tipo *Suscripciones*) → copiá el **Access Token de producción** (`APP_USR-...`).
2. Panel de ITHOS → editá la empresa → **Facturación**: activá *Cobrar suscripción*, poné **precio
   USD**, **comisión %** (tu tarifa de MP → *Costos y cuotas*) y pegá el **Access Token**.
3. Guardá → **💳 Probar suscripción** genera el **link de pago**; el cliente paga → **🔄 Consultar estado**.
> Para PROBAR sin plata real: usar el **Access Token de un VENDEDOR de prueba** + un **comprador de
> prueba** (tarjeta titular **APRO**). Detalle completo en [INFORME_NICOLAS.md](docs/INFORME_NICOLAS.md).

---

# 🖥️ Correr TODO en tu PC (un comando)
```bash
python iniciar_demo.py
```
Si el proyecto está en un **disco local**, corre ahí mismo; si está en un recurso de red
(`\\...`), se copia solo a una carpeta local (uvicorn no corre desde red). Abre el panel,
el portal del cliente y el alta, y te deja probar voz, tickets, micrófono y WhatsApp.
**Todas las rutas son relativas** (portable): podés mover la carpeta a donde quieras.
