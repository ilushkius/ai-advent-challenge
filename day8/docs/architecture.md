# Архитектура дня 8 — «Агент с памятью и контролем токенов»

День 8 наследует архитектуру дня 7 (FastAPI + Streamlit + SQLAlchemy/SQLite) и
добавляет слой **подсчёта токенов**: tiktoken, таблицу `token_usage`, панель
токенов в UI и автоматическую обрезку истории при переполнении контекста.

## Компоненты

| Компонент | Модуль | Ответственность |
| --- | --- | --- |
| `Streamlit app` | `day8/app.py` | Чат + панель «📊 Токены диалога» (счётчик, индикатор лимита, график/таблица из `/usage` и `/usage/graph`) |
| `AgentManager` | `backend/agent_manager.py` | Пул агентов-синглтон, restore из БД, сводки `token_usage` (SQL-агрегаты + занятость контекста) |
| `Agent` | `backend/agent.py` | Конфигурация + `self.messages`; `count_tokens`, метрики хода, лимит-контроль и автообрезка |
| `database` | `backend/database.py` | SQLAlchemy: engine/SessionLocal, ORM `agents`, `messages`, `token_usage`, `init_db` |
| `models` | `backend/models.py` | Pydantic-схемы API: `AgentInfo`, `MessageOut`, `TokenMetrics`, `ContextInfo`, `UsageOut`, `UsageSummary`, `GenerateResponse` |
| `main` | `backend/main.py` | FastAPI: CRUD агентов, история, генерация, `DELETE history`, `GET usage`, `GET usage/graph` |
| `config` | `backend/config.py` | DeepSeek URL, ключ, `MODEL_TOKEN_LIMITS`, `MODEL_PRICES`, путь БД |

Взаимодействие между процессами — HTTP (`requests`, фронтенд → бэкенд на порт
8000); браузер пользователя работает только со Streamlit (порт 8501).

## Схема БД (`day8/agents.db`)

Три таблицы со связью один-ко-многим от агента:

```
agents  (1) ───< messages  (N)     реплики диалога user/assistant
    │            (agent_id FK, ondelete CASCADE)
    └──────────< token_usage (N)    метрики токенов успешного хода
                 (agent_id FK, ondelete CASCADE, index)
```

**`agents`** — конфигурация агента: `agent_id` (PK), `name`, `model`,
`temperature`, `system_prompt` (Text), `max_tokens` (ограничение ОТВЕТА),
`created_at`.

**`messages`** — реплики диалога: `id` (Integer PK), `agent_id` (FK, index),
`role`, `content` (Text), `timestamp`. Системный промпт сюда НЕ пишется — он
конфигурация агента и добавляется первым сообщением только в payload запроса.

**`token_usage`** — одна запись на один успешный ход диалога:
`id` (PK), `agent_id` (FK, index), `timestamp`, `prompt_tokens`,
`completion_tokens`, `total_tokens`, `history_tokens`, `response_tokens`
(Integer) и `cost` (Float).

Жизненный цикл: удаление агента каскадом удаляет `messages` и `token_usage`;
очистка истории (`DELETE /agents/{id}/history`) удаляет и диалог, и метрики
агента — «новый диалог» начинает счёт токенов с нуля. База создаётся при
старте бэкенда (`init_db` → `create_all`), файл в `.gitignore` (`*.db`).

## Механика подсчёта токенов (день 8)

- `Agent.count_tokens(text)` использует **tiktoken**, кодировка
  `cl100k_base`. Кодировка грузится лениво и кэшируется на уровне модуля;
  пустой текст = 0. Подсчёт **приблизительный**: DeepSeek использует свой
  токенизатор (не публикуется), поэтому локальные оценки могут отличаться от
  фактического `usage` API.
- Токены списка сообщений — сумма `count_tokens(content)` по сообщениям
  (включая системный промпт, если он в списке).

Метрики одного хода (семантика — design.md, D3):

| Поле | Источник |
| --- | --- |
| `prompt_tokens` | `usage.prompt_tokens` из ответа DeepSeek; при отсутствии `usage` — оценка «контекст истории + новое сообщение» |
| `completion_tokens` | `usage.completion_tokens`; при отсутствии — `response_tokens` |
| `total_tokens` | `usage.total_tokens`; при отсутствии — сумма предыдущих двух |
| `history_tokens` | локальная оценка контекста, ушедшего в запрос: системный промпт + сообщения истории до нового хода (после возможной обрезки) |
| `response_tokens` | локальная оценка видимого текста ответа (`content`; без reasoning у `deepseek-reasoner`) |
| `cost` | `prompt_tokens/1e6 * IN + completion_tokens/1e6 * OUT` по `MODEL_PRICES` (константы config, приблизительно) |

Запись `token_usage` добавляется **той же транзакцией**, что и пара сообщений
`user`+`assistant` (`Agent._save_turn`) — диалог и его метрики не могут
разъехаться. При сбое API транзакция не коммитится: история и счётчик не
меняются.
## Лимит контекста и автообрезка (поток генерации)

Лимиты модели — `config.MODEL_TOKEN_LIMITS`: `deepseek-chat` → 8 000,
`deepseek-reasoner` → 32 000 (демонстрационные значения из задания; реальный
контекст API шире). `max_tokens` агента — отдельная настройка (лимит ответа).

Последовательность `Agent.generate(prompt)`:

1. В `self.messages` добавляется сообщение пользователя (только в память).
2. Считается оценка запроса: `history_tokens` (системный промпт + история до
   нового сообщения) + `count_tokens(prompt)`.
3. Если оценка ≤ лимита — вызов без изменений.
4. Если оценка > лимита — подбирается максимальное число последних сообщений
   (ЦЕЛЫЕ пары `user`+`assistant`), с которыми контекст влезает в лимит; самые
   старые сообщения за пределами этого окна удаляются из `self.messages` и из
   таблицы `messages` в БД. Факт обрезки попадает в
   `context.over_limit`/`context.trimmed_messages`/`context.warning`.
5. Крайний случай: даже при пустой истории сообщение длиннее лимита — ответ
   со `status: "error"` («Сообщение длиннее лимита контекста модели…») **без**
   вызова DeepSeek и без изменения БД.
6. В DeepSeek уходит payload `[system?] + сокращённая история` с
   конфигурацией агента (`model`, `temperature`, `max_tokens`).
7. При успехе: ответ добавляется в `self.messages`; метрики токенов
   (`token_metrics`) и состояние контекста (`context`) кладутся в ответ API, а
   запись `token_usage` сохраняется транзакцией вместе с парой сообщений.

Почему обрезка по парам, а не «последние N сообщений»: диалог строится
атомарными парами; одиночная реплика `user` без ответа — артефакт. История в
БД и в памяти всегда согласованы («память = БД»), поэтому после обрезки UI и
SQLite показывают одно и то же.

## Поток данных и API

- `POST /agents/{agent_id}/generate` возвращает `GenerateResponse`: текст
  ответа, метрики (`duration_sec`, `usage`, `finish_reason`), **`token_metrics`
  и `context`** (день 8), актуальный диалог `messages`. При сбое — `502` со
  `status: "error"`, `token_metrics: null`, `context: null` и неизменной
  историей (без traceback).
- `GET /agents/{agent_id}/usage` — `UsageSummary`: SQL-агрегаты по
  `token_usage` (число запросов, суммы токенов, стоимость, время последней
  записи) + оценка занятости контекста агента (`context_limit_tokens`,
  `current_history_tokens`, `remaining_tokens`) — источник данных индикатора UI.
- `GET /agents/{agent_id}/usage/graph` — строки `token_usage` по возрастанию
  времени для таблицы и графика.
- Неизвестный агент → `404`; невалидное тело → `422`.

## Интерфейс: панель «📊 Токены диалога»

Под шапкой выбранного агента приложение рисует панель из данных `/usage` и
`/usage/graph`: метрики (использовано токенов за диалог = сумма `total_tokens`,
число запросов, стоимость), прогресс-бар занятости контекста
(`current_history_tokens / context_limit_tokens`) с остатком до лимита,
`st.warning` при остатке < 10% и при автообрезке, график накопленной суммы
`total_tokens` по запросам (`st.line_chart`) и таблицу записей. Панель
перечитывается после каждого ответа и после очистки истории (после очистки —
нули). При недоступном бэкенде панель молча пропускается, страница живёт.

## Сценарий демонстрации (видео)

Создать агента `deepseek-chat` → 2–3 вопроса (растут счётчик, индикатор,
график) → очень длинное сообщение (красная зона + предупреждение) → следующий
длинный запрос вызывает автообрезку («удалено N самых старых сообщений») →
показать таблицу/график и `token_usage` в SQLite. Офлайн-эквивалент сценария
(фейковый клиент, временная БД) выполняется в apply без сети и ключа.
