# Структура дня 20

Карта модулей дня 20: что где лежит и за что отвечает. Правила структуры — в
[`../AGENTS.md`](../AGENTS.md) и [`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

День 20 — копия дня 19 плюс **оркестрация флота из трёх независимых
MCP-серверов**. В дне появились три отдельных stdio-процесса
(`mcp_servers/search_server`, `data_server`, `storage_server`, 11 инструментов на
троих), их конфигурация как **данные** (`mcp_servers.json`), многоподключенческий
`MCPRegistry` с **маршрутизацией вызова по имени инструмента**, `Orchestrator`
(план шагов → маршрутизация → вызов → журнал → FSM), роутеры `/orchestration` и
`/mcp/servers`, раздел «🌐 Оркестрация» в Streamlit с кнопкой «🚀 Запустить
демо-сценарий» и отчёт `docs/reports/orchestration_demo.md` по пяти сценариям.

**Почему флот — три отдельных процесса.** Каждый сервер поднимается по stdio
своим процессом и импортирует только свой пакет, stdlib, `httpx`, SDK `mcp` и
общий `shared/` (проверено: ни `backend/`, ни `mcp_server/`, ни соседние серверы
не импортируются). Поэтому падение или зависание одного сервера не задевает
остальных, а состав флота меняется файлом, а не кодом. Своя копия логики сводки в
`data_server/summarize.py` — цена этой независимости: сервер флота не имеет права
импортировать код дня.

**Почему состав флота — данные.** `mcp_servers.json` описывает имя, команду
запуска, аргументы и описание каждого сервера, а `tools_cache` хранит последний
известный каталог его инструментов. Формат живёт в домене
(`backend/domain/mcp_server_spec.py`), доступ к файлу — в слое `core`
(`backend/core/mcp_server_config.py`), а подключает серверы реестр служб
(`backend/services/mcp_registry.py`). Реестр читает файл при `connect_all()`,
поэтому четвёртый сервер достаточно дописать в конфигурацию — код не меняется
(сценарий 5 прогона). Кэш в файле нужен на случай, когда сервер ещё не поднялся:
`list_all_tools()` и `find_tool_by_name()` работают по нему офлайн.

**Почему маршрутизация в реестре.** План шага называет только **инструмент**, без
сервера: «чьим инструментом является имя» решает `find_tool_by_name` (первый
сервер в порядке файла, при дублях — предупреждение в лог), а поднимает нужное
соединение `ensure_connected`. Так один и тот же `DEMO_PLAN` работает и на
полном флоте, и на урезанном каталоге, а инструменты с одинаковыми именами у
разных серверов не ломают прогон.

Оркестрация добавляет **две таблицы** — `orchestration_runs` (запуск: запрос,
план, статус, начало, конец, длительность, список участников) и
`orchestration_steps` (шаг: сервер, инструмент, входные аргументы, выходной
результат, время, статус, текст ошибки). Журнал лежит в SQLite, а не в памяти,
потому что прогон может идти фоновым потоком процесса бэкенда: интерфейс
опрашивает статус и видит прогресс, пока шаги выполняются, а после перезапуска
приложения история запусков читается снова (сценарий 4). Удаление запуска уносит
его шаги каскадом (`ON DELETE CASCADE`).

Инструмент `save_to_db` пишет в **`day20/storage.db`**, а не в `agents.db`:
в `agents.db` пишет ровно один процесс (бэкенд дня), а `storage_server` — тоже
отдельный процесс, поэтому общий файл сделал бы двух писателей (инвариант дня 18).

Унаследовано полностью: планировщик фоновых задач (день 18) с шестью таблицами,
свой MCP-сервер дня (`mcp_server/`, девять инструментов) и вызов инструмента
агентом с правилами допуска (`mcp_*`), декларативный пайплайн (день 19) с двумя
таблицами, контролируемые переходы (день 15) и инварианты (день 14), состояние
задачи как конечный автомат (день 13), персонализация профилем (день 12), три
слоя памяти и четыре стратегии контекста (день 11). Активное MCP-подключение
раздела «🔌 MCP» по-прежнему таблиц в БД не имеет: оно живёт в памяти процесса.

`STRUCTURE.md` — только карта модулей: он не заменяет `README.md` (нарратив дня и
команды запуска) и `docs/` (`architecture.md`, `api.md`, `usage.md`).

## Раскладка

```
day20/
├── app.py                    # точка входа Streamlit (67 строк, лимит 100): set_page_config + вызовы секций
├── mcp_servers.json          # КОНФИГУРАЦИЯ ФЛОТА: три сервера (команда, аргументы, описание) + кэш каталогов tools_cache
├── mcp_servers/              # ТРИ независимых MCP-сервера дня 20 — каждый отдельным процессом по stdio
│   ├── __init__.py           # докстринг пакета: состав флота, запуск `uv run python mcp_servers/<server>/server.py`, транспорт
│   ├── search_server/        # поиск данных: search_web, search_local, fetch_url (тела — web.py, local.py, fetch.py)
│   ├── data_server/          # обработка данных: summarize, extract_keywords, filter_by_date, aggregate
│   └── storage_server/       # сохранение и выдача: save_to_file (output/), save_to_db (storage.db), list_saved, load_from_file
├── mcp_server/               # СОБСТВЕННЫЙ MCP-сервер дня — унаследован от дней 17–19 (11 модулей, девять инструментов, stdio)
├── frontend/                 # Streamlit UI по секциям (24 модуля, включая __init__.py)
│   ├── orchestration_api.py  # HTTP-запросы оркестрации и флота поверх api_client
│   ├── orchestration_section.py # раздел «🌐 Оркестрация»: флот, кнопка демо, прогресс, история, статистика
│   └── orchestration_steps.py   # один шаг прогона: раскрывающийся отчёт, mermaid-диаграмма флоу, таблица шагов
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным (девять слоёв, в каждом __init__.py)
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # 11 роутеров по доменам (в том числе mcp_servers.py, orchestration.py), сборка app (main.py), lifespan.py
│   ├── core/                 # config (файл флота, границы плана, API_TITLE), mcp_server_config (чтение/запись флота), dependencies
│   ├── domain/               # чистые правила и данные: 41 модуль, в том числе mcp_server_spec и шесть модулей orchestration_*
│   ├── services/             # прикладные сервисы: 20 модулей, в том числе mcp_fleet_state, mcp_registry, orchestrator,
│   │                         # orchestration_service, orchestration_planner
│   ├── storage/              # доступ к БД: 11 модулей, в том числе orchestration_store.py (запуски и шаги) и orchestration_rows.py
│   ├── agents/               # Agent (в generate — шаг оркестрации), MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы: 10 модулей, в том числе orchestration.py (две таблицы дня 20)
│   ├── schemas/              # Pydantic-схемы API: 11 модулей, в том числе orchestration.py и mcp_servers.py
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 2144 теста (unit/ — 1506, integration/ — 458, e2e/ — 180)
│   ├── conftest.py           # общие фикстуры (+ autouse-фикстура no_real_fleet: настоящий флот тесты не поднимают)
│   ├── orchestration_fakes.py # фейки флота: каталоги трёх серверов, результаты 11 инструментов, make_fleet_registry
│   ├── mcp_fakes.py          # MCP-фейки (день 17): FakeMCPClient с журналом вызовов, make_mcp_factory (+ cwd)
│   ├── pipeline_fakes.py     # фейки пайплайна дня 19
│   ├── mcp_echo_server.py    # унаследованный тестовый MCP-сервер (echo, add) — на нём сценарий 5 (четвёртый сервер)
│   ├── stub_api.py           # локальный стенд jsonplaceholder (+ ручка /html для fetch_url)
│   └── support.py, scheduler_fakes.py, search_sources_fakes.py, backend_stub.py  # унаследованные помощники тестов
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов (32 модуля, не пакет)
│   ├── orchestration_demo.py # точка входа дня 20: временный mcp_servers.json, пять сценариев, отчёт, --tests
│   ├── orchestration_scenarios.py # сценарии 1–3 (демо-кнопка, реплика агента, ошибка на шаге)
│   ├── orchestration_fleet.py    # сценарии 4–5 (перезапуск приложения, четвёртый сервер правкой файла)
│   ├── orchestration_report.py   # сборка docs/reports/orchestration_demo.md из данных прогона
│   └── orchestration_report_flow.py  # подписи рёбер и текстовая схема потока для отчёта
├── invariants_demo.md        # отчёт дня 14 (унаследован; лежит в корне дня — путь задан заданием дня 14)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── pyproject.toml, uv.lock   # зависимости (uv): mcp, httpx, apscheduler, sqlalchemy…; точные версии — в локе
├── .agents/skills/           # скиллы библиотек (uvx library-skills --copy); не код дня
├── .python-version           # 3.14
├── .env.example              # шаблон DEEPSEEK_API_KEY и DAY20_BACKEND_URL (.env не копировался из дня 19)
├── output/                   # каталог результатов save_to_file (пример прогона: demo-scenario.md)
├── storage.db                # SQLite сервера хранения (в git не попадает: *.db в корневом .gitignore)
└── agents.db                 # SQLite бэкенда дня (тоже под *.db)
```

Отчёты прогонов лежат в `docs/reports/`: `orchestration_demo.md` — отчёт дня 20
(его создаёт `uv run python scripts/orchestration_demo.py --report docs/reports/orchestration_demo.md`;
там обязательная таблица «шаг | сервер | инструмент | входные данные | выходные
данные | время выполнения | статус»), `pipeline_demo.md` — отчёт дня 19,
`scheduler_demo.md` — дня 18, `mcp_tool_demo.md` — дня 17, `mcp_demo.md` — дня 16,
`task_state_demo.md` — дня 13, `personalization_comparison.md` — дня 12
(унаследованы). `invariants_demo.md` — в корне дня, в `docs/reports/` не
дублируется.

Скрипты в `scripts/` не пакет: они находят корень дня
(`Path(__file__).resolve().parents[1]`) и добавляют его в `sys.path` сами, поэтому
`uv run python scripts/<script>.py` работает из любой рабочей директории. Пакеты
`mcp_server/` и каждый сервер в `mcp_servers/` — наоборот: у них `DAY_ROOT` и
`REPO_ROOT` вычисляются от файла `config.py` (`parents[1]` и `parents[2]`), потому
что запускаются отдельным процессом, где ни корень дня, ни корень репозитория в
`sys.path` не попадают.

## Слои `backend/`

| Слой | Файлов | Что там |
|---|---|---|
| `api/` | 14 | HTTP: 11 роутеров по доменам (включая `mcp_servers.py` — флот и `orchestration.py` — запуски), `lifespan.py` (старт и остановка фоновых служб) и `main.py` (сборка `app`) |
| `core/` | 4 | `config.py` (настройки дня, в том числе файл флота и границы плана), `mcp_server_config.py` (чтение `mcp_servers.json` и запись `tools_cache`), `dependencies.py` (доступ роутов к менеджеру, реестру, планировщику, службам пайплайна и оркестрации) |
| `domain/` | 42 | Чистые правила и данные без БД и сети: FSM задачи/сжатия/MCP/планировщика/пайплайна/**оркестрации**, графы переходов, расписания, агрегация, распознавание реплик, маппинг аргументов, стратегии, профиль, инварианты, тексты промптов, спецификация сервера флота и план шагов. Знают только stdlib, `core.config` и соседей по слою |
| `services/` | 21 | Прикладные сервисы: компрессор, состояние задачи, инварианты, `mcp_*` (клиент, транспорт, ошибки, реестр с флотом, состояние сервера, раннер инструмента), планировщик и его службы, пайплайн, **оркестратор, служба и планировщик плана оркестрации** |
| `storage/` | 12 | Доступ к БД: `database.py` (движок, сессии, реэкспорт ORM), хранилища задач, инвариантов, памяти, планировщика, пайплайна и **оркестрации** (+ модули «строка → словарь») |
| `agents/` | 12 | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов; менеджер передаёт агентам реестр MCP, службу пайплайна и **службу оркестрации** |
| `models/` | 11 | ORM-таблицы SQLAlchemy по доменам, включая **`orchestration.py`** (`orchestration_runs`, `orchestration_steps`) |
| `schemas/` | 12 | Pydantic-схемы API по доменам, включая **`orchestration.py`** и **`mcp_servers.py`** |
| `utils/` | 1 | Своего кода нет (`__init__.py`): общий клиент DeepSeek, база, токены и логи — в repo-level `shared/` |

Девять слоёв обязательны и все содержат `__init__.py` с реэкспортом публичных
имён слоя — это единственное место, где виден публичный контракт. `api/__init__.py`
намеренно **не** импортирует `main`: `core.dependencies.get_manager` тянет
`api.main` лениво, иначе возник бы цикл `api → core → api`. По той же причине
`storage/task_store.py` берёт `MemoryManager` внутри свойства, а
`core/dependencies.py` — `AgentManager` только под `TYPE_CHECKING`.

`domain/__init__.py` (395 строк) импортирует модули планировщика, пайплайна и
оркестрации **как модули** (`from . import orchestration_fsm, orchestration_plan,
pipeline_spec, …`), а не реэкспортирует их имена: иначе список имён слоя вышел бы
за лимит 400 строк. Код дня и так берёт имена из своего модуля
(`from ..domain.orchestration_spec import DEMO_PLAN`), поэтому точек входа
`backend.domain.orchestration_fsm` и соседей достаточно.

## Флот MCP-серверов: `mcp_servers/`

Каждый сервер — независимый процесс со своим пакетом: `config.py` (константы),
`schemas.py` (`TypedDict` ответов, из которых SDK собирает `outputSchema`),
модуль на каждый инструмент и `server.py` (`MCPServer(name=…, version=…,
instructions=…)`, объявление инструментов декоратором `@mcp.tool()`, `parse_args`,
`main()` → `run(transport="stdio")`). Параметры инструментов типизированы, ошибка
инструмента — `ToolError` с понятным текстом.

### `search_server/` — поиск данных

| Модуль | Строк | Назначение |
|---|---|---|
| `search_server/__init__.py` | 17 | Докстринг пакета: сервер поиска, его инструменты и способ запуска |
| `search_server/config.py` | 74 | Адрес jsonplaceholder и API Википедии, таймаут, границы аргументов (`MAX_ITEMS`, `MAX_PAGE_ROWS`, `CONTENT_MAX`, `FETCH_MAX_CHARS_*`), `FILE_ROOT` (корень поиска `search_local`), имя/версия/инструкция сервера |
| `search_server/schemas.py` | 56 | `TypedDict` ответов: `SearchItem`, `WebSearchResult`, `LocalSearchResult`, `FetchUrlResult` |
| `search_server/web.py` | 205 | Тело `search_web`: страница ленты jsonplaceholder (`posts`/`users`) и поиск Википедии (opensearch); неподдержанный источник — ошибка инструмента |
| `search_server/local.py` | 108 | Тело `search_local`: файл внутри папки дня, нарезка на блоки по пустым строкам, фильтр подстрокой; путь вне `FILE_ROOT` — ошибка |
| `search_server/fetch.py` | 135 | Тело `fetch_url`: страница по HTTP → текст (теги, `<script>` и `<style>` снимаются), обрезка до `max_chars` с флагом `truncated` |
| `search_server/server.py` | 121 | Сервер и точка входа: три инструмента (`search_web`, `search_local`, `fetch_url`), `--api-base`/`--wiki-base`/`--timeout`/`--file-root` |

### `data_server/` — обработка данных

| Модуль | Строк | Назначение |
|---|---|---|
| `data_server/__init__.py` | 24 | Докстринг пакета: четыре инструмента обработки данных |
| `data_server/config.py` | 132 | Стили и границы сводки, границы списков и ключевых слов, форматы дат, метрики агрегации, настройки LLM, `ENV_FILE = day20/.env`, `resolve_api_key()`, имя/версия/инструкция |
| `data_server/schemas.py` | 57 | `TypedDict` ответов: `SummaryResult`, `KeywordsResult`, `FilterResult`, `AggregateGroup`, `AggregateResult` |
| `data_server/summarize.py` | 220 | Тело `summarize`: стиль и длина, промпт, разбор ключевых пунктов и агрегационная сводка без LLM |
| `data_server/llm_client.py` | 86 | Необязательный вызов DeepSeek внутри `summarize` (`configure`, `available`, `summarize`); без ключа — `LLMUnavailable` и агрегация |
| `data_server/keywords.py` | 73 | Тело `extract_keywords`: частоты слов без стоп-слов, топ-`limit`, строка `joined` |
| `data_server/dates.py` | 123 | Тело `filter_by_date`: разбор ISO-8601 и `ДД.ММ.ГГГГ`, границы `since`/`until`, счётчик `skipped` |
| `data_server/aggregate.py` | 115 | Тело `aggregate`: группировка и метрики `count`/`sum`/`avg`/`min`/`max`, сортировка по убыванию, обрезка |
| `data_server/server.py` | 112 | Сервер и точка входа: четыре инструмента (`summarize`, `extract_keywords`, `filter_by_date`, `aggregate`), `--llm {auto,off}` и `--timeout` |

### `storage_server/` — сохранение и выдача

| Модуль | Строк | Назначение |
|---|---|---|
| `storage_server/__init__.py` | 21 | Докстринг пакета: сервер сохранения и выдачи |
| `storage_server/config.py` | 77 | `OUTPUT_DIR` (`day20/output/`), `DB_PATH` (`day20/storage.db`), таблица `saved_records`, форматы txt/md/json, границы имени и текста, `LIST_KINDS`, имя/версия/инструкция |
| `storage_server/schemas.py` | 68 | `TypedDict` ответов: `SavedFile`, `SavedFileInfo`, `SavedRecord`, `SavedRecordInfo`, `SavedList`, `LoadedFile` |
| `storage_server/files.py` | 190 | Тело `save_to_file`/`load_from_file`: чистка имени (путь и `..` запрещены), форматы txt/md/json, список файлов каталога вывода |
| `storage_server/db.py` | 180 | Тело `save_to_db`/`list_saved` по строкам: схема `saved_records` на `sqlite3`, вставка, чтение с фильтром по виду |
| `storage_server/server.py` | 188 | Сервер и точка входа: четыре инструмента (`save_to_file`, `save_to_db`, `list_saved`, `load_from_file`), `--output-dir`/`--db-path` |

### `mcp_servers.json` — конфигурация флота

Файл в корне дня: три записи (`name`, `command`, `args`, `description`,
`tools_cache`). Сейчас в нём `search_server` (`uv run python
mcp_servers/search_server/server.py`), `data_server` и `storage_server`; в
`tools_cache` записаны 3, 4 и 4 инструмента — всего 11. Кэш обновляет
`POST /mcp/servers/refresh` (запись атомарная: `.tmp` + `os.replace`, иначе
второй процесс дня, Streamlit, мог бы прочитать половину JSON).

## Домен оркестрации: `backend/domain/`

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/mcp_server_spec.py` | 184 | Запись сервера флота как данные: `MCPServerSpec` (`name`, `command`, `args`, `description`, `tools_cache`, свойство `target`), `load_server_specs` (нет файла → `[]`, битый JSON → ошибка), `validate_specs`, `dump_specs` |
| `backend/domain/orchestration_spec.py` | 219 | План оркестрации как данные: константы имён/статусов/кодов причин, `DEMO_PLAN` (5 шагов по трём серверам), `DEMO_QUERY`, `validate_plan` и `OrchestrationRejected` — шаг без сервера, потому что маршрутизацию решает реестр |
| `backend/domain/orchestration_fsm.py` | 167 | Стейт-машина прогона: `OrchestrationState` (`idle`/`running`/`completed`/`stopped`/`failed` — ровно статусы колонки `orchestration_runs.status`), события `START/ADVANCE/FINISH/STOP/FAIL`, граф переходов, `allowed_events`; структура повторяет `pipeline_fsm.py` дня 19 |
| `backend/domain/orchestration_plan.py` | 220 | План по каталогу флота: `PLANNER_SYSTEM_PROMPT` (в нём требование «Определи, какие инструменты с каких серверов нужно вызвать и в каком порядке»), `PLAN_JSON_HINT`, `catalog_text`, `build_plan_prompt`, `parse_plan` (любая неудача → `None`), `heuristic_plan` (шаги `DEMO_PLAN`, отфильтрованные по доступным инструментам) — здесь нет ни одного сетевого вызова |
| `backend/domain/orchestration_prompt.py` | 75 | Блок результата оркестрации в системном промпте: заголовок, запрос, серверы, по строке на шаг, итог и футер «данные собраны цепочкой MCP-инструментов»; пустой отчёт или провал → пустая строка |
| `backend/domain/orchestration_intent.py` | 109 | Распознавание реплики «выполни флоу по нескольким серверам»: узкий список фраз (`в базу`, `в бд`, `в sqlite`, `оркестрац`, `цепочк`, …), `OrchestrationIntent` и аргументы запуска (`query`, `limit`, `filename`, `format`) |

Почему правило распознавания узкое: реплика дня 19 «найди статьи про RAG, сделай
сводку и сохрани в файл» обязана остаться пайплайном (её контракт закреплён
тестом `tests/integration/test_pipeline_agent.py`), а требование дня 20 «найди
данные и сохрани в БД» пайплайн выполнить не может — он пишет только файл.
Поэтому оркестрация включается на явный признак («в бд», «в базу», «в sqlite»,
слово про оркестрацию или несколько серверов), а не на любой запрос с двумя
инструментами.

## Доступ к конфигурации флота: `backend/core/`

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/core/mcp_server_config.py` | 96 | Связь домена с диском: `load_specs(path)` (по умолчанию `config.MCP_SERVERS_FILE`), `save_tools_cache(name, tools, path)` — обновляет только `tools_cache` одного сервера и пишет файл атомарно; отсутствующий файл — понятная ошибка |

## Сервисы оркестрации: `backend/services/`

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/services/mcp_fleet_state.py` | 52 | `FleetMember`: запись сервера в памяти реестра (конфигурация + соединение + каталог инструментов + текст последней ошибки). Вынесен из `mcp_registry.py`, который подошёл к лимиту 400 строк; каталог может прийти из `tools_cache`, если сервер ещё не поднялся |
| `backend/services/mcp_registry.py` | 391 | Центр изменения дня: **активное** соединение раздела «🔌 MCP» (`connect`/`disconnect`/`tools`/`call_active_tool`/`status`) плюс **флот** (`connect_all`, `disconnect_all`, `refresh_tools`, `servers`, `tools_of`, `list_all_tools`, `find_tool_by_name`, `ensure_connected`, `call_tool_on`, `fleet_status`). Старое `call_tool` раздвоилось: вызов активного соединения — `call_active_tool`, а `call_tool` теперь маршрутизирует по имени инструмента |
| `backend/services/orchestrator.py` | 345 | `Orchestrator`: `build_plan` (явный план → `source=given`, план модели → `llm`, иначе эвристика → `heuristic`) и `run` — на каждый шаг `resolve_mapping` → `evaluate_guard` → `find_tool_by_name` → `ensure_connected` → `MCPToolRunner` → `store.add_step` → событие FSM. Единственное место, где домен оркестрации встречается с флотом |
| `backend/services/orchestration_service.py` | 233 | `OrchestrationService`: когда запускать (синхронно или фоновым потоком), что отдавать API и как читать журнал: `start_run`, `start_demo`, `report`, `list_runs` (+`stats`), `steps`, `delete_run`, `statuses`. Строка запуска создаётся синхронно, терминальный `failed` ставится даже при исключении в потоке |
| `backend/services/orchestration_planner.py` | 94 | Планировщик плана на DeepSeek: `available` (есть ли ключ) и `plan(query, tools)` — промпт из домена, вызов модели, разбор ответа. Любая неудача или отсутствие ключа → `None` (не исключение: оркестратор перейдёт на эвристику) |

## Хранилище и модели

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/models/orchestration.py` | 97 | ORM-таблицы дня 20: `OrchestrationRun` (`orchestration_runs`: запрос, план-JSON, статус, начало, конец, длительность, `servers_used`) и `OrchestrationStep` (`orchestration_steps`: индекс, сервер, инструмент, входные аргументы, выходной результат, время, статус, ошибка; каскад от запуска) |
| `backend/storage/orchestration_rows.py` | 52 | ORM-строки → словари для API/UI (`run_dict`, `step_dict`); метки времени — через `as_utc`, JSON-поля — через `jsonable` из `scheduler_rows.py` |
| `backend/storage/orchestration_store.py` | 204 | `OrchestrationStore`: создание запуска, терминальный статус, строка журнала на шаг, история, удаление и `stats()` (число запусков и шагов, среднее время шага, вызовы по серверам и инструментам) |

Почему журнал в SQLite, а не в памяти: прогон идёт фоновым потоком, поэтому
интерфейс читает прогресс по номеру запуска (`GET /orchestration/runs/{id}`), а
после перезапуска приложения история остаётся. Хранилище (`storage/`) знает про
сессии SQLAlchemy, правила (`domain/`) — про допустимые переходы статуса; граница
та же, что у `PipelineStore` дня 19.

## API и схемы

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/api/mcp_servers.py` | 101 | Роутер флота: `GET /mcp/servers` (состав и состояние подключений), `GET /mcp/servers/{name}/tools` (каталог одного сервера, 404 на неизвестный), `POST /mcp/servers/refresh` (перечитать каталоги и записать кэш в файл; сбой сервера — данные в его записи) |
| `backend/api/orchestration.py` | 191 | Роутер оркестрации, шесть эндпоинтов: `POST /orchestration/run`, `POST /orchestration/demo`, `GET /orchestration/runs`, `GET /orchestration/runs/{run_id}`, `GET /orchestration/runs/{run_id}/steps`, `DELETE /orchestration/runs/{run_id}`; хелпер отказов различает 400 (негодный план или запрос) и 404 (нет запуска) |
| `backend/schemas/mcp_servers.py` | 84 | `MCPServerInfo` (имя, команда, аргументы, описание, цель, транспорт, `connected`, `state`, число инструментов, ошибка), `MCPServersResponse`, `MCPServerToolsResponse`, `MCPRefreshResponse` |
| `backend/schemas/orchestration.py` | 199 | Схемы запуска и журнала: `OrchestrationRunIn`, `OrchestrationDemoIn`, `OrchestrationStepOut`, `OrchestrationRunOut`, `OrchestrationStartOut`, `OrchestrationRunReportOut`, `OrchestrationRunsResponse`, `OrchestrationStepsResponse` и `OrchestrationReportOut` — поле `orchestration` ответа генерации агента |

Семантика `GET /mcp/servers` в дне 20 изменилась: раньше это был каталог
«известных серверов для сравнения» (день 16), теперь — реальный состав флота из
`mcp_servers.json`, где `connected` означает «этот сервер подключён прямо сейчас»,
а не «выбран пользователем». За активное соединение раздела «🔌 MCP» отвечают
пять эндпоинтов `/mcp/*` (`backend/api/mcp.py`).

## Интерфейс: `frontend/`

| Модуль | Строк | Назначение |
|---|---|---|
| `frontend/orchestration_api.py` | 75 | HTTP-запросы дня 20 поверх общего `request_json`: запуск, демо-сценарий, история, отчёт о запуске, его шаги, удаление, состав флота, инструменты сервера, обновление кэша |
| `frontend/orchestration_section.py` | 340 | Раздел «🌐 Оркестрация»: таблица флота и обновление кэша, большая кнопка «🚀 Запустить демо-сценарий», прогресс шагов фрагментом раз в секунду, диаграмма флоу, таблица шагов, история с удалением, статистика по серверам и инструментам |
| `frontend/orchestration_steps.py` | 152 | Всё, что рисует один шаг и связи между шагами: раскрывающийся отчёт (`input_args` и результат), mermaid-диаграмма (узел на шаг, подпись ребра — объём данных) и таблица шагов с колонками требования дня |

`orchestration_steps.py` вынесен из раздела, а подписи оркестрации — из
`frontend/common.py`: тот файл ровно 400 строк (лимит), поэтому день 20 его не
правил. Отдельный модуль `orchestration_api.py` — по той же причине, по которой
есть `mcp_api.py` и `pipeline_api.py`: общий транспорт живёт в `api_client.py`, а
запросы домена — в модуле домена.

## Скрипты: `scripts/`

| Модуль | Строк | Назначение |
|---|---|---|
| `scripts/orchestration_demo.py` | 261 | Точка входа прогона дня 20: собирает временный `mcp_servers.json` с тремя настоящими серверами (`sys.executable` и абсолютные пути, `--llm off`), поднимает флот на временной БД, прогоняет пять сценариев, печатает трассировку шагов и итог «проверок пройдено: N/M», по флагу `--tests` запускает pytest, пишет отчёт; код возврата 1 при любой непройденной проверке |
| `scripts/orchestration_scenarios.py` | 358 | Сценарии 1–3: демо-сценарий кнопки по настоящему флоту, реплика агента «найди данные про RAG и сохрани в базу» на офлайн-заглушке модели, ошибка на шаге (неизвестный инструмент и слишком длинный текст) |
| `scripts/orchestration_fleet.py` | 127 | Сценарии 4–5: перезапуск приложения (новый реестр на той же БД читает историю и поднимает флот заново) и четвёртый сервер (`echo_server`) правкой копии `mcp_servers.json` — без изменения кода реестра |
| `scripts/orchestration_report.py` | 366 | Сборка `docs/reports/orchestration_demo.md` из данных прогона: проверки, состав флота, сценарии 1–5 (в первом — файл из `output/`, строка `saved_records` и снимок интерфейса по флагу `--screenshot`), схема двух таблиц, автотесты дня и рамки |
| `scripts/orchestration_report_flow.py` | 77 | Подписи рёбер диаграммы и текстовая схема потока (`edge_label`, `flow_diagram`, `flow_text`): те же правила, что в `frontend/orchestration_steps.py`, продублированы осознанно — импорт интерфейса из скрипта притянул бы Streamlit |

Четыре модуля, а не один скрипт: прогон делает разные вещи разными средствами —
собирает флот процессов, проходит сценарии, проверяет состояние после перезапуска
и верстает markdown; одним файлом это далеко за лимитом 400 строк, а смешивать
запуск процессов, реплику агента и вёрстку отчёта незачем.

## Тесты: `tests/`

Набор дня 20 — 2144 теста в подпапках `unit/` (1506), `integration/` (458) и
`e2e/` (180); классификация по фикстурам: чистые модули / временная БД и агент /
`TestClient`. Файлы дня 20:

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки | `tests/orchestration_fakes.py` (265) | Каталоги трёх серверов (`FLEET_CATALOGS`), результаты 11 инструментов, `FakeFleetClient`, `make_fleet_factory`, `write_servers_file`, `make_fleet_registry` — на них идут тесты реестра, оркестратора и API без поднятия настоящих процессов |
| Домен и конфигурация флота | `unit/test_mcp_server_spec.py` (167), `unit/test_mcp_server_config.py` (96), `unit/test_orchestration_spec.py` (155), `unit/test_orchestration_fsm.py` (126), `unit/test_orchestration_plan.py` (216), `unit/test_orchestration_prompt.py` (104), `unit/test_orchestration_intent.py` (95) | Спецификация сервера и запись кэша, отказы `validate_plan`, граф FSM прогона, промпт и разбор плана, блок в системном промпте, приоритет «в базу» над пайплайном |
| Логика серверов флота | `unit/test_search_web.py` (183), `unit/test_search_local.py` (135), `unit/test_fetch_url.py` (109), `unit/test_keywords.py` (80), `unit/test_dates.py` (116), `unit/test_aggregate.py` (136), `unit/test_storage_files.py` (251), `unit/test_storage_db.py` (123) | Поиск в ленте и Википедии, блоки файла, HTML → текст и обрезка, частоты и стоп-слова, даты и `skipped`, метрики агрегации, файлы вывода и строки `storage.db` — всё офлайн, на стенде `tests/stub_api.py` и временных каталогах |
| Флот и оркестрация | `integration/test_search_server_stdio.py` (134), `integration/test_data_server_stdio.py` (158), `integration/test_storage_server_stdio.py` (172) | Настоящие серверы по stdio через `sys.executable`: каталог инструментов, успешные вызовы и ошибки данными |
| Реестр, хранилище, прогон | `integration/test_mcp_fleet_registry.py` (282), `integration/test_orchestration_store.py` (165), `integration/test_orchestration_run.py` (293), `integration/test_orchestration_service.py` (219), `integration/test_orchestration_restart.py` (74), `integration/test_orchestration_agent.py` (156) | Подключение и маршрутизация флота, CRUD журнала и статистика, прогон `DEMO_PLAN` (данные доезжают между серверами, падение шага останавливает прогон, guard-стоп), синхронный и фоновый запуск, перезапуск на той же БД, шаг оркестрации в `Agent.generate` |
| API | `e2e/test_orchestration_api.py` (243), `e2e/test_mcp_servers_api.py` (154) | Шесть эндпоинтов оркестрации (включая 400 и 404) и три эндпоинта флота (включая запись `tools_cache` в файл) на временной БД и фейковом флоте |

Фикстура `no_real_fleet` в `tests/conftest.py` — **autouse**: `lifespan` приложения
на старте зовёт `connect_all()`, а тесты не должны поднимать настоящие процессы.
Фикстура подменяет путь к файлу серверов пустым временным файлом и подставляет
реестр на фейковой фабрике; тесты, которым флот нужен, передают серверам реестра
свой файл конфигурации явно.

## Что унаследовано от дня 19 и что переделано

Содержательные изменения (все проверены сравнением с `day19/`; в скобках — было
строк в дне 19 → стало):

| Модуль | Строк | Что изменилось |
|---|---|---|
| `backend/agents/agent.py` | 2094 (2009) | Шаг оркестрации: `apply_orchestration`, свойство `orchestration_service`, поле `record["orchestration"]`; распознанная оркестрация выключает на эту реплику пайплайн и MCP-шаг |
| `backend/services/mcp_registry.py` | 391 (138) | Флот серверов и маршрутизация: `connect_all`, `refresh_tools`, `servers`, `tools_of`, `list_all_tools`, `find_tool_by_name`, `ensure_connected`, `call_tool_on`, `fleet_status`; `call_tool` активного соединения переименован в `call_active_tool` |
| `backend/services/mcp_tool_runner.py` | 171 (144) | Параметр `server_name`: с именем — инструменты и вызов сервера флота, без имени — активное соединение (поведение дня 17 сохраняется) |
| `backend/domain/mcp_tools.py` | 153 (114) | `MCPFleetTool` (инструмент + имя сервера) и `make_tool_infos` — разбор кэша инструментов из файла |
| `backend/services/mcp_client.py` | 398 (392) | Параметр `cwd` — рабочий каталог дочернего процесса stdio: команды флота запускаются от корня дня |
| `backend/services/mcp_transport.py` | 74 (65) | `transport_context(target, cwd)` |
| `backend/services/mcp_errors.py` | 104 (95) | `MCPUnknownServerError`, `MCPUnknownToolError` и метка действия `fleet` |
| `backend/api/lifespan.py` | 60 (49) | Четвёртый пункт старта — `get_mcp_registry().connect_all()`; остановка закрывает флот вместе с активным соединением |
| `backend/api/main.py` | 66 (79) | Подключены роутеры `mcp_servers` и `orchestration`; докстринг сокращён, чтобы файл остался в лимите 80 строк |
| `backend/api/mcp.py` | 154 (180) | Роут `GET /mcp/servers` снят (каталог известных целей) — переехал в `api/mcp_servers.py`; у активного соединения осталось пять эндпоинтов |
| `backend/api/agents.py` | 314 (301) | В инвентаре `GET /` — группы `orchestration` (6) и `mcp_servers` (3) и имя приложения дня 20; всего 85 записей |
| `backend/api/__init__.py` | 56 (40) | Реэкспорт новых роутеров и контракт ошибок: номер запуска оркестрации, неизвестный сервер флота, отказ плана |
| `backend/core/config.py` | 291 (246) | Раздел «Оркестрация MCP-серверов (день 20)»: `MCP_SERVERS_FILE`, `MCP_FLEET_CWD`, границы плана, журнала и флота; убраны `MCP_FETCH_TARGET` и `MCP_FILESYSTEM_TARGET` (их использовал только удалённый каталог) |
| `backend/core/dependencies.py` | 115 (102) | `get_orchestration_service` |
| `backend/domain/__init__.py` | 395 (399) | Импорт `mcp_server_spec` и модулей `orchestration_*` вместо имён удалённого каталога серверов |
| `backend/storage/__init__.py` | 155 (141) | `OrchestrationStore`, `OrchestrationRunNotFoundError` |
| `backend/storage/database.py` | 59 (58) | Реэкспорт ORM-таблиц оркестрации |
| `backend/models/__init__.py` | 77 (70) | `OrchestrationRun`, `OrchestrationStep` |
| `backend/schemas/__init__.py` | 269 (239) | Реэкспорт схем оркестрации и флота |
| `backend/schemas/agent.py` | 352 (346) | Поле `orchestration` ответа генерации |
| `backend/schemas/mcp.py` | 165 (193) | `MCPServerSchema` и `MCPServersResponse` каталога дня 16 убраны: новые схемы флота — в `schemas/mcp_servers.py` |
| `backend/services/__init__.py` | 165 (145) | Реэкспорт `OrchestrationPlanner`, `Orchestrator`, `OrchestrationService`, `get_orchestration_service` и ошибок флота |
| `backend/agents/agent_manager.py` | 105 (99) | Параметр `orchestration_service` в конструкторе — служба передаётся агентам |
| `backend/agents/manager_agents.py` | 255 (253) | Передача `orchestration_service` в обоих местах создания `Agent` |
| `frontend/chat_section.py` | 346 (334) | Восьмой раздел «🌐 Оркестрация» и строка `orchestration_note` в сводке хода |
| `frontend/mcp_call.py` | 210 (202) | `render_servers` читает состав флота и подключает активное соединение к выбранному серверу |
| `frontend/mcp_api.py` | 55 (51) | Докстринг `api_mcp_servers`: ответ — состав флота |
| `tests/conftest.py` | 228 (164) | Autouse-фикстура `no_real_fleet` и фикстуры `orchestration_store`, `fleet_registry`, `orchestrator`, `orchestration_service` |
| `tests/mcp_fakes.py` | 248 (247) | Параметр `cwd` в `FakeMCPClient` и `make_mcp_factory` (реестр передаёт рабочий каталог) |
| `tests/pipeline_fakes.py` | 160 (158) | `cwd` в фабрике фейкового реестра |
| `tests/stub_api.py` | 183 (124) | Страницы ленты (`/posts?_limit=`, `/users?_limit=`) и ручка `/html` — на ней проверяется очистка страницы в `fetch_url` |
| `tests/e2e/test_mcp_call_api.py` | 162 (184) | Убрана сверка `connected_target` со старым каталогом целей |
| `mcp_server/config.py` | 137 | Имя сервера `day20-tools` и версия `1.3.0`, адрес бэкенда из `DAY20_BACKEND_URL` |
| `pyproject.toml` | — | Имя `day20` и описание дня; зависимости не менялись |

Остальные файлы, унаследованные от дня 19, отличаются только идентичностью дня
(`day19` → `day20`, `DAY19_BACKEND_URL` → `DAY20_BACKEND_URL`, упоминания `day20/.env`
и `day20/output/`) — это `app.py` (67), `backend/__init__.py` (49),
`backend/domain/task_fsm.py` (366), `task_intent.py` (89), `task_prompt.py` (190),
`task_proposal.py` (91), `task_state_machine.py` (381),
`backend/domain/mcp_intent.py` (145), `backend/services/invariant_checker.py` (296),
`frontend/api_client.py` (388), `frontend/mcp_section.py` (276),
`frontend/pipeline_api.py` (52), `frontend/pipeline_section.py` (330),
`mcp_server/backend_api.py` (106), `file_writer.py` (109), `llm_client.py` (86),
корневой `conftest.py` (6), `tests/support.py` (280),
`tests/integration/test_mcp_server_stdio.py` (266) и девять скриптов
`scripts/video_scenario*.py` (69–386).

Удалены (clean cutover, вызовов не осталось; число строк — по дню 19, где файл
ещё существовал):

| Файл | Строк в дне 19 | Почему |
|---|---|---|
| `backend/domain/mcp_servers.py` | 108 | Каталог известных серверов (`KNOWN_SERVERS`, `MCPServerOption`, `server_records`) заменён флотом из `mcp_servers.json`; читал его только роут `/mcp/servers` дня 16 и его тест |
| `tests/unit/test_mcp_servers.py` | 81 | Тест удалённого каталога; заменён `tests/unit/test_mcp_server_spec.py` |
| `.env`, `output/rag*.md`, `output/run-success.md` | — | Не копировались из дня 19: секрет в новый день не переносится, а артефакты прежнего прогона не должны выглядеть доказательствами дня 20 |

## Что импортируется из `shared/`

Пакет `shared/` (корень репозитория) подключается в `backend/__init__.py`, который
добавляет корень репозитория в `sys.path`.

| Модуль дня | Импорт | Зачем |
|---|---|---|
| `backend/__init__.py` | — (добавляет корень репозитория в `sys.path`) | Чтобы `from shared…` работал из любого модуля дня |
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов (в том числе блоков пайплайна и оркестрации), логи |
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API и чтение `DEEPSEEK_API_KEY` |
| `backend/core/mcp_server_config.py` | `shared.logging_utils.get_logger` | Лог записи кэша инструментов флота в файл |
| `backend/storage/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/models/*.py` (11 модулей, включая `orchestration.py`) | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/storage/task_store.py`, `invariant_store.py` | `shared.logging_utils.get_logger` | Отладочные логи записанного перехода и инварианта |
| `backend/services/invariant_checker.py` | `shared.deepseek_client.make_client`, `get_logger` | Клиент LLM-слоя проверки и лог причины отказа от проверки |
| `backend/services/mcp_client.py`, `mcp_registry.py`, `mcp_tool_runner.py` | `shared.logging_utils.get_logger` | Логи подключений, смены соединения, флота и отклонённых вызовов |
| `backend/services/scheduler.py`, `schedule_service.py`, `apscheduler_bridge.py` | `shared.logging_utils.get_logger` | Логи сверки планировщика с БД и сбоя тика |
| `backend/services/pipeline.py`, `pipeline_service.py` | `shared.logging_utils.get_logger` | Логи остановки прогона пайплайна и сбоя фонового потока |
| `backend/services/orchestrator.py`, `orchestration_service.py` | `shared.logging_utils.get_logger` | Логи шагов флота, отказа маршрутизации и сбоя фонового прогона |
| `backend/services/orchestration_planner.py` | `shared.deepseek_client.make_client`, `get_logger` | Клиент DeepSeek для плана по каталогу флота и лог перехода на эвристику |
| `backend/api/lifespan.py` | `shared.logging_utils.get_logger` | Логгер старта и остановки бэкенда |
| `mcp_server/config.py` | `shared.deepseek_utils.read_key_from_env_file` | Ключ DeepSeek для инструмента `summarize` (сервер — отдельный процесс, `.env` читает сам) |
| `mcp_server/llm_client.py` | `shared.deepseek_client.make_client`, `get_logger` | Клиент DeepSeek внутри `summarize` (создаётся лениво) и лог перехода к агрегации |
| `mcp_servers/data_server/config.py` | `shared.deepseek_utils.read_key_from_env_file` | Ключ DeepSeek для инструмента `summarize` нового сервера данных |
| `mcp_servers/data_server/summarize.py` | `shared.logging_utils.get_logger` | Лог сводки |
| `mcp_servers/data_server/llm_client.py` | `shared.deepseek_client.make_client`, `get_logger` | Клиент DeepSeek и лог отказа от вызова |
| `mcp_servers/storage_server/server.py` | `shared.logging_utils.get_logger` | Лог сервера сохранения |
| `mcp_servers/search_server/config.py` | — (только корень репозитория в `sys.path`) | Сервер поиска общего кода не импортирует: bootstrap путей нужен ради единообразия пакетов флота |

Модули `frontend/` обращаются к бэкенду только по HTTP (`frontend/api_client.py`),
поэтому `shared/` напрямую не импортируют; тесты дня — тоже. Серверы флота
(`mcp_servers/*`) кода дня не импортируют вовсе: их зависимости — stdlib,
`httpx`, SDK `mcp` и `shared/` (только `data_server`, которому нужен ключ и
клиент DeepSeek для `summarize`).

## Известные расхождения

| Файл | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agents/agent.py` | 2094 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи и переходы, инварианты, шаги MCP, планировщика, пайплайна и оркестрации, генерация) не разложен на миксины — расхождение унаследовано с дней 11–18, день 20 добавил 85 строк шагом оркестрации. Единственное превышение лимита среди кода дня |
| `frontend/common.py` | 400 | 400 | Ровно на границе, поэтому день 20 его не правил: подписи и ключи состояния раздела «🌐 Оркестрация» живут в `frontend/orchestration_section.py` и `frontend/orchestration_steps.py` |
| `backend/domain/__init__.py` | 395 | 400 | Модули планировщика, пайплайна и оркестрации импортируются как модули (`from . import …`), а не реэкспортируются именами: иначе список имён слоя вышел бы за лимит |
| `backend/services/mcp_client.py` | 398 | 400 | Клиент запускает свой daemon-поток с циклом событий и долгоживущую задачу сессии (контексты MCP SDK обязаны входить и выходить в одной задаче anyio); цикл событий и адаптеры SDK уже вынесены в `mcp_loop.py` и `mcp_transport.py` |
| `.agents/skills/**` | 416–449 | — | Вендорные скиллы сторонних пакетов (`uvx library-skills --copy`): в трёх шаблонах Streamlit-приложений больше 400 строк. Это код библиотеки, а не дня |
| MCP-подключение не в БД | — | — | Ни у активного соединения, ни у флота нет таблиц: соединения живут в памяти процесса (`MCPRegistry`), поэтому после рестарта бэкенда `/mcp/status` отвечает `disconnected`, а `connect_all()` в `lifespan` поднимает флот заново |
| Дубли имён инструментов | — | — | `find_tool_by_name` возвращает первый сервер в порядке `mcp_servers.json` и пишет предупреждение в лог: падать на дубле значило бы ломать сценарий добавления сервера правкой файла |
| `save_to_db` пишет в `storage.db` | — | — | Отдельный файл базы, а не `agents.db`: в `agents.db` пишет ровно один процесс (бэкенд дня), а `storage_server` — отдельный процесс, и общий файл сделал бы двух писателей |
| Флот поднимается в `lifespan` | — | — | `connect_all()` стартует три процесса на каждый запуск приложения; сбой сервера не мешает старту (его запись показывает `error`), но тесты не должны поднимать процессы — за это отвечает autouse-фикстура `no_real_fleet` |
| Оркестрация — линейная цепочка | — | — | Ветвления, параллельные шаги, повторы упавшего шага и возобновление с места остановки не сделаны: условие шага (`guard`) может только остановить прогон целиком. Рамки дня — в отчёте `docs/reports/orchestration_demo.md` (§12) |

## Проверка лимита строк

Из папки `day20` (исключены `.venv` и вендорный `.agents/`):

```powershell
uv run python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and '.agents' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод: `[('backend\\agents\\agent.py', 2094)]` — единственное превышение
в коде дня. `app.py` (67 ≤ 100) и `backend/api/main.py` (66 ≤ 80) в лимитах;
`frontend/common.py` (400) и `backend/domain/__init__.py` (395) — на границе, но в
пределах.

Каталог `.agents/` исключён не для красоты: в этой копии скиллы библиотек
скопированы (а не слинкованы), и три шаблона Streamlit внутри скилла
`developing-with-streamlit` длиннее 400 строк (416–449). Это код библиотеки, а не
дня.
