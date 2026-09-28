# AI-челлендж

## О проекте

Персональный практикум по LLM и промпт-инжинирингу на реальных API: **DeepSeek**
(OpenAI-совместимый endpoint) и **Hugging Face**. Челлендж рассчитан на 35 дней;
сейчас пройден день 21, и в нём собрана агентная система: агент с трёхслойной
памятью и профилем пользователя, состояние задачи как конечный автомат (FSM),
инварианты, MCP-клиент и флот MCP-серверов, планировщик фоновых задач,
декларативные пайплайны и оркестрация, поиск по индексу документов (RAG на FAISS)
и оптимизация затрат на LLM. Проект ведётся вместе с терминальным агентом **omp.sh**.

## Структура репозитория

| Путь | Что это |
|---|---|
| **`day21/`** | **Основная рабочая папка.** Вся разработка идёт здесь: приложение дня 21 (индексация документов + оптимизация затрат) поверх агента дня 20 |
| `day1/`–`day20/` | **Архив — снимки прошлых дней.** Код не изменяется; папки оставлены как история, ссылки на них рабочие (см. таблицу ниже) |
| `shared/` | Общие модули, не меняющиеся между днями (`deepseek_client`, `db_base`, `token_counter`, `logging_utils`, `deepseek_utils`) |
| `docs/` | Документация проекта: [`architecture.md`](docs/architecture.md) (устройство), [`usage.md`](docs/usage.md) (как пользоваться), [`project-rules.md`](docs/project-rules.md) (архитектурные цели, раскладка слоёв, история расхождений) |
| `openspec/changes/` | Черновики спецификаций изменений |
| `ARCHITECT_PROMPT.md` | Шаблон архитектурного планирования: превращает «сырое» задание в структурированный план (DoD, шаги, риски, проверки, команды git) |
| `WORKFLOW.md` | Рабочий процесс: сырое задание → план → исполнение → фиксация |
| `AGENTS.md` | Правила для AI-агентов (короткий always-apply файл): границы, тесты, документация, git |
| `RULES.md` | Sticky-правила (переприкрепляются к каждому запросу), максимум 15 строк |
| `CHANGELOG.md` | История изменений по дням (дата, тип, что затронуто) |
| `.clauderules` | Полный свод конвенций проекта: стек, стиль, команды проверки, секреты |
| `.clineignore`, `.gitignore` | Исключения для инструментов: архив дней, служебные и тяжёлые файлы |
| `.omp/config.yml`, `.omp/skills/` | Настройки агента и скиллы проекта (FSM, раскладка дня, `shared/`, TDD, документация дня) |

**Главное правило проекта:** разработка идёт в **одной** папке `day21/`, новые
папки `dayN` не создаются, а история версий фиксируется **git-коммитами и
тегами** (`day21-optimized`, `day21-docs` и т. д.). Поэтому ссылки вида
`day21/...` стабильны.

### Архив дней (day1–day20)

Одна строка на день; подробности — в `CHANGELOG.md` и в `README.md` самой папки.

| День | Тема |
|---|---|
| `day1/` | Первый запрос к DeepSeek: консольный потоковый чат |
| `day2/` | Формат ответа: `temperature`, `seed`, JSON-режим |
| `day3/` | Способы рассуждения: zero-shot, chain-of-thought, «консилиум» |
| `day4/` | Эксперимент с температурой (документный день, без кода) |
| `day5/` | Сравнение моделей Hugging Face (8B / 70B / 235B) |
| `day6/` | Менеджер агентов DeepSeek (FastAPI + Streamlit) |
| `day7/` | Агент с контекстной памятью (SQLite) |
| `day8/` | Агент с контролем токенов (tiktoken, автообрезка истории) |
| `day9/` | Управление контекстом: сжатие истории, первая FSM и первые `pytest` |
| `day10/` | Стратегии сборки контекста (sliding window, sticky facts, branching, summary) |
| `day11/` | Трёхслойная модель памяти агента |
| `day12/` | Персонализация: профиль пользователя |
| `day13/` | Состояние задачи как FSM; раскладка дня по слоям |
| `day14/` | Инварианты агента: правила проекта, проверка запроса и ответа |
| `day15/` | Контролируемые переходы состояния: граф `ALLOWED_TRANSITIONS`, guards, журнал отказов |
| `day16/` | MCP-клиент: подключение к внешнему серверу и каталог инструментов |
| `day17/` | Свой MCP-сервер и вызов инструмента из агента |
| `day18/` | Планировщик фоновых задач (APScheduler) и MCP-инструменты с периодами |
| `day19/` | Декларативный пайплайн композиции MCP-инструментов |
| `day20/` | Оркестрация флота из трёх MCP-серверов |
| **`day21/`** | **Индексация документов (две стратегии чанкинга, FAISS + SQLite) и оптимизация затрат на LLM** |

## Быстрый старт

Все команды — из папки дня (`day21/`), потому что приложение ищет `.env`
в текущей рабочей директории.

```bash
cd day21
uv sync                                   # зависимости из pyproject.toml + uv.lock
copy .env.example .env                    # затем впишите DEEPSEEK_API_KEY=sk-...

uv run uvicorn backend.api.main:app --port 8000   # терминал 1 — бэкенд
uv run streamlit run app.py                       # терминал 2 — интерфейс (localhost:8501)

uv run pytest -m "not slow"    # быстрый прогон тестов при разработке (~30 с)
uv run pytest                  # то же самое: -m "not slow" уже стоит в pytest.ini
uv run pytest -m ""            # полный прогон, все тесты (~70 с)
```

Первый запуск скачивает веса модели эмбеддингов (~470 МБ) в `day21/index/models/`
— это кэш Hugging Face, в Git он не попадает. Ключ DeepSeek нужен для чата; сама
индексация работает и без ключа.

## Как работать над новым днём

1. **Возьмите задание** из челленджа (или из промпта другой нейросети) — как есть.
2. **Сложную задачу сначала спланируйте.** Откройте
   [`ARCHITECT_PROMPT.md`](ARCHITECT_PROMPT.md), вставьте задание в поле
   `{{ЦЕЛЬ}}` и отправьте в **отдельный чат с DeepSeek**: на выходе — декомпозиция
   с Definition of Done, пошаговый план, риски и план Б, проверки и команды
   фиксации.
3. **Передайте план в omp.sh** как промпт дня: агент работает в `day21/` и
   исполняет пункты плана, а не пересказ задания.
4. **Зафиксируйте результат:** `git commit -m "dayN: краткое описание"`,
   `git tag dayN`, затем обновите документацию дня (только текущее состояние).

Сложные задачи (нужен архитектурный этап): новые модули и слои, интеграции,
изменения архитектуры, работа с MCP, планировщик, индексация, оптимизация затрат.
Простые задачи (кнопка, текст, правка документации) можно делать сразу.
Подробности и пример полного цикла — в [`WORKFLOW.md`](WORKFLOW.md).

## Документация

| Где | Что искать |
|---|---|
| [`ARCHITECT_PROMPT.md`](ARCHITECT_PROMPT.md) | Шаблон архитектурного планирования задания |
| [`WORKFLOW.md`](WORKFLOW.md) | Рабочий процесс: задание → план → исполнение → коммит с тегом |
| [`AGENTS.md`](AGENTS.md) | Короткие правила для AI-агентов (always-apply) |
| [`RULES.md`](RULES.md) | Sticky-правила (≤ 15 строк) |
| [`docs/project-rules.md`](docs/project-rules.md) | Архитектурные цели проекта, раскладка слоёв, лимиты, история расхождений со снимками |
| [`docs/architecture.md`](docs/architecture.md) | Как устроен общий код и `shared/` |
| [`docs/usage.md`](docs/usage.md) | Инструкция по работе с проектом |
| [`day21/docs/architecture.md`](day21/docs/architecture.md) | Техническая архитектура текущего дня (+ тестовая инфраструктура) |
| [`day21/docs/usage.md`](day21/docs/usage.md) | Инструкция текущего дня (индексация, расходы, тесты, workflow) |
| [`day21/README.md`](day21/README.md) | День 21 целиком: что сделано, как запустить, как работать над следующим |
| [`day21/WORKFLOW.md`](day21/WORKFLOW.md) | Короткая ссылка на корневой `WORKFLOW.md` + специфика дня |
| [`day21/STRUCTURE.md`](day21/STRUCTURE.md) | Карта модулей дня 21: что где лежит |
| [`day21/docs/reports/`](day21/docs/reports/) | Отчёты прогонов: индексация, стоимость, экономия контекста, тесты |
| [`CHANGELOG.md`](CHANGELOG.md) | История изменений по дням |

## Стек технологий

| Слой | Технология |
|---|---|
| Язык и окружение | Python 3.14+ (Windows), зависимости — `uv` (`pyproject.toml` + `uv.lock` + `.python-version`); у снимков `day1`–`day12` — `pip` + `requirements.txt` |
| API | FastAPI + Uvicorn; клиент моделей — OpenAI SDK (`base_url=https://api.deepseek.com`); MCP Python SDK |
| UI | Streamlit (разделы-секции в `frontend/`) |
| Хранилище | SQLite + SQLAlchemy 2.0 |
| Токены и стоимость | `tiktoken` (`shared/token_counter.py`), формулы стоимости в домене дня |
| Поиск | `sentence-transformers` (эмбеддинги, локально), FAISS (`faiss-cpu`) |
| Фон и планирование | APScheduler, фоновые потоки FastAPI, MCP-серверы по stdio |
| Тесты | `pytest` + `pytest-xdist` (параллельно, `-n auto`) + `pytest-cov` (покрытие) |
| Агент | omp.sh (модель `deepseek/deepseek-flash`), скиллы проекта в `.omp/skills/` |

## Требования

- Windows, **Python 3.14+**, менеджер зависимостей **`uv`**
  (`irm https://astral.sh/uv/install.ps1 | iex`).
- API-ключ DeepSeek (<https://platform.deepseek.com> → API Keys) — для чата,
  сводок и плана оркестрации.
- ~1,5 ГБ диска: `torch` и веса модели эмбеддингов (~470 МБ) для индексации.
- Для агента omp.sh: CLI `omp`, Python LSP `pyright`, дебаггер `debugpy`.

## Установка зависимостей

```bash
# День 13 и далее (включая day21) — uv
cd day21 && uv sync

# Снимки day1–day12 — pip
cd day5 && pip install -r requirements.txt   # и так для любого дня-снимка
```

Скиллы библиотек (FastAPI, Streamlit) отслеживаются командой
`uvx library-skills --check --tool-skill` из папки дня: симлинки лежат в
`dayN/.agents/skills/` и коммитятся в Git.

## Запуск архивных дней

Снимки `day1`–`day13` запускаются каждый по своему README — команды там
актуальны и не менялись. Общая схема:

```bash
# day1 — консольный чат
cd day1 && pip install -r requirements.txt && python deepseek_chat.py

# day2, day3, day5 — Streamlit-демо одним процессом
cd day5 && pip install -r requirements.txt && streamlit run app.py

# day6–day12 — бэкенд и интерфейс в двух терминалах
cd day9 && pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000   # терминал 1
streamlit run app.py                             # терминал 2

# day13 и далее — uv, точка входа backend.api.main:app
cd day13 && uv sync && uv run uvicorn backend.api.main:app --port 8000
```

`day4` — документный день без кода: результат в `day4/results.md`. Файлы `.env`
приложения ищут в текущей рабочей директории, поэтому команды выполняйте из папки
дня; приложения дней 2 и 3 импортируют `shared/` из корня (не удаляйте его).

## Секреты

- Файлы `.env` **не коммитятся** (правило в корневом `.gitignore`); в Git лежат
  только шаблоны `.env.example` — по одному на день.
- Ключ DeepSeek начинается с `sk-`; заглушки вида `sk-вставьте-сюда-ваш-ключ`
  приложения распознают как неподходящие.
- Токен Hugging Face (день 5) начинается с `hf_` и хранится только в `.env`
  (`HF_TOKEN`).

## Процесс разработки (omp.sh)

Перед стартом агент автоматически читает правила из корня:

- [`AGENTS.md`](AGENTS.md) — короткие always-apply правила: где работаем,
  что не читать (архив), как фиксировать результат;
- [`RULES.md`](RULES.md) — sticky-правила (переприкрепляются к каждому запросу);
- [`docs/project-rules.md`](docs/project-rules.md) — архитектурные цели и
  раскладка слоёв (полная версия прежнего `AGENTS.md`);
- [`.clauderules`](.clauderules) — конвенции кода, команды проверок, секреты;
- [`.omp/config.yml`](.omp/config.yml) — модель по умолчанию и роли моделей;
- [`.omp/skills/`](.omp/skills/) — скиллы проекта (FSM, раскладка файлов дня,
  `shared/`, TDD, документация дня): читаются лениво, по триггерам задачи.

Метаданные моделей уточняются в `~/.omp/agent/models.yml` (файл пользовательский,
в репозиторий не попадает) — там для `deepseek-flash` включён приём изображений,
потому что у модели есть зрение, а встроенный каталог omp считает этот SKU
текстовым:

```yaml
providers:
  deepseek:
    modelOverrides:
      deepseek-flash:
        input: [text, image]
        compat:
          stripImageInput: false
```

### Как проходит работа

1. **Разведка и план** — агент читает файлы дня и правила проекта.
2. **Планирование сложной задачи** — через [`ARCHITECT_PROMPT.md`](ARCHITECT_PROMPT.md)
   (см. [`WORKFLOW.md`](WORKFLOW.md)).
3. **Реализация по TDD** — сначала падающий тест (`pytest`), затем реализация до
   зелёного; изменения минимальны и в рамках задачи.
4. **Проверка перед «готово»** — тесты дня, `py_compile` изменённых файлов,
   smoke-запуск приложения, лимиты строк.

### Где искать контекст

- Правила дня: `day21/AGENTS.md` и `day21/.omp/RULES.md` (для сессий из `day21/`).
- Правила проекта: `AGENTS.md`, `RULES.md`, `docs/project-rules.md`,
  `.clauderules`, скиллы в `.omp/skills/`.
- Устройство и инструкции дня: `day21/README.md`, `day21/docs/`,
  `day21/STRUCTURE.md`.
- История: `CHANGELOG.md` и `README.md` конкретного дня.

## Общие модули (`shared/`)

`shared/` — код, который не меняется между днями: день добавляет корень
репозитория в `sys.path` и импортирует модули как `from shared.<module> import ...`.

| Модуль | Что делает |
|---|---|
| `shared/deepseek_utils.py` | Endpoint DeepSeek, ключ из `.env`, stop-строки, `usage_to_dict` |
| `shared/deepseek_client.py` | `make_client(api_key, base_url, timeout)` — клиент OpenAI SDK (ленивый импорт) |
| `shared/db_base.py` | SQLAlchemy: `Base`, `make_engine`, `init_db`, `make_session_factory` |
| `shared/token_counter.py` | `count_tokens` через tiktoken (`cl100k_base`, кодировка кэшируется) |
| `shared/logging_utils.py` | `get_logger`, `configure_logging` |

Модули `shared/` подключают дни 2, 3 (частично) и все дни с `day13`; подробнее —
[`docs/architecture.md`](docs/architecture.md) и [`docs/usage.md`](docs/usage.md).

## Проверки перед «готово»

```bash
cd day21
uv run pytest -m ""                        # весь набор тестов (~70 с)
uv run pytest -m "" --cov=backend --cov-report=html   # покрытие → htmlcov/index.html
uv run python -m py_compile <изменённые .py>          # синтаксис
```

Лимиты структуры: любой `.py` ≤ 400 строк, `app.py` ≤ 100,
`backend/api/main.py` ≤ 80 — правила в [`docs/project-rules.md`](docs/project-rules.md),
проверка описана в скилле `fastapi-streamlit-day-structure`.
