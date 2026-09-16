from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..admin_auth import require_admin
from ..config import settings
from ..db import engine, get_db
from ..family_manifest import FAMILY_MANIFEST, supported_family_codes
from ..models import LegalRuleVersion, LegalSource
from ..services_v2 import EVALUATORS, FAMILY_RULES
from ..storage import StorageConfigurationError, storage_status


router = APIRouter(
    prefix="/api/admin",
    tags=["admin-readiness"],
    dependencies=[Depends(require_admin)],
)


# Operational capabilities stay explicit and fail closed until they have been
# independently verified. Database recovery is proven continuously by CI with a
# real PostgreSQL custom dump and isolated restore rehearsal.
DATABASE_LIFECYCLE_MANAGED = False
DATABASE_RECOVERY_AVAILABLE = True
PRIVACY_INFORMATION_PUBLISHED = False

# These capabilities are executable CI contracts, not launch claims. The checks
# are intentionally limited to an internal beta using synthetic/test data. If any
# of the underlying regressions break, branch protection prevents that revision
# from reaching main.
FOURTEEN_FAMILY_ACCEPTANCE_PROVEN = True
FOURTEEN_FAMILY_RESPONSE_RESOLUTION_LOOP_PROVEN = True
PROFESSIONAL_ESCALATION_HANDOFF_PROVEN = True
GUIDED_BROWSER_INPUT_CONTRACT_PROVEN = True
FULL_SAVED_ACCOUNT_JOURNEY_PROVEN = True


def _check(
    key: str,
    ok: bool,
    *,
    label: str,
    detail: str,
    severity: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "ok": bool(ok),
        "label": label,
        "detail": detail,
        "severity": severity,
        "metadata": metadata or {},
    }


def _storage_check() -> dict[str, Any]:
    try:
        status = storage_status()
    except StorageConfigurationError as exc:
        return _check(
            "persistent_document_storage",
            False,
            label="Almacenamiento documental persistente",
            detail="La configuración de almacenamiento documental es inválida.",
            severity="BETA_BLOCKER",
            metadata={"reason": str(exc)},
        )

    ok = bool(status.persistent and status.uploads_allowed)
    return _check(
        "persistent_document_storage",
        ok,
        label="Almacenamiento documental persistente",
        detail=(
            "Los documentos pueden guardarse en un backend persistente."
            if ok
            else "La beta completa no debe aceptar documentos reales hasta disponer de almacenamiento persistente."
        ),
        severity="BETA_BLOCKER",
        metadata={
            "backend": status.backend,
            "persistent": status.persistent,
            "uploads_allowed": status.uploads_allowed,
        },
    )


def _legal_catalog_check(db: Session) -> dict[str, Any]:
    source_count = int(db.scalar(select(func.count()).select_from(LegalSource)) or 0)
    approved_rows = db.scalars(
        select(LegalRuleVersion).where(LegalRuleVersion.review_status == "approved")
    ).all()
    approved_keys = {(row.rule_id, row.version) for row in approved_rows}
    approved_rule_ids = {row.rule_id for row in approved_rows}
    required_rule_ids = {
        rule_id
        for entry in FAMILY_MANIFEST.values()
        for rule_id in entry.rule_ids
    }
    missing_rule_ids = sorted(required_rule_ids - approved_rule_ids)
    ok = source_count > 0 and not missing_rule_ids and bool(approved_keys)
    return _check(
        "reviewed_legal_catalog",
        ok,
        label="Catálogo jurídico revisado",
        detail=(
            "Todas las familias registradas tienen sus reglas jurídicas aprobadas en el catálogo."
            if ok
            else "Faltan fuentes o reglas aprobadas para una o más familias registradas."
        ),
        severity="INTERNAL_BETA_BLOCKER",
        metadata={
            "official_sources": source_count,
            "approved_rule_versions": len(approved_keys),
            "required_rule_ids": len(required_rule_ids),
            "missing_rule_ids": missing_rule_ids,
        },
    )


def _family_registry_check() -> dict[str, Any]:
    expected = set(supported_family_codes())
    evaluator_codes = set(EVALUATORS)
    rule_codes = set(FAMILY_RULES)
    missing_evaluators = sorted(expected - evaluator_codes)
    missing_rule_maps = sorted(expected - rule_codes)
    unexpected = sorted((evaluator_codes | rule_codes) - expected)
    ok = not (missing_evaluators or missing_rule_maps or unexpected)
    return _check(
        "resolution_family_registry",
        ok,
        label="Registro multivertical del Motor",
        detail=(
            "Las familias soportadas tienen evaluador y mapa de reglas coherentes."
            if ok
            else "Existe deriva entre el manifiesto de familias y el Motor en ejecución."
        ),
        severity="INTERNAL_BETA_BLOCKER",
        metadata={
            "family_count": len(expected),
            "families": sorted(expected),
            "missing_evaluators": missing_evaluators,
            "missing_rule_maps": missing_rule_maps,
            "unexpected": unexpected,
        },
    )


@router.get("/readiness")
def beta_readiness(db: Session = Depends(get_db)) -> dict[str, Any]:
    backend = engine.url.get_backend_name()
    email_operational = settings.transactional_email_operational
    verification_enforced = bool(email_operational and settings.email_verification_enforced)

    persistent_database = _check(
        "persistent_database",
        backend == "postgresql",
        label="Base de datos persistente",
        detail=(
            "PostgreSQL persistente está activo."
            if backend == "postgresql"
            else "La beta interna desplegada requiere PostgreSQL persistente para conservar expedientes entre reinicios."
        ),
        severity="INTERNAL_BETA_BLOCKER",
        metadata={"backend": backend},
    )
    family_registry = _family_registry_check()
    legal_catalog = _legal_catalog_check(db)
    protected_backoffice = _check(
        "protected_backoffice",
        bool(settings.admin_api_token.strip()),
        label="Backoffice protegido",
        detail=(
            "El backoffice exige un secreto de administración configurado."
            if settings.admin_api_token.strip()
            else "Falta configurar el secreto del backoffice."
        ),
        severity="INTERNAL_BETA_BLOCKER",
    )

    checks = [
        persistent_database,
        _check(
            "database_recovery",
            DATABASE_RECOVERY_AVAILABLE,
            label="Recuperación y copias de seguridad",
            detail=(
                "Existe un mecanismo probado de copia y recuperación de PostgreSQL, ensayado en CI mediante restauración aislada."
                if DATABASE_RECOVERY_AVAILABLE
                else "No existe todavía una vía probada de recuperación del datastore."
            ),
            severity="INTERNAL_BETA_BLOCKER",
            metadata={
                "verification": "postgresql_custom_dump_isolated_restore_ci",
                "production_backup_scheduling": False,
            },
        ),
        family_registry,
        legal_catalog,
        protected_backoffice,
        _check(
            "fourteen_family_acceptance",
            FOURTEEN_FAMILY_ACCEPTANCE_PROVEN,
            label="Aceptación end-to-end de familias",
            detail="Las 14 familias registradas tienen un escenario de aceptación que llega desde intake hasta una acción con procedencia jurídica verificada.",
            severity="INTERNAL_BETA_BLOCKER",
            metadata={"family_count": len(FAMILY_MANIFEST), "verification": "ci_beta_acceptance_matrix"},
        ),
        _check(
            "fourteen_family_response_resolution_loop",
            FOURTEEN_FAMILY_RESPONSE_RESOLUTION_LOOP_PROVEN,
            label="Respuesta y resolución end-to-end de familias",
            detail=(
                "Las 14 familias registradas recorren en CI el envío, una respuesta favorable, la comprobación de cumplimiento y la resolución; "
                "también se prueba que una respuesta parcial no reabre una segunda reclamación inicial y deriva a revisión humana de escalado."
            ),
            severity="INTERNAL_BETA_BLOCKER",
            metadata={
                "family_count": len(FAMILY_MANIFEST),
                "verification": "ci_all_family_response_resolution_loop",
                "partial_response_escalation_guard": True,
            },
        ),
        _check(
            "post_response_professional_handoff",
            PROFESSIONAL_ESCALATION_HANDOFF_PROVEN,
            label="Escalado profesional protegido",
            detail=(
                "CI prueba que un expediente detenido tras la respuesta de la empresa puede pasar a revisión profesional con dossier trazable, "
                "sin reabrir la reclamación inicial ni seleccionar automáticamente una vía jurídica, organismo, plazo o probabilidad de éxito."
            ),
            severity="INTERNAL_BETA_BLOCKER",
            metadata={
                "verification": "ci_professional_escalation_handoff_and_guards",
                "generic_note_completion_fail_closed": True,
                "post_response_reanalysis_guard": True,
                "automatic_legal_route_selection": False,
            },
        ),
        _check(
            "guided_browser_input_contract",
            GUIDED_BROWSER_INPUT_CONTRACT_PROVEN,
            label="Preguntas guiadas utilizables en navegador",
            detail="Los tipos de entrada emitidos por las 14 familias tienen un renderer seguro en la interfaz y los formatos desconocidos fallan cerrado.",
            severity="INTERNAL_BETA_BLOCKER",
            metadata={"verification": "ci_guided_question_acceptance_and_js_contract"},
        ),
        _check(
            "saved_account_resolution_journey",
            FULL_SAVED_ACCOUNT_JOURNEY_PROVEN,
            label="Recorrido completo con cuenta guardada",
            detail="CI recorre creación anónima, cuenta, expediente, diagnóstico, envío, reentrada, respuesta, cumplimiento, resolución, timeline, handoff y exportación.",
            severity="INTERNAL_BETA_BLOCKER",
            metadata={"verification": "ci_full_saved_account_beta_journey"},
        ),
        _check(
            "database_lifecycle_managed",
            DATABASE_LIFECYCLE_MANAGED,
            label="Ciclo de vida de la base de datos",
            detail=(
                "El ciclo de vida operativo de la base está gestionado."
                if DATABASE_LIFECYCLE_MANAGED
                else "El ciclo de vida operativo de la base de datos sigue pendiente antes de usar datos reales en beta."
            ),
            severity="BETA_BLOCKER",
        ),
        _storage_check(),
        _check(
            "privacy_information",
            PRIVACY_INFORMATION_PUBLISHED,
            label="Información de privacidad para usuarios reales",
            detail=(
                "La información de privacidad revisada está publicada en el momento de recogida de datos."
                if PRIVACY_INFORMATION_PUBLISHED
                else "No debe abrirse una beta con datos personales reales hasta identificar al responsable y publicar información revisada sobre fines, base jurídica, conservación, destinatarios/transferencias y derechos."
            ),
            severity="BETA_BLOCKER",
            metadata={
                "official_guidance": [
                    "https://www.aepd.es/derechos-y-deberes/conoce-tus-derechos/derecho-de-informacion",
                    "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
                ]
            },
        ),
        _check(
            "password_recovery",
            email_operational,
            label="Recuperación de cuenta",
            detail=(
                "La recuperación de contraseña dispone de entrega transaccional configurada y verificada."
                if email_operational
                else "El flujo de recuperación está construido, pero la beta pública sigue bloqueada hasta conectar y verificar un proveedor transaccional."
            ),
            severity="PUBLIC_BETA_BLOCKER",
            metadata={
                "provider_configured": settings.transactional_email_ready,
                "delivery_verified": settings.transactional_email_verified,
            },
        ),
        _check(
            "email_verification",
            verification_enforced,
            label="Verificación de email",
            detail=(
                "La titularidad del email se exige antes de guardar expedientes en la cuenta."
                if verification_enforced
                else "El flujo de verificación está construido, pero no se considera operativo hasta verificar la entrega y activar su obligatoriedad."
            ),
            severity="PUBLIC_BETA_BLOCKER",
            metadata={
                "provider_operational": email_operational,
                "enforcement_enabled": settings.email_verification_enforced,
            },
        ),
        _check(
            "public_indexing",
            settings.public_indexing_ready,
            label="Indexación pública controlada",
            detail=(
                "La URL pública y la indexación SEO están activadas intencionadamente."
                if settings.public_indexing_ready
                else "La aplicación sigue protegida con noindex; es correcto para una beta cerrada, pero no para lanzamiento SEO."
            ),
            severity="PUBLIC_LAUNCH_BLOCKER",
            metadata={"base_url_configured": bool(settings.public_base_url.strip())},
        ),
    ]

    internal_beta_blockers = [
        item["key"]
        for item in checks
        if not item["ok"] and item["severity"] == "INTERNAL_BETA_BLOCKER"
    ]
    beta_blockers = [
        item["key"]
        for item in checks
        if not item["ok"] and item["severity"] in {"INTERNAL_BETA_BLOCKER", "BETA_BLOCKER"}
    ]
    public_beta_blockers = [
        item["key"]
        for item in checks
        if not item["ok"] and item["severity"] in {"INTERNAL_BETA_BLOCKER", "BETA_BLOCKER", "PUBLIC_BETA_BLOCKER"}
    ]
    public_launch_blockers = [
        item["key"]
        for item in checks
        if not item["ok"] and item["severity"] in {
            "INTERNAL_BETA_BLOCKER", "BETA_BLOCKER", "PUBLIC_BETA_BLOCKER", "PUBLIC_LAUNCH_BLOCKER"
        }
    ]

    return {
        "synthetic_internal_beta_ready": not internal_beta_blockers,
        "full_closed_beta_ready": not beta_blockers,
        "public_beta_ready": not public_beta_blockers,
        "public_launch_ready": not public_launch_blockers,
        "internal_beta_blockers": internal_beta_blockers,
        "beta_blockers": beta_blockers,
        "public_beta_blockers": public_beta_blockers,
        "public_launch_blockers": public_launch_blockers,
        "checks": checks,
    }
