#!/bin/sh
set -e

echo "Running Alembic migrations..."
alembic upgrade head 2>/dev/null || echo "Alembic migration skipped (tables will be created by app)"

echo "Starting API server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
