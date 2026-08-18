# Política de seguridad

## Reporte de vulnerabilidades

Ante una vulnerabilidad de seguridad, **no debe abrirse un issue público**. El reporte se
realiza de forma privada a **bsierra@intellihelp.tech**.

Se solicita incluir, en la medida de lo posible: descripción, pasos de reproducción, impacto
y una posible mitigación. El reporte recibirá respuesta a la brevedad.

## Manejo de secretos y datos

- Las credenciales reales (claves de IA, tokens de los sistemas de tickets y de control de
  acceso, claves de los canales, `ITHOS_MASTER_KEY`, `ITHOS_ADMIN_TOKEN`) residen en
  `ITHOS/central/clientes.json` o en variables de entorno; **no se versionan**. El repositorio
  incluye únicamente `ITHOS/central/clientes.ejemplo.json` y `.env.example` con marcadores.
- Los secretos de cada cliente se **cifran en reposo** con AES-256-GCM, bajo una clave maestra
  (`ITHOS_MASTER_KEY`) que se conserva por separado de los datos.
- El repositorio no contiene datos reales de clientes: ni memorias, ni sesiones de WhatsApp,
  ni métricas, ni bases de conocimiento, ni tokens de alta.

## Control de acceso

- El acceso al Gestor (panel de administración y APIs de gestión) exige **usuario y
  contraseña**; la contraseña se almacena hasheada con *scrypt* y es rotable.
- Las llamadas internas o programáticas usan una cabecera de token de administración.
- Cada cliente accede **únicamente** a su propio dashboard. El alta de un cliente es un
  **enlace temporal de un solo uso** que caduca tras su utilización.
- Cookies `secure`/`httponly`, *rate-limit* en el login, HSTS en Caddy y cierre de sesión.

## Aislamiento entre inquilinos

Cada empresa es un inquilino aislado: memoria, configuración y secretos propios.
La autorización de las funciones sensibles es por **identidad** (número, correo o usuario),
nunca por el canal de origen. Un cliente no puede acceder al contexto de otro.

## Capas de defensa

```mermaid
flowchart TD
    subgraph Red["Perímetro"]
        FW["Firewall del servidor:<br/>sólo 22 / 80 / 443<br/>(8080 y 8090 nunca se publican)"]
        TLS["Caddy: TLS + HSTS<br/>certificado automático"]
        FW --> TLS
    end
    TLS --> Q{"¿quién entra?"}
    Q -->|"INTELLIHELP"| AD["Panel superadmin y APIs:<br/>usuario + contraseña (scrypt),<br/>cookie secure/httponly,<br/>rate-limit y cierre de sesión"]
    Q -->|"cliente"| DA["Sólo su dashboard<br/>(/panel/&lt;api_key&gt;)"]
    Q -->|"empresa nueva"| AL["Alta: enlace de un solo uso,<br/>con vencimiento y revocable"]
    Q -->|"agente"| AG["api_key + contraseña de agente,<br/>comparadas con hmac"]
    AD --> DAT[("Datos por cliente:<br/>secretos cifrados AES-256-GCM<br/>clave maestra en el .env, aparte")]
    DA --> DAT
    AG --> DAT
    AL --> DAT
    DAT --> PR["Contexto propietario:<br/>sólo las identidades del dueño;<br/>por micrófono, clave + voz-id"]
```

Cada capa se verifica en la batería de requerimientos (`tests/probar_requerimientos.py`): puertos y
firewall documentados, login y rate-limit, altas de un solo uso, autenticación del agente por empresa y
cifrado en reposo con clave maestra separada.
