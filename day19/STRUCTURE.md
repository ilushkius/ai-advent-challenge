# Структура дня 19

Карта модулей дня 19: что где лежит и за что отвечает. Правила структуры — в
[`../AGENTS.md`](../AGENTS.md) и [`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

День 19 — копия дня 18 плюс **MCP-инструменты композиции и декларативный
пайплайн**. Свой MCP-сервер дня получил три новых инструмента: `search` (найти
данные в источнике — лента jsonplaceholder, файл внутри папки дня или таблица
базы дня), `summarize` (сводка списка элементов и ключевые пункты; при
недоступности DeepSeek — агрегация) и `save_to_file` (запись текста в файл
каталога `output/`) — всего инструментов девять. Пайплайн описывается ДАННЫМИ
(`backend/domain/pipeline_spec.py`): список шагов, аргументы со ссылками
(`{имя}` — аргумент запуска, `$steps.<i>.<путь>` — выход предыдущего шага) и
необязательное условие перехода (`non_empty`/`empty`/`equals`/`contains`).
Прогон идёт по шагам, а каждый шаг логируется в SQLite (`pipeline_runs`,
`pipeline_steps`: инструмент, входные аргументы, выходной результат, время,
статус, текст ошибки). Добавились роутер `/pipelines` (5 эндпоинтов), раздел
«🔀 Пайплайны» в Streamlit (подключение, форма запуска, прогресс по шагам
фрагментом раз в секунду, схема потока данных с объёмами, история запусков) и
строка «🔀 Пайплайн: …» в сводке хода агента. Нового процесса день не заводит:
фоновая часть прогона — поток процесса бэкенда; отдельным процессом по-прежнему
запускается только собственный MCP-сервер — по stdio, на время вызова
инструментов.

Унаследовано полностью: планировщик фоновых задач (день 18) с шестью таблицами,
свой MCP-сервер и вызов инструмента агентом с правилами допуска (`mcp_*`),
контролируемые переходы (день 15) и инварианты (день 14), состояние задачи как
конечный автомат (день 13), персонализация профилем (день 12), три слоя памяти и
четыре стратегии контекста (день 11). MCP-подключение, как и раньше, таблиц в БД
не имеет: соединение живёт в памяти процесса (`MCPRegistry`), а вызовы читающих
инструментов идут **наружу** (HTTP-запрос к jsonplaceholder).

Пайплайн добавляет **две новые таблицы** — `pipeline_runs` (запуск: имя, статус,
начало, конец, длительность) и `pipeline_steps` (шаг прогона). Журнал лежит в
SQLite, а не в памяти, потому что прогон может идти в фоновом потоке: интерфейс
опрашивает статус и видит прогресс, пока шаги выполняются. Удаление запуска
уносит его шаги каскадом (`ON DELETE CASCADE`).

## Раскладка

```
day19/
├── app.py                    # точка входа Streamlit (67 строк): set_page_config + вызовы секций
├── mcp_server/               # СОБСТВЕННЫЙ MCP-сервер дня (транспорт stdio, 11 модулей)
│   ├── __init__.py           # докстринг пакета: как запускается (`uv run python mcp_server/server.py`) и чем говорит
│   ├── config.py             # адрес jsonplaceholder, адрес бэкенда дня (DAY19_BACKEND_URL), границы аргументов, каталог output/, источники file:/sqlite:, имя, версия и инструкция сервера
│   ├── schemas.py            # TypedDict-ответы девяти инструментов (+ SearchItem, SearchResult, SummaryResult, SavedFile) → outputSchema
│   ├── api_client.py         # HTTP-клиент jsonplaceholder: ExternalAPIError, configure/get_client, list_posts/list_users (страницы для поиска)
│   ├── backend_api.py        # клиент бэкенда дня: BackendAPIError, ScheduleBackendClient (единственный вызов POST /scheduler/tasks)
│   ├── search_sources.py     # источники search: parse_source, file: (блоки файла дня), sqlite: (белый список таблиц, только чтение), лента API
│   ├── summarize_logic.py    # сводка без LLM: стиль, промпт, разбор ключевых пунктов, агрегация
│   ├── llm_client.py         # необязательный вызов DeepSeek внутри summarize (без ключа — агрегация)
│   ├── file_writer.py        # запись результата save_to_file в output/ (чистка имени, форматы txt/md/json)
│   ├── pipeline_tools.py     # три инструмента композиции и register_pipeline_tools
│   └── server.py             # MCPServer, девять инструментов, _run/_scheduled, parse_args (--api-base, --timeout, --backend-url, --output-dir, --file-root, --db-path, --llm), main
├── frontend/                 # Streamlit UI по секциям (20 модулей + __init__.py)
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # FastAPI: 9 роутеров по доменам + сборка app (main.py) и lifespan.py, 78 эндпоинтов
│   ├── core/                 # config, dependencies — настройки и доступ к менеджеру, MCP-реестру и планировщику
│   ├── domain/               # чистые правила и данные: 36 модулей — FSM задачи/сжатия/MCP/планировщика/пайплайна, графы переходов, расписания, агрегация, распознавание реплик, описание пайплайна и маппинг его данных, стратегии, профиль, инварианты, тексты промпта
│   ├── services/             # прикладные сервисы: compressor, task_state, invariant_checker, mcp_*, scheduler, schedule_service, scheduled_jobs, apscheduler_bridge, source_fetch, pipeline, pipeline_service
│   ├── storage/              # доступ к БД: database, task_store, invariant_store, memory_rows, scheduler_store, scheduler_data_store, scheduler_rows, pipeline_store, pipeline_rows
│   ├── agents/               # Agent, MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы SQLAlchemy по доменам (+ scheduler.py — шесть таблиц планировщика, + pipeline.py — запуск и шаг прогона)
│   ├── schemas/              # Pydantic-схемы API по доменам (+ mcp.py, scheduler.py, pipeline.py)
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 1374 теста (unit/ — 888, integration/ — 336, e2e/ — 150)
│   ├── scheduler_fakes.py    # фейки планировщика: FakeFetcher, SchedulerStub, posts_payload
│   ├── pipeline_fakes.py     # фейки пайплайна: каталог трёх инструментов, FakePipelineClient, make_pipeline_registry
│   ├── search_sources_fakes.py # материал тестов источников search: блоки заметок, строки таблиц, заглушка клиента ленты
│   ├── backend_stub.py       # локальный HTTP-стенд бэкенда дня (POST /scheduler/tasks) для stdio-теста инструментов
│   ├── mcp_fakes.py          # MCP-фейки: FakeMCPClient, FAKE_MCP_TOOLS, FAKE_TOOL_CATALOG, make_mcp_factory
│   ├── mcp_echo_server.py    # унаследованный из дня 16 тестовый MCP-сервер по stdio (инструменты echo и add)
│   └── stub_api.py           # локальный HTTP-стенд jsonplaceholder: тесты сервера идут без сети
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов
│   ├── pipeline_demo.py      # день 19: оркестрация четырёх сценариев пайплайна (свой MCP-сервер, журнал, отчёт)
│   ├── pipeline_scenarios.py # день 19: четыре сценария (успех, пустой поиск, ошибка шага, реплика агента)
│   ├── pipeline_report.py    # сборка markdown-отчёта дня 19 (9 разделов, таблица шагов) из данных прогона
│   ├── scheduler_demo.py     # день 18: оркестрация четырёх сценариев (стенд, MCP-клиент, аргументы, отчёт)
│   ├── scheduler_scenarios.py # день 18: четыре сценария (напоминание, сбор, сводка, перезапуск) и данные прогона
│   ├── scheduler_report.py   # сборка markdown-отчёта дня 18 (9 разделов) из DemoRun
│   ├── scheduler_stand.py    # день 18: изолированный бэкенд прогона (своя БД, заглушка модели, детерминированный источник)
│   ├── mcp_tool_demo.py      # унаследовано из дня 17: каталог, три успешных и три отказных вызова, шаг агента → отчёт
│   ├── mcp_tool_report.py    # унаследовано из дня 17: сборка markdown-отчёта (7 разделов) из DemoRun
│   ├── mcp_demo.py           # день 16: подключение к MCP-серверу и печать списка инструментов
│   ├── controlled_transitions_demo.py # унаследовано из дня 15: правила допуска, пауза в новом процессе, отказ агента
│   ├── transitions_report.py # сборка отчёта контролируемых переходов
│   ├── video_scenario.py     # унаследовано из дня 15: точка входа прогона (--all/--auto/--ui/--reset/--serve) и оркестрация
│   ├── video_scenario_checks.py # печать кадров и проверок (VideoChecks) и отчёт о финале
│   ├── video_scenario_client.py # HTTP-клиент прогона и путь БД video_scenario.db
│   ├── video_scenario_frames.py # кадры 0–9 по HTTP: домен, отказ, перезапуск бэкенда, журнал
│   ├── video_scenario_ui.py  # UI-кадры сценария: реальный рендер через streamlit.testing AppTest
│   ├── video_scenario_browser.py # набор действий в браузере: клики, сверки, человеческий темп
│   ├── video_scenario_browser_frames.py # кадры 0–9 в настоящем браузере (Chromium)
│   ├── video_scenario_stand.py # стенд для съёмки: живой Streamlit + браузер + чек-лист кадров
│   ├── video_scenario_server.py # бэкенд прогона на изолированной БД: заглушка DeepSeek и жизненный цикл процесса
│   ├── invariants_demo.py    # три сценария инвариантов → invariants_demo.md (офлайн)
│   ├── seed_invariants.py    # посев демо-инвариантов в БД (--reset/--db)
│   ├── task_state_demo.py    # демонстрация состояния задачи (--all/--phase/--reset)
│   ├── task_demo_report.py   # сборка отчёта демонстрации
│   ├── personalization_comparison.py  # унаследованный прогон отчёта персонализации (день 12)
│   ├── comparison_report.py  # сборка отчёта сравнения профилей
│   └── comparison_stub.py    # офлайн-заглушка (её же используют демо состояния задачи и переходов)
├── invariants_demo.md        # отчёт о трёх сценариях инвариантов (в корне дня — по заданию дня 14)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── pyproject.toml, uv.lock   # зависимости (uv): прямые — в pyproject (включая mcp, httpx, apscheduler), точные версии — в локе
├── .agents/skills/           # скиллы библиотек (uvx library-skills --copy); на Windows симлинки недоступны
├── .python-version           # 3.14 (версия для `uv sync`)
├── .env.example              # шаблон ключа DEEPSEEK_API_KEY (он же нужен инструменту summarize) и адреса бэкенда DAY19_BACKEND_URL
├── output/                   # каталог результатов save_to_file (артефакты прогона, в git попадают только примеры)
└── agents.db                 # SQLite (в .gitignore по *.db)
```

Отчёты прогонов лежат в `docs/reports/`: `pipeline_demo.md` — отчёт дня 19 (его
создаёт `uv run python scripts/pipeline_demo.py --report docs/reports/pipeline_demo.md`;
там же обязательная таблица «шаг | инструмент | входные данные | выходные данные |
время выполнения | статус» и приложенный файл из `output/`),
`scheduler_demo.md` — отчёт дня 18 (его
создаёт `uv run python scripts/scheduler_demo.py --report docs/reports/scheduler_demo.md`),
`mcp_tool_demo.md` (день 17; создаёт
`uv run python scripts/mcp_tool_demo.py --report docs/reports/mcp_tool_demo.md`),
`mcp_demo.md` (день 16), `task_state_demo.md` (день 13) и
`personalization_comparison.md` (день 12) — унаследованы. Отчёт
`invariants_demo.md` — в корне дня: путь задан заданием дня 14, в `docs/reports/`
он не дублируется. Скрипты в `scripts/` не пакет: они находят корень дня
(`Path(__file__).resolve().parents[1]`) и добавляют его в `sys.path` сами,
поэтому `uv run python scripts/<script>.py` работает из любой рабочей
директории; `mcp_server/` — наоборот, пакет со своим корнем дня в `sys.path`
(без этого `python mcp_server/server.py` не видит относительных импортов).

## Слои `backend/`

| Слой | Модули | Назначение |
|---|---|---|
| `core/` | `config.py` (246), `dependencies.py` (102), `__init__.py` (22) | Настройки дня («MCP (день 17)», «Планировщик (день 18)», «Композиция MCP-инструментов (день 19)») и зависимости роутов: `get_manager`, `get_mcp_registry`, `get_scheduler`, `get_schedule_service`, `get_pipeline_service`, `agent_or_404`, `task_or_404`, `invariant_or_404` |
| `domain/` | 36 модулей + `__init__.py` (399) | Чистые правила и данные: FSM задачи, сжатия, MCP-подключения, вызова инструмента и планировщика (задача и напоминание), графы допуска и guards переходов, правила допуска вызова и его код причины, распознавание запроса и реплик планировщика, расписания и их арифметика, агрегация накопленных записей, блоки данных для промпта, каталог серверов, стратегии, факты, слои памяти, профиль, инварианты, тексты промпта, разбор цели MCP и структура инструмента. Знают только stdlib, `core.config` и соседей по слою |
| `storage/` | `database.py` (58), `task_store.py` (278), `invariant_store.py` (255), `memory_rows.py` (47), `scheduler_store.py` (196), `scheduler_data_store.py` (245), `scheduler_rows.py` (177), `pipeline_store.py` (145), `pipeline_rows.py` (48), `__init__.py` (141) | Движок и сессии, ORM-строки → словари, `TaskStateStore`, `InvariantManager`, `SchedulerStore`, `SchedulerDataStore`, `PipelineStore` (запуски пайплайна и журнал шагов; `pipeline_rows` — строки в словари) |
| `services/` | `compressor.py` (329), `task_state.py` (392), `invariant_checker.py` (296), `mcp_client.py` (392), `mcp_transport.py` (65), `mcp_errors.py` (95), `mcp_loop.py` (96), `mcp_registry.py` (138), `mcp_tool_runner.py` (144), `scheduler.py` (369), `schedule_service.py` (305), `scheduled_jobs.py` (176), `apscheduler_bridge.py` (161), `source_fetch.py` (61), `pipeline.py` (195), `pipeline_service.py` (198), `__init__.py` (145) | `ContextCompressor`, `TaskStateMachine` (граф, guards, единая точка отказа), `InvariantChecker`, `MCPClient` (соединение и вызов инструмента), `MCPEventLoop` (цикл событий в потоке), `MCPRegistry` (одно подключение на процесс), `MCPToolRunner` (допуск → вызов → исход), `TaskScheduler` (сверка БД ↔ APScheduler, тики), `ScheduleService` (операции инструментов), `scheduled_jobs` (что делает тик), `apscheduler_bridge` (триггеры и классы библиотеки), `source_fetch` (единственный выход фона в сеть): оркестрация домена, хранилища и внешних процессов |
| `agents/` | `agent.py` (2009 ⚠️), `memory.py` (291), `profile_store.py` (292), `agent_manager.py` (99), `manager_*.py` (7 файлов), `__init__.py` (57) | `Agent` (шаги пайплайна `apply_pipeline` и MCP/планировщика `apply_mcp_tool` в `generate`), `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов; менеджер передаёт созданным и восстановленным агентам реестр MCP и службу пайплайнов |
| `models/` | `agent.py` (93), `message.py` (41), `context.py` (157), `memory.py` (81), `user_profile.py` (57), `task_state.py` (119), `invariant.py` (51), `scheduler.py` (211), `pipeline.py` (89), `__init__.py` (70) | ORM-таблицы SQLAlchemy: `agents`, `short_term_messages`, `summaries`/`token_usage`/`facts`/`checkpoints`, `working_memory`/`long_term_memory`, `user_profiles`, `task_states`/`task_transitions`, `invariants`, шесть таблиц планировщика и две таблицы пайплайна — `pipeline_runs`/`pipeline_steps` |
| `schemas/` | `agent.py` (346), `context.py` (218), `memory.py` (173), `profile.py` (170), `task.py` (170), `invariant.py` (149), `mcp.py` (193), `scheduler.py` (313), `pipeline.py` (150), `__init__.py` (239) | Pydantic-схемы API по доменам (в `agent.py` — поле `pipeline` ответа генерации), реэкспорт из `schemas/__init__.py` |
| `api/` | `agents.py` (301), `context.py` (140), `memory.py` (180), `profiles.py` (126), `tasks.py` (246), `invariants.py` (139), `mcp.py` (180), `scheduler.py` (355), `pipelines.py` (146), `lifespan.py` (49), `main.py` (79), `__init__.py` (40) | 78 эндпоинтов по доменам, старт и остановка фоновых служб (`lifespan.py`) и сборка `app` |
| `utils/` | `__init__.py` (9) | Своего кода нет: общий (клиент DeepSeek, база, токены, логи) — в repo-level `shared/` |

Пакеты `core`, `domain`, `services`, `storage`, `agents`, `models`, `schemas`,
`api` содержат `__init__.py` с реэкспортом публичных имён слоя — это
единственное место, где видно публичный контракт слоя. `api/__init__.py`
намеренно **не** импортирует `main`: `core.dependencies.get_manager` тянет
`api.main` лениво, и ранний импорт создал бы цикл `api → core → api`.

У `domain/__init__.py` модули планировщика (день 18) и пайплайна (день 19)
импортируются **как модули** (`from . import aggregation, pipeline_spec,
schedule_spec, …`), иначе общий список имён слоя вышел бы за лимит 400 строк. Код
дня и так берёт имена из своего модуля
(`from ..domain.pipeline_spec import DEFAULT_PIPELINE`), поэтому точки входа
`backend.domain.pipeline_fsm` и соседей достаточно. По той же причине в
`backend/services/__init__.py` новые модули добавлены и в список `from . import (…)`,
и в `__all__` именами (`TaskScheduler`, `ScheduleService`, `fetch_json`, `prepare`,
`tick`), а сами модули планировщика — как модули (`scheduler`,
`schedule_service`, `scheduled_jobs`, `source_fetch`, `apscheduler_bridge`).

Два импорта отложены намеренно (разрыв циклов `storage ⇄ agents` и
`core ⇄ agents`); поведение от этого не меняется:
`storage/task_store.py` берёт `MemoryManager` внутри свойства `memory_manager`, а
`core/dependencies.py` — `AgentManager` только под `TYPE_CHECKING` (для аннотации).

## Состояние задачи (день 13) — модули и что в них изменил день 15

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/task_fsm.py` | 366 | FSM шагов ВНУТРИ этапа: `TaskStage`/`TaskStep`/`TaskEvent` (`Enum`), классы-этапы с `handle(event, step)`, `STAGE_STEPS`, `InvalidTransitionError`. Таблицы переходов между этапами здесь больше нет — она в `task_state_machine.py` |
| `backend/domain/task_prompt.py` | 190 | Тексты блока состояния для системного промпта: ожидаемые действия, завершённые этапы, допустимые следующие этапы, `render_task_state_block` |
| `backend/domain/task_intent.py` | 89 | Распознавание намерения в реплике (`пауза`/`продолжи`/`откат`/`подтверждаю`) по таблице фраз с приоритетом групп |
| `backend/storage/task_store.py` | 278 | `TaskStateStore`: единственное место работы с таблицами `task_states`/`task_transitions` (чтение, журнал, запись перехода, `log_rejection`, `set_flags`) |
| `backend/services/task_state.py` | 392 | `TaskStateMachine`: публичный контракт переходов (create/pause/resume/advance/rollback/transition_to/set_flags) и единая точка отказа `_reject` |
| `backend/models/task_state.py` | 119 | ORM: `TaskState` (`task_states`, колонка `paused_from_stage`) и `TaskTransition` (`task_transitions`, колонка `accepted`) |
| `backend/agents/manager_tasks.py` | 96 | Миксин `TaskOpsMixin`: тонкие обёртки для API; умолчания шага и действия разрешает сервис |
| `backend/schemas/task.py` | 170 | Схемы API: `TaskStateOut`, `TaskTransitionOut`, `TaskBlockedOut`, `TaskAllowedNextOut`, `TaskFlagsIn`, `TaskCreateIn`, `TaskRollbackIn`, `TaskTransitionIn`, `TaskHistoryOut` |
| `backend/api/tasks.py` | 246 | Роутер: 11 эндпоинтов состояния задачи |
| `frontend/task_panel.py` | 181 | Раздел «🧭 Состояние задачи»: этап, шаг, схема FSM, вкладки журнала; кнопки переходов — в `task_transitions.py` |

Почему `TaskStateMachine` и `TaskStateStore` — разные модули: это граница слоёв
`services/` и `storage/` (та же, что у `ContextCompressor` и `MemoryManager`):
поведение (какие переходы допустимы) отдельно от хранения (сессии SQLAlchemy и
таблицы). Машину читают, не отвлекаясь на ORM; хранилище тестируется без
автомата. Побочный эффект — оба файла укладываются в лимит 400 строк (вместе они
дали бы 670).

## Контролируемые переходы (день 15) — новые модули

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/task_state_machine.py` | 381 | Единственный источник правил допуска: граф `ALLOWED_TRANSITIONS`, `GUARDS` и флаги (`FLAG_PLAN_APPROVED`, `FLAG_IMPLEMENTATION_COMPLETE`, `FLAG_VALIDATION_PASSED`, `STAGE_FLAG`, `TASK_FLAGS`), тексты отказа и подсказки (`transition_explanation`, `transition_error_message`, `transition_hint`, `intent_refusal_notice`), запросы к состоянию (`can_transition`, `is_transition_allowed`, `get_allowed_next_stages`, `get_blocked_stages`, `guard_context`, `cleared_flags`), `STAGE_DISPLAY_ORDER` |
| `backend/domain/task_proposal.py` | 91 | Распознавание предложения модели перейти в этап: `STAGE_PROPOSAL_PHRASES`, `detect_stage_proposal` (при нескольких совпадениях — самый дальний этап) |
| `frontend/task_transitions.py` | 188 | Блок переходов панели задачи: кнопки-этапы с `disabled` и причиной в `help`, «🔒 Заблокированные переходы», «⏭ Следующий шаг», пауза/продолжение с выбором этапа возврата, чекбоксы флагов и «💾 Сохранить флаги». Продолжение в свой этап идёт эндпоинтом `/resume` (сохраняет шаг, как обещает подпись), в другой этап — прямым переходом |
| `scripts/controlled_transitions_demo.py` | 396 | Офлайн-демонстрация в два процесса: недопустимые переходы с причинами, флаги согласования, пауза и продолжение, отказ агента на предложение модели → `docs/reports/controlled_transitions_demo.md` |
| `scripts/transitions_report.py` | 138 | Сборка markdown-отчёта контролируемых переходов |
| `scripts/video_scenario.py` | 280 | Точка входа: CLI (`--all`/`--auto`/`--ui`/`--reset`/`--serve`), оркестрация кадров 0–9 по HTTP (`run`) и в браузере (`run_in_browser`) и один контур отказа (`_guarded`: занятая БД, неготовый бэкенд, невыполненное действие кадра и расхождение проверки — строка «✗ прогон остановлен» и код 1) |
| `scripts/video_scenario_checks.py` | 69 | Печать кадров и проверок: `VideoChecks` (``✓``/``✗`` с доказательством), `ScenarioFailed` — остановка прогона, `summary` — финал с двумя pid и именем БД |
| `scripts/video_scenario_client.py` | 83 | HTTP-клиент прогона (`ApiClient` — те же запросы, что делает фронтенд) и путь БД прогона `video_scenario.db`; конфигурация агента прогона |
| `scripts/video_scenario_browser.py` | 219 | Набор действий в реальном браузере (`BrowserActions`): прокрутка и наведение перед кликом, набор текста по символам, ожидание строки на странице, сверка блокировки кнопок, флаги, темп демонстрации кадров (`--pace` — по умолчанию 2 с на действие, `--typing` — 120 мс на символ: весь прогон 3–4 минуты) |
| `scripts/video_scenario_browser_frames.py` | 267 | Кадры 0–9 в настоящем браузере: класс `Walk(BrowserActions)` и заголовки кадров — что нажать и что должно появиться на экране |
| `scripts/video_scenario_frames.py` | 356 | Кадры 0–9: таблицы домена, проверки по HTTP, перезапуск бэкенда с доказательством двух pid, журнал двух задач |
| `scripts/video_scenario_ui.py` | 386 | UI-кадры кадров 0–9 через `streamlit.testing.v1.AppTest`: реальный рендер `app.py`, нажатия кнопок и чтение карточки, подписей, причин отказа и вкладок журнала |
| `scripts/video_scenario_stand.py` | 145 | Стенд для съёмки (режим `--ui`): поднимает живой `streamlit run app.py` на изолированном бэкенде прогона, открывает адрес в браузере, печатает чек-лист кадров §8 и по Enter доказывает кадр 5 (перезапуск бэкенда, два pid, состояние из SQLite) |
| `scripts/video_scenario_server.py` | 310 | Бэкенд прогона и UI-стенда: офлайн-заглушка DeepSeek, uvicorn на `video_scenario.db` (подмены `main.get_manager`, `database.init_db`, `Agent._make_client`) и жизненный цикл процессов (`Backend`: старт, готовность, pid, остановка; `UiServer`: `streamlit run` и эндпоинт здоровья) |

**Почему прогон кадров — восемь модулей, а не один скрипт.** Прогон делает
разные вещи разными средствами: печатает проверки и останавливается на
расхождении (`video_scenario_checks.py`), ходит в бэкенд по HTTP
(`video_scenario_client.py`), проходит кадры по API (`video_scenario_frames.py`),
рендерит интерфейс без браузера (`video_scenario_ui.py`), ведёт настоящий
браузер (`video_scenario_browser.py` — действия, `video_scenario_browser_frames.py`
— кадры), поднимает стенд для съёмки (`video_scenario_stand.py`) и запускает
процессы бэкенда и Streamlit (`video_scenario_server.py`); точка входа
(`video_scenario.py`) остаётся CLI и оркестрацией. Одним файлом это 2106 строк —
впятеро больше лимита 400 из `AGENTS.md`, а смешивать HTTP, Streamlit, Playwright
и uvicorn в одном модуле значило бы, что дочернему процессу бэкенда импортируется
ещё и AppTest с Chromium.

Отдельная причина, по которой общие части (`checks`, `client`) вынесены из точки
входа: она запускается как ``__main__``, и её импорт по имени (``from
video_scenario import …``) создаёт ВТОРУЮ копию модуля. Исключение из копии не
ловится ``except`` в ``__main__`` — падение печаталось трассировкой вместо строки
«✗ прогон остановлен». Теперь все режимы импортируют один и тот же объект класса.

Границы совпадают с границами исполнения: бэкенд прогона, Streamlit и браузер —
разные процессы у разных режимов, а строгая проверка (`--all`, AppTest), проход в
браузере (`--auto`, Playwright) и стенд (`--ui`, кадры проходит человек) — три
режима с одними и теми же кадрами §8.

**Разделение обязанностей двух модулей домена.** `backend/domain/task_fsm.py`
отвечает на вопрос «что происходит ВНУТРИ этапа»: события
(`advance`/`rollback`/`pause`/`resume`), шаги этапа и явные ошибки на неописанное
событие (`UnknownTaskEvent`, `InvalidTransitionError`). `task_state_machine.py`
отвечает на вопрос «можно ли ПЕРЕЙТИ из этапа в этап»: таблица
`ALLOWED_TRANSITIONS`, guard-условия `GUARDS` и тексты отказа. Поэтому автомат
шагов и проверка графа вызываются подряд: последний шаг `planning` не выпускает
задачу в `execution`, пока не выставлен флаг `plan_approved`, — отказ приходит из
guard, а не из класса этапа. Разделение заодно держит `task_fsm.py` в лимите
400 строк.

## MCP (день 17) — свой сервер, вызов инструмента и правила допуска

Новые модули дня 17 (унаследованные от дня 16 модули подключения — в таблице
ниже под ними):

| Модуль | Строк | Назначение |
|---|---|---|
| `mcp_server/__init__.py` | 23 | Докстринг пакета: собственный MCP-сервер дня 17, запуск `uv run python mcp_server/server.py`, транспорт stdio и JSON-RPC по stdin/stdout |
| `mcp_server/config.py` | 30 | Константы сервера: `DEFAULT_API_BASE` (jsonplaceholder), `DEFAULT_TIMEOUT`, `MAX_POSTS_LIMIT`, `MAX_USER_ID`, `SERVER_NAME`, `SERVER_VERSION`, `SERVER_INSTRUCTIONS` |
| `mcp_server/schemas.py` | 48 | `TypedDict`-ответы инструментов: `UserInfo`, `PostInfo`, `PostSummary`, `UserPosts`; по ним SDK публикует `outputSchema`, а `structuredContent` ответа равен самому словарю |
| `mcp_server/api_client.py` | 145 | HTTP-клиент внешнего API: `ExternalAPIError`, `JsonPlaceholderClient` (`get_user`, `get_post`, `list_user_posts`), модульный `configure`/`get_client`; 404 даёт понятный текст про 10 пользователей, прочие сбои — «Внешний API … недоступен» |
| `mcp_server/server.py` | 144 | `MCPServer(name, version, instructions)` и три инструмента через `@server.tool()` (`get_user(user_id: int) -> UserInfo`, `get_post(post_id: int) -> PostInfo`, `list_user_posts(user_id: int, limit: int = 5) -> UserPosts`); `_run` переводит `ExternalAPIError` в `ToolError`, `parse_args` (`--api-base`, `--timeout`), `main()` → `server.run(transport="stdio")` |
| `backend/domain/mcp_tool_call.py` | 386 | Жизненный цикл вызова и правила допуска: `MCPToolCallState`/`MCPToolCallEvent` (`Enum`), `MCPToolCallFSM` и классы состояний, `UnknownMCPToolCallEvent`, коды причин (`REASON_NOT_CONNECTED`/`UNKNOWN_TOOL`/`BAD_ARGUMENTS`/`TRANSPORT`/`TOOL_ERROR`), `ARGUMENTS_HINT`, `find_tool`, `admission_reason` (проверка соединения → наличия инструмента → обязательных и лишних аргументов → типов по `input_schema`), `MCPToolCallOutcome` со свойством `called` и `to_dict()` |
| `backend/domain/mcp_intent.py` | 134 | Распознавание запроса по ключевым словам: `INTENT_RULES` в порядке приоритета (`list_user_posts` → `get_user` → `get_post`), морфология через границы слова, `classify_tool_call(text, available_tools)` → `MCPToolCallPlan` (правило применяется только если его инструмент есть в каталоге; номер аргумента — первое `\d+`) |
| `backend/domain/mcp_prompt.py` | 52 | Текст блока данных для системного промпта: `MCP_BLOCK_HEADER = "## Данные MCP-инструмента"`, `render_mcp_tool_block(outcome)` — пустая строка, если вызов не `done` |
| `backend/domain/mcp_servers.py` | 104 | Каталог известных серверов: `KNOWN_SERVERS` (свой сервер дня 17, `fetch`, `filesystem`), `MCPServerOption` с `matches`/`to_dict`, `server_records(connected_target, tool_count)` — `connected` ровно у одного |
| `backend/services/mcp_loop.py` | 96 | `MCPEventLoop`: цикл событий в daemon-потоке, `submit`/`spawn`/`call_soon`/`stop`/`running` и `SUBMIT_GRACE` — мост из синхронного кода к асинхронному SDK (вынесен из `mcp_client.py`) |
| `backend/services/mcp_transport.py` | 65 | Адаптеры SDK: `transport_context(target)` (stdio/SSE/Streamable HTTP), `server_info(init)`, `raw_parts(raw)` — разбор `CallToolResult` на структуру, текст и `is_error` (вынесены из `mcp_client.py`) |
| `backend/services/mcp_tool_runner.py` | 144 | `MCPToolRunner`: единственное место, где домен встречается с реестром — `status`/`connected`/`available_tools`, `call(tool, arguments)` (правила допуска → вызов → исход с кодом причины) и `call_for_prompt(prompt)` (распознавание по реплике) |
| `frontend/mcp_call.py` | 199 | Прямой вызов инструмента в UI: `render_servers` (таблица каталога серверов и кнопка подключения), `render_tool_call` (форма аргументов по `input_schema` + «▶ Вызвать инструмент»), `render_call_result` (состояние, длительность, результат, ошибка) |
| `frontend/mcp_ask.py` | 134 | «🤖 Спросить агента»: `render_ask_agent` (агент, запрос, вызов `/agents/{id}/generate`) и `render_ask_result` (ответ агента + отчёт `record["mcp"]` и данные инструмента) |
| `scripts/mcp_tool_demo.py` | 365 | Сквозной прогон дня 17: каталог своего сервера, три успешных и три отказных вызова, шаг агента с офлайн-заглушкой DeepSeek; ключи `--target`, `--api-base`, `--timeout`, `--live`, `--tests`, `--json`, `--report` |
| `scripts/mcp_tool_report.py` | 326 | Сборка markdown-отчёта дня 17 из `DemoRun`: что проверялось, какой API, сервер и инструменты, вызовы, как агент использовал результат, автотесты, что за рамками |
| `tests/mcp_fakes.py` | 211 | MCP-фейки тестов: `FakeMCPClient` (с `call_tool` и журналом `call_calls`, сценарии `call_result`/`call_error`/`call_fail`), `FAKE_MCP_TOOLS`, `FAKE_MCP_SERVER`, `FAKE_TOOL_CATALOG`, `make_mcp_factory` |
| `tests/stub_api.py` | 124 | Локальный HTTP-стенд jsonplaceholder (`http.server` на `127.0.0.1:0`): ручки `/users/{id}`, `/posts/{id}`, `/posts?userId=&_limit=`; так тесты сервера идут без сети |

Обновлены днём 17:

| Модуль | Строк | Что изменилось |
|---|---|---|
| `backend/domain/mcp_tools.py` | 114 | К `MCPToolInfo` добавлено поле `output_schema` (и нормализация в `{}`), появился `MCPToolResult` (tool, arguments, structured, text, is_error, duration_ms) со своим `to_dict` |
| `backend/services/mcp_client.py` | 392 | Добавлен `call_tool` (`tools/call`): общая проверка готовности `_ready_or_raise`, разбор `CallToolResult` — через `mcp_transport.raw_parts`, цикл событий — через `mcp_loop`; каталог читает и `output_schema` |
| `backend/services/mcp_errors.py` | 95 | Новый `MCPCallError` и `ACTION_LABELS["call"] = "Не удалось вызвать инструмент MCP-сервера"` |
| `backend/services/mcp_registry.py` | 138 | Новый `call_tool` с тем же guard «реестр пуст → нет соединения», что у `tools()` |
| `backend/services/__init__.py` | 102 | Реэкспорт `MCPToolRunner`, `MCPCallError`, `MCPEventLoop`, `mcp_transport` |
| `backend/domain/__init__.py` | 373 | Реэкспорт имён вызова: `MCPToolCallState`, `MCPToolCallFSM`, `MCPToolCallOutcome`, `MCPToolResult`, `classify_tool_call`, `admission_reason`, `server_records`, `render_mcp_tool_block` и коды причин |
| `backend/core/config.py` | 194 | Раздел «MCP (день 17)»: `MCP_DEFAULT_TARGET` — свой сервер (`uv run python mcp_server/server.py`), плюс `MCP_FETCH_TARGET`, `MCP_FILESYSTEM_TARGET`, `MCP_TIMEOUT`, `MCP_MAX_TOOL_PAGES`, `MCP_TARGET_MAX`, `MCP_TOOL_NAME_MAX` |
| `backend/agents/agent.py` | 1898 | Метод `apply_mcp_tool(prompt, payload)` (вызов через `MCPToolRunner`, блок данных в системное сообщение, счёт токенов) и `_append_system_block`; в `generate` поле `record["mcp"]` заполняется после проверки инвариантов и до контроля лимита (+73 строки к дню 16) |
| `backend/agents/agent_manager.py` | 92 | Параметр `mcp_registry` в конструкторе — реестр передаётся созданным и восстановленным агентам |
| `backend/agents/manager_agents.py` | 251 | `mcp_registry=self._mcp_registry` в обоих местах создания `Agent` (`create_agent`, `restore_from_db`) |
| `backend/schemas/agent.py` | 336 | В `GenerateResponse` добавлено поле `mcp: Optional[MCPCallReportOut]` |
| `backend/schemas/mcp.py` | 193 | `output_schema` в `MCPToolSchema`; новые `MCPCallIn`, `MCPCallResponse`, `MCPCallReportOut`, `MCPServerSchema`, `MCPServersResponse` |
| `backend/api/mcp.py` | 180 | Добавлены `POST /mcp/call` (400/409/502, ошибка инструмента — тело с `is_error: true`) и `GET /mcp/servers`; всего шесть эндпоинтов |
| `backend/api/agents.py` | 274 | Корневой инвентарь эндпоинтов дополнен двумя MCP-путями, обновлены счётчики |
| `frontend/mcp_api.py` | 51 | `api_mcp_call(tool, arguments)` и `api_mcp_servers()` |
| `frontend/mcp_section.py` | 266 | Цель по умолчанию — свой сервер, показ `output_schema`, вызовы блоков вызова и «Спросить агента» |
| `frontend/common.py` | 348 | Подписи `MCP_CALL_STATE_LABELS`/`MCP_REASON_LABELS` и ключи `mcp_last_call`, `mcp_last_ask` |
| `frontend/chat_section.py` | 301 | Строка про MCP-вызов в сводке хода |
| `app.py` | 71 | `page_title="MCP-инструменты · День 17"` (значок 🔧) |

**Почему сервер — отдельный пакет в корне дня, а не модуль `backend/`.** Сервер
не часть FastAPI-приложения: приложение запускает его отдельным процессом по
stdio (`MCP_DEFAULT_TARGET = "uv run python mcp_server/server.py"`), а соединяется
с ним уже унаследованный от дня 16 `MCPClient`. Пакет не импортирует ни
`backend/*`, ни `shared/*` — ему нужны только stdlib, `httpx` и SDK `mcp`;
в слоях `backend/` такой код оказался бы «чужим» слоем, поэтому в дереве дня он
стоит рядом с `frontend/`.

**Путь вызова.** UI (`POST /mcp/call`) или агент → `MCPToolRunner` → правила
допуска (`admission_reason` и `MCPToolCallFSM`) → `MCPRegistry.call_tool` →
`MCPClient.call_tool` (через `MCPEventLoop`) → `tools/call` по stdio → HTTP-запрос
к jsonplaceholder. Результат возвращается как `MCPToolResult`: ошибка самого
инструмента приходит **данными** (`is_error`), а отказ транспорта —
исключением (`MCPCallError` → 502 в API).

**Как результат попадает в промпт агента.** `Agent.apply_mcp_tool` вызывает
`MCPToolRunner.call_for_prompt(prompt)`, и если исход `done`, `render_mcp_tool_block`
собирает блок «## Данные MCP-инструмента» с аргументами и JSON-результатом,
`_append_system_block` дописывает его в системное сообщение готового `payload`, а
добавленные токены считает `count_tokens` и учитывает контроль лимита. Наружу
виден отчёт `record["mcp"]` (состояние, инструмент, аргументы, ошибка, сколько
токенов добавил блок) — и в ответе `POST /agents/{id}/generate`, и в сводке хода
раздела «💬 Чат и память».

**Почему шаг стоит после проверки инвариантов и до контроля лимита.** Вызов
инструмента — действие с побочным эффектом: наружу уходит HTTP-запрос. Проверка
инвариантов бесплатна и локальна, поэтому отказ по инвариантам не должен платить
за вызов — запрос к серверу уходит только когда правила пропустили ход. При этом
добавленный в промпт блок обязан попасть под контроль лимита, поэтому `mcp`-шаг
завершается до проверки размера контекста.

**Почему правил допуска и вызова два модуля.** `mcp_tool_call.py` — чистые
правила над каталогом и аргументами (граф, коды причин, типы из `input_schema`):
проверяются без процессов и сети. `mcp_tool_runner.py` — оркестрация с реестром
(статус, каталог, сам вызов, сборка исхода), единственное место, где домен
встречается с сервисом. Один файл дал бы около 530 строк и смешал бы чистые
правила с потоками. По той же причине из `mcp_client.py` (423 строки) выделены
`mcp_loop.py` (цикл событий) и `mcp_transport.py` (адаптеры SDK): вместе три
модуля дают 553 строки, порознь каждый укладывается в лимит 400.

## Планировщик (день 18) — новые модули

День 18 добавляет три инструмента с отложенным и периодическим выполнением
(`schedule_reminder`, `collect_data`, `generate_summary`) и планировщик, который
их исполняет. Унаследованные модули дней 9–17 — в таблицах ниже под новыми.

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/scheduler_values.py` | 109 | Значения планировщика: `ScheduleType`/`ScheduledTaskState`/`ReminderState`/`RunStatus` (`Enum`), коды причин отказа (`REASON_*`), фазы запуска (`RUN_PHASE_PREPARE`/`RUN_PHASE_TICK`), виды уведомлений и подписи для интерфейса |
| `backend/domain/scheduler_fsm.py` | 221 | Две стейт-машины в одном модуле: `ScheduledTaskFSM` (`active`→`paused`→`active`, `active`→`completed`) и `ReminderFSM` (`scheduled`→`done`), классы состояний, `ALLOWED_TASK_TRANSITIONS`/`ALLOWED_REMINDER_TRANSITIONS`, `task_allowed_events`/`reminder_allowed_events`, `UnknownSchedulerEvent` (недопустимое событие — ошибка, не «тихий» no-op) |
| `backend/domain/schedule_spec.py` | 395 | Инструменты и их аргументы: `ToolSpec`/`ToolArgument`, `TOOL_SPECS` (три инструмента), `validate_arguments` (типы, обязательность, лишние аргументы, границы, URL), `schedule_for` (разовое расписание напоминания и периодическое у остальных), `default_task_name`, `tool_specs`, `ScheduleRejected` |
| `backend/domain/schedule_timing.py` | 143 | Нормализация расписания (`date`/`interval`/`cron`) и арифметика момента запуска: `schedule_type_of`, `normalize_schedule`, `next_run_at` (для cron — `None`: ближайший запуск знает только APScheduler), `schedule_label` |
| `backend/domain/aggregation.py` | 235 | Агрегация накопленных записей: `aggregate_records` (числовые поля — count/avg/min/max, строковые — уникальные значения и примеры; `bool` числом не считается), `flatten_payload`, `render_summary_text`, `AggregateResult` |
| `backend/domain/schedule_intent.py` | 232 | Распознавание реплик трёх инструментов: `SCHEDULE_INTENT_RULES`, `classify_schedule_intent`, `parse_delay_seconds`/`parse_interval_seconds`/`parse_period_seconds`, `extract_url`, `reminder_text`, `url_name` |
| `backend/domain/scheduler_prompt.py` | 122 | Отчёт `render_schedule_report` (поле `schedule` ответа генерации) и системный блок «## Данные планировщика» (`render_scheduler_block`); при отказе, сбое или отсутствии вызова — `None` и пустой блок |
| `backend/models/scheduler.py` | 211 | ORM: шесть таблиц — `scheduled_tasks`, `task_runs`, `reminders`, `notifications`, `collected_data`, `periodic_summaries` |
| `backend/storage/scheduler_rows.py` | 177 | ORM-строки планировщика → словари API/UI (`task_dict` с `schedule_label` и `allowed_events`, `run_dict`, `reminder_dict`, `notification_dict`, `collected_dict`, `summary_dict`), `as_utc`, `jsonable` |
| `backend/storage/scheduler_store.py` | 196 | `SchedulerStore`: строка `scheduled_tasks` и журнал `task_runs` — создание, чтение, список, удаление, `set_status`, `set_next_run`, `active_tasks`, `due_tasks`, `record_run` |
| `backend/storage/scheduler_data_store.py` | 245 | `SchedulerDataStore`: напоминания (`complete_reminder` прогоняет состояние через `ReminderFSM`), накопленные записи, сводки и очередь уведомлений (`mark_read`) |
| `backend/services/source_fetch.py` | 61 | `fetch_json` — единственное место, где фон ходит в сеть: таймаут, предел размера тела (защита от гигантского JSON), отказ не-2xx/не-JSON текстом, пригодным и модели, и человеку; `SourceFetchError` |
| `backend/services/scheduled_jobs.py` | 176 | Действия трёх инструментов: `prepare` (немедленно при регистрации) и `tick` (по расписанию) — `_fire_reminder`, `_collect`, `_summarise`; сбой источника даёт уведомление и исключение наружу |
| `backend/services/apscheduler_bridge.py` | 161 | Мост к APScheduler — единственное место, знающее его классы: `make_scheduler`, `trigger_for`, `add_task_job`/`remove_task_job`, `pause_job`/`resume_job`, `job_next_run_time`, `reschedule_job_now`, `shutdown_scheduler`, `TASK_JOB_PREFIX`, `RECONCILE_JOB_ID` |
| `backend/services/scheduler.py` | 369 | `TaskScheduler`: `start`/`shutdown`/`sync_from_db`/`register`/`unregister`/`pause`/`resume`/`run_tick`/`status`; `run_tick` — одна точка исполнения тика для job'а APScheduler, `POST /scheduler/tasks/{task_id}/run`, тестов и скрипта; ленивый `get_scheduler` |
| `backend/services/schedule_service.py` | 305 | `ScheduleService`: `create_task` (валидация → расписание → строка БД → `prepare` → регистрация), `list_tasks`/`task`/`delete_task`/`pause_task`/`resume_task`/`task_history`/`run_task_now` и чтение напоминаний, записей, сводок, уведомлений; ленивый `get_schedule_service` |
| `backend/schemas/scheduler.py` | 313 | Схемы API: каталог инструментов, статус планировщика, задачи и их создание, запуски, напоминания, накопленные записи, сводки, уведомления и отчёт `schedule` (классметоды `from_row` собирают модели из словарей хранилища) |
| `backend/api/scheduler.py` | 355 | Роутер `/scheduler`: 14 эндпоинтов; `ScheduleRejected` → HTTP (`not_found` → 404, `not_active`/`not_paused` → 409, остальные причины → 400); фильтры состояния проверяются до запроса |
| `backend/api/lifespan.py` | 49 | Жизненный цикл: `database.init_db()` (атрибутом модуля — на этом держится подмена в стендах прогона), `restore_from_db()`, `get_scheduler().start()`; на выходе `shutdown()` планировщика и закрытие MCP. Вынесен из `main.py`, чтобы тот держал лимит 80 строк |
| `frontend/scheduler_api.py` | 96 | HTTP-запросы планировщика (`api_scheduler_*`) поверх `request_json`; отдельный модуль, потому что `api_client.py` уже держит семь доменов |
| `frontend/scheduler_section.py` | 372 | Раздел «🗓 Планировщик»: таблица задач с действиями (пауза, возобновление, запуск, удаление), форма создания по аргументам инструмента (плюс ручные `interval`/`cron`), напоминания, сводки с метриками и полным текстом, история запусков |
| `frontend/notifications.py` | 59 | Непрочитанные уведомления планировщика в основной области; фрагмент с `run_every="5s"`; пустая очередь не рисует ничего |
| `mcp_server/backend_api.py` | 106 | Клиент бэкенда дня: `ScheduleBackendClient.schedule_tool` — один вызов `POST /scheduler/tasks`, `BackendAPIError` с текстом причины, `configure`/`get_client` |
| `tests/scheduler_fakes.py` | 109 | `FakeFetcher` (очередь ответов, режим ошибки, журнал вызовов), `posts_payload` (ответ в форме jsonplaceholder), `SchedulerStub` (контракт `TaskScheduler` без таймеров) |
| `tests/backend_stub.py` | 130 | Локальный HTTP-стенд `POST /scheduler/tasks` для stdio-теста инструментов: успех и 400 с текстом причины |
| `scripts/scheduler_stand.py` | 328 | Изолированный бэкенд прогона: своя БД, офлайн-заглушка DeepSeek, детерминированный источник (`StandPosts`), жизненный цикл процесса (`StandProcess`, pid-файл) |
| `scripts/scheduler_scenarios.py` | 296 | Четыре сценария задания (напоминание, периодический сбор, сводка, перезапуск) и данные прогона (`DemoRun`) |
| `scripts/scheduler_demo.py` | 141 | Оркестрация прогона: поднять стенд, подключить свой MCP-сервер по stdio, разобрать аргументы, собрать отчёт |
| `scripts/scheduler_report.py` | 394 | Сборка markdown-отчёта дня 18 из `DemoRun` (9 разделов, включая обязательную таблицу «инструмент / расписание / что сохраняется / что возвращает / пример вывода») |

Обновлены днём 18:

| Модуль | Строк | Что изменилось |
|---|---|---|
| `backend/core/config.py` | 225 | Раздел «Планировщик фоновых задач (день 18)»: часовой пояс, период сверки и окно прощения пропуска, границы интервала и полей таблиц, таймаут и предел размера сбора, параметры агрегации |
| `backend/core/dependencies.py` | 89 | `get_scheduler` и `get_schedule_service` (ленивый импорт `api.main`, как у `get_manager`) |
| `backend/api/main.py` | 69 | `lifespan` вынесен в `lifespan.py`; подключён роутер `scheduler`; версия `12.0.0`, заголовок «Агенты DeepSeek + планировщик задач — День 18» |
| `backend/api/agents.py` | 292 | Корневой инвентарь эндпоинтов: блок `scheduler` и 14 новых путей, обновлено имя дня |
| `backend/api/__init__.py` | 37 | Роутер `scheduler` в импорте и `__all__` |
| `backend/schemas/agent.py` | 342 | `GenerateResponse.schedule` — отчёт о шаге планировщика |
| `backend/schemas/mcp.py` | 193 | Описание ключа сервера: `day18-jsonplaceholder | fetch | filesystem` |
| `backend/domain/mcp_intent.py` | 145 | `classify_tool_call` сначала спрашивает `classify_schedule_intent`: реплика планировщика распознаётся раньше запроса данных |
| `backend/agents/agent.py` | 1925 ⚠️ | `apply_mcp_tool` досыпает в промпт и блок «## Данные планировщика» и возвращает `schedule`; `record["schedule"]` заполняется в `generate` (шаг планировщика дал +27 строк к дню 17) |
| `mcp_server/config.py` | 46 | `BACKEND_URL` (`DAY18_BACKEND_URL`), `BACKEND_TIMEOUT`, `SCHEDULER_TOOLS`, `SERVER_NAME = "day18-jsonplaceholder"`, версия `1.1.0`, инструкция про шесть инструментов |
| `mcp_server/schemas.py` | 90 | `ReminderScheduled`, `CollectionStarted`, `SummaryReady` |
| `mcp_server/server.py` | 293 | Три инструмента планировщика (`@server.tool`), помощник `_scheduled`, аргумент `--backend-url` |
| `frontend/api_client.py` | 388 | `DAY17_BACKEND_URL` → `DAY18_BACKEND_URL` (и тексты «из папки day18/») |
| `frontend/common.py` | 400 | Подписи `SCHEDULE_STATE_LABELS`/`REMINDER_STATE_LABELS`/`RUN_STATUS_LABELS`/`NOTIFICATION_KIND_LABELS`, `schedule_note`, `schedule_row` |
| `frontend/chat_section.py` | 334 | Седьмой раздел «🔀 Пайплайны», уведомления в основной области, строки «🗓 Планировщик: …» и «🔀 Пайплайн: …» в сводке хода |
| `frontend/mcp_ask.py` | 137 | Примеры реплик планировщика |
| `frontend/mcp_section.py` | 276 | Подпись про шесть инструментов и `--backend-url` |
| `frontend/__init__.py` | 30 | Описание `scheduler_api`, `scheduler_section`, `notifications` |
| `app.py` | 60 | `page_title="Планировщик задач · День 18"`, значок 🗓 |
| `tests/mcp_fakes.py` | 247 | `FAKE_TOOL_CATALOG` расширен тремя инструментами планировщика (всего шесть) |
| `tests/conftest.py` | 128 | Фикстуры `scheduler_store`, `scheduler_data`, `fetcher`, `scheduler`, `schedule_service`, `backend_api_base` |
| `tests/support.py` | 278 | `seed_scheduled_task` — посев задачи планировщика в БД |

**Шесть таблиц и почему `periodic_summaries`.** Таблица названа
`periodic_summaries`, а не `summaries`, потому что имя `summaries` в проекте уже
занято конспектами сжатия истории (день 9, `backend/models/context.py`), а
переименовывать унаследованную таблицу ради нового дня нельзя. Три отличия от
буквального списка полей задания осознанны: у `reminders` есть `task_id` (связь
напоминания с задачей), у `periodic_summaries` — `total_records`/`key_metrics`/
`task_id` (без них раздел «Сводки» не покажет метрики), а таблицы `task_runs` и
`notifications` задание не перечисляет вовсе, но без них нет истории запусков и
очереди уведомлений. Удаление задачи уносит её запуски каскадом
(`ondelete="CASCADE"`) и отвязывает напоминания, уведомления и сводки
(`ondelete="SET NULL"`): история остаётся, ссылка исчезает.

**Архитектурные решения.**

- **Тик — синхронная функция.** APScheduler 3.x в `AsyncIOExecutor` выполняет
  не-корутины в пуле потоков, поэтому фон не блокирует цикл событий FastAPI.
  Сессии SQLite открываются с `check_same_thread=False` (`shared/db_base`), так
  что запись из потока безопасна.
- **`scheduled_tasks` — источник правды, сверка раз в 5 с.** APScheduler держит
  задачи в памяти и не переживает перезапуск; `sync_from_db` доводит набор
  job'ов до строк БД (добавляет пропавшие, убирает удалённые, подтягивает
  `next_run_at`) при старте и по таймеру `SCHEDULER_SYNC_SECONDS`. Так задача,
  созданная MCP-сервером, подхватывается сама, а после рестарта задачи
  восстанавливаются; `next_run_at` пишется в БД всегда, а для cron берётся из
  `job.next_run_time` — иначе его негде взять.
- **Тик не ходит через MCP.** Соединение MCP принадлежит пользователю и держит
  блокировку клиента, поэтому вызов инструмента из фонового потока был бы
  дедлоком. Тик вызывает функции домена (`scheduled_jobs.tick`), а инструмент —
  тонкая обёртка над `POST /scheduler/tasks`.
- **Единственный писатель в SQLite — процесс бэкенда.** Тела трёх инструментов —
  один HTTP-вызов `POST /scheduler/tasks` дня, поэтому у ручного создания задачи
  и у вызова инструмента один код-путь, `mcp_server/` остаётся тонким (как в
  дне 17), и нет двух писателей в одну БД.
- **Ошибка тика не валит планировщик.** `run_tick` ловит всё: запуск пишется в
  `task_runs` со `status="error"`, пользователь получает уведомление
  `kind="error"`, задача остаётся `active` и повторится на следующем тике.

**Эндпоинты планировщика (14).** Пути абсолютные, префиксов нет; подключены в
`backend/api/main.py`.

| Метод и путь | Что делает |
|---|---|
| `GET /scheduler/tasks` | задачи планировщика (фильтр `status`) и состояние самого планировщика |
| `POST /scheduler/tasks` | создать задачу: `tool`, `arguments`, необязательные `name`, `run_now` и переопределение расписания (`schedule_type`/`schedule_value`); 201; 400 — незнакомый инструмент, негодные аргументы или расписание |
| `DELETE /scheduler/tasks/{task_id}` | удалить задачу (журнал её запусков уходит каскадом); 404 — задачи нет |
| `POST /scheduler/tasks/{task_id}/pause` | пауза; 409 — задача не `active` |
| `POST /scheduler/tasks/{task_id}/resume` | возобновление; 409 — задача не `paused` |
| `POST /scheduler/tasks/{task_id}/run` | запуск вне расписания (запись в журнал); 409 — задача `completed` |
| `GET /scheduler/tasks/{task_id}/history` | журнал запусков задачи (`prepare` и тики) |
| `GET /scheduler/tools` | каталог трёх инструментов с аргументами и границами |
| `GET /scheduler/status` | работает ли планировщик, часовой пояс, число поставленных задач, период сверки |
| `GET /scheduler/reminders` | напоминания (фильтр `status`) |
| `GET /scheduler/collected` | накопленные записи сбора (фильтр `name`) и их число |
| `GET /scheduler/summaries` | регулярные сводки (фильтр `name`) |
| `GET /scheduler/notifications` | очередь уведомлений (`unread_only`) и число непрочитанных |
| `POST /scheduler/notifications/{notification_id}/read` | отметить уведомление прочитанным; 404 — такого нет |

## Композиция и пайплайн (день 19) — новые модули

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/pipeline_spec.py` | 166 | Декларативное описание пайплайна: `DEFAULT_PIPELINE` (`search-summarize-save` из трёх шагов), константы инструментов, операторы условий (`GUARD_OPS`), тексты итогов (`MSG_*`), статусы шага (`STEP_*`), коды отказа (`REASON_*`), источник по умолчанию и `validate_pipeline` (нормализация и отказы `PipelineRejected`) |
| `backend/domain/pipeline_mapping.py` | 179 | Маппинг данных между шагами: `resolve_mapping`/`resolve_path` (`$steps.<i>.<путь>` — значение как есть, `{имя}` — аргумент запуска, подстановки внутри строки), `evaluate_guard` (четыре оператора) и `PipelineMappingError` — незаполненная ссылка это ошибка, а не пустая строка |
| `backend/domain/pipeline_fsm.py` | 167 | Стейт-машина прогона: `PipelineState`/`PipelineEvent` (`Enum`), классы-состояния с `handle(event)`, `ALLOWED_TRANSITIONS` (idle → running → completed/stopped/failed, из терминальных — снова start), `allowed_events`, `PipelineFSM` |
| `backend/domain/pipeline_intent.py` | 173 | Распознавание реплики «собери пайплайн»: фразы трёх действий (поиск, сводка, сохранение) — нужны ВСЕ три; из реплики берутся запрос («про …»), источник (пользователи/посты/заметки дня), стиль, формат и имя файла; `PipelineIntent.to_dict` |
| `backend/domain/pipeline_prompt.py` | 80 | Блок «## Результат пайплайна» для системного промпта: `render_pipeline_block` (нет блока у `failed` и нераспознанной реплики, у `stopped` — только итог) и `step_line` (строка на шаг с объёмом данных) |
| `backend/services/pipeline.py` | 195 | Прогон `Pipeline.run_pipeline`: порядок «маппинг → условие → вызов через `MCPToolRunner` → строка журнала → событие FSM», единая форма `output_result`, остановка на первом не-`ok` шаге, терминальный статус запуска |
| `backend/services/pipeline_service.py` | 198 | `PipelineService`: синхронный и фоновый запуск (`threading.Thread`, строка запуска создаётся ДО старта потока), `report`/`list_runs`/`steps`/`delete_run`, `statuses`, `_run` с терминальным статусом при исключении, `get_pipeline_service` (ленивый singleton процесса) |
| `backend/models/pipeline.py` | 89 | ORM: `pipeline_runs` (имя, статус, начало, конец, длительность) и `pipeline_steps` (номер, инструмент, `input_args`, `output_result`, время, статус, ошибка; `run_id` с `ON DELETE CASCADE`) |
| `backend/storage/pipeline_rows.py` | 48 | ORM-строки в словари API/UI: `run_dict`, `step_dict` (метки времени — UTC-aware, JSON-поля — `jsonable` из `scheduler_rows`) |
| `backend/storage/pipeline_store.py` | 145 | `PipelineStore`: `create_run`/`update_run`/`run`/`run_row`/`list_runs` (свежие первыми, фильтр статуса)/`add_step`/`steps`/`delete_run` и `PipelineRunNotFoundError` |
| `backend/schemas/pipeline.py` | 150 | Pydantic-схемы: `PipelineRunIn` (конфигурация, аргументы, `background`), `PipelineStepOut`, `PipelineRunOut`, `PipelineStartOut`, `PipelineRunReportOut`, `PipelineRunsResponse`, `PipelineStepsResponse`, `PipelineReportOut` (поле `pipeline` ответа генерации) |
| `backend/api/pipelines.py` | 146 | Роутер `/pipelines`: пять эндпоинтов и перевод `PipelineRejected` в 400/404 |
| `mcp_server/search_sources.py` | 252 | Источники `search`: `parse_source`, лента jsonplaceholder (`posts`/`users`), `file:<путь>` (блоки файла, только внутри папки дня), `sqlite:<таблица>` (белый список `config.SQLITE_SOURCES`, соединение `mode=ro`); `SearchSourceError` с текстом для модели |
| `mcp_server/summarize_logic.py` | 178 | Логика `summarize` без LLM: `normalize_style`, `clamp_max_length`, `build_prompt`, `parse_key_points`, `aggregate_summary` (движок `aggregation`), `summary_text_of`, `llm_summary`, `items_payload` |
| `mcp_server/llm_client.py` | 86 | Необязательный вызов DeepSeek: `configure(enabled)`, `available()`, `summarize(prompt)`; отсутствие ключа или сбой — `LLMUnavailable`, инструмент переходит на агрегацию |
| `mcp_server/file_writer.py` | 109 | Запись `save_to_file`: `configure(output_dir)`, `normalize_format`, `sanitize_filename` (путь и `..` запрещены, расширение заменяется на формат), `render_content` (txt/md/json), `save` (размер в байтах, `saved_at` в UTC) |
| `mcp_server/pipeline_tools.py` | 128 | Три инструмента композиции (`search`, `summarize`, `save_to_file`) с типизированными параметрами и `ToolError` вместо исключений, `register_pipeline_tools(server)` |
| `frontend/pipeline_api.py` | 52 | HTTP-запросы раздела: `api_pipeline_run`, `api_pipeline_runs`, `api_pipeline_run_report`, `api_pipeline_run_steps`, `api_pipeline_delete_run` |
| `frontend/pipeline_section.py` | 330 | Раздел «🔀 Пайплайны»: подключение MCP, форма запуска, прогресс по шагам (`@st.fragment(run_every="1s")`), схема потока данных с объёмами, история запусков (`run_every="5s"`) и `pipeline_note` для сводки хода |
| `scripts/pipeline_scenarios.py` | 281 | Четыре сценария дня с проверками: успешный прогон (три `ok` и файл на диске), пустой поиск (`stopped` + «нет данных для обработки»), ошибка на втором шаге (`bad_arguments` и `is_error`), запуск из чата; `DemoRun`, `StubChatClient` |
| `scripts/pipeline_demo.py` | 189 | Оркестрация прогона: свой MCP-сервер по stdio с `--llm off`, временная БД для журнала, четыре сценария, сводка и вызов сборщика отчёта |
| `scripts/pipeline_report.py` | 372 | Сборка `docs/reports/pipeline_demo.md` из данных прогона: проверки, таблица инструментов, обязательная таблица шагов, схема двух таблиц, автотесты и рамки дня |

Опорные решения дня (их проверяют тесты и видно в отчёте):

| Решение | Где | Почему так |
|---|---|---|
| Пайплайн — данные, а не код | `pipeline_spec.DEFAULT_PIPELINE` | «Что делает пайплайн» видно в одном месте, конфигурацию можно прислать телом запроса, а проверка (`validate_pipeline`) отсекает неоднозначные описания |
| Ссылки разрешаются до вызова инструмента | `pipeline_mapping.resolve_mapping` | Иначе незаполненная ссылка ушла бы на сервер пустой строкой, и ошибка выглядела бы ошибкой инструмента, а не конфигурации |
| Условие проверяется до вызова | `pipeline_mapping.evaluate_guard` | «Нет данных для обработки» — решение не звать инструмент вовсе; прогон завершается досрочно (`stopped`), а не падает |
| Форма `output_result` одна у успеха и неудачи | `Pipeline.run_pipeline` | Пути маппинга (`$steps.<i>.structured.<поле>`) определены всегда, поэтому следующий шаг не зависит от исхода предыдущего |
| Строка журнала пишется даже у несобранного шага | `Pipeline._log_step` | Иначе причина остановки не доехала бы до истории и отчёта |
| Строка запуска создаётся до старта потока | `PipelineService.start_pipeline` | Интерфейс опрашивает статус сразу: гонки «запуск ещё не записан» нет |
| Ошибка в потоке даёт терминальный статус | `PipelineService._run` | Прогон без терминального статуса означал бы вечное «выполняется» — худший исход, чем ошибка |
| Реплика-пайплайн не разбирается как одиночный вызов | `Agent.generate` | Один запрос не должен запускать инструменты двумя путями; шаг пайплайна стоит до шага MCP и подменяет его |
| Сводка падает в агрегацию без ключа | `mcp_server/summarize_logic.aggregate_summary` | Демо и тесты работают офлайн, а пайплайн не зависит от наличия ключа DeepSeek |

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
| `frontend/__init__.py` | 35 | Описание пакета (включая `scheduler_api`, `scheduler_section`, `notifications`, `pipeline_api`, `pipeline_section`); модули не выполняют `st.*` на импорте |
| `frontend/api_client.py` | 388 | HTTP-транспорт к бэкенду (`requests`), `BACKEND_URL` / `DAY19_BACKEND_URL`, `BackendError`, `request_json`, функции дней 13–17 |
| `frontend/mcp_api.py` | 51 | Запросы MCP-раздела (`/mcp/status`, `/mcp/connect`, `/mcp/disconnect`, `/mcp/tools`, `/mcp/call`, `/mcp/servers`) поверх `request_json` |
| `frontend/mcp_section.py` | 276 | Раздел «🔌 MCP»: цель (по умолчанию — свой сервер дня с девятью инструментами), транспорт, кнопки подключения/отключения, статус, таблица инструментов, разбор `input_schema` и `output_schema`, вызовы блоков вызова инструмента и «Спросить агента» |
| `frontend/mcp_call.py` | 199 | Каталог серверов с кнопкой подключения, форма аргументов по `input_schema` и результат вызова (`render_servers`, `render_tool_call`, `render_call_result`) |
| `frontend/mcp_ask.py` | 137 | Блок «🤖 Спросить агента»: агент сам вызывает инструмент по реплике; отчёт `record["mcp"]` и данные инструмента в ответе; примеры реплик (включая три планировщика) |
| `frontend/scheduler_api.py` | 96 | HTTP-запросы планировщика (`api_scheduler_status`/`_tools`/`_tasks`/`_create`/`_delete`/`_pause`/`_resume`/`_run`/`_history`/`_reminders`/`_collected`/`_summaries`/`_notifications`/`_mark_read`) поверх `request_json` |
| `frontend/scheduler_section.py` | 372 | Раздел «🗓 Планировщик»: таблица задач с действиями, форма создания по аргументам инструмента и ручное расписание (`interval`/`cron`), напоминания с фильтром, сводки с метриками и текстом, история запусков |
| `frontend/notifications.py` | 59 | Непрочитанные уведомления планировщика в основной области чата: фрагмент с `run_every="5s"`, кнопка «✔ Прочитано»; пустая очередь ничего не рисует |
| `frontend/common.py` | 400 | Подписи (`TASK_STAGE_LABELS`, `TASK_FLAG_LABELS`, `INVARIANT_*_LABELS`, `MCP_*_LABELS`, `SCHEDULE_STATE_LABELS`, `REMINDER_STATE_LABELS`, `RUN_STATUS_LABELS`, `NOTIFICATION_KIND_LABELS`), форматтеры, `invariant_notice`, `stage_button_label`, `blocked_reason`, `schedule_note`, `schedule_row`, единый путь мутаций панели задачи `run_task_action`, `st.session_state`: init (включая `mcp_last_call`, `mcp_last_ask`), флеш-сообщения, выбор активного агента |
| `frontend/sidebar.py` | 191 | Боковая панель: агенты, создание агента, стратегия, задача и сессия (`render_sidebar()`) |
| `frontend/chat_section.py` | 321 | Раздел «💬 Чат и память», переключатель шести разделов, блок предупреждения/отказа по инвариантам над вводом, уведомления планировщика, строка про MCP-вызов и про поставленную фоновую задачу в сводке хода, сборка страницы (`render_main_area()`) |
| `frontend/context_panels.py` | 324 | Панели контекста: токены, сжатие, сравнение режимов, ветки, факты |
| `frontend/memory_panels.py` | 229 | Панели трёх слоёв памяти, индикатор «что ушло в запрос» |
| `frontend/profile_section.py` | 322 | Раздел «👤 Профиль пользователя»: CRUD профилей, предпросмотр промпта |
| `frontend/profile_comparison.py` | 129 | Сравнение двух профилей на одном вопросе (временные агенты) |
| `frontend/task_panel.py` | 181 | Раздел «🧭 Состояние задачи»: состояние, схема FSM, допустимые этапы, вкладки журнала |
| `frontend/task_transitions.py` | 188 | Блок переходов: кнопки-этапы, причины отказа, флаги согласования, пауза/продолжение (`render_transitions`) |
| `frontend/invariant_panel.py` | 254 | Раздел «📏 Инварианты»: таблица правил, форма, правка, включение-выключение, удаление, проверка текста |

## `backend/api/` — эндпоинты по доменам

| Модуль | Строк | Эндпоинтов | Домен |
|---|---|---|---|
| `backend/api/__init__.py` | 37 | — | Описание пакета и реэкспорт роутеров (без `main`) |
| `backend/api/agents.py` | 292 | 11 | CRUD агентов, генерация, диалог, статистика токенов, корневой инвентарь эндпоинтов |
| `backend/api/context.py` | 140 | 9 | Сжатие истории, стратегии, ветки, факты |
| `backend/api/memory.py` | 180 | 10 | Слои памяти (`/memory/short-term`, `/working`, `/long-term`), сессия, задача |
| `backend/api/profiles.py` | 126 | 6 | Профили пользователей `/users...`, `GET /agents/{id}/profile` |
| `backend/api/tasks.py` | 246 | 11 | Состояние задачи: создание, список, чтение, `allowed-next`, журнал, пауза, продолжение, шаг, откат, флаги согласования, переход |
| `backend/api/invariants.py` | 139 | 6 | Инварианты: CRUD правил проекта и проверка текста (`/invariants/check`) |
| `backend/api/mcp.py` | 180 | 6 | MCP: подключение, отключение, статус, список инструментов, вызов инструмента и каталог серверов (`/mcp/...`) |
| `backend/api/scheduler.py` | 355 | 14 | Планировщик: задачи (создание, список, пауза, возобновление, запуск, удаление, история), каталог инструментов, статус, напоминания, накопленные записи, сводки, уведомления (`/scheduler/...`) |
| `backend/api/pipelines.py` | 146 | 5 | Пайплайн: запуск (синхронный и фоновый), история запусков, отчёт о запуске, его шаги, удаление (`/pipelines/...`) |
| `backend/api/lifespan.py` | 49 | — | Старт и остановка фоновых служб: таблицы, агенты, планировщик, закрытие MCP |
| `backend/api/main.py` | 79 | — | Сборка `app`: CORS, `include_router` (lifespan — в `lifespan.py`) |

Всего 78 эндпоинтов (73 дня 18 + 5 пайплайна дня 19: `POST /pipelines/run`,
`GET /pipelines/runs`, `GET /pipelines/runs/{run_id}`,
`GET /pipelines/runs/{run_id}/steps`, `DELETE /pipelines/runs/{run_id}`).
Пути внутри роутеров абсолютные, префиксов нет; подключение — в
`backend/api/main.py`. Доступ к менеджеру, реестру MCP, планировщику и службе
пайплайнов, а также 404/409 — `backend/core/dependencies.py` (`get_manager`,
`get_mcp_registry`, `get_scheduler`, `get_schedule_service`,
`get_pipeline_service`, `agent_or_404`, `task_or_404`, `invariant_or_404`).

## `backend/schemas/` — Pydantic-схемы API, `backend/models/` — ORM

Разделение слоёв: Pydantic-схемы API — в `backend/schemas/` (реэкспорт из
`schemas/__init__.py`, импорт — `from backend.schemas import ...`), ORM-таблицы —
в `backend/models/*.py` (реэкспорт из `backend/storage/database.py`, импорт —
`from backend.storage.database import ...`). Это целевая раскладка `AGENTS.md`:
расхождение дня 12 (схемы в `models/`, ORM в `tables.py`) устранено.

День 19 добавил и то и другое: схемы API — `backend/schemas/pipeline.py`
(`PipelineRunIn`, `PipelineStepOut`, `PipelineRunOut`, `PipelineStartOut`,
`PipelineRunReportOut`, `PipelineRunsResponse`, `PipelineStepsResponse`,
`PipelineReportOut`; поле `pipeline` — в `GenerateResponse`), ORM —
`backend/models/pipeline.py` (`PipelineRun` и `PipelineStep`, таблицы
`pipeline_runs` и `pipeline_steps`). Схемы повторяют форму словарей хранилища
(`pipeline_rows.run_dict`/`step_dict`), поэтому роутер только объявляет контракт и
не переупаковывает данные.

| Схемы (`backend/schemas/`) | Строк | Домен |
|---|---|---|
| `schemas/__init__.py` | 227 | Реэкспорт всех схем (импорт — из `backend.schemas`) |
| `schemas/agent.py` | 342 | Агент, генерация (включая поля `task_state`, `task_intent`, `task_proposal`, `invariants`, `mcp` и `schedule`), метрики использования токенов |
| `schemas/context.py` | 218 | Сжатие истории, стратегии, ветки, факты |
| `schemas/mcp.py` | 193 | MCP: подключение (`MCPConnectIn`), статус (`MCPStatusResponse`), инструменты (`MCPToolSchema` с `input_schema` и `output_schema`, `MCPToolsResponse`), вызов (`MCPCallIn`, `MCPCallResponse`, `MCPCallReportOut`) и каталог серверов (`MCPServerSchema`, `MCPServersResponse`) |
| `schemas/scheduler.py` | 313 | Планировщик: каталог инструментов (`SchedulerToolSchema`, `SchedulerToolsResponse`), статус (`SchedulerStatusOut`), задачи и их создание (`ScheduledTaskOut`, `SchedulerTaskIn`, `SchedulerTaskCreateOut`, `SchedulerTasksResponse`), запуски (`SchedulerRunOut`, `SchedulerRunsResponse`), напоминания, накопленные записи, сводки, уведомления и отчёт `ScheduleReportOut` |
| `schemas/invariant.py` | 149 | Инварианты и результат проверки текста |
| `schemas/memory.py` | 173 | Три слоя памяти агента |
| `schemas/profile.py` | 170 | Профиль пользователя и его вклад в промпт |
| `schemas/task.py` | 170 | Состояние задачи: этап, шаг, переходы, `accepted`, `allowed_next`/`blocked`, флаги согласования, журнал |

| ORM (`backend/models/`) | Строк | Таблицы |
|---|---|---|
| `models/agent.py` | 93 | `agents` (`AgentRecord`) и его `relationship`-связи |
| `models/message.py` | 41 | `short_term_messages` (`ShortTermMessage`) |
| `models/memory.py` | 81 | `working_memory`, `long_term_memory` |
| `models/context.py` | 157 | `summaries`, `token_usage`, `facts`, `checkpoints` |
| `models/user_profile.py` | 57 | `user_profiles` (`UserProfile`) |
| `models/task_state.py` | 119 | `task_states` (`TaskState`, включая колонку `paused_from_stage`), `task_transitions` (`TaskTransition`, включая `accepted`) |
| `models/invariant.py` | 51 | `invariants` (`Invariant`) |
| `models/scheduler.py` | 211 | `scheduled_tasks` (`ScheduledTask`), `task_runs` (`SchedulerTaskRun`), `reminders` (`Reminder`), `notifications` (`SchedulerNotification`), `collected_data` (`CollectedRecord`), `periodic_summaries` (`PeriodicSummary`) |
| `models/__init__.py` | 65 | Реэкспорт ORM-классов (импорт из `backend.storage.database`) |

ORM разложен по доменам не из-за лимита строк, а по правилу слоя: файл лежит в
папке своего домена (в дне 12 ради лимита хватало пары `tables.py` +
`tables_task.py`). Строковые имена в `relationship("TaskState", ...)` не
меняются — SQLAlchemy разрешает их по registry, а все модули `models/`
импортируются из `storage/database.py`, поэтому регистрация таблиц та же, что и
до рефакторинга. Таблица `invariants` добавлена днём 14 (стало 12 таблиц, было
11), при этом `invariants` ни с чем не связана по FK — правила проекта живут
отдельно от агентов и диалога. День 17 таблиц не добавлял. День 18 добавил шесть
таблиц планировщика, день 19 — две таблицы пайплайна (`pipeline_runs`,
`pipeline_steps`): **20 таблиц** на день. `scheduled_tasks` связана каскадом с
`task_runs`, а `reminders`, `notifications` и `periodic_summaries` ссылаются на
неё по `ondelete="SET NULL"` (удаление задачи не уносит историю); `pipeline_steps`
ссылается на `pipeline_runs` по `ondelete="CASCADE"` (удаление запуска уносит его
шаги).

## Тесты

`tests/` — 1789 тестов `pytest`, офлайн (временная SQLite + фейк клиента
DeepSeek; MCP — свой stdio-сервер, фейк или локальный HTTP-стенд; планировщик —
фейковый источник данных и планировщик без таймеров; пайплайн — фейковый
MCP-реестр), разложены по трём подпапкам **по фикстурам**: без БД и агента —
`unit/`, с временной БД и `Agent` — `integration/`, через `TestClient` — `e2e/`.
`tests/conftest.py`, `tests/support.py`, `tests/mcp_fakes.py`,
`tests/scheduler_fakes.py`, `tests/pipeline_fakes.py`,
`tests/search_sources_fakes.py` и `tests/backend_stub.py` остаются в корне
`tests/`: на них опирается `pythonpath = . tests` из `pytest.ini` и импорт
`from support import ...` / `from pipeline_fakes import ...`.

| Подпапка | Файлов | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/` | 35 | 1240 | Чистые модули: FSM сжатия, задачи, MCP-подключения, вызова инструмента и планировщика, графы допуска и guards переходов, тексты отказа, распознавание предложения модели, запроса инструмента и реплик планировщика, расписания и их арифметика, агрегация записей, блоки данных MCP и планировщика, каталог серверов, политика сжатия, извлечение фактов, значения профиля, значения/правила/тексты инвариантов, разбор цели MCP и структура инструмента |
| `tests/integration/` | 32 | 384 | Хранилище, сервисы и агент на временной БД: `TaskStateStore`/`TaskStateMachine`, `InvariantManager`/`InvariantChecker`, `MemoryManager`, `ProfileStore`, `ContextCompressor`, `AgentManager`, `MCPRegistry`, `MCPClient` на настоящем stdio-сервере, `MCPToolRunner` и шаг MCP в `Agent.generate`, `SchedulerStore`/`SchedulerDataStore`/`ScheduleService`/`TaskScheduler` (включая связку с настоящим APScheduler), шаг планировщика в агенте и stdio-инструменты планировщика |
| `tests/e2e/` | 11 | 165 | API через `TestClient`: 78 эндпоинтов, коды 200/201/400/404/409/422/502, полный цикл задачи, поля `task_state`/`task_intent`/`task_proposal`, `invariants`, `mcp`, `schedule` и `pipeline` в ответе генерации, шесть эндпоинтов `/mcp`, 14 — `/scheduler` и пять — `/pipelines` |

Новые файлы дня 19 (подпапка — по фикстурам; тестов в файле) — 415 кейсов:

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_pipeline_fsm.py` | 201 | 43 | Таблица переходов (все девять пар + тринадцать недопустимых → `UnknownPipelineEvent` без смены состояния), значения `Enum` как статусы запуска, `allowed_events` и порядок объявления, `can`/`reset`, сверка `ALLOWED_TRANSITIONS` с классами состояний |
| `tests/unit/test_pipeline_spec.py` | 208 | 39 | Двадцать три отказа `validate_pipeline` (не объект, пустые/чужие шаги, шаг без `tool`, неизвестное условие, длинное имя, шагов больше предела) с кодом `REASON_BAD_CONFIG`, границы `PIPELINE_STEPS_MAX`, встроенный пайплайн и его три шага, условие `non_empty` с «нет данных для обработки», нормализация без мутации исходной конфигурации |
| `tests/unit/test_pipeline_mapping.py` | 295 | 65 | Ссылки `$steps.<i>.<путь>` (значение как есть, вложенные словари, индекс списка), `{имя}` целиком и внутри строки, рекурсия по словарям и спискам, шесть ошибок отсутствующего пути и три — незаполненной заглушки, все четыре условия шага, `equals` без `value`, неизвестное условие |
| `tests/unit/test_pipeline_prompt.py` | 137 | 21 | Блок для `completed` (строки шагов с объёмами), для `stopped` (только итог), пустая строка для `failed` и нераспознанной реплики, устойчивость к отсутствующему результату шага, строка для неизвестного инструмента |
| `tests/unit/test_pipeline_intent.py` | 217 | 43 | Реплика задания → `query="RAG"`, заметки дня, `rag.md`; две группы фраз из трёх → `None`; морфология триггеров и её границы; стиль, формат (в том числе `json`/`txt`), источник (пользователи/посты/заметки), `pipeline_query` и `pipeline_filename`, изоляция `DEFAULT_PIPELINE` от намерения |
| `tests/unit/test_summarize_logic.py` | 279 | 54 | Нормализация стиля и зажим длины, промпт (роль, лимиты, маркер пунктов), разбор ключевых пунктов маркерами `-`/`*`/`1.`, агрегация трёх стилей с обрезкой, ветка LLM, `items_payload` с чужими элементами |
| `tests/unit/test_file_writer.py` | 169 | 32 | Точная форма JSON-файла, замена расширения, запрет пути и «..» в имени, обрезка имени, создание каталога, `size_bytes` == размер на диске, ISO-8601 UTC в `saved_at`, ошибки формата и длины, перезапись |
| `tests/unit/test_search_sources.py` | 183 | 29 | Разбор строки источника (виды и отказ с перечнем), источник `file:` (блоки, фильтр, `limit` и его границы, обрезка запроса, отсутствующий файл, абсолютный путь, выход за папку дня, длинный источник) |
| `tests/unit/test_search_sources_sqlite.py` | 116 | 11 | Источник `sqlite:`: свежие строки первыми, LIKE по объявленным колонкам, `limit`, `source_url` в `url`, чужой таблицы нет в белом списке, отсутствующая база |
| `tests/unit/test_search_sources_api.py` | 123 | 15 | Источник ленты: форма элементов постов и пользователей, запись без `address`/`userId`, фильтр по текстовым полям, «фильтр, потом `limit`», сбой API как ошибка источника |
| `tests/integration/test_pipeline_store.py` | 105 | 7 | Запуск со статусом `running`, порядок шагов по номеру, шаг без результата (`NULL` и текст ошибки), терминальный статус с длительностью, история свежими первыми и фильтр статуса, каскадное удаление шагов, отсутствующий запуск |
| `tests/integration/test_pipeline_execution.py` | 193 | 11 | Успешный прогон трёх шагов с журналом, единая форма `output_result`, передача данных между шагами (типы и значения), проброс `limit`, остановка условием без вызова следующего инструмента, `bad_arguments` до сервера, ошибка инструмента, отсутствие соединения, несобранный шаг в журнале, повторное использование `run_id`, отказ до создания запуска |
| `tests/integration/test_pipeline_service.py` | 168 | 11 | Синхронный запуск полным отчётом, фоновый (строка запуска уже в БД, терминальный статус, «выполняется» в ответе), объяснение досрочной остановки и ошибки шага, фильтр истории, отказ `not_found` у отчёта/шагов/удаления, терминальный статус при исключении в потоке, список статусов, подстановка встроенного пайплайна |
| `tests/integration/test_pipeline_agent.py` | 229 | 10 | Реплика про RAG: прогон выполнен, три шага в отчёте, блок в системном промпте и токены блока, аргументы из реплики, обычная реплика без прогона, реплика-пайплайн не разбирается как одиночный вызов, отказ по hard-инварианту не даёт побочных эффектов, без соединения прогон `failed`, распознавание — единственный переключатель |
| `tests/e2e/test_pipelines_api.py` | 267 | 15 | Пять эндпоинтов `/pipelines`: синхронный и фоновый запуск с опросом, 400 на негодную конфигурацию и неизвестное условие, 422 на тело, отчёты для `completed`/`stopped`/`failed`, шаги отдельной ручкой, 404 и удаление, история с фильтром и пределом, поле `pipeline` в ответе генерации, перечень эндпоинтов в `GET /` |

Обновлены днём 19: `tests/integration/test_mcp_server_stdio.py` (266 строк, 14
тестов: девять инструментов, схемы композиции, реальные вызовы `search` по файлу
и таблице, `summarize` с движком `aggregation`, `save_to_file` в переданный
каталог, отказ по имени с путём, прогон трёх инструментов подряд),
`tests/integration/test_mcp_scheduler_tools.py` (каталог из девяти инструментов),
`tests/unit/test_mcp_servers.py` (ключ `SERVER_KEY_DAY19`),
`tests/e2e/test_mcp_call_api.py` (ключ `day19-pipeline`),
`tests/conftest.py` (фикстуры `pipeline_store`, `pipeline_registry`, `pipeline`,
`pipeline_service`), `tests/support.py` (`create_agent` принимает
`pipeline_service` — иначе агент взял бы службу ПРОЦЕССА и записал данные в
рабочую БД дня).

Новые файлы дня 18 (подпапка — по фикстурам; тестов в файле) — 152 кейса:

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_scheduler_fsm.py` | 96 | 15 | Таблицы переходов задачи и напоминания, `allowed_events` в обоих состояниях, негативные пары (`resume` из `active`, `pause` из `completed`, повторный `FIRE`) → `UnknownSchedulerEvent` без смены состояния, терминальные состояния |
| `tests/unit/test_schedule_spec.py` | 213 | 38 | `schedule_for` для трёх инструментов, `validate_arguments` по каждому коду причины (незнакомый/лишний/отсутствующий аргумент, границы, `str`/`bool` вместо целого, URL без схемы и длиннее предела), `normalize_schedule` (interval, cron из пяти полей, кривой cron, date), `next_run_at` (date, interval от `last_run_at`, просроченный — не раньше `now`, cron → `None`), `default_task_name`, каталог `tool_specs` |
| `tests/unit/test_aggregation.py` | 115 | 10 | Числовые поля (count/avg/min/max) на плоском и вложенном payload, `bool` не считается числом, категориальные уникальные значения и примеры, `sources` по именам сборов, пустой период, обрезка по `max_fields`, текст сводки с именем и периодом |
| `tests/unit/test_schedule_intent.py` | 136 | 18 | «напомни мне через 5 минут проверить почту» → `schedule_reminder` + 300 + текст напоминания, «собирай данные с URL каждые 10 секунд» → `collect_data` + URL + `name="posts"`, «покажи сводку за последний час» → `generate_summary` + 3600, реплики без триггеров и инструмент вне каталога → `None`, регресс дня 17 (`get_user`) |
| `tests/unit/test_scheduler_prompt.py` | 109 | 9 | `render_schedule_report` для `done` (задача, подтверждение), `None` для отказа, сбоя и не-планировщицкого инструмента; пустой блок промпта при отказе |
| `tests/integration/test_scheduler_service.py` | 203 | 17 | `create_task` трёх инструментов: строка `scheduled_tasks` (имя, инструмент, аргументы, расписание, состояние, `next_run_at`), немедленный результат (напоминание + `reminder_id` в аргументах, запись `collected_data`, сводка), `task_runs` с `phase="prepare"`, `run_now=False`, отказы `ScheduleRejected` с кодом, пауза/возобновление и отказ класса 409, удаление задачи уносит её запуски, отметка уведомления прочитанным |
| `tests/integration/test_scheduler_ticks.py` | 146 | 7 | Тик напоминания (`reminders.status=done` + уведомление «Напоминание: …» + задача `completed`) и повторный тик → `UnknownSchedulerEvent`; тик сбора добавляет запись (фейковый источник отдаёт другой ответ), сбой источника → `task_runs.status="error"` и уведомление, задача остаётся `active`; тик сводки: `periodic_summaries` за период и `key_metrics["numeric"]` с avg/min/max |
| `tests/integration/test_scheduler_restore.py` | 138 | 3 | «Перезапуск» (новый `TaskScheduler` на той же БД): `sync_from_db` возвращает активные задачи, просроченный `next_run_at` пересчитан (не в прошлом), `paused` и `completed` не регистрируются, удалённые задачи из БД исчезают |
| `tests/integration/test_scheduler_apscheduler.py` | 77 | 2 | Настоящая связка с APScheduler (`asyncio.run`): задача с интервалом 1 с даёт строку `task_runs` с `phase="tick"`, `status()["running"]` истинно, `shutdown()` не роняет цикл |
| `tests/integration/test_scheduler_agent.py` | 143 | 8 | Шаг планировщика в `Agent.generate` по реплике: инструмент и аргументы верные, `record["schedule"]["registered"]` истинно; реплика-сводка → `generate_summary`; без соединения `schedule is None` при `mcp.reason_code == "not_connected"` |
| `tests/integration/test_mcp_scheduler_tools.py` | 115 | 8 | Настоящий `mcp_server/server.py` со `--backend-url` на стенд: каталог из шести инструментов, `structuredContent` трёх инструментов планировщика, ошибка бэкенда (400) приходит как `is_error` с текстом причины, а не как обрыв связи |
| `tests/e2e/test_scheduler_api.py` | 273 | 17 | Все 14 эндпоинтов `/scheduler` через `TestClient`: 201/400/404/409/422, каталог инструментов, история запусков, запуск вне расписания, чтение напоминаний, накопленных записей, сводок и уведомлений, поле `schedule` в ответе генерации |

Обновлены днём 18 (числа строк и тестов — фактические):

| Модуль | Строк | Тестов | Что изменилось |
|---|---|---|---|
| `tests/unit/test_mcp_servers.py` | 81 | 11 | Ключ своего сервера — `SERVER_KEY_DAY18` |
| `tests/integration/test_mcp_server_stdio.py` | 91 | 5 | Сервер дня публикует шесть инструментов (`EXPECTED_TOOLS`) |
| `tests/e2e/test_mcp_call_api.py` | 184 | 13 | Ключ сервера `day18-jsonplaceholder`; `tool_count` подключённого равен длине `FAKE_TOOL_CATALOG` |
| `tests/mcp_fakes.py` | 247 | — | `FAKE_TOOL_CATALOG` расширен тремя инструментами планировщика (шесть всего) |
| `tests/conftest.py` | 128 | — | Фикстуры планировщика: `scheduler_store`, `scheduler_data`, `fetcher`, `scheduler`, `schedule_service`, `backend_api_base` |
| `tests/support.py` | 278 | — | `seed_scheduled_task` — посев задачи планировщика в БД |

Унаследованы новые файлы дня 17 (подпапка — по фикстурам; тестов в файле) — 120 кейсов, вместе
с обновлённым `test_mcp_tools.py` (15) это 135 кейсов дня:

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_mcp_tool_call.py` | 243 | 43 | Граф вызова (сверка `ALLOWED_TRANSITIONS` с классами состояний, все допустимые пары, негативные → `UnknownMCPToolCallEvent` без смены состояния, `can`/`allowed_events`/`reset`), `admission_reason` по каждому коду причины (нет соединения, инструмент вне каталога, нет обязательного аргумента, лишний аргумент, `str`/`bool` вместо `integer`, схема без `properties`), форма `MCPToolCallOutcome` и `called`, `find_tool` |
| `tests/unit/test_mcp_intent.py` | 104 | 21 | Приоритет правил («Какие посты у пользователя 2» → `list_user_posts`), «Найди информацию о пользователе с ID 1» → `get_user` с `{"user_id": 1}`, «Покажи пост 3» → `get_post`, реплика без номера, «пользовательский отчёт» → `None`, морфология и регистр, пустая строка, инструмента нет в каталоге, порядок `\d+` |
| `tests/unit/test_mcp_prompt.py` | 74 | 9 | Блок для `done`: заголовок, имя инструмента, JSON аргументов и результата, строка-инструкция; пустая строка для `idle`/`rejected`/`failed`; текст инструмента, когда структуры нет |
| `tests/unit/test_mcp_servers.py` | 81 | 11 | Три записи каталога в порядке `KNOWN_SERVERS`, `connected` ровно у одного, `tool_count` только у подключённого, неразобранная цель не даёт исключения |
| `tests/integration/test_mcp_server_stdio.py` | 89 | 5 | Настоящий `mcp_server/server.py` дочерним процессом с `--api-base` на локальный стенд: каталог из трёх инструментов (день 17), `required` и непустой `output_schema` у `get_user`, успешный вызов, `is_error` на несуществующем id с упоминанием 404, `list_user_posts` с `limit`, ошибка без соединения |
| `tests/integration/test_mcp_tool_runner.py` | 160 | 10 | Раннер: успешный вызов (`done`, `accepted`, `called`, структура), `call_error` → `failed`/`tool_error`, `call_fail` → `failed`/`transport`, без подключения → `rejected`/`not_connected`, инструмент вне каталога, неверный тип аргумента, `call_for_prompt` с ключевыми словами и без |
| `tests/integration/test_mcp_agent.py` | 161 | 8 | Шаг MCP в `Agent.generate`: инструмент вызван, аргументы верные, блок данных в системном сообщении запроса и в `record["system_prompt"]`, `added_tokens > 0`; без ключевых слов инструмента нет; «Расскажи про пользователя» → `bad_arguments`, но генерация `ok`; без соединения — `connected false`; сбой инструмента не роняет ход |
| `tests/e2e/test_mcp_call_api.py` | 184 | 13 | `POST /mcp/call` и `GET /mcp/servers` через `TestClient`: 409 без соединения, 200 с полным набором полей, 400 на неизвестный инструмент и неверный тип аргумента, 422 на пустое имя и превышение длины, 502 при обрыве связи, 200 + `is_error` при ошибке инструмента, каталог серверов (3 записи), `output_schema` в `/mcp/tools`, поле `mcp` в генерации |

Обновлены в дне 17 (числа строк и тестов — как в дне 17; правки дня 18 — в таблице выше):

| Модуль | Строк | Тестов | Что изменилось |
|---|---|---|---|
| `tests/unit/test_mcp_tools.py` | 110 | 15 | `output_schema` в `to_dict` (глубокая копия) и в `make_tool_info`, нормализация отсутствующей схемы в `{}`, `MCPToolResult.to_dict()` |
| `tests/support.py` | 255 | — | MCP-фейки вынесены в `tests/mcp_fakes.py`; из `support` остались `FakeClient`, `create_agent`, `seed_invariant`, демо-инварианты |
| `tests/e2e/test_mcp_api.py` | 137 | 7 | Импорт фейков из `mcp_fakes`; `/mcp/tools` теперь проверяет и `output_schema` |
| `tests/conftest.py` | 72 | — | Новая фикстура `stub_api_base` — адрес локального стенда внешнего API (живёт один тест) |
| `tests/integration/test_mcp_stdio.py` | 82 | 5 | Имя тестового сервера дня 17, импорт фейков из `mcp_fakes` |
| `tests/integration/test_mcp_registry.py` | 105 | 7 | Импорт фейков из `mcp_fakes` |
| `tests/integration/test_mcp_client_errors.py` | 69 | 4 | Имена команд дня 17 |
| `tests/mcp_echo_server.py` | 40 | — | Имя сервера `day17-echo-server` |

Унаследованные без изменений — новые файлы дня 16 (MCP-подключение и каталог):

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_mcp_connection_fsm.py` | 113 | 22 | Таблица FSM подключения и её сверка с графом `ALLOWED_TRANSITIONS`, негативные пары → `UnknownMCPConnectionEvent` без смены состояния, идемпотентное отключение, `can`/`allowed_events`/`reset` |
| `tests/unit/test_mcp_target.py` | 131 | 29 | Выбор транспорта по виду цели, разбор команды (кавычки, обратные слэши Windows-путей), перевод `sse://` в `http://`, приоритет явного транспорта, ошибки разбора |

Унаследованы новые файлы дня 15 (контролируемые переходы):

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_task_state_machine.py` | 334 | 106 | Граф `ALLOWED_TRANSITIONS` (все 25 пар), guards по флагам, `get_allowed_next_stages`/`get_blocked_stages`, `cleared_flags`, `guard_context`, расхождение графа и классов-этапов |
| `tests/unit/test_task_transition_texts.py` | 167 | 114 | Дословные тексты отказа и подсказки для каждой недопустимой пары, длина причины ≤ 200 символов, `intent_refusal_notice` |
| `tests/unit/test_task_proposal.py` | 89 | 49 | Распознавание всех фраз предложения модели, регистр, границы слов, самый дальний этап при нескольких совпадениях, `None` без фраз |
| `tests/integration/test_task_transitions.py` | 204 | 18 | Журнал отклонённых попыток (`accepted = False`), отказ не меняет состояние, флаги через сервис, пауза и продолжение |
| `tests/e2e/test_task_transitions_api.py` | 191 | 7 | Эндпоинты `transition`/`allowed-next`/`context`: 400 с причиной и подсказкой, 422 на пустое тело флагов и неизвестный этап, `accepted: false` в журнале |
| `tests/unit/test_task_fsm.py` | 340 | 59 | `InvalidTransitionError` вместо `InvalidTaskTransition`, пауза из `done` — ошибка, проверки графа переехали в `test_task_state_machine.py` |
| `tests/unit/test_task_prompt.py` | 230 | 33 | Новый литерал блока с «Допустимые следующие этапы», «нет» при пустом списке |
| `tests/integration/test_task_state.py` | 372 | 39 | Флаги на каждой границе этапов, точные тексты guard-отказов, `set_flags`, сброс флагов при откате |
| `tests/integration/test_task_store.py` | 273 | 13 | `paused_from_stage` в колонке, `accepted` в журнале, `log_rejection` не меняет состояние |
| `tests/integration/test_task_manager.py` | 232 | 15 | `transition_task` без умолчаний на стороне миксина, `set_task_flags` |
| `tests/integration/test_task_agent.py` | 265 | 15 | Уведомление о неприменённом намерении, отказ на предложение модели, блок промпта с допустимыми этапами |
| `tests/e2e/test_task_api.py` | 345 | 27 | 400 с причиной и подсказкой, `allowed-next`, флаги через `PATCH`, `accepted: false` |
| `tests/unit/test_task_intent.py` | 115 | 63 | Распознавание намерения реплики по таблице фраз с приоритетом групп и границами слов |

Унаследованы новые файлы дня 14 (инварианты):

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_invariant_values.py` | 81 | 17 | `Enum`-значения, списки для API, подписи, тексты ошибок на неизвестное значение |
| `tests/unit/test_invariant_rules.py` | 124 | 28 | Правила-термины по всем 14 средствам, привязка к описанию инварианта, согласие пользователя снимает нарушение, границы слов, форма нарушения |
| `tests/unit/test_invariant_prompt.py` | 150 | 12 | Дословный блок промпта, тексты отказа и предупреждения, сообщение для LLM-проверки |
| `tests/integration/test_invariant_manager.py` | 225 | 24 | CRUD инвариантов, уникальность имени, фильтры, ошибки 404/409/422, независимость от диалога агента |
| `tests/integration/test_invariant_checker.py` | 311 | 21 | Правила → LLM, сбои и мусор от модели, пустой текст, дедупликация и приоритет вердиктов в `merged_with` |
| `tests/integration/test_invariant_agent.py` | 243 | 14 | Блок в системном промпте, отказ без вызова DeepSeek, предупреждение с ответом, пост-проверка ответа, сбой LLM-слоя |
| `tests/e2e/test_invariant_api.py` | 328 | 25 | Шесть эндпоинтов: коды, фильтры, проверка текста, поле `invariants` в генерации, корневой ответ, OpenAPI |

## Что импортируется из `shared/`

| Модуль дня | Импорт | Зачем |
|---|---|---|
| `backend/__init__.py` | — (добавляет корень репозитория в `sys.path`) | Чтобы `from shared...` работал из любого модуля дня |
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов (включая токены блоков MCP и планировщика), логи отказа и неприменимого намерения |
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API, чтение `DEEPSEEK_API_KEY` |
| `backend/storage/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/models/*.py` | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/storage/task_store.py` | `shared.logging_utils.get_logger` | Отладочный лог записанного перехода |
| `backend/storage/invariant_store.py` | `shared.logging_utils.get_logger` | Отладочный лог созданного/изменённого инварианта |
| `backend/services/invariant_checker.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger` | Клиент для LLM-слоя проверки и лог причины, по которой проверка не выполнена |
| `backend/services/mcp_client.py` | `shared.logging_utils.get_logger` | Логи подключения, закрытия, ошибок MCP и вызовов инструмента |
| `backend/services/mcp_registry.py` | `shared.logging_utils.get_logger` | Лог ошибки закрытия прошлого MCP-соединения при смене сервера |
| `backend/services/mcp_tool_runner.py` | `shared.logging_utils.get_logger` | Лог отклонённого вызова и сбоя инструмента |
| `backend/services/scheduler.py`, `schedule_service.py`, `apscheduler_bridge.py` | `shared.logging_utils.get_logger` | Логи сверки планировщика с БД, отказа создания задачи и сбоя тика |
| `backend/api/lifespan.py` | `shared.logging_utils.get_logger` | Логгер старта и остановки бэкенда |
| `backend/services/pipeline.py`, `pipeline_service.py` | `shared.logging_utils.get_logger` | Логи остановки прогона (шаг не собран, шаг упал) и сбоя фонового потока |
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | (то же, что выше) — токены блока пайплайна входят в контроль лимита контекста |
| `mcp_server/config.py` | `shared.deepseek_utils.read_key_from_env_file` | Ключ DeepSeek для инструмента `summarize` (сервер — отдельный процесс, .env читает сам; модуль добавляет корень репозитория в `sys.path`) |
| `mcp_server/llm_client.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger` | Клиент DeepSeek внутри `summarize` (создаётся лениво) и лог перехода к агрегации |

Модули `frontend/` обращаются к бэкенду только по HTTP
(`frontend/api_client.py`), поэтому `shared/` напрямую не импортируют. День 19
сломал это правило у пакета `mcp_server/`: инструмент `summarize` собирает сводку
вызовом DeepSeek, поэтому сервер (отдельный процесс) читает ключ из `day19/.env`
через `shared.deepseek_utils` и создаёт клиента через `shared.deepseek_client`.
Кода дня он по-прежнему не импортирует: зависимости — stdlib, `httpx`, SDK `mcp` и
пакет `shared/`.

## Известные расхождения

| Файл | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agents/agent.py` | 2009 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи и переходы, инварианты, шаги пайплайна, MCP и планировщика, генерация) не разложен на миксины — расхождение унаследовано от дней 11–18 (в день 16 — 1825, в день 17 +73 дал шаг MCP, в день 18 +27 — шаг планировщика, в день 19 +84 дали шаг пайплайна и свойство `pipeline_service`); рефакторинг `Agent` не входит ни в один из этих дней, и это единственное превышение лимита 400 в дне |
| `invariants_demo.md` лежит в корне дня | — | — | Путь задан заданием дня 14; в `docs/reports/` файл не дублируется (там лежат отчёты `scheduler_demo.md` дня 18, `mcp_tool_demo.md` дня 17, `mcp_demo.md` дня 16 и унаследованные) |
| `done` не пускает никуда | — | — | Терминальность `done` (день 15) — следствие требования «контролируемые переходы»: пауза из `done` отклоняется с объяснением, а не выполняется молча; поведение дня 13, разрешавшее `done → paused`, обновлено вместе с тестами и документацией |
| ORM разложен на 8 модулей `models/*.py` | 41–211 | 400 | Домен один (таблицы дня), но по правилу слоя файл лежит в папке своего домена (`scheduler.py` дня 18 собрал шесть таблиц планировщика в один модуль); заодно снят вопрос лимита, который в дне 12 решался парой `tables.py` + `tables_task.py` |
| `backend/agents/profile_store.py` (292) и `backend/agents/memory.py` (291) | — | — | Имена модулей сохранены (в целевом списке слоя они могли бы называться `profile_manager.py` / `memory_manager.py`) |
| `INVARIANT_LLM_CHECK` добавляет вызов DeepSeek | — | — | По умолчанию проверка ОТВЕТА идёт в LLM, когда детерминированные правила молчат: это осознанная цена семантической проверки, выключается одной строкой в `backend/core/config.py` (так работает офлайн-отчёт `scripts/invariants_demo.py`) |
| `scripts/video_scenario*.py` (8 модулей) | 69–386 | 400 | Унаследованы из дня 15 и проверяют кадры **прежнего** сценария (контролируемые переходы, §8 прежней инструкции); в демонстрации дня 18 не участвуют: сценарий задания даёт `scripts/scheduler_demo.py` (стенд, MCP-клиент и отчёт — `scripts/scheduler_stand.py`, `scripts/scheduler_scenarios.py`, `scripts/scheduler_report.py`). Скрипты не удалены как артефакт доказательств дня 15 |
| MCP-подключение не в БД | — | — | У подсистемы нет таблиц: соединение живёт в памяти процесса (`MCPRegistry`), поэтому после рестарта бэкенда `/mcp/status` отвечает `disconnected`. Это осознанно: связь с внешним сервером — не данные домена |
| Одно соединение на процесс | — | — | `GET /mcp/servers` отдаёт каталог известных целей (3 записи), а не несколько одновременных соединений; `connected` истинно ровно у одной записи — унаследованное от дня 16 свойство `MCPRegistry` |
| Вызовы инструмента идут наружу | — | — | `MCPToolRunner` выполняет настоящий HTTP-запрос к `jsonplaceholder.typicode.com` (через свой процесс сервера). В промпт агента попадает только успешный результат: отказ по правилам допуска и ошибка инструмента остаются в отчёте `record["mcp"]` |
| `backend/services/mcp_client.py` делит цикл событий с вызывающим потоком | 392 (+ `mcp_loop.py` 96, `mcp_transport.py` 65) | 400 | Клиент запускает свой daemon-поток с циклом событий и долгоживущую задачу сессии: контексты MCP SDK обязаны входить и выходить в одной задаче anyio. Публичные методы синхронные (FastAPI и Streamlit синхронные), потокобезопасные через `RLock`. Цикл событий и адаптеры SDK вынесены в `mcp_loop.py` и `mcp_transport.py`, потому что в одном файле клиент выходил за лимит (423 строки) |
| `tests/support.py` разделён с `tests/mcp_fakes.py` и `tests/scheduler_fakes.py` | 278 (+ 247, 109) | 400 | MCP-фейки вынесены в отдельный модуль `tests/mcp_fakes.py`: вместе с ними `support.py` выходил за лимит (453 строки). День 18 добавил `tests/scheduler_fakes.py` по той же причине (фейковый источник и планировщик без таймеров); импорты переведены на `mcp_fakes` и `scheduler_fakes` без реэкспорта (clean cutover) |
| `backend/agents/agent.py` не разложен на миксины | — | — | `pipeline_service` — свойство с ленивым импортом службы процесса (как у `MCPToolRunner.registry`): без него агент создавал бы службу в конструкторе и тянул цикл `agents → services → agents`. По той же причине `AgentManager` передаёт службу явно |
| `mcp_server/` импортирует `shared/` | — | — | День 19 сломал прежнее правило «пакет сервера живёт без кода дня» осознанно: `summarize` вызывает DeepSeek, а сервер — ОТДЕЛЬНЫЙ процесс, поэтому ключ он читает сам (`shared.deepseek_utils`) и клиента создаёт через `shared.deepseek_client`. Кода дня пакет по-прежнему не импортирует |
| Пайплайн — линейная цепочка | — | — | Ветвления, параллельные шаги, повторы упавшего шага и возобновление с места остановки не сделаны: условие шага может только остановить прогон целиком. Рамки дня перечислены в отчёте `docs/reports/pipeline_demo.md` (§9) |
| Источник `sqlite:` ищет подстрокой | — | — | `LIKE` по объявленным колонкам, а не векторный поиск: заметки про RAG описывают приём, а не реализуют его. Белый список таблиц (`config.SQLITE_SOURCES`) закрыт, соединение открывается только на чтение (`mode=ro`) |
| Пайплайн не ставится в планировщик | — | — | Инструменты планировщика (день 18) выполняют свои действия, а не пайплайн: периодический запуск композиции не сделаны (см. отчёт, §9) |
| `backend/domain/__init__.py` без имён планировщика и пайплайна | 399 | 400 | Двенадцать модулей (семь планировщика и пять пайплайна) импортируются как модули (`from . import aggregation, pipeline_spec, schedule_spec, …`), а не реэкспортируются по именам: иначе список имён слоя вышел бы за лимит 400 строк — файл ровно на границе, и день 19 сократил его докстринг на 14 строк, чтобы удержаться. Публичный контракт доступен как `backend.domain.pipeline_fsm.PipelineFSM` и т. п.; код дня и так берёт имена из своего модуля |
| `tests/unit/test_search_sources*.py` разделены на три файла | 183 + 116 + 123 | 400 | Один файл тестов источников вырос до 460 строк: материал (заметки, строки таблиц, заглушка клиента ленты) вынесен в `tests/search_sources_fakes.py`, а тесты разложены по видам источника — `file:`, `sqlite:`, лента API |

Лимиты `app.py` (67 ≤ 100) и `backend/api/main.py` (79 ≤ 80) соблюдены;
`frontend/common.py` (400) и `backend/domain/__init__.py` (399) — на границе, но в
пределах. Единственное превышение 400 строк в дне — унаследованный
`backend/agents/agent.py` (2009).

## Проверка лимита строк

Из папки `day19` (исключены `.venv` и вендорный `.agents/`):

```powershell
uv run python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and '.agents' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод сегодня: `[('backend\\agents\\agent.py', 2009)]`.

Каталог `.agents/` исключён не для красоты: в этой копии скиллы библиотек
скопированы (а не слинкованы), и шаблоны Streamlit внутри них длиннее 400 строк.
Это код библиотеки, а не дня; в дне 14 те же скиллы — симлинки, поэтому `**` в их
содержимое не заходит и команда дня 14 обходится без исключения.
