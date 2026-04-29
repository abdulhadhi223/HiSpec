"""
app/api/reference.py
Reference data endpoints — Missions.

ACTION REQUIRED in app/main.py — register this router:
    from app.api.reference import router as reference_router
    app.include_router(reference_router)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import MissionCreate, MissionResponse, MissionUpdate
from app.services import reference_service as svc

router = APIRouter(tags=["Reference Data"])


# ── Missions ──────────────────────────────────────────────────────────────────

@router.post("/missions", response_model=MissionResponse, status_code=status.HTTP_201_CREATED)
def create_mission(data: MissionCreate, db: Session = Depends(get_db)):
    return svc.create_mission(db, data)

@router.get("/missions", response_model=list[MissionResponse])
def list_missions(
    skip:  int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_missions(db, skip, limit)

@router.get("/missions/{id}", response_model=MissionResponse)
def get_mission(id: uuid.UUID, db: Session = Depends(get_db)):
    mission = svc.get_mission(db, id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission

@router.patch("/missions/{id}", response_model=MissionResponse)
def update_mission(id: uuid.UUID, data: MissionUpdate, db: Session = Depends(get_db)):
    mission = svc.update_mission(db, id, data)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission

