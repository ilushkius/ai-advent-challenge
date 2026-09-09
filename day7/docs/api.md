# API бэкенда дня 7 — агенты с контекстной памятью

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
| `DELETE` | `/agents/{agent_id}` | удалить агента с диалогом | `200` |
| `POST` | `/agents/{agent_id}/generate` | сообщение в диалог + генерация с контекстом | `200` + `GenerateResponse` |
| `GET` | `/agents/{agent_id}/history` | диалог агента (по возрастанию) | `200` + `[MessageOut]` |
| `DELETE` | `/agents/{agent_id}/history` | **очистить диалог агента** | `200` |

Формы данных: `AgentInfo` = `{agent_id, name, model, message_count,
temperature, system_prompt, max_tokens, created_at}`; `MessageOut` = `{id,
agent_id, role, content, timestamp}`; `GenerateResponse` = метаданные попытки +
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

Ответ `502` при сбое (нет ключа / DeepSeek недоступен) — та же структура со
`status: "error"`, заполненным `error` и **неизменной** историей `messages`
(реплика без ответа не сохраняется):

```json
{
  "agent_id": "47148cec",
  "status": "error",
  "error": "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day7/.env или в переменной окружения и перезапустите запрос.",
  "model": "deepseek-chat",
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
пустой истории. Неизвестный агент → `404`.

## Коды ошибок

| Код | Когда | Тело |
| --- | --- | --- |
| `404` | неизвестный `agent_id` | `{"detail": "Агент <id> не найден"}` |
| `422` | невалидное тело (диапазоны, пустое имя/промпт) | `{"detail": [...]}` |
| `502` | сбой генерации (сеть/DeepSeek/ключ) | `GenerateResponse` со `status:"error"` и неизменной `messages` |

## Примечания

- В DeepSeek отправляется массив `messages`: `[system?] + вся история диалога`;
  конфигурация генерации — агента (`model`, `temperature`, `max_tokens`).
- История хранится в `day7/agents.db` (таблицы `agents`, `messages`) и
  переживает перезапуск uvicorn.
- `deepseek-reasoner` может игнорировать `temperature` — поведение провайдера.
