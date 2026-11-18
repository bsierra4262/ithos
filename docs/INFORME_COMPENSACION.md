# ITHOS — Parte 2: valor del desarrollo y propuesta de compensación
**Preparado para:** Nicolás Baldelli · INTELLIHELP S.A. · Actualizado 11/2026

> **De qué trata este informe.** Es la segunda de dos partes, complementaria al informe de alcance y costos
> operativos. Aquel muestra qué hace ITHOS y cuánto cuesta operarlo; este presenta el **valor del desarrollo**, la
> **propuesta de compensación** y las **opciones de propiedad**. ITHOS es hoy una herramienta interna de
> INTELLIHELP, no un producto a la venta, y la propuesta está pensada sobre esa base.

---

## 1. Esfuerzo y valor del desarrollo

ITHOS es un desarrollo que realicé para INTELLIHELP: la arquitectura y toda la implementación. No es un script,
sino un sistema completo —un Gestor en el servidor más un agente en la oficina— con integraciones reales, IA, voz
y panel, funcionando en producción. A continuación, el esfuerzo de ingeniería que representa, por componente.

| Componente | Horas |
|---|---:|
| Arquitectura: Gestor, agente, WebSocket, protocolo y registro por API key | 42 |
| Capa de IA enchufable: 10 proveedores, cadena con respaldo, cuota y transcripción | 52 |
| Motor de voz: Charon en streaming con WSOLA, caché, edge‑tts y diccionario de pronunciación | 48 |
| Captura y filtrado de voz: micrófono dinámico, VAD Silero y webrtc, identificación por voz | 34 |
| Mesa de ayuda GLPI completa: tickets, seguimientos, tareas, soluciones, documentos y SLA | 44 |
| Triage con IA, ciclo de vida y acciones: cerrar, asignar, posponer y responder | 46 |
| Control de acceso IVMS: integrador, terminales configurables y portero | 30 |
| WhatsApp: vinculación por QR, grupos por ámbito, texto y notas de voz | 26 |
| Asistente: memoria, base de conocimiento automática con Outline, y autorización | 44 |
| Reportes ITIL 4: KPIs, SLA, MTTR, PDF y CSV, programados y con rango personalizado | 30 |
| Proactivo: aviso de SLA por vencer, agrupado por técnico asignado | 14 |
| Panel web: diseño HUD, estado en vivo, métricas, UX, responsive y multiplataforma | 58 |
| Instaladores multi‑SO para Windows, Linux y Mac, más Docker y Caddy con HTTPS/WSS | 28 |
| QA y testing: baterías de producción, exhaustiva, código, nivel 4 y requerimientos, con seguridad y concurrencia | 48 |
| Integración, ajustes finos, documentación y puesta a punto | 40 |
| **TOTAL** | **≈ 584 h** |

- **Cronograma.** Desarrollado por fases —arquitectura, integraciones, voz y WhatsApp, IA y asistente, panel y
  UX, y finalmente QA y hardening— a lo largo de varios meses de trabajo dedicado.
- **Solo lo que está en uso.** El total cuenta únicamente lo que hoy funciona en ITHOS. No incluye lo que se
  desarrolló y después se sacó para dejarlo enfocado en nuestro uso: otros sistemas de tickets, otros controles de
  acceso, otros canales de mensajería y el cobro de suscripciones.
- **Valor de mercado del desarrollo, costo de reemplazo.** Contratar este desarrollo a un tercero a tarifa de
  mercado, entre US$40 y US$60 por hora, le habría costado a INTELLIHELP entre US$23.360 y US$35.040.
- **Qué le aporta a INTELLIHELP.** Automatiza la mesa de ayuda —clasificar, responder, pedir datos y evidencia,
  recordar esperas y avisar SLA por vencer—, documenta en la wiki cada procedimiento que resuelve el equipo y
  atiende la recepción por voz, con un costo de operación de entre US$9 y US$15 por mes según la Parte 1.
- **Desarrollo.** La ingeniería y la construcción las realicé yo.
- **Formación técnica, a modo de referencia.** Tecnicatura Superior en Redes Informáticas, Teclab, en curso,
  segundo año, con promedio 7,5 y materias de Programación, Scripting, Cloud y Diseño de Sistemas. Programador Web
  Front‑End Developer, UTN‑BA, 75 horas, 2020. Desarrollo Web Niveles 1 y 2, Gobierno de la Ciudad, programa
  Aprendé Programando, 2020. Introducción a la Ciencia de Datos, Santander e IE University, 2025. IA y
  Productividad, Santander y Google, 2025.

---

## 2. Mantenimiento y evolución

Al estar en producción, ITHOS requiere mantenimiento y evolución continuos:

- **Monitoreo y soporte,** para que siga corriendo 24/7 y para atender incidencias.
- **Actualizaciones** por cambios en las APIs de terceros —GLPI, WhatsApp, Outline, Planka y los proveedores de
  IA, que cambian modelos y cuotas con frecuencia—, además de parches de seguridad.
- **Funciones nuevas** que pida el equipo.

**Estimación:** entre 6 y 12 horas por mes de monitoreo, actualizaciones y soporte, más las horas puntuales de
funciones nuevas.

---

## 3. Propuesta de compensación, a acordar con la dirección

**Punto de partida.** Hoy mi compensación es de $830.904 netos por mes, más un beneficio en tarjeta de regalo
recargable de una cuenta de la empresa de aproximadamente $160.000 por mes, lo que da cerca de $1.000.000 mensuales
en total, de forma aproximada, ya que el monto exacto de la tarjeta puede variar. Vengo sin ajuste desde hace
tiempo, mientras desarrollé y sostengo una herramienta con un valor de desarrollo de entre US$23.360 y US$35.040
según la sección 1. Sé que INTELLIHELP es una PyME, así que la propuesta es realista y sin desembolso grande de
entrada.

**Aclaración.** Los costos operativos los paga INTELLIHELP: el servidor y cualquier IA paga, si algún día hiciera
falta. Yo aporto el código, del que soy propietario, más el desarrollo y el mantenimiento.

**Componentes, a acordar.**
1. **Recomposición salarial, fija.** Ajustar mi sueldo reconociendo el desarrollo y el sostenimiento de ITHOS.
   Hoy está desactualizado y sin aumento desde hace tiempo.
2. **Mantenimiento, recurrente.** Un reconocimiento mensual por el mantenimiento y la evolución del sistema, de
   entre 6 y 12 horas por mes según la sección 2.

> Es una propuesta de arranque, a acordar, pensada para ser justa para ambos y sostenible para una PyME.

---

## 4. Propiedad del código y opción de compra

Soy el propietario del código. Hay dos modelos posibles, a elección de la dirección.

**Modelo A, licencia de uso.** Conservo la propiedad del código; INTELLIHELP lo usa internamente y paga la
infraestructura; yo lo mantengo según la sección 3. Es el de menor costo de entrada.

**Modelo B, compra de la propiedad.** Si INTELLIHELP quiere ser dueña del código, con la propiedad intelectual
completa y el derecho a usar, modificar y vender libremente, desligándome a mí de ITHOS, se acuerda un precio de
compra único. Este precio no se descuenta por ser PyME: es el valor real del activo. Se valúa como producto
terminado, no solo como código:

- **Piso, costo de reconstruirlo desde cero:** entre US$23.360 y US$35.040, según la sección 1, solo la mano de obra.
- **Como producto terminado y en producción:** en las adquisiciones de software, un producto que ya funciona se
  paga entre 3 y 6 veces su costo de construcción, por el tiempo ahorrado, el riesgo evitado y el know‑how, lo que
  da un rango aproximado de US$70.000 a US$210.000.
- **Precio a proponer, a negociar:** desde alrededor de US$150.000 por la propiedad completa, es decir la propiedad
  intelectual, el código fuente, el derecho a usar, modificar y vender, y mi desvinculación.
- Con la compra quedo desligado de ITHOS: la empresa es dueña y no hay compensación posterior por el producto.

**Mantenimiento después de la compra, opcional.** Si, ya siendo ellos los dueños, quieren que yo siga
manteniéndolo y evolucionándolo, pertenezca o no a la empresa, se acuerda un contrato de mantenimiento aparte:

- Un abono mensual orientativo de US$400 a US$800, según la carga de monitoreo, actualizaciones y soporte, más las
  horas de funciones nuevas. A acordar.
- Sin ese contrato, la empresa asume el mantenimiento por su cuenta, para lo cual necesita un desarrollador que
  tome el proyecto.

> **Resumen de opciones.** El modelo A es más barato: conservo la propiedad y lo mantengo. El modelo B deja todo en
> manos de la empresa pagando la compra, y si me quieren para mantenerlo, con un abono aparte. Ambas quedan a
> conversar.

---

*Fin de la Parte 2. Los costos de operación y las fuentes oficiales están en la Parte 1, el informe de alcance y
costos operativos.*
