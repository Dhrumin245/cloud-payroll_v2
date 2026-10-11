from tests.conftest import PASSWORD, headers_for


def test_list_users_with_filters_and_paging(client, admin, admin_headers, make_user):
    make_user("m1", "manager")
    make_user("e1", "employee")
    make_user("e2", "employee", active=False)

    everyone = client.get("/users", headers=admin_headers).json()
    assert [u["username"] for u in everyone] == ["admin1", "m1", "e1", "e2"]
    assert all("password_hash" not in u for u in everyone)

    employees = client.get("/users?role=employee", headers=admin_headers).json()
    assert [u["username"] for u in employees] == ["e1", "e2"]
    inactive = client.get("/users?is_active=false", headers=admin_headers).json()
    assert [u["username"] for u in inactive] == ["e2"]
    page = client.get("/users?limit=2&offset=1", headers=admin_headers).json()
    assert [u["username"] for u in page] == ["m1", "e1"]


def test_get_user_and_404(client, admin_headers, make_user):
    user = make_user("m1", "manager")
    assert client.get(f"/users/{user.id}", headers=admin_headers).json()["username"] == "m1"
    assert client.get("/users/9999", headers=admin_headers).status_code == 404


def test_patch_role_and_active(client, admin_headers, make_user):
    user = make_user("m1", "manager")
    r = client.patch(f"/users/{user.id}", json={"role": "admin"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    r = client.patch(f"/users/{user.id}", json={"is_active": False}, headers=admin_headers)
    assert r.json()["is_active"] is False


def test_deactivated_user_cannot_login(client, admin_headers, make_user):
    user = make_user("m1", "manager")
    client.patch(f"/users/{user.id}", json={"is_active": False}, headers=admin_headers)
    r = client.post("/auth/login", json={"username": "m1", "password": PASSWORD})
    assert r.status_code == 401


def test_admin_cannot_deactivate_self(client, admin, admin_headers):
    r = client.patch(f"/users/{admin.id}", json={"is_active": False}, headers=admin_headers)
    assert r.status_code == 400


def test_admin_cannot_change_own_role(client, admin, admin_headers):
    r = client.patch(f"/users/{admin.id}", json={"role": "manager"}, headers=admin_headers)
    assert r.status_code == 400


def test_patch_to_employee_needs_link(client, admin_headers, make_user):
    user = make_user("m1", "manager")
    r = client.patch(f"/users/{user.id}", json={"role": "employee"}, headers=admin_headers)
    assert r.status_code == 422
    r = client.patch(
        f"/users/{user.id}", json={"role": "employee", "employee_id": 3}, headers=admin_headers
    )
    assert r.status_code == 200 and r.json()["employee_id"] == 3


def test_cannot_unlink_employee_role_user(client, admin_headers, make_user):
    user = make_user("e1", "employee", employee_id=3)
    r = client.patch(f"/users/{user.id}", json={"employee_id": None}, headers=admin_headers)
    assert r.status_code == 422


def test_link_already_used_employee_conflicts(client, admin_headers, make_user):
    make_user("e1", "employee", employee_id=3)
    other = make_user("m1", "manager")
    r = client.patch(f"/users/{other.id}", json={"employee_id": 3}, headers=admin_headers)
    assert r.status_code == 409


def test_patch_validation(client, admin_headers, make_user):
    user = make_user("m1", "manager")
    assert client.patch(f"/users/{user.id}", json={}, headers=admin_headers).status_code == 422
    r = client.patch(f"/users/{user.id}", json={"role": None}, headers=admin_headers)
    assert r.status_code == 422
    r = client.patch(f"/users/{user.id}", json={"role": "boss"}, headers=admin_headers)
    assert r.status_code == 422


def test_reset_password(client, admin_headers, make_user):
    user = make_user("m1", "manager")
    r = client.post(
        f"/users/{user.id}/reset-password",
        json={"new_password": "brand-new-password"},
        headers=admin_headers,
    )
    assert r.status_code == 204
    old = client.post("/auth/login", json={"username": "m1", "password": PASSWORD})
    new = client.post("/auth/login", json={"username": "m1", "password": "brand-new-password"})
    assert old.status_code == 401 and new.status_code == 200


def test_reset_password_unknown_user_and_weak_password(client, admin_headers, make_user):
    assert (
        client.post(
            "/users/9999/reset-password",
            json={"new_password": "long-enough-pw"},
            headers=admin_headers,
        ).status_code
        == 404
    )
    user = make_user("m1", "manager")
    r = client.post(
        f"/users/{user.id}/reset-password", json={"new_password": "short"}, headers=admin_headers
    )
    assert r.status_code == 422


def test_non_admin_cannot_manage_users(client, make_user):
    manager = make_user("m1", "manager")
    target = make_user("e1", "employee")
    h = headers_for(manager)
    assert client.get("/users", headers=h).status_code == 403
    assert (
        client.patch(f"/users/{target.id}", json={"is_active": False}, headers=h).status_code == 403
    )
    r = client.post(
        f"/users/{target.id}/reset-password", json={"new_password": "x" * 10}, headers=h
    )
    assert r.status_code == 403


def test_change_own_password(client, make_user):
    user = make_user("e1", "employee")
    h = headers_for(user)
    bad = client.post(
        "/auth/change-password",
        json={"current_password": "wrong-password", "new_password": "new-password-123"},
        headers=h,
    )
    assert bad.status_code == 400
    ok = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-password-123"},
        headers=h,
    )
    assert ok.status_code == 204
    login = client.post("/auth/login", json={"username": "e1", "password": "new-password-123"})
    assert login.status_code == 200


def test_change_password_enforces_policy(client, make_user):
    user = make_user("e1", "employee")
    r = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=headers_for(user),
    )
    assert r.status_code == 422


def test_me_returns_current_user(client, make_user):
    user = make_user("e1", "employee", employee_id=11)
    body = client.get("/auth/me", headers=headers_for(user)).json()
    assert body["username"] == "e1" and body["employee_id"] == 11
