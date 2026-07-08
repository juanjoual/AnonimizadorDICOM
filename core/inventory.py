"""Clasificacion de archivos DICOM escaneados en CT / RTSTRUCT / RTPLAN / RTDOSE
y validaciones de que una carpeta representa un unico paciente/estudio."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydicom.dataset import FileDataset

from .dicom_utils import ScannedFile, scan_folder

SUPPORTED_RT_MODALITIES = {"RTSTRUCT", "RTPLAN", "RTDOSE"}


class InventoryError(ValueError):
    """Error de validacion del inventario (carpeta no cumple 1 paciente/serie)."""


@dataclass
class CTSlice:
    path: Path
    dataset: FileDataset

    @property
    def z(self) -> float:
        return float(self.dataset.ImagePositionPatient[2])


@dataclass
class Inventory:
    ct_slices: list[CTSlice] = field(default_factory=list)
    rtstruct: ScannedFile | None = None
    rtplan: ScannedFile | None = None
    rtdose: ScannedFile | None = None
    ignored: list[ScannedFile] = field(default_factory=list)
    unread: list[ScannedFile] = field(default_factory=list)

    @property
    def has_ct(self) -> bool:
        return len(self.ct_slices) > 0

    @property
    def series_instance_uid(self) -> str | None:
        if not self.ct_slices:
            return None
        return str(self.ct_slices[0].dataset.SeriesInstanceUID)

    def summary_lines(self) -> list[str]:
        lines = [
            f"Cortes CT encontrados: {len(self.ct_slices)}",
            f"RTSTRUCT: {'si (' + self.rtstruct.path.name + ')' if self.rtstruct else 'no'}",
            f"RTPLAN: {'si (' + self.rtplan.path.name + ')' if self.rtplan else 'no'}",
            f"RTDOSE: {'si (' + self.rtdose.path.name + ')' if self.rtdose else 'no'}",
        ]
        if self.unread:
            lines.append(f"Archivos no legibles como DICOM: {len(self.unread)}")
        if self.ignored:
            modalities = sorted({str(f.dataset.get('Modality', '?')) for f in self.ignored if f.dataset})
            lines.append(
                f"Archivos con modalidad no soportada: {len(self.ignored)} ({', '.join(modalities)})"
            )
        return lines

    def detail_lines(self, max_examples: int = 15) -> list[str]:
        """Version extendida de summary_lines(), con mas detalle para el
        registro de la GUI: UID de serie, rango Z, rutas de los RT y ejemplos
        de archivos no legibles/ignorados."""
        lines = list(self.summary_lines())

        if self.ct_slices:
            z_values = [s.z for s in self.ct_slices]
            lines.append(f"  SeriesInstanceUID CT: {self.series_instance_uid}")
            lines.append(f"  Rango Z (ImagePositionPatient): {min(z_values):.2f} a {max(z_values):.2f} mm")
            lines.append(f"  Primer corte: {self.ct_slices[0].path}")
            lines.append(f"  Ultimo corte: {self.ct_slices[-1].path}")

        for label, scanned in (("RTSTRUCT", self.rtstruct), ("RTPLAN", self.rtplan), ("RTDOSE", self.rtdose)):
            if scanned is not None:
                lines.append(f"  Ruta {label}: {scanned.path}")

        if self.ignored:
            for scanned in self.ignored[:max_examples]:
                modality = scanned.dataset.get("Modality", "?") if scanned.dataset else "?"
                lines.append(f"  Ignorado ({modality}): {scanned.path.name}")
            if len(self.ignored) > max_examples:
                lines.append(f"  ... y {len(self.ignored) - max_examples} mas")

        if self.unread:
            for scanned in self.unread[:max_examples]:
                lines.append(f"  No legible: {scanned.path.name} ({scanned.error})")
            if len(self.unread) > max_examples:
                lines.append(f"  ... y {len(self.unread) - max_examples} mas")

        return lines


def build_inventory(folder: Path, recursive: bool = True, progress_callback=None) -> Inventory:
    """Escanea la carpeta y agrupa los archivos DICOM encontrados por Modality.

    Lanza InventoryError si se detecta mas de una serie CT o mas de un archivo
    de un mismo tipo RT (la aplicacion solo soporta un paciente/estudio por carpeta).
    """
    inv = Inventory()
    ct_by_series: dict[str, list[CTSlice]] = {}

    for scanned in scan_folder(folder, recursive=recursive, progress_callback=progress_callback):
        if not scanned.ok:
            inv.unread.append(scanned)
            continue

        ds = scanned.dataset
        modality = str(ds.get("Modality", "")).upper()

        if modality == "CT":
            series_uid = str(ds.SeriesInstanceUID)
            ct_by_series.setdefault(series_uid, []).append(CTSlice(path=scanned.path, dataset=ds))
        elif modality in SUPPORTED_RT_MODALITIES:
            existing = getattr(inv, modality.lower())
            if existing is not None:
                raise InventoryError(
                    f"Se han encontrado al menos dos archivos {modality} en la carpeta "
                    f"({existing.path.name} y {scanned.path.name}). Esta aplicacion solo "
                    "soporta un paciente/estudio por carpeta."
                )
            setattr(inv, modality.lower(), scanned)
        else:
            inv.ignored.append(scanned)

    if len(ct_by_series) > 1:
        detalles = ", ".join(f"{uid} ({len(slices)} cortes)" for uid, slices in ct_by_series.items())
        raise InventoryError(
            f"Se han encontrado {len(ct_by_series)} series CT distintas en la carpeta: {detalles}. "
            "Esta aplicacion solo soporta una serie CT por carpeta."
        )

    if ct_by_series:
        (series_uid, slices), = ct_by_series.items()
        inv.ct_slices = sorted(slices, key=lambda s: s.z)
        z_values = [s.z for s in inv.ct_slices]
        if len(set(round(z, 3) for z in z_values)) != len(z_values):
            raise InventoryError("Hay cortes CT duplicados con la misma coordenada Z (ImagePositionPatient).")

    return inv
