# Anonimizador de DICOM para Torrecárdenas

Herramienta de escritorio para anonimizar archivos DICOM manteniendo la consistencia de enlaces CT/RT (RTSTRUCT, RTPLAN, RTDOSE) para investigación en radioterapia.

## Ejecutar para desarrollo

```bash
cd AnonimizadorDICOM
python -m venv .venv           # o reutilizar el .venv del proyecto
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Generar el ejecutable standalone

- Linux: `./build_linux.sh` (genera `dist/AnonimizadorDICOM`)
- Windows: `build_windows.bat` (genera `dist\AnonimizadorDICOM.exe`)

Ambos scripts usan el mismo `anonimizador.spec`.

## Estructura del proyecto

```
AnonimizadorDICOM/
  main.py               # punto de entrada
  core/                 # logica sin GUI (reutilizable/testeable)
    dicom_utils.py      # escaneo y lectura de archivos DICOM
    inventory.py        # clasificacion CT/RTSTRUCT/RTPLAN/RTDOSE y validaciones
    anonymize.py        # reglas de anonimizacion configurables
    linking.py          # anonimizacion conjunta + reenlace CT-RT
    heuristics.py       # heuristica "¿esta anonimizado?"
  gui/                  # interfaz Tkinter
    app.py              # ventana principal
    anonymize_tab.py    # pestaña de anonimizar/enlazar carpeta
    inspect_tab.py      # pestaña de inspeccion de un archivo
```
