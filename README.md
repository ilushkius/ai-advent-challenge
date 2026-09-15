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
| `day12/` | **День 12 · «Персонализация: профиль пользователя»** | FastAPI + Streamlit + SQLite + tiktoken: структура дня 11 (три слоя памяти, четыре стратегии контекста) плюс персонализация — таблица `user_profiles` (`preferences`: tone/verbosity/language/format, `constraints`: max_response_length/forbidden_topics/required_disclaimers, `custom_instructions`), блок профиля в системном промпте КАЖДОГО запроса, пять эндпоинтов `/users...` + `GET /agents/{id}/profile`, поля `profile` и `system_prompt` в ответе генерации, раздел «👤 Профиль пользователя» в UI с готовыми профилями и сравнением двух профилей на одном вопросе, отчёт `personalization_comparison.md`; тестовый сценарий дня 11 удалён |
| `shared/` | Общие утилиты | Чтение API-ключа, разбор stop-строк, `usage_to_dict`, endpoint DeepSeek (`deepseek_utils.py`) |
| `.clauderules` | Правила проекта для агента | Свод правил ai-challenge: стек, конвенции, процесс, проверки, секреты |
| `AGENTS.md` | Архитектурные цели | Стейт-машина на Python, `Enum` + паттерн State, тесты через `pytest` |
| `.omp/config.yml` | Конфигурация omp.sh | Модель по умолчанию — `deepseek/deepseek-flash` (DeepSeek V4.1 Flash) и роли моделей |

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
| Стейт-машина | `enum.Enum` + паттерн State (чистый Python, `backend/context_fsm.py`) — первая реализация архитектурной цели `AGENTS.md` | day9 |
| Тесты | `pytest` (день 9: 167 тестов — FSM, политика сжатия, хранилище, компрессор, агент, API; день 10: 193 — стратегии, факты, ветки, FSM, хранилище, API; день 11: 235 — слои памяти, API `/memory/...`, стратегии, факты, ветки, FSM, хранилище, компрессор, API; день 12: 314 — профили пользователей, промпт персонализации, API `/users...`, плюс всё из дня 11) | day9–day12 |
| Виртуальные окружения | `day2/.venv` (streamlit 1.62.0, openai 3.6.0); `day5/.venv` (streamlit 1.63.0, huggingface_hub 1.30.0); `day6/.venv` (fastapi, streamlit, openai, requests); `day9/.venv` (fastapi, sqlalchemy, tiktoken, pytest и др.) | day2–day3, day5, day6, day9 |
| Инструменты разработки | терминальный агент **omp.sh** (модель `deepseek/deepseek-flash` — DeepSeek V4.1 Flash), Python LSP `pyright`, `debugpy` | AI-воркфлоу |

Код дней 1–4 и 6–9 написан в синтаксисе, совместимом с OpenAI SDK 1.x/2.x/3.x
(`OpenAI(api_key=..., base_url=...)`); день 5 использует
`huggingface_hub.InferenceClient`; день 7 добавляет слой персистентности
(SQLAlchemy 2.0 + SQLite), день 8 — подсчёт токенов (tiktoken) и таблицу
`token_usage`, день 9 — сжатие истории (таблица `summaries`, конспект вместо
старых реплик), стейт-машину на `Enum` + паттерн State и первые автотесты
`pytest`. Автотесты есть у дней 9–12 (`day9/tests/` — 167 тестов,
`day10/tests/` — 193, `day11/tests/` — 235, `day12/tests/` — 314); для остальных прикладных дней
проверка — `py_compile` и smoke-запуск, а целевой стандарт новых дней —
`pytest` (см. [AGENTS.md](AGENTS.md)).

## Требования

- Windows, **Python 3.14+** и `pip`.
- API-ключ DeepSeek (https://platform.deepseek.com → API Keys).
- Для дня 5: токен Hugging Face (`hf_...`, https://huggingface.co/settings/tokens);
  бесплатные аккаунты HF получают небольшие месячные включённые кредиты Inference
  Providers (~$0.10), при исчерпании — ошибка 402.
- Для агента **omp.sh**: CLI omp.sh, Python LSP `pyright` и дебаггер `debugpy`
  (`pip install pyright debugpy`).

## Установка

### 1. Зависимости приложений (Python)

У каждого прикладного дня свой `requirements.txt` — устанавливайте из папки дня:

```bash
cd day1 && pip install -r requirements.txt
cd day2 && pip install -r requirements.txt
cd day3 && pip install -r requirements.txt
cd day5 && pip install -r requirements.txt
cd day9 && pip install -r requirements.txt
cd day10 && pip install -r requirements.txt
cd day11 && pip install -r requirements.txt
```

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
```

> **Важно:** приложение ищет `.env` в текущей рабочей директории, поэтому
> `streamlit run` выполняйте **из самой папки дня**. Приложения дня 2/3
> импортируют общий пакет `shared/` из корня репозитория — не удаляйте его;
> день 5 автономен (`shared/` не использует).

День 4 — не приложение, а документный день: эксперимент с `temperature` уже
выполнен, результаты открываются в `day4/results.md` (запуск не требуется).

День 5 можно запустить из готового окружения (PowerShell, из папки `day5`):
`.venv\Scripts\streamlit run app.py`.

Дни 6–12 запускаются так же, как день 9, но одним приложением: бэкенд
`uvicorn backend.main:app --port 8000` из папки дня и `streamlit run app.py`
во втором терминале.

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
  работы с `Enum` и паттерном State, запуск тестов через `pytest`.

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
- Описание конкретного дня: `README.md` и `docs/` внутри папки дня
  (например, `day6/docs/`).

