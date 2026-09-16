# Структура дня 13

Карта модулей дня 13: что где лежит и за что отвечает. Правила структуры — в
[`../AGENTS.md`](../AGENTS.md) и [`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

День 13 — копия дня 12 (`day12/` не изменяется, это снимок) плюс **состояние
задачи как конечный автомат**: этапы, шаги внутри этапа, ожидаемое действие,
пауза с продолжением с того же места. Состояние живёт в SQLite, подключается
блоком к системному промпту каждого запроса и обновляется по реплике
пользователя.

## Раскладка

```
day13/
├── app.py                    # точка входа Streamlit (45 строк): set_page_config + вызовы секций
├── frontend/                 # Streamlit UI по секциям (10 модулей)
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # FastAPI: 5 роутеров по доменам + сборка app (main.py)
│   ├── core/                 # config, dependencies — настройки и доступ к менеджеру
│   ├── domain/               # чистые правила и данные: FSM, стратегии, профиль, тексты
│   ├── services/             # прикладные сервисы: compressor, task_state
│   ├── storage/              # доступ к БД: database, task_store, memory_rows
│   ├── agents/               # Agent, MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы SQLAlchemy по доменам
│   ├── schemas/              # Pydantic-схемы API по доменам
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 584 теста (unit/, integration/, e2e/)
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов
│   ├── task_state_demo.py    # демонстрация состояния задачи (--all/--phase/--reset)
│   ├── task_demo_report.py   # сборка отчёта демонстрации
│   ├── personalization_comparison.py  # унаследованный прогон отчёта персонализации (день 12)
│   ├── comparison_report.py  # сборка отчёта сравнения профилей
│   └── comparison_stub.py    # офлайн-заглушка (её же использует task_state_demo.py)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── requirements.txt, .env.example
└── agents.db                 # SQLite (в .gitignore по *.db)
```

Отчёты прогонов лежат в `docs/reports/` (`task_state_demo.md`,
`personalization_comparison.md`). Скрипты в `scripts/` не пакет: они находят
корень дня (`Path(__file__).resolve().parents[1]`) и добавляют его в `sys.path`
сами, поэтому `python scripts/<script>.py` работает из любой рабочей
директории, а отчёт и демо-база по-прежнему создаются в корне дня и в
`docs/reports/`.

## Слои `backend/`

| Слой | Модули | Назначение |
|---|---|---|
| `core/` | `config.py` (156), `dependencies.py` (41), `__init__.py` (16) | Настройки дня и зависимости роутов: `get_manager`, `agent_or_404`, `task_or_404` |
| `domain/` | 11 модулей + `__init__.py` (141) | Чистые правила и данные: FSM задачи и сжатия, стратегии, факты, слои памяти, профиль, тексты промпта. Знают только stdlib, `core.config` и соседей по слою |
| `storage/` | `database.py` (44), `task_store.py` (217), `memory_rows.py` (47), `__init__.py` (60) | Движок и сессии, ORM-строки → словари, `TaskStateStore` |
| `services/` | `compressor.py` (329), `task_state.py` (268), `__init__.py` (43) | `ContextCompressor` и `TaskStateMachine`: оркестрация домена и хранилища |
| `agents/` | `agent.py` (1603 ⚠️), `memory.py` (291), `profile_store.py` (292), `agent_manager.py` (74), `manager_*.py` (6 файлов), `__init__.py` (55) | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов |
| `models/` | `agent.py` (93), `message.py` (41), `context.py` (157), `memory.py` (81), `user_profile.py` (57), `task_state.py` (102), `__init__.py` (43) | ORM-таблицы SQLAlchemy: `agents`, `short_term_messages`, `summaries`/`token_usage`/`facts`/`checkpoints`, `working_memory`/`long_term_memory`, `user_profiles`, `task_states`/`task_transitions` |
| `schemas/` | `agent.py` (319), `context.py` (218), `memory.py` (173), `profile.py` (170), `task.py` (122), `__init__.py` (138) | Pydantic-схемы API по доменам, реэкспорт из `schemas/__init__.py` |
| `api/` | `agents.py` (253), `context.py` (140), `memory.py` (180), `profiles.py` (126), `tasks.py` (183), `main.py` (80), `__init__.py` (15) | 45 эндпоинтов по доменам и сборка `app` |
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

## `frontend/` — интерфейс Streamlit (по секциям)

| Модуль | Строк | Назначение |
|---|---|---|
| `frontend/__init__.py` | 6 | Описание пакета; модули не выполняют `st.*` на импорте |
| `frontend/api_client.py` | 327 | HTTP-транспорт к бэкенду (`requests`), `BACKEND_URL` / `DAY13_BACKEND_URL`, `BackendError`, функции дня 13 (`api_*_task*`) |
| `frontend/common.py` | 190 | Подписи (включая `TASK_STAGE_LABELS`), форматтеры, `st.session_state`: init, флеш-сообщения, выбор активного агента |
| `frontend/sidebar.py` | 191 | Боковая панель: агенты, создание агента, стратегия, задача и сессия (`render_sidebar()`) |
| `frontend/chat_section.py` | 260 | Раздел «💬 Чат и память», переключатель трёх разделов, сборка страницы (`render_main_area()`) |
| `frontend/context_panels.py` | 324 | Панели контекста: токены, сжатие, сравнение режимов, ветки, факты |
| `frontend/memory_panels.py` | 229 | Панели трёх слоёв памяти, индикатор «что ушло в запрос» |
| `frontend/profile_section.py` | 322 | Раздел «👤 Профиль пользователя»: CRUD профилей, предпросмотр промпта |
| `frontend/profile_comparison.py` | 129 | Сравнение двух профилей на одном вопросе (временные агенты) |
| `frontend/task_panel.py` | 206 | Раздел «🧭 Состояние задачи»: состояние, схема FSM, кнопки, журнал |

## `backend/api/` — эндпоинты по доменам

| Модуль | Строк | Эндпоинтов | Домен |
|---|---|---|---|
| `backend/api/__init__.py` | 15 | — | Описание пакета и реэкспорт роутеров (без `main`) |
| `backend/api/agents.py` | 253 | 11 | CRUD агентов, генерация, диалог, статистика токенов |
| `backend/api/context.py` | 140 | 9 | Сжатие истории, стратегии, ветки, факты |
| `backend/api/memory.py` | 180 | 10 | Слои памяти (`/memory/short-term`, `/working`, `/long-term`), сессия, задача |
| `backend/api/profiles.py` | 126 | 6 | Профили пользователей `/users...`, `GET /agents/{id}/profile` |
| `backend/api/tasks.py` | 183 | 9 | Состояние задачи: создание, список, чтение, журнал, пауза, продолжение, шаг, откат, переход |
| `backend/api/main.py` | 80 | — | Сборка `app`: `lifespan`, CORS, `include_router` |

Всего 45 эндпоинтов (36 унаследованных + 9 новых). Пути внутри роутеров
абсолютные, префиксов нет; подключение — в `backend/api/main.py`. Доступ к
менеджеру и 404/409 — `backend/core/dependencies.py` (`get_manager`,
`agent_or_404`, `task_or_404`).

## `backend/schemas/` — Pydantic-схемы API, `backend/models/` — ORM

Разделение слоёв: Pydantic-схемы API — в `backend/schemas/` (реэкспорт из
`schemas/__init__.py`, импорт — `from backend.schemas import ...`), ORM-таблицы —
в `backend/models/*.py` (реэкспорт из `backend/storage/database.py`, импорт —
`from backend.storage.database import ...`). Это целевая раскладка `AGENTS.md`:
расхождение дня 12 (схемы в `models/`, ORM в `tables.py`) устранено.

| Схемы (`backend/schemas/`) | Строк | Домен |
|---|---|---|
| `schemas/__init__.py` | 138 | Реэкспорт всех схем (импорт — из `backend.schemas`) |
| `schemas/agent.py` | 319 | Агент, генерация (включая поле `task_state`), метрики использования токенов |
| `schemas/context.py` | 218 | Сжатие истории, стратегии, ветки, факты |
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
| `models/__init__.py` | 43 | Реэкспорт ORM-классов (импорт из `backend.storage.database`) |

ORM разложен по доменам не из-за лимита строк, а по правилу слоя: файл лежит в
папке своего домена (в дне 12 ради лимита хватало пары `tables.py` +
`tables_task.py`). Строковые имена в `relationship("TaskState", ...)` не
меняются — SQLAlchemy разрешает их по registry, а все модули `models/`
импортируются из `storage/database.py`, поэтому регистрация таблиц та же, что и
до рефакторинга (11 таблиц, схема БД побайтово совпадает).

## Тесты

`tests/` — 584 теста `pytest`, офлайн (временная SQLite + фейк клиента
DeepSeek), разложены по трём подпапкам **по фикстурам**: без БД и агента —
`unit/`, с временной БД и `Agent` — `integration/`, через `TestClient` —
`e2e/`. `tests/conftest.py` и `tests/support.py` остаются в корне `tests/`: на
них опирается `pythonpath = . tests` из `pytest.ini` и импорт
`from support import ...`.

| Подпапка | Файлов | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/` | 7 | 342 | Чистые модули: FSM сжатия и задачи, политика сжатия, извлечение фактов, значения профиля |
| `tests/integration/` | 12 | 148 | Хранилище, сервисы и агент на временной БД: `TaskStateStore`/`TaskStateMachine`, `MemoryManager`, `ProfileStore`, `ContextCompressor`, `AgentManager` |
| `tests/e2e/` | 5 | 94 | API через `TestClient`: 45 эндпоинтов, коды 200/201/400/404/409/422, полный цикл задачи, `task_state` в ответе генерации |

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
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов, лог неприменимого намерения |
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API, чтение `DEEPSEEK_API_KEY` |
| `backend/storage/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/models/*.py` | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/storage/task_store.py` | `shared.logging_utils.get_logger` | Отладочный лог записанного перехода |
| `backend/api/main.py` | `shared.logging_utils.get_logger` | Логгер бэкенда |

Модули `frontend/` обращаются к бэкенду только по HTTP
(`frontend/api_client.py`), поэтому `shared/` напрямую не импортируют.

## Известные расхождения

| Файл | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agents/agent.py` | 1603 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи, генерация) не разложен на миксины — расхождение унаследовано от дней 11–12 (было 1597 строк; +6 дал перенос импортов на слои), рефакторинг `Agent` в день 13 не входил |
| ORM разложен на 6 модулей `models/*.py` | 41–157 | 400 | Домен один (таблицы дня), но по правилу слоя файл лежит в папке своего домена; заодно снят вопрос лимита, который в дне 12 решался парой `tables.py` + `tables_task.py` |
| `backend/agents/profile_store.py` (292) и `backend/agents/memory.py` (291) | — | — | Имена модулей сохранены как в дне 12 (в целевом списке слоя они могли бы называться `profile_manager.py` / `memory_manager.py`); карта «функционал → файл» — в [`docs/usage.md`](docs/usage.md) |

Лимиты `app.py` (45 ≤ 100) и `backend/api/main.py` (80 ≤ 80) соблюдены: в день 13
шапка `main.py` сокращена, а описание эндпоинтов ушло в роутер
`backend/api/tasks.py`.

## Проверка лимита строк

Из папки `day13` (`.venv` исключён):

```powershell
.venv/Scripts/python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод сегодня: `[('backend\\agents\\agent.py', 1603)]`.
