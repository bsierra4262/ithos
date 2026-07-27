# Instalar el AGENTE ITHOS en la PC del cliente (ejecutable + servicio)

> **Modelo Gestor + Agente.** El **GESTOR** (el cerebro) lo hosteamos **nosotros (INTELLIHELP)**; el cliente
> **nunca** accede al gestor. En la PC del cliente va solo el **AGENTE**: una app liviana que se conecta al gestor,
> ejecuta la voz y lee el control de acceso local. Este documento es para instalar ESE agente. Ver la arquitectura
> completa en [ARQUITECTURA_GESTOR_AGENTE.md](ARQUITECTURA_GESTOR_AGENTE.md).

## Quién ve qué (modelo de acceso)
- **Gestor / panel superadmin (`/`)** → **SOLO INTELLIHELP** (la empresa propietaria). El cliente NO entra acá.
- **Dashboard del cliente (`/panel/<api_key>`)** → el cliente ve su SLA, métricas y config. Es lo único suyo.
- **Portal de alta (`/alta`)** → **enlace TEMPORAL de un solo uso** que le damos al cliente para cargarse la
  primera vez; no es público ni permanente (ver §Seguridad del gestor abajo).

---

## 1. Construir el INSTALADOR (una vez, en tu máquina)
Un solo comando arma **todo** (icono → app `.exe` → firma → instalador → firma), y deja **SOLO el instalador** en
`dist\` (limpia lo viejo):
```bat
pip install pyinstaller pywebview pillow
pip install -r requirements.txt
build\construir_agente.bat
```
Queda **`dist\ITHOS-Agente-Setup.exe`** (el `.exe` va adentro; no hay un ejecutable suelto). El agente es una
**APLICACIÓN con interfaz gráfica ITHOS** (no una consola): al abrirla ves el panel con el reactor, el estado y los
botones para **configurar** (api_key + contraseña), **arrancar/detener** y **desinstalar/mover**. Multiplataforma
(webview nativo de cada SO; en un server Linux sin pantalla cae a un menú de consola). El servicio 24/7 corre
**headless** con `ithos-agente.exe --run` (lo pone la tarea del instalador).

El instalador: lo instala en `C:\Program Files\ITHOS`, crea accesos en el menú Inicio (**ITHOS Agente** + **Desinstalar**),
opción de **arranque al iniciar sesión** (portero) y, al terminar, abre la app para configurarla. La config + el
caché por cliente viven en **`%LOCALAPPDATA%\ITHOS`** (persistente y escribible; en un `.exe` onefile NO puede ir en
la carpeta del programa). El **desinstalador** borra **todo lo del agente** (carpeta, datos, tarea, registro) sin
dejar rastro — y **NO toca** el sistema de tickets del cliente, la base de fichadas ni el trabajo hecho.

### Firma de código GRATIS (para que no salga "editor desconocido")
No hay cert gratis de CA pública para software propietario. Para tu **flota** (instalás en PCs conocidas) la vía
oficial de Microsoft, gratis, es un **certificado self-signed de INTELLIHELP** + confiarlo en la PC del cliente:
```bat
:: firmar (lo hace solo build\construir_agente.bat; o a mano):
powershell -ExecutionPolicy Bypass -File build\firmar.ps1
:: -> crea el cert (1 vez), firma el .exe y el instalador con timestamp, y deja build\ithos-publisher.cer
```
**El propio instalador confía el certificado solo** (lleva el `ithos-publisher.cer` adentro y lo instala en Root +
Editores de confianza al instalar, como admin): así el **agente instalado** queda firmado y **de confianza en esa
PC sin que el cliente ejecute ningún comando**. Al desinstalar, lo saca (sin rastro). Para una **flota grande** por
**GPO**, o si instalás sin el `.cer`, está `build\confiar_en_cliente.ps1` como alternativa.
> **Ojo (honesto):** en una PC **nueva**, el **instalador en sí** todavía puede mostrar una vez el aviso de
> SmartScreen ("editor desconocido") — quien instala hace clic en *Más información → Ejecutar de todas formas*. Para
> que **ni eso** aparezca en **cualquier** PC hace falta un cert de **CA pública (pago)**: **Azure Trusted Signing
> ~US$10/mes** o **OV/EV** (ver FALTANTES.md). Migrar a **Nuitka** reduce falsos positivos de antivirus.

## 2. Configurar el agente (menú del ejecutable) — el mismo `.exe` para TODAS las empresas
El **mismo ejecutable** sirve para cualquier cliente: se identifica por empresa con **api_key + contraseña de
agente**, que **asigna el GESTOR** en el alta (la contraseña se genera sola y se ve/copiar en el panel, campo
*"Contraseña de agente"* de la empresa). Corré el agente con **`--menu`** (o simplemente ejecutalo sin configurar) y
usá el menú, con el diseño de la app:

```
  1) Configurar / conectar este equipo a una empresa   ← pegás api_key + contraseña (prueba la conexión)
  2) Arrancar el agente ahora
  3) Desinstalar / mover a otra PC                       ← borra credenciales + arranque; instalás en otra PC igual
  4) Salir
```

El agente guarda **solo** `agente\config.json` = `{ central_url, api_key, agente_token }` (o la variable
`ITHOS_AGENTE_CONFIG`). **El resto de la config —la voz Charon (con la clave del cliente), el integrador de acceso
local y el micrófono— la MANDA el gestor** al autenticar (*thin agent*): no viven en el equipo del cliente.

> La **api_key** y la **contraseña de agente** se las das vos desde el gestor al dar de alta la empresa. Sin **ambas**
> el gestor **rechaza** la conexión (un agente con solo la api_key NO entra). El agente **solo sale hacia afuera**
> (WebSocket seguro): el cliente **no abre ningún puerto**.
>
> **Mover a otra PC:** opción **3** del menú (borra la config local y quita el arranque) → instalás el mismo `.exe`
> en la PC nueva → opción **1** con la **misma** api_key + contraseña. No hace falta re-dar de alta la empresa.

## 3. Dejarlo corriendo 24/7 (arranca solo tras un corte de luz, se reinicia si se cae)

El agente tiene que **volver solo** ante cualquier cosa —corte de luz, reinicio, cierre— y **seguir funcionando
aunque la PC/servidor esté bloqueado**. Hay dos formas según si el agente **habla por parlantes** o no.

### 3.a — RECOMENDADO para PC con parlantes (portero + respuestas por voz)
Como la voz necesita **audio** y un servicio en **sesión 0 no tiene audio** (ver §3.1), la PC‑portero se configura
para que arranque en una **sesión interactiva con audio** y quede sola:

1. **Autologin del usuario** (para que tras un corte de luz la PC bootee y entre sola a la sesión, con audio):
   `netplwiz` → destildar "Los usuarios deben escribir…" → poner el usuario y su clave. *(O `Sysinternals Autologon`.)*
2. **Arranque del agente al iniciar sesión, con reinicio si se cae** — Programador de tareas:
   ```bat
   schtasks /Create /TN "ITHOS Agente" /TR "C:\Program Files\ITHOS\ithos-agente.exe" ^
     /SC ONLOGON /RL HIGHEST /F
   ```
   *(La tarea se llama **"ITHOS Agente"** — igual que la que crea el instalador y la que borra la opción 3 del menú.)*
   En la tarea, pestaña **Configuración** → tildar *"Si la tarea falla, reiniciarla cada 1 minuto"* (hasta 999
   veces). Trigger **Al iniciar sesión** = corre en la sesión interactiva → **tiene parlantes**.

Resultado: **vuelve la luz → la PC bootea → autologin → sesión con audio → arranca el agente → se reconecta solo al
gestor → el portero suena**, aunque después se bloquee la pantalla.

### 3.b — Servicio NSSM (solo si el agente NO usa parlantes)
Si ese agente solo hace tickets/avisos (sin voz local), sirve un servicio con **NSSM** (un `.exe`, gratis):
```bat
nssm install IthosAgente "C:\Program Files\ITHOS\ithos-agente.exe"
nssm set IthosAgente AppDirectory "C:\Program Files\ITHOS"
nssm set IthosAgente Start SERVICE_AUTO_START
nssm start IthosAgente
```
Arranca con la PC y se reinicia solo, **sin necesidad de que nadie inicie sesión** — pero corre en **sesión 0, sin
audio**, así que **no sirve para el portero**. (Para la venta formal, un **instalador MSI** que pida la API key y
deje esto configurado — como el agente de Datadog — Fase 2.)

## 3.1. Audio por los parlantes: pantalla bloqueada, RDP y sesión

Vale para **TODO lo que sale por los parlantes** —el portero (fichadas) **y** las respuestas por voz de tickets/
consultas—: ambas rutas (audio cacheado y streaming) siguen la **misma lógica** de recuperar el dispositivo. Para
que **suene siempre** (aunque la PC esté bloqueada o alguien entre por RDP):

- **Correlo en una sesión interactiva con audio**, no como servicio en sesión 0 (ver §3.a: autologin + arranque al
  iniciar sesión). Así tiene parlantes reales y vuelve solo tras un corte de luz.
- **Que no se suspenda / no baje la pantalla:** el agente ya evita la suspensión (anti‑suspensión); igual conviene
  poner el plan de energía en **"nunca suspender"**. Bloquear la pantalla **no** corta el audio.
- **RDP:** cuando entrás por RDP, el audio del portero sigue saliendo por los **parlantes físicos de la PC‑portero**
  (que es lo que querés para la puerta), no por tu equipo remoto. El agente ahora **re‑toma el dispositivo de audio
  solo** si se pierde al conectar/desconectar RDP o al bloquear (init perezoso + reintento; ver regresión H33). Si
  administrás por RDP, dejá el **audio remoto en "Reproducir en el equipo remoto"** para no desviar el sonido.
- El agente **reintenta** el audio: si al arrancar no había dispositivo (arrancó bloqueado/headless), **vuelve a
  intentar en cada reproducción** y suena apenas el audio está disponible. Todo esto queda registrado en el log.

## 4. Actualizaciones (Fase 2)
El agente se actualizará **solo, por la red** contra el gestor (estilo Chrome/Steam): **avisa** cuando hay una
versión nueva y **el usuario decide** (ahora / más tarde); descarga, verifica la firma y se reemplaza. **Nunca se
manda un archivo a mano.** Detalle en ARQUITECTURA_GESTOR_AGENTE.md §3.1.

## Seguridad del gestor (lo hosteamos nosotros) — IMPLEMENTADO
- El **panel superadmin (`/`)** y las APIs de gestión están **detrás de autenticación** (solo INTELLIHELP):
  **usuario + contraseña** (`ITHOS_ADMIN_USER` / `ITHOS_ADMIN_TOKEN`); las llamadas internas usan la cabecera
  `X-Admin-Token`.
- El **alta (`/alta`)** es un **enlace temporal de un solo uso por cliente** (token que caduca): se genera desde el
  panel (`/api/alta_link`) y se consume al usarse.

> **Nota honesta:** el `.exe` hay que **construirlo y probarlo en una PC Windows del cliente** (trae libs nativas:
> neonize/onnx/portaudio). El spec (`build/agente.spec`) es un punto de partida sólido; si al correr el `.exe`
> falta alguna lib nativa, se agrega en `datas/binaries` del spec.
