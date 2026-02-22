# TutorBot — Educational Tutoring Assistant

> Telegram Bot + API для помощи с домашними заданиями на основе проверенных источников.

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                      TutorBot Monorepo                       │
├─────────────────────────────────────────────────────────────┤
│  apps/                                                       │
│    ├── api/        → FastAPI (REST API, auth, queries)       │
│    ├── worker/     → RQ Worker (обработка очереди)           │
│    └── bot/        → Telegram Bot (уведомления, платежи)     │
│                                                              │
│  packages/                                                   │
│    └── shared/     → Общие константы и утилиты               │
│                                                              │
│  infra/                                                      │
│    └── docker-compose.yml → Postgres, Redis, MinIO           │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Быстрый старт

### 1. Подготовка окружения

```bash
cd infra
cp env.example .env
# Отредактируйте .env при необходимости
```

### 2. Запуск всех сервисов

```bash
cd infra
docker compose up --build -d
```

Это запустит:
- **PostgreSQL 16** (порт 5432)
- **Redis 7** (порт 6379)
- **MinIO** (порты 9000/9001)
- **API** (порт 8000)
- **Worker** (обработка очереди)
- **Bot** (Telegram polling — в standby если токен не указан)

### 3. Применение миграций

Из корня репозитория (при запущенном Docker):

```bash
./scripts/apply_migrations.sh
```

Или вручную из `infra`:

```bash
cd infra && docker compose exec api alembic upgrade head
```

**Полный запуск** (поднять сервисы + миграции): `./scripts/up.sh`

**Перенос на VPS:** см. [docs/DEPLOY_VPS.md](docs/DEPLOY_VPS.md) — требования, что переносить (код, data, дамп БД), настройка .env, запуск, nginx/SSL, бэкапы.

**Деплой на VPS с Caddy:** см. [docs/DEPLOY_VPS_CADDY.md](docs/DEPLOY_VPS_CADDY.md) — развёртывание через GitHub, Caddy reverse proxy, **debug-панель по https://ваш-домен/debug**, команды обновления на каждой итерации.

### 4. Создание тестового пользователя

```bash
docker compose exec postgres psql -U tutorbot -d tutorbot -c "
INSERT INTO users (tg_uid, username, display_name) 
VALUES (123456789, 'testuser', 'Test User');
"

docker compose exec postgres psql -U tutorbot -d tutorbot -c "
INSERT INTO subscriptions (user_id, plan_id, status) 
SELECT 1, 1, 'active';
"
```

### 5. Проверка работы

```bash
# Health check
curl http://localhost:8000/health

# Swagger docs
open http://localhost:8000/docs
```

---

## 📡 API Endpoints

### Health Check

```bash
curl http://localhost:8000/health
```

**Ответ:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "2026-02-02T12:00:00.000000"
}
```

### Создание запроса

```bash
curl -X POST http://localhost:8000/v1/queries \
  -H "Content-Type: application/json" \
  -d '{"text": "Решите уравнение: 2x + 5 = 13"}'
```

**Ответ (201 Created):**
```json
{
  "id": 1,
  "user_id": 1,
  "input_text": "Решите уравнение: 2x + 5 = 13",
  "status": "queued",
  "created_at": "2026-02-02T12:00:00.000000",
  "updated_at": "2026-02-02T12:00:00.000000"
}
```

### Получение результата

```bash
curl http://localhost:8000/v1/queries/1
```

**Ответ (после обработки worker'ом):**
```json
{
  "id": 1,
  "user_id": 1,
  "input_text": "Решите уравнение: 2x + 5 = 13",
  "status": "done",
  "extracted_text": "Решите уравнение: 2x + 5 = 13",
  "response": {
    "id": 1,
    "content_markdown": "## Ответ на запрос\n\n...",
    "citations": [],
    "confidence_score": 100,
    "created_at": "2026-02-02T12:00:01.000000"
  },
  "created_at": "2026-02-02T12:00:00.000000",
  "updated_at": "2026-02-02T12:00:01.000000"
}
```

### Аутентификация (Telegram Mini App)

```bash
curl -X POST http://localhost:8000/v1/auth/telegram \
  -H "Content-Type: application/json" \
  -d '{"init_data": "user=%7B%22id%22%3A123456789%7D&..."}'
```

---

## 🧪 Полный тестовый сценарий

```bash
# 1. Health check
curl -s http://localhost:8000/health | jq

# 2. Создать запрос
RESPONSE=$(curl -s -X POST http://localhost:8000/v1/queries \
  -H "Content-Type: application/json" \
  -d '{"text": "Найдите корни: x² - 5x + 6 = 0"}')
echo "$RESPONSE" | jq

# Получить ID
QUERY_ID=$(echo "$RESPONSE" | jq -r '.id')

# 3. Подождать обработки
sleep 3

# 4. Получить результат
curl -s "http://localhost:8000/v1/queries/$QUERY_ID" | jq

# 5. Логи worker'а
docker compose logs worker --tail 5
```

---

## 🗂️ База данных

| Таблица | Описание |
|---------|----------|
| `users` | Telegram пользователи |
| `plans` | Тарифные планы (free, basic, premium) |
| `subscriptions` | Подписки пользователей |
| `queries` | Запросы на решение задач |
| `responses` | Сгенерированные ответы |

---

## 🔧 Разработка

### Логи сервисов

```bash
docker compose logs -f api      # API
docker compose logs -f worker   # Worker
docker compose logs -f bot      # Bot
```

### Подключение к базе

```bash
docker compose exec postgres psql -U tutorbot -d tutorbot
```

### Учебник геометрии в БД как «Математика»

Если учебник по геометрии при seed попал как subject=math и title="Математика ...", исправить:

```bash
# из корня проекта (или из infra)
python3 scripts/fix_geometry_books.py --book-id 1    # сухой прогон
python3 scripts/fix_geometry_books.py --book-id 1 --apply   # применить
```

Для новых загрузок в `seed_books` добавлен отдельный предмет **geometry** (геометрия не смешивается с математикой).

### Создание новой миграции

```bash
docker compose exec api alembic revision --autogenerate -m "description"
docker compose exec api alembic upgrade head
```

### Перезапуск после изменений

```bash
docker compose build --no-cache api worker bot
docker compose up -d
```

---

## 📋 Статус разработки

### ✅ MVP (Phase 1 + Phase 3 stub)
- [x] Структура монорепо
- [x] Docker Compose инфраструктура (Postgres, Redis, MinIO)
- [x] FastAPI с /health endpoint
- [x] SQLAlchemy модели + Alembic миграции
- [x] POST /v1/queries + Redis Queue (RQ)
- [x] Worker обработка (stub)
- [x] Telegram Bot (минимальный, standby без токена)
- [x] Telegram initData валидация
- [x] /v1/auth/telegram endpoint

### 🔜 Следующие шаги (Phase 2-5)
- [ ] OCR для фото (Tesseract)
- [ ] Поиск по базе решебников (FTS + pgvector)
- [ ] Генерация ответов через OpenAI
- [ ] Push уведомления через бота
- [ ] Telegram Mini App
- [ ] Admin панель

---

## 🔐 Принципы

- **Grounded responses** — все ответы основаны на проверенных источниках
- **Цитирование** — ссылки на страницы и разделы
- **Пошаговое объяснение** — помощь в понимании, не просто ответы

---

## 📝 Лицензия

Private / Internal Use Only
