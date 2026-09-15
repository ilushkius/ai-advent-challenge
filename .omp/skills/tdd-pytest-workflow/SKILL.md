---
name: tdd-pytest-workflow
description: "Test-Driven Development workflow with pytest for the ai-challenge project. Use this whenever adding new logic to day13+ (state machines, memory layers, context strategies, profiles, API endpoints), when writing tests for a new feature, or when the user asks for tests, TDD, pytest or coverage. Triggers: add tests, write test, TDD, pytest, test-driven, negative scenario, parametrize, coverage, new feature needs tests."
---

# TDD и `pytest` в проекте

## Процесс

1. **RED** — сначала падающий тест: он фиксирует контракт до реализации.
2. **GREEN** — минимальная реализация до зелёного.
3. **REFACTOR** — чистка кода при зелёных тестах.

## Где лежат тесты

- `tests/` в папке дня (`day9/tests/`, `day10/tests/`, `day11/tests/`,
  `day12/tests/`), файлы `test_*.py`.
- Запуск — **из папки дня** (CWD важен: `.env` ищется здесь):

```powershell
.venv\Scripts\python -m pytest -q
```

- `pytest.ini` дня задаёт `testpaths = tests` и `pythonpath = . tests`, поэтому
  тесты импортируют модули дня как `from backend.agent import Agent`.
- Офлайн-обязательность: тесты не ходят в сеть — клиент DeepSeek подменяется
  фейком, база — временная SQLite (эталон: `day12/tests/support.py`).

## Обязательные требования

- **Параметризованные тесты для таблиц переходов:** `@pytest.mark.parametrize`
  перебирает пары (состояние, событие) → ожидаемое состояние.
- **Хотя бы один негативный сценарий:** недопустимое событие → исключение (вроде
  `UnknownContextEvent`).
- **Состояние, которое должно переживать рестарт, проверяется тестом на
  восстановление из БД**, а не добавлением отдельного поля состояния в БД.

## Эталоны

- `day9/tests/` — 167 тестов: FSM, политика сжатия, хранилище, компрессор, агент, API.
- `day10/tests/` — 193 теста: стратегии, факты, ветки, FSM, хранилище, API.
- `day11/tests/` — 235 тестов: слои памяти, `/memory/...`, стратегии, факты, ветки.
- `day12/tests/` — 314 тестов: персонализация (профили, промпт, `/users...`) плюс всё из дня 11.

FSM-специфичные тесты (переходы, неизвестное событие, отделение FSM от
транспорта) — см. скилл `python-fsm-agent`.
