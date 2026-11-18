# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec del AGENTE ITHOS. Genera el ejecutable (APP con interfaz gráfica ITHOS).
# Construir con:  compilador\build\construir_agente.bat  (o pyinstaller compilador/build/agente.spec)
# Requiere: pip install pyinstaller  +  las deps del agente (requirements.txt) + pywebview.
# Las rutas se resuelven desde la UBICACIÓN de este .spec (no desde el directorio actual), así el
# build funciona igual se lo llame desde la raíz o desde compilador/.
#
# Notas:
#  - El integrador de acceso (IVMS) se importa por NOMBRE en runtime -> hiddenimports. pyodbc idem.
#  - La GUI usa pywebview (WebView2/WinForms en Windows) -> hiddenimports 'gui','webview','clr' + data
#    de webview (DLLs WebBrowserInterop en webview/lib). Doc: pywebview.flowrl.com/guide/freezing.html
#  - console=False: es una APP con ventana (no consola). El servicio 24/7 corre con --run.
#  - Se construye en Windows: el agente corre en la PC de la oficina.
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

BUILD = os.path.abspath(SPECPATH)                           # compilador/build (SPECPATH ya es el DIRECTORIO del .spec)
RAIZ = os.path.dirname(os.path.dirname(BUILD))              # raíz del proyecto (compilador/build/../..)
APP = os.path.join(RAIZ, "ITHOS")                           # el software (comun/ + agente/)

_ICONO = os.path.join(BUILD, "ithos.ico")

hidden = (["integrador_ivms", "escucha", "voz", "pyodbc",
           "audiotsm", "audiotsm.io.array",              # velocidad de la voz (WSOLA)
           "gui", "webview", "clr",                       # GUI (pywebview) + backend .NET (pythonnet)
           "webview.platforms.winforms", "webview.platforms.edgechromium",
           "bandeja", "pystray", "PIL.Image",             # icono de BANDEJA (system tray)
           "vosk",                                        # wake-word OPEN-SOURCE (STT local)
           # Módulos de comun/ que el agente importa DENTRO de funciones (import perezoso). Se declaran
           # explícitos para que entren al paquete sí o sí: si faltara alguno, el agente arrancaría igual
           # pero perdería esa función (p. ej. sin comun.wake el micrófono no reconoce "Hey ITHOS").
           "comun", "comun.wake", "comun.audio", "comun.despierto", "comun.version",
           "comun.estilo_ithos", "comun.locucion", "comun.ia"]
          + collect_submodules("pystray")                 # backends de bandeja por SO
          + collect_submodules("edge_tts")
          + collect_submodules("onnxruntime") + collect_submodules("google"))

datas = ([(os.path.join(APP, "comun", "silero_vad.onnx"), "comun"),
          (os.path.join(BUILD, "ithos.png"), ".")]           # icono para la bandeja (ruta ABSOLUTA)
         + collect_data_files("edge_tts")
         + collect_data_files("vosk")                     # datos de vosk (si los hay)
         + collect_data_files("webview"))                 # DLLs WebBrowserInterop de pywebview

# La librería NATIVA de Vosk (libvosk) debe ir sí o sí, o el wake-word no carga.
binaries = collect_dynamic_libs("vosk")

a = Analysis(
    [os.path.join(APP, "agente", "agente.py")],             # ruta ABSOLUTA (no depende del cwd)
    pathex=[APP, os.path.join(APP, "agente"), os.path.join(APP, "comun")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    # webrtcvad = VAD de respaldo (perezoso, solo sin onnx; acá va Silero/onnx) -> su hook falla, se
    # excluye. QT/GTK: pywebview usa WebView2 en Windows, no hacen falta. El resto son del gestor.
    excludes=["reportlab", "pypdf", "fastapi", "uvicorn", "webrtcvad", "neonize",
              "matplotlib", "IPython", "tkinter", "pandas", "pytest",
              "PyQt5", "PyQt6", "PySide2", "PySide6", "gi"],   # backends de webview que no usamos + peso muerto
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="ithos-agente",
    console=False,                                    # APP con ventana (no consola DOS)
    icon=_ICONO,
    upx=False,
)

