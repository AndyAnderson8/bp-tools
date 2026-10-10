import json

"""WebSession login, 2FA, 429 and backoff behaviour, with HTTP mocked out."""

import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from bp_tools.tools.item_sniper import web_session as ws

LOGIN_PAGE_URL = f"{ws._WEB_BASE}/login"
HOME_URL = f"{ws._WEB_BASE}/home"
TWOFA_URL = f"{ws._WEB_BASE}/account/email-2fa"


class FakeResponse:
    def __init__(
        self,
        url: str = "",
        text: str = "",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))


LOGIN_PAGE = FakeResponse(LOGIN_PAGE_URL, '<input name="_token" value="tok1">')
HOME = FakeResponse(HOME_URL, "<title>Home | BrickPlanet</title>")
TWOFA_PAGE = FakeResponse(
    TWOFA_URL,
    '<input name="_token" value="tok2">'
    '<form method="POST" action="https://www.brickplanet.com/account/email-2fa/verify">'
    '<input name="code"></form>',
)


def _session_with(responses: list[Any], sent: list[dict[str, Any]]) -> Any:
    """Return a patched ``_send`` that replays *responses* and records calls."""
    queue = iter(responses)

    def fake_send(self: ws.WebSession, method: str, url: str, **kwargs: Any) -> Any:
        sent.append({"method": method, "url": url, "data": kwargs.get("data")})
        return next(queue)

    return fake_send


def test_login_without_2fa(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(ws.WebSession, "_send", _session_with([LOGIN_PAGE, HOME], sent))

    session = ws.WebSession("Revolt", "pw")

    assert session._created_at > 0
    assert sent[1]["data"]["password"] == "pw"


def test_2fa_submits_code_when_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []
    responses = [LOGIN_PAGE, TWOFA_PAGE, HOME]
    monkeypatch.setattr(ws.WebSession, "_send", _session_with(responses, sent))

    ws.WebSession("Revolt", "pw", two_factor_code="123456")

    verify = sent[2]
    assert verify["url"].endswith("/account/email-2fa/verify")
    assert verify["data"]["code"] == "123456"
    assert verify["data"]["trust_device"] == "1"


def test_2fa_without_code_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        ws.WebSession, "_send", _session_with([LOGIN_PAGE, TWOFA_PAGE], sent)
    )

    with pytest.raises(ws.WebSessionError, match="email 2FA"):
        ws.WebSession("Revolt", "pw")


def test_wrong_password_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []
    still_login = FakeResponse(LOGIN_PAGE_URL, "Invalid credentials")
    monkeypatch.setattr(
        ws.WebSession, "_send", _session_with([LOGIN_PAGE, still_login], sent)
    )

    with pytest.raises(ConnectionRefusedError):
        ws.WebSession("Revolt", "bad")


def test_429_pauses_session_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _bare_session()
    limited = FakeResponse(status_code=429, headers={"Retry-After": "120"})
    monkeypatch.setattr(session._session, "request", lambda *a, **k: limited)

    with pytest.raises(ws.WebRateLimited):
        session._send("GET", f"{ws._WEB_BASE}/shop/1")

    assert session._retry_at - time.time() == pytest.approx(120, abs=2)


def test_buy_refuses_while_paused() -> None:
    session = _bare_session()
    session._retry_at = time.time() + 60

    with pytest.raises(ws.WebSessionError, match="paused"):
        session.buy_item(1)


def test_failed_relogin_backs_off_exponentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _bare_session()
    session._created_at = time.time() - ws.SESSION_LIFETIME_SECONDS - 1
    monkeypatch.setattr(
        session, "_login", mock.Mock(side_effect=ConnectionRefusedError("nope"))
    )

    with pytest.raises(ConnectionRefusedError):
        session.ensure_fresh_session()
    first_delay = session._retry_at - time.time()

    session._retry_at = 0.0
    with pytest.raises(ConnectionRefusedError):
        session.ensure_fresh_session()
    second_delay = session._retry_at - time.time()

    assert first_delay == pytest.approx(30, abs=2)
    assert second_delay == pytest.approx(60, abs=2)


def test_already_owned_is_reported_not_success() -> None:
    session = _bare_session()
    session._send = mock.Mock(  # type: ignore[method-assign]
        side_effect=[
            FakeResponse(text='<input name="_token" value="t">'),
            FakeResponse(text="<p>You own this item</p>"),
        ]
    )

    result = session.buy_item(1)

    assert result["already_owned"] is True
    assert result["success"] is False


def _bare_session() -> ws.WebSession:
    """A WebSession without performing a login."""
    session = ws.WebSession.__new__(ws.WebSession)
    session.username = "Revolt"
    session._password = "pw"
    session._two_factor_code = None
    session._session = mock.Mock()
    session._token = ""
    session._created_at = time.time()
    session._retry_at = 0.0
    session._failures = 0
    return session


def test_trusted_device_cookie_is_saved_after_2fa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "web.json"

    def fake_send(self: ws.WebSession, method: str, url: str, **_kw: Any) -> Any:
        if url.endswith("/email-2fa/verify"):
            self._session.cookies.set(
                "bp_2fa_device", "dev123", domain="www.brickplanet.com"
            )
            return HOME
        return LOGIN_PAGE if method == "GET" else TWOFA_PAGE

    monkeypatch.setattr(ws.WebSession, "_send", fake_send)

    ws.WebSession("Revolt", "pw", two_factor_code="111111", cookie_file=store)

    assert json.loads(store.read_text(encoding="utf-8")) == {"bp_2fa_device": "dev123"}


def test_saved_device_cookie_is_sent_on_next_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "web.json"
    store.write_text(json.dumps({"bp_2fa_device": "abc"}), encoding="utf-8")
    seen: list[str | None] = []

    def fake_send(self: ws.WebSession, method: str, url: str, **_kw: Any) -> Any:
        if method == "GET":
            seen.append(self._session.cookies.get("bp_2fa_device"))
            return LOGIN_PAGE
        return HOME

    monkeypatch.setattr(ws.WebSession, "_send", fake_send)

    ws.WebSession("Revolt", "pw", cookie_file=store)

    assert seen == ["abc"]


def test_no_cookie_file_is_written_when_site_sets_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "web.json"
    monkeypatch.setattr(
        ws.WebSession,
        "_send",
        lambda self, method, url, **_kw: LOGIN_PAGE if method == "GET" else HOME,
    )

    ws.WebSession("Revolt", "pw", cookie_file=store)

    assert not store.exists()
