"""Utilidades de bajo nivel para localizar y leer archivos DICOM."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import pydicom
from pydicom.dataset import FileDataset
from pydicom.errors import InvalidDicomError


@dataclass
class ScannedFile:
    """Un archivo que se intento leer como DICOM."""

    path: Path
    dataset: FileDataset | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.dataset is not None


def find_candidate_files(folder: Path, recursive: bool = True) -> list[Path]:
    """Lista todos los archivos regulares de una carpeta (sin filtrar por extension,
    ya que los CT en bruto de este proyecto no siempre tienen extension .dcm)."""
    if not folder.is_dir():
        raise NotADirectoryError(f"No es una carpeta: {folder}")
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in folder.glob(pattern) if p.is_file())


def read_dicom(path: Path, stop_before_pixels: bool = False) -> FileDataset:
    """Lee un archivo DICOM. Usa force=True porque muchos de los archivos de
    origen no tienen preambulo/meta estandar."""
    return pydicom.dcmread(
        str(path), force=True, stop_before_pixels=stop_before_pixels
    )


def scan_folder(
    folder: Path,
    recursive: bool = True,
    stop_before_pixels: bool = True,
    progress_callback: Callable[[int, int, Path], None] | None = None,
) -> Iterator[ScannedFile]:
    """Recorre una carpeta e intenta leer cada archivo como DICOM.

    Los archivos que no son DICOM (o estan corruptos) se reportan como
    ScannedFile con error, no se lanzan excepciones.
    """
    files = find_candidate_files(folder, recursive=recursive)
    total = len(files)
    for i, path in enumerate(files, start=1):
        if progress_callback is not None:
            progress_callback(i, total, path)
        try:
            ds = read_dicom(path, stop_before_pixels=stop_before_pixels)
            # Un DICOM valido de interes debe tener al menos Modality y SOPInstanceUID.
            if "SOPInstanceUID" not in ds:
                yield ScannedFile(path=path, dataset=None, error="Sin SOPInstanceUID (no parece DICOM)")
                continue
            yield ScannedFile(path=path, dataset=ds)
        except (InvalidDicomError, Exception) as e:  # noqa: BLE001 - queremos capturar cualquier fallo de lectura
            yield ScannedFile(path=path, dataset=None, error=str(e))
