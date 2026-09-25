# API дня 20 — агенты DeepSeek с оркестрацией флота MCP-серверов, декларативным пайплайном, планировщиком фоновых задач, контролируемыми переходами, инвариантами, состоянием задачи, памятью и профилем

Бэкенд — FastAPI-приложение `day20/backend/api/main.py`. Заголовок приложения —
«Агенты DeepSeek + оркестрация MCP-серверов — День 20», версия схемы — `14.0.0`
(видны в Swagger UI и `GET /openapi.json`). Базовый адрес после запуска
(из папки `day20`):

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
Protocol), его каталог и **вызов инструмента**: пять эндпоинтов активного
соединения `/mcp/connect`, `/mcp/disconnect`, `/mcp/status`, `/mcp/tools` и
`/mcp/call` (флот серверов — отдельная группа эндпоинтов дня 20, см. ниже).
Транспорт выбирается по виду цели (команда запуска — stdio, `http://` —
Streamable HTTP, `sse://` — SSE), список инструментов отдаётся полями `name`,
`description`, `input_schema`, `output_schema` вместе с `count`. Свой сервер дня
живёт в `day20/mcp_server/` (stdio, девять инструментов: `get_user`, `get_post`,
`list_user_posts` читают jsonplaceholder.typicode.com, `schedule_reminder`,
`collect_data` и `generate_summary` ставят фоновые задачи через API дня, а
`search`, `summarize` и `save_to_file` служат композиции — см. ниже), а агент
сам решает по ключевым словам реплики, нужен ли вызов, и подставляет полученные
данные в системный промпт того же запроса (поле `mcp` ответа генерации).
Соединение одно на процесс и **не переживает** перезапуск бэкенда (это связь с
внешним процессом, а не данные домена); при остановке приложения оно закрывается
в `lifespan`.
Разбор — в разделе [«MCP»](#mcp).

**Планировщик фоновых задач** (день 18) — 14 эндпоинтов `/scheduler...` и три
инструмента с отложенным и периодическим выполнением: напоминание
(`schedule_reminder`), периодический сбор данных из внешнего API (`collect_data`)
и регулярная сводка по накопленным данным (`generate_summary`). Фон живёт в
процессе бэкенда (APScheduler, `AsyncIOScheduler`), метаданные задач — в таблице
`scheduled_tasks`, поэтому задачи переживают перезапуск: при старте `lifespan`
поднимает планировщик и сверяет его набор с базой. Инструменты планировщика не
пишут в SQLite сами — их тела вызывают `POST /scheduler/tasks`, а единственный
писатель в базу — процесс бэкенда. Разбор — в разделе
[«Планировщик»](#планировщик).

**Композиция MCP-инструментов** (день 19) — 5 эндпоинтов `/pipelines...` и
**декларативный пайплайн**: шаги описаны данными (`domain/pipeline_spec.py`), а
не кодом, поэтому одну и ту же конфигурацию можно прислать телом запроса,
показать в интерфейсе и положить в отчёт. Аргументы шага — шаблон со ссылками на
аргументы запуска (`{query}`, `{source}`) и на выход предыдущего шага
(`$steps.0.structured.items`); маппингом заведует `domain/pipeline_mapping.py`,
условие перехода (`guard`: `non_empty` / `empty` / `equals` / `contains`) решает,
звать ли инструмент вообще. Встроенный пайплайн
`search-summarize-save` — три инструмента композиции по очереди: `search` ищет
данные в источнике (лента jsonplaceholder, файл дня или таблица SQLite — только на
чтение), `summarize` сводит найденное (DeepSeek, а без ключа — агрегацией),
`save_to_file` пишет результат в файл каталога `output/`. Каждый шаг журналируется
в таблицу `pipeline_steps` (входные аргументы, результат, время, статус), запуск —
в `pipeline_runs`; прогон можно запустить фоном, тогда интерфейс опрашивает статус
и показывает прогресс по шагам. Та же реплика из чата («найди статьи про RAG,
сделай сводку и сохрани в файл») запускает пайплайн синхронно, и его результат
уходит в системный промпт того же запроса (поле `pipeline` ответа генерации).
Разбор — в разделе [«Пайплайн»](#пайплайн).

**Оркестрация флота MCP-серверов** (день 20) — шесть эндпоинтов
`/orchestration...` и три эндпоинта `/mcp/servers...`. Три независимых
MCP-сервера дня (`day20/mcp_servers/search_server`, `data_server`,
`storage_server` — 11 инструментов) описаны данными в `day20/mcp_servers.json`;
реестр `backend/services/mcp_registry.py` держит соединение с каждым сервером и
**маршрутизирует вызов по имени инструмента**, а `Orchestrator`
(`backend/services/orchestrator.py`) строит план шагов (из запроса, моделью или
эвристикой) и выполняет его: маппинг аргументов → условие шага → поиск сервера →
подключение при нужде → вызов → строка журнала → событие автомата. Каждый шаг
попадает в `orchestration_steps` (сервер, инструмент, вход, выход, время,
статус), запуск — в `orchestration_runs`, поэтому историю и статистику видно
через API и во вкладке «🌐 Оркестрация». `GET /mcp/servers` теперь показывает
состав ФЛОТА и состояние подключений (не каталог «известных целей», как было
днём 16); демонстрационный сценарий — пять шагов по трём серверам — запускается
одной кнопкой «🚀 Запустить демо-сценарий» или одним запросом
`POST /orchestration/demo`. Разбор — в разделах [«Оркестрация»](#оркестрация) и
[«MCP-серверы»](#mcp-серверы), отчёт сквозного прогона —
`day20/docs/reports/orchestration_demo.md`.

Схемы ответов описаны в пакете `day20/backend/schemas/` — по доменам: `agent.py`
(агент, генерация, метрики), `context.py` (сжатие, стратегии, ветки, факты),
`invariant.py` (инварианты и результат проверки), `mcp.py` (статус MCP-подключения,
инструменты сервера и их вызов), `mcp_servers.py` (флот MCP-серверов, его
инструменты и обновление кэша), `memory.py` (три слоя памяти),
`orchestration.py` (запуск оркестрации, его шаги и отчёт по реплике),
`pipeline.py` (запуск пайплайна, его шаги и отчёт по реплике), `profile.py`
(профиль и его вклад в промпт), `task.py` (состояние задачи, его
переходы и журнал), `scheduler.py` (инструменты планировщика, задачи, их запуски,
напоминания, сводки и уведомления); сводная таблица полей — в
разделе [«Формы данных»](#формы-данных).

## Эндпоинты

Всего 85 записей эндпоинтов (в списке `GET /` — все, кроме самой подсказки): 10 в
разделе агентов (CRUD, генерация и статистика), 9 контекста (сжатие, стратегии,
ветки, факты), 10 памяти, 6 профилей пользователей, 11 состояния задачи, 6
инвариантов, 5 MCP активного соединения, 3 флота MCP-серверов, 14 планировщика, 5
пайплайна и 6 оркестрации. Вместе с корневым `GET /` приложение объявляет 86
эндпоинтов, а уникальных путей в OpenAPI — 67: FastAPI сводит методы одного пути
(`GET`/`POST`/`DELETE /orchestration/runs/{run_id}` — это три записи одного пути) в
одну запись схемы.
Ниже — сводка; разбор по группам —
в разделах [«Слои памяти»](#слои-памяти),
[«Персонализация»](#персонализация-профили-пользователей),
[«Состояние задачи»](#состояние-задачи),
[«Инварианты»](#инварианты), [«MCP»](#mcp), [«Планировщик»](#планировщик),
[«Пайплайн»](#пайплайн), [«Оркестрация»](#оркестрация) и
[«MCP-серверы»](#mcp-серверы).

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
| GET | `/mcp/servers` | состав флота MCP-серверов из `mcp_servers.json` и состояние подключений | 200 MCPServersResponse |
| GET | `/mcp/servers/{name}/tools` | инструменты одного сервера флота (из соединения или кэша файла; 404 — нет такого сервера) | 200 MCPServerToolsResponse |
| POST | `/mcp/servers/refresh` | перечитать `tools/list` каждого подключённого сервера и записать кэш в файл | 200 MCPRefreshResponse |
| GET | `/scheduler/tasks` | задачи планировщика (+состояние планировщика; фильтр `status`) | 200 SchedulerTasksResponse |
| POST | `/scheduler/tasks` | создать задачу: инструмент, аргументы, расписание (400 — отказ домена) | 201 SchedulerTaskCreateOut |
| DELETE | `/scheduler/tasks/{task_id}` | снять задачу с обслуживания и удалить её строку | 200 `{status:"deleted", task_id}` |
| POST | `/scheduler/tasks/{task_id}/pause` | пауза задачи (`active` → `paused`) | 200 ScheduledTaskOut |
| POST | `/scheduler/tasks/{task_id}/resume` | возобновить задачу (`paused` → `active`) | 200 ScheduledTaskOut |
| POST | `/scheduler/tasks/{task_id}/run` | запуск вне расписания (тот же тик, что и по таймеру) | 200 SchedulerRunOut |
| GET | `/scheduler/tasks/{task_id}/history` | запуски задачи (`prepare` и `tick`) | 200 SchedulerRunsResponse |
| GET | `/scheduler/tools` | каталог трёх инструментов планировщика с аргументами | 200 SchedulerToolsResponse |
| GET | `/scheduler/status` | работает ли планировщик, часовой пояс, число job'ов | 200 SchedulerStatusOut |
| GET | `/scheduler/reminders` | напоминания (фильтр `status`) | 200 RemindersResponse |
| GET | `/scheduler/collected` | накопленные записи сбора (фильтр `name`) | 200 CollectedResponse |
| GET | `/scheduler/summaries` | регулярные сводки (фильтр `name`) | 200 SummariesResponse |
| GET | `/scheduler/notifications` | очередь уведомлений (`unread_only`, счётчик `unread`) | 200 NotificationsResponse |
| POST | `/scheduler/notifications/{notification_id}/read` | отметить уведомление прочитанным | 200 NotificationOut |
| POST | `/pipelines/run` | запустить пайплайн (синхронно или фоном; 400 — негодная конфигурация) | 200 PipelineStartOut |
| GET | `/pipelines/runs` | история запусков (фильтр `status`, предел `limit`) | 200 PipelineRunsResponse |
| GET | `/pipelines/runs/{run_id}` | отчёт о запуске: статус, шаги, итог, причина остановки | 200 PipelineRunReportOut |
| GET | `/pipelines/runs/{run_id}/steps` | шаги одного запуска по порядку | 200 PipelineStepsResponse |
| DELETE | `/pipelines/runs/{run_id}` | удалить запуск вместе с шагами | 200 `{status:"deleted", run_id}` |
| POST | `/orchestration/run` | запустить оркестрацию по реплике (своим, модельным или встроенным планом; 400 — негодный план) | 200 OrchestrationStartOut |
| POST | `/orchestration/demo` | запустить демо-сценарий: пять шагов по трём серверам | 200 OrchestrationStartOut |
| GET | `/orchestration/runs` | история запусков (фильтр `status`, предел `limit`) + статистика по журналу | 200 OrchestrationRunsResponse |
| GET | `/orchestration/runs/{run_id}` | отчёт о запуске: статус, шаги, серверы, итог, причина остановки | 200 OrchestrationRunReportOut |
| GET | `/orchestration/runs/{run_id}/steps` | шаги одного запуска по порядку | 200 OrchestrationStepsResponse |
| DELETE | `/orchestration/runs/{run_id}` | удалить запуск вместе с шагами | 200 `{status:"deleted", run_id}` |
| GET | `/` | список доступных эндпоинтов | 200 объект-подсказка |

## GET /

Корневая точка — подсказка: имя приложения, путь к Swagger, префиксы памяти,
персонализации, состояния задачи (отдельным ключом — группа `task_transitions`),
инвариантов, MCP (активное соединение), флота MCP-серверов (ключ `mcp_servers`),
планировщика, пайплайна и оркестрации, а также перечень эндпоинтов (85 строк —
все, кроме самого `GET /`).

```bash
curl.exe http://127.0.0.1:8000/
```

```json
{
  "name": "Агенты DeepSeek с оркестрацией MCP-серверов — День 20",
  "docs": "/docs",
  "memory": "/agents/{agent_id}/memory/... (short-term | working | long-term)",
  "personalization": "/users, /users/{user_id}/profile, /agents/{agent_id}/profile",
  "tasks": "/agents/{agent_id}/tasks, /tasks/{task_id}/state, ... (11 эндпоинтов)",
  "task_transitions": "/tasks/{task_id}/transition, /tasks/{task_id}/allowed-next, /tasks/{task_id}/context",
  "invariants": "/invariants, /invariants/{invariant_id}, /invariants/check (6 эндпоинтов)",
  "mcp": "/mcp/connect, /mcp/disconnect, /mcp/status, /mcp/tools, /mcp/call (5 эндпоинтов — активное соединение раздела «MCP»)",
  "mcp_servers": "/mcp/servers, /mcp/servers/{name}/tools, /mcp/servers/refresh (3 эндпоинта — флот серверов)",
  "scheduler": "/scheduler/tasks, /scheduler/tasks/{task_id}/pause|resume|run|history, /scheduler/tools, /scheduler/status, /scheduler/reminders, /scheduler/collected, /scheduler/summaries, /scheduler/notifications (14 эндпоинтов)",
  "pipelines": "/pipelines/run, /pipelines/runs, /pipelines/runs/{run_id}, /pipelines/runs/{run_id}/steps, /pipelines/runs/{run_id} (5 эндпоинтов)",
  "orchestration": "/orchestration/run, /orchestration/demo, /orchestration/runs, /orchestration/runs/{run_id}, /orchestration/runs/{run_id}/steps, DELETE /orchestration/runs/{run_id} (6 эндпоинтов)",
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
    "POST /invariants/check",
    "POST /mcp/connect",
    "POST /mcp/disconnect",
    "GET /mcp/status",
    "GET /mcp/tools",
    "POST /mcp/call",
    "GET /mcp/servers",
    "GET /mcp/servers/{name}/tools",
    "POST /mcp/servers/refresh",
    "GET /scheduler/tasks",
    "POST /scheduler/tasks",
    "DELETE /scheduler/tasks/{task_id}",
    "POST /scheduler/tasks/{task_id}/pause",
    "POST /scheduler/tasks/{task_id}/resume",
    "POST /scheduler/tasks/{task_id}/run",
    "GET /scheduler/tasks/{task_id}/history",
    "GET /scheduler/tools",
    "GET /scheduler/status",
    "GET /scheduler/reminders",
    "GET /scheduler/collected",
    "GET /scheduler/summaries",
    "GET /scheduler/notifications",
    "POST /scheduler/notifications/{notification_id}/read",
    "POST /pipelines/run",
    "GET /pipelines/runs",
    "GET /pipelines/runs/{run_id}",
    "GET /pipelines/runs/{run_id}/steps",
    "DELETE /pipelines/runs/{run_id}",
    "POST /orchestration/run",
    "POST /orchestration/demo",
    "GET /orchestration/runs",
    "GET /orchestration/runs/{run_id}",
    "GET /orchestration/runs/{run_id}/steps",
    "DELETE /orchestration/runs/{run_id}"
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
4. проверяет запрос инвариантами, а затем — если эвристика
   (`backend/domain/pipeline_intent.py`) нашла в реплике все три действия
   пайплайна — **синхронно** прогоняет декларативный пайплайн
   (`Agent.apply_pipeline`) и дописывает его результат системным блоком
   «## Результат пайплайна» в промпт того же запроса (поле `pipeline` отчёта).
   Шаг пайплайна идёт **до** контроля лимита контекста и **вместо** одиночного
   вызова MCP-инструмента: реплика с пайплайном не разбирается как одиночный
   вызов (`record["mcp"]` остаётся `null`). Если пайплайн не распознан,
   выполняется прежний шаг MCP (`apply_mcp_tool`, день 17), а из него —
   регистрация задачи планировщика (`record["schedule"]`);
5. при необходимости вызывает DeepSeek;
6. проверяет ответ модели на предложение перейти в другой этап
   (`backend/domain/task_proposal.py`): недопустимое предложение не выполняется и
   не остаётся в ответе — вместо него уходит отказ с причиной и подсказкой, а
   само предложение видно в поле `task_proposal`;
7. сохраняет пару реплик (в границах текущей сессии) и метрики, включая токены
   по слоям, одной транзакцией;
8. после успешного хода выполняет действие стратегии (сжатие / сохранение
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
  "schedule": null,
  "pipeline": null,
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

Пояснения к шагу планировщика:

- `schedule` — отчёт о фоновой задаче, заведённой этим ходом
  (`ScheduleReportOut`): `registered`, `tool`, `task`, `summary`, `message`.
  Поле считается до вызова DeepSeek (задача к этому моменту уже стоит в
  планировщике), поэтому заполнено и при `502`;
- `null` — фоновой задачи не появилось: реплика не про планировщик, соединение с
  MCP-сервером не открыто, правила допуска вызова отклонили его или инструмент
  ответил ошибкой. Сам отказ в этом случае виден в поле `mcp`
  (`reason_code`/`error`), а ход не падает;
- при `registered: true` в системный промпт того же запроса уходит блок «Данные
  планировщика»: без него модель отвечает «я не умею планировать», хотя задача уже
  поставлена. Токены этого блока учтены в `mcp.added_tokens`.

Пояснения к шагу пайплайна:

- `pipeline` — отчёт о прогоне, запущенном **этой репликой**
  (`PipelineReportOut`): `detected` (распознала ли эвристика композицию в
  реплике), `run_id`, `status` (`completed` / `stopped` / `failed`), `message`,
  `failed_at_step`, `error`, `steps` (те же `PipelineStepOut`, что и в
  `/pipelines`), `count`, `total_duration_ms`, `used_in_prompt` (ушёл ли
  результат системным блоком в промпт) и `added_tokens` (сколько токенов добавил
  блок);
- прогон выполняется **синхронно** в этом же запросе и **до** контроля лимита
  контекста, поэтому `pipeline` заполняется и при `502`: не хватило ключа
  DeepSeek — пайплайн всё равно отработал (`save_to_file` пишет файл), а ошибка
  генерации приходит отдельным полем `error`. Сбой шага пайплайна сам запрос не
  роняет: прогон получает статус `failed`, а `record["pipeline"].error` объясняет
  причину;
- `null` — композиции в реплике нет (`detected: false`) или отказ по `hard`-
  инварианту: пайплайн запускается только после проверки инвариантов, поэтому
  отклонённая реплика его не выполняет;
- при распознанном пайплайне `record["mcp"]` остаётся `null`: реплика не
  разбирается ещё и как одиночный вызов инструмента. В системный промпт уходит
  блок «## Результат пайплайна»; токены блока учтены в `pipeline.added_tokens` и
  входят в контроль лимита контекста;
- в чате результат прогона виден строкой «🔀 Пайплайн: …» в сводке хода
  (`frontend/chat_section.py`), а сам запуск и его шаги — в разделе
  «🔀 Пайплайны» (`frontend/pipeline_section.py`).

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
Шаг пайплайна (`pipeline`) выполняется тоже до вызова DeepSeek — до контроля
лимита контекста, — поэтому распознанный прогон заполнен и при `502`.
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

MCP-подключение дня 17 — одно на процесс бэкенда: его держит реестр
`backend/services/mcp_registry.py` (`MCPRegistry`), а само соединение ведёт
`backend/services/mcp_client.py` (`MCPClient`) вместе со стейт-машиной
`backend/domain/mcp_connection_fsm.py`. Соединение живёт в памяти процесса и
**не переживает** перезапуск (это связь с внешним сервером, а не данные дня);
при остановке приложения `lifespan` вызывает `close()`, поэтому сервер-stdio не
остаётся висеть процессом. Новое подключение закрывает прежнее; список
инструментов кэшируется в открытой сессии до `refresh=true`.
Соединений у процесса дня 20 столько, сколько серверов в `mcp_servers.json`:
кроме активного соединения этого раздела реестр держит **флот** — он описан в
разделе [«MCP-серверы»](#mcp-серверы).

Пять эндпоинтов активного соединения: `POST /mcp/connect`,
`POST /mcp/disconnect`, `GET /mcp/status`, `GET /mcp/tools` и
`POST /mcp/call` (вызов инструмента, добавлен днём 17). Контракт ошибок
подключения: `400` — цель не разобрана
(пустая строка из пробелов, URL там, где нужна команда, и наоборот); `409` —
инструменты запрошены без соединения; `422` — тело не проходит схему (пустая
цель, неизвестный транспорт); `502` — сервер недоступен, команда не найдена,
таймаут или ошибка `tools/list` (текст — одна строка с подсказкой). Коды
`POST /mcp/call` разобраны в его разделе ниже.

Свой сервер дня живёт в `day20/mcp_server/` и запускается по stdio: клиент
поднимает его дочерним процессом (``uv run python mcp_server/server.py``), а
инструменты читают `https://jsonplaceholder.typicode.com` через
`mcp_server/api_client.py`. Сервер вырос по дням: днём 17 у него было три
инструмента чтения, днём 18 стало **шесть** (три прежних читают jsonplaceholder
— `get_user`, `get_post`, `list_user_posts`, а три планировщика —
`schedule_reminder`, `collect_data`, `generate_summary` — ставят фоновые задачи,
их тела вызывают `POST /scheduler/tasks` бэкенда дня через
`mcp_server/backend_api.py`, потому что единственный писатель в SQLite — процесс
бэкенда, и фон живёт там же), а днём 19 — **девять**: добавлены три инструмента
**композиции** (`mcp_server/pipeline_tools.py`) — `search` ищет данные в
источнике (лента внешнего API, файл внутри папки дня или таблица базы дня — только
на чтение), `summarize` сводит найденное, `save_to_file` пишет результат в файл
каталога `output/`. Каталог инструментов, вызов и правила допуска
собраны в `backend/services/mcp_tool_runner.py` (`MCPToolRunner`) и
`backend/domain/mcp_tool_call.py`; агент вызывает инструмент сам
(`Agent.apply_mcp_tool`) и дописывает результат системным блоком в промпт того же
запроса (для задач планировщика — блок «Данные планировщика»), а три инструмента
композиции агент вызывает не по одному, а одним пайплайном
(`Agent.apply_pipeline` — разбор в разделе [«Пайплайн»](#пайплайн)).

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
     "output_schema": {"properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "…": {}}, "type": "object"}},
    {"name": "collect_data",
     "description": "Периодически читает URL и накапливает ответы в базе дня. …",
     "input_schema": {"properties": {"source_url": {"type": "string"},
                                     "interval_seconds": {"type": "integer"},
                                     "name": {"type": "string"}},
                      "required": ["source_url", "interval_seconds", "name"], "type": "object"},
     "output_schema": {"properties": {"task_id": {"type": "integer"}, "records_saved": {"type": "integer"}, "…": {}}, "type": "object"}},
    {"name": "search",
     "description": "Ищет данные в источнике и возвращает найденные элементы. …",
     "input_schema": {"properties": {"query": {"type": "string"},
                                     "source": {"type": "string"},
                                     "limit": {"type": "integer"}},
                      "required": ["query"], "type": "object"},
     "output_schema": {"properties": {"query": {"type": "string"}, "source": {"type": "string"}, "source_kind": {"type": "string"}, "count": {"type": "integer"}, "items": {"type": "array"}}, "type": "object"}},
    {"name": "summarize",
     "description": "Собирает сводку по списку элементов и выделяет ключевые пункты. …",
     "input_schema": {"properties": {"items": {"type": "array"},
                                     "style": {"type": "string"},
                                     "max_length": {"type": "integer"}},
                      "required": ["items"], "type": "object"},
     "output_schema": {"properties": {"summary_text": {"type": "string"}, "key_points": {"type": "array"}, "total_items": {"type": "integer"}, "style_used": {"type": "string"}, "engine": {"type": "string"}}, "type": "object"}},
    {"name": "save_to_file",
     "description": "Сохраняет текст в файл каталога дня output/. …",
     "input_schema": {"properties": {"content": {"type": "string"},
                                     "filename": {"type": "string"},
                                     "format": {"type": "string"}},
                      "required": ["content"], "type": "object"},
     "output_schema": {"properties": {"filename": {"type": "string"}, "filepath": {"type": "string"}, "size_bytes": {"type": "integer"}, "format": {"type": "string"}, "saved_at": {"type": "string"}}, "type": "object"}}
  ],
  "count": 9,
  "target": "uv run python mcp_server/server.py",
  "transport": "stdio",
  "server_name": "day20-tools",
  "server_version": "1.3.0"
}
```

Каталог дня — девять инструментов: `get_user`, `get_post`, `list_user_posts`
(чтение jsonplaceholder), `schedule_reminder`, `collect_data`, `generate_summary`
(фоновые задачи) и `search`, `summarize`, `save_to_file` (композиция). Описания и
аргументы трёх планировщиков — в разделе
[«Планировщик»](#планировщик); их вызов возвращает `structuredContent` с полями,
разобранными в [«Формы планировщика»](#формы-планировщика). Три инструмента
композиции и их `output_schema` разобраны в разделе [«Пайплайн»](#пайплайн).

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
{ "detail": "Инструмент «nope» не найден в каталоге сервера. Доступны: get_user, get_post, list_user_posts, schedule_reminder, collect_data, generate_summary, search, summarize, save_to_file" }
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

Днём 20 этот путь отдаёт не каталог «известных целей для сравнения», а **состав
флота** `mcp_servers.json` и состояние подключений — это разобрано в разделе
[«MCP-серверы»](#mcp-серверы). Активное соединение описывает `GET /mcp/status`:
он показывает состояние одного клиента (FSM, сервер, ошибка), а флот — сколько
серверов зарегистрировано и какие из них подключены прямо сейчас.

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

`result` — вложенный объект домена `MCPToolResult`: `tool`, `arguments`,
`structured` (сам `structuredContent` ответа сервера), `text` (текстовые блоки),
`is_error`, `duration_ms`. Пустой `structured` (`null`) означает, что сервер не
объявил результат схемой и ответил только текстом.

## Планировщик

Фон живёт в процессе бэкенда: `backend/services/scheduler.py` (`TaskScheduler`)
держит `AsyncIOScheduler` из APScheduler, который поднимается в `lifespan`
(`backend/api/lifespan.py`) вместе с таблицами и восстановлением агентов, а при
остановке приложения встаёт **до** закрытия MCP-соединения. Источник правды о
задачах — таблица `scheduled_tasks`, а не память процесса: `sync_from_db` при
старте и затем каждые `SCHEDULER_SYNC_SECONDS = 5` секунд доводит набор job'ов до
базы (подхватывает задачи, созданные другим процессом через этот API, и убирает
удалённые), а в `next_run_at` записывается фактический `job.next_run_time`.
Поэтому задачи переживают перезапуск, а MCP-сервер ставит их, не открывая файл
базы.

Отсюда два решения, объясняющие устройство раздела:

- **тик — синхронная функция**: APScheduler 3.x в `AsyncIOExecutor` выполняет
  не-корутины в пуле потоков, поэтому фон не блокирует цикл событий FastAPI
  (сессии SQLite открыты с `check_same_thread=False`);
- **тик не ходит через MCP**: MCP-соединение принадлежит пользователю и держит
  блокировку клиента, поэтому вызов инструмента из фонового потока был бы
  дедлоком. Тик вызывает функции домена (`backend/services/scheduled_jobs.py`)
  напрямую, а MCP-инструмент — тонкая обёртка над `POST /scheduler/tasks`
  (`mcp_server/backend_api.py`).

Шесть таблиц планировщика: `scheduled_tasks` (задачи с расписанием и состоянием),
`task_runs` (журнал запусков), `reminders`, `notifications`, `collected_data` и
`periodic_summaries`. Последняя названа не `summaries`: так уже называется таблица
конспектов сжатия истории (день 9), и унаследованное имя не переименовывалось.

Что за инструменты — в таблице ниже; их аргументы с типами и границами отдаёт
`GET /scheduler/tools`:

| Инструмент | Аргументы (границы) | Расписание по инструменту | Немедленное действие |
|---|---|---|---|
| `schedule_reminder` | `text` (строка ≤ 500 символов), `delay_seconds` (1…86400) | разовое (`date`): `run_date = now + delay_seconds` | напоминание сохраняется в `reminders` |
| `collect_data` | `source_url` (http/https, ≤ 500), `interval_seconds` (1…86400), `name` | периодическое (`interval`): каждые `interval_seconds` | первый запрос к источнику и запись в `collected_data` |
| `generate_summary` | `name`, `interval_seconds` (1…86400) | периодическое (`interval`): каждые `interval_seconds` | первая сводка сразу за прошедший интервал |

Расписание можно переопределить полями `schedule_type`/`schedule_value` (например,
`cron` — `{"cron": "*/5 * * * *"}`, выражение из пяти полей); иначе оно выводится
из инструмента. Ошибка одного запуска не валит планировщик: запись в `task_runs`
получает `status: "error"`, пользователю уходит уведомление `kind: "error"`, а
задача остаётся `active` и повторит попытку. Пропущенный запуск «догоняется»:
если расчётный момент в прошлом, задача выполняется сразу при восстановлении
(`SCHEDULER_MISFIRE_GRACE = 60` секунд). Разовая задача после успешного запуска
переходит в `completed` и снимается с обслуживания.

Контракт ошибок раздела: `400` — незнакомый инструмент, негодные аргументы,
неразобранное расписание и неизвестный `status` в фильтре; `404` — нет задачи или
уведомления; `409` — пауза не активной задачи и возобновление не стоящей на паузе
(это конфликт состояний, а не ошибка запроса); `422` — тело не прошло схему
(`schedule_type` вне `date`/`interval`/`cron`, пустое или слишком длинное имя
инструмента/задачи). Состояния задачи и допустимые события — из FSM
`backend/domain/scheduler_fsm.py`: `active` → `paused` (пауза) или `completed`
(разовая задача выполнилась), `paused` → `active` (возобновление), из `completed`
событий нет, а напоминание проходит `scheduled` → `done` ровно один раз.

### GET /scheduler/tasks

Задачи планировщика по возрастанию номера: расписание и его подпись, инструмент с
аргументами, состояние, метки последнего и следующего запуска и `allowed_events` —
что с задачей можно сделать сейчас. Блок `scheduler` — состояние самого
планировщика процесса.

| Параметр | Тип | Описание |
|---|---|---|
| `status` | строка, необязательный | фильтр по состоянию: `active` \| `paused` \| `completed` |

```bash
curl.exe "http://127.0.0.1:8000/scheduler/tasks?status=active"
```

```json
{
  "tasks": [
    {"id": 1,
     "name": "Напоминание: проверить почту",
     "schedule_type": "date",
     "schedule_value": {"run_date": "2026-09-23T10:00:30+00:00"},
     "schedule_label": "разовый запуск 23.09 10:00:30 UTC",
     "tool_name": "schedule_reminder",
     "arguments": {"text": "проверить почту", "delay_seconds": 30, "reminder_id": 1},
     "status": "active",
     "last_run_at": "2026-09-23T10:00:00+00:00",
     "next_run_at": "2026-09-23T10:00:30+00:00",
     "created_at": "2026-09-23T10:00:00+00:00",
     "allowed_events": ["pause", "complete"]}
  ],
  "count": 1,
  "scheduler": {"running": true, "timezone": "UTC", "pending_jobs": 1, "sync_seconds": 5}
}
```

Неизвестный фильтр — `400` (иначе список молча был бы пустым):

```json
{ "detail": "Неизвестное состояние задачи «done»; допустимы: active, completed, paused" }
```

### POST /scheduler/tasks

Создаёт задачу: проверяет аргументы инструмента, выводит расписание (или берёт
переопределённое), пишет строку в `scheduled_tasks` и ставит задачу в планировщик.
При `run_now=true` (по умолчанию) **сразу** выполняет действие инструмента —
результат виден в `result`, подтверждение в `message`. Это общий код-путь: им
пользуются и MCP-инструменты планировщика, и человек в интерфейсе.

Тело — `SchedulerTaskIn`:

| Поле | Тип | Описание |
|---|---|---|
| `tool` | строка, 1…64 | инструмент из `GET /scheduler/tools`: `schedule_reminder` \| `collect_data` \| `generate_summary` |
| `arguments` | объект, по умолчанию `{}` | аргументы инструмента (их состав задаёт его описание) |
| `name` | строка, 1…100, необязательный | имя задачи; по умолчанию собирается из инструмента («Сбор: posts») |
| `run_now` | bool, по умолчанию `true` | выполнить немедленное действие инструмента |
| `schedule_type` | `date` \| `interval` \| `cron`, необязательный | переопределение расписания; иначе выводится из инструмента |
| `schedule_value` | объект, необязательный | `{"run_date": "…"}` \| `{"seconds": 10}` \| `{"cron": "*/5 * * * *"}` |

```bash
curl.exe -X POST http://127.0.0.1:8000/scheduler/tasks \
  -H "Content-Type: application/json" \
  -d "{\"tool\": \"collect_data\", \"arguments\": {\"source_url\": \"https://jsonplaceholder.typicode.com/posts\", \"interval_seconds\": 10, \"name\": \"posts\"}}"
```

```json
{
  "task": {
    "id": 3,
    "name": "Сбор: posts",
    "schedule_type": "interval",
    "schedule_value": {"seconds": 10},
    "schedule_label": "каждые 10 с",
    "tool_name": "collect_data",
    "arguments": {"source_url": "https://jsonplaceholder.typicode.com/posts",
                  "interval_seconds": 10, "name": "posts"},
    "status": "active",
    "last_run_at": "2026-09-23T10:00:00+00:00",
    "next_run_at": "2026-09-23T10:00:10+00:00",
    "created_at": "2026-09-23T10:00:00+00:00",
    "allowed_events": ["pause", "complete"]
  },
  "result": {
    "collection": {
      "name": "posts",
      "source_url": "https://jsonplaceholder.typicode.com/posts",
      "records_saved": 1,
      "records_in_payload": 100,
      "last_collected_at": "2026-09-23T10:00:00+00:00",
      "collected_id": 1
    }
  },
  "immediate": true,
  "message": "Сбор «posts» запущен: первая запись собрана. Задача №3: каждые 10 с",
  "error": null
}
```

Напоминание отличается только расписанием и результатом: `schedule_type: "date"`,
`schedule_value: {"run_date": "…"}`, номер напоминания дописывается в аргументы
задачи, чтобы тик знал, что помечать выполненным.

```json
{
  "task": {"id": 1, "name": "Напоминание: проверить почту", "schedule_type": "date",
           "schedule_value": {"run_date": "2026-09-23T10:00:30+00:00"},
           "schedule_label": "разовый запуск 23.09 10:00:30 UTC",
           "tool_name": "schedule_reminder",
           "arguments": {"text": "проверить почту", "delay_seconds": 30, "reminder_id": 1},
           "status": "active", "next_run_at": "2026-09-23T10:00:30+00:00",
           "allowed_events": ["pause", "complete"]},
  "result": {"reminder": {"id": 1, "text": "проверить почту",
                          "remind_at": "2026-09-23T10:00:30+00:00",
                          "status": "scheduled", "task_id": 1, "allowed_events": ["fire"]},
             "reminder_id": 1},
  "immediate": true,
  "message": "Напоминание запланировано на 23.09 10:00:30 UTC. Задача №1: разовый запуск 23.09 10:00:30 UTC",
  "error": null
}
```

Отказы `400` — это данные домена (`backend/domain/schedule_spec.py`), текст
подсказывает, что не так:

```json
{ "detail": "Инструмент «nope» не входит в планировщик дня. Доступны: schedule_reminder, collect_data, generate_summary" }
```

```json
{ "detail": "Аргумент «interval_seconds» инструмента «collect_data» должен быть целым числом от 1 до 86400, получено 0" }
```

```json
{ "detail": "Аргумент «source_url» должен быть адресом http:// или https://, получено «jsonplaceholder.typicode.com/posts»" }
```

```json
{ "detail": "Cron-выражение должно состоять из пяти полей (минуты часы день_месяца месяц день_недели), получено полей: 2" }
```

Неудача **немедленного** шага — не отказ запроса: задача уже зарегистрирована и
повторит попытку по расписанию, поэтому ответ остаётся `201`, а причина едет в
`error` и в `message` («Немедленный шаг не удался: …»), и уведомлением
`kind: "error"`. `422` приходит от Pydantic, если тело не по схеме (например,
`schedule_type: "every"`).

### DELETE /scheduler/tasks/{task_id}

Снимает задачу с обслуживания и удаляет её строку вместе с журналом запусков
(каскад по `task_runs`). Напоминания, сводки и уведомления остаются — у них ссылка
на задачу обнуляется (`ON DELETE SET NULL`), поэтому уже накопленные данные не
пропадают.

```bash
curl.exe -X DELETE http://127.0.0.1:8000/scheduler/tasks/3
```

```json
{"status": "deleted", "task_id": 3}
```

Нет такой задачи — `404`:

```json
{ "detail": "Задача планировщика 99 не найдена" }
```

### POST /scheduler/tasks/{task_id}/pause

`active` → `paused`: расписание сохраняется (в том числе фактический
`next_run_time`), запусков нет. Тело не нужно.

```bash
curl.exe -X POST http://127.0.0.1:8000/scheduler/tasks/3/pause -d "{}"
```

```json
{"id": 3, "name": "Сбор: posts", "schedule_type": "interval",
 "schedule_value": {"seconds": 10}, "schedule_label": "каждые 10 с",
 "tool_name": "collect_data",
 "arguments": {"source_url": "https://jsonplaceholder.typicode.com/posts",
               "interval_seconds": 10, "name": "posts"}, "status": "paused",
 "last_run_at": "2026-09-23T10:00:20+00:00", "next_run_at": "2026-09-23T10:00:30+00:00",
 "created_at": "2026-09-23T10:00:00+00:00", "allowed_events": ["resume"]}
```

Пауза не активной задачи — `409`; состояние при этом не меняется:

```json
{ "detail": "Событие 'pause' недопустимо в состоянии 'paused'; допустимы: resume" }
```

### POST /scheduler/tasks/{task_id}/resume

`paused` → `active` и постановка в планировщик заново — этим пользуются и после
перезапуска приложения, когда пауза пережила остановку процесса (job'а в памяти
уже нет).

```bash
curl.exe -X POST http://127.0.0.1:8000/scheduler/tasks/3/resume -d "{}"
```

```json
{"id": 3, "name": "Сбор: posts", "schedule_type": "interval",
 "schedule_value": {"seconds": 10}, "schedule_label": "каждые 10 с",
 "tool_name": "collect_data",
 "arguments": {"source_url": "https://jsonplaceholder.typicode.com/posts",
               "interval_seconds": 10, "name": "posts"}, "status": "active",
 "last_run_at": "2026-09-23T10:00:20+00:00", "next_run_at": "2026-09-23T10:00:40+00:00",
 "created_at": "2026-09-23T10:00:00+00:00", "allowed_events": ["pause", "complete"]}
```

Возобновление не стоящей на паузе задачи — `409`:

```json
{ "detail": "Событие 'resume' недопустимо в состоянии 'active'; допустимы: pause, complete" }
```

### POST /scheduler/tasks/{task_id}/run

Выполняет **тот же** тик, что и запуск по таймеру (одна точка исполнения —
`TaskScheduler.run_tick`), поэтому запись попадает в журнал запусков. Разовая
задача после успешного запуска переходит в `completed` и снимается; уже
выполненная задача — `409`.

```bash
curl.exe -X POST http://127.0.0.1:8000/scheduler/tasks/3/run -d "{}"
```

```json
{
  "id": 4,
  "task_id": 3,
  "phase": "tick",
  "status": "ok",
  "started_at": "2026-09-23T10:00:20+00:00",
  "finished_at": "2026-09-23T10:00:20+00:00",
  "duration_ms": 187,
  "detail": {"collection": {"name": "posts", "source_url": "https://jsonplaceholder.typicode.com/posts",
                            "records_saved": 1, "records_in_payload": 100,
                            "last_collected_at": "2026-09-23T10:00:20+00:00", "collected_id": 2}},
  "error": null
}
```

```json
{ "detail": "Задача 1 уже выполнена и повторно не запускается" }
```

### GET /scheduler/tasks/{task_id}/history

Задача и её запуски по убыванию времени: `phase` — `prepare` (немедленное действие
при регистрации) или `tick` (запуск по расписанию), `status` — `ok` или `error`,
`detail` — что сделал инструмент, `error` — текст сбоя.

| Параметр | Тип | Описание |
|---|---|---|
| `limit` | int, по умолчанию 50 | сколько запусков вернуть (`SCHEDULER_RUNS_LIMIT`) |

```bash
curl.exe "http://127.0.0.1:8000/scheduler/tasks/3/history?limit=10"
```

```json
{
  "task": {"id": 3, "name": "Сбор: posts", "schedule_label": "каждые 10 с",
           "tool_name": "collect_data", "status": "active", "allowed_events": ["pause", "complete"]},
  "runs": [
    {"id": 4, "task_id": 3, "phase": "tick", "status": "ok",
     "started_at": "2026-09-23T10:00:20+00:00", "finished_at": "2026-09-23T10:00:20+00:00",
     "duration_ms": 187, "detail": {"collection": {"records_saved": 1}}, "error": null},
    {"id": 1, "task_id": 3, "phase": "prepare", "status": "ok",
     "started_at": "2026-09-23T10:00:00+00:00", "finished_at": "2026-09-23T10:00:00+00:00",
     "duration_ms": 512, "detail": {"collection": {"records_saved": 1}}, "error": null}
  ],
  "count": 2
}
```

Сбой сбора тоже виден здесь (и уведомлением `kind: "error"`), а задача остаётся
активной:

```json
{"id": 7, "task_id": 3, "phase": "tick", "status": "error",
 "started_at": "2026-09-23T10:05:10+00:00", "finished_at": "2026-09-23T10:05:21+00:00",
 "duration_ms": 10012, "detail": null,
 "error": "Источник https://jsonplaceholder.typicode.com/posts недоступен: таймаут 10 с"}
```

Нет задачи — `404` (как у всех эндпоинтов с `task_id`).

### GET /scheduler/tools

Каталог трёх инструментов дня: подпись для интерфейса, назначение, подсказка о
расписании и аргументы в объявленном порядке — с типом, признаком обязательности и
границами. По этому ответу строится форма в интерфейсе, и им же проверяются
аргументы вызова.

```bash
curl.exe http://127.0.0.1:8000/scheduler/tools
```

```json
{
  "tools": [
    {"name": "schedule_reminder",
     "label": "⏰ Напоминание",
     "description": "Разовое напоминание: сохраняется в таблицу reminders, а задача через delay_seconds секунд помечает его выполненным и кладёт уведомление в очередь.",
     "schedule_help": "разовый запуск через delay_seconds секунд",
     "arguments": [
       {"name": "text", "type": "string", "required": true,
        "description": "текст напоминания (до 500 символов)"},
       {"name": "delay_seconds", "type": "integer", "required": true,
        "description": "через сколько секунд напомнить", "minimum": 1, "maximum": 86400}
     ]},
    {"name": "collect_data", "label": "📥 Периодический сбор данных",
     "description": "Читает JSON по адресу и накапливает ответы в таблице collected_data: первый запрос выполняется сразу, дальше — каждые interval_seconds.",
     "schedule_help": "первый запрос сразу, дальше каждые interval_seconds секунд",
     "arguments": [
       {"name": "source_url", "type": "string", "required": true,
        "description": "адрес HTTP/HTTPS, откуда читать JSON (до 500 символов)"},
       {"name": "interval_seconds", "type": "integer", "required": true,
        "description": "период сбора в секундах", "minimum": 1, "maximum": 86400},
       {"name": "name", "type": "string", "required": true,
        "description": "имя сбора (по нему записи попадают в collected_data и в сводку)"}
     ]},
    {"name": "generate_summary", "label": "📊 Регулярная сводка",
     "description": "Агрегирует накопленные записи за период в сводку (periodic_summaries): первая сводка считается сразу за прошедший интервал, дальше — каждые interval_seconds.",
     "schedule_help": "первая сводка сразу за прошедший интервал, дальше каждые interval_seconds секунд",
     "arguments": [
       {"name": "name", "type": "string", "required": true,
        "description": "имя сводки (по нему отбираются записи collected_data)"},
       {"name": "interval_seconds", "type": "integer", "required": true,
        "description": "и период агрегации, и период повтора, в секундах",
        "minimum": 1, "maximum": 86400}
     ]}
  ],
  "count": 3
}
```

### GET /scheduler/status

Состояние планировщика процесса: идёт ли обслуживание таймеров (`running`),
часовой пояс расписаний (в дне — UTC, поэтому в БД лежат времена без сдвигов),
сколько задач поставлено в APScheduler (`pending_jobs`) и как часто таблица задач
сверяется с планировщиком (`sync_seconds`).

```bash
curl.exe http://127.0.0.1:8000/scheduler/status
```

```json
{"running": true, "timezone": "UTC", "pending_jobs": 2, "sync_seconds": 5}
```

### GET /scheduler/reminders

Напоминания по возрастанию момента выдачи: текст, когда напомнить, состояние
(`scheduled` — ждёт выдачи, `done` — выдано) и номер задачи, которая его выдаст.

| Параметр | Тип | Описание |
|---|---|---|
| `status` | строка, необязательный | фильтр: `scheduled` \| `done` |
| `limit` | int, по умолчанию 100 | сколько записей вернуть (`SCHEDULER_LIST_LIMIT`) |

```bash
curl.exe "http://127.0.0.1:8000/scheduler/reminders?status=done"
```

```json
{
  "reminders": [
    {"id": 1, "text": "проверить почту", "remind_at": "2026-09-23T10:00:30+00:00",
     "status": "done", "created_at": "2026-09-23T10:00:00+00:00", "task_id": 1,
     "allowed_events": []}
  ],
  "count": 1
}
```

Неизвестный фильтр — `400`: `{"detail": "Неизвестное состояние напоминания «new»; допустимы: done, scheduled"}`.

### GET /scheduler/collected

Записи таблицы `collected_data` по возрастанию времени (свежие — последними): что
вернул источник при каждом сборе. `payload` — ответ источника как есть, поэтому
именно он попадает в агрегацию сводки. `total` показывает общее число записей с
тем же фильтром (а не число записей в ответе).

| Параметр | Тип | Описание |
|---|---|---|
| `name` | строка, необязательный | фильтр по имени сбора (`"posts"`) |
| `limit` | int, по умолчанию 100 | сколько записей вернуть |

```bash
curl.exe "http://127.0.0.1:8000/scheduler/collected?name=posts"
```

```json
{
  "records": [
    {"id": 1, "name": "posts",
     "source_url": "https://jsonplaceholder.typicode.com/posts",
     "payload": [{"userId": 1, "id": 1, "title": "sunt aut facere…", "body": "quia et suscipit…"}],
     "collected_at": "2026-09-23T10:00:00+00:00"}
  ],
  "count": 1,
  "total": 3,
  "name": "posts"
}
```

### GET /scheduler/summaries

Сводки инструмента `generate_summary` (свежие — первыми): текст, период
(`period_start`…`period_end`), число записей за период и ключевые метрики —
`numeric` для числовых полей со статистикой `count`/`avg`/`min`/`max`,
`categorical` для строковых со числом уникальных значений и примерами,
`sources` — сколько записей дал каждый сбор, `payload_types` — формы ответов.

| Параметр | Тип | Описание |
|---|---|---|
| `name` | строка, необязательный | фильтр по имени сводки |
| `limit` | int, по умолчанию 100 | сколько сводок вернуть |

```bash
curl.exe "http://127.0.0.1:8000/scheduler/summaries?name=posts"
```

```json
{
  "summaries": [
    {"id": 2, "name": "posts",
     "content": "Сводка «posts» за период 2026-09-23 10:00:20 — 10:00:40 (20 с).\nЗаписей собрано: 2 (источники: posts — 2).\nЧисловые поля: userId — 2 значений, среднее 1.5, мин 1, макс 2; id — 2 значений, среднее 1.5, мин 1, макс 2.\nКатегориальные поля: title — 2 уникальных (например: «sunt aut facere…», «qui est esse…»); body — 2 уникальных.",
     "period_start": "2026-09-23T10:00:20+00:00",
     "period_end": "2026-09-23T10:00:40+00:00",
     "total_records": 2,
     "key_metrics": {
       "period_seconds": 20,
       "sources": {"posts": 2},
       "numeric": {"userId": {"count": 2, "avg": 1.5, "min": 1, "max": 2},
                   "id": {"count": 2, "avg": 1.5, "min": 1, "max": 2}},
       "categorical": {"title": {"unique": 2, "samples": ["sunt aut facere…", "qui est esse…"]},
                       "body": {"unique": 2, "samples": ["quia et suscipit…"]}},
       "payload_types": {"list": 2, "dict": 0, "scalar": 0}
     },
     "task_id": 3,
     "created_at": "2026-09-23T10:00:40+00:00"}
  ],
  "count": 1
}
```

Пустой период — тоже сводка (тик состоялся): `total_records: 0`, текст
«За период записей не собрано.», а `numeric` и `categorical` пустые. Отличить
«данных не было» от «сбор не настроен» помогает именно эта запись.

### GET /scheduler/notifications

Очередь уведомлений (свежие — первыми): напоминание сработало (`kind:
"reminder"`), сводка готова (`"summary"`), тик завершился ошибкой (`"error"`).
Уведомления durable — их видно и после перезапуска страницы, а `read_at`
показывает, когда уведомление отметили прочитанным.

| Параметр | Тип | Описание |
|---|---|---|
| `unread_only` | bool, по умолчанию `false` | только непрочитанные |
| `limit` | int, по умолчанию 100 | сколько уведомлений вернуть |

```bash
curl.exe "http://127.0.0.1:8000/scheduler/notifications?unread_only=true"
```

```json
{
  "notifications": [
    {"id": 1, "kind": "reminder", "text": "Напоминание: проверить почту", "task_id": 1,
     "payload": {"reminder_id": 1}, "created_at": "2026-09-23T10:00:30+00:00",
     "read_at": null, "unread": true}
  ],
  "count": 1,
  "unread": 1
}
```

### POST /scheduler/notifications/{notification_id}/read

Ставит отметку `read_at` и возвращает уведомление. Повторная отметка — безопасный
no-op (время не сдвигается), поэтому кнопку можно нажимать дважды.

```bash
curl.exe -X POST http://127.0.0.1:8000/scheduler/notifications/1/read -d "{}"
```

```json
{"id": 1, "kind": "reminder", "text": "Напоминание: проверить почту", "task_id": 1,
 "payload": {"reminder_id": 1}, "created_at": "2026-09-23T10:00:30+00:00",
 "read_at": "2026-09-23T10:01:00+00:00", "unread": false}
```

Неизвестное уведомление — `404`:

```json
{ "detail": "Уведомление 99 не найдено" }
```

### Формы планировщика

| Схема | Поля |
|---|---|
| `SchedulerTaskIn` | `tool` (1…64), `arguments` (объект), `name` (1…100, необязательный), `run_now` (bool), `schedule_type` (`date`/`interval`/`cron`, необязательный), `schedule_value` (объект, необязательный) |
| `SchedulerTaskCreateOut` | `task` ([ScheduledTaskOut]), `result` (результат немедленного действия или `null`), `immediate` (bool), `message`, `error` (причина неудачи немедленного шага) |
| `ScheduledTaskOut` | `id`, `name`, `schedule_type`, `schedule_value`, `schedule_label`, `tool_name`, `arguments`, `status`, `last_run_at`, `next_run_at`, `created_at`, `allowed_events` |
| `SchedulerRunOut` | `id`, `task_id`, `phase` (`prepare`/`tick`), `status` (`ok`/`error`), `started_at`, `finished_at`, `duration_ms`, `detail`, `error` |
| `SchedulerTaskCreateOut.result` | у напоминания `{reminder, reminder_id}`, у сбора `{collection}`, у сводки `{summary, aggregate}` |
| `ReminderOut` | `id`, `text`, `remind_at`, `status` (`scheduled`/`done`), `created_at`, `task_id`, `allowed_events` |
| `CollectedRecordOut` | `id`, `name`, `source_url`, `payload` (ответ источника как есть), `collected_at` |
| `PeriodicSummaryOut` | `id`, `name`, `content` (текст сводки), `period_start`, `period_end`, `total_records`, `key_metrics`, `task_id`, `created_at` |
| `NotificationOut` | `id`, `kind` (`reminder`/`summary`/`error`), `text`, `task_id`, `payload`, `created_at`, `read_at`, `unread` |
| `SchedulerStatusOut` | `running`, `timezone`, `pending_jobs`, `sync_seconds` |
| `SchedulerToolSchema` | `name`, `label`, `description`, `schedule_help`, `arguments` ([SchedulerToolArgument]) |
| `SchedulerToolArgument` | `name`, `type` (`string`/`integer`), `required`, `description`, `minimum`, `maximum` |
| `SchedulerToolsResponse` | `tools` ([SchedulerToolSchema]), `count` |
| `SchedulerTasksResponse` | `tasks` ([ScheduledTaskOut]), `count`, `scheduler` ([SchedulerStatusOut]) |
| `SchedulerRunsResponse` | `task` ([ScheduledTaskOut]), `runs` ([SchedulerRunOut]), `count` |
| `RemindersResponse` | `reminders` ([ReminderOut]), `count` |
| `CollectedResponse` | `records` ([CollectedRecordOut]), `count`, `total`, `name` |
| `SummariesResponse` | `summaries` ([PeriodicSummaryOut]), `count` |
| `NotificationsResponse` | `notifications` ([NotificationOut]), `count`, `unread` |
| `ScheduleReportOut` | `registered`, `tool`, `task` ([ScheduledTaskOut]), `summary`, `message`; это тип поля `schedule` ответа генерации |

Ответы MCP-инструментов планировщика приходят в `result.structured` вызова
`POST /mcp/call`: `schedule_reminder` → `ReminderScheduled` (`task_id`,
`reminder_id`, `text`, `remind_at`, `status`, `next_run_at`, `message`),
`collect_data` → `CollectionStarted` (`task_id`, `name`, `source_url`,
`interval_seconds`, `next_run_at`, `records_saved`, `message`), `generate_summary` →
`SummaryReady` (`task_id`, `summary_id`, `name`, `period_start`, `period_end`,
`total_records`, `summary_text`, `key_metrics`, `next_run_at`, `message`) — это те же
данные API дня, собранные в структуру ответа инструмента (`mcp_server/schemas.py`).

## Пайплайн

Пайплайн — это **данные**, а не код: список шагов, у каждого имя
MCP-инструмента, аргументы со ссылками на результаты предыдущих шагов и
необязательное условие перехода (`backend/domain/pipeline_spec.py`,
`DEFAULT_PIPELINE`). Прогон (`backend/services/pipeline.py`) читает эту структуру и
выполняет шаги по порядку, поэтому «что делает пайплайн» видно в одном словаре: его
можно прислать телом запроса, показать в интерфейсе и положить в отчёт. Встроенный
пайплайн `search-summarize-save` состоит из трёх инструментов композиции — их
публикует свой MCP-сервер дня (см. [«MCP»](#mcp)):

| Инструмент | Аргументы (границы) | Что возвращает (`structuredContent`) |
|---|---|---|
| `search` | `query` (строка ≤ 200; пустая — всё), `source` (строка ≤ 200), `limit` (1…20, по умолчанию 5) | `query`, `source`, `source_kind` (`api`/`file`/`sqlite`), `count`, `items` (`id`, `title`, `content`, `url`, `metadata`) |
| `summarize` | `items` (список; берутся первые 200 элементов), `style` (`short`/`detailed`/`bullets`, по умолчанию `short`), `max_length` (50…4000, по умолчанию 600) | `summary_text`, `key_points`, `total_items`, `style_used`, `engine` (`llm`/`aggregation`) |
| `save_to_file` | `content` (строка ≤ 20000), `filename` (имя без пути, по умолчанию `pipeline_result.md`), `format` (`txt`/`md`/`json`, по умолчанию `md`) | `filename`, `filepath` (абсолютный путь), `size_bytes`, `format`, `saved_at` |

Источник `search` задаётся строкой одного из трёх видов: `posts` / `users` (лента
`jsonplaceholder.typicode.com`, фильтр — подстрока по текстовым полям), `file:<путь>`
(файл **внутри** папки дня: относительный путь, разбиение на блоки по пустым
строкам, фильтр — подстрока в блоке) и `sqlite:<таблица>` (таблица дня, открытая
**только на чтение**: белый список — `collected_data`, `periodic_summaries`,
`pipeline_steps`). `summarize` зовёт DeepSeek внутри процесса MCP-сервера, а без
ключа и с `--llm off` собирает сводку агрегацией (`engine: "aggregation"`), поэтому
шаг не падает из-за отсутствия ключа. `save_to_file` пишет **только** в каталог
`day20/output/`: имя чистится (путь и `..` запрещены), а расширение заменяется на
запрошенный формат.

Встроенный пайплайн целиком — вот эта декларация (`{name}` — аргумент запуска,
`$steps.<i>.<путь>` — поле выхода шага `i`):

```json
{
  "name": "search-summarize-save",
  "steps": [
    {"tool": "search",
     "args": {"query": "{query}", "source": "{source}", "limit": "{limit}"}},
    {"tool": "summarize",
     "guard": {"path": "$steps.0.structured.items", "op": "non_empty",
               "message": "нет данных для обработки"},
     "args": {"items": "$steps.0.structured.items", "style": "{style}",
              "max_length": "{max_length}"}},
    {"tool": "save_to_file",
     "args": {"content": "$steps.1.structured.summary_text",
              "filename": "{filename}", "format": "{format}"}}
  ]
}
```

Правила маппинга аргументов (`backend/domain/pipeline_mapping.py`):

1. строка РОВНО вида `$steps.<i>.<путь>` → значение по пути как есть (список
   остаётся списком: `items` второго шага — настоящий массив, а не JSON-строка);
2. иначе каждая подстрока `$steps....` внутри строки заменяется строковым
   представлением значения, затем подставляются заглушки;
3. `{имя}` ровно целиком занимает строку → значение аргумента запуска как есть
   (число остаётся числом);
4. иначе `{имя}` подставляются через `str(value)`;
5. не строка — как есть (словари и списки обходятся рекурсивно).

Путь — `$steps.` + номер шага (целое) + необязательные сегменты через точку;
числовой сегмент читается как индекс списка, иначе как ключ словаря. Отсутствующий
путь или незаполненная заглушка — явная ошибка шага (`failed`), а не тихая пустая
строка: иначе инструменту ушёл бы мусор вместо данных.

Условие шага (`guard`) — путь плюс один из четырёх операторов: `non_empty`
(непустой список/словарь/строка), `empty` (отрицание), `equals` (точное равенство,
нужен ключ `value`), `contains` (вхождение в строку или элемент списка). Условие,
которое **не** выполнилось, не делает прогон ошибкой: пайплайн завершается досрочно
со статусом `stopped` и сообщением условия (у встроенного пайплайна это «нет данных
для обработки»), поэтому шаг с невыполненным условием виден в журнале со статусом
`stopped` и текстом условия.

Каждый прогон — один автомат (`backend/domain/pipeline_fsm.py`), а значения его
состояний — это ровно те статусы, что лежат в колонке `pipeline_runs.status` и
уходят в API: `idle`, `running`, `completed`, `stopped`, `failed` (маппинг не нужен).

| Состояние | Событие → новое состояние | Когда |
|---|---|---|
| `idle` | `start` → `running` | прогон начат |
| `running` | `advance` → `running` | шаг выполнен, остались следующие |
| `running` | `finish` → `completed` | последний шаг выполнен |
| `running` | `stop` → `stopped` | условие шага не выполнено |
| `running` | `fail` → `failed` | шаг завершился ошибкой |
| `completed` / `stopped` / `failed` | `start` → `running` | следующий прогон (терминальные состояния) |

Порядок одного шага прогона: **маппинг аргументов → условие перехода → вызов
инструмента → строка журнала → событие FSM**. Строка журнала пишется ВСЕГДА —
включая шаги, которые упали на маппинге или были остановлены условием, иначе
причина остановки не доехала бы до истории и отчёта. `output_result` шага — единая
форма для всех инструментов: `{"reason_code", "structured", "text", "is_error",
"duration_ms"}`; она одинакова у успеха и неудачи, поэтому пути маппинга
(`$steps.<i>.structured.<поле>`) определены всегда. Прогон останавливается на первом
шаге со статусом не `ok`: ошибка шага — это конец пайплайна, а не «продолжим с
мусором». Коды причин отказа шага (`reason_code`) — те же, что у одиночного вызова
(день 17): `not_connected`, `unknown_tool`, `bad_arguments`, `transport`,
`tool_error`; текст причины лежит в `error_message` и `error` отчёта.

Журнал прогона лежит в SQLite в двух таблицах: `pipeline_runs` (запуск: имя
конфигурации, статус, метки времени, общая длительность) и `pipeline_steps` (шаг:
номер, инструмент, разрешённые аргументы вызова, результат, время, статус, текст
ошибки), связанные внешним ключом с каскадным удалением. Фоновый прогон идёт в
отдельном потоке (`threading.Thread`, daemon): запрос обязан вернуться сразу, а
интерфейс — опрашивать статус из БД (`@st.fragment(run_every="1s")` в разделе
«🔀 Пайплайны»). Строка запуска создаётся **до** старта потока, поэтому состояние
`running` видно с первого же опроса, а исключение в потоке не роняет процесс
бэкенда: прогон получает терминальный статус `failed` и запись в лог.

Контракт ошибок раздела: `400` — негодная конфигурация (не тот тип, пустые шаги,
шагов больше `PIPELINE_STEPS_MAX = 10`, неизвестное условие) и неизвестный `status`
в фильтре; `404` — несуществующий запуск; `422` — тело не прошло схему (Pydantic).
Отказ приходит из домена данными (`PipelineRejected.reason_code`) и переводится в
код в роутере `backend/api/pipelines.py`.

### POST /pipelines/run

Запускает декларативный пайплайн. Тело — `PipelineRunIn`:

| Поле | Тип | Описание |
|---|---|---|
| `pipeline` | объект/null | декларативная конфигурация (`name`, `steps`: `tool`, `args`, `guard`); без него выполняется встроенный `search-summarize-save` |
| `initial_args` | объект | аргументы запуска: `query`, `source`, `limit`, `style`, `max_length`, `filename`, `format` |
| `background` | bool | `true` (по умолчанию) — прогон в фоновом потоке, ответ сразу со статусом `running`; `false` — синхронно, с шагами в ответе |

Синхронный запуск (`background: false`) — весь отчёт сразу:

```bash
curl.exe -X POST http://127.0.0.1:8000/pipelines/run \
  -H "Content-Type: application/json" \
  -d "{\"initial_args\":{\"query\":\"RAG\",\"source\":\"file:mcp_server/data/notes.md\",\"limit\":5,\"style\":\"short\",\"max_length\":600,\"filename\":\"api-run.md\",\"format\":\"md\"},\"background\":false}"
```

```json
{
  "run_id": 4,
  "pipeline_name": "search-summarize-save",
  "status": "completed",
  "steps": [
    {"id": 8, "run_id": 4, "step_index": 0, "tool_name": "search",
     "input_args": {"query": "RAG", "source": "file:mcp_server/data/notes.md", "limit": 5},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 94,
                       "structured": {"query": "RAG", "source": "file:mcp_server/data/notes.md",
                                      "source_kind": "file", "count": 5, "items": ["…"]},
                       "text": "…"},
     "duration_ms": 94, "status": "ok", "error_message": null},
    {"id": 9, "run_id": 4, "step_index": 1, "tool_name": "summarize",
     "input_args": {"items": ["…"], "style": "short", "max_length": 600},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 7,
                       "structured": {"summary_text": "Найдено 5 элементов. Первые: …",
                                      "key_points": ["…"], "total_items": 5,
                                      "style_used": "short", "engine": "aggregation"},
                       "text": "…"},
     "duration_ms": 7, "status": "ok", "error_message": null},
    {"id": 10, "run_id": 4, "step_index": 2, "tool_name": "save_to_file",
     "input_args": {"content": "Найдено 5 элементов. …", "filename": "api-run.md", "format": "md"},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 7,
                       "structured": {"filename": "api-run.md",
                                      "filepath": "…/day20/output/api-run.md",
                                      "size_bytes": 266, "format": "md",
                                      "saved_at": "2026-09-24T16:04:20+00:00"},
                       "text": "…"},
     "duration_ms": 7, "status": "ok", "error_message": null}
  ],
  "count": 3,
  "failed_at_step": null,
  "message": "пайплайн выполнен",
  "error": null,
  "total_duration_ms": 256,
  "background": false
}
```

Фоновый запуск (`background: true`, он же — по умолчанию) отвечает сразу, шагов в
ответе нет, а прогресс читается через `GET /pipelines/runs/{run_id}`:

```bash
curl.exe -X POST http://127.0.0.1:8000/pipelines/run \
  -H "Content-Type: application/json" \
  -d "{\"initial_args\":{\"query\":\"RAG\",\"source\":\"file:mcp_server/data/notes.md\",\"filename\":\"api-run.md\"}}"
```

```json
{
  "run_id": 5,
  "pipeline_name": "search-summarize-save",
  "status": "running",
  "steps": [],
  "count": 0,
  "failed_at_step": null,
  "message": "пайплайн выполняется",
  "error": null,
  "total_duration_ms": 0,
  "background": true
}
```

Коды ответа:

| Код | Когда | Тело |
|---|---|---|
| `200` | прогон запущен (синхронно завершён или ушёл в фон) | `PipelineStartOut` |
| `400` | конфигурация негодная: не объект, пустой список `steps`, шагов больше 10, шаг без `tool`, неизвестный `op` условия | `detail` — причина и что сделать |
| `422` | тело не прошло схему (Pydantic) | стандартная ошибка FastAPI |

Отказ домена — `400` с понятным текстом:

```json
{ "detail": "У пайплайна должен быть непустой список шагов «steps»" }
```

```json
{ "detail": "Условие «exotic_op» не поддержано. Допустимы: non_empty, empty, equals, contains" }
```

### GET /pipelines/runs

История запусков от свежих к старым: номер, имя конфигурации, статус, метки
времени и общую длительность.

| Параметр | Тип | Описание |
|---|---|---|
| `status` | строка | фильтр по статусу: `running` / `completed` / `stopped` / `failed` (неизвестный — 400) |
| `limit` | int | сколько записей вернуть (по умолчанию `PIPELINE_RUNS_LIMIT = 50`) |

```bash
curl.exe "http://127.0.0.1:8000/pipelines/runs?limit=5"
```

```json
{
  "runs": [
    {"id": 5, "pipeline_name": "search-summarize-save", "status": "running",
     "started_at": "2026-09-24T16:10:02+00:00", "finished_at": null, "total_duration_ms": 0},
    {"id": 4, "pipeline_name": "search-summarize-save", "status": "completed",
     "started_at": "2026-09-24T16:04:20+00:00", "finished_at": "2026-09-24T16:04:20+00:00",
     "total_duration_ms": 256}
  ],
  "count": 2
}
```

Неизвестный статус в фильтре — `400` с перечнем допустимых:

```json
{ "detail": "Неизвестный статус запуска «done»; допустимы: completed, failed, idle, running, stopped" }
```

Коды: `200`, `400`, `422` (нечисловой `limit`).

### GET /pipelines/runs/{run_id}

Отчёт о запуске — строка запуска, его шаги по порядку и итог. `message` объясняет
результат: «пайплайн выполнен», сообщение условия при досрочной остановке
(«нет данных для обработки») или «пайплайн остановлен: шаг завершился ошибкой».
`failed_at_step` и `error` заполняются, только когда прогон остановил **сбой** шага.

```bash
curl.exe http://127.0.0.1:8000/pipelines/runs/4
```

```json
{
  "run": {"id": 4, "pipeline_name": "search-summarize-save", "status": "completed",
          "started_at": "2026-09-24T16:04:20+00:00",
          "finished_at": "2026-09-24T16:04:20+00:00", "total_duration_ms": 256},
  "steps": [
    {"id": 8, "run_id": 4, "step_index": 0, "tool_name": "search",
     "input_args": {"query": "RAG", "source": "file:mcp_server/data/notes.md", "limit": 5},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 94,
                       "structured": {"count": 5, "source_kind": "file", "…": "…"},
                       "text": "…"},
     "duration_ms": 94, "status": "ok", "error_message": null},
    {"id": 9, "run_id": 4, "step_index": 1, "tool_name": "summarize",
     "input_args": {"items": ["…"], "style": "short", "max_length": 600},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 7,
                       "structured": {"summary_text": "Найдено 5 элементов. …",
                                      "key_points": ["…"], "total_items": 5,
                                      "style_used": "short", "engine": "aggregation"},
                       "text": "…"},
     "duration_ms": 7, "status": "ok", "error_message": null},
    {"id": 10, "run_id": 4, "step_index": 2, "tool_name": "save_to_file",
     "input_args": {"content": "Найдено 5 элементов. …", "filename": "api-run.md", "format": "md"},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 7,
                       "structured": {"filename": "api-run.md", "size_bytes": 266,
                                      "format": "md", "filepath": "…/output/api-run.md",
                                      "saved_at": "2026-09-24T16:04:20+00:00"},
                       "text": "…"},
     "duration_ms": 7, "status": "ok", "error_message": null}
  ],
  "count": 3,
  "failed_at_step": null,
  "message": "пайплайн выполнен",
  "error": null
}
```

Досрочно завершённый прогон (в заметках нет «квантовых вычислений»): в журнале
два шага, причём остановленный шаг — `stopped` с сообщением условия, а
`failed_at_step` пуст, потому что это не сбой:

```json
{
  "run": {"id": 6, "pipeline_name": "search-summarize-save", "status": "stopped",
          "started_at": "2026-09-24T16:11:00+00:00",
          "finished_at": "2026-09-24T16:11:00+00:00", "total_duration_ms": 42},
  "steps": [
    {"id": 11, "run_id": 6, "step_index": 0, "tool_name": "search",
     "input_args": {"query": "квантовые вычисления", "source": "file:mcp_server/data/notes.md", "limit": 5},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 42,
                       "structured": {"count": 0, "items": [], "…": "…"}, "text": "…"},
     "duration_ms": 42, "status": "ok", "error_message": null},
    {"id": 12, "run_id": 6, "step_index": 1, "tool_name": "summarize",
     "input_args": null, "output_result": null, "duration_ms": 0,
     "status": "stopped", "error_message": "нет данных для обработки"}
  ],
  "count": 2,
  "failed_at_step": null,
  "message": "нет данных для обработки",
  "error": null
}
```

Запуск со сбоем шага: `status: "failed"`, `failed_at_step: 1`, `error` — причина.
Третий шаг не запускался — ошибка любого шага останавливает пайплайн.

```json
{
  "run": {"id": 7, "pipeline_name": "search-summarize-save", "status": "failed",
          "started_at": "2026-09-24T16:12:00+00:00",
          "finished_at": "2026-09-24T16:12:00+00:00", "total_duration_ms": 51},
  "steps": [
    {"id": 13, "run_id": 7, "step_index": 0, "tool_name": "search",
     "input_args": {"query": "RAG", "source": "file:mcp_server/data/notes.md", "limit": 5},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 6,
                       "structured": {"count": 5, "…": "…"}, "text": "…"},
     "duration_ms": 6, "status": "ok", "error_message": null},
    {"id": 14, "run_id": 7, "step_index": 1, "tool_name": "summarize",
     "input_args": {"items": "RAG", "style": "short", "max_length": 600},
     "output_result": {"reason_code": "bad_arguments", "structured": null,
                       "text": "", "is_error": true},
     "duration_ms": 0, "status": "failed",
     "error_message": "Не указан обязательный аргумент «items» …"}
  ],
  "count": 2,
  "failed_at_step": 1,
  "message": "пайплайн остановлен: шаг завершился ошибкой",
  "error": "Не указан обязательный аргумент «items» …"
}
```

Коды: `200`, `404` (несуществующий запуск), `422` (нечисловой `run_id`).

```json
{ "detail": "Запуск пайплайна 99 не найден" }
```

### GET /pipelines/runs/{run_id}/steps

Только шаги одного запуска — тем же порядком, что в отчёте. Этим ответом
пользуется раздел «🔀 Пайплайны» для прогресса по шагам.

```bash
curl.exe http://127.0.0.1:8000/pipelines/runs/4/steps
```

```json
{
  "run_id": 4,
  "steps": [
    {"id": 8, "run_id": 4, "step_index": 0, "tool_name": "search",
     "input_args": {"query": "RAG", "source": "file:mcp_server/data/notes.md", "limit": 5},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 94,
                       "structured": {"count": 5, "…": "…"}, "text": "…"},
     "duration_ms": 94, "status": "ok", "error_message": null},
    {"id": 9, "run_id": 4, "step_index": 1, "tool_name": "summarize",
     "input_args": {"items": ["…"], "style": "short", "max_length": 600},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 7,
                       "structured": {"summary_text": "…", "engine": "aggregation", "…": "…"},
                       "text": "…"},
     "duration_ms": 7, "status": "ok", "error_message": null}
  ],
  "count": 2
}
```

Коды: `200`, `404`, `422` (нечисловой `run_id`).

### DELETE /pipelines/runs/{run_id}

Удаляет запуск вместе с его шагами (каскад) — история шагов без запуска смысла не
имеет.

```bash
curl.exe -X DELETE http://127.0.0.1:8000/pipelines/runs/5
```

```json
{ "status": "deleted", "run_id": 5 }
```

Коды: `200`, `404` (несуществующий запуск), `422` (нечисловой `run_id`).

### Формы пайплайна

| Схема | Поля |
|---|---|
| `PipelineRunIn` | `pipeline` (объект/null), `initial_args` (объект), `background` (bool) |
| `PipelineStepOut` | `id`, `run_id`, `step_index`, `tool_name`, `input_args` (разрешённые аргументы вызова), `output_result` (`structured`/`text`/`reason_code`/`is_error`/`duration_ms`), `duration_ms`, `status` (`ok`/`failed`/`stopped`), `error_message` |
| `PipelineRunOut` | `id`, `pipeline_name`, `status` (`running`/`completed`/`stopped`/`failed`), `started_at`, `finished_at` (`null` — идёт), `total_duration_ms` |
| `PipelineStartOut` | `run_id`, `pipeline_name`, `status`, `steps` ([PipelineStepOut]; при `background=true` пусто), `count`, `failed_at_step`, `message`, `error`, `total_duration_ms`, `background` |
| `PipelineRunReportOut` | `run` ([PipelineRunOut]), `steps` ([PipelineStepOut]), `count`, `failed_at_step`, `message`, `error` |
| `PipelineRunsResponse` | `runs` ([PipelineRunOut]), `count` |
| `PipelineStepsResponse` | `run_id`, `steps` ([PipelineStepOut]), `count` |
| `PipelineReportOut` | `detected`, `run_id`, `status`, `message`, `failed_at_step`, `error`, `steps` ([PipelineStepOut]), `count`, `total_duration_ms`, `used_in_prompt`, `added_tokens`; это тип поля `pipeline` ответа генерации |
| `SearchResult` | `query`, `source`, `source_kind` (`api`/`file`/`sqlite`), `count`, `items` ([SearchItem]) |
| `SearchItem` | `id`, `title`, `content`, `url`, `metadata` |
| `SummaryResult` | `summary_text`, `key_points`, `total_items`, `style_used`, `engine` (`llm`/`aggregation`) |
| `SavedFile` | `filename`, `filepath`, `size_bytes`, `format`, `saved_at` |

Ответы MCP-инструментов композиции приходят в `result.structured` вызова
`POST /mcp/call` (или в `output_result.structured` шага прогона): `search` →
`SearchResult`, `summarize` → `SummaryResult`, `save_to_file` → `SavedFile` — те же
структуры, что объявлены `TypedDict`-ами в `mcp_server/schemas.py`.

## Оркестрация

Оркестрация — это **флоу по нескольким MCP-серверам сразу**: план описывает не один
вызов, а цепочку, и маршрутизацию каждого шага решает имя инструмента. План — это
ДАННЫЕ (как пайплайн дня 19): у шага есть `tool`, `args` и необязательный `guard`, а
**сервера в шаге нет** — его выбирает реестр флота
(`backend/services/mcp_registry.py`, `find_tool_by_name`): вызов уходит на первый
сервер в порядке `mcp_servers.json`, который публикует такой инструмент (совпадение
имён у нескольких серверов реестр пишет предупреждением в лог). Поэтому один и тот
же план переживает переезд инструмента на другой сервер флота.

Встроенный сценарий (`backend/domain/orchestration_spec.py`) — пять шагов по трём
серверам: `search_web` (`search_server`) → `summarize` и `extract_keywords`
(`data_server`) → `save_to_file` и `save_to_db` (`storage_server`). Поиск идёт с
ПУСТЫМ запросом намеренно: лента jsonplaceholder — английский lorem ipsum, и
подстрочный фильтр по русской реплике дал бы ноль элементов; пустой запрос означает
«без фильтра», а сама реплика уходит в заголовок строки базы и в системный блок
результата. Аргументы запуска шаблона — `{query}`, `{limit}`, `{filename}`,
`{format}`: незаданные берутся из умолчаний дня (`limit` = 5, `format` = `md`, а
`filename` — машинное имя из реплики, для демо — `demo-scenario`), иначе заглушка
осталась бы в аргументах инструмента и шаг упал бы на маппинге.

Порядок одного шага прогона — **маппинг аргументов → условие шага → маршрутизация →
подключение сервера при нужде → вызов инструмента → строка журнала → событие
автомата**:

1. `args` разрешает ТОТ ЖЕ механизм, что у пайплайна
   (`backend/domain/pipeline_mapping.py`): `{имя}` — аргумент запуска,
   `$steps.<i>.<путь>` — поле выхода шага `i`; отсутствующий путь или незаполненная
   заглушка — ошибка шага, а не тихая пустая строка;
2. невыполненное условие (`guard`: `non_empty` / `empty` / `equals` / `contains`)
   ошибкой не считается: прогон завершается досрочно со статусом `stopped` и
   сообщением условия;
3. сервер шага подключается динамически (`ensure_connected`), если на старте он не
   поднялся или упал позже; недоступный сервер — ошибка шага `not_connected`.

Журнал прогона лежит в SQLite в двух таблицах: `orchestration_runs` (реплика, план
целиком, статус, метки времени, общая длительность, `servers_used`) и
`orchestration_steps` (номер шага, сервер, инструмент, разрешённые аргументы вызова,
результат, время, статус, текст ошибки), связанные внешним ключом `run_id` с
каскадным удалением. Строка шага пишется ВСЕГДА — включая шаг, упавший на маппинге
(`output_result: null`, `duration_ms: 0`): иначе причина остановки не доехала бы до
истории и отчёта. `output_result` — единая форма для всех инструментов:
`{"reason_code", "structured", "text", "is_error", "duration_ms"}`, поэтому пути
`$steps.<i>.structured.<поле>` определены всегда. Коды причин шага — те же, что у
одиночного вызова: `not_connected`, `unknown_tool`, `bad_arguments`, `transport`,
`tool_error`. Прогон останавливается на первом шаге со статусом не `ok`.

Состояние прогона — автомат (`backend/domain/orchestration_fsm.py`), и значения его
состояний — ровно те статусы, что лежат в `orchestration_runs.status` и уходят в
API: `idle`, `running`, `completed`, `stopped`, `failed` (маппинг не нужен).

| Состояние | Событие → новое состояние | Когда |
|---|---|---|
| `idle` | `start` → `running` | прогон начат |
| `running` | `advance` → `running` | шаг выполнен, остались следующие |
| `running` | `finish` → `completed` | последний шаг выполнен |
| `running` | `stop` → `stopped` | условие шага не выполнено |
| `running` | `fail` → `failed` | шаг завершился ошибкой |
| `completed` / `stopped` / `failed` | `start` → `running` | следующий прогон (терминальные состояния) |

Фоновый запуск идёт в отдельном потоке (`threading.Thread`, daemon), и строка запуска
создаётся ДО старта потока: состояние `running` видно с первого же опроса, а
исключение в потоке не роняет процесс — запуск получает терминальный `failed`.
Путь агента всегда синхронный (`background: false`): ответ хода обязан опираться на
данные этого же запроса.

Откуда взялся план, видно в поле `plan_source` (и в самом плане — `plan.source`):

| `plan_source` | Что значит |
|---|---|
| `given` | план пришёл в запросе (`plan`) — так работает и демо-сценарий, план которого лежит в домене |
| `llm` | план предложила модель DeepSeek по каталогу флота (промпт требует «определи, какие инструменты с каких серверов нужно вызвать и в каком порядке») |
| `heuristic` | модель недоступна (нет ключа) или её ответ не разобран — сработал встроенный сценарий, отфильтрованный по доступным инструментам (`backend/domain/orchestration_plan.py`) |

Контракт ошибок раздела: `400` — негодный план (не объект, пустой список `steps`,
шагов больше `ORCH_STEPS_MAX = 12`, шаг без `tool`, `args` не объект, неизвестное
условие), невыполнимый сценарий (плана нет, а эвристике не из чего собрать ни одного
шага) и неизвестный `status` в фильтре; `404` — несуществующий запуск; `422` — тело
не прошло схему (пустая или длиннее `ORCH_QUERY_MAX = 500` реплика, не объект
`plan`/`initial_args`, не булево `background`). Отказ приходит из домена данными
(`OrchestrationRejected.reason_code`) и переводится в код в роутере
`backend/api/orchestration.py`.

### POST /orchestration/run

Запускает оркестрацию по реплике. Тело — `OrchestrationRunIn`:

| Поле | Тип | Описание |
|---|---|---|
| `query` | строка, 1…500 | реплика-запрос: по ней строится план и подставляются аргументы запуска |
| `background` | bool | `true` (по умолчанию) — прогон в фоновом потоке, ответ сразу со статусом `running`; `false` — синхронно, с шагами в ответе |
| `plan` | объект/null | декларативный план (`name`, `steps`: `tool`, `args`, необязательный `guard`); без него план строит модель, а при её недоступности — встроенный сценарий |
| `initial_args` | объект | аргументы запуска: `query`, `limit`, `filename`, `format`; незаданные берутся из умолчаний дня, поэтому `{limit}`/`{filename}` в плане не остаются пустыми |

Синхронный запуск (`background: false`) — весь отчёт сразу. План не передан, значит
его построил оркестратор: `plan_source: "heuristic"` (в примере ключа DeepSeek нет):

```bash
curl.exe -X POST http://127.0.0.1:8000/orchestration/run \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"найди последние посты пользователей, сделай сводку по темам, сохрани в файл и запиши в базу\",\"initial_args\":{\"query\":\"найди последние посты пользователей, сделай сводку по темам, сохрани в файл и запиши в базу\",\"limit\":5,\"filename\":\"demo-scenario\",\"format\":\"md\"},\"background\":false}"
```

```json
{
  "run_id": 1,
  "query": "найди последние посты пользователей, сделай сводку по темам, сохрани в файл и запиши в базу",
  "status": "completed",
  "plan": {
    "name": "heuristic-chain",
    "steps": [
      {"tool": "search_web",
       "args": {"query": "", "source": "posts", "limit": "{limit}"}},
      {"tool": "summarize",
       "args": {"items": "$steps.0.structured.items", "style": "short",
                "max_length": 600}},
      {"tool": "extract_keywords",
       "args": {"text": "$steps.1.structured.summary_text", "limit": 7}},
      {"tool": "save_to_file",
       "args": {"content": "Сводка:\n$steps.1.structured.summary_text\n\nКлючевые слова: $steps.2.structured.joined",
                "filename": "{filename}", "format": "{format}"}},
      {"tool": "save_to_db",
       "args": {"kind": "orchestration", "title": "{query}",
                "content": "$steps.1.structured.summary_text",
                "source": "search_web",
                "metadata": {"file": "$steps.3.structured.filepath",
                             "keywords": "$steps.2.structured.joined"}}}
    ],
    "source": "heuristic"
  },
  "plan_source": "heuristic",
  "steps": [
    {"id": 1, "run_id": 1, "step_index": 0, "server_name": "search_server",
     "tool_name": "search_web",
     "input_args": {"query": "", "source": "posts", "limit": 5},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 467,
                       "structured": {"query": "", "source": "posts",
                                      "source_kind": "api", "count": 5,
                                      "items": ["…5 элементов: post:1 … post:5…"]},
                       "text": "{\n  \"query\": \"\",\n  …\n}"},
     "duration_ms": 467, "status": "ok", "error_message": null},
    {"id": 2, "run_id": 1, "step_index": 1, "server_name": "data_server",
     "tool_name": "summarize",
     "input_args": {"items": ["…элементы шага 0…"], "style": "short",
                    "max_length": 600},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 7,
                       "structured": {"summary_text": "Найдено 5 элементов. Первые: …",
                                      "key_points": ["sunt aut facere …", "…"],
                                      "total_items": 5, "style_used": "short",
                                      "engine": "aggregation"},
                       "text": "…"},
     "duration_ms": 7, "status": "ok", "error_message": null},
    {"id": 3, "run_id": 1, "step_index": 2, "server_name": "data_server",
     "tool_name": "extract_keywords",
     "input_args": {"text": "Найдено 5 элементов. Первые: …", "limit": 7},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 6,
                       "structured": {"keywords": ["aut", "qui", "repellat", "esse",
                                                   "est", "excepturi", "exercitationem"],
                                      "count": 7,
                                      "joined": "aut, qui, repellat, esse, est, excepturi, exercitationem",
                                      "engine": "frequency"},
                       "text": "…"},
     "duration_ms": 6, "status": "ok", "error_message": null},
    {"id": 4, "run_id": 1, "step_index": 3, "server_name": "storage_server",
     "tool_name": "save_to_file",
     "input_args": {"content": "Сводка:\n…\n\nКлючевые слова: …",
                    "filename": "demo-scenario", "format": "md"},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 8,
                       "structured": {"filename": "demo-scenario.md",
                                      "filepath": "…/day20/output/demo-scenario.md",
                                      "size_bytes": 302, "format": "md",
                                      "saved_at": "2026-09-25T16:10:10+00:00"},
                       "text": "…"},
     "duration_ms": 8, "status": "ok", "error_message": null},
    {"id": 5, "run_id": 1, "step_index": 4, "server_name": "storage_server",
     "tool_name": "save_to_db",
     "input_args": {"kind": "orchestration", "title": "найди последние посты …",
                    "content": "Найдено 5 элементов. …", "source": "search_web",
                    "metadata": {"file": "…/day20/output/demo-scenario.md",
                                 "keywords": "aut, qui, repellat, esse, est, excepturi, exercitationem"}},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 20,
                       "structured": {"row_id": 1, "kind": "orchestration",
                                      "title": "найди последние посты …",
                                      "source": "search_web", "size_bytes": 200,
                                      "created_at": "2026-09-25T16:10:10+00:00"},
                       "text": "…"},
     "duration_ms": 20, "status": "ok", "error_message": null}
  ],
  "count": 5,
  "servers_used": ["search_server", "data_server", "storage_server"],
  "failed_at_step": null,
  "message": "оркестрация выполнена",
  "error": null,
  "total_duration_ms": 681,
  "background": false
}
```

Фоновый запуск (`background: true`, он же — по умолчанию) отвечает сразу, шагов в
ответе нет, а прогресс читается через `GET /orchestration/runs/{run_id}`:

```bash
curl.exe -X POST http://127.0.0.1:8000/orchestration/run \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"найди последние посты пользователей и запиши в базу\"}"
```

```json
{
  "run_id": 2,
  "query": "найди последние посты пользователей и запиши в базу",
  "status": "running",
  "plan": {"name": "heuristic-chain", "steps": ["…5 шагов…"], "source": "heuristic"},
  "plan_source": "heuristic",
  "steps": [],
  "count": 0,
  "servers_used": [],
  "failed_at_step": null,
  "message": "оркестрация выполняется",
  "error": null,
  "total_duration_ms": 0,
  "background": true
}
```

Коды ответа:

| Код | Когда | Тело |
|---|---|---|
| `200` | прогон запущен (синхронно завершён или ушёл в фон) | `OrchestrationStartOut` |
| `400` | негодный план, невыполнимый сценарий (плана нет, а флот не публикует нужных инструментов) | `detail` — причина и что сделать |
| `422` | тело не прошло схему (Pydantic) | стандартная ошибка FastAPI |

Отказ домена — `400` с понятным текстом:

```json
{ "detail": "У плана должен быть непустой список шагов «steps»" }
```

```json
{ "detail": "Условие «exotic» не поддержано. Допустимы: non_empty, empty, equals, contains" }
```

```json
{ "detail": "Ни один шаг сценария не выполним: флот не публикует нужных инструментов" }
```

### POST /orchestration/demo

Демонстрационный сценарий одной кнопкой: реплика, план и аргументы запуска берутся
из домена, поэтому кнопка «🚀 Запустить демо-сценарий» в интерфейсе, CLI-прогон и
тест запускают ровно один и тот же сценарий. Тело — `OrchestrationDemoIn`:

| Поле | Тип | Описание |
|---|---|---|
| `background` | bool | `true` (по умолчанию) — прогон в фоновом потоке: кнопка сразу получает `run_id` и опрашивает шаги; `false` — синхронно |
| `initial_args` | объект | переопределения аргументов запуска: `query`, `limit`, `filename`, `format` |

План здесь всегда приходит готовым, поэтому `plan_source` — `given`, а имя плана —
`demo-scenario`:

```bash
curl.exe -X POST http://127.0.0.1:8000/orchestration/demo \
  -H "Content-Type: application/json" -d "{}"
```

```json
{
  "run_id": 3,
  "query": "найди последние посты пользователей, сделай сводку по темам, сохрани в файл и запиши в базу",
  "status": "running",
  "plan": {"name": "demo-scenario", "steps": ["…5 шагов…"], "source": "given"},
  "plan_source": "given",
  "steps": [],
  "count": 0,
  "servers_used": [],
  "failed_at_step": null,
  "message": "оркестрация выполняется",
  "error": null,
  "total_duration_ms": 0,
  "background": true
}
```

Пустой флот (в `mcp_servers.json` нет серверов или ни один не опубликовал каталог)
отвергается кодом `400` **до** создания запуска: план демо-сценария валиден всегда,
и без этой проверки кнопка отвечала бы «запущено», а прогон падал бы на первом шаге.
Текст отказа — «Флот пуст: ни один сервер не опубликовал инструментов …». Код `400`
также приходит от `POST /orchestration/run` без плана, когда эвристике не из чего
собрать ни одного шага. Ошибка сервера внутри шага (`tool_error`) не отказ запроса:
запуск уже создан, а его итог виден по статусу.

### GET /orchestration/runs

История запусков от свежих к старым плюс статистика по журналу шагов. Параметры:
`status` (необязательный фильтр — допустимы все значения состояний автомата:
`idle` / `running` / `completed` / `stopped` / `failed`; неизвестное значение — `400`.
Нормальный прогон хранит `running`, а затем терминальный статус, поэтому строку со
статусом `idle` фильтр не найдёт) и `limit` (по умолчанию
`ORCH_RUNS_LIMIT = 50`).

```bash
curl.exe "http://127.0.0.1:8000/orchestration/runs?limit=5"
```

```json
{
  "runs": [
    {"id": 2, "query": "найди данные про RAG и сохрани в базу", "status": "completed",
     "started_at": "2026-09-25T16:10:11.100000+00:00",
     "finished_at": "2026-09-25T16:10:11.429000+00:00",
     "total_duration_ms": 329,
     "servers_used": ["search_server", "data_server", "storage_server"]},
    {"id": 1, "query": "найди последние посты пользователей, сделай сводку по темам, сохрани в файл и запиши в базу",
     "status": "completed",
     "started_at": "2026-09-25T16:10:09.895728+00:00",
     "finished_at": "2026-09-25T16:10:10.633267+00:00",
     "total_duration_ms": 681,
     "servers_used": ["search_server", "data_server", "storage_server"]}
  ],
  "count": 2,
  "stats": {
    "runs": 2,
    "steps": 10,
    "avg_step_ms": 85.5,
    "servers": [
      {"server": "storage_server", "calls": 4, "avg_ms": 11.5},
      {"server": "data_server", "calls": 4, "avg_ms": 5.25},
      {"server": "search_server", "calls": 2, "avg_ms": 394.0}
    ],
    "tools": [
      {"tool": "extract_keywords", "server": "data_server", "calls": 2},
      {"tool": "save_to_db", "server": "storage_server", "calls": 2},
      {"tool": "save_to_file", "server": "storage_server", "calls": 2},
      {"tool": "search_web", "server": "search_server", "calls": 2},
      {"tool": "summarize", "server": "data_server", "calls": 2}
    ]
  }
}
```

`stats` считается по журналу шагов (`orchestration_steps`), а число запусков — по
`orchestration_runs`: поэтому статистика не зависит от того, сколько шагов успел
выполнить упавший прогон. Списки `servers` и `tools` отсортированы по убыванию
числа вызовов. В каждом запуске поле `plan` отдаётся целиком (в примере оно
свёрнуто) — по нему видно, какие шаги выполнялись и откуда план взялся.

Неизвестный статус в фильтре — `400` с перечнем допустимых:

```json
{ "detail": "Неизвестный статус запуска «done»; допустимы: completed, failed, idle, running, stopped" }
```

### GET /orchestration/runs/{run_id}

Отчёт о запуске: строка запуска, его шаги по порядку и итог. Ответ —
`OrchestrationRunReportOut`; `failed_at_step` и `error` заполняются у прогона,
остановленного ошибкой, а `message` у досрочно завершённого (`stopped`) — это
сообщение невыполненного условия.

```bash
curl.exe http://127.0.0.1:8000/orchestration/runs/1
```

```json
{
  "run": {
    "id": 1,
    "query": "найди последние посты пользователей, сделай сводку по темам, сохрани в файл и запиши в базу",
    "plan": {"name": "heuristic-chain", "steps": ["…5 шагов…"], "source": "heuristic"},
    "status": "completed",
    "started_at": "2026-09-25T16:10:09.895728+00:00",
    "finished_at": "2026-09-25T16:10:10.633267+00:00",
    "total_duration_ms": 681,
    "servers_used": ["search_server", "data_server", "storage_server"]
  },
  "steps": [
    {"id": 1, "run_id": 1, "step_index": 0, "server_name": "search_server",
     "tool_name": "search_web",
     "input_args": {"query": "", "source": "posts", "limit": 5},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 467,
                       "structured": {"query": "", "source": "posts",
                                      "source_kind": "api", "count": 5,
                                      "items": ["…"]},
                       "text": "…"},
     "duration_ms": 467, "status": "ok", "error_message": null},
    "…шаги 1–4…"
  ],
  "count": 5,
  "servers_used": ["search_server", "data_server", "storage_server"],
  "failed_at_step": null,
  "message": "оркестрация выполнена",
  "error": null
}
```

Несуществующий запуск — `404`:

```json
{ "detail": "Запуск оркестрации 42 не найден" }
```

### GET /orchestration/runs/{run_id}/steps

Только шаги одного запуска (по возрастанию `step_index`) — этот путь опрашивает
прогресс интерфейса, пока прогон идёт. Ответ — `OrchestrationStepsResponse`
(`run_id`, `steps`, `count`); пустой список означает, что запуск есть, но шагов пока
нет. Несуществующий запуск — `404` с тем же текстом, что выше.

```bash
curl.exe http://127.0.0.1:8000/orchestration/runs/1/steps
```

```json
{
  "run_id": 1,
  "steps": [
    {"id": 1, "run_id": 1, "step_index": 0, "server_name": "search_server",
     "tool_name": "search_web",
     "input_args": {"query": "", "source": "posts", "limit": 5},
     "output_result": {"reason_code": null, "is_error": false, "duration_ms": 467,
                       "structured": {"query": "", "source": "posts",
                                      "source_kind": "api", "count": 5, "items": ["…"]},
                       "text": "…"},
     "duration_ms": 467, "status": "ok", "error_message": null},
    "…шаги 1–4…"
  ],
  "count": 5
}
```

### DELETE /orchestration/runs/{run_id}

Удаляет запуск вместе с шагами (каскад): история шагов без запуска смысла не имеет.

```bash
curl.exe -X DELETE http://127.0.0.1:8000/orchestration/runs/1
```

```json
{ "status": "deleted", "run_id": 1 }
```

Коды: `200`, `404` (несуществующий запуск), `422` (нечисловой `run_id`).

### Формы оркестрации

| Схема | Поля |
|---|---|
| `OrchestrationRunIn` | `query` (1…500), `background` (bool, по умолчанию `true`), `plan` (объект/null), `initial_args` (объект, по умолчанию `{}`) |
| `OrchestrationDemoIn` | `background` (bool, по умолчанию `true`), `initial_args` (объект, по умолчанию `{}`) |
| `OrchestrationStepOut` | `id`, `run_id`, `step_index`, `server_name` (пусто — шаг не дошёл до сервера), `tool_name`, `input_args` (разрешённые аргументы вызова), `output_result` (`reason_code`/`structured`/`text`/`is_error`/`duration_ms`; `null` у шага, упавшего на маппинге), `duration_ms`, `status` (`ok`/`failed`/`stopped`), `error_message` |
| `OrchestrationRunOut` | `id`, `query`, `plan` (целиком, с полем `source`), `status` (`running`/`completed`/`stopped`/`failed`), `started_at`, `finished_at` (`null` — идёт), `total_duration_ms`, `servers_used` |
| `OrchestrationStartOut` | `run_id`, `query`, `status`, `plan`, `plan_source` (`given`/`llm`/`heuristic`), `steps` ([OrchestrationStepOut]; при `background=true` пусто), `count`, `servers_used`, `failed_at_step`, `message`, `error`, `total_duration_ms`, `background` |
| `OrchestrationRunReportOut` | `run` (OrchestrationRunOut), `steps` ([OrchestrationStepOut]), `count`, `servers_used`, `failed_at_step`, `message`, `error` |
| `OrchestrationRunsResponse` | `runs` ([OrchestrationRunOut]), `count`, `stats` (`runs`, `steps`, `avg_step_ms`, `servers` [{`server`, `calls`, `avg_ms`}], `tools` [{`tool`, `server`, `calls`}]) |
| `OrchestrationStepsResponse` | `run_id`, `steps` ([OrchestrationStepOut]), `count` |
| `OrchestrationReportOut` | `detected`, `run_id`, `status`, `message`, `plan_source`, `servers_used`, `tools_used`, `steps` ([OrchestrationStepOut]), `count`, `failed_at_step`, `error`, `total_duration_ms`, `used_in_prompt`, `added_tokens`; это тип поля `orchestration` ответа генерации |

### Оркестрация в ответе генерации

`POST /agents/{agent_id}/generate` запускает оркестрацию сам, если реплика про это
явно говорит: срабатывают фразы «в базу», «в бд», «в базу данных», «в sqlite»,
«оркестрац», «несколько серверов», «нескольких серверов», «разными серверами»,
«разных серверов», «флот серверов», «флота серверов» и «цепочк»
(`backend/domain/orchestration_intent.py`). Правило узкое намеренно: реплика дня 19
«найди статьи про RAG, сделай сводку и сохрани в файл» обязана остаться пайплайном
(пайплайн пишет только файл), а «найди данные и сохрани в БД» — это как раз
оркестрация.

Прогон в этом пути синхронный (`background: false`), а его результат уходит в
системный промпт того же запроса отдельным блоком; признак распознавания и вклад
блока видны в поле `orchestration` ответа:

```json
{
  "detected": true,
  "run_id": 3,
  "status": "completed",
  "message": "оркестрация выполнена",
  "plan_source": "heuristic",
  "servers_used": ["search_server", "data_server", "storage_server"],
  "tools_used": ["search_web", "summarize", "extract_keywords", "save_to_file", "save_to_db"],
  "steps": ["…5 шагов…"],
  "count": 5,
  "failed_at_step": null,
  "error": null,
  "total_duration_ms": 681,
  "used_in_prompt": true,
  "added_tokens": 181
}
```

Поля, которых нет у ответа запуска, отвечают на вопросы хода:

| Поле | Что значит |
|---|---|
| `detected` | эвристика распознала в реплике оркестрацию (у нераспознанной реплики поле `orchestration` остаётся пустой формой с `detected: false`) |
| `tools_used` | инструменты шагов по порядку — сводка «какие серверы поработали» для интерфейса |
| `used_in_prompt` | блок «## Результат оркестрации» действительно ушёл в системный промпт |
| `added_tokens` | сколько токенов добавил этот блок (в примере — 181, кодировка `cl100k_base`) |

Блок собирается только для прогона, у которого есть что сообщить: у `failed`
(и пустого статуса) блока нет — правило дня 17 «данные неудачного вызова в промпт не
попадают»; у досрочно завершённого (`stopped`) блок есть, и в нём видно невыполненное
условие, чтобы модель не отвечала так, будто данные собраны. Реплика, распознанная
как оркестрация, **выключает остальные автоматизмы этого хода**: шаг пайплайна не
запускается (в поле `pipeline` ответа остаётся пустая форма с `detected: false`), а
шаг одиночного MCP-инструмента пропускается (поле `mcp` не заполняется). Одна
реплика — один автоматизм: иначе один и тот же запрос писал бы файл дважды.

Так выглядит блок в системном промпте (это же содержимое — в `system_prompt` ответа):

```
## Результат оркестрации
Запрос: найди данные про RAG и сохрани в базу
Серверы: search_server, data_server, storage_server
Шаги:
- search_web (search_server): ok, 467 мс
- summarize (data_server): ok, 7 мс
- extract_keywords (data_server): ok, 6 мс
- save_to_file (storage_server): ok, 8 мс
- save_to_db (storage_server): ok, 20 мс
Итог: оркестрация выполнена
Данные собраны цепочкой MCP-инструментов; используй их как источник правды и не выдумывай полей, которых здесь нет.
```

## MCP-серверы

`GET /mcp/servers` дня 20 отдаёт не каталог «известных целей для сравнения» (как
было днём 16), а **состав флота** из `day20/mcp_servers.json` и состояние
подключений: имя, команда запуска, описание, число инструментов, `connected`/`state`
и текст ошибки у того сервера, который не поднялся. Соединений у процесса столько,
сколько серверов в файле (плюс, если он открыт, один клиент активного соединения
раздела «MCP»), поэтому `connected` значит «этот сервер подключён прямо сейчас», а
не «этот сервер выбран пользователем»; за активное одиночное соединение раздела
[«MCP»](#mcp) отвечает `GET /mcp/status` — это отдельный клиент со своей
стейт-машиной.

Флот описывается данными: три сервера дня — `search_server` (3 инструмента),
`data_server` (4) и `storage_server` (4), всего 11 инструментов.

| Сервер | Команда запуска | Инструменты |
|---|---|---|
| `search_server` | `uv run python mcp_servers/search_server/server.py` | `search_web`, `search_local`, `fetch_url` |
| `data_server` | `uv run python mcp_servers/data_server/server.py` | `summarize`, `extract_keywords`, `filter_by_date`, `aggregate` |
| `storage_server` | `uv run python mcp_servers/storage_server/server.py` | `save_to_file`, `save_to_db`, `list_saved`, `load_from_file` |

Реестр поднимает флот при старте приложения (`connect_all` в `lifespan`) и закрывает
при остановке; записи живут в памяти процесса, поэтому состояние подключения не
переживает перезапуск (переподключение происходит на старте). Сервер, который не
поднялся, остаётся в списке с `error` и `state`: один упавший сервер не мешает
остальным, а сам сервер виден в ответе — и его инструменты тоже, если кэш
`tools_cache` в файле уже заполнен (`POST /mcp/servers/refresh`; в файле дня кэш
заполнен изначально). Тогда каталог берётся из файла, и
`GET /mcp/servers/{name}/tools` отвечает `cached: true`; пока кэша нет, у сервера
`tool_count: 0` и пустой каталог. Файл `mcp_servers.json` — единственное место, где
описан флот: чтобы добавить сервер, правят файл, а код реестра не меняют.

### GET /mcp/servers

Ответ — `MCPServersResponse`: `servers` (список `MCPServerInfo` в порядке файла),
`count`, `connected` (сколько серверов подключено прямо сейчас) и `total_tools`
(сколько инструментов публикует флот целиком).

```bash
curl.exe http://127.0.0.1:8000/mcp/servers
```

```json
{
  "servers": [
    {"name": "search_server", "command": "uv",
     "args": ["run", "python", "mcp_servers/search_server/server.py"],
     "description": "Поиск данных: search_web (jsonplaceholder/wikipedia), search_local (файл дня), fetch_url",
     "target": "uv run python mcp_servers/search_server/server.py",
     "transport": "stdio", "connected": true, "state": "connected",
     "tool_count": 3, "error": null},
    {"name": "data_server", "command": "uv",
     "args": ["run", "python", "mcp_servers/data_server/server.py"],
     "description": "Обработка данных: summarize, extract_keywords, filter_by_date, aggregate",
     "target": "uv run python mcp_servers/data_server/server.py",
     "transport": "stdio", "connected": true, "state": "connected",
     "tool_count": 4, "error": null},
    {"name": "storage_server", "command": "uv",
     "args": ["run", "python", "mcp_servers/storage_server/server.py"],
     "description": "Сохранение и выдача: save_to_file (output/), save_to_db (storage.db), list_saved, load_from_file",
     "target": "uv run python mcp_servers/storage_server/server.py",
     "transport": "stdio", "connected": true, "state": "connected",
     "tool_count": 4, "error": null}
  ],
  "count": 3,
  "connected": 3,
  "total_tools": 11
}
```

Поля записи сервера:

| Поле | Тип | Пояснение |
|---|---|---|
| `name` | строка | имя сервера из `mcp_servers.json` (оно же — ключ маршрутизации и подсказок в отказах) |
| `command` | строка | команда запуска (для трёх серверов дня — `uv`) |
| `args` | [строка] | аргументы команды: путь к `server.py` и его ключи |
| `description` | строка | что умеет сервер и какие инструменты публикует |
| `target` | строка | цель подключения одной строкой (команда с аргументами) — её же принимает `POST /mcp/connect`, если сервер нужно открыть вручную |
| `transport` | строка | транспорт подключения: `stdio` |
| `connected` | bool | открыто ли соединение с этим сервером прямо сейчас |
| `state` | строка | состояние клиента: `disconnected` / `connecting` / `connected` / `error` |
| `tool_count` | int | сколько инструментов у сервера (из соединения или из кэша файла) |
| `error` | строка/null | текст последней ошибки подключения этого сервера |

### GET /mcp/servers/{name}/tools

Инструменты одного сервера флота с описанием, `input_schema` и `output_schema`.
Ответ — `MCPServerToolsResponse`: `server`, `tools` ([`MCPToolSchema`]), `count` и
`cached`. `cached: true` значит «сервер не подключён, поэтому показан каталог из кэша
файла `mcp_servers.json`»: так интерфейс отличает «каталог прочитан сейчас» от
«показан последний известный». Живой каталог всегда важнее кэша — если сервер
подключён, `cached` ложно.

```bash
curl.exe http://127.0.0.1:8000/mcp/servers/data_server/tools
```

```json
{
  "server": "data_server",
  "tools": [
    {"name": "summarize",
     "description": "Собирает сводку по списку элементов и выделяет ключевые пункты. Параметры: items — список элементов (у каждого поля title и content); style — short (по умолчанию), detailed, bullets; max_length — предел длины сводки (50..4000 символов, по умолчанию 600). …",
     "input_schema": {"properties": {"items": {"items": {"additionalProperties": true, "type": "object"}, "title": "Items", "type": "array"},
                                     "style": {"default": "short", "title": "Style", "type": "string"},
                                     "max_length": {"default": 600, "title": "Max Length", "type": "integer"}},
                      "required": ["items"], "type": "object", "title": "summarizeArguments"},
     "output_schema": {"properties": {"summary_text": {"title": "Summary Text", "type": "string"},
                                      "key_points": {"items": {"type": "string"}, "title": "Key Points", "type": "array"},
                                      "total_items": {"title": "Total Items", "type": "integer"},
                                      "style_used": {"title": "Style Used", "type": "string"},
                                      "engine": {"title": "Engine", "type": "string"}},
                       "required": ["summary_text", "key_points", "total_items", "style_used", "engine"],
                       "type": "object", "title": "SummaryResult"}},
    {"name": "extract_keywords", "…": "…"},
    {"name": "filter_by_date", "…": "…"},
    {"name": "aggregate", "…": "…"}
  ],
  "count": 4,
  "cached": false
}
```

Неизвестное имя сервера — `404` с перечнем известных:

```json
{ "detail": "Сервер «nope» не зарегистрирован; известны: search_server, data_server, storage_server" }
```

### POST /mcp/servers/refresh

Перечитывает `tools/list` у каждого подключённого сервера и записывает результат в
`tools_cache` файла `mcp_servers.json` (файл заменяется атомарно: сначала
`mcp_servers.json.tmp`, затем `os.replace`). Ответ — `MCPRefreshResponse`: `servers`
(те же записи, что у `GET /mcp/servers`), `count`, `total_tools` и `refreshed_at`
(ISO-8601, UTC).

```bash
curl.exe -X POST http://127.0.0.1:8000/mcp/servers/refresh \
  -H "Content-Type: application/json" -d "{}"
```

```json
{
  "servers": ["…три записи, как у GET /mcp/servers…"],
  "count": 3,
  "total_tools": 11,
  "refreshed_at": "2026-09-25T16:12:03+00:00"
}
```

`200` приходит **всегда**: сбой отдельного сервера — это не отказ всего запроса, а
данные его записи (`error`, `state`), потому что один упавший сервер не должен
отменять обновление кэша остальных. Сервер, который не подключён, кэш не обновляет:
для него в файле остаётся прежний `tools_cache`.

### Формы флота

| Схема | Поля |
|---|---|
| `MCPServerInfo` | `name`, `command`, `args`, `description`, `target`, `transport`, `connected`, `state`, `tool_count`, `error` |
| `MCPServersResponse` | `servers` ([MCPServerInfo]), `count`, `connected`, `total_tools` |
| `MCPServerToolsResponse` | `server`, `tools` ([`MCPToolSchema`] — `name`, `description`, `input_schema`, `output_schema`), `count`, `cached` |
| `MCPRefreshResponse` | `servers` ([MCPServerInfo]), `count`, `total_tools`, `refreshed_at` |

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
| `schedule` | ScheduleReportOut/null | шаг планировщика: зарегистрирована ли фоновая задача (`registered`), каким инструментом (`tool`), какая задача (`task`), текст сводки (`summary`) и подтверждение (`message`); `null` — фоновой задачи не появилось (реплика не про планировщик, нет MCP-соединения, вызов отклонён правилами или инструмент ответил ошибкой). Считается до вызова DeepSeek, поэтому заполнено и при `error` |
| `pipeline` | PipelineReportOut/null | шаг пайплайна (день 19): распознана ли в реплике композиция (`detected`), номер и статус прогона (`run_id`, `status`), его шаги (`steps`), итог (`message`), шаг с ошибкой (`failed_at_step`, `error`), длительность (`total_duration_ms`), ушёл ли результат в промпт (`used_in_prompt`) и сколько токенов добавил блок (`added_tokens`); `null` — пайплайна в реплике нет или реплика отклонена `hard`-инвариантом. Выполняется до контроля лимита контекста и до вызова DeepSeek, поэтому заполнен и при `error` |
| `system_prompt` | строка | итоговое system-сообщение запроса (профиль + роль + инварианты + блоки памяти + блок состояния задачи + блок данных MCP + блок данных планировщика + блок результата пайплайна; считается до вызова DeepSeek) |
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
| `400` | пустой `task_id` после обрезки пробелов в `PUT /memory/task`; недопустимый переход состояния задачи: пропуск этапа, откат больше чем на этап, переход «в себя», выход из этапа без согласования (guard-условие), любой переход из `done`, пауза из `done` и повторная пауза, `advance` и `rollback` на паузе, шаг чужого этапа, несовпадение `to_stage` с целью отката, `resume` не на паузе; цель MCP не разобрана: пустая после обрезки пробелов, URL там, где нужен запуск команды, и наоборот; `POST /mcp/call` — инструмента нет в каталоге сервера или аргументы не подходят по `input_schema` (нет обязательного, лишний, тип не тот); `POST /scheduler/tasks` — инструмент не входит в планировщик дня, лишний/отсутствующий аргумент, значение не того типа или вне границ, `source_url` без `http(s)://`, неразобранное расписание (интервал вне 1…86400, cron не из пяти полей, `date` без `run_date`); неизвестный `status` в фильтрах `/scheduler/tasks` и `/scheduler/reminders`; негодная конфигурация пайплайна (не объект, пустой список `steps`, шагов больше `PIPELINE_STEPS_MAX`, шаг без `tool`, неизвестное условие `op`) и неизвестный `status` в фильтре `/pipelines/runs`; негодный план оркестрации (не объект, пустой список `steps`, шагов больше `ORCH_STEPS_MAX`, шаг без `tool`, `args` не объект, неизвестное условие), невыполнимый сценарий оркестрации (плана нет, а флот не публикует нужных инструментов) и неизвестный `status` в фильтре `/orchestration/runs` | `HTTPException` с `detail` (у `POST /tasks/{task_id}/transition` — причина и подсказка) |
| `404` | неизвестный `agent_id` во всех `/agents/{agent_id}/...` (а для `DELETE /memory/long-term/{id}` — ещё и отсутствующая запись); нет профиля у `GET`/`PUT`/`DELETE /users/{user_id}/profile`; неизвестный `task_id` во всех `/tasks/{task_id}/...`; неизвестный `task_id` у `/scheduler/tasks/{task_id}/...` и `notification_id` у `POST /scheduler/notifications/{id}/read`; неизвестный `run_id` у `/pipelines/runs/{run_id}`, `…/steps` и `DELETE /pipelines/runs/{run_id}`, а также у `/orchestration/runs/{run_id}`, `…/steps` и `DELETE /orchestration/runs/{run_id}`; неизвестное имя сервера у `GET /mcp/servers/{name}/tools` | `HTTPException` с `detail` |
| `409` | профиль с таким `user_id` уже есть (`POST /users/{user_id}/profile`); задача с таким `task_id` уже заведена (`POST /agents/{agent_id}/tasks`); `GET /mcp/tools` и `POST /mcp/call` без соединения с MCP-сервером; пауза не активной задачи и возобновление не стоящей на паузе, запуск уже выполненной задачи планировщика | `HTTPException` с `detail` |
| `422` | невалидное тело запроса (Pydantic/FastAPI): невалидные поля профиля, `initial_stage` вне `planning`/`execution`/`validation`, неизвестный этап/шаг, слишком длинные `expected_action`/`reason`, пустой `task_id`, тело `PATCH /tasks/{task_id}/context` без единого флага, пустая цель или неизвестный транспорт у `POST /mcp/connect`, пустое или длиннее 100 символов имя инструмента у `POST /mcp/call`, `schedule_type` вне `date`/`interval`/`cron`, пустой или длиннее 64 символов `tool`, пустое или длиннее 100 символов `name` у `POST /scheduler/tasks`, не объект `pipeline`/`initial_args`, не булево `background` у `POST /pipelines/run`, нечисловой `limit`/`run_id` в `/pipelines/...`, пустая или длиннее 500 символов `query`, не объект `plan`/`initial_args`, не булево `background`, нечисловой `run_id`/`limit` в `/orchestration/...` | объект с `detail` — списком ошибок |
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
  профили пользователей (`user_profiles`), состояние задачи (`task_states` с
  журналом `task_transitions`), таблицы планировщика (`scheduled_tasks`,
  `task_runs`, `reminders`, `notifications`, `collected_data`,
  `periodic_summaries`) и журнал пайплайна (`pipeline_runs`, `pipeline_steps`)
  лежат в SQLite (`day20/agents.db`), а активные
  сессия и задача — в строке `agents`
  (`current_session_id`/`current_task_id`). При старте приложения `lifespan`
  создаёт таблицы, восстанавливает агентов вместе с диалогом
  (`restore_from_db`) и поднимает планировщик, который снова ставит задачи из
  `scheduled_tasks`, поэтому `/usage`, `/summary`, `/history`, `/users/...`,
  эндпоинты `/memory/...`, `/tasks/...`, `/scheduler/...` и `/pipelines/...`
  после перезапуска
  показывают те же данные: агент продолжает задачу с того же этапа и шага, а фон
  продолжает собирать данные и считать сводки без повторных объяснений.
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
  дня (память, профили, задачи, инварианты, журнал пайплайна) по-прежнему в базе.
- **Пайплайн — это вызовы инструментов, поэтому ему нужно MCP-соединение.**
  Прогон идёт через тот же `MCPToolRunner`, что и одиночный вызов, и без
  соединения первый же шаг получает `reason_code: "not_connected"` — прогон
  останавливается со статусом `failed`, а причина видна в `error` шага. Сами три
  инструмента композиции работают офлайн: `search` с источником `file:` читает
  файл внутри папки дня, `sqlite:` — таблицу базы дня (только на чтение), а
  `summarize` без ключа DeepSeek собирает сводку агрегацией (`engine:
  "aggregation"`). Только источники `posts`/`users` ходят в сеть, а `summarize`
  с ключом — в DeepSeek внутри процесса MCP-сервера.
- **Файлы пайплайна пишутся только в `day20/output/`.** `save_to_file` чистит имя
  (путь и `..` запрещены) и заменяет расширение на запрошенный формат, так что
  инструмент не может выйти за каталог вывода, даже если модель передала
  `../../etc/passwd`. Абсолютный путь сохранённого файла возвращается в
  `filepath` (`output_result.structured`) и виден в интерфейсе.
- **Вызов инструмента идёт наружу.** `POST /mcp/call` и шаг MCP в генерации
  обращаются к внешнему серверу (у своего сервера дня — HTTP к
  `jsonplaceholder.typicode.com`): без сети инструмент вернёт ошибку
  (`tool_error` или `transport`), а ход агента всё равно завершится — ответ
  придёт без внешних данных. В промпт уходит только успешный результат
  (`state: "done"`); отказ правил допуска, сбой связи и ошибка инструмента
  данных в промпт не добавляют. У пайплайна правило то же: в промпт уходит блок
  «## Результат пайплайна» только для `completed` и `stopped`; прогон `failed`
  блока не даёт.
- **Первое подключение к своему серверу требует готового `.venv`.** Цель по
  умолчанию — команда `uv run python mcp_server/server.py`: если окружение дня
  ещё не собрано (`uv sync`), первый запуск дочернего процесса дольше обычного
  и может не уложиться в `MCP_TIMEOUT = 30` секунд.
