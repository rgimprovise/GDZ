# Отчёт проверки проекта перед пушем (план верификации)

Дата проверки: по результатам выполнения плана верификации.

---

## 1. Ссылки на перенесённые и удалённые скрипты ✅

- **Поиск:** Упоминания `scripts/process_all`, `scripts/assign_sections`, `scripts/link_theory`, `scripts/link_answers` встречаются только в CURSOR_REFACTOR_PLAN.md (контекст «move to legacy»), в docs — везде указаны `scripts/legacy/...` или каноничный пайплайн.
- **Файлы в scripts/:** В корне `scripts/` нет `process_all.py`, `assign_sections.py`, `link_theory.py`; они есть только в `scripts/legacy/`.
- **Исправлено:** В `docs/ROADMAP.md` строки 32–33 обновлены: «Привязка ответов/теории» — указаны `segmentation/answers` или `legacy/link_answers.py`, `legacy/link_theory.py`.

---

## 2. Импорты и зависимости worker/API ✅

- **apps/worker:** Импорты из `ocr_cleaner`, `ocr_files`, `formula_processor`, `llm_ocr_correct`, `document_map`, `segmentation/*`, `pipeline/*` — локальные (от корня worker), пути корректны.
- **apps/api:** Debug использует `PdfPage`, `image_minio_key`; путь к файлу — `Path(os.environ.get("DATA_DIR", "data")) / page.image_minio_key`, тот же базовый каталог, что и у worker.
- **scripts/legacy/process_all.py:** `_root = _here.parent.parent`, `sys.path.insert(0, _root / "apps" / "worker")`; classify подгружается из `_here.parent / "classify_problems.py"` (scripts/), assign_sections/link_answers/link_theory — из `_here / "*.py"` (legacy/). Соответствует структуре.

---

## 3. Конфигурация и окружение ✅

- **DATA_DIR:** В worker (`ocr_files.get_data_base()`), API (debug), `llm/structured.py` используется `os.environ.get("DATA_DIR", "data")`. В `infra/docker-compose.yml` для worker и api задано `DATA_DIR=/app/data`.
- **page_images:** Ключ вида `page_images/{book_id}/{pdf_source_id}/page_{n}.png`; разрешение в debug: `base / page.image_minio_key` — единообразно.
- **Дополнено:** В `infra/env.example` добавлен комментарий про DATA_DIR; в `docs/DEPLOY_VPS.md` и `docs/ARCHITECTURE.md` добавлены упоминания `page_images` и image_minio_key.

---

## 4. Документация vs код ✅

- **CURSOR_REFACTOR_PLAN.md:** Описание PR0–PR9 и файлов соответствует выполненным изменениям.
- **Пайплайн:** В PIPELINE_PDF, ARCHITECTURE, ROADMAP, AUDIT указана каноничная точка входа (`run_ingestion` / smoke_ingest) и legacy-скрипты в `scripts/legacy/`.
- **Debug:** Эндпоинт `/debug/api/page-image/{pdf_page_id}` описан в коде (docstring); в db-preview добавлена ссылка «картинка» на изображение страницы.

---

## 5. База данных и схема ✅

- **Схема:** Изменений схемы по плану до PR8 не предполагалось; поле `PdfPage.image_minio_key` уже было в миграциях и моделях (worker + api).
- **image_minio_key:** Везде трактуется как строка (относительный путь/ключ); формат `page_images/{book_id}/{pdf_source_id}/page_{n}.png` согласован в ocr_files.save_page_image и в debug API.

---

## 6. Дублирование и конфликты ✅

- **Сегментация задач:** Основная логика в `segmentation/problems.py` (`segment_problems`, `extract_problems_from_pages`); в ingestion при наличии doc_map вызывается `extract_problems_from_pages`, иначе — локальный `segment_problems`. Два пути явно разведены (doc_map vs fallback).
- **Ответы:** Основной путь — `segmentation/answers.py` + doc_map; legacy — только `scripts/legacy/link_answers.py`. Дублирования в основном коде нет.
- **Теория:** Основной путь — `segmentation/theory.py` + doc_map; legacy — `scripts/legacy/link_theory.py`. Конфликтов нет.

---

## 7. Тесты и дымовые проверки ✅

- **scripts/dev/test_segment_problems.py** — выполнен, OK (регрессия PR2: §/Параграф не являются началом задачи).
- **scripts/dev/test_strip_headers.py** — выполнен, OK (PR6: только верх/низ, нумерации сохранены).
- **scripts/dev/test_llm_gate.py** — выполнен, OK (gating без вызова API при высоких quality_scores).
- **smoke_ingest:** Требует БД и PDF; при наличии окружения рекомендуется один прогон перед пушем.

---

## 8. Лишние и устаревшие файлы ✅

- В **scripts/** нет файлов `process_all.py`, `assign_sections.py`, `link_theory.py` (только в `scripts/legacy/`).
- **scripts/legacy/README.md** актуален: перечислены link_answers, assign_sections, link_theory, process_all и каноничная замена (run_ingestion + smoke_ingest).
- Крупных закомментированных блоков «старого» кода без пометки не выявлено.
- Дубликатов плана рефакторинга в корне/docs не найдено.

---

## 9. Деплой и обновление приложения ✅

- **DEPLOY_VPS.md:** Добавлены `data/page_images` в список каталогов и в структуру данных; диск и структура обновлены.
- **ARCHITECTURE.md:** В описании DATA_DIR и Ingestion добавлены `page_images` и заполнение `image_minio_key`.
- Очередь ingestion по-прежнему вызывает `ingestion.process_pdf_source` (job_queue); каноничная точка входа `run_ingestion` делегирует в process_pdf_source для mode=full. Изменений в контракте деплоя не требуется.
- Том данных (DATA_DIR) общий для worker и api в docker-compose; каталог `data/page_images` создаётся при записи (save_page_image). Права на запись в DATA_DIR должны быть как и раньше.

---

## 10. Итоговый чеклист ✅

| Пункт | Статус |
|-------|--------|
| Нет ссылок на старые пути скриптов (кроме плана и legacy) | ✅ |
| Импорты и пути worker/API/scripts корректны | ✅ |
| DATA_DIR и путь к page_images единообразны | ✅ |
| Документация приведена в соответствие с кодом | ✅ |
| Схема БД и использование image_minio_key согласованы | ✅ |
| Нет дублирования логики сегментации/ответов/теории | ✅ |
| Тесты (segment_problems, strip_headers, llm_gate) пройдены | ✅ |
| В scripts/ нет удалённых скриптов; legacy/README актуален | ✅ |
| Деплой-документация обновлена (page_images, DATA_DIR) | ✅ |

---

**Вывод:** Проверка по плану выполнена. Проект готов к пушу на GitHub и обновлению приложения при условии однократного прогона smoke_ingest в целевом окружении (БД + PDF) по возможности.
