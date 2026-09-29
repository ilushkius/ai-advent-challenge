# Структура дня 22

Карта модулей дня 22: что где лежит и за что отвечает. Правила структуры — в
[`../docs/project-rules.md`](../docs/project-rules.md) и
[`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

**Что такое день 22.** Проект дня 21 (копия дня 20 — агент DeepSeek с памятью, FSM,
инвариантами, профилем, MCP-клиентом и флотом серверов, планировщиком, пайплайном и
оркестрацией) плюс три новые подсистемы — две дня 21 и одна дня 22:

1. **Индексация документов** — сборка набора документов из источников репозитория в
   `documents/`, две стратегии чанкинга (фиксированное окно по токенам и структурная —
   по секциям документа), эмбеддинги `sentence-transformers` в **FAISS**, метаданные
   чанков в **SQLite** (`document_chunks`), журнал прогонов (`index_runs`), роутер
   `/indexing` (9 эндпоинтов), раздел «📦 Индексация» с кнопкой «🚀 Запустить
   демо-индексацию», отчёт `docs/reports/indexing_demo.md` по пяти сценариям.
2. **Оптимизация затрат на LLM** — строитель промптов с кэшируемым стабильным
   префиксом (`prompt_builder`), сжатие динамической части (`prompt_compressor`),
   единственная точка вызова модели с выбором модели и пределом ответа по типу задачи
   (`llm_client`), журнал расходов `llm_usage` и его агрегаты, домен стоимости
   (`llm_cost`), правило непиковых часов провайдера (`peak_hours`, `off_peak`, флаг
   `prefer_off_peak` планировщика), роутер `/llm` (5 эндпоинтов), вкладка «💰 Расходы»
   и отчёт `docs/reports/cost_optimization.md`.
3. **RAG-режим** — отдельный корпус документов `documents/rag_corpus/` (36 источников
   дня 21), загрузчик корпуса, гибридный отбор фрагментов (кандидаты FAISS плюс
   словесные веса запроса), бюджет контекста в промпте (`fit_context`), ответ по
   фрагментам с оценкой опоры на контекст, роутер `/rag` (3 эндпоинта), панель
   «🔍 RAG-запрос по корпусу» в разделе чата и раздел «🆚 RAG-сравнение», отчёт
   `docs/reports/rag_eval.md` по 10 контрольным вопросам.

Унаследовано из дня 20 — одной строкой: **остальное дерево, включая `mcp_server/`,
`mcp_servers/` с `mcp_servers.json`, память, профиль, состояние задачи, инварианты,
планировщик, пайплайн и оркестрацию, — копия дня 20 без изменений**; карта этих
модулей построчно — в [`day20/STRUCTURE.md`](../day20/STRUCTURE.md). Ниже описано
только то, что дни 21–22 добавили или изменили.

## Почему сделано так (решения дня 21)

**Документы — производные данные.** Папку `documents/` готовить не нужно: её собирает
`DocumentLoader` из таблицы источников (`DOCUMENT_SOURCES` домена), поэтому
демо-сценарий работает на свежем клоне одной кнопкой. В Git `documents/` и `index/` не
попадают (`.gitignore`: `documents/`, `day21/index/`, `*.index`, `*.db`).

**Блоки документа — общая структура обеих стратегий.** Чанкер работает не с сырым
текстом, а с блоками (`backend/domain/chunking.py`: секции markdown, секции кода через
`ast`, абзацы plain text). Блоки делят текст **без пропусков и перекрытий**, поэтому
`content` чанка — это срез исходного текста, `start_char`/`end_char` точны, а метрика
покрытия честная.

**id вектора равен id строки.** `IndexService` кладёт векторы в `faiss.IndexIDMap2` под
id метаданных (`document_chunks.id`), поэтому второго источника истины «какой вектор
какому чанку соответствует» не нужно: FAISS отдаёт id, а `ChunkStore.rows_by_ids`
возвращает метаданные **в том же порядке**. Повторный прогон **дописывает** индекс и
таблицу (поэтому `chunk_id` в таблице не уникален) — чистка только явная
(`POST /indexing/clear`, кнопка «🧹 Очистить обе стратегии»).

**Журнал прогонов в SQLite.** Прогон идёт фоновым потоком (модель считает эмбеддинги
десятками секунд), а прогресс опрашивает другой процесс — Streamlit. Память процесса
такого не переживает, поэтому строка `index_runs` создаётся ДО старта потока,
обновляется по этапам и получает терминальный статус **вместе с метриками**
(`finish_run`).

**Модель эмбеддингов ленивая.** `sentence-transformers` тянет torch и на первой загрузке
скачивает веса: импорт на уровне модуля задержал бы старт бэкенда и сделал бы
офлайн-тесты невозможными. Поэтому `sentence_transformers` импортируется внутри
`EmbeddingService._load`, а прогревает модель демон-поток в `lifespan`.
`max_seq_length = 512` выставляется явно: базовые 128 токенов молча обрезали бы чанк
фиксированной стратегии, и сравнение стратегий потеряло бы смысл.

**Две стратегии — за одним интерфейсом.** `FixedSizeChunker` и `StructuralChunker`
реализуют один контракт (`chunk(document) -> list[Chunk]`), считают токены общим
счётчиком (`shared.token_counter.count_tokens`, tiktoken) и держат точные границы.
Метрики сравнения (`backend/domain/index_metrics.py`) — чистая арифметика отдельно от
прогона: размеры и разброс, покрытие (объединение интервалов), сохранение структуры,
precision@k и recall@k по пяти тестовым запросам с ground truth (`DEMO_QUERIES`).

**Промпт собран зонами, префикс кэшируется.** Кэш контекста DeepSeek работает по самому
длинному общему префиксу, поэтому `PromptBuilder` собирает промпт в два слоя: стабильный
префикс (профиль → системный промпт → инварианты → каталог MCP-инструментов → примеры →
общие инструкции) и динамику (память, конспект, факты, состояние задачи, блоки
результатов инструментов). Префикс кэшируется по содержимому (`cache_hits`/
`cache_misses`), а `looks_dynamic` не даёт занести в него метку времени или hex-id —
иначе кэш промахивался бы на каждой реплике.

**Сжимается только динамика.** `PromptCompressor` убирает комментарии, лишние пробелы и
повторы, минифицирует JSON в ограждениях и целые JSON-блоки; к стабильному префиксу он
не применяется (иначе префикс переставал бы совпадать с кэшированным). Сжатие
идемпотентно и считает снятые токены через тот же tiktoken-счётчик.

**Непик — тариф провайдера, а не догадка.** Правило окон живёт чистым доменом
(`peak_hours.py`), планировщик лишь сдвигает первый запуск задачи с флагом
`prefer_off_peak` в ближайшее дешёвое окно (`off_peak.py`), а размер скидки берётся из
конфига: тариф может измениться, поэтому он не зашит в логику.

## Раскладка

```
day21/
├── app.py                    # точка входа Streamlit (79 строк, лимит 100): set_page_config + вызовы секций
├── AGENTS.md                 # правила дня и workflow нового дня (≤ 5 КБ): границы, документация, тесты, инструменты
├── WORKFLOW.md               # маршрут: сырое задание → ARCHITECT_PROMPT.md → исполнение в omp.sh → commit + tag
├── .omp/RULES.md             # sticky-правила (omp загружает их только из native-локаций: <ближайший непустой .omp/>)
├── .clineignore              # служебное и тяжёлое внутри дня (.venv, output, index, *.db) — вне контекста агента
├── documents/                # СОБРАННЫЕ документы (производные данные, в Git не попадают): 25 файлов + manifest.json;
│                             # rag_corpus/ — корпус RAG: 36 документов + manifest.json
├── index/                    # ИНДЕКСЫ FAISS: fixed.index, structural.index, rag_corpus_fixed.index,
│                             # rag_corpus_structural.index; index/models/ — кэш весов модели (не в Git)
├── mcp_servers.json          # КОНФИГУРАЦИЯ ФЛОТА (унаследована от дня 20): три сервера + кэш каталогов tools_cache
├── mcp_servers/              # три независимых MCP-сервера флота — унаследованы от дня 20 (по процессу на сервер, stdio)
├── mcp_server/               # собственный MCP-сервер дня — унаследован от дней 17–19 (11 модулей, девять инструментов, stdio)
├── frontend/                 # Streamlit UI по секциям (32 модуля, включая __init__.py)
│   ├── indexing_api.py       # HTTP-запросы индексации (/indexing/...) поверх api_client
│   ├── indexing_section.py   # раздел «📦 Индексация»: кнопка демо, прогресс этапов, история, очистка
│   ├── indexing_compare.py   # сравнение стратегий: таблица метрик, гистограммы, примеры чанков, тестовые запросы
│   ├── indexing_search.py    # форма ручного поиска по построенному индексу
│   ├── cost_api.py           # HTTP-запросы вкладки «💰 Расходы» (/llm/...) поверх api_client
│   ├── cost_section.py       # вкладка «💰 Расходы»: пик/непик, кэш и сжатие, расход по дням, журнал запросов
│   ├── rag_api.py            # HTTP-запросы RAG (/rag/...) поверх api_client
│   ├── rag_section.py        # панель «🔍 RAG-запрос по корпусу» и раздел «🆚 RAG-сравнение»
│   └── …                     # остальные секции унаследованы от дня 20
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным (девять слоёв, в каждом __init__.py)
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # 17 модулей: 14 роутеров по доменам (в том числе indexing.py, llm.py и rag.py), main.py, lifespan.py
│   ├── core/                 # 5 модулей: config (в том числе раздел оптимизации затрат), dependencies,
│   │                         # mcp_server_config и prompt_builder (строитель промптов с кэшем префикса)
│   ├── domain/               # 53 модуля: чистые правила и данные — индексация (chunking, document_sources,
│   │                         # index_metrics, index_scenarios, indexing_fsm, indexing_prompt), стоимость и непик
│   │                         # (llm_cost, peak_hours), RAG (rag_mode, rag_corpus_spec, rag_eval) и унаследованные домены
│   ├── services/             # 33 модуля: индексация (chunker, embedding_service, index_service, document_loader,
│   │                         # index_runner, index_comparison, indexing_service), затраты (llm_client,
│   │                         # prompt_compressor, off_peak) и RAG (rag_corpus_loader, rag_service) плюс унаследованные
│   ├── storage/              # 17 модулей: chunk_store и index_run_store (журнал прогонов индексации),
│   │                         # llm_usage_store и llm_usage_rows (журнал расходов) плюс унаследованные хранилища
│   ├── agents/               # Agent (в generate — шаг поиска по индексу, клиент LLM и строитель промптов),
│   │                         # MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы: 13 модулей, в том числе indexing.py (document_chunks, index_runs)
│   │                         # и llm_usage.py (журнал расходов)
│   ├── schemas/              # Pydantic-схемы API: 15 модулей, в том числе indexing.py, llm.py и rag.py
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 2560 тестов (unit/ — 1750, integration/ — 581, e2e/ — 229); по умолчанию 2482 (78 slow отложены)
│   ├── conftest.py           # общие фикстуры (session-scoped schema_template для схемы БД) + autouse no_real_network
│   ├── fixtures_fleet.py     # фикстуры флота MCP-серверов и оркестрации (вынесены из conftest: лимит 400 строк)
│   ├── fixtures_indexing.py  # фикстуры индексации документов (тоже вынесены из conftest)
│   ├── indexing_fakes.py     # фейки индексации: эмбеддер на хешах слов и три тестовых документа
│   ├── fixtures_rag.py       # фикстуры RAG: тестовый корпус, служба поиска, стаб-клиент и служба RAG
│   ├── rag_fakes.py          # фейки RAG: стаб-клиент DeepSeek и тексты тестового корпуса
│   └── …                     # унаследованные помощники тестов дня 20 (orchestration_fakes, mcp_fakes, stub_api, support…)
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов (43 модуля, не пакет)
│   ├── prepare_documents.py  # сборка набора документов: --force (пересобрать), --list (показать манифест)
│   ├── indexing_scenarios.py # пять сценариев индексации (демо, одиночная стратегия, поиск, качество, рестарт) + стенд
│   ├── indexing_demo.py      # точка входа дня: пять сценариев, сборка данных и отчёта, --stub-embedder
│   ├── indexing_report.py    # сборка docs/reports/indexing_demo.md из данных прогона
│   ├── indexing_ui_shot.py   # снимок раздела «📦 Индексация» в браузере (Playwright), fallback без картинки
│   ├── cost_optimization_measure.py # замер «до и после» на реальных текстах дня (токены tiktoken, деньги — формулы домена)
│   ├── cost_optimization_report.py  # рендер docs/reports/cost_optimization.md из данных замера + CLI
│   ├── prepare_rag_corpus.py # сборка корпуса RAG: --list, --force, --validate
│   ├── index_rag_corpus.py   # построение обоих индексов RAG (prepare_corpus через RAGService)
│   ├── run_rag_eval.py       # прогон 10 контрольных вопросов и запись docs/reports/rag_eval.md
│   └── …                     # унаследованные скрипты дней 18–20 (orchestration_*, pipeline_*, scheduler_*, video_*)
├── invariants_demo.md        # отчёт дня 14 (унаследован; лежит в корне дня — путь задан заданием дня 14)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── pyproject.toml, uv.lock   # зависимости (uv): sentence-transformers, faiss-cpu, numpy, mcp, sqlalchemy…; версии — в локе
├── .agents/skills/           # скиллы библиотек (uvx library-skills --copy); не код дня
├── .python-version           # 3.14
├── .env.example              # шаблон DEEPSEEK_API_KEY, DAY21_BACKEND_URL и DAY21_EMBEDDING_MODEL
├── output/                   # каталог результатов save_to_file (пример прогона: demo-scenario.md)
├── index_demo.db             # БД офлайн-прогона пяти сценариев (в Git не попадает: *.db)
├── storage.db                # SQLite сервера хранения (в git не попадает: *.db в корневом .gitignore)
└── agents.db                 # SQLite бэкенда дня (тоже под *.db)
```

Отчёты прогонов лежат в `docs/reports/`: `indexing_demo.md` и `cost_optimization.md` —
отчёты дня 21 (их создают `uv run python scripts/indexing_demo.py` и
`uv run python scripts/cost_optimization_report.py`), `context_optimization.md` —
отчёт об экономии контекста агента (замеры окружения, написан по фактам логов, а не
генерируется скриптом), `test_optimization.md` — отчёт об ускорении тестов
(параллелизм, общая схема БД, маркер `slow`; тоже написан по замерам), остальные
(`orchestration_demo.md`,
`pipeline_demo.md`, `scheduler_demo.md`, `mcp_tool_demo.md`, `mcp_demo.md`,
`task_state_demo.md`, `personalization_comparison.md`) унаследованы и читаются как
история.

Скрипты в `scripts/` не пакет: они находят корень дня
(`Path(__file__).resolve().parents[1]`) и добавляют его в `sys.path` сами, поэтому
`uv run python scripts/<script>.py` работает из любой рабочей директории. Пакеты
`mcp_server/` и каждый сервер в `mcp_servers/` — наоборот: у них `DAY_ROOT` и
`REPO_ROOT` вычисляются от файла `config.py` (`parents[1]` и `parents[2]`), потому
что запускаются отдельным процессом, где ни корень дня, ни корень репозитория в
`sys.path` не попадают.

## Новые модули дня 21 и дня 22

### Индексация документов: `backend/domain/`, `services/`, `storage/`, `api/`

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

### Оптимизация затрат на LLM: `core/`, `domain/`, `services/`, `storage/`, `api/`

| Модуль | Назначение |
|---|---|
| `backend/core/prompt_builder.py` | `PromptBuilder`: зоны промпта (стабильный префикс: профиль → системный промпт → инварианты → каталог MCP-инструментов → примеры → общие инструкции; затем динамика: память, конспект, факты, состояние задачи, блоки результатов инструментов) и хвост «Отвечай не длиннее N токенов»; кэш стабильных префиксов по содержимому (`cache_hits`/`cache_misses`), guard `looks_dynamic` от метки времени и hex-id в префиксе, `compress`, `stable_prefix`, `max_tokens_for`, `stats`, синглтон `get_prompt_builder` |
| `backend/services/prompt_compressor.py` | `PromptCompressor`: убирает комментарии, лишние пробелы и пустые строки, повторы строк и абзацев, минифицирует JSON в ограждениях и целые JSON-блоки; идемпотентен; `compress_blocks`, `stats`/`reset`; к **стабильному** префиксу не применяется |
| `backend/services/llm_client.py` | `LLMClient`: `select_model(task_type)` (модель по типу задачи из `LLM_TASK_MODELS`), `max_tokens_for(task_type, limit)` (предел длины ответа), `call(...)` (модель, предел, извлечение `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens` из ответа, запись строки в журнал), `record_usage`, `get_usage_stats(agent_id, period)`, `usage(...)`; `LLMCallResult` и `extract_cache_metrics` |
| `backend/domain/llm_cost.py` | Чистая арифметика денег: `prices_for`, `estimate_cost` (попадание в кэш — доля `LLM_CACHE_INPUT_RATIO` = 10% цены ввода), `cache_savings`, `compression_savings`, `off_peak_savings`, `savings_summary` (вклад каждого рычага отдельно, `core_saving` против `total_saving`) |
| `backend/domain/peak_hours.py` | Непиковые часы DeepSeek как чистые правила: `is_off_peak`, `next_off_peak`, `window_label`, `peak_status` (пик/непик, подпись окна, скидка, секунды до дешёвого окна), `savings_forecast` |
| `backend/services/off_peak.py` | `shift_to_off_peak(task, ...)`: перенос первого запуска задачи планировщика в непиковое окно (флаг `prefer_off_peak`); вынесено из `scheduler.py` ради лимита строк |
| `backend/models/llm_usage.py` | ORM-таблица журнала расходов `llm_usage`: агент, время, модель, токены ввода и вывода, `cache_hit_tokens`/`cache_miss_tokens`, оценка стоимости, тип задачи |
| `backend/storage/llm_usage_store.py` | `LLMUsageStore`: `add` (строка на каждый запрос), `recent` (последние запросы), `rows`, `stats` (запросы, токены, доля кэша, стоимость, разбивка по моделям, типам задач и дням), `agents`; период `day`/`week`/`month`/`all`, неизвестный — ошибка значения |
| `backend/storage/llm_usage_rows.py` | ORM-строки журнала расходов → словари API/UI (`llm_usage_dict`) |
| `backend/api/llm.py` | Роутер `/llm`, пять эндпоинтов: `GET /llm/usage` (журнал за период), `GET /llm/status` (пик/непик, статистика префикса и сжатия, таблицы «тип задачи → модель/предел»), `POST /llm/estimate` (прогноз по числам токенов), `GET /llm/models` (маршрутизация и тарифы), `GET /llm/peak` (правило окон и текущий статус); 400 на неизвестный период |
| `backend/schemas/llm.py` | Pydantic-схемы журнала и прогноза: `LLMUsageOut`, `LLMStatsOut`, `LLMUsageResponse`, `LLMPromptStatsOut`, `LLMCompressorStatsOut`, `LLMStatusOut`, `LLMEstimateIn`, `LLMSavingsOut`, `LLMModelsOut` |
| `frontend/cost_api.py` | HTTP-запросы вкладки «💰 Расходы» поверх общего `request_json` |
| `frontend/cost_section.py` | Вкладка «💰 Расходы»: пик/непик и прогноз, кэш контекста и статистика префиксов, сжатие, расход по дням, таблица последних запросов с `cache_hit`/`cache_miss`, таблица маршрутизации моделей |
| `scripts/cost_optimization_measure.py` | Замер «до и после»: сценарий диалога и тяжёлой задачи из реальных текстов дня (профиль, инварианты, каталог инструментов, память, состояние задачи, артефакты прогонов), токены — `shared.token_counter`, деньги — формулы `llm_cost`; без сети и ключа. Вынесен из скрипта отчёта ради лимита 400 строк |
| `scripts/cost_optimization_report.py` | Рендер `docs/reports/cost_optimization.md` из данных замера и CLI: «было → стало», вклад каждого рычага, маршрутизация моделей, измеренные факты, допущения и команды воспроизведения |

Числа отчёта об оптимизации — измерение на текстах дня, а не обещание: кэш контекста
берётся из стабильного префикса (`cache_hit_tokens`), сжатие считается реальным
tiktoken-счётчиком, скидка непика — тариф провайдера (в отчёте это указано в
допущениях), а предел длины ответа показан отдельной строкой как оценка **сверху** и в
итог не входит, потому что фактическая длина ответа от потолка не зависит.

### RAG-режим (день 22): `backend/domain/`, `services/`, `schemas/`, `api/`, `frontend/`, `scripts/`

| Модуль | Назначение |
|---|---|
| `backend/domain/rag_mode.py` | Промпт и лимиты режима: `RAG_SYSTEM_PROMPT` (ответ только по контексту), `RAG_DEFAULT_TOP_K = 5`/`RAG_MAX_TOP_K = 10`, `RAG_CONTEXT_MAX_TOKENS = 3000`, `RAG_CHUNK_MAX_CHARS = 2000`, `RAG_GROUNDING_MIN_SHARE = 0.5`/`RAG_GROUNDING_MIN_WORD = 5`, `RAG_LLM_ATTEMPTS = 3` c паузой `RAG_RETRY_SECONDS`/`RAG_RETRY_BACKOFF`, `RAG_CANDIDATE_POOL = 30`, `RAG_VECTOR_WEIGHT = 0.2`; `resolve_rag_strategy`, `render_context`/`render_rag_block` (заголовок `## Контекст из корпуса RAG`), `fit_context` (жадный бюджет), `content_words`/`query_weights`/`lexical_score` (вклад слова = 1 / число фрагментов с ним), `grounding_share`/`grounding_verdict` |
| `backend/domain/rag_corpus_spec.py` | Состав корпуса: `RAG_CORPUS_SOURCES` (36 источников дня 21), `RAG_CORPUS_SUBDIR = "rag_corpus"`, минимумы `RAG_CORPUS_MIN_PAGES = 25`/`RAG_CORPUS_MIN_CHUNKS = 50`, `corpus_pages`, `validate_sources` (пропавший файл или суффикс вне `DOCUMENT_SUFFIXES` — проблема) |
| `backend/domain/rag_eval.py` | Оценка: `RagQuestion` (вопрос, `key_facts`, `expected_sources`, `note`), `RAG_QUESTIONS` (10 записей), `question_as_dict`, `facts_found`, `fact_score` (доля найденных фактов), `verdict` («лучше»/«хуже»/«равно» по долям) |
| `backend/services/rag_corpus_loader.py` | `RagCorpusLoader(DocumentLoader)`: подкаталог `documents/rag_corpus/` и источники дня 21, `status` (документы, символы, страницы, готовность), `validate`; синглтон `get_rag_corpus_loader` |
| `backend/services/rag_service.py` | `RAGService`: `retrieve` (гибридный поиск: кандидаты FAISS + словесные веса), `_answer` (общий путь с контекстом и без), `rag_query`/`no_rag_query` (единый `RAG_SYSTEM_PROMPT`, различие — блок контекста), `compare`, `prepare_corpus` (пересборка корпуса и обоих индексов), `config`; повторы вызова `RAG_LLM_ATTEMPTS`, откат на ответ без RAG, `RAGRejected`/`RAGUpstreamError` с кодами причин, синглтон `get_rag_service` |
| `backend/schemas/rag.py` | Pydantic-схемы: `RagQueryIn`/`RagQueryOut`, `RagSourceOut`, `RagTokensOut`, `RagCompareIn`/`RagCompareOut`, `RagCorpusOut`, `RagIndexOut`, `RagConfigOut` |
| `backend/api/rag.py` | Роутер `/rag`, три эндпоинта; коды: 400 (пустой вопрос, неизвестная стратегия), 409 (корпус не проиндексирован), 502 (сбой вызова модели) |
| `frontend/rag_api.py` | HTTP-запросы RAG поверх общего `request_json` |
| `frontend/rag_section.py` | Панель «🔍 RAG-запрос по корпусу» (тумблер, `top_k` 1–10, стратегия, форма вопроса, метрики времени/токенов/фрагментов/кэша, expander «📚 Использованные источники», строка опоры) и раздел «🆚 RAG-сравнение» (столбцы «🚫 Без RAG» / «✅ С RAG») |
| `scripts/prepare_rag_corpus.py` | CLI сборки корпуса: `--list`, `--force`, `--validate`; печатает документы, символы, страницы против минимума и ожидаемое число чанков по стратегиям |
| `scripts/index_rag_corpus.py` | `RAGService.prepare_corpus()`: строит оба индекса RAG, печатает чанки, векторы и тайминги, проверяет минимум чанков на стратегию |
| `scripts/run_rag_eval.py` | Прогон 10 контрольных вопросов: ответ с RAG и без, `fact_score` и вердикт, запись `docs/reports/rag_eval.md`; флаги `--top-k`, `--strategy`, `--report`, `--limit` |

Корпус — производные данные: `documents/rag_corpus/` собирается из источников дня 21, а
индексы `index/rag_corpus_fixed.index`/`rag_corpus_structural.index` строятся заново
после клонирования. Новых таблиц RAG не вводит: обе стратегии живут строками в той же
таблице `document_chunks`, различаясь колонкой `strategy`.

### Экономия контекста агента: корень дня, `.gitignore` и настройки окружения

| Файл / место | Назначение |
|---|---|
| `AGENTS.md` | Правила дня и workflow нового дня: границы (`day1`–`day20` — архив), документация только о текущем состоянии, тесты не дублировать, обязательные инструменты, непиковые часы |
| `.omp/RULES.md` | Sticky-правила; путь именно `.omp/`, потому что omp загружает sticky только из native-локаций (`~/.omp/agent/RULES.md` и `<ближайший непустой .omp/>/RULES.md`) |
| `.clineignore` | Служебные и тяжёлые пути дня (`.venv`, `.agents`, `output/`, `index/`, `*.faiss`, `*.index`, `*.db`) вне контекста агента |
| корневой `.gitignore`, раздел 4 | `day1/`–`day20/` исключены из обхода `grep`/`glob`/`find`: omp уважает `.gitignore`, а `.clineignore` не читает — это единственный рабочий механизм исключения архива |
| корневой `.clineignore` | Тот же список дней для Cline и других инструментов (omp его не читает) |
| `docs/reports/context_optimization.md` | Замеры: зона видимости, перехват команд, токены сессий, пороги обоих слоёв сжатия, помеченные оценки и команды воспроизведения |

Настройки окружения (вне репозитория, `~/.omp/agent/config.yml`):
`bashInterceptor.enabled`, `compaction.idleEnabled`, `display.showTokenUsage`;
расширение `billion-context` и плагины `@mxalbert/context-mode`,
`@better-compact/pi`. Отслеживаемые файлы архива не потеряны (2 261 на месте) —
правила игнора влияют только на обход и на новые `git add`.

## Слои `backend/`

| Слой | Файлов | Что там |
|---|---|---|
| `api/` | 17 | HTTP: 14 роутеров по доменам (в том числе `indexing.py` — индексация, `llm.py` — расходы, `rag.py` — RAG, `orchestration.py` — запуски, `mcp_servers.py` — флот), `lifespan.py` (старт и остановка фоновых служб, чтение индексов, прогрев модели) и `main.py` (сборка `app`) |
| `core/` | 5 | `config.py` (настройки дня: файл флота, каталоги документов и индексов, модель эмбеддингов, границы поиска и **весь раздел оптимизации затрат** — маршрутизация моделей, пределы ответа, тарифы, доля цены кэша, окна непика и параметры журнала), `mcp_server_config.py` (чтение `mcp_servers.json` и запись `tools_cache`), `dependencies.py` (доступ роутов к менеджеру, реестру, планировщику, службам пайплайна, оркестрации, индексации, RAG и клиенту LLM), `prompt_builder.py` |
| `domain/` | 53 | Чистые правила и данные без БД и сети: FSM задачи/сжатия/MCP/планировщика/пайплайна/оркестрации/**индексации**, графы переходов, расписания, агрегация, распознавание реплик, маппинг аргументов, стратегии, профиль, инварианты, тексты промптов, план шагов, **источники документов, блоки, метрики сравнения, тестовые запросы**, **стоимость запросов и правило непиковых часов**, **RAG-промпт, источники корпуса и контрольные вопросы**. Знают только stdlib, `core.config` и соседей по слою |
| `services/` | 33 | Прикладные сервисы: компрессор контекста, состояние задачи, инварианты, `mcp_*` (клиент, транспорт, ошибки, реестр с флотом, состояние сервера, раннер инструмента), планировщик и его службы, пайплайн, оркестратор, **чанкер, эмбеддинги, векторный индекс, загрузчик документов, прогон индексации, сборка метрик, служба индексации**, **клиент LLM, сжатие промптов и перенос запуска в непик**, а также **загрузчик корпуса RAG и служба RAG** |
| `storage/` | 17 | Доступ к БД: `database.py` (движок, сессии, реэкспорт ORM), хранилища задач, инвариантов, памяти, планировщика, пайплайна, оркестрации, **чанков с журналом индексации** и **журнала расходов на LLM** (+ модули «строка → словарь») |
| `agents/` | 12 | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов; менеджер передаёт агентам реестр MCP, службы пайплайна, оркестрации, **индексации (шаг поиска по документам в `generate`)** и **клиент LLM со строителем промптов** |
| `models/` | 13 | ORM-таблицы SQLAlchemy по доменам, включая **`indexing.py`** (`document_chunks`, `index_runs`), **`llm_usage.py`**, `orchestration.py` |
| `schemas/` | 15 | Pydantic-схемы API по доменам, включая **`indexing.py`**, **`llm.py`**, **`rag.py`**, `orchestration.py` и `mcp_servers.py` |
| `utils/` | 1 | Своего кода нет (`__init__.py`): общий клиент DeepSeek, база, токены и логи — в repo-level `shared/` |

Девять слоёв обязательны и все содержат `__init__.py` с реэкспортом публичных
имён слоя — это единственное место, где виден публичный контракт. `api/__init__.py`
намеренно **не** импортирует `main`: `core.dependencies.get_manager` тянет
`api.main` лениво, иначе возник бы цикл `api → core → api`. По той же причине
`storage/task_store.py` берёт `MemoryManager` внутри свойства, а
`core/dependencies.py` — `AgentManager` только под `TYPE_CHECKING`.

`domain/__init__.py` (ровно 400 строк) импортирует модули планировщика, пайплайна,
оркестрации, индексации, стоимости, непика и RAG **как модули** (`from . import chunking,
indexing_fsm, llm_cost, peak_hours, rag_corpus_spec, rag_eval, rag_mode,
orchestration_fsm, …`), а не реэкспортирует их
имена: иначе список имён слоя вышел бы за лимит 400 строк. Код дня и так берёт имена из
своего модуля (`from ..domain.index_scenarios import DEMO_QUERIES`), поэтому точек входа
`backend.domain.indexing_fsm` и соседей достаточно. Ради лимита исторические абзацы
докстринга (описание задач, инвариантов и планировщика) сжаты.

## Тесты: `tests/`

Набор дня — **2560 тестов**: `unit/` — 1750 (61 файл), `integration/` — 581
(51 файл), `e2e/` — 229 (16 файлов). Классификация по фикстурам: чистые модули /
временная БД и агент / `TestClient`. Унаследованные наборы дней 11–20 (память и
стратегии, профиль, задача и переходы, инварианты, MCP, планировщик, пайплайн, флот и
оркестрация) остаются на месте; их раскладка по файлам — в
[`day20/STRUCTURE.md`](../day20/STRUCTURE.md).

**Режимы прогона и скорость.** Тесты идут параллельно (`pytest-xdist`, `-n auto`)
и делят одну схему БД на прогон: session-scoped `schema_template` строит её один
раз, а `session_factory` копирует файл (2,65 мс вместо 934 мс у `create_all`) —
изоляция сохранена (файл на тест), время полного прогона упало с 370 с до 68 с.
Тяжёлые тесты (78 штук: подпроцессы MCP-серверов по stdio и часть e2e) помечены
`slow` и по умолчанию пропускаются: `uv run pytest` идёт ~31 с и покрывает 2482
теста, полный набор — `uv run pytest -m ""` или `--run-slow`. Autouse-фикстура
`no_real_network` запрещает тестам TCP на нелокальные адреса (внешние API
подменены фейками). Замеры и разбор — в
[`docs/reports/test_optimization.md`](docs/reports/test_optimization.md).

Фикстуры индексации вынесены в `tests/fixtures_indexing.py` (импортируется обратно в
`conftest.py`, поэтому pytest видит их как объявленные там): `documents_dir` (три
документа: markdown с заголовками, plain text и Python с декоратором), `documents`,
`document_loader`, `fake_embedder`, `chunk_store`, `index_run_store`, `index_service`
(фейковый эмбеддер, временная БД и временный каталог индексов), `indexing_service`.
Autouse-фикстура
`isolated_indexing` делает тесты герметичными: `lifespan` при старте читает и пишет
рабочие `index/*.index`, а модель эмбеддингов весит сотни мегабайт и требует сети.
Поэтому `main.get_index_service` подменяется службой на `tmp_path`, а
`EmbeddingService._load` — функцией-ошибкой: случайная загрузка настоящей модели =
падение теста. Модульные `_service` трёх служб обнуляются перед каждым тестом, иначе
singleton протекал бы между тестами вместе с фабрикой сессий прошлого теста. Файл
`tests/integration/test_embedding_service.py` возвращает себе настоящий `_load` (он
проверяет именно загрузку, подменив сам пакет `sentence_transformers`).

Фикстуры RAG вынесены в `tests/fixtures_rag.py` тем же приёмом: `rag_corpus_dir` и
`rag_documents` (тестовый корпус из `tests/rag_fakes.py`), `rag_loader`,
`rag_index_service` (оба индекса на фейковом эмбеддере), `empty_index_service` (отказ
«индекс пуст»), `rag_usage_store`, `rag_stub`/`rag_client` (заглушка клиента DeepSeek) и
`rag_service` (служба RAG без пауз между попытками).

Вторая унаследованная autouse-фикстура, `offline_planner`, запрещает тестам звать
настоящую модель планировщика оркестрации; третья, `no_real_fleet`, — поднимать
процессы флота MCP.

### Индексация документов

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки | `tests/indexing_fakes.py` (141) | Эмбеддер на хешах слов (одинаковый текст → одинаковый вектор, общие слова → близкие) и три тестовых документа — вход чанкинга и поиска без модели и сети |
| Блоки и чанкинг | `unit/test_chunking_blocks.py` (181), `unit/test_chunker_fixed.py` (122), `unit/test_chunker_structural.py` (131) | Секции markdown и кода (`ast` и запасная эвристика при `SyntaxError`), абзацы plain text; главное свойство — блоки делят текст без пропусков и перекрытий, `content` чанка равен срезу исходника; бюджет окна, перекрытие окон, слияние мелких секций, разрез длинных с сохранением заголовка |
| Домен индексации | `unit/test_indexing_fsm.py` (118), `unit/test_index_metrics.py` (197), `unit/test_index_scenarios.py` (132) | Таблица 15 переходов и негативные пары → `UnknownIndexingEvent`; границы бакетов, покрытие как объединение интервалов, precision/recall (в том числе запрос без релевантных чанков), ASCII-гистограмма и строки сравнения; валидность пяти запросов и метаданные источников |
| Загрузка и эмбеддинги | `integration/test_document_loader.py` (148), `integration/test_embedding_service.py` (174) | Сборка документов и манифеста, маркер усечения, пропуск пропавшего источника, эвристики для незнакомого файла, битый манифест; ленивая загрузка модели, нормализация и батчи, `max_seq_length`, один экземпляр модели, `EmbeddingError`, `warmup` без исключений |
| Индекс и прогон | `integration/test_index_service.py` (201), `integration/test_indexing_service.py` (264), `integration/test_indexing_restart.py` (61) | `embedding_id == id`, порядок попаданий, `IndexNotBuiltError`, круговорот файла индекса, очистка, статистика; этапы прогона по FSM и счётчики, метрики и качество по запросам, одиночная стратегия без сравнения, пять кодов отказа, сбой эмбеддера в строке запуска, фоновый прогон; перезапуск без переиндексации |
| API | `e2e/test_indexing_api.py` (298) | Девять эндпоинтов `/indexing`: синхронный и фоновый прогон, прогресс, статистика, поиск (409 на пустом индексе, 400 на пустом запросе, 422 на `top_k` вне границ), примеры чанков, история, 404, очистка, поле `indexing` ответа генерации и правило «один ход — один автоматизм» |

### Оптимизация затрат на LLM

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Промпт и сжатие | `unit/test_prompt_builder.py` (314), `unit/test_prompt_compressor.py` (204) | Зоны промпта, попадание и промах кэша префикса по содержимому, guard `looks_dynamic` (метка времени и hex-id в префиксе — предупреждение, а не молчаливый промах), предел ответа по типу задачи; снятие комментариев, повторов и минификация JSON, идемпотентность, счётчики `stats`, неотрицательность снятых токенов |
| Домен стоимости и непик | `unit/test_llm_cost.py` (117), `unit/test_peak_hours.py` (161) | Цена запроса по тарифам, доля цены попадания в кэш, вклад каждого рычага, `core_saving` против `total_saving`; границы окон непика (будни 00–01, 04–06, 10–24 UTC, все выходные), `next_off_peak` строго позже момента, подпись окна и прогноз скидки |
| Хранилище журнала | `unit/test_llm_usage_rows.py` (127), `integration/test_llm_usage_store.py` (243) | Форма словаря строки журнала; запись строки запроса, свежие запросы первыми, периоды `day`/`week`/`month`/`all`, неизвестный период — ошибка, агрегаты (доля кэша, разбивка по моделям, типам и дням) |
| Клиент и агент | `integration/test_llm_client.py` (273), `integration/test_agent_cost.py` (162) | Выбор модели по типу задачи, предел ответа, извлечение `cache_hit`/`cache_miss` из ответа, запись в журнал, подмена фабрики клиента; ход агента через `LLMClient` и `PromptBuilder`, поле `llm` в ответе генерации |
| Планировщик и непик | `integration/test_scheduler_off_peak.py` (114) | Флаг `prefer_off_peak` переносит первый запуск в дешёвое окно, статус планировщика показывает `off_peak`/`next_off_peak`/`discount_percent`, задачи без флага не сдвигаются |
| API | `e2e/test_llm_api.py` (234) | Пять эндпоинтов `/llm`: журнал с раздельными `cache_hit`/`cache_miss`, состояние рычагов, прогноз, справка по моделям и правило окон; контракт ошибок (400 на неизвестный период, 422 на `off_peak_share` вне границ), поле `llm` ответа генерации |

### RAG-режим

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки и фикстуры | `tests/rag_fakes.py` (96), `tests/fixtures_rag.py` (84) | Стаб-клиент DeepSeek (пишет вызовы и отвечает текстом корпуса) и два markdown-документа с редкими литералами; фикстуры тестового корпуса, службы поиска и службы RAG без пауз |
| Сервис RAG | `unit/test_rag_service.py` (371) | Поиск `top_k` с метаданными пяти полей и порядком по score; промпт с блоком контекста и без него; бюджет `fit_context`; повторы вызова и откат на ответ без RAG; оценка опоры; `compare` зовёт оба режима; отвержение пустого вопроса и неизвестной стратегии; отказ на пустом индексе |
| Полный цикл (slow) | `integration/test_rag_flow.py` (102) | Сборка корпуса из 36 реальных источников и обоих индексов, минимумы страниц и чанков на стратегию; `rag_query` находит нужный фрагмент и отдаёт источники с пятью полями |
| API | `e2e/test_rag_api.py` (174) | Три эндпоинта `/rag`: запрос с RAG и без (пустые источники), конфигурация корпуса, коды 400 (пустой вопрос, неизвестная стратегия), 409 (пустой индекс), 502 (сбой клиента); `POST /rag/compare` |

## Что изменилось относительно дня 20

Новые модули дня 21 и дня 22 перечислены выше. Здесь — только правки **унаследованного** кода
(проверены сравнением с `day20/`; в скобках — было → стало строк):

| Модуль | Строк | Что изменилось |
|---|---|---|
| `backend/agents/agent.py` | 2284 (2094) | Два шага дня 21: поиск по индексу (`_empty_indexing_report`, свойство `indexing_service`, `apply_index_context`, поле `record["indexing"]`) и вызов модели через `LLMClient` + сборка промпта `PromptBuilder` со сжатием блоков (`_make_client` остаётся точкой подмены в тестах); реплика, занятая пайплайном или оркестрацией, поиск по индексу не делает |
| `backend/agents/agent_manager.py` | 110 (105) | Параметры `indexing_service` и `llm_client`/`prompt_builder` — службы передаются агентам |
| `backend/agents/manager_agents.py` | 257 (255) | Передача новых служб в обоих местах создания `Agent` |
| `backend/core/config.py` | 400 (291) | Два новых раздела: «Индексация документов и поиск» (каталоги, модель эмбеддингов, чанкинг, границы топ-k, длины полей) и «Оптимизация затрат на LLM» (`MODEL_PRICES`, `LLM_CACHE_INPUT_RATIO`, типы задач и маршрутизация `LLM_TASK_MODELS`, пределы ответа `LLM_TASK_MAX_TOKENS`, `OFF_PEAK_WEEKDAY_HOURS_UTC`/`PEAK_WEEKDAY_HOURS_UTC`/`OFF_PEAK_DISCOUNT_PERCENT`, параметры журнала `LLM_USAGE_*`); `API_TITLE`/`API_DESCRIPTION`/`API_VERSION` дня 22. Ровно на границе лимита 400 строк |
| `backend/core/dependencies.py` | 195 (115) | `get_indexing_service`, `get_index_service`, `get_embedding_service`, `get_prompt_builder`, `get_llm_client`, `get_rag_service` |
| `backend/api/main.py` | 75 (66) | Подключены роутеры `indexing`, `llm` и `rag` и точки подмены служб индексации, клиента LLM и службы RAG |
| `backend/api/__init__.py` | 69 (56) | Реэкспорт роутеров `indexing`, `llm` и `rag`; контракт ошибок дня (409 на пустой индекс, 400 на стратегию/запрос/документы, неизвестный период расходов и пустой вопрос RAG, 502 на сбой LLM-вызова RAG) |
| `backend/api/lifespan.py` | 75 (60) | Пятый и шестой шаги старта — `get_index_service().load_all()` и прогрев модели эмбеддингов демон-потоком; остановка пишет индексы (`save_all`) |
| `backend/api/agents.py` | 339 (314) | В инвентаре `GET /` — группы `indexing` (9), `llm` (5) и `rag` (3) и имя приложения дня 22; всего 102 записи, из них три `/rag/*` |
| `backend/api/scheduler.py` | 361 (355) | Описание флага `prefer_off_peak` и полей `off_peak`/`next_off_peak`/`discount_percent` в ответе `GET /scheduler/status` |
| `backend/domain/__init__.py` | 400 (395) | Импорт модулей индексации, стоимости, непика и RAG как модулей; исторические абзацы докстринга сжаты, чтобы файл остался в лимите |
| `backend/services/__init__.py` | 242 (165) | Реэкспорт чанкера, эмбеддингов, индекса, загрузчика документов, службы индексации и её кодов отказа, `LLMClient`/`get_llm_client`, `PromptCompressor`, `shift_to_off_peak`, `RagCorpusLoader`/`get_rag_corpus_loader`, `RAGService`/`get_rag_service` и ошибок RAG |
| `backend/services/compressor.py` | 330 (329) | Вызов LLM идёт с `task_type=config.LLM_TASK_SUMMARY` — работа сжатия контекста попадает под маршрутизацию моделей и журнал |
| `backend/services/invariant_checker.py` | 305 (296) | `task_type=config.LLM_TASK_CLASSIFY` при вызове модели и текст ошибки про `day21/.env` |
| `backend/services/orchestration_planner.py` | 98 (94) | Клиент вызова — `LLMClient` (`call` с `task_type`), фабрика вынесена в свойство |
| `backend/services/scheduler.py` | 398 (369) | Непиковые часы: `is_off_peak`, `get_next_off_peak_time`, `peak_status`; статус планировщика дополнен окном непика и скидкой |
| `backend/services/schedule_service.py` | 316 (305) | Задача с `prefer_off_peak` получает сдвиг первого запуска в дешёвое окно |
| `backend/storage/scheduler_rows.py` | 178 (177) | В словарь расписания добавлен `prefer_off_peak` (живёт внутри JSON `schedule_value`, отдельной колонки нет) |
| `backend/schemas/scheduler.py` | 330 (313) | Поля `off_peak`, `next_off_peak`, `discount_percent` в статусе и `prefer_off_peak` в задаче |
| `backend/storage/__init__.py` | 189 (155) | `ChunkStore`, `IndexRunStore`, `IndexRunNotFoundError`, `chunk_dict`, `index_run_dict`, `LLMUsageStore`, `llm_usage_dict` |
| `backend/storage/database.py` | 63 (59) | Реэкспорт ORM-таблиц индексации и журнала расходов |
| `backend/models/__init__.py` | 87 (77) | `DocumentChunk`, `IndexRun`, `LLMUsage` |
| `backend/schemas/__init__.py` | 350 (269) | Реэкспорт схем индексации, расходов и RAG |
| `backend/schemas/agent.py` | 362 (352) | Поля `indexing` и `llm` ответа генерации |
| `frontend/chat_section.py` | 381 (346) | Девятый раздел «📦 Индексация», десятый «💰 Расходы» и одиннадцатый «🆚 RAG-сравнение»; панель «🔍 RAG-запрос по корпусу» в конце ветки чата; строки `indexing_note` и сводка расходов в отчёте хода |
| `tests/conftest.py` | 272 (228) | Общие фикстуры (`schema_template`, `no_real_network`); фикстуры индексации и RAG вынесены в `fixtures_indexing.py` и `fixtures_rag.py` и импортируются обратно |
| `app.py` | 79 (67) | Заголовок страницы и описание разделов дня 22 |
| `README.md`, `docs/architecture.md`, `docs/usage.md`, `docs/api.md` | 562, 630, 268, 6257 | Документация дня переписана под текущее состояние: `README` и `architecture` описывают день, `usage.md` — инструкция дня, в `api.md` есть разделы индексации, расходов на LLM и RAG |
| `pyproject.toml` | 30 (24) | Имя `day21` и описание дня; добавлены `sentence-transformers`, `faiss-cpu`, `numpy` |
| `.env.example` | 20 (15) | `DAY21_BACKEND_URL` вместо `DAY20_BACKEND_URL`, добавлена `DAY21_EMBEDDING_MODEL` |
| `pytest.ini` | — | Комментарий про день 21 |

Остальные файлы отличаются только идентичностью дня (`day20` → `day21`,
`DAY20_BACKEND_URL` → `DAY21_BACKEND_URL`, упоминания `day21/.env` и `day21/output/`),
включая унаследованные скрипты `video_scenario*.py`, серверы `mcp_servers/**` и модули
`mcp_server/**`. Имя собственного MCP-сервера дня (`SERVER_NAME = "day20-tools"`) НЕ
менялось: это идентификатор протокола (`tools/list` и `/mcp/status`), а не путь дня.

## Что импортируется из `shared/`

Пакет `shared/` (корень репозитория) подключается в `backend/__init__.py`, который
добавляет корень репозитория в `sys.path`. Ниже — фактический список импортов
(проверено `grep` по дереву дня).

| Модуль дня | Импорт | Зачем |
|---|---|---|
| `backend/__init__.py` | — (добавляет корень репозитория в `sys.path`) | Чтобы `from shared…` работал из любого модуля дня |
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов (в том числе блоков пайплайна, оркестрации, фрагментов индекса и промпта), логи |
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API и чтение `DEEPSEEK_API_KEY` |
| `backend/core/prompt_builder.py` | `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Токены стабильного префикса и динамики, предупреждение о динамических данных в префиксе |
| `backend/services/prompt_compressor.py` | `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Снятые токены считаются тем же счётчиком, что и размер чанка |
| `backend/services/llm_client.py` | `shared.logging_utils.get_logger` | Лог запроса (модель, тип задачи, токены, попадание в кэш) |
| `backend/services/off_peak.py` | `shared.logging_utils.get_logger` | Лог переноса запуска в дешёвое окно |
| `backend/services/chunker.py` | `shared.token_counter.count_tokens` | Размер окна и размер чанка считаются tiktoken, а не оценкой «символы / 4»: «средний размер» в отчёте — измеренное число |
| `backend/domain/rag_mode.py` | `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Бюджет блока контекста считается тем же счётчиком, логи отбора фрагментов и оценки опоры |
| `backend/services/rag_corpus_loader.py` | `shared.logging_utils.get_logger` | Логи сборки корпуса RAG и проверки его состава |
| `backend/services/rag_service.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger`, `shared.token_counter.count_tokens` | Клиент DeepSeek (когда фабрику не подставило приложение), логи повторов и отката на ответ без RAG, счёт токенов контекста |
| `backend/services/embedding_service.py`, `index_service.py`, `document_loader.py`, `indexing_service.py`, `index_runner.py`, `index_comparison.py` | `shared.logging_utils.get_logger` | Логи загрузки модели, сборки документов, индексации (чей-то размер, время), смены этапа и сбоя фонового потока |
| `backend/services/compressor.py`, `orchestration_planner.py`, `invariant_checker.py`, `scheduler.py`, `schedule_service.py`, `apscheduler_bridge.py`, `mcp_client.py`, `mcp_registry.py`, `mcp_tool_runner.py`, `pipeline.py`, `pipeline_service.py`, `orchestrator.py`, `orchestration_service.py` | `shared.logging_utils.get_logger`; у `orchestration_planner` и `invariant_checker` ещё `shared.deepseek_client.make_client` | Логи служб дня и клиент LLM там, где вызов идёт мимо `LLMClient` |
| `backend/storage/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/models/*.py` (13 модулей, включая `indexing.py` и `llm_usage.py`) | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/storage/task_store.py`, `invariant_store.py` | `shared.logging_utils.get_logger` | Отладочные логи записанного перехода и инварианта |
| `backend/api/lifespan.py` | `shared.logging_utils.get_logger` | Логгер старта и остановки бэкенда |
| `backend/core/mcp_server_config.py` | `shared.logging_utils.get_logger` | Лог записи кэша инструментов флота в файл |
| `mcp_server/config.py`, `mcp_servers/**/config.py` | `shared.deepseek_utils.read_key_from_env_file` | Ключ DeepSeek для инструмента `summarize` (сервер — отдельный процесс, `.env` читает сам) |
| `mcp_server/llm_client.py`, `mcp_servers/data_server/llm_client.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger` | Клиент DeepSeek внутри `summarize` и лог отказа от вызова |
| `mcp_server/pipeline_tools.py`, `mcp_servers/data_server/summarize.py`, `mcp_servers/storage_server/server.py` | `shared.logging_utils.get_logger` | Логи инструментов серверов |
| `scripts/cost_optimization_measure.py` | `shared.token_counter.count_tokens` | Замер «до и после» тем же счётчиком, что и в проде |
| `tests/unit/test_prompt_builder.py`, `tests/unit/test_prompt_compressor.py` | `shared.token_counter.count_tokens` | Ожидаемые размеры в тестах считаются продовым счётчиком |

Модули `frontend/` обращаются к бэкенду только по HTTP (`frontend/api_client.py`),
поэтому `shared/` напрямую не импортируют. Серверы флота (`mcp_servers/*`) кода дня не
импортируют вовсе: их зависимости — stdlib, `httpx`, SDK `mcp` и `shared/` (только
`data_server`, которому нужен ключ и клиент DeepSeek для `summarize`).

## Известные расхождения

| Файл / место | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agents/agent.py` | 2284 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи и переходы, инварианты, шаги MCP, планировщика, пайплайна, оркестрации, поиска по индексу и работа с LLM) не разложен на миксины — расхождение унаследовано с дней 11–18 |
| `frontend/common.py` | 400 | 400 | Ровно на границе, поэтому дни 20 и 21 его не правили: подписи разделов живут в `orchestration_*.py`, `indexing_*.py` и `cost_section.py` |
| `backend/core/config.py` | 400 | 400 | Ровно на границе: копились разделы дней 11–21 (день 21 добавил индексацию и оптимизацию затрат). Следующий раздел потребует выноса части настроек в отдельный модуль конфигурации |
| `backend/domain/__init__.py` | 400 | 400 | Модули планировщика, пайплайна, оркестрации, индексации, стоимости, непика и RAG импортируются как модули (`from . import …`), а не реэкспортируются именами: иначе список имён слоя вышел бы за лимит |
| `GET /` — счётчик эндпоинтов | 102 записи / 84 пути | — | Инвентарь `endpoints` перечисляет эндпоинты по методу (102 записи, включая три `/rag/*`), тогда как OpenAPI группирует их по пути — уникальных путей 84. Расхождение не ошибка, а разная форма счёта |
| `backend/services/mcp_client.py` | 398 | 400 | Клиент запускает свой daemon-поток с циклом событий и долгоживущую задачу сессии (контексты MCP SDK обязаны входить и выходить в одной задаче anyio); цикл событий и адаптеры SDK вынесены в `mcp_loop.py` и `mcp_transport.py` |
| `.agents/skills/**` | 416–449 | — | Вендорные скиллы сторонних пакетов (`uvx library-skills --copy`): в трёх шаблонах Streamlit-приложений больше 400 строк. Это код библиотеки, а не дня |
| `chunk_id` не уникален | — | — | Повторный прогон по тем же документам ДОПИСЫВАЕТ индекс и таблицу (числа растут — это видно в статистике и истории запусков). Уникальный `chunk_id` превратил бы кнопку демо-прогона в одноразовую: второй клик падал бы на ограничении вместо того, чтобы либо дописать, либо честно попросить очистку. Переиндексация с нуля — явная кнопка «🧹 Очистить обе стратегии» |
| Индексы FAISS — файлы, а не таблицы | — | — | FAISS не имеет своей БД, поэтому векторы лежат в `index/*.index`, а метаданные — в SQLite. Согласованность поддерживается тем, что прогон пишет и то, и другое, а `clear` убирает и файл, и строки; расхождение видно в статистике (`index_vectors` против `chunks`) и лечится очисткой индекса |
| `day21/documents/*.py` в игноре | — | — | Каталог `documents/` — производные данные (правило `documents/` в `.gitignore`), поэтому копии четырёх исходников внутри него тоже не в Git. Это ожидаемо: проверка «код не попал в игнор» даёт ровно эти четыре файла, а не потерю исходников дня |
| Сжатие промптов экономит мало | — | — | На компактных блоках дня (профиль, инварианты, каталог инструментов, память) снимать нечего: в отчёте об оптимизации снято 0 токенов, а на материале, для которого сжатие сделано (документ с маркером усечения и JSON в ограждении), — 4173 → 4104 токена (1.7%). Сжатие — страховка от «раздутых» блоков, а не основной рычаг: основной вклад дают кэш контекста и непиковые часы |
| Непик — тариф провайдера | — | — | Окна и размер скидки заданы конфигом (`OFF_PEAK_*`), а не измерением: планировщик переносит задачу флагом `prefer_off_peak`, а размер скидки остаётся за провайдером. Поэтому в отчёте непик указан в допущениях |
| Модель греется в демон-потоке | — | — | Блокирующий прогрев задержал бы старт бэкенда на десятки секунд, а на первой загрузке — на минуты (скачивание весов). Неудача прогрева не валит старт: она видна как `failed` первого прогона индексации с текстом причины |
| PDF-источников нет | — | — | Генерация PDF потребовала бы новой зависимости, а внешние статьи — сети и лицензий. Роль «статей» играют документы репозитория (README дней, `docs/architecture.md`, четыре исходника, `AGENTS.md` и корневой `README.md`) — это задание дня допускает прямо |
| Флот поднимается в `lifespan`; оркестрация — линейная цепочка | — | — | Унаследовано от дня 20: `connect_all()` стартует три процесса на каждый запуск приложения (сбой сервера не мешает старту, тесты защищены autouse-фикстурой `no_real_fleet`); ветвления, параллельные шаги и возобновление прогона оркестрации не сделаны. Рамки — в `docs/reports/orchestration_demo.md` |

## Проверка лимита строк

Из папки `day21` (исключены `.venv` и вендорный `.agents/`):

```powershell
uv run python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and '.agents' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Фактический вывод:

```
[('backend\\agents\\agent.py', 2284)]
```

`app.py` (79 ≤ 100) и `backend/api/main.py` (75 ≤ 80) в лимитах; `frontend/common.py`,
`backend/core/config.py` и `backend/domain/__init__.py` (по 400) — ровно на границе,
в пределах лимита. Скрипт отчёта об оптимизации тоже перестал быть превышением: замер
(`scripts/cost_optimization_measure.py`, 382) вынесен из рендера
(`scripts/cost_optimization_report.py`, 285) — вместе они были длиннее 400. Новые файлы
дня 22 лимит не нарушают: самый длинный — `backend/services/rag_service.py` (396), за
ним `tests/unit/test_rag_service.py` (371), `scripts/run_rag_eval.py` (316) и
`backend/domain/rag_mode.py` (309).
Каталог `.agents/` исключён не для красоты: в этой копии скиллы библиотек скопированы
(а не слинкованы), и три шаблона Streamlit внутри скилла `developing-with-streamlit`
длиннее 400 строк (416–449). Это код библиотеки, а не дня.
