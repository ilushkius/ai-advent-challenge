# Структура дня 32

Карта модулей дня 32: что где лежит и за что отвечает. Правила структуры — в
[`../docs/project-rules.md`](../docs/project-rules.md) и
[`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

**Что такое день 32.** Проект дня 21 (копия дня 20 — агент DeepSeek с памятью, FSM,
инвариантами, профилем, MCP-клиентом и флотом серверов, планировщиком, пайплайном и
оркестрацией) плюс десять подсистем, добавленных днями 21–32:

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
   `prefer_off_peak` планировщика), роутер `/llm` (5 эндпоинтов дня 21; день 29 добавил
   в него `POST /llm/tune`, а день 30 — три эндпоинта удалённой LLM в
   `backend/api/remote_llm.py`, всего `/llm/*` — 11), вкладка «💰 Расходы»
   и отчёт `docs/reports/cost_optimization.md`.
3. **RAG-режим** — отдельный корпус документов `documents/rag_corpus/` (44 источника:
   документация проекта, включая документы репозитория, документация поддержки дня 33
   и исходники дня), загрузчик
   корпуса, гибридный отбор фрагментов (кандидаты FAISS плюс
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
8. **Удалённая LLM** (день 30) — третья точка ответа: та же Ollama, но развёрнутая в
   Google Colab (бесплатный GPU T4) и открытая наружу туннелем Cloudflare. Клиент
   `RemoteLLMClient` говорит с ней по OpenAI-формату (`/v1/chat/completions`,
   `/v1/models`), `llm_factory` принимает `provider="remote"`, раздел
   «🛰 Удалённая LLM» собирает демо из пяти шагов одной кнопкой
   (`GET /llm/remote-config`, `POST /llm/remote/check`, `POST /llm/remote/step`),
   скрипт `scripts/demo_remote_llm.py` повторяет прогон из консоли, отчёт —
   `docs/reports/remote_llm_service.md`.
9. **Ассистент разработчика** (день 31) — ответ на вопрос `/help` по двум источникам:
   документация проекта (фрагменты того же корпуса RAG) и состояние репозитория через
   **свой** MCP-сервер `mcp_servers/dev_server/` (шесть инструментов: ветка и коммит,
   diff, файлы каталога, дерево дня, а с дня 32 — diff PR и список файлов PR). Домен
   `dev_assistant` (типы вопросов, план
   инструментов, сборка контекста), служба `dev_assistant_service`, три эндпоинта
   `/dev-assistant/*`, раздел «🧑‍💻 Ассистент разработчика (Day 31)», скрипты
   `scripts/reindex_with_docs.py` (пересборка корпуса с документацией),
   `scripts/dev_mcp_probe.py` (проба инструмента) и `scripts/demo_dev_assistant.py`
   (пять вопросов и отчёт `docs/reports/dev_assistant_demo.md`).
10. **AI-ревью PR** (день 32) — пайплайн ревью изменений: diff из запроса, через
   MCP (`get_pr_diff`, `get_changed_files`) или из GitHub REST API по URL репозитория и
   номеру PR, RAG-контекст документации проекта и кода изменённых файлов, ответ модели по
   JSON-контракту и разбор в структуру (баги с файлом и строкой, архитектурные проблемы с
   рекомендацией, рекомендации, риски `P0`–`P3`). Домены `code_review` (контракт и разбор)
   и `code_review_report` (markdown комментария и секции отчёта), службы
   `code_review_service` (сшивка и клиент GitHub), `code_review_context` (поиск контекста)
   и `code_review_github` (поток GitHub-ревью), клиент REST API `github_client`, четыре
   эндпоинта `/review/*`, раздел интерфейса «🔎 AI-ревью кода (Day 32)» с вкладками
   «🗂 Локальный diff» и «🐙 GitHub PR», скрипты `scripts/run_local_pr_review.py`
   (локальный прогон двух ref-ов или файла diff-а), `scripts/run_github_pr_review.py`
   (URL и номер PR, публикация по `--post-comment`) и `scripts/gh_review_comment.py`
   (публикация комментария через `gh`), GitHub Action `.github/workflows/ai-review.yml` в
   корне репозитория, отчёты `docs/reports/code_review_demo.md` с двумя примерами и
   `docs/reports/github_pr_review.md` с ревью живого PR.
11. **Ассистент поддержки пользователей** (день 33) — мини-сервис поддержки: ответ на
   вопрос клиента по трём источникам — документация поддержки (FAQ, разборы симптомов
   и справочник API из того же корпуса RAG, `docs/support/*.md`), профиль клиента и его
   тикет из **своего** MCP-сервера `mcp_servers/support_server/` (пять инструментов
   над базой `backend/data/support_db.json`) и раздел продукта по словам вопроса. Домен
   `support` (области продукта и слова-маркеры, обрезка тикета, шапки контекста,
   сценарии демо и вердикт строки), служба `support_service` (контекст, вызовы MCP через
   один хелпер `_call`, панельные методы), пять эндпоинтов `/support/*`, раздел
   «🎧 Поддержка пользователей (Day 33)» с селекторами клиента и тикета из MCP, скрипты
   `scripts/reindex_with_support.py` (пересборка корпуса с документацией поддержки),
   `scripts/support_mcp_probe.py` (проба инструмента) и `scripts/demo_support.py` (пять
   сценариев и отчёт `docs/reports/support_demo.md`).

Унаследовано из дня 20 — одной строкой: **остальное дерево, включая `mcp_server/`,
`mcp_servers/` с `mcp_servers.json`, память, профиль, состояние задачи, инварианты,
планировщик, пайплайн и оркестрацию, — копия дня 20 без изменений**; карта этих
модулей построчно — в [`day20/STRUCTURE.md`](../day20/STRUCTURE.md). Ниже описано
только то, что дни 21–33 добавили или изменили.

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
├── app.py                    # точка входа Streamlit (100 строк, лимит 100): set_page_config + вызовы секций
├── AGENTS.md                 # правила дня и workflow нового дня (≤ 5 КБ): границы, документация, тесты, инструменты
├── WORKFLOW.md               # маршрут: сырое задание → ARCHITECT_PROMPT.md → исполнение в omp.sh → commit + tag
├── .omp/RULES.md             # sticky-правила (omp загружает их только из native-локаций: <ближайший непустой .omp/>)
├── .clineignore              # служебное и тяжёлое внутри дня (.venv, output, index, *.db) — вне контекста агента
├── documents/                # СОБРАННЫЕ документы (производные данные, в Git не попадают): 25 файлов + manifest.json;
│                             # rag_corpus/ — корпус RAG: 44 документа + manifest.json
├── index/                    # ИНДЕКСЫ FAISS: fixed.index, structural.index, rag_corpus_fixed.index,
│                             # rag_corpus_structural.index; index/models/ — кэш весов модели (не в Git)
├── mcp_servers.json          # КОНФИГУРАЦИЯ ФЛОТА (унаследована от дня 20): три сервера + кэш каталогов tools_cache
├── mcp_servers/              # три независимых MCP-сервера флота — унаследованы от дня 20 (по процессу на сервер, stdio)
│   ├── dev_server/           # ЧЕТВЁРТЫЙ сервер дня 31 (вне флота): config.py, schemas.py, tools.py, server.py —
│   │                         # git-контекст (ветка, коммит, diff), файлы каталога, дерево папки дня (день 31),
│   │                         # а с дня 32 — diff PR и список изменённых файлов (get_pr_diff, get_changed_files)
│   └── support_server/       # ПЯТЫЙ сервер дня 33 (вне флота): config.py, schemas.py, tools.py, server.py —
│                             # get_user, get_ticket, list_user_tickets, get_product_info и list_users над
│                             # базой backend/data/support_db.json (читается на каждый вызов)
├── mcp_server/               # собственный MCP-сервер дня — унаследован от дней 17–19 (11 модулей, девять инструментов, stdio)
├── frontend/                 # Streamlit UI по секциям (45 модулей, включая __init__.py)
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
│   ├── remote_llm_api.py     # HTTP-запросы раздела удалённой LLM (/llm/remote-config, /llm/remote/check, /llm/remote/step)
│   ├── remote_llm_section.py # раздел «🛰 Удалённая LLM»: поля URL и модели, слайдеры лимита и окна, кнопка демо, таблица
│   ├── dev_assistant_api.py  # HTTP-запросы ассистента разработчика (/dev-assistant/...)
│   ├── dev_assistant_section.py # раздел «🧑‍💻 Ассистент разработчика (Day 31)»: подсказки, диалог, источники, панели MCP и git
│   ├── code_review_api.py    # HTTP-запросы ревью (/review/pr, /review/github-pr и обе проверки готовности)
│   ├── code_review_section.py # раздел «🔎 AI-ревью кода (Day 32)»: провайдер, вкладки локального diff-а и GitHub PR,
│   │                          # таблицы находок, источники, публикация комментария, панели готовности службы и GitHub
│   ├── support_api.py        # HTTP-запросы поддержки (/support/ask, /support/users, тикеты клиента и один тикет)
│   ├── support_section.py    # раздел «🎧 Поддержка пользователей (Day 33)»: селекторы клиента и тикета из MCP,
│   │                          # карточка контекста над вопросом, диалог с четырьмя раскрывашками и панель сервера
│   └── …                     # остальные секции унаследованы от дня 20
├── mini_chat/                # ОТДЕЛЬНОЕ приложение дня 25 (Streamlit, порт 8502): app.py — точка входа
│                             # (root дня в sys.path + панели), api.py — HTTP-запросы /mini-chat/... поверх
│                             # frontend.api_client, panels.py — боковая панель и ход диалога
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным (девять слоёв, в каждом __init__.py)
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # 22 модуля: 19 роутеров по доменам (в том числе indexing.py, llm.py,
│   │                         # remote_llm.py, rag.py, mini_chat.py, dev_assistant.py, code_review.py
│   │                         # и support.py),
│   │                         # main.py, lifespan.py
│   ├── core/                 # 7 модулей: config (сборка настроек и разделы оптимизации затрат),
│   │                         # llm_settings (провайдеры ответа: DeepSeek, локальная Ollama дня 26
│   │                         # и удалённая дня 30), env_file (путь .env дня и парсер его строк),
│   │                         # dependencies, mcp_server_config
│   │                         # и prompt_builder (строитель промптов с кэшем префикса)
│   ├── domain/               # 65 модулей: чистые правила и данные — индексация (chunking, document_sources,
│   │                         # index_metrics, index_scenarios, indexing_fsm, indexing_prompt), стоимость и непик
│   │                         # (llm_cost, peak_hours), RAG (rag_mode, rag_filter, rag_corpus_spec, rag_eval,
│   │                         # rag_compare), провайдер LLM (llm_provider), оптимизация локальной модели
│   │                         # (local_tuning, local_tuning_eval), сценарий демо удалённой LLM (remote_demo),
│   │                         # контракт ассистента разработчика (dev_assistant), контракт AI-ревью
│   │                         # (code_review) и разметка его отчёта (code_review_report), контракт поддержки
│   │                         # (support) и унаследованные домены
│   ├── services/             # 56 модулей: индексация (chunker, embedding_service, index_service, document_loader,
│   │                         # index_runner, index_comparison, indexing_service), затраты (llm_client,
│   │                         # prompt_compressor, off_peak), RAG (rag_corpus_loader, rag_service, rag_retrieval,
│   │                         # rag_records, rag_llm, rag_errors, rag_corpus_index, rerank_service, rag_compare_service), мини-чат
│   │                         # (mini_chat_service, mini_chat_memory), провайдер (llm_factory, local_llm_client,
│   │                         # local_llm_demo, remote_llm_client, remote_llm_service), ассистент разработчика
│   │                         # (dev_assistant_service), AI-ревью PR (code_review_service, code_review_context,
│   │                         # code_review_github, github_client), поддержка (support_service) и оптимизация
│   │                         # локальной модели (local_llm_resources, local_tuning_service) плюс унаследованные
│   ├── storage/              # 17 модулей: chunk_store и index_run_store (журнал прогонов индексации),
│   │                         # llm_usage_store и llm_usage_rows (журнал расходов) плюс унаследованные хранилища
│   ├── agents/               # Agent (в generate — шаг поиска по индексу, клиент LLM и строитель промптов),
│   │                         # MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы: 13 модулей, в том числе indexing.py (document_chunks, index_runs)
│   │                         # и llm_usage.py (журнал расходов)
│   ├── schemas/              # Pydantic-схемы API: 22 модуля, в том числе indexing.py, llm.py, remote_llm.py, rag.py, rag_compare.py, mini_chat.py, dev_assistant.py, code_review.py, support.py и local_tuning.py
│   ├── data/                 # данные дня: demo_questions.json (10 контрольных вопросов RAG),
│   │                         # mini_chat_scenarios.json (два сценария мини-чата: 14 и 12 реплик)
│   │                         # и support_db.json (день 33: 5 клиентов, 10 тикетов, 5 разделов продукта)
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 2807 тестов (unit/ — 1962, integration/ — 596, e2e/ — 249); по умолчанию 2714 (93 slow отложено)
│   ├── conftest.py           # общие фикстуры (session-scoped schema_template для схемы БД) + autouse no_real_network
│   ├── fixtures_fleet.py     # фикстуры флота MCP-серверов и оркестрации (вынесены из conftest: лимит 400 строк)
│   ├── fixtures_indexing.py  # фикстуры индексации документов (тоже вынесены из conftest)
│   ├── indexing_fakes.py     # фейки индексации: эмбеддер на хешах слов и три тестовых документа
│   ├── fixtures_rag.py       # фикстуры RAG: тестовый корпус, служба поиска, стаб-клиент и служба RAG
│   ├── rag_fakes.py          # фейки RAG: стаб-клиент DeepSeek и тексты тестового корпуса
│   ├── dev_assistant_fakes.py # фейки дня 31: служба поиска, MCP-клиент, подмена MCPClient и make_service
│   ├── code_review_fakes.py  # фейки дня 32: diff трёх файлов, попадания документации и кода, индекс без фрагментов,
│   │                         # MCP-клиент с diff-ом по имени инструмента, пять кейсов ревью и make_service
│   ├── support_fakes.py      # фейки дня 33: профиль, тикет и раздел продукта, попадания документации поддержки,
│   │                         # MCP-клиент с «записью не найдена», подмена MCPClient и make_service
│   ├── mini_chat_fakes.py    # фейки мини-чата: стаб-клиент с двумя ответами (ответ и JSON памяти),
│   │                         # заглушка отбора (сильная/слабая выдача) и клиент с неразобранной памятью
│   ├── fixtures_mini_chat.py # фикстуры мини-чата: служба на фейковом отборе — сильная, слабая и сломанная
│   ├── unit/test_rag_service_providers.py      # unit дня 28–29: сборка клиента по провайдеру, парный прогон, строка-ошибка, вердикт, сводка, профиль настройки в вызове
│   ├── unit/test_local_tuning.py               # unit дня 29: профили и разрешение окружения, вердикты строки, сводка варианта и ранжирование
│   ├── unit/test_local_tuning_service.py       # unit дня 29: прогон на заглушке — параметры доходят до вызова, строка-ошибка, отказ Ollama, незнакомый профиль
│   ├── integration/test_local_rag_flow.py      # slow дня 28: реальный индекс дня 22, настоящая модель эмбеддингов и настоящая Ollama
│   ├── unit/test_remote_llm_client.py          # unit дня 30: OpenAI-формат запроса, счётчик частоты и его окно, GET /models вне лимита, понятные ошибки
│   ├── integration/test_remote_llm_flow.py     # slow + remote дня 30: полный цикл пяти шагов по настоящему адресу туннеля (без адреса — skip; маркер remote снимает autouse-запрет сети)
│   ├── unit/test_dev_assistant_service.py      # unit дня 31: тип вопроса и план инструментов, контекст двух источников, отказы (индекс, сервер, инструмент, модель), пустой вопрос
│   ├── unit/test_dev_assistant_panels.py       # unit дня 31: каталог инструментов, git-контекст, соединение со stdio-сервером и его закрытие, клиент по ключу, синглтон
│   ├── integration/test_dev_assistant_flow.py  # slow дня 31: настоящий корпус и настоящий процесс mcp_servers/dev_server/server.py, заглушка модели
│   ├── unit/test_code_review_service.py        # unit дня 32: пять кейсов структуры ревью (payload, MCP, отказ MCP, отказ модели, пустой индекс),
│   │                                           # отказ «нечего анализировать», запрос по пути файла, порядок приоритетов P0–P3
│   │                                           # и режим GitHub: github_meta, публикация комментария и её отказ предупреждением
│   ├── unit/test_code_review_report.py         # unit дня 32: разделы markdown, обрезка полного ответа, замена секции отчёта без дублей и блок «GitHub PR»
│   ├── unit/test_github_client.py              # unit дня 32: клиент REST API на httpx.MockTransport — три формы URL, заголовки Accept/Authorization,
│   │                                           # коды 401/403/404/422, отличие rate limit, публикация отзыва, health и маска токена
│   ├── integration/test_code_review_flow.py    # slow дня 32: настоящий git diff day30..day31 через dev_server, обрезка до 2000 строк, документация в источниках
│   ├── integration/test_github_pr_flow.py      # slow + github дня 32: живой GitHub API по токену (без GITHUB_TOKEN — skip)
│   ├── unit/test_support_service.py            # unit дня 33: контекст трёх источников (профиль, тикет, раздел продукта), предупреждения и записи
│   │                                           # инструментов, отказ MCP и ненайденный тикет, панельные методы, соединение со stdio-сервером
│   ├── integration/test_support_flow.py        # slow дня 33: настоящий корпус, настоящий процесс mcp_servers/support_server и рабочая база клиентов
│   └── …                     # унаследованные помощники тестов дня 20 (orchestration_fakes, mcp_fakes, stub_api, support…)
├── docs/                     # architecture.md, usage.md, api.md, reports/ (включая code_review_demo.md дня 32,
│                             # github_pr_review.md — ревью живого PR — support_demo.md дня 33
│                             # и вход синтетического примера reports/synthetic_pr.diff),
│                             # support/ (faq.md, troubleshooting.md, api_reference.md — документация поддержки)
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
│   ├── demo_remote_llm.py    # прогон пяти шагов удалённой LLM из консоли (--url, --rate-limit, --max-context) и запись отчёта дня 30
│   ├── reindex_with_docs.py  # пересборка корпуса RAG дня 31: чанки документации по стратегиям, минимум 30 на стратегию, общий объём
│   ├── dev_mcp_probe.py      # проба одного инструмента mcp_servers/dev_server по stdio (--tool, --args, --target) без модели
│   ├── demo_dev_assistant.py # пять вопросов /help через DevAssistantService (--provider, --report, --no-report) и отчёт дня 31
│   ├── run_local_pr_review.py # локальное ревью дня 32: git diff двух ref-ов или --diff-file, вызов службы, печать находок и секция отчёта
│   ├── run_github_pr_review.py # ревью реального PR дня 32: URL и номер (--repo-url, --pr-number), --post-comment, печать находок и отчёт с блоком GitHub PR
│   ├── gh_review_comment.py  # публикация ответа POST /review/pr комментарием в PR через gh (--pr, --repo, --input, --dry-run)
│   ├── reindex_with_support.py # пересборка корпуса RAG дня 33: чанки документации поддержки по стратегиям, минимум 20 на стратегию
│   ├── support_mcp_probe.py  # проба одного инструмента mcp_servers/support_server по stdio (--tool, --args, --target) без модели
│   ├── demo_support.py       # пять сценариев клиента через SupportService (--provider, --report, --no-report) и отчёт дня 33
│   └── …                     # унаследованные скрипты дней 18–20 (orchestration_*, pipeline_*, scheduler_*, video_*)
├── invariants_demo.md        # отчёт дня 14 (унаследован; лежит в корне дня — путь задан заданием дня 14)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── pyproject.toml, uv.lock   # зависимости (uv): sentence-transformers, faiss-cpu, numpy, mcp, sqlalchemy…; версии — в локе
├── .agents/skills/           # скиллы: вендорные библиотек (uvx library-skills --copy) и проектный check_docs (проверка документации перед коммитом); не код дня
├── .python-version           # 3.14
├── .env.example              # шаблон DEEPSEEK_API_KEY, GITHUB_TOKEN, DAY21_BACKEND_URL, DAY21_EMBEDDING_MODEL,
│                             # LLM_PROVIDER, LOCAL_LLM_MODEL, LOCAL_LLM_URL и профиля настройки
│                             # локальной модели (LOCAL_LLM_PROFILE, LOCAL_LLM_TEMPERATURE,
│                             # LOCAL_LLM_NUM_CTX, LOCAL_LLM_CHAT_MAX_TOKENS), REMOTE_LLM_URL,
│                             # REMOTE_LLM_MODEL, REMOTE_LLM_API_KEY, REMOTE_LLM_RATE_LIMIT,
│                             # REMOTE_LLM_MAX_CONTEXT
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
`remote_llm_service.md` — удалённая Ollama в Colab за туннелем Cloudflare: пять шагов
демо, лимит частоты и окно контекста (день 30),
`code_review_demo.md` — два примера AI-ревью (реальный diff `day30..day31` и
синтетический PR из `reports/synthetic_pr.diff`, день 32),
`github_pr_review.md` — два ревью из GitHub REST API (чужой
`fastapi/fastapi#16481`: 4 файла, 222 строки diff-а — анонимное чтение, публикации не
было; свой `ilushkius/go-url-shortener#7`: 8 файлов, 524 строки diff-а — комментарий
опубликован, `pullrequestreview-5508238833`) с блоком «GitHub PR» у каждого (день 32),
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

## Новые модули дней 21–33

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
| `backend/domain/rag_corpus_spec.py` | Состав корпуса: `RAG_CORPUS_SOURCES` (44 источника: документация проекта вместе с документами репозитория, документация поддержки дня 33 (`docs/support/*.md`) и исходники дня; день 31 добавил `docs/api.md`, корневые `README.md`/`AGENTS.md`/`WORKFLOW.md`/`ARCHITECT_PROMPT.md` и расширил окно README дня до 30 000, а окно `backend/api/lifespan.py` — до 5 200 символов, иначе правка дня вытеснила бы из окна факт `model-warmup`), `RAG_CORPUS_SUBDIR = "rag_corpus"`, минимумы `RAG_CORPUS_MIN_PAGES = 25`/`RAG_CORPUS_MIN_CHUNKS = 50`, `corpus_pages`, `validate_sources` (пропавший файл или суффикс вне `DOCUMENT_SUFFIXES` — проблема) |
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

### Удалённая LLM (день 30): `backend/core/`, `backend/`, `frontend/`, `scripts/`, `tests/`

| Модуль | Назначение |
|---|---|
| `backend/core/llm_settings.py` | Настройки провайдеров ответа, вынесенные из `config.py` (тот упёрся в лимит 400 строк): константы дня 26 (`LLM_PROVIDER`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_URL`, `LOCAL_LLM_TIMEOUT = 120.0`, `LOCAL_LLM_DEMO_MAX_TOKENS`) и дня 30 (`REMOTE_LLM_URL` — по умолчанию пустой, `REMOTE_LLM_MODEL = "qwen2.5-coder:7b"`, `REMOTE_LLM_API_KEY = "ollama"`, `REMOTE_LLM_RATE_LIMIT = 10`, `REMOTE_LLM_MAX_CONTEXT = 4096`, границы слайдеров `1…30` и `1024…8192`, `REMOTE_LLM_RATE_WINDOW_SECONDS = 60.0`, `REMOTE_LLM_TIMEOUT = 120.0`, `REMOTE_LLM_DEMO_MAX_TOKENS`, `REMOTE_LLM_CONNECT_MAX_TOKENS = 8`); чтение как раньше — `_env`/`_int_env` (процесс → `.env` дня → значение по умолчанию, битое число → дефолт); `config.py` нижним блоком импорта отдаёт эти имена наружу, поэтому старые обращения не меняются |
| `backend/domain/llm_provider.py` | `PROVIDER_REMOTE = "remote"` и `PROVIDERS` из трёх провайдеров плюс отдельный `PICKER_PROVIDERS` (`deepseek`, `local`) для радиокнопок чата и мини-чата: удалённого в общем переключателе нет, потому что адрес туннеля живёт часами |
| `backend/services/remote_llm_client.py` | `RemoteSettings` (адрес, модель, ключ, лимит, окно контекста, таймаут; `from_config` и `from_values` — значения из UI, пустые подменяются конфигом) и `RemoteLLMClient`: `POST {base_url}/chat/completions` в формате OpenAI (`messages`, `stream=false`, `temperature`, `top_p = 0.9`, `max_tokens`) с расширением Ollama `options.num_ctx`; `GET /models` для проверки соединения (в лимит не входит); счётчик частоты `deque` за окно 60 с и `RateLimitExceeded` (семантика 429, несёт `limit` и `window_seconds`); методы `generate`, `generate_with_context`, `rate_limit_state`, `reset_rate_limit`; результат — та же форма, что у клиента дня 26 (`provider: "remote"`, `duration_ms`, блок `tokens`); ошибки — `RemoteLLMError` с подсказкой про ячейку Colab и туннель |
| `backend/services/llm_factory.py` | Третья ветка выбора клиента: `provider="remote"` отдаёт `RemoteLLMClient` (переданные из раздела `RemoteSettings` или собранные из конфига); профиль дня 29 к удалённому провайдеру не применяется |
| `backend/domain/remote_demo.py` | Сценарий демо данными: `STEP_KEYS`/`KIND_*`, пять шагов (`connection`, `fact`, `logic`, `code`, `rate_limit`) с заголовками и вопросами, `rate_limit_steps(limit)` — сколько запросов слать в шаге частоты |
| `backend/services/remote_llm_service.py` | Служба раздела: реестр клиентов по ключу настроек и `run_id` (счётчик частоты переживает отдельные HTTP-запросы шагов), `run_step` для одного шага, `check_connection`, сборка строки, сводки (`calls`, `errors`, `blocked`, `avg_ms`, подтверждение `remote_confirmed`) и `reset_client_cache()` для тестов; шаг частоты начинает окно заново (`reset_rate_limit`), иначе отказ пришёлся бы на запрос N−2 |
| `backend/schemas/remote_llm.py` | Схемы `GET /llm/remote-config`, `POST /llm/remote/check`, `POST /llm/remote/step`: настройки с границами слайдеров, список шагов, проверка соединения, строка таблицы и сводка. Отдельный модуль, потому что `backend/schemas/__init__.py` на пределе строк |
| `backend/api/remote_llm.py` | Три эндпоинта: `GET /llm/remote-config` (настройки раздела и шаги), `POST /llm/remote/check` (`GET {base_url}/models`, 400 при пустом адресе), `POST /llm/remote/step` (400 — незнакомый шаг, 502 — сбой вызова); подключён в `backend/api/main.py` |
| `frontend/remote_llm_section.py`, `remote_llm_api.py`, `chat_section.py` | Раздел «🛰 Удалённая LLM»: поля Base URL (из конфига) и модели, кнопки «Проверить соединение» (зелёный/красный индикатор, список моделей) и «🚀 Прогнать демо одной кнопкой», слайдеры «Rate limit (запросов в минуту)» и «Max context (токенов)» с предупреждением при лимите меньше 3, прогресс-бар по шагам, таблица (шаг, запрос, ответ до 200 символов, время, провайдер, статус), метрики и подтверждение провайдера `remote`, кнопка «Открыть Open WebUI» |
| `scripts/demo_remote_llm.py` | Тот же прогон из консоли: `--url`, `--model`, `--api-key`, `--rate-limit`, `--max-context`, `--report`/`--no-report`; печатает таблицу шагов и метрики и записывает `docs/reports/remote_llm_service.md`; прогон по локальному адресу помечается в отчёте предупреждением, что удалённость сервиса он не проверяет |
| `tests/unit/test_remote_llm_client.py`, `tests/integration/test_remote_llm_flow.py` | Unit: формат запроса (адрес, заголовок, `num_ctx`, `max_tokens` по типу задачи), окно счётчика частоты и отказ на N+1, `GET /models` вне лимита, понятные тексты ошибок. Slow-интеграция: полный цикл пяти шагов по настоящему адресу туннеля, без адреса — `skip` |

Демо смотрит наружу, но остаётся обычным поставщиком ответа: клиент подчиняется тем же
правилам, что локальный (форма результата, `generate_with_context` для RAG), поэтому
удалённую модель можно поставить третьим вариантом в сравнении провайдеров. Предел
частоты считает **клиент**, а не сервис: Ollama в Colab никакого лимита не знает, и
раздел дня 30 показывает, что программа умеет держать бюджет запросов, а не что лимит
есть у сервиса.

### Ассистент разработчика (день 31): `backend/`, `mcp_servers/dev_server/`, `frontend/`, `scripts/`, `tests/`

| Модуль | Назначение |
|---|---|
| `backend/domain/dev_assistant.py` | Контракт ассистента: `AGENT_ID`, `DEV_SERVER_TARGET`, типы вопросов (`KIND_DOCS`/`KIND_GIT`/`KIND_MIXED` и подписи), имена инструментов, умолчания (`DEFAULT_TOP_K`, `DEFAULT_TREE_DEPTH`, `DEFAULT_DIFF_LINES`, `DEFAULT_FILE_DIRECTORY`), `DOCUMENTATION_SOURCES`/`DOCUMENTATION_SLUGS`/`DOCUMENTATION_MIN_CHUNKS = 30`, `DEMO_QUESTIONS`, таблицы слов (`GIT_WORDS`, `DOCS_WORDS`, `STRUCTURE_WORDS`, `DIFF_WORDS`, `FILE_LIST_WORDS`), тексты промпта, шапок контекста и предупреждений, функции `normalize_question` (снимает «/help»), `classify_question`, `plan_tools`, `render_context`, `verdict` — без HTTP, диска и модели |
| `backend/services/dev_assistant_service.py` | Служба: поиск фрагментов документации (`IndexService.search` стратегией дня 22), вызовы инструментов по плану (соединение с dev-сервером поднимается один раз и закрывается `close()`), сборка контекста, ответ через `rag_llm.answer`, `tools()` и `git_context()` для панелей, отказы данными (`warnings`) и `DevAssistantMCPError` при недоступном сервере |
| `backend/schemas/dev_assistant.py`, `backend/api/dev_assistant.py` | Схемы и три эндпоинта: `POST /dev-assistant/help` (400 — пустой вопрос или незнакомый провайдер, 502 — контекста нет вовсе), `GET /dev-assistant/tools`, `GET /dev-assistant/git-context` (оба всегда 200, причина в поле `error`) |
| `backend/core/dependencies.py`, `backend/api/main.py`, `backend/api/lifespan.py` | Точка подмены `get_dev_assistant_service` (роутер берёт службу через `dependencies`), роутер в цикле регистрации, закрытие соединения с dev-сервером при остановке бэкенда |
| `mcp_servers/dev_server/config.py` | Корни (`REPO_ROOT` для git, `DAY_ROOT` для дерева), имя/версия/инструкция сервера, границы (`MAX_FILES`, `MAX_MODIFIED`, `MAX_TREE_FILES`, `MIN_DEPTH`/`MAX_DEPTH`, `MIN_DIFF_LINES`/`MAX_DIFF_LINES`, `GIT_TIMEOUT`), `SKIP_DIRS` |
| `mcp_servers/dev_server/schemas.py` | `TypedDict`-ответы (`GitBranchInfo`, `FileList`, `ChangedFiles`) → `outputSchema` инструментов; форма дерева описана докстрингом (`dict`), а `get_pr_diff` возвращает строку — рекурсивный `TypedDict` дал бы перекрёстную ссылку в схеме |
| `mcp_servers/dev_server/tools.py` | Шесть инструментов: `get_git_branch` (`rev-parse`/`log -1 --oneline`/`status --porcelain`, у переименования — новый путь), `list_files` (нерекурсивно, путь обязан лежать внутри `REPO_ROOT`, фильтр расширения без учёта регистра и точки), `get_git_diff` (последние N строк `git diff HEAD`), `get_project_structure` (дерево папки дня, каталоги первыми, счётчики) и добавленные днём 32 `get_pr_diff`/`get_changed_files` (diff двух ref-ов и имена изменённых файлов; ref проверяется образцом `REF_PATTERN` до вызова git, иначе аргумент стал бы опцией команды). Всё через `subprocess` с таймаутом; сбой git и выход за границы — `ToolError` |
| `mcp_servers/dev_server/server.py` | Сборка `MCPServer` (`mcp.server.mcpserver`, mcp 2.x) и регистрация шести функций `tools.py` (внешняя регистрация: SDK берёт имя, докстринг и аннотации из самой функции), запуск `run(transport="stdio")` |
| `frontend/dev_assistant_section.py`, `dev_assistant_api.py`, `chat_section.py` | Раздел «🧑‍💻 Ассистент разработчика (Day 31)»: кнопки-подсказки (подставляют вопрос и сразу отправляют), переключатель провайдера, диалог с раскрывашками «📚 Источники» и «🛠 MCP-инструменты», панель процесса (каталог инструментов с обновлением, ветка и коммит, очистка диалога); HTTP-обёртки `api_dev_help` (`LONG_TIMEOUT`), `api_dev_tools`, `api_dev_git_context` |
| `scripts/reindex_with_docs.py` | Пересборка корпуса с документацией: `RAGService.prepare_corpus` плюс отдельный счётчик чанков документации по стратегиям (код 0 только при минимуме 30 чанков на стратегию и общем минимуме корпуса) |
| `scripts/dev_mcp_probe.py` | Проба инструмента по stdio без модели: `--tool`, `--args` (JSON), `--target`; печатает каталог и структурированный результат, коды 0/1/2 |
| `scripts/demo_dev_assistant.py` | Пять вопросов демо через ту же службу: `--provider`, `--report`/`--no-report`, печать источников и инструментов по строке, отчёт `docs/reports/dev_assistant_demo.md` (контекст запуска, таблица, полные ответы); код 2 — пустой индекс или недоступная модель |
| `tests/dev_assistant_fakes.py`, `tests/unit/test_dev_assistant_service.py`, `test_dev_assistant_panels.py`, `tests/integration/test_dev_assistant_flow.py` | Фейки (индекс, MCP-клиент, подмена `MCPClient` со счётчиком созданных клиентов) вынесены отдельным модулем: два тестовых файла и предел 400 строк. Unit: классификация (обязательный сценарий «git против документации»), контекст документации с проверкой промпта, git-вопрос, смешанный вопрос, ошибка инструмента, недоступный сервер и модель, пустой индекс, «нет данных» без вызова модели, пустой вопрос; панели — каталог, git-контекст, соединение (создаётся один раз, закрывается, рабочий каталог дня), клиент по ключу, синглтон. Slow-интеграция: настоящий корпус (все источники таблицы) и настоящий процесс `dev_server` |

Ассистент не заводит ни одной новой таблицы и не меняет флот: он читает те же индекс и
`document_chunks`, что день 22, и поднимает свой сервер отдельным процессом. Поэтому
«недоступный dev-сервер» — штатный случай: ответ строится по документации, а причина
видна в предупреждениях и в панели раздела.

### AI-ревью PR (день 32): `backend/`, `mcp_servers/dev_server/`, `scripts/`, `tests/`, `.github/`

| Модуль | Назначение |
|---|---|
| `backend/domain/code_review.py` | Контракт ревью без HTTP, диска и модели: `SYSTEM_PROMPT` с JSON-схемой и границами находок (не больше 3 багов, 2 архитектурных проблем, 2 рекомендаций, 3 рисков — ответ идёт типом задачи `chat` с пределом 1000 токенов), `normalize_priority` (`"p0"`/`2`/`"P1 (важно)"` → `P0`–`P3`), `sort_risks`, `changed_files_from_diff`, `added_lines`, `context_query` (пути плюс добавленные строки), `truncate_diff` (предел 2000 строк и список пропущенных файлов), `strip_json_fence`/`normalize_review` (терпимый разбор: строка вместо объекта, `message` вместо `issue`, текст без JSON), `review_question`, `render_context`, тексты предупреждений |
| `backend/domain/code_review_report.py` | Разметка: `render_markdown` (разделы комментария PR и секции отчёта — изменённые файлы, таблицы багов и рисков, рекомендации, источники, предупреждения, полный ответ модели под `<details>`), `render_github_meta` (блок «GitHub PR»: ссылка, число файлов и строк diff-а, признак публикации; у локального ревью возвращает пустую строку), `github_report_header`, `report_header`, `upsert_report_section` с маркером `SECTION_MARKER` и своим заголовком (граница секции — невидимый `<!-- section: … -->`, а не заголовок: тело ревью само начинается с `## 🤖 AI-ревью`) |
| `backend/services/code_review_service.py` | Служба: diff из payload, через MCP `get_pr_diff` или из GitHub REST API, файлы из payload/MCP/самого diff-а, обрезка diff-а, вызов модели, разбор ответа, `mcp_tools_used`/`sources`/`warnings`, ленивый клиент GitHub (`review_github_pr`, `github_health`), `health()`, синглтон `get_code_review_service` и закрытие своих соединений |
| `backend/services/code_review_context.py` | Поиск контекста, вынесенный из службы на пределе 400 строк: фрагменты документации проекта одним запросом и код изменённых файлов по одному запросу на файл (второй запрос — по пути, когда добавленные строки увели выдачу); отказы данными, а не исключениями |
| `backend/services/code_review_github.py` | Поток GitHub-ревью: URL и номер PR → `get_repo`/`get_pr`/`get_pr_diff`/`get_changed_files`, запись `github_meta`, публикация комментария по флагу; отказ публикации — предупреждение и `posted=false` |
| `backend/services/github_client.py` | Клиент GitHub REST API: разбор URL (https, `.git`, scp-форма), чтения PR с заголовком `Accept: application/vnd.github.v3.diff`, `post_review_comment` (событие `COMMENT`), `health()` по `/rate_limit`, тексты ошибок 401/403/404/422, отличие исчерпанного rate limit, маска токена (в лог и health токен целиком не попадает) |
| `backend/schemas/code_review.py`, `backend/api/code_review.py` | Схемы (`PrReviewIn`, `PrReviewOut`, `CodeReviewHealthOut` и вложенные, плюс `GitHubPrReviewIn`, `GitHubPrReviewOut`, `GitHubMetaOut`, `GitHubRateLimitOut`, `GitHubHealthOut`) и четыре эндпоинта: `POST /review/pr` (400 — нечего анализировать или незнакомый провайдер, 502 — MCP не поднялся и diff не добыть), `GET /review/health`, `POST /review/github-pr` (`GitHubError` → 400, а не 502) и `GET /review/github-health` (всегда 200) |
| `backend/core/dependencies.py`, `backend/api/main.py`, `backend/api/__init__.py`, `backend/services/__init__.py`, `backend/api/lifespan.py`, `backend/api/agents.py` | Прошивка: точка подмены `get_code_review_service`, роутер в цикле регистрации и в `__all__` пакета, закрытие соединения при остановке, ключ `code_review` (4 эндпоинта) и четыре строки в перечне эндпоинтов корневой точки |
| `frontend/chat_section.py`, `frontend/code_review_api.py`, `frontend/code_review_section.py` | Раздел «🔎 AI-ревью кода (Day 32)»: восемнадцатый пункт переключателя разделов, HTTP-запросы (`api_review_pr`, `api_review_github_pr`, обе проверки готовности) и сам раздел — провайдер, вкладки «🗂 Локальный diff» и «🐙 GitHub PR», таблицы находок, источники, ссылки на PR и комментарий, панели готовности |
| `backend/domain/dev_assistant.py`, `mcp_servers/dev_server/config.py`, `schemas.py`, `tools.py`, `server.py` | Правки dev-сервера: имена `TOOL_PR_DIFF`/`TOOL_CHANGED_FILES` в реестре `TOOLS` (по нему собирается каталог панели и ограничение `--tool`), `MAX_CHANGED_FILES = 300` и образец ref-а, `TypedDict ChangedFiles`, два инструмента и их регистрация |
| `scripts/run_local_pr_review.py` | Локальный прогон: `git diff base..head` или `--diff-file`, вызов службы, печать строк прогресса, предупреждений и источников, секция отчёта `docs/reports/code_review_demo.md` (`--pr-label`, `--section-title`, `--report`, `--no-report`, `--top-k`, `--provider`); коды 0/1/2 |
| `scripts/run_github_pr_review.py` | GitHub-прогон: `--repo-url` и `--pr-number` (обязательные), `--post-comment`, `--provider`, `--report`, `--no-report`, `--section-title`, `--top-k`; печатает `github_meta`-числа, предупреждения, источники, ссылки на PR и комментарий, пишет секцию отчёта `docs/reports/github_pr_review.md` с блоком «GitHub PR»; коды 0/1/2 |
| `scripts/gh_review_comment.py` | Публикация ответа `POST /review/pr` комментарием: `render_markdown` → `gh pr comment --body-file -`; `--dry-run` печатает разметку; коды 0/1/2 |
| `.github/workflows/ai-review.yml` | Action в корне репозитория: на `opened`/`synchronize`/`reopened` поднимает бэкенд на раннере, ждёт `/review/health`, собирает payload из `gh pr diff` и `gh pr view --json files`, зовёт `/review/pr` и публикует комментарий |
| `docs/reports/synthetic_pr.diff`, `docs/reports/code_review_demo.md`, `docs/reports/github_pr_review.md` | Вход синтетического примера (два метода `IndexService` с намеренными проблемами; `git apply --check` проходит), отчёт с двумя секциями локального режима и отчёт режима GitHub с двумя секциями: анонимное чтение `fastapi/fastapi#16481` и свой `ilushkius/go-url-shortener#7` с опубликованным комментарием |
| `tests/code_review_fakes.py`, `tests/unit/test_code_review_service.py`, `tests/unit/test_code_review_report.py`, `tests/unit/test_github_client.py`, `tests/integration/test_code_review_flow.py`, `tests/integration/test_github_pr_flow.py` | Фейки (diff трёх файлов, попадания документации и кода, индекс без фрагментов, MCP-клиент с diff-ом, `FakeGitHub` с diff-ом, файлами и записью публикаций, подмена `MCPClient`, пять кейсов) вынесены отдельным модулем — как фейки дня 31. Unit: структура ответа и разбор находок по кейсам, отказы MCP, модели и пустого индекса, отказ «нечего анализировать», запрос по пути файла, порядок приоритетов; разметка отчёта, блок «GitHub PR» и замена секции без дублей; режим GitHub (мета, публикация и её отказ) и клиент REST API на подменённом транспорте. Slow-интеграция: настоящий `git diff day30..day31` через настоящий `dev_server` и живой GitHub API по токену (без токена — skip) |

День 32 не заводит ни таблиц, ни новых индексов: он переиспользует индекс корпуса дня 22,
клиент модели (`rag_llm`), MCP-сервер дня 31 и путь публикации через `gh`; режим GitHub
добавляет к этому HTTP-клиент GitHub REST API и раздел интерфейса. Поэтому недоступный
индекс или файл вне корпуса — штатный случай: ревью идёт по diff-у, а причина остаётся в
`warnings` и в отчёте.

### Ассистент поддержки (день 33): `backend/`, `mcp_servers/support_server/`, `frontend/`, `scripts/`, `tests/`, `docs/support/`

| Модуль | Назначение |
|---|---|
| `backend/domain/support.py` | Контракт поддержки без HTTP, диска и модели: области продукта и слова-маркеры (`AREA_WORDS`), `detect_area` (побеждает область с большим числом разных слов), `normalize_question`, `ticket_block` (последние `MAX_TICKET_MESSAGES = 5` сообщений, текст до `MESSAGE_CHARS_MAX = 600`, блок до `TICKET_CONTEXT_MAX_CHARS = 3600`), `render_context` (шапки блоков документации, профиля, тикета и раздела продукта), `verdict` строки прогона, тексты отказов и предупреждений, пять `DEMO_SCENARIOS`, список документации поддержки `SUPPORT_SOURCES`/`SUPPORT_SLUGS` и минимум `SUPPORT_MIN_CHUNKS = 20` |
| `backend/services/support_service.py` | Служба: `answer` собирает контекст трёх источников (поиск по корпусу, `get_ticket`/`get_user`/`get_product_info` через один хелпер `_call`), отвечает моделью через `rag_llm`, отдаёт `sources`/`user_context`/`ticket_context`/`product_context`/`mcp_tools_used`/`warnings`; панельные методы `users`/`user`/`ticket`/`user_tickets`, ленивое соединение со своим stdio-сервером, синглтон `get_support_service` и закрытие своего соединения |
| `backend/schemas/support.py`, `backend/api/support.py` | Схемы (`SupportAskIn`/`SupportAskOut` и вложенные, `SupportUserListOut`, `SupportUserOut`, `SupportTicketsOut` с `SupportTicketSummaryOut`, `SupportTicketOut`) и пять эндпоинтов: `POST /support/ask` (400 — пустой вопрос или незнакомый провайдер, 502 — модель недоступна и контекста нет), панельные списки `GET /support/users` и `GET /support/tickets` (всегда 200, причина в `error`), одиночные `GET /support/users/{id}` и `GET /support/tickets/{id}` (404 — записи нет, 502 — MCP не поднялся) |
| `mcp_servers/support_server/config.py`, `schemas.py`, `tools.py`, `server.py` | Свой stdio-сервер поддержки: путь к базе `backend/data/support_db.json` (читается на каждый вызов — источник истины), структуры ответов `TypedDict` как `outputSchema` (все поля обязательны, ненайденная запись — непустой `error`), пять инструментов (`get_user`, `get_ticket`, `list_user_tickets`, `get_product_info`, `list_users`) и сборка `MCPServer` |
| `backend/core/dependencies.py`, `backend/api/main.py`, `backend/api/__init__.py`, `backend/services/__init__.py`, `backend/api/lifespan.py`, `backend/api/agents.py` | Прошивка: точка подмены `get_support_service`, роутер в цикле регистрации и в `__all__` пакета, закрытие соединения поддержки при остановке бэкенда (четвёртое «вне флота» после дней 31 и 32), ключ `support` (5 эндпоинтов) и пять строк в перечне эндпоинтов корневой точки |
| `frontend/chat_section.py`, `frontend/support_api.py`, `frontend/support_section.py` | Раздел «🎧 Поддержка пользователей (Day 33)»: девятнадцатый пункт переключателя разделов, HTTP-запросы (`api_support_ask`, `api_support_users`, `api_support_tickets`, `api_support_ticket`) и сам раздел — селекторы клиента и тикета из MCP, карточка контекста над полем вопроса, диалог с четырьмя раскрывашками и панель сервера |
| `backend/data/support_db.json` | База клиентов поддержки: 5 профилей (тарифы `free`/`pro`/`enterprise`), 10 тикетов с историей сообщений и 5 разделов продукта (`auth`, `billing`, `api`, `integrations`, `notifications`) |
| `docs/support/faq.md`, `docs/support/troubleshooting.md`, `docs/support/api_reference.md` | Документация поддержки: 33 пары «вопрос — ответ» под пятью областями, 13 разборов «симптом → причина → решение» и справочник семи эндпоинтов продукта с примерами `curl`; добавлены в таблицу `RAG_CORPUS_SOURCES` (44 источника) |
| `scripts/reindex_with_support.py` | Пересборка корпуса с документацией поддержки: `RAGService.prepare_corpus` плюс счётчик чанков трёх файлов поддержки по стратегиям; код 0 только при минимуме 20 чанков на стратегию и общем минимуме корпуса, 2 — `RAGError` |
| `scripts/support_mcp_probe.py` | Проба инструмента по stdio без модели: `--tool`, `--args` (JSON), `--target`; печатает каталог и структурированный результат, код 1 — ошибка инструмента или ненайденная запись |
| `scripts/demo_support.py` | Пять сценариев клиента через ту же службу: `--provider`, `--report`/`--no-report`, строки «контекст — ответ — источники — MCP — время», отчёт `docs/reports/support_demo.md` (контекст запуска, таблица, полные ответы); код 2 — пустой индекс поддержки или недоступная модель |
| `tests/support_fakes.py`, `tests/unit/test_support_service.py`, `tests/integration/test_support_flow.py` | Фейки (профиль, тикет с историей, раздел продукта по области, попадания документации поддержки, MCP-клиент с «записью не найдена», подмена `MCPClient`, `make_service`) отдельным модулем — как у дней 31–32. Unit: контекст трёх источников и предупреждения, отказ MCP, ненайденный тикет, панельные методы, соединение со stdio-сервером. Интеграция (slow): настоящий корпус, настоящий процесс `support_server` и рабочая база клиентов |

День 33 не заводит ни таблиц, ни новых индексов: он переиспользует индекс корпуса дня 22
(документация поддержки добавлена в ту же таблицу источников), клиент модели (`rag_llm`) и
путь MCP-подключения дней 31–32. Данные клиентов — собственный JSON-файл, который читает
только сервер поддержки: `mcp_servers.json` (флот дня 20) не меняется, а правка базы видна
сразу, потому что сервер читает её на каждый вызов инструмента.

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
| `api/` | 22 | HTTP: 19 роутеров по доменам (в том числе `indexing.py` — индексация, `llm.py` — расходы, `remote_llm.py` — удалённый сервер дня 30, `rag.py` — RAG, `mini_chat.py` — мини-чат, `dev_assistant.py` — ассистент, `code_review.py` — AI-ревью PR, `support.py` — ассистент поддержки, `orchestration.py` — запуски, `mcp_servers.py` — флот), `lifespan.py` (старт и остановка фоновых служб, чтение индексов, прогрев модели) и `main.py` (сборка `app`) |
| `core/` | 7 | `config.py` (настройки дня: файл флота, каталоги документов и индексов, модель эмбеддингов, границы поиска и **весь раздел оптимизации затрат** — маршрутизация моделей, пределы ответа, тарифы, доля цены кэша, окна непика и параметры журнала), `llm_settings.py` (**провайдеры ответа:** DeepSeek, локальная Ollama дня 26 и удалённая дня 30 — адрес, модель, ключ, лимит частоты и окно контекста; вынесены из `config.py` на пределе 400 строк), `mcp_server_config.py` (чтение `mcp_servers.json` и запись `tools_cache`), `dependencies.py` (доступ роутов к менеджеру, реестру, планировщику, службам пайплайна, оркестрации, индексации, RAG и клиенту LLM), `prompt_builder.py` |
| `domain/` | 65 | Чистые правила и данные без БД и сети: FSM задачи/сжатия/MCP/планировщика/пайплайна/оркестрации/**индексации**, графы переходов, расписания, агрегация, распознавание реплик, маппинг аргументов, стратегии, профиль, инварианты, тексты промптов, план шагов, **источники документов, блоки, метрики сравнения, тестовые запросы**, **стоимость запросов и правило непиковых часов**, **RAG-промпт, источники корпуса и контрольные вопросы**, **режимы отбора RAG с порогом и реранкером (день 23)**, **профили настройки локальной модели (день 29)**, **провайдеры ответа и сценарий демо удалённой LLM (день 30)**, **контракт ассистента разработчика (день 31)**, **контракт AI-ревью и разметка его отчёта (день 32)**, **контракт поддержки (день 33): области продукта, обрезка тикета, шапки контекста и вердикт строки**. Знают только stdlib, `core.config` и соседей по слою |
| `services/` | 56 | Прикладные сервисы: компрессор контекста, состояние задачи, инварианты, `mcp_*` (клиент, транспорт, ошибки, реестр с флотом, состояние сервера, раннер инструмента), планировщик и его службы, пайплайн, оркестратор, **чанкер, эмбеддинги, векторный индекс, загрузчик документов, прогон индексации, сборка метрик, служба индексации**, **клиент LLM, сжатие промптов и перенос запуска в непик**, **загрузчик корпуса RAG, служба RAG, этапы отбора, рекорды ответа, повторы вызова и служба кросс-энкодера (день 23)**, **служба мини-чата с правилами памяти задачи (день 25)**, **клиенты и службы обоих ответчиков на Ollama — локального (дни 26/29) и удалённого (день 30) с счётчиком частоты**, **служба ассистента разработчика (день 31)**, **служба AI-ревью PR с вынесенными поиском контекста, потоком GitHub и клиентом REST API (день 32)** и **служба ассистента поддержки с панельными методами и своим соединением со stdio-сервером (день 33)** |
| `storage/` | 17 | Доступ к БД: `database.py` (движок, сессии, реэкспорт ORM), хранилища задач, инвариантов, памяти, планировщика, пайплайна, оркестрации, **чанков с журналом индексации** и **журнала расходов на LLM** (+ модули «строка → словарь») |
| `agents/` | 12 | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов; менеджер передаёт агентам реестр MCP, службы пайплайна, оркестрации, **индексации (шаг поиска по документам в `generate`)** и **клиент LLM со строителем промптов** |
| `models/` | 13 | ORM-таблицы SQLAlchemy по доменам, включая **`indexing.py`** (`document_chunks`, `index_runs`), **`llm_usage.py`**, `orchestration.py` |
| `schemas/` | 22 | Pydantic-схемы API по доменам, включая **`indexing.py`**, **`llm.py`**, **`remote_llm.py`** (настройки, проверка соединения и шаг демо удалённой LLM), **`rag.py`**, **`mini_chat.py`**, **`local_tuning.py`**, **`dev_assistant.py`** (день 31), **`code_review.py`** (день 32), **`support.py`** (день 33), `orchestration.py` и `mcp_servers.py` |
| `utils/` | 1 | Своего кода нет (`__init__.py`): общий клиент DeepSeek, база, токены и логи — в repo-level `shared/` |

Девять слоёв обязательны и все содержат `__init__.py` с реэкспортом публичных
имён слоя — это единственное место, где виден публичный контракт. `api/__init__.py`
намеренно **не** импортирует `main`: `core.dependencies.get_manager` тянет
`api.main` лениво, иначе возник бы цикл `api → core → api`. По той же причине
`storage/task_store.py` берёт `MemoryManager` внутри свойства, а
`core/dependencies.py` — `AgentManager` только под `TYPE_CHECKING`.

`domain/__init__.py` (399 строк) импортирует модули планировщика, пайплайна,
оркестрации, индексации, стоимости, непика, RAG, настройки локальной модели и демо
удалённой LLM **как модули** (`from . import chunking,
indexing_fsm, llm_cost, local_tuning, peak_hours, rag_corpus_spec, rag_eval, rag_mode,
remote_demo, orchestration_fsm, …`), а не реэкспортирует их
имена: иначе список имён слоя вышел бы за лимит 400 строк. Код дня и так берёт имена из
своего модуля (`from ..domain.index_scenarios import DEMO_QUERIES`), поэтому точек входа
`backend.domain.indexing_fsm` и соседей достаточно. Ради лимита исторические абзацы
докстринга (описание задач, инвариантов и планировщика) сжаты.

## Тесты: `tests/`

Набор дня — **2807 тестов**: `unit/` — 1962 (80 файлов), `integration/` — 596
(59 файлов), `e2e/` — 249 (16 файлов). Классификация по фикстурам: чистые модули /
временная БД и агент / `TestClient`. Унаследованные наборы дней 11–20 (память и
стратегии, профиль, задача и переходы, инварианты, MCP, планировщик, пайплайн, флот и
оркестрация) остаются на месте; их раскладка по файлам — в
[`day20/STRUCTURE.md`](../day20/STRUCTURE.md).

**Режимы прогона и скорость.** Тесты идут параллельно (`pytest-xdist`, `-n auto`)
и делят одну схему БД на прогон: session-scoped `schema_template` строит её один
раз, а `session_factory` копирует файл (2,65 мс вместо 934 мс у `create_all`) —
изоляция сохранена (файл на тест), время полного прогона упало с 370 с до 68 с.
Тяжёлые тесты (93 штуки: подпроцессы MCP-серверов по stdio, сборка реального
RAG-корпуса и часть e2e) помечены
`slow` и по умолчанию пропускаются: `uv run pytest` идёт ~18 с и покрывает 2714
тестов, полный набор — `uv run pytest -m ""` или `--run-slow` — ~57 с и 2807 тестов. Autouse-фикстура
`no_real_network` запрещает тестам TCP на нелокальные адреса (внешние API
подменены фейками); исключение — тесты с маркерами `remote` и `github`: сквозной прогон
удалённой модели дня 30 идёт по настоящему туннелю, а живой REST API GitHub дня 32
(diff реального PR) фейком проверял бы не то. Замеры и разбор — в
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
| Полный цикл (slow) | `integration/test_rag_flow.py` (141), `integration/test_rag_quotes_flow.py` (112) | Сборка корпуса из 41 реального источника и обоих индексов, минимумы страниц и чанков на стратегию; `rag_query` находит нужный фрагмент и отдаёт источники с восемью полями; реранк стабом переставляет кандидатов на реальном корпусе и порог оставляет хотя бы один фрагмент; день 24 — `run_demo` на десяти вопросах из `backend/data/demo_questions.json`: режимы, источники и цитаты у `rag`-строк, пустые источники и текст «не знаю» у `dont_know`-строк, сводка; при недостижимом пороге все десять строк становятся «не знаю» без единого вызова модели |
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

### Удалённая LLM (день 30)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Клиент и счётчик частоты | `unit/test_remote_llm_client.py` (189) | Запрос идёт на `{base_url}/chat/completions` в формате OpenAI (`model`, `messages`, `stream=false`, `temperature`, `top_p`, `max_tokens`) с заголовком `Authorization: Bearer …` и расширением `options.num_ctx`; предел ответа берётся по типу задачи; `generate_with_context` кладёт системный промпт отдельно, а контекст — в вопрос; счётчик частоты пропускает N запросов и отклоняет N+1 (`RateLimitExceeded`, `status_code=429`), окно 60 с уезжает вместе с подменёнными часами; `GET /models` не тратит бюджет; ответ сервера «429» и сбои связи превращаются в понятные тексты (сервер, Cloudflare, пустой ответ, пустой адрес) |
| Полный цикл (slow + remote) | `integration/test_remote_llm_flow.py` (67) | Пять шагов демо по настоящему адресу туннеля (`DAY21_REMOTE_LLM_URL` или `REMOTE_LLM_URL`, иначе `skip`): порядок шагов, провайдер `remote` и его подтверждение, непустые строки без ошибок, счётчик частоты — один отказ на N+1, число вызовов равно числу вопросов плюс лимит; проверка соединения пропускается, если адрес не отвечает. Маркер `remote` снимает autouse-запрет сети `no_real_network`: адрес туннеля внешний, подменять его фейком нечем |

### Мини-чат (день 25)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки и фикстуры | `tests/mini_chat_fakes.py` (161), `tests/fixtures_mini_chat.py` (61) | Стаб-клиент с двумя ответами (текст ответа и JSON памяти, различаются по вопросу извлекателя), клиент с неразобранным JSON памяти, заглушка отбора (`FakeRetrieval`/`FakeRagService`: сильная и слабая выдача, запись вызовов); фикстуры службы на фейковом отборе — сильная, слабая (режим «не знаю») и сломанная (режим ошибки) |
| Сервис | `unit/test_mini_chat_service.py` (272) | Ответ с источниками и цитатами (восемь полей источника, `chunks_used`, расходы, отбор вызван без реранка); память задачи после реплики и JSON-строки рабочей памяти; история реплик и `limit`; порядок блоков промпта (RAG → память с напоминанием о цели → диалог); режим «не знаю» на слабой выдаче без вызова модели; режим ошибки после повторов; сохранение прежней памяти при неразобранном ответе извлекателя; неизвестная сессия и пустое сообщение; закрытие сессии (реплики удалены, повтор идемпотентен, история недоступна) и `make_mini_chat_client` без ключа; сессия переживает перезапуск службы; ленивые зависимости и синглтон |
| Полный цикл (slow) | `integration/test_mini_chat_flow.py` (111) | Сборка реального корпуса фейковым эмбеддером, прогон первого сценария целиком (14 реплик): непустые ответы, режимы `rag`/`dont_know`, не менее 80 % ответов с источниками, цель не потеряна, история и рабочая память на месте, закрытие удаляет все реплики |

### Ассистент разработчика (день 31)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки | `tests/dev_assistant_fakes.py` (155) | `FakeIndexService` (заданные попадания или исключение), `FakeMCP` (вызовы, результат по имени инструмента, ошибка инструмента, обрыв связи, пустой результат), `FakeStdioClient`/`FailingStdioClient` (подмена `MCPClient` со счётчиком созданных клиентов) и `make_service` — общие для двух юнит-файлов, потому что один файл вышел бы за предел 400 строк |
| Ответы и отказы | `unit/test_dev_assistant_service.py` (234) | Тип вопроса шестью вопросами (включая смешанный), ответ по документации с полным набором источников и текстом фрагмента в промпте, git-вопрос без поиска по корпусу, смешанный вопрос с двумя инструментами, ошибка инструмента поверх ответа, обрыв связи MCP, пустой индекс документации, «нет данных» без вызова модели, недоступная модель с текстом провайдера (отдельно — локального), текстовый результат инструмента без структуры, пустой вопрос, покрытие документации таблицей источников |
| Панели и соединение | `unit/test_dev_assistant_panels.py` (145) | Ленивое разрешение зависимостей, каталог инструментов, недоступный сервер (каталог и git-контекст данными), ошибка инструмента в панели git, соединение: создаётся один раз, с рабочим каталогом дня, закрывается методом `close()`, плюс сервер, не поднявшийся посреди вопроса, клиент по ключу и синглтон службы процесса |
| Полный цикл (slow) | `integration/test_dev_assistant_flow.py` (134) | Настоящий корпус (все 44 источника таблицы) и настоящий процесс `mcp_servers/dev_server/server.py`: вопрос по документации находит фрагменты из документации проекта, git-вопрос доходит до инструмента, каталог отдаёт шесть инструментов со схемами, вопрос про структуру возвращает дерево |

### AI-ревью PR (день 32)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки | `tests/code_review_fakes.py` (304) | Diff трёх файлов корпуса и список этих файлов, попадания документации и кода по slug-ам запроса, `FakeMCP` (diff и имена файлов по имени инструмента, ошибка связи, ошибка инструмента), `FakeGitHub` (diff, файлы, запись публикаций, отказ публикации, `health`), `FailingStdioClient` (подмена `MCPClient`) и пять кейсов `CASES` плюс `make_service` — общие для двух юнит-файлов |
| Служба | `unit/test_code_review_service.py` (199) | Пять кейсов параметризации: набор полей ответа, разбор находок (баг с файлом и строкой, рекомендация архитектурной проблемы), порядок рисков `P0`–`P3`, diff и файлы из payload или через MCP, `changed_files` как якорь контекста, предупреждения (обрыв MCP, пустой индекс) и честный текст при недоступной модели; отдельно — `CodeReviewError` при неработающем MCP, `ValueError` без diff-а и ref-ов, второй запрос по пути файла, когда добавленные строки увели выдачу, и семь форм записи приоритета; режим GitHub — `github_meta` из ответов клиента, публикация комментария с меткой PR, отказ публикации предупреждением при сохранённом ревью и `GitHubError` на негодном URL |
| Разметка | `unit/test_code_review_report.py` (104) | Разделы markdown ревью (включая экранирование `\|` в ячейках и приоритет с подписью), пустые разделы, обрезка полного ответа модели; блок «GitHub PR» (ссылка, число файлов и строк diff-а, «не публиковался» против «[опубликован](…)», пустая строка у локального ревью) и свой заголовок GitHub-отчёта; замена секции отчёта целиком без дублей — регрессия на то, что границей секции служит маркер, а не заголовок (тело ревью само начинается с `## 🤖 AI-ревью`) |
| Клиент GitHub | `unit/test_github_client.py` (225) | На подменённом транспорте `httpx.MockTransport` (сеть не открывается, autouse-запрет сети в силе): разбор URL в трёх формах и отказ на мусоре, чтения PR с заголовками `Accept` (JSON и `v3.diff`) и `Authorization: Bearer` (и его отсутствие без токена), тело публикации отзыва (`event: COMMENT`), тексты и коды 401/403/404/422, отличие исчерпанного rate limit по `X-RateLimit-Remaining`, сбой транспорта как «недоступен» с кодом 0, `health()` на живом и сломанном API, токен из окружения и его маска |
| Полный цикл (slow) | `integration/test_code_review_flow.py` (94) | Настоящий `git diff day30..day31` (4344 строки, 35 файлов) через настоящий процесс `mcp_servers/dev_server/server.py`: инструменты `get_pr_diff` и `get_changed_files` отдают данные, diff обрезается до 2000 строк (предупреждение с именами пропущенных файлов), файл дня 31 попадает в `changed_files`, а в источниках есть документация корпуса; отдельно — `CodeReviewError`, когда MCP не поднимается |
| Живой GitHub (slow + `github`) | `integration/test_github_pr_flow.py` (45) | Настоящий GitHub REST API по токену: метаданные PR, diff в формате unified и список файлов с непустыми именами; без `GITHUB_TOKEN` тест пропускается (анонимный лимит 60 запросов в час тратится общим на IP) |

### Ассистент поддержки (день 33)

| Группа | Файлы (строк) | Что проверяют |
|---|---|---|
| Фейки | `tests/support_fakes.py` (258) | Профиль клиента, тикет с историей из трёх сообщений и раздел продукта по запрошенной области, попадания документации поддержки, `FakeIndexService`, `FakeMCP` (результат по имени инструмента, «запись не найдена» данными, ошибка инструмента, обрыв связи, пустой результат), `FakeStdioClient`/`FailingStdioClient` (подмена `MCPClient`) и `make_service` |
| Служба | `unit/test_support_service.py` (257) | Три тестовые функции. (1) Вопрос с профилем: контекст профиля и раздела продукта, два вызова MCP, источники с баллами, блоки контекста в промпте, пустой вопрос → `ValueError`. (2) Вопрос с тикетом: тикет, профиль ПОДТЯНУТ из тикета, раздел продукта, заголовок блока тикета и статус в промпте; ненайденный тикет — предупреждение, `ticket_context is None`, запись инструмента `ok=True`. (3) Общий вопрос: MCP не вызывается вовсе; пустой индекс и недоступная модель (шаблоны провайдера и Ollama), ошибка инструмента, обрыв связи MCP, ленивое соединение со stdio-сервером и его закрытие, панельные методы (каталог, профиль, тикеты, ненайденная запись, ошибка инструмента), фабрика клиента без ключа и с ключом, неизвестный раздел продукта, покрытие таблицы источников документацией поддержки |
| Полный цикл (slow) | `integration/test_support_flow.py` (87) | Настоящий корпус (все 44 источника таблицы), настоящий процесс `mcp_servers/support_server/server.py` и рабочая база клиентов: вопрос про вход с `ticket_007` даёт тикет, профиль клиента из тикета (`user_003`, `pro`), раздел продукта и источники из FAQ и разборов симптомов; все вызовы инструментов без ошибок, предупреждений нет |

## Что изменилось относительно дня 20

Новые модули дней 21–33 перечислены выше. Здесь — только правки **унаследованного** кода
(проверены сравнением с `day20/`; в скобках — было → стало строк); правки дня 26 в уже
изменённых файлах (`rag_llm`, `rag_service`, `mini_chat_service`, `frontend/*`, `mini_chat/*`)
описаны в таблице «Локальная LLM как второй провайдер», правки дня 28 (`rag_service.py`,
`api/rag.py`, `api/agents.py`, `schemas/__init__.py`, `frontend/rag_api.py`,
`frontend/chat_section.py`, `app.py`) — в таблице «Локальный RAG», правки дня 29
(`local_llm_client.py`, `llm_factory.py`, `rag_llm.py`, `rag_service.py`,
`mini_chat_service.py`, `schemas/__init__.py`, `api/llm.py`, `api/agents.py`,
`domain/__init__.py`, `services/__init__.py`, `frontend/chat_section.py`, `app.py`,
`.env.example`) — в таблице «Оптимизация локальной LLM», правки дня 30 (`core/config.py`,
`domain/llm_provider.py`, `domain/__init__.py`, `services/llm_factory.py`,
`services/__init__.py`, `api/main.py`, `api/__init__.py`, `api/agents.py`,
`frontend/chat_section.py`, `frontend/sidebar.py`, `mini_chat/panels.py`, `app.py`,
`.env.example`) — в таблице «Удалённая LLM», а правки дня 31 (`domain/rag_corpus_spec.py`,
`core/dependencies.py`, `services/__init__.py`, `api/main.py`, `api/__init__.py`,
`api/lifespan.py`, `api/agents.py`, `frontend/chat_section.py`, `app.py`, `README.md`,
`STRUCTURE.md`, `docs/*`) — в таблице «Ассистент разработчика», а правки дня 32
(`core/dependencies.py`, `api/main.py`, `api/__init__.py`, `api/lifespan.py`,
`api/agents.py`, `services/__init__.py`, `api/dev_assistant.py`,
`domain/dev_assistant.py`, `mcp_servers/dev_server/*`, `README.md`, `STRUCTURE.md`,
`docs/*`) — в таблице «AI-ревью PR», а правки дня 33 (`backend/domain/rag_corpus_spec.py`,
`core/dependencies.py`, `api/main.py`, `api/__init__.py`, `api/lifespan.py`,
`api/agents.py`, `services/__init__.py`, `frontend/chat_section.py`, `app.py`,
`README.md`, `STRUCTURE.md`, `docs/*`) — в таблице «Ассистент поддержки»:

| Модуль | Строк | Что изменилось |
|---|---|---|
| `backend/agents/agent.py` | 2284 (2094) | Два шага дня 21: поиск по индексу (`_empty_indexing_report`, свойство `indexing_service`, `apply_index_context`, поле `record["indexing"]`) и вызов модели через `LLMClient` + сборка промпта `PromptBuilder` со сжатием блоков (`_make_client` остаётся точкой подмены в тестах); реплика, занятая пайплайном или оркестрацией, поиск по индексу не делает |
| `backend/agents/agent_manager.py` | 110 (105) | Параметры `indexing_service` и `llm_client`/`prompt_builder` — службы передаются агентам |
| `backend/agents/manager_agents.py` | 257 (255) | Передача новых служб в обоих местах создания `Agent` |
| `backend/core/config.py` | 399 (291) | Два новых раздела дня 21: «Индексация документов и поиск» (каталоги, модель эмбеддингов, чанкинг, границы топ-k, длины полей) и «Оптимизация затрат на LLM» (`MODEL_PRICES`, `LLM_CACHE_INPUT_RATIO`, типы задач и маршрутизация `LLM_TASK_MODELS`, пределы ответа `LLM_TASK_MAX_TOKENS`, `OFF_PEAK_WEEKDAY_HOURS_UTC`/`PEAK_WEEKDAY_HOURS_UTC`); заголовок и описание API дня 24 — «ОБЯЗАТЕЛЬНЫЕ ИСТОЧНИКИ, ЦИТАТЫ И РЕЖИМ «НЕ ЗНАЮ»», счётчик `/rag/... (6)`, `API_VERSION = "17.0.0"`. День 26 отдал чтение `.env` (`ENV_FILE`, `read_env_value`, `resolve_api_key`) в `backend/core/env_file.py` и добавил раздел «Локальная LLM»: `LLM_PROVIDER_DEFAULT`, `LOCAL_LLM_MODEL_DEFAULT`, `LOCAL_LLM_URL_DEFAULT`, `LLM_PROVIDER`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_URL`, `LOCAL_LLM_TIMEOUT`, `LOCAL_LLM_DEMO_MAX_TOKENS`; день 29 расширил его настройками профиля локальной модели (см. таблицу «Оптимизация локальной LLM»), а день 30 **вынес весь раздел провайдеров ответа в `backend/core/llm_settings.py`** (файл упёрся в лимит 400 строк, как раньше `env_file.py`) и оставил нижним блоком импорта только реэкспорт — поэтому `config.LLM_PROVIDER`, `config.LOCAL_LLM_*` и `config.REMOTE_LLM_*` читаются как прежде |
| `backend/core/dependencies.py` | 254 (115) | `get_indexing_service`, `get_index_service`, `get_embedding_service`, `get_prompt_builder`, `get_llm_client`, `get_rag_service`, `get_rerank_service`, `get_mini_chat_service`, `get_dev_assistant_service` (день 31: ассистент разработчика), `get_code_review_service` (день 32: служба AI-ревью PR) и `get_support_service` (день 33: служба поддержки) |
| `backend/api/main.py` | 79 (66) | Подключены роутеры `indexing`, `llm`, `rag`, `mini_chat` и (день 30) `remote_llm`, (день 31) `dev_assistant`, (день 32) `code_review`, (день 33) `support` и точки подмены служб индексации, клиента LLM, службы RAG, реранкера, мини-чата, ассистента, ревью и поддержки. День 31 заменил 16 строк `include_router` циклом по кортежу роутеров: места стало больше, и лимит 80 строк перестал быть узким (было ровно 80) |
| `backend/api/__init__.py` | 85 (56) | Реэкспорт роутеров `indexing`, `llm`, `rag`, `mini_chat`, `remote_llm`, `dev_assistant`, `code_review` (день 32) и `support` (день 33); контракт ошибок дня (409 на пустой индекс, 400 на стратегию/запрос/документы, неизвестный период расходов, пустой вопрос RAG, неизвестный режим отбора, пустой адрес удалённой модели и незнакомый шаг её демо, пустой вопрос ассистента и незнакомый его провайдер, а с дня 33 — пустой вопрос поддержки и незнакомый её провайдер, отсутствие diff-а и ref-ов в ревью PR, 422 на порог вне 0…1 и пул вне 1…60, 502 на сбой LLM-вызова RAG и на недоступный MCP без diff-а; у мини-чата — 404 на неизвестную сессию и 400 на пустое сообщение) |
| `backend/api/lifespan.py` | 98 (60) | Пятый и шестой шаги старта — `get_index_service().load_all()` и прогрев моделей демон-потоком `model-warmup` (эмбеддинги, затем реранкер); остановка пишет индексы (`save_all`) и закрывает соединение ассистента с сервером `dev_server` (день 31), затем такое же соединение службы ревью (день 32) и службы поддержки с её `support_server` (день 33) |
| `backend/api/agents.py` | 397 (314) | В инвентаре `GET /` — группы `indexing` (9), `llm` (8, включая `GET /llm/provider`, `POST /llm/local-demo` дня 26 и `POST /llm/tune` дня 29), `remote_llm` (3 эндпоинта дня 30), `rag` (7, включая `POST /rag/compare_modes`, эндпоинты демо `GET /rag/demo-questions`/`POST /rag/demo-run` и `POST /rag/compare_providers` дня 28), `mini_chat` (5), `dev_assistant` (3 эндпоинта дня 31), `code_review` (4 эндпоинта дня 32) и `support` (5 эндпоинтов дня 33), имя приложения дня 24 и 129 записей в списке эндпоинтов |
| `backend/api/scheduler.py` | 361 (355) | Описание флага `prefer_off_peak` и полей `off_peak`/`next_off_peak`/`discount_percent` в ответе `GET /scheduler/status` |
| `backend/domain/__init__.py` | 399 (395) | Импорт модулей индексации, стоимости, непика, RAG и настройки локальной модели (`local_tuning`, `local_tuning_eval`) как модулей; исторические абзацы докстринга сжаты, чтобы файл остался в лимите. День 30 добавил в тот же список `remote_demo` (сценарий пяти шагов демо) — строка та же, поэтому файл остался на 399 |
| `backend/services/__init__.py` | 301 (165) | Реэкспорт чанкера, эмбеддингов, индекса, загрузчика документов, службы индексации и её кодов отказа, `LLMClient`/`get_llm_client`, `PromptCompressor`, `shift_to_off_peak`, `RagCorpusLoader`/`get_rag_corpus_loader`, `RAGService`/`get_rag_service`, ошибок RAG, модулей дня 23 (`rag_errors`, `rag_corpus_index`, `rag_llm`, `rag_records`, `rag_retrieval`, `rerank_service`), мини-чата (`mini_chat_service`, `mini_chat_memory`, `MiniChatService`, `MiniChatSessionError`, `get_mini_chat_service`, `make_mini_chat_client`, `MINI_CHAT_AGENT_ID`), модулей дня 29 (`local_llm_resources`, `local_tuning_service`), дня 30 (`remote_llm_client`, `remote_llm_service`), `code_review_service` дня 32 и `support_service` дня 33 |
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
| `backend/schemas/__init__.py` | 395 (269) | Реэкспорт схем индексации, расходов, RAG (включая `RagModeOut`/`RagModesIn`/`RagModesOut`, `RagQuoteOut`, схемы демо дня 24 и схемы сравнения провайдеров дня 28 `RagCompareProvidersIn`/`RagCompareProvidersOut`/`RagProviderRowOut`/`RagProviderSummaryOut`), мини-чата (восемь `MiniChat*`) и прогона профилей дня 29 (`LocalTune*`); докстринг сжат, чтобы удержать лимит. Схемы дня 31 здесь НЕ реэкспортируются — файл стоит на пределе, поэтому `api/dev_assistant.py` импортирует их из `schemas/dev_assistant.py` напрямую (тот же приём, что у схем дня 30 в `schemas/remote_llm.py`) |
| `backend/schemas/agent.py` | 362 (352) | Поля `indexing` и `llm` ответа генерации |
| `frontend/chat_section.py` | 400 (346) | Девятый раздел «📦 Индексация», десятый «💰 Расходы», одиннадцатый «🆚 RAG-сравнение», двенадцатый «🧪 RAG-демо», тринадцатый «🏠 Локальный RAG» (день 28), четырнадцатый «⚙️ Оптимизация локальной LLM» (день 29), пятнадцатый «🛰 Удалённая LLM» (день 30) и семнадцатый «🧑‍💻 Ассистент разработчика» (день 31; шестнадцатым идёт «🖥 Локальная LLM» дня 26), восемнадцатый «🔎 AI-ревью кода» (день 32) и девятнадцатый «🎧 Поддержка пользователей» (день 33); панель «🔍 RAG-запрос по корпусу» в конце ветки чата; строки `indexing_note` и сводка расходов в отчёте хода. День 31 удержал файл на 399: ветка раздела сжата в три строки, а несколько многострочных вызовов собраны в одну строку — не поведение, а разметка; день 33 вернул файл к границе (400): ветка раздела и кортеж импортов, иначе новый раздел не влезал |
| `frontend/sidebar.py`, `mini_chat/panels.py` | 205, 227 | Переключатель провайдера в обоих местах берёт `llm_provider.PICKER_PROVIDERS` (`deepseek`, `local`), а не `PROVIDERS`: у удалённой модели свой раздел, и адрес туннеля живёт часами — в общем списке она была бы третьим, часто нерабочим пунктом; подпись боковой панели упоминает новую вкладку |
| `tests/conftest.py` | 286 (228) | Общие фикстуры (`schema_template`, `no_real_network`); фикстуры индексации, RAG (включая стаб-реранкер) и мини-чата вынесены в `fixtures_indexing.py`, `fixtures_rag.py` и `fixtures_mini_chat.py` и импортируются обратно; autouse-запрет сети пропускает тесты с маркером `remote` (сквозной прогон по туннелю дня 30) |
| `app.py` | 100 (67) | Заголовок страницы и описание девятнадцати разделов (лимит — 100 строк: перечень модулей `frontend/` собран плотнее, чтобы новые разделы влезали без превышения) |
| `README.md`, `STRUCTURE.md`, `docs/architecture.md`, `docs/usage.md`, `docs/api.md` | 1236, 1129, 1673, 1594, 7489 | Документация дня описывает текущее состояние (дни 21–33): `README` — задание дня 33 (ассистент поддержки: три источника контекста, свой MCP-сервер, демо и отчёт), `architecture` — устройство подсистем, включая «Ассистент поддержки — день 33» (поток данных, обрезка тикета, предупреждения вместо ошибок), `usage` — раздел 15 о запуске (пересборка индекса с документацией поддержки, проба сервера, раздел интерфейса, демо и отчёт, пять эндпоинтов, тесты, ограничения), `api` — пять эндпоинтов `/support/*` в таблице, в примере `GET /` и в разделе «Ассистент поддержки (день 33)»; `STRUCTURE` — раскладка и модули дня. Корпус вырос с 41 до 44 документов, поэтому числа корпуса обновлены во всех трёх документах |
| `pyproject.toml` | 30 (24) | Имя `day21` и описание дня; добавлены `sentence-transformers`, `faiss-cpu`, `numpy` |
| `.env.example` | 72 (15) | `DAY21_BACKEND_URL` вместо `DAY20_BACKEND_URL`, добавлены `DAY21_EMBEDDING_MODEL`, закомментированный `RAG_RERANK_MODEL`, порог дня 24 `RAG_RELEVANCE_THRESHOLD=0.6`, модель и адрес локальной LLM (день 26), профиль её настройки (день 29: `LOCAL_LLM_PROFILE`, `LOCAL_LLM_TEMPERATURE`, `LOCAL_LLM_NUM_CTX`, `LOCAL_LLM_CHAT_MAX_TOKENS`) и раздел удалённой LLM (день 30: `REMOTE_LLM_URL`, `REMOTE_LLM_MODEL`, `REMOTE_LLM_API_KEY`, `REMOTE_LLM_RATE_LIMIT`, `REMOTE_LLM_MAX_CONTEXT`) |
| `pytest.ini` | — | Комментарий про день 21; зарегистрированы маркеры `slow` и `remote` (второй снимает autouse-запрет сети у сквозного прогона по туннелю дня 30) |

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
| `backend/services/remote_llm_client.py` | `shared.logging_utils.get_logger` | Логгер клиента удалённой Ollama (обрыв туннеля, серверный 429, ответ не в формате OpenAI) |
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
| `backend/core/config.py` | 399 | 400 | Долго стоял ровно на границе (разделы дней 11–21); день 30 вынес настройки провайдеров ответа в `backend/core/llm_settings.py` — тот же приём, что раньше с `env_file.py`, — и файл отошёл от предела на строку |
| `backend/domain/__init__.py` | 399 | 400 | Модули планировщика, пайплайна, оркестрации, индексации, стоимости, непика, RAG, настройки локальной модели и демо удалённой LLM импортируются как модули (`from . import …`), а не реэкспортируются именами: иначе список имён слоя вышел бы за лимит. `remote_demo` дня 30 добавлен в уже существующую строку — файл остался на 399 |
| `GET /` — счётчик эндпоинтов | 123 записи / 104 пути | — | Инвентарь `endpoints` перечисляет эндпоинты по методу (123 записи, включая семь `/rag/*`, пять `/mini-chat/*`, одиннадцать `/llm/*`, три `/dev-assistant/*` и два `/review/*`), тогда как OpenAPI группирует их по пути — уникальных путей 104. Расхождение не ошибка, а разная форма счёта |
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
(2284 строки); код дня 33 в лимит укладывается (самые длинные новые модули —
`backend/services/support_service.py` (370) и `frontend/support_section.py` (353)).

`app.py` (100 ≤ 100) и `backend/api/main.py` (79 ≤ 80) в лимитах; день 30 снял с границы
`backend/core/config.py` (399: настройки провайдеров ответа уехали в
`backend/core/llm_settings.py`, 96) и увёл вглубь `frontend/chat_section.py` (400
после сжатия докстринга и ввоза раздела поддержки), `frontend/common.py` остался на 400, а
`backend/domain/__init__.py`, `backend/services/rag_service.py` и
`frontend/rag_section.py` — на 399; `backend/schemas/__init__.py` (395) и
`backend/services/mini_chat_service.py` (396) внутри лимита — по той же причине схемы
дня 30 лежат отдельным модулем `backend/schemas/remote_llm.py` (137).
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
`backend/services/rag_records.py` (87). Дальше идут `frontend/chat_section.py` (400),
`frontend/rag_section.py` (399), `frontend/local_rag_section.py` (222),
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

День 30 удержал лимит разделением ролей: HTTP-клиент удалённой модели
(`backend/services/remote_llm_client.py`, 349) отделён от службы прогона
(`backend/services/remote_llm_service.py`, 221), сценарий шагов живёт в домене
(`backend/domain/remote_demo.py`, 105), у раздела свой роутер со схемами
(`backend/api/remote_llm.py`, 134 и `backend/schemas/remote_llm.py`, 137 — отдельным
модулем, потому что `backend/schemas/__init__.py` на пределе), интерфейс — в
`frontend/remote_llm_section.py` (322) с тонким клиентом API
(`frontend/remote_llm_api.py`, 39), консольный прогон — в
`scripts/demo_remote_llm.py` (309). Тому же лимиту обязана и главная правка дня:
настройки провайдеров ответа переехали из `backend/core/config.py` (399) в
`backend/core/llm_settings.py` (96) — файл впервые за несколько дней не на границе.
Файлы дня 30 в тестах: `tests/unit/test_remote_llm_client.py` (189) и
`tests/integration/test_remote_llm_flow.py` (64).

День 31 удержал лимит тремя решениями. Во-первых, `backend/api/main.py` (72): 17 строк
`include_router` заменены циклом по кортежу роутеров, и файл перестал стоять ровно на
лимите 80. Во-вторых, `app.py` (100): новый раздел занял место, освобождённое плотной
сборкой перечня модулей `frontend/` в докстринге. В-третьих, тесты службы разложены на
три модуля — `tests/dev_assistant_fakes.py` (155, общие фейки),
`tests/unit/test_dev_assistant_service.py` (234, ответы и отказы) и
`tests/unit/test_dev_assistant_panels.py` (145, панели и соединение): один файл вышел бы
за 400 строк, а фейки в двух копиях разошлись бы. Самые длинные новые файлы дня:
`backend/services/dev_assistant_service.py` (349), `mcp_servers/dev_server/tools.py` (241),
`frontend/dev_assistant_section.py` (208), `scripts/demo_dev_assistant.py` (224),
`backend/domain/dev_assistant.py` (261) — все в лимите. Схемы дня пришлось НЕ
реэкспортировать через `backend/schemas/__init__.py` (395, на пределе): роутер
импортирует их из `backend/schemas/dev_assistant.py` (105) напрямую — тот же приём, что
у схем дня 30.

День 32 удержал лимит разделением обязанностей и выносами. Во-первых, домен
ревью разложен на два модуля: `backend/domain/code_review.py` (353 — контракт, разбор
ответа, приоритеты, обрезка diff-а, контекст промпта) и
`backend/domain/code_review_report.py` (196 — markdown комментария, секции отчёта и блок
«GitHub PR»): вместе они не влезли бы в 400 строк, а читатели у них разные — правила
разбора нужны службе, разметка только скриптам. Во-вторых, разметка отчёта получила
маркер секции (`SECTION_MARKER`), и это же решение сняло дефект: границей секции раньше
служил следующий заголовок `##`, а тело ревью само начинается с `## 🤖 AI-ревью`,
поэтому повторный прогон оставлял старое тело под новым — теперь секции заменяются
целиком (регрессия закреплена тестом `unit/test_code_review_report.py`). Расширение
режима GitHub добавило третий вынос: из службы ушли поиск контекста
(`backend/services/code_review_context.py`, 85) и поток GitHub-ревью
(`backend/services/code_review_github.py`, 74) — служба стояла ровно на пределе и после
выноса занимает 376 строк, а HTTP-часть GitHub живёт отдельным клиентом
(`backend/services/github_client.py`, 230). Самые длинные новые
файлы дня: `backend/services/code_review_service.py` (376), `mcp_servers/dev_server/tools.py` (306:
шесть инструментов и валидатор ref-а), `frontend/code_review_section.py` (281),
`backend/schemas/code_review.py` (184), `scripts/run_local_pr_review.py` (157),
`scripts/run_github_pr_review.py` (139) и `backend/api/code_review.py` (127). Схемы дня,
как и у дней 30–31, НЕ реэкспортируются через `backend/schemas/__init__.py` (395, на
пределе): роутер импортирует их из `backend/schemas/code_review.py` напрямую.

Каталог `.agents/` в выводе не случаен: в этой копии скиллы библиотек скопированы
(а не слинкованы), и три шаблона Streamlit внутри скилла `developing-with-streamlit`
длиннее 400 строк (416–449). Это код библиотеки, а не дня, поэтому при подсчёте кода
дня его исключают явно (`.agents` not in p.parts) — тогда превышение одно: `agent.py`.
