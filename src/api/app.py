from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import capture, laps, sessions

app = FastAPI(title="SlipStream API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(laps.router)
app.include_router(capture.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
