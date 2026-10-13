# Changelog

Todos los cambios notables de este proyecto se documentan acá.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y el versionado, [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Changed
- **La mesa de ayuda de INTELLIHELP pasó de GLPI 10.0.16 a GLPI 12.0.0.** El salto cruza dos
  versiones mayores, así que antes se ensayó entero —migración incluida— contra una **copia real
  de la base**, en un entorno aparte. El ensayo atajó tres cosas que habrían roto la actualización
  de verdad:
  1. la clave `config/glpicrypt.key` hay que **conservarla**: sin ella, todo lo que GLPI guarda
     cifrado queda ilegible;
  2. el optimizador de la base del hosting había agregado tres índices propios (`wdbi_…`) y, con
     ellos, la migración **se niega a arrancar** por esquema inconsistente;
  3. GLPI 12 **no trae ningún `.htaccess`**: da por sentado que el servidor web apunta a `public/`.
     Sin reescritura, Apache devuelve 404 en todo; y sin las reglas que protegían `config/`, la
     clave de cifrado habría quedado **descargable** por web.

  Para ITHOS no cambia nada: GLPI 12 conserva la ruta `/apirest.php` (ahora servida por
  `ApiRestController`), y las llamadas que usa el Gestor —`initSession`, `changeActiveEntities`
  con su envoltorio `input`, `getActiveProfile`, los rangos, los sub-recursos de seguimientos y
  soluciones, `search`— se probaron una por una contra la versión nueva antes de tocar producción.
  Requiere **PHP 8.3** (8.2 corta en seco); 8.3 es además la única versión que sirve para las dos,
  así que el GLPI viejo siguió funcionando mientras se preparaba el cambio.

- **El tema de ITH dejó de estar hardcodeado y ahora vive en un solo lugar** (`docs/glpi/tema_ith.css`,
  aplicado al CSS propio de la entidad raíz). Antes era un bloque PHP **copiado a mano en ~100
  archivos `front/*.php`**: por eso la actualización a GLPI 12 se lo llevó entero, porque trae esos
  archivos nuevos. El CSS de entidad es el mecanismo que GLPI soporta oficialmente, GLPI lo sirve en
  el `head` de **todas** las páginas —la de login incluida— y ninguna actualización lo pisa.

  **La regla del tema**, que es de donde salen las tres decisiones de abajo: *todo estado que cambia
  el fondo tiene que fijar también el texto, y el de todo lo que hay adentro.* Nunca puede quedar
  oscuro sobre oscuro ni claro sobre claro. Queda verificada en `tests/probar_tema_glpi.py`, que mide
  los contrastes reales contra la paleta puesta y falla si alguna regla pinta un fondo sin fijar su
  texto.

  1. **Lo seleccionado es verde, no violeta.** Todos los usuarios están en la paleta `auror_dark`.
     Ahí el violeta del "activo" (`#653899`) queda a **1.5:1** contra el fondo oscuro: el elemento
     seleccionado era indistinguible del resto. Ahora cada control seleccionado o bajo el puntero se
     pinta de `#9acc31` con tinta `#161922` encima —**9.2:1**— y, como el control trae su propio
     fondo, se lee igual en el tema claro que en el oscuro.

     Pintar el contenedor no alcanza: los controles de GLPI tienen hijos con **color propio**. El
     botón de perfil es un `button.nav-link` con dos `div` adentro, y el segundo es
     `.text-muted-menu`; quedaba verde con el texto blanco, **1.9:1**. Por eso cada regla de
     selección se repite con ` *`, para alcanzar a los descendientes.
  2. **El hover ahora funciona en todos lados.** El tema anterior cubría sólo `.nav-link` de la
     barra; los menús desplegables, el selector de entidad y perfil, las pestañas, las listas, el
     paginador y los `select2` no estaban contemplados. De ahí que "en varios lados no funcionara".
  3. **Los enlaces ya visitados dejan de irse al violeta del navegador** (`#551A8B`), que sobre
     `auror_dark` da **1.3:1** — era lo que hacía ilegibles los nombres ya abiertos en la lista de
     usuarios. No se arregla con `color: inherit`: por privacidad, los navegadores **descartan en
     `:visited` los valores que dependen del entorno** y sólo respetan un color explícito. La forma
     correcta, y la que se usa, es darle a `:link` y a `:visited` el **mismo** valor explícito, así
     el estado "ya visitado" no existe visualmente. En la barra va blanco; en tablas y listas, el
     color de enlace de la paleta activa, para que el arreglo siga valiendo si se cambia de paleta.

     Los enlaces del contenido no se tocan: pintarlos dejó las etiquetas de las tarjetas del tablero
     —que son enlaces— en violeta sobre naranja.

  No se tocan, a propósito, los colores de **SLA, prioridad y estado**: ahí el color es información,
  no decoración.

- **El logo de ITH pasó a tener nombre propio** (`pics/logos/ith-*.png`). Estaba pisando los PNG de
  GLPI (`logo-GLPI-*.png`), lo que traía dos problemas: cada actualización mayor los **vuelve a
  escribir**, y el navegador se queda con la copia vieja en caché —por eso seguía apareciendo el
  logo de GLPI en la pantalla de login aunque el servidor ya entregaba el de ITH—. Ahora el tema
  apunta las seis variables `--glpi-logo-*` a archivos que GLPI no conoce y no puede pisar, con un
  `?v=` para forzar la descarga.

  La marca también llegó a los dos lugares que faltaban. **El favicon** —la pestaña del navegador
  seguía mostrando la "G" de GLPI— no se puede cambiar por CSS: `head.html.twig` lo declara fijo
  como `/pics/favicon.ico`, y ese archivo lo reescribe cada versión mayor. Se resolvió desviando la
  ruta desde el `.htaccess` (que GLPI 12 **no trae**, así que es nuestro) a `ith-favicon.ico`, un
  `.ico` de seis tamaños generado del logo; la regla va **antes** del chequeo de archivo existente,
  porque si no Apache sirve el de GLPI y la reescritura nunca corre. Con la reescritura sola no
  alcanzaba para verlo: el servidor manda `Cache-Control: max-age=604800` (**7 días**) y **Chrome
  guarda los favicons en una base propia que no se refresca ni con Ctrl+Shift+R**, así que mientras
  la URL no cambie el navegador sigue mostrando el viejo. Por eso la ruta lleva ahora `?v=2`. Y **el título** decía
  "— GLPI" porque la clave `app_name` no existía en `glpi_configs` y GLPI caía en su valor por
  omisión; ahora dice **Mesa de Ayuda ITH**, que es además lo que firma el pie de las
  notificaciones. Todo queda versionado y explicado en `docs/glpi/`.

### Fixed

- **Un plugin fantasma hacía trabajar a GLPI de más en cada pedido.** La carpeta `plugins/` quedó
  vacía tras la actualización, pero `glpi_plugins` seguía marcando **mreporting** como *activado*:
  GLPI intentaba cargarlo en cada petición y dejaba el aviso `Plugin "mreporting" version changed.
  It has been deactivated` en el log una y otra vez. Desactivado por la vía oficial
  (`php bin/console plugin:deactivate`), sin borrar la fila, para poder volver atrás.

- **Diagnosticado, no nuestro:** el error *"no se pudo establecer comunicación con la base de
  datos"* que aparece de vez en cuando y se va al recargar. Sale de
  `CheckDatabaseStatusListener` cuando `$DB->connected` es falso. Los errores llegan **en ráfagas
  dentro del mismo segundo** (17 en un día), que es por lo que el mini tablero de tickets es el
  primero en mostrarlo: dispara sus siete tarjetas en paralelo y las que fallan dejan el spinner
  girando. **No es un tope nuestro**: 20 pedidos simultáneos pasan los 20. Es el MySQL compartido
  del hosting rechazando conexiones de a ratos, y GLPI no reintenta. Se arregla en el hosting o
  mudando GLPI a la VPS.

- **Los husos horarios de GLPI no se pueden activar en este hosting.** `database:enable_timezones`
  se niega porque las tablas de husos de MySQL no están cargadas, y el usuario de la base no tiene
  permiso sobre `mysql.time_zone_name` (`ERROR 1142`). Hoy **no rompe nada**: GLPI guarda en hora
  local de Argentina (`time_offset = -10800`). Lo único que no se puede es tener husos por usuario.

- **Una alarma que no se podía apagar tapaba los errores de verdad.** Los tickets #666, #673 y #680
  arrastran los recordatorios del bucle viejo, así que el tope de 30 quedaba superado para siempre
  y el ciclo registraba un `ERROR` por ticket **en cada vuelta**: ~1.180 líneas por día por algo ya
  contenido. El tope no se toca —sigue sin escribirle al cliente—, pero la alarma ahora mide el
  **espaciado**, que es el síntoma real: por diseño sale un recordatorio por día, así que **dos o
  más en la misma fecha** es `ERROR` y se avisa cada vez; el tope alcanzado por acumulación
  histórica se informa **una sola vez por corrida**.

- **El chequeo que prohíbe la marca vieja no estaba mirando el código.** Escaneaba `comun/`, `central/` y
  `agente/` colgando de la raíz, carpetas que dejaron de existir cuando el código se movió bajo
  `ITHOS/`: abría **cero archivos** y daba verde sin verificar nada. Así sobrevivieron seis
  menciones de la marca vieja en los `requirements.txt` y una en `comun/wake.py`. Corregidas las
  rutas y ampliado el
  alcance (requirements, instalador `.iss`, configuraciones), ahora abre **107 archivos**; y se le
  agregó un piso mínimo de archivos leídos, para que **un chequeo que no mira nada falle en vez de
  pasar**. Las dos únicas excepciones quedan explícitas: la carpeta de deploy `jarvis-cloud` y el
  usuario del SQL Server de fichadas, que es de un sistema de terceros.

- **Una caída pasajera de GLPI hacía que ITHOS le pisara el trabajo al técnico.**
  `_tecnicos_asignados()` atrapaba el error de lectura y devolvía un conjunto **vacío**, que es
  exactamente lo que dice un ticket todavía sin triagear. Indistinguibles. Así, un fallo de un
  segundo se leía como "ticket nuevo" y el triage volvía a correr sobre un ticket **ya trabajado**,
  cambiándole la categoría, la prioridad y la asignación que una persona había puesto a mano —
  justo lo que el requisito de triage robusto prohíbe. Y no es hipotético: el MySQL compartido del
  hosting rechaza conexiones en ráfagas, que es la condición que lo dispara. Ahora el error se
  **propaga** y, ante la duda, **no se triagea**: reintentar en la vuelta siguiente (~1 minuto) no
  cuesta nada; pisarle el trabajo a alguien, sí.

- **Un ticket podía quedar sin responsable y en silencio.** La asignación usaba
  `except Exception: pass`, comentado como "ya asignado, estado final correcto". Eso vale para el
  error **esperado** de GLPI (alta duplicada), pero se tragaba igual una caída real. Ahora, cuando
  una asignación falla, se **relee quién quedó asignado**: si falta alguien, sale un `ERROR` que
  dice a quién hay que poner a mano. Se verifica el estado final en vez de adivinar por el texto
  del error.

- **El Gestor podía arrancar sin ningún cliente, sin decirlo.** Si `clientes.json` no se podía leer,
  el padrón quedaba vacío **sin una sola línea de log**: el Gestor levantaba normal, aceptaba la
  conexión del agente y después no validaba a nadie. Como el padrón se carga **una sola vez al
  arrancar**, eso dejaba el Gestor inútil hasta que alguien lo notara a mano. Ahora el fallo se
  registra como `ERROR` diciendo qué pasa, no se pisa lo que ya estuviera cargado, y un fallo al
  **descifrar** los secretos también se avisa (antes los tokens quedaban como `enc:v1:…` y todo
  fallaba después con errores que no se parecían a la causa).

- **El log operativo era mayoría chatarra de librerías.** `httpx` y el SDK de Google escriben a
  nivel INFO en **cada** llamada a la IA, y el triage llama una vez por ticket. Se los subió a
  WARNING en `comun/ia.py` —no en el Gestor, porque el agente usa la misma capa—, así siguen
  apareciendo cuando algo falla de verdad.

- **Diagnosticado, upstream:** las notas de voz de WhatsApp no se generan cuando toca el respaldo
  gratuito. `edge-tts` 7.2.8 (la última publicada, de marzo 2026) recibe **403 en el handshake**
  del servicio de Microsoft. **No es el hosting**: falla igual desde una conexión residencial. El
  aviso igual llega al cliente, porque el código cae a texto. La voz de marca (Charon) no está
  afectada.

### Security
- **El portal del cliente entregaba TODOS sus secretos.** `GET /api/cliente/<api_key>` devolvía la
  configuración completa y descifrada —los tokens de GLPI (incluido el de **super admin**), las
  claves de IA, la contraseña del agente y la de la base de fichajes— a cualquiera que tuviera la
  `api_key`. Y esa clave viaja en la URL del portal, así que termina en los registros del proxy, en
  el historial del navegador y en la cabecera `Referer`. El cifrado en reposo dejaba de servir por
  esta sola puerta. Ahora los secretos salen **enmascarados** (se ve que están y cuál es cuál, no su
  valor) salvo para el superadmin, y al guardar, un valor enmascarado **no pisa** al que estaba.
- **Todo el ciclo de vida de los tickets corría como administrador de GLPI.** Se instanciaba el
  cliente sin token, así que caía en `glpi_user_token`: el usuario que puede **borrar**. ITHOS tiene
  a propósito un perfil acotado para que un error suyo no pueda destruir nada. Ahora usa el suyo; el
  nombre de quien escribe se lee con el token de lectura, que es el único que puede.
- **El anti fuerza-bruta del login no existía en la práctica.** Contaba los intentos por el PRIMER
  valor de `X-Forwarded-For`, que lo escribe quien llama: mandando uno distinto en cada intento,
  nunca se llegaba al límite. Ahora se usa el último, que es el que agrega nuestro proxy.
- **Se entraba al panel con la contraseña en la URL** (`?k=…`), que queda registrada en todos lados.
  Se eliminó: se entra por el formulario.
- **Toda ruta nueva nacía pública.** El control enumeraba lo privado, así que cualquier endpoint que
  se agregara quedaba abierto a internet hasta que alguien se acordara de listarlo. Ahora es al
  revés: **denegar por defecto**, con una lista explícita de lo público.
- **El modo administrador se concedía ante la duda.** El control de identidad fallaba abierto por
  tres caminos distintos —sin perfil de voz entrenado, ante cualquier excepción del verificador, y
  en todo canal que no fuera el micrófono—. Por WhatsApp la frase-clave **sola** daba acceso total:
  cualquiera del grupo que la escuchara una vez quedaba con el conocimiento propietario y las
  acciones sobre los tickets. Ahora la frase-clave es un **segundo** factor y, sin poder confirmar
  quién habla, no hay acceso.
- **La frase-clave se aceptaba a medias.** Bastaba con algo que *sonara* parecido (pasaban
  "canelito", "panerito") más una palabra de uso común como "administrador". El número ahora es
  obligatorio y la tolerancia fonética admite una sola letra.
- **La clave de administrador estaba escrita en el código**, la misma para todos los clientes, y
  viajaba al proveedor de transcripción en el vocabulario de **cada audio**. Sale de
  `ITHOS_CLAVE_ADMIN`.
- **La sesión del panel no vencía ni se podía revocar.** La cookie era un hash fijo: el mismo valor
  siempre, aceptado para siempre; `max_age` sólo le pide al navegador que la olvide, y `/logout`
  borraba nada más esa copia. Una cookie copiada servía hasta cambiar la contraseña. Ahora va
  firmada con su fecha de emisión, el servidor la vence a las 8 horas y cerrar sesión invalida
  todas las anteriores.
- **El enlace de alta de "un solo uso" se podía usar dos veces.** Se leía y escribía sin candado:
  dos envíos simultáneos —el doble clic de siempre— lo consumían los dos. Y la escritura no atómica
  podía dejar el archivo a medias y perder, en silencio, todos los enlaces vigentes.

### Fixed
- **Un ticket que quede en "Nuevo" podía no volver a mirarse nunca.** El poll revisa los 30 tickets
  MÁS NUEVOS, que es lo que hace falta para atender lo que entra; pero uno que quedara en "Nuevo"
  —porque su triage falló, o porque entraron 30 más mientras tanto— iba saliendo de esa ventana y
  dejaba de existir para el circuito: sin categoría, sin asignar, sin primera respuesta y sin SLA
  corriendo, y nadie se enteraba. Ahora, cada diez vueltas, se revisa el histórico completo. Es un
  hueco que hoy no se estaba dando (el volumen de tickets no alcanza para llenar la ventana entre
  dos vueltas), pero no depende de eso: depende de que el triage no falle nunca, y eso no se puede
  dar por sentado.
- **La mesa de ayuda dejaba de funcionar cuando el cliente apagaba la PC.** El triage, los reportes,
  la alerta de SLA, la base de conocimiento y la reactivación de tickets pospuestos vivían dentro
  del manejador del WebSocket del agente y se cancelaban al desconectarse. Un ticket que entraba a
  la noche o un fin de semana no se categorizaba, no se asignaba, no recibía primera respuesta y no
  corría su SLA hasta que alguien encendiera la computadora. Ahora esos servicios son **del
  cliente, no de la conexión**: arrancan con el Gestor y siguen estén o no los agentes. El agente
  aporta la voz y el control de acceso; si no está, lo único que no se puede entregar es la voz.
- **Guardar desde el panel borraba configuración.** El registro se reconstruía con los campos del
  formulario, y el formulario no los tiene todos: una edición para cambiar un correo dejaba al
  cliente sin su bloque `tecnicos`, sin los tokens de GLPI de cada técnico, sin Planka, sin su
  saludo, su abreviatura, su horario de atención ni su micrófono. Ahora se fusiona sobre lo guardado.
- **El estado de las tareas de fondo se perdía en cada actualización.** `proactivo`, `anomalias` y
  `reportes_programados` lo guardaban junto a su propio código, que en el servidor vive dentro de la
  imagen del contenedor: cada deploy lo borraba, así que las alertas de SLA ya avisadas volvían a
  salir y el reporte del día se reenviaba. Va al volumen, y **todos** los archivos de estado se
  escriben de forma atómica (antes, un corte a mitad de escritura los dejaba truncados y, como la
  lectura devuelve vacío ante un error, el estado se perdía sin que nadie se enterara).
- **Los avisos salían con la hora del servidor.** La alerta de SLA decía "21:40" cuando para el
  cliente eran las 18:40, y el contador de "una vez por día" se reiniciaba a las 21:00 de su hora,
  así que la misma alerta podía repetirse esa noche. El asistente, además, le daba a la IA la fecha
  del servidor: entre las 21:00 y la medianoche le contestaba con la fecha de **mañana**.
- **No se le podía asignar un ticket a nadie del equipo nuevo.** `asignar` salía de una lista fija
  de dos personas escrita en el código: pedirle "asigná el #123 a Laura" contestaba que no la
  reconocía, aunque estuviera cargada en la configuración y el triage automático sí la usara. Y el
  prompt del asistente nombraba a esas mismas dos personas como únicos responsables posibles.
- **La base de conocimiento aprendía los recordatorios como si fueran soluciones.** La "resolución"
  se tomaba del último comentario del ticket, fuera lo que fuera; con los tickets llenos de avisos
  automáticos, terminó registrando "le recordamos que su ticket está a la espera…" como la forma de
  resolver un problema de fichaje. Ahora los avisos del circuito nunca cuentan como resolución.
- **Lecturas repetidas contra la mesa de ayuda.** Cada acción sobre un ticket abría y cerraba una
  sesión de GLPI (cuatro viajes para hacer uno, y tres sesiones para una sola operación lógica); la
  solución de un ticket se pedía tres veces por vuelta; y armar la lista de resueltos hacía una
  petición por ticket (hasta 160). Todo eso es una lectura ahora.
- **La consulta al sistema de fichajes se armaba pegando valores del formulario**, y el recorte de
  fichadas ya anunciadas descartaba entradas al azar (un conjunto no tiene orden), así que podía
  volver a anunciar una fichada reciente por los parlantes.
- **El Gestor informaba una versión escrita a mano** ("0.5" con el Gestor en 1.1.x). Sale del
  control de versiones, y el deploy deja asentada **qué revisión quedó corriendo** —antes no había
  forma de saber si un arreglo había llegado al servidor—.

- **Cada cliente nuevo nacía consultando la mesa de ayuda cada 5 segundos.** El valor estaba fijo en
  el panel (`_armar_cliente`), en el ejemplo de configuración y en la de INTELLIHELP: **17.280
  vueltas por día** contra GLPI para atender un puñado de tickets, y cada vuelta lee los tickets,
  sus seguimientos y consulta la IA. Ese ritmo, además, hacía que GLPI escribiera una fila de
  registro por cada llamada a su API: su base llegó a **2.045 MB de log (9,4 millones de filas)**
  para 577 tickets, y ya se había llenado una vez. Ahora el valor por defecto —en el panel, en el
  ejemplo y en el propio integrador— es de **60 segundos**.
- **El ciclo leía sólo los 50 primeros seguimientos de un ticket, y eso derivó en 19.555
  recordatorios duplicados.** La API de GLPI devuelve **50 ítems** cuando no se le pasa `range`, y
  lo hace **sin avisar**: no hay error ni bandera de "hay más". El ciclo pedía
  `/Ticket/<id>/ITILFollowup` a secas, así que mientras el ticket tenía menos de 50 seguimientos
  todo funcionaba —un recordatorio por día hábil, que es lo diseñado— pero **el día que cruzaba los
  50**, la API empezaba a devolver siempre los 50 **más viejos**. Desde ahí el "último aviso" que
  calculaba el ciclo quedaba congelado en el pasado, el control de "uno por día" daba siempre que
  sí, y salía un recordatorio **en cada vuelta del ciclo** (cada 5 segundos); cada uno empujaba la
  ventana más lejos, así que se realimentaba solo. En producción escribió **1.269 comentarios en un
  ticket en seis horas**, y **10.525** en otro, todos visibles para el cliente. Peor todavía: el
  ciclo decide **todo** con esa misma lista —si el cliente respondió, si ya se pidió la
  confirmación, si ya se escaló—, así que pasados los 50 seguimientos **ITHOS dejaba de ver lo que
  contestaba el cliente** y el ticket no podía avanzar nunca más. Ahora los seguimientos se leen
  **paginados y completos** (`comun/glpi.py: followups()` / `pagina_todo()`, que avanzan por lo que
  GLPI **devuelve** y no por lo que se pidió) y hay un **tope absoluto de 30 recordatorios por
  ticket**: una red para que ningún error futuro en el espaciado pueda volver a inundar al cliente
  —se deja de insistir y se avisa al equipo en el log—.
- **`recordar_espera()` decía que había enviado un aviso que GLPI había rechazado.** El envío del
  comentario es "no fatal" a propósito (si GLPI lo rechaza, el ticket igual tiene que quedar con el
  estado correcto), pero el error se tragaba **y además se devolvía `True`**. El ciclo entonces
  registraba "recordatorio enviado", el ticket no cambiaba, y en la vuelta siguiente lo volvía a
  intentar; para siempre. Se vio con GLPI caído tres horas: 187 recordatorios "enviados" por hora
  que nunca existieron. Ahora `_followup()` devuelve si GLPI **aceptó** la escritura, y
  `recordar_espera()`, `recordar_confirmacion()` y `pedir_confirmacion()` propagan esa verdad.
- **El texto del panel prometía canales que no existen.** La ayuda del formulario decía que ITHOS
  avisa por WhatsApp, Telegram, Email, Teams, Slack o Matrix; el único canal implementado —y el
  único que el formulario ofrece— es **WhatsApp**. El texto ahora dice lo que el software hace.

### Added
- **Los grupos por tema se configuran desde el panel.** Hasta ahora los grupos de WhatsApp y su
  ámbito había que escribirlos a mano en la configuración. La tarjeta del canal ahora deja agregar,
  editar y quitar grupos, eligiendo de qué es cada uno de una lista con su explicación.
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
- **Los dos archivos más grandes, partidos por tema.** `central/triage.py` (1.129 líneas) y
  `comun/conversacion.py` (1.186) hacían demasiadas cosas a la vez y cada arreglo obligaba a leerlos
  enteros. Ahora el triage vive en cuatro módulos —`triage.py` (clasificar el ticket nuevo),
  `ciclo.py` (el ciclo de vida: esperas, recordatorios, escalada, reapertura), `equipo.py` (quién es
  quién) y `textos_ticket.py` (todo lo que se le escribe a una persona)— y el asistente en dos:
  `asistente.py` (el que conversa) y `herramientas.py` (qué puede leer y qué puede escribir sobre los
  tickets). `triage.py` y `conversacion.py` siguen exportando lo mismo que antes, así que nada de lo
  que los importaba cambió: **no hay cambio de comportamiento**, sólo de dónde vive cada cosa.
- **Avisos de Planka más legibles.** El resumen diario y el seguimiento listan una tarea por
  línea, agrupadas por lista y con su contador, en lugar de una única línea con comas.
- **Seguimiento acotado a lo activo.** El «¿cómo venís?» pregunta únicamente por Haciendo y
  En revisión/Esperando. Cuando la persona termina todo lo que tenía en curso, ITHOS le pregunta
  qué tarea sigue (ofreciendo lo de Por hacer) o cuál nueva quiere agregar.
- **Triage de GLPI más robusto.** Respeta la asignación manual del técnico, detecta pedidos de
  coordinación sólo del lado del técnico (no del cliente), deja notas internas privadas y ajusta
  el SLA por calendario y horario de atención (Lun–Vie 09–18).

### Changed
- **El seguimiento del tablero pasa de cada hora a cada 3 horas.** Preguntarle a alguien nueve veces
  por día cómo viene con la misma tarea deja de ser seguimiento y pasa a ser ruido, y el ruido se
  ignora. Lo que de verdad cambió —una tarjeta nueva, una asignación, un movimiento de lista— se
  sigue avisando **en el momento**. Configurable con `seguimiento_cada_horas`.
- **Mientras falte algo del cliente, el ticket lo espera.** El ciclo ahora pregunta **primero** si
  queda algo en manos del cliente y **después** si está resuelto. Un comentario del técnico puede
  decir «el acceso quedó solucionado» y en la misma línea pedirle al cliente que escale algo para
  cerrarlo del todo: eso no es un cierre, es un **seguimiento**. Queda En espera, el cliente
  responde, vuelve a En curso, y así hasta que de verdad no falte nada. También cuenta como pendiente
  que el cliente tenga que gestionar algo **de su lado** (derivarlo a otra área suya, reconectar o
  revisar un equipo propio), no sólo coordinar una visita.

### Fixed
- **Si el cliente rechazaba la solución con el botón, nadie se enteraba.** El cliente puede contestar
  de dos formas: escribiendo, o apretando **Aprobar / Rechazar** sobre la solución. Sólo mirábamos lo
  escrito, así que quien rechazaba sin escribir nada quedaba esperando para siempre: la solución
  figuraba rechazada y el ticket seguía en Resuelto. Ahora aprobar **cierra** el ticket y rechazar lo
  devuelve a **En curso**, avisando al equipo.
- **El cliente no tenía cómo confirmar el cierre ni rechazarlo.** El ticket pasaba a Resuelto **sin
  cargar la solución**, y en la mesa de ayuda el solicitante aprueba o rechaza **la solución**: sin
  ella veía el ticket resuelto y no tenía ningún botón que tocar. Ahora se carga con **las palabras
  del propio técnico** y **con su usuario**, así el cliente puede confirmar que quedó bien o decir
  que sigue igual para que vuelva a En curso.
- **El SLA seguía alertando de tickets que estaban pausados.** El vigilante incluía los tickets **En
  espera**, cuando ahí el SLA no corre porque la pelota es del cliente; encima usaba un vencimiento
  que la mesa de ayuda todavía no había descontado (lo ajusta recién al salir de la espera). Eran dos
  errores en el mismo aviso. Ahora sólo se alerta por **Nuevo** y **En curso**.
- **El comentario del técnico le llegaba a la IA como una pared de CSS.** GLPI guarda el contenido con
  las etiquetas **escapadas** (`&#60;p&#62;` por `<p>`), así que quitar `<...>` no quitaba nada: de un
  comentario de 24.000 caracteres, el texto real quedaba enterrado entre los estilos del editor y la
  IA no lo veía. Un «quedó solucionado» pasaba de largo. Ahora se desescapa antes de limpiar, en el
  comentario del técnico y en la solución documentada.
- **Un «quedó solucionado» explícito ya no depende de interpretación.** Si el técnico lo dice con
  todas las letras, cuenta —por largo que siga el comentario—, salvo que quede algo pendiente del
  cliente. Reconoce las formas habituales y no se confunde con las negadas ni con las futuras
  («todavía no se resolvió», «cuando quede solucionado»).
- **Un ticket podía quedarse esperando una respuesta que ya había llegado.** Para saber si el cliente
  había contestado, el ciclo miraba el **último comentario de un técnico**. Cuando el técnico
  respondía **después** del cliente —que es lo normal y lo deseable—, esa referencia se corría por
  delante de la respuesta y el ticket se quedaba **En espera para siempre**. Y en espera el SLA no
  corre: no vence, no alerta, no se entera nadie. Un ticket estuvo así **dieciséis días**. Ahora la
  referencia es **el pedido de ITHOS**, no el último que habló: si hay una respuesta del cliente
  posterior al pedido, el ticket avanza. Vale igual para la confirmación de un ticket resuelto.
- **La prioridad dependía del humor del modelo.** Era sólo un mínimo: si el modelo decía «Media» para
  el caso de una persona, nadie lo corregía, así que dos tickets iguales salían con prioridades
  distintas y los reportes de SLA comparaban cosas que no son comparables. Ahora la prioridad **es la
  que le corresponde al alcance**, siempre.
- **Un ticket quedaba trabado si la IA no estaba en ese instante.** Interpretar el comentario de un
  técnico («quedó solucionado») necesita la IA. Si no estaba, el ciclo no hacía nada —correcto—, pero
  **daba el comentario por visto**, así que cuando la IA volvía minutos después ya no lo miraba más.
  Ahora queda pendiente y se reintenta.
- **Los tickets que entraban por otra área del cliente no los veía nadie.** En GLPI un mismo cliente
  tiene **una entidad por área** —mesa de ayuda, soporte técnico, infraestructura— e ITHOS miraba una
  sola: todo lo que entraba por las otras quedaba fuera del circuito. Un aviso de Sistemas por unas
  terminales desenergizadas estuvo **siete días en Nuevo**, sin asignar, sin primera respuesta y sin
  SLA. Ahora el cliente son **todas sus entidades** (se resuelven leyendo GLPI, sin escribir nada a
  mano; se pueden fijar con `entidades: [12, 13]`), y eso vale para el vigilante, el ciclo de vida,
  el asistente y los reportes. Además, cada área tiene **sus propias categorías y sus propios SLA**,
  con ids distintos: el triage ahora usa el catálogo **de la entidad del ticket** en vez de los ids
  fijos de la entidad principal, que era cargar el ticket mal. Si un área no tiene catálogo cargado,
  se deja sin categoría y sin SLA —mejor vacío que equivocado— pero el ticket **se asigna y se
  contesta igual**. Va con esto que la sesión de GLPI abra con **todas las entidades activas**:
  GLPI activa una sola y el resto responde «sin permiso» aunque el permiso esté.
- **Un modelo dado de baja por el proveedor dejaba el triage sin IA.** Groq retiró los Llama y todas
  las consultas empezaron a devolver «el modelo no existe». Igual que con la cuota, ahora ITHOS sigue
  con el **modelo siguiente del mismo proveedor** antes de cambiar de proveedor.
- **El triage se quedaba sin IA y dejaba de clasificar tickets.** La cuota gratuita de Gemini es por
  **modelo y por día**, y la de `gemini-2.5-flash-lite` —el que elegía «auto» por ser el más eficiente—
  quedó en **20 pedidos por día**: se agotaba con 20 tickets. ITHOS saltaba de **proveedor** aunque
  `gemini-2.5-flash` todavía tuviera cuota del día, y si el proveedor siguiente estaba caído se quedaba
  sin ninguna IA (el ticket no se clasificaba y el ciclo no cerraba nada). Ahora, agotado un modelo,
  sigue con el **siguiente modelo de Gemini** y recién cambia de proveedor cuando se agotan todos; lo
  agotado se libera solo al día siguiente. Vale igual para el texto y para transcribir audios.
- **La voz no sonaba: el modelo guardado ya no genera audio.** La configuración de los clientes tenía
  fijado `gemini-2.5-flash-native-audio-latest`, que es **conversacional** y devuelve 404 al pedirle
  audio, y pisaba al TTS dedicado. Una configuración con un modelo que no es TTS ahora se corrige sola:
  es preferible una voz que suena a una que no.
- **El panel ofrecía sistemas que ya no existen.** Después del recorte, los desplegables seguían
  listando Zendesk, Jira, Telegram, Teams, Slack, HikCentral y demás: elegirlos daba de alta un cliente
  que **nunca iba a recibir nada**, sin ningún aviso. Ahora el catálogo lista exactamente lo que tiene
  implementación (GLPI · WhatsApp con número propio · IVMS) y el test general lo verifica contra el
  código, no contra una lista escrita a mano.
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
