from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from .models import LegalSource


@dataclass(frozen=True)
class OfficialLegalSource:
    authority: str
    title: str
    official_url: str
    publication_date: date
    jurisdiction: str = "ES"
    status: str = "active"


# Source metadata is deliberately separate from legal-rule versions. Source metadata
# (for example an official publication date or canonical URL) can be corrected in place.
# A substantive rule change must instead create a new LegalRuleVersion.
OFFICIAL_LEGAL_SOURCES: dict[str, OfficialLegalSource] = {
    "RD88_2026": OfficialLegalSource(
        authority="BOE / Ministerio para la Transición Ecológica y el Reto Demográfico",
        title="Real Decreto 88/2026, de 11 de febrero",
        official_url="https://www.boe.es/eli/es/rd/2026/02/11/88",
        publication_date=date(2026, 2, 12),
    ),
    "RD899_2009": OfficialLegalSource(
        authority="BOE / Ministerio de la Presidencia",
        title="Real Decreto 899/2009, de 22 de mayo, por el que se aprueba la carta de derechos del usuario de los servicios de comunicaciones electrónicas",
        official_url="https://www.boe.es/eli/es/rd/2009/05/22/899",
        publication_date=date(2009, 5, 30),
    ),
    "TRLGDCU": OfficialLegalSource(
        authority="BOE / Jefatura del Estado",
        title=(
            "Real Decreto Legislativo 1/2007, de 16 de noviembre, por el que se aprueba "
            "el texto refundido de la Ley General para la Defensa de los Consumidores y "
            "Usuarios y otras leyes complementarias"
        ),
        official_url="https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555",
        publication_date=date(2007, 11, 30),
    ),
    "CODIGO_CIVIL": OfficialLegalSource(
        authority="Gaceta de Madrid / Ministerio de Gracia y Justicia",
        title="Real Decreto de 24 de julio de 1889 por el que se publica el Código Civil",
        official_url="https://www.boe.es/buscar/act.php?id=BOE-A-1889-4763",
        publication_date=date(1889, 7, 25),
    ),
}


def reconcile_legal_sources(db: Session) -> None:
    """Make persisted source provenance match the reviewed official registry.

    ``seed_legal`` creates the rows when needed. This reconciliation then fixes stale
    metadata in already-running databases without mutating substantive rule versions.
    Missing sources fail closed because registry drift should never be silent.
    """
    missing: list[str] = []
    for source_id, expected in OFFICIAL_LEGAL_SOURCES.items():
        source = db.get(LegalSource, source_id)
        if source is None:
            missing.append(source_id)
            continue
        source.authority = expected.authority
        source.title = expected.title
        source.official_url = expected.official_url
        source.publication_date = expected.publication_date
        source.jurisdiction = expected.jurisdiction
        source.status = expected.status

    if missing:
        raise RuntimeError(f"Missing reviewed legal sources after seed: {sorted(missing)}")
