#!/usr/bin/env bash
# Применить миграции БД (из корня репозитория или из infra).
set -e
cd "$(dirname "$0")/../infra"
docker compose exec api alembic upgrade head
echo "✅ Миграции применены."
