from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..family_manifest import FAMILY_MANIFEST


class ModelOutputRejected(ValueError):
    """Raised when untrusted model output crosses the permitted intelligence boundary."""


class ClassificationOutput(BaseModel):
    """Routing only. A model is not allowed to return law, remedies, deadlines or legal conclusions."""

    model_config = ConfigDict(extra="forbid")

    vertical: str | None = None
    family: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_family_vertical_pair(self):
        if self.family is None:
            return self
        manifest = FAMILY_MANIFEST.get(self.family)
        if manifest is None:
            raise ValueError("family is not registered in the resolution-family manifest")
        if self.vertical != manifest.vertical:
            raise ValueError("family and vertical do not match the registered manifest")
        return self


CompanyArgument = Literal[
    "INDEPENDENT_ADDON_CONTRACT",
    "EXPRESS_KEEP_REQUEST",
    "CONSENT_EVIDENCE",
    "CUPS_CORRECT_ASSERTED",
    "PRICING_MATCHES_CONTRACT_ASSERTED",
    "ESTIMATE_ALLOWED_ASSERTED",
    "NOTICE_COMPLIANT_ASSERTED",
    "CONTRACTUAL_PRICE_FORMULA_ASSERTED",
    "CORRECT_AMOUNT_DISPUTED",
    "DIFFERENT_DEBTS",
    "FIXED_PRICE_FIRST_YEAR_ASSERTED",
    "MISUSE_OR_ACCIDENTAL_DAMAGE",
    "OUTSIDE_LEGAL_GUARANTEE",
    "REFER_TO_MANUFACTURER",
    "GOODS_MATCH_CONTRACT_ASSERTED",
    "DELIVERY_PROOF_ASSERTED",
    "WITHDRAWAL_LATE_ASSERTED",
    "WITHDRAWAL_EXCEPTION_ASSERTED",
    "INTERNET_INTERRUPTION_COMPENSATION_APPLIED_ASSERTED",
    "FLIGHT_REFUND_ALREADY_PAID_ASSERTED",
    "DENIED_BOARDING_COMPENSATION_PAID_ASSERTED",
    "PAYMENT_AUTHENTICATED_ASSERTED",
    "ARTICLE_48_4_EXCEPTION_ASSERTED",
    "BANK_FEE_REQUESTED_AND_PROVIDED_ASSERTED",
    "RENT_DEPOSIT_DEDUCTIONS_ASSERTED",
    "INSURANCE_MINIMUM_PAYMENT_PAID_ASSERTED",
    "INSURANCE_NONRENEWAL_LATE_ASSERTED",
]


class ResponseAnalysisOutput(BaseModel):
    """Semantic reading of a company response, never a legal decision."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["ACCEPTANCE", "DENIAL", "PARTIAL", "UNKNOWN"]
    arguments: list[CompanyArgument] = Field(default_factory=list, max_length=20)


class ExtractionOutput(BaseModel):
    """Literal extraction only. Extracted monetary mentions are not claimable amounts."""

    model_config = ConfigDict(extra="forbid")

    mentioned_amounts: list[float] = Field(default_factory=list, max_length=50)


PROHIBITED_LEGAL_FIELDS = frozenset(
    {
        "legal_basis",
        "legal_source",
        "legal_sources",
        "law",
        "article",
        "deadline",
        "deadline_days",
        "authority",
        "organism",
        "remedy",
        "remedies",
        "claimable_amount",
        "economic_value",
        "viability",
        "worth_pursuing",
        "success_probability",
        "probability_of_success",
        "legal_conclusion",
    }
)


def _reject_explicit_legal_fields(value: Any) -> None:
    """Defense in depth before schema validation, including nested dictionaries."""

    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in PROHIBITED_LEGAL_FIELDS:
                raise ModelOutputRejected(f"prohibited model field: {key}")
            _reject_explicit_legal_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_explicit_legal_fields(child)


def _validate(schema: type[BaseModel], raw: Any) -> dict[str, Any]:
    _reject_explicit_legal_fields(raw)
    try:
        validated = schema.model_validate(raw)
    except ValidationError as exc:
        raise ModelOutputRejected("model output failed the strict structured-output contract") from exc
    return validated.model_dump(mode="json")


def validate_classification(raw: Any) -> dict[str, Any]:
    return _validate(ClassificationOutput, raw)


def validate_extraction(raw: Any) -> dict[str, Any]:
    return _validate(ExtractionOutput, raw)


def validate_response_analysis(raw: Any) -> dict[str, Any]:
    return _validate(ResponseAnalysisOutput, raw)
