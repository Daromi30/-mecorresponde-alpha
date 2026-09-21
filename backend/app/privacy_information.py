from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any


REQUIRED_PRIVACY_FIELDS = (
    "privacy_controller_identity",
    "privacy_controller_contact",
    "privacy_purposes",
    "privacy_legal_basis",
    "privacy_retention",
    "privacy_recipients",
    "privacy_international_transfers",
    "privacy_rights",
    "privacy_automated_decisions",
    "privacy_special_categories",
    "privacy_data_requirement",
    "privacy_notice_version",
)


@dataclass(frozen=True)
class PrivacyInformationStatus:
    ready: bool
    reviewed: bool
    missing_fields: tuple[str, ...]
    notice_version: str


def privacy_information_status(settings: Any) -> PrivacyInformationStatus:
    missing = tuple(
        field
        for field in REQUIRED_PRIVACY_FIELDS
        if not str(getattr(settings, field, "") or "").strip()
    )
    reviewed = bool(getattr(settings, "privacy_information_reviewed", False))
    return PrivacyInformationStatus(
        ready=reviewed and not missing,
        reviewed=reviewed,
        missing_fields=missing,
        notice_version=str(getattr(settings, "privacy_notice_version", "") or "").strip(),
    )


def _value(settings: Any, field: str) -> str:
    return escape(str(getattr(settings, field, "") or "").strip())


def render_first_layer(settings: Any, *, compact: bool = False) -> str:
    status = privacy_information_status(settings)
    if not status.ready:
        return ""

    controller = _value(settings, "privacy_controller_identity")
    purposes = _value(settings, "privacy_purposes")
    legal_basis = _value(settings, "privacy_legal_basis")
    recipients = _value(settings, "privacy_recipients")
    transfers = _value(settings, "privacy_international_transfers")

    if compact:
        return (
            '<div class="privacyLayer notice">'
            f'<b>Privacidad.</b> Responsable: {controller}. '
            f'Finalidad: {purposes}. Base jurídica: {legal_basis}. '
            '<a href="/privacidad">Información completa y ejercicio de derechos</a>.'
            '</div>'
        )

    return (
        '<div class="privacyLayer notice">'
        '<b>Información básica de privacidad</b>'
        f'<div class="tiny" style="margin-top:4px"><b>Responsable:</b> {controller}</div>'
        f'<div class="tiny"><b>Finalidades:</b> {purposes}</div>'
        f'<div class="tiny"><b>Base jurídica:</b> {legal_basis}</div>'
        f'<div class="tiny"><b>Destinatarios:</b> {recipients}</div>'
        f'<div class="tiny"><b>Transferencias internacionales:</b> {transfers}</div>'
        '<div class="tiny"><b>Derechos:</b> consulta la información completa para conocer cómo ejercerlos.</div>'
        '<div class="tiny"><a href="/privacidad">Ver información de privacidad completa</a></div>'
        '</div>'
    )


def render_full_privacy_page(settings: Any) -> str:
    status = privacy_information_status(settings)
    if not status.ready:
        raise ValueError("Privacy information is not reviewed and complete")

    dpo = str(getattr(settings, "privacy_dpo_contact", "") or "").strip()
    dpo_html = (
        f'<section><h2>Delegado de Protección de Datos</h2><p>{escape(dpo)}</p></section>'
        if dpo
        else ""
    )
    sections = [
        ("Responsable del tratamiento", "privacy_controller_identity"),
        ("Contacto del responsable", "privacy_controller_contact"),
        ("Finalidades del tratamiento", "privacy_purposes"),
        ("Base jurídica", "privacy_legal_basis"),
        ("Conservación", "privacy_retention"),
        ("Destinatarios", "privacy_recipients"),
        ("Transferencias internacionales", "privacy_international_transfers"),
        ("Derechos", "privacy_rights"),
        ("Decisiones automatizadas y perfiles", "privacy_automated_decisions"),
        ("Categorías especiales de datos", "privacy_special_categories"),
        ("Datos necesarios y consecuencias de no facilitarlos", "privacy_data_requirement"),
    ]
    body = "".join(
        f'<section><h2>{escape(title)}</h2><p>{_value(settings, field)}</p></section>'
        for title, field in sections
    )
    version = _value(settings, "privacy_notice_version")
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Información de privacidad | MECORRESPONDE</title>'
        '<style>body{font:16px/1.55 system-ui,sans-serif;max-width:820px;margin:0 auto;padding:32px 20px;'
        'color:#151714;background:#f5f4ef}main{background:#fff;border:1px solid #dedfd8;border-radius:20px;padding:28px}'
        'h1{letter-spacing:-.04em}h2{font-size:18px;margin:28px 0 8px}p{white-space:pre-wrap}a{color:#173c2b}</style>'
        '</head><body><main><a href="/">← Volver</a><h1>Información de privacidad</h1>'
        f'<p>Versión: {version}</p>{body}{dpo_html}'
        '<section><h2>Autoridad de control</h2>'
        '<p>Puedes presentar una reclamación ante la Agencia Española de Protección de Datos cuando corresponda.</p>'
        '<p><a href="https://www.aepd.es/" rel="noopener noreferrer">Agencia Española de Protección de Datos</a></p>'
        '</section></main></body></html>'
    )
