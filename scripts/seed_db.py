#!/usr/bin/env python3
"""
Database seed script.

Creates test data for development:
- Test user
- Free plan (if not exists)
- Subscription for test user

Usage:
    docker compose exec api python /app/scripts/seed_db.py
    # or locally:
    cd apps/api && python ../../scripts/seed_db.py
"""
import sys
import os

# Add api directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'apps', 'api'))

from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import from api
from config import get_settings
from database import Base
from models import User, Plan, Subscription, PlanType, SubscriptionStatus

settings = get_settings()

# Create engine
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine)


def seed_database():
    """Seed database with test data."""
    db = SessionLocal()
    
    try:
        print("🌱 Seeding database...")
        
        # 1. Create or get Free plan
        free_plan = db.query(Plan).filter(Plan.type == PlanType.FREE).first()
        
        if not free_plan:
            print("  Creating Free plan...")
            free_plan = Plan(
                name="Free",
                type=PlanType.FREE,
                daily_queries=5,
                monthly_queries=50,
                price_monthly=0,
                price_yearly=0,
                features={"hints_only": False},
            )
            db.add(free_plan)
            db.commit()
            db.refresh(free_plan)
            print(f"  ✅ Created Free plan (id={free_plan.id})")
        else:
            print(f"  ℹ️ Free plan already exists (id={free_plan.id})")
        
        # 2. Create Basic plan
        basic_plan = db.query(Plan).filter(Plan.type == PlanType.BASIC).first()
        
        if not basic_plan:
            print("  Creating Basic plan...")
            basic_plan = Plan(
                name="Basic",
                type=PlanType.BASIC,
                daily_queries=20,
                monthly_queries=300,
                price_monthly=29900,  # 299 RUB
                price_yearly=299900,  # 2999 RUB
                features={"hints_only": False, "priority": True},
            )
            db.add(basic_plan)
            db.commit()
            print(f"  ✅ Created Basic plan (id={basic_plan.id})")
        
        # 3. Create Premium plan
        premium_plan = db.query(Plan).filter(Plan.type == PlanType.PREMIUM).first()
        
        if not premium_plan:
            print("  Creating Premium plan...")
            premium_plan = Plan(
                name="Premium",
                type=PlanType.PREMIUM,
                daily_queries=100,
                monthly_queries=1000,
                price_monthly=49900,  # 499 RUB
                price_yearly=499900,  # 4999 RUB
                features={"hints_only": False, "priority": True, "no_ads": True},
            )
            db.add(premium_plan)
            db.commit()
            print(f"  ✅ Created Premium plan (id={premium_plan.id})")
        
        # 4. Create test user
        test_user = db.query(User).filter(User.tg_uid == 123456789).first()
        
        if not test_user:
            print("  Creating test user...")
            test_user = User(
                tg_uid=123456789,
                username="testuser",
                display_name="Test User",
                language_code="ru",
                accepted_terms_at=datetime.utcnow(),
                accepted_privacy_at=datetime.utcnow(),
            )
            db.add(test_user)
            db.commit()
            db.refresh(test_user)
            print(f"  ✅ Created test user (id={test_user.id}, tg_uid=123456789)")
        else:
            print(f"  ℹ️ Test user already exists (id={test_user.id})")
        
        # 5. Create subscription for test user
        subscription = (
            db.query(Subscription)
            .filter(Subscription.user_id == test_user.id)
            .filter(Subscription.status == SubscriptionStatus.ACTIVE)
            .first()
        )
        
        if not subscription:
            print("  Creating subscription for test user...")
            subscription = Subscription(
                user_id=test_user.id,
                plan_id=free_plan.id,
                status=SubscriptionStatus.ACTIVE,
                queries_used_today=0,
                queries_used_month=0,
            )
            db.add(subscription)
            db.commit()
            print(f"  ✅ Created Free subscription for test user")
        else:
            print(f"  ℹ️ Test user already has active subscription")
        
        print("")
        print("🎉 Database seeded successfully!")
        print("")
        print("Test user credentials:")
        print(f"  User ID: {test_user.id}")
        print(f"  Telegram UID: {test_user.tg_uid}")
        print(f"  Username: {test_user.username}")
        print("")
        
    except Exception as e:
        print(f"❌ Error seeding database: {e}")
        db.rollback()
        raise
        
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
