# ITHOS — FALTANTES (Fase 2, para el despliegue en la VPS)

> **Cuándo aplicar:** cuando pasemos de la prueba local a poner el **Gestor en la VPS de Hostinger (KVM 2)** —
> primer cliente **INTELLIHELP S.A.**. Estos ítems rinden y se hacen bien recién con un despliegue real (flota,
> firma de código, instalación en clientes). Detalle y fuentes en [ARQUITECTURA_GESTOR_AGENTE.md](ARQUITECTURA_GESTOR_AGENTE.md).

## Pendientes de Fase 2

- [ ] **Gemini PAGO para la voz Charon** (voz-id del cliente): (1) **generar una API key nueva** en AI Studio
      (la actual `AQ...` es válida y paga pero tiene el **saldo de prepago en 0** → 429 "prepayment credits
      depleted"); (2) **cargar créditos** (prepago, mínimo US$10 — alcanza para AÑOS: cachear el padrón cuesta
      ~US$0,35–1,40, una vez, y los saludos se reusan); (3) recomendado **auto-recarga con tope mensual bajo**.
      Con saldo, se guarda la key (cifrada) y se **regenera todo el padrón con Charon a 1.20 uniforme al instante**
      (sin el tope free de 10 TTS/día). Hasta entonces, sigue la key free (10/día) — no se toca. Ver
      [[voz-velocidad-variedad]] / billing: ai.google.dev/gemini-api/docs/billing.
- [ ] **Empaquetar el agente con Nuitka** (en vez de PyInstaller): menos falsos positivos de antivirus, más rápido.
      Requiere toolchain C. Se hace al distribuir a clientes reales.
- [ ] **Firma de código de CA pública (OV/EV pago o Azure Trusted Signing ~US$10/mes)** para que el instalador NO
      lo marque SmartScreen **en cualquier PC** (fuera de la flota). Hoy está la firma **self-signed gratis** (ok en
      las PCs de la flota que confían el cert — ver INSTALACION_AGENTE.md §1). No hay cert gratis de CA pública para
      software propietario (SignPath Foundation = solo open-source).
- [ ] **Auto‑update del agente por red** (estilo Chrome/Steam): el Gestor publica versión + manifiesto firmado; el
      agente **avisa** y **el usuario decide** (ahora/después); descarga, **verifica la firma**, se reemplaza y
      reinicia. **Nunca se manda un archivo a mano.** ⚠️ **Necesita firma de código + rollback + pruebas de campo**
      (es lo más delicado: un update malo rompe agentes). Herramienta: PyUpdater o updater propio servido por el Gestor.
- [ ] **Métricas de flota** en el Gestor: qué agentes están conectados y con qué versión (para desplegar updates
      de a poco / staged rollout).

## Hecho (Fase 1) — referencia
- [x] Versionado SemVer (Gestor + Agente) + handshake de versión en el `auth` (compat hacia atrás). (H26)
- [x] Jitter en la reconexión del agente (backoff + jitter, tope 30s).
- [x] Vocabulario **Gestor + Agente** (app, logs, demo, docs).
- [x] **Agente = APP con interfaz gráfica ITHOS** (pywebview, multiplataforma, no consola) + **un solo instalador**
      Inno personalizado (`dist\ITHOS-Agente-Setup.exe`), con arranque al iniciar sesión, datos en `%LOCALAPPDATA%\ITHOS`
      y desinstalado **sin rastro** (solo lo del agente). Build: `build/construir_agente.bat`. (H47)
- [x] **Firma de código GRATIS (self-signed INTELLIHELP + timestamp)** para la flota controlada: `build/firmar.ps1`
      + `build/confiar_en_cliente.ps1` (Trusted Root/Publishers, admin o GPO). (H47)
- [x] Test de **comunicación entre redes** Gestor(VPS) ↔ Agente(cliente, otra IP) — agente sale hacia afuera, NAT ok. (H27)
- [x] **Seguridad de acceso** (Fase 1.5): login del Gestor (solo INTELLIHELP) + enlace de alta temporal de un solo
      uso, con la demo adaptada. (ver más abajo / H28)

*Actualizar este archivo a medida que se completen los pendientes.*
