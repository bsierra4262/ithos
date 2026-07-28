# Changelog

Todos los cambios notables de este proyecto se documentan acá.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y el versionado, [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added
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
