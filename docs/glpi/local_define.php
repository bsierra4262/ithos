<?php
/**
 * Configuración local de esta instalación de GLPI (INTELLIHELP / ayuda.intellihelp.tech).
 *
 * GLPI lo carga al arrancar desde Glpi\Application\SystemConfigurator, antes de hacer nada, y
 * ninguna actualización lo pisa: config/ se conserva entre versiones.
 *
 * ZONA HORARIA. El servidor corre en UTC: el sistema operativo, PHP (`date.timezone = UTC`) y
 * MySQL (`time_zone = SYSTEM`, con `NOW()` igual a `UTC_TIMESTAMP()`). Como acá estamos en
 * UTC-3, GLPI guardaba y mostraba TODO tres horas adelantado: un ticket cargado a las 08:59
 * figuraba a las 11:59.
 *
 * Y no era sólo cosmético:
 *   · los calendarios de SLA (Lun-Vie 09:00 a 18:00) se aplicaban sobre horas UTC, así que la
 *     ventana real de atención corría de 06:00 a 15:00;
 *   · ITHOS lee las fechas de la API y las interpreta como hora local, así que daba por "fuera
 *     de horario" lo que había llegado dentro. Pasó en el ticket #803: el cliente contestó a las
 *     15:47 reales, se leyó 18:47, y el ticket quedó dormido En espera hasta el día siguiente.
 *
 * NO SE ARREGLA desde la configuración de GLPI. `DBmysql::setTimezone()` sólo ajusta el reloj
 * `if ($this->use_timezones)`, y esa opción exige las tablas de zonas horarias de MySQL
 * (`mysql.time_zone_name`), sobre las que este hosting compartido no da permiso (ERROR 1142).
 * Tampoco sirve un `.user.ini`: está deshabilitado (`user_ini.filename` sin valor).
 *
 * Por eso se fija acá, que vale para la web Y para las tareas por consola (cron).
 */

date_default_timezone_set('America/Argentina/Buenos_Aires');
