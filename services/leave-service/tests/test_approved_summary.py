from tests.conftest import ADMIN, EMP, EMP2, MANAGER, apply


def approve(client, headers, leave_type_id, start, end):
    leave_id = apply(client, headers, leave_type_id, start, end).json()["id"]
    assert client.post(f"/leaves/{leave_id}/approve", headers=ADMIN).status_code == 200
    return leave_id


def summary(client, month, headers=ADMIN):
    return client.get(f"/leaves/approved?month={month}", headers=headers)


def test_admin_only(client):
    assert summary(client, "2026-10", MANAGER).status_code == 403
    assert summary(client, "2026-10", EMP).status_code == 403
    assert client.get("/leaves/approved?month=2026-10").status_code == 401


def test_month_validation(client):
    assert summary(client, "2026-13").status_code == 422
    assert summary(client, "202610").status_code == 422
    assert client.get("/leaves/approved", headers=ADMIN).status_code == 422


def test_paid_and_unpaid_days_are_split_per_employee(client, make_type):
    paid = make_type("Casual", max_days=12, is_paid=True)
    unpaid = make_type("Unpaid", is_paid=False)
    approve(client, EMP, paid.id, "2026-10-05", "2026-10-07")  # 3 paid
    approve(client, EMP, unpaid.id, "2026-10-12", "2026-10-13")  # 2 unpaid
    approve(client, EMP2, unpaid.id, "2026-10-19", "2026-10-19")  # 1 unpaid

    body = summary(client, "2026-10").json()
    assert body["month"] == "2026-10"
    assert body["employees"] == [
        {"employee_id": 10, "paid_days": "3.0", "unpaid_days": "2.0"},
        {"employee_id": 20, "paid_days": "0.0", "unpaid_days": "1.0"},
    ]


def test_leave_spanning_two_months_only_counts_days_inside_the_month(client, make_type):
    lt = make_type("Unpaid", is_paid=False)
    # Mon 28 Sep .. Sat 3 Oct 2026: Sep 28-30 = 3 days, Oct 1-3 = 3 days
    approve(client, EMP, lt.id, "2026-09-28", "2026-10-03")
    assert summary(client, "2026-09").json()["employees"][0]["unpaid_days"] == "3.0"
    assert summary(client, "2026-10").json()["employees"][0]["unpaid_days"] == "3.0"
    assert summary(client, "2026-11").json()["employees"] == []


def test_only_approved_leave_counts(client, make_type):
    lt = make_type("Casual")
    apply(client, EMP, lt.id, "2026-10-05", "2026-10-06")  # pending
    rejected = apply(client, EMP2, lt.id, "2026-10-05", "2026-10-06").json()["id"]
    client.post(f"/leaves/{rejected}/reject", json={"reason": "no"}, headers=MANAGER)
    assert summary(client, "2026-10").json()["employees"] == []


def test_sundays_excluded_in_summary(client, make_type):
    lt = make_type("Casual")
    approve(client, EMP, lt.id, "2026-10-05", "2026-10-11")  # Mon..Sun -> 6
    assert summary(client, "2026-10").json()["employees"][0]["paid_days"] == "6.0"
