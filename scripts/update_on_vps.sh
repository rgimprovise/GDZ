#!/usr/bin/env bash
# Обновление приложения на VPS после git push.
# Запускать на VPS из корня репозитория: ./scripts/update_on_vps.sh
# Опционально: BRANCH=main (по умолчанию), SKIP_PULL=1 чтобы не делать git pull.

set -e
BRANCH="${BRANCH:-main}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ -z "$SKIP_PULL" ]; then
  echo "📥 git pull origin $BRANCH"
  git pull origin "$BRANCH"
fi

echo "🔨 docker-compose build & up (infra)"
cd "$REPO_ROOT/infra"
docker-compose build --no-cache
docker-compose up -d
docker-compose exec -T api alembic upgrade head 2>/dev/null || true
echo "✅ Update done. Debug: https://gdz.n8nrgimprovise.space/debug"
