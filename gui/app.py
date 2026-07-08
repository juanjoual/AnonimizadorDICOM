"""Ventana principal de la aplicacion: un Notebook con dos pestañas
(anonimizar/enlazar carpeta e inspeccionar un archivo)."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

APP_TITLE = "Anonimizador de DICOM para Torrecárdenas"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x650")
        self.minsize(700, 500)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # Import diferido para evitar dependencias circulares entre modulos de gui/.
        from .anonymize_tab import AnonymizeTab
        from .inspect_tab import InspectTab

        self.anonymize_tab = AnonymizeTab(notebook)
        self.inspect_tab = InspectTab(notebook)

        notebook.add(self.anonymize_tab, text="Anonimizar y enlazar carpeta")
        notebook.add(self.inspect_tab, text="Inspeccionar archivo DICOM")


class BackgroundTaskMixin:
    """Mixin para widgets que necesitan lanzar trabajo en un hilo aparte y
    volcar mensajes/resultados de vuelta al hilo de la GUI de forma segura."""

    def _init_background(self) -> None:
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._result_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._worker: threading.Thread | None = None

    def _poll_queues(self, log_widget: tk.Text) -> None:
        drained = False
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            log_widget.configure(state="normal")
            log_widget.insert("end", msg + "\n")
            log_widget.see("end")
            log_widget.configure(state="disabled")
            drained = True

        while True:
            try:
                callback = self._result_queue.get_nowait()
            except queue.Empty:
                break
            callback()
            drained = True

        self.after(150, self._poll_queues, log_widget)

    def _run_in_background(self, target: Callable[[], None]) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()

    def _log(self, message: str) -> None:
        self._log_queue.put(message)

    def _schedule_result(self, callback: Callable[[], None]) -> None:
        self._result_queue.put(callback)
