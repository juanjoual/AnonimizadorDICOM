"""Reglas de anonimizacion configurables, basadas en las usadas en
Notebooks/Anonimizado2.ipynb y Anonimizado3.ipynb.

Por defecto, dicomanonymizer.anonymize_dataset() ya elimina/reemplaza los
campos identificativos habituales (PatientName, PatientID, InstitutionName,
direcciones, etc.) y regenera los UID (StudyInstanceUID, SeriesInstanceUID,
SOPInstanceUID, FrameOfReferenceUID...). Aqui solo se definen las excepciones:
campos clinicos que se quieren conservar y el tratamiento especial de la
fecha de nacimiento.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

from dicomanonymizer import anonymize_dataset, keep
from dicomanonymizer import simpledicomanonymizer
from pydicom.dataset import FileDataset

# Tags "conservables" que en los notebooks originales se marcan con `keep`
# (se dejan tal cual, sin anonimizar). Clave = etiqueta mostrada en la GUI.
KEEPABLE_TAGS: dict[str, tuple[int, int]] = {
    "Sexo del paciente (PatientSex)": (0x0010, 0x0040),
    "Edad del paciente (PatientAge)": (0x0010, 0x1010),
    "Talla del paciente (PatientSize)": (0x0010, 0x1020),
    "Peso del paciente (PatientWeight)": (0x0010, 0x1030),
    "Grupo etnico (EthnicGroup)": (0x0010, 0x2160),
    "Nombre del protocolo (ProtocolName)": (0x0018, 0x1030),
}

PATIENT_BIRTH_DATE_TAG = (0x0010, 0x0030)

BIRTH_DATE_MODE_YEAR_ONLY = "year_only"
BIRTH_DATE_MODE_REMOVE = "remove"


def _set_birth_date_to_year(dataset, tag):
    element = dataset.get(tag)
    if element is not None and element.value:
        element.value = f"{str(element.value)[:4]}0101"


@dataclass
class AnonymizationConfig:
    """Configuracion elegida por el usuario en la GUI."""

    keep_tags: set[tuple[int, int]] = field(default_factory=lambda: set(KEEPABLE_TAGS.values()))
    birth_date_mode: str = BIRTH_DATE_MODE_YEAR_ONLY
    patient_label: str | None = None  # Si se indica, fija PatientName/PatientID
    delete_private_tags: bool = True

    def build_extra_rules(self) -> dict[tuple[int, int], Callable]:
        rules: dict[tuple[int, int], Callable] = {tag: keep for tag in self.keep_tags}
        if self.birth_date_mode == BIRTH_DATE_MODE_YEAR_ONLY:
            rules[PATIENT_BIRTH_DATE_TAG] = _set_birth_date_to_year
        # Si el modo es "remove", no se añade regla y se aplica el
        # comportamiento por defecto de dicomanonymizer (borra la fecha).
        return rules


def reset_uid_cache() -> None:
    """Limpia la cache global old_uid->new_uid de dicomanonymizer.

    Debe llamarse antes de procesar cada carpeta/paciente nuevo para que los
    UID regenerados no se mezclen entre ejecuciones sucesivas dentro del
    mismo proceso (la GUI puede procesar varias carpetas sin reiniciarse).
    """
    simpledicomanonymizer.dictionary.clear()


def anonymize_dataset_copy(
    dataset: FileDataset, config: AnonymizationConfig
) -> FileDataset:
    """Devuelve una copia anonimizada del dataset, sin modificar el original."""
    ds = copy.deepcopy(dataset)
    extra_rules = config.build_extra_rules()
    anonymize_dataset(ds, extra_rules, delete_private_tags=config.delete_private_tags)
    if config.patient_label:
        ds.PatientName = config.patient_label
        ds.PatientID = config.patient_label
    return ds
