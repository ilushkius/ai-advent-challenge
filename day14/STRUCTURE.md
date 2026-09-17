# Структура дня 14

Карта модулей дня 14: что где лежит и за что отвечает. Правила структуры — в
[`../AGENTS.md`](../AGENTS.md) и [`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

День 14 — копия дня 13 (`day13/` не изменяется, это снимок) плюс **инварианты**:
правила проекта, которые агент не имеет права нарушать. Правила лежат в отдельной
таблице `invariants` (не в истории сообщений), блоком подставляются в системный
промпт каждого запроса, а предложение проверяется перед выдачей — сначала
детерминированными правилами, при неоднозначности вызовом LLM. Нарушение
hard-инварианта превращается в отказ (с объяснением, какое правило нарушено),
нарушение soft — в предупреждение, но решение предлагается.

## Раскладка

```
day14/
├── app.py                    # точка входа Streamlit (50 строк): set_page_config + вызовы секций
├── frontend/                 # Streamlit UI по секциям (11 модулей)
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # FastAPI: 6 роутеров по доменам + сборка app (main.py)
│   ├── core/                 # config, dependencies — настройки и доступ к менеджеру
│   ├── domain/               # чистые правила и данные: FSM, стратегии, профиль, инварианты, тексты
│   ├── services/             # прикладные сервисы: compressor, task_state, invariant_checker
│   ├── storage/              # доступ к БД: database, task_store, invariant_store, memory_rows
│   ├── agents/               # Agent, MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы SQLAlchemy по доменам
│   ├── schemas/              # Pydantic-схемы API по доменам
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 725 тестов (unit/, integration/, e2e/)
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов
│   ├── invariants_demo.py    # три сценария инвариантов → invariants_demo.md (офлайн)
│   ├── seed_invariants.py    # посев демо-инвариантов в БД (--reset/--db)
│   ├── task_state_demo.py    # демонстрация состояния задачи (--all/--phase/--reset)
│   ├── task_demo_report.py   # сборка отчёта демонстрации
│   ├── personalization_comparison.py  # унаследованный прогон отчёта персонализации (день 12)
│   ├── comparison_report.py  # сборка отчёта сравнения профилей
│   └── comparison_stub.py    # офлайн-заглушка (её же использует task_state_demo.py)
├── invariants_demo.md        # отчёт о трёх сценариях инвариантов (в корне дня — по заданию дня)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── pyproject.toml, uv.lock   # зависимости (uv): прямые — в pyproject, точные версии — в локе
├── .agents/skills/           # симлинки на AI-скиллы библиотек (uvx library-skills)
├── .python-version           # 3.14 (версия для `uv sync`)
├── .env.example              # шаблон ключа DEEPSEEK_API_KEY
└── agents.db                 # SQLite (в .gitignore по *.db)
```

Отчёты прогонов лежат в `docs/reports/` (`task_state_demo.md`,
`personalization_comparison.md` — оба **унаследованы от дня 13**), а отчёт
`invariants_demo.md` — в корне дня: путь задан заданием дня 14, в `docs/reports/`
он не дублируется. Скрипты в `scripts/` не пакет: они находят корень дня
(`Path(__file__).resolve().parents[1]`) и добавляют его в `sys.path` сами, поэтому
`uv run python scripts/<script>.py` работает из любой рабочей директории.

## Слои `backend/`

| Слой | Модули | Назначение |
|---|---|---|
| `core/` | `config.py` (174), `dependencies.py` (53), `__init__.py` (22) | Настройки дня и зависимости роутов: `get_manager`, `agent_or_404`, `task_or_404`, `invariant_or_404` |
| `domain/` | 15 модулей + `__init__.py` (213) | Чистые правила и данные: FSM задачи и сжатия, стратегии, факты, слои памяти, профиль, инварианты, тексты промпта. Знают только stdlib, `core.config` и соседей по слою |
| `storage/` | `database.py` (46), `task_store.py` (217), `invariant_store.py` (255), `memory_rows.py` (47), `__init__.py` (72) | Движок и сессии, ORM-строки → словари, `TaskStateStore`, `InvariantManager` |
| `services/` | `compressor.py` (329), `task_state.py` (268), `invariant_checker.py` (296), `__init__.py` (59) | `ContextCompressor`, `TaskStateMachine` и `InvariantChecker`: оркестрация домена и хранилища |
| `agents/` | `agent.py` (1727 ⚠️), `memory.py` (291), `profile_store.py` (292), `agent_manager.py` (85), `manager_*.py` (7 файлов), `__init__.py` (57) | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов |
| `models/` | `agent.py` (93), `message.py` (41), `context.py` (157), `memory.py` (81), `user_profile.py` (57), `task_state.py` (102), `invariant.py` (51), `__init__.py` (46) | ORM-таблицы SQLAlchemy: `agents`, `short_term_messages`, `summaries`/`token_usage`/`facts`/`checkpoints`, `working_memory`/`long_term_memory`, `user_profiles`, `task_states`/`task_transitions`, `invariants` |
| `schemas/` | `agent.py` (325), `context.py` (218), `memory.py` (173), `profile.py` (170), `task.py` (122), `invariant.py` (149), `__init__.py` (154) | Pydantic-схемы API по доменам, реэкспорт из `schemas/__init__.py` |
| `api/` | `agents.py` (263), `context.py` (140), `memory.py` (180), `profiles.py` (126), `tasks.py` (183), `invariants.py` (139), `main.py` (79), `__init__.py` (15) | 51 эндпоинт по доменам и сборка `app` |
| `utils/` | `__init__.py` (9) | Своего кода нет: общий (клиент DeepSeek, база, токены, логи) — в repo-level `shared/` |

Пакеты `core`, `domain`, `services`, `storage`, `agents`, `models`, `schemas`,
`api` содержат `__init__.py` с реэкспортом публичных имён слоя — это
единственное место, где видно публичный контракт слоя. `api/__init__.py`
намеренно **не** импортирует `main`: `core.dependencies.get_manager` тянет
`api.main` лениво, и ранний импорт создал бы цикл `api → core → api`.

Два импорта отложены намеренно (разрыв циклов `storage ⇄ agents` и
`core ⇄ agents`); поведение от этого не меняется:
`storage/task_store.py` берёт `MemoryManager` внутри свойства `memory_manager`, а
`core/dependencies.py` — `AgentManager` только под `TYPE_CHECKING` (для аннотации).

## Состояние задачи (день 13) — новые модули

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/task_fsm.py` | 387 | FSM: `TaskStage`/`TaskStep`/`TaskEvent` (`Enum`), классы-этапы с `handle(event, step)`, таблицы `STAGE_STEPS`/`STAGE_TRANSITIONS` |
| `backend/domain/task_prompt.py` | 174 | Тексты блока состояния для системного промпта: ожидаемые действия, завершённые этапы, `render_task_state_block` |
| `backend/domain/task_intent.py` | 89 | Распознавание намерения в реплике (`пауза`/`продолжи`/`откат`/`подтверждаю`) по таблице фраз с приоритетом групп |
| `backend/storage/task_store.py` | 217 | `TaskStateStore`: единственное место работы с таблицами `task_states`/`task_transitions` (чтение, журнал, запись перехода) |
| `backend/services/task_state.py` | 268 | `TaskStateMachine`: публичный контракт переходов (create/pause/resume/advance/rollback/transition_to) и валидация |
| `backend/models/task_state.py` | 102 | ORM: `TaskState` (`task_states`) и `TaskTransition` (`task_transitions`) |
| `backend/agents/manager_tasks.py` | 104 | Миксин `TaskOpsMixin`: тонкие обёртки для API, разрешение умолчаний шага/действия |
| `backend/schemas/task.py` | 122 | Схемы API: `TaskStateOut`, `TaskTransitionOut`, `TaskCreateIn`, `TaskRollbackIn`, `TaskTransitionIn`, `TaskHistoryOut` |
| `backend/api/tasks.py` | 183 | Роутер: 9 эндпоинтов состояния задачи |
| `frontend/task_panel.py` | 206 | Раздел «🧭 Состояние задачи»: этап, шаг, ASCII-схема, пять кнопок, журнал переходов |

Почему `TaskStateMachine` и `TaskStateStore` — разные модули: это граница слоёв
`services/` и `storage/` (та же, что у `ContextCompressor` и `MemoryManager`):
поведение (какие переходы допустимы) отдельно от хранения (сессии SQLAlchemy и
таблицы). Машину читают, не отвлекаясь на ORM; хранилище тестируется без
автомата. Побочный эффект — оба файла укладываются в лимит 400 строк (вместе они
дали бы 485).

## Инварианты (день 14) — новые модули

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/invariant_values.py` | 120 | Значения инварианта: `InvariantCategory`/`InvariantSeverity` (`Enum`), вердикты (`VERDICT_ALLOWED`/`WARNING`/`REFUSAL`), подписи, `category_from_value`/`severity_from_value` (неизвестное → `InvariantValueError`) |
| `backend/domain/invariant_rules.py` | 159 | Детерминированный слой проверки: `DeterministicRule` (gate — признак в описании инварианта, signal — в тексте, exclude — согласие пользователя), `DETERMINISTIC_RULES` (15 правил), `deterministic_violations` |
| `backend/domain/invariant_prompt.py` | 102 | Тексты: блок инвариантов для системного промпта, отказ (`render_violation_refusal`), предупреждение, сообщение для LLM-проверки |
| `backend/domain/demo_invariants.py` | 71 | Четыре демонстрационных правила — по одному на категорию (UI, посев, отчёт) |
| `backend/storage/invariant_store.py` | 255 | `InvariantManager`: единственное место работы с таблицей `invariants` (чтение, CRUD, включение-выключение, проекция в словарь) |
| `backend/services/invariant_checker.py` | 296 | `InvariantChecker`: правила → (при неоднозначности) один вызов LLM; `InvariantCheckResult`/`InvariantViolation`, `merged_with` для объединения вердиктов запроса и ответа |
| `backend/models/invariant.py` | 51 | ORM: `Invariant` (`invariants`) |
| `backend/agents/manager_invariants.py` | 69 | Миксин `InvariantOpsMixin`: CRUD и проверка текста для API |
| `backend/schemas/invariant.py` | 149 | Схемы API: `InvariantIn`, `InvariantUpdateIn`, `InvariantOut`, `InvariantCheckIn`, `InvariantCheckOut`, `InvariantViolationOut` |
| `backend/api/invariants.py` | 139 | Роутер: 6 эндпоинтов инвариантов |
| `frontend/invariant_panel.py` | 254 | Раздел «📏 Инварианты»: таблица, форма создания, правка, включение-выключение, удаление, проверка текста |
| `scripts/seed_invariants.py` | 90 | Посев демо-инвариантов в БД дня (`--reset`, `--db`), идемпотентно, без сети |
| `scripts/invariants_demo.py` | 271 | Три сценария (разрешено / предупреждение / отказ) офлайн, заглушка DeepSeek, LLM-слой выключен → `invariants_demo.md` |

Почему правил два слоя (домен и сервис) и почему проверка не в агенте: правила —
чистые функции над строками (`deterministic_violations` проверяются без БД), а
`InvariantChecker` — прикладная логика (читает таблицу, зовёт LLM, объединяет
вердикты). `Agent` только решает, КОГДА проверять: запрос — до вызова модели
(детерминированно, чтобы не платить за отказ), ответ — после и вместе с LLM-слоем.
Хранилище отдельно от правил по той же границе, что `task_store.py` и
`task_state.py`: `InvariantManager` тестируется без правил, правила — без БД.

Ключевое свойство механизма: инварианты живут в СВОЕЙ таблице, а не в истории
сообщений. Их не «вымывает» сжатие контекста, они одинаковы для всех агентов и
видны в промпте каждого запроса; выключенное правило остаётся в таблице и
возвращается одной кнопкой, не набирая текст заново.

## `frontend/` — интерфейс Streamlit (по секциям)

| Модуль | Строк | Назначение |
|---|---|---|
| `frontend/__init__.py` | 17 | Описание пакета; модули не выполняют `st.*` на импорте |
| `frontend/api_client.py` | 365 | HTTP-транспорт к бэкенду (`requests`), `BACKEND_URL` / `DAY14_BACKEND_URL`, `BackendError`, функции дня 13 (`api_*_task*`) и дня 14 (`api_*_invariant*`) |
| `frontend/common.py` | 238 | Подписи (включая `TASK_STAGE_LABELS` и `INVARIANT_*_LABELS`), форматтеры, `invariant_notice`, `st.session_state`: init, флеш-сообщения, выбор активного агента |
| `frontend/sidebar.py` | 191 | Боковая панель: агенты, создание агента, стратегия, задача и сессия (`render_sidebar()`) |
| `frontend/chat_section.py` | 288 | Раздел «💬 Чат и память», переключатель четырёх разделов, блок предупреждения/отказа по инвариантам над вводом, сборка страницы (`render_main_area()`) |
| `frontend/context_panels.py` | 324 | Панели контекста: токены, сжатие, сравнение режимов, ветки, факты |
| `frontend/memory_panels.py` | 229 | Панели трёх слоёв памяти, индикатор «что ушло в запрос» |
| `frontend/profile_section.py` | 322 | Раздел «👤 Профиль пользователя»: CRUD профилей, предпросмотр промпта |
| `frontend/profile_comparison.py` | 129 | Сравнение двух профилей на одном вопросе (временные агенты) |
| `frontend/task_panel.py` | 206 | Раздел «🧭 Состояние задачи»: состояние, схема FSM, кнопки, журнал |
| `frontend/invariant_panel.py` | 254 | Раздел «📏 Инварианты»: таблица правил, форма, правка, включение-выключение, удаление, проверка текста |

## `backend/api/` — эндпоинты по доменам

| Модуль | Строк | Эндпоинтов | Домен |
|---|---|---|---|
| `backend/api/__init__.py` | 15 | — | Описание пакета и реэкспорт роутеров (без `main`) |
| `backend/api/agents.py` | 263 | 11 | CRUD агентов, генерация, диалог, статистика токенов |
| `backend/api/context.py` | 140 | 9 | Сжатие истории, стратегии, ветки, факты |
| `backend/api/memory.py` | 180 | 10 | Слои памяти (`/memory/short-term`, `/working`, `/long-term`), сессия, задача |
| `backend/api/profiles.py` | 126 | 6 | Профили пользователей `/users...`, `GET /agents/{id}/profile` |
| `backend/api/tasks.py` | 183 | 9 | Состояние задачи: создание, список, чтение, журнал, пауза, продолжение, шаг, откат, переход |
| `backend/api/invariants.py` | 139 | 6 | Инварианты: CRUD правил проекта и проверка текста (`/invariants/check`) |
| `backend/api/main.py` | 79 | — | Сборка `app`: `lifespan`, CORS, `include_router` |

Всего 51 эндпоинт (45 унаследованных + 6 новых). Пути внутри роутеров абсолютные,
префиксов нет; подключение — в `backend/api/main.py`. Доступ к менеджеру и
404/409 — `backend/core/dependencies.py` (`get_manager`, `agent_or_404`,
`task_or_404`, `invariant_or_404`).

## `backend/schemas/` — Pydantic-схемы API, `backend/models/` — ORM

Разделение слоёв: Pydantic-схемы API — в `backend/schemas/` (реэкспорт из
`schemas/__init__.py`, импорт — `from backend.schemas import ...`), ORM-таблицы —
в `backend/models/*.py` (реэкспорт из `backend/storage/database.py`, импорт —
`from backend.storage.database import ...`). Это целевая раскладка `AGENTS.md`:
расхождение дня 12 (схемы в `models/`, ORM в `tables.py`) устранено.

| Схемы (`backend/schemas/`) | Строк | Домен |
|---|---|---|
| `schemas/__init__.py` | 154 | Реэкспорт всех схем (импорт — из `backend.schemas`) |
| `schemas/agent.py` | 325 | Агент, генерация (включая поля `task_state` и `invariants`), метрики использования токенов |
| `schemas/context.py` | 218 | Сжатие истории, стратегии, ветки, факты |
| `schemas/invariant.py` | 149 | Инварианты и результат проверки текста |
| `schemas/memory.py` | 173 | Три слоя памяти агента |
| `schemas/profile.py` | 170 | Профиль пользователя и его вклад в промпт |
| `schemas/task.py` | 122 | Состояние задачи: этап, шаг, переходы, журнал |

| ORM (`backend/models/`) | Строк | Таблицы |
|---|---|---|
| `models/agent.py` | 93 | `agents` (`AgentRecord`) и его `relationship`-связи |
| `models/message.py` | 41 | `short_term_messages` (`ShortTermMessage`) |
| `models/memory.py` | 81 | `working_memory`, `long_term_memory` |
| `models/context.py` | 157 | `summaries`, `token_usage`, `facts`, `checkpoints` |
| `models/user_profile.py` | 57 | `user_profiles` (`UserProfile`) |
| `models/task_state.py` | 102 | `task_states` (`TaskState`), `task_transitions` (`TaskTransition`) |
| `models/invariant.py` | 51 | `invariants` (`Invariant`) |
| `models/__init__.py` | 46 | Реэкспорт ORM-классов (импорт из `backend.storage.database`) |

ORM разложен по доменам не из-за лимита строк, а по правилу слоя: файл лежит в
папке своего домена (в дне 12 ради лимита хватало пары `tables.py` +
`tables_task.py`). Строковые имена в `relationship("TaskState", ...)` не
меняются — SQLAlchemy разрешает их по registry, а все модули `models/`
импортируются из `storage/database.py`, поэтому регистрация таблиц та же, что и
до рефакторинга. Таблица `invariants` добавлена днём 14: **12 таблиц** на день
(было 11), при этом `invariants` ни с чем не связана по FK — правила проекта
живут отдельно от агентов и диалога.

## Тесты

`tests/` — 725 тестов `pytest`, офлайн (временная SQLite + фейк клиента
DeepSeek), разложены по трём подпапкам **по фикстурам**: без БД и агента —
`unit/`, с временной БД и `Agent` — `integration/`, через `TestClient` —
`e2e/`. `tests/conftest.py` и `tests/support.py` остаются в корне `tests/`: на
них опирается `pythonpath = . tests` из `pytest.ini` и импорт
`from support import ...`.

| Подпапка | Файлов | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/` | 10 | 399 | Чистые модули: FSM сжатия и задачи, политика сжатия, извлечение фактов, значения профиля, значения/правила/тексты инвариантов |
| `tests/integration/` | 15 | 222 | Хранилище, сервисы и агент на временной БД: `TaskStateStore`/`TaskStateMachine`, `InvariantManager`/`InvariantChecker`, `MemoryManager`, `ProfileStore`, `ContextCompressor`, `AgentManager` |
| `tests/e2e/` | 6 | 104 | API через `TestClient`: 51 эндпоинт, коды 200/201/400/404/409/422, полный цикл задачи, поля `task_state` и `invariants` в ответе генерации |

Наследованные от дня 13 тесты (584) остались зелёными без правок: при пустой
таблице `invariants` проверка не добавляет вызовов и не меняет ни системный
промпт, ни ответ — это отдельно закреплено тестами дня 14.

Новые файлы дня 14 (подпапка — по фикстурам; тестов в файле):

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_invariant_values.py` | 81 | 17 | `Enum`-значения, списки для API, подписи, тексты ошибок на неизвестное значение |
| `tests/unit/test_invariant_rules.py` | 124 | 28 | Правила-термины по всем 14 средствам, привязка к описанию инварианта, согласие пользователя снимает нарушение, границы слов, форма нарушения |
| `tests/unit/test_invariant_prompt.py` | 150 | 12 | Дословный блок промпта, тексты отказа и предупреждения, сообщение для LLM-проверки |
| `tests/integration/test_invariant_manager.py` | 225 | 24 | CRUD инвариантов, уникальность имени, фильтры, ошибки 404/409/422, независимость от диалога агента |
| `tests/integration/test_invariant_checker.py` | 311 | 21 | Правила → LLM, сбои и мусор от модели, пустой текст, дедупликация и приоритет вердиктов в `merged_with` |
| `tests/integration/test_invariant_agent.py` | 243 | 14 | Блок в системном промпте, отказ без вызова DeepSeek, предупреждение с ответом, пост-проверка ответа, сбой LLM-слоя |
| `tests/e2e/test_invariant_api.py` | 328 | 25 | Шесть эндпоинтов: коды, фильтры, проверка текста, поле `invariants` в генерации, корневой ответ, OpenAPI |

Новые файлы дня 13 (подпапка — по фикстурам):

| Модуль | Строк | Что проверяет |
|---|---|---|
| `tests/unit/test_task_fsm.py` | 395 | Таблица переходов «этап × событие» (20 пар), негативные сценарии, `is_valid_transition`, шаги этапов |
| `tests/unit/test_task_prompt.py` | 168 | Ожидаемые действия, перечень завершённых этапов, дословный формат строки блока |
| `tests/unit/test_task_intent.py` | 115 | Распознавание всех фраз, приоритет групп, границы слов |
| `tests/integration/test_task_state.py` | 324 | Поведение `TaskStateMachine`: create/advance/pause/resume/rollback/transition, ошибки, неизвестная задача |
| `tests/integration/test_task_store.py` | 191 | Хранение: журнал в `task_transitions`, снимок рабочей памяти, проекция в словарь, переживание нового объекта машины |
| `tests/integration/test_task_manager.py` | 202 | `TaskOpsMixin`: умолчания перехода, список активных задач, причины в журнале, удаление агента |
| `tests/integration/test_task_agent.py` | 149 | Блок состояния в системном промпте, авто-обновление по реплике, переживание пересборки агента |
| `tests/e2e/test_task_api.py` | 319 | 9 эндпоинтов: коды 201/400/404/409/422, полный цикл, журнал, `task_state` в ответе генерации |

## Что импортируется из `shared/`

| Модуль дня | Импорт | Зачем |
|---|---|---|
| `backend/__init__.py` | — (добавляет корень репозитория в `sys.path`) | Чтобы `from shared...` работал из любого модуля дня |
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов, логи отказа и неприменимого намерения |
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API, чтение `DEEPSEEK_API_KEY` |
| `backend/storage/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/models/*.py` | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/storage/task_store.py` | `shared.logging_utils.get_logger` | Отладочный лог записанного перехода |
| `backend/storage/invariant_store.py` | `shared.logging_utils.get_logger` | Отладочный лог созданного/изменённого инварианта |
| `backend/services/invariant_checker.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger` | Клиент для LLM-слоя проверки и лог причины, по которой проверка не выполнена |
| `backend/api/main.py` | `shared.logging_utils.get_logger` | Логгер бэкенда |

Модули `frontend/` обращаются к бэкенду только по HTTP
(`frontend/api_client.py`), поэтому `shared/` напрямую не импортируют.

## Известные расхождения

| Файл | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agents/agent.py` | 1727 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи, инварианты, генерация) не разложен на миксины — расхождение унаследовано от дней 11–13 (в день 13 было 1603 строки; +124 дали интеграция инвариантов: блок в промпте, проверка запроса, пост-проверка ответа, отказ и раздел методов), рефакторинг `Agent` в день 14 не входил |
| `invariants_demo.md` лежит в корне дня | — | — | Путь задан заданием дня 14; в `docs/reports/` файл не дублируется (там остаются только унаследованные отчёты дня 13) |
| ORM разложен на 7 модулей `models/*.py` | 41–157 | 400 | Домен один (таблицы дня), но по правилу слоя файл лежит в папке своего домена; заодно снят вопрос лимита, который в дне 12 решался парой `tables.py` + `tables_task.py` |
| `backend/agents/profile_store.py` (292) и `backend/agents/memory.py` (291) | — | — | Имена модулей сохранены (в целевом списке слоя они могли бы называться `profile_manager.py` / `memory_manager.py`) |
| `INVARIANT_LLM_CHECK` добавляет вызов DeepSeek | — | — | По умолчанию проверка ОТВЕТА идёт в LLM, когда детерминированные правила молчат: это осознанная цена семантической проверки, выключается одной строкой в `backend/core/config.py` (так работает офлайн-отчёт `scripts/invariants_demo.py`) |

Лимиты `app.py` (50 ≤ 100) и `backend/api/main.py` (79 ≤ 80) соблюдены.

## Проверка лимита строк

Из папки `day14` (`.venv` исключён):

```powershell
uv run python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод сегодня: `[('backend\\agents\\agent.py', 1727)]`.
