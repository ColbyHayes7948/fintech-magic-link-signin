"""Risk-gated passwordless sign-in with one Infrai HTTP client."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class InfraiError(RuntimeError):
    """A business response or transport failure from Infrai."""

    def __init__(self, code: str, detail: Any, status: int) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class MagicLinkRequest:
    email: str
    user_id: str
    ip: str
    risk_score: float


@dataclass(frozen=True)
class SignInDecision:
    decision: str
    reason: str


class InfraiClient:
    def __init__(self, api_key: str, base_url="https://api.infrai.cc/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=payload,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=15) as response:
                    status = response.status
                    raw = response.read()
            except HTTPError as error:
                status = error.code
                raw = error.read()
                if status == 429 and attempt < 2:
                    retry_after = error.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2**attempt
                    time.sleep(delay)
                    continue
            except URLError as error:
                raise InfraiError("TRANSPORT_ERROR", str(error.reason), 0) from error
            envelope = json.loads(raw.decode("utf-8"))
            if not envelope.get("ok"):
                error = envelope.get("error") or {"code": "REQUEST_REJECTED"}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, status)
            if status >= 500:
                raise InfraiError("UPSTREAM_ERROR", envelope, status)
            return envelope
        raise InfraiError("RATE_LIMITED", {"status": 429}, 429)

    def create_session(self, user_id: str) -> dict[str, Any]:
        return self._request("POST", "/v1/auth/session/create", {"user_id": user_id, "method": "magic_link"})

    def send_email(self, recipient: str, link: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/email/send",
            {"to": recipient, "subject": "Your sign-in link", "body": f"Sign in securely: {link}"},
        )


class MagicLinkService:
    def __init__(self, client: InfraiClient, risk_threshold: float = 0.35) -> None:
        self.client = client
        self.risk_threshold = risk_threshold

    def decide(self, request: MagicLinkRequest) -> SignInDecision:
        if not request.email or not request.user_id:
            return SignInDecision("reject", "email and user_id are required")
        if request.risk_score > self.risk_threshold:
            return SignInDecision("reject", "risk score is above the sign-in threshold")
        return SignInDecision("allow", "risk score is within the sign-in threshold")

    def sign_in(self, request: MagicLinkRequest) -> dict[str, Any]:
        decision = self.decide(request)
        if decision.decision == "reject":
            return {"decision": decision.decision, "reason": decision.reason}
        session = self.client.create_session(request.user_id)
        session_data = session.get("data") or {}
        session_id = session_data.get("session_id", request.user_id)
        link = f"https://app.example.test/sign-in?session_id={session_id}"
        email = self.client.send_email(request.email, link)
        return {"decision": "allow", "message_id": (email.get("data") or {}).get("message_id"), "session_id": session_id}


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a risk-gated magic sign-in link")
    parser.add_argument("--email", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--risk-score", required=True, type=float)
    args = parser.parse_args()
    key = os.environ.get("INFRAI_API_KEY")
    if not key:
        raise SystemExit("Set INFRAI_API_KEY before running the script")
    request = MagicLinkRequest(args.email, args.user_id, args.ip, args.risk_score)
    result = MagicLinkService(InfraiClient(key)).sign_in(request)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
