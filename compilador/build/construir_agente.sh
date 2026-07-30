#!/usr/bin/env bash
# ============================================================================
#  Construye el AGENTE ITHOS (app con GUI) en LINUX o macOS. PyInstaller NO
#  cross-compila: este script se corre EN cada SO (el de Windows es
#  build\construir_agente.bat). "Todo a todo": mismo código, un binario por SO.
#  Uso (desde la RAIZ del proyecto):  bash build/construir_agente.sh
#  Requisitos: python3, pip install pyinstaller pywebview pillow + requirements.txt
#    Linux: además  sudo apt install python3-gi gir1.2-webkit2-4.1 (backend GTK de pywebview)
# ============================================================================
set -e
cd "$(dirname "$0")/.."
PY="$(command -v python3 || command -v python)"

echo "[1/4] Icono / imágenes"
"$PY" build/hacer_icono.py

echo "[2/4] Limpiando lo viejo (dist + temporales)"
rm -rf dist build/exe build/work
mkdir -p dist

echo "[3/4] PyInstaller (app a build/exe)"
"$PY" -m PyInstaller --clean --noconfirm --distpath compilador/build/exe --workpath compilador/build/work compilador/build/agente.spec

echo "[4/4] Empaquetando para este SO"
OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
  ( cd build/exe && zip -r -q "../../dist/ITHOS-Agente-mac.zip" "ITHOS Agente.app" )
  echo "OK  dist/ITHOS-Agente-mac.zip  (descomprimí y arrastrá 'ITHOS Agente.app' a Aplicaciones)"
  echo "    Firma (opcional, si tenés cert Apple):  codesign --deep -s 'Developer ID' 'build/exe/ITHOS Agente.app'"
else
  tar czf dist/ITHOS-Agente-linux.tar.gz -C build/exe ithos-agente
  echo "OK  dist/ITHOS-Agente-linux.tar.gz  (el binario 'ithos-agente'; instalá el servicio con"
  echo "    instaladores/agente_linux.sh apuntando a ese binario)"
fi
rm -rf build/exe build/work
