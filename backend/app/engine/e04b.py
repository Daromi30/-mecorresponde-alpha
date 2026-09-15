from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Any

RULE_START = date(2026, 2, 12)
RULE_ID = "ELEC_ADDON_END_WITH_SUPPLY"
RULE_SOURCE_URL = "https://www.boe.es/eli/es/rd/2026/02/11/88"


@dataclass
class FactValue:
    value: Any
    state: str = "asserted"
    user_confirmed: bool = False


@dataclass
class EngineResult:
    viability: str
    scope_status: str
    claimable_amount: float | None
    worth_pursuing: str
    reasoning_summary: str
    counterarguments: list[dict[str, Any]]
    missing_facts: list[str]
    next_action: str
    rule_result: str
    failed_conditions: list[str]
    calculation: dict[str, Any] | None
    sources: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _raw(facts: dict[str, FactValue], key: str, default=None):
    return facts.get(key).value if key in facts else default


def _verified(facts: dict[str, FactValue], key: str) -> bool:
    f = facts.get(key)
    return bool(f and (f.state == "confirmed" or f.user_confirmed))


def evaluate_e04b(facts: dict[str, FactValue]) -> EngineResult:
    missing: list[str] = []
    failed: list[str] = []
    counterarguments: list[dict[str, Any]] = []
    sources = [{"title": "Real Decreto 88/2026, art. 32.4", "url": RULE_SOURCE_URL}]

    ever_contracted = _raw(facts, "electricity.addon.ever_contracted", True)
    if ever_contracted is False:
        return EngineResult(
            viability="RECLASSIFY", scope_status="REDIRECT_E04A", claimable_amount=None,
            worth_pursuing="NEEDS_REANALYSIS",
            reasoning_summary="El usuario niega haber contratado el servicio. Debe analizarse como E04-A (servicio no contratado), no como E04-B.",
            counterarguments=[], missing_facts=[], next_action="RECLASSIFY_E04A",
            rule_result="NOT_APPLICABLE", failed_conditions=["ever_contracted=false"], calculation=None, sources=sources
        )

    end_date = _raw(facts, "electricity.supply_end_date")
    if not end_date:
        missing.append("electricity.supply_end_date")
    elif isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)

    addon_identity = _raw(facts, "electricity.addon.identity")
    if not addon_identity:
        missing.append("electricity.addon.identity")

    joint = _raw(facts, "electricity.addon.contracted_with_supply")
    if joint is None:
        missing.append("electricity.addon.contracted_with_supply")
        counterarguments.append({"type":"INDEPENDENT_ADDON_CONTRACT","status":"open","impact":"critical"})
    elif joint is False:
        failed.append("addon_not_contracted_with_supply")
        counterarguments.append({"type":"INDEPENDENT_ADDON_CONTRACT","status":"confirmed","impact":"critical"})

    keep = _raw(facts, "electricity.addon.keep_requested")
    if keep is True:
        failed.append("express_keep_request")
        counterarguments.append({"type":"EXPRESS_KEEP_REQUEST","status":"confirmed","impact":"critical"})
    elif keep is None:
        counterarguments.append({"type":"EXPRESS_KEEP_REQUEST","status":"open","impact":"critical"})

    if _raw(facts, "company.asserts_independent_addon_contract", False):
        counterarguments.append({"type":"INDEPENDENT_ADDON_CONTRACT","status":"open","impact":"critical","origin":"company_response"})
    if _raw(facts, "company.asserts_keep_request", False):
        counterarguments.append({"type":"EXPRESS_KEEP_REQUEST","status":"open","impact":"critical","origin":"company_response"})

    charges = _raw(facts, "electricity.addon.charges")
    if not charges:
        missing.append("electricity.addon.charges")
        charges = []

    if end_date and end_date < RULE_START:
        return EngineResult(
            viability="PROFESSIONAL_REVIEW", scope_status="LEGACY_REVIEW", claimable_amount=None,
            worth_pursuing="PROFESSIONAL_REVIEW",
            reasoning_summary="La terminación es anterior al ruleset E04-B soportado desde el 12/02/2026. No se aplica retrospectivamente la regla actual.",
            counterarguments=counterarguments, missing_facts=missing, next_action="HUMAN_REVIEW_LEGACY",
            rule_result="OUT_OF_VALIDITY", failed_conditions=["event_before_rule_start"], calculation=None, sources=sources
        )

    if failed:
        reason = "El supuesto E04-B no queda sustentado con los hechos actuales."
        if "addon_not_contracted_with_supply" in failed:
            reason = "El servicio consta como contrato independiente, por lo que la regla de extinción conjunta no resulta aplicable en este árbol."
        if "express_keep_request" in failed:
            reason = "Consta una petición expresa de mantener el servicio después de terminar el suministro; E04-B pierde fundamento por esta vía."
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0,
            worth_pursuing="NO_PAID_MANAGEMENT", reasoning_summary=reason,
            counterarguments=counterarguments, missing_facts=missing, next_action="EXPLAIN_NO_E04B_BASIS",
            rule_result="FAILED", failed_conditions=failed, calculation=None, sources=sources
        )

    fully_post: list[dict[str, Any]] = []
    mixed: list[dict[str, Any]] = []
    unknown_period: list[dict[str, Any]] = []
    pre: list[dict[str, Any]] = []

    if end_date:
        for ch in charges:
            ps, pe = ch.get("service_period_start"), ch.get("service_period_end")
            if ps: ps = date.fromisoformat(ps) if isinstance(ps, str) else ps
            if pe: pe = date.fromisoformat(pe) if isinstance(pe, str) else pe
            if not ps or not pe:
                unknown_period.append(ch); continue
            if ps > end_date:
                fully_post.append(ch)
            elif pe <= end_date:
                pre.append(ch)
            else:
                mixed.append(ch)

    amount = round(sum(float(ch.get("amount", 0)) for ch in fully_post if ch.get("evidence_verified", False)), 2)
    calculation = {
        "type":"sum_verified_full_post_termination_charges",
        "included": fully_post, "excluded_pre": pre, "mixed_requires_review": mixed,
        "unknown_period": unknown_period, "result": amount
    }

    if mixed:
        counterarguments.append({"type":"MIXED_SERVICE_PERIOD","status":"open","impact":"material"})
    if unknown_period:
        counterarguments.append({"type":"CHARGE_PERIOD_UNKNOWN","status":"open","impact":"critical"})

    if missing:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=amount or None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Faltan hechos materiales para cerrar el diagnóstico sin asumir información.",
            counterarguments=counterarguments, missing_facts=sorted(set(missing)), next_action="REQUEST_MATERIAL_FACT",
            rule_result="PENDING", failed_conditions=[], calculation=calculation, sources=sources
        )

    if unknown_period and amount == 0:
        return EngineResult(
            viability="INSUFFICIENT_INFORMATION", scope_status="SUPPORTED", claimable_amount=None,
            worth_pursuing="NEEDS_INFORMATION",
            reasoning_summary="Hay cargos posteriores en fecha, pero falta saber a qué período del servicio corresponden. No se consideran reclamables automáticamente.",
            counterarguments=counterarguments, missing_facts=["charge.service_period"], next_action="REQUEST_CHARGE_PERIOD",
            rule_result="PENDING", failed_conditions=[], calculation=calculation, sources=sources
        )

    if amount <= 0:
        return EngineResult(
            viability="LOW", scope_status="SUPPORTED", claimable_amount=0.0,
            worth_pursuing="NO_PAID_MANAGEMENT",
            reasoning_summary="No se han identificado cargos acreditados correspondientes íntegramente a períodos posteriores al fin del suministro.",
            counterarguments=counterarguments, missing_facts=[], next_action="EXPLAIN_NO_CLAIMABLE_CHARGE",
            rule_result="APPLIES_BUT_NO_AMOUNT", failed_conditions=[], calculation=calculation, sources=sources
        )

    critical_verified = all(_verified(facts, k) for k in [
        "electricity.supply_end_date", "electricity.addon.contracted_with_supply", "electricity.addon.keep_requested"
    ])
    open_critical = any(c["impact"] == "critical" and c["status"] == "open" for c in counterarguments)
    viability = "HIGH" if critical_verified and not open_critical and not mixed else "MEDIUM"
    worth = "YES_IF_LOW_COST" if amount < 30 else "YES"
    return EngineResult(
        viability=viability, scope_status="SUPPORTED", claimable_amount=amount,
        worth_pursuing=worth,
        reasoning_summary=(
            f"Se han identificado {amount:.2f} € en cargos acreditados correspondientes a períodos posteriores al fin del suministro. "
            "El servicio consta como contratado junto con el suministro y no consta una petición expresa de mantenerlo."
        ),
        counterarguments=counterarguments, missing_facts=[], next_action="PREPARE_INITIAL_CLAIM",
        rule_result="APPLIES", failed_conditions=[], calculation=calculation, sources=sources
    )
