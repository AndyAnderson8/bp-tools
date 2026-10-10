"""Rate-limit tier routing: each endpoint must map to the documented tier."""

import pytest

from bp_tools.core.api import ApiClient
from bp_tools.core.constants import RATE_LIMITS


@pytest.fixture()
def client() -> ApiClient:
    return ApiClient(token="test", rate_limits=RATE_LIMITS)


@pytest.mark.parametrize(
    ("method", "path", "tier"),
    [
        ("POST", "/items/123/buy", "trading"),
        ("POST", "/items/123/offers", "trading"),
        ("POST", "/currency/orders", "trading"),
        # Cancel / withdraw use the id-suffixed paths; these must match too.
        ("DELETE", "/currency/orders/65773", "trading"),
        ("DELETE", "/offers/42", "write"),
        ("GET", "/me", "default"),
    ],
)
def test_tier_for_route(client: ApiClient, method: str, path: str, tier: str) -> None:
    assert client._tier_for(method, path) == tier


def test_error_response_raises_api_error_with_status(client: ApiClient) -> None:
    from unittest import mock

    from bp_tools.core.api import ApiError

    response = mock.Mock(ok=False, status_code=422)
    response.json.return_value = {"message": "duplicate"}
    response.headers = {}
    client._session.request = mock.Mock(return_value=response)  # type: ignore[method-assign]

    try:
        client.post("/items/1/offers", {"offer_amount": 2})
    except ApiError as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("expected ApiError")
