# API бэкенда дня 8 — агенты с памятью и контролем токенов

Базовый URL: `http://127.0.0.1:8000`. Интерактивная документация (Swagger) —
<http://127.0.0.1:8000/docs>, OpenAPI-схема — <http://127.0.0.1:8000/openapi.json>.

> В PowerShell `curl` — алиас `Invoke-WebRequest`; в примерах используйте
> `curl.exe`. Тела — JSON в UTF-8.

## Эндпоинты

| Метод | Путь | Назначение | Успех |
| --- | --- | --- | --- |
| `POST` | `/agents` | создать агента (конфигурация в SQLite) | `201` + `AgentInfo` |
| `GET` | `/agents` | список агентов с числом сообщений | `200` + `[AgentSummary]` |
| `GET` | `/agents/{agent_id}` | информация об агенте | `200` + `AgentInfo` |
| `DELETE` | `/agents/{agent_id}` | удалить агента с диалогом и метриками | `200` |
| `POST` | `/agents/{agent_id}/generate` | сообщение + генерация с контролем токенов | `200` + `GenerateResponse` |
| `GET` | `/agents/{agent_id}/history` | диалог агента (по возрастанию) | `200` + `[MessageOut]` |
| `DELETE` | `/agents/{agent_id}/history` | очистить диалог (сбрасывает счётчик токенов) | `200` |
| `GET` | `/agents/{agent_id}/usage` | **сводка токенов агента** | `200` + `UsageSummary` |
| `GET` | `/agents/{agent_id}/usage/graph` | **записи token_usage для графика** | `200` + `[UsageOut]` |

Формы данных: `AgentInfo` = `{agent_id, name, model, message_count,
temperature, system_prompt, max_tokens, created_at}`; `MessageOut` = `{id,
agent_id, role, content, timestamp}`; `GenerateResponse` = метаданные попытки +
метрики токенов (`token_metrics`), состояние контекста (`context`) и
`messages: [MessageOut]` (обновлённая история после попытки).

## POST /agents — создать агента

```bash
curl.exe -X POST http://127.0.0.1:8000/agents ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Конспектёр\",\"model\":\"deepseek-chat\",\"temperature\":0.3,
       \"system_prompt\":\"Излагай тезисами.\",\"max_tokens\":1024}"
```

Ответ `201`:

```json
{
  "agent_id": "47148cec",
  "name": "Конспектёр",
  "model": "deepseek-chat",
  "message_count": 0,
  "temperature": 0.3,
  "system_prompt": "Излагай тезисами.",
  "max_tokens": 1024,
  "created_at": "2026-09-09T12:00:00Z"
}
```

История нового агента пустая (`message_count: 0`). Диапазоны: температура
0.0–2.0, `max_tokens` 1–8192, имя 1–100 символов.

## GET /agents — список с числом сообщений

```bash
curl.exe http://127.0.0.1:8000/agents
```

```json
[{"agent_id": "47148cec", "name": "Конспектёр", "model": "deepseek-chat", "message_count": 4}]
```

## GET /agents/{agent_id} — информация

Ответ — `AgentInfo` (см. выше). Неизвестный id → `404`:
`{"detail": "Агент 47148cec не найден"}`.

## DELETE /agents/{agent_id} — удалить агента

```bash
curl.exe -X DELETE http://127.0.0.1:8000/agents/47148cec
```

Ответ `200`: `{"status": "deleted", "agent_id": "47148cec"}`. Диалог агента
удаляется из SQLite каскадом. Повторный запрос → `404`.

## POST /agents/{agent_id}/generate — сообщение + генерация с контекстом

Бэкенд добавляет сообщение в диалог агента, отправляет в DeepSeek **всю**
историю (системный промпт — первым, если задан), добавляет ответ и сохраняет в
SQLite.

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/47148cec/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"Что я спрашивал(а) в первом сообщении?\"}"
```

Ответ `200` (диалог уже из двух ходов — история из 4 реплик):

```json
{
  "agent_id": "47148cec",
  "status": "ok",
  "prompt": "Что я спрашивал(а) в первом сообщении?",
  "response": "Вы спрашивали про RAG…",
  "error": null,
  "model": "deepseek-chat",
  "finish_reason": "stop",
  "usage": {"prompt_tokens": 180, "completion_tokens": 42, "total_tokens": 222},
  "token_metrics": {
    "prompt_tokens": 180, "completion_tokens": 42, "total_tokens": 222,
    "history_tokens": 138, "response_tokens": 40, "cost": 0.0000948
  },
  "context": {
    "max_model_tokens": 8000, "payload_tokens": 180,
    "context_tokens": 222, "remaining_tokens": 7778,
    "over_limit": false, "trimmed_messages": 0, "warning": null
  },
  "duration_sec": 1.24,
  "timestamp": "2026-09-09T12:05:00Z",
  "messages": [
    {"id": 1, "agent_id": "47148cec", "role": "user", "content": "Что такое RAG?", "timestamp": "2026-09-09T12:02:00Z"},
    {"id": 2, "agent_id": "47148cec", "role": "assistant", "content": "RAG — это…", "timestamp": "2026-09-09T12:02:01Z"},
    {"id": 3, "agent_id": "47148cec", "role": "user", "content": "Что я спрашивал(а) в первом сообщении?", "timestamp": "2026-09-09T12:05:00Z"},
    {"id": 4, "agent_id": "47148cec", "role": "assistant", "content": "Вы спрашивали про RAG…", "timestamp": "2026-09-09T12:05:00Z"}
  ]
}
```

Ответ `200` содержит метрики токенов хода (`token_metrics`) и состояние
контекста (`context`). Значения `prompt_tokens`/`completion_tokens`/
`total_tokens` — из `usage` DeepSeek (при его отсутствии — локальные оценки
tiktoken); `history_tokens` — оценка контекста истории (системный промпт +
предыдущие сообщения), `response_tokens` — оценка ответа, `cost` — стоимость
по тарифам модели. Поля `context` интерфейс использует для индикатора лимита;
при автообрезке (переполнение контекста) `over_limit: true`,
`trimmed_messages > 0` и заполнен `warning`.

Ответ `502` при сбое (нет ключа / DeepSeek недоступен) — та же структура со
`status: "error"`, заполненным `error` и **неизменной** историей `messages`
(реплика без ответа не сохраняется):

```json
{
  "agent_id": "47148cec",
  "status": "error",
  "error": "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day8/.env или в переменной окружения и перезапустите запрос.",
  "model": "deepseek-chat",
  "usage": null,
  "token_metrics": null,
  "context": null,
  "messages": []
}
```

## GET /agents/{agent_id}/history — диалог агента

```bash
curl.exe http://127.0.0.1:8000/agents/47148cec/history
```

Ответ — массив `MessageOut` **по возрастанию времени** (хронология чата),
например `[{id, role: "user", content: ...}, {id, role: "assistant", content: ...}]`.

## DELETE /agents/{agent_id}/history — очистить историю агента

```bash
curl.exe -X DELETE http://127.0.0.1:8000/agents/47148cec/history
```

Ответ `200`: `{"status": "cleared", "agent_id": "47148cec", "message_count": 0}`.
Конфигурация агента не изменяется; следующий `generate` начнёт новый диалог с
пустой истории (записи `token_usage` тоже удаляются — счётчик токенов с нуля).
Неизвестный агент → `404`.

## GET /agents/{agent_id}/usage — сводка токенов агента

```bash
curl.exe http://127.0.0.1:8000/agents/47148cec/usage
```

Ответ `200` — `UsageSummary`: агрегаты по таблице `token_usage` + оценка
занятости контекста диалога для индикатора в интерфейсе:

```json
{
  "agent_id": "47148cec",
  "model": "deepseek-chat",
  "total_requests": 2,
  "total_prompt_tokens": 320,
  "total_completion_tokens": 77,
  "total_tokens": 397,
  "total_cost": 0.0001774,
  "last_usage_at": "2026-09-09T12:05:00Z",
  "context_limit_tokens": 8000,
  "current_history_tokens": 397,
  "remaining_tokens": 7603
}
```

## GET /agents/{agent_id}/usage/graph — данные для графика

```bash
curl.exe http://127.0.0.1:8000/agents/47148cec/usage/graph
```

Ответ `200` — записи `token_usage` **по возрастанию времени** для таблицы и
графика роста токенов (все поля записи: `id`, `agent_id`, `timestamp`,
`prompt_tokens`, `completion_tokens`, `total_tokens`, `history_tokens`,
`response_tokens`, `cost`).

## Коды ошибок

| Код | Когда | Тело |
| --- | --- | --- |
| `404` | неизвестный `agent_id` | `{"detail": "Агент <id> не найден"}` |
| `422` | невалидное тело (диапазоны, пустое имя/промпт) | `{"detail": [...]}` |
| `502` | сбой генерации (сеть/DeepSeek/ключ) | `GenerateResponse` со `status:"error"` и неизменной `messages` |

## Примечания

- В DeepSeek отправляется массив `messages`: `[system?] + история диалога`;
  конфигурация генерации — агента (`model`, `temperature`, `max_tokens`).
- Перед вызовом бэкенд оценивает токены запроса; при превышении лимита модели
  (`deepseek-chat` 8000, `deepseek-reasoner` 32000) самые старые ЦЕЛЫЕ пары
  сообщений удаляются из истории, а в ответе приходит предупреждение
  (`context.over_limit`, `context.trimmed_messages`, `context.warning`).
- Метрики успешных ходов хранятся в `day8/agents.db` (таблицы `agents`,
  `messages`, `token_usage`) и переживают перезапуск uvicorn. Одна запись
  `token_usage` = один успешный ход.
- `deepseek-reasoner` может игнорировать `temperature` — поведение провайдера.
  Оценки `response_tokens` считают только видимый текст ответа (без reasoning).
