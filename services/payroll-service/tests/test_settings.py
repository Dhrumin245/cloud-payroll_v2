import pytest

from tests.conftest import ADMIN, EMP10, MANAGER

ON = {"pf_enabled": True, "esi_enabled": False, "pt_enabled": True, "pt_state": "KA"}


def test_defaults_when_nothing_is_configured(client):
    body = client.get("/settings/statutory", headers=ADMIN).json()
    assert (body["pf_enabled"], body["esi_enabled"], body["pt_enabled"], body["pt_state"]) == (
        False,
        False,
        False,
        "MH",
    )
    assert body["pt_states"]["MH"] == "Maharashtra"


def test_save_and_read_back(client):
    assert client.put("/settings/statutory", json=ON, headers=ADMIN).json()["pt_state"] == "KA"
    body = client.get("/settings/statutory", headers=ADMIN).json()
    assert (
        body["pf_enabled"] is True and body["esi_enabled"] is False and body["pt_enabled"] is True
    )


def test_invalid_state_and_missing_fields(client):
    assert (
        client.put("/settings/statutory", json={**ON, "pt_state": "ZZ"}, headers=ADMIN).status_code
        == 422
    )
    assert (
        client.put("/settings/statutory", json={"pf_enabled": True}, headers=ADMIN).status_code
        == 422
    )


@pytest.mark.parametrize("headers", [MANAGER, EMP10])
def test_settings_are_admin_only(client, headers):
    assert client.get("/settings/statutory", headers=headers).status_code == 403
    assert client.put("/settings/statutory", json=ON, headers=headers).status_code == 403
    assert client.get("/settings/pt-slabs", headers=headers).status_code == 403
    slab = {"state_code": "MH", "gross_from": "0", "monthly_tax": "0"}
    assert client.post("/settings/pt-slabs", json=slab, headers=headers).status_code == 403


def slab(**over):
    return {"state_code": "MH", "gross_from": "0", "gross_to": "7500", "monthly_tax": "0", **over}


def test_pt_slab_crud(client):
    created = client.post("/settings/pt-slabs", json=slab(), headers=ADMIN)
    assert created.status_code == 201
    sid = created.json()["id"]
    assert created.json()["gross_to"] == "7500.00" and created.json()["monthly_tax"] == "0.00"
    client.post(
        "/settings/pt-slabs",
        json=slab(gross_from="7501", gross_to=None, monthly_tax="200"),
        headers=ADMIN,
    )
    client.post("/settings/pt-slabs", json=slab(state_code="KA"), headers=ADMIN)

    assert len(client.get("/settings/pt-slabs", headers=ADMIN).json()) == 3
    mh = client.get("/settings/pt-slabs?state=MH", headers=ADMIN).json()
    assert [s["gross_from"] for s in mh] == ["0.00", "7501.00"]
    assert mh[1]["gross_to"] is None

    updated = client.put(f"/settings/pt-slabs/{sid}", json=slab(monthly_tax="50"), headers=ADMIN)
    assert updated.json()["monthly_tax"] == "50.00"
    assert client.delete(f"/settings/pt-slabs/{sid}", headers=ADMIN).status_code == 204
    assert client.delete(f"/settings/pt-slabs/{sid}", headers=ADMIN).status_code == 404
    assert client.put(f"/settings/pt-slabs/{sid}", json=slab(), headers=ADMIN).status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        {"state_code": "ZZ"},
        {"gross_from": "-1"},
        {"monthly_tax": "-5"},
        {"gross_from": "9000", "gross_to": "100"},
    ],
)
def test_pt_slab_validation(client, bad):
    assert client.post("/settings/pt-slabs", json=slab(**bad), headers=ADMIN).status_code == 422
