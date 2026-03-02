"""
TutorBot API — FastAPI Application

Simplified architecture: all content retrieval via OpenAI Assistants API.
"""
import logging
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from schemas import HealthResponse
from routers import auth as auth_router
from routers import conversations as conversations_router

logger = logging.getLogger(__name__)
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


def _seed_database():
    """Create free plan and guest user if they don't exist."""
    from database import SessionLocal
    from models import Plan, User, Subscription

    db = SessionLocal()
    try:
        free_plan = db.query(Plan).filter(Plan.type == "free").first()
        if not free_plan:
            free_plan = Plan(
                name="Free",
                type="free",
                daily_queries=20,
                monthly_queries=500,
                price_monthly=0,
                price_yearly=0,
                features={"hints_only": False},
            )
            db.add(free_plan)
            db.commit()
            db.refresh(free_plan)
            logger.info("Created free plan (id=%d)", free_plan.id)

        guest = db.query(User).filter(User.tg_uid == 0).first()
        if not guest:
            guest = User(
                tg_uid=0,
                username="guest",
                display_name="Гость",
                language_code="ru",
            )
            db.add(guest)
            db.commit()
            db.refresh(guest)
            logger.info("Created guest user (id=%d)", guest.id)

        has_sub = (
            db.query(Subscription)
            .filter(Subscription.user_id == guest.id, Subscription.status == "active")
            .first()
        )
        if not has_sub:
            sub = Subscription(user_id=guest.id, plan_id=free_plan.id)
            db.add(sub)
            db.commit()
            logger.info("Created guest subscription")
    except Exception:
        db.rollback()
        logger.exception("Seed failed — tables may not exist yet")
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    from database import Base, engine
    Base.metadata.create_all(bind=engine)
    logger.info("DB tables ensured")

    _seed_database()

    print(f"TutorBot API v0.2.0 | env={settings.env}")
    print(f"DB: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    print(f"Assistant: {settings.openai_assistant_id or '(not set)'}")
    print(f"Docs: http://localhost:8000/docs")


@app.on_event("shutdown")
async def shutdown_event():
    print("TutorBot API shutting down")
