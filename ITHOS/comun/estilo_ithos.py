#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diseño ITHOS COMPARTIDO (panel web + app del agente): el MISMO look exacto en los dos.
Fuente única de verdad del estilo (HUD Iron Man / reactor cian). Si cambiás el diseño, cambia
en ambos a la vez. Lo usa central/panel_ui.py y agente/gui.py."""

# Fuentes de marca (Orbitron + Rajdhani). El agente tiene internet (se conecta al gestor), así
# que las carga igual que la web; si no hay red, cae a system-ui (definido en el CSS).
FUENTES = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet">'

# Emblema ITHOS (usa la clase .reactor del CSS).
REACTOR = "<div class=reactor></div>"

ESTILO = """
:root{
 --bg:#03060d; --panel:rgba(9,20,36,.72); --line:rgba(45,224,255,.16);
 --cyan:#2fe3ff; --cyan2:#12b6e8; --deep:#0a2a3a; --gold:#ffc46b; --txt:#d6f2ff;
 --muted:#6f93ab; --ok:#39e08a; --warn:#ffcf5c; --danger:#ff5f70;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
/* Guardas GLOBALES de responsive: nada desborda horizontal en ninguna resolución (PC/laptop/tablet/
   celular). Medios e íconos nunca superan el ancho; el contenido ancho scrollea DENTRO de su caja. */
html,body{max-width:100%;overflow-x:hidden}
img,canvas,svg,video{max-width:100%;height:auto}
input,select,textarea{max-width:100%}
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
body{font-family:'Rajdhani','Segoe UI',system-ui,sans-serif;background:
 radial-gradient(1200px 700px at 78% -10%,rgba(47,227,255,.12),transparent 60%),
 radial-gradient(900px 600px at 0% 110%,rgba(255,196,107,.07),transparent 55%),
 var(--bg);color:var(--txt)}
body.locked{overflow:hidden}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
 background-image:linear-gradient(rgba(47,227,255,.035) 1px,transparent 1px),
 linear-gradient(90deg,rgba(47,227,255,.035) 1px,transparent 1px);
 background-size:44px 44px;mask:radial-gradient(circle at 50% 40%,#000 60%,transparent 100%)}
h1,h2,h3,.ttl{font-family:'Orbitron','Rajdhani',sans-serif;letter-spacing:1.5px;text-transform:uppercase}
.app{display:flex;min-height:100vh;position:relative;z-index:1}
.side{width:250px;background:linear-gradient(180deg,rgba(6,16,30,.95),rgba(4,9,18,.98));
 border-right:1px solid var(--line);display:flex;flex-direction:column;padding:22px 16px;gap:10px;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:12px;margin-bottom:14px}
/* Emblema ITHOS — HUD de anillos concéntricos (ticks exteriores + anillo segmentado interior
   girando en sentidos opuestos, centro oscuro). Todo CSS, sin imágenes. */
.reactor{width:46px;height:46px;border-radius:50%;position:relative;flex:0 0 auto;
 background:
  radial-gradient(circle at 50% 50%,transparent 39%,var(--cyan) 40% 42%,transparent 43%),
  radial-gradient(circle at 50% 50%,rgba(47,227,255,.18),rgba(6,18,30,.35) 55%,transparent 72%);
 box-shadow:0 0 12px rgba(47,227,255,.55),0 0 28px rgba(47,227,255,.22)}
.reactor::before,.reactor::after{content:"";position:absolute;inset:0;border-radius:50%}
/* anillo de TICKS exterior (como una regla) girando lento */
.reactor::before{
 background:repeating-conic-gradient(from 0deg,rgba(127,233,255,.9) 0deg 1.5deg,transparent 1.5deg 9deg);
 -webkit-mask:radial-gradient(circle,transparent 72%,#000 73% 90%,transparent 92%);
         mask:radial-gradient(circle,transparent 72%,#000 73% 90%,transparent 92%);
 animation:spin 16s linear infinite}
/* anillo interior SEGMENTADO (4 arcos) girando al revés + borde fino */
.reactor::after{inset:12px;border:1.5px solid rgba(47,227,255,.5);
 background:conic-gradient(from 0deg,var(--cyan) 0 10%,transparent 10% 25%,var(--cyan) 25% 35%,
  transparent 35% 50%,var(--cyan) 50% 60%,transparent 60% 75%,var(--cyan) 75% 85%,transparent 85%);
 -webkit-mask:radial-gradient(circle,transparent 54%,#000 56%);
         mask:radial-gradient(circle,transparent 54%,#000 56%);
 box-shadow:0 0 8px rgba(47,227,255,.5);
 animation:spin 10s linear infinite reverse}
@keyframes spin{to{transform:rotate(360deg)}}
.brand b{font-family:'Orbitron',sans-serif;font-size:20px;color:#eafcff;letter-spacing:3px;text-shadow:0 0 10px rgba(47,227,255,.6)}
.brand span{display:block;font-size:10px;color:var(--muted);letter-spacing:3px}
.nav{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.nav a{display:flex;gap:10px;align-items:center;padding:11px 14px;border-radius:9px;color:var(--muted);cursor:pointer;font-weight:600;letter-spacing:.5px;border:1px solid transparent;transition:.12s}
.nav a:hover{color:var(--txt);background:rgba(47,227,255,.06)}
.nav a.on{color:#eafcff;background:linear-gradient(90deg,rgba(47,227,255,.16),transparent);border-color:var(--line);box-shadow:inset 2px 0 0 var(--cyan)}
.nav a .ic{width:18px;text-align:center;filter:drop-shadow(0 0 6px rgba(47,227,255,.5))}
.side .foot{margin-top:auto;font-size:11px;color:var(--muted);letter-spacing:1px;line-height:1.6}
.pulse{width:8px;height:8px;border-radius:50%;background:var(--ok);display:inline-block;box-shadow:0 0 8px var(--ok);animation:blink 1.6s infinite}
@keyframes blink{50%{opacity:.35}}
.main{flex:1;padding:26px 30px}
.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px;flex-wrap:wrap;gap:12px}
.top h1{font-size:22px;margin:0;color:#eafcff;text-shadow:0 0 12px rgba(47,227,255,.4)}
.top .sub{color:var(--muted);font-size:12px;letter-spacing:2px}
.sub{color:var(--muted);font-size:12.5px;line-height:1.5}
/* Texto de ayuda bajo cada título de sección — explica en criollo qué es y para qué sirve */
.hint{color:var(--muted);font-size:12.5px;line-height:1.55;margin:-2px 0 9px}
.hint b{color:var(--txt);font-weight:600}
.btn{font-family:'Rajdhani',sans-serif;font-weight:700;letter-spacing:1px;cursor:pointer;border:1px solid var(--cyan2);color:#eafcff;background:linear-gradient(180deg,rgba(47,227,255,.18),rgba(18,182,232,.06));padding:10px 18px;border-radius:9px;text-transform:uppercase;font-size:13px;transition:.12s}
.btn:hover{box-shadow:0 0 16px rgba(47,227,255,.45);transform:translateY(-1px)}
.btn.ghost{background:transparent;border-color:var(--line);color:var(--muted)}
.btn.gold{border-color:var(--gold);color:#ffe6bf;background:linear-gradient(180deg,rgba(255,196,107,.18),transparent)}
.btn.danger{border-color:var(--danger);color:#ffd3d8;background:linear-gradient(180deg,rgba(255,95,112,.16),transparent)}
.btn.sm{padding:6px 12px;font-size:11px;border-radius:7px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;position:relative;backdrop-filter:blur(6px)}
.panel::before,.panel::after{content:"";position:absolute;width:14px;height:14px;border:2px solid var(--cyan);opacity:.5}
.panel::before{left:-1px;top:-1px;border-right:0;border-bottom:0;border-top-left-radius:14px}
.panel::after{right:-1px;bottom:-1px;border-left:0;border-top:0;border-bottom-right-radius:14px}
.grid{display:grid;gap:16px}
.stats{grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin-bottom:22px}
.stat b{font-family:'Orbitron',sans-serif;font-size:32px;color:var(--cyan);display:block;line-height:1;text-shadow:0 0 14px rgba(47,227,255,.5)}
.stat span{color:var(--muted);font-size:12px;letter-spacing:2px;text-transform:uppercase}
.stat.gold b{color:var(--gold);text-shadow:0 0 14px rgba(255,196,107,.5)}
.cards{grid-template-columns:repeat(auto-fill,minmax(360px,1fr))}
.cc{display:flex;flex-direction:column;gap:9px}
.cc .hd{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.cc .nm{font-family:'Orbitron',sans-serif;font-size:15px;color:#eafcff;letter-spacing:1px}
.pill{font-size:10px;letter-spacing:1.5px;padding:4px 9px;border-radius:20px;text-transform:uppercase;font-weight:700;white-space:nowrap}
.pill.on{color:var(--ok);border:1px solid rgba(57,224,138,.5);background:rgba(57,224,138,.1)}
.pill.off{color:var(--muted);border:1px solid var(--line);background:rgba(255,255,255,.03)}
.pill.live{color:#04121a;background:var(--ok);border:1px solid var(--ok);box-shadow:0 0 10px rgba(57,224,138,.6)}
.badge{font-size:11px;letter-spacing:1px;color:var(--cyan);border:1px solid var(--line);padding:3px 9px;border-radius:6px;background:rgba(47,227,255,.06);display:inline-block}
.badge.tk{color:#ffd9a0;border-color:rgba(255,196,107,.3);background:rgba(255,196,107,.06)}
.badge.wa{color:#7ee0a0;border-color:rgba(57,224,138,.3);background:rgba(57,224,138,.06)}
.kv{display:flex;justify-content:space-between;gap:10px;font-size:13px;color:var(--muted);padding:3px 0;border-bottom:1px dashed rgba(255,255,255,.05)}
.kv b{color:var(--txt);font-weight:600;text-align:right;word-break:break-all}
.key{font-family:ui-monospace,monospace;font-size:11px;color:var(--gold);background:rgba(255,196,107,.07);padding:5px 8px;border-radius:6px;border:1px solid rgba(255,196,107,.2);cursor:pointer;word-break:break-all}
.link{font-family:ui-monospace,monospace;font-size:11px;color:var(--cyan);cursor:pointer;word-break:break-all}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.ov{position:fixed;inset:0;background:rgba(2,6,12,.78);backdrop-filter:blur(4px);z-index:50;display:none;align-items:flex-start;justify-content:center;padding:34px 20px;overflow:auto}
.ov.show{display:flex}
.modal{width:100%;max-width:820px;background:linear-gradient(180deg,rgba(8,18,32,.98),rgba(4,10,20,.99));border:1px solid var(--cyan2);border-radius:16px;padding:26px;box-shadow:0 0 50px rgba(47,227,255,.2)}
.modal h2{font-size:18px;color:#eafcff;margin:0 0 18px;text-shadow:0 0 10px rgba(47,227,255,.4)}
.form{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.f{display:flex;flex-direction:column;gap:5px}
.f.full{grid-column:1/-1}
.f label{font-size:11px;letter-spacing:1.5px;color:var(--muted);text-transform:uppercase}
.f input,.f select{background:#05101d;border:1px solid var(--line);border-radius:8px;padding:10px 12px;color:var(--txt);font-family:'Rajdhani',sans-serif;font-size:15px;outline:none;transition:.12s}
.f input:focus,.f select:focus{border-color:var(--cyan);box-shadow:0 0 12px rgba(47,227,255,.3)}
.f input::placeholder{color:rgba(111,147,171,.55)}
/* Controles nativos con el DISEÑO del theme (spinner de números, calendario/reloj, flecha del select) */
.f select{appearance:none;-webkit-appearance:none;-moz-appearance:none;cursor:pointer;padding-right:36px;
 background-image:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8'%3E%3Cpath fill='none' stroke='%232fe3ff' stroke-width='1.6' d='M1 1.5l5 5 5-5'/%3E%3C/svg%3E");
 background-repeat:no-repeat;background-position:right 13px center}
.f input[type=number]{appearance:textfield;-moz-appearance:textfield}
.f input[type=number]::-webkit-inner-spin-button,.f input[type=number]::-webkit-outer-spin-button{-webkit-appearance:none;margin:0}
.f input[type=date]::-webkit-calendar-picker-indicator,.f input[type=time]::-webkit-calendar-picker-indicator{
 filter:invert(74%) sepia(64%) saturate(700%) hue-rotate(150deg);cursor:pointer;opacity:.85}
.f input[type=date]::-webkit-calendar-picker-indicator:hover,.f input[type=time]::-webkit-calendar-picker-indicator:hover{opacity:1}
.f .withbtn{display:flex;gap:8px}.f .withbtn input{flex:1}
.sec{grid-column:1/-1;margin-top:8px;padding-top:12px;border-top:1px solid var(--line);font-family:'Orbitron',sans-serif;font-size:12px;letter-spacing:2px;color:var(--cyan);text-transform:uppercase;display:flex;justify-content:space-between;align-items:center}
.chk{display:flex;align-items:center;gap:9px;font-size:14px;color:var(--txt)}
.chk input{width:18px;height:18px;accent-color:var(--cyan)}
.canal{border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:10px;background:rgba(255,255,255,.02)}
.canal .chd{display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
.canal .chd select{flex:1;min-width:140px}
.acts{display:flex;justify-content:flex-end;gap:10px;margin-top:22px}
pre{background:#05101d;border:1px solid var(--line);border-radius:10px;padding:14px;color:#bfe;overflow:auto;font-size:12px;max-height:340px}
.gauge{width:150px;height:150px;border-radius:50%;display:grid;place-items:center;margin:0 auto;position:relative;background:conic-gradient(var(--cyan) calc(var(--p)*1%),rgba(255,255,255,.06) 0)}
.gauge::before{content:"";position:absolute;inset:14px;border-radius:50%;background:#05101d;box-shadow:inset 0 0 20px rgba(47,227,255,.25)}
.gauge b{position:relative;font-family:'Orbitron',sans-serif;font-size:26px;color:var(--cyan);text-shadow:0 0 12px rgba(47,227,255,.6)}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:rgba(8,20,34,.97);border:1px solid var(--cyan);border-radius:10px;padding:12px 20px;color:#eafcff;z-index:99;box-shadow:0 0 24px rgba(47,227,255,.4);display:none;letter-spacing:1px}
.empty{color:var(--muted);text-align:center;padding:50px;letter-spacing:1px}
::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:var(--deep);border-radius:6px}
/* Input de ARCHIVO con el estilo del theme (el 'Elegir archivos' crudo del browser rompe el diseño) */
input[type=file]{color:var(--muted);font-family:'Rajdhani',sans-serif;font-size:13px;padding:8px 0;cursor:pointer;max-width:100%}
input[type=file]::file-selector-button,input[type=file]::-webkit-file-upload-button{
 font-family:'Rajdhani',sans-serif;font-weight:700;letter-spacing:1px;cursor:pointer;border:1px solid var(--cyan2);color:#eafcff;
 background:linear-gradient(180deg,rgba(47,227,255,.18),rgba(18,182,232,.06));padding:9px 15px;border-radius:8px;
 text-transform:uppercase;font-size:12px;margin-right:12px;transition:.12s}
input[type=file]::file-selector-button:hover,input[type=file]::-webkit-file-upload-button:hover{box-shadow:0 0 14px rgba(47,227,255,.45)}
/* RESPONSIVE — TODO se adapta a CUALQUIER resolución: monitores de PC, laptops/notebooks, tablets y
   smartphones (chicos incluidos). Mobile-first de mayor a menor; combinado con las guardas globales
   de arriba, no queda NADA sin adaptar. */
@media (max-width:1024px){        /* tablets landscape / laptops chicos: tarjetas un poco más angostas */
 .cards{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
}
@media (max-width:900px){         /* tablet vertical: la barra lateral pasa ARRIBA (gana ancho útil) */
 .app{flex-direction:column}
 .side{width:auto;height:auto;position:static;flex-direction:row;flex-wrap:wrap;align-items:center;
  padding:12px 14px;gap:8px;border-right:0;border-bottom:1px solid var(--line)}
 .side .brand{margin-bottom:0}.side .foot{display:none}
 .nav{flex-direction:row;flex-wrap:wrap;margin-top:0;width:100%}.nav a{padding:8px 12px}
}
@media (max-width:820px){         /* formulario y tarjetas a 1 columna */
 .form{grid-template-columns:1fr}
 .main{padding:20px 16px}.modal{padding:20px 16px}.ov{padding:16px 10px}
 .cards{grid-template-columns:1fr}
 .top h1{font-size:19px}.top .sub{font-size:11px}
}
@media (max-width:600px){         /* celulares grandes */
 .stats{grid-template-columns:repeat(auto-fit,minmax(130px,1fr))}
 .gauge{width:132px;height:132px}.acts{flex-wrap:wrap}
 .kv{font-size:12.5px}.sec{font-size:11px}
}
@media (max-width:480px){         /* celulares */
 .btn{padding:9px 13px;font-size:12px}.btn.sm{padding:6px 10px}
 .stat b{font-size:26px}.main{padding:14px 10px}
 .modal h2{font-size:16px}.row{gap:6px}
 .wacard{padding:20px 16px}.waqr{width:220px}
}
@media (max-width:380px){         /* celulares chicos (360/320): todo a 1 columna, sin apreturas */
 .main{padding:12px 8px}.panel{padding:14px}
 .stats{grid-template-columns:1fr}
 .brand b,.top h1{font-size:17px}
 .modal{padding:16px 12px}.canal{padding:10px}
 .acts{flex-direction:column}.acts .btn{width:100%}
}
/* Pantallas GRANDES (laptop/desktop/ultra-wide): aprovechan el ancho sin estirar de más.
   'body .wrap' pisa el max-width que cada página fija inline (alta 860 / portal 960). */
@media (min-width:1100px){ .modal{max-width:900px} }        /* desktop: form a 2 columnas cómodo */
@media (min-width:1200px){ body .wrap{max-width:1080px} .form{gap:16px} }
@media (min-width:1500px){ body .wrap{max-width:1180px} }
@media (min-width:1800px){ body .wrap{max-width:1280px} .modal{max-width:980px} }
@media (min-width:2400px){ body .wrap{max-width:1440px} }
/* El panel superadmin (.app/.side/.main) ya es fluido (flex + tarjetas auto-fill);
   en monitores anchos le damos un tope cómodo para que las líneas no queden larguísimas. */
@media (min-width:2000px){ .main{max-width:1900px;margin:0 auto} }

/* ---- Vinculación de WhatsApp por QR (panel + portal + alta) ---- */
.pill.ok{color:var(--ok);border:1px solid rgba(57,224,138,.5);background:rgba(57,224,138,.1)}
.pill.gold{color:var(--gold);border:1px solid rgba(255,196,107,.5);background:rgba(255,196,107,.1)}
.pill.err{color:#ffb3bc;border:1px solid rgba(255,95,112,.5);background:rgba(255,95,112,.1)}
.pill.muted{color:var(--muted);border:1px solid var(--line);background:rgba(255,255,255,.03)}
.walink{margin-top:10px}
.walink-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.wamodal{position:fixed;inset:0;background:rgba(3,7,13,.82);backdrop-filter:blur(4px);
 display:none;align-items:center;justify-content:center;z-index:60;padding:20px}
.wamodal.show{display:flex}
.wacard{position:relative;background:linear-gradient(180deg,#08202e,#061019);border:1px solid var(--cyan);
 border-radius:16px;padding:26px 24px;max-width:380px;width:100%;text-align:center;
 box-shadow:0 0 40px rgba(47,227,255,.25)}
.wacard h3{font-family:'Orbitron',sans-serif;color:#eafcff;font-size:16px;margin:0 0 14px}
.wabody{color:var(--txt)}
.waqr{width:250px;max-width:72vw;height:auto;border-radius:12px;background:#fff;padding:12px;image-rendering:pixelated}
.waclose{position:absolute;top:10px;right:12px;background:none;border:0;color:var(--muted);
 font-size:18px;cursor:pointer;line-height:1}
"""
