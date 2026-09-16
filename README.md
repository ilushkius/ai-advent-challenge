# AI-челлендж

Персональный практикум по большим языковым моделям (LLM) и промпт-инжинирингу на
реальных API: **DeepSeek** (OpenAI-совместимый endpoint) и **Hugging Face**
(Inference Providers). Каждый день — одно
небольшое, самодостаточное приложение в папке `dayN/`.

Проект ведётся вместе с терминальным агентом **omp.sh**, который читает правила
проекта из [`.clauderules`](.clauderules) и [`AGENTS.md`](AGENTS.md)
(см. [Процесс разработки](#процесс-разработки)).

## Структура проекта

| Папка | Что это | Назначение |
|---|---|---|
| `day1/` | **День 1 · «Первый запрос к DeepSeek»** | Консольный потоковый чат с моделью `deepseek-chat` (`deepseek_chat.py`) |
| `day2/` | **День 2 · «Формат ответа»** | Streamlit-демо управления генерацией: `temperature`, `seed`, `max_tokens`, `stop`, JSON-режим (`app.py`) |
| `day3/` | **День 3 · «Способы рассуждения ИИ»** | Streamlit-демо: Zero-Shot, Chain-of-Thought, мета-промпт, «консилиум экспертов» (`app.py`) |
| `day4/` | **День 4 · «Эксперимент с температурой»** | Документный день (без кода): сравнение ответов `deepseek-chat` при `temperature` 0 / 0.7 / 1.2 с оценками и выводами (`results.md`) |
| `day5/` | **День 5 · «Сравнение моделей Hugging Face»** | Streamlit-приложение: один запрос через три модели HF разного размера (8B / 70B / 235B), метрики, оценка качества 0–10, отчёт (`app.py`) |
| `day6/` | **День 6 · «Менеджер агентов DeepSeek»** | FastAPI + Streamlit: пул независимых агентов с единым менеджером-синглтоном и историей запросов в памяти (`backend/`, `app.py`) |
| `day7/` | **День 7 · «Агент с контекстной памятью»** | FastAPI + Streamlit + SQLite: каждый агент хранит полный диалог в SQLite и отправляет его в DeepSeek целиком; память переживает рестарт (`backend/`, `app.py`) |
| `day8/` | **День 8 · «Агент с контролем токенов»** | FastAPI + Streamlit + SQLite + tiktoken: подсчёт токенов каждого запроса (история/ответ), таблица `token_usage`, панель лимита в UI и автообрезка истории при переполнении контекста (`backend/`, `app.py`) |
| `day9/` | **День 9 · «Управление контекстом: сжатие истории»** | FastAPI + Streamlit + SQLite + tiktoken: последние N реплик уходят «как есть», остальные заменяются конспектом (таблица `summaries`), метрики экономии токенов, сравнение режимов «без сжатия / со сжатием»; первая стейт-машина (`Enum` + State) и первые `pytest`-тесты (`backend/`, `app.py`, `tests/`) |
| `day10/` | **День 10 · «Управление контекстом: стратегии»** | FastAPI + Streamlit + SQLite + tiktoken: четыре стратегии сборки контекста (sliding_window / sticky_facts / branching / summary) с переключателем, таблицы `facts` и `checkpoints`, сравнение в `comparison.md` (`backend/`, `app.py`, `tests/`) |
| `day11/` | **День 11 · «Трёхслойная модель памяти агента»** | FastAPI + Streamlit + SQLite + tiktoken: память агента разложена на три слоя со своими таблицами — краткосрочная (`short_term_messages`, сессия), рабочая (`working_memory`, задача) и долговременная (`long_term_memory`, профиль/предпочтения/решения/знания); `MemoryManager`, десять эндпоинтов `/memory/...`, панели слоёв в UI, разбивка токенов по слоям в ответе генерации, отчёт `memory_layers_comparison.md`; установка, маршрутизация «что куда» и проверки «какие данные попадают в каждый слой» / «как слои влияют на ответы» — в `docs/usage.md` (`backend/`, `app.py`, `tests/`) |
| `day12/` | **День 12 · «Персонализация: профиль пользователя»** — **снимок** | FastAPI + Streamlit + SQLite + tiktoken: структура дня 11 (три слоя памяти, четыре стратегии контекста) плюс персонализация — таблица `user_profiles` (`preferences`: tone/verbosity/language/format, `constraints`: max_response_length/forbidden_topics/required_disclaimers, `custom_instructions`), блок профиля в системном промпте КАЖДОГО запроса, пять эндпоинтов `/users...` + `GET /agents/{id}/profile`, поля `profile` и `system_prompt` в ответе генерации, раздел «👤 Профиль пользователя» в UI с готовыми профилями и сравнением двух профилей на одном вопросе, отчёт `personalization_comparison.md`; тестовый сценарий дня 11 удалён. Код дня разложен по модулям: `ui/` (8 модулей интерфейса), `backend/routers/` (4 роутера по доменам), `backend/models/` (Pydantic-схемы по доменам), ORM-таблицы — `backend/tables.py`, общие помощники — `shared/` (см. [`day12/STRUCTURE.md`](day12/STRUCTURE.md)) |
| `day13/` | **День 13 · «Состояние задачи как FSM»** | FastAPI + Streamlit + SQLite + tiktoken: структура дня 12 (три слоя памяти, четыре стратегии контекста, профиль пользователя) плюс формализованное состояние задачи — конечный автомат с этапами `planning`/`execution`/`validation`/`done`/`paused`, шагами внутри этапа, ожидаемым действием и паузой с продолжением с того же места. Состояние живёт в SQLite (таблицы `task_states`, `task_transitions`), блок состояния подключается к системному промпту КАЖДОГО запроса (последним), обновляется автоматически по реплике пользователя (`пауза`/`продолжи`/`откат`/`подтверждаю`), управляется девятью эндпоинтами `/agents/{id}/tasks` и `/tasks/{id}/...` (всего в API 45 эндпоинтов; версия приложения — `7.0.0`) и разделом «🧭 Состояние задачи» в UI; отчёт `task_state_demo.md` доказывает продолжение после перезапуска процесса (см. [`day13/STRUCTURE.md`](day13/STRUCTURE.md)) |
| `shared/` | **Общие модули** (код, не меняющийся между днями) | `deepseek_utils.py` (endpoint DeepSeek, ключ из `.env`, stop-строки, `usage_to_dict`), `deepseek_client.py` (`make_client` — клиент OpenAI SDK), `db_base.py` (`Base`, `make_engine`, `init_db`, `make_session_factory`), `token_counter.py` (`count_tokens` через tiktoken), `logging_utils.py` (`get_logger`, `configure_logging`) |
| `.clauderules` | Правила проекта для агента | Свод правил ai-challenge: стек, конвенции, процесс, проверки, секреты |
| `AGENTS.md` | Архитектурные цели и правила структуры | Стейт-машина на Python, `Enum` + паттерн State, тесты через `pytest`, лимиты размера файлов (400 строк), слои дня (`frontend/` · `backend/{api,core,models,schemas,services,storage,domain,agents,utils}/` · `scripts/` · `tests/{unit,integration,e2e}/` · `shared/`) |
| `CHANGELOG.md` | История изменений | Записи о значимых изменениях структуры и документации (дата, тип, что затронуто) |
| `.omp/config.yml` | Конфигурация omp.sh | Модель по умолчанию — `deepseek/deepseek-flash` (DeepSeek V4.1 Flash) и роли моделей |
| `.omp/skills/` | **Скиллы проекта** | Процедурные правила для агента: `python-fsm-agent`, `fastapi-streamlit-day-structure`, `shared-modules-usage`, `tdd-pytest-workflow`, `day-docs-structure` (список — в `AGENTS.md`, раздел «Скиллы проекта») |

Статус папок: `day1/`–`day12/` — **снимки** (сданы, код не изменяется; правка —
только по прямому запросу), `day13/` — **активная разработка** (здесь
применяются правила структуры из [`AGENTS.md`](AGENTS.md)), `shared/` — общие
модули для дней.

### День 13: состояние задачи

День 13 — копия дня 12 плюс **состояние задачи как конечный автомат**: этапы,
шаги внутри этапа, ожидаемое действие, пауза и продолжение с того же места.
Полная карта модулей — [`day13/STRUCTURE.md`](day13/STRUCTURE.md):

| Путь | Что внутри | Строк кода |
|---|---|---|
| `day13/app.py` | точка входа Streamlit: `set_page_config` + вызовы секций | 45 |
| `day13/frontend/` | 10 модулей интерфейса: `sidebar.py`, `chat_section.py`, `context_panels.py`, `memory_panels.py`, `profile_section.py`, `profile_comparison.py`, `task_panel.py`, `common.py`, `api_client.py`, `__init__.py` | 6–327 |
| `day13/backend/api/` | FastAPI: эндпоинты по доменам — `agents.py` (11), `context.py` (9), `memory.py` (10), `profiles.py` (6), `tasks.py` (9) — и сборка приложения `main.py` (`lifespan`, CORS, `include_router`) | 15–253, `main.py` — 80 |
| `day13/backend/core/` | `config.py` (настройки, лимиты, цены, пути `.env` и `agents.db`), `dependencies.py` (`get_manager`, `agent_or_404`, `task_or_404`) | 41–156 |
| `day13/backend/domain/` | чистые правила и данные: `strategies`, `context_fsm`, `context_policy`, `fact_extractor`, `memory_layers`, `profile_values`, `profiles`, `demo_profiles`, `task_fsm`, `task_prompt`, `task_intent` | 62–387 |
| `day13/backend/services/` | `compressor.py` (`ContextCompressor`), `task_state.py` (`TaskStateMachine` — переходы и валидация) | 268–329 |
| `day13/backend/storage/` | `database.py` (движок, сессии, реэкспорт ORM), `task_store.py` (`TaskStateStore`), `memory_rows.py` | 44–217 |
| `day13/backend/agents/` | `agent.py` (`Agent`), `memory.py` (`MemoryManager`), `profile_store.py` (`ProfileStore`), `agent_manager.py` + `manager_*.py` (миксины менеджера по доменам) | 55–1603 ⚠️ |
| `day13/backend/models/` | ORM-таблицы SQLAlchemy по доменам: `agent`, `message`, `memory`, `context`, `user_profile`, `task_state` (11 таблиц), реэкспорт через `backend/storage/database.py` | 41–157 |
| `day13/backend/schemas/` | Pydantic-схемы API по доменам (`agent`, `context`, `memory`, `profile`, `task`), реэкспорт через `schemas/__init__.py` | 122–319 |
| `day13/backend/utils/` | слой объявлен обязательным, но пуст: общий код живёт в `shared/` | 9 |
| `day13/scripts/` | прогоны демонстраций и сборка отчётов: `task_state_demo.py`, `task_demo_report.py`, `personalization_comparison.py`, `comparison_report.py`, `comparison_stub.py` | 79–354 |
| `day13/tests/` | 584 теста в подпапках `unit/` (7 файлов), `integration/` (12), `e2e/` (5); общие фикстуры — `conftest.py`, `support.py` | 60–395 |
| `shared/` | общие модули, которые день импортирует как `from shared.<module> import ...` | 26–62 |

⚠️ `day13/backend/agents/agent.py` (1603 строки) превышает лимит 400 строк из
`AGENTS.md` — расхождение унаследовано от дня 12 и зафиксировано в
`AGENTS.md` и [`day13/STRUCTURE.md`](day13/STRUCTURE.md).

## Правила разработки

- **Процедурные правила вынесены в скиллы omp.sh** (см.
  [`AGENTS.md`](AGENTS.md), раздел «Скиллы проекта»): папка `.omp/skills/` —
  FSM (`python-fsm-agent`), раскладка файлов дня
  (`fastapi-streamlit-day-structure`), общий код (`shared-modules-usage`), тесты
  (`tdd-pytest-workflow`), документация дня (`day-docs-structure`).
- **Архитектурные цели и структура файлов** — [`AGENTS.md`](AGENTS.md): явная
  стейт-машина на `Enum` + паттерн State, лимит **400 строк** на любой `.py`
  (`app.py` ≤ 100, `backend/api/main.py` ≤ 80), раскладка по слоям
  (`frontend/`, `backend/{api,core,models,schemas,services,storage,domain,agents,utils}/`,
  `scripts/`, `tests/{unit,integration,e2e}/`, `shared/`),
  запрет дублирования кода между днями и правки снимков прошлых дней.
- **Общие конвенции** (стек, git, команды проверки, стиль) —
  [`.clauderules`](.clauderules).
- **Структура модулей дня** — файл `STRUCTURE.md` в папке дня: список модулей и
  назначение каждого в одну строку (пример — [`day13/STRUCTURE.md`](day13/STRUCTURE.md)).
- **Plan Mode**: задача по новому приложению начинается с утверждения структуры
  файлов (модули и их обязанности), и только затем идёт реализация.
- **Проверки перед «готово»**: `pytest` из папки дня
  (`.venv/Scripts/python -m pytest -q`), `python -m py_compile` по изменённым
  файлам, smoke-запуск приложения без реальных запросов к API; подробнее —
  `.clauderules`, раздел «Проверки перед завершением».
- **Междневные изменения** фиксируются в [`CHANGELOG.md`](CHANGELOG.md).

## Общие модули (`shared/`)

`shared/` — код, который не меняется между днями и лежит в корне репозитория.
День добавляет корень репозитория в `sys.path` и импортирует модули как
`from shared.<module> import ...` (в дне 13 это делает `day13/backend/__init__.py`).

| Модуль | Что делает | Кто использует |
|---|---|---|
| `shared/deepseek_utils.py` | `DEEPSEEK_BASE_URL` (endpoint `https://api.deepseek.com`), `read_key_from_env_file` (ключ из `.env`), `parse_stop_sequences` (stop-строки из UI), `usage_to_dict` (объект `Usage` → dict) | day2, day3, `day13/backend/core/config.py` |
| `shared/deepseek_client.py` | `make_client(api_key, base_url, timeout)` — клиент OpenAI SDK для DeepSeek; `openai` импортируется лениво, `DEFAULT_TIMEOUT = 60.0` | `day13/backend/agents/agent.py` |
| `shared/db_base.py` | SQLAlchemy/SQLite: `Base` (декларативная база), `make_engine` (`check_same_thread=False` + `PRAGMA foreign_keys=ON`), `init_db` (создание таблиц), `make_session_factory` | `day13/backend/storage/database.py`, `day13/backend/models/*.py` |
| `shared/token_counter.py` | `count_tokens(text)` и `get_tokenizer()` — локальная оценка токенов через tiktoken (`cl100k_base`, кодировка кэшируется на процесс) | `day13/backend/agents/agent.py` |
| `shared/logging_utils.py` | `get_logger(name)` (логгер без хендлеров, вывод по умолчанию выключен), `configure_logging()` (включает вывод в консоль), `DEFAULT_FORMAT` | `day13/backend/api/main.py`, `day13/backend/agents/agent.py`, `day13/backend/storage/task_store.py` и модули `shared/` изнутри |

Сегодня `shared/` подключают `day2/`, `day3/` (только `deepseek_utils.py`)
и `day13/` (все модули); дни 5–11 автономны, `day12/` — снимок той же
архитектуры. Для новых дней `shared/` —
обязательное место для междневного кода (см. `AGENTS.md`). Подробнее —
[docs/architecture.md](docs/architecture.md) и [docs/usage.md](docs/usage.md).

## Стек технологий

| Слой | Технология | Где используется |
|---|---|---|
| Язык | Python 3.14+ (Windows, PowerShell, VS Code) | все дни |
| UI демо | Streamlit ≥ 1.30 (day2/.venv — 1.62.0; day5/.venv — 1.63.0) | day2, day3, day5–day8 |
| API DeepSeek | официальный OpenAI SDK (`openai>=1.40.0`, установлен 3.6.0), `base_url=https://api.deepseek.com` | day1–day4, day6–day8 |
| API Hugging Face | `huggingface_hub>=0.24` (установлен 1.30.0): `InferenceClient.chat_completion` через роутер Inference Providers | day5 |
| Модели | DeepSeek: `deepseek-chat` (основная), `deepseek-reasoner` (ограничения: может игнорировать `temperature`/`response_format`); HF (день 5): `Llama-3.1-8B-Instruct`, `Llama-3.3-70B-Instruct`, `Qwen3-235B-A22B-Instruct-2507` | все дни |
| Хранилище | SQLite + SQLAlchemy 2.0 (дни 7–9): файлы `day7/agents.db`, `day8/agents.db`, `day9/agents.db`; таблицы `agents` (конфигурация), `messages` (диалог), `token_usage` (метрики токенов, день 8+) и `summaries` (конспекты истории, день 9) | day7–day9 |
| Токенизация | `tiktoken` (`cl100k_base`) — локальный подсчёт токенов, оценки близки к токенизатору DeepSeek | day8–day9 |
| Стейт-машина | `enum.Enum` + паттерн State (чистый Python): `context_fsm.py` — сжатие истории (день 9; в дне 13 — `backend/domain/context_fsm.py`), `backend/domain/task_fsm.py` — состояние задачи (день 13) | day9, day13 |
| Тесты | `pytest` (день 9: 167 тестов — FSM, политика сжатия, хранилище, компрессор, агент, API; день 10: 193 — стратегии, факты, ветки, FSM, хранилище, API; день 11: 235 — слои памяти, API `/memory/...`, стратегии, факты, ветки, FSM, хранилище, компрессор, API; день 12: 314 — профили пользователей, промпт персонализации, API `/users...`, плюс всё из дня 11; день 13: 584 — FSM состояния задачи, хранение и журнал переходов, авто-обновление по реплике, API `/tasks...`, плюс всё из дня 12) | day9–day13 |
| Виртуальные окружения | `day2/.venv` (streamlit 1.62.0, openai 3.6.0); `day5/.venv` (streamlit 1.63.0, huggingface_hub 1.30.0); `day6/.venv` (fastapi, streamlit, openai, requests); `day9/.venv` (fastapi, sqlalchemy, tiktoken, pytest и др.); `day13/.venv` создаётся `uv sync` | day2–day3, day5, day6, day9, day13 |
| Зависимости | `uv` в дне 13 и далее: прямые зависимости — `pyproject.toml`, точные версии — `uv.lock`, интерпретатор — `.python-version` (в снимках `day1`–`day12` — `pip` + `requirements.txt`) | day13+ |
| Инструменты разработки | терминальный агент **omp.sh** (модель `deepseek/deepseek-flash` — DeepSeek V4.1 Flash), Python LSP `pyright`, `debugpy` | AI-воркфлоу |

Код дней 1–4 и 6–9 написан в синтаксисе, совместимом с OpenAI SDK 1.x/2.x/3.x
(`OpenAI(api_key=..., base_url=...)`); день 5 использует
`huggingface_hub.InferenceClient`; день 7 добавляет слой персистентности
(SQLAlchemy 2.0 + SQLite), день 8 — подсчёт токенов (tiktoken) и таблицу
`token_usage`, день 9 — сжатие истории (таблица `summaries`, конспект вместо
старых реплик), стейт-машину на `Enum` + паттерн State и первые автотесты
`pytest`. Автотесты есть у дней 9–13 (`day9/tests/` — 167 тестов,
`day10/tests/` — 193, `day11/tests/` — 235, `day12/tests/` — 314,
`day13/tests/` — 584); для остальных прикладных дней
проверка — `py_compile` и smoke-запуск, а целевой стандарт новых дней —
`pytest` (см. [AGENTS.md](AGENTS.md)).

## Требования

- Windows, **Python 3.14+** и `pip` (для дня 13 и последующих — менеджер `uv`).
- API-ключ DeepSeek (https://platform.deepseek.com → API Keys).
- Для дня 5: токен Hugging Face (`hf_...`, https://huggingface.co/settings/tokens);
  бесплатные аккаунты HF получают небольшие месячные включённые кредиты Inference
  Providers (~$0.10), при исчерпании — ошибка 402.
- Для агента **omp.sh**: CLI omp.sh, Python LSP `pyright` и дебаггер `debugpy`
  (`pip install pyright debugpy`).

## Установка

### 1. Зависимости приложений (Python)

У каждого прикладного дня из снимков (`day1`–`day12`) свой `requirements.txt` —
устанавливайте из папки дня:

```bash
cd day1 && pip install -r requirements.txt
cd day2 && pip install -r requirements.txt
cd day3 && pip install -r requirements.txt
cd day5 && pip install -r requirements.txt
cd day9 && pip install -r requirements.txt
cd day10 && pip install -r requirements.txt
cd day11 && pip install -r requirements.txt
```

День 13 и последующие дни зависимости ведут через **uv** (`pyproject.toml` +
`uv.lock` + `.python-version`; `requirements.txt` там нет): установка — `uv sync`
из папки дня, запуск — `uv run <команда>`. Правило для новых дней и порядок
миграции — в `AGENTS.md`, раздел «Зависимости: uv»; если `uv` ещё не установлен —
`irm https://astral.sh/uv/install.ps1 | iex`.

Для дня 2 локально доступно готовое виртуальное окружение `day2/.venv` —
его можно переиспользовать и для дня 3; у дня 5 своё окружение `day5/.venv`
(streamlit + huggingface_hub), у дня 6 — `day6/.venv` (fastapi + streamlit).
Дни 7–11 отдельного окружения в репозитории не имеют: создайте его командой
`python -m venv .venv` из папки дня (см. `README.md` дня) — в окружениях дней
9, 10 и 11 дополнительно нужен `pytest` для автотестов.

День 4 — документный день без кода: `requirements.txt` для него нет, а результат
эксперимента лежит в `day4/results.md`.

### 2. Инструменты разработки (глобально, один раз)

```bash
# терминальный агент omp.sh — правила берёт из .clauderules и AGENTS.md,
# настройки проекта — из .omp/config.yml
pip install pyright debugpy                  # Python LSP и дебаггер для агента
```

> Правила и настройки уже лежат в репозитории (`.clauderules`, `AGENTS.md`,
> `.omp/config.yml`); повторная настройка нужна только на новой машине.

Отдельно один раз на машине создайте файл `~/.omp/agent/models.yml` — он
включает приём изображений для DeepSeek V4.1 Flash (во вшитом в omp 18.1.21
каталоге модель помечена как текстовая, хотя зрение у неё есть):

```yaml
# ~/.omp/agent/models.yml
providers:
  deepseek:
    modelOverrides:
      deepseek-flash:
        input: [text, image]
        compat:
          stripImageInput: false
      deepseek-v4-flash:
        input: [text, image]
        compat:
          stripImageInput: false
```

## Как запустить

Ключ ищется в порядке: файл `.env` рядом с приложением → переменная окружения →
ручной ввод (в консоли или в поле-пароле интерфейса). Дни 1–4 используют
`DEEPSEEK_API_KEY`, день 5 — `HF_TOKEN`; детали — в README папки дня.

```bash
# День 1 — консольный чат (из папки day1)
pip install -r requirements.txt
python deepseek_chat.py

# День 2 — «Формат ответа» (из папки day2)
pip install -r requirements.txt
streamlit run app.py

# День 3 — «Способы рассуждения ИИ» (из папки day3)
pip install -r requirements.txt
streamlit run app.py

# День 5 — «Сравнение моделей Hugging Face» (из папки day5)
pip install -r requirements.txt
streamlit run app.py

# День 9 — «Сжатие истории» (из папки day9): сначала бэкенд, потом UI
pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000   # терминал 1
streamlit run app.py                             # терминал 2
python -m pytest -q                              # автотесты дня 9 (167 тестов)

# День 11 — «Трёхслойная модель памяти агента» (из папки day11)
pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000   # терминал 1
streamlit run app.py                             # терминал 2
python -m pytest -q                              # автотесты дня 11 (235 тестов)
python memory_layers_demo.py                     # офлайн-прогон по слоям, без сети

# День 12 — «Персонализация: профиль пользователя» (из папки day12)
pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000   # терминал 1
streamlit run app.py                             # терминал 2
python -m pytest -q                              # автотесты дня 12 (314 тестов)
python personalization_comparison.py             # сравнение профилей (нужен ключ)
python personalization_comparison.py --no-api    # то же офлайн, без сети

# День 13 — «Состояние задачи как FSM» (из папки day13, зависимости — uv)
uv sync
uv run uvicorn backend.api.main:app --port 8000       # терминал 1
uv run streamlit run app.py                           # терминал 2
uv run pytest -q                                      # автотесты дня 13 (584 теста)
uv run python scripts/task_state_demo.py --all        # 5 фаз в 5 процессах (нужен ключ)
uv run python scripts/task_state_demo.py --all --no-api  # то же офлайн, без сети
```

> **Важно:** приложение ищет `.env` в текущей рабочей директории, поэтому
> `streamlit run` выполняйте **из самой папки дня**. Приложения дня 2/3
> импортируют общий пакет `shared/` из корня репозитория — не удаляйте его;
> день 5 автономен (`shared/` не использует).

День 4 — не приложение, а документный день: эксперимент с `temperature` уже
выполнен, результаты открываются в `day4/results.md` (запуск не требуется).

День 5 можно запустить из готового окружения (PowerShell, из папки `day5`):
`.venv\Scripts\streamlit run app.py`.

Дни 6–13 запускаются так же, как день 9, но одним приложением: бэкенд
`uvicorn backend.main:app --port 8000` из папки дня и `streamlit run app.py`
во втором терминале.

После рефакторинга дня 12 **команды запуска не изменились**: `backend.main:app`
собирает приложение из роутеров `backend/routers/`, а `app.py` вызывает секции
пакета `ui/`. В дне 13 раскладка доведена до слоёв: точка входа —
`backend.api.main:app`, роутеры — `backend/api/`, ORM — `backend/models/*.py`,
схемы API — `backend/schemas/`, интерфейс — `frontend/`, прогоны демонстраций —
`scripts/` (отчёты — в `docs/reports/`), тесты — `tests/{unit,integration,e2e}/`.
День 13 добавляет раздел «🧭 Состояние задачи».
Команды и проверки — в [docs/usage.md](docs/usage.md),
раскладка модулей — в [day13/STRUCTURE.md](day13/STRUCTURE.md).

## Секреты

- Файлы `.env` **не коммитятся** (правило в корневом `.gitignore`).
- В git хранятся только шаблоны `.env.example` (по одному на день).
- Ключ DeepSeek начинается с `sk-`; заглушки вида `sk-вставьте-сюда-ваш-ключ`
  приложения распознают как неподходящие и запрашивают настоящий ключ.
- Токен Hugging Face (день 5) начинается с `hf_`; тоже хранится только в
  gitignored-файле `.env` (переменная `HF_TOKEN`).

## Процесс разработки

Проект ведётся вместе с терминальным агентом **omp.sh**. Перед стартом агент
автоматически читает два файла из корня:

- [`.clauderules`](.clauderules) — полный свод правил: стек, конвенции кодинга,
  рабочий процесс, команды проверки, секреты и Git, стиль ответов.
- [`AGENTS.md`](AGENTS.md) — архитектурные цели: стейт-машина на Python, правила
  работы с `Enum` и паттерном State, запуск тестов через `pytest`. Процедурные
  правила (FSM, раскладка файлов дня, `shared/`, TDD, документация дня) вынесены
  в скиллы — раздел «Скиллы проекта».

Кроме правил из корня, omp.sh подгружает **скиллы** проекта из
[`.omp/skills/`](.omp/skills/): при старте читаются только их метаданные
(`name` + `description`), а полный текст скилла подставляется **лениво** — когда
задача совпала с его триггерами (плюс он доступен явно по `skill://<name>` и
через `/skill:<name>`). Поэтому в `AGENTS.md` лежат цели и границы, а процедуры —
в самих скиллах, без дублирования. Список скиллов проекта — в `AGENTS.md`,
раздел «Скиллы проекта».

Конфигурация агента — [`.omp/config.yml`](.omp/config.yml): модель по умолчанию
`deepseek/deepseek-flash` (DeepSeek V4.1 Flash) и её роли (`smol`, `slow`, `plan`,
`task`, `vision`). Файл `.omp.json` в корне omp не читает: настройки проекта
живут только в `.omp/config.yml`, глобальные — в `~/.omp/agent/config.yml`.

Метаданные моделей уточняются в `~/.omp/agent/models.yml` — файл
пользовательский, в репозиторий не попадает. Там для `deepseek-flash` включён
приём изображений: V4.1 Flash умеет зрение, а каталог omp 18.1.21 считает этот SKU
текстовым. Python LSP (`pyright`) и дебаггер `debugpy` берутся из встроенных
настроек omp — отдельная конфигурация для них не нужна.

### Как проходит работа

1. **Разведка и план** — агент читает файлы дня и `AGENTS.md`, предлагает план.
2. **Реализация по TDD** — сначала падающий тест (`pytest`), затем реализация до
   зелёного; изменения минимальны и в рамках задачи.
3. **Проверка перед «готово»** — `py_compile`, `pytest`, smoke-запуск приложения
   (см. `.clauderules`, раздел «Проверки перед завершением»).

### Где искать контекст

- Правила проекта и конвенции по коду: `.clauderules`.
- Архитектурные цели и стандарт тестов: `AGENTS.md`.
- Процедурные правила (FSM, раскладка файлов дня, `shared/`, TDD, документация
  дня): скиллы в `.omp/skills/` — список в `AGENTS.md`, раздел «Скиллы проекта».
- Описание конкретного дня: `README.md` и `docs/` внутри папки дня
  (например, `day6/docs/`).

