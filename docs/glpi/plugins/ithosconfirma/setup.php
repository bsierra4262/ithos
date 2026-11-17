<?php

/**
 * ITHOS · Confirmar resolución — plugin de GLPI de INTELLIHELP.
 *
 * Pone un cartel grande delante del botón «Aprobar» de la solución de un ticket. Ese botón CIERRA el
 * ticket, y el cliente lo usaba para contestar cualquier cosa: en el #849 escribió «No puede fichar
 * aún» y apretó Aprobar, y el ticket quedó cerrado con el problema abierto. El cartel le dice qué
 * está por hacer y, si lo que escribió suena a que el problema sigue, se lo marca.
 *
 * Es un plugin y no un cambio en GLPI a propósito: el núcleo se pisa en cada actualización.
 */

define('PLUGIN_ITHOSCONFIRMA_VERSION', '1.0.0');

function plugin_version_ithosconfirma()
{
    return [
        'name'         => 'ITHOS · Confirmar resolución',
        'version'      => PLUGIN_ITHOSCONFIRMA_VERSION,
        'author'       => 'INTELLIHELP',
        'license'      => 'GPLv3+',
        'homepage'     => 'https://ithos.intellihelp.tech',
        'requirements' => [
            'glpi' => ['min' => '12.0.0', 'max' => '12.0.99'],
        ],
    ];
}

function plugin_ithosconfirma_check_prerequisites()
{
    return true;
}

function plugin_ithosconfirma_check_config($verbose = false)
{
    return true;
}

function plugin_init_ithosconfirma()
{
    global $PLUGIN_HOOKS;

    $PLUGIN_HOOKS['csrf_compliant']['ithosconfirma'] = true;
    // En las dos interfaces: la simplificada (la que usa el cliente) y la estándar.
    $PLUGIN_HOOKS['add_javascript']['ithosconfirma'][] = 'js/confirmar.js';
    $PLUGIN_HOOKS['add_css']['ithosconfirma'][]        = 'css/confirmar.css';
}
