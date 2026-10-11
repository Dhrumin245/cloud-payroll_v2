"""Statutory deductions (India): PF, ESI and Professional Tax. Ported from the legacy app.

  PF   12% of FULL basic pay, capped at Rs 1,800 / month
  ESI  0.75% of the (prorated) gross, only while gross <= Rs 21,000
  PT   slab lookup by state and (prorated) gross

Each is switched on or off company-wide in `statutory_configs`. If an employee already has a
deduction with the same name (e.g. a manually entered "Provident Fund (PF)"), the automatic
one is skipped, which allows per-employee overrides.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import ComponentInput
from app.models import PtSlab, StatutoryConfig

PF_RATE = Decimal("0.12")
PF_CAP = Decimal("1800.00")
ESI_RATE = Decimal("0.0075")
ESI_GROSS_CEILING = Decimal("21000.00")
_TWO = Decimal("0.01")

PF_NAME = "Provident Fund (PF)"
ESI_NAME = "Employee State Insurance (ESI)"
PT_NAME = "Professional Tax (PT)"

PT_STATES = {
    "MH": "Maharashtra",
    "KA": "Karnataka",
    "WB": "West Bengal",
    "TN": "Tamil Nadu",
    "AP": "Andhra Pradesh",
    "TG": "Telangana",
    "GJ": "Gujarat",
    "MP": "Madhya Pradesh",
    "KL": "Kerala",
}
CONFIG_KEYS = ("pf_enabled", "esi_enabled", "pt_enabled", "pt_state")


# ---------------------------------------------------------------- config
def get_all_configs(db: Session) -> dict[str, str]:
    return {row.key: row.value for row in db.scalars(select(StatutoryConfig))}


def set_config(db: Session, key: str, value: str, user_id: int | None) -> None:
    row = db.scalar(select(StatutoryConfig).where(StatutoryConfig.key == key))
    if row is None:
        db.add(StatutoryConfig(key=key, value=value, updated_by_user_id=user_id))
    else:
        row.value = value
        row.updated_by_user_id = user_id


def _enabled(configs: dict[str, str], key: str) -> bool:
    return configs.get(key, "false").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------- pure maths
def compute_pf(basic_pay: Decimal) -> Decimal:
    return min((basic_pay * PF_RATE).quantize(_TWO, rounding=ROUND_HALF_UP), PF_CAP)


def compute_esi(gross_pay: Decimal) -> Decimal:
    if gross_pay > ESI_GROSS_CEILING:
        return Decimal("0.00")
    return (gross_pay * ESI_RATE).quantize(_TWO, rounding=ROUND_HALF_UP)


def compute_pt(gross_pay: Decimal, slabs: list[PtSlab]) -> Decimal:
    for slab in sorted(slabs, key=lambda s: s.gross_from):
        if gross_pay >= slab.gross_from and (slab.gross_to is None or gross_pay <= slab.gross_to):
            return slab.monthly_tax
    return Decimal("0.00")


# ---------------------------------------------------------------- payroll integration
class StatutoryContext:
    """Loads config and slabs ONCE per payroll run instead of once per employee."""

    def __init__(self, db: Session) -> None:
        self.configs = get_all_configs(db)
        state = self.configs.get("pt_state") or "MH"
        self.slabs = (
            list(db.scalars(select(PtSlab).where(PtSlab.state_code == state)))
            if _enabled(self.configs, "pt_enabled")
            else []
        )

    def deductions(
        self, basic_pay: Decimal, gross_pay: Decimal, existing_names: set[str]
    ) -> list[ComponentInput]:
        result: list[ComponentInput] = []
        if _enabled(self.configs, "pf_enabled") and PF_NAME not in existing_names:
            amount = compute_pf(basic_pay)
            if amount > 0:
                result.append(ComponentInput("deduction", PF_NAME, amount))
        if _enabled(self.configs, "esi_enabled") and ESI_NAME not in existing_names:
            amount = compute_esi(gross_pay)
            if amount > 0:
                result.append(ComponentInput("deduction", ESI_NAME, amount))
        if _enabled(self.configs, "pt_enabled") and PT_NAME not in existing_names:
            amount = compute_pt(gross_pay, self.slabs)
            if amount > 0:
                result.append(ComponentInput("deduction", PT_NAME, amount))
        return result
