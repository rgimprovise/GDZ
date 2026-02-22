# Перенос TutorBot (GDZ) на VPS

Кратко: что перенести, как настроить и запустить проект на VPS так, чтобы БД, данные (PDF, OCR-файлы) и сервисы работали стабильно.

---

## 1. Требования к VPS

- **ОС:** Ubuntu 22.04 / 24.04 или Debian 12 (рекомендуется).
- **Ресурсы:** минимум 2 GB RAM, 2 CPU; для OCR (Tesseract) и нескольких воркеров — 4 GB RAM и больше.
- **Диск:** 20+ GB (БД, PDF, `data/ocr_raw`, `data/ocr_normalized`, образы Docker).
- **Сеть:** открыть порты 80, 443 (если ставите nginx + SSL) и по желанию 22 для SSH.

Установка Docker на Ubuntu/Debian:

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER
# выйти и зайти снова или newgrp docker
```

---

## 2. Что переносить

| Что | Куда на VPS | Как |
|-----|-------------|-----|
| **Код** | Репозиторий (git clone или архив) | `git clone <repo>` в каталог, например `/opt/tutorbot` или `~/tutorbot`. |
| **Конфиг** | `infra/.env` | Создать из `infra/env.example`, заполнить секреты и `BASE_URL`. В репозиторий не коммитить. |
| **Данные приложения** | Каталог `data/` | Копировать целиком (PDF, при необходимости уже созданные `ocr_raw/`, `ocr_normalized/`). |
| **БД** | Внутри контейнера Postgres (volume) | Дамп с текущей машины, восстановление на VPS (см. ниже). |

Структура после клона на VPS (пример):

```
/opt/tutorbot/          # корень репозитория
├── apps/
├── infra/
│   ├── .env            # создан вручную, не из git
│   └── docker-compose.yml
├── data/               # скопирован с текущей машины
│   ├── pdfs/           # PDF учебников
│   ├── ocr_raw/        # после первого запуска по новому пайплайну
│   └── ocr_normalized/
└── ...
```

---

## 3. Конфигурация на VPS

### 3.1 Создание `.env`

```bash
cd /opt/tutorbot/infra
cp env.example .env
nano .env   # или vim
```

Обязательно поменять:

- **`BASE_URL`** — публичный URL API, например `https://yourdomain.com` (или `http://IP:8000` до настройки nginx).
- **`POSTGRES_PASSWORD`** — надёжный пароль (на VPS не использовать дефолтный из примера).
- **`JWT_SECRET`** — случайная строка для подписи JWT.
- **`TELEGRAM_BOT_TOKEN`** — токен бота.
- **`TELEGRAM_WEBHOOK_SECRET`** — секрет для вебхука (если бот будет в webhook-режиме).
- **`OPENAI_API_KEY`** — ключ API OpenAI (если уже используется).
- **MinIO:** при желании на VPS можно оставить те же `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` или задать свои.

Внутри Docker имена хостов не меняем: `POSTGRES_HOST=postgres`, `REDIS_URL=redis://redis:6379/0`, `MINIO_ENDPOINT=minio:9000`. Они заданы в `docker-compose.yml` через `environment`.

### 3.2 Путь к данным (PDF и OCR-файлы)

В `docker-compose.yml` у сервиса **worker** указано:

```yaml
volumes:
  - ../data:/app/data
```

Это относительный путь от каталога `infra/`. Если на VPS репозиторий лежит в `/opt/tutorbot`, то `../data` = `/opt/tutorbot/data`. Положите туда каталог `data/` с хоста (включая `pdfs/`). После первого запуска ingestion по новому пайплайну там появятся `ocr_raw/` и `ocr_normalized/`.

Если хотите хранить данные отдельно от репозитория (удобно при обновлении кода через git):

1. Создайте на VPS каталог, например: `sudo mkdir -p /var/lib/tutorbot/data`.
2. Скопируйте туда содержимое вашего `data/` (в т.ч. `pdfs/`).
3. В `infra/docker-compose.yml` у **worker** замените volume на:

   ```yaml
   volumes:
     - /var/lib/tutorbot/data:/app/data
   ```

Тогда PDF и OCR-файлы будут в `/var/lib/tutorbot/data` и не зависят от расположения репозитория.

---

## 4. Запуск на VPS

### 4.1 Первый запуск (без переноса БД)

Если начинаете с чистой БД:

```bash
cd /opt/tutorbot/infra
docker compose up -d --build
# Дождаться healthcheck postgres/redis/minio
docker compose exec api alembic upgrade head
```

Проверка:

```bash
curl -s http://localhost:8000/health
# или снаружи: curl -s http://IP_VPS:8000/health
```

Дальше: seed книг/источников (если есть скрипт), загрузка PDF в `data/pdfs/` и постановка ingestion в очередь.

### 4.2 Если переносите существующую БД

С **текущей машины** (где уже крутится проект):

```bash
# Дамп БД (пароль и хост — как у вас локально/в Docker)
PGPASSWORD=tutorbot_secret_change_me pg_dump -h localhost -U tutorbot -d tutorbot -F c -f tutorbot_dump.dump
# Или из контейнера:
docker compose exec postgres pg_dump -U tutorbot -d tutorbot -F c > tutorbot_dump.dump
```

Перенесите файл на VPS (scp, rsync и т.п.):

```bash
scp tutorbot_dump.dump user@VPS_IP:/opt/tutorbot/
```

На **VPS** поднимите только Postgres (или весь стек), создайте БД при необходимости и восстановите дамп:

```bash
cd /opt/tutorbot/infra
docker compose up -d postgres redis minio
sleep 5
docker compose exec -T postgres pg_restore -U tutorbot -d tutorbot --clean --if-exists < ../tutorbot_dump.dump
# Если база ещё не создана:
# docker compose exec postgres psql -U tutorbot -c "CREATE DATABASE tutorbot;"
# затем pg_restore без --clean
```

После этого поднимите остальные сервисы и при необходимости догоните миграции:

```bash
docker compose up -d
docker compose exec api alembic upgrade head
```

---

## 5. Данные приложения (data/)

- Скопируйте с текущей машины каталог **`data/`** (как минимум `data/pdfs/`) на VPS в выбранное место (`/opt/tutorbot/data` или `/var/lib/tutorbot/data`).
- Если уже есть каталоги **`ocr_raw/`** и **`ocr_normalized/`** — перенесите их вместе с `data/`, чтобы не перегонять OCR заново.
- Права: чтобы контейнер worker мог писать в `data/`, на VPS обычно достаточно `chmod -R 755 /path/to/data` и при необходимости указать владельца (например, того же пользователя, от которого запускается Docker).

---

## 6. Nginx и HTTPS (опционально)

Чтобы отдавать API по 80/443 и подставить SSL:

1. Установите nginx и certbot:

   ```bash
   sudo apt install -y nginx certbot python3-certbot-nginx
   ```

2. В DNS у домена укажите A-запись на IP VPS.

3. Пример конфига nginx для проксирования на API (файл в `/etc/nginx/sites-available/tutorbot`):

   ```nginx
   server {
       listen 80;
       server_name yourdomain.com;
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

   Включите сайт и получите сертификат:

   ```bash
   sudo ln -s /etc/nginx/sites-available/tutorbot /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d yourdomain.com
   ```

4. В **`.env`** на VPS поставьте `BASE_URL=https://yourdomain.com`.

---

## 7. Проверка после переноса

- `curl https://yourdomain.com/health` (или `http://IP:8000/health`) — ответ `{"status":"ok", ...}`.
- Зайти в Swagger: `https://yourdomain.com/docs`.
- Проверить, что в БД есть книги/источники и страницы:  
  `docker compose exec postgres psql -U tutorbot -d tutorbot -c "SELECT id, status, page_count FROM pdf_sources;"`
- При необходимости поставить в очередь ingestion/reanalyze и убедиться, что worker обрабатывает задачи и пишет в `data/ocr_raw` и `data/ocr_normalized` (если уже по новому пайплайну).

---

## 8. Бэкапы на VPS

- **Postgres:** по расписанию (cron) дамп в файл и копирование в безопасное место:

  ```bash
  0 3 * * * docker compose -f /opt/tutorbot/infra/docker-compose.yml exec -T postgres pg_dump -U tutorbot tutorbot -F c > /backups/tutorbot_$(date +\%Y\%m\%d).dump
  ```

- **Данные:** периодически архивировать `data/` (или `/var/lib/tutorbot/data`), включая `pdfs/`, `ocr_raw/`, `ocr_normalized/`.

---

## 9. Использование VPS только для OCR (мощностей компа не хватает)

Если локально OCR тормозит или падает по памяти, можно гонять **ingestion (OCR)** на VPS, а дальше либо работать уже на VPS, либо забрать результат обратно на комп.

**Важно:** не присылайте и не вставляйте в чат SSH-ключи и пароли. Используйте ключ только у себя: подключайтесь к VPS с своей машины по SSH и выполняйте команды ниже.

### 9.1 Рекомендуемый вариант: весь стек на VPS

На VPS поднимаете проект целиком (Postgres, Redis, MinIO, API, **worker**, bot), переносите туда `data/` и при необходимости дамп БД. OCR выполняется воркером на VPS (больше RAM/CPU — меньше шанс OOM и быстрее обработка).

**Шаги:**

1. **На своей машине** — подготовить данные и (опционально) дамп БД:
   ```bash
   # Дамп БД (если хотите сохранить книги/источники и потом забрать результат обратно)
   cd infra && docker compose exec -T postgres pg_dump -U tutorbot -d tutorbot -F c > ../tutorbot_dump.dump
   ```

2. **Скопировать на VPS** репозиторий и данные (подставьте свой `user` и `VPS_IP`):
   ```bash
   rsync -avz --exclude '.git' --exclude 'node_modules' ./ user@VPS_IP:/opt/tutorbot/
   rsync -avz ./data/ user@VPS_IP:/opt/tutorbot/data/
   scp tutorbot_dump.dump user@VPS_IP:/opt/tutorbot/
   ```

3. **Подключиться к VPS** и запустить стек:
   ```bash
   ssh user@VPS_IP
   cd /opt/tutorbot/infra
   cp env.example .env
   # Отредактировать .env (POSTGRES_PASSWORD, BASE_URL и т.д.)
   docker compose up -d --build
   docker compose exec api alembic upgrade head
   ```

4. **Восстановить дамп** (если переносили БД):
   ```bash
   docker compose exec -T postgres pg_restore -U tutorbot -d tutorbot --clean --if-exists < ../tutorbot_dump.dump
   ```

5. **Поставить ingestion в очередь** (все источники или выборочно):
   ```bash
   docker compose exec -T worker sh -c 'cd /app && python3 -c "
   from ingestion import enqueue_ingestion
   for i in range(1, 7):
       enqueue_ingestion(i)
       print(\"Enqueued\", i)
   "'
   ```

6. Следить за логами воркера: `docker compose logs -f worker`. После завершения в `data/ocr_raw/` и `data/ocr_normalized/` появятся файлы, в БД — страницы и задачи.

7. **Забрать результат обратно на комп** (по желанию):
   ```bash
   rsync -avz user@VPS_IP:/opt/tutorbot/data/ocr_raw/    ./data/ocr_raw/
   rsync -avz user@VPS_IP:/opt/tutorbot/data/ocr_normalized/ ./data/ocr_normalized/
   # и/или дамп БД после обработки
   ssh user@VPS_IP "cd /opt/tutorbot/infra && docker compose exec -T postgres pg_dump -U tutorbot -d tutorbot -F c" > tutorbot_after_ocr.dump
   ```

### 9.2 Ресурсы VPS для OCR

- OCR выполняется **Tesseract** (легче по памяти, чем прежний EasyOCR).

---

## 10. Краткий чеклист переноса

1. Подготовить VPS (Docker, диск, порты).
2. Клонировать репозиторий в выбранный каталог.
3. Создать `infra/.env` из `env.example`, задать `BASE_URL`, пароли, токены.
4. При необходимости изменить volume для `data` в `docker-compose.yml` на абсолютный путь.
5. Скопировать на VPS каталог `data/` (как минимум `pdfs/`).
6. При необходимости перенести дамп БД и восстановить его после `docker compose up -d postgres`.
7. Запустить стек: `docker compose up -d --build`, применить миграции.
8. При необходимости настроить nginx и HTTPS, обновить `BASE_URL`.
9. Проверить health, БД, при необходимости — ingestion и файлы в `data/`.

**Если нужен только быстрый OCR на VPS** — см. раздел 9 (копируете репозиторий и `data/` на VPS, поднимаете стек, ставите ingestion в очередь, по завершении забираете `ocr_raw/`, `ocr_normalized/` и/или дамп БД обратно на комп).

После этого проект на VPS будет работать по той же схеме, что и локально (в т.ч. по новому пайплайну OCR → файлы → нормализация → импорт в БД), если запускать ingestion уже с обновлённым кодом.
