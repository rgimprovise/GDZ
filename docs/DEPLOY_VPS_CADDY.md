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

**Если порты 5432 или 6379 на VPS уже заняты** (системный Postgres/Redis и т.п.), используйте файл с другими портами:

```bash
cd /opt/tutorbot/infra
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml up -d --build
docker-compose exec api alembic upgrade head
```

Файл `docker-compose.vps-ports.yml` пробрасывает Postgres на **5433**, Redis на **6380** (внутри сети контейнеры по-прежнему используют 5432 и 6379).

Если 5432 и 6379 свободны, можно без override:

```bash
docker-compose up -d --build
docker-compose exec api alembic upgrade head
```

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

### 2.2 На VPS: подтянуть код и перезапустить

Выполнять **на VPS** по SSH. Если у вас `docker-compose` (через дефис), замените `docker compose` на `docker-compose`:

```bash
cd /opt/tutorbot
git pull origin main
cd infra
docker-compose build --no-cache
docker-compose up -d
docker-compose exec api alembic upgrade head
```

Кратко в одну строку:

```bash
cd /opt/tutorbot && git pull origin main && cd infra && docker-compose build --no-cache && docker-compose up -d && docker-compose exec api alembic upgrade head
```

### 2.3 Скрипт обновления на VPS (опционально)

В репозитории есть скрипт `scripts/update_on_vps.sh`. На VPS один раз сделайте его исполняемым и запускайте при обновлении:

```bash
cd /opt/tutorbot
chmod +x scripts/update_on_vps.sh
./scripts/update_on_vps.sh
```

(Скрипт делает `git pull` и `docker compose build && up` в каталоге `infra`.)

---

## 3. Ошибка 502 (Bad Gateway)

Если страница не открывается с кодом 502, Caddy не может достучаться до API на localhost:8000. Проверьте **на VPS**:

```bash
cd /opt/tutorbot/infra

# 1. Все ли контейнеры запущены? (должны быть Up)
docker-compose -f docker-compose.yml -f docker-compose.vps-ports.yml ps -a

# 2. Логи API — нет ли падения при старте (--tail перед именем сервиса)
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

**Частые причины:**
- **Postgres или Redis в Exit 128** — тогда api/worker не стартуют. Проверьте логи postgres и redis (команды ниже), затем перезапустите стек.
- Запуск без override портов при занятых 5432/6379 — Postgres/Redis не поднимаются. Всегда используйте `-f docker-compose.vps-ports.yml` на этом VPS.

---

## 4. Полезные команды на VPS

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

## 5. Итог

| Действие              | Где      | Команда |
|-----------------------|----------|---------|
| Пуш изменений         | Локально | `git add -A && git commit -m "..." && git push origin main` |
| Обновить на VPS       | VPS      | `cd /opt/tutorbot && git pull && cd infra && docker-compose build --no-cache && docker-compose up -d && docker-compose exec api alembic upgrade head` |
| Открыть debug-панель | Браузер  | **https://gdz.n8nrgimprovise.space/debug** |
