from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import statutory
from app.models import PtSlab
from app.schemas import PtSlabIn, StatutorySettingsIn, StatutorySettingsOut


def get_settings_view(db: Session) -> StatutorySettingsOut:
    c = statutory.get_all_configs(db)
    on = lambda k: c.get(k, "false").lower() in ("true", "1", "yes")  # noqa: E731
    return StatutorySettingsOut(
        pf_enabled=on("pf_enabled"),
        esi_enabled=on("esi_enabled"),
        pt_enabled=on("pt_enabled"),
        pt_state=c.get("pt_state") or "MH",
        pt_states=statutory.PT_STATES,
    )


def save_settings(db: Session, data: StatutorySettingsIn, user_id: int) -> StatutorySettingsOut:
    if data.pt_state not in statutory.PT_STATES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid PT state code")
    for key in ("pf_enabled", "esi_enabled", "pt_enabled"):
        statutory.set_config(db, key, "true" if getattr(data, key) else "false", user_id)
    statutory.set_config(db, "pt_state", data.pt_state, user_id)
    db.commit()
    return get_settings_view(db)


def list_slabs(db: Session, state: str | None) -> list[PtSlab]:
    stmt = select(PtSlab).order_by(PtSlab.state_code, PtSlab.gross_from)
    if state:
        stmt = stmt.where(PtSlab.state_code == state)
    return list(db.scalars(stmt))


def _check_state(code: str) -> None:
    if code not in statutory.PT_STATES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid PT state code")


def create_slab(db: Session, data: PtSlabIn) -> PtSlab:
    _check_state(data.state_code)
    slab = PtSlab(**data.model_dump())
    db.add(slab)
    db.commit()
    return slab


def get_slab_or_404(db: Session, slab_id: int) -> PtSlab:
    slab = db.get(PtSlab, slab_id)
    if slab is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slab not found")
    return slab


def update_slab(db: Session, slab: PtSlab, data: PtSlabIn) -> PtSlab:
    _check_state(data.state_code)
    for key, value in data.model_dump().items():
        setattr(slab, key, value)
    db.commit()
    return slab


def delete_slab(db: Session, slab: PtSlab) -> None:
    db.delete(slab)
    db.commit()
