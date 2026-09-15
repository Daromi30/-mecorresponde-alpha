from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .gateway import ModelGateway
from .model_contracts import (
    validate_classification,
    validate_extraction,
    validate_response_analysis,
)


@dataclass
class GuardedModelGateway:
    """Trust boundary around any current or future model provider.

    Providers may interpret user/company text, but every output is validated before
    the rest of the resolution engine can observe it. Legal decisions and sources
    are deliberately absent from these contracts.
    """

    inner: ModelGateway

    def classify(self, text: str) -> dict[str, Any]:
        return validate_classification(self.inner.classify(text))

    def extract(self, text: str) -> dict[str, Any]:
        return validate_extraction(self.inner.extract(text))

    def analyze_response(self, text: str) -> dict[str, Any]:
        return validate_response_analysis(self.inner.analyze_response(text))
