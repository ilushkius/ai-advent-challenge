---
name: day-docs-structure
description: "Documentation structure for each day in the ai-challenge project. Use this whenever finishing a new day (day13+), updating a day README.md, writing STRUCTURE.md, or recording changes in CHANGELOG.md. Triggers: finish day, update README, write STRUCTURE.md, update changelog, document day, day docs."
---

# Документация дня и проекта

## `README.md` дня

- Краткое описание дня (одна строка заголовком).
- Стек дня.
- Установка: `uv sync` из папки дня (зависимости — `pyproject.toml` + `uv.lock`,
  версия Python — `.python-version`; снимки `day1`–`day12` остаются на
  `pip install -r requirements.txt`).
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
- **Перед коммитом проверить, что файлы кода не попали в игнор.** Широкие правила
  в корневом `.gitignore` (`models/`, `lib/`, `logs/`, `*.txt`, `*.jsonl`)
  матчатся на любой глубине и вырезают исходники **молча**: `git add` для
  игнорируемого пути — no-op, а в `git status` такие файлы не видны, поэтому
  пропажа не находится ни ревью, ни тестами в рабочем дереве.

  ```bash
  git ls-files --others --ignored --exclude-standard | grep -E '\.py$' \
    | grep -vE '(\.venv/|__pycache__/|site-packages/)'
  ```

  Пустой вывод = потерь нет. **Нужен именно `git ls-files --others --ignored`**,
  а не `git status --ignored`: последний сворачивает игнорируемую папку в одну
  строку `!! dayN/backend/models/` и файлы внутри не показывает, поэтому таким
  грепом баг не находится (проверено на состоянии до фикса `f6b7ed8`: 0 находок
  против 5 у команды выше).

  Так был найден `day12/backend/models/` — пакет Pydantic-схем, вырезанный
  правилом `models/`; фикс — `!day*/backend/models/*.py` в `.gitignore`
  (коммит `4cfee38`).
