from decimal import Decimal

from app.models import PtSlab
from app.statutory import (
    ESI_NAME,
    PF_NAME,
    PT_NAME,
    StatutoryContext,
    compute_esi,
    compute_pf,
    compute_pt,
    set_config,
)

D = Decimal


def test_pf_is_12_percent_of_basic_capped_at_1800():
    assert compute_pf(D("10000")) == D("1200.00")
    assert compute_pf(D("15000")) == D("1800.00")
    assert compute_pf(D("50000")) == D("1800.00")  # cap


def test_esi_applies_only_up_to_the_ceiling():
    assert compute_esi(D("20000")) == D("150.00")
    assert compute_esi(D("21000")) == D("157.50")
    assert compute_esi(D("21000.01")) == D("0.00")


def test_pt_picks_the_matching_slab():
    slabs = [
        PtSlab(state_code="MH", gross_from=D(0), gross_to=D(7500), monthly_tax=D(0)),
        PtSlab(state_code="MH", gross_from=D(7501), gross_to=D(10000), monthly_tax=D(175)),
        PtSlab(state_code="MH", gross_from=D(10001), gross_to=None, monthly_tax=D(200)),
    ]
    assert compute_pt(D(5000), slabs) == D(0)
    assert compute_pt(D(9000), slabs) == D(175)
    assert compute_pt(D(50000), slabs) == D(200)  # open-ended top slab
    assert compute_pt(D(5000), []) == D(0)  # no slabs configured


def seed(db, pf=False, esi=False, pt=False, state="MH"):
    for key, val in (("pf_enabled", pf), ("esi_enabled", esi), ("pt_enabled", pt)):
        set_config(db, key, "true" if val else "false", None)
    set_config(db, "pt_state", state, None)
    db.add(PtSlab(state_code="MH", gross_from=D(0), gross_to=None, monthly_tax=D(200)))
    db.add(PtSlab(state_code="KA", gross_from=D(0), gross_to=None, monthly_tax=D(150)))
    db.commit()


def test_nothing_is_deducted_when_everything_is_off(db):
    seed(db)
    assert StatutoryContext(db).deductions(D(20000), D(20000), set()) == []


def test_all_three_when_enabled(db):
    seed(db, pf=True, esi=True, pt=True)
    got = {c.name: c.amount for c in StatutoryContext(db).deductions(D(10000), D(20000), set())}
    assert got == {PF_NAME: D("1200.00"), ESI_NAME: D("150.00"), PT_NAME: D(200)}


def test_pt_uses_the_configured_state(db):
    seed(db, pt=True, state="KA")
    got = StatutoryContext(db).deductions(D(10000), D(20000), set())
    assert [(c.name, c.amount) for c in got] == [(PT_NAME, D(150))]


def test_existing_deduction_of_same_name_overrides_the_automatic_one(db):
    seed(db, pf=True)
    assert StatutoryContext(db).deductions(D(10000), D(20000), {PF_NAME}) == []
