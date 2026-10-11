import pytest

from tests.conftest import ADMIN, EMP, MANAGER, apply


def test_apply_creates_pending_request(client, casual, fake_employees):
    r = apply(client, EMP, casual.id, reason="  family function ")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending" and body["employee_id"] == 10
    assert body["total_days"] == "3.0" and body["reason"] == "family function"
    assert body["leave_type"]["name"] == "Casual Leave"
    assert body["decided_by_user_id"] is None


def test_applicant_comes_from_token_not_body(client, casual):
    r = apply(client, EMP, casual.id, employee_id=999)  # extra field is ignored
    assert r.json()["employee_id"] == 10


def test_caller_token_is_forwarded_to_employee_service(client, casual, fake_employees):
    apply(client, EMP, casual.id)
    employee_id, token = fake_employees.calls[0]
    assert employee_id == 10 and token == EMP["Authorization"].removeprefix("Bearer ")


def test_sundays_are_not_counted(client, casual):
    # Mon 5 Oct .. Sun 11 Oct 2026 -> 6 working days
    assert apply(client, EMP, casual.id, "2026-10-05", "2026-10-11").json()["total_days"] == "6.0"


def test_sunday_only_request_is_rejected(client, casual):
    r = apply(client, EMP, casual.id, "2026-10-11", "2026-10-11")
    assert r.status_code == 422 and "no working days" in r.json()["detail"]


def test_account_without_employee_link_cannot_apply(client, casual):
    r = apply(client, ADMIN, casual.id)
    assert r.status_code == 400 and "not linked" in r.json()["detail"]


def test_unknown_or_inactive_employee(client, casual, fake_employees):
    fake_employees.employees[10] = (False, False)
    assert apply(client, EMP, casual.id).status_code == 404
    fake_employees.employees[10] = (True, False)
    assert apply(client, EMP, casual.id).status_code == 403


def test_employee_service_down_gives_503(client, casual, fake_employees):
    fake_employees.down = True
    r = apply(client, EMP, casual.id)
    assert r.status_code == 503
    assert client.get("/leaves/my", headers=EMP).status_code == 200  # reads don't depend on it


def test_managers_and_employees_can_apply_but_unauthenticated_cannot(client, casual):
    assert apply(client, MANAGER, casual.id).status_code == 201
    r = client.post(
        "/leaves",
        json={"leave_type_id": casual.id, "start_date": "2026-10-05", "end_date": "2026-10-06"},
    )
    assert r.status_code == 401


@pytest.mark.parametrize(
    "bad",
    [
        {"start_date": "2026-10-09", "end_date": "2026-10-05"},  # end before start
        {"start_date": "2026-13-01"},
        {"reason": "x" * 256},
        {"start_date": "2026-01-01", "end_date": "2027-02-01"},  # longer than a year
    ],
)
def test_validation(client, casual, bad):
    body = {"leave_type_id": casual.id, "start_date": "2026-10-05", "end_date": "2026-10-07", **bad}
    assert client.post("/leaves", json=body, headers=EMP).status_code == 422


def test_unknown_leave_type_is_404(client):
    assert apply(client, EMP, 999).status_code == 404


def test_overlap_with_pending_or_approved_is_rejected(client, casual):
    first = apply(client, EMP, casual.id, "2026-10-05", "2026-10-07").json()["id"]
    assert apply(client, EMP, casual.id, "2026-10-07", "2026-10-09").status_code == 409  # touches
    assert apply(client, EMP, casual.id, "2026-10-01", "2026-10-31").status_code == 409  # contains
    assert apply(client, EMP, casual.id, "2026-10-06", "2026-10-06").status_code == 409  # inside
    client.post(f"/leaves/{first}/approve", headers=MANAGER)  # approved still blocks
    assert apply(client, EMP, casual.id, "2026-10-06", "2026-10-06").status_code == 409


def test_adjacent_dates_and_other_employees_do_not_overlap(client, casual):
    assert apply(client, EMP, casual.id, "2026-10-05", "2026-10-07").status_code == 201
    assert apply(client, EMP, casual.id, "2026-10-08", "2026-10-09").status_code == 201
    from tests.conftest import EMP2

    assert apply(client, EMP2, casual.id, "2026-10-05", "2026-10-07").status_code == 201


def test_rejected_and_cancelled_requests_do_not_block_new_ones(client, casual):
    a = apply(client, EMP, casual.id, "2026-10-05", "2026-10-07").json()["id"]
    client.post(f"/leaves/{a}/reject", json={"reason": "busy"}, headers=MANAGER)
    b = apply(client, EMP, casual.id, "2026-10-05", "2026-10-07")
    assert b.status_code == 201
    client.post(f"/leaves/{b.json()['id']}/cancel", headers=EMP)
    assert apply(client, EMP, casual.id, "2026-10-05", "2026-10-07").status_code == 201


def test_request_larger_than_remaining_balance_is_refused_early(client, make_type):
    tiny = make_type("Tiny", max_days=2)
    r = apply(client, EMP, tiny.id, "2026-10-05", "2026-10-07")  # 3 days > 2
    assert r.status_code == 409 and "limit exceeded" in r.json()["detail"].lower()
