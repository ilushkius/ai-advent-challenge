# API бэкенда дня 6 — документация эндпоинтов

Базовый URL: `http://127.0.0.1:8000`. Интерактивная документация (Swagger) —
<http://127.0.0.1:8000/docs>, OpenAPI-схема — <http://127.0.0.1:8000/openapi.json>.

> В PowerShell `curl` — алиас `Invoke-WebRequest`; для примеров ниже используйте
> `curl.exe`. Все тела — JSON, кодировка UTF-8.

## Эндпоинты

| Метод | Путь | Назначение | Успех |
| --- | --- | --- | --- |
| `POST` | `/agents` | создать агента | `201` + `AgentInfo` |
| `GET` | `/agents` | список агентов | `200` + `[AgentSummary]` |
| `GET` | `/agents/{agent_id}` | информация об агенте | `200` + `AgentInfo` |
| `DELETE` | `/agents/{agent_id}` | удалить агента с историей | `200` |
| `POST` | `/agents/{agent_id}/generate` | отправить промпт агенту | `200` + запись |
| `GET` | `/agents/{agent_id}/history` | история попыток (новые сверху) | `200` + `[запись]` |

`AgentInfo` = `{agent_id, name, model, temperature, system_prompt, max_tokens,
created_at, history_count}`. Запись попытки = `{agent_id, status, prompt,
response, error, model, finish_reason, usage, duration_sec, timestamp}`.

## POST /agents — создать агента

```bash
curl.exe -X POST http://127.0.0.1:8000/agents ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Критик\",\"model\":\"deepseek-chat\",\"temperature\":0.4,
       \"system_prompt\":\"Ты строгий критик.\",\"max_tokens\":1024}"
```

Ответ `201`:

```json
{
  "agent_id": "47148cec",
  "name": "Критик",
  "model": "deepseek-chat",
  "temperature": 0.4,
  "system_prompt": "Ты строгий критик.",
  "max_tokens": 1024,
  "created_at": "2026-09-07T20:00:00Z",
  "history_count": 0
}
```

Поля необязательные: `model` (по умолчанию `deepseek-chat`), `temperature`
(0.7), `system_prompt` (пустая), `max_tokens` (2048). Диапазоны: температура
0.0–2.0, `max_tokens` 1–8192, имя 1–100 символов.

## GET /agents — список

```bash
curl.exe http://127.0.0.1:8000/agents
```

```json
[{"agent_id": "47148cec", "name": "Критик", "model": "deepseek-chat"}]
```

## GET /agents/{agent_id} — информация

```bash
curl.exe http://127.0.0.1:8000/agents/47148cec
```

Ответ — `AgentInfo` (см. выше). Неизвестный id → `404`:
`{"detail": "Агент 47148cec не найден"}`.

## DELETE /agents/{agent_id} — удалить

```bash
curl.exe -X DELETE http://127.0.0.1:8000/agents/47148cec
```

Ответ `200`: `{"status": "deleted", "agent_id": "47148cec"}`. Повторный запрос →
`404`.

## POST /agents/{agent_id}/generate — генерация

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/47148cec/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"Оцени идею приложения\"}"
```

Ответ `200` при успехе:

```json
{
  "agent_id": "47148cec",
  "status": "ok",
  "prompt": "Оцени идею приложения",
  "response": "Идея перспективная…",
  "error": null,
  "model": "deepseek-chat",
  "finish_reason": "stop",
  "usage": {"prompt_tokens": 18, "completion_tokens": 120, "total_tokens": 138},
  "duration_sec": 1.93,
  "timestamp": "2026-09-07T20:01:00Z"
}
```

Ответ `502` при сбое (например, ключ не задан или DeepSeek недоступен) — та же
структура, но `status: "error"` и заполнен `error` (без traceback):

```json
{
  "agent_id": "47148cec",
  "status": "error",
  "prompt": "Оцени идею приложения",
  "response": null,
  "error": "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day6/.env или в переменной окружения и перезапустите запрос.",
  "model": "deepseek-chat",
  "finish_reason": null,
  "usage": null,
  "duration_sec": 0.0,
  "timestamp": "2026-09-07T20:01:00Z"
}
```

## GET /agents/{agent_id}/history — история

```bash
curl.exe http://127.0.0.1:8000/agents/47148cec/history
```

Ответ — массив записей попыток (успех и ошибки), **новые первыми**.

## Коды ошибок

| Код | Когда | Тело |
| --- | --- | --- |
| `404` | неизвестный `agent_id` | `{"detail": "Агент <id> не найден"}` |
| `422` | невалидное тело (диапазоны, пустое имя/промпт) | `{"detail": [...]}` |
| `502` | сбой генерации (сеть/DeepSeek/ключ) | запись со `status:"error"` |

## Примечания

- Вызов DeepSeek идёт через OpenAI-совместимый endpoint
  `https://api.deepseek.com` (`chat/completions`), конфигурация — агента.
- `deepseek-reasoner` может **игнорировать `temperature`** и иначе трактовать
  `max_tokens` (лимит на итоговый ответ) — это поведение провайдера, не ошибка.
- Состояние (агенты и история) хранится в памяти процесса бэкенда: перезапуск
  uvicorn очищает его. Для массового создания просто шлите N запросов
  `POST /agents` — создание не обращается к DeepSeek и не требует ключа.
