# ITHOS — Parte 2: valor del desarrollo y propuesta de compensación
**Preparado para:** Nicolás Baldelli · INTELLIHELP S.A. · Actualizado 07/2026

> **De qué trata este informe.** Es la segunda de dos partes, complementaria al informe de alcance y costos
> operativos. Aquel muestra qué hace ITHOS y cuánto cuesta operarlo; este presenta el **valor del desarrollo**, la
> **propuesta de compensación** y las **opciones de propiedad**. Se comparte una vez definida la implementación de
> la Parte 1.

---

## 1. Esfuerzo y valor del desarrollo, base para la comisión

ITHOS es un desarrollo que realicé para INTELLIHELP: la arquitectura y toda la implementación. No es un script,
sino una plataforma multiempresa —central más agentes— con integraciones reales, IA, voz, cobros y panel, probada
a nivel de producción. A continuación, el esfuerzo de ingeniería que representa el producto, por componente. Sirve
para dimensionar el valor creado y, sobre esa base, la comisión.

| Componente | Horas |
|---|---:|
| Arquitectura multiempresa: central, agentes, WebSocket, protocolo y registro por API key | 42 |
| Capa de IA enchufable: 10 proveedores, cadena con respaldo, cuota y transcripción | 52 |
| Motor de voz: Charon en streaming con WSOLA, caché, edge‑tts y diccionario de pronunciación | 48 |
| Captura y filtrado de voz: micrófono dinámico, VAD Silero y webrtc, identificación por voz | 34 |
| Sistemas de tickets: GLPI completo, más Zendesk, Jira, Freshservice y osTicket contra API oficiales | 68 |
| Triage con IA, ciclo de vida y acciones: cerrar, asignar, posponer y responder | 46 |
| Control de acceso: cinco integradores, IVMS, HikCentral, BioStar 2, ZKTeco y Honeywell | 54 |
| Canales conversacionales: WhatsApp oficial y no oficial, Telegram, Email, Teams, Slack y Matrix | 50 |
| Asistente: memoria por cliente, base de conocimiento automática con Outline, y autorización | 44 |
| Reportes ITIL 4: KPIs, SLA, MTTR, PDF y CSV, programados y con rango personalizado | 30 |
| Proactivo: aviso de SLA por vencer y anomalías de horario | 20 |
| Facturación MercadoPago: suscripciones, gross‑up de comisión, dólar BNA y webhook con firma | 34 |
| Panel web: diseño HUD, superadmin, portal, auto‑alta, UX, responsive y multiplataforma | 58 |
| Instaladores multi‑SO para Windows, Linux y Mac, más Docker y Caddy con HTTPS/WSS | 28 |
| QA y testing: cinco baterías de producción, exhaustiva, código, nivel 4 y requerimientos, con seguridad, concurrencia y escala | 48 |
| Integración, ajustes finos, documentación y puesta a punto | 40 |
| **TOTAL** | **≈ 696 h** |

- **Cronograma.** Desarrollado por fases —arquitectura, integraciones, voz y canales, IA y asistente, facturación,
  panel y UX, y finalmente QA y hardening— a lo largo de varios meses de trabajo dedicado.
- **Valor de mercado del desarrollo, costo de reemplazo.** Contratar este desarrollo a un tercero a tarifa de
  mercado, entre US$40 y US$60 por hora, le habría costado a INTELLIHELP entre US$28.000 y US$42.000. Es el costo
  de mercado de construir este producto, es decir el valor que aporté.
- **Base de la comisión.** Por el desarrollo completo de este producto corresponde una comisión proporcional al
  valor creado y a los ingresos recurrentes que genere para INTELLIHELP. El producto es replicable por cliente,
  con un costo marginal de centavos por mes según el informe de costos operativos, de modo que ese margen del
  negocio nace de este desarrollo.
- **Desarrollo.** La ingeniería y la construcción del producto las realicé yo. La comisión es por ese trabajo.
- **Formación técnica, a modo de referencia.** Tecnicatura Superior en Redes Informáticas, Teclab, en curso,
  segundo año, con promedio 7,5 y materias de Programación, Scripting, Cloud y Diseño de Sistemas. Programador Web
  Front‑End Developer, UTN‑BA, 75 horas, 2020. Desarrollo Web Niveles 1 y 2, Gobierno de la Ciudad, programa
  Aprendé Programando, 2020. Introducción a la Ciencia de Datos, Santander e IE University, 2025. IA y
  Productividad, Santander y Google, 2025.

---

## 2. Sistemas a certificar en el cliente: contingencia de adaptación

Cada integración está programada contra la API y la documentación oficial de cada fabricante. Están probados y
certificados en vivo GLPI para tickets, IVMS para acceso, WhatsApp no oficial, Gemini, Cerebras y Groq para IA, y
MercadoPago para cobros. El resto está implementado según la documentación, pero al conectarlo a un cliente real
puede diferir por la versión del sistema, la autenticación o campos a medida. A continuación, las horas estimadas
de adaptación y certificación por cliente en caso de que algo no funcione como indica la documentación; si funciona
directo, es solo conectar y probar.

| Categoría | Sistema | Horas si difiere de la documentación |
|---|---|---:|
| **Tickets** | Zendesk | 6 |
| | Jira Service Management | 8 |
| | Freshservice | 6 |
| | osTicket, lectura y cierre por MySQL | 8 |
| **Control de acceso** | HikCentral, Artemis con HMAC | 10 |
| | BioStar 2 | 8 |
| | ZKTeco, ZKBio y BioTime | 10 |
| | Honeywell Pro‑Watch | 10 |
| **Canales** | WhatsApp oficial, Meta Cloud API | 5 |
| | Telegram | 2 |
| | Email, IMAP y SMTP | 3 |
| | Microsoft Teams | 5 |
| | Slack | 5 |
| | Matrix y Element | 4 |
| **IA** | Claude, OpenAI, Grok, DeepSeek, Mistral y OpenRouter, cada uno | 2 |
| | DeepSeek local u Ollama, levantar el servidor | 3 |
| **Base de conocimiento** | Outline | 4 |

> **Cómo leerlo.** Son topes por sistema y por cliente, y solo aplican si el sistema real difiere de la
> documentación. Un cliente usa un sistema de tickets, uno de acceso y uno o dos canales, así que la contingencia
> real ronda entre 8 y 25 horas por cliente nuevo, habitualmente menos, porque muchas integraciones conectan
> directo. Este trabajo de puesta en marcha por cliente forma parte de la comisión.

---

## 3. Mantenimiento y evolución: comisión recurrente

El sistema se vende y va a producción, así que, además del desarrollo inicial, requiere mantenimiento y evolución
continuos, que son parte del valor y justifican una comisión recurrente, no solo un pago único:

- **Monitoreo y soporte,** para que siga corriendo 24/7 y para atender incidencias.
- **Actualizaciones** por cambios en las APIs de terceros —por ejemplo, Jira cambió su endpoint de búsqueda en
  2025—, en MercadoPago, en WhatsApp y en los proveedores de IA, además de parches de seguridad.
- **Nuevas integraciones y funciones** a pedido: otro sistema de tickets, otro canal, otra IA.
- **Alta y certificación de cada cliente nuevo,** según la contingencia de la sección 2.

**Estimación de mantenimiento:** entre 6 y 12 horas por mes por despliegue activo, sumando monitoreo,
actualizaciones y soporte, más las horas puntuales de funciones nuevas. En un modelo SaaS suele cobrarse como un
porcentaje del ingreso mensual recurrente o como un abono mensual fijo; en cualquier caso, es una parte recurrente
de la comisión, no un único cobro.

---

## 4. Propuesta de compensación, a acordar con la dirección

**Punto de partida.** Hoy mi compensación es de $830.904 netos por mes, más un beneficio en tarjeta de regalo
recargable de una cuenta de la empresa de aproximadamente $160.000 por mes, lo que da cerca de $1.000.000 mensuales
en total, de forma aproximada, ya que el monto exacto de la tarjeta puede variar. Vengo sin ajuste desde hace
tiempo, mientras desarrollé y sostengo una plataforma que INTELLIHELP puede vender y monetizar, con un valor de
desarrollo de entre US$28.000 y US$42.000 según la sección 1, y un costo de operación de centavos por cliente
según el informe de costos operativos. Sé que INTELLIHELP es una PyME, así que la propuesta es realista, sin
desembolso grande de entrada y escalonada. El objetivo es que mis ingresos crezcan junto con los de la empresa: si
ITHOS le genera más a INTELLIHELP, a mí también.

**Aclaraciones.**
- La primera implementación, de uso interno de INTELLIHELP, es sin costo, ya que es nuestra propia empresa y sirve
  de demo y vidriera. Aplicarlo a un cliente que paga es distinto: ahí corre el modelo de comisión.
- Los costos operativos los paga INTELLIHELP: las IA, el hosting y toda la infraestructura corren por cuenta de la
  empresa. Yo aporto el código, del que soy propietario, más el desarrollo y el mantenimiento. Mi comisión no sale
  de esos costos, que son de la empresa y de todos modos son centavos.

**Componentes, a acordar.**
1. **Recomposición salarial, fija.** Ajustar mi sueldo reconociendo el desarrollo y el sostenimiento de este
   producto. Hoy está desactualizado y sin aumento desde hace tiempo.
2. **Comisión variable, revenue‑share de ITHOS.** Un porcentaje de los ingresos mensuales que ITHOS genere por
   suscripciones de clientes. Sin techo, escala con el negocio. Como sugerencia, entre 10 y 20% del MRR neto; en
   el ejemplo se usa 15%.
3. **Puesta en marcha por cliente.** Un monto por dar de alta y certificar cada cliente nuevo, según la
   contingencia de la sección 2, que reconoce el trabajo puntual de cada implementación.
4. **Mantenimiento, recurrente.** El porcentaje cubre el mantenimiento y la evolución continua del sistema, entre
   6 y 12 horas por mes por despliegue, según la sección 3.

**Cómo escala.** Ejemplo con 15% del MRR, US$20 netos por cliente y mes, y pesos al dólar BNA de $1.510.

| Clientes con ITHOS | Ingreso ITHOS por mes | Mi comisión, 15% | En pesos, aproximado |
|---:|---:|---:|---:|
| 5 | US$100 | US$15 | ~$22.650 |
| 10 | US$200 | US$30 | ~$45.300 |
| 25 | US$500 | US$75 | ~$113.250 |
| 50 | US$1.000 | US$150 | ~$226.500 |
| 100 | US$2.000 | US$300 | ~$453.000 |

> Arranca chico, viable para la PyME hoy, y crece solo con la facturación de ITHOS, sin pedir dinero grande de
> entrada. Con 50 a 100 clientes, la comisión ya se acerca o supera medio sueldo actual, y sigue subiendo.

**Continuidad de la comisión.** Lo ideal es que la comisión por el producto se mantenga mientras genere ingresos
y mientras yo me ocupe de su mantenimiento. El alcance exacto, sea durante la relación laboral o como esquema de
regalías, queda a conversar.

> Es una propuesta de arranque, a acordar, pensada para ser justa para ambos y sostenible para una PyME: poco
> costo fijo y mucho techo de crecimiento atado al éxito real de ITHOS.

---

## 5. Propiedad del código y opción de compra

Soy el propietario del código. Hay dos modelos posibles, a elección de la dirección.

**Modelo A, licencia y uso.** Es el de la propuesta anterior. Conservo la propiedad del código; INTELLIHELP usa y
monetiza ITHOS y paga la infraestructura; yo cobro la comisión y lo mantengo. Es el de menor costo de entrada y el
que alinea intereses, porque crecemos juntos.

**Modelo B, compra de la propiedad.** Si INTELLIHELP quiere ser dueña del código, con la propiedad intelectual
completa y el derecho a usar, modificar y vender libremente, desligándome a mí de ITHOS, se acuerda un precio de
compra único. Este precio no se descuenta por ser PyME: es el valor real del activo, el mismo si lo compra una
PyME, Google o Meta. Se valúa como producto terminado, no solo como código:

- **Piso, costo de reconstruirlo desde cero:** entre US$28.000 y US$42.000, según la sección 1, solo la mano de obra.
- **Como producto listo para vender:** en las adquisiciones de software, un producto en producción se paga entre
  3 y 6 veces su costo de construcción, por el time‑to‑market, el riesgo evitado, el know‑how y las más de quince
  integraciones reales, lo que da un rango aproximado de US$120.000 a US$250.000.
- **Con ingresos ya en marcha:** además se valúa por múltiplo de facturación anual, típicamente entre 3 y 5 veces
  el ARR en SaaS, lo que lo lleva más arriba a medida que crece la base de clientes.
- **Precio a proponer, a negociar:** desde alrededor de US$150.000 por la propiedad completa, es decir la propiedad
  intelectual, el código fuente, el derecho a usar, modificar y vender, y mi desvinculación, ajustable hacia arriba
  según la proyección de ingresos.
- Con la compra quedo desligado de ITHOS: la empresa es dueña y no hay comisión posterior.

**Mantenimiento después de la compra, opcional.** Si, ya siendo ellos los dueños, quieren que yo siga
manteniéndolo y evolucionándolo, pertenezca o no a la empresa, se acuerda un contrato de mantenimiento aparte:

- Un abono mensual orientativo de US$400 a US$800, según la carga de monitoreo, actualizaciones y soporte, más las
  horas de funciones nuevas y el alta y certificación por cliente de la sección 2. A acordar.
- Sin ese contrato, la empresa asume el mantenimiento por su cuenta, para lo cual necesita un desarrollador que
  tome el proyecto.

> **Resumen de opciones.** El modelo A es más barato y de crecimiento compartido, conmigo como dueño más comisión.
> El modelo B deja todo en manos de la empresa pagando el buyout, y si me quieren para mantenerlo, con un abono
> aparte. Ambas quedan a conversar.

---

*Fin de la Parte 2. Los costos de operación, las fuentes oficiales y la evidencia del test de facturación están en
la Parte 1, el informe de alcance y costos operativos.*
