#!/usr/bin/env bash
# Genera el ejecutable standalone para Linux con PyInstaller.
# Ejecutar desde la carpeta AnonimizadorDICOM, con el entorno virtual activado
# (o instalar antes `pip install -r requirements.txt pyinstaller`).
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v pyinstaller >/dev/null 2>&1; then
    echo "pyinstaller no esta instalado en este entorno. Instalalo con:"
    echo "  pip install pyinstaller"
    exit 1
fi

pyinstaller --clean anonimizador.spec

echo
echo "Ejecutable generado en dist/AnonimizadorDICOM"
