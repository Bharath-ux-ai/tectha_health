"""Adapter for the official WhatsApp Business Platform Cloud API (Meta Graph API).

Only this module talks to graph.facebook.com. A send is reported as successful only when the API
returns a message id ("wamid"); delivery is confirmed later by status webhooks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.config import settings

# Graph/WhatsApp error codes that are temporary and safe to retry later.
RETRYABLE_ERROR_CODES = {
    1, 2, 4, 17, 341, 80007,  # generic temporary / API-level throttling
    130429,  # Cloud API throughput reached
    131000,  # something went wrong
    131016,  # service unavailable
    131056,  # pair rate limit (too many messages to the same user)
    133004,  # server temporarily unavailable
}
AUTH_ERROR_CODES = {190, 10, 200, 100}  # token/permission problems — fix configuration, don't retry


@dataclass
class SendResult:
    ok: bool
    wa_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    # True when we cannot tell whether Meta accepted the message (e.g. the response timed out).
    # Automatic retries are suppressed in that case to avoid duplicate reminders.
    ambiguous: bool = False
    http_status: int | None = None
    raw: dict = field(default_factory=dict)


class WhatsAppCloudClient:
    def __init__(
        self,
        *,
        phone_number_id: str,
        access_token: str,
        api_version: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.phone_number_id = phone_number_id
        self.base = f"{(base_url or settings.WHATSAPP_GRAPH_BASE_URL).rstrip('/')}/{api_version or settings.WHATSAPP_GRAPH_VERSION}"
        self._client = httpx.Client(
            timeout=timeout or settings.WHATSAPP_HTTP_TIMEOUT,
            transport=transport,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- sending ----------
    def send_template(
        self,
        *,
        to: str,
        template_name: str,
        language_code: str,
        body_params: list[str],
        button_payloads: list[str] | None = None,
    ) -> SendResult:
        components: list[dict] = []
        if body_params:
            components.append({"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]})
        for idx, payload in enumerate(button_payloads or []):
            components.append({
                "type": "button", "sub_type": "quick_reply", "index": str(idx),
                "parameters": [{"type": "payload", "payload": payload}],
            })
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {"name": template_name, "language": {"code": language_code}, "components": components},
        }
        return self._post_message(body)

    def send_text(self, *, to: str, text: str) -> SendResult:
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": True, "body": text},
        }
        return self._post_message(body)

    def _post_message(self, body: dict) -> SendResult:
        url = f"{self.base}/{self.phone_number_id}/messages"
        try:
            resp = self._client.post(url, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            # Request never reached Meta: safe to retry.
            return SendResult(ok=False, error_code="network", error_message=str(exc) or exc.__class__.__name__, retryable=True)
        except httpx.HTTPError as exc:
            # Request may have reached Meta (read timeout, dropped connection): outcome unknown.
            return SendResult(ok=False, error_code="timeout", error_message=str(exc) or exc.__class__.__name__,
                              ambiguous=True)
        return parse_send_response(resp.status_code, _json(resp))

    # ---------- account / templates ----------
    def get_phone_number(self) -> tuple[bool, dict]:
        resp = self._safe_get(f"{self.base}/{self.phone_number_id}",
                              params={"fields": "display_phone_number,verified_name,quality_rating"})
        return resp

    def list_templates(self, waba_id: str) -> tuple[bool, dict]:
        return self._safe_get(f"{self.base}/{waba_id}/message_templates",
                              params={"fields": "name,language,status,category,id,rejected_reason", "limit": 200})

    def create_template(self, waba_id: str, definition: dict) -> tuple[bool, dict]:
        try:
            resp = self._client.post(f"{self.base}/{waba_id}/message_templates", json=definition)
        except httpx.HTTPError as exc:
            return False, {"error": {"message": str(exc)}}
        data = _json(resp)
        return resp.status_code < 400 and "error" not in data, data

    def _safe_get(self, url: str, params: dict) -> tuple[bool, dict]:
        try:
            resp = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            return False, {"error": {"message": str(exc)}}
        data = _json(resp)
        return resp.status_code < 400 and "error" not in data, data


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {"data": data}
    except ValueError:
        return {"error": {"message": resp.text[:500] or f"HTTP {resp.status_code}"}}


def parse_send_response(status_code: int, data: dict) -> SendResult:
    if status_code < 400 and "error" not in data:
        messages = data.get("messages") or []
        wamid = messages[0].get("id") if messages else None
        if wamid:
            return SendResult(ok=True, wa_message_id=wamid, http_status=status_code, raw=data)
        # 2xx without a message id is not proof of acceptance.
        return SendResult(ok=False, error_code="no_message_id", error_message="WhatsApp did not return a message id.",
                          ambiguous=True, http_status=status_code, raw=data)
    err = data.get("error", {}) if isinstance(data, dict) else {}
    code = err.get("code")
    details = (err.get("error_data") or {}).get("details")
    message = err.get("message") or f"HTTP {status_code}"
    if details:
        message = f"{message} — {details}"
    retryable = status_code == 429 or status_code >= 500 or (isinstance(code, int) and code in RETRYABLE_ERROR_CODES)
    return SendResult(ok=False, error_code=str(code) if code is not None else f"http_{status_code}",
                      error_message=message, retryable=retryable, http_status=status_code, raw=data)


def template_definition(*, name: str, language_code: str, body_text: str, example_params: list[str],
                        buttons: list[str], category: str = "UTILITY") -> dict:
    """Template creation payload for POST /{waba_id}/message_templates."""
    components: list[dict] = [{"type": "BODY", "text": body_text}]
    if example_params:
        components[0]["example"] = {"body_text": [example_params]}
    if buttons:
        components.append({"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": b} for b in buttons]})
    return {"name": name, "language": language_code, "category": category, "components": components}
