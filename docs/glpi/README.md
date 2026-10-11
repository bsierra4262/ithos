# La marca de ITH en GLPI

Todo lo que hace que la mesa de ayuda se vea de **ITH** y no de GLPI vive acá, versionado, para
que se pueda reconstruir sin depender de la memoria de nadie.

El problema que resuelve: el tema anterior era un bloque PHP **copiado a mano en ~100 archivos
`front/*.php`**, y la actualización a GLPI 12 se lo llevó entero, porque trae esos archivos
nuevos. Lo mismo pasaba con el logo, que estaba pisando los PNG de GLPI. Así que la regla de todo
lo de abajo es la misma: **nada que una actualización de GLPI pueda reescribir**.

## Qué hay y dónde va

| Archivo | Dónde va en el servidor | Lo pisa una actualización |
|---|---|---|
| `tema_ith.css` | el campo `custom_css_code` de la entidad raíz, **en la base** | no |
| `public.htaccess` | `public/.htaccess` | **no**: GLPI 12 no trae ninguno |
| `ith-favicon.ico` | `public/pics/logos/ith-favicon.ico` | no: GLPI no conoce ese nombre |
| `ith-touch-icon.png` | `public/pics/logos/` y `public/apple-touch-icon.png` | no |
| los logos `ith-*.png` | `public/pics/logos/` | no: GLPI no conoce esos nombres |

El nombre que sale en la pestaña y al pie de los correos es la clave `app_name` de
`glpi_configs` (contexto `core`), hoy **Mesa de Ayuda ITH**. Está en la base, así que tampoco se
pierde al actualizar; GLPI sólo trae `GLPI` como valor por omisión en `src/autoload/CFG_GLPI.php`
para cuando la clave no existe.

## Por qué el favicon necesita el `.htaccess`

Un favicon **no se puede cambiar por CSS**: `head.html.twig` lo declara fijo como
`/pics/favicon.ico`, y ese archivo lo reescribe cada versión mayor de GLPI. Por eso el
`.htaccess` desvía esa ruta al archivo propio:

```apache
RewriteRule ^pics/favicon\.ico$ pics/logos/ith-favicon.ico [L]
```

Esa regla tiene que ir **antes** del chequeo `RewriteCond %{REQUEST_FILENAME} -f`. Si va después,
Apache encuentra que `/pics/favicon.ico` existe, lo sirve tal cual, y la reescritura nunca corre.
`tests/probar_tema_glpi.py` verifica justamente ese orden.

## Cómo se reaplica el tema

El CSS se guarda en la base con una consulta preparada (nunca pegándolo a mano en el editor de
GLPI, que es donde se cuelan los errores):

```sql
UPDATE glpi_entities SET enable_custom_css = 1, custom_css_code = ? WHERE id = 0;
```

Después hace falta **limpiar la caché**, porque GLPI cachea la configuración de la entidad:

```bash
php bin/console cache:clear --no-interaction
```

Dos cosas para no olvidar:

- GLPI pasa el CSS por `strip_tags()`, así que **un solo `<` se come todo lo que sigue**.
- `CHAR_LENGTH()` cuenta caracteres y `strlen()` cuenta bytes: el CSS tiene caracteres `·` que
  ocupan 2 bytes, así que comparar uno contra el otro hace creer que quedó truncado cuando no.
  Para verificar que se guardó entero, comparar **md5**.

## Después de actualizar GLPI

1. Verificar que `public/.htaccess` siga ahí (GLPI 12 no trae uno; si falta, la aplicación
   devuelve 404 en todo y `config/` queda descargable por web).
2. Verificar que los `pics/logos/ith-*.png`, `ith-favicon.ico` y `apple-touch-icon.png` sigan ahí.
3. Correr `python tests/probar_tema_glpi.py`.
4. Mirar la interfaz con la paleta puesta (hoy `auror_dark`): lo seleccionado tiene que verse
   verde con texto oscuro, en el menú, en los desplegables, en las pestañas y en las listas.

## La regla del tema

> Todo estado que cambia el fondo tiene que fijar también el texto, y el de todo lo que hay
> adentro. Nunca oscuro sobre oscuro ni claro sobre claro.

El ` *` de las reglas de selección no es decorativo: los controles de GLPI tienen hijos con color
propio —el botón de perfil es un `button.nav-link` con un `div.text-muted-menu` adentro— y sin él
quedan con su color viejo sobre el fondo nuevo.

Y los enlaces visitados **no se arreglan con `color: inherit`**: por privacidad los navegadores
descartan en `:visited` los valores que dependen del entorno. Hay que darle a `:link` y a
`:visited` el mismo valor explícito.
