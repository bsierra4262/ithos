# ITHOS — Parte 1: alcance y costos operativos
**Preparado para:** Nicolás Baldelli · INTELLIHELP S.A. · Actualizado 11/2026

> **Qué es ITHOS hoy.** Una herramienta interna de INTELLIHELP, no un producto a la venta. Atiende nuestra mesa de
> ayuda y nuestra oficina: no tiene clientes externos, suscripciones ni cobros. Este informe muestra qué hace y
> cuánto nos cuesta operarla.

---

## 1. ¿Qué hace ITHOS hoy?

Alcance actual, funcionando en producción. ITHOS tiene dos piezas: un **Gestor** (el cerebro), que corre en
nuestro servidor VPS, y un **agente** liviano instalado en una PC de la oficina, que maneja los parlantes, el
micrófono y el control de acceso. Se instala en Windows, Linux o Mac.

- **Portero por voz.** Cuando alguien ficha en el control de acceso IVMS, ITHOS lo saluda por los parlantes con
  voz propia, Charon, a una velocidad cómoda y pareja. El saludo es coherente con la hora —buenos días, buenas
  tardes o buenas noches—, cambia de fórmula día a día para no sonar repetitivo y no vuelve a saludar a la misma
  persona en la jornada. Cada terminal se configura como entrada, salida o sala, con su propio saludo.
- **Mesa de ayuda con IA sobre GLPI.** Detecta los tickets nuevos y los clasifica, prioriza, asigna y responde.
  Pide datos solo si faltan de verdad; si el problema sigue, pide la evidencia que necesita el técnico —foto o
  video, terminal, lado del molinete, fecha y hora— y deja el ticket en espera. No pisa la categoría ni la
  asignación que hizo un técnico a mano. Antes de aprobar una solución, GLPI muestra un cartel de confirmación.
- **Ninguna espera queda olvidada.** Mientras el ticket depende del solicitante —porque falta un dato o porque
  tiene que confirmar un trabajo— el SLA queda detenido y ITHOS le recuerda una vez por día hábil, dentro del
  horario de atención. Cuando responde, el ticket vuelve a estar en curso solo; si pasan cinco días hábiles sin
  respuesta, el técnico asignado recibe el aviso para definir qué hacer.
- **Antecedentes.** Ante un ticket nuevo, ITHOS busca los casos parecidos ya resueltos y le acerca al técnico
  cómo se solucionaron.
- **Wiki del equipo (Outline).** ITHOS lee la wiki para su base de conocimiento y, cuando se cierra un ticket,
  publica el procedimiento: el paso a paso literal que dejó el técnico, con sus capturas, en el documento del
  cliente que corresponda. Si el procedimiento ya existe, le suma el caso en vez de duplicarlo. Nunca lee ni
  escribe la colección de credenciales.
- **Tareas del equipo (Planka).** Integrado con el tablero de tareas de INTELLIHELP: crea, consulta y mueve
  tareas, y pasa las vencidas al día siguiente.
- **Reportes ITIL 4 automáticos.** Tickets creados, resueltos y pendientes, cumplimiento de SLA, MTTR y desglose
  por técnico y categoría. Se envían solos el día y la hora elegidos, en PDF o CSV, o se piden por período diario,
  semanal, mensual o por un rango a elección.
- **Trabajo por técnico.** Cada técnico puede preguntar por sus tickets —«¿cómo están los míos?»— y ponerlos en
  espera o posponerlos en lote. ITHOS lo reconoce por su número de teléfono y filtra siempre por «Asignado a», así
  nunca toca un ticket en el que la persona es solo observador.
- **WhatsApp.** Trabaja con cuatro grupos, cada uno con su función: consultas, tickets y alertas de SLA, tareas de
  Planka, y avisos del sistema. Recibe y responde texto y audios, y ejecuta acciones: leer, cerrar, asignar y
  posponer un ticket. Cada aviso menciona al técnico asignado.
- **Asistente conversacional.** Se le habla por micrófono o se le manda un audio por WhatsApp, y responde por voz
  y por texto. Hay que llamarlo —«Hey ITHOS…»—: si solo se lo nombra no interviene. Las órdenes de administración
  por micrófono exigen la voz del dueño y una frase clave.
- **Multi‑IA con respaldo automático.** Hoy usa la cadena Gemini → Cerebras → Groq, las tres en su plan gratuito.
  Usa una sola IA por consulta y salta a la siguiente solo cuando se agota la cuota de la anterior. Soporta además
  Claude, ChatGPT, Grok, DeepSeek, Mistral, OpenRouter y una IA local con Ollama, por si alguna vez conviene.
- **Panel web.** Estado en vivo de los canales, el micrófono y el control de acceso, métricas, SLA y reportes.

---

## 2. Costo por operación, con la cuenta hecha

Hoy las tres IA de la cadena se usan en su **plan gratuito**, así que el costo real de IA es **US$0**. Igual dejamos
la cuenta con el precio de pago de Gemini 2.5 Flash‑Lite, la más barata, para saber cuánto costaría si algún día
el plan gratuito no alcanzara: US$0,10 por millón de tokens de entrada y US$0,40 de salida (fuente en la sección 6.1).

> Un "token" es un fragmento de texto, aproximadamente tres cuartos de palabra. Se paga por lo que entra —el texto
> y el contexto— y por lo que sale —la respuesta—.

| Operación | Cómo se calcula | Costo con plan pago | Costo hoy |
|---|---|---|---|
| **1 ticket completo** | La IA interviene unas tres veces —clasificar, responder y seguir—, con cerca de 11.000 tokens de entrada y 700 de salida. `11.000×0,10/1M = 0,0011` más `700×0,40/1M = 0,00028` | ≈ US$0,0014 | **US$0** |
| **1 consulta por voz** | Cerca de 4.000 tokens de entrada y 300 de salida. `4.000×0,10/1M = 0,0004` más `300×0,40/1M = 0,00012` | ≈ US$0,0005 | **US$0** |
| **1 fichada del portero** | El saludo se genera con Charon una sola vez por persona y se guarda; después se reproduce el audio guardado, sin costo y al instante. | ~US$0,0005 la 1ª vez | **US$0** |

> **Por qué alcanza el plan gratuito.** La cuota gratuita de Gemini es por modelo y por día; cuando se agota, la
> consulta pasa a Cerebras y después a Groq, que también son gratuitas. Para el volumen de nuestra mesa de ayuda y
> una oficina de siete personas, la cadena no se queda sin cuota. Si alguna vez pasara, con el plan pago un mes
> entero de nuestro uso costaría menos de US$1.

Las notas de voz que ITHOS manda por WhatsApp usan edge‑tts, que es gratuito, así que mandar audios tampoco
agrega costo.

---

## 3. Comparativa de IAs

Por si alguna vez conviene cambiar de motor. Se usa el mismo cálculo por ticket —11.000 tokens de entrada y 700 de
salida— con el precio oficial de cada proveedor.

| IA | Precio API, US$/1M entrada / salida | Costo por ticket | Fuente oficial |
|---|---|---|---|
| **Gemini 2.5 Flash‑Lite** ✅ | Plan gratuito · pago 0,10 / 0,40 | **US$0** · pago US$0,0014 | [ai.google.dev/pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| **Cerebras y Groq** ✅ | Plan gratuito | **US$0** | [cerebras.ai](https://www.cerebras.ai/) · [groq.com](https://groq.com/pricing) |
| Gemini 2.5 Flash | 0,30 / 2,50 | US$0,005 | [ai.google.dev/pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| DeepSeek chat | ~0,27 / ~1,10 | ~US$0,004 | [api-docs.deepseek.com](https://api-docs.deepseek.com/quick_start/pricing) |
| ChatGPT GPT‑4o | ~2,50 / ~10 | ~US$0,035 | [openai.com/api/pricing](https://openai.com/api/pricing) |
| Claude Sonnet 4.5 | ~3 / ~15 | ~US$0,044 | [claude.com/pricing](https://claude.com/pricing) |
| IA local con Ollama | Sin costo de API | **US$0**, requiere PC o GPU propia | — |

> **Recomendación.** Seguir con la cadena gratuita Gemini → Cerebras → Groq. Los precios marcados con "~"
> conviene reconfirmarlos en el link antes de usarlos.

---

## 4. Infraestructura

### Servidor VPS de Hostinger

El Gestor corre en un VPS **KVM 2** de Hostinger, en `ithos.intellihelp.tech`, con HTTPS sin costo por Let's
Encrypt. El agente corre en una PC que la oficina ya tiene, así que no suma servidor. Precios oficiales de
Hostinger, según la sección 6.2:

| Plan | Especificaciones | Precio promocional, contrato 2 años | Precio de renovación |
|---|---|---|---|
| KVM 1 | 1 vCPU · 4 GB · 50 GB NVMe | US$6,49/mes | US$11,99/mes |
| **KVM 2**, el que usamos | 2 vCPU · 8 GB · 100 GB NVMe | **US$8,99/mes** | **US$14,99/mes** |
| KVM 4 | 4 vCPU · 16 GB · 200 GB NVMe | US$12,99/mes | US$28,99/mes |

> El precio bajo es promocional pagando dos años por adelantado; la renovación cuesta más. El KVM 2 alcanza de
> sobra para ITHOS.

### WhatsApp

Usamos WhatsApp con un número propio, sin la API de Meta: **no tiene costo por mensaje**.

### Firma de código del agente (opcional)

Al instalar el agente, Windows puede mostrar el aviso de SmartScreen "aplicación no reconocida", porque el
instalador no está firmado. Para uso interno no es un problema: se confirma una vez y listo. Si algún día molesta,
un certificado de firma de código OV cuesta alrededor de US$225 por año en Sectigo, o entre US$385 y US$409 en
DigiCert (fuentes en la sección 6.3). Hoy no hace falta.

---

## 5. Costo total por mes

| Concepto | Costo por mes |
|---|---:|
| IA (Gemini, Cerebras y Groq en plan gratuito) | US$0 |
| WhatsApp (número propio) | US$0 |
| Voz del portero (Charon guardado) y notas de voz (edge‑tts) | US$0 |
| Agente (PC que ya tiene la oficina) | US$0 |
| Servidor VPS KVM 2 | US$8,99 a US$14,99 |
| **Total** | **≈ US$9 a US$15** |

> **Resumen.** Operar ITHOS le cuesta a INTELLIHELP solo el servidor, entre US$9 y US$15 por mes según el período
> del contrato de Hostinger. Todo lo demás corre en planes gratuitos o en equipos que ya tenemos.

---

## 6. Fuentes oficiales, guía de verificación

Para cada dato: el enlace, la sección donde está y el texto exacto a buscar con Ctrl+F.

### 6.1 Gemini API, precio de la IA
- **Link:** https://ai.google.dev/gemini-api/docs/pricing
- **Dónde:** la tarjeta o tabla titulada "Gemini 2.5 Flash‑Lite".
- **Qué buscar:** `Free tier`, y en el plan pago "Input price" en $0.10 y "Output price" en $0.40, por millón de
  tokens. A modo de comparación, "Gemini 2.5 Flash" indica Input $0.30 y Output $2.50.
- **Se usa en** las secciones 2 y 3.

### 6.2 Hostinger, precio del servidor VPS
- **Link:** https://www.hostinger.com/vps-hosting
- **Dónde:** la tabla de planes VPS, KVM 1 a KVM 8.
- **Qué buscar:** `KVM 2`, con 2 vCPU, 8 GB y 100 GB NVMe. El precio grande es el promocional; debajo, la leyenda
  "Renews at $14.99/mo" es el de renovación.
- **Se usa en** las secciones 4 y 5.

### 6.3 Otras IAs y firma de código, para reconfirmar los precios marcados con "~"
- **DeepSeek:** https://api-docs.deepseek.com/quick_start/pricing — buscar `deepseek-chat`.
- **OpenAI, GPT‑4o:** https://openai.com/api/pricing — buscar `GPT-4o`.
- **Claude, Sonnet 4.5:** https://claude.com/pricing — sección API, buscar `Sonnet`.
- **Cerebras:** https://www.cerebras.ai/ · **Groq:** https://groq.com/pricing — buscar `free`.
- **Firma de código:** Sectigo https://www.sectigo.com/ssl-certificates-tls/code-signing · DigiCert
  https://www.digicert.com/signing/code-signing-certificates — buscar `OV` y el precio anual. Por qué se firma:
  https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation

> **Nota de veracidad.** Los precios de Gemini y de Hostinger se verificaron contra la fuente oficial en 07/2026.
> Los marcados con "~" pueden cambiar: conviene abrir el link y confirmar el número. Ningún costo está inventado.
