# ITHOS — FALTANTES

> **Qué es esto:** lo que queda pendiente o tiene un límite conocido, con ITHOS ya en producción como
> **herramienta interna de INTELLIHELP S.A.**: un Gestor en el VPS Hostinger KVM 2 y un agente en la PC de la
> oficina. Actualizado el 18-nov-2026. Lo que era de la etapa de producto a la venta (MSI, auto-update por red,
> métricas de flota, firma de CA pública, Nuitka, alta de clientes, facturación) salió del alcance y no se sigue.

## Pendientes

- [ ] **Derivación con balanceo a los técnicos** más allá de la mesa por carga (hoy: instalaciones,
      escalamiento y la mesa repartida por la cantidad de tickets abiertos, todo desde `reparto`). Se diseña con
      el equipo.

## Límites conocidos (se aceptan como están)

- **Voz Charon con la cuota gratuita de Gemini.** Se decidió no pagar. El TTS tiene tope diario: el padrón de
  saludos se cachea de a poco y, mientras tanto, lo que no está en caché suena con edge-tts. Las notas de voz de
  WhatsApp usan siempre edge-tts para no gastar esa cuota.
- **IA local lenta.** En el VPS sin GPU, `qwen3:4b` tarda unos 100 segundos por triage: es el último respaldo de
  la cadena, no la primaria. Cuando salga un modelo nuevo o cambie el VPS, se vuelve a medir con
  `tests/medir_ia_local.py`.
- **IVMS no tiene API.** Se lee su base de fichajes (SQL Server), por eso ese integrador corre en el agente y la
  PC necesita el driver ODBC.
- **WhatsApp no oficial (neonize).** Depende de una sesión vinculada por QR; si WhatsApp la cierra, hay que volver
  a vincular desde el panel.
- **SmartScreen en una PC nueva.** El agente se firma con el certificado propio de INTELLIHELP; el instalador lo
  deja como confiable, pero la primera ejecución del instalador en una PC nueva puede mostrar una vez el aviso de
  "editor desconocido".

## Hecho — referencia
- [x] Versionado SemVer (Gestor + Agente) + handshake de versión en el `auth` (compatible hacia atrás). La versión
      del Gestor se sube en el repositorio antes de armar el paquete.
- [x] Jitter en la reconexión del agente (backoff + jitter ±30 %, tope 30 s).
- [x] Vocabulario **Gestor + Agente** (app, logs, docs).
- [x] **Agente = APP con interfaz gráfica ITHOS** (pywebview + bandeja) y **un solo instalador** Inno
      (`compilador\dist\ITHOS-Agente-Setup.exe`), con arranque al iniciar sesión (`--run`), datos en
      `%LOCALAPPDATA%\ITHOS` y desinstalado **sin rastro**. Build: `compilador/build/construir_agente.bat`.
- [x] **Firma de código propia de INTELLIHELP** (`compilador/build/firmar.ps1`); el instalador confía el
      certificado en la PC.
- [x] Comunicación entre redes Gestor (VPS) ↔ Agente (oficina): el agente sale hacia afuera, NAT ok.
- [x] **Seguridad de acceso**: todo el panel con login del administrador (denegar por defecto), secretos cifrados
      en reposo, sin rutas que devuelvan la configuración con claves.
- [x] **Gestor en producción** en el VPS Hostinger KVM 2 (central, panel, ollama, caddy), con la cadena
      Gemini → Groq → IA local.
- [x] **Wiki Outline conectada** en los dos sentidos (lee para la KB y publica el paso a paso de los cerrados).

*Actualizar este archivo a medida que se completen los pendientes.*
