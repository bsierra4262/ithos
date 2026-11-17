/*
 * ITHOS · Confirmar resolución.
 *
 * El botón «Aprobar» de la solución CIERRA el ticket. Antes de que lo haga, este cartel le dice al
 * cliente qué está por hacer. Si el comentario que escribió suena a que el problema sigue (#849:
 * «No puede fichar aún» + Aprobar), se lo muestra y le ofrece rechazar en su lugar.
 *
 * Escucha en `document` y en fase de captura: el formulario de aprobación llega por AJAX con la
 * línea de tiempo, así que no existe cuando carga la página.
 */
(function () {
    'use strict';

    // Frases que dicen que el problema NO se resolvió. Sólo deciden si se muestra la advertencia:
    // el cartel aparece siempre, y quien decide es la persona.
    var SIGUE = new RegExp([
        '\\bno\\s+(puede|pueden|pude|pudo|pudimos|anda|andan|funciona|funcionan|sirve|resolvi|se\\s+resolvi|est[aá]|qued[oó]|me\\s+deja|le\\s+deja)',
        '\\bsigue|\\bsiguen|\\bsegu[ií]mos',
        '\\btodav[ií]a\\b', '\\ba[uú]n\\b',
        '\\bpersiste', '\\botra\\s+vez\\b', '\\bde\\s+nuevo\\b',
        '\\bnada\\b', '\\bigual\\b',
        '\\berror\\b', '\\bfalla'
    ].join('|'), 'i');

    function comentario(form) {
        var ta = form && form.querySelector('textarea[name="content"]');
        if (!ta) {
            return '';
        }
        var ed = window.tinymce && ta.id ? window.tinymce.get(ta.id) : null;
        var txt = ed ? ed.getContent({ format: 'text' }) : (ta.value || '');
        return txt.replace(/\s+/g, ' ').trim();
    }

    function enfocarComentario(form) {
        var ta = form.querySelector('textarea[name="content"]');
        var ed = window.tinymce && ta && ta.id ? window.tinymce.get(ta.id) : null;
        if (ed) {
            ed.focus();
        } else if (ta) {
            ta.focus();
        }
    }

    function el(tag, clase, texto) {
        var n = document.createElement(tag);
        if (clase) {
            n.className = clase;
        }
        if (texto) {
            n.textContent = texto;   // nunca innerHTML con lo que escribió el usuario
        }
        return n;
    }

    function cartel(form, aprobar) {
        var dijo = comentario(form);
        var sigue = SIGUE.test(dijo);
        var rechazar = form.querySelector('button[name="add_reopen"]');

        var fondo = el('div', 'ithos-conf-fondo');
        var caja = el('div', 'ithos-conf-caja' + (sigue ? ' ithos-conf-alerta' : ''));
        caja.setAttribute('role', 'alertdialog');
        caja.setAttribute('aria-modal', 'true');
        caja.setAttribute('aria-labelledby', 'ithos-conf-titulo');

        var titulo = el('h2', 'ithos-conf-titulo', 'Estás confirmando la resolución del ticket');
        titulo.id = 'ithos-conf-titulo';
        caja.appendChild(el('div', 'ithos-conf-icono', sigue ? '!' : '✓'));
        caja.appendChild(titulo);
        caja.appendChild(el('p', 'ithos-conf-texto',
            'Al confirmar, el ticket se CIERRA y el problema queda dado por solucionado. ' +
            'Confirmá sólo si ya funciona correctamente.'));

        if (sigue) {
            var aviso = el('div', 'ithos-conf-aviso');
            aviso.appendChild(el('strong', '', 'Escribiste: '));
            aviso.appendChild(el('span', 'ithos-conf-cita', '«' + dijo.slice(0, 200) + '»'));
            aviso.appendChild(el('p', '',
                'Parece que el problema sigue. Si es así, no confirmes: tocá «No, el problema sigue» ' +
                'y lo volvemos a revisar.'));
            caja.appendChild(aviso);
        }

        var botones = el('div', 'ithos-conf-botones');
        var si = el('button', 'ithos-conf-si', 'Sí, está resuelto. Cerrar el ticket');
        var no = el('button', 'ithos-conf-no', 'No, el problema sigue');
        var volver = el('button', 'ithos-conf-volver', 'Volver');
        [si, no, volver].forEach(function (b) {
            b.type = 'button';
        });
        botones.appendChild(si);
        botones.appendChild(no);
        botones.appendChild(volver);
        caja.appendChild(botones);
        fondo.appendChild(caja);
        document.body.appendChild(fondo);
        document.body.classList.add('ithos-conf-abierto');

        function cerrar() {
            document.removeEventListener('keydown', teclas, true);
            document.body.classList.remove('ithos-conf-abierto');
            fondo.remove();
        }

        function teclas(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                cerrar();
                aprobar.focus();
            }
            if (e.key === 'Tab') {      // el foco no se escapa del cartel
                var f = [si, no, volver];
                var i = f.indexOf(document.activeElement);
                e.preventDefault();
                f[(i + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus();
            }
        }

        si.addEventListener('click', function () {
            cerrar();
            aprobar.dataset.ithosConfirmado = '1';
            aprobar.click();                       // el envío original de GLPI, con su botón
        });
        no.addEventListener('click', function () {
            cerrar();
            if (rechazar && comentario(form)) {
                rechazar.click();                  // ya explicó qué pasa: se rechaza
            } else {
                // Rechazar exige un comentario: se lo pedimos en vez de dejar que GLPI dé error.
                var hint = form.querySelector('.ithos-conf-hint');
                if (!hint) {
                    hint = el('div', 'ithos-conf-hint',
                        'Contanos qué sigue pasando y tocá «Rechazar». Si podés, adjuntá una foto o un video del error.');
                    (rechazar ? rechazar.parentNode : form).insertBefore(hint, rechazar || null);
                }
                enfocarComentario(form);
            }
        });
        volver.addEventListener('click', function () {
            cerrar();
            aprobar.focus();
        });
        fondo.addEventListener('click', function (e) {
            if (e.target === fondo) {
                cerrar();
            }
        });
        document.addEventListener('keydown', teclas, true);
        (sigue ? no : si).focus();
    }

    document.addEventListener('click', function (e) {
        var aprobar = e.target.closest && e.target.closest('button[name="add_close"]');
        if (!aprobar || !aprobar.form) {
            return;
        }
        if (aprobar.dataset.ithosConfirmado === '1') {
            delete aprobar.dataset.ithosConfirmado;   // pasa una sola vez
            return;
        }
        e.preventDefault();
        e.stopImmediatePropagation();
        cartel(aprobar.form, aprobar);
    }, true);
}());
