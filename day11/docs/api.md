# API дня 11 — агенты DeepSeek с трёхслойной памятью

Бэкенд — FastAPI-приложение `day11/backend/main.py`. Базовый адрес после запуска
(из папки `day11`):

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

Настройки сжатия и стратегия управления контекстом задаются при создании
агента, меняются через `PATCH` и `POST /agents/{id}/strategy`, видны в ответах.
Три слоя памяти (краткосрочная, рабочая, долговременная) доступны через
эндпоинты `POST/GET/DELETE /agents/{id}/memory/...`, а разбивка контекста по
слоям возвращается в поле `memory` ответа генерации. Схемы ответов описаны в
`day11/backend/models.py`; сводная таблица полей — в разделе
[«Формы данных»](#формы-данных).

## Эндпоинты

Всего 29 эндпоинтов с префиксом `/agents/{agent_id}` плюс корневой `GET /`.

| Метод | Путь | Назначение | Успех |
|---|---|---|---|
| POST | `/agents` | создать агента (конфигурация, сжатие, стратегия) | 201 AgentInfo |
| GET | `/agents` | список агентов с числом сообщений, стратегией и активной задачей | 200 [AgentSummary] |
| GET | `/agents/{agent_id}` | полная информация об агенте (включая `session_id`/`task_id`) | 200 AgentInfo |
| PATCH | `/agents/{agent_id}` | частично обновить агента (в т.ч. стратегию/сжатие) | 200 AgentInfo |
| DELETE | `/agents/{agent_id}` | удалить агента со всеми данными | 200 `{status:"deleted"}` |
| POST | `/agents/{agent_id}/generate` | ход диалога по текущей стратегии + отчёт по слоям | 200 GenerateResponse |
| GET | `/agents/{agent_id}/history` | реплики текущей сессии (с признаком `summarized`) | 200 [MessageOut] |
| DELETE | `/agents/{agent_id}/history` | очистить диалог, факты, ветки, конспекты и метрики | 200 `{status:"cleared"}` |
| POST | `/agents/{agent_id}/summarize` | сжать историю сейчас | 200 отчёт о сжатии |
| GET | `/agents/{agent_id}/summary` | конспект, watermark и экономика | 200 SummaryInfo |
| POST | `/agents/{agent_id}/compare` | сравнить режимы «полная история» и «конспект» | 200 CompareResult |
| GET | `/agents/{agent_id}/usage` | сводка токенов и экономии (включая расход по слоям) | 200 UsageSummary |
| GET | `/agents/{agent_id}/usage/graph` | записи `token_usage` для графика | 200 [UsageOut] |
| POST | `/agents/{agent_id}/strategy` | сменить стратегию (и опц. `window_size`) | 200 StrategiesOut |
| GET | `/agents/{agent_id}/strategies` | текущая стратегия + список доступных | 200 StrategiesOut |
| POST | `/agents/{agent_id}/branches` | создать ветку (чекпоинт) | 200 BranchListOut |
| GET | `/agents/{agent_id}/branches` | дерево веток агента | 200 BranchListOut |
| POST | `/agents/{agent_id}/branches/{branch_id}/switch` | переключить активную ветку | 200 BranchListOut |
| GET | `/agents/{agent_id}/facts` | факты диалога (sticky_facts) | 200 FactsOut |
| POST | `/agents/{agent_id}/memory/short-term` | добавить реплику в краткосрочную память | 201 ShortTermMessageOut |
| GET | `/agents/{agent_id}/memory/short-term` | реплики сессии (по умолчанию текущей) | 200 ShortTermOut |
| DELETE | `/agents/{agent_id}/memory/short-term` | очистить реплики сессии | 200 ShortTermClearOut |
| POST | `/agents/{agent_id}/memory/working` | upsert записи рабочей памяти задачи | 201 WorkingEntryOut |
| GET | `/agents/{agent_id}/memory/working` | записи задачи + список задач агента | 200 WorkingMemoryOut |
| POST | `/agents/{agent_id}/memory/long-term` | upsert записи долговременной памяти | 201 LongTermEntryOut |
| GET | `/agents/{agent_id}/memory/long-term` | записи (все или одной категории) + категории | 200 LongTermMemoryOut |
| DELETE | `/agents/{agent_id}/memory/long-term/{entry_id}` | удалить запись долговременной памяти | 200 LongTermDeleteOut |
| POST | `/agents/{agent_id}/memory/session` | начать новую сессию (очистка краткосрочного слоя) | 200 SessionOut |
| PUT | `/agents/{agent_id}/memory/task` | переключить активную задачу | 200 TaskOut |
| GET | `/` | список доступных эндпоинтов | 200 объект-подсказка |

## GET /

Корневая точка — подсказка: имя приложения, путь к Swagger и перечень
эндпоинтов.

```bash
curl.exe http://127.0.0.1:8000/
```

```json
{
  "name": "Агенты DeepSeek с трёхслойной памятью — День 11",
  "docs": "/docs",
  "memory": "/agents/{agent_id}/memory/... (short-term | working | long-term)",
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
    "GET /agents/{agent_id}/usage/graph",
    "POST /agents/{agent_id}/strategy",
    "GET /agents/{agent_id}/strategies",
    "POST /agents/{agent_id}/branches",
    "GET /agents/{agent_id}/branches",
    "POST /agents/{agent_id}/branches/{branch_id}/switch",
    "GET /agents/{agent_id}/facts",
    "POST /agents/{agent_id}/memory/short-term",
    "GET /agents/{agent_id}/memory/short-term",
    "DELETE /agents/{agent_id}/memory/short-term",
    "POST /agents/{agent_id}/memory/working",
    "GET /agents/{agent_id}/memory/working",
    "POST /agents/{agent_id}/memory/long-term",
    "GET /agents/{agent_id}/memory/long-term",
    "DELETE /agents/{agent_id}/memory/long-term/{entry_id}",
    "POST /agents/{agent_id}/memory/session",
    "PUT /agents/{agent_id}/memory/task"
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
  "session_id": "3f9a1c20",
  "task_id": "default",
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
`system_prompt` / `max_tokens` / `created_at`, но с числом сообщений,
настройками сжатия, активной сессией и задачей.

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
    "summary_count": 1,
    "session_id": "3f9a1c20",
    "task_id": "tz-portal"
  }
]
```

Коды: `200`.

## GET /agents/{agent_id}

Полная информация об агенте (та же короткая запись + параметры генерации, дата
создания и активные сессия/задача). Используется интерфейсом, чтобы показать
конфигурацию выбранного агента.

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
  "session_id": "3f9a1c20",
  "task_id": "tz-portal",
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
  "session_id": "3f9a1c20",
  "task_id": "tz-portal",
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

1. добавляет реплику пользователя в краткосрочный слой (в памяти);
2. собирает блоки рабочей и долговременной памяти и краткосрочный слой по
   стратегии, для `summary` — **два** варианта контекста (полный и сжатый) ради
   метрик экономии; отчёт по слоям (`memory`) заполняется уже здесь;
3. при необходимости вызывает DeepSeek;
4. сохраняет пару реплик (в границах текущей сессии) и метрики, включая токены
   по слоям, одной транзакцией;
5. после успешного хода выполняет действие стратегии (сжатие / сохранение
   фактов / снимок ветки).

Тело запроса:

| Поле | Тип | Ограничение |
|---|---|---|
| `prompt` | строка | 1–16000 символов, не может быть пустым |

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/generate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"Объясни, что такое контекст модели\"}"
```

Ответ `200` (сокращённый, но со всеми полями):

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
    "summary_used": true,
    "short_term_tokens": 1200,
    "working_tokens": 138,
    "long_term_tokens": 147
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
  "memory": {
    "session_id": "3f9a1c20",
    "task_id": "tz-portal",
    "short_term_tokens": 1200,
    "working_tokens": 138,
    "long_term_tokens": 147,
    "total_tokens": 1485,
    "keywords": ["какой", "стек", "команд"],
    "layers": [
      {
        "layer": "short_term",
        "used": true,
        "entries": 6,
        "tokens": 1200,
        "details": "сессия 3f9a1c20, режим compressed"
      },
      {
        "layer": "working",
        "used": true,
        "entries": 6,
        "tokens": 138,
        "details": "задача tz-portal"
      },
      {
        "layer": "long_term",
        "used": true,
        "entries": 2,
        "tokens": 147,
        "details": "ключевые слова: какой, стек, команд"
      }
    ]
  },
  "duration_sec": 1.842,
  "timestamp": "2026-09-10T12:05:00",
  "messages": []
}
```

Пояснения к блоку `memory`:

- `total_tokens` — сумма токенов трёх слоёв
  (`short_term_tokens + working_tokens + long_term_tokens`); конспект в неё не
  входит — он виден отдельно как `token_metrics.summary_tokens`;
- `layers[].entries` — для краткосрочного слоя это число отправленных реплик,
  для рабочего — число записей задачи, для долговременного — число отобранных
  записей; `used` — попал ли слой в контекст;
- `keywords` — ключевые слова запроса, по которым отбирались долговременные
  записи (пусто, если слов длиной ≥ 3 без стоп-слов нет — тогда блок
  заполняется по уверенности, и `details` это отмечает);
- блок заполняется **и при ошибке генерации** (слои читаются из БД до вызова
  API), поэтому отчёт проверяем без ключа.

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
  "memory": {
    "session_id": "3f9a1c20",
    "task_id": "tz-portal",
    "short_term_tokens": 0,
    "working_tokens": 138,
    "long_term_tokens": 147,
    "total_tokens": 285,
    "keywords": ["объясни", "такое", "контекст", "модели"],
    "layers": [
      { "layer": "short_term", "used": false, "entries": 0, "tokens": 0,
        "details": "сессия 3f9a1c20, режим full" },
      { "layer": "working", "used": true, "entries": 6, "tokens": 138,
        "details": "задача tz-portal" },
      { "layer": "long_term", "used": true, "entries": 2, "tokens": 147,
        "details": "ключевые слова: объясни, такое, контекст, модели" }
    ]
  },
  "duration_sec": 0.12,
  "timestamp": "2026-09-10T12:05:00",
  "messages": []
}
```

Здесь `memory` заполнен: блоки памяти собраны до вызова API, поэтому отчёт по
слоям виден и при сбое — `total_tokens` уже посчитан, а `short_term.used`
ложно, если реплик в сессии ещё не было (в запрос идёт только сам промпт).

## GET /agents/{agent_id}/history

Реплики **текущей сессии** по порядку. Поле `summarized` показывает, покрыта ли
реплика конспектом: такие реплики остаются в истории, но в следующий запрос не
уходят. Реплики прошлых сессий удаляются `POST /memory/session`, поэтому в
ответе их нет.

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
    "created_at": "2026-09-10T12:01:00",
    "summarized": true
  },
  {
    "id": 2,
    "agent_id": "8f1c2d3e4b5a",
    "role": "assistant",
    "content": "Привет! Чем помочь?",
    "created_at": "2026-09-10T12:01:02",
    "summarized": true
  },
  {
    "id": 13,
    "agent_id": "8f1c2d3e4b5a",
    "role": "user",
    "content": "Объясни, что такое контекст модели",
    "created_at": "2026-09-10T12:05:00",
    "summarized": false
  }
]
```

Коды: `200`, `404`.

## DELETE /agents/{agent_id}/history

Очищает диалог агента: удаляются реплики всех сессий, конспекты, факты, ветки и
метрики. Конфигурация агента, рабочая и долговременная память не меняются.

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
  "compressed_requests": 6,
  "total_short_term_tokens": 7200,
  "total_working_tokens": 828,
  "total_long_term_tokens": 882
}
```

Коды: `200`, `404`.

## GET /agents/{agent_id}/usage/graph

Записи `token_usage` по порядку — для таблицы и графика роста токенов и экономии
в интерфейсе. Каждая запись содержит базовые метрики хода, поля сжатия и расход
по слоям памяти.

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
    "summary_used": true,
    "short_term_tokens": 1200,
    "working_tokens": 138,
    "long_term_tokens": 147
  }
]
```

Коды: `200`, `404`.

## Стратегии, ветки и факты (день 11)

### POST /agents/{agent_id}/strategy

Меняет стратегию агента (и, опционально, `window_size`). Диалог не теряется.

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/АГЕНТ/strategy `
  -H "Content-Type: application/json" `
  -d '{\"strategy\": \"sticky_facts\", \"window_size\": 5}'
```

```json
{
  "agent_id": "…",
  "strategy": "sticky_facts",
  "window_size": 5,
  "available": ["sliding_window", "sticky_facts", "branching", "summary"]
}
```

Коды: `200`, `404`, `422` (неизвестная стратегия, `window_size` вне 2–50).

### GET /agents/{agent_id}/strategies

Текущая стратегия + `window_size` + список доступных. Ответ — тот же
`StrategiesOut`. Коды: `200`, `404`.

### POST /agents/{agent_id}/branches

Создаёт ветку (чекпоинт) и делает её активной. Тело `{ "checkpoint_id": … }` —
от какого чекпоинта ответвляться; `null`/пропущено — от текущего сообщения.

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/АГЕНТ/branches `
  -H "Content-Type: application/json" -d '{}'
```

```json
{
  "agent_id": "…",
  "active_branch_id": 2,
  "branches": [
    {"id": 1, "agent_id": "…", "parent_id": null, "message_count": 6,
     "created_at": "…", "is_active": false},
    {"id": 2, "agent_id": "…", "parent_id": 1, "message_count": 6,
     "created_at": "…", "is_active": true}
  ]
}
```

### GET /agents/{agent_id}/branches

Дерево веток (чекпоинты с `parent_id` и `is_active`). Ответ — `BranchListOut`.

### POST /agents/{agent_id}/branches/{branch_id}/switch

Переключает активную ветку: история агента заменяется снимком выбранной ветки.
Возвращает обновлённое дерево (`BranchListOut`).

### GET /agents/{agent_id}/facts

Текущие факты диалога (стратегия `sticky_facts`): `{ "agent_id", "facts": [
{"key", "value", "updated_at"}, …] }`. Коды: `200`, `404`.

## Слои памяти (день 11)

Десять эндпоинтов трёх слоёв памяти. Краткосрочный слой привязан к сессии
(`session_id`), рабочий — к задаче (`task_id`), долговременный — к категории
(`category` + `key`). Все они начинаются с проверки агента, поэтому неизвестный
`agent_id` даёт `404`.

### POST /agents/{agent_id}/memory/short-term

Добавляет реплику в краткосрочную память. `session_id` в теле не указан — пишем
в текущую сессию агента.

| Поле | Тип | Ограничение |
|---|---|---|
| `role` | строка | `user` / `assistant` / `system` (иначе `422`) |
| `content` | строка | 1–16000 символов |
| `session_id` | строка/null | сессия; `null` — текущая сессия агента |

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/memory/short-term \
  -H "Content-Type: application/json" \
  -d "{\"role\":\"user\",\"content\":\"Ограничение: только on-premise\"}"
```

```json
{
  "id": 25,
  "agent_id": "8f1c2d3e4b5a",
  "session_id": "3f9a1c20",
  "role": "user",
  "content": "Ограничение: только on-premise",
  "created_at": "2026-09-10T12:10:00"
}
```

Коды: `201`, `404`, `422`.

### GET /agents/{agent_id}/memory/short-term

Реплики сессии в хронологическом порядке.

| Query | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `session_id` | строка/null | текущая сессия | какая сессия читается |
| `limit` | int | 50 | последние `limit` реплик (1–500, иначе `422`) |

```bash
curl.exe "http://127.0.0.1:8000/agents/8f1c2d3e4b5a/memory/short-term?limit=2"
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "session_id": "3f9a1c20",
  "messages": [
    { "id": 24, "agent_id": "8f1c2d3e4b5a", "session_id": "3f9a1c20",
      "role": "assistant", "content": "Принято", "created_at": "2026-09-10T12:09:50" },
    { "id": 25, "agent_id": "8f1c2d3e4b5a", "session_id": "3f9a1c20",
      "role": "user", "content": "Ограничение: только on-premise",
      "created_at": "2026-09-10T12:10:00" }
  ]
}
```

Коды: `200`, `404`, `422`.

### DELETE /agents/{agent_id}/memory/short-term

Удаляет реплики сессии (по умолчанию текущей). Возвращает число удалённых; `0` —
не ошибка. Рабочая и долговременная память не затрагиваются.

```json
{ "agent_id": "8f1c2d3e4b5a", "session_id": "3f9a1c20", "deleted": 24 }
```

Коды: `200`, `404`.

### POST /agents/{agent_id}/memory/working

Upsert записи рабочей памяти по `(task_id, key)`: повторный запрос с тем же
ключом перезаписывает значение.

| Поле | Тип | Ограничение |
|---|---|---|
| `key` | строка | 1–200 символов |
| `value` | строка | 1–16000 символов |
| `task_id` | строка/null | задача (до 64 символов); `null` — активная задача агента |

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/memory/working \
  -H "Content-Type: application/json" \
  -d "{\"key\":\"ограничение\",\"value\":\"только on-premise\"}"
```

```json
{
  "id": 7,
  "agent_id": "8f1c2d3e4b5a",
  "task_id": "tz-portal",
  "key": "ограничение",
  "value": "только on-premise",
  "updated_at": "2026-09-10T12:11:00"
}
```

Коды: `201`, `404`, `422`.

### GET /agents/{agent_id}/memory/working

Записи задачи (по умолчанию активной) и список всех задач агента — для селектора
в интерфейсе.

```bash
curl.exe "http://127.0.0.1:8000/agents/8f1c2d3e4b5a/memory/working?task_id=tz-portal"
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "task_id": "tz-portal",
  "entries": [
    { "id": 4, "agent_id": "8f1c2d3e4b5a", "task_id": "tz-portal", "key": "цель",
      "value": "Корпоративный портал", "updated_at": "2026-09-10T12:02:00" },
    { "id": 7, "agent_id": "8f1c2d3e4b5a", "task_id": "tz-portal",
      "key": "ограничение", "value": "только on-premise",
      "updated_at": "2026-09-10T12:11:00" }
  ],
  "tasks": ["default", "tz-portal"]
}
```

Коды: `200`, `404`.

### POST /agents/{agent_id}/memory/long-term

Upsert записи долговременной памяти по `(category, key)`.

| Поле | Тип | Ограничение |
|---|---|---|
| `category` | строка | `profile` / `preference` / `decision` / `knowledge` (иначе `422`) |
| `key` | строка | 1–200 символов |
| `value` | строка | 1–16000 символов |
| `confidence` | число | 0.0–1.0 (по умолчанию 1.0) |

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/memory/long-term \
  -H "Content-Type: application/json" \
  -d "{\"category\":\"preference\",\"key\":\"язык_интерфейса\",\"value\":\"русский\",\"confidence\":0.95}"
```

```json
{
  "id": 3,
  "agent_id": "8f1c2d3e4b5a",
  "category": "preference",
  "key": "язык_интерфейса",
  "value": "русский",
  "confidence": 0.95,
  "updated_at": "2026-09-10T12:12:00"
}
```

Коды: `201`, `404`, `422` (неизвестная категория или `confidence` вне 0..1).

### GET /agents/{agent_id}/memory/long-term

Записи агента (все или одной категории) + список доступных категорий.

| Query | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `category` | строка/null | все категории | фильтр по категории |

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "category": null,
  "entries": [
    { "id": 2, "agent_id": "8f1c2d3e4b5a", "category": "decision", "key": "бд",
      "value": "PostgreSQL", "confidence": 0.8, "updated_at": "2026-09-10T12:03:00" },
    { "id": 3, "agent_id": "8f1c2d3e4b5a", "category": "preference",
      "key": "язык_интерфейса", "value": "русский", "confidence": 0.95,
      "updated_at": "2026-09-10T12:12:00" }
  ],
  "categories": ["profile", "preference", "decision", "knowledge"]
}
```

Коды: `200`, `404`.

### DELETE /agents/{agent_id}/memory/long-term/{entry_id}

Удаляет запись долговременной памяти по id.

```bash
curl.exe -X DELETE http://127.0.0.1:8000/agents/8f1c2d3e4b5a/memory/long-term/3
```

```json
{ "status": "deleted", "agent_id": "8f1c2d3e4b5a", "entry_id": 3 }
```

Коды: `200`, `404` (нет агента **или** нет записи — во втором случае
`detail: "Запись 3 не найдена"`).

### POST /agents/{agent_id}/memory/session

Начинает новую сессию: удаляются реплики прошлой сессии, конспекты и факты
старого диалога, у агента появляется новый `session_id`. Рабочая и
долговременная память, ветки и метрики сохраняются.

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/memory/session
```

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "previous_session_id": "3f9a1c20",
  "session_id": "7b21e0f4",
  "deleted_messages": 24
}
```

Коды: `200`, `404`.

### PUT /agents/{agent_id}/memory/task

Переключает активную задачу: рабочая память следующих запросов фильтруется по
новому `task_id`. Диалог и краткосрочный слой не затрагиваются.

| Поле | Тип | Ограничение |
|---|---|---|
| `task_id` | строка | 1–64 символа (после обрезки пробелов не пустая) |

```bash
curl.exe -X PUT http://127.0.0.1:8000/agents/8f1c2d3e4b5a/memory/task \
  -H "Content-Type: application/json" \
  -d "{\"task_id\":\"tz-portal\"}"
```

```json
{ "agent_id": "8f1c2d3e4b5a", "task_id": "tz-portal", "entries": 6 }
```

Коды: `200`, `400` (пустой `task_id` после обрезки), `404`, `422` (пустая строка
в теле).

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
| `session_id` | строка | активная сессия краткосрочной памяти (пусто — у схемы нет данных) |
| `task_id` | строка | активная задача рабочей памяти, по умолчанию `default` |

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
| `created_at` | datetime | время записи (бывшее `timestamp`) |
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
| `token_metrics` | TokenMetrics/null | метрики хода, включая экономию и токены по слоям |
| `context` | ContextInfo/null | лимит, остаток, обрезка, состояние, блок сжатия |
| `memory` | MemoryInfo/null | разбивка контекста по слоям памяти (заполнена и при `error`) |
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
| `short_term_tokens` | int | токены отправленной части краткосрочного слоя |
| `working_tokens` | int | токены блока рабочей памяти |
| `long_term_tokens` | int | токены блока долговременной памяти |

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
| `total_short_term_tokens` | int | сумма токенов краткосрочного слоя по ходам (день 11) |
| `total_working_tokens` | int | сумма токенов рабочей памяти по ходам (день 11) |
| `total_long_term_tokens` | int | сумма токенов долговременной памяти по ходам (день 11) |

### UsageOut

Одна запись `token_usage`: `id`, `agent_id`, `timestamp`, `prompt_tokens`,
`completion_tokens`, `total_tokens`, `history_tokens`, `response_tokens`,
`cost`, поля дня 9 — `mode`, `full_context_tokens`, `sent_context_tokens`,
`saved_tokens`, `summary_tokens`, `summarized_messages`, `summary_used`, и поля
дня 11 — `short_term_tokens`, `working_tokens`, `long_term_tokens`.

### Слои памяти

| ShortTermMessageOut | Тип | Пояснение |
|---|---|---|
| `id` | int | id реплики |
| `agent_id` | строка | владелец |
| `session_id` | строка | сессия краткосрочной памяти |
| `role` | строка | `user` / `assistant` / `system` |
| `content` | строка | текст реплики |
| `created_at` | datetime | время записи |

| ShortTermOut | Тип | Пояснение |
|---|---|---|
| `agent_id` | строка | владелец |
| `session_id` | строка | сессия, из которой прочитаны реплики |
| `messages` | [ShortTermMessageOut] | реплики в хронологическом порядке |

`ShortTermClearOut` — `agent_id`, `session_id`, `deleted` (сколько реплик
удалено). `SessionOut` — `agent_id`, `previous_session_id`, `session_id`,
`deleted_messages`.

| WorkingEntryOut | Тип | Пояснение |
|---|---|---|
| `id` | int | id записи |
| `agent_id` | строка | владелец |
| `task_id` | строка | задача, к которой привязана запись |
| `key` | строка | ключ (уникален внутри задачи) |
| `value` | строка | значение |
| `updated_at` | datetime | когда запись создана/обновлена |

`WorkingMemoryOut` — `agent_id`, `task_id`, `entries` ([WorkingEntryOut]) и
`tasks` (все задачи агента, по алфавиту). `TaskOut` — `agent_id`, `task_id`,
`entries` (сколько записей в рабочей памяти этой задачи).

| LongTermEntryOut | Тип | Пояснение |
|---|---|---|
| `id` | int | id записи |
| `agent_id` | строка | владелец |
| `category` | строка | `profile` / `preference` / `decision` / `knowledge` |
| `key` | строка | ключ (уникален внутри категории) |
| `value` | строка | значение |
| `confidence` | float | уверенность 0.0–1.0 |
| `updated_at` | datetime | когда запись создана/обновлена |

`LongTermMemoryOut` — `agent_id`, `category` (фильтр, `null` — все записи),
`entries` ([LongTermEntryOut]), `categories` (доступные категории).
`LongTermDeleteOut` — `status` (`"deleted"`), `agent_id`, `entry_id`.

| MemoryInfo | Тип | Пояснение |
|---|---|---|
| `session_id` | строка | сессия, в которой собран контекст |
| `task_id` | строка | активная задача |
| `layers` | [MemoryLayerInfo] | по элементу на слой: `layer`, `used`, `entries`, `tokens`, `details` |
| `short_term_tokens` | int | токены отправленной части краткосрочного слоя |
| `working_tokens` | int | токены блока рабочей памяти |
| `long_term_tokens` | int | токены блока долговременной памяти |
| `total_tokens` | int | сумма трёх слоёв (конспект сюда не входит) |
| `keywords` | [строка] | ключевые слова запроса, по которым отобран долговременный слой |

## Коды ошибок

| Код | Когда | Тело |
|---|---|---|
| `400` | пустой `task_id` после обрезки пробелов в `PUT /memory/task` | `HTTPException` с `detail` |
| `404` | неизвестный `agent_id` во всех `/agents/{agent_id}/...` (а для `DELETE /memory/long-term/{id}` — ещё и отсутствующая запись) | `HTTPException` с `detail` |
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
  "memory": {
    "session_id": "3f9a1c20",
    "task_id": "tz-portal",
    "short_term_tokens": 0,
    "working_tokens": 138,
    "long_term_tokens": 147,
    "total_tokens": 285,
    "keywords": ["объясни", "такое", "контекст", "модели"],
    "layers": [
      { "layer": "short_term", "used": false, "entries": 0, "tokens": 0,
        "details": "сессия 3f9a1c20, режим full" },
      { "layer": "working", "used": true, "entries": 6, "tokens": 138,
        "details": "задача tz-portal" },
      { "layer": "long_term", "used": true, "entries": 2, "tokens": 147,
        "details": "ключевые слова: объясни, такое, контекст, модели" }
    ]
  },
  "duration_sec": 0.12,
  "timestamp": "2026-09-10T12:05:00",
  "messages": []
}
```

## Примечания

- **Что появилось в дне 11.** Три слоя памяти: таблицы `short_term_messages`,
  `working_memory`, `long_term_memory`; поля `session_id`/`task_id` в
  `AgentSummary`/`AgentInfo`; десять эндпоинтов `/agents/{id}/memory/...`;
  схемы `ShortTermMessageIn`/`ShortTermMessageOut`/`ShortTermOut`/
  `ShortTermClearOut`, `WorkingEntryIn`/`WorkingEntryOut`/`WorkingMemoryOut`,
  `LongTermEntryIn`/`LongTermEntryOut`/`LongTermMemoryOut`/`LongTermDeleteOut`,
  `SessionOut`, `TaskSetRequest`/`TaskOut`, `MemoryInfo`/`MemoryLayerInfo`;
  поле `memory` в `GenerateResponse`; поля `short_term_tokens`,
  `working_tokens`, `long_term_tokens` в `TokenMetrics`/`UsageOut`/
  `UsageSummary`. Поле времени реплики переименовано: `timestamp` →
  `created_at` в `MessageOut`.
- **Что появилось раньше (стратегии, ветки, факты).** Поля `strategy` и
  `window_size` в `AgentConfig`/`AgentInfo`/`AgentSummary`; поле `strategy` в
  `ContextInfo`; эндпоинты `/strategy`, `/strategies`, `/branches`,
  `/branches/{branch_id}/switch`, `/facts`; схемы `StrategiesOut`,
  `BranchCreateRequest`/`BranchOut`/`BranchListOut`, `FactOut`/`FactsOut`;
  таблицы `facts` и `checkpoints`.
- **Что появилось в дне 9.** Настройки сжатия в `AgentConfig`/`AgentInfo`/
  `AgentSummary` (`summary_enabled`, `keep_last_messages`, `summarize_every`,
  `summary_count`); поле `summarized` у `MessageOut`; блок метрик
  `token_metrics` и `context.compression` в ответе генерации; эндпоинты
  `/summarize`, `/summary`, `/compare`; поля `mode`, `full_context_tokens`,
  `sent_context_tokens`, `saved_tokens`, `summary_tokens`,
  `summarized_messages`, `summary_used` в записях `token_usage` и
  агрегаты экономии в `UsageSummary`.
- **Токены по слоям и конспект.** `memory.total_tokens` — сумма трёх слоёв;
  конспект в неё не входит, потому что это сжатие того же краткосрочного слоя
  (он виден отдельно как `token_metrics.summary_tokens`). Токены нового промпта
  тоже не принадлежат слоям: реплика становится памятью только после успешного
  хода, поэтому в первой реплике новой сессии `memory.short_term_tokens = 0`.
- **Что удаляет `POST /memory/session`.** Реплики прошлой сессии, конспекты
  (`summaries`) и факты (`facts` — они производны от конкретного диалога).
  Рабочая и долговременная память, `checkpoints` и `token_usage` сохраняются:
  счётчик токенов и стоимость живут дольше одной сессии. `DELETE
  /agents/{id}/history` дополнительно чистит `token_usage` и `checkpoints`.
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
- **Всё состояние переживает рестарт.** Реплики (`short_term_messages`), рабочая
  (`working_memory`) и долговременная (`long_term_memory`) память, конспекты
  (`summaries`), факты (`facts`), ветки (`checkpoints`) и записи `token_usage`
  лежат в SQLite (`day11/agents.db`), а активные сессия и задача — в строке
  `agents` (`current_session_id`/`current_task_id`). При старте приложения
  `lifespan` создаёт таблицы и восстанавливает агентов вместе с диалогом
  (`restore_from_db`), поэтому `/usage`, `/summary`, `/history` и эндпоинты
  `/memory/...` после перезапуска показывают те же данные.
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
