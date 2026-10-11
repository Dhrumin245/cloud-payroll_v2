from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import settings_service
from app.database import get_db
from app.schemas import PtSlabIn, PtSlabOut, StatutorySettingsIn, StatutorySettingsOut
from app.security import CurrentUser, require_admin

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/statutory", response_model=StatutorySettingsOut)
def get_statutory(_admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    return settings_service.get_settings_view(db)


@router.put("/statutory", response_model=StatutorySettingsOut)
def put_statutory(
    body: StatutorySettingsIn,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Switch PF / ESI / Professional Tax on or off for the whole company."""
    return settings_service.save_settings(db, body, admin.user_id)


@router.get("/pt-slabs", response_model=list[PtSlabOut])
def list_pt_slabs(
    state: str | None = None,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return settings_service.list_slabs(db, state)


@router.post("/pt-slabs", response_model=PtSlabOut, status_code=status.HTTP_201_CREATED)
def create_pt_slab(
    body: PtSlabIn, _admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    return settings_service.create_slab(db, body)


@router.put("/pt-slabs/{slab_id}", response_model=PtSlabOut)
def update_pt_slab(
    slab_id: int,
    body: PtSlabIn,
    _admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return settings_service.update_slab(db, settings_service.get_slab_or_404(db, slab_id), body)


@router.delete("/pt-slabs/{slab_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pt_slab(
    slab_id: int, _admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    settings_service.delete_slab(db, settings_service.get_slab_or_404(db, slab_id))
