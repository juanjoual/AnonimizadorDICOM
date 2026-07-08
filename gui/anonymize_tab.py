"""Pestaña: escanear una carpeta con CT/RT y anonimizarla + reenlazarla."""

from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core.anonymize import (
    BIRTH_DATE_MODE_REMOVE,
    BIRTH_DATE_MODE_YEAR_ONLY,
    KEEPABLE_TAGS,
    AnonymizationConfig,
)
from core.inventory import Inventory, InventoryError, build_inventory
from core.linking import run_pipeline

from .app import BackgroundTaskMixin

_BIRTH_DATE_OPTIONS = {
    "Recortar a solo el año (ej. 19800101)": BIRTH_DATE_MODE_YEAR_ONLY,
    "Eliminar por completo": BIRTH_DATE_MODE_REMOVE,
}

APP_NO_DIR_TITLE = "Falta seleccionar carpeta"


class AnonymizeTab(BackgroundTaskMixin, ttk.Frame):
    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent)
        self._init_background()

        self._input_dir = tk.StringVar()
        self._output_dir = tk.StringVar()
        self._recursive = tk.BooleanVar(value=True)
        self._patient_label = tk.StringVar()
        self._birth_date_label = tk.StringVar(value=next(iter(_BIRTH_DATE_OPTIONS)))
        self._keep_vars: dict[str, tk.BooleanVar] = {
            label: tk.BooleanVar(value=True) for label in KEEPABLE_TAGS
        }

        self._inventory: Inventory | None = None

        self._build_widgets()
        self.after(150, self._poll_queues, self._log_text)

    # ------------------------------------------------------------------
    def _build_widgets(self) -> None:
        pad = {"padx": 6, "pady": 4}

        folders = ttk.LabelFrame(self, text="Carpetas")
        folders.pack(fill="x", **pad)

        ttk.Label(folders, text="Carpeta de entrada:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(folders, textvariable=self._input_dir, width=60).grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(folders, text="Examinar...", command=self._choose_input_dir).grid(row=0, column=2, **pad)

        ttk.Checkbutton(
            folders, text="Buscar en subcarpetas", variable=self._recursive
        ).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(folders, text="Carpeta de salida:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(folders, textvariable=self._output_dir, width=60).grid(row=2, column=1, sticky="we", **pad)
        ttk.Button(folders, text="Examinar...", command=self._choose_output_dir).grid(row=2, column=2, **pad)

        folders.columnconfigure(1, weight=1)

        rules = ttk.LabelFrame(self, text="Reglas de anonimizacion")
        rules.pack(fill="x", **pad)

        ttk.Label(rules, text="Campos clinicos a conservar:").grid(row=0, column=0, sticky="nw", **pad)
        keep_frame = ttk.Frame(rules)
        keep_frame.grid(row=0, column=1, sticky="w", **pad)
        for i, label in enumerate(KEEPABLE_TAGS):
            ttk.Checkbutton(keep_frame, text=label, variable=self._keep_vars[label]).grid(
                row=i, column=0, sticky="w"
            )

        ttk.Label(rules, text="Fecha de nacimiento:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(
            rules,
            textvariable=self._birth_date_label,
            values=list(_BIRTH_DATE_OPTIONS),
            state="readonly",
            width=40,
        ).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(rules, text="Etiqueta de paciente (opcional):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(rules, textvariable=self._patient_label, width=30).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(
            rules, text="Si se indica, fija PatientName/PatientID a este valor en todos los archivos."
        ).grid(row=3, column=1, sticky="w", **pad)

        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        ttk.Button(actions, text="Escanear carpeta", command=self._on_scan).pack(side="left", padx=6)
        ttk.Button(actions, text="Anonimizar y enlazar", command=self._on_run).pack(side="left", padx=6)

        self._progress = ttk.Progressbar(self, mode="indeterminate")
        self._progress.pack(fill="x", **pad)

        log_frame = ttk.LabelFrame(self, text="Registro")
        log_frame.pack(fill="both", expand=True, **pad)
        self._log_text = tk.Text(log_frame, state="disabled", wrap="word")
        self._log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    def _choose_input_dir(self) -> None:
        path = filedialog.askdirectory(title="Selecciona la carpeta con archivos DICOM")
        if path:
            self._input_dir.set(path)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Selecciona la carpeta de salida")
        if path:
            self._output_dir.set(path)

    def _clear_log(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _log_timestamped(self, message: str) -> None:
        self._log(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def _make_scan_progress_logger(self, step: int = 50):
        def progress_callback(i: int, total: int, path: Path) -> None:
            if i == total or i % step == 0:
                self._log_timestamped(f"Leyendo archivo {i}/{total}: {path.name}")
        return progress_callback

    def _build_config(self) -> AnonymizationConfig:
        keep_tags = {KEEPABLE_TAGS[label] for label, var in self._keep_vars.items() if var.get()}
        birth_mode = _BIRTH_DATE_OPTIONS[self._birth_date_label.get()]
        patient_label = self._patient_label.get().strip() or None
        return AnonymizationConfig(
            keep_tags=keep_tags, birth_date_mode=birth_mode, patient_label=patient_label
        )

    # ------------------------------------------------------------------
    def _on_scan(self) -> None:
        input_dir = self._input_dir.get().strip()
        if not input_dir:
            messagebox.showwarning(APP_NO_DIR_TITLE, "Selecciona primero una carpeta de entrada.")
            return
        recursive = self._recursive.get()
        self._clear_log()
        self._progress.start(10)

        def work() -> None:
            self._log_timestamped(f"Escaneando carpeta: {input_dir}")
            self._log_timestamped(f"Busqueda en subcarpetas: {'si' if recursive else 'no'}")
            start = time.perf_counter()
            try:
                inv = build_inventory(
                    Path(input_dir),
                    recursive=recursive,
                    progress_callback=self._make_scan_progress_logger(),
                )
            except InventoryError as e:
                self._log_timestamped(f"ERROR: {e}")
                self._schedule_result(self._progress.stop)
                return
            except Exception as e:  # noqa: BLE001
                self._log_timestamped(f"ERROR inesperado al escanear: {e}")
                self._schedule_result(self._progress.stop)
                return

            elapsed = time.perf_counter() - start

            def apply() -> None:
                self._inventory = inv
                self._progress.stop()

            self._schedule_result(apply)
            self._log_timestamped(f"Escaneo completado en {elapsed:.1f} s:")
            for line in inv.detail_lines():
                self._log(f"  - {line}")

        self._run_in_background(work)

    def _on_run(self) -> None:
        input_dir = self._input_dir.get().strip()
        output_dir = self._output_dir.get().strip()
        if not input_dir or not output_dir:
            messagebox.showwarning(APP_NO_DIR_TITLE, "Selecciona la carpeta de entrada y la de salida.")
            return

        recursive = self._recursive.get()
        config = self._build_config()
        # Se leen todos los valores de los widgets Tk (StringVar/BooleanVar)
        # aqui, en el hilo principal: Tkinter/Tcl no es seguro de acceder
        # desde un hilo en segundo plano.
        birth_date_label = self._birth_date_label.get()
        keep_labels = sorted(label for label, var in self._keep_vars.items() if var.get())
        self._clear_log()
        self._progress.start(10)

        def work() -> None:
            overall_start = time.perf_counter()
            try:
                self._log_timestamped(f"Carpeta de entrada: {input_dir}")
                self._log_timestamped(f"Carpeta de salida: {output_dir}")
                self._log_timestamped(f"Busqueda en subcarpetas: {'si' if recursive else 'no'}")
                self._log(f"  Fecha de nacimiento: {birth_date_label}")
                self._log(f"  Etiqueta de paciente: {config.patient_label or '(sin cambios)'}")
                keep_labels = sorted(label for label, var in self._keep_vars.items() if var.get())
                self._log(f"  Campos conservados: {', '.join(keep_labels) or '(ninguno)'}")

                self._log_timestamped("Escaneando carpeta...")
                scan_start = time.perf_counter()
                inv = build_inventory(
                    Path(input_dir),
                    recursive=recursive,
                    progress_callback=self._make_scan_progress_logger(),
                )
                self._log_timestamped(f"Escaneo completado en {time.perf_counter() - scan_start:.1f} s:")
                for line in inv.detail_lines():
                    self._log(f"  - {line}")

                self._log_timestamped("Anonimizando y reenlazando...")
                pipeline_start = time.perf_counter()
                result = run_pipeline(inv, config, Path(output_dir), log=self._log_timestamped)
                self._log_timestamped(
                    f"Anonimizacion y reenlace completados en {time.perf_counter() - pipeline_start:.1f} s"
                )

                self._log_timestamped("Comprobaciones de enlace:")
                for check in result.checks:
                    estado = "OK" if check.passed else "FALLO"
                    detalle = f" ({check.detail})" if check.detail else ""
                    self._log(f"  [{estado}] {check.label}{detalle}")
                for warning in result.warnings:
                    self._log(f"  AVISO: {warning}")

                self._log_timestamped(f"Tiempo total: {time.perf_counter() - overall_start:.1f} s")
                if result.all_checks_passed:
                    self._log_timestamped("Proceso completado correctamente.")
                else:
                    self._log_timestamped("Proceso completado con comprobaciones fallidas. Revisa el registro.")
            except InventoryError as e:
                self._log_timestamped(f"ERROR: {e}")
            except Exception as e:  # noqa: BLE001
                self._log_timestamped(f"ERROR inesperado: {e}")
            finally:
                self._schedule_result(self._progress.stop)

        self._run_in_background(work)
