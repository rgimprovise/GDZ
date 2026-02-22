#!/bin/bash
# Локальный запуск TutorBot для разработки
# 
# Использование:
#   ./scripts/run_local.sh          # Запустить API
#   ./scripts/run_local.sh worker   # Запустить Worker
#   ./scripts/run_local.sh infra    # Только инфраструктуру (Postgres, Redis, MinIO)

set -e

cd "$(dirname "$0")/.."

# Загрузить переменные из .env
if [ -f infra/.env ]; then
    export $(grep -v '^#' infra/.env | xargs)
fi

# Переопределить для локального запуска
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export REDIS_URL=redis://localhost:6379/0
export MINIO_ENDPOINT=localhost:9000

case "$1" in
    infra)
        echo "🐳 Запуск инфраструктуры..."
        cd infra
        docker compose -f docker-compose.infra.yml up -d
        echo ""
        echo "✅ Инфраструктура запущена:"
        echo "   PostgreSQL: localhost:5432"
        echo "   Redis:      localhost:6379"
        echo "   MinIO:      localhost:9000 (console: localhost:9001)"
        echo ""
        echo "Для запуска API:"
        echo "   ./scripts/run_local.sh"
        ;;
        
    worker)
        echo "👷 Запуск Worker..."
        cd apps/worker
        
        # Установка зависимостей если нужно
        if [ ! -d "venv" ]; then
            echo "📦 Создание виртуального окружения..."
            python3 -m venv venv
            source venv/bin/activate
            pip install -r requirements.txt
        else
            source venv/bin/activate
        fi
        
        echo "🚀 Worker запущен"
        python -c "from rq import Worker; from redis import Redis; Worker(['default'], connection=Redis.from_url('$REDIS_URL')).work()"
        ;;
        
    *)
        echo "🚀 Запуск API..."
        cd apps/api
        
        # Установка зависимостей если нужно
        if [ ! -d "venv" ]; then
            echo "📦 Создание виртуального окружения..."
            python3 -m venv venv
            source venv/bin/activate
            pip install -r requirements.txt
        else
            source venv/bin/activate
        fi
        
        echo ""
        echo "🌐 API: http://localhost:8000"
        echo "🔧 Debug Panel: http://localhost:8000/debug"
        echo "📚 Swagger: http://localhost:8000/docs"
        echo ""
        
        uvicorn main:app --reload --host 0.0.0.0 --port 8000
        ;;
esac
