# Одна сборка: остановка → пересборка образов → запуск
.PHONY: rebuild
rebuild:
	docker compose down --remove-orphans
	docker compose build --no-cache
	docker compose up -d

# Запуск без пересборки (образы уже собраны)
.PHONY: up
up:
	docker compose up -d

# Остановка
.PHONY: down
down:
	docker compose down --remove-orphans
