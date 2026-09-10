# API дня 9 — агенты DeepSeek со сжатием истории

Бэкенд — FastAPI-приложение `day9/backend/main.py`. Базовый адрес после запуска
(из папки `day9`):

```powershell
.venv/Scripts/python -m uvicorn backend.main:app --port 8000
```

| Что | Адрес |
|---|---|
| Базовый URL | `http://127.0.0.1:8000` |
| Swagger UI | `http://127.0.0.1:8000/docs` |
| OpenAPI-схема | `http://127.0.0.1:8000/openapi.json` |

Все примеры ниже даны для `curl.exe` и предполагают, что вы запускаете их **из
командной строки, где `curl` — это настоящий curl** (bash, Git Bash, cmd с
установленным curl). В PowerShell `curl` — это алиас командлета
`Invoke-WebRequest`, у него другие ключи (`-Method`, `-Body`, `-Headers`), и
примеры вида `curl -X POST ...` там не сработают. Поэтому в примерах явно указан
`curl.exe`, а не `curl`.

Настройки сжатия (сколько реплик держать «как есть», порог конспектирования)
задаются при создании агента, меняются через `PATCH` и видны в ответах. Схемы
ответов описаны в `day9/backend/models.py`; сводная таблица полей — в разделе
[«Формы данных»](#формы-данных).

## Эндпоинты

Всего 13 эндпоинтов с префиксом `/agents/{agent_id}` плюс корневой `GET /`.

| Метод | Путь | Назначение | Успех |
|---|---|---|---|
| POST | `/agents` | создать агента (конфигурация + настройки сжатия) | 201 AgentInfo |
| GET | `/agents` | список агентов с числом сообщений и настройками сжатия | 200 [AgentSummary] |
| GET | `/agents/{agent_id}` | полная информация об агенте | 200 AgentInfo |
| PATCH | `/agents/{agent_id}` | частично обновить агента (в т.ч. переключить сжатие) | 200 AgentInfo |
| DELETE | `/agents/{agent_id}` | удалить агента с диалогом, конспектами и метриками | 200 `{status:"deleted"}` |
| POST | `/agents/{agent_id}/generate` | ход диалога со сжатием истории | 200 GenerateResponse |
| GET | `/agents/{agent_id}/history` | все реплики диалога (с признаком `summarized`) | 200 [MessageOut] |
| DELETE | `/agents/{agent_id}/history` | очистить диалог, конспекты и метрики | 200 `{status:"cleared"}` |
| POST | `/agents/{agent_id}/summarize` | сжать историю сейчас | 200 отчёт о сжатии |
| GET | `/agents/{agent_id}/summary` | конспект, watermark и экономика | 200 SummaryInfo |
| POST | `/agents/{agent_id}/compare` | сравнить режимы «полная история» и «конспект» | 200 CompareResult |
| GET | `/agents/{agent_id}/usage` | сводка токенов и экономии | 200 UsageSummary |
| GET | `/agents/{agent_id}/usage/graph` | записи `token_usage` для графика | 200 [UsageOut] |
| GET | `/` | список доступных эндпоинтов | 200 объект-подсказка |

## GET /

Корневая точка — подсказка: имя приложения, путь к Swagger и перечень
эндпоинтов.

```bash
curl.exe http://127.0.0.1:8000/
```

```json
{
  "name": "Агенты DeepSeek со сжатием истории — День 9",
  "docs": "/docs",
  "endpoints": [
    "POST /agents",
    "GET /agents",
    "GET /agents/{agent_id}",
    "PATCH /agents/{agent_id}",
    "DELETE /agents/{agent_id}",
    "POST /agents/{agent_id}/generate",
    "GET /agents/{agent_id}/history",
    "DELETE /agents/{agent_id}/history",
    "POST /agents/{agent_id}/summarize",
    "GET /agents/{agent_id}/summary",
    "POST /agents/{agent_id}/compare",
    "GET /agents/{agent_id}/usage",
    "GET /agents/{agent_id}/usage/graph"
  ]
}
```

Коды: `200`.

## POST /agents

Создаёт агента и сохраняет его конфигурацию (включая настройки сжатия) в SQLite.
`agent_id` генерируется на сервере и возвращается в ответе — используйте его во
всех последующих запросах.

Настройки сжатия по умолчанию: `summary_enabled = true`,
`keep_last_messages = 6`, `summarize_every = 10`.

Например, что означают эти поля:

| Поле | Смысл |
|---|---|
| `summary_enabled` | включено ли сжатие истории в конспект |
| `keep_last_messages` | сколько последних реплик всегда отправлять «как есть» (2–20) |
| `summarize_every` | порог: конспектируем, когда непокрытых реплик накопилось не меньше этого числа (2–40) |

Запрос:

```bash
curl.exe -X POST http://127.0.0.1:8000/agents \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Учитель\",\"model\":\"deepseek-chat\",\"temperature\":0.7,\"max_tokens\":1024,\"system_prompt\":\"Ты объясняешь просто.\",\"summary_enabled\":true,\"keep_last_messages\":6,\"summarize_every\":10}"
```

Ответ `201`:

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "name": "Учитель",
  "model": "deepseek-chat",
  "message_count": 0,
  "summary_enabled": true,
  "keep_last_messages": 6,
  "summarize_every": 10,
  "summary_count": 0,
  "temperature": 0.7,
  "system_prompt": "Ты объясняешь просто.",
  "max_tokens": 1024,
  "created_at": "2026-09-10T12:00:00"
}
```

Коды: `201`, `422` (невалидное тело — например, пустое имя, `temperature`
вне 0.0–2.0, `max_tokens` вне 1–8192, `keep_last_messages` вне 2–20).

## GET /agents

Список всех агентов. Для каждого — короткая запись без `temperature` /
`system_prompt` / `max_tokens` / `created_at`, но с числом сообщений и
настройками сжатия.

```bash
curl.exe http://127.0.0.1:8000/agents
```

```json
[
  {
    "agent_id": "8f1c2d3e4b5a",
    "name": "Учитель",
    "model": "deepseek-chat",
    "message_count": 12,
    "summary_enabled": true,
    "keep_last_messages": 6,
    "summarize_every": 10,
    "summary_count": 1
  }
]
```

Коды: `200`.

## GET /agents/{agent_id}

Полная информация об агенте (та же короткая запись + параметры генерации и дата
создания). Используется интерфейсом, чтобы показать конфигурацию выбранного
агента.

```bash
curl.exe http://127.0.0.1:8000/agents/8f1c2d3e4b5a
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "name": "Учитель",
  "model": "deepseek-chat",
  "message_count": 12,
  "summary_enabled": true,
  "keep_last_messages": 6,
  "summarize_every": 10,
  "summary_count": 1,
  "temperature": 0.7,
  "system_prompt": "Ты объясняешь просто.",
  "max_tokens": 1024,
  "created_at": "2026-09-10T12:00:00"
}
```

Коды: `200`, `404` (неизвестный `agent_id`).

## PATCH /agents/{agent_id}

Частичное обновление: меняются только переданные поля, диалог и конспекты при
этом не теряются. Все поля необязательные:

| Поле | Тип | Ограничение |
|---|---|---|
| `name` | строка | 1–100 символов |
| `temperature` | число | 0.0–2.0 |
| `system_prompt` | строка | до 4000 символов |
| `max_tokens` | число | 1–8192 |
| `summary_enabled` | bool | включить/выключить сжатие |
| `keep_last_messages` | число | 2–20 |
| `summarize_every` | число | 2–40 |

Модель (`model`) через `PATCH` не меняется.

Пример — выключить сжатие на живом агенте:

```bash
curl.exe -X PATCH http://127.0.0.1:8000/agents/8f1c2d3e4b5a \
  -H "Content-Type: application/json" \
  -d "{\"summary_enabled\":false,\"keep_last_messages\":8}"
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "name": "Учитель",
  "model": "deepseek-chat",
  "message_count": 12,
  "summary_enabled": false,
  "keep_last_messages": 8,
  "summarize_every": 10,
  "summary_count": 1,
  "temperature": 0.7,
  "system_prompt": "Ты объясняешь просто.",
  "max_tokens": 1024,
  "created_at": "2026-09-10T12:00:00"
}
```

Коды: `200`, `404`, `422`.

## DELETE /agents/{agent_id}

Удаляет агента вместе с его диалогом, конспектами и метриками (связанные строки
уходят каскадом).

```bash
curl.exe -X DELETE http://127.0.0.1:8000/agents/8f1c2d3e4b5a
```

```json
{ "status": "deleted", "agent_id": "8f1c2d3e4b5a" }
```

Коды: `200`, `404`.

## POST /agents/{agent_id}/generate

Основной ход диалога. Сервер:

1. добавляет реплику пользователя в контекст;
2. собирает **два** варианта контекста — полный (вся история) и сжатый
   (конспект + последние `keep_last_messages` непокрытых реплик) — и считает
   токены обоих;
3. при необходимости вызывает DeepSeek;
4. сохраняет пару реплик и метрики (включая экономию) одной транзакцией;
5. после успешного хода пытается выполнить сжатие (если включено и набран
   порог).

Тело запроса:

| Поле | Тип | Ограничение |
|---|---|---|
| `prompt` | строка | 1–16000 символов, не может быть пустым |

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/generate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"Объясни, что такое контекст модели\"}"
```

Ответ `200` (сокращённый, но со всеми полями дня 9):

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "status": "ok",
  "prompt": "Объясни, что такое контекст модели",
  "response": "Контекст модели — это...",
  "error": null,
  "model": "deepseek-chat",
  "finish_reason": "stop",
  "usage": {
    "prompt_tokens": 320,
    "completion_tokens": 180,
    "total_tokens": 500
  },
  "token_metrics": {
    "prompt_tokens": 320,
    "completion_tokens": 180,
    "total_tokens": 500,
    "history_tokens": 480,
    "response_tokens": 180,
    "cost": 0.000284,
    "mode": "compressed",
    "full_context_tokens": 5400,
    "sent_context_tokens": 1200,
    "saved_tokens": 4200,
    "summary_tokens": 900,
    "summarized_messages": 10,
    "summary_used": true
  },
  "context": {
    "max_model_tokens": 8000,
    "payload_tokens": 1200,
    "context_tokens": 1200,
    "remaining_tokens": 6800,
    "over_limit": false,
    "trimmed_messages": 0,
    "warning": null,
    "state": "tracking",
    "compression": {
      "enabled": true,
      "mode": "compressed",
      "summary_used": true,
      "summary_tokens": 900,
      "kept_messages": 6,
      "summarized_messages": 10,
      "covered_messages": 10,
      "full_context_tokens": 5400,
      "sent_context_tokens": 1200,
      "saved_tokens": 4200,
      "saved_percent": 77.8,
      "error": null
    }
  },
  "duration_sec": 1.842,
  "timestamp": "2026-09-10T12:05:00",
  "messages": []
}
```

Пояснения к блоку `context`:

- `payload_tokens` — сколько токенов реально ушло в этом запросе;
- `remaining_tokens` — остаток до демонстрационного лимита модели;
- `trimmed_messages` — сколько самых старых реплик пришлось не отправлять из-за
  аварийного предохранителя (они остаются в БД);
- `warning` заполняется **только** при срабатывании этого предохранителя;
- `state` — состояние процесса сжатия (`idle`, `tracking`, `summary_pending`,
  `summarizing`, `error`);
- `compression.error` — текст ошибки сжатия, если конспект создать не удалось.
  Ошибка сжатия **не отменяет** ответ: модель уже ответила, а повтор сжатия
  произойдёт на следующем ходу;
- `compression.saved_percent` — доля экономии относительно полного контекста.

Коды: `200`, `404`, `422` (пустой `prompt`), `502` — сбой генерации
(нет ключа, сеть, лимиты). Тело `502` — тот же `GenerateResponse` со
`status:"error"`, заполненным `error` и **неизменённой** историей (реплика
пользователя откатывается):

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "status": "error",
  "prompt": "Объясни, что такое контекст модели",
  "response": null,
  "error": "Сбой запроса к DeepSeek: ...",
  "model": "deepseek-chat",
  "finish_reason": null,
  "usage": null,
  "token_metrics": null,
  "context": null,
  "duration_sec": 0.12,
  "timestamp": "2026-09-10T12:05:00",
  "messages": []
}
```

## GET /agents/{agent_id}/history

Все реплики диалога по порядку. Поле `summarized` показывает, покрыта ли реплика
конспектом: такие реплики остаются в истории, но в следующий запрос не уходят.

```bash
curl.exe http://127.0.0.1:8000/agents/8f1c2d3e4b5a/history
```

```json
[
  {
    "id": 1,
    "agent_id": "8f1c2d3e4b5a",
    "role": "user",
    "content": "Привет!",
    "timestamp": "2026-09-10T12:01:00",
    "summarized": true
  },
  {
    "id": 2,
    "agent_id": "8f1c2d3e4b5a",
    "role": "assistant",
    "content": "Привет! Чем помочь?",
    "timestamp": "2026-09-10T12:01:02",
    "summarized": true
  },
  {
    "id": 13,
    "agent_id": "8f1c2d3e4b5a",
    "role": "user",
    "content": "Объясни, что такое контекст модели",
    "timestamp": "2026-09-10T12:05:00",
    "summarized": false
  }
]
```

Коды: `200`, `404`.

## DELETE /agents/{agent_id}/history

Очищает диалог агента: удаляются сообщения, все конспекты и метрики. Сама
конфигурация агента (имя, модель, настройки сжатия) не меняется.

```bash
curl.exe -X DELETE http://127.0.0.1:8000/agents/8f1c2d3e4b5a/history
```

```json
{ "status": "cleared", "agent_id": "8f1c2d3e4b5a", "message_count": 0 }
```

Коды: `200`, `404`.

## POST /agents/{agent_id}/summarize

Принудительное сжатие («Сжать сейчас»). По умолчанию (`force:false`) срабатывает
только если набран порог `summarize_every`; с `force:true` в конспект уходит всё,
что выше `keep_last_messages`.

| Поле | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `force` | bool | `false` | `true` — сжать, даже если порог не набран |

Ответ — отчёт о попытке: `attempted` (пытались ли сжимать), `created` (создан ли
новый конспект), `error`, `summarized_messages`, `state` и полный `summary`
(та же схема, что у `GET /summary`).

Сжатие прошло:

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/summarize \
  -H "Content-Type: application/json" \
  -d "{\"force\":true}"
```

```json
{
  "attempted": true,
  "created": true,
  "error": null,
  "summarized_messages": 10,
  "state": "tracking",
  "summary": {
    "agent_id": "8f1c2d3e4b5a",
    "model": "deepseek-chat",
    "enabled": true,
    "keep_last_messages": 6,
    "summarize_every": 10,
    "state": "tracking",
    "message_count": 16,
    "summary_count": 1,
    "covered_messages": 10,
    "uncovered_messages": 6,
    "current": { "id": 1, "agent_id": "8f1c2d3e4b5a", "content": "…конспект…", "covered_from_message_id": 1, "covered_to_message_id": 10, "covered_messages": 10, "source_tokens": 2100, "summary_tokens": 900, "prompt_tokens": 2400, "completion_tokens": 900, "cost": 0.001638, "created_at": "2026-09-10T12:06:00" },
    "history": [
      { "id": 1, "agent_id": "8f1c2d3e4b5a", "content": "…конспект…", "covered_from_message_id": 1, "covered_to_message_id": 10, "covered_messages": 10, "source_tokens": 2100, "summary_tokens": 900, "prompt_tokens": 2400, "completion_tokens": 900, "cost": 0.001638, "created_at": "2026-09-10T12:06:00" }
    ],
    "total_source_tokens": 2100,
    "total_summary_tokens": 900,
    "summary_cost": 0.001638,
    "saved_tokens": 1200,
    "net_saved_tokens": 300,
    "next_compression_in": 10
  }
}
```

Сжимать нечего (порог не набран, `force` не задан) — `created:false` с причиной:

```json
{
  "attempted": true,
  "created": false,
  "error": "Сжимать пока нечего: непокрытых реплик 4, порог сжатия — 6 последних + 10 новых.",
  "summarized_messages": 0,
  "state": "tracking",
  "summary": { "agent_id": "8f1c2d3e4b5a", "uncovered_messages": 4, "summary_count": 0 }
}
```

Сжатие выключено у агента — тоже `created:false`, но попытки не было:

```json
{
  "attempted": false,
  "created": false,
  "error": "Сжатие истории выключено для этого агента",
  "summarized_messages": 0,
  "state": "idle",
  "summary": { "agent_id": "8f1c2d3e4b5a", "enabled": false, "summary_count": 0 }
}
```

Если сам вызов суммаризации не удался (нет ключа, сеть), в `error` попадёт
`"Сбой суммаризации: ..."`, а `state` станет `"error"`. Коды: `200`, `404`.

## GET /agents/{agent_id}/summary

Текущее состояние сжатия: конспект, watermark (сколько и какие реплики покрыты),
история конспектов и экономика.

```bash
curl.exe http://127.0.0.1:8000/agents/8f1c2d3e4b5a/summary
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "model": "deepseek-chat",
  "enabled": true,
  "keep_last_messages": 6,
  "summarize_every": 10,
  "state": "tracking",
  "message_count": 16,
  "summary_count": 1,
  "covered_messages": 10,
  "uncovered_messages": 6,
  "current": {
    "id": 1,
    "agent_id": "8f1c2d3e4b5a",
    "content": "…конспект…",
    "covered_from_message_id": 1,
    "covered_to_message_id": 10,
    "covered_messages": 10,
    "source_tokens": 2100,
    "summary_tokens": 900,
    "prompt_tokens": 2400,
    "completion_tokens": 900,
    "cost": 0.001638,
    "created_at": "2026-09-10T12:06:00"
  },
  "history": [],
  "total_source_tokens": 2100,
  "total_summary_tokens": 900,
  "summary_cost": 0.001638,
  "saved_tokens": 1200,
  "net_saved_tokens": 300,
  "next_compression_in": 10
}
```

Если диалог ещё не сжимался, `current` равен `null`, а `summary_count` — `0`.
Коды: `200`, `404`.

## POST /agents/{agent_id}/compare

Сравнивает два режима контекста на одном промпте: `full` (вся история) и
`compressed` (конспект + последние реплики). **История диалога при этом не
изменяется** — ни при `call_api:false`, ни при `call_api:true`.

| Поле | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `prompt` | строка | — | 1–16000 символов, не пустой |
| `call_api` | bool | `false` | `false` — посчитать только токены; `true` — сделать два реальных вызова DeepSeek |

Только подсчёт токенов (работает без ключа API):

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/compare \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"Сформулируй итог\",\"call_api\":false}"
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "prompt": "Сформулируй итог",
  "call_api": false,
  "history_messages": 16,
  "full": {
    "mode": "full",
    "sent_context_tokens": 5400,
    "full_context_tokens": 5400,
    "summary_used": false,
    "kept_messages": 16,
    "summarized_messages": 0,
    "prompt_tokens": null,
    "completion_tokens": null,
    "total_tokens": null,
    "cost": 0.0,
    "duration_sec": null,
    "response": null,
    "error": null
  },
  "compressed": {
    "mode": "compressed",
    "sent_context_tokens": 1200,
    "full_context_tokens": 5400,
    "summary_used": true,
    "kept_messages": 6,
    "summarized_messages": 10,
    "prompt_tokens": null,
    "completion_tokens": null,
    "total_tokens": null,
    "cost": 0.0,
    "duration_sec": null,
    "response": null,
    "error": null
  },
  "saved_tokens": 4200,
  "saved_percent": 77.8,
  "warning": null
}
```

С реальными вызовами (`call_api:true`) в каждой стороне появляются
`prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`, `duration_sec` и
`response` — оба ответа модели возвращаются рядом для сравнения:

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/compare \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"Сформулируй итог\",\"call_api\":true}"
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "prompt": "Сформулируй итог",
  "call_api": true,
  "history_messages": 16,
  "full": {
    "mode": "full",
    "sent_context_tokens": 5400,
    "full_context_tokens": 5400,
    "summary_used": false,
    "kept_messages": 16,
    "summarized_messages": 0,
    "prompt_tokens": 5420,
    "completion_tokens": 210,
    "total_tokens": 5630,
    "cost": 0.001695,
    "duration_sec": 2.31,
    "response": "Итог по всему диалогу...",
    "error": null
  },
  "compressed": {
    "mode": "compressed",
    "sent_context_tokens": 1200,
    "full_context_tokens": 5400,
    "summary_used": true,
    "kept_messages": 6,
    "summarized_messages": 10,
    "prompt_tokens": 1220,
    "completion_tokens": 190,
    "total_tokens": 1410,
    "cost": 0.000538,
    "duration_sec": 1.94,
    "response": "Итог: ...",
    "error": null
  },
  "saved_tokens": 4200,
  "saved_percent": 77.8,
  "warning": null
}
```

Если один из вызовов не удался, его `error` заполняется, а в общем `warning`
появляется пометка вида `"Часть сравнения не выполнена: ..."`. Коды: `200`,
`404`, `422`.

## GET /agents/{agent_id}/usage

Сводка по таблице `token_usage`: суммы токенов и стоимости, занятость контекста
и экономия от сжатия. Поля дня 9 — `total_full_context_tokens`,
`total_sent_context_tokens`, `total_saved_tokens`, `total_summary_cost`,
`total_net_saved_tokens`, `compressed_requests`.

```bash
curl.exe http://127.0.0.1:8000/agents/8f1c2d3e4b5a/usage
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "model": "deepseek-chat",
  "total_requests": 8,
  "total_prompt_tokens": 3200,
  "total_completion_tokens": 1480,
  "total_tokens": 4680,
  "total_cost": 0.002492,
  "last_usage_at": "2026-09-10T12:05:00",
  "context_limit_tokens": 8000,
  "current_history_tokens": 1200,
  "remaining_tokens": 6800,
  "total_full_context_tokens": 32400,
  "total_sent_context_tokens": 9600,
  "total_saved_tokens": 22800,
  "total_summary_cost": 0.001638,
  "total_net_saved_tokens": 21162,
  "compressed_requests": 6
}
```

Коды: `200`, `404`.

## GET /agents/{agent_id}/usage/graph

Записи `token_usage` по порядку — для таблицы и графика роста токенов и экономии
в интерфейсе. Каждая запись содержит базовые метрики хода и поля сжатия.

```bash
curl.exe http://127.0.0.1:8000/agents/8f1c2d3e4b5a/usage/graph
```

```json
[
  {
    "id": 1,
    "agent_id": "8f1c2d3e4b5a",
    "timestamp": "2026-09-10T12:05:00",
    "prompt_tokens": 320,
    "completion_tokens": 180,
    "total_tokens": 500,
    "history_tokens": 480,
    "response_tokens": 180,
    "cost": 0.000284,
    "mode": "compressed",
    "full_context_tokens": 5400,
    "sent_context_tokens": 1200,
    "saved_tokens": 4200,
    "summary_tokens": 900,
    "summarized_messages": 10,
    "summary_used": true
  }
]
```

Коды: `200`, `404`.

## Формы данных

### AgentSummary

Короткая запись агента в списке `GET /agents`.

| Поле | Тип | Пояснение |
|---|---|---|
| `agent_id` | строка | id, выданный сервером |
| `name` | строка | имя агента |
| `model` | строка | `deepseek-chat` или `deepseek-reasoner` |
| `message_count` | int | число реплик диалога |
| `summary_enabled` | bool | включено ли сжатие |
| `keep_last_messages` | int | сколько реплик всегда «как есть» |
| `summarize_every` | int | порог сжатия |
| `summary_count` | int | сколько конспектов создано |

### AgentInfo (расширяет AgentSummary)

| Поле | Тип | Пояснение |
|---|---|---|
| `temperature` | float | температура генерации, 0.0–2.0 |
| `system_prompt` | строка | системный промпт (роль) |
| `max_tokens` | int | максимум токенов в ответе, 1–8192 |
| `created_at` | datetime | когда создан агент |

### MessageOut

| Поле | Тип | Пояснение |
|---|---|---|
| `id` | int | id сообщения |
| `agent_id` | строка | владелец |
| `role` | строка | `user` или `assistant` |
| `content` | строка | текст реплики |
| `timestamp` | datetime | время записи |
| `summarized` | bool | покрыта ли реплика конспектом (день 9) |

### GenerateResponse

| Поле | Тип | Пояснение |
|---|---|---|
| `agent_id` | строка | id агента |
| `status` | строка | `ok` или `error` |
| `prompt` | строка | отправленный запрос |
| `response` | строка/null | ответ модели (при `ok`) |
| `error` | строка/null | причина сбоя (при `error`) |
| `model` | строка | модель агента |
| `finish_reason` | строка/null | причина остановки генерации |
| `usage` | объект/null | `prompt_tokens`, `completion_tokens`, `total_tokens` от API |
| `token_metrics` | TokenMetrics/null | метрики хода, включая экономию |
| `context` | ContextInfo/null | лимит, остаток, обрезка, состояние, блок сжатия |
| `duration_sec` | float/null | длительность запроса |
| `timestamp` | datetime | время ответа |
| `messages` | [MessageOut] | актуальный диалог **после** попытки |

### TokenMetrics

| Поле | Тип | Пояснение |
|---|---|---|
| `prompt_tokens` | int | токены запроса (по API либо оценка) |
| `completion_tokens` | int | токены ответа |
| `total_tokens` | int | сумма |
| `history_tokens` | int | токены истории |
| `response_tokens` | int | токены ответа (оценка tiktoken) |
| `cost` | float | приблизительная стоимость, $ |
| `mode` | строка | `full` или `compressed` |
| `full_context_tokens` | int | сколько заняла бы полная история |
| `sent_context_tokens` | int | сколько реально отправлено |
| `saved_tokens` | int | `full_context_tokens − sent_context_tokens` |
| `summary_tokens` | int | размер конспекта в токенах |
| `summarized_messages` | int | сколько реплик заменено конспектом |
| `summary_used` | bool | применён ли конспект в этом ходу |

### ContextInfo и CompressionInfo

| ContextInfo | Тип | Пояснение |
|---|---|---|
| `max_model_tokens` | int | демонстрационный лимит контекста модели |
| `payload_tokens` | int | токенов отправлено в запросе |
| `context_tokens` | int | занято контекста |
| `remaining_tokens` | int | остаток до лимита |
| `over_limit` | bool | превышен ли лимит |
| `trimmed_messages` | int | сколько реплик не отправлено предохранителем |
| `warning` | строка/null | заполнен только при обрезке |
| `state` | строка | состояние процесса сжатия |
| `compression` | CompressionInfo/null | блок сжатия |

| CompressionInfo | Тип | Пояснение |
|---|---|---|
| `enabled` | bool | включено ли сжатие у агента |
| `mode` | строка | `full` или `compressed` |
| `summary_used` | bool | применён ли конспект |
| `summary_tokens` | int | размер конспекта |
| `kept_messages` | int | сколько последних реплик отправлено «как есть» |
| `summarized_messages` | int | сколько реплик добавлено в конспект в этом ходу |
| `covered_messages` | int | всего реплик покрыто конспектом |
| `full_context_tokens` | int | токены полного контекста |
| `sent_context_tokens` | int | токены отправленного контекста |
| `saved_tokens` | int | экономия в токенах |
| `saved_percent` | float | экономия в процентах |
| `error` | строка/null | ошибка сжатия (ответ уже получен) |

### SummaryOut

Одна запись таблицы `summaries` (история конспектов).

| Поле | Тип | Пояснение |
|---|---|---|
| `id` | int | id записи |
| `agent_id` | строка | владелец |
| `content` | строка | текст конспекта |
| `covered_from_message_id` | int | первая покрытая реплика |
| `covered_to_message_id` | int | последняя покрытая реплика |
| `covered_messages` | int | сколько реплик покрыто |
| `source_tokens` | int | токены исходных реплик |
| `summary_tokens` | int | токены конспекта |
| `prompt_tokens` | int | токены запроса суммаризации |
| `completion_tokens` | int | токены ответа суммаризации |
| `cost` | float | стоимость вызова суммаризации, $ |
| `created_at` | datetime | когда создан конспект |

### SummaryInfo

Состояние сжатия агента (`GET /summary` и вложенный `summary` в отчёте
`/summarize`).

| Поле | Тип | Пояснение |
|---|---|---|
| `agent_id` | строка | id агента |
| `model` | строка | модель агента |
| `enabled` | bool | включено ли сжатие |
| `keep_last_messages` | int | сколько реплик всегда «как есть» |
| `summarize_every` | int | порог сжатия |
| `state` | строка | состояние процесса сжатия |
| `message_count` | int | всего реплик |
| `summary_count` | int | сколько конспектов |
| `covered_messages` | int | реплик покрыто конспектом |
| `uncovered_messages` | int | реплик ещё не покрыто |
| `current` | SummaryOut/null | текущий (последний) конспект |
| `history` | [SummaryOut] | все конспекты агента |
| `total_source_tokens` | int | сумма токенов исходных реплик |
| `total_summary_tokens` | int | сумма токенов конспектов |
| `summary_cost` | float | суммарная стоимость суммаризаций |
| `saved_tokens` | int | сэкономленные токены запросов |
| `net_saved_tokens` | int | экономия за вычетом стоимости суммаризаций |
| `next_compression_in` | int | сколько непокрытых реплик осталось до порога |

### CompareResult и CompareSide

| CompareResult | Тип | Пояснение |
|---|---|---|
| `agent_id` | строка | id агента |
| `prompt` | строка | промпт сравнения |
| `call_api` | bool | делались ли реальные вызовы |
| `history_messages` | int | размер истории на момент сравнения |
| `full` | CompareSide | сторона «без сжатия» |
| `compressed` | CompareSide | сторона «со сжатием» |
| `saved_tokens` | int | экономия в токенах |
| `saved_percent` | float | экономия в процентах |
| `warning` | строка/null | если часть сравнения не выполнена |

| CompareSide | Тип | Пояснение |
|---|---|---|
| `mode` | строка | `full` или `compressed` |
| `sent_context_tokens` | int | токены отправленного контекста |
| `full_context_tokens` | int | токены полного контекста |
| `summary_used` | bool | использован ли конспект |
| `kept_messages` | int | реплик отправлено «как есть» |
| `summarized_messages` | int | реплик заменено конспектом |
| `prompt_tokens` | int/null | токены запроса (при `call_api:true`) |
| `completion_tokens` | int/null | токены ответа (при `call_api:true`) |
| `total_tokens` | int/null | сумма токенов |
| `cost` | float | стоимость запроса, $ |
| `duration_sec` | float/null | длительность вызова |
| `response` | строка/null | ответ модели |
| `error` | строка/null | ошибка стороны сравнения |

### UsageSummary

| Поле | Тип | Пояснение |
|---|---|---|
| `agent_id` | строка | id агента |
| `model` | строка | модель |
| `total_requests` | int | число запросов |
| `total_prompt_tokens` | int | сумма токенов запросов |
| `total_completion_tokens` | int | сумма токенов ответов |
| `total_tokens` | int | общая сумма |
| `total_cost` | float | суммарная стоимость, $ |
| `last_usage_at` | datetime/null | время последнего запроса |
| `context_limit_tokens` | int | лимит контекста модели |
| `current_history_tokens` | int | токены текущей истории |
| `remaining_tokens` | int | остаток контекста |
| `total_full_context_tokens` | int | сколько заняла бы полная история (день 9) |
| `total_sent_context_tokens` | int | сколько реально отправлено (день 9) |
| `total_saved_tokens` | int | суммарная экономия токенов (день 9) |
| `total_summary_cost` | float | стоимость всех суммаризаций (день 9) |
| `total_net_saved_tokens` | int | чистая экономия (день 9) |
| `compressed_requests` | int | запросов со сжатым контекстом (день 9) |

### UsageOut

Одна запись `token_usage`: `id`, `agent_id`, `timestamp`, `prompt_tokens`,
`completion_tokens`, `total_tokens`, `history_tokens`, `response_tokens`,
`cost`, а также поля дня 9 — `mode`, `full_context_tokens`,
`sent_context_tokens`, `saved_tokens`, `summary_tokens`, `summarized_messages`,
`summary_used`.

## Коды ошибок

| Код | Когда | Тело |
|---|---|---|
| `404` | неизвестный `agent_id` во всех `/agents/{agent_id}/...` | `HTTPException` с `detail` |
| `422` | невалидное тело запроса (Pydantic/FastAPI) | объект с `detail` — списком ошибок |
| `502` | сбой генерации `POST /generate` (нет ключа, сеть, лимиты) | `GenerateResponse` со `status:"error"` |

`404` — например, запрос к удалённому или опечатанному id:

```json
{ "detail": "Агент 8f1c2d3e4b5a не найден" }
```

`422` — например, пустой `prompt` или `temperature` вне диапазона. Формат
стандартный для FastAPI:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "prompt"],
      "msg": "String should have at least 1 character",
      "input": " "
    }
  ]
}
```

`502` — генерация не удалась, история не изменилась:

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "status": "error",
  "prompt": "Объясни, что такое контекст модели",
  "response": null,
  "error": "Сбой запроса к DeepSeek: ...",
  "model": "deepseek-chat",
  "finish_reason": null,
  "usage": null,
  "token_metrics": null,
  "context": null,
  "duration_sec": 0.12,
  "timestamp": "2026-09-10T12:05:00",
  "messages": []
}
```

## Примечания

- **Что появилось в дне 9.** Настройки сжатия в `AgentConfig`/`AgentInfo`/
  `AgentSummary` (`summary_enabled`, `keep_last_messages`, `summarize_every`,
  `summary_count`); поле `summarized` у `MessageOut`; блок метрик
  `token_metrics` и `context.compression` в ответе генерации; эндпоинты
  `/summarize`, `/summary`, `/compare`; поля `mode`, `full_context_tokens`,
  `sent_context_tokens`, `saved_tokens`, `summary_tokens`,
  `summarized_messages`, `summary_used` в записях `token_usage` и
  агрегаты экономии в `UsageSummary`.
- **Семантика `saved_tokens` и `net_saved_tokens`.** `saved_tokens` — это
  `full_context_tokens − sent_context_tokens`, то есть экономия токенов запросов
  (оценка tiktoken). `net_saved_tokens` вычитает из неё собственные токены
  вызовов суммаризации (`prompt_tokens + completion_tokens` из таблицы
  `summaries`). При коротких репликах net-экономия может быть **отрицательной** —
  конспект оказывается дороже заменяемых реплик. Это ожидаемо: пороги
  `summarize_every` и `keep_last_messages` подбираются под длину сообщений.
- **Лимиты контекста 8000/32000.** `deepseek-chat` — 8000 токенов,
  `deepseek-reasoner` — 32000. Это демонстрационные лимиты (как в задании дня 8),
  реальный контекст DeepSeek шире; при необходимости они правятся в
  `MODEL_TOKEN_LIMITS` (`backend/config.py`). По ним считается
  `context.remaining_tokens` и срабатывает аварийный предохранитель
  `trimmed_messages`.
- **Метрики переживают рестарт.** Сообщения, конспекты (`summaries`) и записи
  `token_usage` лежат в SQLite (`day9/agents.db`), при старте приложения
  `lifespan` создаёт таблицы и восстанавливает агентов вместе с историей и
  конспектами (`restore_from_db`). Поэтому `/usage`, `/summary` и `/history`
  после перезапуска показывают те же цифры.
- **Суммаризация всегда на `deepseek-chat`.** Конспект создаётся моделью
  `SUMMARY_MODEL = deepseek-chat` при `temperature = 0.2` и
  `max_tokens = 512`, независимо от модели самого агента.
- **Ошибка сжатия не отменяет ответ.** Если конспект создать не удалось,
  ответ модели уже сохранён и возвращён; текст ошибки виден в
  `context.compression.error` (и в отчёте `/summarize`), состояние процесса
  сжатия переходит в `error`, а повтор произойдёт на следующем ходу.
- **Состояние сжатия не хранится в БД.** Оно выводится из watermark, числа
  непокрытых реплик и порога, поэтому корректно переживает рестарт и ручные
  изменения настроек через `PATCH`.
- **Стоимость приблизительна.** Тарифы берутся из `MODEL_PRICES` ($ за 1 млн
  токенов) и не учитывают кэширование и скидки провайдера. Оценки tiktoken
  (`cl100k_base`) тоже приблизительны — DeepSeek использует свой токенизатор;
  для запроса и ответа приоритет у фактических `usage` API.
