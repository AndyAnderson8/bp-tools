"""ApiClient: dry-run guards, error handling and the sliding-window limiter."""

from unittest import mock

import pytest

from bp_tools.core import api as api_mod
from bp_tools.core.api import ApiClient, ApiError, RateLimiter
from bp_tools.core.constants import RATE_LIMITS


def _response(
    status: int = 200, body: object | None = None, headers: dict | None = None
):
    resp = mock.Mock(status_code=status, ok=200 <= status < 300, headers=headers or {})
    resp.json.return_value = body if body is not None else {}
    resp.text = ""
    return resp


def test_dry_run_post_never_hits_the_network() -> None:
    client = ApiClient(token="t", dry_run=True)
    client._session.request = mock.Mock()  # type: ignore[method-assign]

    result = client.post("/items/1/buy", {"currency": "credits"})

    assert result == {"data": {"message": "dry-run"}}
    client._session.request.assert_not_called()


def test_dry_run_delete_never_hits_the_network() -> None:
    client = ApiClient(token="t", dry_run=True)
    client._session.request = mock.Mock()  # type: ignore[method-assign]

    client.delete("/offers/1")

    client._session.request.assert_not_called()


def test_get_returns_parsed_json() -> None:
    client = ApiClient(token="t")
    client._session.request = mock.Mock(  # type: ignore[method-assign]
        return_value=_response(200, {"data": {"id": 1}})
    )

    assert client.get("/me") == {"data": {"id": 1}}


def test_error_response_raises_api_error_with_status() -> None:
    client = ApiClient(token="t")
    client._session.request = mock.Mock(  # type: ignore[method-assign]
        return_value=_response(422, {"message": "duplicate"})
    )

    with pytest.raises(ApiError) as info:
        client.post("/items/1/offers", {"offer_amount": 2})

    assert info.value.status_code == 422
    assert "duplicate" in str(info.value)


def test_429_is_not_retried_and_starts_a_cooldown() -> None:
    client = ApiClient(token="t")
    client._session.request = mock.Mock(  # type: ignore[method-assign]
        return_value=_response(429, headers={"Retry-After": "1"})
    )

    with pytest.raises(ApiError) as info:
        client.get("/me")

    assert info.value.status_code == 429
    assert client._session.request.call_count == 1  # never retried
    assert client._paused_for() <= 1
    assert info.value.retry_after == 1


def test_requests_fail_fast_during_cooldown_without_network() -> None:
    client = ApiClient(token="t")
    client._paused_until = api_mod.time.monotonic() + 600
    client._session.request = mock.Mock()  # type: ignore[method-assign]

    with pytest.raises(ApiError, match=r"\[backoff\]") as info:
        client.get("/me")

    assert info.value.is_backoff is True
    client._session.request.assert_not_called()


def test_missing_retry_after_uses_bounded_exponential_backoff() -> None:
    client = ApiClient(token="t")
    client._session.request = mock.Mock(  # type: ignore[method-assign]
        return_value=_response(429)
    )

    with pytest.raises(ApiError):
        client.get("/me")
    first_pause = client._paused_for()
    client._paused_until = api_mod.time.monotonic() - 1

    with pytest.raises(ApiError):
        client.get("/me")

    assert first_pause <= api_mod.RATE_LIMIT_COOLDOWN_SECONDS
    assert client._paused_for() <= api_mod.RATE_LIMIT_COOLDOWN_SECONDS * 2


def test_requests_resume_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ApiClient(token="t")
    client._paused_until = api_mod.time.monotonic() - 1  # cooldown already over
    client._session.request = mock.Mock(  # type: ignore[method-assign]
        return_value=_response(200, {"ok": True})
    )

    assert client.get("/me") == {"ok": True}


def test_limiter_sleeps_when_window_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(api_mod.time, "sleep", slept.append)
    limiter = RateLimiter(limit=2, window=60)

    limiter.acquire()
    limiter.acquire()
    limiter.acquire()  # third call in the same window must wait

    assert len(slept) == 1
    assert 0 < slept[0] <= 60


def test_limiter_allows_calls_within_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(api_mod.time, "sleep", slept.append)
    limiter = RateLimiter(limit=5, window=60)

    for _ in range(5):
        limiter.acquire()

    assert slept == []


def test_buy_is_rate_limited_on_the_trading_tier() -> None:
    client = ApiClient(token="t", rate_limits=RATE_LIMITS)

    assert client._tier_for("POST", "/items/9/buy") == "trading"
    assert client._limiters["trading"]._limit == 10
