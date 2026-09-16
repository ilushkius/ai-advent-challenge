# Архитектура проекта

Документ описывает **междневные** слои репозитория: общий пакет
[`shared/`](../shared/), политику папок `dayN/` и модульную раскладку активного
дня 13. Устройство конкретного дня — в `docs/` внутри его папки (день 13:
[`../day13/docs/architecture.md`](../day13/docs/architecture.md)); карта модулей
дня — [`../day13/STRUCTURE.md`](../day13/STRUCTURE.md).

## Политика папок: снимки и активная разработка

| Папка | Статус | Что это значит |
|---|---|---|
| `day1/`–`day12/` | **снимки** | код сдан и не изменяется; правка — только по прямому запросу пользователя |
| `day13/` | **активная разработка** | здесь применяются правила структуры из [`AGENTS.md`](../AGENTS.md) |
| `shared/` | общий пакет | код, не меняющийся между днями; дни импортируют его, а не копируют |

## Модульная структура

Модульная раскладка пришла в день 13 из дня 12: до рефакторинга (коммит
`9c7021c`, 2026-09-15) приложение дня было набором крупных файлов
(`day12/app.py` — 1852 строки, `backend/main.py` — 660,
`backend/agent_manager.py` — 637, `backend/models.py` — 845,
`backend/database.py` — 425, `backend/profiles.py` — 343). Логика интерфейса,
эндпоинты, схемы и ORM лежали в одном слое, а общий код дублировался по дням.
Затем день 13 разложен по слоям: у каждого слоя своя папка, файл лежит в папке
**своего** слоя, корень `backend/` пуст (только `__init__.py`).

**Сейчас архитектура дня 13 — слоистая**: интерфейс разложен по секциям
(`frontend/`), FastAPI — по доменам (`backend/api/`), Pydantic-схемы — в
`backend/schemas/`, ORM — по доменам в `backend/models/*.py`, чистые правила —
в `backend/domain/`, доступ к БД — в `backend/storage/`, прикладные сервисы — в
`backend/services/`, агент и его менеджер — в `backend/agents/`, настройки —
в `backend/core/`, а междневный код — в `shared/`.

```mermaid
flowchart TB
    subgraph L1["Слой интерфейса (Streamlit, порт 8501)"]
        APP["app.py — точка входа (45 строк)"]
        UI["frontend/ — sidebar, chat_section, context_panels,<br/>memory_panels, profile_section, profile_comparison,<br/>task_panel, common, api_client"]
        APP --> UI
    end
    subgraph L2["API-слой (FastAPI, порт 8000)"]
        MAIN["backend/api/main.py — сборка app (80 строк)"]
        ROUTERS["backend/api/ — agents, context,<br/>memory, profiles, tasks"]
        DEPS["backend/core/dependencies.py"]
        MAIN --> ROUTERS --> DEPS
    end
    subgraph L3["Слои домена дня 13"]
        AG["backend/agents/ — agent, memory,<br/>profile_store, agent_manager + manager_*"]
        SV["backend/services/ — compressor, task_state"]
        DOM["backend/domain/ — strategies, task_fsm, task_prompt,<br/>task_intent, context_fsm, context_policy, fact_extractor,<br/>memory_layers, profiles, profile_values, demo_profiles"]
        SCH["backend/schemas/ — схемы API по доменам"]
        CFG["backend/core/config.py"]
    end
    subgraph L4["Данные"]
        ST["backend/storage/ — database, task_store, memory_rows"]
        TAB["backend/models/*.py — ORM-таблицы по доменам"]
        DB[("SQLite<br/>day13/agents.db")]
        ST --> TAB --> DB
    end
    subgraph L5["shared/ — общий код дней"]
        SH["deepseek_utils, deepseek_client,<br/>db_base, token_counter, logging_utils"]
    end
    UI -->|HTTP / requests| ROUTERS
    DEPS --> AG
    AG --> DOM
    AG --> SV
    AG --> ST
    AG --> SCH
    AG --> SH
    SV --> ST
    SV --> DOM
    CFG --> SH
    MAIN --> DB
```

### `day13/frontend/` — Streamlit UI, разбитый по секциям

| Модуль | Строк | Зона ответственности |
|---|---|---|
| `frontend/__init__.py` | 6 | Описание пакета; ни один модуль не выполняет `st.*` на импорте |
| `frontend/api_client.py` | 327 | HTTP-транспорт к бэкенду: `requests`, `BACKEND_URL` (переопределяется `DAY13_BACKEND_URL`), ошибка `BackendError`; функции состояния задачи (`api_*_task*`); не зависит от Streamlit и pandas |
| `frontend/common.py` | 190 | Подписи (включая `TASK_STAGE_LABELS`), форматтеры, `st.session_state`: инициализация, флеш-сообщения, список агентов и активный агент |
| `frontend/sidebar.py` | 191 | Боковая панель: список агентов, создание агента, стратегия, задача и сессия (`render_sidebar()`) |
| `frontend/chat_section.py` | 260 | Основная область: переключатель трёх разделов («💬 Чат и память», «👤 Профиль пользователя», «🧭 Состояние задачи») и сборка страницы (`render_main_area()`) |
| `frontend/context_panels.py` | 324 | Панели контекста: токены диалога, сжатие, сравнение режимов, ветки, факты |
| `frontend/memory_panels.py` | 229 | Панели трёх слоёв памяти и индикатор «что ушло в последний запрос» |
| `frontend/profile_section.py` | 322 | Раздел «👤 Профиль пользователя»: CRUD профилей, предпросмотр блока промпта, сравнение |
| `frontend/profile_comparison.py` | 129 | Сравнение двух профилей на одном вопросе через временных агентов |
| `frontend/task_panel.py` | 200 | Раздел «🧭 Состояние задачи»: этап, шаг, ожидаемое действие, ASCII-схема FSM, пять кнопок, журнал переходов |

Точка входа `day13/app.py` (45 строк) не содержит логики панелей: он вызывает
`common.init_state()`, `sidebar.render_sidebar()`, `chat_section.render_main_area()`.
Прогоны демонстраций и сборка отчётов — в `day13/scripts/`, отчёты — в
`day13/docs/reports/`.

### `day13/backend/api/` — FastAPI-роутеры по доменам

| Роутер | Строк | Эндпоинтов | Домен |
|---|---|---|---|
| `api/agents.py` | 253 | 11 | CRUD агентов, генерация, диалог, статистика токенов |
| `api/context.py` | 140 | 9 | Сжатие истории, стратегии, ветки, факты |
| `api/memory.py` | 180 | 10 | Три слоя памяти: `/memory/short-term`, `/memory/working`, `/memory/long-term`, сессия и задача |
| `api/profiles.py` | 126 | 6 | Профили пользователей (`/users...`) и `GET /agents/{id}/profile` |
| `api/tasks.py` | 183 | 9 | Состояние задачи: создание и список (`/agents/{id}/tasks`), чтение, журнал, пауза, продолжение, шаг, откат, переход |
| `api/main.py` | 80 | — | Сборка `app`: `lifespan` (создание таблиц + восстановление агентов), CORS, `include_router` |

Всего — **45 эндпоинтов** (36 унаследованных от дня 12 + 9 новых). Пути внутри
роутеров абсолютные (`/agents/...`), префиксы не используются; подключение — в
`api/main.py` (`app.include_router(...)`). Доступ к менеджеру агентов,
обработка «агента нет» (404) и «задачи нет» (404) — в
`backend/core/dependencies.py` (`get_manager`, `agent_or_404`, `task_or_404`),
поэтому тесты подменяют одну точку (`main.get_manager`). Недопустимый переход
состояния задачи (`InvalidTaskTransition`/`UnknownTaskEvent`) роутер отдаёт
кодом 400, повторный `task_id` (`TaskExistsError`) — 409.

### `day13/backend/schemas/` — схемы API по доменам

| Модуль | Строк | Домен |
|---|---|---|
| `schemas/agent.py` | 319 | Конфигурация/патч агента, тела и ответы генерации (включая поле `task_state`), метрики токенов |
| `schemas/context.py` | 218 | Сжатие истории, стратегии, ветки, факты |
| `schemas/memory.py` | 173 | Три слоя памяти агента |
| `schemas/profile.py` | 170 | Профиль пользователя и его вклад в промпт |
| `schemas/task.py` | 122 | Состояние задачи: этап, шаг, ожидаемое действие, переходы, журнал |
| `schemas/__init__.py` | 138 | Реэкспорт всех схем — остальной код импортирует их из `backend.schemas` |

### `day13/backend/models/` — ORM-таблицы по доменам

| Модуль | Строк | Таблицы |
|---|---|---|
| `models/agent.py` | 93 | `agents` (`AgentRecord`) и его `relationship`-связи |
| `models/message.py` | 41 | `short_term_messages` (`ShortTermMessage`) |
| `models/memory.py` | 81 | `working_memory`, `long_term_memory` |
| `models/context.py` | 157 | `summaries`, `token_usage`, `facts`, `checkpoints` |
| `models/user_profile.py` | 57 | `user_profiles` (`UserProfile`) |
| `models/task_state.py` | 102 | `task_states` (`TaskState`), `task_transitions` (`TaskTransition`) |
| `models/__init__.py` | 43 | Реэкспорт ORM-классов (импорт — из `backend.storage.database`) |

Это **целевая раскладка** `AGENTS.md`: Pydantic-схемы — `schemas/`, ORM —
`models/`. Движок и фабрику сессий создаёт `backend/storage/database.py`
помощниками `shared/db_base.py` и он же реэкспортирует ORM-классы, поэтому
остальной код импортирует таблицы из `backend.storage.database`.

### Остальные модули дня 13

| Модуль | Строк | Слой | Назначение |
|---|---|---|---|
| `backend/core/config.py` | 156 | core | URL и модели DeepSeek, дефолты агента, лимиты и цены, настройки сжатия/стратегий/памяти/профиля, границы полей состояния задачи, путь к `day13/agents.db` и `.env` |
| `backend/core/dependencies.py` | 41 | core | Зависимости API-слоя: `get_manager`, `agent_or_404`, `task_or_404` |
| `backend/domain/strategies.py` | 62 | domain | `Enum Strategy` (`sliding_window` / `sticky_facts` / `branching` / `summary`) и проверка значения |
| `backend/domain/context_fsm.py` | 256 | domain | Стейт-машина сжатия: `Enum` + паттерн State (цель `AGENTS.md`) |
| `backend/domain/context_policy.py` | 173 | domain | Чистая арифметика «когда сжимать и что оставить» |
| `backend/domain/fact_extractor.py` | 96 | domain | Эвристика извлечения фактов «ключ → значение» |
| `backend/domain/memory_layers.py` | 105 | domain | Категории и тексты блоков слоёв памяти (без ORM) |
| `backend/domain/profile_values.py` | 335 | domain | Перечисления и нормализация значений профиля |
| `backend/domain/profiles.py` | 204 | domain | Сборка блока персонализации для системного промпта |
| `backend/domain/demo_profiles.py` | 107 | domain | Демонстрационные профили для UI и отчёта |
| `backend/domain/task_fsm.py` | 387 | domain | Стейт-машина состояния задачи: `TaskStage`/`TaskStep`/`TaskEvent`, классы-этапы с `handle(event, step)`, таблицы `STAGE_STEPS`/`STAGE_TRANSITIONS` (цель `AGENTS.md`) |
| `backend/domain/task_prompt.py` | 174 | domain | Тексты блока состояния для системного промпта: ожидаемые действия, завершённые этапы, `render_task_state_block` |
| `backend/domain/task_intent.py` | 89 | domain | Распознавание намерения в реплике (`пауза` / `продолжи` / `откат` / `подтверждаю`) по таблице фраз с приоритетом групп |
| `backend/storage/database.py` | 44 | storage | Движок и фабрика сессий + реэкспорт ORM-классов и `Base` |
| `backend/storage/task_store.py` | 217 | storage | `TaskStateStore` — единственное место работы с таблицами `task_states`/`task_transitions` (чтение, журнал, запись перехода) |
| `backend/storage/memory_rows.py` | 47 | storage | ORM-строки слоёв памяти → словари API/UI |
| `backend/services/compressor.py` | 329 | services | `ContextCompressor`: план сжатия, суммаризация, запись конспекта |
| `backend/services/task_state.py` | 268 | services | `TaskStateMachine`: публичный контракт переходов (`create`/`pause`/`resume`/`advance`/`rollback`/`transition_to`) и валидация |
| `backend/agents/agent.py` | 1603 | agents | `Agent`: память, токены, `prepare_context`, стратегии, факты, ветки, профиль, состояние задачи (`task_state`, `task_state_block`, `apply_task_intent`) (⚠️ превышает лимит 400 строк) |
| `backend/agents/memory.py` | 291 | agents | `MemoryManager`: хранение трёх слоёв памяти |
| `backend/agents/profile_store.py` | 292 | agents | Чтение/запись профиля пользователя в SQLite |
| `backend/agents/manager_*.py` | 88–249 | agents | Миксины `AgentManager`: агенты, контекст, память, профили, статистика, задачи |
| `backend/agents/agent_manager.py` | 74 | agents | `AgentManager` — синглтон из миксинов |
| `backend/utils/__init__.py` | 9 | utils | Слой объявлен обязательным, но пуст: общий код живёт в `shared/` |
| `backend/__init__.py` | 42 | — | Описание пакета + добавление корня репозитория в `sys.path` (для `shared/`) |

Публичный контракт слоя объявлен в его `__init__.py` (реэкспорт имён);
`backend/api/__init__.py` намеренно не импортирует `main` — его тянет
`core.dependencies.get_manager` в момент вызова, и ранний импорт создал бы цикл.

### `shared/` — общие утилиты, используемые днями

| Модуль | Публичные имена | Назначение |
|---|---|---|
| `shared/deepseek_utils.py` | `DEEPSEEK_BASE_URL`, `read_key_from_env_file`, `parse_stop_sequences`, `usage_to_dict` | Endpoint DeepSeek (OpenAI-совместимый), чтение `DEEPSEEK_API_KEY` из `.env`, разбор stop-строк из UI, объект `Usage` → обычный dict |
| `shared/deepseek_client.py` | `make_client`, `DEFAULT_TIMEOUT` | Клиент OpenAI SDK для DeepSeek; пакет `openai` импортируется лениво внутри функции |
| `shared/db_base.py` | `Base`, `make_engine`, `init_db`, `make_session_factory` | Декларативная база SQLAlchemy, движок SQLite (`check_same_thread=False`, `PRAGMA foreign_keys=ON`), создание таблиц, фабрика сессий |
| `shared/token_counter.py` | `count_tokens`, `get_tokenizer` | Локальная оценка токенов через tiktoken (`cl100k_base`), кодировка кэшируется на процесс, `tiktoken` импортируется лениво |
| `shared/logging_utils.py` | `get_logger`, `configure_logging`, `DEFAULT_FORMAT` | Единственный источник настроек логирования: `get_logger` не добавляет хендлеров (вывод по умолчанию выключен), включение — явный `configure_logging()` |

Кто подключает `shared/` сегодня: `day2/app.py` и `day3/app.py`
(`deepseek_utils`), `day13/backend/` — `agents/agent.py`, `core/config.py`,
`storage/database.py`, `models/*.py`, `storage/task_store.py`, `api/main.py`
(шесть точек входа слоёв). Дни 1, 4–11 автономны, `day12/` — снимок той же
архитектуры, что и день 13.
Для новых дней `shared/` — обязательное место для междневного кода
(см. [`AGENTS.md`](../AGENTS.md), раздел «Структура файлов»).

## Как день 13 использует `shared/`

Корень репозитория добавляется в `sys.path` в `day13/backend/__init__.py`
(`Path(__file__).resolve().parents[2]`), поэтому модули дня импортируют общий
пакет напрямую, без правок в тестах и без копий кода:

| Модуль дня | Импорт из `shared/` | Зачем |
|---|---|---|
| `backend/agents/agent.py` | `deepseek_client.make_client`, `token_counter.count_tokens`, `logging_utils.get_logger` | Клиент DeepSeek на каждый агент, локальный подсчёт токенов контекста, лог неприменимого намерения из реплики |
| `backend/core/config.py` | `deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API и чтение `DEEPSEEK_API_KEY` из `.env` дня |
| `backend/storage/database.py` | `db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite (`check_same_thread=False`, `PRAGMA foreign_keys=ON`) |
| `backend/models/*.py` | `db_base.Base` | База для ORM-классов дня (в каждом модуле моделей) |
| `backend/storage/task_store.py` | `logging_utils.get_logger` | Отладочный лог записанного перехода |
| `backend/api/main.py` | `logging_utils.get_logger` | Логгер бэкенда; вывод включается только явным `configure_logging()` |

## Инварианты структуры

- Любой `.py` — **не больше 400 строк**; `app.py` ≤ 100,
  `backend/api/main.py` ≤ 80 (команда проверки — в `AGENTS.md`, раздел
  «Структура файлов»).
- Файл лежит в папке **своего слоя** (`core` / `domain` / `storage` /
  `services` / `agents` / `models` / `schemas` / `api` / `utils`); в корне
  `backend/` — только `__init__.py`. Интерфейс — `frontend/`, прогоны — `scripts/`,
  отчёты — `docs/reports/`, тесты — `tests/{unit,integration,e2e}/`.
- `shared/` — единственное место для кода, не меняющегося между днями; копия
  того же кода в `dayN/` и `dayN+1/` запрещена.
- Снимки `day1/`–`day12/` не переписываются под новые правила.
- Каждый новый день ведёт `STRUCTURE.md` со списком модулей; междневные
  изменения фиксируются в [`../CHANGELOG.md`](../CHANGELOG.md).
