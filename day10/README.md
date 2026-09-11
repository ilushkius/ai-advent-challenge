# День 10 — Стратегии управления контекстом (FastAPI + Streamlit + SQLite + tiktoken)

Приложение развивает день 9: агент по-прежнему ведёт **полный диалог с памятью**
(SQLite, история переживает рестарт) и умеет **сжимать историю** конспектом, но
теперь сборкой контекста для запроса управляет **одна из четырёх стратегий** —
переключается на живом агенте, без потери диалога.

## Управление контекстом

Атрибут агента `strategy` принимает одно из четырёх значений (`Enum Strategy`,
`backend/strategies.py`); сборка контекста — метод `Agent.prepare_context()`:

| Стратегия | Что уходит в DeepSeek | Сильная сторона |
|---|---|---|
| 🪟 `sliding_window` | системный промпт + последние `window_size` реплик | самый дешёвый и предсказуемый |
| 📌 `sticky_facts` | системный промпт (+факты «ключ: значение») + последние N | детали не теряются — факты хранятся в таблице `facts` |
| 🌿 `branching` | системный промпт + вся история активной ветки | ничего не теряет + ветвление диалога (`checkpoints`) |
| 🗜 `summary` | системный промпт (+конспект) + последние непокрытые реплики | сбалансированный компромисс (день 9) |

Переключатель — в сайдбаре («⚙️ Стратегия контекста»): выпадающий список
стратегии + слайдер `window_size`. Прогон сценария «собираем ТЗ» на каждой
стратегии с таблицей качества/стабильности/расхода токенов — в
[`comparison.md`](comparison.md).

## Архитектура

```
Streamlit (порт 8501) ── HTTP (requests) ──► FastAPI (порт 8000) ──► DeepSeek API
   переключатель стратегии,                       │              https://api.deepseek.com
   панели фактов/веток/токенов                    ▼
                                    AgentManager (синглтон)
                                      └─ Agent × N
                                         ├─ self.messages (история активной ветки)
                                         ├─ подсчёт токенов (tiktoken)
                                         ├─ prepare_context() ──► стратегия:
                                         │     sliding_window / sticky_facts /
                                         │     branching / summary (ContextCompressor)
                                         └─ факты (facts) / ветки (checkpoints)
                                              │
                                              ▼
                                    SQLAlchemy → SQLite (day10/agents.db)
                                    таблицы: agents      (конфигурация + strategy/window_size)
                                             messages    (история активной ветки)
                                             summaries   (конспекты, append-only)
                                             token_usage (метрики хода)
                                             facts       (факты sticky_facts)
                                             checkpoints (снимки/ветки branching)
```

Поток одного сообщения: **пользователь → `prepare_context()` по стратегии →
аварийная обрезка при переполнении → API → метрики в БД → пост-ходовое действие
стратегии (сжатие / сохранение фактов / снимок ветки) → ответ** (детали —
[docs/architecture.md](docs/architecture.md)).

## Структура

```
day10/
├── app.py               # Streamlit: переключатель стратегии (сайдбар), слайдер окна,
│                        # панели фактов и веток, кнопка тестового сценария, панели дня 9
├── backend/
│   ├── config.py        # URL/дефолты, лимиты/цены, настройки сжатия, DEFAULT_STRATEGY/окно
│   ├── strategies.py    # Enum Strategy + AVAILABLE_STRATEGIES + strategy_from_value
│   ├── fact_extractor.py# эвристика извлечения фактов «ключ: значение»
│   ├── context_fsm.py   # стейт-машина сжатия: ContextState/ContextEvent (Enum) + State
│   ├── context_policy.py# чистая арифметика: когда сжимать, что оставить
│   ├── database.py      # SQLAlchemy: agents/messages/summaries/token_usage/facts/checkpoints
│   ├── models.py        # Pydantic-схемы API (включая стратегии/ветки/факты)
│   ├── compressor.py    # ContextCompressor: план, суммаризация, запись конспекта (summary)
│   ├── agent.py         # Agent: память, токены, prepare_context, факты, ветки, метрики
│   ├── agent_manager.py # AgentManager: пул, restore, set_strategy, ветки, факты, агрегаты
│   └── main.py          # FastAPI: 19 эндпоинтов
├── tests/               # pytest: стратегии, факты, ветки, FSM, хранилище, API (193 теста)
├── docs/
│   ├── architecture.md  # компоненты, схема БД, стратегии, правило сжатия, FSM
│   ├── api.md           # эндпоинты с примерами и кодами ошибок
│   └── usage.md         # установка, запуск, стратегии/ветки/сценарий, FAQ
├── comparison.md        # прогон «собираем ТЗ» на 4 стратегиях: таблица метрик
├── requirements.txt     # fastapi, uvicorn, streamlit, openai, requests, sqlalchemy,
│                        # tiktoken, httpx, pytest, pandas
└── .env.example         # шаблон ключа DEEPSEEK_API_KEY
```

## Быстрый старт

```bash
cd day10
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
copy .env.example .env   # затем впишите DEEPSEEK_API_KEY=sk-...
```

Терминал 1 (бэкенд):

```bash
.venv/Scripts/python -m uvicorn backend.main:app --port 8000
```

Терминал 2 (фронтенд): откройте <http://localhost:8501>.

```bash
.venv/Scripts/python -m streamlit run app.py
```

Полная инструкция (ключ, переключение стратегий, ветки, тестовый сценарий,
просмотр SQLite, FAQ) — в [docs/usage.md](docs/usage.md); эндпоинты с примерами —
в [docs/api.md](docs/api.md); Swagger — на `http://127.0.0.1:8000/docs`.

## Тесты

```bash
cd day10
.venv/Scripts/python -m pytest -q      # 193 теста
```

Тесты работают офлайн: клиент DeepSeek подменяется фейком (`tests/support.py`),
база — временная SQLite. Покрыты `prepare_context` всех четырёх стратегий,
извлечение/персистентность фактов, ветвление (снимок/форк/переключение),
эндпоинты `/strategy`, `/branches`, `/facts`, а также FSM, политика сжатия,
хранилище, компрессор, метрики и контракты API дня 9.

## Возможности

- **Четыре стратегии контекста**: `sliding_window`, `sticky_facts`, `branching`
  и `summary` (сжатие из дня 9); переключаются на живом агенте
  (`POST /agents/{id}/strategy`).
- **Sliding Window**: только последние `window_size` реплик + системный промпт.
- **Sticky Facts**: эвристика извлекает факты «ключ: значение» в таблицу `facts`
  (уникальность по `agent_id+key`), факты уходят в LLM блоком системного
  сообщения; панель фактов в UI.
- **Branching**: чекпоинты-снимки истории в таблице `checkpoints` (`parent_id`
  задаёт дерево), создание веток от текущего сообщения и переключение между ними.
- **Summary** (день 9): конспект вместо старых реплик, стейт-машина сжатия,
  экономия токенов (`saved_tokens` / `net_saved_tokens`).
- **Подсчёт токенов** (tiktoken) и таблица `token_usage` с режимом хода.
- **Тестовый сценарий «собираем ТЗ»**: кнопка «🎬 Запустить тестовый сценарий»
  прогоняет 12 реплик; результаты по стратегиям — в `comparison.md`.
- Ошибки без traceback, при сбое генерации история не портится, UI жив при
  недоступном бэкенде (паттерн дней 6–9).

## Ограничения

- Один процесс бэкенда и один файл `day10/agents.db` (в `.gitignore` по `*.db`).
- Активная ветка (branching) хранится в памяти и сбрасывается при рестарте
  бэкенда; дерево веток в `checkpoints` при этом сохраняется.
- Переключение ветки перезаписывает таблицу `messages` снимком выбранной ветки.
- Извлечение фактов — эвристика (`ключ: значение`), а не LLM-извлечение.
- Оценки tiktoken (`cl100k_base`) приблизительны: DeepSeek использует свой
  токенизатор; для запроса/ответа приоритет — фактические `usage` API.
- Лимиты контекста 8K/32K демонстрационные; правка — `MODEL_TOKEN_LIMITS` в
  `backend/config.py`.
- Суммаризация всегда идёт на `deepseek-chat` (temperature 0.2); при коротких
  репликах конспект может оказаться дороже заменяемых сообщений.
