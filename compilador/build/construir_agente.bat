@echo off
REM ============================================================================
REM  Construye el AGENTE ITHOS: APP con interfaz grafica (.exe) + INSTALADOR.
REM  Correr desde la RAIZ del proyecto:   build\construir_agente.bat
REM  Requisitos: pip install pyinstaller pywebview pillow  +  pip install -r requirements.txt
REM              + Inno Setup 7 (ISCC.exe).
REM  Deja SOLO el instalador en dist\  ->  dist\ITHOS-Agente-Setup.exe
REM ============================================================================
setlocal
cd /d "%~dp0.."

echo.
echo  [0/6] Subiendo la version del AGENTE (auto, control de versiones)...
python build\bump_version.py agente patch || goto :err

echo  [1/6] Icono + imagenes del instalador...
python build\hacer_icono.py || goto :err

echo  [2/5] Limpiando lo VIEJO (dist + build temporales + logs)...
if exist dist rmdir /s /q dist
if exist build\exe rmdir /s /q build\exe
if exist build\work rmdir /s /q build\work
del /q agente\*.log 2>nul
del /q *.log 2>nul

echo  [3/6] Construyendo la app (ithos-agente.exe) a build\exe ...
python -m PyInstaller --clean --noconfirm --distpath build\exe --workpath build\work build\agente.spec || goto :err

echo  [4/6] Firmando el ejecutable (INTELLIHELP)...
powershell -NoProfile -ExecutionPolicy Bypass -File build\firmar.ps1 -Files build\exe\ithos-agente.exe

echo  [5/6] Compilando el INSTALADOR (Inno Setup) a dist ...
set "ISCC=C:\Users\%USERNAME%\AppData\Local\Programs\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
"%ISCC%" build\ithos-agente.iss || goto :err

echo  [5b/6] Firmando el INSTALADOR (INTELLIHELP)...
powershell -NoProfile -ExecutionPolicy Bypass -File build\firmar.ps1 -Files dist\ITHOS-Agente-Setup.exe

echo  [6/6] Limpiando temporales del build...
if exist build\exe rmdir /s /q build\exe
if exist build\work rmdir /s /q build\work

echo.
echo  LISTO:  dist\ITHOS-Agente-Setup.exe   (unico artefacto; el .exe va adentro del instalador)
endlocal
exit /b 0
:err
echo.
echo  ERROR en el build. Revisa el mensaje de arriba.
endlocal
exit /b 1
