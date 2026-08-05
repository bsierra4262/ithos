# Changelog

Todos los cambios notables de este proyecto se documentan acá.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y el versionado, [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added
- **Un grupo de WhatsApp por tema (ámbitos).** Un solo grupo para todo se volvía inservible: las alertas
  de tickets tapaban las tareas del equipo y quien sólo quería preguntar algo leía alertas todo el día.
  Ahora cada grupo declara su **ámbito**, que define **qué avisos recibe** y **sobre qué se consulta
  ahí**: `consultas` (ninguna alerta, pero todas las capacidades), `soporte` (tickets y SLA, y sólo se
  contestan tickets), `tareas` (el tablero del equipo) y `sistema` (reinicios, cuotas, cobranza y
  entrenamiento de voz). Cada aviso **nace con su tipo** y va sólo a donde corresponde —las @menciones
  al técnico asignado también—, y una consulta fuera del alcance de un grupo se **deriva** al que sí la
  maneja en vez de quedar sin respuesta. Se configura con `grupos: [{grupo, ambito}]`; un cliente con un
  solo `grupo` sigue funcionando igual que antes.
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
- **El equipo sale de la configuración, y los que se están formando trabajan acompañados.** Los
  técnicos se declaran en `tecnicos` (nombre, id/login y teléfonos): con eso ITHOS los reconoce
  —sus comentarios resuelven—, les asigna, les menciona y les responde «mis tickets» por su número,
  **sin tocar código**. Si en la ficha de alguien se indica un `responsable`, el ticket que le toca
  a esa persona **se le asigna también a él, al mismo tiempo y con el mismo criterio**: trabajan el
  mismo caso hasta que pueda resolverlo solo. Se saca el campo y se vuelve a la derivación normal.
- **Tareas del equipo — las columnas conservan su color y el equipo se mantiene al día.** Cada mes
  nuevo nace con los mismos colores que el anterior (y una columna que quedó gris se corrige sola),
  y quien entra al equipo se suma como miembro de **todos** los tableros del mes —incluidos los que
  ya existían—, así se le puede asignar una tarjeta desde el primer día.
- **Triage — el ALCANCE del problema decide el ticket.** Antes de clasificar, ITHOS define **qué**
  falla: el fichaje de una persona (`individual`), varias identificadas (`grupo`), un lector de los
  que tiene la sede (`equipo`), la sede entera sin fichaje (`sede`) o varias sedes (`masivo`). De ahí
  salen el **piso de prioridad** (Baja/Media/Alta/Urgente/Urgente), **quién lo toma** —el equipamiento
  caído es instalaciones; los casos individuales y el software, soporte— y si corresponde pedir el
  **legajo**. Cuando el alcance no es individual **no hay a quién pedírselo**, y si hay que **ir al
  lugar** —un equipo caído no se arregla por mail— lo único que se le pide al cliente es **coordinar la
  visita**: qué día y en qué franja horaria podemos pasar, y con quién nos encontramos. Las
  instalaciones las hicimos nosotros, así que no se pregunta la ubicación, si tiene energía ni si hay
  otro lector: eso ya lo sabemos y se ve al llegar. Con ese pedido el ticket queda **En espera de la
  coordinación**, con el recordatorio por día hábil y la escalada al técnico a los cinco. No depende de
  que el modelo se acuerde: las reglas se aplican sobre lo que devolvió, la respuesta se **reemplaza**
  antes de salir si pide identificar a un afectado, si pregunta datos que ya tenemos o si no pide la
  coordinación, y si el texto dice que el equipo *dejó de funcionar / está apagado* o que *nadie puede
  fichar* y no identifica a nadie, el alcance **sube** aunque el modelo lo haya leído como individual.
  Cada corrección se le explica al técnico asignado por nota privada. Además, el triage clasifica
  **viendo los casos parecidos ya trabajados** del cliente, no sólo el texto del ticket.
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
- **Un técnico nuevo se leía como si fuera el cliente.** El ciclo de vida reconocía sólo a los
  técnicos escritos en el código, no a los de la configuración. Cuando alguien que entró al equipo
  resolvió un ticket a las 18:30, ITHOS lo tomó como «el cliente respondió fuera de horario» y lo
  dejó **En espera** hasta el día siguiente, en vez de marcarlo resuelto y pedirle la confirmación
  al cliente. Ahora el ciclo usa el equipo de la config, igual que el triage.
- **La resolución del técnico se duplicaba, y a nombre de otro.** Cuando alguien resolvía por
  comentario, ITHOS escribía además su propia «solución» —genérica y a nombre de ITHOS o del
  administrador—, así que el ticket mostraba la explicación dos veces y atribuida a quien no
  resolvió. Ahora la resolución es **el comentario del técnico, con sus palabras**: el ticket sólo
  pasa a **Resuelto** y acto seguido se le informa al cliente para que confirme. Como el técnico ya
  explicó cómo lo resolvió, tampoco se le pide que lo documente. Si el ticket se cierra por otra vía
  y sí hay que documentar una solución, se carga **con el usuario del técnico** (token
  `glpi_<login>_token`), no con el de ITHOS.
- **Pedía un legajo que ya estaba en el ticket.** El asunto se carga como «00084 Zuker Sebastián»: el
  número **es** el legajo aunque no diga la palabra. ITHOS leía sólo la descripción, no lo veía, y dejaba
  el ticket **En espera** pidiéndole al cliente un dato que ya había escrito. Ahora el legajo se reconoce
  también en el asunto —con o sin la palabra «legajo»—, el ticket **avanza** y la respuesta lo nombra en
  vez de pedirlo. Si de verdad falta, se sigue pidiendo como siempre.
- **La primera respuesta firmaba dos veces.** Cuando el modelo cerraba con su propia firma («Gracias,
  Soporte ITH») y el sistema le agregaba el cierre de espera, el cliente leía «Soporte ITH» repetido.
- **El SLA corría de noche y los fines de semana.** Cuando el cliente respondía fuera del horario de
  atención el ticket pasaba a **En curso** igual, así que el reloj del SLA corría sábado y domingo
  contra un equipo que no estaba trabajando y el lunes el ticket ya nacía vencido. Ahora, si la
  respuesta llega fuera de horario, el ticket queda **En espera** y se reabre **solo** al abrir la
  jornada (por defecto el próximo día hábil a las 09:00). El cliente no se entera del corte y no
  recibe recordatorios: no le estamos pidiendo nada.
- **Una respuesta del cliente podía pasar desapercibida.** Un ticket ya **En curso** no avisaba nada
  cuando el cliente escribía. Ahora **cada** respuesta se avisa por los canales del equipo citando lo
  que dijo y cómo queda el ticket; y si pasan **2 horas hábiles** sin que le contestemos, el técnico
  asignado recibe el aviso —nota interna privada y WhatsApp @mencionándolo— de que le respondieron y
  todavía no contestó. Una vez por día hábil y sin repetirse tras un reinicio.
- **Un equipo caído se trataba como el problema de un usuario suelto.** Un ticket que avisaba que el
  biométrico de una sede **dejó de funcionar y quedó apagado** —nadie podía fichar ahí— entró con
  prioridad **Baja**, asignado a soporte y **En espera** pidiendo "el nombre y el legajo de la persona
  afectada", que no existía: la sede quedó sin fichar mientras el ticket dormía. La regla que exigía el
  legajo era incondicional y nada distinguía la falla de una persona de la caída del servicio. Ahora lo
  decide el **alcance** (ver arriba), con corrección determinística y respaldo en el texto del ticket.
- **La primera respuesta se despedía dos veces.** El modelo cerraba con su propia fórmula ("Quedo a la
  espera de tu respuesta. Soporte ITH") y el sistema le agregaba la suya, así que el cliente leía la
  misma frase repetida. Ahora se reconoce cualquier variante de esa despedida y se reemplaza por la
  única que el ciclo necesita para saber que el ticket espera al cliente.
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
