# Структура дня 17

Карта модулей дня 17: что где лежит и за что отвечает. Правила структуры — в
[`../AGENTS.md`](../AGENTS.md) и [`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

День 17 — копия дня 16 (`day16/` не изменяется, это снимок) плюс **свой
MCP-сервер с вызываемым инструментом**. В `mcp_server/` лежит собственный сервер
по stdio: три инструмента (`get_user`, `get_post`, `list_user_posts`) поверх
публичного `jsonplaceholder.typicode.com`. Клиент и реестр научились вызывать
инструмент (`tools/call`); домен получил граф жизненного цикла вызова и правила
допуска (`mcp_tool_call.py`), распознавание запроса по ключевым словам
(`mcp_intent.py`), блок данных для системного промпта (`mcp_prompt.py`) и каталог
известных серверов (`mcp_servers.py`); агент сам вызывает инструмент и кладёт
результат в промпт того же запроса; API отдаёт шесть эндпоинтов `/mcp` (включая
`POST /mcp/call` и `GET /mcp/servers`) и поле `mcp` в ответе генерации.
Унаследовано полностью: MCP-подключение и каталог инструментов (день 16),
контролируемые переходы и инварианты (день 15), состояние задачи как конечный
автомат (день 13), персонализация профилем (день 12), три слоя памяти и четыре
стратегии контекста (день 11).

MCP-подсистема не имеет таблиц в БД: соединение живёт в памяти процесса
(`MCPRegistry`), поэтому схема дня не меняется. Вызов инструмента идёт **наружу**
(HTTP-запрос к jsonplaceholder), а в промпт агента попадает только успешный
результат.

## Раскладка

```
day17/
├── app.py                    # точка входа Streamlit (71 строка): set_page_config + вызовы секций
├── mcp_server/               # СОБСТВЕННЫЙ MCP-сервер дня 17 (транспорт stdio, 5 модулей)
│   ├── __init__.py           # докстринг пакета: как запускается (`uv run python mcp_server/server.py`) и чем говорит
│   ├── config.py             # адрес jsonplaceholder, таймаут, границы user_id/limit, имя, версия и инструкция сервера
│   ├── schemas.py            # TypedDict-ответы (UserInfo, PostInfo, PostSummary, UserPosts) → outputSchema инструментов
│   ├── api_client.py         # HTTP-клиент jsonplaceholder: ExternalAPIError, configure/get_client
│   └── server.py             # MCPServer, три инструмента (@server.tool), _run, parse_args, main
├── frontend/                 # Streamlit UI по секциям (15 модулей + __init__.py)
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # FastAPI: 7 роутеров по доменам + сборка app (main.py), 59 эндпоинтов
│   ├── core/                 # config, dependencies — настройки и доступ к менеджеру и MCP-реестру
│   ├── domain/               # чистые правила и данные: FSM задачи/сжатия/MCP, граф переходов, правила допуска вызова, распознавание запроса, стратегии, профиль, инварианты, тексты
│   ├── services/             # прикладные сервисы: compressor, task_state, invariant_checker, mcp_loop, mcp_transport, mcp_client, mcp_errors, mcp_registry, mcp_tool_runner
│   ├── storage/              # доступ к БД: database, task_store, invariant_store, memory_rows
│   ├── agents/               # Agent, MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы SQLAlchemy по доменам
│   ├── schemas/              # Pydantic-схемы API по доменам (включая mcp.py)
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 1222 теста (unit/ — 798, integration/ — 291, e2e/ — 133)
│   ├── mcp_fakes.py          # MCP-фейки: FakeMCPClient, FAKE_MCP_TOOLS, FAKE_TOOL_CATALOG, make_mcp_factory
│   ├── mcp_echo_server.py    # унаследованный из дня 16 тестовый MCP-сервер по stdio (инструменты echo и add)
│   └── stub_api.py           # локальный HTTP-стенд jsonplaceholder: тесты сервера идут без сети
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов
│   ├── mcp_tool_demo.py      # день 17: каталог, три успешных и три отказных вызова, шаг агента → отчёт
│   ├── mcp_tool_report.py    # сборка markdown-отчёта дня 17 (7 разделов) из DemoRun
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
├── pyproject.toml, uv.lock   # зависимости (uv): прямые — в pyproject (включая mcp, httpx), точные версии — в локе
├── .agents/skills/           # скиллы библиотек (uvx library-skills --copy); на Windows симлинки недоступны
├── .python-version           # 3.14 (версия для `uv sync`)
├── .env.example              # шаблон ключа DEEPSEEK_API_KEY
└── agents.db                 # SQLite (в .gitignore по *.db)
```

Отчёты прогонов лежат в `docs/reports/`: `mcp_tool_demo.md` — отчёт дня 17 (его
создаёт `uv run python scripts/mcp_tool_demo.py --report docs/reports/mcp_tool_demo.md`),
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
| `core/` | `config.py` (194), `dependencies.py` (67), `__init__.py` (22) | Настройки дня (включая раздел «MCP (день 17)») и зависимости роутов: `get_manager`, `get_mcp_registry`, `agent_or_404`, `task_or_404`, `invariant_or_404` |
| `domain/` | 25 модулей + `__init__.py` (373) | Чистые правила и данные: FSM задачи, сжатия, MCP-подключения и вызова инструмента, граф допуска и guards переходов, правила допуска вызова и его код причины, распознавание запроса, блок данных для промпта, каталог серверов, стратегии, факты, слои памяти, профиль, инварианты, тексты промпта, разбор цели MCP и структура инструмента. Знают только stdlib, `core.config` и соседей по слою |
| `storage/` | `database.py` (46), `task_store.py` (278), `invariant_store.py` (255), `memory_rows.py` (47), `__init__.py` (72) | Движок и сессии, ORM-строки → словари, `TaskStateStore` (включая журнал отклонённых попыток), `InvariantManager` |
| `services/` | `compressor.py` (329), `task_state.py` (392), `invariant_checker.py` (296), `mcp_client.py` (392), `mcp_transport.py` (65), `mcp_errors.py` (95), `mcp_loop.py` (96), `mcp_registry.py` (138), `mcp_tool_runner.py` (144), `__init__.py` (102) | `ContextCompressor`, `TaskStateMachine` (граф, guards, единая точка отказа), `InvariantChecker`, `MCPClient` (соединение и вызов инструмента), `MCPEventLoop` (цикл событий в потоке), `MCPRegistry` (одно подключение на процесс), `MCPToolRunner` (допуск → вызов → исход): оркестрация домена, хранилища и внешних процессов |
| `agents/` | `agent.py` (1898 ⚠️), `memory.py` (291), `profile_store.py` (292), `agent_manager.py` (92), `manager_*.py` (7 файлов), `__init__.py` (57) | `Agent` (включая шаг MCP `apply_mcp_tool`), `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов; менеджер передаёт реестр MCP созданным и восстановленным агентам |
| `models/` | `agent.py` (93), `message.py` (41), `context.py` (157), `memory.py` (81), `user_profile.py` (57), `task_state.py` (119), `invariant.py` (51), `__init__.py` (46) | ORM-таблицы SQLAlchemy: `agents`, `short_term_messages`, `summaries`/`token_usage`/`facts`/`checkpoints`, `working_memory`/`long_term_memory`, `user_profiles`, `task_states`/`task_transitions`, `invariants` |
| `schemas/` | `agent.py` (336), `context.py` (218), `memory.py` (173), `profile.py` (170), `task.py` (170), `invariant.py` (149), `mcp.py` (193), `__init__.py` (184) | Pydantic-схемы API по доменам, реэкспорт из `schemas/__init__.py` |
| `api/` | `agents.py` (274), `context.py` (140), `memory.py` (180), `profiles.py` (126), `tasks.py` (246), `invariants.py` (139), `mcp.py` (180), `main.py` (80), `__init__.py` (15) | 59 эндпоинтов по доменам и сборка `app` |
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
| `frontend/__init__.py` | 24 | Описание пакета; модули не выполняют `st.*` на импорте |
| `frontend/api_client.py` | 388 | HTTP-транспорт к бэкенду (`requests`), `BACKEND_URL` / `DAY17_BACKEND_URL`, `BackendError`, `request_json`, функции дней 13–17 |
| `frontend/mcp_api.py` | 51 | Запросы MCP-раздела (`/mcp/status`, `/mcp/connect`, `/mcp/disconnect`, `/mcp/tools`, `/mcp/call`, `/mcp/servers`) поверх `request_json` |
| `frontend/mcp_section.py` | 266 | Раздел «🔌 MCP»: цель (по умолчанию — свой сервер дня 17), транспорт, кнопки подключения/отключения, статус, таблица инструментов, разбор `input_schema` и `output_schema`, вызовы блоков вызова инструмента и «Спросить агента» |
| `frontend/mcp_call.py` | 199 | Каталог серверов с кнопкой подключения, форма аргументов по `input_schema` и результат вызова (`render_servers`, `render_tool_call`, `render_call_result`) |
| `frontend/mcp_ask.py` | 134 | Блок «🤖 Спросить агента»: агент сам вызывает инструмент по реплике; отчёт `record["mcp"]` и данные инструмента в ответе |
| `frontend/common.py` | 348 | Подписи (`TASK_STAGE_LABELS`, `TASK_FLAG_LABELS`, `INVARIANT_*_LABELS`, `MCP_STATE_LABELS`, `MCP_TRANSPORT_LABELS`, `MCP_CALL_STATE_LABELS`, `MCP_REASON_LABELS`), форматтеры, `invariant_notice`, `stage_button_label`, `blocked_reason`, единый путь мутаций панели задачи `run_task_action`, `st.session_state`: init (включая `mcp_last_call`, `mcp_last_ask`), флеш-сообщения, выбор активного агента |
| `frontend/sidebar.py` | 191 | Боковая панель: агенты, создание агента, стратегия, задача и сессия (`render_sidebar()`) |
| `frontend/chat_section.py` | 301 | Раздел «💬 Чат и память», переключатель пяти разделов, блок предупреждения/отказа по инвариантам над вводом, строка про MCP-вызов в сводке хода, сборка страницы (`render_main_area()`) |
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
| `backend/api/__init__.py` | 15 | — | Описание пакета и реэкспорт роутеров (без `main`) |
| `backend/api/agents.py` | 274 | 11 | CRUD агентов, генерация, диалог, статистика токенов |
| `backend/api/context.py` | 140 | 9 | Сжатие истории, стратегии, ветки, факты |
| `backend/api/memory.py` | 180 | 10 | Слои памяти (`/memory/short-term`, `/working`, `/long-term`), сессия, задача |
| `backend/api/profiles.py` | 126 | 6 | Профили пользователей `/users...`, `GET /agents/{id}/profile` |
| `backend/api/tasks.py` | 246 | 11 | Состояние задачи: создание, список, чтение, `allowed-next`, журнал, пауза, продолжение, шаг, откат, флаги согласования, переход |
| `backend/api/invariants.py` | 139 | 6 | Инварианты: CRUD правил проекта и проверка текста (`/invariants/check`) |
| `backend/api/mcp.py` | 180 | 6 | MCP: подключение, отключение, статус, список инструментов, вызов инструмента и каталог серверов (`/mcp/...`) |
| `backend/api/main.py` | 80 | — | Сборка `app`: `lifespan`, CORS, `include_router` |

Всего 59 эндпоинтов (45 унаследованных дней 1–13 + 6 инвариантов дня 14 +
2 дня 15: `GET /tasks/{id}/allowed-next`, `PATCH /tasks/{id}/context` +
6 дней 16–17: `POST /mcp/connect`, `POST /mcp/disconnect`, `GET /mcp/status`,
`GET /mcp/tools`, `POST /mcp/call`, `GET /mcp/servers`).
Пути внутри роутеров абсолютные, префиксов нет; подключение — в
`backend/api/main.py`. Доступ к менеджеру и 404/409 —
`backend/core/dependencies.py` (`get_manager`, `get_mcp_registry`, `agent_or_404`,
`task_or_404`, `invariant_or_404`).

## `backend/schemas/` — Pydantic-схемы API, `backend/models/` — ORM

Разделение слоёв: Pydantic-схемы API — в `backend/schemas/` (реэкспорт из
`schemas/__init__.py`, импорт — `from backend.schemas import ...`), ORM-таблицы —
в `backend/models/*.py` (реэкспорт из `backend/storage/database.py`, импорт —
`from backend.storage.database import ...`). Это целевая раскладка `AGENTS.md`:
расхождение дня 12 (схемы в `models/`, ORM в `tables.py`) устранено.

| Схемы (`backend/schemas/`) | Строк | Домен |
|---|---|---|
| `schemas/__init__.py` | 184 | Реэкспорт всех схем (импорт — из `backend.schemas`) |
| `schemas/agent.py` | 336 | Агент, генерация (включая поля `task_state`, `task_intent`, `task_proposal`, `invariants` и `mcp`), метрики использования токенов |
| `schemas/context.py` | 218 | Сжатие истории, стратегии, ветки, факты |
| `schemas/mcp.py` | 193 | MCP: подключение (`MCPConnectIn`), статус (`MCPStatusResponse`), инструменты (`MCPToolSchema` с `input_schema` и `output_schema`, `MCPToolsResponse`), вызов (`MCPCallIn`, `MCPCallResponse`, `MCPCallReportOut`) и каталог серверов (`MCPServerSchema`, `MCPServersResponse`) |
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
| `models/__init__.py` | 46 | Реэкспорт ORM-классов (импорт из `backend.storage.database`) |

ORM разложен по доменам не из-за лимита строк, а по правилу слоя: файл лежит в
папке своего домена (в дне 12 ради лимита хватало пары `tables.py` +
`tables_task.py`). Строковые имена в `relationship("TaskState", ...)` не
меняются — SQLAlchemy разрешает их по registry, а все модули `models/`
импортируются из `storage/database.py`, поэтому регистрация таблиц та же, что и
до рефакторинга. Таблица `invariants` добавлена днём 14: **12 таблиц** на день
(было 11), при этом `invariants` ни с чем не связана по FK — правила проекта
живут отдельно от агентов и диалога. День 17 таблиц не добавлял.

## Тесты

`tests/` — 1222 теста `pytest`, офлайн (временная SQLite + фейк клиента
DeepSeek; MCP — свой stdio-сервер, фейк или локальный HTTP-стенд), разложены по
трём подпапкам **по фикстурам**: без БД и агента — `unit/`, с временной БД и
`Agent` — `integration/`, через `TestClient` — `e2e/`. `tests/conftest.py`,
`tests/support.py` и `tests/mcp_fakes.py` остаются в корне `tests/`: на них
опирается `pythonpath = . tests` из `pytest.ini` и импорт `from support import ...`
/ `from mcp_fakes import ...`.

| Подпапка | Файлов | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/` | 20 | 798 | Чистые модули: FSM сжатия, задачи, MCP-подключения и вызова инструмента, граф допуска и guards переходов, тексты отказа, распознавание предложения модели и запроса инструмента, блок данных MCP, каталог серверов, политика сжатия, извлечение фактов, значения профиля, значения/правила/тексты инвариантов, разбор цели MCP и структура инструмента |
| `tests/integration/` | 22 | 291 | Хранилище, сервисы и агент на временной БД: `TaskStateStore`/`TaskStateMachine`, `InvariantManager`/`InvariantChecker`, `MemoryManager`, `ProfileStore`, `ContextCompressor`, `AgentManager`, `MCPRegistry`, `MCPClient` на настоящем stdio-сервере, `MCPToolRunner` и шаг MCP в `Agent.generate` |
| `tests/e2e/` | 9 | 133 | API через `TestClient`: 59 эндпоинтов, коды 200/201/400/404/409/422/502, полный цикл задачи, поля `task_state`/`task_intent`/`task_proposal` и `invariants` в ответе генерации, шесть эндпоинтов `/mcp` и поле `mcp` в генерации |

Новые файлы дня 17 (подпапка — по фикстурам; тестов в файле) — 120 кейсов, вместе
с обновлённым `test_mcp_tools.py` (15) это 135 кейсов дня:

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_mcp_tool_call.py` | 243 | 43 | Граф вызова (сверка `ALLOWED_TRANSITIONS` с классами состояний, все допустимые пары, негативные → `UnknownMCPToolCallEvent` без смены состояния, `can`/`allowed_events`/`reset`), `admission_reason` по каждому коду причины (нет соединения, инструмент вне каталога, нет обязательного аргумента, лишний аргумент, `str`/`bool` вместо `integer`, схема без `properties`), форма `MCPToolCallOutcome` и `called`, `find_tool` |
| `tests/unit/test_mcp_intent.py` | 104 | 21 | Приоритет правил («Какие посты у пользователя 2» → `list_user_posts`), «Найди информацию о пользователе с ID 1» → `get_user` с `{"user_id": 1}`, «Покажи пост 3» → `get_post`, реплика без номера, «пользовательский отчёт» → `None`, морфология и регистр, пустая строка, инструмента нет в каталоге, порядок `\d+` |
| `tests/unit/test_mcp_prompt.py` | 74 | 9 | Блок для `done`: заголовок, имя инструмента, JSON аргументов и результата, строка-инструкция; пустая строка для `idle`/`rejected`/`failed`; текст инструмента, когда структуры нет |
| `tests/unit/test_mcp_servers.py` | 81 | 11 | Три записи каталога в порядке `KNOWN_SERVERS`, `connected` ровно у одного, `tool_count` только у подключённого, неразобранная цель не даёт исключения |
| `tests/integration/test_mcp_server_stdio.py` | 89 | 5 | Настоящий `mcp_server/server.py` дочерним процессом с `--api-base` на локальный стенд: каталог из трёх инструментов, `required` и непустой `output_schema` у `get_user`, успешный вызов, `is_error` на несуществующем id с упоминанием 404, `list_user_posts` с `limit`, ошибка без соединения |
| `tests/integration/test_mcp_tool_runner.py` | 160 | 10 | Раннер: успешный вызов (`done`, `accepted`, `called`, структура), `call_error` → `failed`/`tool_error`, `call_fail` → `failed`/`transport`, без подключения → `rejected`/`not_connected`, инструмент вне каталога, неверный тип аргумента, `call_for_prompt` с ключевыми словами и без |
| `tests/integration/test_mcp_agent.py` | 161 | 8 | Шаг MCP в `Agent.generate`: инструмент вызван, аргументы верные, блок данных в системном сообщении запроса и в `record["system_prompt"]`, `added_tokens > 0`; без ключевых слов инструмента нет; «Расскажи про пользователя» → `bad_arguments`, но генерация `ok`; без соединения — `connected false`; сбой инструмента не роняет ход |
| `tests/e2e/test_mcp_call_api.py` | 184 | 13 | `POST /mcp/call` и `GET /mcp/servers` через `TestClient`: 409 без соединения, 200 с полным набором полей, 400 на неизвестный инструмент и неверный тип аргумента, 422 на пустое имя и превышение длины, 502 при обрыве связи, 200 + `is_error` при ошибке инструмента, каталог серверов (3 записи), `output_schema` в `/mcp/tools`, поле `mcp` в генерации |

Обновлены в дне 17 (числа строк и тестов — фактические):

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
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов (включая токены блока MCP), логи отказа и неприменимого намерения |
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API, чтение `DEEPSEEK_API_KEY` |
| `backend/storage/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/models/*.py` | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/storage/task_store.py` | `shared.logging_utils.get_logger` | Отладочный лог записанного перехода |
| `backend/storage/invariant_store.py` | `shared.logging_utils.get_logger` | Отладочный лог созданного/изменённого инварианта |
| `backend/services/invariant_checker.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger` | Клиент для LLM-слоя проверки и лог причины, по которой проверка не выполнена |
| `backend/services/mcp_client.py` | `shared.logging_utils.get_logger` | Логи подключения, закрытия, ошибок MCP и вызовов инструмента |
| `backend/services/mcp_registry.py` | `shared.logging_utils.get_logger` | Лог ошибки закрытия прошлого MCP-соединения при смене сервера |
| `backend/services/mcp_tool_runner.py` | `shared.logging_utils.get_logger` | Лог отклонённого вызова и сбоя инструмента |
| `backend/api/main.py` | `shared.logging_utils.get_logger` | Логгер бэкенда |

Модули `frontend/` обращаются к бэкенду только по HTTP
(`frontend/api_client.py`), поэтому `shared/` напрямую не импортируют. Пакет
`mcp_server/` — тоже: он запускается отдельным процессом и живёт на stdlib,
`httpx` и SDK `mcp`, без кода дня.

## Известные расхождения

| Файл | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agents/agent.py` | 1898 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи и переходы, инварианты, шаг MCP, генерация) не разложен на миксины — расхождение унаследовано от дней 11–16 (в день 14 было 1727, в день 15 — 1825, в день 16 — 1825, в день 17 +73 дал шаг MCP), рефакторинг `Agent` в дни 15–17 не входил |
| `invariants_demo.md` лежит в корне дня | — | — | Путь задан заданием дня 14; в `docs/reports/` файл не дублируется (там лежат отчёты `mcp_tool_demo.md` дня 17, `mcp_demo.md` дня 16 и унаследованные) |
| `done` не пускает никуда | — | — | Терминальность `done` (день 15) — следствие требования «контролируемые переходы»: пауза из `done` отклоняется с объяснением, а не выполняется молча; поведение дня 13, разрешавшее `done → paused`, обновлено вместе с тестами и документацией |
| ORM разложен на 7 модулей `models/*.py` | 41–157 | 400 | Домен один (таблицы дня), но по правилу слоя файл лежит в папке своего домена; заодно снят вопрос лимита, который в дне 12 решался парой `tables.py` + `tables_task.py` |
| `backend/agents/profile_store.py` (292) и `backend/agents/memory.py` (291) | — | — | Имена модулей сохранены (в целевом списке слоя они могли бы называться `profile_manager.py` / `memory_manager.py`) |
| `INVARIANT_LLM_CHECK` добавляет вызов DeepSeek | — | — | По умолчанию проверка ОТВЕТА идёт в LLM, когда детерминированные правила молчат: это осознанная цена семантической проверки, выключается одной строкой в `backend/core/config.py` (так работает офлайн-отчёт `scripts/invariants_demo.py`) |
| `scripts/video_scenario*.py` (8 модулей) | 69–386 | 400 | Унаследованы из дня 15 и проверяют кадры **прежнего** сценария (контролируемые переходы, §8 прежней инструкции); в демонстрации дня 17 не участвуют: минимальный сценарий даёт `scripts/mcp_tool_demo.py`. Скрипты не удалены как артефакт доказательств дня 15 |
| MCP-подключение не в БД | — | — | У подсистемы нет таблиц: соединение живёт в памяти процесса (`MCPRegistry`), поэтому после рестарта бэкенда `/mcp/status` отвечает `disconnected`. Это осознанно: связь с внешним сервером — не данные домена |
| Одно соединение на процесс | — | — | `GET /mcp/servers` отдаёт каталог известных целей (3 записи), а не несколько одновременных соединений; `connected` истинно ровно у одной записи — унаследованное от дня 16 свойство `MCPRegistry` |
| Вызовы инструмента идут наружу | — | — | `MCPToolRunner` выполняет настоящий HTTP-запрос к `jsonplaceholder.typicode.com` (через свой процесс сервера). В промпт агента попадает только успешный результат: отказ по правилам допуска и ошибка инструмента остаются в отчёте `record["mcp"]` |
| `backend/services/mcp_client.py` делит цикл событий с вызывающим потоком | 392 (+ `mcp_loop.py` 96, `mcp_transport.py` 65) | 400 | Клиент запускает свой daemon-поток с циклом событий и долгоживущую задачу сессии: контексты MCP SDK обязаны входить и выходить в одной задаче anyio. Публичные методы синхронные (FastAPI и Streamlit синхронные), потокобезопасные через `RLock`. Цикл событий и адаптеры SDK вынесены в `mcp_loop.py` и `mcp_transport.py`, потому что в одном файле клиент выходил за лимит (423 строки) |
| `tests/support.py` разделён с `tests/mcp_fakes.py` | 255 (+ 211) | 400 | MCP-фейки вынесены в отдельный модуль `tests/mcp_fakes.py`: вместе с ними `support.py` выходил за лимит (453 строки). Импорты переведены на `mcp_fakes` без реэкспорта (clean cutover) |

Лимиты `app.py` (71 ≤ 100) и `backend/api/main.py` (80 ≤ 80) соблюдены.

## Проверка лимита строк

Из папки `day17` (исключены `.venv` и вендорный `.agents/`):

```powershell
uv run python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and '.agents' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод сегодня: `[('backend\\agents\\agent.py', 1898)]`.

Каталог `.agents/` исключён не для красоты: в этой копии скиллы библиотек
скопированы (а не слинкованы), и шаблоны Streamlit внутри них длиннее 400 строк.
Это код библиотеки, а не дня; в дне 14 те же скиллы — симлинки, поэтому `**` в их
содержимое не заходит и команда дня 14 обходится без исключения.
