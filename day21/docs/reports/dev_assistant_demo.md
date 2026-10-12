# День 31 — ассистент разработчика: /help по документации и git-контексту

Прогон: 2026-10-12 22:55, скрипт `scripts/demo_dev_assistant.py`, провайдер 🌐 DeepSeek (облако). Отчёт снят до коммита дня, поэтому инструмент `get_git_diff` показывает незакоммиченные правки дня.

## Контекст запуска

* корпус: 41 документов, 382652 символов (~212 страниц)
* документация проекта: 8 файлов, чанков 113 (rag_corpus_fixed) и 125 (rag_corpus_structural) при минимуме 30 на стратегию
* MCP-инструментов сервера разработки: 4
* репозиторий: ветка main, коммит fc199f6 day30: удалённая LLM (Ollama в Colab за туннелем Cloudflare) и демо одной кнопкой
* изменённых файлов: `CHANGELOG.md`, `day21/README.md`, `day21/STRUCTURE.md`, `day21/app.py`, `day21/backend/api/__init__.py`, `day21/backend/api/agents.py`, `day21/backend/api/lifespan.py`, `day21/backend/api/main.py`, `day21/backend/core/dependencies.py`, `day21/backend/domain/rag_corpus_spec.py`, `day21/backend/services/__init__.py`, `day21/docs/api.md`, `day21/docs/architecture.md`, `day21/docs/usage.md`, `day21/frontend/chat_section.py`, `day21/tests/integration/test_rag_flow.py`, `day21/backend/api/dev_assistant.py`, `day21/backend/domain/dev_assistant.py`, `day21/backend/schemas/dev_assistant.py`, `day21/backend/services/dev_assistant_service.py`, `day21/docs/reports/dev_assistant_demo.md`, `day21/frontend/dev_assistant_api.py`, `day21/frontend/dev_assistant_section.py`, `day21/mcp_servers/dev_server/`, `day21/scripts/demo_dev_assistant.py`, `day21/scripts/dev_mcp_probe.py`, `day21/scripts/reindex_with_docs.py`, `day21/tests/dev_assistant_fakes.py`, `day21/tests/integration/test_dev_assistant_flow.py`, `day21/tests/unit/test_dev_assistant_panels.py`, `day21/tests/unit/test_dev_assistant_service.py`

## Сводка прогона

| # | Вопрос | Источники RAG | MCP-инструменты | Ответ | Вердикт |
|---|---|---|---|---|---|
| 1 | как устроена память агента? | workflow.md · Почему план идёт отдельной ступенью; day21-readme.md · День 30 — удалённая … | нет | Честно: в предоставленных фрагментах документации **прямого ответа на вопрос «как устроена память агента» нет**. Что реально есть в контексте: - **[1] workflow.md → «Рабочий процесс проекта: от сырог… | ✅ источники |
| 2 | что в текущей git-ветке? | нет | get_git_branch ✅ | В текущей git‑ветке: - **Ветка:** `main` - **Последний коммит:** `fc199f6` — «day30: удалённая LLM (Ollama в Colab за туннелем Cloudflare) и демо одной кнопкой» - **Рабочее дерево:** не чистое (`clea… | ✅ MCP |
| 3 | покажи структуру проекта | нет | get_git_branch ✅; get_project_structure ✅ | ## Структура проекта `day21` По результатам вызова MCP-инструмента **`get_project_structure`** (корень — `C:\Users\ilushkius\ai-challenge\day21`, глубина до 3 уровней): ### Сводные цифры - **39 дирек… | ✅ MCP |
| 4 | какие файлы изменены? | нет | get_git_branch ✅; get_git_diff ✅ | Вот список изменённых файлов по данным `get_git_branch` (MCP‑инструмент `get_git_branch`, ветка `main`, последний коммит `fc199f6`): **Корень проекта:** - `CHANGELOG.md` **Документация (day21):** - `… | ✅ MCP |
| 5 | как запустить тесты? | workflow.md · Пример полного цикла; day21-readme.md · Как запускать тесты; workflow.md · … | нет | # Как запустить тесты По документации проекта тесты запускаются из каталога `day21` через `uv`. ## Основные команды Источник: [4] `readme.md` · секция «Проверки перед "готово"» ```bash cd day21 uv ru… | ✅ источники |

## Вопрос 1

**как устроена память агента?**

Честно: в предоставленных фрагментах документации **прямого ответа на вопрос «как устроена память агента» нет**.

Что реально есть в контексте:

- **[1] workflow.md → «Рабочий процесс проекта: от сырого задания до коммита с тегом» → секция «Почему план идёт отдельной ступенью»** — описывает процесс (ТЗ → план → исполнение), но не устройство памяти агента.
- **[2] day21-readme.md → «День 30 — удалённая LLM: Ollama в Google Colab…»** — про удалённую LLM и таймаут запроса (120 с), к памяти агента не относится.
- **[3] day21-readme.md → «Как запускать тесты»** — про оптимизацию набора тестов, не о памяти.
- **[4] day21-scripts-prepare_documents.py** — сборка набора документов и манифест (`guide`/`code`/`device`-подобные поля).
- **[5] day21-backend-services-embedding_service.py** — эмбеддинги чанков (sentence-transformers, модель `paraphrase-multilingual-MiniLM-L12-v2`, `max_seq_length=512`, `normalize_embeddings=True`, FAISS). Это ближе всего к «памяти» в смысле RAG/векторного поиска, но в тексте прямо говорится про **индексацию и поиск**, а не про «память агента».

То есть косвенно можно предположить, что под «памятью» имеется в виду RAG-механизм (документы → чанки → эмбеддинги → FAISS), но это **моя интерпретация, а не утверждение из документации** — и она не подтверждается явно ни одним фрагментом.

**MCP-инструменты, которые я мог бы использовать для проверки:** git MCP (поиск коммитов/файлов по теме «agent memory», «память», «memory») и файловый/RAG-поиск по репозиторию. В текущем контексте инструменты **не вызывались** — я работал только с переданными фрагментами.

**Рекомендация:** если нужен точный ответ, уточните, какой именно агент имеется в виду (RAG-агент дня 21? демо дня 30?) — тогда я смогу найти соответствующий файл (например, `day21-backend-services-*` или отдельный модуль памяти) и дать ответ со ссылкой на источник.

Тип вопроса: docs · время: 17.22 с · вердикт: ✅ источники

## Вопрос 2

**что в текущей git-ветке?**

В текущей git‑ветке:

- **Ветка:** `main`
- **Последний коммит:** `fc199f6` — «day30: удалённая LLM (Ollama в Colab за туннелем Cloudflare) и демо одной кнопкой»
- **Рабочее дерево:** не чистое (`clean: false`) — есть незакоммиченные изменения

Изменённые (модифицированные) файлы:

**Корень:**
- `CHANGELOG.md`

**day21 (основной блок изменений):**
- `day21/README.md`, `day21/STRUCTURE.md`, `day21/app.py`
- `day21/backend/api/`: `__init__.py`, `agents.py`, `lifespan.py`, `main.py`, `dev_assistant.py`
- `day21/backend/core/dependencies.py`
- `day21/backend/domain/`: `rag_corpus_spec.py`, `dev_assistant.py`
- `day21/backend/services/`: `__init__.py`, `dev_assistant_service.py`
- `day21/backend/schemas/dev_assistant.py`
- `day21/docs/`: `api.md`, `architecture.md`, `usage.md`, `reports/dev_assistant_demo.md`
- `day21/frontend/`: `chat_section.py`, `dev_assistant_api.py`, `dev_assistant_section.py`
- `day21/tests/`: `integration/test_rag_flow.py`, `integration/test_dev_assistant_flow.py`, `unit/test_dev_assistant_panels.py`, `unit/test_dev_assistant_service.py`, `dev_assistant_fakes.py`
- `day21/mcp_servers/dev_server/`
- `day21/scripts/`: `demo_dev_assistant.py`, `dev_mcp_probe.py`, `reindex_with_docs.py`

**Корень репозитория:** `C:\Users\ilushkius\ai-challenge`

---

Источники и инструменты:
- **Источник данных:** вывод MCP‑инструмента `get_git_branch` (состояние репозитория, переданное в контексте).
- **Использованные MCP‑инструменты:** `get_git_branch`.
- Данные о конкретных изменениях внутри файлов (diff, статус add/modify/untracked) в переданном снимке отсутствуют, поэтому указать подробности по каждому файлу нельзя — только факт их модификации.

Тип вопроса: git · время: 3.27 с · вердикт: ✅ MCP

## Вопрос 3

**покажи структуру проекта**

## Структура проекта `day21`

По результатам вызова MCP-инструмента **`get_project_structure`** (корень — `C:\Users\ilushkius\ai-challenge\day21`, глубина до 3 уровней):

### Сводные цифры
- **39 директорий**
- **591 файл**

### Дерево верхнего уровня

```
day21/
├── .agents/                # агентские скиллы (check_docs, developing-with-streamlit,
│                           #   fastapi, library-skills, typer)
├── .omp/RULES.md           # правила проекта
├── backend/                # основной бэкенд (FastAPI)
│   ├── agents/             # агенты, менеджеры, память, профили
│   ├── api/                # роутеры: agents, rag, indexing, mcp, llm, memory,
│   │                       #   dev_assistant, remote_llm, scheduler, tasks, …
│   ├── core/               # config, dependencies, env_file, llm_settings, …
│   ├── data/               # demo_questions.json, mini_chat_scenarios.json
│   ├── domain/             # предметная логика (chunking, FSM, инварианты, …)
│   ├── schemas/            # pydantic-схемы API
│   ├── services/           # сервисы (index, embedding, llm, mcp_client, …)
│   ├── storage/            # доступ к БД / хранилищам
│   └── utils/
├── docs/                   # документация проекта
│   ├── reports/            # отчёты (demo, optimization, comparison, …)
│   ├── api.md
│   ├── architecture.md
│   └── usage.md
├── documents/rag_corpus/   # корпус для RAG (md и .py-выдержки)
├── frontend/               # Streamlit-UI: чат, indexing, mcp, dev_assistant, …
├── index/                  # построенные индексы (fixed / structural)
├── mcp_server/             # MCP-сервер (search, file_writer, pipeline_tools, …)
├── mcp_servers/            # MCP-флот: data_server, dev_server, search_server,
│                           #   storage_server
├── mini_chat/              # мини-чат (api, app, panels)
├── output/                 # артефакты MCP-демо (.md)
├── scripts/                # утилиты и демо-скрипты (20 файлов)
├── tests/                  # e2e / integration / unit + фикстуры и фейки
├── .clineignore, .coverage, .env.example, .python-version
├── AGENTS.md, README.md, STRUCTURE.md, WORKFLOW.md
├── agents.db               # SQLite-БД
├── app.py                  # точка входа (Streamlit)
├── conftest.py, pytest.ini, pyproject.toml, uv.lock
├── invariants_demo.md
└── mcp_servers.json        # конфиг MCP-флота
```

### Уточнения по ключевым каталогам
- **`backend/api/`** — 20 модулей-роутеров, включая недавно изменённые `dev_assistant.py`, `lifespan.py`, `main.py`, `agents.py`.
- **`backend/services/`** — сервисный слой: `dev_assistant_service.py`, `indexing_service.py`, `embedding_service.py`, `llm_factory.py`, `mcp_client.py` и др.
- **`backend/domain/`** — доменные модели и правила (`dev_assistant.py`, `chunking.py`, `indexing_fsm.py`, `invariant_rules.py`, …).
- **`frontend/`** — Streamlit-секции: `dev_assistant_section.py`, `dev_assistant_api.py`, `chat_section.py`, `indexing_section.py`, `mcp_ask.py` и др.
- **`mcp_servers/`** — четыре самостоятельных MCP-сервера плюс общий `__init__.py`.
- **`tests/`** — разделены на `e2e/`, `integration/`, `unit/`

Тип вопроса: git · время: 5.57 с · вердикт: ✅ MCP

## Вопрос 4

**какие файлы изменены?**

Вот список изменённых файлов по данным `get_git_branch` (MCP‑инструмент `get_git_branch`, ветка `main`, последний коммит `fc199f6`):

**Корень проекта:**
- `CHANGELOG.md`

**Документация (day21):**
- `day21/README.md`
- `day21/STRUCTURE.md`
- `day21/docs/api.md`
- `day21/docs/architecture.md`
- `day21/docs/usage.md`
- `day21/docs/reports/dev_assistant_demo.md`

**Backend (day21/backend):**
- `day21/app.py`
- `day21/backend/api/__init__.py`
- `day21/backend/api/agents.py`
- `day21/backend/api/lifespan.py`
- `day21/backend/api/main.py`
- `day21/backend/api/dev_assistant.py`
- `day21/backend/core/dependencies.py`
- `day21/backend/domain/rag_corpus_spec.py`
- `day21/backend/domain/dev_assistant.py`
- `day21/backend/schemas/dev_assistant.py`
- `day21/backend/services/__init__.py`
- `day21/backend/services/dev_assistant_service.py`

**Frontend (day21/frontend):**
- `day21/frontend/chat_section.py`
- `day21/frontend/dev_assistant_api.py`
- `day21/frontend/dev_assistant_section.py`

**MCP‑серверы:**
- `day21/mcp_servers/dev_server/` (каталог)

**Скрипты (day21/scripts):**
- `day21/scripts/demo_dev_assistant.py`
- `day21/scripts/dev_mcp_probe.py`
- `day21/scripts/reindex_with_docs.py`

**Тесты (day21/tests):**
- `day21/tests/integration/test_rag_flow.py`
- `day21/tests/integration/test_dev_assistant_flow.py`
- `day21/tests/unit/test_dev_assistant_panels.py`
- `day21/tests/unit/test_dev_assistant_service.py`
- `day21/tests/dev_assistant_fakes.py`

Итого — **30 позиций** (из них 29 файлов и 1 каталог `day21/mcp_servers/dev_server/`). Признак `"clean": false`, то есть в рабочем дереве есть незакоммиченные изменения.

---

**Дополнительно из `get_git_diff`** (MCP‑инструмент `get_git_diff`) видно, что в диффе присутствуют правки как минимум в:
- `day21/app.py` — подключён рендер секции ассистента разработчика (`dev_assistant_section.render_dev_assistant_section()`), косметика форматирования f‑строк.
- `day21/tests/integration/test_rag_flow.py` — обновлён docstring теста сборки корпуса.

Дифф в предоставленном срезе обрезан, поэтому полный перечень фактически изменённых строк по всем 29 файлам по нему не восстановить.

---

**Источники:** вывод MCP‑инструментов `get_git_branch` (поле `modified_files`) и `get_git_diff` (фрагменты по `day21/app.py` и `day21/tests/integration/test_rag_flow.py`). Документация проекта (`day21/docs/*.md`, `day21/STRUCTURE.md`) не использовалась, поскольку вопрос носит чисто фактический характер и полностью покрывается состоянием git.

Тип вопроса: git · время: 4.01 с · вердикт: ✅ MCP

## Вопрос 5

**как запустить тесты?**

# Как запустить тесты

По документации проекта тесты запускаются из каталога `day21` через `uv`.

## Основные команды

Источник: [4] `readme.md` · секция «Проверки перед "готово"»

```bash
cd day21
uv run pytest -m ""                        # весь набор тестов (~70 с)
uv run pytest -m "" --cov=backend --cov-report=html   # покрытие → htmlcov/index.html
uv run python -m py_compile <изменённые .py>          # синтаксис
```

Ключевые моменты:
- `cd day21` — тесты запускаются именно из каталога дня.
- `-m ""` — снимает фильтр маркеров, т.е. собирает **весь** набор, включая помеченные `slow`.
- `--cov=backend --cov-report=html` — замер покрытия с HTML-отчётом в `htmlcov/index.html`.

## Контекст по ускорению набора

Источник: [2] `day21-readme.md` · секция «Как запускать тесты»
Источник: [1] `workflow.md` · секция «Пример полного цикла»

Набор был оптимизирован (это как раз пример полного цикла из workflow):
- параллельный запуск `-n auto` (`pytest-xdist`);
- общая session-scoped схема БД на прогон;
- маркер `slow` для медленных тестов.

Замеры и детали — в `docs/reports/test_optimization.md` (упоминается в [1] и [2]).

## Оговорки

- В фрагментах **нет** явной команды для запуска только быстрого подмножества (без `slow`) — упоминаются «быстрый прогон ~30 с» и «полный ~70 с» [1], но точный флаг (например, `-m "not slow"`) в приведённом контексте не показан. Если нужна точная команда быстрого прогона — стоит уточнить по `docs/reports/test_optimization.md` или `docs/usage.md`.
- Проверки лимитов структуры (`.py` ≤ 400 строк, `app.py` ≤ 100, `backend/api/main.py` ≤ 80) описаны в `docs/project-rules.md` [4].

## Использованные MCP-инструменты

В данном ответе инструменты не вызывались — ответ построен **только** на предоставленных фрагментах документации (RAG-контекст). Уточнить команду быстрого прогона можно, вызвав чтение файлов `docs/reports/test_optimization.md` / `docs/usage.md` (например, через MCP filesystem, если он доступен).

Тип вопроса: docs · время: 3.63 с · вердикт: ✅ источники
