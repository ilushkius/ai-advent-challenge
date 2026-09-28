# Структура дня 21

Карта модулей дня 21: что где лежит и за что отвечает. Правила структуры — в
[`../AGENTS.md`](../AGENTS.md) и [`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

День 21 — копия дня 20 плюс **индексация документов**: сборка набора документов из
источников репозитория в `documents/`, две стратегии чанкинга (фиксированное окно по
токенам и структурная — по секциям документа), эмбеддинги `sentence-transformers` в
**FAISS**, метаданные чанков в **SQLite** (`document_chunks`), журнал прогонов
(`index_runs`), роутер `/indexing` (9 эндпоинтов), раздел «📦 Индексация» с кнопкой
«🚀 Запустить демо-индексацию» и отчёт `docs/reports/indexing_demo.md` по пяти
сценариям.

**Почему документы — производные данные.** Папку `documents/` готовить не нужно: её
собирает `DocumentLoader` из таблицы источников (`DOCUMENT_SOURCES` домена), поэтому
демо-сценарий работает на свежем клоне одной кнопкой. В Git `documents/` и `index/` не
попадают (`.gitignore`: `documents/`, `day21/index/`, `*.index`, `*.db`).

**Почему блоки документа — общая структура обеих стратегий.** Чанкер работает не с
сырым текстом, а с блоками (`backend/domain/chunking.py`: секции markdown, секции кода
через `ast`, абзацы plain text). Блоки делят текст **без пропусков и перекрытий**,
поэтому `content` чанка — это срез исходного текста, `start_char`/`end_char` точны, а
метрика покрытия честная. Расхождения с буквой плана сделаны ровно ради этого
свойства: секция markdown идёт «до следующего заголовка **любого** уровня» (а не «до
заголовка с уровнем не выше»), секция кода — «до начала следующей», а не до
`node.end_lineno`, а абзац plain text забирает пустую строку-разделитель. Вариант
«секция первого уровня вместе с подсекциями» перекрывал бы подсекции и клал один текст
в индекс дважды; вариант с `node.end_lineno` оставлял бы между секциями дыры
(модульные переменные и `if __name__` не попали бы ни в один блок).

**Почему id вектора равен id строки.** `IndexService` кладёт векторы в
`faiss.IndexIDMap2` под id метаданных (`document_chunks.id`), поэтому второго
источника истины «какой вектор какому чанку соответствует» не нужно: FAISS отдаёт id,
а `ChunkStore.rows_by_ids` возвращает метаданные **в том же порядке**. Повторный
прогон **дописывает** индекс и таблицу (поэтому `chunk_id` в таблице не уникален) —
чистка только явная (`POST /indexing/clear`, кнопка «🧹 Очистить обе стратегии»):
неявная переиндексация означала бы пересчёт всех эмбеддингов на каждый прогон.

**Почему журнал прогонов в SQLite.** Прогон идёт фоновым потоком (модель считает
эмбеддинги десятками секунд), а прогресс опрашивает другой процесс — Streamlit. Память
процесса такого не переживает, поэтому строка `index_runs` создаётся ДО старта потока,
обновляется по этапам и получает терминальный статус **вместе с метриками**
(`finish_run`): иначе читатель увидел бы «завершено» без метрик.

**Почему модель эмбеддингов ленивая.** `sentence-transformers` тянет torch, весит
сотни мегабайт и на первой загрузке скачивает веса: импорт на уровне модуля задержал бы
старт бэкенда и сделал бы офлайн-тесты невозможными. Поэтому
`sentence_transformers` импортируется внутри `EmbeddingService._load`, а прогревает
модель демон-поток в `lifespan`. `max_seq_length = 512` выставляется явно: базовые 128
токенов молча обрезали бы чанк фиксированной стратегии, и сравнение стратегий потеряло
бы смысл.

**Две стратегии — за одним интерфейсом.** `FixedSizeChunker` и `StructuralChunker`
реализуют один контракт (`chunk(document) -> list[Chunk]`), считают токены общим
счётчиком (`shared.token_counter.count_tokens`, tiktoken) и держат точные границы.
Метрики сравнения (`backend/domain/index_metrics.py`) — чистая арифметика отдельно от
прогона: размеры и разброс, покрытие (объединение интервалов, поэтому перекрытие окон
не удваивает покрытие), сохранение структуры, precision@k и recall@k по пяти тестовым
запросам с ground truth (`DEMO_QUERIES` домена).

**Почему логика прогона разделена на три модуля.** `indexing_service.py` отвечает на
вопрос «когда запускать и что отдавать API», `index_runner.py` — «как идут этапы по FSM
с журналом прогресса», `index_comparison.py` — «как из чисел собрать метрики». В одном
файле это было 487 строк — за лимитом 400; граница проведена по вопросам, а не по
объёму.

Унаследовано полностью: оркестрация флота из трёх MCP-серверов вместе с
`mcp_servers.json` (день 20), планировщик фоновых задач (день 18), свой MCP-сервер дня
(`mcp_server/`, девять инструментов) и вызов инструмента агентом, декларативный
пайплайн (день 19), контролируемые переходы (день 15), инварианты (день 14), состояние
задачи как конечный автомат (день 13), профиль (день 12), три слоя памяти (день 11).
Активное MCP-подключение раздела «🔌 MCP» по-прежнему таблиц в БД не имеет: оно живёт
в памяти процесса. Имя собственного MCP-сервера дня (`day20-tools`) оставлено как
есть: это идентификатор протокола, а не путь дня.

## Унаследовано из дня 20 — оркестрация флота MCP-серверов

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
day21/
├── app.py                    # точка входа Streamlit (74 строки, лимит 100): set_page_config + вызовы секций
├── documents/                # СОБРАННЫЕ документы (производные данные, в Git не попадают): 25 файлов + manifest.json
├── index/                    # ИНДЕКСЫ FAISS: fixed.index, structural.index; index/models/ — кэш весов модели (не в Git)
├── mcp_servers.json          # КОНФИГУРАЦИЯ ФЛОТА: три сервера (команда, аргументы, описание) + кэш каталогов tools_cache
├── mcp_servers/              # ТРИ независимых MCP-сервера дня 20 — каждый отдельным процессом по stdio
│   ├── __init__.py           # докстринг пакета: состав флота, запуск `uv run python mcp_servers/<server>/server.py`, транспорт
│   ├── search_server/        # поиск данных: search_web, search_local, fetch_url (тела — web.py, local.py, fetch.py)
│   ├── data_server/          # обработка данных: summarize, extract_keywords, filter_by_date, aggregate
│   └── storage_server/       # сохранение и выдача: save_to_file (output/), save_to_db (storage.db), list_saved, load_from_file
├── mcp_server/               # СОБСТВЕННЫЙ MCP-сервер дня — унаследован от дней 17–19 (11 модулей, девять инструментов, stdio)
├── frontend/                 # Streamlit UI по секциям (28 модулей, включая __init__.py)
│   ├── indexing_api.py       # HTTP-запросы индексации (/indexing/...) поверх api_client
│   ├── indexing_section.py   # раздел «📦 Индексация»: кнопка демо, прогресс этапов, история, очистка
│   ├── indexing_compare.py   # сравнение стратегий: таблица метрик, гистограммы, примеры чанков, тестовые запросы
│   ├── indexing_search.py    # форма ручного поиска по построенному индексу
│   ├── orchestration_api.py  # HTTP-запросы оркестрации и флота поверх api_client
│   ├── orchestration_section.py # раздел «🌐 Оркестрация»: флот, кнопка демо, прогресс, история, статистика
│   └── orchestration_steps.py   # один шаг прогона: раскрывающийся отчёт, mermaid-диаграмма флоу, таблица шагов
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным (девять слоёв, в каждом __init__.py)
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # 15 модулей: 12 роутеров по доменам (в том числе indexing.py), сборка app (main.py), lifespan.py
│   ├── core/                 # config (каталоги документов и индексов, API_TITLE), mcp_server_config, dependencies
│   ├── domain/               # чистые правила и данные: 48 модулей, в том числе chunking, document_sources, index_metrics,
│   │                         # index_scenarios, indexing_fsm, indexing_prompt и шесть модулей orchestration_*
│   ├── services/             # прикладные сервисы: 28 модулей, в том числе chunker, embedding_service, index_service,
│   │                         # document_loader, indexing_service, index_runner, index_comparison, mcp_registry, orchestrator
│   ├── storage/              # доступ к БД: 15 модулей, в том числе chunk_store.py (чанки) и index_run_store.py (журнал прогонов)
│   ├── agents/               # Agent (в generate — шаг поиска по индексу), MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы: 12 модулей, в том числе indexing.py (document_chunks, index_runs)
│   ├── schemas/              # Pydantic-схемы API: 13 модулей, в том числе indexing.py, orchestration.py, mcp_servers.py
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 2349 тестов (unit/ — 1625, integration/ — 519, e2e/ — 205)
│   ├── conftest.py           # общие фикстуры (+ autouse no_real_fleet, offline_planner и isolated_indexing)
│   ├── indexing_fakes.py     # фейки индексации: эмбеддер на хешах слов и три тестовых документа
│   ├── orchestration_fakes.py # фейки флота: каталоги трёх серверов, результаты 11 инструментов, make_fleet_registry
│   ├── mcp_fakes.py          # MCP-фейки (день 17): FakeMCPClient с журналом вызовов, make_mcp_factory (+ cwd)
│   ├── pipeline_fakes.py     # фейки пайплайна дня 19
│   ├── mcp_echo_server.py    # унаследованный тестовый MCP-сервер (echo, add) — на нём сценарий 5 (четвёртый сервер)
│   ├── stub_api.py           # локальный стенд jsonplaceholder (+ ручка /html для fetch_url)
│   └── support.py, scheduler_fakes.py, search_sources_fakes.py, backend_stub.py  # унаследованные помощники тестов
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов (38 модулей, не пакет)
│   ├── prepare_documents.py  # сборка набора документов: --force (пересобрать), --list (показать манифест)
│   ├── indexing_scenarios.py # пять сценариев индексации (демо, одиночная стратегия, поиск, качество, рестарт) + стенд
│   ├── indexing_demo.py      # точка входа дня 21: пять сценариев, сборка данных и отчёта, --stub-embedder
│   ├── indexing_report.py    # сборка docs/reports/indexing_demo.md из данных прогона
│   ├── indexing_ui_shot.py   # снимок раздела «📦 Индексация» в браузере (Playwright), fallback без картинки
│   ├── orchestration_demo.py # точка входа дня 20: временный mcp_servers.json, пять сценариев, отчёт, --tests
│   ├── orchestration_scenarios.py # сценарии 1–3 (демо-кнопка, реплика агента, ошибка на шаге)
│   ├── orchestration_fleet.py    # сценарии 4–5 (перезапуск приложения, четвёртый сервер правкой файла)
│   ├── orchestration_report.py   # сборка docs/reports/orchestration_demo.md из данных прогона
│   └── orchestration_report_flow.py  # подписи рёбер и текстовая схема потока для отчёта
├── invariants_demo.md        # отчёт дня 14 (унаследован; лежит в корне дня — путь задан заданием дня 14)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── pyproject.toml, uv.lock   # зависимости (uv): sentence-transformers, faiss-cpu, numpy, mcp, sqlalchemy…; версии — в локе
├── .agents/skills/           # скиллы библиотек (uvx library-skills --copy); не код дня
├── .python-version           # 3.14
├── .env.example              # шаблон DEEPSEEK_API_KEY, DAY21_BACKEND_URL и DAY21_EMBEDDING_MODEL
├── output/                   # каталог результатов save_to_file (пример прогона: demo-scenario.md)
├── storage.db                # SQLite сервера хранения (в git не попадает: *.db в корневом .gitignore)
└── agents.db                 # SQLite бэкенда дня (тоже под *.db)
```

Отчёты прогонов лежат в `docs/reports/`: `indexing_demo.md` — отчёт дня 21 (его
создаёт `uv run python scripts/indexing_demo.py --report
docs/reports/indexing_demo.md`; там обязательны таблица сравнения стратегий,
распределение размеров чанков, примеры чанков, результаты пяти запросов и выводы
пяти сценариев), `orchestration_demo.md` — отчёт дня 20 (его создаёт `uv run python scripts/orchestration_demo.py --report docs/reports/orchestration_demo.md`;
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

## Индексация документов: `backend/domain/`, `services/`, `storage/`, `api/`

| Модуль | Назначение |
|---|---|
| `backend/domain/document_sources.py` | Источники документов **данными**: `DocumentSource` (путь, вид, предел символов), `DOCUMENT_SOURCES` (25 записей), `Document` (собранный документ), `source_slug` (`day20/README.md` → `day20-readme.md`), `detect_language` (по доле кириллицы), `detect_title` (заголовок markdown или докстринг модуля, иначе имя файла), `truncate` (обрезка с маркером `<!-- документ усечён -->`) |
| `backend/domain/chunking.py` | Структура документа: `BlockKind` (`markdown`/`code`/`plain`), `ChunkStrategy` (`fixed`/`structural`), `iter_blocks` — блоки делят текст **без пропусков и перекрытий** (секции markdown по заголовкам, секции кода через `ast` с запасной эвристикой по строкам при `SyntaxError`, абзацы plain text), `line_offsets` |
| `backend/domain/index_metrics.py` | Метрики сравнения: `size_stats` (avg/median/σ/min/max), `histogram` (бакеты 0-128 … 513+), `coverage_ratio` (объединение интервалов — перекрытие не удваивает покрытие), `structure_ratio`, `precision_recall` (precision@k и recall@k по запросам), `ascii_histogram`, `comparison_rows` |
| `backend/domain/index_scenarios.py` | Пять тестовых запросов демонстрации с ожидаемыми источниками (ground truth — имена файлов) и их проверка: `DEMO_QUERIES`, `TestQuery`, `validate_queries`, `queries_as_dicts` |
| `backend/domain/indexing_fsm.py` | Стейт-машина прогона: `IndexingState` (`loading`…`failed` — ровно статусы `index_runs.status`), `IndexingEvent`, граф `ALLOWED_TRANSITIONS`, `IndexingFSM`; у `indexing` два выхода — `DONE` (одиночная стратегия) и `INDEXED` (демо: дальше поиск и сравнение) |
| `backend/domain/indexing_prompt.py` | Блок «## Контекст из индекса документов» для системного промпта: источник, секция, оценка близости и выдержка до 300 символов (`render_index_block`) |
| `backend/services/chunker.py` | `FixedSizeChunker` (окно по токенам с перекрытием целыми блоками) и `StructuralChunker` (чанк — секция; мелкие секции сливаются, длинные режутся с сохранением заголовка), `Chunk`, `chunk_document`, `get_chunker` |
| `backend/services/embedding_service.py` | `EmbeddingService`: ленивая загрузка sentence-transformers, `max_seq_length = 512`, батчи, нормализованные векторы, `encode`/`encode_one`/`warmup`/`reset`, `EmbeddingError` с понятным текстом |
| `backend/services/index_service.py` | `IndexService`: `IndexIDMap2(IndexFlatIP)`, id вектора = `document_chunks.id`, `index_chunks` (эмбеддинги → строки → векторы → файл), `search`, `save_index`/`save_all`/`load_index`/`load_all`, `clear_index`, `get_stats`/`stats`, `sample_chunks`, `IndexNotBuiltError` |
| `backend/services/document_loader.py` | `DocumentLoader`: `collect` (сборка `documents/` + манифест), `load_documents` (метаданные из манифеста, незнакомый файл — эвристиками), `ensure_documents` (пусто → собрать), `manifest` |
| `backend/services/index_runner.py` | `IndexRunner`: этапы прогона по FSM с журналом прогресса, терминальный статус при любом исходе (доменный отказ — `failed` в БД и исключение наружу) |
| `backend/services/index_comparison.py` | Сборка метрик прогона: документы, запросы, по стратегии — `stats`/`coverage`/`structure`/`search`/`timing`, таблица сравнения; `summary` для лога |
| `backend/services/indexing_service.py` | `IndexingService`: запуск прогонов (фоном или синхронно), `status`/`runs`/`run`, `stats`/`chunks`/`search`/`clear`/`queries`/`index_size`, `IndexingRejected` с кодами причин (`bad_strategy`, `bad_query`, `no_documents`, `run_not_found`, `index_empty`) |
| `backend/storage/chunk_store.py` | `ChunkStore`: `add_chunks` (возвращает id — под ними ложатся векторы), `rows_by_ids` (порядок FAISS), `chunks`, `count`, `counts_by_source`, `token_counts`, `with_section`, `chunks_by_sources` (знаменатель recall), `delete_strategy` |
| `backend/storage/index_run_store.py` | `IndexRunStore`: `create_run` (строка создаётся ДО потока), `update_progress` (этап и счётчики), `finish_run` (терминальный статус **вместе с метриками**), `run`/`latest`/`list_runs` |
| `backend/storage/index_rows.py` | ORM-строки индексации → словари API/UI (`chunk_dict`, `index_run_dict`) |
| `backend/models/indexing.py` | ORM: `document_chunks` (метаданные и текст чанка; `embedding_id` = `id`; `chunk_id` НЕ уникален — повторный прогон дописывает индекс) и `index_runs` (стратегия, этап, счётчики, длительности, метрики, ошибка) |
| `backend/schemas/indexing.py` | Pydantic-схемы: запуск, отчёт, статистика обеих стратегий, попадания поиска, примеры чанков, очистка и поле `indexing` ответа генерации |
| `backend/api/indexing.py` | Роутер `/indexing`, девять эндпоинтов; коды: 400 (стратегия, пустой запрос, нет документов), 404 (запуск), 409 (поиск по пустому индексу), 422 (параметры) |
| `frontend/indexing_api.py` | HTTP-запросы индексации поверх общего `request_json` |
| `frontend/indexing_section.py` | Раздел «📦 Индексация»: кнопка демо-прогона, прогресс этапов фрагментом раз в секунду, подписи этапов и `stage_progress`, история запусков, `indexing_note` для сводки хода |
| `frontend/indexing_compare.py` | Сравнение стратегий: таблица метрик, две гистограммы размеров чанков, примеры чанков каждой стратегии, результаты пяти тестовых запросов |
| `frontend/indexing_search.py` | Форма ручного поиска по построенному индексу: запрос, стратегия, топ-k, таблица попаданий и текст чанка |
| `scripts/prepare_documents.py` | CLI сборки набора документов: `--force`, `--list`; печатает документы, символы, страницы и разбивку по видам |
| `scripts/indexing_scenarios.py` | Пять сценариев проверки + стенд `DemoStand` (БД дня и рабочие `documents/` и `index/`; перед прогоном индексы чистятся), `HashEmbedder` для офлайн-прогона |
| `scripts/indexing_demo.py` | Точка входа прогона: сценарии → данные → отчёт, флаги `--stub-embedder`, `--report`, `--screenshot`, `--skip-scenarios` |
| `scripts/indexing_report.py` | Сборка `docs/reports/indexing_demo.md` из данных прогона (таблица сравнения, ASCII-гистограммы, примеры чанков, запросы, сценарии, артефакты) |
| `scripts/indexing_ui_shot.py` | Снимок раздела «📦 Индексация» в браузере: поднимает бэкенд и Streamlit, жмёт кнопку демо, ждёт таблицу сравнения; при любой неудаче печатает причину и не мешает отчёту |

`documents/` и `index/` — производные данные: их собирает и строит код, в Git они
не попадают. `scripts/indexing_scenarios.py` работает на **той же БД, что
приложение** (`day21/agents.db`), и на **рабочих** файлах `index/`: векторы лежат в
общих файлах, поэтому метаданные обязаны быть в общей таблице — иначе запущенный
бэкенд прочитает чужие векторы и не найдёт к ним строк (поиск вернёт пустой список
при непустом индексе). Чтобы это расхождение не было молчаливым, `GET /indexing/stats`
отдаёт `index_vectors` рядом с `chunks`. Перед прогоном стенд чистит индексы: так
число чанков не зависит от прошлых прогонов (рабочую БД он при этом не удаляет — в
ней диалоги, задачи и профили пользователя).

## Слои `backend/`

| Слой | Файлов | Что там |
|---|---|---|
| `api/` | 15 | HTTP: 12 роутеров по доменам (включая `indexing.py` — индексация, `orchestration.py` — запуски, `mcp_servers.py` — флот), `lifespan.py` (старт и остановка фоновых служб, чтение индексов, прогрев модели) и `main.py` (сборка `app`) |
| `core/` | 4 | `config.py` (настройки дня, в том числе файл флота, каталоги документов и индексов, модель эмбеддингов и границы поиска), `mcp_server_config.py` (чтение `mcp_servers.json` и запись `tools_cache`), `dependencies.py` (доступ роутов к менеджеру, реестру, планировщику, службам пайплайна, оркестрации и **индексации**) |
| `domain/` | 48 | Чистые правила и данные без БД и сети: FSM задачи/сжатия/MCP/планировщика/пайплайна/оркестрации/**индексации**, графы переходов, расписания, агрегация, распознавание реплик, маппинг аргументов, стратегии, профиль, инварианты, тексты промптов, план шагов и **источники документов, блоки, метрики сравнения, тестовые запросы**. Знают только stdlib, `core.config` и соседей по слою |
| `services/` | 28 | Прикладные сервисы: компрессор, состояние задачи, инварианты, `mcp_*` (клиент, транспорт, ошибки, реестр с флотом, состояние сервера, раннер инструмента), планировщик и его службы, пайплайн, оркестратор, **чанкер, эмбеддинги, векторный индекс, загрузчик документов, прогон индексации, сборка метрик и служба индексации** |
| `storage/` | 15 | Доступ к БД: `database.py` (движок, сессии, реэкспорт ORM), хранилища задач, инвариантов, памяти, планировщика, пайплайна, оркестрации и **чанков с журналом индексации** (+ модули «строка → словарь») |
| `agents/` | 12 | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов; менеджер передаёт агентам реестр MCP, службы пайплайна, оркестрации и **индексации (шаг поиска по документам в `generate`)** |
| `models/` | 12 | ORM-таблицы SQLAlchemy по доменам, включая **`indexing.py`** (`document_chunks`, `index_runs`) и `orchestration.py` |
| `schemas/` | 13 | Pydantic-схемы API по доменам, включая **`indexing.py`**, `orchestration.py` и `mcp_servers.py` |
| `utils/` | 1 | Своего кода нет (`__init__.py`): общий клиент DeepSeek, база, токены и логи — в repo-level `shared/` |

Девять слоёв обязательны и все содержат `__init__.py` с реэкспортом публичных
имён слоя — это единственное место, где виден публичный контракт. `api/__init__.py`
намеренно **не** импортирует `main`: `core.dependencies.get_manager` тянет
`api.main` лениво, иначе возник бы цикл `api → core → api`. По той же причине
`storage/task_store.py` берёт `MemoryManager` внутри свойства, а
`core/dependencies.py` — `AgentManager` только под `TYPE_CHECKING`.

`domain/__init__.py` (ровно 400 строк) импортирует модули планировщика, пайплайна,
оркестрации и индексации **как модули** (`from . import chunking, indexing_fsm,
orchestration_fsm, pipeline_spec, …`), а не реэкспортирует их имена: иначе список
имён слоя вышел бы за лимит 400 строк. Код дня и так берёт имена из своего модуля
(`from ..domain.index_scenarios import DEMO_QUERIES`), поэтому точек входа
`backend.domain.indexing_fsm` и соседей достаточно. В день 21 ради лимита
исторические абзацы докстринга (описание задач, инвариантов и планировщика)
сжаты.

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

Набор дня 21 — 2349 тестов в подпапках `unit/` (1625), `integration/` (519) и
`e2e/` (205); классификация по фикстурам: чистые модули / временная БД и агент /
`TestClient`. Фикстуры дня 21 добавляют к унаследованным: `documents_dir` (три
документа: markdown с заголовками, plain text и Python с декоратором),
`documents`, `document_loader` (загрузчик на тестовой папке),
`fake_embedder` (эмбеддер на хешах слов), `chunk_store`, `index_run_store`,
`index_service` (фейковый эмбеддер, временная БД и временный каталог индексов) и
`indexing_service` (те же три документа).

Autouse-фикстура `isolated_indexing` делает тесты герметичными: `lifespan`
приложения при старте читает и пишет рабочие `index/*.index`, а модель
эмбеддингов весит сотни мегабайт и требует сети. Поэтому `main.get_index_service`
подменяется службой на `tmp_path` (файлов там нет, писать нечего), а
`EmbeddingService._load` — функцией-ошибкой: случайная загрузка настоящей модели
= падение теста. Модульные `_service` трёх служб обнуляются перед каждым тестом,
иначе singleton протекал бы между тестами вместе с фабрикой сессий прошлого теста.
Файл `tests/integration/test_embedding_service.py` возвращает себе настоящий
`_load` (он проверяет именно загрузку, подменив сам пакет
`sentence_transformers`): там `sys.modules` заменяется фейком с `FakeModel`.

Вторая autouse-фикстура, `offline_planner`, запрещает тестам звать настоящую модель
планировщика оркестрации: `OrchestrationPlanner` читает ключ DeepSeek из `.env` дня,
и унаследованные тесты дня 20 («без плана сработала эвристика») падали, когда ответ
приходил от модели. Тесты, которым план модели нужен, подставляют планировщик явно.
Побочный эффект — набор перестал ждать сетевых таймаутов (полный прогон: минуты
вместо десятков минут).

Файлы дня 21:

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки | `tests/indexing_fakes.py` (141) | Эмбеддер на хешах слов (одинаковый текст → одинаковый вектор, общие слова → близкие) и три тестовых документа — вход чанкинга и поиска без модели и сети |
| Блоки и чанкинг | `unit/test_chunking_blocks.py` (181), `unit/test_chunker_fixed.py` (122), `unit/test_chunker_structural.py` (131) | Секции markdown и кода (`ast` и запасная эвристика при `SyntaxError`), абзацы plain text; главное свойство — блоки делят текст без пропусков и перекрытий, `content` чанка равен срезу исходника; бюджет окна, перекрытие окон, слияние мелких секций, разрез длинных с сохранением заголовка |
| Домен индексации | `unit/test_indexing_fsm.py` (118), `unit/test_index_metrics.py` (197), `unit/test_index_scenarios.py` (132) | Таблица 15 переходов и негативные пары → `UnknownIndexingEvent`; границы бакетов, покрытие как объединение интервалов, precision/recall (в том числе запрос без релевантных чанков), ASCII-гистограмма и строки сравнения; валидность пяти запросов и метаданные источников |
| Загрузка и эмбеддинги | `integration/test_document_loader.py` (148), `integration/test_embedding_service.py` (174) | Сборка документов и манифеста, маркер усечения, пропуск пропавшего источника, эвристики для незнакомого файла, битый манифест; ленивая загрузка модели, нормализация и батчи, `max_seq_length`, один экземпляр модели, `EmbeddingError`, `warmup` без исключений |
| Индекс и прогон | `integration/test_index_service.py` (197), `integration/test_indexing_service.py` (264), `integration/test_indexing_restart.py` (61) | `embedding_id == id`, порядок попаданий, `IndexNotBuiltError`, круговорот файла индекса, очистка, статистика; этапы прогона по FSM и счётчики, метрики и качество по запросам, одиночная стратегия без сравнения, пять кодов отказа, сбой эмбеддера в строке запуска, фоновый прогон; перезапуск без переиндексации |
| API | `e2e/test_indexing_api.py` (298) | Девять эндпоинтов `/indexing`: синхронный и фоновый прогон, прогресс, статистика, поиск (409 на пустом индексе, 400 на пустом запросе, 422 на `top_k` вне границ), примеры чанков, история, 404, очистка, поле `indexing` ответа генерации и правило «один ход — один автоматизм» |

Унаследованные наборы (дни 11–20: память и стратегии, профиль, задача и переходы,
инварианты, MCP, планировщик, пайплайн, флот и оркестрация) остаются на месте; их
раскладка по файлам описана в [`day20/STRUCTURE.md`](../day20/STRUCTURE.md).

Фикстура `no_real_fleet` в `tests/conftest.py` — **autouse**: `lifespan` приложения
на старте зовёт `connect_all()`, а тесты не должны поднимать настоящие процессы.
Фикстура подменяет путь к файлу серверов пустым временным файлом и подставляет
реестр на фейковой фабрике; тесты, которым флот нужен, передают серверам реестра
свой файл конфигурации явно.

## Что изменилось относительно дня 20

Новые модули дня 21 перечислены выше (раздел «Индексация документов»). Здесь —
только правки унаследованного кода (проверены сравнением с `day20/`; в скобках
было → стало):

| Модуль | Строк | Что изменилось |
|---|---|---|
| `backend/agents/agent.py` | 2192 (2094) | Шаг поиска по индексу: `_empty_indexing_report`, свойство `indexing_service`, `apply_index_context`, поле `record["indexing"]`; реплика, занятая пайплайном или оркестрацией, поиск не делает |
| `backend/agents/agent_manager.py` | 110 (105) | Параметр `indexing_service` — служба передаётся агентам |
| `backend/agents/manager_agents.py` | 257 (255) | Передача `indexing_service` в обоих местах создания `Agent` |
| `backend/core/config.py` | 342 (291) | Раздел «Индексация документов и поиск (день 21)»: каталоги `documents/` и `index/`, модель эмбеддингов, батч, параметры чанкинга, границы топ-k, длины полей и периоды опроса; `API_TITLE`/`API_DESCRIPTION`/`API_VERSION` дня 21 |
| `backend/core/dependencies.py` | 152 (115) | `get_indexing_service`, `get_index_service`, `get_embedding_service` |
| `backend/api/main.py` | 70 (66) | Подключены роутер `indexing` и три точки подмены служб индексации |
| `backend/api/__init__.py` | 63 (56) | Реэкспорт роутера `indexing` и контракт ошибок дня 21 (409 на пустой индекс, 400 на стратегию/запрос/документы) |
| `backend/api/lifespan.py` | 75 (60) | Пятый и шестой шаги старта — `get_index_service().load_all()` и прогрев модели эмбеддингов демон-потоком; остановка пишет индексы (`save_all`) |
| `backend/api/agents.py` | 327 (314) | В инвентаре `GET /` — группа `indexing` (9) и имя приложения дня 21; всего 94 записи |
| `backend/domain/__init__.py` | 400 (395) | Импорт модулей индексации как модулей; исторические абзацы докстринга сжаты, чтобы файл остался в лимите |
| `backend/services/__init__.py` | 217 (165) | Реэкспорт чанкера, эмбеддингов, индекса, загрузчика документов, службы индексации и её кодов отказа |
| `backend/storage/__init__.py` | 176 (155) | `ChunkStore`, `IndexRunStore`, `IndexRunNotFoundError`, `chunk_dict`, `index_run_dict` |
| `backend/storage/database.py` | 68 (59) | Реэкспорт ORM-таблиц индексации |
| `backend/models/__init__.py` | 83 (77) | `DocumentChunk`, `IndexRun` |
| `backend/schemas/__init__.py` | 304 (269) | Реэкспорт схем индексации |
| `backend/schemas/agent.py` | 358 (352) | Поле `indexing` ответа генерации |
| `frontend/chat_section.py` | 358 (346) | Девятый раздел «📦 Индексация» и строка `indexing_note` в сводке хода |
| `tests/conftest.py` | 327 (228) | Autouse-фикстура `isolated_indexing` (модель не грузится, индексы — в `tmp_path`) и фикстуры `documents_dir`, `documents`, `document_loader`, `fake_embedder`, `chunk_store`, `index_run_store`, `index_service`, `indexing_service` |
| `app.py` | 74 (67) | Заголовок страницы и описание разделов дня 21 |
| `pyproject.toml` | — | Имя `day21` и описание дня; добавлены `sentence-transformers`, `faiss-cpu`, `numpy` |
| `.env.example` | — | `DAY21_BACKEND_URL` вместо `DAY20_BACKEND_URL`, добавлена `DAY21_EMBEDDING_MODEL` |
| `pytest.ini` | — | Комментарий про день 21 |

Остальные файлы отличаются только идентичностью дня (`day20` → `day21`,
`DAY20_BACKEND_URL` → `DAY21_BACKEND_URL`, упоминания `day21/.env` и
`day21/output/`), включая скрипты `video_scenario*.py` (в них заменена переменная
окружения адреса бэкенда).

Имя собственного MCP-сервера дня (`SERVER_NAME = "day20-tools"`) НЕ менялось: это
идентификатор протокола (`tools/list` и `/mcp/status`), а не путь дня, и его
переименование потребовало бы правки серверов флота и их тестов без пользы для
дня 21. Свойства прогона, отличающие день 21 от дня 20 (кроме индексации как
таковой), перечислены в отчёте `docs/reports/indexing_demo.md`.

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
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов (в том числе блоков пайплайна, оркестрации и фрагментов индекса), логи |
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API и чтение `DEEPSEEK_API_KEY` |
| `backend/core/mcp_server_config.py` | `shared.logging_utils.get_logger` | Лог записи кэша инструментов флота в файл |
| `backend/storage/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/models/*.py` (12 модулей, включая `indexing.py`) | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/services/chunker.py` | `shared.token_counter.count_tokens` | Размер окна и размер чанка считаются tiktoken, а не оценкой «символы / 4»: «средний размер» в отчёте — измеренное число |
| `backend/services/embedding_service.py`, `index_service.py`, `document_loader.py`, `indexing_service.py`, `index_runner.py`, `index_comparison.py` | `shared.logging_utils.get_logger` | Логи загрузки модели, сборки документов, индексации (чей-то размер, время), смены этапа и сбоя фонового потока |
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
| `backend/agents/agent.py` | 2192 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи и переходы, инварианты, шаги MCP, планировщика, пайплайна, оркестрации и поиска по индексу, генерация) не разложен на миксины — расхождение унаследовано с дней 11–18, день 21 добавил 98 строк шагом индекса. Единственное превышение лимита среди кода дня |
| `frontend/common.py` | 400 | 400 | Ровно на границе, поэтому дни 20 и 21 его не правили: подписи разделов живут в `orchestration_section.py`, `orchestration_steps.py` и `indexing_*.py` |
| `backend/domain/__init__.py` | 400 | 400 | Модули планировщика, пайплайна, оркестрации и индексации импортируются как модули (`from . import …`), а не реэкспортируются именами: иначе список имён слоя вышел бы за лимит. День 21 сжал исторические абзацы докстринга, чтобы добавить шесть модулей и остаться ровно в лимите |
| `backend/services/mcp_client.py` | 398 | 400 | Клиент запускает свой daemon-поток с циклом событий и долгоживущую задачу сессии (контексты MCP SDK обязаны входить и выходить в одной задаче anyio); цикл событий и адаптеры SDK уже вынесены в `mcp_loop.py` и `mcp_transport.py` |
| `.agents/skills/**` | 416–449 | — | Вендорные скиллы сторонних пакетов (`uvx library-skills --copy`): в трёх шаблонах Streamlit-приложений больше 400 строк. Это код библиотеки, а не дня |
| `chunk_id` не уникален | — | — | Повторный прогон по тем же документам ДОПИСЫВАЕТ индекс и таблицу (числа растут — это видно в статистике и истории запусков). Уникальный `chunk_id` превратил бы кнопку демо-прогона в одноразовую: второй клик падал бы на ограничении вместо того, чтобы либо дописать, либо честно попросить очистку. Переиндексация с нуля — явная кнопка «🧹 Очистить обе стратегии» |
| Модель греется в демон-потоке | — | — | Блокирующий прогрев задержал бы старт бэкенда на десятки секунд, а на первой загрузке — на минуты (скачивание весов). Неудача прогрева не валит старт: она видна как `failed` первого прогона индексации с текстом причины |
| Индексы FAISS — файлы, а не таблицы | — | — | FAISS не имеет своей БД, поэтому векторы лежат в `index/*.index`, а метаданные — в SQLite. Согласованность поддерживается тем, что прогон пишет и то, и другое, а `clear` убирает и файл, и строки; расхождение видно в статистике (`index_vectors` против `chunks`) и лечится очисткой индекса |
| PDF-источников нет | — | — | Генерация PDF потребовала бы новой зависимости, а внешние статьи — сети и лицензий. Роль «статей» играют документы репозитория (README дней, `docs/architecture.md`, четыре исходника, `AGENTS.md` и корневой `README.md`) — это задание дня допускает прямо |
| `day21/documents/*.py` в игноре | — | — | Каталог `documents/` — производные данные (правило `documents/` в `.gitignore`), поэтому копии четырёх исходников внутри него тоже не в Git. Это ожидаемо: проверка «код не попал в игнор» даёт ровно эти четыре файла, а не потерю исходников дня |
| Флот поднимается в `lifespan` | — | — | `connect_all()` стартует три процесса на каждый запуск приложения; сбой сервера не мешает старту (его запись показывает `error`), но тесты не должны поднимать процессы — за это отвечает autouse-фикстура `no_real_fleet` |
| Оркестрация — линейная цепочка | — | — | Ветвления, параллельные шаги, повторы упавшего шага и возобновление с места остановки не сделаны: условие шага (`guard`) может только остановить прогон целиком. Рамки дня — в отчёте `docs/reports/orchestration_demo.md` (§12) |

## Проверка лимита строк

Из папки `day21` (исключены `.venv` и вендорный `.agents/`):

```powershell
uv run python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and '.agents' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод: `[('backend\\agents\\agent.py', 2192)]` — единственное превышение
в коде дня. `app.py` (74 ≤ 100) и `backend/api/main.py` (70 ≤ 80) в лимитах;
`frontend/common.py` (400) и `backend/domain/__init__.py` (400) — ровно на границе,
в пределах лимита.

Каталог `.agents/` исключён не для красоты: в этой копии скиллы библиотек
скопированы (а не слинкованы), и три шаблона Streamlit внутри скилла
`developing-with-streamlit` длиннее 400 строк (416–449). Это код библиотеки, а не
дня.
