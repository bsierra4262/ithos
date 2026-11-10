# -*- coding: utf-8 -*-
"""Interfaz web (HUD estilo Iron Man / ITHOS). Superadmin + Alta + Portal cliente.
Todo elegible por cliente: sistema de tickets, canales de aviso y control de acceso."""

from comun.estilo_ithos import ESTILO as _ESTILO  # noqa: E402  (diseño compartido con el agente)

# --- Constructor de formulario COMPLETO (compartido: admin, alta, portal) ---
_FORM_JS = r"""
let CATS={integradores:{},tickets:{},canales:{},ia:{}};
const $=s=>document.querySelector(s);
function esc(s){return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
async function loadCats(){
 let [i,t,c,a]=await Promise.all([fetch('/api/integradores'),fetch('/api/tickets'),fetch('/api/canales'),fetch('/api/ia_proveedores')]);
 CATS.integradores=await i.json();CATS.tickets=await t.json();CATS.canales=await c.json();CATS.ia=await a.json();
}
function catLabel(cat,t){return (CATS[cat]&&CATS[cat][t]&&CATS[cat][t].label)||t||'—'}
function tipoInteg(c){return (c&&typeof c.integrador==='object'&&c.integrador)?(c.integrador.tipo||'ninguno'):((c&&c.integrador)||'ninguno')}
function tipoTicket(c){ if(c&&c.tickets&&c.tickets.tipo) return c.tickets.tipo;
 if(c&&c.integrador_glpi&&c.integrador_glpi.glpi_url) return 'glpi';   // cliente GLPI existente
 return 'ninguno'; }                                                    // alta nueva -> sin sistema por defecto
function integName(t){return catLabel('integradores',t)}

// Los grupos de WhatsApp por tema: filas de (nombre del grupo, de qué es).
// Se guardan como [{grupo, ambito}] — la misma forma que lee el Gestor.
function filaGrupo(pref,g,ops){
 let sel=ops.map(o=>`<option value="${o[0]}" ${o[0]===(g.ambito||'')?'selected':''}>${esc(o[1])}</option>`).join('');
 return `<div class=grupo-fila style="display:flex;gap:8px;margin-bottom:6px">
   <input class="${pref}g-nombre" style="flex:1" value="${esc(g.grupo||'')}" placeholder="Nombre exacto del grupo">
   <select class="${pref}g-ambito" style="flex:1.4">${sel}</select>
   <button type=button class="btn sm ghost" onclick="this.parentNode.remove()" title="Quitar">✕</button></div>`;
}
function agregarGrupo(pref){
 let host=$('#'+pref+'grupos'), ops=window['_ops_'+pref]||[];
 host.insertAdjacentHTML('beforeend', filaGrupo(pref,{ambito:ops.length?ops[0][0]:''},ops));
}
function leerGrupos(pref){
 let host=$('#'+pref+'grupos'); if(!host) return [];
 return [...host.querySelectorAll('.grupo-fila')].map(f=>({
   grupo:f.querySelector('.'+pref+'g-nombre').value.trim(),
   ambito:f.querySelector('.'+pref+'g-ambito').value})).filter(g=>g.grupo);
}

// Render genérico de una lista de campos {k,l,t,ph} con ids `${pref}${k}`
function campoInput(pref,f,val){
 let v = (f.t==='list' && Array.isArray(val)) ? val.join(', ') : (val==null?'':val);
 let ayuda = f.d ? `<div class="hint" style="margin:4px 0 0;font-size:12px">${esc(f.d)}</div>` : '';
 if(f.t==='grupos'){
   let ops=f.opciones||[]; window['_ops_'+pref]=ops;
   let filas=(Array.isArray(val)?val:[]).map(g=>filaGrupo(pref,g||{},ops)).join('');
   return `<div class=f><label>${f.l}</label><div id="${pref}${f.k}">${filas}</div>
     <button type=button class="btn sm ghost" style="margin-top:4px" onclick="agregarGrupo('${pref}')">+ Agregar grupo</button>${ayuda}</div>`;
 }
 if(f.t==='select'){
   let ops=(f.opciones||[]).map(o=>`<option ${String(o)===String(v)?'selected':''}>${o}</option>`).join('');
   return `<div class=f><label>${f.l}</label><select id="${pref}${f.k}">${ops}</select>${ayuda}</div>`;
 }
 return `<div class=f><label>${f.l}</label><input id="${pref}${f.k}" type="${f.t==='number'?'number':(f.t==='password'?'password':'text')}" value="${esc(v)}" placeholder="${f.ph||''}">${ayuda}</div>`;
}
function renderCampos(hostSel,cat,tipo,pref,vals){
 let campos=(CATS[cat]&&CATS[cat][tipo]&&CATS[cat][tipo].campos)||[];
 $(hostSel).innerHTML = campos.length ? ('<div class=form style="padding:0">'+campos.map(f=>campoInput(pref,f,(vals||{})[f.k])).join('')+'</div>')
   : '';   // 'Ninguno' u opciones sin datos: no mostramos nada (más limpio que 'Sin campos.')
}
function readCampos(cat,tipo,pref){
 let campos=(CATS[cat]&&CATS[cat][tipo]&&CATS[cat][tipo].campos)||[], out={};
 campos.forEach(f=>{
   if(f.t==='grupos'){let g=leerGrupos(pref); if(g.length)out[f.k]=g; return;}
   let e=$('#'+pref+f.k); if(!e)return; let v=e.value;
   if(f.t==='number')out[f.k]=+v||0; else if(f.t==='list')out[f.k]=v.split(',').map(x=>x.trim()).filter(Boolean); else if(v)out[f.k]=v;});
 return out;
}

function optList(cat,sel){return Object.entries(CATS[cat]).map(([k,v])=>`<option value="${k}" ${k===sel?'selected':''}>${v.label}</option>`).join('')}

function formHTML(c,admin){
 c=c||{}; let ia=c.ia||{}, gl=c.integrador_glpi||{}, t=tipoInteg(c), tkt=tipoTicket(c),
 icfg=c.integrador_config||(typeof c.integrador==='object'?c.integrador:{})||{};
 let idis=['es-AR','es-ES','en','pt-BR','fr','it'].map(x=>`<option ${x===(c.idioma||'es-AR')?'selected':''}>${x}</option>`).join('');
 // Zonas horarias del MUNDO por región (IANA). El horario del cliente rige la hora de sus reportes y
 // los reinicios de cuota, sin importar dónde esté alojado el servidor. Se agregan por optgroup.
 let ZONAS={
  'Argentina y Sudamérica':['America/Argentina/Buenos_Aires','America/Argentina/Cordoba','America/Argentina/Mendoza','America/Montevideo','America/Santiago','America/Asuncion','America/Sao_Paulo','America/La_Paz','America/Bogota','America/Lima','America/Caracas','America/Guayaquil'],
  'Norteamérica y Centroamérica':['America/Mexico_City','America/Tijuana','America/New_York','America/Chicago','America/Denver','America/Phoenix','America/Los_Angeles','America/Toronto','America/Guatemala','America/Costa_Rica','America/Panama','America/Santo_Domingo'],
  'Europa':['Europe/Madrid','Europe/Lisbon','Europe/London','Europe/Paris','Europe/Berlin','Europe/Rome','Europe/Amsterdam','Europe/Athens','Europe/Moscow'],
  'Asia y Oriente Medio':['Asia/Jerusalem','Asia/Dubai','Asia/Karachi','Asia/Kolkata','Asia/Bangkok','Asia/Shanghai','Asia/Singapore','Asia/Tokyo','Asia/Seoul','Asia/Manila'],
  'África':['Africa/Casablanca','Africa/Lagos','Africa/Cairo','Africa/Johannesburg','Africa/Nairobi'],
  'Oceanía':['Australia/Perth','Australia/Sydney','Pacific/Auckland'],
  'Otros':['UTC']};
 let _zactual=(c.zona_horaria||'America/Argentina/Buenos_Aires');
 let zsel=Object.entries(ZONAS).map(([g,zs])=>`<optgroup label="${g}">`+
   zs.map(z=>`<option ${z===_zactual?'selected':''}>${z}</option>`).join('')+'</optgroup>').join('');
 let secProv=(ia.secundario&&ia.secundario.proveedor)||'';
 let sec2=Object.entries(CATS.ia).map(([k,v])=>`<option value="${k}" ${k===secProv?'selected':''}>${v.label}</option>`).join('');
 let terProv=(ia.terciario&&ia.terciario.proveedor)||'';
 let sec3=Object.entries(CATS.ia).map(([k,v])=>`<option value="${k}" ${k===terProv?'selected':''}>${v.label}</option>`).join('');
 let vm=ia.voz_motor||'charon'; let rp=c.reportes||{};
 let pr=c.proactivo||{}; let an=c.anomalias||{};
 return `<div class=form id=jform>
   <div class="f full"><label>Nombre de la empresa</label><input id=f_nombre value="${esc(c.nombre)}" placeholder="INTELLIHELP S.A."></div>
   <div class=f><label>Email de contacto (también se usa para la facturación)</label><input id=f_email type=email value="${esc(c.email)}" placeholder="soporte@empresa.com"></div>
   <div class=f><label>Idioma de la voz</label><select id=f_idioma>${idis}</select></div>
   <div class=f><label>Zona horaria (tu región · rige la hora de tus reportes)</label><select id=f_zona onchange="if($('#f_rep_zona'))$('#f_rep_zona').value=this.value">${zsel}</select></div>
   <div class="f full"><label>API key del agente</label><div class=withbtn>
     <input id=f_key value="${esc(c.api_key)}" placeholder="se genera sola" ${c.api_key?'readonly':''}>
     <button class="btn sm" type=button onclick="genKey()">Generar</button></div></div>
   ${c.api_key?`<div class="f full"><label>Contraseña de agente (para instalar el agente en la PC del cliente)</label>
     <div class=withbtn><input id=f_atok value="${esc(c.agente_token||'')}" placeholder="se genera sola con la empresa" readonly>
     <button class="btn sm" type=button onclick="navigator.clipboard.writeText(document.getElementById('f_atok').value);toast('Contraseña copiada')">Copiar</button></div>
     <div class=hint>El agente entra con la <b>api_key + esta contraseña</b>. Pasásela al cliente para instalar el agente.</div></div>`:''}
   <div class=f><div class=chk style="margin-top:22px"><input type=checkbox id=f_activo ${c.activo!==false?'checked':''}><span>Empresa activa</span></div></div>

   <div class=sec><span>Inteligencia artificial · el cerebro de ITHOS</span></div>
   <div class="f full hint">Elegí hasta 3 IAs en cadena: la <b>primaria</b> responde siempre y, si se queda sin cuota, ITHOS <b>salta solo</b> a la 2ª y a la 3ª (sin cortes). Dejá el modelo en <b>auto</b> y ITHOS elige el mejor según tu clave (gratis o pago, lo detecta solo).</div>
   <div class=f><label>IA primaria (la que responde siempre)</label><select id=f_prov onchange="camposIAp()">${optList('ia',ia.proveedor||'gemini')}</select></div>
   <div class=f><label>IA secundaria (respaldo si se agota la cuota)</label>
     <select id=f_prov2 onchange="camposIAs()"><option value="">(ninguna — usar sólo una)</option>${sec2}</select></div>
   <div class="f full" id=iapHost></div>
   <div class="f full" id=iasHost></div>
   <div class=f><label>IA terciaria (2º respaldo, opcional)</label>
     <select id=f_prov3 onchange="camposIAt()"><option value="">(ninguna)</option>${sec3}</select></div>
   <div class="f full" id=iatHost></div>
   <div class="f full"><label>API key de Gemini — para la VOZ Charon</label>
     <input id=f_gem value="${esc(ia.gemini_api_key)}" placeholder="AIza... (la voz ITHOS es Charon/Gemini)"></div>
   <div class="f full"><label>Motor de voz</label><select id=f_vozmotor>
     <option value="charon" ${vm==='charon'?'selected':''}>Charon (Gemini) — si se agota, pasa a ITHOS gratis (edge-tts)</option>
     <option value="edge" ${vm==='edge'?'selected':''}>ITHOS gratis (edge-tts, neural) — siempre, sin cuota</option>
     <option value="windows" ${vm==='windows'?'selected':''}>Windows local (offline, básica) — siempre</option></select></div>
   <div class=f><label>Límite diario (cuota gratis Gemini)</label><input id=f_lim type=number value="${ia.limite_diario||200}"></div>
   <div class=f><label>Avisar al quedar</label><input id=f_av type=number value="${ia.avisar_en||15}"></div>
   <div class="f full"><div class=chk><input type=checkbox id=f_ilim ${ia.ilimitada?'checked':''}><span>Forzar plan PAGO (opcional — normalmente ITHOS detecta solo si la API es paga o gratis y elige el mejor modelo)</span></div></div>

   <div class=sec><span>Sistema de tickets · tu mesa de ayuda</span></div>
   <div class="f full hint">ITHOS lee y gestiona tus tickets: los clasifica, asigna, responde al cliente y cierra. Elegí el sistema que usás; si todavía no tenés uno, poné <b>Ninguno</b> y ITHOS igual funciona por voz y avisos.</div>
   <div class="f full"><label>¿Qué sistema de tickets usás?</label><select id=f_tkt onchange="camposTickets()">${optList('tickets',tkt)}</select></div>
   <div class="f full" id=tkHost></div>

   <div class=sec><span>Canales · dónde te habla y le hablás</span><button class="btn sm" type=button onclick="addCanal()">＋ Agregar canal</button></div>
   <div class="f full hint">Por dónde ITHOS te avisa y vos le escribís o le mandás un audio. Hoy el canal disponible es <b>WhatsApp</b>, con un grupo por tema: ahí mismo podés <b>pedirle acciones</b> (leer, cerrar, asignar o posponer un ticket) por texto o por audio.</div>
   <div class="f full" id=canalesHost></div>

   <div class=sec><span>Control de acceso · portero por voz</span></div>
   <div class="f full hint">Si tenés molinetes o lectores biométricos, ITHOS saluda por voz al fichar y avisa los fichajes fuera de horario. Compatible con IVMS, HikCentral, BioStar 2, ZKTeco y Honeywell. Si no tenés, dejá <b>Ninguno</b>.</div>
   <div class="f full"><label>¿Qué sistema de control de acceso usás?</label><select id=f_integ onchange="camposInteg()">${optList('integradores',t)}</select></div>
   <div class="f full" id=integCampos></div>

   <div id=depTerminales style="display:contents">
   <div class=sec style="border:0;margin:8px 0 4px"><span style="font-size:12px;color:var(--muted)">Terminales · qué dice en cada lector/puerta</span><button class="btn sm" type=button onclick="addTerminal()">＋ Agregar terminal</button></div>
   <div class="f full hint">Asigná a cada terminal si es de <b>entrada</b>, <b>salida</b> o <b>sala</b>, con qué frecuencia saluda y (opcional) un saludo propio. ITHOS reconoce la terminal por su nombre: escribí una parte del nombre del lector (en IVMS es el <i>device</i> de la base; en las demás marcas, el nombre o IP del lector). Si no configurás nada, entrada saluda 1 vez por día y "sala técnica" siempre.</div>
   <div class="f full" id=termDescubiertas></div>
   <div class="f full" id=termHost></div>
   </div>

   <div id=depTickets style="display:contents">
   <div class=sec><span>Reportes automáticos · ITIL 4</span></div>
   <div class="f full hint">ITHOS te manda solo el informe de tu mesa de ayuda (volumen, cumplimiento de SLA, MTTR, por técnico y categoría) en el día y la hora que elijas (en <b>tu</b> zona horaria), por tus canales, en PDF o CSV. Cada informe cubre el período <b>ya cerrado</b>: el <b>diario</b> es el día anterior, el <b>semanal</b> la semana pasada y el <b>mensual</b> el mes pasado, para que siempre traiga datos reales y completos (nunca vacío). Si activás <b>solo días hábiles</b>, el diario no se envía sábados ni domingos y el lunes cubre el fin de semana (no se pierde el viernes).</div>
   <div class=f><div class=chk style="margin-top:22px"><input type=checkbox id=f_rep_en ${rp.enabled?'checked':''}><span>Enviar reportes solos</span></div></div>
   <div class=f><label>Cada cuánto</label><select id=f_rep_frec onchange="repFrec()">
     ${[['diario','Todos los días'],['semanal','Una vez por semana'],['mensual','Una vez por mes']].map(x=>`<option value="${x[0]}" ${x[0]===(rp.frecuencia||'diario')?'selected':''}>${x[1]}</option>`).join('')}</select></div>
   <div class=f><label>A qué hora</label><input id=f_rep_hora type=time value="${esc(rp.hora||'09:00')}"></div>
   <div class=f><div class=chk style="margin-top:22px"><input type=checkbox id=f_rep_habil ${rp.dias_habiles?'checked':''}><span>Solo días hábiles (Lun a Vie)</span></div></div>
   <div class=f><label>Zona horaria del reporte (tu región)</label><select id=f_rep_zona onchange="if($('#f_zona'))$('#f_zona').value=this.value">${zsel}</select></div>
   <div class=f id=rep_diasem_box><label>Qué día de la semana</label><select id=f_rep_diasem>
     ${['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'].map((d,i)=>`<option value="${i}" ${i===(rp.dia_semana!=null?rp.dia_semana:0)?'selected':''}>${i+1} · ${d}</option>`).join('')}</select></div>
   <div class=f id=rep_diames_box><label>Qué día del mes (1 al 28)</label><input id=f_rep_diames type=number min=1 max=28 value="${rp.dia_mes!=null?rp.dia_mes:1}"></div>
   <div class=f><div class=chk style="margin-top:22px"><input type=checkbox id=f_rep_pdf ${(rp.formato||['pdf']).includes('pdf')?'checked':''}><span>Adjuntar PDF</span></div></div>
   <div class=f><div class=chk style="margin-top:22px"><input type=checkbox id=f_rep_csv ${(rp.formato||[]).includes('csv')?'checked':''}><span>Adjuntar CSV</span></div></div>
   <div class="f full hint">Ejemplo: para recibirlo <b>todos los viernes a las 18:00</b>, elegí <b>Una vez por semana</b>, día <b>Viernes</b> y hora <b>18:00</b>. El informe trae los KPIs (creados, resueltos, backlog), el SLA, el MTTR y el desglose por técnico y categoría, y sale por los canales que configuraste arriba.</div>

   <div class=sec><span>ITHOS proactivo · se adelanta a los problemas</span></div>
   <div class="f full hint">ITHOS no espera a que le preguntes: te avisa antes de que un ticket incumpla su SLA y detecta fichajes fuera de horario. Además arma <b>solo</b> una base de conocimiento con tus tickets resueltos para resolver casos parecidos.</div>
   <div class=f><div class=chk style="margin-top:22px"><input type=checkbox id=f_pro_sla ${pr.sla_enabled?'checked':''}><span>Avisarme antes de que venza un SLA</span></div></div>
   <div class=f><label>Avisar cuando falten (horas)</label><input id=f_pro_horas type=number value="${pr.aviso_horas!=null?pr.aviso_horas:4}"></div>
   <div class=f><label>Revisar cada (min)</label><input id=f_pro_min type=number value="${pr.revisar_min!=null?pr.revisar_min:15}"></div>
   <div class=f><div class=chk style="margin-top:22px"><input type=checkbox id=f_ano_en ${an.enabled?'checked':''}><span>Anomalías de horario (HikCentral/BioStar2)</span></div></div>
   <div class="f full hint">Las <b>anomalías de horario</b> vienen apagadas y solo aplican a sistemas con control horario (HikCentral / BioStar 2), que toman su config por API sola (IVMS no aplica). La base de conocimiento se arma sola, por empresa, y es privada.</div>
   <div class="f full"><button class="btn sm" type=button onclick="regenKB()" ${c.api_key?'':'disabled'}>Regenerar base de conocimiento ahora</button></div>
   </div>
 </div>`;
}
function camposInteg(){renderCampos('#integCampos','integradores',$('#f_integ').value,'ic_',window._icfg||{})}
function camposTickets(){
 let tkt=$('#f_tkt').value, vals=window._tkv||{};
 if(tkt==='glpi'){let gl=window._gl||{};vals={glpi_url:gl.glpi_url,glpi_app_token:gl.glpi_app_token,glpi_user_token:gl.glpi_user_token,glpi_ithos_token:gl.glpi_ithos_token,glpi_bsierra_token:gl.glpi_bsierra_token,glpi_test_token:gl.glpi_test_token,entity_id:gl.entity_id};}
 // Reportes ITIL + ITHOS proactivo son de la MESA DE AYUDA: si no hay sistema de tickets, se ocultan.
 let dep=document.getElementById('depTickets');
 if(dep) dep.style.display=(tkt==='ninguno')?'none':'contents';
 renderCampos('#tkHost','tickets',tkt,'tk_',vals);
}
// --- Canales múltiples ---
function addCanal(){window._canales=window._canales||[];syncCanales();window._canales.push({tipo:'whatsapp_no_oficial',enabled:true});renderCanales()}
function removeCanal(i){syncCanales();window._canales.splice(i,1);renderCanales()}
function syncCanales(){(window._canales||[]).forEach((cn,i)=>{let s=$('#cn_tipo_'+i);if(s)cn.tipo=s.value;let e=$('#cn_en_'+i);if(e)cn.enabled=e.checked;
  let vals=readCampos('canales',cn.tipo,'cn_'+i+'_');Object.assign(cn,vals);})}
function renderCanales(){
 let host=$('#canalesHost');if(!host)return;let arr=window._canales||[];
 if(!arr.length){host.innerHTML='<div style="color:var(--muted);font-size:13px">Todavía no agregaste ningún canal. Tocá <b>＋ Agregar canal</b> y elegí WhatsApp, Telegram, Email, Teams, Slack o Matrix/Element.</div>';return}
 host.innerHTML=arr.map((cn,i)=>`<div class=canal>
   <div class=chd><select id="cn_tipo_${i}" onchange="onCanalTipo(${i})">${optList('canales',cn.tipo)}</select>
     <label class=chk><input type=checkbox id="cn_en_${i}" ${cn.enabled!==false?'checked':''}><span>activo</span></label>
     <button class="btn sm danger" type=button onclick="removeCanal(${i})">Quitar</button></div>
   <div id="cnf_${i}"></div>
   ${cn.tipo==='whatsapp_no_oficial'?`<div class=walink id="walink_${i}"></div>`:''}</div>`).join('');
 arr.forEach((cn,i)=>{renderCampos('#cnf_'+i,'canales',cn.tipo,'cn_'+i+'_',cn);
   if(cn.tipo==='whatsapp_no_oficial')waRender(i);});
}
function onCanalTipo(i){syncCanales();window._canales[i].tipo=$('#cn_tipo_'+i).value;renderCanales()}
// ---- Vinculación de WhatsApp NO-OFICIAL por QR (compartido: alta, panel admin y portal) ----
// Contexto: si hay api_key (cliente ya creado) se usa como credencial; en el ALTA (sin api_key aún)
// se genera una sesión propia y se manda el token de alta. El wa_session se persiste al guardar.
function _waCtx(){
 let k=window._apiKey||(($('#f_key')||{}).value||'').trim();
 if(k) return {api_key:k};
 window._waSesion=window._waSesion||('alta-'+Math.random().toString(36).slice(2,14));
 return {sesion:window._waSesion,_alta_token:(new URLSearchParams(location.search).get('t')||'')};
}
async function waEstado(){
 let c=_waCtx();
 let q=new URLSearchParams(c.api_key?{api_key:c.api_key}:{sesion:c.sesion,t:c._alta_token||''});
 try{return await (await fetch('/api/whatsapp/estado?'+q)).json()}catch(e){return {estado:'desconocido'}}
}
function waBadge(st){return ({vinculado:['✓ WhatsApp vinculado','ok'],qr:['Escaneá el QR','gold'],
 iniciando:['Generando QR…','gold'],caducada:['Sesión de WhatsApp caducada','err'],
 expirado:['El QR expiró','err'],sin_vincular:['WhatsApp sin vincular','muted'],
 error:['No se pudo vincular','err'],desconocido:['Consultando…','muted']})[st]||['—','muted'];}
async function waRender(i){
 let host=document.getElementById('walink_'+i); if(!host)return;
 let st=await waEstado(); let b=waBadge(st.estado); let num=st.numero?(' · +'+st.numero):'';
 let reintentar=(st.estado==='caducada'||st.estado==='expirado');
 let btn=(st.estado==='vinculado')
   ? `<button class="btn sm ghost" type=button onclick="waDesvincular(${i})">Desvincular</button>`
   : `<button class="btn sm" type=button onclick="waVincular(${i})">${reintentar?'Volver a vincular':'Vincular WhatsApp'}</button>`;
 let aviso=(st.estado==='caducada')?'<div class="hint" style="color:#ffb3bc">La sesión se cerró (probablemente por inactividad). Volvé a vincular para que ITHOS pueda enviar y responder por WhatsApp.</div>':'';
 host.innerHTML=`<div class="walink-row"><span class="pill ${b[1]}">${b[0]}${num}</span>${btn}</div>${aviso}
   <div class=hint>Vinculás el WhatsApp de tu empresa escaneando un QR (en el teléfono: WhatsApp → Dispositivos vinculados → Vincular un dispositivo). Queda guardado; si se cierra, acá te avisa y lo volvés a vincular.</div>`;
}
let _waTimer=null;
async function waVincular(i){
 let c=_waCtx(); waModal(true,'Generando el código QR…','<div class=hint>Un momento…</div>');
 try{await fetch('/api/whatsapp/vincular',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)});}catch(e){}
 waPoll(i);
}
async function waPoll(i){
 clearInterval(_waTimer);
 let tick=async()=>{
  let st=await waEstado();
  if(st.estado==='qr'&&st.qr){
   waModal(true,'Escaneá este código con WhatsApp','<img src="'+st.qr+'" alt="QR de WhatsApp" class=waqr>'+
    (st.expira_en?('<div class=hint>Expira en '+st.expira_en+' s · En el teléfono: WhatsApp → Ajustes → Dispositivos vinculados → Vincular un dispositivo.</div>'):''));
  }else if(st.estado==='vinculado'){clearInterval(_waTimer);
   waModal(true,'✓ ¡WhatsApp vinculado!','<div class=hint>Listo. ITHOS ya puede enviar y responder por este WhatsApp.</div>');
   setTimeout(()=>waModal(false),1800); waRender(i);
  }else if(st.estado==='expirado'){clearInterval(_waTimer);
   waModal(true,'El código expiró','<button class="btn sm" type=button onclick="waVincular('+JSON.stringify(i)+')">Generar otro</button>'); waRender(i);
  }else if(st.estado==='error'){clearInterval(_waTimer);
   waModal(true,'No se pudo iniciar','<div class="hint" style="color:#ffb3bc">'+(st.error||'Reintentá en unos segundos.')+'</div>');
  }
 };
 await tick(); _waTimer=setInterval(tick,2500);
}
async function waDesvincular(i){
 if(!confirm('¿Desvincular el WhatsApp? ITHOS dejará de enviar por ahí hasta que lo vincules de nuevo.'))return;
 let c=_waCtx();
 try{await fetch('/api/whatsapp/desvincular',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)});}catch(e){}
 toast('WhatsApp desvinculado'); waRender(i);
}
function waModal(show,titulo,cuerpo){
 let m=document.getElementById('wamodal');
 if(!m){m=document.createElement('div');m.id='wamodal';m.className='wamodal';
  m.addEventListener('click',e=>{if(e.target===m)waModal(false)});document.body.appendChild(m);}
 if(!show){m.classList.remove('show');clearInterval(_waTimer);return;}
 m.innerHTML=`<div class=wacard><button class=waclose type=button onclick="waModal(false)">✕</button>
   <h3>${titulo}</h3><div class=wabody>${cuerpo||''}</div></div>`;
 m.classList.add('show');
}
// ---- Terminales del control de acceso (entrada/salida/sala + frecuencia + saludo propio) ----
const TERM_TIPOS=[['entrada','Entrada'],['salida','Salida'],['sala','Sala técnica']];
const TERM_FREC=[['1_por_dia','1 vez por día'],['siempre','Siempre'],['1_por_persona','1 sola vez por persona']];
function optT(list,val){return list.map(o=>`<option value="${o[0]}" ${o[0]===val?'selected':''}>${o[1]}</option>`).join('')}
function addTerminal(nombre){window._terminales=window._terminales||[];syncTerminales();
 window._terminales.push({match:(typeof nombre==='string'?nombre:''),tipo:'entrada',frecuencia:'1_por_dia',saludo:''});renderTerminales()}
function removeTerminal(i){syncTerminales();window._terminales.splice(i,1);renderTerminales()}
function syncTerminales(){(window._terminales||[]).forEach((t,i)=>{
 let m=$('#tm_match_'+i);if(m)t.match=m.value; let tp=$('#tm_tipo_'+i);if(tp)t.tipo=tp.value;
 let fr=$('#tm_frec_'+i);if(fr)t.frecuencia=fr.value; let s=$('#tm_sal_'+i);if(s)t.saludo=s.value;})}
function renderTerminales(){
 let host=$('#termHost');if(!host)return;let arr=window._terminales||[];
 if(!arr.length){host.innerHTML='<div style="color:var(--muted);font-size:13px">Sin reglas propias: la entrada saluda 1 vez por día y "sala técnica" siempre. Tocá <b>＋ Agregar terminal</b> para personalizar.</div>';return}
 host.innerHTML=arr.map((t,i)=>`<div class=canal>
   <div class=chd style="flex-wrap:wrap;gap:8px">
     <input id="tm_match_${i}" placeholder="nombre del lector (ej: Puerta Principal)" value="${esc(t.match||'')}" style="flex:1;min-width:min(150px,100%)">
     <select id="tm_tipo_${i}">${optT(TERM_TIPOS,t.tipo||'entrada')}</select>
     <select id="tm_frec_${i}">${optT(TERM_FREC,t.frecuencia||'1_por_dia')}</select>
     <button class="btn sm danger" type=button onclick="removeTerminal(${i})">Quitar</button></div>
   <input id="tm_sal_${i}" placeholder="saludo propio (opcional) · {n}=nombre, {emp}=empresa" value="${esc(t.saludo||'')}" style="width:100%;margin-top:6px"></div>`).join('');
}
async function loadDescubiertas(){
 let host=$('#termDescubiertas');if(!host)return; let k=window._apiKey||(($('#f_key')||{}).value||'').trim();
 if(!k){host.innerHTML='';return}
 try{let d=await (await fetch('/api/terminales/'+encodeURIComponent(k))).json();
  window._termDesc=(d.terminales||[]);
  if(!window._termDesc.length){host.innerHTML='';return}
  host.innerHTML='<div class=hint>Terminales detectadas por el agente (tocá para agregarlas): '+
   window._termDesc.map((t,i)=>`<span class="badge" style="cursor:pointer" onclick="addTerminal(window._termDesc[${i}])">＋ ${esc(t)}</span>`).join(' ')+'</div>';
 }catch(e){host.innerHTML=''}
}
// ---- Salud del sistema: activo/inactivo de agente + canales + micrófono + integrador ----
// En producción TODO debe estar 100% activo; acá se ve de un vistazo si algo quedó sin arrancar.
function saludPill(label,val,detalle){
 // Tri-estado: true=activo(verde ●), false=caído(rojo ○), null/undefined=sin dato todavía(gris ◌).
 let cls=val===true?'ok':(val===false?'err':'muted'), ic=val===true?'●':(val===false?'○':'◌');
 return `<span class="pill ${cls}"${detalle?` title="${esc(detalle)}"`:''}>${ic} ${esc(label)}</span>`;
}
async function renderSalud(hostId,key){
 let host=document.getElementById(hostId); if(!host||!key)return;
 let s; try{s=await (await fetch('/api/salud/'+encodeURIComponent(key))).json()}catch(e){return}
 let rep=!!s.ts;                               // ¿el agente ya reportó su estado (mic/integrador/voz)?
 let con=!!s.agente_conectado;
 let icfg=s.integrador_cfg||s.integrador_tipo; // integrador CONFIGURADO (mostramos aunque no reportó aún)
 let pills=[saludPill('Agente',con,con?'Conectado al gestor':'El agente no está conectado')];
 if(icfg)pills.push(saludPill('Acceso: '+integName(icfg), !con?false:(rep?!!s.integrador:null),'Control de acceso'));
 if(s.mic_habilitado)pills.push(saludPill('Micrófono', !con?false:(rep?!!s.microfono:null),'Escucha por voz'));
 (s.canales||[]).forEach(c=>pills.push(saludPill(catLabel('canales',c.tipo).split(' ')[0],!!c.activo,c.detalle||'')));
 let problemas=!con||(s.canales||[]).some(c=>!c.activo)||(icfg&&rep&&!s.integrador)||(s.mic_habilitado&&rep&&!s.microfono);
 let esperando=con&&!rep&&(icfg||s.mic_habilitado);
 let msg=!con?'El agente no está conectado: no se puede ver el estado.':
   (problemas?'Hay algo sin arrancar (en rojo). En producción todo debe estar activo.':
   (esperando?'Agente conectado. Esperando el estado de sus componentes…':'Todo activo y funcionando al 100%.'));
 host.innerHTML=`<div class=walink-row>${pills.join(' ')}</div>
   <div class="hint"${problemas?' style="color:#ffb3bc"':''}>${msg}</div>`;
}
// --- Proveedores de IA (primaria + secundaria) ---
function camposIAp(){renderCampos('#iapHost','ia',$('#f_prov').value,'iap_',window._iaVals||{})}
function camposIAs(){let t=$('#f_prov2').value; if(!t){$('#iasHost').innerHTML='';return} renderCampos('#iasHost','ia',t,'ias_',window._iaSec||{})}
function camposIAt(){let t=$('#f_prov3').value; if(!t){$('#iatHost').innerHTML='';return} renderCampos('#iatHost','ia',t,'iat_',window._iaTer||{})}

function initForm(c){
 window._apiKey=(c&&c.api_key)||'';       // credencial para vincular WhatsApp (reset por cliente)
 window._waSesion=(c&&c.wa_session)||'';  // sesión de WhatsApp persistida (reset por cliente)
 window._icfg=(c&&(c.integrador_config||(typeof c.integrador==='object'?c.integrador:{})))||{};
 window._gl=(c&&c.integrador_glpi)||{}; window._tkv=(c&&c.tickets)||{};
 window._iaVals=(c&&c.ia)||{}; window._iaSec=(c&&c.ia&&c.ia.secundario)||{}; window._iaTer=(c&&c.ia&&c.ia.terciario)||{};
 window._canales=JSON.parse(JSON.stringify((c&&c.notificaciones)||[]));
 window._terminales=JSON.parse(JSON.stringify((c&&c.terminales)||[]));   // reglas de terminales
 window._kbOutline=(c&&c.kb_outline)||{};   // Outline: valores guardados si los hay
 camposInteg();camposTickets();camposIAp();camposIAs();camposIAt();renderCanales();repFrec();
 renderTerminales();loadDescubiertas();
}
// Muestra el selector de día correcto según la frecuencia (semana / mes) y oculta el otro.
function repFrec(){let f=(($('#f_rep_frec')||{}).value)||'diario';
 let s=document.getElementById('rep_diasem_box'), m=document.getElementById('rep_diames_box');
 if(s) s.style.display=(f==='semanal')?'flex':'none';
 if(m) m.style.display=(f==='mensual')?'flex':'none';
}
async function genKey(){
 let n=$('#f_nombre').value||'CLI';
 let r=await (await fetch('/api/generar_key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nombre:n})})).json();
 let k=$('#f_key');k.value=r.api_key;k.removeAttribute('readonly');
}
function collectForm(){
 let tkt=$('#f_tkt').value, tickets={tipo:tkt,...readCampos('tickets',tkt,'tk_')};
 syncCanales();syncTerminales();
 let notis=(window._canales||[]).map(cn=>({tipo:cn.tipo,enabled:cn.enabled!==false,...canalVals(cn)}));
 let terms=(window._terminales||[]).filter(t=>(t.match||'').trim()).map(t=>({match:t.match.trim(),tipo:t.tipo||'entrada',frecuencia:t.frecuencia||'1_por_dia',saludo:(t.saludo||'').trim()}));
 return {api_key:$('#f_key').value.trim(), agente_token:($('#f_atok')?$('#f_atok').value.trim():''),
   nombre:$('#f_nombre').value.trim(), email:$('#f_email').value.trim(),
   activo:$('#f_activo').checked, idioma:$('#f_idioma').value, zona_horaria:$('#f_zona').value,
   proveedor:$('#f_prov').value, proveedor_secundario:$('#f_prov2').value, proveedor_terciario:$('#f_prov3').value,
   voz_motor:$('#f_vozmotor').value, gemini_api_key:$('#f_gem').value.trim(),
   ia_config:readCampos('ia',$('#f_prov').value,'iap_'),
   ia_config_2:$('#f_prov2').value?readCampos('ia',$('#f_prov2').value,'ias_'):{},
   ia_config_3:$('#f_prov3').value?readCampos('ia',$('#f_prov3').value,'iat_'):{},
   limite_diario:+$('#f_lim').value||200, avisar_en:+$('#f_av').value||15, ilimitada:$('#f_ilim').checked,
   integrador:$('#f_integ').value, integrador_config:readCampos('integradores',$('#f_integ').value,'ic_'),
   tickets:tickets, notificaciones:notis, terminales:terms,
   kb_outline:{url:(($('#kb_ol_url')||{}).value||'').trim(), token:(($('#kb_ol_tok')||{}).value||'').trim()},
   wa_session:window._waSesion||'',   // sesión de WhatsApp vinculada (se preserva; no perder el QR)
   reportes:colReportes(), proactivo:colProactivo(), anomalias:colAnomalias()};
}
function colReportes(){
 let frec=$('#f_rep_frec').value, r={enabled:$('#f_rep_en').checked,frecuencia:frec,hora:($('#f_rep_hora')||{}).value||'09:00'};
 if(frec==='semanal')r.dia_semana=+(($('#f_rep_diasem')||{}).value)||0;
 else if(frec==='mensual')r.dia_mes=+(($('#f_rep_diames')||{}).value)||1;
 let fmt=[]; if(($('#f_rep_pdf')||{}).checked)fmt.push('pdf'); if(($('#f_rep_csv')||{}).checked)fmt.push('csv');
 r.formato=fmt; r.por_tecnico=true; r.dias_habiles=($('#f_rep_habil')||{}).checked||false;
 return r;
}
function colProactivo(){return {sla_enabled:($('#f_pro_sla')||{}).checked||false,
 aviso_horas:+($('#f_pro_horas')||{}).value||4, revisar_min:+($('#f_pro_min')||{}).value||15}}
function colAnomalias(){return {enabled:($('#f_ano_en')||{}).checked||false,
 revisar_min:+($('#f_pro_min')||{}).value||10}}
function regenKB(){let k=($('#f_key')||{}).value;if(!k){toast('Guardá la empresa primero');return;}
 toast('Regenerando base de conocimiento…');
 fetch('/api/kb_generar/'+encodeURIComponent(k)).then(r=>r.json()).then(d=>{
  toast(d.ok?('Base lista: '+d.casos+' casos resueltos'):('Error: '+(d.error||'')));}).catch(e=>toast('Error KB'));}
function canalVals(cn){let o={};(CATS.canales[cn.tipo].campos||[]).forEach(f=>{if(cn[f.k]!=null&&cn[f.k]!=='')o[f.k]=cn[f.k]});return o}

function toast(m){let t=$('#toast');if(!t)return;t.textContent=m;t.style.display='block';clearTimeout(t._);t._=setTimeout(()=>t.style.display='none',2600)}
function mask(k){return k?k.slice(0,6)+'••••'+k.slice(-4):'—'}
function slaGauge(s){
 if(s&&s.error) return `<div style="color:var(--muted);text-align:center">SLA: ${s.error}</div>`;
 let p=(s&&s.sla_cumplimiento_pct!=null)?s.sla_cumplimiento_pct:0;
 return `<div class=gauge style="--p:${p}"><b>${p}%</b></div>
  <div style="text-align:center;color:var(--muted);margin-top:10px">${s.total} tickets ·
   <b style="color:var(--ok)">${s.sla_cumplidos}</b> en tiempo · <b style="color:var(--danger)">${s.sla_incumplidos}</b> fuera</div>`;
}
// Tarjetas con datos REALES de GLPI (a partir del reporte de SLA).
function realCards(s){
 if(!s||s.error) return '<div class=empty>'+(s&&s.error?('No pude leer los tickets — '+esc(s.error)):'Todavía no hay datos de tickets. Conectá tu sistema de tickets para verlos acá.')+'</div>';
 let e=s.por_estado||{}, ab=(e['Nuevo']||0)+(e['En curso']||0)+(e['Planificado']||0);  // 'En espera' tiene su propia tarjeta -> no lo duplicamos acá
 let c=(t,v,g,ti)=>`<div class="panel stat ${g||''}"${ti?' title="'+esc(ti)+'"':''}><b>${v||0}</b><span>${t}</span></div>`;
 return `<div class="grid stats" style="margin-bottom:16px">
   ${c('Tickets (total)',s.total,'gold','Todos los tickets de tu mesa de ayuda')}
   ${c('Abiertos',ab,'','Sin resolver: Nuevos + En curso + Planificados')}
   ${c('En espera',e['En espera'],'','Pausados esperando algo (respuesta, repuesto, aprobación…)')}
   ${c('Resueltos',e['Resuelto'],'','Ya resueltos, a la espera del cierre')}
   ${c('Cerrados',e['Cerrado'],'','Cerrados definitivamente')}
   ${c('SLA',(s.sla_cumplimiento_pct!=null?s.sla_cumplimiento_pct+'%':'—'),'','% de tickets atendidos dentro del tiempo comprometido')}</div>`;
}
function canalesResumen(c){let n=(c&&c.notificaciones)||[];let act=n.filter(x=>x.enabled!==false);
 if(!act.length)return 'Sin canales de aviso';
 return act.map(x=>catLabel('canales',x.tipo).split(' ')[0]).join(' · ');
}
// ---- Reportes ITIL (compartido por el panel superadmin y el PORTAL del cliente) ----
// UI: selector de período + botones. Cualquiera puede sacar el reporte diario/semanal/mensual
// a mano y descargar PDF/CSV, aunque NO tenga configurado el envío automático.
function itilBloque(){return `<div class=sec style="border:0;margin-top:16px"><span>Reportes ITIL 4</span></div>
   <div class=f style="flex-direction:row;gap:8px;align-items:end;flex-wrap:wrap">
     <div><label>Período</label><select id=r_per onchange="itilPer()"><option value=diario>Diario</option><option value=semanal>Semanal</option><option value=mensual selected>Mensual</option><option value=total>Histórico (todo)</option><option value=personalizado>Personalizado…</option></select></div>
     <div id=r_rango class=row style="display:none;gap:8px;align-items:end">
       <div><label>Desde</label><input type=date id=r_desde></div>
       <div><label>Hasta</label><input type=date id=r_hasta></div></div>
     <button class="btn sm" onclick="verReporteITIL()">Ver KPIs</button>
     <button class="btn sm ghost" onclick="descReporte('pdf')">⬇ PDF</button>
     <button class="btn sm ghost" onclick="descReporte('csv')">⬇ CSV</button>
   </div><div id=itil_body style="margin-top:10px"></div>`;}
function itilPer(){let s=document.getElementById('r_per'),r=document.getElementById('r_rango');
 if(r) r.style.display=(s&&s.value==='personalizado')?'flex':'none';}
function itilQS(){let p=(document.getElementById('r_per')||{}).value||'mensual';let qs='periodo='+encodeURIComponent(p);
 if(p==='personalizado'){let d=(document.getElementById('r_desde')||{}).value||'',h=(document.getElementById('r_hasta')||{}).value||'';
  qs+='&desde='+encodeURIComponent(d)+'&hasta='+encodeURIComponent(h);}
 return qs;}
function descReporte(fmt){window.open('/api/reporte_itil/'+encodeURIComponent(window._RKEY)+'/'+fmt+'?'+itilQS(),'_blank');}
async function verReporteITIL(){
 let box=document.getElementById('itil_body'); if(box) box.innerHTML='<div class=empty>Calculando KPIs ITIL (por técnico incluido)…</div>';
 let r=await (await fetch('/api/reporte_itil/'+encodeURIComponent(window._RKEY)+'?'+itilQS()+'&tecnico=1')).json();
 if(!box) return;
 if(r.error){box.innerHTML='<div class=empty>'+esc(r.error)+'</div>';return;}
 box.innerHTML=itilCards(r.kpis)+itilTablas(r.kpis);}
function itilCards(k){let c=(t,v,g)=>`<div class="panel stat ${g||''}"><b>${v==null?'—':v}</b><span>${t}</span></div>`;
 let mt=k.mttr_horas==null?'—':(k.mttr_horas<48?k.mttr_horas+' h':(k.mttr_horas/24).toFixed(1)+' d');
 return `<div class=sub style="margin:2px 0 8px">${esc(k.etiqueta)} · generado ${esc(k.generado)}</div>
  <div class="grid stats" style="margin-bottom:12px">
  ${c('Creados',k.creados,'gold')}${c('Resueltos',k.resueltos)}${c('Cerrados',k.cerrados)}${c('Backlog',k.backlog)}
  ${c('SLA resolución',k.sla_ttr_pct!=null?k.sla_ttr_pct+'%':'—')}${c('SLA 1ª resp.',k.sla_tto_pct!=null?k.sla_tto_pct+'%':'—')}${c('MTTR',mt)}</div>`;}
function itilTablas(k){function T(tit,o){let e=Object.entries(o||{}).filter(x=>x[1]).sort((a,b)=>b[1]-a[1]);
  if(!e.length)return '';return `<div class=sec style="border:0"><span>${tit}</span></div>`+
   '<div class=tablewrap><table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:6px">'+
   e.map(x=>`<tr><td style="padding:4px 8px;border-bottom:1px solid rgba(120,160,200,.15)">${esc(x[0])}</td><td style="padding:4px 8px;text-align:right;border-bottom:1px solid rgba(120,160,200,.15);color:var(--cyan)">${x[1]}</td></tr>`).join('')+'</table></div>';}
 return T('Por prioridad',k.por_prioridad)+T('Por categoría',k.por_categoria)+T('Por técnico',k.por_tecnico)+T('Por estado',k.por_estado)+T('Backlog por antigüedad',k.aging);}
// ---- Base de conocimiento (subir MUCHOS archivos juntos + regenerar de tickets) ----
function kbBloque(){return `<div class=sec style="border:0;margin-top:16px"><span>Base de conocimiento</span></div>
   <div style="color:var(--muted);font-size:12.5px;margin-bottom:10px;line-height:1.5">ITHOS aprende <b>solo</b> de tus tickets ya resueltos (problema → solución) y usa eso para resolver casos parecidos. Podés <b>sumarle</b> tus instructivos/manuales, o traer tu wiki de <b>Outline</b>, para que responda con más precisión. Es privada y exclusiva de tu empresa.</div>
   <div class=f style="gap:8px;align-items:end;flex-wrap:wrap">
     <div style="flex:1;min-width:min(240px,100%)"><label>Subí instructivos o manuales (PDF, Word, texto — podés elegir varios a la vez)</label>
       <input type=file id=kb_files multiple accept=".pdf,.txt,.md,.csv,.docx"></div>
     <button class="btn sm" onclick="subirKB()">⬆ Subir a la base</button>
     <button class="btn sm ghost" onclick="regenKB()">↻ Volver a aprender de mis tickets</button>
   </div>
   <div class=f style="gap:8px;align-items:end;flex-wrap:wrap;margin-top:12px">
     <div style="flex:1;min-width:min(220px,100%)"><label>Outline — dirección de tu wiki</label>
       <input id=kb_ol_url placeholder="https://tuempresa.getoutline.com" value="${esc((window._kbOutline||{}).url||'')}"></div>
     <div style="flex:1;min-width:min(200px,100%)"><label>Outline — API token (Ajustes → API tokens)</label>
       <input id=kb_ol_tok type=password placeholder="ol_api_..." value="${esc((window._kbOutline||{}).token||'')}"></div>
     <button class="btn sm ghost" onclick="importarOutline()">📚 Traer docs de Outline</button>
   </div>
   <div id=kb_msg style="margin-top:8px;color:var(--muted);font-size:12px"></div>`;}
async function importarOutline(){if(!window._RKEY){toast('Primero creá la empresa (botón Crear empresa)');return;}
 let url=((document.getElementById('kb_ol_url')||{}).value||'').trim();
 let tok=((document.getElementById('kb_ol_tok')||{}).value||'').trim();
 if(!url||!tok){toast('Poné la dirección de Outline y el API token');return;}
 let msg=document.getElementById('kb_msg'); msg.textContent='Trayendo documentos de Outline…';
 try{let d=await (await fetch('/api/kb_outline/'+encodeURIComponent(window._RKEY),{method:'POST',
     headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url,token:tok})})).json();
   if(d.error){msg.textContent='Error: '+d.error;return;}
   msg.textContent='✅ '+d.traidos+' de '+d.total+' documentos importados de Outline y sumados a la base.';
   toast('Outline importado');}catch(e){msg.textContent='No se pudo importar de Outline';}}
async function subirKB(){if(!window._RKEY){toast('Primero creá la empresa (botón Crear empresa)');return;}
 let inp=document.getElementById('kb_files');
 if(!inp||!inp.files.length){toast('Elegí uno o varios archivos');return;}
 let fd=new FormData(); for(let f of inp.files) fd.append('archivos',f);
 let msg=document.getElementById('kb_msg'); msg.textContent='Subiendo y procesando '+inp.files.length+' archivo(s)…';
 try{let d=await (await fetch('/api/kb_subir/'+encodeURIComponent(window._RKEY),{method:'POST',body:fd})).json();
   if(d.error){msg.textContent='Error: '+d.error;return;}
   msg.textContent='✅ '+d.cargados+' de '+d.total+' aprendidos.'+((d.instructivos&&d.instructivos.length)?' Instructivos: '+d.instructivos.join(', '):'');
   toast('KB actualizada');}catch(e){msg.textContent='Error subiendo';}}
async function regenKB(){if(!window._RKEY){toast('Primero creá la empresa (botón Crear empresa)');return;}
 let msg=document.getElementById('kb_msg'); msg.textContent='Regenerando desde los tickets resueltos…';
 try{let d=await (await fetch('/api/kb_generar/'+encodeURIComponent(window._RKEY))).json();
   msg.textContent = d.error?('Error: '+d.error):('✅ '+d.casos+' casos resueltos aprendidos');}catch(e){msg.textContent='Error';}}
"""

_ADMIN_JS = r"""
let CLIENTES=[], VIVOS=[], VISTA='dash';
function el(t,c,h){let e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e}
// Sesión vencida: si el servidor responde 401 (cookie caducada), volvemos al login (no dejar el
// panel roto en silencio). Solo en el panel superadmin ('/'), no en el portal del cliente.
{const _f=window.fetch;window.fetch=async(...a)=>{let r=await _f(...a);
 if(r.status===401&&location.pathname==='/'){location.href='/login';}return r;};}
async function boot(){await loadCats();nav('dash');poll();setInterval(poll,4000);
 // El panel general se refresca solo cada 6s (métricas EN VIVO), salvo que haya un modal abierto.
 setInterval(()=>{if(VISTA==='dash'&&!document.getElementById('ov').classList.contains('show'))vistaDash();},6000)}
async function poll(){try{VIVOS=(await (await fetch('/api/estado')).json()).conectados||VIVOS}catch(e){/* hipo de red: MANTENER el ultimo valor, no blanquear (evita el "microcorte" visual) */}
 document.querySelectorAll('[data-live]').forEach(x=>{let on=VIVOS.includes(x.dataset.live);
   x.className='pill '+(on?'live':(x.dataset.act==='1'?'on':'off'));x.textContent=on?'● EN VIVO':(x.dataset.act==='1'?'● activa':'○ inactiva')});
 let cb=document.querySelector('[data-stat="Conectadas"] b'); if(cb&&cb.textContent!=String(VIVOS.length))cb.textContent=VIVOS.length;}
function nav(v){VISTA=v;document.querySelectorAll('.nav a').forEach(a=>a.classList.toggle('on',a.dataset.v===v));if(v==='dash')vistaDash();else vistaEmp()}
async function vistaDash(){
 let r=await (await fetch('/api/resumen')).json();let u=r.uso_total||{};
 let vals={'Empresas':r.total,'Activas':r.activos,'Conectadas':VIVOS.length,
           'Tickets IA':u.ticket||0,'Anuncios':u.anuncio||0,'Consultas':u.consulta_voz||0};
 // Si el dashboard YA está pintado, actualizamos SOLO los números EN EL LUGAR (sin reemplazar el
 // HTML) -> no parpadea. La primera vez (nav a dash) sí se pinta entero.
 if(document.querySelector('#view .grid.stats')){
   for(let k in vals){let b=document.querySelector('[data-stat="'+k+'"] b'); if(b&&b.textContent!=String(vals[k]))b.textContent=vals[k];}
   return poll();
 }
 let integs=Object.entries(r.por_integrador||{}).map(([k,v])=>`<span class=badge>${integName(k)} · ${v}</span>`).join(' ')||'—';
 $('#view').innerHTML=`<div class="grid stats">
   ${sc('Empresas',vals['Empresas'],'','Total de empresas dadas de alta en la central')}
   ${sc('Activas',vals['Activas'],'gold','Empresas con el servicio activo (encendido)')}
   ${sc('Conectadas',vals['Conectadas'],'','Agentes conectados AHORA mismo, en tiempo real')}
   ${sc('Tickets IA',vals['Tickets IA'],'','Tickets que la IA gestionó este mes (clasificó, asignó o respondió)')}
   ${sc('Anuncios',vals['Anuncios'],'','Avisos proactivos que ITHOS envió este mes por los canales')}
   ${sc('Consultas',vals['Consultas'],'','Preguntas que ITHOS respondió este mes por voz o chat')}</div>
  <div class="hint" style="margin:-6px 0 16px">Las tres primeras tarjetas son el estado actual; las tres últimas, la actividad del mes en curso. Pasá el mouse por cada una para ver qué mide.</div>
  <div class=panel><h3 class=ttl style="color:var(--cyan);font-size:13px;margin:0 0 12px">Sistemas de acceso desplegados</h3><div class=row>${integs}</div></div>`;
 poll();
}
function sc(t,v,g,ti){return `<div class="panel stat ${g||''}" data-stat="${esc(t)}"${ti?' title="'+esc(ti)+'"':''}><b>${v}</b><span>${t}</span></div>`}
async function vistaEmp(){
 CLIENTES=(await (await fetch('/api/clientes')).json()).clientes||[];
 if(!CLIENTES.length){$('#view').innerHTML='<div class="panel empty">Todavía no cargaste ninguna empresa.<br><br>Tocá <b>＋ Nueva empresa</b> arriba para dar de alta la primera y ITHOS empieza a trabajar.</div>';return}
 let g=el('div','grid cards');
 CLIENTES.forEach(c=>{
  let prov=(c.ia&&c.ia.proveedor)||'gemini',portal=location.origin+'/panel/'+encodeURIComponent(c.api_key);
  let card=el('div','panel cc');
  card.innerHTML=`<div class=hd><div class=nm>${esc(c.nombre)}</div>
     <span class=pill data-live="${esc(c.nombre)}" data-act="${c.activo?1:0}">…</span></div>
   <div class=row><span class="badge tk">TICKETS: ${catLabel('tickets',tipoTicket(c))}</span>
     <span class=badge>ACCESO: ${integName(tipoInteg(c))}</span><span class=badge>IA: ${prov}${c.ia&&c.ia.secundario&&c.ia.secundario.proveedor?' → '+c.ia.secundario.proveedor:''}${c.ia&&c.ia.terciario&&c.ia.terciario.proveedor?' → '+c.ia.terciario.proveedor:''}${c.ia&&c.ia.ilimitada?' ∞':''}</span></div>
   <div class=row><span class="badge wa">AVISO: ${canalesResumen(c)}</span></div>
   <div id="salud_${esc(c.api_key)}" style="margin:4px 0"></div>
   <div class=kv><span>API key</span><b class=key title="Copiar">${mask(c.api_key)}</b></div>
   <div class=kv><span>Contraseña agente</span><b class="${c.agente_token?'key atok':''}" title="Copiar">${c.agente_token?mask(c.agente_token):'—'}</b></div>
   <div class=kv><span>Gemini</span><b>${c.ia&&c.ia.gemini_api_key?mask(c.ia.gemini_api_key):'—'}</b></div>
   <div class=kv><span>Portal cliente</span><b class=link title="Abrir">/panel/…${esc(c.api_key.slice(-6))}</b></div>
   <div class=row style="margin-top:8px">
     <button class="btn sm" data-a=met>Métricas / SLA</button>
     <button class="btn sm ghost" data-a=cfg>Config agente</button>
     <button class="btn sm gold" data-a=edit>Editar</button>
     <button class="btn sm danger" data-a=del>Borrar</button></div>`;
  card.querySelector('.key').onclick=()=>{navigator.clipboard.writeText(c.api_key);toast('API key copiada')};
  {let a=card.querySelector('.atok');if(a)a.onclick=()=>{navigator.clipboard.writeText(c.agente_token);toast('Contraseña de agente copiada')};}
  card.querySelector('.link').onclick=()=>{navigator.clipboard.writeText(portal);window.open(portal,'_blank');toast('URL del portal copiada')};
  card.querySelector('[data-a=met]').onclick=()=>verMetricas(c);
  card.querySelector('[data-a=cfg]').onclick=()=>verConfigAgente(c);
  card.querySelector('[data-a=edit]').onclick=()=>openForm(c);
  card.querySelector('[data-a=del]').onclick=()=>delCliente(c);
  g.appendChild(card);
 });
 $('#view').innerHTML='';$('#view').appendChild(g);poll();
 CLIENTES.forEach(c=>renderSalud('salud_'+c.api_key,c.api_key));   // salud por empresa (agente/canales)
}
function openForm(c){
 $('#modal').innerHTML=`<h2>${c&&c.api_key?'Editar empresa':'Nueva empresa'}</h2>${formHTML(c,true)}
   <div class=acts><button class="btn ghost" onclick="cerrar()">Cancelar</button><button class="btn" onclick="saveForm()">Guardar empresa</button></div>`;
 openModal();initForm(c);
}
async function saveForm(){
 let cli=collectForm(); if(!cli.nombre){toast('Falta el nombre');return}
 let r=await fetch('/api/clientes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cli)});
 if(r.ok){cerrar();toast('Empresa guardada');nav('emp')}else{let e=await r.json();toast(e.error||'Error')}
}
// Genera un ENLACE DE ALTA TEMPORAL de un solo uso para pasarle a un cliente (se lo mandás y él
// carga su empresa la 1ª vez). Caduca y sirve una sola vez.
async function generarAlta(){
 let nombre=prompt('Nombre de la empresa a dar de alta (opcional, ayuda a identificar el enlace):','')||'';
 let r=await fetch('/api/alta_link',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nombre:nombre,horas:48})});
 if(!r.ok){let e=await r.json().catch(()=>({}));toast(e.error||'No se pudo generar el enlace');return}
 let d=await r.json(); let url=location.origin+d.url;
 $('#modal').innerHTML=`<h2>Enlace de alta temporal</h2>
   <div class=panel><b>Pasale este enlace al cliente</b> (o usalo vos para cargar la empresa).
   Sirve <b>una sola vez</b> y caduca en <b>${esc(d.horas)} h</b>.<br><br>
   <div class=key style="word-break:break-all">${esc(url)}</div></div>
   <div class=acts>
     <button class="btn ghost" onclick="cerrar()">Cerrar</button>
     <button class="btn danger" onclick="revocarAlta('${esc(d.token)}')">Revocar (lo generé sin querer)</button>
     <button class="btn" onclick="navigator.clipboard.writeText('${url}');toast('Enlace copiado')">Copiar enlace</button>
     <button class="btn gold" onclick="window.open('${url}','_blank')">Abrir</button></div>`;
 openModal();
}
// Revoca un enlace de alta recién generado (si lo creaste por error): deja de valer al instante.
async function revocarAlta(token){
 if(!confirm('¿Revocar este enlace de alta? Ya no se va a poder usar.'))return;
 let r=await fetch('/api/alta_revocar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token})});
 let d=await r.json().catch(()=>({})); toast(d.ok?'Enlace revocado — ya no sirve':'No se pudo revocar'); if(d.ok)cerrar();
}
async function delCliente(c){if(!confirm('¿Borrar la empresa '+c.nombre+'?'))return;
 await fetch('/api/clientes/'+encodeURIComponent(c.api_key),{method:'DELETE'});toast('Empresa borrada');vistaEmp()}
async function verMetricas(c){
 window._RKEY=c.api_key;
 $('#modal').innerHTML=`<h2>${esc(c.nombre)} — Métricas &amp; Reportes ITIL</h2><div id=met_body><div class=empty>Calculando… (leyendo tickets reales de GLPI)</div></div>
   ${itilBloque()}
   ${kbBloque()}
   <div class=acts><button class="btn ghost" onclick="cerrar()">Cerrar</button></div>`;openModal();
 let s=await (await fetch('/api/sla/'+encodeURIComponent(c.api_key))).json();
 $('#met_body').innerHTML=realCards(s)+'<div class=sec style="border:0"><span>Cumplimiento de SLA</span></div>'+slaGauge(s);
}
async function verConfigAgente(c){
 let cfg=await (await fetch('/api/config_agente/'+encodeURIComponent(c.api_key))).json();
 let js=JSON.stringify(cfg,null,2);
 $('#modal').innerHTML=`<h2>${esc(c.nombre)} — Config del agente</h2>
   <p style="color:var(--muted);font-size:13px">Pegá en <b>agente/config.json</b>. Acceso: <span class=badge>${integName(tipoInteg(c))}</span>. Cambiá <b>TU-DOMINIO</b>.</p>
   <pre id=cfgpre>${esc(js)}</pre>
   <div class=acts><button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('cfgpre').innerText);toast('Copiado')">Copiar</button>
   <button class="btn ghost" onclick="cerrar()">Cerrar</button></div>`;openModal();
}
// Cambiar la contraseña del Gestor: la fijás vos, nadie más la ve (se guarda hasheada). Al cambiarla,
// la sesión actual deja de valer y hay que volver a entrar.
function cambiarPass(){
 $('#modal').innerHTML=`<h2>Cambiar contraseña del Gestor</h2>
   <div class=panel>Elegí una contraseña propia (mínimo 10 caracteres). Se guarda <b>hasheada</b> (nunca en claro);
   ni nosotros la vemos. Al cambiarla se cierra esta sesión y entrás con la nueva.</div>
   <div class=f full><label>Contraseña actual</label><input id=cp_act type=password autocomplete=current-password></div>
   <div class=f full><label>Nueva contraseña</label><input id=cp_new type=password autocomplete=new-password></div>
   <div class=f full><label>Repetir nueva</label><input id=cp_rep type=password autocomplete=new-password></div>
   <div class=acts><button class="btn ghost" onclick="cerrar()">Cancelar</button>
     <button class="btn gold" onclick="guardarPass()">Cambiar contraseña</button></div>`;
 openModal();
}
async function guardarPass(){
 let act=$('#cp_act').value, nue=$('#cp_new').value, rep=$('#cp_rep').value;
 if(nue!==rep){toast('La nueva y su repetición no coinciden');return}
 if((nue||'').length<10){toast('La nueva debe tener al menos 10 caracteres');return}
 let r=await fetch('/api/cambiar_password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actual:act,nueva:nue})});
 let d=await r.json().catch(()=>({})); toast(d.mensaje||(d.ok?'Contraseña cambiada':'No se pudo cambiar'));
 if(d.ok){setTimeout(()=>location.href='/logout',1200);}
}
function openModal(){$('#ov').classList.add('show');document.body.classList.add('locked')}
function cerrar(){$('#ov').classList.remove('show');document.body.classList.remove('locked')}
document.addEventListener('click',e=>{if(e.target.id==='ov')cerrar()});
boot();
"""

HTML = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>ITHOS · Centro de mando</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@500;600;700&display=swap" rel=stylesheet>
<style>__ESTILO__</style></head><body>
<div class=app>
 <aside class=side>
   <div class=brand><div class=reactor></div><div><b>ITHOS</b><span>CONTROL DECK · SUPERADMIN</span></div></div>
   <nav class=nav>
     <a class=on data-v=dash onclick="nav('dash')"><span class=ic>◎</span> Panel general</a>
     <a data-v=emp onclick="nav('emp')"><span class=ic>▤</span> Empresas</a>
     <a onclick="openForm()"><span class=ic>＋</span> Nueva empresa</a>
     <a onclick="generarAlta()"><span class=ic>⇲</span> Enlace de alta</a>
     <a onclick="cambiarPass()"><span class=ic>🔑</span> Cambiar contraseña</a>
     <a onclick="location.href='/logout'"><span class=ic>⎋</span> Cerrar sesión</a>
   </nav>
   <div class=foot><span class=pulse></span> Núcleo en línea<br>v0.6 · Iron HUD<br>INTELLIHELP · ITHOS SaaS</div>
 </aside>
 <main class=main>
   <div class=top><div><h1>Centro de mando</h1><div class=sub>EMPRESAS · IA · TICKETS · AVISOS · ACCESO · SLA · TIEMPO REAL</div></div>
     <button class="btn gold" onclick="openForm()">＋ Nueva empresa</button></div>
   <div id=view></div>
 </main>
</div>
<div class=ov id=ov><div class=modal id=modal></div></div>
<div class=toast id=toast></div>
<script>__FORM_JS__</script><script>__ADMIN_JS__</script></body></html>"""

HTML_ALTA = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>ITHOS · Alta de empresa</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@500;600;700&display=swap" rel=stylesheet>
<style>__ESTILO__ .wrap{max-width:860px;margin:0 auto;padding:34px 20px}</style></head><body>
<div class=wrap>
 <div class=brand style="justify-content:center;margin-bottom:8px"><div class=reactor></div>
   <div><b style="font-family:Orbitron;font-size:22px;color:#eafcff">ITHOS</b>
   <span style="color:var(--muted);font-size:10px;letter-spacing:3px">ALTA DE EMPRESA</span></div></div>
 <p class=sub style="text-align:center;max-width:620px;margin:6px auto 22px">Completá los datos de tu empresa y elegí qué querés que haga ITHOS: gestionar tus tickets, avisarte por tus canales y atender el control de acceso. Al crearla te damos tu <b style="color:var(--txt)">API key</b> y el enlace a tu <b style="color:var(--txt)">portal privado</b>, donde después podés ver métricas y cambiar todo cuando quieras.</p>
 <div class=panel><div id=formhost></div>
   <div class=acts><button class="btn" onclick="enviarAlta()">Crear empresa</button></div>
   <div id=res style="margin-top:16px"></div></div>
</div>
<div class=toast id=toast></div>
<script>__FORM_JS__</script>
<script>
window._RKEY="";   // se setea al crear la empresa -> ahí funcionan Subir/Importar/Regenerar KB
(async function(){await loadCats();
 // El alta también muestra la BASE DE CONOCIMIENTO (subir instructivos + traer tu wiki de Outline),
 // igual que el portal. Los botones se habilitan al crear la empresa (necesitan su API key).
 document.getElementById('formhost').innerHTML=formHTML({},false)+kbBloque();initForm({})})();
async function enviarAlta(){
 let cli=collectForm(); if(!cli.nombre){toast('Poné el nombre de la empresa');return}
 cli._alta_token=new URLSearchParams(location.search).get('t')||'';   // enlace de un solo uso
 let r=await fetch('/api/alta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cli)});
 let d=await r.json(); if(!r.ok){toast(d.error||'Error');return}
 window._RKEY=d.api_key;                         // ya podés subir instructivos / importar Outline
 let portal=location.origin+d.portal;
 document.getElementById('res').innerHTML=`<div class=panel style="border-color:var(--ok)">
   <b style="color:var(--ok)">¡Empresa creada: ${esc(d.nombre)}!</b><br><br>
   API key del agente:<br><div class=key style="margin-top:6px">${esc(d.api_key)}</div><br>
   Portal de la empresa:<br><a class=link href="${portal}" target=_blank>${portal}</a><br><br>
   <span style="color:var(--muted);font-size:12.5px">Ya podés <b>subir tus instructivos</b> o
   <b>traer tu wiki de Outline</b> desde la sección Base de conocimiento de arriba.</span></div>`;
 toast('Empresa creada · ya podés sumar conocimiento');
}
</script></body></html>"""


def portal_html(api_key, nombre):
    tpl = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>ITHOS · __NOMBRE__</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@500;600;700&display=swap" rel=stylesheet>
<style>__ESTILO__ .wrap{max-width:960px;margin:0 auto;padding:28px 20px}</style></head><body>
<div class=wrap>
 <div class=top><div class=brand><div class=reactor></div>
   <div><b style="font-family:Orbitron;font-size:20px;color:#eafcff">ITHOS</b>
   <span style="color:var(--muted);font-size:10px;letter-spacing:3px">PORTAL · __NOMBRE__</span></div></div>
   <button class="btn gold" onclick="toggleEdit()" id=btnEdit>Editar mi configuración</button></div>
 <p class=sub style="margin:2px 0 16px">Este es el portal privado de tu empresa. Acá ves en vivo el estado de tus tickets y el cumplimiento de SLA, descargás tus reportes y le sumás conocimiento a ITHOS. Con <b style="color:var(--txt)">Editar mi configuración</b> cambiás la IA, los canales y todo lo demás.</p>
 <div id=dash></div>
 <div id=editbox style="display:none;margin-top:18px"><div class=panel><div id=formhost></div>
   <div class=acts><button class="btn ghost" onclick="toggleEdit()">Cancelar</button>
   <button class="btn" onclick="guardar()">Guardar cambios</button></div></div></div>
</div>
<div class=toast id=toast></div>
<script>__FORM_JS__</script>
<script>
const KEY="__KEY__"; let C=null;
async function cargar(){
 await loadCats(); C=await (await fetch('/api/cliente/'+encodeURIComponent(KEY))).json();
 window._apiKey=KEY; window._waSesion=C.wa_session||'';   // contexto para vincular WhatsApp
 let hayWA=(C.notificaciones||[]).some(n=>n.tipo==='whatsapp_no_oficial'&&n.enabled!==false);
 document.getElementById('dash').innerHTML=`
  <div class=row style="margin-bottom:14px">
   <span class="pill ${C.activo?'on':'off'}">${C.activo?'● activa':'○ inactiva'}</span>
   <span class="badge tk">TICKETS: ${catLabel('tickets',tipoTicket(C))}</span>
   <span class=badge>ACCESO: ${integName(tipoInteg(C))}</span>
   <span class=badge>IA: ${(C.ia&&C.ia.proveedor)||'gemini'}</span>
   <span class="badge wa">AVISO: ${canalesResumen(C)}</span></div>
  <div class=panel style="margin-bottom:14px"><div class=sec style="border:0;margin:0 0 8px"><span>Estado del sistema · todo debe estar activo</span></div><div id=saludHost><div class=hint>Consultando estado…</div></div></div>
  ${hayWA?`<div class=panel style="margin-bottom:14px"><div class=sec style="border:0;margin:0 0 8px"><span>WhatsApp de tu empresa</span></div><div class=walink id=walink_p></div></div>`:''}
  <div id=cards><div class=empty>Calculando… (leyendo tus tickets reales de GLPI)</div></div>
  <div class=panel><div class=sec style="border:0;margin:0 0 8px"><span>Cumplimiento de SLA</span></div><div id=slabox><div class=empty>Calculando…</div></div></div>
  <div class=panel style="margin-top:14px">${itilBloque()}</div>
  <div class=panel style="margin-top:14px">${kbBloque()}</div>`;
 if(hayWA)waRender('p');                            // estado de WhatsApp en el dashboard (vinculado/caducada)
 renderSalud('saludHost',KEY);                      // salud del sistema (agente/canales/micrófono)
 clearInterval(window._saludTimer);
 window._saludTimer=setInterval(()=>renderSalud('saludHost',KEY),10000);   // refresco cada 10s
 window._RKEY=KEY;                                  // para descargar/ver reportes ITIL + subir KB
 let s=await (await fetch('/api/sla/'+encodeURIComponent(KEY))).json();
 document.getElementById('cards').innerHTML=realCards(s);
 document.getElementById('slabox').innerHTML=slaGauge(s);
}
function toggleEdit(){let e=document.getElementById('editbox');let on=e.style.display==='none';
 e.style.display=on?'block':'none';document.getElementById('btnEdit').textContent=on?'Cerrar editor':'Editar mi configuración';
 if(on){document.getElementById('formhost').innerHTML=formHTML(C,false);initForm(C);}}
async function guardar(){let cli=collectForm();cli.api_key=KEY;
 let r=await fetch('/api/clientes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cli)});
 if(r.ok){toast('Configuración guardada');toggleEdit();cargar()}else{toast('Error al guardar')}}
cargar();
</script></body></html>"""
    return (tpl.replace("__ESTILO__", _ESTILO).replace("__FORM_JS__", _FORM_JS)
            .replace("__NOMBRE__", nombre).replace("__KEY__", api_key))


HTML = HTML.replace("__ESTILO__", _ESTILO).replace("__FORM_JS__", _FORM_JS).replace("__ADMIN_JS__", _ADMIN_JS)
HTML_ALTA = HTML_ALTA.replace("__ESTILO__", _ESTILO).replace("__FORM_JS__", _FORM_JS)
