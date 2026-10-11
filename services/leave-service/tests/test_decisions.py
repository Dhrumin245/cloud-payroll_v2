from decimal import Decimal

from app.models import LeaveBalance
from tests.conftest import ADMIN, EMP, EMP2, MANAGER, apply


def used(db, employee_id, leave_type_id, year):
    row = (
        db.query(LeaveBalance)
        .filter_by(employee_id=employee_id, leave_type_id=leave_type_id, year=year)
        .one_or_none()
    )
    return row.days_used if row else None


def test_manager_approves_any_employees_leave(client, db, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    r = client.post(f"/leaves/{leave_id}/approve", json={"note": "enjoy"}, headers=MANAGER)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved" and body["decided_by_user_id"] == 101
    assert body["decided_at"] and body["decision_note"] == "enjoy"
    assert used(db, 10, casual.id, 2026) == Decimal("3.0")


def test_admin_can_approve_and_body_is_optional(client, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    r = client.post(f"/leaves/{leave_id}/approve", headers=ADMIN)
    assert r.status_code == 200 and r.json()["decided_by_user_id"] == 100


def test_employee_cannot_decide(client, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    assert client.post(f"/leaves/{leave_id}/approve", headers=EMP2).status_code == 403
    assert client.post(f"/leaves/{leave_id}/approve").status_code == 401


def test_nobody_can_approve_or_reject_their_own_request(client, casual):
    leave_id = apply(client, MANAGER, casual.id).json()["id"]  # manager is employee 30
    r = client.post(f"/leaves/{leave_id}/approve", headers=MANAGER)
    assert r.status_code == 403 and "own" in r.json()["detail"]
    assert (
        client.post(f"/leaves/{leave_id}/reject", json={"reason": "x"}, headers=MANAGER).status_code
        == 403
    )
    # but another approver can
    assert client.post(f"/leaves/{leave_id}/approve", headers=ADMIN).status_code == 200


def test_only_pending_requests_can_be_decided(client, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    client.post(f"/leaves/{leave_id}/approve", headers=MANAGER)
    assert client.post(f"/leaves/{leave_id}/approve", headers=MANAGER).status_code == 409
    assert (
        client.post(
            f"/leaves/{leave_id}/reject", json={"reason": "late"}, headers=MANAGER
        ).status_code
        == 409
    )


def test_double_approval_does_not_double_count(client, db, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    client.post(f"/leaves/{leave_id}/approve", headers=MANAGER)
    client.post(f"/leaves/{leave_id}/approve", headers=ADMIN)
    assert used(db, 10, casual.id, 2026) == Decimal("3.0")


def test_unknown_request_is_404(client):
    assert client.post("/leaves/999/approve", headers=MANAGER).status_code == 404
    assert (
        client.post("/leaves/999/reject", json={"reason": "x"}, headers=MANAGER).status_code == 404
    )


def test_approval_blocked_when_limit_would_be_exceeded(client, db, make_type):
    four = make_type("Four", max_days=4)
    a = apply(client, EMP, four.id, "2026-10-05", "2026-10-07").json()["id"]  # 3 days
    b = apply(client, EMP, four.id, "2026-10-12", "2026-10-13").json()["id"]  # 2 days
    assert client.post(f"/leaves/{a}/approve", headers=MANAGER).status_code == 200
    r = client.post(f"/leaves/{b}/approve", headers=MANAGER)  # 3 + 2 > 4
    assert r.status_code == 409 and "limit exceeded" in r.json()["detail"].lower()
    assert client.get(f"/leaves/{b}", headers=MANAGER).json()["status"] == "pending"  # unchanged
    assert used(db, 10, four.id, 2026) == Decimal("3.0")  # balance untouched


def test_unlimited_types_still_track_usage(client, db, make_type):
    unlimited = make_type("Comp Off", max_days=None)
    leave_id = apply(client, EMP, unlimited.id).json()["id"]
    client.post(f"/leaves/{leave_id}/approve", headers=MANAGER)
    assert used(db, 10, unlimited.id, 2026) == Decimal("3.0")


def test_request_over_new_year_is_split_between_years(client, db, make_type):
    lt = make_type("Annual", max_days=20)
    # Mon 28 Dec 2026 .. Sat 2 Jan 2027: 4 days in 2026 (Mon-Thu), 2 in 2027 (Fri, Sat)
    leave_id = apply(client, EMP, lt.id, "2026-12-28", "2027-01-02").json()["id"]
    assert client.get(f"/leaves/{leave_id}", headers=EMP).json()["total_days"] == "6.0"
    client.post(f"/leaves/{leave_id}/approve", headers=MANAGER)
    assert used(db, 10, lt.id, 2026) == Decimal("4.0")
    assert used(db, 10, lt.id, 2027) == Decimal("2.0")


def test_reject_requires_a_reason_and_records_it(client, db, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    assert client.post(f"/leaves/{leave_id}/reject", json={}, headers=MANAGER).status_code == 422
    assert (
        client.post(
            f"/leaves/{leave_id}/reject", json={"reason": "  "}, headers=MANAGER
        ).status_code
        == 422
    )
    r = client.post(f"/leaves/{leave_id}/reject", json={"reason": "Release week"}, headers=MANAGER)
    body = r.json()
    assert body["status"] == "rejected" and body["decision_note"] == "Release week"
    assert body["decided_by_user_id"] == 101
    assert used(db, 10, casual.id, 2026) is None  # no balance consumed


def test_cancel_own_pending_request(client, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    assert client.post(f"/leaves/{leave_id}/cancel", headers=EMP2).status_code == 403
    assert (
        client.post(f"/leaves/{leave_id}/cancel", headers=MANAGER).status_code == 403
    )  # not even managers
    r = client.post(f"/leaves/{leave_id}/cancel", headers=EMP)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.post(f"/leaves/{leave_id}/cancel", headers=EMP).status_code == 409
    assert client.post(f"/leaves/{leave_id}/approve", headers=MANAGER).status_code == 409


def test_approved_request_cannot_be_cancelled(client, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    client.post(f"/leaves/{leave_id}/approve", headers=MANAGER)
    assert client.post(f"/leaves/{leave_id}/cancel", headers=EMP).status_code == 409


def test_lifecycle_metrics(client, casual):
    a = apply(client, EMP, casual.id, "2026-10-05", "2026-10-06").json()["id"]
    b = apply(client, EMP, casual.id, "2026-10-12", "2026-10-13").json()["id"]
    client.post(f"/leaves/{a}/approve", headers=MANAGER)
    client.post(f"/leaves/{b}/reject", json={"reason": "no"}, headers=MANAGER)
    text = client.get("/metrics").text
    for event in ("created", "approved", "rejected", "cancelled"):
        assert f'leave_requests_total{{event="{event}"}}' in text
