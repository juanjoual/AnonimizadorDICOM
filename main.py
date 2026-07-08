"""Punto de entrada de la aplicacion.

Se asegura de que la carpeta del proyecto este en sys.path (necesario tanto
en desarrollo como cuando se empaqueta con PyInstaller) y captura cualquier
excepcion no controlada mostrando un dialogo, ya que el ejecutable
empaquetado no tiene consola visible.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> None:
    import tkinter as tk
    from tkinter import messagebox

    from gui.app import App

    app = App()

    def report_callback_exception(exc_type, exc_value, exc_tb) -> None:
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(message, file=sys.stderr)
        messagebox.showerror("Error inesperado", str(exc_value) or message[:500])

    app.report_callback_exception = report_callback_exception

    try:
        app.mainloop()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
