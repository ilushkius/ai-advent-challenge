# День 8 — Агент DeepSeek с контролем токенов (FastAPI + Streamlit + SQLite)

Веб-приложение развивает день 7: агент по-прежнему ведёт **полный диалог с
памятью** (SQLite, история переживает рестарт бэкенда), а день 8 добавляет
**подсчёт и наглядность токенов** — tiktoken по каждому запросу, хранение
метрик в таблице `token_usage`, панель «📊 Токены диалога» в интерфейсе
(счётчик, индикатор лимита, график роста) и **автоматическую обрезку истории**
при переполнении контекста.

## Архитектура

```
Streamlit (порт 8501) ── HTTP (requests) ──► FastAPI (порт 8000) ──► DeepSeek API
                                              │                        https://api.deepseek.com
                                              ▼
                                     AgentManager (синглтон)
                                       └─ Agent × N (конфигурация + self.messages
                                          + подсчёт токенов tiktoken)
                                              │
                                              ▼
                                    SQLAlchemy → SQLite (day8/agents.db)
                                    таблицы: agents (конфигурация)
                                             messages (диалог, FK → agents)
                                             token_usage (метрики токенов хода,
                                                          FK → agents)
```

Поток одного сообщения: **пользователь → интерфейс → агент → оценка токенов →
(при переполнении: автообрезка старых пар) → API → ответ → метрики → БД**
(детали — [docs/architecture.md](docs/architecture.md)).

## Структура

```
day8/
├── app.py               # Streamlit-чат + панель «📊 Токены диалога»
├── backend/
│   ├── __init__.py
│   ├── config.py        # URL/дефолты, DEEPSEEK_API_KEY, MODEL_TOKEN_LIMITS,
│   │                    # MODEL_PRICES, путь к БД
│   ├── database.py      # SQLAlchemy: engine, сессии, ORM agents/messages/token_usage
│   ├── agent.py         # класс Agent: память + count_tokens + автообрезка
│   ├── agent_manager.py # AgentManager: пул, restore, сводки token_usage
│   ├── models.py        # Pydantic-схемы API (включая TokenMetrics/Usage*)
│   └── main.py          # FastAPI: 9 эндпоинтов (добавлены /usage, /usage/graph)
├── docs/
│   ├── architecture.md  # архитектура, схема БД, механика подсчёта и обрезки
│   ├── api.md           # эндпоинты с примерами (usage, graph, token_metrics)
│   └── usage.md         # установка, запуск, демо «переполнение контекста», FAQ
├── requirements.txt     # fastapi, uvicorn, streamlit, openai, requests, sqlalchemy, tiktoken
└── .env.example         # шаблон ключа DEEPSEEK_API_KEY
```

## Быстрый старт

```bash
cd day8
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

Полная инструкция (ключ, сценарии, демо «токены и переполнение», FAQ) — в
[docs/usage.md](docs/usage.md); эндпоинты с примерами curl — в
[docs/api.md](docs/api.md); Swagger — на `http://127.0.0.1:8000/docs`.
## Возможности

- **Контекстная память** (день 7): диалог `user`/`assistant` в SQLite,
  полностью уходит в DeepSeek при каждом запросе, переживает рестарт.
- **Подсчёт токенов** (день 8): `Agent.count_tokens(text)` на tiktoken
  (`cl100k_base`, приближение к токенизатору DeepSeek); для каждого хода
  считаются токены контекста истории и нового сообщения, а фактические числа
  запроса/ответа берутся из `usage` API.
- **Таблица `token_usage`**: одна запись на успешный ход — `agent_id`,
  `timestamp`, `prompt_tokens`, `completion_tokens`, `total_tokens`,
  `history_tokens`, `response_tokens`, `cost` (приблизительная стоимость по
  тарифам модели). Каскад при удалении агента, сброс при очистке истории.
- **Панель «📊 Токены диалога»**: счётчик токенов за диалог, стоимость,
  прогресс-бар занятости контекста с остатком до лимита
  (`deepseek-chat` — 8000, `deepseek-reasoner` — 32000), предупреждения,
  график роста токенов (`st.line_chart`) и таблица записей.
- **Автообрезка при переполнении**: если оценка «история + новое сообщение»
  превышает лимит модели, агент удаляет самые старые ЦЕЛЫЕ пары сообщений
  (память + БД), шлёт запрос с сокращённым контекстом и предупреждает
  («удалено N самых старых сообщений»). Сообщение длиннее лимита при пустой
  истории — понятная ошибка без вызова API.
- **Новые эндпоинты**: `GET /agents/{id}/usage` (сводка) и
  `GET /agents/{id}/usage/graph` (записи для графика); ответ `generate`
  содержит `token_metrics` и `context`.
- Ошибки без traceback, при сбое история не портится; UI жив при
  недоступном бэкенде (паттерн дней 6–7).

## Демо для видео (токены и переполнение контекста)

1. Создайте агента `deepseek-chat`, задайте 2–3 вопроса — растут счётчик,
   индикатор и график в панели.
2. Отправьте очень длинное сообщение (~6–7 тыс. символов) — индикатор в
   красной зоне, предупреждение о почти полном контексте.
3. Отправьте ещё одно длинное сообщение — автообрезка: «⚠️ Контекст был
   переполнен: удалено N самых старых сообщений», чат показывает
   сокращённую историю.
4. Покажите таблицу/график и записи `token_usage` в SQLite.

## Ограничения

- Один процесс бэкенда и один файл `day8/agents.db` (в `.gitignore` по `*.db`).
- Оценки tiktoken (`cl100k_base`) приблизительны: DeepSeek использует свой
  токенизатор; для запроса/ответа приоритет — фактические `usage` API.
- Лимиты 8K/32K демонстрационные (пример из задания); реальный контекст
  DeepSeek шире. Правка — константы `MODEL_TOKEN_LIMITS` в `backend/config.py`.
- Автообрезка удаляет старые сообщения безвозвратно; полный сброс диалога и
  счётчика — кнопка «🧹 Очистить историю».
- `deepseek-reasoner` может игнорировать `temperature` и добавляет в
  `completion_tokens` скрытые рассуждения (в `response_tokens` — только текст).
