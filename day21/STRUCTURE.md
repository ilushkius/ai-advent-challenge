# Структура дня 29

Карта модулей дня 29: что где лежит и за что отвечает. Правила структуры — в
[`../docs/project-rules.md`](../docs/project-rules.md) и
[`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

**Что такое день 29.** Проект дня 21 (копия дня 20 — агент DeepSeek с памятью, FSM,
инвариантами, профилем, MCP-клиентом и флотом серверов, планировщиком, пайплайном и
оркестрацией) плюс семь подсистем, добавленных днями 21–29:

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
   фрагментам с оценкой опоры на контекст, роутер `/rag` (7 эндпоинтов), панель
   «🔍 RAG-запрос по корпусу» в разделе чата, раздел «🆚 RAG-сравнение» и раздел
   «🧪 RAG-демо». День 23 добавил второй этап отбора: переформулировку вопроса
   моделью, пересортировку кандидатов кросс-энкодером (`RAG_RERANK_MODEL`), порог
   отсечения слабых фрагментов (`RAG_FILTER_MIN_SCORE`) и сравнение четырёх режимов
   отбора (`POST /rag/compare_modes`); отчёт — `docs/reports/rag_modes.md` по 10
   контрольным вопросам. День 24 сделал источники и цитаты обязательными, добавил
   проверку опоры ответа на цитаты (`backend/domain/rag_quotes.py`), порог
   релевантности с режимом «не знаю» (`RAG_RELEVANCE_THRESHOLD`) и демо-прогон
   десяти контрольных вопросов (`backend/data/demo_questions.json`,
   `GET /rag/demo-questions`, `POST /rag/demo-run`); отчёт —
   `docs/reports/rag_quotes_eval.md`.
4. **Мини-чат с RAG и памятью задачи** — отдельное приложение `mini_chat/` (Streamlit
   на порту 8502), изолированное от песочницы `app.py`: чат с «Источниками» и
   «Цитатами» под каждым ответом и боковая панель «Память задачи». Промпт собирает сам
   сервис (`MiniChatService.chat`): фрагменты берёт тем же отбором RAG
   (`rag_service.retrieval.run`), добавляет память задачи (четыре ключа рабочей памяти
   дня 11 — `goal`, `terms`, `constraints`, `clarifications`) и историю диалога. Ответ
   идёт через `rag_llm.call_with_retry` (повторный сбой — `mode="error"`), а память
   обновляет отдельный вызов модели с пределом ожидания 5 с: не ответила — остаётся
   предыдущее состояние и `memory_updated: false`. Роутер `/mini-chat` (5 эндпоинтов),
   отчёт — `docs/reports/mini_chat_scenarios.md` по двум длинным сценариям
   (`backend/data/mini_chat_scenarios.json`).
5. **Локальная LLM как второй провайдер** (день 26) — рядом с DeepSeek появляется
   локальная модель Ollama: домен `llm_provider`, клиент `local_llm_client`, точка
   выбора клиента `llm_factory`, переключатель «🤖 Провайдер LLM» и раздел
   «🖥 Локальная LLM»; отчёт `docs/reports/local_llm_demo.md`.
6. **Сравнение провайдеров** (день 28) — парный прогон «один вопрос — локальный и
   облачный ответ»: эндпоинт `POST /rag/compare_providers`, чистый домен `rag_compare`
   (вердикт строки и сводка), раздел «🏠 Локальный RAG», скрипт
   `scripts/run_local_rag_comparison.py` и отчёт
   `docs/reports/local_rag_comparison.md`.
7. **Оптимизация локальной LLM** (день 29) — профили настройки локального провайдера
   (`baseline` дня 26 и `tuned` по умолчанию) и их прогон на вопросах корпуса:
   эндпоинт `POST /llm/tune`, домены `local_tuning`/`local_tuning_eval`, службы
   `local_tuning_service`/`local_llm_resources`, раздел «⚙️ Оптимизация локальной LLM»,
   скрипты `scripts/run_local_llm_optimization.py` и `scripts/local_tuning_report.py`,
   отчёт `docs/reports/local_llm_optimization.md`.

Унаследовано из дня 20 — одной строкой: **остальное дерево, включая `mcp_server/`,
`mcp_servers/` с `mcp_servers.json`, память, профиль, состояние задачи, инварианты,
планировщик, пайплайн и оркестрацию, — копия дня 20 без изменений**; карта этих
модулей построчно — в [`day20/STRUCTURE.md`](../day20/STRUCTURE.md). Ниже описано
только то, что дни 21–29 добавили или изменили.

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
├── app.py                    # точка входа Streamlit (88 строк, лимит 100): set_page_config + вызовы секций
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
├── frontend/                 # Streamlit UI по секциям (37 модулей, включая __init__.py)
│   ├── indexing_api.py       # HTTP-запросы индексации (/indexing/...) поверх api_client
│   ├── indexing_section.py   # раздел «📦 Индексация»: кнопка демо, прогресс этапов, история, очистка
│   ├── indexing_compare.py   # сравнение стратегий: таблица метрик, гистограммы, примеры чанков, тестовые запросы
│   ├── indexing_search.py    # форма ручного поиска по построенному индексу
│   ├── cost_api.py           # HTTP-запросы вкладки «💰 Расходы» (/llm/...) поверх api_client
│   ├── cost_section.py       # вкладка «💰 Расходы»: пик/непик, кэш и сжатие, расход по дням, журнал запросов
│   ├── rag_api.py            # HTTP-запросы RAG (/rag/...): query, compare, compare_modes, config
│   ├── rag_section.py        # панель «🔍 RAG-запрос по корпусу» и раздел «🆚 RAG-сравнение» (включая сравнение режимов)
│   ├── llm_api.py            # HTTP-запросы провайдера, демо и оптимизации локальной модели (/llm/provider, /llm/local-demo, /llm/tune)
│   ├── local_llm_section.py  # раздел «🖥 Локальная LLM»: подпись провайдера, кнопка прогона, таблица ответов
│   ├── local_rag_section.py  # раздел «🏠 Локальный RAG»: вопросы, кнопка прогона, таблица сравнения и сводка
│   ├── local_tuning_section.py  # раздел «⚙️ Оптимизация локальной LLM»: профили и кванты, таблицы, промпт до/после
│   └── …                     # остальные секции унаследованы от дня 20
├── mini_chat/                # ОТДЕЛЬНОЕ приложение дня 25 (Streamlit, порт 8502): app.py — точка входа
│                             # (root дня в sys.path + панели), api.py — HTTP-запросы /mini-chat/... поверх
│                             # frontend.api_client, panels.py — боковая панель и ход диалога
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным (девять слоёв, в каждом __init__.py)
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # 18 модулей: 15 роутеров по доменам (в том числе indexing.py, llm.py, rag.py
│   │                         # и mini_chat.py), main.py, lifespan.py
│   ├── core/                 # 6 модулей: config (в том числе разделы оптимизации затрат и локальной LLM),
│   │                         # env_file (путь .env дня и парсер его строк), dependencies, mcp_server_config
│   │                         # и prompt_builder (строитель промптов с кэшем префикса)
│   ├── domain/               # 60 модулей: чистые правила и данные — индексация (chunking, document_sources,
│   │                         # index_metrics, index_scenarios, indexing_fsm, indexing_prompt), стоимость и непик
│   │                         # (llm_cost, peak_hours), RAG (rag_mode, rag_filter, rag_corpus_spec, rag_eval,
│   │                         # rag_compare), провайдер LLM (llm_provider), оптимизация локальной модели
│   │                         # (local_tuning, local_tuning_eval) и унаследованные домены
│   ├── services/             # 48 модулей: индексация (chunker, embedding_service, index_service, document_loader,
│   │                         # index_runner, index_comparison, indexing_service), затраты (llm_client,
│   │                         # prompt_compressor, off_peak), RAG (rag_corpus_loader, rag_service, rag_retrieval,
│   │                         # rag_records, rag_llm, rag_errors, rag_corpus_index, rerank_service, rag_compare_service), мини-чат
│   │                         # (mini_chat_service, mini_chat_memory), провайдер (llm_factory, local_llm_client,
│   │                         # local_llm_demo) и оптимизация локальной модели (local_llm_resources,
│   │                         # local_tuning_service) плюс унаследованные
│   ├── storage/              # 17 модулей: chunk_store и index_run_store (журнал прогонов индексации),
│   │                         # llm_usage_store и llm_usage_rows (журнал расходов) плюс унаследованные хранилища
│   ├── agents/               # Agent (в generate — шаг поиска по индексу, клиент LLM и строитель промптов),
│   │                         # MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы: 13 модулей, в том числе indexing.py (document_chunks, index_runs)
│   │                         # и llm_usage.py (журнал расходов)
│   ├── schemas/              # Pydantic-схемы API: 18 модулей, в том числе indexing.py, llm.py, rag.py, rag_compare.py, mini_chat.py и local_tuning.py
│   ├── data/                 # данные дня: demo_questions.json (10 контрольных вопросов RAG) и
│   │                         # mini_chat_scenarios.json (два сценария мини-чата: 14 и 12 реплик)
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 2721 тест (unit/ — 1885, integration/ — 587, e2e/ — 249); по умолчанию 2637 (84 slow отложены)
│   ├── conftest.py           # общие фикстуры (session-scoped schema_template для схемы БД) + autouse no_real_network
│   ├── fixtures_fleet.py     # фикстуры флота MCP-серверов и оркестрации (вынесены из conftest: лимит 400 строк)
│   ├── fixtures_indexing.py  # фикстуры индексации документов (тоже вынесены из conftest)
│   ├── indexing_fakes.py     # фейки индексации: эмбеддер на хешах слов и три тестовых документа
│   ├── fixtures_rag.py       # фикстуры RAG: тестовый корпус, служба поиска, стаб-клиент и служба RAG
│   ├── rag_fakes.py          # фейки RAG: стаб-клиент DeepSeek и тексты тестового корпуса
│   ├── mini_chat_fakes.py    # фейки мини-чата: стаб-клиент с двумя ответами (ответ и JSON памяти),
│   │                         # заглушка отбора (сильная/слабая выдача) и клиент с неразобранной памятью
│   ├── fixtures_mini_chat.py # фикстуры мини-чата: служба на фейковом отборе — сильная, слабая и сломанная
│   ├── unit/test_rag_service_providers.py      # unit дня 28–29: сборка клиента по провайдеру, парный прогон, строка-ошибка, вердикт, сводка, профиль настройки в вызове
│   ├── unit/test_local_tuning.py               # unit дня 29: профили и разрешение окружения, вердикты строки, сводка варианта и ранжирование
│   ├── unit/test_local_tuning_service.py       # unit дня 29: прогон на заглушке — параметры доходят до вызова, строка-ошибка, отказ Ollama, незнакомый профиль
│   ├── integration/test_local_rag_flow.py      # slow дня 28: реальный индекс дня 22, настоящая модель эмбеддингов и настоящая Ollama
│   └── …                     # унаследованные помощники тестов дня 20 (orchestration_fakes, mcp_fakes, stub_api, support…)
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов (не пакет)
│   ├── prepare_documents.py  # сборка набора документов: --force (пересобрать), --list (показать манифест)
│   ├── indexing_scenarios.py # пять сценариев индексации (демо, одиночная стратегия, поиск, качество, рестарт) + стенд
│   ├── indexing_demo.py      # точка входа дня: пять сценариев, сборка данных и отчёта, --stub-embedder
│   ├── indexing_report.py    # сборка docs/reports/indexing_demo.md из данных прогона
│   ├── indexing_ui_shot.py   # снимок раздела «📦 Индексация» в браузере (Playwright), fallback без картинки
│   ├── cost_optimization_measure.py # замер «до и после» на реальных текстах дня (токены tiktoken, деньги — формулы домена)
│   ├── cost_optimization_report.py  # рендер docs/reports/cost_optimization.md из данных замера + CLI
│   ├── prepare_rag_corpus.py # сборка корпуса RAG: --list, --force, --validate
│   ├── index_rag_corpus.py   # построение обоих индексов RAG (prepare_corpus через RAGService)
│   ├── rag_eval_cells.py     # клетки markdown-таблицы отчёта (экранирование, обрезка, строки источников)
│   ├── rag_eval_report.py    # рендер docs/reports/rag_modes.md: таблица режимов, свип порога, вердикты
│   ├── run_rag_eval.py       # прогон 10 контрольных вопросов через 4 режима и запись docs/reports/rag_modes.md
│   ├── demo_local_llm.py     # три запроса к локальной Ollama из программы (без бэкенда) и печать отчёта
│   ├── run_local_rag_comparison.py # прогон десяти вопросов через POST /rag/compare_providers и запись docs/reports/local_rag_comparison.md
│   ├── run_local_llm_optimization.py # прогон профилей и квантов через POST /llm/tune и запись docs/reports/local_llm_optimization.md
│   ├── local_tuning_report.py # рендер отчёта дня 29: шапка, метод, промпт до/после, таблицы, ресурсы, кванты
│   └── …                     # унаследованные скрипты дней 18–20 (orchestration_*, pipeline_*, scheduler_*, video_*)
├── invariants_demo.md        # отчёт дня 14 (унаследован; лежит в корне дня — путь задан заданием дня 14)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── pyproject.toml, uv.lock   # зависимости (uv): sentence-transformers, faiss-cpu, numpy, mcp, sqlalchemy…; версии — в локе
├── .agents/skills/           # скиллы: вендорные библиотек (uvx library-skills --copy) и проектный check_docs (проверка документации перед коммитом); не код дня
├── .python-version           # 3.14
├── .env.example              # шаблон DEEPSEEK_API_KEY, DAY21_BACKEND_URL, DAY21_EMBEDDING_MODEL,
│                             # LLM_PROVIDER, LOCAL_LLM_MODEL, LOCAL_LLM_URL и профиль настройки
│                             # локальной модели (LOCAL_LLM_PROFILE, LOCAL_LLM_TEMPERATURE,
│                             # LOCAL_LLM_NUM_CTX, LOCAL_LLM_CHAT_MAX_TOKENS)
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
(параллелизм, общая схема БД, маркер `slow`; тоже написан по замерам),
`local_llm_demo.md` — развёртывание и замеры локальной модели (день 26),
`local_rag_comparison.md` — парный прогон провайдеров (день 28),
`local_llm_optimization.md` — профили и кванты на вопросах корпуса (день 29),
остальные (`orchestration_demo.md`,
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

## Новые модули дней 21–29

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

### RAG-режим (дни 22–24): `backend/domain/`, `services/`, `schemas/`, `api/`, `frontend/`, `scripts/`

| Модуль | Назначение |
|---|---|
| `backend/domain/rag_mode.py` | Промпт и лимиты режима: `RAG_SYSTEM_PROMPT` (ответ только по контексту, прямые цитаты в кавычках, «Не знаю» при отсутствии ответа), `RAG_DEFAULT_TOP_K = 5`/`RAG_MAX_TOP_K = 10`, `RAG_CONTEXT_MAX_TOKENS = 3000`, `RAG_CHUNK_MAX_CHARS = 2000`, `RAG_GROUNDING_MIN_SHARE = 0.5`/`RAG_GROUNDING_MIN_WORD = 5`, `RAG_LLM_ATTEMPTS = 3` c паузой `RAG_RETRY_SECONDS`/`RAG_RETRY_BACKOFF`, `RAG_CANDIDATE_POOL = 30`, `RAG_VECTOR_WEIGHT = 0.2`; `resolve_rag_strategy`, `render_context`/`render_rag_block` (заголовок `## Контекст из корпуса RAG`), `fit_context` (жадный бюджет), `content_words`/`query_weights`/`lexical_score` (вклад слова = 1 / число фрагментов с ним), `grounding_share`/`grounding_verdict`; `rank_candidates` отдаёт вместе с гибридным `score` и `lexical_score` |
| `backend/domain/rag_quotes.py` | Домен дня 24 — порог релевантности, цитаты и уверенность: `RAG_RELEVANCE_THRESHOLD` (резолв при импорте: `RAG_RELEVANCE_ENV` → `.env` → `RAG_RELEVANCE_THRESHOLD_DEFAULT = 0.6`), `resolve_relevance_threshold`, `best_vector_score`/`is_weak` (максимум косинуса по пулу кандидатов), `dont_know_warning`, режимы `RAG_MODE_RAG`/`RAG_MODE_NO_RAG`/`RAG_MODE_DONT_KNOW`, `quote_of` (выдержка ≤ `QUOTE_MAX_CHARS = 200` по границе предложения), `quotes_from_items` (по цитате на фрагмент, детерминированно), `normalize`, `citation_share`, `verify_citations` (подстрока или доля ключевых слов ≥ `CITATION_MIN_SHARE = 0.3`), `confidence` (`CONFIDENCE_HIGH = 1.0`/`CONFIDENCE_LOW = 0.3`/`CONFIDENCE_NONE = 0.0`), `citation_block` |
| `backend/domain/rag_demo.py` | Контрольные вопросы демо: `DEMO_QUESTIONS_PATH` (`backend/data/demo_questions.json`), `DemoQuestion` (вопрос, ожидание, ожидаемый режим, ожидаемые источники), `load_questions` (битый или пропавший файл — пустой список с предупреждением), `question_as_dict`, `expected_found` (через `rag_eval.source_matches`), `verdict` и тексты вердиктов (`VERDICT_OK`, `VERDICT_DONT_KNOW_OK`, `VERDICT_MODE_MISMATCH`, `VERDICT_SOURCE_MISS`, `VERDICT_UNCITED`, `VERDICT_FALLBACK`, `VERDICT_NONE`) |
| `backend/domain/rag_filter.py` | Домен дня 23 — режимы и порог: `RAG_MODE_BASELINE`/`RAG_MODE_REWRITE`/`RAG_MODE_RERANK`/`RAG_MODE_RERANK_FILTER` с подписями и рычагами (`RAG_MODE_KNOBS`), `resolve_rag_mode`, `mode_knobs`, `mode_catalog`, `normalize_rerank_scores` (баллы в `[0, 1]`), `candidate_text` (обрезка фрагмента до `RAG_RERANK_MAX_CHARS = 1000`), `apply_rerank` (поле `rerank_score`, стабильная сортировка), `filter_hits` (порог `min_score`), `RAG_RERANK_MODEL` (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`), `RAG_RERANK_BATCH_SIZE = 32`/`RAG_RERANK_MAX_LENGTH = 512`, `RAG_FILTER_MIN_SCORE`, `RAG_MAX_CANDIDATES = 60`, `RAG_THRESHOLD_GRID`, тексты предупреждений этапов |
| `backend/domain/rag_corpus_spec.py` | Состав корпуса: `RAG_CORPUS_SOURCES` (36 источников дня 21), `RAG_CORPUS_SUBDIR = "rag_corpus"`, минимумы `RAG_CORPUS_MIN_PAGES = 25`/`RAG_CORPUS_MIN_CHUNKS = 50`, `corpus_pages`, `validate_sources` (пропавший файл или суффикс вне `DOCUMENT_SUFFIXES` — проблема) |
| `backend/domain/rag_eval.py` | Оценка: `RagQuestion` (вопрос, `key_facts`, `expected_sources`, `note`), `RAG_QUESTIONS` (10 записей), `question_as_dict`, `facts_found`, `fact_score` (доля найденных фактов), `verdict` («лучше»/«хуже»/«равно» по долям), `expected_found` (найден ли ожидаемый источник в выдаче) |
| `backend/data/demo_questions.json` | Данные демо дня 24: 10 контрольных вопросов с ожидаемым режимом (`rag`/`dont_know`), ожидаемыми источниками (слаги файлов корпуса) и пояснением; правится без кода |
| `backend/services/rag_corpus_loader.py` | `RagCorpusLoader(DocumentLoader)`: подкаталог `documents/rag_corpus/` и источники дня 21, `status` (документы, символы, страницы, готовность), `validate`; синглтон `get_rag_corpus_loader` |
| `backend/services/rag_errors.py` | Исключения режима: `RAGError`, `RAGRejected` (код причины и сообщение), `RAGUpstreamError` — вынесены из службы, чтобы их импортировали и роутер, и этапы поиска без цикла |
| `backend/services/rag_corpus_index.py` | Подготовка корпуса: `CHUNK_STRATEGIES`, `prepare_corpus(loader, index_service)` (пересборка корпуса и обоих индексов, проверка минимума чанков), `corpus_config(loader, store)` (состояние корпуса и индексов для `GET /rag/config`) |
| `backend/services/rag_retrieval.py` | Этапы отбора дня 23: `RAGStages` (запрос, режим, стратегия, пул, порог, поле сортировки, кандидаты до и после отсечения, флаг реранка, предупреждение) и `RAGRetrieval.run` — поиск (сырая близость в `vector_score`), гибридный отбор, `_rerank`, `filter_hits`, обрезка до `top_k`; `_limit`/`_candidate_limit` держат границы дня 22 |
| `backend/services/rerank_service.py` | `RerankService`: ленивая загрузка `CrossEncoder(RAG_RERANK_MODEL)` в кэш `INDEX_MODELS_DIR`, `score(query, texts)` с партией `RAG_RERANK_BATCH_SIZE`, `warmup`, `reset`, `RerankError`; синглтон `get_rerank_service`; модель грузится только внутри `_load`, поэтому тесты идут на стабе |
| `backend/services/rag_records.py` | Сборка полей ответа: `source(hit)` (восемь полей фрагмента, `score` = балл отбора), `selection(stages)` (метрики отбора и предупреждения для `RagQueryOut`) и `dont_know(question, stages, duration_ms)` — запись режима «не знаю» без вызова модели |
| `backend/services/rag_demo_service.py` | Прогон демо: `questions` (для API), `run_demo(service, questions)` — строка на вопрос плюс сводка, `demo_row` (режим, `top_score`, ответ, источники, цитаты, уверенность, вердикт), `summary` (распределение режимов, источников, цитат и расхождений); падение одного вопроса — строка с `fallback`, а не срыв прогона |
| `backend/services/rag_llm.py` | Повторы вызова модели: `call_with_retry` (попытки `RAG_LLM_ATTEMPTS`, паузы `RAG_RETRY_SECONDS`/`RAG_RETRY_BACKOFF`), `response_text`, `usage_dict` |
| `backend/services/rag_service.py` | `RAGService`: `retrieve`/`_stages` (режим → переформулировка → этапы поиска), `_rewrite` (запрос моделью с `RAG_REWRITE_SYSTEM_PROMPT`), `_answer` (гейт порога релевантности → общий путь с контекстом и без), `rag_query`/`no_rag_query` (единый `RAG_SYSTEM_PROMPT`, различие — блок контекста), `verify_citations`, `compare`, `compare_modes` (четыре режима на одном вопросе), `prepare_corpus`, `config` (включая `relevance_threshold`); повторы вызова, откат на ответ без RAG, `RAGRejected`/`RAGUpstreamError` с кодами причин, синглтон `get_rag_service` |
| `backend/schemas/rag.py` | Pydantic-схемы: `RagQueryIn`/`RagQueryOut` (рычаги `rewrite`/`rerank`/`min_score`/`top_k_candidates`, метрики отбора, `quotes`/`quotes_verified`/`confidence`), `RagSourceOut` (четыре балла), `RagQuoteOut`, `RagTokensOut`, `RagCompareIn`/`RagCompareOut`, `RagModesIn`/`RagModeOut`/`RagModesOut`, `RagCorpusOut`, `RagIndexOut`, `RagConfigOut` (`modes`, `rerank_model`, `min_score_default`, `candidates_max`, `relevance_threshold`), схемы демо `RagDemoQuestionOut`/`RagDemoQuestionsOut`/`RagDemoIn`/`RagDemoRowOut`/`RagDemoSummaryOut`/`RagDemoOut` |
| `backend/api/rag.py` | Роутер `/rag`, семь эндпоинтов (запрос, конфигурация, сравнение, сравнение режимов, `GET /rag/demo-questions`, `POST /rag/demo-run`, `POST /rag/compare_providers`); коды: 400 (пустой вопрос, неизвестная стратегия или режим), 422 (порог вне 0…1, пул вне 1…60), 409 (корпус не проиндексирован), 502 (сбой вызова модели) |
| `frontend/rag_api.py` | HTTP-запросы RAG поверх общего `request_json`: `api_rag_query` (рычаги `rewrite`/`rerank`/`min_score`/`top_k_candidates`), `api_rag_compare`, `api_rag_compare_modes`, `api_rag_config`, `api_rag_demo_questions`, `api_rag_demo_run`, `api_rag_compare_providers` |
| `frontend/rag_section.py` | Панель «🔍 RAG-запрос по корпусу» (тумблер, `top_k` 1–10, стратегия, тумблеры переформулировки и реранкера, слайдер порога, форма вопроса, метрики времени/токенов/фрагментов до и после фильтра/порога/кэша, предупреждения этапов, expander «📝 Цитаты из корпуса», expander «📚 Использованные источники» со четырьмя баллами, строка опоры и уверенности) и раздел «🆚 RAG-сравнение» (столбцы «🚫 Без RAG» / «✅ С RAG» плюс мультиселект режимов и сравнение четырёх режимов отбора) |
| `frontend/rag_demo_section.py` | Раздел «🧪 RAG-демо»: таблица контрольных вопросов, кнопка «🚀 Прогнать демо», прогресс «i/10», таблица результатов (режим, ответ, источники, цитаты, вердикт) и сводка; результат хранится в сессии, поэтому переживает перерисовку |
| `scripts/prepare_rag_corpus.py` | CLI сборки корпуса: `--list`, `--force`, `--validate`; печатает документы, символы, страницы против минимума и ожидаемое число чанков по стратегиям |
| `scripts/index_rag_corpus.py` | `RAGService.prepare_corpus()`: строит оба индекса RAG, печатает чанки, векторы и тайминги, проверяет минимум чанков на стратегию |
| `scripts/rag_eval_cells.py` | Клетки markdown-таблицы отчёта: `cell` (экранирование и обрезка до `REPORT_CELL_CHARS`), `expectation`, `verdicts_cell`, `answer_cell`, `sources_cell`, `source_line`, `misses`, `metrics_line`; вынесены из `rag_eval_report.py` по лимиту 400 строк |
| `scripts/rag_eval_report.py` | Чистый рендер отчёта и подсчёт итогов: `render_report`, `render_sweep`, `choose_threshold` (правило выбора порога), `summary_lines`, `step_check` (сверка ступени отсечения с `rerank`), `counts`, `appendix`; отделён от прогона, чтобы печать правилась без вызовов модели |
| `scripts/run_rag_eval.py` | Прогон 10 контрольных вопросов через 4 режима отбора и ответ без RAG: `fact_score`, вердикты против «без RAG» и против `baseline`, метрики «до/после фильтра», свип порога офлайн по баллам реранкера, запись `docs/reports/rag_modes.md`; флаги `--top-k`, `--strategy`, `--report`, `--limit`, `--threshold`, `--sweep` |
| `scripts/run_rag_quotes_eval.py` | Прогон демо дня 24: таблица десяти вопросов (режим, ответ, источники, цитаты, `max v`, авто- и ручной смысл, вердикт), распределение `max v` и итог, запись `docs/reports/rag_quotes_eval.md`; флаги `--out`, `--limit`, `--threshold`, `--sweep` (замер без вызовов модели), `--json`; код возврата 1 при расхождениях |

Корпус — производные данные: `documents/rag_corpus/` собирается из источников дня 21, а
индексы `index/rag_corpus_fixed.index`/`rag_corpus_structural.index` строятся заново
после клонирования. Новых таблиц RAG не вводит: обе стратегии живут строками в той же
таблице `document_chunks`, различаясь колонкой `strategy`.

Веса реранкера (день 23) тоже производные: кросс-энкодер складывается в `index/models/`
подкаталогами кэша `huggingface_hub`; при отсутствии весов реранкер не грузится, режимы
без него работают (`rerank_warning` в ответе), а `GET /rag/config` продолжает отдавать
конфигурацию корпуса и индексов.

### Мини-чат с RAG и памятью задачи (день 25): `mini_chat/`, `backend/`, `scripts/`, `tests/`

| Модуль | Назначение |
|---|---|
| `backend/services/mini_chat_service.py` | `MiniChatService`: `start_session` (8 hex-символов, `task_id = "mc-" + session_id`), `_known_session` (сессия восстанавливается по репликам, поэтому переживает перезапуск бэкенда), `chat` (отбор → контекст из трёх блоков → ответ → запись реплик → извлечение памяти), `_ensure_agent` (служебная строка `agents.agent_id = "mini-chat"` как якорь внешних ключей памяти), `get_task_memory`, `get_history`, `extract_task_memory`, `update_task_memory`, `end_session`, `_prompt_context`; фабрика `make_mini_chat_client` и синглтон `get_mini_chat_service`; ошибка `MiniChatSessionError` |
| `backend/services/mini_chat_memory.py` | Правила памяти задачи: ключи `goal`/`terms`/`constraints`/`clarifications`, `payload`/`task_memory`/`store_payload` (полная замена значений, в БД — JSON-строки), `memory_block`/`dialog_block` (блоки промпта), `extract_payload` (вызов извлекателя, `None` при сбое или неразобранном ответе); вынесен из сервиса по лимиту строк |
| `backend/schemas/mini_chat.py` | Pydantic-схемы: `MiniChatSessionIn`/`MiniChatSessionOut`, `MiniChatMessageIn` (`message` 1…500, `top_k` 1…10), `MiniChatTaskMemoryOut`, `MiniChatAnswerOut`, `MiniChatHistoryMessageOut`, `MiniChatHistoryOut`, `MiniChatCloseOut`; источники, цитаты и расходы — схемы RAG (`RagSourceOut`, `RagQuoteOut`, `RagTokensOut`) |
| `backend/api/mini_chat.py` | Роутер `/mini-chat`, пять эндпоинтов (создание сессии, реплика, память задачи, история, закрытие); коды: 400 (пустое сообщение), 404 (неизвестная сессия), 409 (корпус не проиндексирован, неизвестный режим), 422 (тело), 502 (сбой отбора) |
| `mini_chat/app.py` | Точка входа отдельного Streamlit-приложения (порт 8502): корень дня в `sys.path`, заголовок страницы и две отрисовки панелей; 28 строк |
| `mini_chat/api.py` | HTTP-запросы `/mini-chat/...` поверх общего `frontend.api_client.request_json` (второй HTTP-клиент не заводится) |
| `mini_chat/panels.py` | Разметка: боковая панель («Новая сессия», слайдер `top_k` 1–10, «Показывать цитаты», панель «Память задачи» с `goal`/`terms`/`constraints`/`clarifications`) и ход диалога (ответ, предупреждения режимов, expanders «Источники» и «Цитаты») |
| `backend/data/mini_chat_scenarios.json` | Два сценария прогона (14 и 12 реплик: RAG по документации проекта и агент обработки заявок) с целью каждого — читают и скрипт прогона, и slow-тест |
| `scripts/mini_chat_report.py` | Чистый рендер отчёта: слова цели, `goal_lost` (покрытие слов базовой цели против `GOAL_SHARE_MIN`), `goal_verdict` (доля реплик, удержавших цель, против `GOAL_KEEP_MIN`), таблицы сценариев и итог |
| `scripts/run_mini_chat_scenarios.py` | Прогон сценариев настоящей моделью и запись `docs/reports/mini_chat_scenarios.md`; флаги `--scenarios`, `--report`, `--top-k`, `--limit`, `--quiet` |
| `tests/mini_chat_fakes.py`, `tests/fixtures_mini_chat.py` | Фейки и фикстуры: стаб-клиент с двумя ответами (ответ и JSON памяти), заглушка отбора, службы — сильная, слабая (режим «не знаю») и сломанная (режим ошибки) |
| `tests/unit/test_mini_chat_service.py`, `tests/integration/test_mini_chat_flow.py` | 16 unit-тестов сервиса (источники и цитаты, память, история, режимы, сессии) и slow-тест прогона сценария на настоящем корпусе с заглушками модели и эмбеддера |

Промпт собирает сам сервис, а не `RAGService.rag_query`: у `rag_query` нет ни памяти, ни
истории, а при сбое модели он уходит в ответ без контекста, тогда как мини-чату нужен
`mode="error"`. Поэтому файлы дней 22–24 не правятся — RAG-служба используется только как
источник отбора (`rag_service.retrieval`). Основной `app.py` и его разделы тоже не
меняются: мини-чат живёт отдельным входом, а «Память задачи» — обычные записи рабочей
памяти в той же БД `agents.db`.

### Локальная LLM как второй провайдер (день 26): `backend/`, `frontend/`, `scripts/`, `tests/`

| Модуль | Назначение |
|---|---|
| `backend/domain/llm_provider.py` | Имена провайдеров (`PROVIDER_DEEPSEEK`, `PROVIDER_LOCAL`), `PROVIDERS`, `PROVIDER_LABELS` (подписи с эмодзи для интерфейса), `normalize_provider` (пусто/пробелы/регистр), `resolve` (явный аргумент → `config.LLM_PROVIDER` → `deepseek`; незнакомое имя — `ValueError`), `label`; значение по умолчанию читается в момент вызова, а не на импорте |
| `backend/services/local_llm_client.py` | `LocalLLMClient`: HTTP-клиент Ollama (`POST /api/chat`, `stream: false`, системное сообщение отдельно, контекст блоком в пользовательском), `generate` для демо, `generate_with_context` с той же сигнатурой, что у `LLMClient`; возвращает словарь (`provider`, `model`, `answer`, `duration_ms`, `tokens`), предел ответа — `max_tokens` → `LLM_TASK_MAX_TOKENS[task_type]` → `LLM_MAX_RESPONSE_TOKENS`; `post` — точка подмены HTTP, `LocalLLMError` на любой сбой (нет службы, статус ≠ 200, не-JSON, пустой ответ) |
| `backend/services/llm_factory.py` | `get_llm_client(provider, ...)`: единственная точка выбора клиента (`local` → `LocalLLMClient`, иначе `LLMClient` с фабрикой SDK-клиента вызывающего кода); в `services/__init__.py` не реэкспортируется — там уже есть одноимённая функция-синглтон DeepSeek из `llm_client` |
| `backend/services/local_llm_demo.py` | `LOCAL_DEMO_QUESTIONS` (факт, логика, код), `quality_score` (эвристика 1–5 по тексту ответа), `run_demo` (три запроса через клиент провайдера, строки и `total_ms`) — один источник запросов для API, скрипта и отчёта |
| `backend/core/env_file.py` | `ENV_FILE` дня, `read_env_value` (парсер `NAME=VALUE` с `export` и кавычками) и `read_key_from_env_file`; вынесено из `config.py` по лимиту 400 строк. Резолвер `resolve_api_key` остался в `config.py` (он читает окружение процесса и потому вызывается как `config.resolve_api_key()`), а тесты подменяют его точку входа `config.read_key_from_env_file` |
| `backend/core/config.py` | Раздел «Локальная LLM (день 26)»: `LLM_PROVIDER_DEFAULT`, `LOCAL_LLM_MODEL_DEFAULT`, `LOCAL_LLM_URL_DEFAULT`, `LLM_PROVIDER` (окружение → `.env` → дефолт), `LOCAL_LLM_MODEL`, `LOCAL_LLM_URL`, `LOCAL_LLM_TIMEOUT` (120 с), `LOCAL_LLM_DEMO_MAX_TOKENS` |
| `backend/services/rag_llm.py` | Плюс `completion_tokens` и терпимость `response_text`/`usage_dict` к словарю локального клиента (два вида ответа читаются одним кодом); сюда же переехала фабрика `make_rag_client` — деталь клиента, а не режима RAG |
| `backend/services/rag_service.py` | `llm_client_for(provider)` с кэшем клиентов по имени, `rag_query`/`no_rag_query`/`_answer`/`_stages`/`_rewrite` протягивают `provider`, в записи ответа — поле `provider` |
| `backend/services/mini_chat_service.py` | `llm_client_for` и `memory_client_for` (два кэша: ответ и извлечение памяти), `chat(..., provider=)`, `extract_task_memory`/`update_task_memory(provider=)`, `memory_timeout` (5 с у облака, `LOCAL_LLM_TIMEOUT` у Ollama) |
| `backend/api/llm.py` | `POST /llm/local-demo` (502 при недоступной Ollama) и `GET /llm/provider` (провайдер процесса, имена, подписи, модель, адрес, таймаут) |
| `backend/schemas/llm.py` | `LocalDemoOut` и `LocalDemoRowOut`; в `rag.py`/`mini_chat.py` — поле `provider` во входе и выходе |
| `frontend/llm_api.py` | `api_llm_provider()` и `api_local_demo()` (второй — с `LONG_TIMEOUT` 600 с: первый запрос локальной модели грузит веса) |
| `frontend/local_llm_section.py` | Раздел «🖥 Локальная LLM»: подпись провайдера/модели/адреса, кнопка «▶ Прогнать 3 запроса», таблица (запрос, ответ, время, токены, качество, провайдер) и полные ответы в expanders; `BackendError` — плашкой, страница не падает |
| `frontend/sidebar.py`, `frontend/rag_section.py`, `frontend/rag_api.py`, `frontend/chat_section.py` | Переключатель «🤖 Провайдер LLM» в начале боковой панели (ключ `llm_provider`), передача `provider` в `POST /rag/query`, метрика «Провайдер» в ответе, новая вкладка раздела |
| `mini_chat/api.py`, `mini_chat/panels.py` | Свой переключатель (ключ `mc_provider`), `provider` в запросе реплики, подпись «Провайдер: … · модель: …» под ответом |
| `scripts/demo_local_llm.py` | Прогон трёх запросов без бэкенда (прямо в Ollama) и печать отчёта; код возврата 1 печатает причину и подсказки `ollama serve` / `ollama pull` |
| `tests/unit/test_local_llm_client.py`, `tests/unit/test_llm_factory.py`, `tests/unit/test_rag_llm_dict.py`, `tests/unit/test_rag_provider.py` | HTTP-запрос к `/api/chat` на фейковом `post` (URL, payload, `stream`, системное сообщение, `num_predict` по типу задачи, форма ответа) и негативные случаи; выбор клиента фабрикой и нормализация имён; чтение словаря помощниками `rag_llm`; путь `provider=local` через RAG-службу и мини-чат |
| `tests/e2e/test_rag_api.py`, `tests/e2e/test_llm_api.py`, `tests/rag_fakes.py` | `LocalDictStubClient` (ответ-словарь без HTTP), HTTP-контракт `provider` в `/rag/query` (200 и 400 на незнакомое имя), демо `/llm/local-demo` (три строки, токены, 502 при сбое Ollama) и `GET /llm/provider` |

Точка выбора клиента одна — `llm_factory`, поэтому ни `RAGService`, ни
`MiniChatService` не знают имён провайдеров: они получают клиента и читают его ответ
помощниками `rag_llm`. Агентский чат (`POST /agents/{id}/generate`) в день 26 не
меняется: его путь — `Agent.llm_client` и `PromptBuilder`, задание дня его не называет.

### Локальный RAG (день 28): `backend/domain/`, `services/`, `schemas/`, `api/`, `frontend/`, `scripts/`, `tests/`

| Модуль | Назначение |
|---|---|
| `backend/domain/rag_compare.py` | Правило вердикта строки и сводка прогона: `verdict(local, cloud)` (сначала «ответил ли по корпусу» — режим `rag` и не `fallback`, затем подтверждённые цитаты → уверенность → число источников), `row(question, local, cloud)` и `summary(rows)` из 15 полей (средние времена, счётчики режимов, источников и вердиктов, общий вердикт); чистый домен |
| `backend/services/rag_compare_service.py` | Прогон списка вопросов двумя провайдерами: `run(service, questions=None, *, top_k, strategy)` задаёт пару ответов на вопрос (сначала `local`, затем `deepseek`) и возвращает строки и сводку; пустой список — десять контрольных вопросов демо; сбой одного вызова — строка `mode="error"` с предупреждением, а не срыв прогона |
| `backend/schemas/rag_compare.py` | Pydantic-схемы `RagCompareProvidersIn` (`questions`, `top_k`, `strategy`), `RagProviderRowOut` (вопрос, `local`/`cloud` как `RagQueryOut`, вердикт), `RagProviderSummaryOut` (15 полей сводки) и `RagCompareProvidersOut` (строки и сводка) |
| `backend/api/rag.py` | Седьмой эндпоинт `POST /rag/compare_providers`: принимает `RagCompareProvidersIn` и отдаёт строки и сводку; отказы по-прежнему 400/409 (`RAGRejected`), сбой одного вызова — строка `mode="error"`, а не 502 |
| `frontend/local_rag_section.py` | Раздел «🏠 Локальный RAG»: список вопросов, слайдер `top_k`, кнопка «🚀 Прогнать сравнение», таблица (вопрос, ответы обеих моделей, источники, время, режим, вердикт), метрики сводки и раскрывашки с полными ответами |
| `scripts/run_local_rag_comparison.py` | Прогон через HTTP-эндпоинт `POST /rag/compare_providers` и markdown-отчёт: шапка с моделью и числами индекса, правило вердикта, таблица сравнения, приложение с полными ответами и итог; флаги `--report`, `--backend`, `--top-k`, `--strategy`, `--limit` |
| `tests/unit/test_rag_service_providers.py`, `tests/integration/test_local_rag_flow.py` | Unit: сборка клиента по провайдеру, парный прогон, строка-ошибка, вердикт и сводка (15 тестов). Slow: полный локальный цикл на настоящих весах — реальный индекс дня 22, настоящая модель эмбеддингов и настоящая Ollama (пропускается, если служба или индекс недоступны) |

Retrieval в это сравнение не входит: поиск по корпусу у обеих сторон один и тот же и
всегда локальный, различается только тот, кто генерирует ответ, — поэтому колонка
«Источники» сравнивает не retrieval, а то, воспользовалась ли модель контекстом.
Автовердикт — машинный (режим → цитаты → уверенность → источники); общий вердикт
прогона берётся по большинству строк.

### Оптимизация локальной LLM (день 29): `backend/domain/`, `services/`, `schemas/`, `api/`, `frontend/`, `scripts/`, `tests/`

| Модуль | Назначение |
|---|---|
| `backend/domain/local_tuning.py` | Профили настройки локальной модели: константы (`PROFILE_BASELINE`/`PROFILE_TUNED`, `PROFILE_LABELS`, `BASELINE_NUM_CTX = 4096`, переписанный `LOCAL_TUNED_RAG_PROMPT`), `TuningProfile` (`key` для кэша клиентов, `title`, `as_dict`), `baseline_profile`/`tuned_profile`/`create`/`active`/`profile_for`/`prompt_for` и разрешение окружения `resolve_profile`/`resolve_number` (env → `.env` → значение по умолчанию, битое — предупреждение и дефолт, как у порога дня 24) |
| `backend/domain/local_tuning_eval.py` | Оценка прогона: `quality_row` (вердикт дня 24 плюс `mode_match`, `sources_found`, `quotes_verified`, `grounding_ok`, токены, скорость, прогрев), `summarize` варианта (`avg_ms` только по строкам режима `rag`), `compare` (ранг `verdict_ok` → `quotes_verified` → `grounding_ok`, тайбрейк — меньшее `avg_ms`) и `summary` прогона (варианты, пары «до/после» по каждой модели, лучший вариант и суммарное время) |
| `backend/services/local_tuning_service.py` | Прогон `run(service, …)`: пары «модель × профиль», запрос на вариант через `RAGService.rag_query(provider="local", profile=…)`, ресурсы после прогона варианта, сбой вызова — строка `error`, все строки упали — `LocalLLMError` (роутер отдаёт 502) |
| `backend/services/local_llm_resources.py` | Метрики Ollama: `version()` (`GET /api/version`) и `snapshot()` (`GET /api/ps` → `size_mb`, `vram_mb`, `gpu_percent`, `context_length`); сбой метрики приходит данными (`error`), а не исключением — прогон из-за неё не срывается |
| `backend/services/rag_llm.py` | Общие точки дня 29: `client_for` (кэш клиентов службы по паре «провайдер + профиль»: профиль несёт модель и `num_ctx`) и `answer` (вызов с системным промптом, температурой и пределом ответа профиля) |
| `backend/services/rag_service.py`, `mini_chat_service.py`, `llm_factory.py`, `local_llm_client.py` | Профиль протянут в обе службы: `llm_client_for(provider, profile)`, `_answer`/`_answer_record` берут промпт и параметры профиля; фабрика передаёт профилю `model`/`num_ctx`; клиент Ollama кладёт `num_ctx` в `options` только когда он задан и считает `tokens_per_second` (`eval_duration`) и `load_ms` (`load_duration`) |
| `backend/schemas/local_tuning.py` | Схемы прогона: `LocalTuneIn` (вопросы, профили, модели, `top_k`, стратегия), `LocalTuneProfileOut`, `LocalTuneRowOut`, `LocalTuneSummaryOut`, `LocalTuneVariantOut`, `LocalTunePairOut`, `LocalTuneOut` |
| `backend/api/llm.py` | Восьмой эндпоинт `POST /llm/tune` (400 — незнакомый профиль, 502 — Ollama недоступна) и новые поля `GET /llm/provider` (`local_profile`, `profiles`, `profile_labels`, `local_num_ctx`, `local_temperature`, `local_chat_max_tokens`) |
| `frontend/local_tuning_section.py`, `llm_api.py`, `chat_section.py` | Раздел «⚙️ Оптимизация локальной LLM»: подпись профиля и параметров, модели через запятую (квант — второй тег), мультивыбор профилей, слайдер `top_k`, кнопка «🚀 Прогнать сравнение профилей» (по одному варианту за запрос с прогрессом), таблицы строк и сводки, ресурсы, блок «Промпт: до и после» и раскрывашки с полными ответами; `api_local_tune` с `LONG_TIMEOUT` |
| `scripts/run_local_llm_optimization.py`, `scripts/local_tuning_report.py` | Драйвер прогона через `POST /llm/tune` (флаги `--report`, `--backend`, `--models`, `--profiles`, `--top-k`, `--strategy`, `--limit`) и рендер markdown-отчёта: шапка, метод, промпт до/после, таблицы строк и сводки, ресурсы, сравнение квантов, приложение, итог и «Выводы» |
| `tests/unit/test_local_tuning.py`, `test_local_tuning_service.py`, `test_local_llm_client.py`, `test_llm_factory.py`, `test_rag_service_providers.py`, `tests/e2e/test_llm_api.py` | Домен (профили, вердикты строки, сводка и ранжирование), прогон на заглушке (параметры доходят до вызова, строка-ошибка, отказ Ollama, незнакомый профиль), окно контекста и метрики скорости клиента, профиль в фабрике и в вызове RAG, HTTP-контракт `/llm/tune` (200/400/502) и новые поля `/llm/provider` |

Профиль выбирает клиента (модель плюс `num_ctx` — разные загруженные экземпляры
Ollama), а параметры вызова уходят аргументами: поэтому переформулировка запроса и
извлечение памяти мини-чата идут тем же клиентом, без перезагрузки весов. Оценка
прогона детерминированная — правила дней 22/24 плюс время как тайбрейк; модели-судьи и
оценки человека в прогоне нет.

### Экономия контекста агента: корень дня, `.gitignore` и настройки окружения

| Файл / место | Назначение |
|---|---|
| `AGENTS.md` | Правила дня и workflow нового дня: границы (`day1`–`day20` — архив), документация только о текущем состоянии, тесты не дублировать, обязательные инструменты, непиковые часы |
| `.omp/RULES.md` | Sticky-правила; путь именно `.omp/`, потому что omp загружает sticky только из native-локаций (`~/.omp/agent/RULES.md` и `<ближайший непустой .omp/>/RULES.md`) |
| `.agents/skills/check_docs/SKILL.md` | Проектный скилл «проверка документации перед коммитом»: чек-лист (`docs/usage.md`, `README.md`, `docs/architecture.md`, отчёт дня) и правило-вопрос перед `git commit`; каталог объявлен в корневом `.omp/config.yml` (`skills.customDirectories`) |
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
| `api/` | 18 | HTTP: 15 роутеров по доменам (в том числе `indexing.py` — индексация, `llm.py` — расходы, `rag.py` — RAG, `mini_chat.py` — мини-чат, `orchestration.py` — запуски, `mcp_servers.py` — флот), `lifespan.py` (старт и остановка фоновых служб, чтение индексов, прогрев модели) и `main.py` (сборка `app`) |
| `core/` | 6 | `config.py` (настройки дня: файл флота, каталоги документов и индексов, модель эмбеддингов, границы поиска и **весь раздел оптимизации затрат** — маршрутизация моделей, пределы ответа, тарифы, доля цены кэша, окна непика и параметры журнала), `mcp_server_config.py` (чтение `mcp_servers.json` и запись `tools_cache`), `dependencies.py` (доступ роутов к менеджеру, реестру, планировщику, службам пайплайна, оркестрации, индексации, RAG и клиенту LLM), `prompt_builder.py` |
| `domain/` | 57 | Чистые правила и данные без БД и сети: FSM задачи/сжатия/MCP/планировщика/пайплайна/оркестрации/**индексации**, графы переходов, расписания, агрегация, распознавание реплик, маппинг аргументов, стратегии, профиль, инварианты, тексты промптов, план шагов, **источники документов, блоки, метрики сравнения, тестовые запросы**, **стоимость запросов и правило непиковых часов**, **RAG-промпт, источники корпуса и контрольные вопросы**, **режимы отбора RAG с порогом и реранкером (день 23)**. Знают только stdlib, `core.config` и соседей по слою |
| `services/` | 45 | Прикладные сервисы: компрессор контекста, состояние задачи, инварианты, `mcp_*` (клиент, транспорт, ошибки, реестр с флотом, состояние сервера, раннер инструмента), планировщик и его службы, пайплайн, оркестратор, **чанкер, эмбеддинги, векторный индекс, загрузчик документов, прогон индексации, сборка метрик, служба индексации**, **клиент LLM, сжатие промптов и перенос запуска в непик**, **загрузчик корпуса RAG, служба RAG, этапы отбора, рекорды ответа, повторы вызова и служба кросс-энкодера (день 23)**, а также **служба мини-чата с правилами памяти задачи (день 25)** |
| `storage/` | 17 | Доступ к БД: `database.py` (движок, сессии, реэкспорт ORM), хранилища задач, инвариантов, памяти, планировщика, пайплайна, оркестрации, **чанков с журналом индексации** и **журнала расходов на LLM** (+ модули «строка → словарь») |
| `agents/` | 12 | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов; менеджер передаёт агентам реестр MCP, службы пайплайна, оркестрации, **индексации (шаг поиска по документам в `generate`)** и **клиент LLM со строителем промптов** |
| `models/` | 13 | ORM-таблицы SQLAlchemy по доменам, включая **`indexing.py`** (`document_chunks`, `index_runs`), **`llm_usage.py`**, `orchestration.py` |
| `schemas/` | 16 | Pydantic-схемы API по доменам, включая **`indexing.py`**, **`llm.py`**, **`rag.py`**, **`mini_chat.py`**, `orchestration.py` и `mcp_servers.py` |
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

Набор дня — **2721 тест**: `unit/` — 1885 (73 файла), `integration/` — 587
(54 файла), `e2e/` — 249 (16 файлов). Классификация по фикстурам: чистые модули /
временная БД и агент / `TestClient`. Унаследованные наборы дней 11–20 (память и
стратегии, профиль, задача и переходы, инварианты, MCP, планировщик, пайплайн, флот и
оркестрация) остаются на месте; их раскладка по файлам — в
[`day20/STRUCTURE.md`](../day20/STRUCTURE.md).

**Режимы прогона и скорость.** Тесты идут параллельно (`pytest-xdist`, `-n auto`)
и делят одну схему БД на прогон: session-scoped `schema_template` строит её один
раз, а `session_factory` копирует файл (2,65 мс вместо 934 мс у `create_all`) —
изоляция сохранена (файл на тест), время полного прогона упало с 370 с до 68 с.
Тяжёлые тесты (84 штуки: подпроцессы MCP-серверов по stdio, сборка реального
RAG-корпуса и часть e2e) помечены
`slow` и по умолчанию пропускаются: `uv run pytest` идёт ~17 с и покрывает 2637
тестов, полный набор — `uv run pytest -m ""` или `--run-slow` — ~45 с и 2721 тест. Autouse-фикстура
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
«индекс пуст»), `rag_usage_store`, `rag_stub`/`rag_client` (заглушка клиента DeepSeek),
`rag_reranker` (стаб-реранкер: балл — доля слов запроса в тексте фрагмента, без модели
и сети) и `rag_service` (служба RAG без пауз между попытками). Ленивая загрузка
настоящего кросс-энкодера запрещена так же, как для эмбеддера: autouse-фикстура
`isolated_indexing` подменяет `RerankService._load` функцией-ошибкой и обнуляет
модульный `_service` реранкера.

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
| Индекс и прогон | `integration/test_index_service.py` (202), `integration/test_indexing_service.py` (270), `integration/test_indexing_restart.py` (61) | `embedding_id == id`, порядок попаданий, `IndexNotBuiltError`, круговорот файла индекса, очистка, статистика; этапы прогона по FSM и счётчики, метрики и качество по запросам, одиночная стратегия без сравнения, пять кодов отказа, сбой эмбеддера в строке запуска, фоновый прогон; перезапуск без переиндексации |
| API | `e2e/test_indexing_api.py` (299) | Девять эндпоинтов `/indexing`: синхронный и фоновый прогон, прогресс, статистика, поиск (409 на пустом индексе, 400 на пустом запросе, 422 на `top_k` вне границ), примеры чанков, история, 404, очистка, поле `indexing` ответа генерации и правило «один ход — один автоматизм» |

### Оптимизация затрат на LLM

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Промпт и сжатие | `unit/test_prompt_builder.py` (314), `unit/test_prompt_compressor.py` (204) | Зоны промпта, попадание и промах кэша префикса по содержимому, guard `looks_dynamic` (метка времени и hex-id в префиксе — предупреждение, а не молчаливый промах), предел ответа по типу задачи; снятие комментариев, повторов и минификация JSON, идемпотентность, счётчики `stats`, неотрицательность снятых токенов |
| Домен стоимости и непик | `unit/test_llm_cost.py` (117), `unit/test_peak_hours.py` (161) | Цена запроса по тарифам, доля цены попадания в кэш, вклад каждого рычага, `core_saving` против `total_saving`; границы окон непика (будни 00–01, 04–06, 10–24 UTC, все выходные), `next_off_peak` строго позже момента, подпись окна и прогноз скидки |
| Хранилище журнала | `unit/test_llm_usage_rows.py` (127), `integration/test_llm_usage_store.py` (244) | Форма словаря строки журнала; запись строки запроса, свежие запросы первыми, периоды `day`/`week`/`month`/`all`, неизвестный период — ошибка, агрегаты (доля кэша, разбивка по моделям, типам и дням) |
| Клиент и агент | `integration/test_llm_client.py` (297), `integration/test_agent_cost.py` (162) | Выбор модели по типу задачи, предел ответа, извлечение `cache_hit`/`cache_miss` из ответа, запись в журнал, подмена фабрики клиента; ход агента через `LLMClient` и `PromptBuilder`, поле `llm` в ответе генерации |
| Планировщик и непик | `integration/test_scheduler_off_peak.py` (114) | Флаг `prefer_off_peak` переносит первый запуск в дешёвое окно, статус планировщика показывает `off_peak`/`next_off_peak`/`discount_percent`, задачи без флага не сдвигаются |
| API | `e2e/test_llm_api.py` (312) | Семь эндпоинтов `/llm`: журнал с раздельными `cache_hit`/`cache_miss`, состояние рычагов, прогноз, справка по моделям, правило окон, провайдер и демо локальной модели (три строки, токены, 502 при сбое Ollama); контракт ошибок (400 на неизвестный период, 422 на `off_peak_share` вне границ), поле `llm` ответа генерации |

### RAG-режим (дни 22–24)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки и фикстуры | `tests/rag_fakes.py` (212), `tests/fixtures_rag.py` (104) | Стаб-клиент DeepSeek (пишет вызовы, отвечает по сценарию `replies`, умеет падать первые N раз), стаб-реранкер (балл по словам запроса), два markdown-документа с редкими литералами; фикстуры тестового корпуса, службы поиска, реранкера и службы RAG без пауз (порог дня 24 в фикстуре опущен до 0, потому что заглушечные эмбеддинги дают нулевой косинус) |
| Домен отбора | `unit/test_rag_filter.py` (112) | Таблица четырёх режимов и родство режима с ручками (`RAG_MODE_KNOBS`), неизвестное имя режима, нормализация баллов кросс-энкодера (логистика вне 0…1, порядок сохраняется), текст пары для кросс-энкодера с усечением, `apply_rerank` (добавляет балл, сортирует, при рассинхроне — `ValueError`), `filter_hits` (`None` — тот же список, отсутствующий балл = 0.0), текст предупреждения о пустом результате |
| Домен цитат | `unit/test_rag_quotes.py` (109) | День 24: ответ с источниками и цитатами при рабочем пороге (полный набор полей цитаты, обрезка до 200 символов, уверенность 1.0 и подтверждённые цитаты); детерминированные выдержки (`quote_of`, `quotes_from_items`); режим «не знаю» при недостижимом пороге (нет источников и цитат, модель не вызывалась, `tokens` пуст) и режим `rag` при нулевом пороге; `is_weak` берёт максимум по фрагментам, а не первый; порядок резолва порога (переменная окружения → `.env` с кавычками и комментарием → значение по умолчанию, мусор и выход за границы); `verify_citations` (подстрока, пересечение слов, чужой ответ, пустой ответ); ответ без RAG не несёт ни цитат, ни уверенности |
| Реранкер | `unit/test_rerank_service.py` (167) | Ленивая загрузка под локом, `score` без текстов не грузит модель, порядок пар и `batch_size`, ошибка загрузки → `RerankError` с подсказкой про `RAG_RERANK_MODEL`, `reset`, синглтон; пакет `sentence_transformers` подменён заглушкой |
| Сервис RAG | `unit/test_rag_service.py` (397), `unit/test_rag_provider.py` (92) | Поиск `top_k` с метаданными восьми полей и порядком по score; гибридный балл и видимые `vector_score`/`lexical_score`; сборка промпта, бюджет контекста, опора на источники; `compare` зовёт оба режима; отвержение пустого вопроса, неизвестной стратегии и режима; отказ на пустом индексе; повтор сбойного вызова и откат на ответ без контекста |
| Режимы отбора | `unit/test_rag_modes.py` (194) | Режимы дня 23 на заглушке реранкера: три балла без реранка и связь `score` с `lexical_score`/`vector_score`; `rewrite` делает второй вызов модели и ищет по переформулировке, пустая переформулировка и сбой возвращают исходный вопрос; `rerank` сортирует по баллу кросс-энкодера, сбой реранкера не стоит ответа; `top_k_candidates` урезает пул; неизвестный режим отвергается; `compare_modes` собирает записи по режимам; `min_score`, срезавший все фрагменты, даёт режим «не знаю» (`test_min_score_dropping_all_fragments_gives_dont_know`) — ответа без источников больше нет |
| Полный цикл (slow) | `integration/test_rag_flow.py` (141), `integration/test_rag_quotes_flow.py` (112) | Сборка корпуса из 36 реальных источников и обоих индексов, минимумы страниц и чанков на стратегию; `rag_query` находит нужный фрагмент и отдаёт источники с восемью полями; реранк стабом переставляет кандидатов на реальном корпусе и порог оставляет хотя бы один фрагмент; день 24 — `run_demo` на десяти вопросах из `backend/data/demo_questions.json`: режимы, источники и цитаты у `rag`-строк, пустые источники и текст «не знаю» у `dont_know`-строк, сводка; при недостижимом пороге все десять строк становятся «не знаю» без единого вызова модели |
| API | `e2e/test_rag_api.py` (361) | Семь эндпоинтов `/rag` (плюс поле `provider`: 200 при `local`, 400 на незнакомое имя): запрос с RAG и без, конфигурация корпуса, режимы и эхо-поля отбора, `POST /rag/compare_modes`, `POST /rag/compare_providers`, `GET /rag/demo-questions` (десять вопросов), `POST /rag/demo-run` (все вопросы или один), коды 400 (пустой вопрос, неизвестная стратегия, неизвестный режим), 409 (пустой индекс), 422 (`min_score` вне 0…1, `top_k_candidates` вне 1…60), 502 (сбой клиента), `POST /rag/compare`; порог, срезавший все фрагменты, возвращает «не знаю» |

### Локальный RAG (день 28)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Провайдеры и прогон | `unit/test_rag_service_providers.py` (225) | Сборка клиента по провайдеру (`local` → `LocalLLMClient`, `deepseek` → `LLMClient` и кэш по имени), парный прогон одного вопроса двумя клиентами, строка `mode="error"` при сбое одного вызова, пустой список вопросов = десять контрольных, правило вердикта на семи парах записей и сводка из 15 полей; день 29 добавил проверки профиля (см. таблицу ниже) |
| Полный цикл (slow) | `integration/test_local_rag_flow.py` (104) | Реальный индекс дня 22 с диска, настоящая модель эмбеддингов и настоящая Ollama: ответ по корпусу с источниками, цитатами и временем, режим `dont_know` без вызова модели; пропускается, если Ollama или индекс недоступны |

### Оптимизация локальной LLM (день 29)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Домен настройки | `unit/test_local_tuning.py` (277) | Профили (значения `tuned` читаются из констант модуля, `baseline` совпадает с днём 26, `create` с моделью даёт ключ кэша и подпись, незнакомое имя — `ValueError`), правило «кто получил профиль» (`active`: только локальный провайдер и только при `tuned`; незнакомое значение — как день 26), приоритет явного профиля над окружением, разрешение окружения (файл `.env`, битые значения, нечисловые настройки) и вердикт строки по правилу дня 24 (шесть случаев параметризованно), сводка варианта (время — только по строкам режима `rag`), ранжирование пар (ранг, тайбрейк по времени) и пары «до/после» без baseline |
| Служба прогона | `unit/test_local_tuning_service.py` (138) | Прогон на заглушке: вариант на каждый профиль, по строке на вопрос, ресурсы после варианта, пары и «лучший»; профиль доходит до вызова (промпт, температура, предел ответа различаются у `baseline` и `tuned`); сбой заглушки — строка `error`, полный отказ — `LocalLLMError`; незнакомый профиль отсекается до первого вызова; пустой список вопросов — десять контрольных |
| Клиент и фабрика | `unit/test_local_llm_client.py` (226), `unit/test_llm_factory.py` (96) | Окно контекста уходит в `options` только при явном значении (без него — значение Ollama) и зажимается до единицы; `tokens_per_second` из `eval_duration`, запасной расчёт по времени запроса (часы подменены), `load_ms` из `load_duration`, нули без полей; профиль задаёт модель и `num_ctx` клиента, без профиля — модель конфига и окно по умолчанию |
| Сервис RAG с профилем | `unit/test_rag_service_providers.py` (225) | Профиль по умолчанию (`tuned`) даёт свой промпт, температуру и предел ответа в вызове локальной модели; `baseline` — промпт режима и значения по умолчанию; явный профиль важнее окружения; профиль уходит и в фабрику клиентов (модель и `num_ctx` берутся из него) |
| API | `e2e/test_llm_api.py` (399) | `POST /llm/tune`: вариант на профиль, строка на вопрос, окно контекста по профилям, поля строки и сводки, пары и «лучший», ресурсы и версия Ollama; 400 на незнакомый профиль, 502 при полном отказе модели; новые поля `GET /llm/provider` (`local_profile`, `profiles`, `profile_labels`, `local_num_ctx`, `local_temperature`, `local_chat_max_tokens`) — в том числе значения профиля `baseline` |

### Мини-чат (день 25)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки и фикстуры | `tests/mini_chat_fakes.py` (161), `tests/fixtures_mini_chat.py` (61) | Стаб-клиент с двумя ответами (текст ответа и JSON памяти, различаются по вопросу извлекателя), клиент с неразобранным JSON памяти, заглушка отбора (`FakeRetrieval`/`FakeRagService`: сильная и слабая выдача, запись вызовов); фикстуры службы на фейковом отборе — сильная, слабая (режим «не знаю») и сломанная (режим ошибки) |
| Сервис | `unit/test_mini_chat_service.py` (272) | Ответ с источниками и цитатами (восемь полей источника, `chunks_used`, расходы, отбор вызван без реранка); память задачи после реплики и JSON-строки рабочей памяти; история реплик и `limit`; порядок блоков промпта (RAG → память с напоминанием о цели → диалог); режим «не знаю» на слабой выдаче без вызова модели; режим ошибки после повторов; сохранение прежней памяти при неразобранном ответе извлекателя; неизвестная сессия и пустое сообщение; закрытие сессии (реплики удалены, повтор идемпотентен, история недоступна) и `make_mini_chat_client` без ключа; сессия переживает перезапуск службы; ленивые зависимости и синглтон |
| Полный цикл (slow) | `integration/test_mini_chat_flow.py` (111) | Сборка реального корпуса фейковым эмбеддером, прогон первого сценария целиком (14 реплик): непустые ответы, режимы `rag`/`dont_know`, не менее 80 % ответов с источниками, цель не потеряна, история и рабочая память на месте, закрытие удаляет все реплики |

## Что изменилось относительно дня 20

Новые модули дней 21–29 перечислены выше. Здесь — только правки **унаследованного** кода
(проверены сравнением с `day20/`; в скобках — было → стало строк); правки дня 26 в уже
изменённых файлах (`rag_llm`, `rag_service`, `mini_chat_service`, `frontend/*`, `mini_chat/*`)
описаны в таблице «Локальная LLM как второй провайдер», правки дня 28 (`rag_service.py`,
`api/rag.py`, `api/agents.py`, `schemas/__init__.py`, `frontend/rag_api.py`,
`frontend/chat_section.py`, `app.py`) — в таблице «Локальный RAG», а правки дня 29
(`local_llm_client.py`, `llm_factory.py`, `rag_llm.py`, `rag_service.py`,
`mini_chat_service.py`, `schemas/__init__.py`, `api/llm.py`, `api/agents.py`,
`domain/__init__.py`, `services/__init__.py`, `frontend/chat_section.py`, `app.py`,
`.env.example`) — в таблице «Оптимизация локальной LLM»:

| Модуль | Строк | Что изменилось |
|---|---|---|
| `backend/agents/agent.py` | 2284 (2094) | Два шага дня 21: поиск по индексу (`_empty_indexing_report`, свойство `indexing_service`, `apply_index_context`, поле `record["indexing"]`) и вызов модели через `LLMClient` + сборка промпта `PromptBuilder` со сжатием блоков (`_make_client` остаётся точкой подмены в тестах); реплика, занятая пайплайном или оркестрацией, поиск по индексу не делает |
| `backend/agents/agent_manager.py` | 110 (105) | Параметры `indexing_service` и `llm_client`/`prompt_builder` — службы передаются агентам |
| `backend/agents/manager_agents.py` | 257 (255) | Передача новых служб в обоих местах создания `Agent` |
| `backend/core/config.py` | 400 (291) | Два новых раздела дня 21: «Индексация документов и поиск» (каталоги, модель эмбеддингов, чанкинг, границы топ-k, длины полей) и «Оптимизация затрат на LLM» (`MODEL_PRICES`, `LLM_CACHE_INPUT_RATIO`, типы задач и маршрутизация `LLM_TASK_MODELS`, пределы ответа `LLM_TASK_MAX_TOKENS`, `OFF_PEAK_WEEKDAY_HOURS_UTC`/`PEAK_WEEKDAY_HOURS_UTC`); заголовок и описание API дня 24 — «ОБЯЗАТЕЛЬНЫЕ ИСТОЧНИКИ, ЦИТАТЫ И РЕЖИМ «НЕ ЗНАЮ»», счётчик `/rag/... (6)`, `API_VERSION = "17.0.0"`. День 26 отдал чтение `.env` (`ENV_FILE`, `read_env_value`, `resolve_api_key`) в `backend/core/env_file.py` и добавил раздел «Локальная LLM»: `LLM_PROVIDER_DEFAULT`, `LOCAL_LLM_MODEL_DEFAULT`, `LOCAL_LLM_URL_DEFAULT`, `LLM_PROVIDER`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_URL`, `LOCAL_LLM_TIMEOUT` (120 с) и `LOCAL_LLM_DEMO_MAX_TOKENS` — файл остался ровно на 400 строках |
| `backend/core/dependencies.py` | 221 (115) | `get_indexing_service`, `get_index_service`, `get_embedding_service`, `get_prompt_builder`, `get_llm_client`, `get_rag_service`, `get_rerank_service`, `get_mini_chat_service` |
| `backend/api/main.py` | 78 (66) | Подключены роутеры `indexing`, `llm`, `rag` и `mini_chat` и точки подмены служб индексации, клиента LLM, службы RAG, реранкера и мини-чата |
| `backend/api/__init__.py` | 73 (56) | Реэкспорт роутеров `indexing`, `llm`, `rag` и `mini_chat`; контракт ошибок дня (409 на пустой индекс, 400 на стратегию/запрос/документы, неизвестный период расходов, пустой вопрос RAG и неизвестный режим отбора, 422 на порог вне 0…1 и пул вне 1…60, 502 на сбой LLM-вызова RAG; у мини-чата — 404 на неизвестную сессию и 400 на пустое сообщение) |
| `backend/api/lifespan.py` | 88 (60) | Пятый и шестой шаги старта — `get_index_service().load_all()` и прогрев моделей демон-потоком `model-warmup` (эмбеддинги, затем реранкер); остановка пишет индексы (`save_all`) |
| `backend/api/agents.py` | 363 (314) | В инвентаре `GET /` — группы `indexing` (9), `llm` (8, включая `GET /llm/provider`, `POST /llm/local-demo` дня 26 и `POST /llm/tune` дня 29), `rag` (7, включая `POST /rag/compare_modes`, эндпоинты демо `GET /rag/demo-questions`/`POST /rag/demo-run` и `POST /rag/compare_providers` дня 28) и `mini_chat` (5) и имя приложения дня 24 |
| `backend/api/scheduler.py` | 361 (355) | Описание флага `prefer_off_peak` и полей `off_peak`/`next_off_peak`/`discount_percent` в ответе `GET /scheduler/status` |
| `backend/domain/__init__.py` | 399 (395) | Импорт модулей индексации, стоимости, непика, RAG и настройки локальной модели (`local_tuning`, `local_tuning_eval`) как модулей; исторические абзацы докстринга сжаты, чтобы файл остался в лимите |
| `backend/services/__init__.py` | 278 (165) | Реэкспорт чанкера, эмбеддингов, индекса, загрузчика документов, службы индексации и её кодов отказа, `LLMClient`/`get_llm_client`, `PromptCompressor`, `shift_to_off_peak`, `RagCorpusLoader`/`get_rag_corpus_loader`, `RAGService`/`get_rag_service`, ошибок RAG, модулей дня 23 (`rag_errors`, `rag_corpus_index`, `rag_llm`, `rag_records`, `rag_retrieval`, `rerank_service`), мини-чата (`mini_chat_service`, `mini_chat_memory`, `MiniChatService`, `MiniChatSessionError`, `get_mini_chat_service`, `make_mini_chat_client`, `MINI_CHAT_AGENT_ID`) и модулей дня 29 (`local_llm_resources`, `local_tuning_service`) |
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
| `backend/schemas/__init__.py` | 395 (269) | Реэкспорт схем индексации, расходов, RAG (включая `RagModeOut`/`RagModesIn`/`RagModesOut`, `RagQuoteOut`, схемы демо дня 24 и схемы сравнения провайдеров дня 28 `RagCompareProvidersIn`/`RagCompareProvidersOut`/`RagProviderRowOut`/`RagProviderSummaryOut`), мини-чата (восемь `MiniChat*`) и прогона профилей дня 29 (`LocalTune*`); докстринг сжат, чтобы удержать лимит |
| `backend/schemas/agent.py` | 362 (352) | Поля `indexing` и `llm` ответа генерации |
| `frontend/chat_section.py` | 400 (346) | Девятый раздел «📦 Индексация», десятый «💰 Расходы», одиннадцатый «🆚 RAG-сравнение», двенадцатый «🧪 RAG-демо», тринадцатый «🏠 Локальный RAG» (день 28) и четырнадцатый «⚙️ Оптимизация локальной LLM» (день 29); панель «🔍 RAG-запрос по корпусу» в конце ветки чата; строки `indexing_note` и сводка расходов в отчёте хода |
| `tests/conftest.py` | 279 (228) | Общие фикстуры (`schema_template`, `no_real_network`); фикстуры индексации, RAG (включая стаб-реранкер) и мини-чата вынесены в `fixtures_indexing.py`, `fixtures_rag.py` и `fixtures_mini_chat.py` и импортируются обратно |
| `app.py` | 93 (67) | Заголовок страницы и описание пятнадцати разделов дня 29 |
| `README.md`, `docs/architecture.md`, `docs/usage.md`, `docs/api.md` | 928, 1186, 795, 7000 | Документация дня описывает текущее состояние (дни 21–29): `README` — задание дня 29 (профили настройки локальной модели и кванты на вопросах корпуса), `architecture` — устройство подсистем, включая «Локальный RAG — день 28» и «Оптимизация локальной LLM — день 29», `usage` — инструкция (раздел 10 — локальный RAG, раздел 11 — оптимизация локальной LLM, раздел 12 — частые ошибки), `api` — восемь эндпоинтов `/llm` (включая `POST /llm/tune`) и семь `/rag`; отдельные отчёты дня — `docs/reports/local_rag_comparison.md` и `docs/reports/local_llm_optimization.md` |
| `pyproject.toml` | 30 (24) | Имя `day21` и описание дня; добавлены `sentence-transformers`, `faiss-cpu`, `numpy` |
| `.env.example` | 54 (15) | `DAY21_BACKEND_URL` вместо `DAY20_BACKEND_URL`, добавлены `DAY21_EMBEDDING_MODEL`, закомментированный `RAG_RERANK_MODEL`, порог дня 24 `RAG_RELEVANCE_THRESHOLD=0.6`, модель и адрес локальной LLM (день 26) и профиль её настройки (день 29: `LOCAL_LLM_PROFILE`, `LOCAL_LLM_TEMPERATURE`, `LOCAL_LLM_NUM_CTX`, `LOCAL_LLM_CHAT_MAX_TOKENS`) |
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
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL` | Адрес API DeepSeek (он же реэкспортируется для служб) |
| `backend/core/env_file.py` | `shared.deepseek_utils.read_key_from_env_file` | Общий парсер `.env`: дня 26 он вызывается из `config.read_key_from_env_file`, а не напрямую из служб |
| `backend/domain/llm_provider.py` | — (только `backend.core.config`) | Имена провайдеров и разбор значения по умолчанию |
| `backend/services/local_llm_client.py` | `shared.logging_utils.get_logger` | Логгер клиента Ollama (HTTP-сбой, пустой ответ) |
| `backend/services/rag_llm.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger` | Фабрика `make_rag_client` переехала сюда из `rag_service` в день 26 (предел строк) |
| `backend/core/prompt_builder.py` | `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Токены стабильного префикса и динамики, предупреждение о динамических данных в префиксе |
| `backend/services/prompt_compressor.py` | `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Снятые токены считаются тем же счётчиком, что и размер чанка |
| `backend/services/llm_client.py` | `shared.logging_utils.get_logger` | Лог запроса (модель, тип задачи, токены, попадание в кэш) |
| `backend/services/off_peak.py` | `shared.logging_utils.get_logger` | Лог переноса запуска в дешёвое окно |
| `backend/services/chunker.py` | `shared.token_counter.count_tokens` | Размер окна и размер чанка считаются tiktoken, а не оценкой «символы / 4»: «средний размер» в отчёте — измеренное число |
| `backend/domain/rag_mode.py` | `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Бюджет блока контекста считается тем же счётчиком, логи отбора фрагментов и оценки опоры |
| `backend/services/rag_corpus_loader.py` | `shared.logging_utils.get_logger` | Логи сборки корпуса RAG и проверки его состава |
| `backend/services/rag_service.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger`, `shared.token_counter.count_tokens` | Клиент DeepSeek (когда фабрику не подставило приложение), логи повторов и отката на ответ без RAG, счёт токенов контекста |
| `backend/services/mini_chat_service.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger`, `shared.token_counter.count_tokens` | Собственная фабрика клиента (`make_mini_chat_client`), логи, счёт токенов собранного контекста |
| `backend/services/mini_chat_memory.py` | `shared.logging_utils.get_logger` | Лог «память задачи не извлечена» (ответ модели не разобран или сбой вызова) |
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
| `GET /` — счётчик эндпоинтов | 114 записей / 96 путей | — | Инвентарь `endpoints` перечисляет эндпоинты по методу (114 записей, включая семь `/rag/*`, пять `/mini-chat/*` и восемь `/llm/*`), тогда как OpenAPI группирует их по пути — уникальных путей 96. Расхождение не ошибка, а разная форма счёта |
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

Из папки `day21` (исключён только `.venv`; вендорный `.agents/` виден, поэтому его превышения перечислены явно):

```powershell
python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Фактический вывод:

```
[('.agents\\skills\\developing-with-streamlit\\assets\\templates\\apps\\dashboard-companies\\streamlit_app.py', 416), ('.agents\\skills\\developing-with-streamlit\\assets\\templates\\apps\\dashboard-compute\\streamlit_app.py', 447), ('.agents\\skills\\developing-with-streamlit\\assets\\templates\\apps\\dashboard-metrics\\streamlit_app.py', 449), ('backend\\agents\\agent.py', 2284)]
```

Превышения — только у трёх шаблонов Streamlit внутри вендорного `.agents/skills/`
(код библиотеки, а не дня) и у давно известного `backend/agents/agent.py`
(2284 строки); код дня 29 в лимит укладывается.

`app.py` (93 ≤ 100) и `backend/api/main.py` (78 ≤ 80) в лимитах; день 29 оставил на
границе `frontend/chat_section.py`, `frontend/common.py` и `backend/core/config.py`
(по 400), а `backend/domain/__init__.py`, `backend/services/rag_service.py` и
`frontend/rag_section.py` (по 399) — на строку ниже; `backend/schemas/__init__.py`
(395) и `backend/services/mini_chat_service.py` (396) отодвинулись внутрь лимита.
Прежние выносы держат лимит и сейчас: чтение `.env` — в `backend/core/env_file.py`,
фабрика клиента DeepSeek — в `backend/services/rag_llm.py`, режимы отбора — в
`backend/domain/rag_filter.py`. Скрипт отчёта об оптимизации перестал быть превышением:
замер (`scripts/cost_optimization_measure.py`, 382) вынесен из рендера
(`scripts/cost_optimization_report.py`, 285).

День 29 удержал лимит тремя выносами: домен настройки разложен на
`backend/domain/local_tuning.py` (276 — профили и разрешение окружения) и
`backend/domain/local_tuning_eval.py` (195 — строка, сводка, вердикт пары, как
`rag_eval` отделён от `rag_mode` дня 24); общая точка дня «кэш клиентов по паре
провайдер плюс профиль» и «вызов с параметрами профиля» ушла в
`backend/services/rag_llm.py` (134), поэтому `backend/services/rag_service.py` (399) и
`backend/services/mini_chat_service.py` (396) не выросли за 400; рендер отчёта вынесен
из драйвера — `scripts/local_tuning_report.py` (392) и
`scripts/run_local_llm_optimization.py` (228). Самый длинный файл дня по-прежнему
`backend/services/rag_service.py` (399): день 29 добавил в него профиль
(`llm_client_for(provider, profile)`, `_profile` через домен, система и параметры
вызова из профиля), а запись режима «не знаю» живёт в
`backend/services/rag_records.py` (87). Дальше идут `frontend/rag_section.py` (399),
`frontend/chat_section.py` (400), `frontend/local_rag_section.py` (222),
`backend/domain/rag_mode.py` (310), `backend/domain/rag_quotes.py` (287),
`backend/domain/local_tuning.py` (276), `frontend/local_tuning_section.py` (260),
`backend/services/local_llm_client.py` (197),
`backend/domain/local_tuning_eval.py` (195), `backend/schemas/local_tuning.py` (186),
`backend/services/local_tuning_service.py` (140), `backend/services/rag_llm.py` (134),
`backend/services/local_llm_resources.py` (99).
Файлы дня 29 в тестах: `tests/unit/test_local_tuning.py` (277),
`tests/unit/test_local_tuning_service.py` (138), `tests/e2e/test_llm_api.py` (399),
`tests/unit/test_rag_service_providers.py` (225), `tests/unit/test_local_llm_client.py`
(226), `tests/unit/test_llm_factory.py` (96) — все в лимите.
`tests/unit/test_rag_service.py` после выноса режимов ушёл с 567 строк до 395 —
лимит держится и в тестах.
Каталог `.agents/` в выводе не случаен: в этой копии скиллы библиотек скопированы
(а не слинкованы), и три шаблона Streamlit внутри скилла `developing-with-streamlit`
длиннее 400 строк (416–449). Это код библиотеки, а не дня, поэтому при подсчёте кода
дня его исключают явно (`.agents` not in p.parts) — тогда превышение одно: `agent.py`.
