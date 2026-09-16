# API дня 13 — агенты DeepSeek с состоянием задачи, памятью и профилем

Бэкенд — FastAPI-приложение `day13/backend/api/main.py`. Заголовок приложения —
«Агенты DeepSeek с состоянием задачи — День 13», версия схемы — `7.0.0`
(видны в Swagger UI и `GET /openapi.json`). Базовый адрес после запуска
(из папки `day13`):

```powershell
.venv/Scripts/python -m uvicorn backend.api.main:app --port 8000
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

День 13 добавляет к этому состояние задачи — конечный автомат из этапов
(`planning`, `execution`, `validation`, `done`, `paused`) и шагов внутри этапов.
Состояние живёт в SQLite (таблицы `task_states` и `task_transitions`), читается
из БД на каждый запрос — поэтому переживает перезапуск процесса — и
подключается **последним** блоком к системному промпту (после профиля, роли и
блоков памяти). Новая реплика пользователя сама двигает состояние: «пауза»,
«продолжи», «вернись на предыдущий этап», «подтверждаю» распознаются до сборки
контекста, поэтому промпт того же запроса описывает уже новое состояние.
Управление — девять эндпоинтов `/tasks...`: создание, список, чтение состояния и
журнала, пауза, продолжение, следующий шаг, откат и прямой переход. Разбор —
в разделе [«Состояние задачи»](#состояние-задачи-день-13).

Профиль пользователя (наследовано из дня 12): у агента есть поле `user_id` —
идентификатор пользователя, чей профиль из таблицы `user_profiles`
подключается **первым** блоком к системному промпту каждого запроса (до роли
агента и до блоков памяти). Профиль заводится и правится через `/users/...`,
применяется к живым агентам пользователя сразу, без перезапуска; его вклад
виден в `GET /agents/{id}/profile` и в полях `profile`/`system_prompt` ответа
генерации. Агент без профиля работает как обычно: пустой профиль не даёт
блоков промпта и ошибкой не считается.

Схемы ответов описаны в пакете `day13/backend/schemas/` — по доменам: `agent.py`
(агент, генерация, метрики), `context.py` (сжатие, стратегии, ветки, факты),
`memory.py` (три слоя памяти), `profile.py` (профиль и его вклад в промпт),
`task.py` (состояние задачи, его переходы и журнал);
сводная таблица полей — в
разделе [«Формы данных»](#формы-данных).

## Эндпоинты

Всего 45 эндпоинтов: 11 в разделе агентов (десять эндпоинтов CRUD, генерации и
статистики плюс корневой `GET /`), 9 контекста (сжатие, стратегии, ветки,
факты), 10 памяти, 6 профилей пользователей и 9 новых — состояния задачи.
Ниже — сводка; разбор по группам —
в разделах [«Слои памяти»](#слои-памяти-день-11),
[«Персонализация»](#персонализация-профили-пользователей-день-12) и
[«Состояние задачи»](#состояние-задачи-день-13).

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
| GET | `/tasks/{task_id}/state` | текущий этап, шаг и ожидаемое действие | 200 TaskStateOut |
| GET | `/tasks/{task_id}/history` | журнал переходов задачи (включая создание) | 200 TaskHistoryOut |
| POST | `/tasks/{task_id}/pause` | пауза с сохранением этапа и шага | 200 TaskStateOut |
| POST | `/tasks/{task_id}/resume` | продолжение с того же места | 200 TaskStateOut |
| POST | `/tasks/{task_id}/advance` | следующий шаг (на последнем шаге этапа — следующий этап) | 200 TaskStateOut |
| POST | `/tasks/{task_id}/rollback` | откат ровно на один этап назад | 200 TaskStateOut |
| POST | `/tasks/{task_id}/transition` | переход в указанный этап/шаг (им пользуется кнопка «Завершить задачу») | 200 TaskStateOut |
| GET | `/` | список доступных эндпоинтов | 200 объект-подсказка |

## GET /

Корневая точка — подсказка: имя приложения, путь к Swagger, префиксы памяти,
персонализации и состояния задачи и перечень эндпоинтов (44 строки — все, кроме
самого `GET /`).

```bash
curl.exe http://127.0.0.1:8000/
```

```json
{
  "name": "Агенты DeepSeek с состоянием задачи — День 13",
  "docs": "/docs",
  "memory": "/agents/{agent_id}/memory/... (short-term | working | long-term)",
  "personalization": "/users, /users/{user_id}/profile, /agents/{agent_id}/profile",
  "tasks": "/agents/{agent_id}/tasks, /tasks/{task_id}/state, ... (9 эндпоинтов)",
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
    "POST /tasks/{task_id}/pause",
    "POST /tasks/{task_id}/resume",
    "POST /tasks/{task_id}/advance",
    "POST /tasks/{task_id}/rollback",
    "POST /tasks/{task_id}/transition"
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

Персонализация (день 12): поле `user_id` (строка 1–64 символа, по умолчанию
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
| `user_id` | строка | 1–64 символа; переключает профиль живого агента (день 12) |

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
   описывает новое место задачи;
2. собирает ОДНО системное сообщение: блок профиля пользователя (если профиль
   не пуст) → системный промпт (роль) агента → рабочая память → долговременная
   память → конспект → факты → состояние задачи (если задача заведена); блок
   профиля — часть системного сообщения, поэтому он попадает в контекст при
   любой стратегии и учитывается в оценке токенов;
3. собирает блоки рабочей и долговременной памяти и краткосрочный слой по
   стратегии, для `summary` — **два** варианта контекста (полный и сжатый) ради
   метрик экономии; отчёт по слоям (`memory`) заполняется уже здесь;
4. при необходимости вызывает DeepSeek;
5. сохраняет пару реплик (в границах текущей сессии) и метрики, включая токены
   по слоям, одной транзакцией;
6. после успешного хода выполняет действие стратегии (сжатие / сохранение
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

Пояснения к персонализации (день 12):

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
не было (в запрос идёт только сам промпт).

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

## Стратегии, ветки и факты (наследовано из дня 10)

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

## Персонализация: профили пользователей (день 12)

Шесть эндпоинтов дня 12. Профиль лежит в таблице `user_profiles` и привязан к
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

## Состояние задачи (день 13)

Девять эндпоинтов дня 13. Состояние задачи — конечный автомат: пять **этапов**
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
этап), `pause` и `resume`:

```text
прямой ход:    planning -> execution -> validation -> done
откат:         validation -> execution;  execution -> planning
пауза:         planning|execution|validation|done -> paused
возобновление: paused -> тот же этап и шаг, с которого встали
```

Допустимые переходы этапов (`STAGE_TRANSITIONS` в `backend/domain/task_fsm.py`):

| Из этапа | Куда можно перейти |
|---|---|
| `planning` | `execution`, `paused` |
| `execution` | `validation`, `planning`, `paused` |
| `validation` | `done`, `execution`, `paused` |
| `done` | `paused` |
| `paused` | `planning`, `execution`, `validation`, `done` |

`advance` идёт по шагам этапа, а с его последнего шага — на первый шаг
следующего этапа (`create_plan → execution/implement`, `test_locally →
validation/review`, `finalize → done/finalize`). `rollback` — ровно один этап
назад, с шагом на первый шаг целевого этапа. Из `planning`, `done` и `paused`
откатываться некуда, а `advance` и `rollback` на паузе запрещены: сначала
`resume`. Недопустимый переход — `400`; неизвестный этап или шаг в теле — `422`
(схема), шаг чужого этапа — `400` (автомат).

Каждый переход попадает в `task_transitions` (и в JSON-поле `history` строки) с
причиной: «задача создана», «следующий шаг», «пауза», «продолжение после паузы»,
«откат на предыдущий этап», «задача завершена», «откат по реплике
пользователя», «переход по запросу».

Блок состояния добавляется **последним** в системное сообщение каждого запроса
(после профиля, роли, памяти, конспекта и фактов) — независимо от стратегии
управления контекстом:

```text
Состояние задачи (текущий этап и шаг; продолжай с этого места):
Текущий этап: execution. Текущий шаг: implement. Ожидаемое действие: ожидается реализация модуля. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены.
```

Ожидаемое действие — текст из `backend/domain/task_prompt.py`: по строке на пару «этап +
шаг» (например, `planning/create_plan` — «ожидается утверждение плана
пользователем», `validation/run_tests` — «ожидается проверка тестов»), у `paused`
— «задача на паузе; ожидается продолжение (resume)», у `done` — «задача
завершена; ожидается новая задача».

Реплика пользователя сама двигает состояние: `backend/domain/task_intent.py` распознаёт
намерение (приоритет — пауза → продолжение → откат → подтверждение шага) **до**
сборки контекста, поэтому блок в промпте того же запроса уже описывает новое
состояние. Совпадение ищется на границе слова, поэтому «продолжительность
сессии» намерением не считается. Недопустимый переход диалог не роняет: он
пишется в лог, а запрос выполняется как обычно.

Активна задача, у которой `stage != "done"` (пауза считается активной). Блок
состояния подключается к промпту только у активной задачи агента, поэтому
`POST /agents/{agent_id}/tasks` делает созданную задачу активной.

| Метод и путь | Тело | Ответ | Коды |
|---|---|---|---|
| `POST /agents/{agent_id}/tasks` | `TaskCreateIn` | `TaskStateOut` | `201`, `404`, `409`, `422` |
| `GET /agents/{agent_id}/tasks` | — | `[TaskStateOut]` | `200`, `404` |
| `GET /tasks/{task_id}/state` | — | `TaskStateOut` | `200`, `404` |
| `GET /tasks/{task_id}/history` | — | `TaskHistoryOut` | `200`, `404` |
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
    "working_memory": {},
    "paused_from_stage": null,
    "paused_from_step": null
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
  "prompt_block": "Состояние задачи (текущий этап и шаг; продолжай с этого места):\nТекущий этап: planning. Текущий шаг: gather_requirements. Ожидаемое действие: ожидается уточнение требований пользователем. Предыдущие шаги: нет."
}
```

`context` — снимок рабочей памяти задачи (`working_memory`, по ключам) плюс метка
паузы: `paused_from_stage`/`paused_from_step` заполняются только на паузе.
`rollback_stage` — куда приведёт откат (`null` — откатываться некуда).

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
    "prompt_block": "…Текущий этап: execution. Текущий шаг: implement. Ожидаемое действие: ожидается реализация модуля. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
  },
  { "id": 2, "task_id": "tz2", "agent_id": "8f1c2d3e4b5a", "stage": "planning",
    "current_step": "define_scope", "expected_action": "ожидается определение границ задачи агентом",
    "rollback_stage": null, "paused_from_stage": null, "is_active": true,
    "prompt_block": "…" }
]
```

Каждый элемент — полный `TaskStateOut` (в примере опущены `context`, `history`,
`created_at`, `updated_at`).

Коды: `200`, `404`.

### GET /tasks/{task_id}/state

Текущее состояние задачи: этап, шаг, ожидаемое действие и производные поля
(`rollback_stage`, `paused_from_stage`, `is_active`, `prompt_block`). `prompt_block`
— ровно тот текст, который уходит в системный промпт запроса.

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
    "paused_from_stage": null,
    "paused_from_step": null
  },
  "history": [ "…четыре записи: создание и три перехода «следующий шаг»…" ],
  "created_at": "2026-09-10T12:20:00+00:00",
  "updated_at": "2026-09-10T12:24:00+00:00",
  "rollback_stage": "planning",
  "paused_from_stage": null,
  "is_active": true,
  "prompt_block": "Состояние задачи (текущий этап и шаг; продолжай с этого места):\nТекущий этап: execution. Текущий шаг: implement. Ожидаемое действие: ожидается реализация модуля. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

До этой точки задачу довели три вызова `POST /tasks/tz/advance`:
`gather_requirements → define_scope → create_plan → execution/implement`.

Коды: `200`, `404`.

### GET /tasks/{task_id}/history

Журнал переходов по возрастанию `id`, включая создание задачи (у него
`from_stage`/`from_step` пусты). Причины повторяют операции: «задача создана»,
«следующий шаг», «пауза», «продолжение после паузы», «откат на предыдущий этап»,
«задача завершена».

```bash
curl.exe http://127.0.0.1:8000/tasks/tz/history
```

```json
{
  "task_id": "tz",
  "entries": [
    { "id": 1, "task_id": "tz", "from_stage": null, "from_step": null,
      "to_stage": "planning", "to_step": "gather_requirements",
      "reason": "задача создана", "created_at": "2026-09-10T12:20:00+00:00" },
    { "id": 2, "task_id": "tz", "from_stage": "planning", "from_step": "gather_requirements",
      "to_stage": "planning", "to_step": "define_scope",
      "reason": "следующий шаг", "created_at": "2026-09-10T12:21:00+00:00" },
    { "id": 3, "task_id": "tz", "from_stage": "planning", "from_step": "define_scope",
      "to_stage": "planning", "to_step": "create_plan",
      "reason": "следующий шаг", "created_at": "2026-09-10T12:22:00+00:00" },
    { "id": 4, "task_id": "tz", "from_stage": "planning", "from_step": "create_plan",
      "to_stage": "execution", "to_step": "implement",
      "reason": "следующий шаг", "created_at": "2026-09-10T12:24:00+00:00" }
  ]
}
```

Коды: `200`, `404`.

### POST /tasks/{task_id}/pause

Ставит задачу на паузу, **сохраняя** этап и шаг: продолжение вернёт её ровно
туда, где она встала. В ответе `stage = "paused"`, `current_step` не меняется,
`paused_from_stage`/`paused_from_step` описывают точку возврата, а
`expected_action` — «задача на паузе; ожидается продолжение (resume)».
Повторная пауза — `400` («задача уже на паузе»).

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
    "paused_from_stage": "execution",
    "paused_from_step": "implement"
  },
  "history": [ "…пятая запись: reason «пауза»…" ],
  "created_at": "2026-09-10T12:20:00+00:00",
  "updated_at": "2026-09-10T12:25:00+00:00",
  "rollback_stage": null,
  "paused_from_stage": "execution",
  "is_active": true,
  "prompt_block": "Состояние задачи (текущий этап и шаг; продолжай с этого места):\nТекущий этап: paused. Текущий шаг: implement. Ожидаемое действие: задача на паузе; ожидается продолжение (resume). Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

Коды: `200`, `400` (повторная пауза), `404`.

### POST /tasks/{task_id}/resume

Возвращает задачу из `paused` в этап и шаг, с которых она встала; метка паузы
снимается (`paused_from_stage` и `paused_from_step` — `null`). Продолжение
задачи, которая не на паузе, — `400` («задача не на паузе»).

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
  "prompt_block": "…Текущий этап: execution. Текущий шаг: implement. Ожидаемое действие: ожидается реализация модуля. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

Коды: `200`, `400` (не на паузе), `404`.

### POST /tasks/{task_id}/advance

Следующий шаг текущего этапа; с последнего шага этапа — первый шаг следующего
этапа. Ожидаемое действие и производные поля пересчитываются.

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
    "paused_from_stage": null,
    "paused_from_step": null
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
  "prompt_block": "…Текущий этап: execution. Текущий шаг: implement. Ожидаемое действие: ожидается реализация модуля. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

Это ответ третьего подряд `advance` из `planning/gather_requirements` — на
границе этапов: последний шаг `planning` переводит в первый шаг `execution`.

Из `done` шаг вперёд не идёт, из `paused` — тоже (сначала `resume`):

```json
{ "detail": "задача завершена: этап done терминальный" }
```

```json
{ "detail": "задача на паузе: сначала продолжите её (resume)" }
```

Коды: `200`, `400`, `404`.

### POST /tasks/{task_id}/rollback

Откат ровно на один этап назад (`validation → execution`, `execution →
planning`) с шагом на первый шаг целевого этапа и причиной «откат на предыдущий
этап». Значение `to_stage` обязано совпасть с целью отката — иначе `400`, как в
примере ниже. Перед примером задача стояла на `validation/run_tests`.

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
  "history": [ "…последняя запись: из validation/run_tests в execution/implement, reason «откат на предыдущий этап»…" ],
  "rollback_stage": "planning",
  "paused_from_stage": null,
  "is_active": true,
  "prompt_block": "…Текущий этап: execution. Текущий шаг: implement. Ожидаемое действие: ожидается реализация модуля. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
}
```

Задача на этапе `execution`, а `to_stage` указывает на `validation` — цель отката
не совпала:

```json
{ "detail": "откат с этапа execution возможен только на этап planning" }
```

Откат из `planning`, `done` и `paused` невозможен:

```json
{ "detail": "у этапа planning нет предыдущего этапа" }
```

Коды: `200`, `400`, `404`, `422` (неизвестный этап в `to_stage`).

### POST /tasks/{task_id}/transition

Прямой переход в указанный этап и шаг — им пользуется кнопка «Завершить задачу»
интерфейса. `step`, `expected_action` и `reason` необязательны: без них берётся
первый шаг целевого этапа (`finalize` для `done`, текущий шаг для `paused`),
ожидаемое действие этапа и причина «переход по запросу». Так завершение задачи
описывается одним вызовом.

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
    "paused_from_stage": null,
    "paused_from_step": null
  },
  "history": [ "…последняя запись: из validation/finalize в done/finalize, reason «задача завершена»…" ],
  "created_at": "2026-09-10T12:20:00+00:00",
  "updated_at": "2026-09-10T12:30:00+00:00",
  "rollback_stage": null,
  "paused_from_stage": null,
  "is_active": false,
  "prompt_block": "…Текущий этап: done. Текущий шаг: finalize. Ожидаемое действие: задача завершена; ожидается новая задача. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены; execution (implement, test_locally) — завершены; validation (review, run_tests, finalize) — завершены."
}
```

После этого задача неактивна (`is_active: false`) и пропадает из
`GET /agents/{agent_id}/tasks`; шаг вперёд уже не описан:

```json
{ "detail": "задача завершена: этап done терминальный" }
```

`step` можно задать явно: `{"stage": "execution", "step": "test_locally"}`;
шаг чужого этапа — `400` («шаг review не принадлежит этапу execution»).

Коды: `200`, `400`, `404`, `422` (неизвестный этап/шаг, слишком длинные
`expected_action` — до 500 символов — и `reason` — до 200).

### Состояние задачи в ответе генерации

`POST /agents/{agent_id}/generate` возвращает поле `task_state` (`TaskStateOut`
или `null`, если у активной задачи агента состояния нет) — состояние на момент
запроса. Поле и блок `system_prompt` считаются **до** вызова DeepSeek, поэтому
видны и при `502`:

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
    "prompt_block": "…Текущий этап: execution. Текущий шаг: implement. Ожидаемое действие: ожидается реализация модуля. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены."
  },
  "system_prompt": "Профиль пользователя (персонализация; соблюдай в каждом ответе):\n…\n\nРабочая память задачи tz:\n…\n\nСостояние задачи (текущий этап и шаг; продолжай с этого места):\nТекущий этап: execution. Текущий шаг: implement. Ожидаемое действие: ожидается реализация модуля. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены.",
  "messages": [ "…" ]
}
```

Реплика, в которой распознано намерение, двигает состояние **в этом же** запросе:
`generate` с промптом «продолжаем» на задаче, стоящей на `paused/implement`,
вернёт `task_state.stage = "execution"` и блок промпта с `execution/implement`.
Недопустимое намерение (например, «вернись на предыдущий этап» на `planning`)
состояние не меняет, а запрос проходит как обычно.

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
| `user_id` | строка | пользователь, чей профиль применяется к запросам агента (день 12), по умолчанию `default` |

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
| `profile` | AppliedProfileOut/null | применённый профиль и его вклад в промпт (день 12; заполнен и при `error`) |
| `task_state` | TaskStateOut/null | состояние задачи на момент ответа (день 13; заполнено и при `error`; `null` — задачи нет) |
| `system_prompt` | строка | итоговое system-сообщение запроса (профиль + роль + блоки памяти + блок состояния задачи; считается до вызова DeepSeek) |
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

### Профили пользователей (день 12)

`UserProfileIn` — тело `POST`/`PUT /users/{user_id}/profile` (поля разобраны в
разделе [«Персонализация»](#персонализация-профили-пользователей-день-12)):
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

### Состояние задачи (день 13)

`TaskCreateIn` — тело `POST /agents/{agent_id}/tasks`: `task_id` (1–64 символа,
уникален; повторный — `409`) и `initial_stage` (`planning` / `execution` /
`validation`, по умолчанию `planning`; `paused` и `done` — `422`).

`TaskRollbackIn` — тело `POST /tasks/{task_id}/rollback`: одно поле `to_stage`
(значение этапа, проверяется `stage_from_value`). Оно обязано совпасть с целью
отката (`validation → execution`, `execution → planning`), иначе `400`.

`TaskTransitionIn` — тело `POST /tasks/{task_id}/transition`: `stage` (обязателен),
`step` (`null` — первый шаг целевого этапа, для `done` это `finalize`, для
`paused` — текущий шаг), `expected_action` (до 500 символов) и `reason` (до 200);
непереданные значения домен подставляет сам.

| TaskStateOut | Тип | Пояснение |
|---|---|---|
| `id` | int | id строки `task_states` |
| `task_id` | строка | идентификатор задачи (уникален) |
| `agent_id` | строка | агент-владелец |
| `stage` | строка | текущий этап: `planning`/`execution`/`validation`/`done`/`paused` |
| `current_step` | строка | текущий шаг этапа (у `done` остаётся `finalize`) |
| `expected_action` | строка | чего ждём на этом шаге (текст из `task_prompt.py`) |
| `context` | объект | `task_id`, снимок `working_memory` задачи, `paused_from_stage`, `paused_from_step` |
| `history` | [объект] | журнал переходов внутри строки (те же поля, что у `TaskTransitionOut`, плюс `at` и `expected_action`) |
| `created_at` | datetime | когда задача заведена (UTC) |
| `updated_at` | datetime | последний переход (UTC) |
| `rollback_stage` | строка/null | этап, на который приведёт откат (`null` — откатываться некуда) |
| `paused_from_stage` | строка/null | этап, с которого встали на паузу |
| `is_active` | bool | `stage != "done"`; пауза считается активной |
| `prompt_block` | строка | заголовок и строка блока состояния — ровно тот текст, что идёт в системный промпт |

| TaskTransitionOut | Тип | Пояснение |
|---|---|---|
| `id` | int | id записи журнала |
| `task_id` | строка | задача |
| `from_stage` | строка/null | откуда перешли (`null` только у создания задачи) |
| `from_step` | строка/null | шаг до перехода (`null` только у создания задачи) |
| `to_stage` | строка | этап после перехода |
| `to_step` | строка | шаг после перехода |
| `reason` | строка | причина: «задача создана», «следующий шаг», «пауза», «продолжение после паузы», «откат на предыдущий этап», «задача завершена», «откат по реплике пользователя», «переход по запросу» |
| `created_at` | datetime | время перехода (UTC) |

`TaskHistoryOut` — ответ `GET /tasks/{task_id}/history`: `task_id` и `entries`
([TaskTransitionOut] по возрастанию `id`, первая запись — создание задачи).

## Коды ошибок

| Код | Когда | Тело |
|---|---|---|
| `400` | пустой `task_id` после обрезки пробелов в `PUT /memory/task`; недопустимый переход состояния задачи (`advance` из `done`, откат из `planning`/`done`/`paused`, `advance` и `rollback` на паузе, шаг чужого этапа); пауза и продолжение не по месту (`pause` дважды, `resume` не на паузе) | `HTTPException` с `detail` |
| `404` | неизвестный `agent_id` во всех `/agents/{agent_id}/...` (а для `DELETE /memory/long-term/{id}` — ещё и отсутствующая запись); нет профиля у `GET`/`PUT`/`DELETE /users/{user_id}/profile`; неизвестный `task_id` во всех `/tasks/{task_id}/...` | `HTTPException` с `detail` |
| `409` | профиль с таким `user_id` уже есть (`POST /users/{user_id}/profile`); задача с таким `task_id` уже заведена (`POST /agents/{agent_id}/tasks`) | `HTTPException` с `detail` |
| `422` | невалидное тело запроса (Pydantic/FastAPI): невалидные поля профиля, `initial_stage` вне `planning`/`execution`/`validation`, неизвестный этап/шаг, слишком длинные `expected_action`/`reason`, пустой `task_id` | объект с `detail` — списком ошибок |
| `502` | сбой генерации `POST /generate` (нет ключа, сеть, лимиты) | `GenerateResponse` со `status:"error"` |

`400` — недопустимый переход состояния задачи (`advance` из `done`, откат не на
предыдущий этап, пауза/продолжение не по месту):

```json
{ "detail": "задача завершена: этап done терминальный" }
```

```json
{ "detail": "откат с этапа execution возможен только на этап planning" }
```

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

- **Что появилось в дне 13.** Состояние задачи как конечный автомат: таблицы
  `task_states` и `task_transitions` (ORM-классы `TaskState`/`TaskTransition` в
  `backend/models/task_state.py`); модули `backend/domain/task_fsm.py` (этапы, шаги, события,
  таблица переходов), `backend/domain/task_prompt.py` (ожидаемые действия и сборка
  блока промпта), `backend/domain/task_intent.py` (распознавание намерения в реплике),
  `backend/storage/task_store.py` (доступ к таблицам), `backend/services/task_state.py`
  (`TaskStateMachine` — валидация и переходы), `backend/agents/manager_tasks.py`
  (миксин `TaskOpsMixin`), `backend/schemas/task.py` (схемы),
  `backend/api/tasks.py` (девять эндпоинтов `/tasks...`); блок состояния
  последним элементом системного промпта (учитывается и в `system_prompt` ответа
  генерации); авто-обновление состояния по реплике пользователя до сборки
  контекста; поле `task_state` в `GenerateResponse`; ключ `tasks` в ответе
  `GET /`; панель «🧭 Состояние задачи» в Streamlit и скрипт
  `scripts/task_state_demo.py` (отчёт `reports/task_state_demo.md`).
- **Что появилось в дне 12.** Персонализация: таблица `user_profiles` (ORM-класс
  `UserProfile`) и колонка `agents.user_id`; модули `backend/domain/profiles.py`
  (правила и сборка блока промпта), `backend/agents/profile_store.py` (доступ к
  таблице), `backend/domain/demo_profiles.py` (данные демонстрации); эндпоинты
  `/users`, `/users/{user_id}/profile` (`GET`/`POST`/`PUT`/`DELETE`),
  `/agents/{agent_id}/profile`; схемы `UserProfileIn`, `UserProfileOut`,
  `UserProfileDeleteOut`, `ProfileElementOut`, `AppliedProfileOut`; поля
  `profile`/`system_prompt` в `GenerateResponse`; поле `personalization` в
  ответе `GET /`; `user_id` в `AgentConfig`/`AgentPatch`/`AgentSummary`
  (а значит, и в `AgentInfo`).
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
  `MODEL_TOKEN_LIMITS` (`backend/core/config.py`). По ним считается
  `context.remaining_tokens` и срабатывает аварийный предохранитель
  `trimmed_messages`.
- **Всё состояние переживает рестарт.** Реплики (`short_term_messages`), рабочая
  (`working_memory`) и долговременная (`long_term_memory`) память, конспекты
  (`summaries`), факты (`facts`), ветки (`checkpoints`), записи `token_usage`,
  профили пользователей (`user_profiles`) и состояние задачи (`task_states` с
  журналом `task_transitions`) лежат в SQLite (`day13/agents.db`), а активные
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
