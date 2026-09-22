# API дня 17 — агенты DeepSeek с MCP-инструментами, контролируемыми переходами, инвариантами, состоянием задачи, памятью и профилем

Бэкенд — FastAPI-приложение `day17/backend/api/main.py`. Заголовок приложения —
«Агенты DeepSeek + MCP — День 17», версия схемы — `11.0.0`
(видны в Swagger UI и `GET /openapi.json`). Базовый адрес после запуска
(из папки `day17`):

```powershell
uv run uvicorn backend.api.main:app --port 8000
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
слоям возвращается в поле `memory` ответа генерации.

Кроме агентов API закрывает три слоя памяти, профили пользователей, состояние
задачи как конечный автомат с **контролируемыми переходами** (граф допуска,
guard-условия, журнал отклонённых попыток) и инварианты проекта.

**Контролируемые переходы** (день 15) — правила, по которым задача меняет этап.
Куда можно перейти, решает единственная таблица `ALLOWED_TRANSITIONS`
(`backend/domain/task_state_machine.py`): `done` терминален, `paused` возвращает
только в рабочие этапы, а три перехода вперёд закрыты guard-условиями — флагами
`plan_approved`, `implementation_complete`, `validation_passed`. Недопустимая
попытка **не меняет** состояние задачи: она попадает в журнал
`task_transitions` строкой с `accepted: false` и возвращается кодом `400` с
причиной отказа и подсказкой, что сделать. Кнопки панели задачи рисуются по
ответу `GET /tasks/{task_id}/allowed-next`, поэтому интерфейс не дублирует
правила допуска у себя. Разбор — в разделе
[«Состояние задачи»](#состояние-задачи).

**Инварианты** — правила проекта, которые агент не имеет права нарушать: они
лежат в отдельной таблице `invariants`, блок активных правил подставляется в
системный промпт каждого запроса сразу после роли агента, а предложение
проверяется перед выдачей — сначала детерминированными правилами, при
неоднозначности одним вызовом LLM. Нарушение `hard`-инварианта превращается в
отказ, `soft` — в предупреждение. Управление — шесть эндпоинтов `/invariants...`
и раздел «📏 Инварианты» в интерфейсе; разбор — в разделе
[«Инварианты»](#инварианты).

Профиль пользователя: у агента есть поле `user_id` — идентификатор
пользователя, чей профиль из таблицы `user_profiles` подключается **первым** блоком к системному промпту каждого запроса (до роли
агента и до блоков памяти). Профиль заводится и правится через `/users/...`,
применяется к живым агентам пользователя сразу, без перезапуска; его вклад
виден в `GET /agents/{id}/profile` и в полях `profile`/`system_prompt` ответа
генерации. Агент без профиля работает как обычно: пустой профиль не даёт
блоков промпта и ошибкой не считается.

**MCP-инструменты** (день 17) — подключение к MCP-серверу (Model Context
Protocol), его каталог и **вызов инструмента**: шесть эндпоинтов `/mcp/connect`,
`/mcp/disconnect`, `/mcp/status`, `/mcp/tools`, `/mcp/call` и `/mcp/servers`.
Транспорт выбирается по виду цели (команда запуска — stdio, `http://` —
Streamable HTTP, `sse://` — SSE), список инструментов отдаётся полями `name`,
`description`, `input_schema`, `output_schema` вместе с `count`. Свой сервер дня
живёт в `day17/mcp_server/` (stdio, инструменты `get_user`, `get_post`,
`list_user_posts` поверх jsonplaceholder.typicode.com), а агент сам решает по
ключевым словам реплики, нужен ли вызов, и подставляет полученные данные в
системный промпт того же запроса (поле `mcp` ответа генерации). Соединение одно
на процесс и **не переживает** перезапуск бэкенда (это связь с внешним процессом,
а не данные домена); при остановке приложения оно закрывается в `lifespan`.
Разбор — в разделе [«MCP»](#mcp).

Схемы ответов описаны в пакете `day17/backend/schemas/` — по доменам: `agent.py`
(агент, генерация, метрики), `context.py` (сжатие, стратегии, ветки, факты),
`invariant.py` (инварианты и результат проверки), `mcp.py` (статус MCP-подключения,
инструменты сервера, их вызов и каталог серверов), `memory.py` (три слоя памяти),
`profile.py` (профиль и его вклад в промпт), `task.py` (состояние задачи, его
переходы и журнал); сводная таблица полей — в
разделе [«Формы данных»](#формы-данных).

## Эндпоинты

Всего 59 эндпоинтов: 11 в разделе агентов (десять эндпоинтов CRUD, генерации и
статистики плюс корневой `GET /`), 9 контекста (сжатие, стратегии, ветки,
факты), 10 памяти, 6 профилей пользователей, 11 состояния задачи, 6 инвариантов
и 6 MCP.
Ниже — сводка; разбор по группам —
в разделах [«Слои памяти»](#слои-памяти),
[«Персонализация»](#персонализация-профили-пользователей),
[«Состояние задачи»](#состояние-задачи),
[«Инварианты»](#инварианты) и [«MCP»](#mcp).

| Метод | Путь | Назначение | Успех |
|---|---|---|---|
| POST | `/agents` | создать агента (конфигурация, сжатие, стратегия, `user_id`) | 201 AgentInfo |
| GET | `/agents` | список агентов с числом сообщений, стратегией, активной задачей и `user_id` | 200 [AgentSummary] |
| GET | `/agents/{agent_id}` | полная информация об агенте (включая `session_id`/`task_id`/`user_id`) | 200 AgentInfo |
| PATCH | `/agents/{agent_id}` | частично обновить агента (в т.ч. стратегию/сжатие/`user_id`) | 200 AgentInfo |
| DELETE | `/agents/{agent_id}` | удалить агента со всеми данными | 200 `{status:"deleted"}` |
| POST | `/agents/{agent_id}/generate` | ход диалога по текущей стратегии + отчёт по слоям + применённый профиль | 200 GenerateResponse |
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
| GET | `/users` | список профилей пользователей | 200 [UserProfileOut] |
| GET | `/users/{user_id}/profile` | профиль пользователя (404 — если профиля нет) | 200 UserProfileOut |
| POST | `/users/{user_id}/profile` | создать профиль (409 — если уже есть) | 201 UserProfileOut |
| PUT | `/users/{user_id}/profile` | заменить настройки профиля + применить к живым агентам | 200 UserProfileOut |
| DELETE | `/users/{user_id}/profile` | удалить профиль (агенты остаются без персонализации) | 200 `{status:"deleted"}` |
| GET | `/agents/{agent_id}/profile` | профиль, применяемый к запросам агента, и его вклад в промпт | 200 AppliedProfileOut |
| POST | `/agents/{agent_id}/tasks` | завести состояние задачи (этап по умолчанию — `planning`) | 201 TaskStateOut |
| GET | `/agents/{agent_id}/tasks` | незавершённые задачи агента (пауза считается активной) | 200 [TaskStateOut] |
| GET | `/tasks/{task_id}/state` | текущий этап, шаг, ожидаемое действие и допустимые переходы | 200 TaskStateOut |
| GET | `/tasks/{task_id}/history` | журнал переходов и отклонённых попыток (поле `accepted`) | 200 TaskHistoryOut |
| GET | `/tasks/{task_id}/allowed-next` | куда задача может перейти сейчас + причины запретов | 200 TaskAllowedNextOut |
| PATCH | `/tasks/{task_id}/context` | флаги-согласования этапов (guard-условия переходов вперёд) | 200 TaskStateOut |
| POST | `/tasks/{task_id}/pause` | пауза с сохранением этапа и шага | 200 TaskStateOut |
| POST | `/tasks/{task_id}/resume` | продолжение с того же места | 200 TaskStateOut |
| POST | `/tasks/{task_id}/advance` | следующий шаг (на последнем шаге этапа — следующий этап) | 200 TaskStateOut |
| POST | `/tasks/{task_id}/rollback` | откат ровно на один этап назад | 200 TaskStateOut |
| POST | `/tasks/{task_id}/transition` | переход в указанный этап/шаг (им пользуются кнопки-этапы панели задачи) | 200 TaskStateOut |
| POST | `/invariants` | создать инвариант проекта (имя уникально) | 201 InvariantOut |
| GET | `/invariants` | список правил (фильтры `category`, `active_only`) | 200 [InvariantOut] |
| GET | `/invariants/{invariant_id}` | одно правило | 200 InvariantOut |
| PUT | `/invariants/{invariant_id}` | изменить переданные поля (в т.ч. `is_active`) | 200 InvariantOut |
| DELETE | `/invariants/{invariant_id}` | удалить правило | 200 `{id, deleted}` |
| POST | `/invariants/check` | проверить текст так же, как агент проверяет ход | 200 InvariantCheckOut |
| POST | `/mcp/connect` | подключиться к MCP-серверу (URL или команда запуска) | 200 MCPStatusResponse |
| POST | `/mcp/disconnect` | закрыть соединение с MCP-сервером (и процесс stdio) | 200 MCPStatusResponse |
| GET | `/mcp/status` | состояние MCP-подключения, сервер, число инструментов | 200 MCPStatusResponse |
| GET | `/mcp/tools` | список инструментов сервера (`name`, `description`, `input_schema`, `output_schema`, `count`) | 200 MCPToolsResponse |
| POST | `/mcp/call` | вызвать инструмент с аргументами (400/409/502 — отказ или сбой) | 200 MCPCallResponse |
| GET | `/mcp/servers` | каталог известных MCP-серверов и подключённый из них | 200 MCPServersResponse |
| GET | `/` | список доступных эндпоинтов | 200 объект-подсказка |

## GET /

Корневая точка — подсказка: имя приложения, путь к Swagger, префиксы памяти,
персонализации, состояния задачи (отдельным ключом — группа `task_transitions`)
и инвариантов, а также перечень эндпоинтов (52 строки — все, кроме самого
`GET /`).

```bash
curl.exe http://127.0.0.1:8000/
```

```json
{
  "name": "Агенты DeepSeek с контролируемыми переходами и MCP — День 17",
  "docs": "/docs",
  "memory": "/agents/{agent_id}/memory/... (short-term | working | long-term)",
  "personalization": "/users, /users/{user_id}/profile, /agents/{agent_id}/profile",
  "tasks": "/agents/{agent_id}/tasks, /tasks/{task_id}/state, ... (11 эндпоинтов)",
  "task_transitions": "/tasks/{task_id}/transition, /tasks/{task_id}/allowed-next, /tasks/{task_id}/context",
  "invariants": "/invariants, /invariants/{invariant_id}, /invariants/check (6 эндпоинтов)",
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
    "PUT /agents/{agent_id}/memory/task",
    "GET /users",
    "GET /users/{user_id}/profile",
    "POST /users/{user_id}/profile",
    "PUT /users/{user_id}/profile",
    "DELETE /users/{user_id}/profile",
    "GET /agents/{agent_id}/profile",
    "POST /agents/{agent_id}/tasks",
    "GET /agents/{agent_id}/tasks",
    "GET /tasks/{task_id}/state",
    "GET /tasks/{task_id}/history",
    "GET /tasks/{task_id}/allowed-next",
    "PATCH /tasks/{task_id}/context",
    "POST /tasks/{task_id}/pause",
    "POST /tasks/{task_id}/resume",
    "POST /tasks/{task_id}/advance",
    "POST /tasks/{task_id}/rollback",
    "POST /tasks/{task_id}/transition",
    "POST /invariants",
    "GET /invariants",
    "GET /invariants/{invariant_id}",
    "PUT /invariants/{invariant_id}",
    "DELETE /invariants/{invariant_id}",
    "POST /invariants/check"
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

Персонализация: поле `user_id` (строка 1–64 символа, по умолчанию
`"default"`) указывает, чей профиль подключается к системному промпту запросов
агента. Профиль создавать заранее не обязательно — агент с несуществующим
профилем работает без персонализации.

Например, что означают эти поля:

| Поле | Смысл |
|---|---|
| `summary_enabled` | включено ли сжатие истории в конспект |
| `keep_last_messages` | сколько последних реплик всегда отправлять «как есть» (2–20) |
| `summarize_every` | порог: конспектируем, когда непокрытых реплик накопилось не меньше этого числа (2–40) |
| `user_id` | пользователь, чей профиль применяется к запросам агента (1–64 символа) |

Запрос:

```bash
curl.exe -X POST http://127.0.0.1:8000/agents \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Учитель\",\"model\":\"deepseek-chat\",\"temperature\":0.7,\"max_tokens\":1024,\"system_prompt\":\"Ты объясняешь просто.\",\"summary_enabled\":true,\"keep_last_messages\":6,\"summarize_every\":10,\"user_id\":\"strict_tech\"}"
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
  "user_id": "strict_tech",
  "temperature": 0.7,
  "system_prompt": "Ты объясняешь просто.",
  "max_tokens": 1024,
  "created_at": "2026-09-10T12:00:00"
}
```

Коды: `201`, `422` (невалидное тело — например, пустое имя, `temperature`
вне 0.0–2.0, `max_tokens` вне 1–8192, `keep_last_messages` вне 2–20, пустой
`user_id`).

## GET /agents

Список всех агентов. Для каждого — короткая запись без `temperature` /
`system_prompt` / `max_tokens` / `created_at`, но с числом сообщений,
настройками сжатия, активной сессией, задачей и профилем пользователя
(`user_id`).

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
    "task_id": "tz-portal",
    "user_id": "strict_tech"
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
  "user_id": "strict_tech",
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
| `user_id` | строка | 1–64 символа; переключает профиль живого агента |

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
  "user_id": "strict_tech",
  "temperature": 0.7,
  "system_prompt": "Ты объясняешь просто.",
  "max_tokens": 1024,
  "created_at": "2026-09-10T12:00:00"
}
```

Пример — переключить живого агента на другого пользователя (его профиль
подхватится следующим же запросом, перезапуск не нужен):

```bash
curl.exe -X PATCH http://127.0.0.1:8000/agents/8f1c2d3e4b5a \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"friendly_mentor\"}"
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

1. добавляет реплику пользователя в краткосрочный слой (в памяти) и обновляет
   состояние задачи по намерению реплики («пауза», «продолжи», «подтверждаю») —
   до сборки контекста, поэтому блок состояния в промпте того же запроса уже
   описывает новое место задачи; намерение, которое правила допуска не пустили,
   состояние не меняет: оно попадает в журнал (`accepted: false`) и
   возвращается в отчёте полем `task_intent`;
2. собирает ОДНО системное сообщение: блок профиля пользователя (если профиль
   не пуст) → системный промпт (роль) агента → рабочая память → долговременная
   память → конспект → факты → состояние задачи (если задача заведена); блок
   профиля — часть системного сообщения, поэтому он попадает в контекст при
   любой стратегии и учитывается в оценке токенов;
3. собирает блоки рабочей и долговременной памяти и краткосрочный слой по
   стратегии, для `summary` — **два** варианта контекста (полный и сжатый) ради
   метрик экономии; отчёт по слоям (`memory`) заполняется уже здесь;
4. при необходимости вызывает DeepSeek;
5. проверяет ответ модели на предложение перейти в другой этап
   (`backend/domain/task_proposal.py`): недопустимое предложение не выполняется и
   не остаётся в ответе — вместо него уходит отказ с причиной и подсказкой, а
   само предложение видно в поле `task_proposal`;
6. сохраняет пару реплик (в границах текущей сессии) и метрики, включая токены
   по слоям, одной транзакцией;
7. после успешного хода выполняет действие стратегии (сжатие / сохранение
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
  "profile": {
    "user_id": "strict_tech",
    "name": "Инженер",
    "personalized": true,
    "summary": "Инженер · технический/кратко/русский/plain text · ≤600 символов",
    "elements": [
      { "field": "name", "label": "обращение", "value": "Инженер", "text": "Обращайся к пользователю по имени: Инженер." },
      { "field": "preferences.tone", "label": "стиль (tone)", "value": "технический", "text": "Стиль общения: технический — точные термины и конкретика, без вводных фраз, эмодзи и «воды»." },
      { "field": "preferences.format", "label": "формат (format)", "value": "plain text", "text": "Формат ответа: plain text — простой текст без markdown-разметки." },
      { "field": "preferences.verbosity", "label": "длина (verbosity)", "value": "кратко", "text": "Длина ответа: кратко — только суть, без прелюдий и повторов." },
      { "field": "preferences.language", "label": "язык (language)", "value": "русский", "text": "Язык ответа: русский." },
      { "field": "constraints.max_response_length", "label": "ограничение длины", "value": "600", "text": "Жёсткое ограничение: весь ответ не длиннее 600 символов." }
    ],
    "prompt_block": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\nОбращайся к пользователю по имени: Инженер.\nСтиль общения: технический — точные термины и конкретика, без вводных фраз, эмодзи и «воды».\nФормат ответа: plain text — простой текст без markdown-разметки.\nДлина ответа: кратко — только суть, без прелюдий и повторов.\nЯзык ответа: русский.\nЖёсткое ограничение: весь ответ не длиннее 600 символов.",
    "system_prompt": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\n…\n\nТы объясняешь просто.\n\nРабочая память задачи tz-portal:\n…",
    "instructions": []
  },
  "task_state": null,
  "task_intent": null,
  "task_proposal": null,
  "system_prompt": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\n…\n\nТы объясняешь просто.\n\nРабочая память задачи tz-portal:\n…",
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

Пояснения к персонализации:

- `profile` — применённый к запросу профиль (`AppliedProfileOut`): `elements`
  (по элементу на каждую заполненную настройку), `prompt_block` — текст блока
  персонализации, `instructions` — произвольные инструкции профиля; при пустом
  профиле `personalized: false`, `elements: []`, `prompt_block: ""`;
- `system_prompt` — итоговое system-сообщение запроса: блок профиля, роль
  агента (`config.system_prompt`), рабочая и долговременная память, конспект и
  факты, склеенные в одно сообщение (порядок блоков — в шаге 2 выше). Это ровно
  тот текст, который ушёл в модель;
- оба поля считаются **до** вызова DeepSeek, поэтому присутствуют и в ответе
  `502`. Токены блока профиля входят в общие `prompt_tokens` /
  `sent_context_tokens`, но не в разбивку `memory` — она считает только три слоя
  памяти.

Пояснения к контролируемым переходам:

- `task_state` — состояние задачи на момент ответа (`TaskStateOut` или `null`,
  если активной задачи нет): среди его полей `allowed_next` (этапы, доступные
  сейчас с учётом флагов) и `blocked` (`[{stage, reason}]` — остальные с
  причиной отказа). Поле считается **до** вызова DeepSeek, поэтому заполнено и
  при `502`;
- `task_intent` — отчёт о намерении реплики: `{intent, applied, reason,
  allowed_next}`. `null`, когда намерения в реплике нет, задачи не заведено или
  задача завершена (`done` на реплики не реагирует). При `applied: false` в
  `reason` — причина отказа, в `allowed_next` — доступные этапы, а ответ
  начинается с уведомления `⚠️ Переход по реплике «…» не выполнен: …`;
- `task_proposal` — предложенный моделью, но недопустимый переход:
  `{proposed, allowed_next, reason, hint}`. `null`, когда предложения нет или оно
  допустимо (допустимое предложение перехода тоже не выполняется — этапы двигает
  пользователь). Недопустимое предложение заменяет ответ отказом
  `🚧 Ответ предлагает переход в …`, а состояние задачи не меняется;
- блок состояния в `system_prompt` заканчивается фразой «Не пытайся перейти в
  недопустимый этап — сначала заверши текущий.» — модель видит границу, за
  которую правила допуска её не пустят.

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
  "profile": {
    "user_id": "strict_tech",
    "name": "Инженер",
    "personalized": true,
    "summary": "Инженер · технический/кратко/русский/plain text · ≤600 символов",
    "elements": [
      { "field": "name", "label": "обращение", "value": "Инженер", "text": "Обращайся к пользователю по имени: Инженер." },
      { "field": "preferences.tone", "label": "стиль (tone)", "value": "технический", "text": "Стиль общения: технический — точные термины и конкретика, без вводных фраз, эмодзи и «воды»." }
    ],
    "prompt_block": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\n…",
    "system_prompt": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\n…",
    "instructions": []
  },
  "system_prompt": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\n…",
  "duration_sec": 0.12,
  "timestamp": "2026-09-10T12:05:00",
  "messages": []
}
```

Здесь `memory` и `profile` заполнены: блоки памяти и профиль собраны до вызова
API, поэтому отчёт по слоям и вклад персонализации видны и при сбое —
`total_tokens` уже посчитан, а `short_term.used` ложно, если реплик в сессии ещё
не было (в запрос идёт только сам промпт). Так же считаются до вызова DeepSeek
`task_state` (вместе с `allowed_next` и `blocked`) и `invariants`, а `task_intent`
заполняется ещё раньше — намерение реплики двигает состояние в этом же запросе.
При `502` остаётся `null` только `task_proposal`: проверять нечего — ответа
модели нет.

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
и экономия от сжатия. Поля сжатия — `total_full_context_tokens`,
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

## Стратегии, ветки и факты

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

## Слои памяти

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

## Персонализация: профили пользователей

Шесть эндпоинтов. Профиль лежит в таблице `user_profiles` и привязан к
`user_id` (строка 1–64 символа): одни и те же настройки действуют для всех
агентов пользователя, всех его задач и сессий. Профиль — не слой памяти: он не
хранит диалог и не отбирается по релевантности, а целиком подставляется
**первым** блоком в системное сообщение каждого запроса (до роли агента и до
блоков памяти), поэтому работает при любой стратегии, а его токены входят в
общие `prompt_tokens`/`sent_context_tokens`.

Внешнего ключа между `agents.user_id` и `user_profiles.user_id` нет намеренно:
удаление профиля не уносит агентов — они остаются работоспособными и просто
теряют персонализацию.

Тело `POST` и `PUT` — схема `UserProfileIn` (`extra="forbid"`: неизвестное поле
объекта → `422`). Тело описывает профиль целиком; непереданные поля получают
значения по умолчанию «не настроено»:

| Поле | Тип | Ограничение |
|---|---|---|
| `name` | строка | до 100 символов; пусто — без обращения по имени |
| `preferences` | объект | `tone`, `verbosity`, `language`, `format` (таблица ниже) |
| `constraints` | объект | `max_response_length`, `forbidden_topics`, `required_disclaimers` |
| `custom_instructions` | строка | до 4000 символов; до 30 инструкций, каждая до 500 символов; одна инструкция на строку |

Допустимые значения `preferences` (пустое значение = «не настроено» и в промпт
не попадает):

| Поле | Допустимые значения |
|---|---|
| `tone` | `формальный` / `дружелюбный` / `технический` |
| `verbosity` | `кратко` / `подробно` / `сбалансировано` |
| `language` | `русский` / `английский` |
| `format` | `markdown` / `plain text` / `структурированный` |

Границы `constraints`: `max_response_length` — 20–8000 символов (`null` — без
ограничения); `forbidden_topics` — до 20 тем по 100 символов;
`required_disclaimers` — до 20 вставок по 500 символов. Неизвестное значение
перечисления, неизвестное поле объекта или выход за границы → `422`.

Как выглядит вклад профиля в промпт: заполненные поля становятся элементами
(`elements`) и строками блока персонализации (`prompt_block`); пустые
пропускаются, профиль без настроек даёт пустой блок и `personalized: false`.

### GET /users

Все профили из таблицы `user_profiles` — для селектора пользователя в
интерфейсе. Каждая запись — `UserProfileOut`: настройки, ограничения,
`custom_instructions`, метки времени, однострочное описание `summary` и признак
`personalized`.

```bash
curl.exe http://127.0.0.1:8000/users
```

```json
[
  {
    "id": 1,
    "user_id": "strict_tech",
    "name": "Инженер",
    "preferences": { "tone": "технический", "verbosity": "кратко", "language": "русский", "format": "plain text" },
    "constraints": { "max_response_length": 600, "forbidden_topics": [], "required_disclaimers": [] },
    "custom_instructions": "",
    "created_at": "2026-09-10T12:00:00+00:00",
    "updated_at": "2026-09-10T12:00:00+00:00",
    "summary": "Инженер · технический/кратко/русский/plain text · ≤600 символов",
    "personalized": true,
    "applied_to_agents": 0
  },
  {
    "id": 2,
    "user_id": "friendly_mentor",
    "name": "Илья",
    "preferences": { "tone": "дружелюбный", "verbosity": "подробно", "language": "русский", "format": "markdown" },
    "constraints": { "max_response_length": null, "forbidden_topics": ["политика"], "required_disclaimers": [] },
    "custom_instructions": "Объясняй простыми словами, используй аналогии\nОбращайся ко мне по имени",
    "created_at": "2026-09-10T12:00:10+00:00",
    "updated_at": "2026-09-10T12:00:10+00:00",
    "summary": "Илья · дружелюбный/подробно/русский/markdown · запреты: политика · инструкций: 2",
    "personalized": true,
    "applied_to_agents": 0
  }
]
```

Пустой список (`[]`) — профилей ещё нет, это не ошибка. Коды: `200`.

### GET /users/{user_id}/profile

Профиль одного пользователя — тот же `UserProfileOut`. Используется интерфейсом,
чтобы показать форму редактирования и предпросмотр блока промпта.

```bash
curl.exe http://127.0.0.1:8000/users/strict_tech/profile
```

```json
{
  "id": 1,
  "user_id": "strict_tech",
  "name": "Инженер",
  "preferences": { "tone": "технический", "verbosity": "кратко", "language": "русский", "format": "plain text" },
  "constraints": { "max_response_length": 600, "forbidden_topics": [], "required_disclaimers": [] },
  "custom_instructions": "",
  "created_at": "2026-09-10T12:00:00+00:00",
  "updated_at": "2026-09-10T12:00:00+00:00",
  "summary": "Инженер · технический/кратко/русский/plain text · ≤600 символов",
  "personalized": true,
  "applied_to_agents": 0
}
```

Коды: `200`, `404` — профиля с таким `user_id` нет:

```json
{ "detail": "Профиль пользователя strict_tech не найден" }
```

### POST /users/{user_id}/profile

Создаёт профиль. `user_id` берётся из пути (в теле его нет). Если у
пользователя уже есть живые агенты, профиль применяется к ним сразу — следующий
же запрос агента идёт с персонализацией.

Запрос:

```bash
curl.exe -X POST http://127.0.0.1:8000/users/strict_tech/profile \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Инженер\",\"preferences\":{\"tone\":\"технический\",\"verbosity\":\"кратко\",\"language\":\"русский\",\"format\":\"plain text\"},\"constraints\":{\"max_response_length\":600},\"custom_instructions\":\"\"}"
```

Ответ `201`:

```json
{
  "id": 1,
  "user_id": "strict_tech",
  "name": "Инженер",
  "preferences": { "tone": "технический", "verbosity": "кратко", "language": "русский", "format": "plain text" },
  "constraints": { "max_response_length": 600, "forbidden_topics": [], "required_disclaimers": [] },
  "custom_instructions": "",
  "created_at": "2026-09-10T12:00:00+00:00",
  "updated_at": "2026-09-10T12:00:00+00:00",
  "summary": "Инженер · технический/кратко/русский/plain text · ≤600 символов",
  "personalized": true,
  "applied_to_agents": 0
}
```

Коды: `201`, `409` — профиль с таким `user_id` уже есть:

```json
{ "detail": "Профиль пользователя strict_tech уже существует" }
```

`422` — невалидные поля: неизвестное значение перечисления (например,
`"tone": "строгий"`), неизвестное поле объекта (`{"constraints": {"max_words":
100}}`), выход за границы (`max_response_length: 10`, имя длиннее 100 символов,
инструкции длиннее 4000 символов) — формат ошибки стандартный для FastAPI.

### PUT /users/{user_id}/profile

**Заменяет** настройки профиля целиком: поля, не переданные в теле, сбрасываются
в «не настроено» (в отличие от `PATCH` у агента). `created_at` сохраняется,
`updated_at` обновляется. Профиль обязан существовать — иначе `404` (создавайте
через `POST`).

Живые агенты пользователя получают новые настройки немедленно, без перезапуска;
сколько их было обновлено, показывает поле `applied_to_agents`.

```bash
curl.exe -X PUT http://127.0.0.1:8000/users/strict_tech/profile \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Инженер\",\"preferences\":{\"tone\":\"технический\",\"verbosity\":\"сбалансировано\",\"language\":\"русский\",\"format\":\"структурированный\"},\"constraints\":{},\"custom_instructions\":\"Всегда предлагай два варианта решения\"}"
```

```json
{
  "id": 1,
  "user_id": "strict_tech",
  "name": "Инженер",
  "preferences": { "tone": "технический", "verbosity": "сбалансировано", "language": "русский", "format": "структурированный" },
  "constraints": { "max_response_length": null, "forbidden_topics": [], "required_disclaimers": [] },
  "custom_instructions": "Всегда предлагай два варианта решения",
  "created_at": "2026-09-10T12:00:00+00:00",
  "updated_at": "2026-09-10T12:03:00+00:00",
  "summary": "Инженер · технический/сбалансировано/русский/структурированный · инструкций: 1",
  "personalized": true,
  "applied_to_agents": 1
}
```

Коды: `200`, `404` (профиля нет), `422` (невалидные поля — как у `POST`).

### DELETE /users/{user_id}/profile

Удаляет профиль. Агенты пользователя **не удаляются**: они остаются с пустым
профилем (персонализация выключена) и отвечают как обычно. Краткосрочная,
рабочая и долговременная память, конспекты, ветки и метрики не затрагиваются.

```bash
curl.exe -X DELETE http://127.0.0.1:8000/users/strict_tech/profile
```

```json
{ "status": "deleted", "user_id": "strict_tech" }
```

Коды: `200`, `404` — профиля нет:

```json
{ "detail": "Профиль пользователя strict_tech не найден" }
```

### GET /agents/{agent_id}/profile

Что именно уйдёт в запросы агента: настройки применённого профиля и его вклад в
системный промпт — `AppliedProfileOut`.

| Поле | Тип | Пояснение |
|---|---|---|
| `user_id` | строка | пользователь, чей профиль применён |
| `name` | строка | имя для обращения из профиля |
| `personalized` | bool | `false`, если профиля нет или он пуст |
| `summary` | строка | однострочное описание профиля |
| `elements` | [ProfileElementOut] | по элементу на каждую заполненную настройку: `field`, `label`, `value`, `text` |
| `prompt_block` | строка | весь блок персонализации (текст без блоков памяти задачи) |
| `system_prompt` | строка | системное сообщение агента без блоков памяти текущего запроса (профиль + роль) |
| `instructions` | [строка] | произвольные инструкции профиля, по одной на строку `custom_instructions` |

```bash
curl.exe http://127.0.0.1:8000/agents/8f1c2d3e4b5a/profile
```

```json
{
  "user_id": "friendly_mentor",
  "name": "Илья",
  "personalized": true,
  "summary": "Илья · дружелюбный/подробно/русский/markdown · запреты: политика · инструкций: 2",
  "elements": [
    { "field": "name", "label": "обращение", "value": "Илья", "text": "Обращайся к пользователю по имени: Илья." },
    { "field": "preferences.tone", "label": "стиль (tone)", "value": "дружелюбный", "text": "Стиль общения: дружелюбный — тепло и просто, уместны эмодзи и обращение к собеседнику напрямую." },
    { "field": "preferences.format", "label": "формат (format)", "value": "markdown", "text": "Формат ответа: markdown — заголовки, списки, блоки кода." },
    { "field": "preferences.verbosity", "label": "длина (verbosity)", "value": "подробно", "text": "Длина ответа: подробно — с пояснениями, примерами и обоснованием." },
    { "field": "preferences.language", "label": "язык (language)", "value": "русский", "text": "Язык ответа: русский." },
    { "field": "constraints.forbidden_topics", "label": "запрещённые темы", "value": "политика", "text": "Не обсуждай темы: политика. Если запрос про них — вежливо откажись и предложи другую формулировку." },
    { "field": "custom_instructions", "label": "инструкции пользователя", "value": "Объясняй простыми словами, используй аналогии | Обращайся ко мне по имени", "text": "Дополнительные инструкции пользователя (выполняй буквально):\n- Объясняй простыми словами, используй аналогии\n- Обращайся ко мне по имени" }
  ],
  "prompt_block": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\nОбращайся к пользователю по имени: Илья.\nСтиль общения: дружелюбный — тепло и просто, уместны эмодзи и обращение к собеседнику напрямую.\nФормат ответа: markdown — заголовки, списки, блоки кода.\nДлина ответа: подробно — с пояснениями, примерами и обоснованием.\nЯзык ответа: русский.\nНе обсуждай темы: политика. Если запрос про них — вежливо откажись и предложи другую формулировку.\nДополнительные инструкции пользователя (выполняй буквально):\n- Объясняй простыми словами, используй аналогии\n- Обращайся ко мне по имени",
  "system_prompt": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\n…\n\nТы объясняешь просто.",
  "instructions": ["Объясняй простыми словами, используй аналогии", "Обращайся ко мне по имени"]
}
```

Профиля у пользователя агента нет — ответ без персонализации (не ошибка):

```json
{
  "user_id": "default",
  "name": "",
  "personalized": false,
  "summary": "без настроек",
  "elements": [],
  "prompt_block": "",
  "system_prompt": "Ты объясняешь просто.",
  "instructions": []
}
```

Коды: `200`, `404` (неизвестный `agent_id`).

### Профиль и три слоя памяти

- **краткосрочная** память (`short_term_messages`, привязана к сессии) — реплики
  диалога; профиль её не читает и не пишет. Новая сессия
  (`POST /memory/session`) и `DELETE /memory/short-term` очищают диалог, но
  профиль не трогают: после новой сессии персонализация та же;
- **рабочая** память (`working_memory`, привязана к задаче) — данные задачи;
  `PUT /memory/task` переключает задачу, профиль не меняется. Блок профиля и
  блок рабочей памяти сосуществуют в одном системном сообщении (профиль —
  раньше);
- **долговременная** память (`long_term_memory`, привязана к агенту) — записи
  `profile`/`preference`/`decision`/`knowledge`, отбираемые по ключевым словам
  запроса: это **данные** для ответа, а не инструкции о стиле. Профиль же —
  таблица `user_profiles` по `user_id`: одни и те же настройки применяются ко
  всем агентам пользователя, ко всем задачам и сессиям, меняются на лету и не
  зависят от того, что попало в долговременную память.

Формально профиль — четвёртый по счёту источник в системном сообщении, но не
слой памяти: он не хранит диалог и не отбирается по релевантности, а
подставляется целиком в каждый запрос. Оценки токенов слоёв (`memory` в ответе
генерации) считают только три слоя; токены блока профиля входят в общие
`prompt_tokens` / `sent_context_tokens`.

## Состояние задачи

Одиннадцать эндпоинтов. Состояние задачи — конечный автомат: пять **этапов**
(`planning`, `execution`, `validation`, `done`, `paused`) и **шаги** внутри
этапов. Этап, шаг и ожидаемое действие лежат в таблице `task_states` (по строке
на задачу), каждый переход — в журнале `task_transitions`; состояние читается из
БД на каждый запрос, поэтому переживает перезапуск процесса.

| Этап | Шаги этапа | Смысл |
|---|---|---|
| `planning` | `gather_requirements`, `define_scope`, `create_plan` | уточнение требований, границы задачи, план |
| `execution` | `implement`, `test_locally` | реализация и её локальная проверка |
| `validation` | `review`, `run_tests`, `finalize` | ревью, тесты, итоговое подтверждение |
| `done` | — (шагов нет) | задача сдана; `current_step` остаётся `finalize` |
| `paused` | — (шагов нет) | шаг сохраняется: продолжение вернёт в тот же этап и шаг |

События автомата — `advance` (следующий шаг), `rollback` (откат на предыдущий
этап), `pause` и `resume`. Классы этапов (`backend/domain/task_fsm.py`) описывают
только шаги **внутри** этапа и то, какая пара «этап, шаг» получится из события;
право на сам переход этапа даёт граф допуска
(`backend/domain/task_state_machine.py`):

```text
прямой ход:    planning -> execution -> validation -> done
откат:         execution -> planning;  validation -> execution
пауза:         planning|execution|validation -> paused
возобновление: paused -> planning|execution|validation
терминал:      done -> переходов нет
guards:        planning->execution: plan_approved
               execution->validation: implementation_complete
               validation->done: validation_passed
```

**Граф допуска** — таблица `ALLOWED_TRANSITIONS` («этап → куда разрешено»): пары,
которой в таблице нет, отклоняются, а не «переходят по умолчанию». `done`
терминален: из сданной задачи переходов нет вовсе — даже на паузу. Откаты
(`execution → planning`, `validation → execution`) и пауза guard-условий не
имеют: их решает только граф.

| Из этапа | Куда можно перейти (по графу) |
|---|---|
| `planning` | `execution` (guard `plan_approved`), `paused` |
| `execution` | `validation` (guard `implementation_complete`), `planning`, `paused` |
| `validation` | `done` (guard `validation_passed`), `execution`, `paused` |
| `done` | — (терминальный этап) |
| `paused` | `planning`, `execution`, `validation` (свой этап возврата или достижимый из этапа паузы) |

**Guard-условия и флаги.** Три перехода вперёд открывает явное согласование
пользователя — флаг в `task_states.context`, который выставляет
`PATCH /tasks/{task_id}/context` (чекбоксы «📝 План утверждён», «⚙️ Реализация
завершена», «✅ Валидация пройдена» в панели задачи):

| Переход | Флаг | Текст отказа без флага |
|---|---|---|
| `planning → execution` | `plan_approved` | «Нельзя перейти в execution: план не утверждён» |
| `execution → validation` | `implementation_complete` | «Нельзя перейти в validation: реализация не завершена» |
| `validation → done` | `validation_passed` | «Нельзя перейти в done: валидация не пройдена» |

Флаг считается выставленным, только если в `context` лежит именно `true` (строка
`"true"` или `1` — нет): согласование, прошедшее мимо интерфейса, не должно
открывать переход. Выход из паузы тоже под guard-условием: продолжаться можно в
этап, откуда задачу поставили на паузу, или в этап, достижимый из этапа паузы,
поэтому `paused → done` невозможен — «Нельзя перейти из paused в done: из паузы
возвращаются только в planning, execution или validation». Движение **назад**
сбрасывает согласования этапа-цели и всех последующих этапов (`cleared_flags`):
после отката «план утверждён» уже не факт, и оставлять флаг выставленным значило
бы пропустить этап при следующем движении вперёд. Правило действует и для
`rollback`, и для перехода назад кнопкой-этапом.

`advance` идёт по шагам этапа, а с его последнего шага — на первый шаг следующего
этапа (`create_plan → execution/implement`, `test_locally → validation/review`,
`finalize → done/finalize`). Но выход из этапа закрыт без согласования: последний
`advance` в `planning` без `plan_approved` отвечает `400` («Нельзя перейти в
execution: план не утверждён») и пишет строку журнала. `rollback` — ровно один
этап назад, с шагом на первый шаг целевого этапа. Из `planning` и `done`
откатываться некуда, а `advance` и `rollback` на паузе запрещены: сначала
`resume`.

**Порядок проверки перехода** — «этап понятен → граф и guard → шаг принадлежит
этапу → действие задано». Отказ называет первую настоящую причину, а не её
следствие: неизвестный этап, пропуск этапа, откат больше чем на этап, отсутствие
флага, шаг чужого этапа. Отказ — это `InvalidTransitionError`
(`backend/domain/task_fsm.py`) плюс строка журнала: состояние задачи он не
меняет и возвращается кодом `400`. Неизвестный этап или шаг в теле запроса
отсекает схема — это `422`, а не `400`: значения проверяются по `Enum` ещё до
стейт-машины.

**Журнал попыток.** Каждый состоявшийся переход попадает в `task_transitions`
(и в JSON-поле `history` строки) с причиной: «задача создана», «следующий шаг»,
«пауза», «продолжение после паузы», «откат на предыдущий этап», «задача
завершена», «откат по реплике пользователя», «переход по запросу». Любая
недопустимая попытка попадает туда же строкой с `accepted: false` (`true` — у
состоявшихся переходов), а `to_stage`/`to_step` у такой строки могут быть пустыми
— попытку перехода в неизвестный этап иначе не записать. Поэтому журнал отвечает
и на вопрос «что пользователь пытался сделать и почему не вышло». Изменение
флагов — не переход, в журнал оно не пишется.

**Блок состояния в промпте.** Блок добавляется **последним** в системное
сообщение каждого запроса (после профиля, роли, памяти, конспекта и фактов) —
независимо от стратегии управления контекстом:

```text
Состояние задачи (текущий этап и шаг; продолжай с этого места):
Текущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены.
```

Допустимые следующие этапы называются явно (это тот же `allowed_next`; пустой
список пишется как «нет»), поэтому модель видит границу, за которую правила
допуска её не пустят. Ожидаемое действие — текст из
`backend/domain/task_prompt.py`: по строке на пару «этап + шаг» (например,
`planning/create_plan` — «ожидается утверждение плана пользователем»,
`validation/run_tests` — «ожидается проверка тестов»), у `paused` — «задача на
паузе; ожидается продолжение (resume)», у `done` — «задача завершена; ожидается
новая задача».

**Реплика и ответ модели.** Реплика пользователя сама двигает состояние:
`backend/domain/task_intent.py` распознаёт намерение (приоритет — пауза →
продолжение → откат → подтверждение шага) **до** сборки контекста, поэтому блок в
промпте того же запроса уже описывает новое состояние. Совпадение ищется на
границе слова, поэтому «продолжительность сессии» намерением не считается.
Намерение, которое граф не пустил, диалог не роняет: отказ уходит в журнал
(`accepted: false`), возвращается в отчёте генерации (`task_intent`) и
добавляется к ответу уведомлением «⚠️ Переход по реплике «advance» не выполнен:
…». Отдельно проверяется и ответ модели (`backend/domain/task_proposal.py`): если
он предлагает недопустимый переход, вместо предложения уходит отказ «🚧 Ответ
предлагает переход в done, но это недопустимо. …», а `task_proposal` попадает в
отчёт генерации. Упоминание **текущего** этапа («приступаю к реализации», когда
задача уже на `execution`) предложением не считается, а допустимое предложение
перехода не выполняется: этапы двигает пользователь.

Активна задача, у которой `stage != "done"` (пауза считается активной). Блок
состояния подключается к промпту только у активной задачи агента, поэтому
`POST /agents/{agent_id}/tasks` делает созданную задачу активной.

| Метод и путь | Тело | Ответ | Коды |
|---|---|---|---|
| `POST /agents/{agent_id}/tasks` | `TaskCreateIn` | `TaskStateOut` | `201`, `404`, `409`, `422` |
| `GET /agents/{agent_id}/tasks` | — | `[TaskStateOut]` | `200`, `404` |
| `GET /tasks/{task_id}/state` | — | `TaskStateOut` | `200`, `404` |
| `GET /tasks/{task_id}/history` | — | `TaskHistoryOut` | `200`, `404` |
| `GET /tasks/{task_id}/allowed-next` | — | `TaskAllowedNextOut` | `200`, `404` |
| `PATCH /tasks/{task_id}/context` | `TaskFlagsIn` | `TaskStateOut` | `200`, `400`, `404`, `422` |
| `POST /tasks/{task_id}/pause` | — | `TaskStateOut` | `200`, `400`, `404` |
| `POST /tasks/{task_id}/resume` | — | `TaskStateOut` | `200`, `400`, `404` |
| `POST /tasks/{task_id}/advance` | — | `TaskStateOut` | `200`, `400`, `404` |
| `POST /tasks/{task_id}/rollback` | `TaskRollbackIn` | `TaskStateOut` | `200`, `400`, `404`, `422` |
| `POST /tasks/{task_id}/transition` | `TaskTransitionIn` | `TaskStateOut` | `200`, `400`, `404`, `422` |

### POST /agents/{agent_id}/tasks

Заводит состояние задачи у существующего агента: этап (по умолчанию
`planning`), первый шаг этапа и ожидаемое действие. Повторный `task_id` — `409`,
состояние не перезаписывается. Созданная задача становится активной задачей
агента, поэтому её блок сразу попадает в системный промпт.

| Поле | Тип | Ограничение |
|---|---|---|
| `task_id` | строка | 1–64 символа, уникален глобально |
| `initial_stage` | строка | `planning` / `execution` / `validation` (по умолчанию `planning`); `paused` и `done` — `422` |

```bash
curl.exe -X POST http://127.0.0.1:8000/agents/8f1c2d3e4b5a/tasks \
  -H "Content-Type: application/json" \
  -d "{\"task_id\":\"tz\",\"initial_stage\":\"planning\"}"
```

```json
{
  "id": 1,
  "task_id": "tz",
  "agent_id": "8f1c2d3e4b5a",
  "stage": "planning",
  "current_step": "gather_requirements",
  "expected_action": "ожидается уточнение требований пользователем",
  "context": {
    "task_id": "tz",
    "working_memory": {}
  },
  "history": [
    {
      "at": "2026-09-10T12:20:00+00:00",
      "from_stage": null,
      "from_step": null,
      "to_stage": "planning",
      "to_step": "gather_requirements",
      "reason": "задача создана",
      "expected_action": "ожидается уточнение требований пользователем"
    }
  ],
  "created_at": "2026-09-10T12:20:00+00:00",
  "updated_at": "2026-09-10T12:20:00+00:00",
  "rollback_stage": null,
  "paused_from_stage": null,
  "is_active": true,
  "allowed_next": ["paused"],
  "blocked": [
    { "stage": "execution", "reason": "Нельзя перейти в execution: план не утверждён" },
    { "stage": "validation", "reason": "Нельзя перейти из planning в validation: пропущен этап execution" },
    { "stage": "done", "reason": "Нельзя перейти из planning в done: пропущены этапы execution и validation" }
  ],
  "prompt_block": "Состояние задачи (текущий этап и шаг; продолжай с этого места):\nТекущий этап задачи: planning. Допустимые следующие этапы: paused. Ожидаемое действие: ожидается уточнение требований пользователем. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: gather_requirements. Предыдущие шаги: нет."
}
```

`context` — снимок рабочей памяти задачи (`working_memory`, по ключам) и
флаги-согласования, если они уже выставлены (`plan_approved`,
`implementation_complete`, `validation_passed`). Метки паузы в `context` не
лежат: этап возврата — отдельное поле строки `paused_from_stage`, а шаг паузы не
меняется, поэтому дублировать его не нужно. `rollback_stage` — куда приведёт
откат (`null` — откатываться некуда), а `allowed_next`/`blocked` — что доступно
прямо сейчас с учётом флагов (тот же расчёт, что у
`GET /tasks/{task_id}/allowed-next`).

Коды: `201`, `404` (нет агента), `409` («Задача tz уже существует»), `422`.

### GET /agents/{agent_id}/tasks

Незавершённые задачи агента по возрастанию `id` — для селектора активной задачи
в интерфейсе. Завершённые не возвращаются (их видно в `GET
/tasks/{task_id}/state` и в журнале), пауза считается активной.

```bash
curl.exe http://127.0.0.1:8000/agents/8f1c2d3e4b5a/tasks
```

```json
[
  {
    "id": 1,
    "task_id": "tz",
    "agent_id": "8f1c2d3e4b5a",
    "stage": "execution",
    "current_step": "implement",
    "expected_action": "ожидается реализация модуля",
    "rollback_stage": "planning",
    "paused_from_stage": null,
    "is_active": true,
    "allowed_next": ["planning", "paused"],
    "prompt_block": "…Текущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
  },
  { "id": 2, "task_id": "tz2", "agent_id": "8f1c2d3e4b5a", "stage": "planning",
    "current_step": "define_scope", "expected_action": "ожидается определение границ задачи агентом",
    "rollback_stage": null, "paused_from_stage": null, "is_active": true,
    "allowed_next": ["paused"], "blocked": [ "…причины запретов…" ],
    "prompt_block": "…" }
]
```

Каждый элемент — полный `TaskStateOut` (в примере опущены `context`, `history`,
`created_at`, `updated_at`).

Коды: `200`, `404`.

### GET /tasks/{task_id}/state

Текущее состояние задачи: этап, шаг, ожидаемое действие и производные поля
(`rollback_stage`, `paused_from_stage`, `is_active`, `allowed_next`, `blocked`,
`prompt_block`). `prompt_block` — ровно тот текст, который уходит в системный
промпт запроса, а `allowed_next`/`blocked` — результат правил допуска с учётом
выставленных флагов.

```bash
curl.exe http://127.0.0.1:8000/tasks/tz/state
```

```json
{
  "id": 1,
  "task_id": "tz",
  "agent_id": "8f1c2d3e4b5a",
  "stage": "execution",
  "current_step": "implement",
  "expected_action": "ожидается реализация модуля",
  "context": {
    "task_id": "tz",
    "working_memory": { "ограничение": "только on-premise" },
    "plan_approved": true
  },
  "history": [ "…четыре записи: создание и три перехода «следующий шаг»…" ],
  "created_at": "2026-09-10T12:20:00+00:00",
  "updated_at": "2026-09-10T12:24:00+00:00",
  "rollback_stage": "planning",
  "paused_from_stage": null,
  "is_active": true,
  "allowed_next": ["planning", "paused"],
  "blocked": [
    { "stage": "validation", "reason": "Нельзя перейти в validation: реализация не завершена" },
    { "stage": "done", "reason": "Нельзя перейти из execution в done: пропущен этап validation" }
  ],
  "prompt_block": "Состояние задачи (текущий этап и шаг; продолжай с этого места):\nТекущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

До этой точки задачу довели три вызова `POST /tasks/tz/advance`
(`gather_requirements → define_scope → create_plan`), а границу этапов открыл
флаг: `PATCH /tasks/tz/context` с `{"plan_approved": true}` — без него
последний `advance` в `planning` вернул бы `400` («Нельзя перейти в execution:
план не утверждён»). В `blocked` видно, что `validation` закрыта тем же способом
(`implementation_complete`), а `done` недостижим и графом — от `execution` до
него пропущен `validation`.

Коды: `200`, `404`.

### GET /tasks/{task_id}/history

Журнал по возрастанию `id`, включая создание задачи (у него
`from_stage`/`from_step` пусты) и отклонённые попытки. Поле `accepted` отличает
состоявшийся переход (`true`) от занесённой в журнал попытки (`false`): у
отклонённой строки состояние задачи прежнее, а `to_stage`/`to_step` могут быть
`null` — попытку перехода в неизвестный этап иначе не записать. Причины
повторяют операции: «задача создана», «следующий шаг», «пауза», «продолжение
после паузы», «откат на предыдущий этап», «задача завершена», а у отклонённых
строк — текст отказа.

```bash
curl.exe http://127.0.0.1:8000/tasks/tz/history
```

```json
{
  "task_id": "tz",
  "entries": [
    { "id": 1, "task_id": "tz", "from_stage": null, "from_step": null,
      "to_stage": "planning", "to_step": "gather_requirements", "accepted": true,
      "reason": "задача создана", "created_at": "2026-09-10T12:20:00+00:00" },
    { "id": 2, "task_id": "tz", "from_stage": "planning", "from_step": "gather_requirements",
      "to_stage": "planning", "to_step": "define_scope", "accepted": true,
      "reason": "следующий шаг", "created_at": "2026-09-10T12:21:00+00:00" },
    { "id": 3, "task_id": "tz", "from_stage": "planning", "from_step": "define_scope",
      "to_stage": "planning", "to_step": "create_plan", "accepted": true,
      "reason": "следующий шаг", "created_at": "2026-09-10T12:22:00+00:00" },
    { "id": 4, "task_id": "tz", "from_stage": "planning", "from_step": "create_plan",
      "to_stage": "execution", "to_step": "implement", "accepted": true,
      "reason": "следующий шаг", "created_at": "2026-09-10T12:24:00+00:00" },
    { "id": 5, "task_id": "tz", "from_stage": "execution", "from_step": "implement",
      "to_stage": "done", "to_step": null, "accepted": false,
      "reason": "Нельзя перейти из execution в done: пропущен этап validation",
      "created_at": "2026-09-10T12:26:00+00:00" }
  ]
}
```

Запись `id: 5` — попытка `POST /tasks/tz/transition` с `{"stage": "done"}`:
состояние задачи она не изменила (задача осталась на `execution/implement`), но
в журнале осталась — вместе с причиной отказа.

Коды: `200`, `404`.

### GET /tasks/{task_id}/allowed-next

Куда задача может перейти прямо сейчас и что мешает остальным переходам —
отдельный, самый дешёвый способ спросить об этом, не читая всю строку состояния.

| Поле | Тип | Пояснение |
|---|---|---|
| `task_id` | строка | задача |
| `stage` | строка | текущий этап |
| `allowed_next` | [строка] | этапы, доступные сейчас с учётом графа и флагов |
| `blocked` | [TaskBlockedOut] | остальные этапы с причиной отказа (`stage`, `reason`) |

```bash
curl.exe http://127.0.0.1:8000/tasks/tz/allowed-next
```

```json
{
  "task_id": "tz",
  "stage": "planning",
  "allowed_next": ["paused"],
  "blocked": [
    { "stage": "execution", "reason": "Нельзя перейти в execution: план не утверждён" },
    { "stage": "validation", "reason": "Нельзя перейти из planning в validation: пропущен этап execution" },
    { "stage": "done", "reason": "Нельзя перейти из planning в done: пропущены этапы execution и validation" }
  ]
}
```

Порядок этапов — прямой ход плюс пауза в конце (`planning`, `execution`,
`validation`, `done`, `paused`), поэтому `blocked` читается как «что и почему
закрыто» без дополнительных запросов. Кнопки панели задачи рисуются по этому
ответу: недоступные этапы в ней заблокированы, а `reason` идёт в подсказку.

Коды: `200`, `404` (неизвестная задача).

### PATCH /tasks/{task_id}/context

Выставляет флаги-согласования этапов — guard-условия переходов вперёд. Тело
`TaskFlagsIn`: три необязательных флага, непереданный (`null`) не меняется.
Ответ — обновлённое `TaskStateOut` (обычно меняется `allowed_next`: флаг открывает
ровно свой переход).

| Поле | Тип | Пояснение |
|---|---|---|
| `plan_approved` | bool | согласование плана: открывает `planning → execution` |
| `implementation_complete` | bool | согласование реализации: открывает `execution → validation` |
| `validation_passed` | bool | согласование валидации: открывает `validation → done` |

```bash
curl.exe -X PATCH http://127.0.0.1:8000/tasks/tz/context \
  -H "Content-Type: application/json" \
  -d "{\"plan_approved\":true}"
```

```json
{
  "id": 1,
  "task_id": "tz",
  "agent_id": "8f1c2d3e4b5a",
  "stage": "planning",
  "current_step": "create_plan",
  "expected_action": "ожидается утверждение плана пользователем",
  "context": { "task_id": "tz", "working_memory": {}, "plan_approved": true },
  "history": [ "…записи журнала не изменились: флаги — не переход…" ],
  "rollback_stage": null,
  "paused_from_stage": null,
  "is_active": true,
  "allowed_next": ["execution", "paused"],
  "blocked": [
    { "stage": "validation", "reason": "Нельзя перейти из planning в validation: пропущен этап execution" },
    { "stage": "done", "reason": "Нельзя перейти из planning в done: пропущены этапы execution и validation" }
  ],
  "prompt_block": "…Допустимые следующие этапы: execution, paused.…"
}
```

Тело без единого флага (`{}`, а также `{"nope": true}` или опечатка
`{"plan_aproved": true}`) — `422`: запрос, который ничего не меняет, почти всегда
означает опечатку в имени поля, и молча вернуть `200` хуже, чем сказать об этом.
Изменение флагов в `task_transitions` не пишется: это не переход. Сбросить флаг
можно, передав `false`.

Коды: `200`, `400` (ошибка поля на стороне сервиса), `404`, `422` (ни одного
флага в теле).

### POST /tasks/{task_id}/pause

Ставит задачу на паузу, **сохраняя** этап и шаг: продолжение вернёт её ровно
туда, где она встала. В ответе `stage = "paused"`, `current_step` не меняется,
поле строки `paused_from_stage` описывает точку возврата (отдельного «шага
паузы» нет: это и есть `current_step`), а `expected_action` — «задача на паузе;
ожидается продолжение (resume)». Повторная пауза — `400` («Нельзя перейти из
paused в paused: задача уже на этом этапе»); пауза завершённой задачи — `400`
(«Нельзя перейти из done: этап done терминальный»), потому что из `done`
переходов нет вовсе.

```bash
curl.exe -X POST http://127.0.0.1:8000/tasks/tz/pause
```

```json
{
  "id": 1,
  "task_id": "tz",
  "agent_id": "8f1c2d3e4b5a",
  "stage": "paused",
  "current_step": "implement",
  "expected_action": "задача на паузе; ожидается продолжение (resume)",
  "context": {
    "task_id": "tz",
    "working_memory": { "ограничение": "только on-premise" },
    "plan_approved": true
  },
  "history": [ "…пятая запись: reason «пауза»…" ],
  "created_at": "2026-09-10T12:20:00+00:00",
  "updated_at": "2026-09-10T12:25:00+00:00",
  "rollback_stage": null,
  "paused_from_stage": "execution",
  "is_active": true,
  "allowed_next": ["planning", "execution"],
  "blocked": [
    { "stage": "validation", "reason": "Нельзя перейти из paused в validation: пауза была на этапе execution" },
    { "stage": "done", "reason": "Нельзя перейти из paused в done: из паузы возвращаются только в planning, execution или validation" }
  ],
  "prompt_block": "Состояние задачи (текущий этап и шаг; продолжай с этого места):\nТекущий этап задачи: paused. Допустимые следующие этапы: planning, execution. Ожидаемое действие: задача на паузе; ожидается продолжение (resume). Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

`allowed_next` у паузы — свой этап возврата плюс этапы, достижимые из этапа
паузы: из `execution` это `planning` (откат) и сам `execution`; `validation`
закрыта guard-условием `implementation_complete`, а `done` недостижим из паузы
ни при каких флагах.

Коды: `200`, `400` (повторная пауза, пауза из `done`), `404`.

### POST /tasks/{task_id}/resume

Возвращает задачу из `paused` в этап и шаг, с которых она встала; метка паузы
снимается (`paused_from_stage` — `null`). Продолжение задачи, которая не на
паузе, — `400` («задача не на паузе»). Это ровно возврат «на своё место»:
продолжить в **другой** допустимый этап — это осознанный переход кнопкой-этапом
(`POST /tasks/{task_id}/transition`), а не `resume`.

```bash
curl.exe -X POST http://127.0.0.1:8000/tasks/tz/resume
```

```json
{
  "id": 1,
  "task_id": "tz",
  "agent_id": "8f1c2d3e4b5a",
  "stage": "execution",
  "current_step": "implement",
  "expected_action": "ожидается реализация модуля",
  "history": [ "…шестая запись: reason «продолжение после паузы»…" ],
  "rollback_stage": "planning",
  "paused_from_stage": null,
  "is_active": true,
  "allowed_next": ["planning", "paused"],
  "prompt_block": "…Текущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

Коды: `200`, `400` (не на паузе), `404`.

### POST /tasks/{task_id}/advance

Следующий шаг текущего этапа; с последнего шага этапа — первый шаг следующего
этапа. Ожидаемое действие и производные поля пересчитываются. Выход из этапа
проверяется правилами допуска: если согласование этапа не выставлено, `advance` с
последнего шага вернёт `400` с текстом guard-условия и запишет отклонённую
попытку в журнал.

```bash
curl.exe -X POST http://127.0.0.1:8000/tasks/tz/advance
```

```json
{
  "id": 1,
  "task_id": "tz",
  "agent_id": "8f1c2d3e4b5a",
  "stage": "execution",
  "current_step": "implement",
  "expected_action": "ожидается реализация модуля",
  "context": {
    "task_id": "tz",
    "working_memory": { "ограничение": "только on-premise" },
    "plan_approved": true
  },
  "history": [
    { "at": "…", "from_stage": null, "from_step": null, "to_stage": "planning",
      "to_step": "gather_requirements", "reason": "задача создана",
      "expected_action": "ожидается уточнение требований пользователем" },
    { "at": "…", "from_stage": "planning", "from_step": "gather_requirements",
      "to_stage": "planning", "to_step": "define_scope", "reason": "следующий шаг",
      "expected_action": "ожидается определение границ задачи агентом" },
    { "at": "…", "from_stage": "planning", "from_step": "define_scope",
      "to_stage": "planning", "to_step": "create_plan", "reason": "следующий шаг",
      "expected_action": "ожидается утверждение плана пользователем" },
    { "at": "…", "from_stage": "planning", "from_step": "create_plan",
      "to_stage": "execution", "to_step": "implement", "reason": "следующий шаг",
      "expected_action": "ожидается реализация модуля" }
  ],
  "created_at": "2026-09-10T12:20:00+00:00",
  "updated_at": "2026-09-10T12:24:00+00:00",
  "rollback_stage": "planning",
  "paused_from_stage": null,
  "is_active": true,
  "allowed_next": ["planning", "paused"],
  "prompt_block": "…Текущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

Это ответ третьего подряд `advance` из `planning/gather_requirements` — на
границе этапов: последний шаг `planning` переводит в первый шаг `execution`.
Флаг `plan_approved` к этому моменту уже выставлен: без него этот же вызов
вернул бы `400` (см. ниже).

Из `done` шаг вперёд не идёт, из `paused` — тоже (сначала `resume`):

```json
{ "detail": "завершена: этап done терминальный" }
```

```json
{ "detail": "задача на паузе: сначала продолжите её (resume)" }
```

Последний шаг этапа без согласования — `400` с текстом guard-условия:

```json
{ "detail": "Нельзя перейти в execution: план не утверждён" }
```

```json
{ "detail": "Нельзя перейти в validation: реализация не завершена" }
```

У отказов из `done` и из `paused` подсказки нет — целевой этап там выбирает
система; подсказку «отметьте флаг …» добавляет `POST /tasks/{task_id}/transition`,
где целевой этап назвал пользователь.

Коды: `200`, `400`, `404`.

### POST /tasks/{task_id}/rollback

Откат ровно на один этап назад (`validation → execution`, `execution →
planning`) с шагом на первый шаг целевого этапа и причиной «откат на предыдущий
этап». Значение `to_stage` обязано совпасть с целью отката — иначе `400`, как в
примере ниже. Перед примером задача стояла на `validation/run_tests`. Движение
назад сбрасывает флаги-согласования этапа-цели и всех последующих этапов: после
этого отката `implementation_complete` и `validation_passed` удаляются из
`context` (они уже недействительны), а `plan_approved` остаётся.

```bash
curl.exe -X POST http://127.0.0.1:8000/tasks/tz/rollback \
  -H "Content-Type: application/json" \
  -d "{\"to_stage\":\"execution\"}"
```

```json
{
  "id": 1,
  "task_id": "tz",
  "agent_id": "8f1c2d3e4b5a",
  "stage": "execution",
  "current_step": "implement",
  "expected_action": "ожидается реализация модуля",
  "context": { "task_id": "tz", "working_memory": {}, "plan_approved": true },
  "history": [ "…последняя запись: из validation/run_tests в execution/implement, reason «откат на предыдущий этап»…" ],
  "rollback_stage": "planning",
  "paused_from_stage": null,
  "is_active": true,
  "allowed_next": ["planning", "paused"],
  "blocked": [
    { "stage": "validation", "reason": "Нельзя перейти в validation: реализация не завершена" },
    { "stage": "done", "reason": "Нельзя перейти из execution в done: пропущен этап validation" }
  ],
  "prompt_block": "…Текущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

Задача на этапе `execution`, а `to_stage` указывает на `validation` — цель отката
не совпала:

```json
{ "detail": "откат с этапа execution возможен только на этап planning" }
```

Откат из `planning` и `done` невозможен — предыдущего этапа нет:

```json
{ "detail": "у этапа planning нет предыдущего этапа" }
```

```json
{ "detail": "у этапа done нет предыдущего этапа" }
```

На паузе откат запрещён: сначала `resume`.

```json
{ "detail": "задача на паузе: сначала продолжите её (resume)" }
```

Коды: `200`, `400`, `404`, `422` (неизвестный этап в `to_stage`).

### POST /tasks/{task_id}/transition

Прямой переход в указанный этап и шаг — им пользуются кнопки-этапы панели задачи.
`step`, `expected_action` и `reason` необязательны: `step: null` — первый шаг
целевого этапа (`finalize` для `done`, текущий шаг для `paused`),
`expected_action` — умолчание `task_prompt` для пары «этап, шаг», `reason` —
«переход по запросу». Так завершение задачи описывается одним вызовом. Переход
проходит те же правила допуска, что и остальные: пропуск этапа, отказ вернуться
больше чем на этап, отсутствие флага — `400`.

```bash
curl.exe -X POST http://127.0.0.1:8000/tasks/tz/transition \
  -H "Content-Type: application/json" \
  -d "{\"stage\":\"done\",\"reason\":\"задача завершена\"}"
```

```json
{
  "id": 1,
  "task_id": "tz",
  "agent_id": "8f1c2d3e4b5a",
  "stage": "done",
  "current_step": "finalize",
  "expected_action": "задача завершена; ожидается новая задача",
  "context": {
    "task_id": "tz",
    "working_memory": { "ограничение": "только on-premise" },
    "plan_approved": true,
    "implementation_complete": true,
    "validation_passed": true
  },
  "history": [ "…последняя запись: из validation/finalize в done/finalize, reason «задача завершена»…" ],
  "created_at": "2026-09-10T12:20:00+00:00",
  "updated_at": "2026-09-10T12:30:00+00:00",
  "rollback_stage": null,
  "paused_from_stage": null,
  "is_active": false,
  "allowed_next": [],
  "blocked": [
    { "stage": "planning", "reason": "Нельзя перейти из done: этап done терминальный" },
    { "stage": "execution", "reason": "Нельзя перейти из done: этап done терминальный" },
    { "stage": "validation", "reason": "Нельзя перейти из done: этап done терминальный" },
    { "stage": "paused", "reason": "Нельзя перейти из done: этап done терминальный" }
  ],
  "prompt_block": "…Текущий этап задачи: done. Допустимые следующие этапы: нет. Ожидаемое действие: задача завершена; ожидается новая задача. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: finalize. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены; execution (implement, test_locally) — завершены; validation (review, run_tests, finalize) — завершены."
}
```

Переход в `done` открыт только флагом `validation_passed`: без него `400`. После
перехода задача неактивна (`is_active: false`) и пропадает из
`GET /agents/{agent_id}/tasks`, `allowed_next` пуст, а все остальные этапы
перечислены в `blocked` с одной и той же причиной — терминальный этап.

`step` можно задать явно: `{"stage": "execution", "step": "test_locally"}` (при
выставленном `plan_approved`). Порядок проверок — «этап → граф и guard → шаг»,
поэтому ошибка в шаге называется, только когда сам переход разрешён: шаг чужого
этапа — `400` («шаг review не принадлежит этапу execution»), а для `paused` шаг
обязан совпасть с текущим («пауза сохраняет шаг implement, а не review»).

`detail` ответа `400` — короткая причина **и** подсказка, что сделать (целевой
этап назвал пользователь, поэтому подсказка уместна):

```json
{ "detail": "Нельзя перейти из planning в done: пропущены этапы execution и validation Сначала перейдите в execution и пройдите этапы по порядку." }
```

```json
{ "detail": "Нельзя перейти в execution: план не утверждён Утвердите план: отметьте флаг «📝 План утверждён» в панели задачи." }
```

```json
{ "detail": "Нельзя перейти из execution в done: пропущен этап validation Сначала перейдите в validation и пройдите этапы по порядку." }
```

Возврат больше чем на этап отклоняется с указанием идти по одному:

```json
{ "detail": "Нельзя перейти из validation в planning: откат идёт по одному этапу (сначала execution) Откатывайтесь по одному этапу (кнопка «Откат»)." }
```

Из паузы возвращаются только в рабочие этапы, из `done` — никуда:

```json
{ "detail": "Нельзя перейти из paused в done: из паузы возвращаются только в planning, execution или validation Продолжите задачу в этап, откуда её поставили на паузу, и доведите до нужного этапа." }
```

```json
{ "detail": "Нельзя перейти из done: этап done терминальный Завершённая задача изменению не подлежит: заведите новую задачу." }
```

Переход «в себя» тоже отклоняется — «задача уже на этом этапе»:

```json
{ "detail": "Нельзя перейти из planning в planning: задача уже на этом этапе Выберите другой этап." }
```

Каждая такая попытка остаётся в журнале строкой `accepted: false`, а состояние
задачи не меняется.

Коды: `200`, `400` (недопустимый переход: пропуск этапа, откат больше чем на
этап, закрытый guard-условием, шаг чужого этапа, переход «в себя»), `404`
(неизвестная задача), `422` (неизвестный этап/шаг в теле — проверка схемы,
слишком длинные `expected_action` — до 500 символов — и `reason` — до 200).

### Состояние задачи в ответе генерации

`POST /agents/{agent_id}/generate` возвращает поле `task_state` (`TaskStateOut`
или `null`, если у активной задачи агента состояния нет) — состояние на момент
запроса, включая `allowed_next` и `blocked`. Поле и блок `system_prompt`
считаются **до** вызова DeepSeek, поэтому видны и при `502`:

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "status": "ok",
  "task_state": {
    "task_id": "tz",
    "stage": "execution",
    "current_step": "implement",
    "expected_action": "ожидается реализация модуля",
    "is_active": true,
    "allowed_next": ["planning", "paused"],
    "blocked": [
      { "stage": "validation", "reason": "Нельзя перейти в validation: реализация не завершена" },
      { "stage": "done", "reason": "Нельзя перейти из execution в done: пропущен этап validation" }
    ],
    "prompt_block": "…Текущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
  },
  "task_intent": null,
  "task_proposal": null,
  "system_prompt": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\n…\n\nРабочая память задачи tz:\n…\n\nСостояние задачи (текущий этап и шаг; продолжай с этого места):\nТекущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены.",
  "messages": [ "…" ]
}
```

Переходы в ответе генерации видны тремя полями:

- `task_state.allowed_next`/`task_state.blocked` — что доступно сейчас и что
  закрыто (тот же расчёт, что у `GET /tasks/{task_id}/allowed-next`);
- `task_intent` — что сделала реплика: `{intent, applied, reason, allowed_next}`,
  `null` — намерения нет (или задачи нет, или она завершена);
- `task_proposal` — предложение модели, которое правила не пустили:
  `{proposed, allowed_next, reason, hint}`, `null` — предложения нет или оно
  допустимо.

Реплика, в которой распознано намерение, двигает состояние **в этом же**
запросе: `generate` с промптом «продолжаем» на задаче, стоящей на
`paused/implement`, вернёт `task_state.stage = "execution"` и блок промпта с
`execution/implement`. Намерение, которое правила не пустили, состояние не
меняет — вместо перехода приходит уведомление, а отчёт объясняет причину:

```json
{
  "task_intent": {
    "intent": "advance",
    "applied": false,
    "reason": "Нельзя перейти в execution: план не утверждён",
    "allowed_next": ["paused"]
  },
  "response": "⚠️ Переход по реплике «advance» не выполнен: Нельзя перейти в execution: план не утверждён Доступные следующие этапы: paused.\n\nПринято, продолжаю по плану."
}
```

Ответ модели, предлагающий недопустимый переход, не выполняется и не остаётся в
ответе: вместо предложения уходит отказ с причиной и подсказкой, а в отчёте
появляется `task_proposal`:

```json
{
  "task_proposal": {
    "proposed": "done",
    "allowed_next": ["execution", "paused"],
    "reason": "Нельзя перейти в done: валидация не пройдена",
    "hint": "Отметьте флаг «✅ Валидация пройдена» в панели задачи."
  },
  "response": "🚧 Ответ предлагает переход в done, но это недопустимо. Нельзя перейти в done: валидация не пройдена Отметьте флаг «✅ Валидация пройдена» в панели задачи."
}
```

## Инварианты

Шесть эндпоинтов с абсолютными путями (`/invariants...`; префиксов нет).

| Метод и путь | Тело запроса | Ответ | Коды ошибок |
|---|---|---|---|
| `POST /invariants` | `InvariantIn`: `name`, `description`, `category`, `severity` | `201 InvariantOut` | 409 — имя занято, 422 — неизвестная категория/важность или пустое поле |
| `GET /invariants?category=&active_only=` | — | `200 [InvariantOut]` (по алфавиту имён) | 422 — неизвестная категория |
| `GET /invariants/{invariant_id}` | — | `200 InvariantOut` | 404 — правила нет |
| `PUT /invariants/{invariant_id}` | `InvariantUpdateIn`: любые из `name`, `description`, `category`, `severity`, `is_active` | `200 InvariantOut` | 404, 409 — имя занято, 422 — неизвестное значение |
| `DELETE /invariants/{invariant_id}` | — | `200 {"id": 3, "deleted": true}` | 404 |
| `POST /invariants/check` | `InvariantCheckIn`: `text` (1…8000), `use_llm` (по умолчанию `true`) | `200 InvariantCheckOut` | 422 — пустой текст |

`GET /invariants` по умолчанию (`active_only=false`) отдаёт **все** правила —
выключенные тоже: их показывает раздел интерфейса, чтобы правило можно было
вернуть. Список для промпта и проверки берётся отдельно — только активные
(`active_only=true`).

### Категории и важность

`category` — одно из `architecture`, `tech_decisions`, `stack_constraints`,
`business_rules`; `severity` — `hard` или `soft`. Неизвестное значение —
`422` с текстом домена («Неизвестная категория инварианта: 'flask'. Допустимые:
…»), а не «тихое» значение по умолчанию. Важность решает поведение агента:
нарушение `hard` → отказ, `soft` → предупреждение, но решение предлагается.

### Пример: создание правила

```bash
curl.exe -X POST http://127.0.0.1:8000/invariants ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"Только FastAPI и Streamlit\",\"description\":\"Используем только FastAPI и Streamlit; никаких Flask, Django, Bottle или Tornado\",\"category\":\"architecture\",\"severity\":\"hard\"}"
```

```json
{
  "id": 1,
  "name": "Только FastAPI и Streamlit",
  "description": "Используем только FastAPI и Streamlit; никаких Flask, Django, Bottle или Tornado",
  "category": "architecture",
  "severity": "hard",
  "is_active": true,
  "created_at": "2026-09-17T09:15:02.331000Z",
  "updated_at": "2026-09-17T09:15:02.331000Z"
}
```

Правило сразу активно: со следующего запроса оно попадает в системный промпт
агентов и в проверку. Повторный `POST` с тем же именем вернёт `409`
(«Инвариант «Только FastAPI и Streamlit» уже существует»).

### Пример: проверка текста

```bash
curl.exe -X POST http://127.0.0.1:8000/invariants/check ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Давай перепишем бэкенд на Flask\",\"use_llm\":false}"
```

```json
{
  "checked": [
    "Платные API — только с согласия",
    "Состояние задачи в SQLite",
    "Только FastAPI и Streamlit",
    "Только Python"
  ],
  "llm_used": false,
  "verdict": "refusal",
  "violations": [
    {
      "name": "Только FastAPI и Streamlit",
      "category": "architecture",
      "severity": "hard",
      "reason": "текст упоминает Flask, а инвариант «Только FastAPI и Streamlit» это запрещает",
      "source": "deterministic"
    }
  ],
  "note": ""
}
```

Тот же текст с `"use_llm": true` даст тот же результат: детерминированные правила
нарушение нашли, поэтому модель не вызывается (`llm_used: false`) — вызов идёт
только когда правила молчат. Если правила молчат и `use_llm=true`, нарушение
может назвать модель (`source: "llm"`); сбой вызова или неразобранный ответ не
ломают проверку — вердикт считается по правилам, а причина попадает в `note`
(«проверка LLM не выполнена: …» либо «ответ LLM не разобран: …»).

### Поля схем

**`InvariantOut`** — одно правило:

| Поле | Тип | Значение |
|---|---|---|
| `id` | int | Идентификатор правила |
| `name` | str | Имя (уникально, до 100 символов) |
| `description` | str | Формулировка (до 2000 символов) |
| `category` | str | `architecture` / `tech_decisions` / `stack_constraints` / `business_rules` |
| `severity` | str | `hard` / `soft` |
| `is_active` | bool | Включено ли правило (выключенное не идёт ни в промпт, ни в проверку) |
| `created_at`, `updated_at` | datetime | Метки времени (UTC) |

**`InvariantCheckOut`** — результат проверки:

| Поле | Тип | Значение |
|---|---|---|
| `checked` | [str] | Имена активных правил, против которых проверяли текст (`[]` — правил нет) |
| `llm_used` | bool | Звали ли модель (значит, правила молчали) |
| `verdict` | str | `allowed` / `warning` (только soft) / `refusal` (есть hard) |
| `violations` | [InvariantViolationOut] | Нарушения: `name`, `category`, `severity`, `reason`, `source` (`deterministic` / `llm`) |
| `note` | str | Почему LLM-проверка не выполнена (пусто — если выполнена или не требовалась) |

### Инварианты в ответе генерации

`POST /agents/{agent_id}/generate` возвращает поле `invariants`
(`InvariantCheckOut` или `null`, если проверки не было) — объединённый вердикт по
запросу и ответу:

```json
{
  "agent_id": "8f1c2d3e4b5a",
  "status": "ok",
  "prompt": "Давай перепишем бэкенд на Flask",
  "response": "Отказ: предложение нарушает инварианты проекта.\n- [hard] Только FastAPI и Streamlit (architecture): текст упоминает Flask, а инвариант «Только FastAPI и Streamlit» это запрещает\nПредложение не выполнено: измените запрос или обновите список инвариантов.",
  "invariants": {
    "checked": ["Только FastAPI и Streamlit"],
    "llm_used": false,
    "verdict": "refusal",
    "violations": [
      {"name": "Только FastAPI и Streamlit", "category": "architecture",
       "severity": "hard", "source": "deterministic",
       "reason": "текст упоминает Flask, а инвариант «Только FastAPI и Streamlit» это запрещает"}
    ],
    "note": ""
  },
  "usage": null,
  "token_metrics": null,
  "messages": [ "…" ]
}
```

Особенности отказа:

- `status` остаётся `"ok"` — ход состоялся как диалог, но `usage` и
  `token_metrics` равны `null`: DeepSeek при отказе в запросе не вызывается;
- реплика пользователя и текст отказа сохраняются в краткосрочный слой, то есть
  видны в `messages` и в `GET /agents/{agent_id}/history`;
- остальные поля отчёта (`profile`, `task_state`, `system_prompt`, `memory`)
  заполнены — они считаются до проверки.

Нарушение soft-инварианта не отменяет ответ: он приходит с предупреждением в
начале (`"⚠️ Предупреждение: ответ может нарушать soft-инварианты проекта."`),
`verdict` = `"warning"`, вызов модели состоялся. Нарушение hard-инварианта в
**ответе** модели (правила или LLM его нашли) заменяет текст ответа отказом.

## MCP

MCP-подключение — одно на процесс бэкенда: его держит реестр
`backend/services/mcp_registry.py` (`MCPRegistry`), а само соединение ведёт
`backend/services/mcp_client.py` (`MCPClient`) вместе со стейт-машиной
`backend/domain/mcp_connection_fsm.py`. Соединение живёт в памяти процесса и
**не переживает** перезапуск (это связь с внешним сервером, а не данные дня);
при остановке приложения `lifespan` вызывает `close()`, поэтому сервер-stdio не
остаётся висеть процессом. Новое подключение закрывает прежнее; список
инструментов кэшируется в открытой сессии до `refresh=true`.

Четыре базовых эндпоинта подключения: `POST /mcp/connect`,
`POST /mcp/disconnect`, `GET /mcp/status`, `GET /mcp/tools`; днём 17 к ним
добавлены `POST /mcp/call` (вызов инструмента) и `GET /mcp/servers` (каталог
известных серверов). Контракт ошибок подключения: `400` — цель не разобрана
(пустая строка из пробелов, URL там, где нужна команда, и наоборот); `409` —
инструменты запрошены без соединения; `422` — тело не проходит схему (пустая
цель, неизвестный транспорт); `502` — сервер недоступен, команда не найдена,
таймаут или ошибка `tools/list` (текст — одна строка с подсказкой). Коды
`POST /mcp/call` разобраны в его разделе ниже.

Свой сервер дня живёт в `day17/mcp_server/` и запускается по stdio: клиент
поднимает его дочерним процессом (``uv run python mcp_server/server.py``), а
инструменты читают `https://jsonplaceholder.typicode.com` через
`mcp_server/api_client.py`. Каталог инструментов, вызов и правила допуска
собраны в `backend/services/mcp_tool_runner.py` (`MCPToolRunner`) и
`backend/domain/mcp_tool_call.py`; агент вызывает инструмент сам
(`Agent.apply_mcp_tool`) и дописывает результат системным блоком в промпт того же
запроса.

### POST /mcp/connect

Тело — `MCPConnectIn`:

| Поле | Тип | Описание |
|---|---|---|
| `target` | строка, 1…500 | URL MCP-сервера (`http://` — Streamable HTTP, `sse://` — SSE) или команда запуска по stdio |
| `transport` | `auto` \| `stdio` \| `sse` \| `http` | по умолчанию `auto` — транспорт по виду цели; явное значение сильнее |

Открывает соединение: `initialize` и согласование версии протокола. Команда
stdio разбирается на исполняемый файл и аргументы (кавычки и обратные слэши
Windows-путей сохраняются).

```bash
curl.exe -X POST http://127.0.0.1:8000/mcp/connect \
  -H "Content-Type: application/json" \
  -d "{\"target\": \"uvx mcp-server-fetch\"}"
```

```json
{
  "connected": true,
  "state": "connected",
  "target": "uvx mcp-server-fetch",
  "transport": "stdio",
  "transport_label": "stdio (дочерний процесс)",
  "server_name": "mcp-fetch",
  "server_version": "1.30.0",
  "protocol": "2025-11-25",
  "tool_count": 0,
  "error": null,
  "allowed_events": ["fail", "disconnect"]
}
```

Недоступный сервер — `502`, и клиент остаётся в реестре: `GET /mcp/status`
покажет `"state": "error"` с тем же текстом, а повторное подключение разрешено.

```json
{ "detail": "Не удалось подключиться к MCP-серверу [Streamable HTTP] http://127.0.0.1:9/mcp: All connection attempts failed (проверьте URL и что сервер поднят)" }
```

### POST /mcp/disconnect

Тело не нужно (пустой объект). Закрывает соединение и завершает дочерний процесс
stdio-сервера; повторный вызов без соединения — безопасный no-op.

```bash
curl.exe -X POST http://127.0.0.1:8000/mcp/disconnect -d "{}"
```

```json
{"connected": false, "state": "disconnected", "target": null, "transport": null,
 "transport_label": null, "server_name": "", "server_version": "", "protocol": "",
 "tool_count": 0, "error": null, "allowed_events": ["connect"]}
```

### GET /mcp/status

Состояние подключения (`MCPStatusResponse`, те же поля, что в ответах
`connect`/`disconnect`). `state` — состояние стейт-машины: `disconnected`,
`connecting`, `connected`, `error`; `allowed_events` — что допустимо сейчас.

### GET /mcp/tools

Параметр `refresh` (bool, по умолчанию `false`) — опросить сервер заново вместо
кэша. Ответ `MCPToolsResponse`: `tools` (список `MCPToolSchema`), `count`,
`target`, `transport`, `server_name`, `server_version`.

```bash
curl.exe "http://127.0.0.1:8000/mcp/tools?refresh=true"
```

```json
{
  "tools": [
    {"name": "get_user",
     "description": "Возвращает данные пользователя по его id. …",
     "input_schema": {"properties": {"user_id": {"type": "integer"}}, "required": ["user_id"], "type": "object"},
     "output_schema": {"properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "…": {}}, "type": "object"}}
  ],
  "count": 3,
  "target": "uv run python mcp_server/server.py",
  "transport": "stdio",
  "server_name": "day17-jsonplaceholder",
  "server_version": "1.0.0"
}
```

Без соединения — `409`. Текст зависит от того, было ли подключение вообще:
реестр без клиента отвечает «Подключение к MCP-серверу не установлено: сначала
`POST /mcp/connect`», а клиент, оставшийся в состоянии `error` или
`disconnected`, — «Соединение с MCP-сервером не установлено (состояние error).
Вызовите POST /mcp/connect с целью подключения. Последняя ошибка: …».

```json
{ "detail": "Подключение к MCP-серверу не установлено: сначала POST /mcp/connect" }
```

Ошибка самого `tools/list` (сервер оборвал связь) — `502`, а `GET /mcp/status`
переходит в `error` с тем же текстом — «Не удалось получить список инструментов
MCP-сервера […]» или «Соединение с MCP-сервером оборвалось […]».

`output_schema` приходит не от всякого сервера: у инструмента без объявленного
результата поле остаётся пустым словарём, и это не мешает его вызывать.

### POST /mcp/call

Тело — `MCPCallIn`: `tool` (имя из `GET /mcp/tools`, 1…100 символов) и
`arguments` (объект по `input_schema` инструмента). Ответ — `MCPCallResponse`
(см. [«Формы MCP»](#формы-mcp)): `state` (`done` / `failed` / `rejected`),
`accepted`, `called`, `tool`, `arguments`, `result`, `is_error`, `reason_code`,
`error`, `duration_ms` и `allowed_events` (события FSM вызова, допустимые сейчас).

Прежде чем звать сервер, бэкенд проверяет вызов правилами допуска
(`backend/domain/mcp_tool_call.py`): есть ли соединение, есть ли инструмент в
каталоге, заполнены ли обязательные аргументы, нет ли лишних и совпадают ли типы
со схемой. Отказ виден кодом причины: `not_connected`, `unknown_tool`,
`bad_arguments`.

```bash
curl.exe -X POST http://127.0.0.1:8000/mcp/call \
  -H "Content-Type: application/json" \
  -d "{\"tool\": \"get_user\", \"arguments\": {\"user_id\": 1}}"
```

```json
{
  "accepted": true,
  "state": "done",
  "detected": true,
  "connected": true,
  "called": true,
  "tool": "get_user",
  "arguments": {"user_id": 1},
  "result": {
    "tool": "get_user",
    "arguments": {"user_id": 1},
    "structured": {"id": 1, "name": "Leanne Graham", "username": "Bret",
                   "email": "Sincere@april.biz", "city": "Gwenborough", "…": "…"},
    "text": "{\n  \"id\": 1,\n  …\n}",
    "is_error": false,
    "duration_ms": 214
  },
  "is_error": false,
  "reason_code": null,
  "error": null,
  "duration_ms": 214,
  "allowed_events": ["plan"]
}
```

Коды ответа и что они значат:

| Код | Когда | Тело |
|---|---|---|
| `200` | вызов состоялся (в том числе если инструмент ответил ошибкой) | `MCPCallResponse` с `state: "done"` или `"failed"` + `is_error: true` |
| `400` | инструмента нет в каталоге или аргументы не подходят по схеме | `detail` — причина и что сделать |
| `409` | соединения нет вовсе (это конфликт состояний, а не ошибка запроса) | `detail` — «Подключитесь через POST /mcp/connect» |
| `422` | тело не прошло схему (нет `tool`, пустое или длиннее 100 символов имя) | стандартная ошибка FastAPI |
| `502` | соединение оборвалось: ответа от сервера не было | `detail` — текст ошибки связи |

Отказ по неизвестному инструменту:

```bash
curl.exe -i -X POST http://127.0.0.1:8000/mcp/call \
  -H "Content-Type: application/json" -d "{\"tool\": \"nope\", \"arguments\": {}}"
```

```json
{ "detail": "Инструмент «nope» не найден в каталоге сервера. Доступны: get_user, get_post, list_user_posts" }
```

Не хватает обязательного аргумента — тоже `400`, и текст подсказывает формат:

```json
{ "detail": "Не указан обязательный аргумент «user_id» инструмента «get_user». Укажите число в запросе (например, «пользователь 3») или передайте аргументы через POST /mcp/call." }
```

Ошибка самого инструмента — это **ответ**, а не отказ запроса: `200` и
`is_error: true`. Например, несуществующий id в jsonplaceholder:

```json
{ "accepted": true, "state": "failed", "called": true, "is_error": true,
  "reason_code": "tool_error",
  "error": "Error executing tool get_user: Пользователь с id=999 не найден (HTTP 404): у jsonplaceholder 10 пользователей, id от 1 до 10.",
  "result": {"structured": null, "is_error": true, "text": "Error executing tool get_user: …"} }
```

### GET /mcp/servers

Каталог известных MCP-серверов (не список открытых соединений: у процесса оно
одно). Ответ `MCPServersResponse`: `servers` (список `MCPServerSchema`), `count`,
`connected_target` (цель открытого соединения или `null`) и `connected_key` (ключ
подключённого сервера из каталога или `null`). Цель открытого соединения
сравнивается с целями каталога по нормализованному виду, поэтому подключённым
подсвечивается нужный сервер даже при другой записи команды.

```bash
curl.exe http://127.0.0.1:8000/mcp/servers
```

```json
{
  "servers": [
    {"key": "day17-jsonplaceholder",
     "label": "День 17: свой MCP-сервер (jsonplaceholder)",
     "target": "uv run python mcp_server/server.py",
     "description": "Собственный сервер дня по stdio: инструменты get_user, get_post и list_user_posts читают https://jsonplaceholder.typicode.com …",
     "connected": true,
     "tool_count": 3},
    {"key": "fetch", "label": "Официальный набор: fetch (uvx)",
     "target": "uvx mcp-server-fetch", "description": "…",
     "connected": false, "tool_count": 0},
    {"key": "filesystem", "label": "Официальный набор: filesystem (npx)",
     "target": "npx -y @modelcontextprotocol/server-filesystem .", "description": "…",
     "connected": false, "tool_count": 0}
  ],
  "count": 3,
  "connected_target": "uv run python mcp_server/server.py",
  "connected_key": "day17-jsonplaceholder"
}
```

`tool_count` считается по уже полученному каталогу `tools/list`: сразу после
`POST /mcp/connect` он равен нулю, пока список не запросили (`GET /mcp/tools`).
Отличие от `GET /mcp/status`: статус описывает одно текущее соединение (FSM,
сервер, ошибка), а каталог — какие цели вообще бывают и какая из них открыта.

### Формы MCP

| Схема | Поля |
|---|---|
| `MCPConnectIn` | `target` (1…500), `transport` (`auto`/`stdio`/`sse`/`http`) |
| `MCPStatusResponse` | `connected`, `state`, `target`, `transport`, `transport_label`, `server_name`, `server_version`, `protocol`, `tool_count`, `error`, `allowed_events` |
| `MCPToolSchema` | `name`, `description`, `input_schema` (JSON Schema аргументов как отдал сервер), `output_schema` (JSON Schema структурированного результата) |
| `MCPToolsResponse` | `tools` ([MCPToolSchema]), `count`, `target`, `transport`, `server_name`, `server_version` |
| `MCPCallIn` | `tool` (1…100), `arguments` (объект, по умолчанию `{}`) |
| `MCPCallResponse` | `accepted`, `state`, `detected`, `connected`, `called`, `tool`, `arguments`, `result`, `is_error`, `reason_code`, `error`, `duration_ms`, `allowed_events` |
| `MCPCallReportOut` | то же плюс `used_in_prompt` (ушли ли данные в системный промпт) и `added_tokens`; это тип поля `mcp` ответа генерации |
| `MCPServerSchema` | `key`, `label`, `target`, `description`, `connected`, `tool_count` |
| `MCPServersResponse` | `servers` ([MCPServerSchema]), `count`, `connected_target`, `connected_key` |

`result` — вложенный объект домена `MCPToolResult`: `tool`, `arguments`,
`structured` (сам `structuredContent` ответа сервера), `text` (текстовые блоки),
`is_error`, `duration_ms`. Пустой `structured` (`null`) означает, что сервер не
объявил результат схемой и ответил только текстом.

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
| `user_id` | строка | пользователь, чей профиль применяется к запросам агента, по умолчанию `default` |

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
| `summarized` | bool | покрыта ли реплика конспектом |

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
| `profile` | AppliedProfileOut/null | применённый профиль и его вклад в промпт (заполнен и при `error`) |
| `task_state` | TaskStateOut/null | состояние задачи на момент ответа (заполнено и при `error`; `null` — задачи нет); включает `allowed_next` и `blocked` |
| `task_intent` | объект/null | отчёт о намерении реплики: `{intent, applied, reason, allowed_next}`; `null` — намерения нет (или задачи нет, или она завершена) |
| `task_proposal` | объект/null | предложенный моделью, но недопустимый переход: `{proposed, allowed_next, reason, hint}`; `null` — предложения нет или оно допустимо |
| `invariants` | InvariantCheckOut/null | вердикт проверки запроса и ответа против правил проекта (заполнен и при отказе, и при `error`) |
| `mcp` | MCPCallReportOut/null | шаг MCP: какой инструмент распознан в реплике, с какими аргументами вызван, чем закончился (`state`, `reason_code`, `is_error`, `error`), ушли ли данные в промпт (`used_in_prompt`) и сколько токенов добавил блок (`added_tokens`); `null` — шаг не выполнялся (например, отказ по инвариантам) |
| `system_prompt` | строка | итоговое system-сообщение запроса (профиль + роль + инварианты + блоки памяти + блок состояния задачи + блок данных MCP; считается до вызова DeepSeek) |
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
| `total_full_context_tokens` | int | сколько заняла бы полная история |
| `total_sent_context_tokens` | int | сколько реально отправлено |
| `total_saved_tokens` | int | суммарная экономия токенов |
| `total_summary_cost` | float | стоимость всех суммаризаций |
| `total_net_saved_tokens` | int | чистая экономия |
| `compressed_requests` | int | запросов со сжатым контекстом |
| `total_short_term_tokens` | int | сумма токенов краткосрочного слоя по ходам |
| `total_working_tokens` | int | сумма токенов рабочей памяти по ходам |
| `total_long_term_tokens` | int | сумма токенов долговременной памяти по ходам |

### UsageOut

Одна запись `token_usage`: `id`, `agent_id`, `timestamp`, `prompt_tokens`,
`completion_tokens`, `total_tokens`, `history_tokens`, `response_tokens`,
`cost`, поля сжатия — `mode`, `full_context_tokens`, `sent_context_tokens`,
`saved_tokens`, `summary_tokens`, `summarized_messages`, `summary_used`, и поля
по слоям — `short_term_tokens`, `working_tokens`, `long_term_tokens`.

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

### Профили пользователей

`UserProfileIn` — тело `POST`/`PUT /users/{user_id}/profile` (поля разобраны в
разделе [«Персонализация»](#персонализация-профили-пользователей)):
`name`, `preferences` (`tone`/`verbosity`/`language`/`format`), `constraints`
(`max_response_length`/`forbidden_topics`/`required_disclaimers`),
`custom_instructions`. Схема строгая (`extra="forbid"`), все поля необязательные.

| UserProfileOut | Тип | Пояснение |
|---|---|---|
| `id` | int | id строки `user_profiles` |
| `user_id` | строка | идентификатор пользователя (1–64 символа) |
| `name` | строка | имя для обращения |
| `preferences` | объект | `tone`/`verbosity`/`language`/`format`; `null` — «не настроено» |
| `constraints` | объект | `max_response_length`, `forbidden_topics`, `required_disclaimers` |
| `custom_instructions` | строка | произвольные инструкции, одна на строку |
| `created_at` | datetime | создание (UTC) |
| `updated_at` | datetime | последнее изменение (UTC) |
| `summary` | строка | однострочное описание профиля (селектор в UI) |
| `personalized` | bool | добавляет ли профиль хотя бы один блок в промпт |
| `applied_to_agents` | int | сколько живых агентов получили настройки (заполняет `PUT`) |

`UserProfileDeleteOut` — `status` (`"deleted"`) и `user_id`.

| ProfileElementOut | Тип | Пояснение |
|---|---|---|
| `field` | строка | поле профиля: `name`, `preferences.tone`, `preferences.format`, `preferences.verbosity`, `preferences.language`, `constraints.max_response_length`, `constraints.forbidden_topics`, `constraints.required_disclaimers`, `custom_instructions` |
| `label` | строка | человекочитаемая подпись поля |
| `value` | строка | значение из профиля |
| `text` | строка | строка, добавленная в блок персонализации |

| AppliedProfileOut | Тип | Пояснение |
|---|---|---|
| `user_id` | строка | пользователь, чей профиль применён (`default`, если профиля нет) |
| `name` | строка | имя для обращения |
| `personalized` | bool | `false`, если профиль пуст или отсутствует |
| `summary` | строка | однострочное описание профиля (`без настроек`, если пусто) |
| `elements` | [ProfileElementOut] | только заполненные поля профиля |
| `prompt_block` | строка | текст блока персонализации (пусто — блока нет) |
| `system_prompt` | строка | системное сообщение агента без блоков памяти текущего запроса |
| `instructions` | [строка] | произвольные инструкции профиля (пусто, если их нет) |

### Состояние задачи

`TaskCreateIn` — тело `POST /agents/{agent_id}/tasks`: `task_id` (1–64 символа,
уникален; повторный — `409`) и `initial_stage` (`planning` / `execution` /
`validation`, по умолчанию `planning`; `paused` и `done` — `422`).

`TaskRollbackIn` — тело `POST /tasks/{task_id}/rollback`: одно поле `to_stage`
(значение этапа, проверяется `stage_from_value`). Оно обязано совпасть с целью
отката (`validation → execution`, `execution → planning`), иначе `400`.

`TaskTransitionIn` — тело `POST /tasks/{task_id}/transition`: `stage` (обязателен),
`step` (`null` — первый шаг целевого этапа, для `done` это `finalize`, для
`paused` — текущий шаг), `expected_action` (до 500 символов; пустое значение
заменяется умолчанием `task_prompt`) и `reason` (до 200; пустое — «переход по
запросу»). Непереданные значения подставляет домен, а не схема: их проверяет
стейт-машина, потому что умолчание зависит от целевого этапа и шага.

`TaskFlagsIn` — тело `PATCH /tasks/{task_id}/context`: три необязательных флага
(`plan_approved`, `implementation_complete`, `validation_passed`). Непереданный
флаг (`null`) не меняется, а тело без единого флага — `422` («нужен хотя бы один
флаг задачи»): запрос, который ничего не меняет, почти всегда означает опечатку в
имени поля. Изменение флагов — не переход, в журнал `task_transitions` оно не
пишется.

| TaskStateOut | Тип | Пояснение |
|---|---|---|
| `id` | int | id строки `task_states` |
| `task_id` | строка | идентификатор задачи (уникален) |
| `agent_id` | строка | агент-владелец |
| `stage` | строка | текущий этап: `planning`/`execution`/`validation`/`done`/`paused` |
| `current_step` | строка | текущий шаг этапа (у `done` остаётся `finalize`) |
| `expected_action` | строка | чего ждём на этом шаге (текст из `task_prompt.py`) |
| `context` | объект | `task_id`, снимок `working_memory` задачи и выставленные флаги (`plan_approved`, `implementation_complete`, `validation_passed`) |
| `history` | [объект] | журнал переходов внутри строки (те же поля, что у `TaskTransitionOut`, плюс `at` и `expected_action`) |
| `created_at` | datetime | когда задача заведена (UTC) |
| `updated_at` | datetime | последний переход (UTC) |
| `rollback_stage` | строка/null | этап, на который приведёт откат (`null` — откатываться некуда) |
| `paused_from_stage` | строка/null | этап, с которого встали на паузу (отдельная колонка `task_states`) |
| `is_active` | bool | `stage != "done"`; пауза считается активной |
| `allowed_next` | [строка] | этапы, доступные сейчас с учётом графа и флагов (порядок — прямой ход, пауза в конце) |
| `blocked` | [TaskBlockedOut] | недоступные этапы с причиной отказа — по ним строятся подсказки кнопок |
| `prompt_block` | строка | заголовок и строка блока состояния — ровно тот текст, что идёт в системный промпт |

| TaskTransitionOut | Тип | Пояснение |
|---|---|---|
| `id` | int | id записи журнала |
| `task_id` | строка | задача |
| `from_stage` | строка/null | откуда перешли (`null` только у создания задачи) |
| `from_step` | строка/null | шаг до перехода (`null` только у создания задачи) |
| `to_stage` | строка/null | этап после перехода (`null` у отклонённой попытки без названного этапа) |
| `to_step` | строка/null | шаг после перехода (`null` — шаг в попытке не назывался) |
| `accepted` | bool | `true` — переход состоялся; `false` — попытка, отклонённая правилами (состояние задачи она не меняет) |
| `reason` | строка | причина: «задача создана», «следующий шаг», «пауза», «продолжение после паузы», «откат на предыдущий этап», «задача завершена», «откат по реплике пользователя», «переход по запросу»; у отклонённой строки — текст отказа |
| `created_at` | datetime | время перехода (UTC) |

`TaskHistoryOut` — ответ `GET /tasks/{task_id}/history`: `task_id` и `entries`
([TaskTransitionOut] по возрастанию `id`, первая запись — создание задачи с
`accepted: true`; строки с `accepted: false` — отклонённые попытки).

`TaskBlockedOut` — один недоступный переход: `stage` (этап) и `reason` (короткая
причина отказа, та же, что в `detail` ответа `400`, но без подсказки).

`TaskAllowedNextOut` — ответ `GET /tasks/{task_id}/allowed-next`: `task_id`,
`stage`, `allowed_next` ([строка] — доступные этапы) и `blocked`
([TaskBlockedOut]).

## Коды ошибок

| Код | Когда | Тело |
|---|---|---|
| `400` | пустой `task_id` после обрезки пробелов в `PUT /memory/task`; недопустимый переход состояния задачи: пропуск этапа, откат больше чем на этап, переход «в себя», выход из этапа без согласования (guard-условие), любой переход из `done`, пауза из `done` и повторная пауза, `advance` и `rollback` на паузе, шаг чужого этапа, несовпадение `to_stage` с целью отката, `resume` не на паузе; цель MCP не разобрана: пустая после обрезки пробелов, URL там, где нужен запуск команды, и наоборот; `POST /mcp/call` — инструмента нет в каталоге сервера или аргументы не подходят по `input_schema` (нет обязательного, лишний, тип не тот) | `HTTPException` с `detail` (у `POST /tasks/{task_id}/transition` — причина и подсказка) |
| `404` | неизвестный `agent_id` во всех `/agents/{agent_id}/...` (а для `DELETE /memory/long-term/{id}` — ещё и отсутствующая запись); нет профиля у `GET`/`PUT`/`DELETE /users/{user_id}/profile`; неизвестный `task_id` во всех `/tasks/{task_id}/...` | `HTTPException` с `detail` |
| `409` | профиль с таким `user_id` уже есть (`POST /users/{user_id}/profile`); задача с таким `task_id` уже заведена (`POST /agents/{agent_id}/tasks`); `GET /mcp/tools` и `POST /mcp/call` без соединения с MCP-сервером | `HTTPException` с `detail` |
| `422` | невалидное тело запроса (Pydantic/FastAPI): невалидные поля профиля, `initial_stage` вне `planning`/`execution`/`validation`, неизвестный этап/шаг, слишком длинные `expected_action`/`reason`, пустой `task_id`, тело `PATCH /tasks/{task_id}/context` без единого флага, пустая цель или неизвестный транспорт у `POST /mcp/connect`, пустое или длиннее 100 символов имя инструмента у `POST /mcp/call` | объект с `detail` — списком ошибок |
| `502` | сбой генерации `POST /generate` (нет ключа, сеть, лимиты); MCP-сервер недоступен, команда запуска не найдена, таймаут `initialize` или ошибка `tools/list`; `POST /mcp/call` — соединение оборвалось и ответа от инструмента не было | `GenerateResponse` со `status:"error"`; у MCP — `HTTPException` с одной строкой текста и подсказкой |

`400` — недопустимый переход состояния задачи. Там, где целевой этап назвал
пользователь (`POST /tasks/{task_id}/transition`), `detail` — короткая причина
**и** подсказка, что сделать:

```json
{ "detail": "Нельзя перейти из planning в done: пропущены этапы execution и validation Сначала перейдите в execution и пройдите этапы по порядку." }
```

```json
{ "detail": "Нельзя перейти в execution: план не утверждён Утвердите план: отметьте флаг «📝 План утверждён» в панели задачи." }
```

```json
{ "detail": "Нельзя перейти в done: валидация не пройдена Отметьте флаг «✅ Валидация пройдена» в панели задачи." }
```

У переходов, целевой этап которых выбирает система (`pause`, `resume`, `advance`,
`rollback`), `detail` — одна причина без подсказки:

```json
{ "detail": "завершена: этап done терминальный" }
```

```json
{ "detail": "Нельзя перейти из paused в paused: задача уже на этом этапе" }
```

```json
{ "detail": "Нельзя перейти из done: этап done терминальный" }
```

```json
{ "detail": "Нельзя перейти в execution: план не утверждён" }
```

```json
{ "detail": "задача на паузе: сначала продолжите её (resume)" }
```

```json
{ "detail": "откат с этапа execution возможен только на этап planning" }
```

Через HTTP попытка перейти в неизвестный этап до стейт-машины не доходит — её
отсекает схема (`422`, «Неизвестный этап задачи: 'нет-такого'. Допустимые:
planning, execution, validation, done, paused»). Тот же отказ домена остаётся для
прямых вызовов `transition_to` (скрипты, демо) и попадает в журнал строкой
`accepted: false` с пустым `to_stage`.

`404` — например, запрос к удалённому или опечатанному id:

```json
{ "detail": "Агент 8f1c2d3e4b5a не найден" }
```

```json
{ "detail": "Профиль пользователя strict_tech не найден" }
```

```json
{ "detail": "Задача nope не найдена" }
```

`409` — повторное создание профиля:

```json
{ "detail": "Профиль пользователя strict_tech уже существует" }
```

`409` — повторное создание задачи:

```json
{ "detail": "Задача tz уже существует" }
```

`409` — повторное имя инварианта:

```json
{ "detail": "Инвариант «Только FastAPI и Streamlit» уже существует" }
```

`404` — неизвестный инвариант:

```json
{ "detail": "Инвариант 7 не найден" }
```

`422` — например, пустой `prompt`, `temperature` вне диапазона или неизвестное
значение перечисления в профиле. Формат стандартный для FastAPI:

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

`422` — тело `PATCH /tasks/{task_id}/context` без единого флага. Сюда попадают и
`{}`, и тело с опечаткой (`{"plan_aproved": true}`) или лишним полем
(`{"nope": true}`): лишнее отбрасывается, а известных флагов не остаётся —
поэтому ответ один и тот же:

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body"],
      "msg": "Value error, нужен хотя бы один флаг задачи",
      "input": {}
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

- **Профиль — не слой памяти.** Он не хранит диалог и не отбирается по
  релевантности, а целиком подставляется первым блоком в системное сообщение
  каждого запроса; токены блока входят в `prompt_tokens`/`sent_context_tokens`,
  но в разбивке `memory` не учитываются. Подробнее — раздел
  [«Профиль и три слоя памяти»](#профиль-и-три-слоя-памяти).
- **Профиль применяется к живым агентам.** `POST`/`PUT`/`DELETE
  /users/{user_id}/profile` немедленно меняют профиль у работающих агентов
  этого `user_id` (перезапуск не нужен); `PUT` возвращает их число в поле
  `applied_to_agents`. Внешнего ключа `agents.user_id → user_profiles.user_id`
  нет намеренно: удаление профиля не уносит агентов — они остаются с пустым
  профилем.
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
  `deepseek-reasoner` — 32000. Это демонстрационные лимиты,
  реальный контекст DeepSeek шире; при необходимости они правятся в
  `MODEL_TOKEN_LIMITS` (`backend/core/config.py`). По ним считается
  `context.remaining_tokens` и срабатывает аварийный предохранитель
  `trimmed_messages`.
- **Всё состояние переживает рестарт.** Реплики (`short_term_messages`), рабочая
  (`working_memory`) и долговременная (`long_term_memory`) память, конспекты
  (`summaries`), факты (`facts`), ветки (`checkpoints`), записи `token_usage`,
  профили пользователей (`user_profiles`) и состояние задачи (`task_states` с
  журналом `task_transitions`) лежат в SQLite (`day17/agents.db`), а активные
  сессия и задача — в строке `agents`
  (`current_session_id`/`current_task_id`). При старте приложения `lifespan`
  создаёт таблицы и восстанавливает агентов вместе с диалогом
  (`restore_from_db`), поэтому `/usage`, `/summary`, `/history`, `/users/...`,
  эндпоинты `/memory/...` и `/tasks/...` после перезапуска показывают те же
  данные: агент продолжает задачу с того же этапа и шага без повторных
  объяснений.
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
- **MCP-подключение не переживает рестарт.** Оно живёт в памяти процесса
  (`MCPRegistry`), а не в SQLite: после перезапуска бэкенда `/mcp/status` честно
  отвечает `disconnected`, и подключиться нужно снова. Всё остальное состояние
  дня (память, профили, задачи, инварианты) по-прежнему в базе.
- **Вызов инструмента идёт наружу.** `POST /mcp/call` и шаг MCP в генерации
  обращаются к внешнему серверу (у своего сервера дня — HTTP к
  `jsonplaceholder.typicode.com`): без сети инструмент вернёт ошибку
  (`tool_error` или `transport`), а ход агента всё равно завершится — ответ
  придёт без внешних данных. В промпт уходит только успешный результат
  (`state: "done"`); отказ правил допуска, сбой связи и ошибка инструмента
  данных в промпт не добавляют.
- **Первое подключение к своему серверу требует готового `.venv`.** Цель по
  умолчанию — команда `uv run python mcp_server/server.py`: если окружение дня
  ещё не собрано (`uv sync`), первый запуск дочернего процесса дольше обычного
  и может не уложиться в `MCP_TIMEOUT = 30` секунд.
