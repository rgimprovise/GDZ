# Деплой TutorBot на VPS (Ubuntu + Caddy)

Развёртывание через GitHub; на VPS уже работают Caddy и другие сервисы. Как поднять приложение, открыть debug-интерфейс и обновлять его при новых итерациях.

---

## 1. Первичная настройка на VPS (один раз)

### 1.1 Клонирование и окружение

```bash
# На VPS (под вашим пользователем или в /opt)
cd /opt   # или ваш каталог для приложений
git clone https://github.com/YOUR_USER/GDZ.git tutorbot
cd tutorbot/infra
cp env.example .env
nano .env   # POSTGRES_PASSWORD, BASE_URL (https://ваш-домен-для-tutorbot), TELEGRAM_*, OPENAI_* и т.д.
```

**BASE_URL** укажите тот, по которому будет доступен API (например `https://tutorbot.yourdomain.com`).

### 1.2 Данные (PDF)

Создайте каталог и при необходимости скопируйте туда PDF:

```bash
mkdir -p /opt/tutorbot/data/pdfs
# Если PDF уже есть на компе — с компа: rsync -avz ./data/ user@VPS_IP:/opt/tutorbot/data/
```

### 1.3 Caddy: проксирование на API

API в Docker слушает порт **8000** на хосте. Нужно проксировать ваш домен на `localhost:8000`.

**Вариант A:** отдельный файл конфига Caddy (рекомендуется)

Создайте файл (путь может отличаться в зависимости от вашей установки Caddy):

```bash
sudo nano /etc/caddy/conf.d/tutorbot.conf
```

Содержимое (подставьте свой домен):

```
tutorbot.yourdomain.com {
    reverse_proxy localhost:8000
}
```

Или если Caddy читает один Caddyfile:

```bash
sudo nano /etc/caddy/Caddyfile
```

Добавьте блок (можно в конец):

```
tutorbot.yourdomain.com {
    reverse_proxy localhost:8000
}
```

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

```bash
cd /opt/tutorbot/infra
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Проверка:

```bash
curl -s http://localhost:8000/health
curl -s https://tutorbot.yourdomain.com/health   # через Caddy
```

### 1.5 Debug-интерфейс

После настройки Caddy debug-панель доступна по адресу:

- **https://ваш-домен-для-tutorbot/debug**

Например: `https://tutorbot.yourdomain.com/debug`

Там же:
- **/docs** — Swagger
- **/health** — проверка работы API

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

Выполнять **на VPS** по SSH:

```bash
cd /opt/tutorbot
git pull origin main
cd infra
docker compose build --no-cache
docker compose up -d
docker compose exec api alembic upgrade head
```

Кратко в одну строку (подставьте ветку при необходимости):

```bash
cd /opt/tutorbot && git pull origin main && cd infra && docker compose build --no-cache && docker compose up -d && docker compose exec api alembic upgrade head
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

## 3. Полезные команды на VPS

```bash
cd /opt/tutorbot/infra

# Логи
docker compose logs -f api
docker compose logs -f worker

# Статус
docker compose ps

# Остановить
docker compose down

# Запустить снова
docker compose up -d
```

---

## 4. Итог

| Действие              | Где      | Команда |
|-----------------------|----------|---------|
| Пуш изменений         | Локально | `git add -A && git commit -m "..." && git push origin main` |
| Обновить на VPS       | VPS      | `cd /opt/tutorbot && git pull && cd infra && docker compose build --no-cache && docker compose up -d && docker compose exec api alembic upgrade head` |
| Открыть debug-панель | Браузер  | **https://ваш-домен-для-tutorbot/debug** |
