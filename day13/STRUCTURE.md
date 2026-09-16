# Структура дня 13

Карта модулей дня 13: что где лежит и за что отвечает. Правила структуры — в
[`../AGENTS.md`](../AGENTS.md) и [`../docs/architecture.md`](../docs/architecture.md).

**Главное правило: любой `.py` файл ≤ 400 строк** (`app.py` ≤ 100,
`backend/main.py` ≤ 80). Файл подошёл к ~350 строкам — дели на модули по
доменам, не дожидаясь 401-й строки.

День 13 — копия дня 12 (`day12/` не изменяется, это снимок) плюс **состояние
задачи как конечный автомат**: этапы, шаги внутри этапа, ожидаемое действие,
пауза с продолжением с того же места. Состояние живёт в SQLite, подключается
блоком к системному промпту каждого запроса и обновляется по реплике
пользователя.

## Раскладка

```
day13/
├── app.py                    # точка входа Streamlit (45 строк): set_page_config + вызовы секций
├── ui/                       # Streamlit UI по секциям (10 модулей)
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным
│   ├── routers/              # эндпоинты по доменам (5 роутеров)
│   ├── models/               # Pydantic-схемы API по доменам (5 модулей)
│   ├── manager_*.py          # миксины AgentManager по доменам (6 модулей)
│   ├── tables.py             # ORM-таблицы агента, памяти и профилей
│   └── tables_task.py        # ORM-таблицы состояния задачи (day13)
├── tests/                    # pytest: 584 теста (офлайн)
├── docs/                     # architecture.md, usage.md, api.md
├── task_state_demo.py        # прогон демонстрации состояния задачи (--all/--phase/--reset)
├── task_demo_report.py       # сборка отчёта демонстрации
├── task_state_demo.md        # отчёт: 5 фаз в 5 процессах
├── personalization_comparison.py  # унаследованный прогон отчёта персонализации (день 12)
├── personalization_comparison.md  # унаследованный отчёт персонализации
├── comparison_report.py      # сборка отчёта сравнения профилей
├── comparison_stub.py        # офлайн-заглушка (её же использует task_state_demo.py)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── requirements.txt, .env.example
└── agents.db                 # SQLite (в .gitignore по *.db)
```

## Состояние задачи (день 13) — новые модули

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/task_fsm.py` | 387 | FSM: `TaskStage`/`TaskStep`/`TaskEvent` (`Enum`), классы-этапы с `handle(event, step)`, таблицы `STAGE_STEPS`/`STAGE_TRANSITIONS` |
| `backend/task_prompt.py` | 174 | Тексты блока состояния для системного промпта: ожидаемые действия, завершённые этапы, `render_task_state_block` |
| `backend/task_intent.py` | 89 | Распознавание намерения в реплике (`пауза`/`продолжи`/`откат`/`подтверждаю`) по таблице фраз с приоритетом групп |
| `backend/task_store.py` | 209 | `TaskStateStore`: единственное место работы с таблицами `task_states`/`task_transitions` (чтение, журнал, запись перехода) |
| `backend/task_state.py` | 268 | `TaskStateMachine`: публичный контракт переходов (create/pause/resume/advance/rollback/transition_to) и валидация |
| `backend/tables_task.py` | 102 | ORM: `TaskState` (`task_states`) и `TaskTransition` (`task_transitions`) |
| `backend/manager_tasks.py` | 104 | Миксин `TaskOpsMixin`: тонкие обёртки для API, разрешение умолчаний шага/действия |
| `backend/models/task.py` | 122 | Схемы API: `TaskStateOut`, `TaskTransitionOut`, `TaskCreateIn`, `TaskRollbackIn`, `TaskTransitionIn`, `TaskHistoryOut` |
| `backend/routers/tasks.py` | 183 | Роутер: 9 эндпоинтов состояния задачи |
| `ui/task_panel.py` | 200 | Раздел «🧭 Состояние задачи»: этап, шаг, ASCII-схема, пять кнопок, журнал переходов |

Почему `TaskStateMachine` и `TaskStateStore` — разные модули: та же граница, что
`agent.py` / `profile_store.py` в дне 12 — поведение (какие переходы допустимы)
отдельно от хранения (SQLAlchemy-сессии и таблицы). Стейт-машину читают, не
отвлекаясь на ORM; хранилище тестируется без автомата. Оба модуля вместе
укладываются в лимит 400 строк, один файл — нет (441 строка).

## `ui/` — интерфейс Streamlit (по секциям)

| Модуль | Строк | Назначение |
|---|---|---|
| `ui/__init__.py` | 6 | Описание пакета; модули не выполняют `st.*` на импорте |
| `ui/api_client.py` | 327 | HTTP-транспорт к бэкенду (`requests`), `BACKEND_URL` / `DAY13_BACKEND_URL`, `BackendError`, функции дня 13 (`api_*_task*`) |
| `ui/common.py` | 190 | Подписи (включая `TASK_STAGE_LABELS`), форматтеры, `st.session_state`: init, флеш-сообщения, выбор активного агента |
| `ui/sidebar.py` | 191 | Боковая панель: агенты, создание агента, стратегия, задача и сессия (`render_sidebar()`) |
| `ui/chat_section.py` | 260 | Раздел «💬 Чат и память», переключатель трёх разделов, сборка страницы (`render_main_area()`) |
| `ui/context_panels.py` | 324 | Панели контекста: токены, сжатие, сравнение режимов, ветки, факты |
| `ui/memory_panels.py` | 229 | Панели трёх слоёв памяти, индикатор «что ушло в запрос» |
| `ui/profile_section.py` | 322 | Раздел «👤 Профиль пользователя»: CRUD профилей, предпросмотр промпта |
| `ui/profile_comparison.py` | 129 | Сравнение двух профилей на одном вопросе (временные агенты) |
| `ui/task_panel.py` | 200 | Раздел «🧭 Состояние задачи»: состояние, схема FSM, кнопки, журнал |

## `backend/routers/` — эндпоинты по доменам

| Модуль | Строк | Эндпоинтов | Домен |
|---|---|---|---|
| `backend/routers/__init__.py` | 1 | — | Описание пакета |
| `backend/routers/agents.py` | 253 | 11 | CRUD агентов, генерация, диалог, статистика токенов |
| `backend/routers/context.py` | 140 | 9 | Сжатие истории, стратегии, ветки, факты |
| `backend/routers/memory.py` | 180 | 10 | Слои памяти (`/memory/short-term`, `/working`, `/long-term`), сессия, задача |
| `backend/routers/profiles.py` | 126 | 6 | Профили пользователей `/users...`, `GET /agents/{id}/profile` |
| `backend/routers/tasks.py` | 183 | 9 | Состояние задачи: создание, список, чтение, журнал, пауза, продолжение, шаг, откат, переход |

Всего 45 эндпоинтов (36 унаследованных + 9 новых). Пути внутри роутеров
абсолютные, префиксов нет; подключение — в `backend/main.py`. Доступ к менеджеру
и 404/409 — `backend/dependencies.py` (`get_manager`, `agent_or_404`,
`task_or_404`).

## `backend/models/` — Pydantic-схемы API по доменам

| Модуль | Строк | Домен |
|---|---|---|
| `backend/models/__init__.py` | 138 | Реэкспорт всех схем (импорт — из `backend.models`) |
| `backend/models/agent.py` | 319 | Агент, генерация (включая поле `task_state`), метрики использования токенов |
| `backend/models/context.py` | 218 | Сжатие истории, стратегии, ветки, факты |
| `backend/models/memory.py` | 173 | Три слоя памяти агента |
| `backend/models/profile.py` | 170 | Профиль пользователя и его вклад в промпт |
| `backend/models/task.py` | 122 | Состояние задачи: этап, шаг, переходы, журнал |

ORM-таблицы агента, памяти и профилей (`AgentRecord`, `ShortTermMessage`,
`WorkingMemory`, `LongTermMemory`, `Summary`, `TokenUsage`, `Fact`,
`Checkpoint`, `UserProfile`) лежат в `backend/tables.py` (393 строки), таблицы
состояния задачи (`TaskState`, `TaskTransition`) — в `backend/tables_task.py`
(102 строки); обе группы реэкспортируются через `backend/database.py`.
Расхождение с целевой раскладкой `AGENTS.md` (`models/` — ORM, `schemas/` —
Pydantic) зафиксировано в `AGENTS.md`, раздел «Известные расхождения со
снимками».

## Остальные модули `backend/`

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/__init__.py` | 45 | Описание пакета + добавление корня репозитория в `sys.path` (для `shared/`) |
| `backend/config.py` | 156 | Настройки: URL/модели DeepSeek, дефолты, лимиты и цены, сжатие, стратегии, память, профиль, границы полей состояния задачи, пути `.env` и `agents.db` |
| `backend/strategies.py` | 62 | `Enum Strategy` и проверка значения |
| `backend/context_fsm.py` | 256 | Стейт-машина сжатия (`Enum` + паттерн State) |
| `backend/context_policy.py` | 173 | Чистая арифметика сжатия |
| `backend/fact_extractor.py` | 96 | Эвристика извлечения фактов |
| `backend/memory_layers.py` | 143 | Представления слоёв памяти и их тексты |
| `backend/memory.py` | 286 | `MemoryManager`: хранение трёх слоёв |
| `backend/profile_values.py` | 335 | Перечисления и нормализация значений профиля |
| `backend/profiles.py` | 204 | Блок персонализации для системного промпта |
| `backend/profile_store.py` | 291 | Чтение/запись профиля в SQLite |
| `backend/demo_profiles.py` | 107 | Демонстрационные профили |
| `backend/compressor.py` | 326 | `ContextCompressor`: план, суммаризация, конспект |
| `backend/agent.py` | 1597 ⚠️ | `Agent`: память, токены, `prepare_context`, стратегии, факты, ветки, профиль, состояние задачи (`task_state`, `task_state_block`, `apply_task_intent`) |
| `backend/manager_agents.py` | 249 | Миксин пула агентов (удаление агента уносит его задачи) |
| `backend/manager_profiles.py` | 119 | Миксин профилей пользователей |
| `backend/manager_context.py` | 107 | Миксин сжатия, стратегий, веток, фактов |
| `backend/manager_usage.py` | 107 | Миксин статистики токенов (SQL-агрегаты) |
| `backend/manager_memory.py` | 88 | Миксин трёх слоёв памяти |
| `backend/manager_tasks.py` | 104 | Миксин состояния задачи |
| `backend/agent_manager.py` | 74 | `AgentManager` — синглтон из миксинов |
| `backend/dependencies.py` | 34 | `get_manager`, `agent_or_404`, `task_or_404` для роутеров |
| `backend/main.py` | 80 | Сборка `app`: `lifespan`, CORS, `include_router` |

## Тесты

`tests/` — 584 теста `pytest`, офлайн (временная SQLite + фейк клиента
DeepSeek). Новые файлы дня 13:

| Модуль | Строк | Что проверяет |
|---|---|---|
| `tests/test_task_fsm.py` | 395 | Таблица переходов «этап × событие» (20 пар), негативные сценарии, `is_valid_transition`, шаги этапов |
| `tests/test_task_prompt.py` | 168 | Ожидаемые действия, перечень завершённых этапов, дословный формат строки блока |
| `tests/test_task_intent.py` | 115 | Распознавание всех фраз, приоритет групп, границы слов |
| `tests/test_task_state.py` | 324 | Поведение `TaskStateMachine`: create/advance/pause/resume/rollback/transition, ошибки, неизвестная задача |
| `tests/test_task_store.py` | 191 | Хранение: журнал в `task_transitions`, снимок рабочей памяти, проекция в словарь, переживание нового объекта машины |
| `tests/test_task_manager.py` | 202 | `TaskOpsMixin`: умолчания перехода, список активных задач, причины в журнале, удаление агента |
| `tests/test_task_agent.py` | 149 | Блок состояния в системном промпте, авто-обновление по реплике, переживание пересборки агента |
| `tests/test_task_api.py` | 319 | 9 эндпоинтов: коды 201/400/404/409/422, полный цикл, журнал, `task_state` в ответе генерации |

## Что импортируется из `shared/`

| Модуль дня | Импорт | Зачем |
|---|---|---|
| `backend/__init__.py` | — (добавляет корень репозитория в `sys.path`) | Чтобы `from shared...` работал из любого модуля дня |
| `backend/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов, лог неприменимого намерения |
| `backend/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API, чтение `DEEPSEEK_API_KEY` |
| `backend/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/tables.py` | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/tables_task.py` | `shared.db_base.Base` | База для ORM-классов состояния задачи |
| `backend/task_store.py` | `shared.logging_utils.get_logger` | Отладочный лог записанного перехода |
| `backend/main.py` | `shared.logging_utils.get_logger` | Логгер бэкенда |

Модули `ui/` обращаются к бэкенду только по HTTP (`ui/api_client.py`), поэтому
`shared/` напрямую не импортируют.

## Известные расхождения

| Файл | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agent.py` | 1597 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи, генерация) не разложен на миксины — расхождение унаследовано от дней 11–12, рефакторинг `Agent` в день 13 не входил |
| ORM разложен на `tables.py` + `tables_task.py` | 393 + 102 | 400 | Домен один (таблицы дня), но добавление двух таблиц состояния задачи вывело бы `tables.py` за лимит; по скиллу `fastapi-streamlit-day-structure` файл делится по доменам, поэтому состояние задачи вынесено отдельным модулем |

Лимиты `app.py` (45 ≤ 100) и `backend/main.py` (80 ≤ 80) соблюдены: в день 13
шапка `main.py` сокращена, а описание эндпоинтов ушло в роутер
`backend/routers/tasks.py`.

## Проверка лимита строк

Из папки `day13` (`.venv` исключён):

```powershell
.venv/Scripts/python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод сегодня: `[('backend\\agent.py', 1597)]`.
