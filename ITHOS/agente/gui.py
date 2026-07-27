#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI del Agente ITHOS — app de escritorio profesional (mismo lenguaje visual que el panel web:
comun/estilo_ithos.py). Usa pywebview: HTML/CSS/JS en la ventana NATIVA de cada SO (WebView2 en
Windows, WebKit/Cocoa en macOS, GTK/WebKit2 en Linux) → multiplataforma.

Diseño de nivel producto (estilo Meta/Anthropic/OpenAI): un HERO con el estado en vivo, credenciales
resumidas, y las opciones técnicas (actividad/log, desinstalar) escondidas en "Opciones avanzadas".
La VERSIÓN del agente y del Gestor están siempre visibles. El agente corre en 2do plano como proceso
`--run` DESACOPLADO (sobrevive al cierre de la ventana); si no hay entorno gráfico, cae al menú de
consola. Doc pywebview: https://pywebview.flowrl.com/guide/
"""
import os
import sys
import time
import json
import asyncio
import logging
import importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # para importar comun/

log = logging.getLogger("agente.gui")


def _A():
    """Módulo del agente (config, conexión, ciclo de vida). Import perezoso para evitar ciclos."""
    import agente
    return agente


def _version_agente():
    try:
        from comun import version as VER
        return VER.AGENTE_VERSION
    except Exception:  # noqa: BLE001
        return ""


class Api:
    """Puente entre el HTML (JS) y el agente (Python). Cada método se llama desde el front."""

    # -- estado / configuración --
    def estado(self):
        A = _A()
        cfg = A._leer_cfg()
        conf = bool(cfg.get("api_key") and cfg.get("agente_token"))
        return {"configurado": conf, "corriendo": bool(A.agente_corriendo()),
                "version": _version_agente(),
                "api_key": A._mask(cfg.get("api_key", "")) if conf else "",
                "agente_token": A._mask(cfg.get("agente_token", "")) if conf else "",
                "central_url": cfg.get("central_url", A.CENTRAL_URL_DEFECTO),
                "salud": self._salud()}

    def _salud(self):
        """Salud del agente headless (la deja en estado.json). Si el archivo está viejo (>45s) o no
        está, se considera desconectado."""
        A = _A()
        try:
            with open(A._estado_file(), encoding="utf-8") as f:
                d = json.load(f)
            if not A.agente_corriendo() or (time.time() - d.get("ts", 0)) > 45:
                return {"conectado": False}
            return {"conectado": bool(d.get("conectado")), "microfono": bool(d.get("microfono")),
                    "mic_habilitado": bool(d.get("mic_habilitado")),
                    "integrador": bool(d.get("integrador")),
                    "integrador_tipo": d.get("integrador_tipo", ""),
                    "voz": bool(d.get("voz")), "gestor_version": d.get("gestor_version", ""),
                    "empresa": d.get("empresa", "")}
        except Exception:  # noqa: BLE001
            return {"conectado": False}

    def config_editar(self):
        """Config REAL (sin enmascarar) para PRE-LLENAR el formulario al Editar: es la config del
        PROPIO equipo del usuario, así no tiene que reescribir todo cada vez."""
        cfg = _A()._leer_cfg()
        return {"api_key": cfg.get("api_key", ""), "agente_token": cfg.get("agente_token", ""),
                "central_url": cfg.get("central_url", _A().CENTRAL_URL_DEFECTO)}

    def guardar_y_probar(self, api_key, agente_token, central_url):
        A = _A()
        cfg0 = A._leer_cfg()
        # Si un campo se deja vacío al editar, se CONSERVA el valor guardado (no hay que retipear todo).
        api_key = (api_key or "").strip() or cfg0.get("api_key", "")
        agente_token = (agente_token or "").strip() or cfg0.get("agente_token", "")
        central_url = (central_url or "").strip() or cfg0.get("central_url", "") or A.CENTRAL_URL_DEFECTO
        if not api_key or not agente_token:
            return {"ok": False, "msg": "Falta la API key o la contraseña de agente."}
        cfg = {"central_url": central_url, "api_key": api_key, "agente_token": agente_token}
        try:
            ok = asyncio.run(A._probar_conexion(cfg))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": f"No se pudo conectar con el Gestor: {e}"}
        if not ok:
            return {"ok": False, "msg": "El Gestor rechazó las credenciales (API key o contraseña)."}
        A._guardar_cfg(cfg)
        return {"ok": True, "msg": "Conectado y guardado. ITHOS ya está en marcha."}

    # -- correr / frenar el agente EN 2do PLANO (proceso desacoplado, sobrevive al cierre) --
    def arrancar(self):
        A = _A()
        cfg = A._leer_cfg()
        if not (cfg.get("api_key") and cfg.get("agente_token")):
            return {"ok": False, "msg": "Configurá el equipo primero."}
        # Arranque LIMPIO: frenamos lo que haya (un proceso COLGADO, o un PID viejo) y relanzamos, para
        # que 'Arrancar' SIEMPRE deje el agente corriendo de verdad — nunca un no-op sobre un proceso
        # muerto/trabado que dejaba la GUI en 'Conectando…'. El nuevo proceso reintenta tomar el lock.
        A.detener_headless()
        time.sleep(0.4)
        A.lanzar_headless()
        return {"ok": True, "msg": "ITHOS en marcha (sigue activo aunque cierres esta ventana)."}

    def detener(self):
        _A().detener_headless()
        return {"ok": True, "msg": "ITHOS detenido."}

    def logs(self):
        return _A().leer_log(200)

    def limpiar_cache(self):
        """Borra TODO el caché de VOZ del agente (los saludos ya generados) y lo regenera desde cero:
        frena el agente, borra la carpeta voz_cache y lo vuelve a arrancar -> el baseline re-cachea todo.
        NO toca las credenciales, el perfil de voz (voz-id) ni nada del cliente."""
        import shutil
        A = _A()
        corria = bool(A.agente_corriendo())
        A.detener_headless()                     # frenar para borrar sin archivos en uso
        try:
            d = A._dir_cache_voz()
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            if corria:
                A.lanzar_headless()
            return {"ok": False, "msg": f"No se pudo borrar el caché: {e}"}
        if corria:
            A.lanzar_headless()                  # re-arranca -> el baseline regenera todos los saludos
        return {"ok": True, "msg": "Caché borrado. ITHOS está regenerando todos los saludos desde cero."}

    def detectar_nuevos(self):
        """Detecta las personas NUEVAS de la empresa (relee la DB/API según el sistema del cliente) y
        cachea SOLO las que falten — las ya cacheadas se conservan (el pre-cacheo saltea lo que ya está).
        Reinicia el agente SIN borrar el caché: el baseline re-descubre el roster y genera únicamente los
        saludos nuevos. Ideal cuando entran empleados nuevos, sin re-generar todo."""
        A = _A()
        if not A.agente_corriendo():
            A.lanzar_headless()
            return {"ok": True, "msg": "ITHOS arrancado: detectando personas y cacheando las que falten."}
        A.detener_headless()
        A.lanzar_headless()                      # re-baseline: descubre nuevos y cachea SOLO los que faltan
        return {"ok": True, "msg": "Detectando personas nuevas y cacheando solo las que falten "
                                   "(las ya cacheadas se conservan)."}

    # -- desinstalar / mover a otra PC --
    def desinstalar(self):
        A = _A()
        A.detener_headless()
        A._quitar_autoarranque()
        A._borrar_datos()        # borra SOLO config + caché del agente: no deja rastro
        return {"ok": True, "msg": "Equipo limpio (sin rastro). Instalá ITHOS en la otra PC con la "
                                   "misma API key + contraseña."}


def _html():
    from comun.estilo_ithos import ESTILO, FUENTES
    cuerpo = r"""
<div class=wrap>
  <header class=appbar>
    <div class=brand><div class=reactor></div>
      <div><b>ITHOS</b><span>Agente de acceso por voz</span></div></div>
    <div class=appbar-r><span class="pill" id=pill>…</span></div>
  </header>

  <!-- HERO: estado en vivo, el foco de la app -->
  <section class="panel hero" id=hero>
    <div class=hero-row>
      <div class=hero-txt>
        <div class=hero-title id=heroTitle>ITHOS</div>
        <div class=hero-sub id=heroSub>—</div>
      </div>
      <div class=hero-act>
        <button class=btn id=bstart onclick="arrancar()">▶ Arrancar</button>
        <button class="btn ghost" id=bstop onclick="detener()">■ Detener</button>
      </div>
    </div>
    <div id=salud class=salud></div>
  </section>

  <!-- CONEXIÓN con la empresa -->
  <section class="panel" id=connCard>
    <div class=cardhd>
      <div><div class=ctitle>Conexión con la empresa</div>
        <div class=hint id=connHint>Pegá la API key y la contraseña de agente que te dio INTELLIHELP.</div></div>
      <button class="btn sm ghost" id=btnEditar onclick="toggleConn()" style="display:none">Editar</button>
    </div>
    <div id=connFields>
      <div class="f full"><label>API key de la empresa</label><input id=api placeholder="EMPRESA-xxxxxxxxxxxx" autocomplete=off spellcheck=false></div>
      <div class="f full"><label>Contraseña de agente</label><input id=tok type=password placeholder="la contraseña que te pasamos" autocomplete=off spellcheck=false></div>
      <div class="f full"><label>Gestor (dejalo así salvo que te digamos otro)</label><input id=url spellcheck=false></div>
      <div class=row style="margin-top:14px"><button class=btn id=bsave onclick="guardar()">Probar y guardar</button></div>
      <div class=msg id=msg></div>
    </div>
  </section>

  <!-- OPCIONES AVANZADAS (técnicas): ocultas para el usuario final -->
  <section class="panel adv">
    <button class=disclosure type=button onclick="toggleAdv()">
      <span>Opciones avanzadas</span><span class=caret id=advCaret>▸</span></button>
    <div id=advBody style="display:none">
      <div class=hint style="margin-top:12px">Actividad técnica en vivo (para soporte). El uso normal no la necesita.</div>
      <pre id=logbox>—</pre>
      <div class=sec style="margin-top:14px"><span>Caché de voz</span></div>
      <div class=hint><b>Detectar personas nuevas</b>: relee tu sistema (IVMS/HikCentral/BioStar/ZKTeco/Honeywell) y cachea SOLO los empleados nuevos — los ya cacheados se conservan (ideal cuando entra gente nueva, sin regenerar todo). <b>Regenerar todo</b>: borra y recrea desde cero. Los archivos llevan el <b>nombre de la persona y el saludo</b> para identificarlos. <b>No toca</b> tus credenciales ni el reconocimiento de tu voz.</div>
      <div class=row><button class="btn sm" onclick="detectarNuevos()">＋ Detectar personas nuevas</button>
        <button class="btn sm ghost" onclick="borrarCache()">↻ Regenerar todo desde cero</button></div>
      <div class=msg id=msgc></div>
      <div class=sec style="margin-top:14px"><span>Mover a otra PC / desinstalar</span></div>
      <div class=hint>Borra las credenciales y el caché de este equipo y quita el arranque automático. Después instalás ITHOS en la otra PC con la misma API key + contraseña. <b>No toca</b> tu sistema de tickets ni tus fichadas.</div>
      <div class=row><button class="btn sm danger" onclick="desinstalar()">Eliminar de esta PC</button></div>
      <div class=msg id=msg3></div>
    </div>
  </section>

  <footer class=foot id=foot></footer>
</div>
<div class=toast id=toast></div>
<script>
const $=s=>document.querySelector(s);
let PRIMERA=true, EDIT=false;
function toast(m){let t=$('#toast');t.textContent=m;t.style.display='block';clearTimeout(window._tt);window._tt=setTimeout(()=>t.style.display='none',2600)}
async function api(m,...a){return await window.pywebview.api[m](...a)}
function setPill(st){const p=$('#pill');
  if(st.corriendo){p.className='pill live';p.textContent='● EN MARCHA'}
  else if(st.configurado){p.className='pill on';p.textContent='● CONFIGURADO'}
  else{p.className='pill off';p.textContent='○ SIN CONFIGURAR'}}
function spill(label,val){let c=val===true?'ok':(val===false?'err':'muted'),i=val===true?'●':(val===false?'○':'◌');
  return `<span class="pill ${c}">${i} ${label}</span>`}
function setSalud(st){
  const s=st.salud||{}, h=$('#salud');
  // Título/subtítulo del HERO según el estado
  if(!st.configurado){$('#heroTitle').textContent='Configurá tu equipo';$('#heroSub').textContent='Pegá tu API key y contraseña abajo para conectar con el Gestor.';h.innerHTML='';return}
  if(!st.corriendo){$('#heroTitle').textContent='ITHOS está detenido';$('#heroSub').textContent='Tocá Arrancar para que ITHOS empiece a trabajar.';h.innerHTML='';return}
  if(!s.conectado){$('#heroTitle').textContent='Conectando…';$('#heroSub').textContent='ITHOS arrancó y está conectando con el Gestor.';h.innerHTML='<div class=salud-row>'+spill('Gestor',false)+'</div>';return}
  $('#heroTitle').textContent=(s.empresa? s.empresa : 'ITHOS')+' · activo';
  let pills=[spill('Gestor',true)];
  if(s.integrador_tipo)pills.push(spill('Control de acceso',s.integrador));
  if(s.mic_habilitado)pills.push(spill('Micrófono',s.microfono));
  pills.push(spill('Voz',s.voz));
  let faltan=(s.integrador_tipo&&!s.integrador)||(s.mic_habilitado&&!s.microfono)||(!s.voz);
  $('#heroSub').textContent=faltan?'Hay un componente sin arrancar (en rojo).':'Todo funcionando al 100%. ITHOS está atendiendo.';
  h.innerHTML='<div class=salud-row>'+pills.join(' ')+'</div>';
}
function setConn(st){
  // Si ya está configurado, mostramos las credenciales enmascaradas y colapsamos el formulario.
  if(st.configurado && !EDIT){
    $('#connFields').style.display='none';$('#btnEditar').style.display='';
    $('#connHint').innerHTML='Conectado como <b>'+ (st.api_key||'—') +'</b> · Gestor '+ (st.central_url||'');
  }else{
    $('#connFields').style.display='';$('#btnEditar').style.display=st.configurado?'':'none';
    $('#connHint').textContent='Pegá la API key y la contraseña de agente que te dio INTELLIHELP.';
    if(st.configurado){if(!$('#api').value)$('#api').placeholder=st.api_key; if(!$('#tok').value)$('#tok').placeholder=st.agente_token;}
  }
  if(!$('#url').value)$('#url').value=st.central_url;
}
function setFoot(st){let g=(st.salud&&st.salud.gestor_version)?(' · Gestor v'+st.salud.gestor_version):'';
  $('#foot').textContent='ITHOS Agente v'+(st.version||'')+g+' · INTELLIHELP S.A.';}
async function toggleConn(){EDIT=!EDIT;
  if(EDIT){ // al Editar, pre-llenamos con la config REAL guardada (no hay que reescribir todo)
    try{const c=await api('config_editar');$('#api').value=c.api_key||'';$('#tok').value=c.agente_token||'';$('#url').value=c.central_url||'';}catch(e){}
  }
  refrescar();}
function toggleAdv(){let b=$('#advBody'),on=b.style.display==='none';b.style.display=on?'block':'none';$('#advCaret').textContent=on?'▾':'▸';}
async function refrescar(){const st=await api('estado');setPill(st);setSalud(st);setConn(st);setFoot(st);
  $('#bstop').disabled=!st.corriendo;$('#bstart').disabled=st.corriendo;}
// AUTO-ARRANQUE profesional y ROBUSTO: al abrir la app, si el equipo está configurado pero ITHOS no
// corre, lo arrancamos solo (una sola vez), así el usuario no tiene que apretar "Arrancar" cada vez.
async function autoArranque(){
  if(!PRIMERA)return; PRIMERA=false;
  try{const st=await api('estado');
    if(st.configurado && !st.corriendo){toast('Iniciando ITHOS…');await api('arrancar');
      setTimeout(()=>{refrescar();tickLogs()},900);}
  }catch(e){}
}
async function guardar(){const b=$('#bsave');b.disabled=true;$('#msg').textContent='Probando conexión…';$('#msg').className='msg';
  const r=await api('guardar_y_probar',$('#api').value,$('#tok').value,$('#url').value);
  $('#msg').textContent=r.msg;$('#msg').className='msg '+(r.ok?'ok':'bad');b.disabled=false;
  if(r.ok){EDIT=false; await api('arrancar');}     // al guardar bien, arranca solo
  setTimeout(()=>{refrescar();tickLogs()},700);toast(r.msg);}
async function arrancar(){const r=await api('arrancar');toast(r.msg);setTimeout(()=>{refrescar();tickLogs()},700);}
async function detener(){const r=await api('detener');toast(r.msg);setTimeout(refrescar,600);}
async function borrarCache(){if(!confirm('¿Borrar todos los saludos cacheados y regenerarlos desde cero?'))return;
  $('#msgc').textContent='Borrando y regenerando…';$('#msgc').className='msg';
  const r=await api('limpiar_cache');$('#msgc').textContent=r.msg;$('#msgc').className='msg '+(r.ok?'ok':'bad');toast(r.msg);setTimeout(()=>{refrescar();tickLogs()},900);}
async function detectarNuevos(){$('#msgc').textContent='Detectando personas nuevas…';$('#msgc').className='msg';
  const r=await api('detectar_nuevos');$('#msgc').textContent=r.msg;$('#msgc').className='msg '+(r.ok?'ok':'bad');toast(r.msg);setTimeout(()=>{refrescar();tickLogs()},900);}
async function desinstalar(){if(!confirm('¿Eliminar ITHOS de esta PC? Vas a poder instalarlo en otra con la misma API key + contraseña.'))return;
  const r=await api('desinstalar');$('#msg3').textContent=r.msg;$('#msg3').className='msg '+(r.ok?'ok':'bad');$('#api').value='';$('#tok').value='';EDIT=false;refrescar();toast(r.msg);}
async function tickLogs(){try{const l=await api('logs');const box=$('#logbox');
  box.textContent=(l&&l.length)?l.join(''):'— (sin actividad todavía)';box.scrollTop=box.scrollHeight;}catch(e){}
  const st=await api('estado');setPill(st);setSalud(st);setConn(st);setFoot(st);$('#bstop').disabled=!st.corriendo;$('#bstart').disabled=st.corriendo;}
let BOOTED=false;
async function boot(){ if(BOOTED)return; BOOTED=true;
  await refrescar(); tickLogs(); setInterval(tickLogs,2500);
  autoArranque();          // arranca solo si está configurado y no corre
}
window.addEventListener('pywebviewready',boot);
setTimeout(()=>{if(window.pywebview)boot();},700);
</script>
"""
    css = ESTILO + """
      .appbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:18px}
      .appbar .brand b{font-family:'Orbitron',sans-serif;font-size:20px;color:#eafcff;letter-spacing:3px}
      .appbar .brand span{display:block;font-size:10.5px;color:var(--muted);letter-spacing:2px}
      .hero{margin-bottom:16px}
      .hero-row{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
      .hero-title{font-family:'Orbitron',sans-serif;font-size:clamp(18px,3.4vw,24px);color:#eafcff;letter-spacing:1px}
      .hero-sub{color:var(--muted);font-size:13.5px;margin-top:4px;line-height:1.5}
      .hero-act{display:flex;gap:10px;flex-wrap:wrap}
      .salud{margin-top:14px}
      .salud-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
      .cardhd{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
      .ctitle{font-family:'Orbitron',sans-serif;font-size:13px;letter-spacing:2px;color:var(--cyan);text-transform:uppercase;margin-bottom:6px}
      .disclosure{width:100%;background:none;border:0;color:var(--muted);cursor:pointer;font-family:'Rajdhani',sans-serif;
        font-weight:700;letter-spacing:1.5px;text-transform:uppercase;font-size:12px;display:flex;justify-content:space-between;align-items:center;padding:2px 0}
      .disclosure:hover{color:var(--txt)}
      .caret{color:var(--cyan)}
      .adv{background:rgba(9,20,36,.45)}
      .msg{margin-top:12px;font-size:13px;min-height:18px;color:var(--muted)}
      .msg.ok{color:var(--ok)} .msg.bad{color:var(--danger)}
      .foot{text-align:center;color:var(--muted);font-size:11.5px;letter-spacing:1.5px;margin:22px 0 6px;opacity:.85}
      body .wrap{width:100%;max-width:min(760px,94vw);margin:0 auto;padding:clamp(18px,4vw,40px) clamp(14px,3vw,28px)}
      #logbox{height:clamp(150px,24vh,240px);white-space:pre-wrap;font-size:11.5px}
      @media (max-width:560px){ .appbar .brand b{font-size:18px} .hero-act{width:100%}
        .hero-act .btn{flex:1} .btn{width:100%} .row{flex-direction:column} .cardhd{flex-direction:column} }
    """
    return ("<!doctype html><html lang=es><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            "<title>ITHOS Agente</title>" + FUENTES +
            "<style>" + css + "</style></head><body>" + cuerpo + "</body></html>")


def disponible():
    """True si se puede abrir una ventana GUI (hay pywebview + entorno gráfico)."""
    if importlib.util.find_spec("webview") is None:
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return False
    return True


def lanzar():
    """Abre la ventana de la app (bloquea hasta que se cierra). El agente headless sigue corriendo aparte."""
    import webview
    webview.create_window("ITHOS Agente", html=_html(), js_api=Api(),
                          width=880, height=800, min_size=(720, 620),
                          background_color="#03060d")
    webview.start()
