from src.magic_link_service import InfraiClient, MagicLinkRequest, MagicLinkService


class RecordingClient(InfraiClient):
    def __init__(self):
        super().__init__("test-key")
        self.calls = []

    def create_session(self, user_id):
        self.calls.append(("session", user_id))
        return {"ok": True, "data": {"session_id": "sess_123"}}

    def send_email(self, recipient, link):
        self.calls.append(("email", recipient, link))
        return {"ok": True, "data": {"message_id": "msg_123"}}


def test_low_risk_request_creates_session_and_sends_link():
    client = RecordingClient()
    service = MagicLinkService(client)
    request = MagicLinkRequest("founder@example.com", "user_123", "198.51.100.10", 0.18)

    result = service.sign_in(request)

    assert result == {"decision": "allow", "message_id": "msg_123", "session_id": "sess_123"}
    assert client.calls[0] == ("session", "user_123")
    assert client.calls[1][0:2] == ("email", "founder@example.com")
    assert "sess_123" in client.calls[1][2]


def test_high_risk_request_does_not_send_email():
    client = RecordingClient()
    result = MagicLinkService(client).sign_in(
        MagicLinkRequest("founder@example.com", "user_123", "198.51.100.10", 0.80)
    )

    assert result["decision"] == "reject"
    assert client.calls == []
