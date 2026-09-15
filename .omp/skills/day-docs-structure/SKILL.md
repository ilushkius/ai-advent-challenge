---
name: day-docs-structure
description: "Documentation structure for each day in the ai-challenge project. Use this whenever finishing a new day (day13+), updating a day README.md, writing STRUCTURE.md, or recording changes in CHANGELOG.md. Triggers: finish day, update README, write STRUCTURE.md, update changelog, document day, day docs."
---

# Документация дня и проекта

## `README.md` дня

- Краткое описание дня (одна строка заголовком).
- Стек дня.
- Установка: `pip install -r requirements.txt` из папки дня (и создание `.venv`).
- Запуск: команды бэкенда и фронтенда в двух терминалах (из папки дня).
- Структура: ссылка на `STRUCTURE.md` дня.
- Примеры использования.

## `STRUCTURE.md` дня

- Список модулей дня и назначение каждого — в одну строку.
- Какие файлы импортируют `shared/`.
- Известные превышения лимита строк (и почему).
- Эталон: `day12/STRUCTURE.md`.

## `CHANGELOG.md` в корне проекта

- Записи о значимых изменениях структуры и документации проекта.
- Формат: дата, тип (`feat` / `refactor` / `docs` / `chore`), краткое описание,
  список затронутых файлов.

## Правила

- `README.md` дня и `docs/` внутри дня **не заменяют** `STRUCTURE.md`, и
  наоборот: README отвечает «что это и как запустить», `docs/` — «как устроено и
  как пользоваться», `STRUCTURE.md` — «где что лежит».
- При завершении дня обновить: `README.md` дня, `STRUCTURE.md` дня и запись в
  `CHANGELOG.md`.
