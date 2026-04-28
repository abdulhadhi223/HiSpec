"""
app/main.py
FastAPI application entry-point.
"""
from fastapi import FastAPI

from app.api.activity_reports import router as activity_reports_router
from app.api.ew_tracks import router as ew_tracks_router
from app.api.reference import router as reference_router

app = FastAPI(title="NMDB EW Feature API", version="5.0")

app.include_router(reference_router)
app.include_router(ew_tracks_router)
app.include_router(activity_reports_router)
