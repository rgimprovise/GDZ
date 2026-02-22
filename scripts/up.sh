#!/usr/bin/env bash
# Поднять сервисы и применить миграции. Интерфейс: http://localhost:8000, дебаг: http://localhost:8000/debug
set -e
cd "$(dirname "$0")/../infra"
docker compose up -d --build
echo "⏳ Ожидание готовности API..."
sleep 5
docker compose exec api alembic upgrade head 2>/dev/null || true
echo "✅ Сервисы запущены."
echo "   API:      http://localhost:8000"
echo "   Дебаг:    http://localhost:8000/debug"
echo "   Swagger:  http://localhost:8000/docs"
