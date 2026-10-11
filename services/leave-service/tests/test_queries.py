from tests.conftest import ADMIN, EMP, EMP2, MANAGER, apply


def test_my_leaves_only_shows_own_newest_first_with_status_filter(client, casual):
    first = apply(client, EMP, casual.id, "2026-10-05", "2026-10-06").json()["id"]
    second = apply(client, EMP, casual.id, "2026-10-12", "2026-10-13").json()["id"]
    apply(client, EMP2, casual.id, "2026-10-05", "2026-10-06")
    client.post(f"/leaves/{first}/approve", headers=MANAGER)

    mine = client.get("/leaves/my", headers=EMP).json()
    assert [r["id"] for r in mine] == [second, first]
    assert all(r["employee_id"] == 10 for r in mine)
    approved = client.get("/leaves/my?status=approved", headers=EMP).json()
    assert [r["id"] for r in approved] == [first]
    assert client.get("/leaves/my?status=bogus", headers=EMP).status_code == 422


def test_my_leaves_needs_an_employee_link(client):
    assert client.get("/leaves/my", headers=ADMIN).status_code == 400


def test_pending_is_oldest_first_and_excludes_decided(client, casual):
    a = apply(client, EMP, casual.id, "2026-10-05", "2026-10-06").json()["id"]
    b = apply(client, EMP2, casual.id, "2026-10-05", "2026-10-06").json()["id"]
    c = apply(client, EMP, casual.id, "2026-10-12", "2026-10-13").json()["id"]
    client.post(f"/leaves/{b}/approve", headers=MANAGER)
    assert [r["id"] for r in client.get("/leaves/pending", headers=MANAGER).json()] == [a, c]
    assert client.get("/leaves/pending", headers=EMP).status_code == 403


def test_list_all_filters(client, make_type):
    casual, sick = make_type("Casual"), make_type("Sick")
    a = apply(client, EMP, casual.id, "2026-10-05", "2026-10-06").json()["id"]
    b = apply(client, EMP2, sick.id, "2026-11-02", "2026-11-03").json()["id"]
    client.post(f"/leaves/{b}/approve", headers=ADMIN)

    def ids(query):
        return sorted(r["id"] for r in client.get(f"/leaves{query}", headers=MANAGER).json())

    assert ids("") == sorted([a, b])
    assert ids("?status=approved") == [b]
    assert ids("?employee_id=10") == [a]
    assert ids(f"?leave_type_id={sick.id}") == [b]
    assert ids("?month=2026-10") == [a]
    assert ids("?month=2026-11") == [b]
    assert ids("?limit=1") and len(ids("?limit=1")) == 1
    assert client.get("/leaves?month=2026-13", headers=MANAGER).status_code == 422
    assert client.get("/leaves", headers=EMP).status_code == 403


def test_get_one_owner_or_staff(client, casual):
    leave_id = apply(client, EMP, casual.id).json()["id"]
    assert client.get(f"/leaves/{leave_id}", headers=EMP).status_code == 200
    assert client.get(f"/leaves/{leave_id}", headers=MANAGER).status_code == 200
    assert client.get(f"/leaves/{leave_id}", headers=EMP2).status_code == 403
    assert client.get("/leaves/999", headers=MANAGER).status_code == 404


def test_balance_shows_used_pending_and_remaining(client, make_type):
    casual, unlimited = make_type("Casual", max_days=12), make_type("Comp Off")
    a = apply(client, EMP, casual.id, "2026-10-05", "2026-10-07").json()["id"]  # 3 days
    apply(client, EMP, casual.id, "2026-10-12", "2026-10-13")  # 2 days, stays pending
    client.post(f"/leaves/{a}/approve", headers=MANAGER)

    body = client.get("/leaves/balance?year=2026", headers=EMP).json()
    assert body["employee_id"] == 10 and body["year"] == 2026
    by_name = {b["leave_type_name"]: b for b in body["balances"]}
    assert by_name["Casual"]["days_used"] == "3.0"
    assert by_name["Casual"]["days_pending"] == "2.0"
    assert by_name["Casual"]["remaining"] == "9.0"
    assert (
        by_name["Comp Off"]["max_days_per_year"] is None
        and by_name["Comp Off"]["remaining"] is None
    )
    assert unlimited.id == by_name["Comp Off"]["leave_type_id"]
    assert (
        client.get("/leaves/balance?year=2025", headers=EMP).json()["balances"][0]["days_used"]
        == "0.0"
    )


def test_balance_access_rules(client, casual):
    assert client.get("/leaves/balance?employee_id=20", headers=EMP).status_code == 403
    assert client.get("/leaves/balance?employee_id=10", headers=EMP).status_code == 200
    assert client.get("/leaves/balance?employee_id=10", headers=MANAGER).status_code == 200
    assert (
        client.get("/leaves/balance", headers=ADMIN).status_code == 400
    )  # admin has no own record
    assert client.get("/leaves/balance?employee_id=10", headers=ADMIN).status_code == 200
