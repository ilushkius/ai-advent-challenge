# AI-челлендж

Персональный практикум по большим языковым моделям (LLM) и промпт-инжинирингу на
реальных API: **DeepSeek** (OpenAI-совместимый endpoint) и **Hugging Face**
(Inference Providers). Каждый день — одно
небольшое, самодостаточное приложение в папке `dayN/`.

Проект ведётся вместе с Cline по spec-driven процессу **OpenSpec**
(см. [Процесс разработки](#процесс-разработки) и [`docs/development.md`](docs/development.md)).

## Структура проекта

| Папка | Что это | Назначение |
|---|---|---|
| `day1/` | **День 1 · «Первый запрос к DeepSeek»** | Консольный потоковый чат с моделью `deepseek-chat` (`deepseek_chat.py`) |
| `day2/` | **День 2 · «Формат ответа»** | Streamlit-демо управления генерацией: `temperature`, `seed`, `max_tokens`, `stop`, JSON-режим (`app.py`) |
| `day3/` | **День 3 · «Способы рассуждения ИИ»** | Streamlit-демо: Zero-Shot, Chain-of-Thought, мета-промпт, «консилиум экспертов» (`app.py`) |
| `day4/` | **День 4 · «Эксперимент с температурой»** | Документный день (без кода): сравнение ответов `deepseek-chat` при `temperature` 0 / 0.7 / 1.2 с оценками и выводами (`results.md`) |
| `day5/` | **День 5 · «Сравнение моделей Hugging Face»** | Streamlit-приложение: один запрос через три модели HF разного размера (8B / 70B / 235B), метрики, оценка качества 0–10, отчёт (`app.py`) |
| `shared/` | Общие утилиты | Чтение API-ключа, разбор stop-строк, `usage_to_dict`, endpoint DeepSeek (`deepseek_utils.py`) |
| `openspec/` | Спецификации проекта | `specs/` — эталонные capability-спеки; `changes/` — изменения (active/archive); `config.yaml` — контекст и правила |
| `docs/` | Документация | `development.md` — процесс разработки (OpenSpec + Superpowers + Caveman) |
| `.clinerules/` | Правила Cline | Индекс навыков Superpowers, автоактивация Caveman, workflow-команды `opsx-*`, указатель на OpenSpec-процесс |
| `.cline/skills/` | Навыки Cline | Тела навыков Superpowers и OpenSpec (SKILL.md) |
| `.agents/skills/` | Навыки Caveman | 20 навыков Caveman (универсальное расположение `npx skills add`) |

## Стек технологий

| Слой | Технология | Где используется |
|---|---|---|
| Язык | Python 3.14+ (Windows, PowerShell, VS Code) | все дни |
| UI демо | Streamlit ≥ 1.30 (day2/.venv — 1.62.0; day5/.venv — 1.63.0) | day2, day3, day5 |
| API DeepSeek | официальный OpenAI SDK (`openai>=1.40.0`, установлен 3.6.0), `base_url=https://api.deepseek.com` | day1–day4 |
| API Hugging Face | `huggingface_hub>=0.24` (установлен 1.30.0): `InferenceClient.chat_completion` через роутер Inference Providers | day5 |
| Модели | DeepSeek: `deepseek-chat` (основная), `deepseek-reasoner` (ограничения: может игнорировать `temperature`/`response_format`); HF (день 5): `Llama-3.1-8B-Instruct`, `Llama-3.3-70B-Instruct`, `Qwen3-235B-A22B-Instruct-2507` | все дни |
| Виртуальные окружения | `day2/.venv` (streamlit 1.62.0, openai 3.6.0); `day5/.venv` (streamlit 1.63.0, huggingface_hub 1.30.0) | day2–day3, day5 |
| Инструменты разработки | OpenSpec CLI 1.11, Superpowers-ZH (20 навыков), Caveman (20 навыков), Node.js 24 / npm | спецификации и AI-воркфлоу |

Код дней 1–4 написан в синтаксисе, совместимом с OpenAI SDK 1.x/2.x/3.x
(`OpenAI(api_key=..., base_url=...)`); день 5 использует
`huggingface_hub.InferenceClient`. Автотестов, линтеров и CI в проекте нет
(см. [docs/development.md](docs/development.md#проверка-качества)).

## Требования

- Windows, **Python 3.14+** и `pip`.
- API-ключ DeepSeek (https://platform.deepseek.com → API Keys).
- Для дня 5: токен Hugging Face (`hf_...`, https://huggingface.co/settings/tokens);
  бесплатные аккаунты HF получают небольшие месячные включённые кредиты Inference
  Providers (~$0.10), при исчерпании — ошибка 402.
- Для OpenSpec/инструментов: **Node.js 18+** и `npm`.

## Установка

### 1. Зависимости приложений (Python)

У каждого прикладного дня свой `requirements.txt` — устанавливайте из папки дня:

```bash
cd day1 && pip install -r requirements.txt
cd day2 && pip install -r requirements.txt
cd day3 && pip install -r requirements.txt
cd day5 && pip install -r requirements.txt
```

Для дня 2 локально доступно готовое виртуальное окружение `day2/.venv` —
его можно переиспользовать и для дня 3; у дня 5 своё окружение `day5/.venv`
(streamlit + huggingface_hub).

День 4 — документный день без кода: `requirements.txt` для него нет, а результат
эксперимента лежит в `day4/results.md`.

### 2. Инструменты разработки (глобально, один раз)

```bash
npm install -g @fission-ai/openspec@latest   # OpenSpec CLI (проверка: openspec --version)
npx superpowers-zh --tool cline              # навыки Superpowers → .cline/skills/
npx skills add JuliusBrussee/caveman -a cline --with-init   # Caveman + автоактивация
openspec init --tools cline                  # структура openspec/ и воркфлоу для Cline
```

> В этом репозитории инструменты уже установлены и настроены; повторная
> установка нужна только на новой машине.

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
```

> **Важно:** приложение ищет `.env` в текущей рабочей директории, поэтому
> `streamlit run` выполняйте **из самой папки дня**. Приложения дня 2/3
> импортируют общий пакет `shared/` из корня репозитория — не удаляйте его;
> день 5 автономен (`shared/` не использует).

День 4 — не приложение, а документный день: эксперимент с `temperature` уже
выполнен, результаты открываются в `day4/results.md` (запуск не требуется).

День 5 можно запустить из готового окружения (PowerShell, из папки `day5`):
`.venv\Scripts\streamlit run app.py`.

## Секреты

- Файлы `.env` **не коммитятся** (правило в корневом `.gitignore`).
- В git хранятся только шаблоны `.env.example` (по одному на день).
- Ключ DeepSeek начинается с `sk-`; заглушки вида `sk-вставьте-сюда-ваш-ключ`
  приложения распознают как неподходящие и запрашивают настоящий ключ.
- Токен Hugging Face (день 5) начинается с `hf_`; тоже хранится только в
  gitignored-файле `.env` (переменная `HF_TOKEN`).

## Процесс разработки

Проект ведётся по spec-driven процессу **OpenSpec** с навыками Superpowers и
Caveman. Каждое изменение проходит ритуал:

1. `/opsx:propose <задача>` — создать change: `proposal.md`, `specs/` (дельты),
   `design.md`, `tasks.md`. Пишется только план, код не трогается.
2. `/opsx:apply` — реализация задач по TDD (Superpowers), проверка перед
   завершением (`verification-before-completion`).
3. `/opsx:archive` — архивация change и слияние дельт в основные спецификации
   `openspec/specs/`.

Полное описание — в [`docs/development.md`](docs/development.md).

### Где искать контекст

- Поведение проекта: `openspec/specs/<capability>/spec.md`
  (`project`, `architecture`, `tech-stack`, `day1-console-chat`,
  `day2-response-format`, `day3-reasoning-methods`,
  `day4-temperature-experiment`, `day5-model-comparison`).
- Конвенции и стек: `openspec/config.yaml` (раздел `context`).
- Правила Cline: `.clinerules/` (индекс Superpowers `superpowers-zh.md`,
  автоактивация Caveman `caveman.md`, workflow-команды `workflows/opsx-*.md`,
  общий процесс `openspec-workflow.md`).

### Навыки и режимы

- **Superpowers** — 20 навыков в `.cline/skills/` (TDD, планирование, ревью,
  отладка). Активируются по триггерам из индекса `.clinerules/superpowers-zh.md`.
- **Caveman** — экономит токены ответов. Автоактивируется в каждой сессии
  (правило `.clinerules/caveman.md`, режим `full`). Сменить режим:
  `/caveman lite|ultra|off`. Код/коммиты/документация пишутся обычным языком.

