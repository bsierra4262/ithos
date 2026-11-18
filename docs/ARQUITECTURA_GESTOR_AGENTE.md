# ITHOS — Gestor + Agente: arquitectura, versionado, empaquetado y red 24/7
**Cómo está armado hoy.** Actualizado 18-nov-2026.

> **Qué es esto.** La arquitectura de ITHOS como **GESTOR** (el cerebro, en el VPS de INTELLIHELP) **+ AGENTE**
> (la app liviana de la PC de la oficina), validada contra documentación oficial y contra cómo lo resuelven los
> sistemas de agentes profesionales. ITHOS es una herramienta interna: hay **un Gestor y un agente**.

---

## 0. Resumen

| Tema | Cómo quedó |
|---|---|
| **Nombres** | **Gestor** (carpeta `ITHOS/central/`) + **Agente** (`ITHOS/agente/`). |
| **Arquitectura** | **Control‑plane (Gestor) / data‑plane (Agente)**: el agente manda eventos y ejecuta comandos; toda la lógica vive en el Gestor. |
| **Red 24/7** | Reconexión con **backoff exponencial + jitter (±30 %)**, tope 30 s; ping/pong cada 20 s; el Gestor se pone al día por **estado**, sin replay. |
| **Versionado** | **SemVer** para Gestor (hoy 1.2.0) y Agente + **contrato de protocolo** con número de versión en el `auth`. |
| **Empaquetado** | **Agente:** ejecutable con **PyInstaller** + instalador **Inno Setup** firmado (Windows). **Gestor:** **Docker** en el VPS (central, panel, ollama, caddy), no ejecutable. |
| **Actualización del agente** | Con un instalador nuevo: detecta la versión instalada, cierra el agente y actualiza conservando config y caché. |

---

## 1. La arquitectura Gestor + Agente

Es el patrón que usan los sistemas de agentes profesionales: separar el **control‑plane** (decide, gobierna,
observa) del **data‑plane** (ejecuta). El agente es un **cliente delgado**; toda la lógica y la política viven en
el centro (IBM, AWS, HashiCorp Consul).

### 1.0 Conexión, handshake y qué viaja en cada dirección

```mermaid
sequenceDiagram
    participant A as AGENTE (PC de la oficina)
    participant C as GESTOR (VPS)
    A->>C: conecta wss://DOMINIO/ws
    A->>C: auth {api_key, agente_token, version, protocol_version}
    Note over C: valida las credenciales (hmac, tiempo constante)<br/>y la compatibilidad de protocolo
    C-->>A: auth_ok {config: voz · idioma · velocidad · integrador · micrófono}
    Note over C: los servicios (tickets+triage, WhatsApp, Planka,<br/>reportes, proactivo, KB, wiki) ya corren desde<br/>que arrancó el Gestor; el agente se engancha
    loop mientras esté conectado
        A->>C: evento acceso {nombre, device, es_fallo}
        C-->>A: comando decir {texto, cachear}
        A->>C: evento consulta_voz {audio}
        C-->>A: comando decir {respuesta}
        A->>C: evento estado_agente {micrófono, integrador, versión}
        A->>C: evento terminales_descubiertos {lista}
        C-->>A: ping / pong (cada 20 s)
    end
    Note over A,C: si se corta: el agente reconecta con backoff + jitter ±30 % (tope 30 s).<br/>No hace falta replay: el Gestor se pone al día por ESTADO (baseline de tickets y fichadas).
```

**Regla de oro:** el agente **manda eventos** y **ejecuta comandos**; nunca decide. Toda la política (qué decir,
cómo clasificar, a quién avisar) vive en el Gestor, así una mejora se despliega en **un solo lugar** y el agente
instalado no se toca.

| Concepto de la industria | En ITHOS |
|---|---|
| **Control‑plane / cerebro** | **Gestor** (`ITHOS/central/`): IA, tickets, triage, ciclo de vida, KB, wiki, reportes, Planka; decide y manda órdenes |
| **Data‑plane / executor delgado** | **Agente** (`ITHOS/agente/`): conecta por WebSocket y EJECUTA (voz por parlantes, lectura de IVMS, micrófono) |
| **El agente manda EVENTOS, el Gestor manda COMANDOS** | `{"tipo":"evento",...}` ↔ `{"accion":"decir",...}` |
| **Punto central de logs** | el Gestor centraliza |
| **Fail‑safe cuando el centro no está** | el agente reconecta solo |

---

## 1.1 Modelo de acceso (quién ve qué)

- **Panel del Gestor → sólo el administrador de INTELLIHELP.** Todo el panel exige el login (usuario +
  contraseña hasheada con scrypt, cookie `httponly`/`secure`, rate-limit, logout); sólo `/login` y `/logout`
  quedan abiertos, y una ruta nueva nace privada. Detrás de **HTTPS/WSS** (Caddy + HSTS). No hay alta por
  enlace, ni portal de cliente, ni ruta que devuelva la configuración con sus claves.
- **AGENTE ↔ GESTOR → api_key + contraseña de agente** (`agente_token`), las dos de `clientes.json`. El agente
  entra **sólo si manda las dos y coinciden** (comparación en tiempo constante); con sólo la api_key **no
  entra**. Es *thin agent*: guarda sólo esas credenciales y **el Gestor le manda el resto** (voz Charon,
  integrador de acceso, micrófono) en el `auth_ok`. Se mueve a otra PC con las mismas credenciales (menú del
  agente). Regresiones: `tests/probar_requerimientos.py` y `tests/probar_auditoria_seguridad.py`.

---

## 2. Red 24/7

**Objetivo:** con internet aunque sea mínimo, el agente responde al instante; sin internet no hay nada que hacer
(el cerebro está en el VPS). Lo que está implementado, según las prácticas recomendadas (websocket.org, docs de
`websockets`):

1. **Reconexión con backoff exponencial + JITTER + tope.** `2 → 4 → … → 30 s` con jitter de **±30 %**
   (`ITHOS/agente/agente.py`): sin tope, un corte largo dejaría al agente esperando de más; sin jitter, todas las
   reconexiones caerían en el mismo instante. Una reconexión limpia vuelve el backoff a 2 s.
2. **Heartbeat.** `ping_interval=20, ping_timeout=20` del protocolo WebSocket.
3. **Re‑sync por estado.** No hace falta replay: el Gestor **consulta el estado** (tickets por GLPI, fichadas por
   baseline) y se pone al día solo.
4. **Avisos sin ruido.** El aviso de "ITHOS en línea" sale **una vez** por arranque del Gestor, no en cada
   reconexión del agente; el de "disponible" sale sólo si se venía de un mantenimiento.
5. **Latencia:** transcripción por Groq, nota de voz en memoria y precalentada, cachés, sin N+1.

---

## 3. Versionado (Gestor y Agente)

**SemVer** (`MAJOR.MINOR.PATCH`): MAJOR = cambio incompatible, MINOR = función compatible, PATCH = arreglo.

- Las versiones viven en `ITHOS/comun/version.py`: `GESTOR_VERSION` (hoy **1.2.0**), `AGENTE_VERSION`,
  `PROTOCOL_VERSION` y `AGENTE_MIN_VERSION`.
- **Contrato de protocolo** con su propia versión: el agente manda `protocol_version` en el `auth` y el Gestor
  responde la suya; si el agente es incompatible, el log lo marca para actualizarlo.
- **Compatibilidad hacia atrás:** el Gestor nuevo entiende agentes viejos (se agregan campos, no se rompen los
  que hay; un comando existente nunca cambia de significado).
- **Quién sube cada versión:** `compilador/build/bump_version.py`. La del agente la sube `construir_agente.bat`
  en cada compilación (y la sincroniza con el instalador). La del Gestor se sube **en el repositorio** antes de
  armar el paquete: subirla en el servidor la pisaba el paquete siguiente y nunca avanzaba.

---

## 4. Empaquetado

**Agente:** un **ejecutable** —instalar Python y correr un `.py` en la PC sería frágil—, armado con
**PyInstaller** (`compilador/build/agente.spec`) y envuelto en un instalador **Inno Setup**
(`compilador/build/ithos-agente.iss`), los dos firmados con el certificado propio de INTELLIHELP
(`firmar.ps1`). El instalador confía ese certificado en la PC, crea la tarea «ITHOS Agente» (al iniciar sesión,
con `--run`, para tener audio) y el desinstalador no deja rastro. Detalle en
[INSTALACION_AGENTE.md](INSTALACION_AGENTE.md).

Por qué **tarea al iniciar sesión** y no servicio de Windows: un servicio corre en la sesión 0, **sin audio**, y
el portero necesita los parlantes.

**El GESTOR no se empaqueta como ejecutable:** va en **Docker en el VPS** (`ITHOS/docker-compose.yml`, proyecto
`jarvis-cloud`), detrás de Caddy con HTTPS. Se actualiza en un solo lugar con
`compilador/instaladores/actualizar.sh` (ver [HOSTINGER.md](HOSTINGER.md)).

---

## 5. Fuentes
- Control‑plane / data‑plane y patrón de agente delgado: [IBM — Agent Control Plane](https://www.ibm.com/think/topics/agent-control-plane) · [AWS Prescriptive Guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-multitenant/employing-control-planes-in-agentic-environments.html) · [HashiCorp Consul — control plane](https://developer.hashicorp.com/consul/docs/architecture/control-plane) · [Control Plane vs Data Plane](https://www.truefoundry.com/blog/control-plane-vs-data-plane)
- Reconexión WebSocket 24/7: [websocket.org — reconnection](https://websocket.org/guides/reconnection/) · [websockets (Python) docs](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html) · [OneUptime — reconnection](https://oneuptime.com/blog/post/2026-01-27-websocket-reconnection/view)
- Empaquetado: [PyInstaller](https://pyinstaller.org/) · [Inno Setup](https://jrsoftware.org/isinfo.php)
- Versionado / compatibilidad: [SemVer](https://semver.org/lang/es/)
