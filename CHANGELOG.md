# Changelog

Todos los cambios notables de este proyecto se documentan acá.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y el versionado, [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added
- **Helpdesk — espera por el cliente con recordatorio y escalada.** Cuando el ticket queda En espera
  porque depende del cliente —falta un **dato** que le pedimos en la primera respuesta, o tiene que
  **confirmar/coordinar** algo—, ITHOS le manda **un recordatorio por día hábil**, siempre **dentro
  del horario de atención** (Lun-Vie 09:00-18:00 en su zona) y a la misma hora, hasta que responda;
  al responder, el ticket vuelve a **En curso** solo. A los **5 días hábiles sin respuesta** avisa al
  **técnico asignado** (nota interna privada + WhatsApp) para que decida: contactarlo, posponerlo o
  cerrarlo. El SLA queda pausado todo ese tiempo (estado En espera) y un ticket **pospuesto** no
  recibe nada. El recordatorio de confirmación de un ticket **Resuelto** sigue la misma cadencia
  (antes salía cada 24 h a cualquier hora, incluso de madrugada o un fin de semana).
- **Helpdesk — @mención al técnico asignado.** Los avisos de WhatsApp de un ticket (triage, respuesta
  del cliente, cierre, reapertura, escalada) y la alerta de **SLA en riesgo/vencido** @mencionan
  **sólo al asignado**, por su teléfono (config `tecnicos` del cliente). La alerta de SLA se manda
  **agrupada por técnico** (cada uno ve lo suyo). Los canales sin menciones (Telegram, email, Teams,
  Element) reciben el mismo aviso con el nombre del asignado, y el WhatsApp oficial (Cloud API) se lo
  manda directo a su número: el aviso nunca se pierde. Vale para cualquier sistema de tickets: el
  asignado se resuelve por id de GLPI, id/login/email o nombre según el sistema.
- **Activación por llamada: "Hey ITHOS"** (`ITHOS/comun/wake.py`, una sola fuente de verdad para los
  canales de texto, Planka y el micrófono del agente). Hay que **llamarlo**: "Hey ITHOS…" y también
  "oye/ok/hola/che ithos", en español o inglés, en mayúsculas o minúsculas, con tildes o puntuación,
  tolerando que el reconocedor **parta** la palabra ("hey it hos"), la pegue ("heyithos") o la
  transcriba con pronunciación inglesa ("hey ethos"). **Nombrar la marca suelta ya no activa**: en un
  grupo de trabajo se la menciona todo el tiempo ("preguntale a ITHOS") y no corresponde intervenir.
  Los textos que explican cómo usarlo —aviso de inicio, mensajes de las tareas del equipo— lo dicen así.
- **Antecedentes: "¿qué casos como este ya resolvimos?".** Preguntar por casos ya trabajados ahora
  revisa el **histórico completo** del cliente —todos los tickets cerrados y en espera, no los últimos
  60— y trae cada caso con la **resolución que escribió soporte**. Encuentra el ticket aunque esté
  redactado con otras palabras (busca por **raíz**, así "fichadas" encuentra "la fichada", y sin
  espacios, así "HikCentral" encuentra "hik central"), pesa cada término según lo distintivo que sea y
  descarta las palabras con que se *pregunta*. Un **cierre administrativo** —categoría mal cargada,
  duplicado, sin respuesta del cliente— se marca como **sin resolución técnica** y no se ofrece como
  modelo, igual que no lo haría un experto de mesa de ayuda. Los casos reales entran al contexto antes
  de redactar la respuesta: **los números que dice son los que existen**. Antes, la consulta se
  respondía con los tickets abiertos y la memoria del modelo, que llegó a citar un ticket inexistente,
  se salteaba el que sí correspondía y ofrecía cierres administrativos como resoluciones.
- **Consultar los tickets por técnico asignado.** Además de poner en espera o posponer en lote, ahora se
  puede **preguntar** por los tickets de una persona ("¿cómo están los asignados a mí?", "los de
  Alejandro") y ITHOS devuelve los abiertos con su estado. Identifica a quien escribe por su **número**
  —o su usuario/correo según el canal—, así que **no pide nombre ni legajo**; si el número no está
  mapeado, pregunta de quién se trata en vez de adivinar. Filtra por "Asignado a", nunca por observador.
- **ITHOS se explica desde su propia documentación.** Cuando el **dueño** pide detalle, la respuesta se
  arma con el **DOCUMENTO_MAESTRO** completo —montado en el Gestor como sólo lectura— más el conocimiento
  técnico interno; sin pedir detalle contesta lo mismo resumido. A cualquier otro le cuenta **qué hace**
  ITHOS (alcance resumido) y nunca cómo está construido. Por micrófono se exige, además de la clave de
  administrador, que la **voz** coincida con el perfil del dueño.
- **Horario de atención compartido** (`ITHOS/comun/horario.py`): una sola fuente para "¿estamos en
  horario?" y "¿cuántos días hábiles pasaron?", que usan el ciclo de vida del ticket y las alertas. La
  **alerta de SLA** ahora sale sólo **dentro del horario del cliente** y agrupada por técnico: antes podía
  avisar de madrugada o un fin de semana.
- **La batería de requerimientos vive en el repositorio** (`tests/probar_requerimientos.py`): 117
  chequeos transversales —marca, multiplataforma, UI/UX, tickets, portero y voz, seguridad, latencia sin
  N+1, deploy— que corren **sin red ni credenciales**. Incluye los chequeos nuevos de la activación por
  llamada, del conocimiento propio y de que el README y el documento maestro no puedan divergir.
- **Documentación 1 a 1 y con diagramas de flujo en todas las guías.** El README trae los **mismos
  diagramas y el mismo contenido** que el documento maestro (mapa completo del producto, cadena multi-IA,
  voz y audio, portero, ciclo de vida del ticket, alta con seguridad y suscripción), el mapa de qué hace
  cada archivo, la operación y los límites; y las guías de arquitectura, despliegue e instalación suman su
  propio diagrama.
- **Receta de compilación del agente versionada** (`compilador/build`): del repositorio se puede
  reconstruir y firmar el instalador. El versionado del agente y del instalador queda sincronizado.
- **Tareas del equipo — aviso de cambio de estado en el tablero.** En cada recorrido se compara contra
  el último estado conocido de cada tarjeta: si alguna cambió de lista —movida a mano en el tablero o por
  ITHOS— se anuncia en el grupo con el estado anterior, el nuevo y quién la tiene asignada, **antes** del
  seguimiento, así el "¿cómo venís?" nunca vuelve a preguntar por algo ya terminado. Si no hubo cambios,
  no se dice nada. El estado **persiste en disco**, de modo que un reinicio del Gestor ya no hace perder
  los movimientos ocurridos mientras estuvo fuera (antes el cambio se detectaba pero no se avisaba, y la
  referencia vivía sólo en memoria).
- **Portero — saludo de entrada coherente con la hora.** En los dispositivos de ENTRADA el saludo
  arranca con «Buenos días / Buenas tardes / Buenas noches» según la hora de la zona del cliente. La
  salida mantiene su despedida. El dedup «una vez por día por persona» ahora **persiste** en disco, así
  la 2ª fichada queda en silencio aunque el central se reinicie.
- **Planka — rollover automático mensual/semanal.** Un proyecto por mes y un board por semana
  (bloques del mes: 1–7, 8–14, 15–21, 22–28, 29–fin, de modo que el mes cierra exacto el último
  día). Al cambiar de semana o de mes se crea lo que falte y se arrastra lo no terminado a su
  misma lista; al cerrar el mes se consolida entero en un board **MENSUAL** de archivo.
- **Planka — cierre de año automático.** Al cambiar de año, junta los meses en un proyecto
  «AÑO 2026» (un board por mes con su archivo) y borra los proyectos mensuales ya consolidados;
  arranca «Enero 2027» arrastrando lo pendiente. Los meses se nombran con el año («Julio 2026»).
  Todo con la fecha real: nada se dispara antes de tiempo.
- **Planka — asignación por membresía de board.** Se agrega a cada persona del equipo como
  miembro del board antes de asignarle una tarjeta, tal como se hace de forma manual.
- **Planka — reenvío manual del resumen** por bandera, para corregir un envío sin esperar al
  día siguiente.

### Changed
- **Avisos de Planka más legibles.** El resumen diario y el seguimiento listan una tarea por
  línea, agrupadas por lista y con su contador, en lugar de una única línea con comas.
- **Seguimiento acotado a lo activo.** El «¿cómo venís?» pregunta únicamente por Haciendo y
  En revisión/Esperando. Cuando la persona termina todo lo que tenía en curso, ITHOS le pregunta
  qué tarea sigue (ofreciendo lo de Por hacer) o cuál nueva quiere agregar.
- **Triage de GLPI más robusto.** Respeta la asignación manual del técnico, detecta pedidos de
  coordinación sólo del lado del técnico (no del cliente), deja notas internas privadas y ajusta
  el SLA por calendario y horario de atención (Lun–Vie 09–18).

### Fixed
- **El token del usuario de ITHOS en la mesa de ayuda tenía el nombre anterior de la marca en la
  configuración**, así que el Gestor no lo encontraba y arrancaba **sin triage**, en silencio. Se
  renombró a `glpi_ithos_token` (mismo token) en la config y en el ejemplo, y el registro de clientes
  adopta el token de usuario que traiga una config vieja —avisando por log— para no volver a dejar el
  triage apagado sin que se note.
- **Una actualización del código pisaba el dominio del despliegue.** El `Caddyfile` del paquete traía un
  marcador de dominio, así que al actualizar el Gestor quedaba pidiendo un certificado equivocado y sin
  HTTPS. El dominio ahora vive en `ITHOS_DOMINIO` (en el `.env`, que no viaja en el paquete) y el
  `Caddyfile` lo lee de ahí.
- **El empaquetado del agente estaba roto** desde que el software pasó a `ITHOS/`: el `.spec` mezclaba
  rutas y el versionador apuntaba a un instalador que ya no estaba ahí, así que el instalador se quedaba
  en una versión vieja. Además, un patrón del `.gitignore` excluía **toda la receta de compilación**, de
  modo que el agente no podía reconstruirse desde el repositorio.
- **Los recordatorios al cliente podían salir fuera de horario.** El recordatorio de la espera se
  manda ahora sólo **dentro del horario de atención del cliente** (Lun-Vie 09:00-18:00 por defecto,
  en su zona): nunca de noche ni un fin de semana.
- **Helpdesk — acciones sobre "los tickets asignados a X" tocaban tickets ajenos.** «Poné en espera
  los tickets asignados a Brian Sierra» dejaba también en espera un ticket donde Brian sólo era
  observador. Ahora la acción `poner_en_espera_asignados` filtra **en código** por el campo «Asignado a»
  (Ticket_User type=2), nunca por observador/solicitante, y reconoce a quien escribe por su número →
  usuario GLPI (config `tecnicos`). «mis tickets» / «los míos» resuelven por el número del remitente.
- **Planka no ejecutaba las órdenes por WhatsApp** («ithos, terminé…» / «ithos, agregá…»): al
  integrador se le pasaba el diccionario de configuración de IA en lugar del objeto ProveedorIA, así
  que la interpretación con IA fallaba siempre y el mensaje caía al asistente. Ahora recibe el
  ProveedorIA real; el intérprete elige la tarjeta por **número** (no copia IDs largos), entiende
  muchas más formas de decirlo (terminé/listo/ya está/empecé/trabé/…) y deja logs de diagnóstico.
- **Planka no reconocía a quien escribía por WhatsApp** cuando el número venía con otro formato o
  WhatsApp lo ocultaba con un LID: ahora identifica al remitente por los últimos 10 dígitos del
  teléfono y, si no hay teléfono, por su nombre visible (PushName).

### Security
- Cifrado en reposo (AES-256-GCM) de los secretos por cliente, con clave maestra separada.
- Alta de un solo uso, cookies `secure`/`httponly`, *rate-limit* de login y HSTS en Caddy.

## [1.0.0] - 2026-07

### Added
- Arquitectura **Gestor (control-plane) + Agente (data-plane)** multi-inquilino sobre WebSocket
  autenticado por `api_key` y token de agente.
- **Portero por voz** con TTS dedicado de Gemini (*Charon*, verbatim) sobre los parlantes.
- **Mesa de ayuda con IA**: clasificación, priorización, asignación, respuesta y ciclo de vida
  completo de los tickets (GLPI, con adaptadores para Zendesk, Freshservice, Jira y osTicket).
- **Cadena multi-IA** (Gemini → Cerebras → Groq → local) con respaldo automático por cuota.
- **Mensajería multicanal** (WhatsApp oficial y no oficial, Telegram, Email, Matrix) en texto y
  nota de voz, con activación por palabra clave y autorización por identidad.
- **Reportes ITIL** por período cerrado, en la zona horaria y los días hábiles del cliente.
- **Facturación SaaS** con MercadoPago: suscripción recurrente, *gross-up* de comisión,
  *dunning*, gracia y suspensión.
- **Empaquetado**: Docker (Gestor + Panel + Caddy con TLS/WSS) e instalador Inno firmado (Agente).
- Batería de tests de regresión y de requerimientos transversales.
