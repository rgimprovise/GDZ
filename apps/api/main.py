"""
TutorBot API — FastAPI Application

Simplified architecture: all content retrieval via OpenAI Assistants API.
"""
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from schemas import HealthResponse
from routers import auth as auth_router
from routers import conversations as conversations_router

settings = get_settings()

app = FastAPI(
    title="TutorBot API",
    description="Educational tutoring assistant API (OpenAI Assistants)",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(conversations_router.router)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check():
    return HealthResponse(
        status="ok",
        version="0.2.0",
        timestamp=datetime.utcnow(),
    )


@app.on_event("startup")
async def startup_event():
    print(f"TutorBot API v0.2.0 | env={settings.env}")
    print(f"DB: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    print(f"Assistant: {settings.openai_assistant_id or '(not set)'}")
    print(f"Docs: http://localhost:8000/docs")


@app.on_event("shutdown")
async def shutdown_event():
    print("TutorBot API shutting down")
