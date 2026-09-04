# Рабочий процесс: OpenSpec

Проект ведётся по spec-driven процессу **OpenSpec**.

## Источники правды

- Поведение проекта: `openspec/specs/<capability>/spec.md` — **читать нужный
  spec перед реализацией/изменением**;
- Контекст и конвенции проекта: `openspec/config.yaml` (впрыскивается CLI при
  генерации артефактов);
- Подробное описание процесса: `docs/development.md`;
- Корневой `README.md` — обзор, запуск, установка.

## Ритуал разработки (каждый день/задача)

1. `/opsx:propose <описание задачи>` — планирование: proposal → specs → design
   → tasks (только планирование, код не пишем).
2. `/opsx:apply` — реализация задач по TDD (навык Superpowers
   `test-driven-development`), затем проверка.
3. `/opsx:archive` — архивация change и синхронизация основных спецификаций.

Полные пошаговые инструкции команд: `.clinerules/workflows/opsx-*.md`.

## Навыки Superpowers

- Индекс (всегда в контексте): `.clinerules/superpowers-zh.md`.
- Тела навыков: `.cline/skills/<skill>/SKILL.md` — **читать по требованию**, не
  копировать в правила (экономия контекста).
- Обязательные проверки перед «готово»: `verification-before-completion`,
  `test-driven-development`, `systematic-debugging`.

## Caveman

Caveman активен по умолчанию (правило `.clinerules/caveman.md`). Переключение:
`/caveman lite|full|ultra|off`. Код, коммиты и документация пишутся обычным
языком (не «кавеманом»).

## Проверки перед завершением

- Синтаксис Python: `python -m py_compile day1/deepseek_chat.py day2/app.py
  day3/app.py day5/app.py shared/deepseek_utils.py`
- Запуск Streamlit-приложений без API: `streamlit.testing.AppTest` (для day5 —
  интерпретатором `day5/.venv/Scripts/python`, там установлены streamlit и
  huggingface_hub)
- Валидация OpenSpec: `openspec validate --all`
- Секреты: `.env` не коммитить; при изменении ключей — обновить `.env.example`
