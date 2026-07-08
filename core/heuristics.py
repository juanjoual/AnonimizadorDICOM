"""Heuristica basica para estimar si un archivo DICOM ya ha sido anonimizado.

No es una deteccion perfecta (no hay forma de saberlo con certeza total sin
conocer el proceso de origen), pero combina varias señales habituales:

- Indicadores explicitos: PatientIdentityRemoved, DeidentificationMethod.
- Formato de PatientBirthDate (recortada a año vs fecha completa).
- Presencia de nombre de paciente con pinta de nombre real (formato DICOM PN
  "Apellidos^Nombre") o de campos institucionales/de personal.
- Cantidad de tags privados restantes.
- Patrones de texto tipicos de datos personales (DNI/NIE espanol, telefonos).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydicom.dataset import FileDataset

# VRs de tipo texto donde tiene sentido buscar patrones de datos personales.
_TEXT_VRS = {"LO", "SH", "ST", "LT", "UT", "PN"}

_DNI_NIE_RE = re.compile(r"\b[0-9XYZxyz][0-9]{7}[A-Za-z]\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?\d{9}\b")
_NAME_LIKE_RE = re.compile(r"[A-Za-zÀ-ÿ]+\^[A-Za-zÀ-ÿ^]+")

_IDENTIFYING_TOP_LEVEL_TAGS = [
    ("InstitutionName", "Nombre de institucion"),
    ("InstitutionAddress", "Direccion de institucion"),
    ("ReferringPhysicianName", "Medico remitente"),
    ("OperatorsName", "Nombre del operador"),
    ("RequestingPhysician", "Medico solicitante"),
    ("PerformingPhysicianName", "Medico que realiza el estudio"),
]

# Valores placeholder que algunas herramientas (p.ej. dicomanonymizer) escriben
# en lugar de borrar el tag por completo. No deben contar como "identificable".
_GENERIC_PLACEHOLDER_VALUES = {"anonymized", "anonymous", "anonimo", "removed", ""}


@dataclass
class Finding:
    label: str
    supports_anonymized: bool  # True = a favor de "anonimizado", False = en contra


@dataclass
class AnonymizationReport:
    verdict: str  # "likely_anonymized" | "likely_not_anonymized" | "uncertain"
    score: int
    findings: list[Finding] = field(default_factory=list)


def assess_anonymization(dataset: FileDataset) -> AnonymizationReport:
    findings: list[Finding] = []
    score = 0

    identity_removed = str(dataset.get("PatientIdentityRemoved", "")).upper()
    if identity_removed == "YES":
        findings.append(Finding("PatientIdentityRemoved = YES", True))
        score += 3
    elif identity_removed == "NO":
        findings.append(Finding("PatientIdentityRemoved = NO (declarado explicitamente)", False))
        score -= 3

    deident_method = dataset.get("DeidentificationMethod")
    if deident_method:
        findings.append(Finding(f"DeidentificationMethod presente: '{deident_method}'", True))
        score += 2

    birth_date = dataset.get("PatientBirthDate")
    if birth_date:
        birth_date_str = str(birth_date)
        if re.fullmatch(r"\d{4}0101", birth_date_str) or birth_date_str in ("", "00010101"):
            findings.append(Finding(f"PatientBirthDate con formato recortado ('{birth_date_str}')", True))
            score += 1
        elif re.fullmatch(r"\d{8}", birth_date_str):
            findings.append(Finding(f"PatientBirthDate parece una fecha completa real ('{birth_date_str}')", False))
            score -= 1

    patient_name = str(dataset.get("PatientName", "")).strip()
    if not patient_name or patient_name.upper() in ("ANONYMIZED", "ANONIMO", "ANON"):
        findings.append(Finding(f"PatientName vacio o generico ('{patient_name}')", True))
        score += 1
    elif _NAME_LIKE_RE.search(patient_name):
        findings.append(Finding(f"PatientName con formato de nombre real ('{patient_name}')", False))
        score -= 2

    for tag_name, label in _IDENTIFYING_TOP_LEVEL_TAGS:
        value = dataset.get(tag_name)
        if value and str(value).strip().lower() not in _GENERIC_PLACEHOLDER_VALUES:
            findings.append(Finding(f"{label} presente ('{value}')", False))
            score -= 1

    private_count = sum(1 for e in dataset if e.tag.is_private)
    if private_count > 10:
        findings.append(Finding(f"Quedan {private_count} tags privados (señal debil)", False))
        score -= 1
    elif private_count == 0:
        findings.append(Finding("Sin tags privados restantes", True))
        score += 1

    text_hits: list[str] = []
    for elem in dataset:
        if elem.VR in _TEXT_VRS and elem.value:
            value_str = str(elem.value)
            if _DNI_NIE_RE.search(value_str) or _PHONE_RE.search(value_str):
                text_hits.append(f"{elem.keyword or elem.tag}: '{value_str}'")
    if text_hits:
        findings.append(Finding(
            "Patrones de posible DNI/NIE o telefono encontrados: " + "; ".join(text_hits[:5]),
            False,
        ))
        score -= 2 * len(text_hits[:5])

    if score >= 3:
        verdict = "likely_anonymized"
    elif score <= -2:
        verdict = "likely_not_anonymized"
    else:
        verdict = "uncertain"

    return AnonymizationReport(verdict=verdict, score=score, findings=findings)
