#!/usr/bin/env bash
# Единое обновление на VPS после git push.
# Данные (БД, PDF, OCR-файлы) не удаляются — только подтягивается код, пересборка и миграции.
#
# На VPS запускать из корня репозитория:
#   cd /opt/tutorbot && ./scripts/update_on_vps.sh
#
# Опционально: BRANCH=main (по умолчанию), SKIP_PULL=1 — не делать git pull.

set -e
BRANCH="${BRANCH:-main}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
INFRA="$REPO_ROOT/infra"

# На VPS используем порты 5433/6380, если есть override
COMPOSE_OPTS="-f docker-compose.yml"
[ -f "$INFRA/docker-compose.vps-ports.yml" ] && COMPOSE_OPTS="$COMPOSE_OPTS -f docker-compose.vps-ports.yml"

echo "📥 git pull origin $BRANCH"
if [ -z "$SKIP_PULL" ]; then
  if ! git pull origin "$BRANCH"; then
    echo "   Локальные изменения мешают pull. Сбрасываю отслеживаемые файлы и повторяю..."
    git checkout -- .
    git pull origin "$BRANCH"
  fi
else
  echo "   (SKIP_PULL=1, пропуск)"
fi

echo "🔨 Остановка контейнеров (volumes и данные сохраняются)"
cd "$INFRA"
docker-compose $COMPOSE_OPTS down

echo "🔨 Сборка и запуск контейнеров (кэш Docker используется — пересборка только при изменении Dockerfile/requirements)"
docker-compose $COMPOSE_OPTS build
docker-compose $COMPOSE_OPTS up -d

echo "📋 Применение миграций БД (alembic upgrade head)"
docker-compose $COMPOSE_OPTS exec -T api alembic upgrade head || {
  echo "⚠️  Миграции не выполнились (возможно, api ещё не поднялся). Запустите вручную:"
  echo "   cd $INFRA && docker-compose $COMPOSE_OPTS exec api alembic upgrade head"
}

echo "✅ Обновление завершено. Debug: https://gdz.n8nrgimprovise.space/debug"
