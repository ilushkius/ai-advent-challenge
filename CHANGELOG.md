# История изменений

Формат записи: **дата — тип — краткое описание**, затем список затронутых
файлов и папок. Типы: `feat` (новая функциональность), `refactor` (изменение
структуры кода), `docs` (документация), `rules` (правила для агента и процесса),
`chore` (прочее: инфраструктура, скиллы, служебные изменения).

## 2026-09-16 — chore — процедурные правила вынесены в скиллы omp.sh

Создана система проектных скиллов в `.omp/skills/`; `AGENTS.md` сокращён —
дублирующиеся разделы заменены ссылками на скиллы. Скиллы:
`python-fsm-agent` (правила FSM, вынесены из `AGENTS.md`; отдельного файла скилла
до этого не существовало), `fastapi-streamlit-day-structure` (раскладка файлов
дня и лимиты 400/100/80 строк), `shared-modules-usage` (работа с `shared/` и его
подключение), `tdd-pytest-workflow` (TDD и `pytest`), `day-docs-structure`
(README/STRUCTURE/CHANGELOG дня). Видимость скиллов проверена запуском omp.sh:
свежая сессия видит все пять, `skill://<name>` отдаёт тело.

**Затронуто:** `.omp/skills/python-fsm-agent/SKILL.md`,
`.omp/skills/fastapi-streamlit-day-structure/SKILL.md`,
`.omp/skills/shared-modules-usage/SKILL.md`,
`.omp/skills/tdd-pytest-workflow/SKILL.md`,
`.omp/skills/day-docs-structure/SKILL.md` (новые), `AGENTS.md`, `README.md`,
`CHANGELOG.md`. Код в `dayN/` и `.clauderules` не менялись.

## 2026-09-15 — docs — документация приведена в соответствие с рефакторингом дня 12

Описана модульная структура дня 12 и общий пакет `shared/`: разделы про
структуру проекта, правила разработки и общие модули в корневом README, новые
`docs/architecture.md` и `docs/usage.md`, карта модулей дня 12, исправлены
ссылки на монолитные `backend/models.py` и `backend/main.py` в документации дня.

**Затронуто:** `README.md`, `docs/architecture.md` (новый), `docs/usage.md`
(новый), `CHANGELOG.md` (новый), `day12/STRUCTURE.md` (новый),
`day12/README.md`, `day12/docs/architecture.md`, `day12/docs/usage.md`,
`day12/docs/api.md`, `AGENTS.md`. Код в `dayN/` не менялся.

## 2026-09-15 — rules — правила структуры файлов и модулей в `AGENTS.md`

В `AGENTS.md` добавлены разделы «Структура файлов» (лимит 400 строк на `.py`,
`app.py` ≤ 100, `backend/main.py` ≤ 80, раскладка `ui/` · `backend/routers/` ·
`backend/models/` · `backend/schemas/` · `shared/`), «Запрещено», «Обязательно»
(`STRUCTURE.md` дня, Plan Mode, проверка лимитов) и «Известные расхождения со
снимками»; в `Definition of Done` — два пункта про лимиты и `STRUCTURE.md`.

**Затронуто:** `AGENTS.md` (коммит `024e6a7`). Существующие правила не
изменялись — только дополнены.

## 2026-09-15 — refactor — модульная структура дня 12 и общий пакет `shared/`

Приложение дня 12 разложено по модулям, общий код вынесен в `shared/`:

* `app.py` — 1852 строки → 40 (только точка входа); интерфейс вынесен в пакет
  `ui/` из 8 модулей по секциям: `api_client`, `common`, `sidebar`,
  `chat_section`, `context_panels`, `memory_panels`, `profile_section`,
  `profile_comparison`.
* `backend/main.py` — 660 строк → 84 (только сборка `app` и `include_router`);
  эндпоинты разложены по роутерам `backend/routers/` (`agents`, `context`,
  `memory`, `profiles` — 36 эндпоинтов), зависимости API-слоя — в
  `backend/dependencies.py`.
* `backend/models.py` (845 строк) → пакет `backend/models/` с Pydantic-схемами по
  доменам (`agent`, `context`, `memory`, `profile`) и реэкспортом из
  `models/__init__.py`; ORM-таблицы вынесены в `backend/tables.py`, а
  `backend/database.py` стал тонким слоем над `shared/db_base.py`.
* `backend/agent_manager.py` — 637 строк → 71 (синглтон); методы разложены по
  миксинам `backend/manager_agents.py`, `manager_context.py`, `manager_memory.py`,
  `manager_profiles.py`, `manager_usage.py`.
* `backend/profiles.py` — 343 строки → 204, значения профиля вынесены в
  `backend/profile_values.py`; `backend/memory.py` дополнен
  `backend/memory_layers.py`; отчётные скрипты — `comparison_report.py`,
  `comparison_stub.py`, `personalization_comparison.py` (364 → 108 строк).
* Создан общий пакет `shared/` с кодом, не меняющимся между днями:
  `deepseek_client.py`, `db_base.py`, `token_counter.py`, `logging_utils.py`
  (`deepseek_utils.py` существовал ранее).

**Затронуто:** `day12/app.py`, `day12/ui/**` (новый), `day12/backend/**`
(`main.py`, `dependencies.py` (новый), `routers/**` (новый), `models/**`
(новый), `tables.py` (новый), `manager_*.py` (новые), `database.py`,
`agent_manager.py`, `agent.py`, `config.py`, `memory.py`, `memory_layers.py`,
`profiles.py`, `profile_values.py`, `models.py` (удалён — заменён пакетом),
`day12/comparison_report.py`, `day12/comparison_stub.py`,
`day12/personalization_comparison.py`), `shared/db_base.py`,
`shared/deepseek_client.py`, `shared/token_counter.py`,
`shared/logging_utils.py` (коммит `9c7021c`, 40 файлов).
