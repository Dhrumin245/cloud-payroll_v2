import logging

from app.models import EmployeeBankDetails
from tests.conftest import ADMIN, MANAGER, auth

BANK = {
    "account_holder_name": "Asha Rao",
    "account_number": "123456789012",
    "ifsc_code": "hdfc0001234",
    "bank_name": "HDFC Bank",
}


def put(client, emp_id, headers=ADMIN, **overrides):
    return client.put(
        f"/employees/{emp_id}/bank-details", json={**BANK, **overrides}, headers=headers
    )


def test_save_returns_masked_view_and_stores_ciphertext(client, make_employee, db):
    emp = make_employee()
    r = put(client, emp.id)
    assert r.status_code == 200
    body = r.json()
    assert body["account_number_masked"] == "****9012" and body["account_number_last4"] == "9012"
    assert body["ifsc_code"] == "HDFC0001234"  # normalised to upper case
    assert "account_number" not in body and "123456789012" not in r.text

    row = db.query(EmployeeBankDetails).one()
    assert row.account_number_encrypted != "123456789012"
    assert "123456789012" not in row.account_number_encrypted
    assert row.reveal_account_number() == "123456789012"


def test_new_details_require_account_number(client, make_employee):
    emp = make_employee()
    r = client.put(
        f"/employees/{emp.id}/bank-details",
        json={"account_holder_name": "Asha Rao"},
        headers=ADMIN,
    )
    assert r.status_code == 422


def test_update_without_account_number_keeps_the_stored_one(client, make_employee):
    emp = make_employee()
    put(client, emp.id)
    r = client.put(
        f"/employees/{emp.id}/bank-details",
        json={"account_holder_name": "Asha R. Rao", "bank_name": "ICICI"},
        headers=ADMIN,
    )
    assert r.status_code == 200 and r.json()["account_holder_name"] == "Asha R. Rao"
    revealed = client.get(f"/employees/{emp.id}/bank-details/reveal", headers=ADMIN).json()
    assert revealed["account_number"] == "123456789012"


def test_changing_account_number_updates_last4(client, make_employee):
    emp = make_employee()
    put(client, emp.id)
    r = put(client, emp.id, account_number="987654321000")
    assert r.json()["account_number_last4"] == "1000"


def test_spaces_in_account_number_are_stripped(client, make_employee):
    emp = make_employee()
    put(client, emp.id, account_number="1234 5678 9012")
    assert (
        client.get(f"/employees/{emp.id}/bank-details/reveal", headers=ADMIN).json()[
            "account_number"
        ]
        == "123456789012"
    )


def test_validation(client, make_employee):
    emp = make_employee()
    assert put(client, emp.id, account_number="12").status_code == 422
    assert put(client, emp.id, account_number="12-34-56").status_code == 422
    assert put(client, emp.id, ifsc_code="BAD").status_code == 422
    assert put(client, emp.id, account_holder_name="").status_code == 422


def test_read_access_admin_or_self_only(client, make_employee):
    mine, other = make_employee(), make_employee()
    put(client, mine.id)
    assert client.get(f"/employees/{mine.id}/bank-details", headers=ADMIN).status_code == 200
    assert (
        client.get(
            f"/employees/{mine.id}/bank-details", headers=auth("employee", employee_id=mine.id)
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/employees/{mine.id}/bank-details", headers=auth("employee", employee_id=other.id)
        ).status_code
        == 403
    )
    assert client.get(f"/employees/{mine.id}/bank-details", headers=MANAGER).status_code == 403


def test_only_admin_writes(client, make_employee):
    emp = make_employee()
    assert put(client, emp.id, MANAGER).status_code == 403
    assert put(client, emp.id, auth("employee", employee_id=emp.id)).status_code == 403


def test_missing_details_and_unknown_employee_are_404(client, make_employee):
    emp = make_employee()
    assert client.get(f"/employees/{emp.id}/bank-details", headers=ADMIN).status_code == 404
    assert client.get("/employees/9999/bank-details", headers=ADMIN).status_code == 404


def test_reveal_is_admin_only_even_for_own_record(client, make_employee):
    emp = make_employee()
    put(client, emp.id)
    url = f"/employees/{emp.id}/bank-details/reveal"
    assert client.get(url, headers=ADMIN).json()["account_number"] == "123456789012"
    assert client.get(url, headers=MANAGER).status_code == 403
    assert client.get(url, headers=auth("employee", employee_id=emp.id)).status_code == 403


def test_reveal_is_audit_logged_without_the_number(client, make_employee, caplog):
    emp = make_employee()
    put(client, emp.id)
    with caplog.at_level(logging.WARNING, logger="app.audit"):
        client.get(f"/employees/{emp.id}/bank-details/reveal", headers=ADMIN)
    records = [r for r in caplog.records if getattr(r, "event", "") == "bank_revealed"]
    assert len(records) == 1
    assert (
        f"employee_id={emp.id}" in records[0].getMessage()
        and "user_id=100" in records[0].getMessage()
    )
    assert "123456789012" not in caplog.text
