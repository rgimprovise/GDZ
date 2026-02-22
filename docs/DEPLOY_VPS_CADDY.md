# Деплой TutorBot на VPS (Ubuntu + Caddy)

Развёртывание через GitHub; на VPS уже работают Caddy и другие сервисы. Как поднять приложение, открыть debug-интерфейс и обновлять его при новых итерациях.

---

## 1. Первичная настройка на VPS (один раз)

### 1.1 Клонирование и окружение

На VPS обычно проще клонировать по **HTTPS** (не нужен SSH-ключ для GitHub):

```bash
# На VPS (root или ваш пользователь)
cd /opt
git clone https://github.com/rgimprovise/GDZ.git tutorbot
cd tutorbot/infra
cp env.example .env
nano .env   # POSTGRES_PASSWORD, BASE_URL (https://ваш-домен-для-tutorbot), TELEGRAM_*, OPENAI_* и т.д.
```

Если репозиторий **приватный**, после `git clone` по HTTPS при первом `git pull` Git запросит логин и пароль — укажите ваш GitHub **логин** и **Personal Access Token** (не пароль от аккаунта). Создать токен: GitHub → Settings → Developer settings → Personal access tokens.

Клонирование по SSH (`git@github.com:rgimprovise/GDZ.git`) возможно только если на VPS добавлен SSH-ключ в GitHub (Settings → SSH and GPG keys или Deploy key у репозитория).

**BASE_URL** укажите тот, по которому будет доступен API. Для текущего деплоя: `https://gdz.n8nrgimprovise.space`.

### 1.2 Данные (PDF)

Создайте каталог и при необходимости скопируйте туда PDF:

```bash
mkdir -p /opt/tutorbot/data/pdfs
# Если PDF уже есть на компе — с компа: rsync -avz ./data/ user@VPS_IP:/opt/tutorbot/data/
```

### 1.3 Caddy: проксирование на API

API в Docker слушает порт **8000** на хосте. Нужно проксировать ваш домен на `localhost:8000`.

**Вариант A:** отдельный файл конфига Caddy (рекомендуется)

Добавьте блок в ваш основной Caddyfile (рядом с остальными сайтами):

```bash
sudo nano /etc/caddy/Caddyfile
```

Вставьте блок (порт 8000 свободен; заняты у вас: 5678, 8083, 3001, 3002, 3003):

```
# TutorBot GDZ API
gdz.n8nrgimprovise.space {
    encode gzip
    reverse_proxy localhost:8000
}
```

Либо используйте готовый сниппет из репозитория: `cat /opt/tutorbot/infra/Caddyfile.snippet`.

Перезагрузите Caddy:

```bash
sudo systemctl reload caddy
```

**Вариант B:** использовать готовый сниппет из репозитория

```bash
# На VPS в корне репозитория
cat infra/Caddyfile.snippet
# Скопировать вывод, заменить tutorbot.example.com на ваш домен, добавить в ваш Caddyfile и reload caddy
```

### 1.4 Запуск приложения

**Если Docker Compose не установлен**, установите один из вариантов:

```bash
# Вариант 1: плагин Docker Compose v2 (рекомендуется, команда: docker compose)
sudo apt update
sudo apt install -y docker-compose-plugin

# Вариант 2: старый бинарник (команда: docker-compose)
# sudo apt install -y docker-compose
```

Проверка: `docker compose version` или `docker-compose version`.

**Если порты 5432 или 6379 на VPS уже заняты** (системный Postgres/Redis и т.п.), используйте файл с другими портами. **Важно:** сначала остановите и удалите контейнеры, затем подтяните код и поднимите стек заново — иначе старые контейнеры остаются с привязкой к 5432/6379:

```bash
cd /opt/tutorbot/infra
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml down
cd /opt/tutorbot && git pull && cd infra
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d --build
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml exec api alembic upgrade head
```

Файл `docker-compose.vps-ports.yml` пробрасывает Postgres на **5433**, Redis на **6380** (внутри сети контейнеры по-прежнему используют 5432 и 6379). На VPS используйте только `-f docker-compose.vps-ports.yml` (файла с портами 5432/6379 в репозитории нет).

Локально (если 5432/6379 свободны): `docker-compose -f docker-compose.yml -f docker-compose.local-ports.yml up -d --build`

Проверка:

```bash
curl -s http://localhost:8000/health
curl -s https://gdz.n8nrgimprovise.space/health   # через Caddy
```

### 1.5 Debug-интерфейс

После настройки Caddy debug-панель доступна по адресу:

- **https://gdz.n8nrgimprovise.space/debug**
- **https://gdz.n8nrgimprovise.space/docs** — Swagger
- **https://gdz.n8nrgimprovise.space/health** — проверка работы API

В debug-панели доступны:
- **Загрузить новый учебник** — загрузка PDF через веб; файл сохраняется в `data/pdfs/`, создаётся книга и источник PDF (по имени файла — предмет/класс). Если при загрузке появляется ошибка «relation "books" does not exist» — сначала примените миграции (команда ниже).
- **Источники PDF — начать OCR** — кнопка «Начать OCR» ставит в очередь пайплайн: EasyOCR + Tesseract → md/txt → нормализация (OpenAI) → распределение в БД (OpenAI). Worker должен быть запущен.

**После первого подъёма или после `down -v` обязательно выполните миграции:**
```bash
cd /opt/tutorbot/infra
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml exec api alembic upgrade head
```

---

## 2. Обновление приложения на каждой итерации

После того как в репозитории на GitHub появились новые изменения.

### 2.1 У вас (локально): отправить изменения в GitHub

```bash
cd /path/to/GDZ
git add -A
git status
git commit -m "Описание изменений"
git push origin main
```

(Вместо `main` подставьте вашу ветку, если другая.)

### 2.2 На VPS: одна команда для обновления

После пуша изменений на GitHub на VPS достаточно **одной команды**. Данные (БД, загруженные PDF, OCR-файлы) **не удаляются** — скрипт только подтягивает код, пересобирает образы, поднимает контейнеры и применяет миграции.

**Один раз** сделайте скрипт исполняемым (если ещё не делали):

```bash
chmod +x /opt/tutorbot/scripts/update_on_vps.sh
```

**При каждом обновлении** (после `git push` с локальной машины):

```bash
cd /opt/tutorbot && ./scripts/update_on_vps.sh
```

Скрипт сам:
- выполняет `git pull origin main`;
- подставляет `docker-compose.vps-ports.yml` (порты 5433/6380), если файл есть;
- останавливает контейнеры (`down` **без** `-v` — данные и volumes не удаляются);
- собирает образы и запускает контейнеры (`build --no-cache` и `up -d`);
- применяет миграции БД (`alembic upgrade head`).

Такой порядок (сначала `down`, затем `up -d`) избегает ошибки `KeyError: 'ContainerConfig'` у старого docker-compose при пересоздании контейнеров.

Опционально: `SKIP_PULL=1 ./scripts/update_on_vps.sh` — не делать `git pull` (например, уже подтянули вручную). `BRANCH=develop` — другая ветка.

Если при pull появляется «Your local changes would be overwritten», скрипт сам сбросит изменения в **отслеживаемых** файлах (`git checkout -- .`) и повторит pull. Неотслеживаемые файлы (например `.env`) не трогаются. Если на VPS вы вручную правили код и хотите сохранить правки — перед запуском скрипта сделайте `git stash`.

---

## 3. Ошибка 502 (Bad Gateway)

Если страница не открывается с кодом 502, Caddy не может достучаться до API на localhost:8000. Проверьте **на VPS**:

```bash
cd /opt/tutorbot/infra

# 1. Все ли контейнеры запущены? (должны быть Up)
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml ps -a
```

**Если при `up -d` падает с `KeyError: 'ContainerConfig'`** (часто после добавления volume к api) — баг старого docker-compose при «recreate». Снести контейнеры и поднять заново:

```bash
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml down
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml ps -a
```

Проверка:

```bash
# 2. Логи API — нет ли падения при старте
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml logs --tail 100 api

# 3. Слушает ли что-то на порту 8000
ss -tlnp | grep 8000
curl -s http://127.0.0.1:8000/health
```

Если **Postgres или Redis в Exit 128**, смотрите их логи:

```bash
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml logs postgres
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml logs redis
```

Часто помогает: снести контейнеры и поднять заново (volumes сохраняются):

```bash
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml down
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml ps -a
```

Если логи postgres/redis **пустые** и контейнеры снова Exit 128 — часто виноваты **права на volume**. Тогда снести и контейнеры, и volumes (БД будет пустая) и поднять заново:

```bash
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml down -v
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d
# затем: docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml exec api alembic upgrade head
```

Если после этого postgres/redis **всё ещё Exit 128**, запустите их в foreground — в консоли появится текст ошибки (затем Ctrl+C):

```bash
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml run --rm postgres
# или
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml run --rm redis
```

Если при `run --rm` оба сервиса стартуют без ошибок — образы и конфиг в порядке; однократный `run --rm postgres` уже инициализирует volume. Тогда снова поднимите стек и проверьте статус:

```bash
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml ps -a
```

Если при `up -d` снова Exit 128 — проверьте, не заняты ли порты на хосте: `ss -tlnp | grep -E '5433|6380'`. Затем запустите стек в foreground (без `-d`), чтобы увидеть вывод всех сервисов при старте: `docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up`.

**Redis:** предупреждение про `vm.overcommit_memory` можно убрать на VPS: `sudo sysctl vm.overcommit_memory=1` (постоянно: добавить в `/etc/sysctl.conf` и перезагрузка).

**Частые причины:**
- **Postgres или Redis в Exit 128** — тогда api/worker не стартуют. Проверьте логи postgres и redis (команды ниже), затем перезапустите стек.
- **"address already in use" для 5432/6379** — порты задаются только в `docker-compose.vps-ports.yml` (5433, 6380). Сначала выполните `down`, затем `git pull`, затем `up -d` — иначе старые контейнеры продолжают использовать 5432/6379.

---

## 4. Проверка PDF на VPS

Данные (в т.ч. PDF) монтируются в контейнер из каталога **`/opt/tutorbot/data`** (путь `../data` относительно `infra/`). PDF должны лежать в `data/pdfs/`.

**Проверить наличие PDF на VPS:**

```bash
# Список файлов в каталоге PDF
ls -la /opt/tutorbot/data/pdfs

# Все PDF в data (включая вложенные папки)
find /opt/tutorbot/data -name "*.pdf"

# Есть ли каталог data и подкаталог pdfs
ls -la /opt/tutorbot/data
ls -la /opt/tutorbot/data/pdfs 2>/dev/null || echo "Каталог pdfs отсутствует"
```

Если каталога нет: `mkdir -p /opt/tutorbot/data/pdfs`. Скопировать PDF с локальной машины: `rsync -avz ./data/ user@VPS_IP:/opt/tutorbot/data/`.

---

## 5. Debug-панель «в состоянии подгрузки»

Если страница **https://gdz.n8nrgimprovise.space/debug** открывается, но блоки «Книг», «Задач», «Книги в базе» и т.д. остаются скелетонами (серые полоски), значит запросы HTMX к `/debug/api/*` не доходят или API возвращает ошибку.

**Проверка на VPS:**

```bash
cd /opt/tutorbot/infra

# Ответ API по статистике и книгам (должен быть HTML, не 500)
curl -s -o /dev/null -w "%{http_code}" https://gdz.n8nrgimprovise.space/debug/api/stats
curl -s https://gdz.n8nrgimprovise.space/debug/api/stats | head -5
curl -s https://gdz.n8nrgimprovise.space/debug/api/books | head -5

# Логи API — ошибки при запросе к БД (нет таблиц, нет подключения)
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml logs --tail 50 api
```

**Частые причины:**
- **Миграции не применены** — таблиц `books`, `problems`, `pdf_pages` нет, API падает с 500. Выполните:  
  `docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml exec api alembic upgrade head`
- **БД пустая** — после миграций панель покажет нули и «Книги не найдены»; это нормально, пока не добавлены книги и PDF (seed_books, загрузка PDF в `data/pdfs/`, ingestion).

---

## 6. Полезные команды на VPS

```bash
cd /opt/tutorbot/infra

# Логи (с override портов)
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml logs -f api
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml logs -f worker

# Статус
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml ps

# Остановить / запустить снова
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml down
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d
```

---

## 7. Итог

| Действие              | Где      | Команда |
|-----------------------|----------|---------|
| Пуш изменений         | Локально | `git add -A && git commit -m "..." && git push origin main` |
| Обновить на VPS       | VPS      | `cd /opt/tutorbot && ./scripts/update_on_vps.sh` |
| Открыть debug-панель | Браузер  | **https://gdz.n8nrgimprovise.space/debug** |
