"""Pestaña: inspeccionar un archivo DICOM y valorar si esta anonimizado."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core.dicom_utils import read_dicom
from core.heuristics import AnonymizationReport, assess_anonymization

_VERDICT_LABELS = {
    "likely_anonymized": ("Probablemente ANONIMIZADO", "#1a7f37"),
    "likely_not_anonymized": ("Probablemente NO anonimizado", "#c62828"),
    "uncertain": ("No concluyente", "#b8860b"),
}


class InspectTab(ttk.Frame):
    def __init__(self, parent: ttk.Notebook) -> None:
        super().__init__(parent)

        self._file_path = tk.StringVar()
        self._build_widgets()

    def _build_widgets(self) -> None:
        pad = {"padx": 6, "pady": 4}

        chooser = ttk.Frame(self)
        chooser.pack(fill="x", **pad)
        ttk.Label(chooser, text="Archivo DICOM:").pack(side="left")
        ttk.Entry(chooser, textvariable=self._file_path, width=70).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(chooser, text="Examinar...", command=self._choose_file).pack(side="left")
        ttk.Button(chooser, text="Analizar", command=self._on_analyze).pack(side="left", padx=6)

        self._verdict_var = tk.StringVar(value="")
        self._verdict_label = tk.Label(self, textvariable=self._verdict_var, font=("", 14, "bold"))
        self._verdict_label.pack(fill="x", **pad)

        columns = ttk.PanedWindow(self, orient="horizontal")
        columns.pack(fill="both", expand=True, **pad)

        meta_frame = ttk.LabelFrame(columns, text="Metadatos completos")
        columns.add(meta_frame, weight=3)

        meta_scroll_y = ttk.Scrollbar(meta_frame, orient="vertical")
        meta_scroll_x = ttk.Scrollbar(meta_frame, orient="horizontal")
        self._meta_text = tk.Text(
            meta_frame,
            state="disabled",
            wrap="none",
            yscrollcommand=meta_scroll_y.set,
            xscrollcommand=meta_scroll_x.set,
        )
        meta_scroll_y.configure(command=self._meta_text.yview)
        meta_scroll_x.configure(command=self._meta_text.xview)
        meta_frame.rowconfigure(0, weight=1)
        meta_frame.columnconfigure(0, weight=1)
        self._meta_text.grid(row=0, column=0, sticky="nsew")
        meta_scroll_y.grid(row=0, column=1, sticky="ns")
        meta_scroll_x.grid(row=1, column=0, sticky="ew")

        findings_frame = ttk.LabelFrame(columns, text="Hallazgos de la heuristica")
        columns.add(findings_frame, weight=1)
        self._findings_text = tk.Text(findings_frame, state="disabled", wrap="word")
        self._findings_text.pack(fill="both", expand=True)

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(title="Selecciona un archivo DICOM")
        if path:
            self._file_path.set(path)

    def _on_analyze(self) -> None:
        path_str = self._file_path.get().strip()
        if not path_str:
            messagebox.showwarning("Falta seleccionar archivo", "Selecciona primero un archivo DICOM.")
            return
        path = Path(path_str)
        try:
            ds = read_dicom(path, stop_before_pixels=True)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error al leer el archivo", f"No se ha podido leer como DICOM:\n{e}")
            return

        self._show_metadata(ds)
        report = assess_anonymization(ds)
        self._show_report(report)

    def _show_metadata(self, ds) -> None:
        # Volcado completo del dataset, equivalente a `print(ds)` con pydicom:
        # todos los elementos presentes (incluidas secuencias anidadas), con
        # tag, VR, nombre y valor. Se leyo con stop_before_pixels=True, asi que
        # no incluye los pixeles en si.
        dump = str(ds)
        self._meta_text.configure(state="normal")
        self._meta_text.delete("1.0", "end")
        self._meta_text.insert("end", dump)
        self._meta_text.configure(state="disabled")

    def _show_report(self, report: AnonymizationReport) -> None:
        label, color = _VERDICT_LABELS[report.verdict]
        self._verdict_var.set(f"{label}  (puntuacion heuristica: {report.score:+d})")
        self._verdict_label.configure(foreground=color)

        self._findings_text.configure(state="normal")
        self._findings_text.delete("1.0", "end")
        for finding in report.findings:
            marker = "+" if finding.supports_anonymized else "-"
            self._findings_text.insert("end", f"[{marker}] {finding.label}\n")
        if not report.findings:
            self._findings_text.insert("end", "Sin hallazgos relevantes.\n")
        self._findings_text.configure(state="disabled")
