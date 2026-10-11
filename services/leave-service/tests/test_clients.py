"""The REAL employee-service client, tested against a mocked HTTP transport."""

import httpx
import pytest
from fastapi import HTTPException

from app.clients import EmployeeClient


def client_with(handler) -> EmployeeClient:
    return EmployeeClient(
        "http://employee-service:8000", 1.0, transport=httpx.MockTransport(handler)
    )


def test_parses_a_successful_answer_and_forwards_the_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        return httpx.Response(200, json={"exists": True, "is_active": False})

    result = client_with(handler).check(7, "tok123")
    assert (result.exists, result.is_active) == (True, False)
    assert seen == {
        "url": "http://employee-service:8000/employees/7/exists",
        "auth": "Bearer tok123",
    }


@pytest.mark.parametrize("status_code", [401, 403, 404, 500, 502])
def test_non_200_answers_become_503(status_code):
    with pytest.raises(HTTPException) as exc:
        client_with(lambda r: httpx.Response(status_code)).check(1, "t")
    assert exc.value.status_code == 503


def test_network_errors_and_timeouts_become_503():
    def boom(request):
        raise httpx.ConnectError("connection refused")

    def slow(request):
        raise httpx.ReadTimeout("timed out")

    for handler in (boom, slow):
        with pytest.raises(HTTPException) as exc:
            client_with(handler).check(1, "t")
        assert exc.value.status_code == 503


def _count(target, outcome):
    from app.metrics import DOWNSTREAM_CALLS

    return DOWNSTREAM_CALLS.labels(target=target, outcome=outcome)._value.get()


def test_downstream_calls_are_counted_by_outcome():
    ok_before, err_before = _count("employee-service", "ok"), _count("employee-service", "error")
    good = lambda r: httpx.Response(200, json={"exists": True, "is_active": True})  # noqa: E731
    client_with(good).check(1, "t")
    assert _count("employee-service", "ok") == ok_before + 1

    with pytest.raises(HTTPException):
        client_with(lambda r: httpx.Response(500)).check(1, "t")

    def boom(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(HTTPException):
        client_with(boom).check(1, "t")
    assert _count("employee-service", "error") == err_before + 2
