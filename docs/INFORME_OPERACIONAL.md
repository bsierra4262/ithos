# ITHOS — Parte 1: alcance y costos operativos
## 1. ¿Qué hace ITHOS hoy?

Alcance actual, ya funcionando y probado. ITHOS es un producto multiempresa en la nube: un "cerebro" central y un
agente liviano por cliente, con aislamiento total entre empresas. Se instala en Windows, Linux o Mac.

- **Portero por voz.** Cuando alguien ficha en el control de acceso —IVMS, HikCentral, BioStar 2, ZKTeco u
  Honeywell—, ITHOS lo saluda por los parlantes con voz propia, Charon, a una velocidad cómoda y pareja. El saludo
  de entrada es coherente con la hora —buenos días, buenas tardes o buenas noches—, cambia de fórmula día a día
  para que no suene repetitivo y no vuelve a saludar a la misma persona en la jornada. Cada terminal se reconoce
  sola y se configura como entrada, salida o sala, con su propio saludo y su frecuencia.
- **Mesa de ayuda con IA.** Detecta los tickets nuevos del sistema del cliente —GLPI, Zendesk, Freshservice, Jira,
  osTicket, o ninguno si aún no tiene— y los clasifica, prioriza, asigna, responde y cierra, pidiendo confirmación.
  Pide datos solo si faltan de verdad; si un técnico resuelve por un comentario, lo marca resuelto y le pide al
  cliente que confirme, con recordatorio diario hasta la respuesta. **Ninguna espera queda olvidada:** mientras el
  ticket depende del cliente —porque falta un dato o porque tiene que confirmar un trabajo— el SLA queda detenido y
  ITHOS le recuerda una vez por día hábil, dentro del horario de atención; cuando responde, el ticket vuelve a estar
  en curso solo, y si pasan cinco días hábiles sin respuesta el técnico asignado recibe el aviso para definir qué
  hacer. Cada aviso por WhatsApp **menciona al técnico asignado**, así cada uno ve lo suyo, incluida la alerta de
  SLA por vencer. Arma una base de conocimiento automática por empresa a partir de los tickets resueltos —que se
  **regenera sola cada semana**, sin que nadie apriete un botón— y admite sumar instructivos en PDF, Word o texto,
  o importar una wiki de Outline, todo desde el alta o el portal.
- **Reportes ITIL 4 automáticos.** KPIs de creados, resueltos y backlog, cumplimiento de SLA, MTTR, y desglose por
  técnico y categoría. Se envían solos el día y la hora elegidos —por ejemplo, todos los viernes a las 18:00— en
  PDF o CSV, o se generan a demanda por período diario, semanal, mensual, histórico o un rango personalizado.
- **Trabajo por técnico.** Cada uno puede preguntar por los tickets que tiene asignados —«¿cómo están los
  míos?»— y ponerlos en espera o posponerlos en lote, y ITHOS lo reconoce por su número de teléfono, sin
  pedirle nombre ni legajo. Filtra siempre por el campo «Asignado a», así nunca toca un ticket en el que la
  persona es sólo observador.
- **Canales.** Recibe y responde en WhatsApp, Telegram, Email, Microsoft Teams, Slack y Matrix/Element. En
  WhatsApp, Telegram, Email y Matrix además ejecuta acciones: leer, cerrar, asignar y posponer un ticket a una
  fecha y hora, reactivándolo solo cuando llega el momento. Los avisos —ticket nuevo, cambios de estado, SLA por
  vencer y reportes— salen por todos los canales que el cliente tenga configurados, además de los parlantes, en
  texto y/o nota de voz según el formato que elija el cliente en WhatsApp y Telegram.
- **Asistente conversacional.** Se le habla por micrófono o se le envía un audio por WhatsApp, y responde por voz
  y por texto. Hay que llamarlo —«Hey ITHOS…», en español o en inglés—: si sólo se lo menciona no interviene,
  así no se mete en la conversación del grupo. Incluye identificación por voz del dueño, con un perfil que se
  afina solo.
- **Multi‑IA con respaldo automático, hasta tres en cadena.** Gemini, Cerebras, Groq, Claude, ChatGPT, Grok,
  DeepSeek en nube o local sin Ollama, Mistral, OpenRouter y Ollama. Usa una sola IA por consulta y, solo cuando
  se queda sin cuota, salta sola a la segunda o a la tercera, sin cortes y sin gastar las otras de más. Avisa al
  cliente por su canal cuando una IA está por agotarse y cuando cambia a la siguiente, para que siempre sepa cómo
  va el consumo.
- **Panel web** tipo consola: alta de empresas, estado en vivo con autorrefresco, métricas, y un portal propio
  por cliente para ver su SLA y sus reportes.
- **Facturación SaaS integrada con MercadoPago.** Suscripción mensual, con el precio en dólares cobrado en pesos
  al dólar BNA. El detalle y los costos están en la sección 6.

---

## 2. Costo por operación, con la cuenta hecha

La IA primaria es Google Gemini 2.5 Flash‑Lite, la más barata y con plan gratuito. Su precio oficial por millón
de tokens es de US$0,10 de entrada y US$0,40 de salida. La fuente está en la sección 9.1.

> Un "token" es un fragmento de texto, aproximadamente tres cuartos de palabra. Se paga por lo que entra —el texto
> y el contexto— y por lo que sale —la respuesta—.

| Operación | Cómo se calcula | Costo |
|---|---|---|
| **1 ticket completo** | La IA interviene unas tres veces —clasificar, responder y hacer el seguimiento—, con cerca de 11.000 tokens de entrada y 700 de salida. `11.000×0,10/1.000.000 = 0,0011` más `700×0,40/1.000.000 = 0,00028` | **≈ US$0,0014** |
| **1 consulta por voz** | La transcripción del audio, unos 320 tokens de costo casi nulo, más la respuesta, cerca de 4.000 tokens de entrada y 300 de salida. `4.000×0,10/1M = 0,0004` más `300×0,40/1M = 0,00012` | **≈ US$0,0005** |
| **1 fichada del portero** | El saludo se dice con **Charon** (voz de la marca) y se **cachea**: la 1ª vez por persona cuesta una fracción de centavo; después se **reproduce el audio cacheado, gratis**. (edge‑tts solo como respaldo si Charon fallara.) | **US$0 en reproducción · ~US$0,0005 la 1ª vez** |

> En términos simples: un ticket cuesta menos de dos milésimas de dólar; una consulta por voz, medio milésimo; y
> el saludo del portero es **prácticamente gratis**: se genera una única vez por persona con Charon (una fracción de
> centavo) y después se reproduce **cacheado, sin costo y al instante**. Las cuentas usan el precio oficial; lo único
> estimado es la cantidad de tokens por operación, que varía algo según el largo del texto.

---

## 3. Estimación por uso y por tamaño de empresa

El costo de IA depende del **volumen de uso** —tickets y consultas por voz—, no de la cantidad de empleados en sí.
Las **fichadas del portero** se dicen con **Charon** (la voz de la marca, de Gemini) y se **cachean**: la primera vez
que se saluda a una persona, ITHOS genera el audio con Charon (una fracción de centavo) y lo **guarda**; a partir de
ahí **reproduce el audio cacheado**, gratis e instantáneo. Como el personal se repite todos los días, el costo de las
fichadas en régimen es prácticamente **US$0** (solo una generación única por persona nueva). Nuestra oficina
(INTELLIHELP) hoy son **7 personas**: es el caso de *PyME chica* de la tabla.

> **Dos rutas de voz (para entender los costos).** Lo que ITHOS **habla por los parlantes** en el lugar —el
> portero y las respuestas habladas— usa **Charon** (la voz de la marca, de Gemini) si está disponible, y
> **edge‑tts** como respaldo. Si el cliente **no usa Gemini**, no hay voz de marca: en ese caso usa **edge‑tts
> siempre** (edge es gratis, así que su voz sale **US$0**). En cambio, las **notas de voz que se envían por
> WhatsApp y los demás canales** usan **edge‑tts** en todos los casos, que es **gratis y rápido**. Por eso mandar
> audios por los canales **no agrega costo**.

Para dimensionar, tomamos escenarios hipotéticos desde una PyME como la nuestra hasta una multinacional. El supuesto
de actividad es razonable para una mesa de ayuda de IT: **~0,15–0,2 tickets por persona por día** y **~2 fichadas por
persona por día** (entrada y salida). Se usan los costos por operación de la sección 2 (ticket ≈ US$0,0014, consulta
por voz ≈ US$0,0005, fichada US$0).

| Tamaño | Personas (aprox.) | Fichadas/día | Tickets/día | Consultas voz/día | Costo IA/día | **Costo IA/mes** |
|---|---:|---:|---:|---:|---:|---:|
| **PyME chica** (nuestra oficina) | 7 | ~14 | 3 | 4 | US$0,006 | **≈ US$0,20** |
| **PyME** | 50 | ~100 | 15 | 10 | US$0,026 | **≈ US$0,80** |
| **Mediana empresa** | 250 | ~500 | 60 | 40 | US$0,104 | **≈ US$3,10** |
| **Gran empresa** | 1.000 | ~2.000 | 200 | 120 | US$0,34 | **≈ US$10** |
| **Multinacional** | 10.000 | ~20.000 | 1.500 | 500 | US$2,35 | **≈ US$70** |

> **Cómo leer la tabla.** Aun una **multinacional de 10.000 personas** con 1.500 tickets por día gasta del orden de
> **US$70 por mes de IA** —centavos por ticket—, porque el modelo Flash‑Lite es barato y las fichadas son prácticamente gratis (Charon cacheado). Una
> PyME como la nuestra gasta **centavos por mes**.

**Consideraciones al escalar (por qué el costo se mantiene bajo):**
- **Cuota gratis vs. paga.** El plan **gratuito** de Gemini alcanza para una PyME. A partir de *mediana empresa*, el
  volumen supera el límite diario gratuito: ahí entra el **respaldo gratis** (Cerebras/Groq) o la **key paga** de
  Gemini Flash‑Lite (que igual cuesta ~US$0,0014 por ticket, ya incluido en la tabla). En todos los casos, centavos.
- **Infraestructura (ver sección 5).** PyME y mediana comparten un **KVM 2** (US$9–15/mes total, repartido entre
  varias empresas). Gran empresa conviene un **KVM 4**; una multinacional, un **KVM 8** o un **VPS dedicado** por
  región. El cerebro es liviano, así que aun así el costo de servidor por empresa es bajo.
- **WhatsApp.** No oficial es **gratis** en cualquier tamaño. El oficial (Meta) solo cobra las notificaciones fuera
  de la ventana de 24 h (ver sección 5): a mayor volumen, más alertas, pero sigue siendo del orden de centavos por
  mensaje y solo si se usa el canal oficial.

---

## 4. Comparativa de IAs

Por si en algún cliente se prefiere otro motor en lugar de Gemini. Se usa el mismo cálculo por ticket —11.000
tokens de entrada y 700 de salida— con el precio oficial de cada proveedor.

| IA | Precio API, US$/1M entrada / salida | Costo por ticket | Fuente oficial |
|---|---|---|---|
| **Gemini 2.5 Flash‑Lite** ✅ | 0,10 / 0,40 | **US$0,0014** | [ai.google.dev/pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Gemini 2.5 Flash | 0,30 / 2,50 | US$0,005 | [ai.google.dev/pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Cerebras y Groq, Llama | Gratis, plan free | **US$0** | [cerebras.ai](https://www.cerebras.ai/) · [groq.com](https://groq.com/pricing) |
| DeepSeek chat | ~0,27 / ~1,10 | ~US$0,004 | [api-docs.deepseek.com](https://api-docs.deepseek.com/quick_start/pricing) |
| ChatGPT GPT‑4o | ~2,50 / ~10 | ~US$0,035 | [openai.com/api/pricing](https://openai.com/api/pricing) |
| Claude Sonnet 4.5 | ~3 / ~15 | ~US$0,044 | [claude.com/pricing](https://claude.com/pricing) |
| Local o DeepSeek local | Sin costo de API | **US$0**, requiere PC o GPU propia | — |

> **Recomendación.** Gemini Flash‑Lite como primaria, casi gratuita, con Cerebras o Groq como respaldo sin cargo,
> y opcionalmente DeepSeek como alternativa paga muy económica. Aun cambiando de motor, el costo sigue siendo de
> centavos. Los precios marcados con "~" conviene reconfirmarlos en el link; los de Gemini y la comisión de
> MercadoPago fueron verificados contra la fuente oficial al redactar este informe.

---

## 5. Infraestructura

### Servidor VPS de Hostinger (lo hostea INTELLIHELP)

El **Gestor** (el cerebro) lo **hosteamos nosotros, INTELLIHELP**: corre en un VPS que atiende a **toda la flota de
agentes** de todos los clientes. El **cliente solo instala el Agente** (liviano) en una PC que ya tiene; **no
hostea ni paga servidor, y no tiene acceso al Gestor**. Un mismo KVM sirve a muchas empresas y se agranda a medida
que crece la flota (ver sección 7‑B). Estos son los precios oficiales de Hostinger, según la sección 9.2.

| Plan | Especificaciones | Precio promocional, contrato 2 años | Precio de renovación |
|---|---|---|---|
| KVM 1 | 1 vCPU · 4 GB · 50 GB NVMe | US$6,49/mes | US$11,99/mes |
| **KVM 2**, recomendado | 2 vCPU · 8 GB · 100 GB NVMe | **US$8,99/mes** | **US$14,99/mes** |
| KVM 4 | 4 vCPU · 16 GB · 200 GB NVMe | US$12,99/mes | US$28,99/mes |
| KVM 8 | 8 vCPU · 32 GB · 400 GB NVMe | US$25,99/mes | US$49,99/mes |

> El precio bajo es promocional pagando dos años por adelantado; la renovación cuesta más, según la columna
> derecha. Un KVM 2 alcanza para varias empresas, ya que el cerebro es liviano. El cifrado HTTPS/WSS va sin
> costo con Let's Encrypt, ya preparado mediante Caddy.

### WhatsApp

Hay dos formas de usar WhatsApp, y el costo cambia mucho entre una y otra.

**No oficial, número propio a un grupo. Gratis.** Es lo que usamos hoy, sin costo por mensaje.

**Oficial, API de Meta. De pago, pero muy económica para nuestro uso.** Desde el 1 de julio de 2025, Meta cobra
por mensaje de plantilla entregado, no por conversación. Las categorías son marketing, utility y authentication.
Para ITHOS aplica lo siguiente:

- Los mensajes que envía ITHOS son notificaciones de utilidad, categoría utility.
- Son gratis cuando se envían dentro de la ventana de atención de 24 horas, es decir en respuesta a un mensaje del
  usuario. También son gratis todas las conversaciones de servicio iniciadas por el usuario.
- Fuera de esa ventana, una notificación utility cuesta en Argentina alrededor de US$0,0072 por mensaje. Un
  mensaje de marketing cuesta alrededor de US$0,0265, pero ITHOS no envía marketing.

Ejemplo: si ITHOS envía 15 alertas de utilidad por día fuera de la ventana de atención, son 15 × 0,0072 =
US$0,108 por día, es decir cerca de US$3,24 por mes. Las que caen dentro de la ventana de atención son gratis, y
el costo baja aún más.

> Los valores por país están en el rate card oficial de Meta, que se consulta eligiendo el mercado y la moneda; la
> referencia está en la sección 9.7. La API oficial solo conviene si un cliente exige el número verificado; para
> uso interno, el no oficial sale $0.

---

## 6. Facturación SaaS con MercadoPago: costos y comisión

ITHOS cobra la suscripción con MercadoPago Suscripciones, mediante la API preapproval, que hace el cobro mensual
automático. Documentación oficial: [Suscripciones](https://www.mercadopago.com.ar/developers/es/docs/subscriptions/landing).

**Cómo funciona el precio.**
1. Se define el precio neto en dólares, es decir lo que se quiere recibir, por ejemplo US$20.
2. ITHOS lo convierte a pesos al dólar oficial BNA del día, tomado en vivo de
   [dolarapi.com](https://dolarapi.com/v1/dolares/oficial).
3. La comisión de MercadoPago se suma al precio mediante un gross‑up, para que, después de que MercadoPago
   retiene su parte, quede el neto deseado. La fórmula es: bruto = neto / (1 − comisión%). Por ejemplo, con un
   neto de US$20 y una comisión de 6,29%, el bruto es US$21,34; tras la comisión, quedan los US$20. Al dólar BNA
   de US$1.510, se cobran $32.227.

**Email de facturación.** Se toma del email de contacto que el cliente carga en el alta, de modo que siempre está
disponible para facturar. Además, tras el pago, MercadoPago confirma el email real del pagador y ITHOS lo guarda,
como dato oficial de quién pagó.

**Comisión real de nuestra cuenta**, tomada de MercadoPago → Costos y cuotas → Link de pago, según el plazo de
acreditación del dinero:

| Recibís el dinero | Comisión, Link de pago |
|---|---|
| **Al instante** | **6,29%** |
| En 10 días | 4,39% |
| En 18 días | 3,39% |
| En 35 días | 1,49% |

- No incluye IVA ni retenciones, que se suman aparte, según lo aclara MercadoPago.
- La comisión no se puede evitar, pero se reduce eligiendo cobrar a más días: pasa de 6,29% al instante a 1,49% a
  35 días. El plazo se elige en MercadoPago → Costos y cuotas.
- El porcentaje puede variar por provincia, impuestos y medio de pago; el número exacto y actual de la cuenta
  está siempre en MercadoPago → Costos y cuotas o en el Simulador de costos. Por eso el campo de comisión del
  panel es configurable: hoy está en 6,29% al instante, que es la tarifa real de la cuenta.
- Fuentes oficiales: [¿Cuánto cuesta recibir pagos con Checkout?](https://www.mercadopago.com.ar/ayuda/33399) ·
  [Comisiones y cargos](https://www.mercadopago.com.ar/ayuda/26748) ·
  [Costos por cobro](https://www.mercadopago.com.ar/ayuda/220).

**Transparencia con el cliente.** El panel muestra el desglose: precio del plan más comisión de procesamiento
igual a total. Se recomienda itemizarlo en la propuesta o factura del cliente, del estilo "Plan US$20, comisión
de procesamiento del X%: US$Y, Total US$Z al dólar BNA". Así el cliente entiende por qué el total es mayor.

**No hace falta URL pública, tampoco en producción.** El pago se realiza en la página de MercadoPago, no en
nuestro servidor, y el estado se consulta a la API de MercadoPago con el botón Consultar estado. Por eso el panel
de facturación es simple: solo el Access Token, más precio, comisión y email. Cobrar una suscripción no requiere
dominio ni configuración adicional. Esto está confirmado por dos vías:

- **Documentación oficial.** Para crear la suscripción preapproval sin plan, los campos requeridos son
  payer_email, reason y auto_recurring. No se exige una URL pública del comercio ni un webhook; la notificación
  es opcional. Referencias:
  [Crear suscripción](https://www.mercadopago.com.ar/developers/es/reference/subscriptions/_preapproval/post) ·
  [Webhooks](https://www.mercadopago.com.ar/developers/es/docs/your-integrations/notifications/webhooks).
- **Test real.** La suscripción quedó autorizada sin ninguna URL pública configurada.

**Webhook, opcional.** MercadoPago puede avisar por webhook cuando entra un pago, pero no es necesario: ITHOS
consulta el estado a demanda con Consultar estado, y la suscripción se cobra sola cada mes de todos modos, ya que
lo hace MercadoPago. El endpoint de webhook queda disponible por si en el futuro se quiere usar con un dominio,
pero no requiere configurarse.

**Para el test en sandbox se usan dos usuarios de prueba.** MercadoPago exige que el cobrador y el pagador sean
ambos de prueba, de modo que se usa el Access Token de un vendedor de prueba junto con un comprador de prueba que
paga con una tarjeta de prueba a nombre de APRO. En producción no hace falta nada de eso: es la cuenta real y el
cliente real.

> **Cambiar de prueba a producción** consiste en reemplazar el token de prueba por el Access Token real de la
> cuenta en el panel; no se toca código. La cuenta dueña del token es la que recibe el dinero.

### 6.1 Evidencia del test real, sandbox 07/2026

Se realizó el circuito completo con usuarios de prueba de MercadoPago. Quedó registrado así, y es verificable en
la cuenta de MercadoPago:

- **Suscripción autorizada.** MercadoPago mostró "¡Listo! Ya te suscribiste a ITHOS — INTELLIHELP S.A.
  (Mensual)", con estado authorized y próximo cobro mensual el 6 de agosto.
- **El comprador pagó el monto correcto.** Su saldo pasó de $50.000 a $17.773, es decir pagó $32.227, que
  equivalen a los US$20 netos más el 6,29% de comisión, al dólar BNA.
- **Al vendedor le quedó el neto.** $30.905 a liquidar, es decir los $32.227 menos la comisión de MercadoPago,
  exactamente lo buscado con el gross‑up.
- **Comisión real de la cuenta.** MercadoPago → Costos y cuotas → Link de pago da 6,29% al instante, y baja a
  4,39%, 3,39% y 1,49% cobrando a más días, sin IVA.
- Todo esto se logró sin ninguna URL pública configurada.

---

## 7. Costo total por mes: lo que consume cada empresa y la infraestructura de INTELLIHELP

Hay que separar **dos cosas**, porque el modelo es **Gestor + Agente**: el **Gestor** (el cerebro) **lo hosteamos
nosotros, INTELLIHELP**, en un VPS; el **cliente solo instala el Agente** (liviano) en una PC que ya tiene. **El
cliente NUNCA hostea el Gestor ni paga un servidor** — no tiene acceso a él, solo a su portal. Su único costo de
operación es la IA que consume.

**A) Lo que consume cada empresa cliente (su costo de operación):** IA según su volumen (sección 3) + WhatsApp no
oficial (US$0). El agente corre en una PC existente del cliente; **sin servidor**.

| Tamaño de la empresa | Personas | IA/mes | WhatsApp | **Costo de la empresa/mes** |
|---|---:|---:|---:|---:|
| **PyME chica** (nuestra oficina) | 7 | ~US$0,20 | US$0 | **~US$0,20** |
| **PyME** | 50 | ~US$0,80 | US$0 | **~US$0,80** |
| **Mediana empresa** | 250 | ~US$3 | US$0 | **~US$3** |
| **Gran empresa** | 1.000 | ~US$10 | US$0 | **~US$10** |
| **Multinacional** | 10.000 | ~US$70 | US$0 | **~US$70** |

**B) Infraestructura de INTELLIHELP (el Gestor, lo hosteamos nosotros):** un VPS KVM que corre el Gestor para
**toda la flota de agentes**. Es un costo **nuestro**, único y compartido entre todos los clientes, que **se
agranda a medida que crece la flota** (más empresas y agentes conectados) — no es un servidor por empresa. Como el
Gestor es **liviano** (solo razona y orquesta, no toca hardware), un KVM chico aguanta muchas empresas.

| Flota (empresas/agentes conectados) | KVM sugerido | Costo/mes (de INTELLIHELP) |
|---|---|---:|
| Arranque, hasta ~10–20 empresas | **KVM 2** (2 vCPU · 8 GB) | US$9–15 |
| Crecimiento, hasta ~50–80 | **KVM 4** (4 vCPU · 16 GB) | US$13–29 |
| Escala, cientos de empresas | **KVM 8** (8 vCPU · 32 GB) o varios/dedicados | US$26–50+ |

> **Lectura.** El **cliente** paga solo su IA: de **centavos** (PyME) a **~US$70/mes** (multinacional), y **US$0**
> de servidor. La **inversión en el servidor del Gestor es de INTELLIHELP**, se reparte entre todos los clientes y
> se upgradea al crecer la flota; por eso el costo de servidor **por empresa es marginal**. El cliente **no puede
> ni necesita** hostear el Gestor: instala el agente y listo.

**Ejemplo real, INTELLIHELP en uso interno (7 personas):** menos de **US$1 por mes de IA** y US$0 de WhatsApp. El
Gestor corre en nuestra infraestructura (una PC de la oficina en la demo, o el KVM 2 en producción, ~US$9–15/mes)
y **el mismo servidor hostea a todos los clientes** que se vayan sumando.

> **Seguridad de acceso: incluida, sin costo.** El control de acceso al Gestor (login del panel superadmin solo
> para INTELLIHELP + enlace de alta de un solo uso por cliente) es parte del código, no agrega costo mensual.

### 7.1 Costo futuro (Fase 2): firma de código del agente

Es un costo **de INTELLIHELP**, único y compartido por todos los clientes (no por empresa), que **todavía no se
incurre**: aplica recién cuando empaquetemos el agente como ejecutable con actualización automática por red.

**Qué es y por qué se paga.** Un **certificado de firma de código** (code signing) de una Autoridad Certificante.
Con él se **firma** el ejecutable del agente y cada actualización, de modo que Windows verifique que vienen de
INTELLIHELP y no fueron alterados. Sin firma, al instalar aparece el aviso de **SmartScreen** "aplicación no
reconocida" y algunos antivirus dan **falsos positivos**; firmando, ese aviso se reduce y el instalador genera
**reputación** con el editor. *(Microsoft Learn — SmartScreen reputation, ver sección 9.8.)*

**Cuánto cuesta, con la cuenta.** Un certificado **OV** (validación de organización) cuesta según la CA:

| Autoridad certificante (CA) | Tipo | Precio de lista | Fuente |
|---|---|---|---|
| **Sectigo** | OV code signing | **~US$225 / año** | sección 9.8 |
| **DigiCert** | OV code signing | **~US$385–409 / año** | sección 9.8 |

Es **por año** y **uno solo** firma el agente de **todos** los clientes, así que el costo por empresa es marginal.
Nota 2026: el CA/Browser Forum bajó la validez máxima de estos certificados a ~15 meses (sección 9.8).

**Cómo se hace.** Se compra el certificado a la CA, se **valida la organización** (INTELLIHELP S.A.), y con la
herramienta oficial de Windows (`signtool`) se firma el `.exe`/instalador y cada update antes de publicarlos.
*(Microsoft Learn — Code signing options, sección 9.8.)*

> La comisión de MercadoPago, detallada en la sección 6, no es un costo de operar ITHOS: aplica solo cuando se
> cobra la suscripción a un cliente, y se traslada al precio mediante el gross‑up, de modo que no afecta el margen.

---

## 8. Recomendación

1. **IA.** Gemini Flash‑Lite como primaria, con facturación por uso activada, ya que el plan gratuito de 20 usos
   por día no alcanza para producción; el límite es la cuota, no el costo. Como respaldo sin cargo, Cerebras o Groq.
2. **WhatsApp** no oficial, gratuito, para uso interno; el oficial solo si el cliente lo exige.
3. **Servidor.** Una PC para la demo y el arranque; un KVM 2, de unos US$9 a US$15 por mes, para producción 24/7,
   repartido entre clientes.
4. **Cobro.** MercadoPago con la comisión configurada según el Simulador de la cuenta y el gross‑up activado, para
   que el neto sea exacto, y con el desglose visible para transparencia con el cliente.

> **Resumen para decidir.** Operar ITHOS cuesta centavos por empresa al mes, verificable con las cuentas de la
> sección 2 y los precios oficiales. Lo que resta definir es el precio de venta de la suscripción y cargar la
> comisión real de MercadoPago para no perder margen. La inversión en infraestructura es mínima frente a lo que
> automatiza.

---

## 9. Fuentes oficiales, guía de verificación

Para cada dato: el enlace, la sección donde está y el texto exacto a buscar con Ctrl+F.

### 9.1 Gemini API, precio de la IA
- **Link:** https://ai.google.dev/gemini-api/docs/pricing
- **Dónde:** bajar hasta la tarjeta o tabla titulada "Gemini 2.5 Flash‑Lite".
- **Qué buscar:** `Flash-Lite`, y dentro "Input price" en $0.10 y "Output price" en $0.40, por millón de tokens.
  A modo de comparación, "Gemini 2.5 Flash" indica Input $0.30 y Output $2.50.
- **Se usa en** las secciones 2 y 4.

### 9.2 Hostinger, precio del servidor VPS
- **Link:** https://www.hostinger.com/vps-hosting
- **Dónde:** la tabla de planes VPS, KVM 1 a KVM 8.
- **Qué buscar:** `KVM 2`, con 2 vCPU, 8 GB y 100 GB NVMe. El precio grande es el promocional; debajo, la leyenda
  "Renews at $14.99/mo" es el precio de renovación. Confirmar promoción de $8.99/mes y renovación de $14.99/mes.
- **Se usa en** la sección 5.

### 9.3 MercadoPago, comisión por cobro
- **Links:** https://www.mercadopago.com.ar/ayuda/33399 · https://www.mercadopago.com.ar/ayuda/26748 · https://www.mercadopago.com.ar/ayuda/220
- **Qué buscar:** la frase "El costo por cobro varía según el plazo de acreditación" y la tabla de porcentajes por
  plazo, al instante o en varios días. Se confirma que a menor plazo, mayor comisión, y que lleva IVA.
- **El número exacto de la cuenta,** el que va en el campo de comisión del panel, está en MercadoPago → Costos y
  cuotas o en el Simulador de costos, dentro del panel, no en la ayuda pública.
- **Se usa en** la sección 6.

### 9.4 MercadoPago, Suscripciones y Webhook
- **Suscripciones, preapproval:** https://www.mercadopago.com.ar/developers/es/docs/subscriptions/landing —
  buscar `preapproval` y `auto_recurring`, el cobro mensual recurrente.
- **Webhooks:** https://www.mercadopago.com.ar/developers/es/docs/your-integrations/notifications/webhooks —
  buscar `x-signature` y `HMAC`, la firma que ITHOS valida, y los tópicos `subscription_preapproval` y
  `subscription_authorized_payment`.

### 9.5 Dólar oficial, conversión de dólares a pesos
- **Link en vivo:** https://dolarapi.com/v1/dolares/oficial
- **Qué buscar:** el campo `venta` del JSON, que es el valor que usa ITHOS para pasar dólares a pesos. Es el dólar
  oficial del Banco Nación.

### 9.6 Otras IAs de respaldo, para reconfirmar los precios marcados con "~"
- **DeepSeek:** https://api-docs.deepseek.com/quick_start/pricing — buscar `deepseek-chat`, Input y Output por millón.
- **OpenAI, GPT‑4o:** https://openai.com/api/pricing — buscar `GPT-4o`, precio Input y Output por millón.
- **Claude, Sonnet 4.5:** https://claude.com/pricing — sección API, buscar `Sonnet`, Input y Output por millón.
- **Cerebras:** https://www.cerebras.ai/ · **Groq:** https://groq.com/pricing — buscar `free`, tienen plan gratuito.

### 9.7 WhatsApp oficial, solo si el cliente lo exige
- **Link:** https://developers.facebook.com/docs/whatsapp/pricing/ — el modelo es por mensaje desde el 1 de julio
  de 2025. Buscar las categorías marketing, utility y authentication, y el rate card por país. Para Argentina, la
  categoría utility ronda US$0,0072 y la de marketing US$0,0265 por mensaje; los mensajes de servicio y las
  plantillas utility dentro de la ventana de 24 horas son gratis. El número exacto y actual está en el rate card
  oficial de Meta, que se elige por mercado y moneda.

### 9.8 Firma de código del agente (costo futuro, Fase 2 — sección 7.1)
- **Por qué se firma (Microsoft):** https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation
  — buscar `Publisher reputation` y `digitally sign your code`. Explica que firmar reduce el aviso de SmartScreen
  "aplicación no reconocida" y construye reputación del editor.
- **Cómo se firma (Microsoft):** https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
  — buscar `signtool` y `Certificate Authority`, el procedimiento para firmar el ejecutable/instalador.
- **Precio, CA oficiales:** Sectigo https://www.sectigo.com/ssl-certificates-tls/code-signing (OV code signing,
  ~US$225/año) · DigiCert https://www.digicert.com/signing/code-signing-certificates (OV, ~US$385–409/año). Buscar
  `OV` / `Organization Validation` y el precio anual.
- **Validez 2026 (CA/Browser Forum):** https://cabforum.org/working-groups/code-signing/ — la validez máxima de los
  certificados de firma bajó a ~460 días (≈15 meses) desde marzo de 2026.

> **Nota de veracidad.** Los precios de Gemini, punto 9.1, y de Hostinger, punto 9.2, fueron verificados contra la
> fuente oficial al redactar, en 07/2026. Los marcados con "~", puntos 9.6 y 9.8, pueden cambiar: conviene abrir el
> link, buscar el texto indicado y confirmar el número. Ningún costo está inventado: cada uno tiene su cuenta en la
> sección 2 (o su detalle en la 7.1) y su fuente en esta sección.

---