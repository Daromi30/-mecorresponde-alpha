from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import settings


class EmailDeliveryUnavailable(RuntimeError):
    pass


class EmailDeliveryFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class EmailDeliveryResult:
    provider: str
    message_id: str | None


def transactional_email_ready() -> bool:
    return settings.transactional_email_ready


def action_link(fragment_key: str, token: str) -> str:
    if not transactional_email_ready():
        raise EmailDeliveryUnavailable("Transactional email is not configured")
    base = settings.auth_action_base_url.strip().rstrip("/")
    # Put one-time secrets in the URL fragment. Browsers do not send fragments in
    # HTTP requests, which avoids exposing the token in normal access logs/referrers.
    return f"{base}/#{fragment_key}={token}"


def send_transactional_email(*, to_email: str, subject: str, text: str) -> EmailDeliveryResult:
    if not transactional_email_ready():
        raise EmailDeliveryUnavailable("Transactional email is not configured")
    provider = settings.email_delivery_provider.strip().casefold()
    if provider != "brevo":
        raise EmailDeliveryUnavailable("Unsupported transactional email provider")

    payload = {
        "sender": {
            "name": settings.email_sender_name.strip() or "MECORRESPONDE",
            "email": settings.email_sender_email.strip(),
        },
        "to": [
            {
                "email": to_email,
                # Account recovery/verification does not require identifiable open
                # tracking. Keep it anonymized at the provider when supported.
                "contactPixelTrackingConsent": False,
            }
        ],
        "subject": subject,
        "textContent": text,
        "tags": ["mecorresponde-auth"],
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": settings.brevo_api_key.strip(),
    }
    try:
        response = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers=headers,
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Never include the API response body: provider errors may contain recipient
        # or request details. Callers decide whether to expose a generic failure.
        raise EmailDeliveryFailed("Transactional email delivery failed") from exc
    message_id = body.get("messageId") if isinstance(body, dict) else None
    return EmailDeliveryResult(provider="brevo", message_id=message_id)
