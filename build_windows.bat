@echo off
REM Genera el ejecutable standalone para Windows con PyInstaller.
REM Debe ejecutarse en una maquina Windows real: PyInstaller no permite
REM generar un .exe de Windows desde Linux/macOS (no hace cross-compile).
REM
REM Uso:
REM   1. Crear un entorno virtual e instalar dependencias:
REM        python -m venv .venv
REM        .venv\Scripts\activate
REM        pip install -r requirements.txt pyinstaller
REM   2. Ejecutar este script desde la carpeta AnonimizadorDICOM.

cd /d "%~dp0"

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo pyinstaller no esta instalado en este entorno. Instalalo con:
    echo   pip install pyinstaller
    exit /b 1
)

pyinstaller --clean anonimizador.spec

echo.
echo Ejecutable generado en dist\AnonimizadorDICOM.exe
