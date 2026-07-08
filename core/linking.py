"""Anonimizacion conjunta de CT + RTSTRUCT/RTPLAN/RTDOSE y reenlace de las
referencias cruzadas entre ellos.

Generaliza la logica de Notebooks/relink_ct_rt.py y de la celda de reenlace de
Notebooks/Anonimizado3.ipynb:

- dicomanonymizer regenera los UID de nivel superior (Study/Series/SOPInstanceUID,
  FrameOfReferenceUID) de forma independiente en cada dataset, pero NO conoce ni
  actualiza las secuencias de referencias cruzadas propias de RT
  (ContourImageSequence, ReferencedStructureSetSequence, ReferencedRTPlanSequence...).
- Por eso, tras anonimizar cada archivo por separado, hay que recorrer esas
  secuencias a mano y sustituir los UID antiguos por los nuevos.

Estrategia de emparejamiento de cortes CT:
1. Mapeo directo old_sop -> new_sop, construido mientras se anonimiza cada
   corte CT (exacto, sin ambiguedad posible).
2. Si un SOPInstanceUID referenciado no aparece en ese mapeo (p.ej. el RT
   proviene de otra anonimizacion previa e independiente), se recurre al
   emparejamiento geometrico por coordenada Z real (ImagePositionPatient /
   ContourData), igual que hace relink_ct_rt.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pydicom.dataset import FileDataset

from .anonymize import AnonymizationConfig, anonymize_dataset_copy, reset_uid_cache
from .dicom_utils import read_dicom
from .inventory import Inventory

LogFn = Callable[[str], None]


@dataclass
class CheckResult:
    label: str
    passed: bool
    detail: str = ""


@dataclass
class PipelineResult:
    output_dir: Path
    ct_count: int = 0
    ct_dir: Path | None = None
    rtstruct_path: Path | None = None
    rtplan_path: Path | None = None
    rtdose_path: Path | None = None
    checks: list[CheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_checks_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _noop_log(_msg: str) -> None:
    return None


def _get_series_contour_image_sequence(rtstruct: FileDataset):
    ref_frame = rtstruct.ReferencedFrameOfReferenceSequence[0]
    ref_study = ref_frame.RTReferencedStudySequence[0]
    ref_series = ref_study.RTReferencedSeriesSequence[0]
    return ref_series


def _build_old_to_new_sop_map(
    rtstruct: FileDataset,
    old_sop_to_new_sop: dict[str, str],
    z_to_new_sop: dict[float, str],
) -> dict[str, str]:
    """Empareja cada SOPInstanceUID original referenciado por el RTSTRUCT con
    el nuevo SOPInstanceUID del CT anonimizado.

    Prioriza el mapeo directo (exacto); si un UID no aparece ahi, cae al
    emparejamiento por Z real de los contornos, incluyendo la inferencia de
    huecos por eliminacion (cortes sin contorno propio) como en el notebook.
    """
    sop_to_z: dict[str, float] = {}
    for roi_contour in rtstruct.ROIContourSequence:
        contour_seq = roi_contour.get("ContourSequence")
        if not contour_seq:
            continue
        for contour in contour_seq:
            cis = contour.get("ContourImageSequence")
            if not cis:
                continue
            sop = cis[0].ReferencedSOPInstanceUID
            z = round(float(contour.ContourData[2]))
            sop_to_z[sop] = z

    ref_series = _get_series_contour_image_sequence(rtstruct)
    all_uids = [c.ReferencedSOPInstanceUID for c in ref_series.ContourImageSequence]

    old_to_new: dict[str, str] = {}
    unresolved: list[str] = []
    for uid in all_uids:
        uid_str = str(uid)
        if uid_str in old_sop_to_new_sop:
            old_to_new[uid_str] = old_sop_to_new_sop[uid_str]
        else:
            unresolved.append(uid_str)

    if unresolved:
        # Fallback geometrico por Z para los UID que no se pudieron mapear
        # directamente (p.ej. el RT no proviene de esta misma sesion de
        # anonimizacion de CT).
        missing_without_z = [u for u in unresolved if u not in sop_to_z]
        if missing_without_z:
            used_z = {sop_to_z[u] for u in unresolved if u in sop_to_z}
            full_range = set(z_to_new_sop.keys())
            leftover_z = sorted(full_range - used_z)
            if len(missing_without_z) != len(leftover_z):
                raise ValueError(
                    f"No se puede emparejar {len(missing_without_z)} corte(s) referenciado(s) "
                    f"por el RTSTRUCT sin contorno propio (quedan {len(leftover_z)} Z libres "
                    "en el CT). Revisar manualmente: " + ", ".join(missing_without_z)
                )
            for uid, z in zip(missing_without_z, leftover_z):
                sop_to_z[uid] = z

        for uid in unresolved:
            z = sop_to_z[uid]
            if z not in z_to_new_sop:
                raise ValueError(f"No hay corte de CT en Z={z} para casar con el SOPInstanceUID {uid}")
            old_to_new[uid] = z_to_new_sop[z]

    return old_to_new


def _relink_rtstruct(rtstruct: FileDataset, old_to_new: dict[str, str], new_for: str, new_study: str, new_series: str) -> None:
    ref_frame = rtstruct.ReferencedFrameOfReferenceSequence[0]
    ref_frame.FrameOfReferenceUID = new_for
    ref_study = ref_frame.RTReferencedStudySequence[0]
    ref_study.ReferencedSOPInstanceUID = new_study
    ref_series = ref_study.RTReferencedSeriesSequence[0]
    ref_series.SeriesInstanceUID = new_series

    for item in ref_series.ContourImageSequence:
        item.ReferencedSOPInstanceUID = old_to_new[str(item.ReferencedSOPInstanceUID)]

    for roi_contour in rtstruct.ROIContourSequence:
        contour_seq = roi_contour.get("ContourSequence")
        if not contour_seq:
            continue
        for contour in contour_seq:
            cis = contour.get("ContourImageSequence")
            if not cis:
                continue
            cis[0].ReferencedSOPInstanceUID = old_to_new[str(cis[0].ReferencedSOPInstanceUID)]

    rtstruct.StudyInstanceUID = new_study


def _relink_rtplan(rtplan: FileDataset, new_for: str, new_study: str, rtstruct_sop: str | None) -> None:
    rtplan.FrameOfReferenceUID = new_for
    rtplan.StudyInstanceUID = new_study
    if rtstruct_sop is not None and rtplan.get("ReferencedStructureSetSequence"):
        # Bug heredado de la anonimizacion original: esta referencia puede
        # apuntar al SOPInstanceUID PRE-anonimizacion del RTSTRUCT. Se corrige
        # para que apunte al RTSTRUCT anonimizado real.
        rtplan.ReferencedStructureSetSequence[0].ReferencedSOPInstanceUID = rtstruct_sop


def _relink_rtdose(rtdose: FileDataset, new_for: str, new_study: str, rtplan_sop: str | None) -> None:
    rtdose.FrameOfReferenceUID = new_for
    rtdose.StudyInstanceUID = new_study
    if rtplan_sop is not None and rtdose.get("ReferencedRTPlanSequence"):
        # Mismo bug heredado: corrige la referencia para que apunte al
        # RTPLAN anonimizado real.
        rtdose.ReferencedRTPlanSequence[0].ReferencedSOPInstanceUID = rtplan_sop


def run_pipeline(
    inventory: Inventory,
    config: AnonymizationConfig,
    output_dir: Path,
    log: LogFn = _noop_log,
) -> PipelineResult:
    """Anonimiza el CT y los RT presentes en el inventario, y reenlaza las
    referencias cruzadas. Guarda todo en output_dir sin tocar los originales."""
    result = PipelineResult(output_dir=output_dir)
    reset_uid_cache()

    old_sop_to_new_sop: dict[str, str] = {}
    z_to_new_sop: dict[float, str] = {}
    new_for = new_study = new_series = None

    if inventory.ct_slices:
        ct_dir = output_dir / "CT"
        ct_dir.mkdir(parents=True, exist_ok=True)
        result.ct_dir = ct_dir
        for slice_ in inventory.ct_slices:
            # Se relee el archivo completo (con pixeles) para no perder la
            # imagen: el inventario solo cargo metadatos (stop_before_pixels=True).
            full_ds = read_dicom(slice_.path, stop_before_pixels=False)
            old_sop = str(full_ds.SOPInstanceUID)
            anon_ds = anonymize_dataset_copy(full_ds, config)
            new_sop = str(anon_ds.SOPInstanceUID)
            old_sop_to_new_sop[old_sop] = new_sop
            z_to_new_sop[round(slice_.z)] = new_sop
            new_for = str(anon_ds.FrameOfReferenceUID)
            new_study = str(anon_ds.StudyInstanceUID)
            new_series = str(anon_ds.SeriesInstanceUID)

            instance_number = int(anon_ds.InstanceNumber)
            dst_path = ct_dir / f"CT_{instance_number:03d}.dcm"
            anon_ds.save_as(str(dst_path), write_like_original=False)
            result.ct_count += 1
        log(f"CT anonimizado: {result.ct_count} corte(s) guardado(s) en {ct_dir}")
    else:
        log("No se ha encontrado ninguna serie CT en la carpeta de entrada.")

    anon_rtstruct = None
    if inventory.rtstruct is not None:
        rtstruct_full = read_dicom(inventory.rtstruct.path, stop_before_pixels=False)
        anon_rtstruct = anonymize_dataset_copy(rtstruct_full, config)
        if new_for is not None:
            old_to_new = _build_old_to_new_sop_map(anon_rtstruct, old_sop_to_new_sop, z_to_new_sop)
            log(f"RTSTRUCT: {len(old_to_new)} referencia(s) a cortes CT reenlazadas")
            _relink_rtstruct(anon_rtstruct, old_to_new, new_for, new_study, new_series)
        else:
            result.warnings.append("RTSTRUCT presente pero no hay CT: no se ha podido reenlazar.")
        result.rtstruct_path = output_dir / "RTSTRUCT.dcm"
        anon_rtstruct.save_as(str(result.rtstruct_path), write_like_original=False)
        log(f"RTSTRUCT anonimizado guardado en {result.rtstruct_path}")

    anon_rtplan = None
    if inventory.rtplan is not None:
        rtplan_full = read_dicom(inventory.rtplan.path, stop_before_pixels=False)
        anon_rtplan = anonymize_dataset_copy(rtplan_full, config)
        if new_for is not None:
            rtstruct_sop = str(anon_rtstruct.SOPInstanceUID) if anon_rtstruct is not None else None
            _relink_rtplan(anon_rtplan, new_for, new_study, rtstruct_sop)
        else:
            result.warnings.append("RTPLAN presente pero no hay CT: no se ha podido reenlazar.")
        result.rtplan_path = output_dir / "RTPLAN.dcm"
        anon_rtplan.save_as(str(result.rtplan_path), write_like_original=False)
        log(f"RTPLAN anonimizado guardado en {result.rtplan_path}")

    if inventory.rtdose is not None:
        rtdose_full = read_dicom(inventory.rtdose.path, stop_before_pixels=False)
        anon_rtdose = anonymize_dataset_copy(rtdose_full, config)
        if new_for is not None:
            rtplan_sop = str(anon_rtplan.SOPInstanceUID) if anon_rtplan is not None else None
            _relink_rtdose(anon_rtdose, new_for, new_study, rtplan_sop)
        else:
            result.warnings.append("RTDOSE presente pero no hay CT: no se ha podido reenlazar.")
        result.rtdose_path = output_dir / "RTDOSE.dcm"
        anon_rtdose.save_as(str(result.rtdose_path), write_like_original=False)
        log(f"RTDOSE anonimizado guardado en {result.rtdose_path}")

    result.checks = _validate(inventory, anon_rtstruct, anon_rtplan if inventory.rtplan else None,
                               set(old_sop_to_new_sop.values()), new_for, new_study)
    return result


def _validate(
    inventory: Inventory,
    anon_rtstruct: FileDataset | None,
    anon_rtplan: FileDataset | None,
    ct_sop_uids: set[str],
    new_for: str | None,
    new_study: str | None,
) -> list[CheckResult]:
    checks: list[CheckResult] = []

    if anon_rtstruct is not None and ct_sop_uids:
        ref_series = _get_series_contour_image_sequence(anon_rtstruct)
        bad = [
            str(c.ReferencedSOPInstanceUID)
            for c in ref_series.ContourImageSequence
            if str(c.ReferencedSOPInstanceUID) not in ct_sop_uids
        ]
        checks.append(CheckResult(
            "RTSTRUCT: todos los cortes referenciados existen en el CT",
            not bad,
            f"UID sin corte correspondiente: {bad}" if bad else "",
        ))
        checks.append(CheckResult(
            "RTSTRUCT: FrameOfReferenceUID coincide con el CT",
            str(anon_rtstruct.ReferencedFrameOfReferenceSequence[0].FrameOfReferenceUID) == new_for,
        ))
        checks.append(CheckResult(
            "RTSTRUCT: StudyInstanceUID coincide con el CT",
            str(anon_rtstruct.StudyInstanceUID) == new_study,
        ))

    if anon_rtplan is not None and new_for is not None:
        checks.append(CheckResult(
            "RTPLAN: FrameOfReferenceUID coincide con el CT",
            str(anon_rtplan.FrameOfReferenceUID) == new_for,
        ))
        checks.append(CheckResult(
            "RTPLAN: StudyInstanceUID coincide con el CT",
            str(anon_rtplan.StudyInstanceUID) == new_study,
        ))
        if anon_rtstruct is not None and anon_rtplan.get("ReferencedStructureSetSequence"):
            checks.append(CheckResult(
                "RTPLAN: referencia al RTSTRUCT correcta",
                str(anon_rtplan.ReferencedStructureSetSequence[0].ReferencedSOPInstanceUID)
                == str(anon_rtstruct.SOPInstanceUID),
            ))

    return checks
