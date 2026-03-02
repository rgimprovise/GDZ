"""
Promote a user (by Telegram ID) to a high-limit "Premium" plan.

Usage from API container:
  python -m scripts.promote_premium 430019680

Creates plan "Premium" with daily_queries=99999 if missing,
then sets the user's active subscription to that plan and resets usage counters.
"""
from __future__ import annotations

import sys
import os

# Ensure app root is on path when run as python -m scripts.promote_premium
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import User, Plan, Subscription


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.promote_premium <telegram_user_id>")
        print("Example: python -m scripts.promote_premium 430019680")
        sys.exit(1)

    try:
        tg_uid = int(sys.argv[1])
    except ValueError:
        print("Error: telegram_user_id must be an integer")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.tg_uid == tg_uid).first()
        if not user:
            print(f"User with tg_uid={tg_uid} not found. Create the user first (e.g. open the app from Telegram once).")
            sys.exit(1)

        plan = db.query(Plan).filter(Plan.name == "Premium").first()
        if not plan:
            plan = Plan(
                name="Premium",
                type="premium",
                daily_queries=99999,
                monthly_queries=999999,
                price_monthly=0,
                price_yearly=0,
                features={"unlimited": True},
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            print(f"Created plan 'Premium' (id={plan.id}, daily_queries={plan.daily_queries})")

        sub = db.query(Subscription).filter(
            Subscription.user_id == user.id,
            Subscription.status == "active",
        ).first()
        if not sub:
            sub = Subscription(user_id=user.id, plan_id=plan.id)
            db.add(sub)
            db.commit()
            db.refresh(sub)
            print(f"Created subscription for user id={user.id} -> plan_id={plan.id}")
        else:
            sub.plan_id = plan.id
            sub.queries_used_today = 0
            sub.queries_used_month = 0
            db.commit()
            print(f"Updated subscription for user id={user.id} -> plan 'Premium' (daily_queries={plan.daily_queries}), reset usage")

        print(f"Done. User tg_uid={tg_uid} (id={user.id}) is now on Premium.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
