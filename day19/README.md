# День 19 — MCP-инструменты композиции и декларативный пайплайн: `search` → `summarize` → `save_to_file` (+ планировщик, MCP, память, профиль, задача, инварианты и переходы)

Задание дня — **собирать MCP-инструменты в пайплайн**. К шести инструментам
своего MCP-сервера дня добавились три инструмента **композиции**: `search`
(найти элементы в ленте jsonplaceholder, в файле внутри папки дня или в таблице
SQLite дня), `summarize` (свести найденные элементы в текст и выделить ключевые
пункты) и `save_to_file` (записать текст в файл каталога дня `output/`). В
каталоге `day19/mcp_server/server.py` теперь **девять** инструментов, а сервер
представляется как `day19-pipeline` версии `1.2.0`.

Пайплайн описан **декларативно**: встроенная конфигурация `DEFAULT_PIPELINE` с
именем `search-summarize-save` состоит из трёх шагов, и каждый шаг объявляет
инструмент, его аргументы и (если нужно) условие перехода. Данные между шагами
передаются ссылками: `{имя}` — аргумент запуска, `$steps.<i>.<путь>` — поле
результата предыдущего шага. Прогон живёт в SQLite (`pipeline_runs` и
`pipeline_steps`): строка на запуск и строка на шаг с входными аргументами,
выходным результатом, длительностью и статусом. Условие перехода может
остановить прогон досрочно (шаг `summarize` требует непустой
`$steps.0.structured.items`, иначе пишет «нет данных для обработки»), а ошибка
шага останавливает пайплайн на его номере — исходы `completed`, `stopped` и
`failed` видят API, интерфейс и агент.

Агент запускает пайплайн сам по реплике («найди статьи про RAG, сделай сводку и
сохрани в файл»): намерение распознаётся эвристикой по ключевым словам
(`backend/domain/pipeline_intent.py`), прогон идёт **синхронно** — до проверки
лимита контекста и до шага одиночного MCP-инструмента — а результат
подставляется блоком «## Результат пайплайна» в системный промпт этого же
запроса; отчёт лежит в поле `pipeline` ответа генерации. Реплика с пайплайном не
разбирается ещё и как вызов одного инструмента.

Живой прогон дня —
[docs/reports/pipeline_demo.md](docs/reports/pipeline_demo.md): четыре
офлайн-сценария (успешный пайплайн, пустой результат поиска с досрочным
завершением, ошибка на втором шаге, запуск через агента), таблица инструментов
композиции и трассировка шагов «шаг | инструмент | входные данные | выходные
данные | время выполнения | статус» с фактическими значениями из журнала; прогон
проходит 26 из 26 проверок. Артефакт прогона остаётся в репозитории —
`day19/output/run-success.md`.

В интерфейсе появился раздел «🔀 Пайплайны» (седьмой в переключателе): форма
запуска, прогресс по шагам с обновлением раз в секунду, схема потока данных с
объёмами на переходах, история запусков с деталями каждого шага и удалением. В
сводке хода раздела «💬 Чат и память» реплика с пайплайном даёт строку
«🔀 Пайплайн: …».

Структура дня 18 сохранена полностью: планировщик фоновых задач с уведомлениями,
MCP-клиент и свой MCP-сервер, инварианты агента, состояние задачи как конечный
автомат с **контролируемыми переходами**, персонализация профилем пользователя,
три слоя памяти, четыре стратегии контекста и сжатие истории в конспект.
Пайплайн надстроен над ними и использует общий код-путь: и агент, и интерфейс, и
API, и MCP-инструменты идут через `Pipeline.run_pipeline` с журналом в
`pipeline_steps`. Приложение развивает день 18, а `day18/`, `day17/`, `day16/` и
более ранние дни остаются снимками.

Единственный писатель в SQLite — процесс бэкенда: он ведёт память, профили,
задачи, инварианты, журнал планировщика и журнал пайплайна. MCP-сервер в базу дня
только **читает** (источник `sqlite:<таблица>` открывает файл в режиме
`mode=ro`), а фоновые задачи ставит через API дня (`POST /scheduler/tasks`).
Исключение — таблиц у MCP-подсистемы по-прежнему нет: соединение живёт в памяти
процесса, и после перезапуска бэкенда `/mcp/status` честно отвечает
`disconnected`. Всё остальное
состояние (память, профили, задачи, инварианты, задачи планировщика с их
журналами, запуски и шаги пайплайна) — в SQLite и переживает рестарт.

Код дней 1–18 не изменялся — их файлы не тронуты; изменения только внутри
`day19/` плюс общий пакет `shared/` в корне репозитория, куда вынесен код, не
меняющийся между днями. Карта модулей — [STRUCTURE.md](STRUCTURE.md), междневные
изменения — [../CHANGELOG.md](../CHANGELOG.md). Инструкция —
[docs/usage.md](docs/usage.md).

## Что нового относительно дня 18

| Новое | Где |
|---|---|
| **Инструменты**: три инструмента композиции — `search` (источники `posts`/`users`/`file:<путь>`/`sqlite:<таблица>`), `summarize` (DeepSeek, а без ключа — движок агрегации), `save_to_file` (только каталог `output/`, форматы `txt`/`md`/`json`); сервер дня публикует девять инструментов | `mcp_server/pipeline_tools.py`, `mcp_server/search_sources.py`, `mcp_server/summarize_logic.py`, `mcp_server/llm_client.py`, `mcp_server/file_writer.py` |
| **Пайплайн**: декларативная конфигурация `search-summarize-save` из трёх шагов с маппингом `{имя}` / `$steps.<i>.<путь>` и условиями перехода `non_empty`/`empty`/`equals`/`contains`; стейт-машина прогона `IDLE → RUNNING → COMPLETED/STOPPED/FAILED`, остановка на первом шаге не со статусом `ok` | `backend/domain/pipeline_spec.py`, `backend/domain/pipeline_mapping.py`, `backend/domain/pipeline_fsm.py`, `backend/services/pipeline.py` |
| **Таблицы**: две новые таблицы — `pipeline_runs` (запуск: имя, статус, начало, конец, длительность) и `pipeline_steps` (шаг: инструмент, аргументы, результат, время, статус, сообщение об ошибке) с каскадным удалением | `backend/models/pipeline.py`, `backend/storage/pipeline_store.py` |
| **API**: пять эндпоинтов `/pipelines` (запуск, список запусков с фильтром статуса, отчёт запуска, шаги запуска, удаление) — всего в API дня **78**; версия приложения `13.0.0` | `backend/api/pipelines.py`, `backend/schemas/pipeline.py` |
| **Интерфейс**: седьмой раздел «🔀 Пайплайны» — форма запуска, прогресс по шагам (`@st.fragment(run_every="1s")`), схема потока с объёмами на переходах, история запусков (`run_every="5s"`); в сводке хода — строка «🔀 Пайплайн: …» | `frontend/pipeline_section.py`, `frontend/pipeline_api.py`, `frontend/chat_section.py` |
| **Тесты и документы**: новые наборы unit/integration/e2e на пайплайн и инструменты композиции (файлы — в [STRUCTURE.md](STRUCTURE.md)), фейки композиции `tests/pipeline_fakes.py`; отчёт `docs/reports/pipeline_demo.md` | `tests/unit/test_pipeline_*.py`, `tests/unit/test_search_sources.py`, `tests/unit/test_summarize_logic.py`, `tests/unit/test_file_writer.py`, `tests/integration/test_pipeline_*.py`, `tests/e2e/test_pipelines_api.py` |

## Пайплайны MCP

Пайплайн — то, чем день 19 отличается от дня 18. Он соединяет несколько
MCP-инструментов в одну цепочку, где результат предыдущего шага становится
аргументом следующего, а весь ход виден в журнале `pipeline_steps`.

### Три инструмента композиции

Сервер дня публикует их вместе с шестью унаследованными (всего девять) — вызов
идёт обычным путём (`tools/call`), поэтому инструменты доступны и вручную из
раздела «🔌 MCP», и из кода, и пайплайну.

| Инструмент | Параметры | Что делает |
|---|---|---|
| `search` | `query: str` (обязательный), `source: str = "posts"`, `limit: int = 5` (1…20) | ищет элементы в источнике: `query`, `source`, `source_kind`, `count`, `items[]` (у элемента `id`, `title`, `content`, `url`, `metadata`) |
| `summarize` | `items: list[dict]` (обязательный), `style: str = "short"` (`short`/`detailed`/`bullets`), `max_length: int = 600` (50…4000) | сводит элементы: `summary_text`, `key_points[]`, `total_items`, `style_used`, `engine` (`llm` или `aggregation`) |
| `save_to_file` | `content: str` (обязательный), `filename: str = "pipeline_result.md"`, `format: str = "md"` (`txt`/`md`/`json`) | пишет файл в каталог `day19/output/`: `filename`, `filepath`, `size_bytes`, `format`, `saved_at` |

Источники `search`:

| Источник | Что читает |
|---|---|
| `posts`, `users` | лента jsonplaceholder (`GET /posts?_limit=…` / `GET /users?_limit=…`); фильтр — подстрока без учёта регистра, пустой запрос — все записи |
| `file:<путь>` | файл **внутри папки дня** (выход за её пределы — ошибка), блоки разделяются пустыми строками |
| `sqlite:<таблица>` | таблица дня **только на чтение** (`mode=ro`); разрешены `collected_data`, `periodic_summaries`, `pipeline_steps` |

`summarize` вызывает DeepSeek, когда ключ доступен; если ключа нет, у сервера
выключена LLM (флаг `--llm off`) или вызов не удался, сводку собирает движок
**агрегации** (`engine: "aggregation"`) — шаг не падает из-за отсутствия ключа.
`save_to_file` пишет только в `output/`, а расширение имени заменяется на
запрошенный формат.

### Как устроен пайплайн

Конфигурация — обычные данные (`backend/domain/pipeline_spec.py`), поэтому
пайплайн можно прислать в API целиком, а можно взять встроенный:

```json
{
  "name": "search-summarize-save",
  "steps": [
    {"tool": "search", "args": {"query": "{query}", "source": "{source}", "limit": "{limit}"}},
    {"tool": "summarize",
     "guard": {"path": "$steps.0.structured.items", "op": "non_empty", "message": "нет данных для обработки"},
     "args": {"items": "$steps.0.structured.items", "style": "{style}", "max_length": "{max_length}"}},
    {"tool": "save_to_file",
     "args": {"content": "$steps.1.structured.summary_text", "filename": "{filename}", "format": "{format}"}}
  ]
}
```

* `{имя}` — аргумент запуска: `query`, `source`, `limit`, `style`, `max_length`, `filename`, `format` (значение подставляется как есть, если занимает строку целиком);
* `$steps.<i>.<путь>` — поле результата шага `i` (`structured`, `text`, `reason_code`, `is_error`, `duration_ms`);
* `guard` — условие перехода **перед** вызовом инструмента: `non_empty`, `empty`, `equals` (с ключом `value`), `contains`; своё сообщение задаёт `message`, иначе «условие шага не выполнено».

Порядок шага жёсткий: **маппинг аргументов → условие → вызов MCP-инструмента →
строка журнала → событие стейт-машины**. Строка в `pipeline_steps` пишется
всегда — даже если маппинг не сошёлся; прогон останавливается на первом шаге не
со статусом `ok`, а ошибка шага приходит данными (`reason_code`: `not_connected`,
`unknown_tool`, `bad_arguments`, `transport`, `tool_error`).

Стейт-машина прогона (`backend/domain/pipeline_fsm.py`): `IDLE` —`start`→
`RUNNING`; из `RUNNING` — `advance` → `RUNNING`, `finish` → `COMPLETED`, `stop` →
`STOPPED`, `fail` → `FAILED`; из терминального состояния `start` начинает новый
прогон. Значения состояний попадают в колонку `pipeline_runs.status` без
маппинга.

### Три исхода прогона

| Статус | Когда | Что видно |
|---|---|---|
| `completed` | последний шаг выполнен | все шаги со статусом `ok`, `message` — «пайплайн выполнен» |
| `stopped` | условие перехода не выполнено | шаг со статусом `stopped` и сообщением условия (для пустого поиска — «нет данных для обработки»); `failed_at_step` пуст: это решение, а не сбой |
| `failed` | шаг упал или маппинг не сошёлся | `failed_at_step` — номер шага, `error` — причина; предыдущие шаги остаются `ok` |

Результат последнего шага — файл в `day19/output/`; прогон офлайн-демонстрации
оставляет там `run-success.md` (пример приведён в отчёте).

### Как запустить из интерфейса

Раздел «🔀 Пайплайны» (седьмой в переключателе вверху страницы): сначала
подключитесь к серверу дня кнопкой «🔌 Подключиться к серверу дня» — без
соединения каждый шаг завершится отказом `not_connected`, — затем в форме
выберите источник, задайте запрос (по умолчанию «RAG»), `limit`, стиль сводки,
имя файла и формат и нажмите «▶ Запустить пайплайн». Прогон идёт в фоновом потоке
бэкенда, а раздел опрашивает
статус раз в секунду: видны прогресс по шагам, аргументы и результат каждого шага,
схема потока данных с объёмами на переходах и путь сохранённого файла. Ниже —
история запусков (обновляется раз в 5 секунд) с деталями шагов и кнопкой
«🗑 Удалить запуск».

### Как запустить из чата

Достаточно реплики, в которой есть все три действия — поиск, сводка и
сохранение, например:

> найди статьи про RAG, сделай сводку и сохрани в файл

Агент распознаёт намерение, запускает пайплайн **синхронно** (до проверки лимита
контекста и до шага одиночного MCP-инструмента) и подставляет результат блоком
«## Результат пайплайна» в системный промпт; из реплики берутся запрос (`RAG`),
источник (по умолчанию заметки дня `mcp_server/data/notes.md`) и имя файла
(`rag.md`). Отчёт виден в поле `pipeline` ответа генерации, а в сводке хода
раздела «💬 Чат и память» появляется строка «🔀 Пайплайн: …». Реплика без одной из
трёх групп слов пайплайн не запускает.

### Прогон и отчёт

Четыре сценария задания прогоняются офлайн (без ключа и сети): источник — заметки
дня `mcp_server/data/notes.md`, сводка — агрегация.

```bash
cd day19
uv run python scripts/pipeline_demo.py --report docs/reports/pipeline_demo.md
uv run python scripts/pipeline_demo.py --llm auto --report docs/reports/pipeline_demo.md  # сводка через DeepSeek (нужен ключ в .env)
```

Отчёт — [docs/reports/pipeline_demo.md](docs/reports/pipeline_demo.md): проверки
26 из 26, таблица трёх инструментов, трассировка шагов каждого сценария (колонки
«шаг | инструмент | входные данные | выходные данные | время выполнения |
статус»), содержимое сохранённого файла, схема двух таблиц пайплайна и раздел
«что осталось за рамками дня».

### Эндпоинты `/pipelines`

```bash
curl -X POST http://127.0.0.1:8000/pipelines/run -H "Content-Type: application/json" -d "{\"initial_args\": {\"query\": \"RAG\", \"source\": \"file:mcp_server/data/notes.md\"}, \"background\": false}"
curl "http://127.0.0.1:8000/pipelines/runs?status=completed&limit=10"
curl http://127.0.0.1:8000/pipelines/runs/1
curl http://127.0.0.1:8000/pipelines/runs/1/steps
curl -X DELETE http://127.0.0.1:8000/pipelines/runs/1
```

| Метод и путь | Что делает |
|---|---|
| `POST /pipelines/run` | запускает пайплайн: без тела — встроенный `search-summarize-save`; `background: true` (по умолчанию) — фоновый поток и статус `running`, `background: false` — синхронно и сразу с полным отчётом |
| `GET /pipelines/runs?status=&limit=` | список запусков (свежие первыми) с фильтром по статусу |
| `GET /pipelines/runs/{run_id}` | отчёт запуска: сам запуск, шаги, `failed_at_step`, `message`, `error` |
| `GET /pipelines/runs/{run_id}/steps` | только шаги запуска |
| `DELETE /pipelines/runs/{run_id}` | удаляет запуск вместе с шагами (каскад) |

Ошибки: 400 — невалидная конфигурация пайплайна или неизвестный фильтр статуса,
404 — запуска нет, 422 — невалидное тело. Подробности — [docs/api.md](docs/api.md).

## Что нового относительно дня 17

| Новое | Где |
|---|---|
| Тип расписания, состояния задачи и напоминания, коды причин отказа, фазы запуска и подписи для интерфейса | `backend/domain/scheduler_values.py` |
| Две стейт-машины: состояние задачи (`active → paused → active`, `active → completed`) и состояние напоминания (`scheduled → done`), отказ `UnknownSchedulerEvent` | `backend/domain/scheduler_fsm.py` |
| Единственный источник правды о трёх инструментах: аргументы, их проверка, расписание «по инструменту», отказ данными (`ScheduleRejected`) | `backend/domain/schedule_spec.py` |
| Формы расписания (`date`/`interval`/`cron`), нормализация cron-строки, расчёт ближайшего запуска и подпись расписания | `backend/domain/schedule_timing.py` |
| Агрегация накопленных записей: числовые поля (`count`/`avg`/`min`/`max`), категориальные (`unique` + примеры) и текст сводки | `backend/domain/aggregation.py` |
| Распознавание реплик трёх инструментов: «напомни через 5 минут», «собирай данные с URL каждые 10 секунд», «покажи сводку за последний час» | `backend/domain/schedule_intent.py` |
| Отчёт «был ли запланирован фоновый процесс» и блок данных планировщика для системного промпта | `backend/domain/scheduler_prompt.py` |
| Проекции ORM-строк планировщика в словари API/UI (с готовыми `schedule_label` и `allowed_events`) | `backend/storage/scheduler_rows.py` |
| Хранилище задач: создание, список, смена состояния, журнал запусков, просроченные задачи для сверки | `backend/storage/scheduler_store.py` |
| Хранилище накопленного: напоминания, уведомления, собранные записи, сводки | `backend/storage/scheduler_data_store.py` |
| Шесть таблиц планировщика (список — ниже) | `backend/models/scheduler.py` |
| Единственное место, где фон ходит в сеть: JSON по HTTP с таймаутом и пределом тела ответа | `backend/services/source_fetch.py` |
| Действия трёх инструментов: «подготовка» (немедленно при регистрации) и «тик» (по расписанию) | `backend/services/scheduled_jobs.py` |
| Мост к APScheduler: `AsyncIOScheduler`, идентификаторы job'ов, пауза/возобновление, безопасная остановка | `backend/services/apscheduler_bridge.py` |
| `TaskScheduler`: старт и остановка в lifespan, сверка БД ↔ таймеры раз в 5 секунд, регистрация, пауза/возобновление, единая точка тика | `backend/services/scheduler.py` |
| `ScheduleService` — операции уровня инструментов для роутера, интерфейса и MCP-инструментов | `backend/services/schedule_service.py` |
| Четырнадцать эндпоинтов `/scheduler/...` (всего в API дня 78 — с пятью эндпоинтами пайплайна дня 19) и общий код-путь `POST /scheduler/tasks` | `backend/api/scheduler.py`, `backend/schemas/scheduler.py` |
| Жизненный цикл вынесен из `main.py`: таблицы → агенты → планировщик, на выходе планировщик → MCP | `backend/api/lifespan.py` |
| Три новых инструмента (`schedule_reminder`, `collect_data`, `generate_summary`), HTTP-клиент бэкенда дня и структуры ответов | `mcp_server/server.py`, `mcp_server/backend_api.py`, `mcp_server/schemas.py` |
| Раздел «🗓 Планировщик» (задачи, форма, напоминания, сводки, история запусков) и уведомления в области чата | `frontend/scheduler_api.py`, `frontend/scheduler_section.py`, `frontend/notifications.py` |
| Шаг планировщика в агенте: вызов инструмента по реплике и поле `record["schedule"]` ответа генерации | `backend/agents/agent.py`, `backend/domain/scheduler_prompt.py` |
| Сквозной прогон четырёх сценариев, сборка отчёта и изолированный стенд бэкенда с офлайн-источником | `scripts/scheduler_demo.py`, `scripts/scheduler_scenarios.py`, `scripts/scheduler_report.py`, `scripts/scheduler_stand.py` |
| Новые тесты: домен (5 файлов, 90 кейсов), сервисы и MCP (6 файлов, 45), e2e (1 файл, 17); фейки планировщика и стенд бэкенда | `tests/unit/test_scheduler_fsm.py`, `test_schedule_spec.py`, `test_aggregation.py`, `test_schedule_intent.py`, `test_scheduler_prompt.py`, `tests/integration/test_scheduler_*.py`, `tests/integration/test_mcp_scheduler_tools.py`, `tests/e2e/test_scheduler_api.py`, `tests/scheduler_fakes.py`, `tests/backend_stub.py` |
| Отчёт дня | `docs/reports/scheduler_demo.md` |

Наследовано из дня 17 (описано ниже как есть): свой MCP-сервер по stdio и вызов
его инструментов — `get_user`, `get_post`, `list_user_posts`; правила допуска
вызова и стейт-машина `MCPToolCallFSM`; шаг MCP в агенте; каталог серверов и
раздел «🔌 MCP». Из дня 15 — контролируемые переходы состояния задачи с журналом
отклонённых попыток; из дня 14 — инварианты проекта; из дня 13 — состояние задачи
как конечный автомат; из дней 11–12 — три слоя памяти, четыре стратегии контекста,
сжатие в конспект, ветки, факты, метрики токенов и персонализация профилем
пользователя.

## Что нового относительно дня 16

| Новое | Где |
|---|---|
| Свой MCP-сервер по stdio: три инструмента — `get_user`, `get_post`, `list_user_posts` — поверх jsonplaceholder | `mcp_server/config.py`, `mcp_server/api_client.py`, `mcp_server/server.py` |
| `TypedDict`-структуры ответов: из них SDK собирает `outputSchema`, а `structuredContent` ответа равен самому словарю | `mcp_server/schemas.py` |
| Ошибка внешнего API — понятный текст в результате инструмента с `isError` (404 объясняет, сколько id у jsonplaceholder) | `mcp_server/api_client.py`, `mcp_server/server.py` |
| Вызов инструмента: `MCPClient.call_tool` (`tools/call`) и разбор ответа в `MCPToolResult` | `backend/services/mcp_client.py`, `backend/domain/mcp_tools.py` |
| Адаптеры MCP SDK (транспорт, данные `InitializeResult` и `CallToolResult`) вынесены из клиента отдельным модулем | `backend/services/mcp_transport.py` |
| Цикл событий вынесен в отдельный модуль — клиент не растёт за лимит 400 строк | `backend/services/mcp_loop.py` |
| `MCPRegistry.call_tool` — вызов через единственное соединение процесса | `backend/services/mcp_registry.py` |
| Правила допуска вызова: соединение, инструмент в каталоге, обязательные аргументы, типы по `input_schema`, коды причин отказа | `backend/domain/mcp_tool_call.py` |
| Стейт-машина вызова: `MCPToolCallState`/`MCPToolCallEvent`, граф переходов, `UnknownMCPToolCallEvent` | `backend/domain/mcp_tool_call.py` |
| Распознавание запроса к инструменту по реплике: приоритет правил, морфология, номер аргумента | `backend/domain/mcp_intent.py` |
| Блок данных инструмента для системного промпта | `backend/domain/mcp_prompt.py` |
| Каталог известных серверов: свой, fetch, filesystem; `connected` ровно у одной цели | `backend/domain/mcp_servers.py` |
| Раннер вызова: правила допуска → вызов → отчёт-результат | `backend/services/mcp_tool_runner.py` |
| Шаг MCP в агенте: вызов по реплике и блок данных в системном промпте, поле `record["mcp"]` | `backend/agents/agent.py`, `backend/agents/agent_manager.py`, `backend/agents/manager_agents.py` |
| Схемы `MCPCallIn`, `MCPCallResponse`, `MCPCallReportOut`, `MCPServerSchema`, `MCPServersResponse`; `output_schema` в `MCPToolSchema` | `backend/schemas/mcp.py` |
| Эндпоинты `POST /mcp/call` и `GET /mcp/servers` — всего шесть MCP-эндпоинтов | `backend/api/mcp.py` |
| Раздел «🔌 MCP»: каталог серверов, форма аргументов по `input_schema`, результат вызова и блок «🤖 Спросить агента» | `frontend/mcp_call.py`, `frontend/mcp_ask.py`, `frontend/mcp_section.py`, `frontend/mcp_api.py` |
| Сквозной прогон (каталог → три вызова → три отказа → шаг агента) и сборка отчёта | `scripts/mcp_tool_demo.py`, `scripts/mcp_tool_report.py` |
| Локальный HTTP-стенд jsonplaceholder для офлайн-тестов на настоящем stdio | `tests/stub_api.py` |
| MCP-фейки вынесены в отдельный модуль тестов (каталог, фейковый клиент с `call_tool`, журнал вызовов) | `tests/mcp_fakes.py` |
| Настройки дня: цель по умолчанию (свой сервер), цели официального набора, границы имени инструмента | `backend/core/config.py` |
| Отчёт дня | `docs/reports/mcp_tool_demo.md` |

Наследовано из дня 16 (описано ниже как есть): MCP-клиент с каталогом инструментов
(`MCPClient`, `MCPRegistry`, стейт-машина подключения, разбор цели, раздел
«🔌 MCP»); из дня 15 — контролируемые переходы состояния задачи с журналом
отклонённых попыток; из дня 14 — инварианты проекта; из дня 13 — состояние задачи
как конечный автомат; из дней 11–12 — три слоя памяти, четыре стратегии, сжатие в
конспект, ветки, факты, метрики токенов и персонализация профилем пользователя.

Что **сохранено** без изменений: три слоя памяти, четыре стратегии контекста
(`sliding_window`, `sticky_facts`, `branching`, `summary`) с переключателем на
живом агенте, сжатие истории в конспект, факты «ключ: значение», ветвление
(`checkpoints`), метрики токенов, панели краткосрочной/рабочей/долговременной
памяти, селектор задачи, кнопка «🆕 Новая сессия», expander сравнения режимов
сжатия и весь раздел «👤 Профиль пользователя».

## MCP-инструменты

MCP — то, чем день 17 отличался от дня 16. В дне лежит собственный MCP-сервер
(`day19/mcp_server/`, транспорт **stdio**), клиент умеет вызывать его инструменты
(`tools/call`), а агент делает это сам по реплике пользователя. В дне 19 сервер
(имя `day19-pipeline`, версия `1.2.0`) публикует **девять** инструментов: три
прежних читают jsonplaceholder, три ставят фоновые задачи через API дня
(разбор — в разделе
[«Фоновые задачи (планировщик)»](#фоновые-задачи-планировщик)), а три
**композиции** — `search`, `summarize` и `save_to_file` — собирают данные в
пайплайн (разбор — в разделе [«Пайплайны MCP»](#пайплайны-mcp)).

### Свой сервер

| Файл | Что делает |
|---|---|
| `mcp_server/config.py` | адрес внешнего API и бэкенда дня, таймаут, границы `limit` и id, имя/версия сервера, инструкция для модели; пути каталога `output/`, корня источников, базы дня и ключ DeepSeek из `day19/.env` |
| `mcp_server/schemas.py` | `TypedDict`-структуры ответов (`UserInfo`, `PostInfo`, `PostSummary`, `UserPosts`, `ReminderScheduled`, `CollectionStarted`, `SummaryReady`, `SearchResult`, `SummaryResult`, `SavedFile`) — из них SDK собирает `outputSchema` |
| `mcp_server/api_client.py` | `JsonPlaceholderClient` и `ExternalAPIError`: HTTP-запросы к jsonplaceholder (в т.ч. `list_posts`/`list_users` для источника `posts`/`users`) и понятные тексты ошибок (404 объясняет границы id) |
| `mcp_server/backend_api.py` | `ScheduleBackendClient` и `BackendAPIError`: `POST /scheduler/tasks` — тела трёх инструментов планировщика |
| `mcp_server/search_sources.py` | разбор источника (`posts`/`users`/`file:<путь>`/`sqlite:<таблица>`) и поиск элементов; свой отказ `SearchSourceError` |
| `mcp_server/summarize_logic.py` | чистая логика сводки: нормализация стиля, зажим длины, промпт для LLM, разбор ключевых пунктов, агрегация без LLM |
| `mcp_server/llm_client.py` | ленивый клиент DeepSeek: `available()` и `summarize()`; при отсутствии ключа или ошибке — `LLMUnavailable`, шаг переходит к агрегации |
| `mcp_server/file_writer.py` | запись файла в каталог `output/`: проверка формата и имени, замена расширения, `render_content` для `txt`/`md`/`json` |
| `mcp_server/pipeline_tools.py` | три инструмента композиции с докстрингами и регистрация их на сервере (`register_pipeline_tools`) |
| `mcp_server/data/notes.md` | локальные заметки дня — источник `file:` по умолчанию для офлайн-прогона пайплайна |
| `mcp_server/server.py` | регистрация инструментов `@server.tool()`, перевод ошибки внешнего API, бэкенда и инструментов композиции в `ToolError`, разбор аргументов (`--api-base`, `--backend-url`, `--timeout`, `--output-dir`, `--file-root`, `--db-path`, `--llm`), запуск по stdio |

Сервер запускается одной командой из папки дня и общается с клиентом протоколом
JSON-RPC по stdin/stdout:

```bash
cd day19
uv run python mcp_server/server.py                                     # ждёт JSON-RPC на stdin
uv run python mcp_server/server.py --api-base http://127.0.0.1:8765    # стенд вместо живой сети
uv run python mcp_server/server.py --backend-url http://127.0.0.1:8100  # API дня на другом порту
uv run python mcp_server/server.py --llm off --output-dir output --db-path agents.db  # офлайн: сводка агрегацией, файлы в свой каталог
```

Отдельно запускать его для работы приложения не нужно: при подключении по stdio
(цель `uv run python mcp_server/server.py`) реестр бэкенда поднимает сервер
дочерним процессом. Аргумент `--timeout` задаёт таймаут HTTP-запроса к внешнему
API, `--output-dir` — каталог записи `save_to_file`, `--file-root` — корень
источников `file:` (по умолчанию папка дня), `--db-path` — база для источника
`sqlite:`, `--llm off` полностью выключает LLM у `summarize`.

### Инструменты

Аннотации типов дают `inputSchema`, аннотация возврата (`TypedDict`) —
`outputSchema`, а `structuredContent` ответа равен самому словарю. Докстринг
инструмента — его описание для модели. Шесть инструментов унаследованы из дней
17–18, три — новые инструменты композиции:

| Инструмент | Параметры | Возвращает | Что читает |
|---|---|---|---|
| `get_user` | `user_id: int` (обязательный) | `UserInfo`: `id`, `name`, `username`, `email`, `city`, `phone`, `website`, `company` | `GET /users/{id}` |
| `get_post` | `post_id: int` (обязательный) | `PostInfo`: `id`, `user_id`, `title`, `body` | `GET /posts/{id}` |
| `list_user_posts` | `user_id: int` (обязательный), `limit: int = 5` (1…20) | `UserPosts`: `user_id`, `count`, `posts[]` (`id`, `title`) | `GET /posts?userId=N&_limit=K` |
| `schedule_reminder`, `collect_data`, `generate_summary` | см. [«Три инструмента»](#три-инструмента) планировщика | подтверждение постановки задачи | `POST /scheduler/tasks` бэкенда дня |
| `search` | `query: str` (обязательный), `source: str = "posts"`, `limit: int = 5` | `SearchResult`: `query`, `source`, `source_kind`, `count`, `items[]` | лента jsonplaceholder, файл дня или таблица SQLite дня |
| `summarize` | `items: list[dict]` (обязательный), `style: str = "short"`, `max_length: int = 600` | `SummaryResult`: `summary_text`, `key_points[]`, `total_items`, `style_used`, `engine` | DeepSeek, а без ключа — агрегация |
| `save_to_file` | `content: str` (обязательный), `filename: str = "pipeline_result.md"`, `format: str = "md"` | `SavedFile`: `filename`, `filepath`, `size_bytes`, `format`, `saved_at` | каталог дня `output/` |

Подробности о трёх инструментах композиции (источники `search`, форматы и
поведение без ключа) — в разделе [«Пайплайны MCP»](#пайплайны-mcp).

Внешний API — публичный mock [jsonplaceholder.typicode.com](https://jsonplaceholder.typicode.com):
без ключа и регистрации (пользователей 10, постов 100). Если пользователя или
поста с таким id нет, сервер отвечает 404, а инструмент возвращает результат с
`is_error: true` и текстом «у jsonplaceholder 10 пользователей, id от 1 до 10» —
причина доходит до модели и до пользователя, а не теряется в трассировке.

### Как инструмент подключается к агенту

Главное поведение дня — шаг MCP в `Agent.generate` (`apply_mcp_tool`). Перед ним
идёт шаг пайплайна (`apply_pipeline`, разбор — в разделе
[«Пайплайны MCP»](#пайплайны-mcp)): если реплика распознана как запуск пайплайна,
пайплайн выполняется синхронно, а одиночный инструмент уже не вызывается.

1. **распознавание** — `backend/domain/mcp_intent.py` по таблице фраз
   (`INTENT_RULES`) решает, к какому инструменту относится реплика:
   «Какие посты у пользователя 2» → `list_user_posts`, «Найди информацию о
   пользователе с ID 1» → `get_user`, «Покажи пост 3» → `get_post`; номер
   аргумента — первое число в тексте. Реплика без ключевых слов плана не даёт;
2. **допуск** — `MCPToolRunner.call` проверяет соединение, наличие инструмента в
   каталоге, обязательные аргументы и типы по `input_schema`
   (`admission_reason`), а жизненный цикл вызова описан стейт-машиной
   `MCPToolCallFSM` (`idle → planned → invoked → done | failed | rejected`);
3. **вызов** — `MCPRegistry.call_tool` → `MCPClient.call_tool` (`tools/call`);
   ошибка инструмента приходит данными (`is_error`), обрыв связи — исключением;
4. **промпт** — `render_mcp_tool_block` собирает блок «## Данные MCP-инструмента»
   (имя инструмента, JSON аргументов, JSON результата, инструкция «не выдумывать
   поля»), а `_append_system_block` дописывает его в системное сообщение этого же
   запроса. Блок добавляется **после** проверки запроса инвариантами (вызов — это
   HTTP-запрос наружу) и **до** контроля лимита, поэтому добавленные токены
   входят в лимит;
5. **ответ** — `record["mcp"]` содержит состояние вызова, инструмент, аргументы,
   результат, признак ошибки и `added_tokens`; если вызванный инструмент —
   инструмент планировщика, рядом лежит `record["schedule"]` (была ли задача
   поставлена, её расписание и подтверждение) — в интерфейсе это видно в ответе
   блока «🤖 Спросить агента» и строкой в сводке хода раздела «💬 Чат и память».

Неудача вызова ход не роняет: отказ правил (`reason_code`), ошибка инструмента и
обрыв связи попадают в отчёт `mcp`, а генерация идёт как обычно; если вызов не
состоялся, не распознан, отклонён или упал, `record["schedule"] = null`.

### Из интерфейса

Раздел «🔌 MCP» (переключатель вверху страницы): поле «URL или команда запуска
MCP-сервера» (по умолчанию — свой сервер дня,
`uv run python mcp_server/server.py`), селектор транспорта
(`auto`/`stdio`/`sse`/`http`), кнопки «🔌 Подключиться» и «⏏ Отключиться». После
подключения появляется зелёная плашка «сервер, версия, протокол, инструментов: N»,
строка деталей и таблица инструментов `name` / `description` / `input_schema`;
кнопка «🔄 Обновить список инструментов» просит сервер заново (`refresh=true`), а
раскладка «🧾 Полная input_schema инструмента» показывает схему аргументов и
`output_schema` результата. Дальше идут три блока:

* **каталог серверов** — три цели (`GET /mcp/servers`: свой сервер, fetch,
  filesystem), у подключённой видно число инструментов, к остальным можно
  подключиться кнопкой;
* **вызов инструмента вручную** — выбор инструмента, форма аргументов, собранная
  по его `input_schema` (`integer`/`number` → число, `boolean` → флажок,
  `string` → строка, массив/объект → JSON), кнопка «▶ Вызвать инструмент» и
  результат: состояние, длительность, `st.json` данных; ошибка самого инструмента
  показывается предупреждением, отказ запроса (400/409/502) — сообщением;
* **«🤖 Спросить агента»** — тот же вопрос, но через агента: он сам вызывает
  инструмент по реплике и отвечает по полученным данным; в ответе виден блок
  «🔧 MCP-инструмент» с именем, аргументами и состоянием вызова, а если вызов не
  потребовался — честная подпись. В подсказках есть и реплики планировщика
  («Напомни мне через 30 секунд проверить почту», «Собирай данные с … каждые
  10 секунд», «Покажи сводку за последний час»), и реплика пайплайна («найди
  статьи про RAG, сделай сводку и сохрани в файл»), а рядом со сводкой хода
  появляются строки «🗓 Планировщик: …» и «🔀 Пайплайн: …».

Пока соединения нет, раздел показывает подсказку и не рисует пустой список:
«не подключено» и «список пуст» — разные состояния.

### Через API

```bash
curl -X POST http://127.0.0.1:8000/mcp/connect -H "Content-Type: application/json" -d "{\"target\": \"uv run python mcp_server/server.py\"}"
curl http://127.0.0.1:8000/mcp/tools          # {"tools": [...], "count": 9, ...} — три читают jsonplaceholder, три ставят фоновые задачи, три собирают пайплайн
curl http://127.0.0.1:8000/mcp/servers        # каталог серверов, connected ровно у одного
curl -X POST http://127.0.0.1:8000/mcp/call -H "Content-Type: application/json" -d "{\"tool\": \"get_user\", \"arguments\": {\"user_id\": 1}}"
curl -X POST http://127.0.0.1:8000/mcp/disconnect -d "{}"
```

`POST /mcp/call` отвечает 409, если соединения нет, 400 — если инструмента нет в
каталоге или аргументы не подходят по `input_schema` (в теле — текст причины и
код `reason_code`), 502 — если связь оборвалась; ошибка самого инструмента — 200
с `is_error: true`. Подробности — [docs/api.md](docs/api.md).

### Из кода

```python
from backend.services.mcp_client import MCPClient

client = MCPClient("uv run python mcp_server/server.py")
client.connect()                                    # initialize + согласование протокола
for tool in client.list_tools():                    # tools/list: имя, описание и обе схемы
    print(tool.name, tool.input_schema, tool.output_schema)
result = client.call_tool("get_user", {"user_id": 1})   # tools/call
print(result.structured, result.is_error)
client.disconnect()                                 # закрыть соединение и процесс сервера
```

### Что поддерживается

| Транспорт | Цель | Как запускается |
|---|---|---|
| stdio | `uv run python mcp_server/server.py` (свой сервер), `uvx mcp-server-fetch`, `npx -y @modelcontextprotocol/server-filesystem .` | сервер — дочерний процесс, обмен JSON-RPC по stdin/stdout |
| Streamable HTTP | `http://127.0.0.1:9000/mcp` | один HTTP-эндпоинт MCP |
| SSE | `sse://127.0.0.1:9000/sse` | ранний HTTP-транспорт MCP |

Состояние подключения — стейт-машина
(`backend/domain/mcp_connection_fsm.py`): `disconnected → connecting → connected`
и `error` при сбое; повторное отключение — безопасный no-op, обрыв связи переводит
в `error`, а повторное подключение разрешено. `GET /mcp/status` показывает
состояние, сервер, число инструментов, текст последней ошибки и допустимые
события. Состояние **вызова** — своя стейт-машина
(`backend/domain/mcp_tool_call.py`), её состояния видны в ответе `POST /mcp/call`
и в отчёте `mcp`.

Подробности — [docs/architecture.md](docs/architecture.md) (разделы «MCP-сервер и
инструменты» и «MCP-интеграция»), эндпоинты — [docs/api.md](docs/api.md),
доказательства — [docs/reports/mcp_tool_demo.md](docs/reports/mcp_tool_demo.md),
сценарии проверки — [docs/usage.md](docs/usage.md).

## Фоновые задачи (планировщик)

Планировщик — то, чем день 18 отличается от дня 17. Фон живёт **в процессе
бэкенда**: `TaskScheduler` (`backend/services/scheduler.py`) поднимает
`AsyncIOScheduler` в `lifespan` FastAPI и останавливает его при завершении
приложения. Источник правды — таблица `scheduled_tasks`: APScheduler держит
таймеры только в памяти, а планировщик раз в 5 секунд (`SCHEDULER_SYNC_SECONDS`)
сверяет с ней свой набор задач. Поэтому задачи, созданные другим процессом
(MCP-сервером через `POST /scheduler/tasks`), и задачи прошлого запуска
подхватываются сами.

### Три инструмента

Аннотации типов дают `inputSchema`, аннотация возврата (`TypedDict`) —
`outputSchema`; `structuredContent` ответа равен самому словарю. Все три
инструмента видны в каталоге MCP-сервера (`GET /mcp/tools`), в каталоге дня
(`GET /scheduler/tools`) и в форме раздела «🗓 Планировщик».

| Инструмент | Расписание | Что сохраняет | Что возвращает |
|---|---|---|---|
| `schedule_reminder(text, delay_seconds)` | разовое (`date`): через `delay_seconds` секунд | строку в `reminders` (`status = "scheduled"`), задачу в `scheduled_tasks` | `ReminderScheduled`: `task_id`, `reminder_id`, `text`, `remind_at`, `status`, `next_run_at`, `message` |
| `collect_data(source_url, interval_seconds, name)` | периодическое (`interval`): первый запрос сразу, дальше каждые `interval_seconds` | строку в `collected_data` на каждый сбор — JSON-ответ источника | `CollectionStarted`: `task_id`, `name`, `source_url`, `interval_seconds`, `next_run_at`, `records_saved`, `message` |
| `generate_summary(name, interval_seconds)` | периодическое (`interval`): первая сводка сразу за прошедший интервал, дальше каждые `interval_seconds` | строку в `periodic_summaries` — текст, период, число записей и `key_metrics` | `SummaryReady`: `task_id`, `summary_id`, `name`, `period_start`, `period_end`, `total_records`, `summary_text`, `key_metrics`, `next_run_at`, `message` |

Границы аргументов: интервал и задержка — от `SCHEDULE_INTERVAL_MIN = 1` до
`SCHEDULE_INTERVAL_MAX = 86400` секунд, текст напоминания — до
`REMINDER_TEXT_MAX = 500` символов, адрес источника — до `COLLECT_URL_MAX = 500`
и только `http`/`https` (иначе отказ `bad_url`). Проверяет их
`validate_arguments` (`backend/domain/schedule_spec.py`), а расписание «по
инструменту» выбирает `schedule_for`: напоминание — `date`, сбор и сводка —
`interval`.

### Как запланировать задачу

Из интерфейса: раздел «🗓 Планировщик» → форма «Запланировать задачу» →
инструмент, поля его аргументов, необязательное имя задачи, чекбокс «выполнить
сразу при регистрации» и (при желании) переопределение расписания на `interval`
или `cron`. Через API — `POST /scheduler/tasks`:

```bash
curl.exe -X POST http://127.0.0.1:8000/scheduler/tasks -H "Content-Type: application/json" \
  -d "{\"tool\": \"collect_data\", \"arguments\": {\"source_url\": \"https://jsonplaceholder.typicode.com/posts\", \"interval_seconds\": 10, \"name\": \"posts\"}}"
```

```json
{
  "task": {
    "id": 1, "name": "Сбор: posts", "tool_name": "collect_data",
    "arguments": {"source_url": "https://jsonplaceholder.typicode.com/posts",
                  "interval_seconds": 10, "name": "posts"},
    "schedule_type": "interval", "schedule_value": {"seconds": 10},
    "schedule_label": "каждые 10 с", "status": "active",
    "last_run_at": null, "next_run_at": "2026-09-23T10:00:10+00:00",
    "created_at": "2026-09-23T10:00:00+00:00", "allowed_events": ["pause", "complete"]
  },
  "result": {"collection": {"name": "posts", "source_url": "https://jsonplaceholder.typicode.com/posts",
                            "records_saved": 1, "records_in_payload": 100,
                            "collected_id": 1, "last_collected_at": "2026-09-23T10:00:00+00:00"}},
  "immediate": true,
  "message": "Сбор «posts» запущен: первая запись собрана. Задача №1: каждые 10 с",
  "error": null
}
```

`POST /scheduler/tasks` — **общий код-путь дня**: им пользуются и MCP-инструменты
(их тела — один HTTP-вызов этой ручки, `mcp_server/backend_api.py`), и человек в
интерфейсе. Поэтому проверка аргументов, расписание, немедленное действие (фаза
`prepare`) и подтверждение `message` у обоих входов одинаковы. Контракт ошибок:
незнакомый инструмент, негодные аргументы и неразобранное расписание — 400;
отсутствующая задача — 404; пауза не активной задачи и возобновление не стоящей на
паузе — 409; невалидное тело — 422.

### Напоминания и уведомления

`schedule_reminder` создаёт строку в `reminders` со временем `remind_at` и
задачу-таймер на то же время. Когда таймер срабатывает, тик помечает напоминание
выполненным (`reminders.status = "done"`) и кладёт уведомление в таблицу
`notifications` (`kind = "reminder"`, текст «Напоминание: …»). Уведомления
показывает область чата: фрагмент `frontend/notifications.py` раз в 5 секунд
запрашивает `GET /scheduler/notifications?unread_only=true` и рисует каждое
непрочитанное с кнопкой «✔ Прочитано» (`POST /scheduler/notifications/{id}/read`)
— перезагружать страницу не нужно. Уведомление лежит в БД, поэтому переживает
перезапуск приложения.

### Сводка и её метрики

`generate_summary` агрегирует записи `collected_data` за прошедший интервал.
`aggregate_records` (`backend/domain/aggregation.py`) разбирает payload каждой
записи (списки — по элементам, словари — рекурсивно, листья — под именем своего
ключа) и собирает `key_metrics`:

* `period_seconds`, `sources` (имя сбора → число записей) и `payload_types`
  (`list` / `dict` / `scalar`);
* `numeric` — по каждому числовому полю `count`, `avg`, `min`, `max` (`bool` в
  числовые не попадает: в Python он подкласс `int`);
* `categorical` — по каждому строковому полю `unique` (сколько уникальных
  значений) и `samples` (несколько примеров).

Тот же агрегат рендерится в текст (`render_summary_text`) и сохраняется в
`periodic_summaries` вместе с периодом и числом записей. Пустой период — тоже
сводка: `total_records = 0` и строка «За период записей не собрано» (тик
состоялся). В интерфейсе блок «📊 Регулярные сводки» показывает имя, период, число
записей и метрики, а кнопка «📄 Показать текст» выводит текст сводки; рубрика
«🧾 Запуски задачи» показывает журнал запусков (`phase`, `status`, время,
длительность, текст ошибки).

### Пауза, возобновление и удаление

Состояние задачи — конечный автомат (`ScheduledTaskFSM`,
`backend/domain/scheduler_fsm.py`): `active → paused` (событие `pause`),
`paused → active` (`resume`), `active → completed` (`complete`). Недопустимое
событие — например, `resume` из `active` — это `UnknownSchedulerEvent`, который
сервис переводит в `ScheduleRejected`: роутер отдаёт 409, интерфейс показывает
текст. Список задач отдаётся с полем `allowed_events`, поэтому доступные кнопки
рисуются по ответу API, а не по копии правил у интерфейса. Пауза сохраняет момент
следующего запуска (в БД), поэтому возобновление не сдвигает расписание.
`DELETE /scheduler/tasks/{id}` снимает таймер и удаляет задачу вместе с её
журналом запусков.

### Восстановление после перезапуска

При старте `lifespan` вызывает `TaskScheduler.start()`: планировщик поднимает
APScheduler, ставит задачу сверки и вызывает `sync_from_db()`. Сверка делает три
работы: снимает таймеры удалённых задач, ставит таймеры новых активных и
записывает в БД фактическое `next_run_time` (у cron ближайший запуск знает только
APScheduler). Пропущенный запуск «догоняется»: если расчётный момент уже прошёл
(приложение было выключено), задача с расписанием `interval`/`date` выполняется
сразу — напоминание не теряется, а сбор не ждёт целый период
(`SCHEDULER_MISFIRE_GRACE = 60` секунд). Задачи на паузе и выполненные не
регистрируются, а разовая (`date`) задача после успешного тика получает
`status = "completed"` и снимается с обслуживания.

### Таблицы планировщика

| Таблица | Что хранит |
|---|---|
| `scheduled_tasks` | задачи: имя, инструмент, аргументы, тип и значение расписания, состояние, `last_run_at`/`next_run_at`, `created_at` — источник правды о том, что должно работать |
| `task_runs` | журнал запусков: фаза (`prepare`/`tick`), результат (`ok`/`error`), начало, конец, длительность, что сделал инструмент (`detail`) и текст ошибки |
| `reminders` | напоминания: текст, время `remind_at`, состояние (`scheduled`/`done`), связь с задачей |
| `notifications` | очередь уведомлений: вид (`reminder`/`summary`/`error`), текст, связь с задачей, момент прочтения |
| `collected_data` | собранные записи: имя сбора, адрес источника, payload, время сбора |
| `periodic_summaries` | сводки: имя, текст, период, число записей и `key_metrics`, связь с задачей |

Таблица сводок названа `periodic_summaries`, потому что имя `summaries` уже занято
конспектами сжатия истории (день 9, append-only): унаследованную таблицу
переименовывать нельзя, а смешивать в ней две разные сущности — тем более.

### Как это устроено

* **Тик — синхронная функция.** APScheduler 3.x выполняет обычные функции в пуле
  потоков (`AsyncIOExecutor`), поэтому фон не блокирует цикл событий FastAPI —
  требование задания «не блокировать основной поток» выполняется без отдельного
  процесса.
* **`scheduled_tasks` — источник правды, таймеры — в памяти.** APScheduler не
  хранит задачи в БД, поэтому набор таймеров раз в 5 секунд сверяется с таблицей
  (`sync_from_db`); та же сверка подхватывает задачи, созданные другим процессом.
* **Тик не ходит через MCP.** Инструмент вызывается из тика напрямую
  (`scheduled_jobs.tick`), а не через MCP-соединение: соединение принадлежит
  пользователю и держит блокировку клиента, поэтому вызов инструмента из
  фонового потока был бы дедлоком.
* **Единственный писатель в SQLite — бэкенд.** Тела MCP-инструментов планировщика
  не открывают БД, а вызывают `POST /scheduler/tasks`: у ручного создания и у
  вызова из агента один код-путь и нет конкурентных писателей.
* **Ошибка тика не роняет планировщик.** Сбой инструмента ловится в `run_tick`,
  записывается как `task_runs.status = "error"` с текстом, кладёт уведомление
  `kind = "error"` и оставляет задачу активной — следующий тик придёт по
  расписанию.

### Границы

* Планировщик живёт в **одном процессе** бэкенда: второй экземпляр приложения на
  той же БД получит свою копию таймеров (день рассчитан на один процесс и одну
  `day19/agents.db`).
* Доставки уведомлений **вне приложения** нет: уведомление — строка в БД и плашка
  в интерфейсе; писем и сообщений в мессенджеры день не отправляет.
* **cron** доступен только через ручное переопределение расписания
  (`schedule_type: "cron"`, `schedule_value: {"cron": "*/5 * * * *"}`): три
  инструмента создают `date`/`interval`, а cron-выражение разбирает APScheduler.
* Источник сбора — **живой HTTP**: без сети тик получит ошибку и запишет её в
  журнал; офлайн-прогон подменяет источник детерминированным JSON
  (`scripts/scheduler_stand.py`), а тесты — фейком (`tests/scheduler_fakes.py`).

## Что нового относительно дня 14 (унаследовано из дня 15)

| Новое | Где |
|---|---|
| Явный граф допуска переходов между этапами, guards на флаги, тексты отказа и подсказки | `backend/domain/task_state_machine.py` |
| Сброс флагов согласования при движении назад (`cleared_flags`) | `backend/domain/task_state_machine.py` |
| Распознавание предложения модели перейти в этап («задача завершена» → `done`) | `backend/domain/task_proposal.py` |
| Колонка `task_states.paused_from_stage` — этап паузы в отдельном поле, а не в `context` | `backend/models/task_state.py` |
| Колонка `task_transitions.accepted` и nullable `to_stage`/`to_step` — журнал отклонённых попыток | `backend/models/task_state.py` |
| Производные поля состояния `allowed_next`, `blocked`, `prompt_block`; методы `log_rejection`, `set_flags`, параметр `clear_flags` | `backend/storage/task_store.py` |
| Единая точка отказа `_reject` (журнал + исключение), проверки графа и guard в `transition_to`, `pause`, `resume`, `advance`, `rollback`, метод `set_flags` | `backend/services/task_state.py` |
| Отказ на предложение модели и отчёт о применении намерения: `record["task_proposal"]`, `record["task_intent"]` | `backend/agents/agent.py` |
| Схемы `TaskBlockedOut`, `TaskAllowedNextOut`, `TaskFlagsIn`; поле `accepted` в `TaskTransitionOut` | `backend/schemas/task.py` |
| Эндпоинты `GET /tasks/{id}/allowed-next` и `PATCH /tasks/{id}/context` (флаги согласования) | `backend/api/tasks.py` |
| Кнопки-этапы с блокировкой и причиной в подсказке, чекбоксы флагов, пауза с выбором этапа продолжения | `frontend/task_transitions.py` |
| Единый путь мутаций панели задачи `run_task_action` | `frontend/common.py` |
| Офлайн-демонстрация правил допуска, паузы в отдельном процессе и отказа агента | `scripts/controlled_transitions_demo.py`, `scripts/transitions_report.py`, `docs/reports/controlled_transitions_demo.md` |
| Автопроверка кадров сценария видео (HTTP + реальный рендер интерфейса) | `scripts/video_scenario.py`, `scripts/video_scenario_checks.py`, `scripts/video_scenario_client.py`, `scripts/video_scenario_frames.py`, `scripts/video_scenario_ui.py`, `scripts/video_scenario_server.py` |
| Автоматический проход кадров в настоящем браузере с человеческим темпом (`--auto`) | `scripts/video_scenario_browser.py`, `scripts/video_scenario_browser_frames.py`, `playwright` (dev) |

Наследовано из дня 14 (описано ниже как есть): инварианты проекта с проверкой
запроса и ответа; из дня 13 — состояние задачи как конечный автомат, а из
дней 11–12 — три слоя памяти, четыре стратегии, сжатие в конспект, ветки, факты,
метрики токенов и персонализация профилем пользователя.

Что **сохранено** без изменений: три слоя памяти, четыре стратегии контекста
(`sliding_window`, `sticky_facts`, `branching`, `summary`) с переключателем на
живом агенте, сжатие истории в конспект, факты «ключ: значение», ветвление
(`checkpoints`), метрики токенов, панели краткосрочной/рабочей/долговременной
памяти, селектор задачи, кнопка «🆕 Новая сессия», expander сравнения режимов
сжатия и весь раздел «👤 Профиль пользователя».

## Что осталось артефактом дня 11

Сценария дня 11 в `day19/` нет — вместе с ним ушли кнопка его запуска, панель
его итога и захардкоженный набор реплик. Отчёт по трём слоям памяти тоже остался
артефактом дня 11 —
[`../day11/memory_layers_comparison.md`](../day11/memory_layers_comparison.md).
В `day19/` диалог ведётся вручную в чате, а доказательства дают
[`docs/reports/controlled_transitions_demo.md`](docs/reports/controlled_transitions_demo.md) (контролируемые переходы),
[`docs/reports/task_state_demo.md`](docs/reports/task_state_demo.md) (состояние задачи) и унаследованный
[`docs/reports/personalization_comparison.md`](docs/reports/personalization_comparison.md) (персонализация).

## Контролируемые переходы

Правила допуска переходов живут в **одном** модуле —
`backend/domain/task_state_machine.py`. Он отвечает на три вопроса: какие
переходы вообще существуют (граф), при каких условиях они разрешены (guards) и
что именно сказать пользователю, если переход отклонён (тексты отказа и
подсказки). Классы-этапы (`backend/domain/task_fsm.py`) обрабатывают только
события и шаги ВНУТРИ этапа.

### Граф `ALLOWED_TRANSITIONS`

| Этап | Куда можно перейти |
|---|---|
| `planning` | `execution`, `paused` |
| `execution` | `validation`, `planning` (откат), `paused` |
| `validation` | `done`, `execution` (откат), `paused` |
| `done` | никуда: этап терминальный, переходов из него нет вовсе (даже в `paused`) |
| `paused` | `planning`, `execution`, `validation` |

Всё, чего нет в таблице, отклоняется: `planning → done` — это пропуск двух
этапов, `validation → planning` — перескок назад через этап, а `paused → done`
невозможен, потому что из паузы возвращаются только в три этапа прямого хода.

### Guards: флаги согласования

Три перехода прямого хода требуют явного согласия пользователя — флага в
`context` задачи:

| Переход | Флаг в `context` | Текст отказа |
|---|---|---|
| `planning → execution` | `plan_approved` | «Нельзя перейти в execution: план не утверждён» |
| `execution → validation` | `implementation_complete` | «Нельзя перейти в validation: реализация не завершена» |
| `validation → done` | `validation_passed` | «Нельзя перейти в done: валидация не пройдена» |

Флагом считается только логическое `True` (строка `"true"` — нет). Флаги
выставляются **явно**: `PATCH /tasks/{id}/context` или чекбоксы «📝 План
утверждён», «⚙️ Реализация завершена», «✅ Валидация пройдена» в панели задачи;
реплика пользователя флаг не подставляет. Выход из паузы проверяется отдельным
guard: по умолчанию задача возвращается в свой этап (`paused_from_stage`),
явный переход в другой доступный этап разрешён только если он достижим из этапа
паузы.

Движение **назад** сбрасывает согласования: переход в более ранний этап
(`rollback` или кнопка-этап) очищает флаг этапа-цели и всех последующих этапов
прямого хода (`cleared_flags`). Иначе после возврата назад задача пересекла бы
границу на основании устаревшего согласования.

### Отказ с объяснением

Отклоняет переход сервис `TaskStateMachine` — через единую точку `_reject`,
которая пишет строку в журнал и поднимает `InvalidTransitionError`
(переименованное `InvalidTaskTransition` дня 13). Порядок проверок в
`transition_to`: понятен ли этап → граф и guard → принадлежит ли шаг этапу →
корректно ли ожидаемое действие. Примеры текстов:

```
Нельзя перейти из planning в done: пропущены этапы execution и validation
Нельзя перейти в execution: план не утверждён
Нельзя перейти из done: этап done терминальный
Нельзя перейти из paused в done: из паузы возвращаются только в planning, execution или validation
Неизвестный этап задачи: 'нет-такого'. Допустимые: planning, execution, validation, done, paused
```

Короткая причина идёт в журнал (`task_transitions.reason`), в `blocked[].reason`
(подсказка недоступной кнопки) и в `detail` ответа 400; полная подсказка «что
сделать» добавляется в `detail` эндпоинта `POST /tasks/{id}/transition` и в
ответ агента.

Допустимый переход — `validation → done` после флага `validation_passed`:

```bash
curl.exe -X PATCH http://127.0.0.1:8000/tasks/tz/context ^
  -H "Content-Type: application/json" -d "{\"validation_passed\": true}"
curl.exe -X POST http://127.0.0.1:8000/tasks/tz/transition ^
  -H "Content-Type: application/json" -d "{\"stage\": \"done\"}"
```

Недопустимый переход из `planning` в `done` — 400 с причиной и подсказкой:

```
"Нельзя перейти из planning в done: пропущены этапы execution и validation Сначала перейдите в execution и пройдите этапы по порядку."
```

### Журнал попыток

`task_transitions` хранит и **отклонённые** попытки: у них `accepted = False`,
`to_stage`/`to_step` могут быть пустыми, а в `reason` лежит короткая причина
отказа. Состояние задачи при этом не меняется. В интерфейсе это отдельная
вкладка «🚫 Попытки недопустимых переходов»; API отдаёт их тем же
`GET /tasks/{id}/history` с полем `accepted`.

### Предложение модели

Ответ модели тоже проверяется: `backend/domain/task_proposal.py` распознаёт по
таблице фраз предложение перейти в этап («задача завершена, можно сдавать» →
`done`, «перехожу к тестам» → `validation`) и берёт **самый дальний** этап, если
подходящих фраз несколько. Если такой переход недопустим, ответ заменяется
отказом:

```
🚧 Ответ предлагает переход в done, но это недопустимо. Нельзя перейти в done: валидация не пройдена Отметьте флаг «✅ Валидация пройдена» в панели задачи.
```

Упоминание текущего этапа («приступаю к реализации» на этапе `execution`)
предложением не считается. **Допустимое** предложение тоже ничего не меняет:
этапы двигает пользователь кнопкой или репликой-намерением, а проверка лишь не
даёт модели выдать ответ, противоречащий состоянию задачи. Неприменённое
намерение реплики даёт более мягкое уведомление перед ответом:

```
⚠️ Переход по реплике «advance» не выполнен: Нельзя перейти в execution: план не утверждён Доступные следующие этапы: paused.
```

### Доказательство

[`docs/reports/controlled_transitions_demo.md`](docs/reports/controlled_transitions_demo.md)
— офлайн-прогон (без ключа и сети) в два процесса: таблица «Попытка перехода →
допустимость → причина отказа → что предложил агент → как продолжил после
паузы», продолжение паузы в новом процессе и выборка отклонённых попыток из
журнала.

```bash
cd day19
uv run python scripts/controlled_transitions_demo.py            # прогон и отчёт
uv run python scripts/controlled_transitions_demo.py --phase 2  # только фаза 2
uv run python scripts/controlled_transitions_demo.py --reset    # очистить прогон
```

## Состояние задачи

### Таблица `task_states`

Одна строка на задачу в той же базе `day19/agents.db`. `task_id` уникален
глобально: состояние запрашивается по нему одному (`GET /tasks/{task_id}/state`)
и на него ссылается журнал переходов.

| Колонка | Тип | Смысл |
|---|---|---|
| `id` | Integer, primary key, autoincrement | ключ строки |
| `task_id` | String(64), unique, index, NOT NULL | идентификатор задачи |
| `agent_id` | String, FK → `agents.agent_id` (CASCADE), NOT NULL | чей агент ведёт задачу |
| `stage` | String(32), index, NOT NULL | этап: `planning` / `execution` / `validation` / `done` / `paused` |
| `current_step` | String(32), NOT NULL | шаг внутри этапа |
| `expected_action` | String(500), NOT NULL | чего ждём на этом шаге |
| `context` | JSON, NOT NULL | снимок данных задачи: `task_id`, `working_memory`, флаги согласования (`plan_approved`, `implementation_complete`, `validation_passed`) |
| `paused_from_stage` | String(32), NULL | этап, с которого задача встала на паузу; NULL у активной задачи |
| `history` | JSON, NOT NULL | журнал переходов внутри строки (та же информация, что в `task_transitions`) |
| `created_at` | DateTime(tz) | создание (UTC) |
| `updated_at` | DateTime(tz) | последний переход (UTC) |

`context.working_memory` — снимок рабочей памяти дня 11 по паре
`(agent_id, task_id)`, перечитывается на каждом переходе: состояние задачи и
данные задачи читаются вместе. Этап паузы живёт в **отдельной колонке**
`paused_from_stage` (день 15): именно оттуда `resume` и guard выхода из паузы
узнают, куда возвращаться, и это же значение переживает перезапуск процесса.
В `context` остались только `task_id`, `working_memory` и флаги согласования.

### Этапы, шаги и переходы

| Этап | Шаги |
|---|---|
| `planning` | `gather_requirements`, `define_scope`, `create_plan` |
| `execution` | `implement`, `test_locally` |
| `validation` | `review`, `run_tests`, `finalize` |
| `done` | шагов нет (у завершённой задачи `current_step` остаётся `finalize`) |
| `paused` | шагов нет (сохраняется тот шаг, на котором встали) |

```
прямой ход:    planning -> execution -> validation -> done
откат:         execution -> planning;  validation -> execution
пауза:         planning|execution|validation -> paused
возобновление: paused -> planning|execution|validation (по умолчанию — этап паузы)
терминал:      done -> переходов нет
guards:        planning->execution: plan_approved
               execution->validation: implementation_complete
               validation->done: validation_passed
```

События — `advance`, `rollback`, `pause`, `resume` (`backend/domain/task_fsm.py`).
У каждого события в конкретном этапе ровно один результат; всё, что не описано,
— явная ошибка: `UnknownTaskEvent` для события, которого у этапа нет, и
`InvalidTransitionError` для недопустимого перехода (`planning → done`,
`rollback` из `planning`/`done`/`paused`, `advance` после `done`, пауза из
`done`). Классы-этапы знают только события и шаги ВНУТРИ этапа, а таблица
допуска переходов между этапами и guard-условия живут в
`backend/domain/task_state_machine.py` — см. «Контролируемые переходы».
`test_task_fsm.py` параметризует все 20 пар «этап × событие», а
`test_task_state_machine.py` проверяет граф, guards и тексты отказа.

### Таблица `task_transitions`

Журнал переходов: по строке на переход. У строки создания задачи
`from_stage`/`from_step` пусты.

| Колонка | Тип | Смысл |
|---|---|---|
| `id` | Integer, primary key, autoincrement | порядок перехода |
| `task_id` | String(64), FK → `task_states.task_id` (CASCADE), index, NOT NULL | чей переход |
| `from_stage` / `from_step` | String, NULL | откуда (NULL у создания) |
| `to_stage` / `to_step` | String, NULL | куда (NULL у отклонённой попытки: перехода не было) |
| `accepted` | Boolean, NOT NULL, по умолчанию `True` | `True` — переход выполнен, `False` — попытка отклонена и записана в журнал |
| `reason` | String(200), NOT NULL | «задача создана», «следующий шаг», «пауза», «продолжение после паузы», «откат на предыдущий этап», «задача завершена», «откат по реплике пользователя», «переход по запросу», а у отклонённой попытки — причина отказа |
| `created_at` | DateTime(tz) | когда (UTC) |

### Блок состояния в системном промпте

Состояние подключается **последним** блоком системного сообщения каждого
запроса — после профиля, роли агента и блоков памяти. Формат фиксирован:
заголовок и одна строка.

```
Состояние задачи (текущий этап и шаг; продолжай с этого места):
Текущий этап задачи: execution. Допустимые следующие этапы: planning, paused. Ожидаемое действие: ожидается реализация модуля. Не пытайся перейти в недопустимый этап — сначала заверши текущий. Текущий шаг: implement. Предыдущие шаги: planning (gather_requirements, define_scope, create_plan) — завершены.
```

Список допустимых этапов считается по графу и guards (день 15): у только что
заведённой задачи это `paused` (план ещё не утверждён), у завершённой — `нет`,
потому что из терминального этапа переходов нет.

Именно поэтому после перезапуска процесса агенту не нужно объяснять, где он
остановился: блок читается из SQLite на каждый запрос (`Agent.task_state_block`),
а `record["task_state"]` и `record["system_prompt"]` заполняются ДО вызова
DeepSeek — они видны и при 502.

### Авто-обновление по реплике

`Agent.apply_task_intent(prompt)` вызывается до сборки контекста, поэтому блок в
промпте описывает уже новое состояние. Приоритет групп фиксирован: пауза →
продолжение → откат → подтверждение.

| Намерение | Фразы | Что делает |
|---|---|---|
| `pause` | «пауза», «паузу», «поставь на паузу», «поставь задачу на паузу», «останови задачу», «приостанови» | задача встаёт в `paused`, шаг сохраняется |
| `resume` | «продолжи», «продолжить», «продолжаем», «возобнови», «с того же места» | возврат на сохранённый этап и шаг |
| `rollback` | «откат», «откатись», «вернись на предыдущий», «вернись к предыдущему» | откат на один этап назад с шагом на первый шаг этапа |
| `advance` | «подтверждаю», «подтверждаю план», «шаг выполнен», «выполнено», «готово», «следующий шаг», «дальше» | следующий шаг (с последнего шага этапа — следующий этап) |

Совпадение ищется на границе слова, поэтому «продолжительность сессии» — не
намерение, а «продолжи» — намерение. Недопустимый для текущего этапа переход не
роняет диалог: он пишется в журнал `task_transitions` со `accepted = False`,
запрос выполняется как обычно, а перед ответом появляется уведомление
«⚠️ Переход по реплике … не выполнен: …». Например, «подтверждаю» на последнем
шаге планирования не сработает, пока не выставлен флаг `plan_approved`. Задача в
`done` репликами не воскрешается.

`apply_task_intent` возвращает отчёт `{"intent", "applied", "reason",
"allowed_next"}` — он уходит в `record["task_intent"]` ответа генерации. Рядом
лежит `record["task_proposal"]` — предложение самого ответа модели, отклонённое
правилами (см. «Контролируемые переходы»).

### Эндпоинты состояния задачи

| Метод и путь | Что делает |
|---|---|
| `POST /agents/{agent_id}/tasks` | создаёт состояние задачи (`TaskCreateIn`: `task_id`, `initial_stage`), делает задачу активной у агента; повторный `task_id` → 409 |
| `GET /agents/{agent_id}/tasks` | незавершённые задачи агента (пауза считается активной) |
| `GET /tasks/{task_id}/state` | `TaskStateOut`: этап, шаг, ожидаемое действие, `rollback_stage`, `paused_from_stage`, `is_active`, `prompt_block`, `allowed_next`, `blocked` |
| `GET /tasks/{task_id}/allowed-next` | `TaskAllowedNextOut`: `task_id`, `stage`, `allowed_next`, `blocked` — что доступно сейчас и почему остальное нельзя |
| `GET /tasks/{task_id}/history` | `TaskHistoryOut`: все переходы по возрастанию id, включая создание и отклонённые попытки (`accepted`) |
| `POST /tasks/{task_id}/pause` | пауза (этап уходит в `paused_from_stage`, шаг сохраняется); повторная → 400 |
| `POST /tasks/{task_id}/resume` | продолжение в `paused_from_stage`; не на паузе → 400 |
| `POST /tasks/{task_id}/advance` | следующий шаг; выход из этапа без флага согласования → 400 с объяснением |
| `POST /tasks/{task_id}/rollback` | откат на предыдущий этап (`to_stage` обязан совпасть с целью, иначе 400); сбрасывает флаги |
| `PATCH /tasks/{task_id}/context` | флаги согласования (`TaskFlagsIn`: `plan_approved`, `implementation_complete`, `validation_passed`); тело без единого флага → 422 |
| `POST /tasks/{task_id}/transition` | прямой переход в этап/шаг: проверяет граф и guard, при отказе 400 с причиной и подсказкой; умолчания (`step`, `expected_action`, `reason`) разрешает `TaskStateMachine` |

Ошибки: 404 — нет задачи или агента, 400 — недопустимый переход, 409 — повторный
`task_id`, 422 — невалидное тело (в том числе пустое тело флагов и неизвестный
этап в `transition`). Кнопка-этап `done` в интерфейсе — это один вызов
`POST /tasks/{task_id}/transition` с телом `{"stage": "done"}`; подсказку
«что сделать» роутер добавляет к `detail` ответа 400.

### Раздел «🧭 Состояние задачи» в интерфейсе

Третий раздел основной области (`st.radio`, ключ `main_section`). Показывает
подпись «задача · агент · обновлено», текущий этап и шаг, ожидаемое действие,
строку о паузе, строку «Допустимые следующие этапы», ASCII-схему переходов и
блок переходов (`frontend/task_transitions.py`): кнопка на каждый этап
(`planning`, `execution`, `validation`, `done`, `paused`) — недоступные
заблокированы (`disabled`), а причина отказа видна в подсказке кнопки; рядом
раскрывающийся список причин «🔒 Заблокированные переходы», кнопка
«⏭ Следующий шаг», пауза и продолжение (на паузе — выбор этапа возврата) и
чекбоксы трёх флагов согласования с кнопкой «💾 Сохранить флаги». Все мутации
идут одним путём — `common.run_task_action`. Ниже — вкладки: «📜 Журнал переходов»
(таблица «из → в, причина, время», только `accepted = True`), «🚫 Попытки
недопустимых переходов» (`accepted = False`: этап, шаг, цель, причина отказа,
время) и блок состояния ровно в том виде, в каком он уходит в системный промпт.
Если состояния у активной задачи ещё нет, панель предлагает его завести формой
(`task_id` + начальный этап).

### Демонстрация: `docs/reports/task_state_demo.md`

[`docs/reports/task_state_demo.md`](docs/reports/task_state_demo.md) — унаследованное от дня 13 доказательство:
состояние задачи и этап паузы переживают перезапуск процесса. Скрипт прогоняет
пять фаз, каждая в **отдельном процессе** (`subprocess`), и дописывает раздел с
таблицей переходов, ответом агента, блоком состояния из системного промпта и
строкой-доказательством «новый процесс (pid …), состояние прочитано из
`task_state_demo.db`»:

1. постановка задачи, реплика «подтверждаю», шаг вперёд и реплика «поставь
   задачу на паузу» → `paused/create_plan`;
2. новый процесс читает `paused/create_plan`, реплика «продолжи» возвращает
   задачу на сохранённый шаг, затем флаг `plan_approved` и шаг вперёд →
   `execution/implement`;
3. новый процесс: флаг `implementation_complete` и реплика «готово» →
   `validation/review`;
4. новый процесс: откат на `execution` (флаги согласования сброшены), снова
   `implementation_complete`, возврат до `validation/finalize`, флаг
   `validation_passed` и завершение задачи → `done/finalize`;
5. новый процесс: чтение итога, полный журнал переходов и подтверждение, что
   задача ушла из списка активных.

Флаги в фазах 2–4 выставляются явно (`set_task_flags`): с дня 15 выход из этапа
закрыт guard-условием, поэтому демонстрация дня 13 показывает заодно и это
правило.

```bash
cd day19
uv run python scripts/task_state_demo.py --all           # нужен DEEPSEEK_API_KEY в day19/.env
uv run python scripts/task_state_demo.py --all --no-api  # офлайн-заглушка, без сети
uv run python scripts/task_state_demo.py --phase 2       # одна фаза
uv run python scripts/task_state_demo.py --reset         # очистить демо-БД и отчёт
```

Скрипт работает на отдельной базе `day19/task_state_demo.db`, заводит агента
`demo15` («Демо-агент дня 17») и задачу `tz-portal` и переиспользует
офлайн-заглушку `comparison_stub.StubClient`.

## Инварианты

Инвариант — правило проекта, которое агент не имеет права нарушать. Правила
хранятся в **отдельной таблице** `invariants` (не в истории сообщений и не в
промпте агента): их не вымывает сжатие контекста, они одинаковы для всех агентов
и видны в системном промпте каждого запроса. Инварианты описывают проект, а не
агента, поэтому таблица глобальная — без `agent_id`.

### Категории

| Значение | Подпись в UI | Пример правила |
|---|---|---|
| `architecture` | архитектура | «Используем только FastAPI и Streamlit; никаких Flask, Django, Bottle или Tornado» |
| `tech_decisions` | технические решения | «Состояние задачи хранится в SQLite, а не в Redis, Memcached, MongoDB или Kafka» |
| `stack_constraints` | ограничения стека | «Только Python: без JavaScript, TypeScript и их фреймворков (Node.js, React, Vue, Angular)» |
| `business_rules` | бизнес-правила | «Платные API — только с явного согласия пользователя» |

Неизвестная категория — не «тихое» значение по умолчанию, а ошибка домена:
`InvariantValueError` → HTTP 422 (`category_from_value`,
`backend/domain/invariant_values.py`).

### Важность: `hard` и `soft`

| Важность | Что делает агент при нарушении |
|---|---|
| `hard` | **Отказывается** и объясняет, какое правило нарушено; DeepSeek при отказе запроса не вызывается вовсе (токены не тратятся) |
| `soft` | **Предупреждает**, но решение предлагает: ответ начинается с «⚠️ Предупреждение…» и строк нарушений |

Включить/выключить правило можно без удаления (`is_active`): выключенное правило
не уходит в промпт и не проверяется, но остаётся в таблице — его можно вернуть
одной кнопкой.

### Как это работает

Порядок проверки — от дешёвого к дорогому:

1. **Запрос пользователя проверяется до вызова DeepSeek** — только
   детерминированными правилами: очевидное («давай перепишем на Flask») ловится
   без сети и без токенов, нарушение hard-инварианта останавливает ход.
2. **Ответ модели проверяется после генерации** — тоже сначала правилами, и лишь
   если правила молчат, делается **один** вызов LLM: `InvariantChecker` отдаёт
   модели список активных правил и текст, а в ответ ждёт строгий JSON
   `{"violations": [{"name", "reason"}]}`. Категория и важность нарушения берутся
   из инварианта, а не из ответа модели.
3. **Вердикты объединяются** (`merged_with`): нарушение из запроса не теряется из-за
   чистого ответа, одно правило не попадает в отказ дважды, жёсткое нарушение в
   ответе побеждает мягкое в запросе.
4. **Итог** — `allowed` (нарушений нет), `warning` (только soft) или `refusal`
   (есть hard). При отказе ответ заменяется текстом отказа, при предупреждении
   текст отказа добавляется перед ответом модели; в диалог сохраняется именно то,
   что увидел пользователь.

Сбой LLM-слоя проверку не ломает: вердикт правил остаётся, а причина («проверка
LLM не выполнена: …») попадает в поле `note` — ход диалога не срывается.
`compare_modes` (служебное сравнение режимов контекста) инварианты не проверяет:
это не ход диалога.

Детерминированные правила привязаны к описанию инварианта: правило действует,
только если сам инвариант называет средство. Поэтому «Только Python, без
JavaScript…» ловит слово `JavaScript` в тексте, но не мешает правилу про Flask.
Согласие пользователя снимает нарушение бизнес-правила, а отрицание согласия
(«согласие пользователя не нужно») — нет.

### Блок в системном промпте

Блок идёт сразу после роли агента (до памяти, конспекта, фактов и состояния
задачи) — правила проекта сильнее любых пожеланий в диалоге:

```text
Ты обязан соблюдать следующие инварианты:
- [hard] Только FastAPI и Streamlit (architecture): Используем только FastAPI и Streamlit; никаких Flask, Django, Bottle или Tornado
- [soft] Платные API — только с согласия (business_rules): Агент не должен предлагать решения, которые требуют платных API без явного согласия пользователя

Если запрос пользователя или твоё предлагаемое решение нарушает хотя бы один из них, ты обязан отказаться и объяснить причину.
```

При пустой таблице (или когда все правила выключены) блок не добавляется вовсе —
поведение агента совпадает с днём 13, лишних вызовов проверки не появляется.

### Эндпоинты инвариантов

| Метод и путь | Что делает | Коды ошибок |
|---|---|---|
| `POST /invariants` | создаёт правило (сразу активное) | 409 — имя занято, 422 — категория/важность |
| `GET /invariants` | список по алфавиту; `category`, `active_only` | 422 — неизвестная категория |
| `GET /invariants/{id}` | одно правило | 404 |
| `PUT /invariants/{id}` | меняет переданные поля (в т.ч. `is_active`) | 404, 409, 422 |
| `DELETE /invariants/{id}` | удаляет правило | 404 |
| `POST /invariants/check` | проверяет текст как ход агента (`use_llm`) | 422 — пустой текст |

### Раздел «📏 Инварианты» в интерфейсе

Четвёртый раздел основной области: таблица правил с фильтрами по категории и
активности, форма «➕ Добавить инвариант», блок «✏️ Редактировать» (правка полей,
кнопка «⏸ Деактивировать»/«▶️ Активировать», «🗑 Удалить») и блок «🔎 Проверка
текста на инварианты» — тот же путь, что у агента: правила, затем при
неоднозначности LLM. В разделе «💬 Чат и память» предупреждение или отказ по
последнему ходу показывается над полем ввода, а вердикт — в сводке хода.

### Посев правил и отчёт

```bash
cd day19
uv run python scripts/seed_invariants.py            # 4 демо-правила в day19/agents.db
uv run python scripts/seed_invariants.py --reset    # пересобрать список
uv run python scripts/invariants_demo.py            # отчёт invariants_demo.md
```

`seed_invariants.py` идемпотентен (существующие имена не дублируются) и работает
без сети. `invariants_demo.py` прогоняет три сценария офлайн — на своей БД
`invariants_demo.db`, с заглушкой DeepSeek и выключенным LLM-слоем проверки,
поэтому результат воспроизводим и не зависит от ключа: разрешённый запрос
проходит как обычно, soft-нарушение даёт предупреждение, hard-нарушение — отказ
**без обращения к модели**. Отчёт — [`invariants_demo.md`](invariants_demo.md).

## Персонализация (наследовано из дня 12)

### Таблица `user_profiles`

Профиль — одна строка на пользователя в той же базе `day19/agents.db`:

| Колонка | Тип | Смысл |
|---|---|---|
| `id` | Integer, primary key, autoincrement | ключ строки |
| `user_id` | String(64), unique, index, NOT NULL | идентификатор пользователя |
| `name` | String(100), NOT NULL | имя для обращения |
| `preferences` | JSON, NOT NULL | tone / verbosity / language / format |
| `constraints` | JSON, NOT NULL | max_response_length / forbidden_topics / required_disclaimers |
| `custom_instructions` | Text, NOT NULL | произвольные инструкции, одна на строку |
| `created_at` | DateTime(tz) | создание (UTC) |
| `updated_at` | DateTime(tz) | последнее изменение (UTC) |

Агент ссылается на профиль колонкой `agents.user_id` (String(64), index,
NOT NULL, по умолчанию `"default"`). Внешнего ключа между таблицами **нет
намеренно**: удаление профиля не должно уносить агентов — они просто теряют
персонализацию.

### Поля и допустимые значения

`preferences` — четыре поля с фиксированными значениями (`Enum` в
`backend/domain/profiles.py`). Пустое значение (`None`) означает «не настроено», такая
строка в промпт не попадает. В промпт уходит готовый текст:

| Поле | Значение | Текст в промпте |
|---|---|---|
| `tone` | формальный | Стиль общения: формальный — на «Вы», без сленга и эмодзи, официальные формулировки. |
| `tone` | дружелюбный | Стиль общения: дружелюбный — тепло и просто, уместны эмодзи и обращение к собеседнику напрямую. |
| `tone` | технический | Стиль общения: технический — точные термины и конкретика, без вводных фраз, эмодзи и «воды». |
| `verbosity` | кратко | Длина ответа: кратко — только суть, без прелюдий и повторов. |
| `verbosity` | подробно | Длина ответа: подробно — с пояснениями, примерами и обоснованием. |
| `verbosity` | сбалансировано | Длина ответа: сбалансированно — суть плюс короткое пояснение ключевых мест. |
| `language` | русский | Язык ответа: русский. |
| `language` | английский | Язык ответа: английский — отвечай на английском. |
| `format` | markdown | Формат ответа: markdown — заголовки, списки, блоки кода. |
| `format` | plain text | Формат ответа: plain text — простой текст без markdown-разметки. |
| `format` | структурированный | Формат ответа: структурированный — нумерованные разделы с подписями (например: 1. Анализ, 2. Решение, 3. Проверка). |

`constraints` и `custom_instructions` ограничены по размеру:

| Поле | Границы | Строка в промпте |
|---|---|---|
| `name` | String(100), NOT NULL | `Обращайся к пользователю по имени: <name>.` |
| `constraints.max_response_length` | 20…8000 символов; `None` — без ограничения | `Жёсткое ограничение: весь ответ не длиннее <N> символов.` |
| `constraints.forbidden_topics` | до 20 тем, по 100 символов | `Не обсуждай темы: <a>, <b>. Если запрос про них — вежливо откажись и предложи другую формулировку.` |
| `constraints.required_disclaimers` | до 20 вставок, по 500 символов | `Всегда добавляй в ответ: <дисклеймеры>.` |
| `custom_instructions` | до 4000 символов, до 30 инструкций, каждая до 500 символов | `Дополнительные инструкции пользователя (выполняй буквально):` + строки списка |

Неизвестное значение перечисления, неизвестное поле объекта или выход за границы
дают `ProfileValueError` в `profiles.py` → HTTP 422 у API (схемы используют
`extra="forbid"`).

### Готовые профили демонстрации

`backend/domain/demo_profiles.py` держит три профиля с противоположными настройками —
их ставят кнопками в интерфейсе и прогоняют в отчёте (`DEMO_PROFILES`,
`demo_profile()`, `demo_titles()`). Вопрос для сравнения — `DEMO_QUESTION`
(«Как ускорить медленный SQL-запрос в PostgreSQL?»), запрос про инструкцию о
порядке ролей — `DEMO_FEATURE_REQUEST` («напиши фичу: экспорт отчётов в Excel»).

**`strict_tech` — «Строгий технический».** Ожидание: сухой ответ без разметки и
вступлений — термины и план действий списком, длина ограничена 600 символами.

```json
{
  "name": "Инженер",
  "preferences": {
    "tone": "технический",
    "verbosity": "кратко",
    "language": "русский",
    "format": "plain text"
  },
  "constraints": {"max_response_length": 600},
  "custom_instructions": ""
}
```

**`friendly_mentor` — «Дружелюбный наставник».** Ожидание: подробный тёплый
ответ в Markdown — заголовки, списки, аналогия, обращение по имени, никакой
политики.

```json
{
  "name": "Илья",
  "preferences": {
    "tone": "дружелюбный",
    "verbosity": "подробно",
    "language": "русский",
    "format": "markdown"
  },
  "constraints": {"forbidden_topics": ["политика"]},
  "custom_instructions": "Объясняй простыми словами, используй аналогии\nОбращайся ко мне по имени"
}
```

**`process_orchestrator` — «Оркестратор процесса».** Ожидание: ответ разложен по
ролям в порядке аналитик → разработчик → тестировщик, с двумя вариантами решения
и дисклеймером.

```json
{
  "name": "Тимлид",
  "preferences": {
    "tone": "технический",
    "verbosity": "сбалансировано",
    "language": "русский",
    "format": "структурированный"
  },
  "constraints": {"required_disclaimers": ["Порядок ролей согласован с тимлидом"]},
  "custom_instructions": "При запросе «напиши фичу» следуй порядку: аналитик → разработчик → тестировщик\nВсегда предлагай два варианта решения"
}
```

Произвольные инструкции — свободный текст, одна инструкция на строку. Подсказка
в форме интерфейса показывает тот же пример, что стоит у оркестратора процесса:
`При запросе «напиши фичу» следуй порядку: аналитик → разработчик → тестировщик`
(`CUSTOM_INSTRUCTION_EXAMPLE`).

### Блок профиля в системном промпте

Если профиль не пуст, в начало системного сообщения встаёт блок. Порядок строк
фиксирован, каждая строка появляется только для заполненного поля:

```
Профиль пользователя (персонализация; соблюдай в каждом ответе):
Обращайся к пользователю по имени: <name>.
Стиль общения: <текст по tone>
Формат ответа: <текст по format>
Длина ответа: <текст по verbosity>
Язык ответа: <текст по language>
Жёсткое ограничение: весь ответ не длиннее <N> символов.
Не обсуждай темы: <a>, <b>. Если запрос про них — вежливо откажись и предложи другую формулировку.
Всегда добавляй в ответ: <дисклеймеры>.
Дополнительные инструкции пользователя (выполняй буквально):
- <инструкция 1>
- <инструкция 2>
```

Тот же блок для профиля `friendly_mentor`:

```
Профиль пользователя (персонализация; соблюдай в каждом ответе):
Обращайся к пользователю по имени: Илья.
Стиль общения: дружелюбный — тепло и просто, уместны эмодзи и обращение к собеседнику напрямую.
Формат ответа: markdown — заголовки, списки, блоки кода.
Длина ответа: подробно — с пояснениями, примерами и обоснованием.
Язык ответа: русский.
Не обсуждай темы: политика. Если запрос про них — вежливо откажись и предложи другую формулировку.
Дополнительные инструкции пользователя (выполняй буквально):
- Объясняй простыми словами, используй аналогии
- Обращайся ко мне по имени
```

### Отчёт `docs/reports/personalization_comparison.md`

[`docs/reports/personalization_comparison.md`](docs/reports/personalization_comparison.md) — прогон трёх
профилей на одном и том же вопросе: таблица «Профиль — настройки — ответ — какие
элементы профиля повлияли», полные ответы вместе с системными промптами запросов
и таблица наблюдений (ограничение длины, отсутствие markdown у plain text, длина
подробного ответа против краткого, порядок ролей
аналитик → разработчик → тестировщик). Ответы — реальные запросы к
`deepseek-chat`.

```bash
cd day19
uv run python scripts/personalization_comparison.py            # нужен DEEPSEEK_API_KEY в day19/.env
uv run python scripts/personalization_comparison.py --no-api   # офлайн-заглушка, без сети
```

Скрипт пишет `day19/docs/reports/personalization_comparison.md` и работает на отдельной базе
`day19/personalization_demo.db` (пересоздаётся при каждом прогоне).

## Как профиль попадает в запрос

`Agent.__init__` читает профиль из БД по `cfg.user_id`
(`self.profile_store = ProfileStore(...)`,
`self.profile = self.profile_store.load(self.user_id)`). Профиля нет →
`ProfileData.exists == False`, промпт пустой, агент работает как обычно, без
ошибки.

`Agent._system_message(...)` собирает **одно** system-сообщение, порядок блоков:

1. блок персонализации (если профиль не пуст);
2. системный промпт (роль) агента — `config.system_prompt`, сразу после него блок
   активных инвариантов проекта (день 14);
3. рабочая память активной задачи;
4. долговременная память (отбор по ключевым словам запроса);
5. конспект предыдущей части диалога;
6. факты (стратегия `sticky_facts`);
7. состояние задачи (день 13; если у активной задачи есть строка в
   `task_states`) — конкретная точка, с которой надо продолжать, поэтому идёт
   последней, сразу после общей рамки.

Профиль идёт первым: это постоянная инструкция пользователя, одинаковая во всех
запросах, и она не должна теряться за блоками памяти. Состояние задачи идёт
последним: это КОНКРЕТНАЯ точка, с которой надо продолжать. Оба блока — часть
`_system_message()`, поэтому они попадают в контекст при **любой** стратегии
(`sliding_window`, `sticky_facts`, `branching`, `summary`) и учитывается в
оценке токенов (`_context_tokens_for`, метрики `token_metrics`).

Правки профиля применяются к живым агентам сразу: `AgentManager` при
создании/обновлении профиля рассылает его агентам этого `user_id`
(`applied_to_agents` в ответе `PUT`), а `Agent.apply_config(cfg)` перечитывает
профиль при смене `user_id`. Удаление профиля оставляет агентов
работоспособными с пустым профилем.

## Эндпоинты персонализации

| Метод и путь | Что делает |
|---|---|
| `GET /users` | список всех профилей (`UserProfileOut`: настройки, `summary`, `personalized`) |
| `GET /users/{user_id}/profile` | профиль; нет профиля → 404 |
| `POST /users/{user_id}/profile` | создание; профиль уже есть → 409; тело — `UserProfileIn` |
| `PUT /users/{user_id}/profile` | замена настроек; нет профиля → 404; в ответе `applied_to_agents` — сколько агентов обновилось |
| `DELETE /users/{user_id}/profile` | удаление; нет профиля → 404; ответ `{"status": "deleted", "user_id": ...}` |
| `GET /agents/{agent_id}/profile` | `AppliedProfileOut`: применённый профиль, `elements`, `prompt_block`, `instructions`, `system_prompt` |

Дополнительно: `POST /agents` и `PATCH /agents/{agent_id}` принимают `user_id`
(PATCH переключает профиль живого агента); `GET /agents` и `GET /agents/{id}`
возвращают `user_id`; `POST /agents/{agent_id}/generate` возвращает поля
`profile` (`AppliedProfileOut`) и `system_prompt`. Остальные эндпоинты —
из дня 11 (память, стратегии, ветки, факты, метрики, сжатие). Корневой `GET /`
перечисляет эндпоинты персонализации (поле `personalization`). Ошибки: 404 — нет
агента/профиля, 409 — профиль уже есть, 422 — невалидные поля, 502 — сбой
генерации.

## Интерфейс: раздел «👤 Профиль пользователя»

Раздел переключается вверху основной области: `st.radio` с вариантами
«💬 Чат и память», «👤 Профиль пользователя», «🧭 Состояние задачи»,
«📏 Инварианты», «🔌 MCP», «🗓 Планировщик» и «🔀 Пайплайны» (ключ
`main_section`) — именно radio, а не `st.tabs`: Streamlit не сохраняет выбор
вкладки между перезапусками скрипта, а после «Сохранить профиль» нужен
`st.rerun`.

* «💬 Чат и память»: выбор агента, карточка агента (модель, температура,
  стратегия, профиль `user_id`), панели по стратегии, панель токенов, три панели
  слоёв памяти, индикатор «что ушло в последний запрос», диалог с маркером
  сжатия, expander сравнения режимов, поле ввода и кнопка «🚀 Отправить»,
  «🧹 Очистить историю»; сверху — уведомления планировщика (фрагмент с
  автообновлением раз в 5 секунд и кнопкой «✔ Прочитано» на каждом), а в сводке
  хода — строки «🗓 Планировщик: …» и «🔀 Пайплайн: …».
* Боковая панель: создание агента (в том числе выбор профиля пользователя в
  селекторе `user_id`), переключатель стратегии и `window_size`, блок «🗂 Задача и
  сессия» (переключатель и создание задачи), «🆕 Новая сессия».
* «👤 Профиль пользователя»: селектор профиля, форма создания нового профиля
  (`user_id` + «➕ Создать профиль»), три кнопки готовых профилей, форма
  редактирования (имя, tone, verbosity, language, format, предел длины,
  запрещённые темы, дисклеймеры, произвольные инструкции) с кнопкой
  «💾 Сохранить профиль», предпросмотр блока промпта, «🗑 Удалить профиль», блок
  «🔀 Профиль активного агента» (быстрое переключение профиля живого агента),
  таблица элементов применённого профиля, expander «Итоговый системный промпт
  (без блоков памяти задачи)» и панель «📊 Сравнение двух профилей на одном
  вопросе» (два временных агента → два ответа рядом, «что повлияло на ответ»,
  системный промпт; агенты удаляются после прогона).
* Плашка после ответа содержит применённый профиль: «👤 профиль strict_tech:
  6 элементов» (или «👤 профиль: без персонализации»).
* «🧭 Состояние задачи»: подпись «задача · агент · обновлено», текущий этап и шаг,
  ожидаемое действие, строка о паузе, допустимые следующие этапы, ASCII-схема
  переходов, кнопки-этапы (недоступные заблокированы, причина — в подсказке),
  «⏭ Следующий шаг», пауза и продолжение, чекбоксы трёх флагов согласования и
  вкладки «📜 Журнал переходов», «🚫 Попытки недопустимых переходов» и
  «🧩 Блок в системном промпте». Если состояния у активной задачи нет — форма
  заведения (`task_id` + начальный этап).
* «🗓 Планировщик»: статус планировщика, таблица задач (имя, расписание,
  состояние, последний и следующий запуск) с кнопками «⏸ Пауза»,
  «▶ Возобновить», «▶ Запустить сейчас» и «🗑 Удалить», форма «Запланировать
  задачу» (инструмент, его аргументы, имя, чекбокс немедленного выполнения и
  необязательное переопределение расписания на `interval` или `cron`), блоки
  «⏰ Напоминания» с фильтром, «📊 Регулярные сводки» с метриками и кнопкой
  «📄 Показать текст» и «🧾 Запуски задачи» с журналом `prepare`/`tick`.
* «🔀 Пайплайны»: состояние подключения к серверу дня и кнопка
  «🔌 Подключиться», форма запуска (источник, запрос, `limit`, стиль сводки, имя
  файла, формат), прогресс активного прогона по шагам (фрагмент с
  автообновлением раз в секунду: аргументы и результат каждого шага, путь
  сохранённого файла), схема потока данных с объёмами на переходах и история
  запусков (фрагмент раз в 5 секунд) с деталями шагов и кнопкой
  «🗑 Удалить запуск».
* Переменная окружения адреса бэкенда: `DAY19_BACKEND_URL` (по умолчанию
  `http://127.0.0.1:8000`). Ключ API фронтенду не нужен.

## Модель памяти агента

Три слоя живут в трёх таблицах и различаются не только содержимым, но и ключом,
к которому привязаны:

| Слой | Таблица | Ключ | Что хранит | Когда очищается |
|---|---|---|---|---|
| 👤 Краткосрочная | `short_term_messages` | `session_id` | реплики текущего диалога (роль + текст + время) | `new_session()`, `DELETE /agents/{id}/memory/short-term`, `DELETE /agents/{id}/history` |
| 🗂 Рабочая | `working_memory` | `task_id` + `key` | данные активной задачи: цель, ограничения, решения, критерии | вручную (перезапись ключа) или сменой задачи; новая сессия её не трогает |
| 🧠 Долговременная | `long_term_memory` | `category` + `key` | профиль, устойчивые предпочтения, важные решения, знания | только вручную: `DELETE /agents/{id}/memory/long-term/{entry_id}` |

Контекст запроса собирается так: **блок профиля пользователя (если профиль не
пуст) → системный промпт → блок рабочей памяти (все ключи активной задачи) → блок
долговременной памяти (релевантные записи, отбор по ключевым словам с добором по
уверенности) → конспект (если есть) → факты → состояние задачи (если у активной
задачи есть строка в `task_states`; день 13) → краткосрочный слой по стратегии →
новый промпт**. Все блоки вкладываются в одно системное сообщение.

Где смотреть результат:

* индикатор **«🧭 Что ушло в последний запрос»** — три метрики «N записей ·
  M токенов» (краткосрочная / рабочая / долговременная) плюс сессия, задача,
  сумма токенов и ключевые слова запроса;
* поле `memory` ответа `POST /agents/{id}/generate` — `session_id`, `task_id`,
  `layers[{layer, used, entries, tokens, details}]`, `short_term_tokens` /
  `working_tokens` / `long_term_tokens` / `total_tokens`, `keywords`;
* вкладка «👤 Профиль пользователя», поле `profile` ответа
  `POST /agents/{id}/generate` (`AppliedProfileOut`) и поле `system_prompt` —
  это уже персонализация, а не слой памяти (см. выше).

### Как профиль соотносится с тремя слоями

* **краткосрочная** (`short_term_messages`, привязана к сессии агента) — реплики
  диалога; профиль её не читает и не пишет. `Agent.new_session()` и
  `DELETE /memory/short-term` очищают диалог, но профиль не трогают: после новой
  сессии персонализация та же;
* **рабочая** (`working_memory`, привязана к `task_id`/задаче) — данные задачи;
  `PUT /memory/task` переключает задачу, профиль не меняется. Блок профиля и блок
  рабочей памяти сосуществуют в системном промпте (профиль — раньше);
* **долговременная** (`long_term_memory`, привязана к агенту) — записи
  profile/preference/decision/knowledge, отбираемые по ключевым словам запроса:
  это **данные** для ответа, а не инструкции о стиле. Профиль же — таблица
  `user_profiles`, привязанная к `user_id`: одни и те же настройки и инструкции
  применяются ко всем агентам пользователя, ко всем его задачам и сессиям,
  меняются на лету и не зависят от того, что попало в долговременную память.

Формально профиль — четвёртый по счёту источник в системном сообщении, но не
слой памяти: он не хранит диалог и не отбирается по релевантности, а
подставляется целиком в системный промпт каждого запроса. Оценки токенов слоёв
(`memory` в ответе генерации) считают только три слоя; токены блока профиля
входят в общие `prompt_tokens` / `sent_context_tokens`.

## Что и куда сохраняется

* Ход диалога (`POST /agents/{id}/generate`) → **краткосрочная** память: после
  успешного ответа сохраняется пара реплик `user` + `assistant` текущей сессии.
* Форма вкладки «🗂 Рабочая» (`POST /memory/working`) → **рабочая** память,
  upsert по паре «задача + ключ».
* Форма вкладки «🧠 Долговременная» (`POST /memory/long-term`) →
  **долговременная** память, upsert по паре «категория + ключ».
* Автоматического извлечения профиля и предпочтений LLM **нет**: в рабочую и
  долговременную память данные попадают только решением пользователя (UI или
  API). Ход диалога в эти два слоя ничего не пишет. Сам профиль заполняется
  вручную в разделе «👤 Профиль пользователя» или через
  `POST/PUT /users/{user_id}/profile` — диалог его тоже не меняет.
* Состояние задачи (`task_states`) заводится явно: `POST /agents/{id}/tasks` или
  форма в разделе «🧭 Состояние задачи». Авто-создания нет — пока состояния нет,
  блока в системном промпте тоже нет. Создание задачи делает её активной у
  агента, потому что состояние подключается к промпту только у активной задачи.
  `clear_history()` и `new_session()` состояние задачи не трогают: это не
  диалог; строки задач удаляются вместе с агентом.
* **MCP-инструменты не пишут в БД**: соединение и каталог живут в памяти
  процесса, вызов — разовое действие, а результат уходит в промпт запроса и в
  отчёт `mcp` ответа; таблиц у самой подсистемы MCP нет. Единственное
  исключение — инструмент композиции `save_to_file` пишет файл в каталог дня
  `output/`, а источник `sqlite:` у `search` читает базу дня в режиме «только
  чтение».
* **Инструменты планировщика пишут в шесть своих таблиц**: `scheduled_tasks` —
  сама фоновая задача (расписание и состояние), `task_runs` — каждый запуск
  (`prepare` при создании и `tick` по расписанию) с результатом и ошибкой,
  `reminders` — напоминания, `notifications` — очередь уведомлений,
  `collected_data` — собранные из внешнего API записи,
  `periodic_summaries` — регулярные сводки с метриками. Пишет их бэкенд: MCP-инструмент
  и форма интерфейса лишь вызывают `POST /scheduler/tasks`.
* **Пайплайн пишет в две свои таблицы**: `pipeline_runs` — запуск (имя, статус,
  начало, конец, длительность), `pipeline_steps` — строка на каждый шаг с уже
  разрешёнными аргументами, результатом, временем и статусом. Строка шага
  пишется и тогда, когда маппинг не сошёлся или инструмент упал; удаление
  запуска уносит шаги каскадом. Результат последнего шага дополнительно остаётся
  файлом в `day19/output/`.
* Проверки наследованных возможностей описаны в самом README и в
  [`STRUCTURE.md`](STRUCTURE.md); пайплайн проверяется отчётом
  [`docs/reports/pipeline_demo.md`](docs/reports/pipeline_demo.md), планировщик —
  отчётом [`docs/reports/scheduler_demo.md`](docs/reports/scheduler_demo.md),
  персонализация — отчётом
  [`docs/reports/personalization_comparison.md`](docs/reports/personalization_comparison.md),
  состояние задачи — [`docs/reports/task_state_demo.md`](docs/reports/task_state_demo.md),
  инварианты — [`invariants_demo.md`](invariants_demo.md), контролируемые
  переходы — [`docs/reports/controlled_transitions_demo.md`](docs/reports/controlled_transitions_demo.md),
  MCP-инструменты — [`docs/reports/mcp_tool_demo.md`](docs/reports/mcp_tool_demo.md).

## Архитектура

```
Streamlit (порт 8501) ── HTTP (requests) ──► FastAPI (порт 8000) ──► DeepSeek API
   разделы «💬 Чат и память» /                    │              https://api.deepseek.com
   «👤 Профиль пользователя» /                    ▼
   «🧭 Состояние задачи» /          AgentManager (синглтон)
   «📏 Инварианты» / «🔌 MCP» /     └─ Agent × N
   «🗓 Планировщик» / «🔀 Пайплайны»
                                         ├─ session_id / task_id (активные)
                                         ├─ profile / profile_store ──► user_profiles
                                         ├─ MemoryManager ──► три слоя памяти
                                         ├─ task_state_machine (граф + guards) ──► task_states / task_transitions
                                         ├─ self.short_term_messages (зеркало сессии)
                                         ├─ подсчёт токенов (tiktoken)
                                         ├─ apply_pipeline() ──► Pipeline (маппинг → условие → вызов → журнал → PipelineFSM)
                                         │                              │
                                         │                              ▼
                                         │                        MCPRegistry.call_tool (те же инструменты, что и вручную)
                                         ├─ apply_mcp_tool() ──► MCPToolRunner (допуск + MCPToolCallFSM)
                                         │                              │
                                         │                              ▼
                                         │                        MCPRegistry ──► MCPClient.call_tool
                                         │                        (одно соединение        (tools/call;
                                         │                         на процесс)             адаптеры SDK — mcp_transport)
                                         │                                                   │
                                         │                                                   ▼
                                         │                                          MCP SDK ──► MCP-сервер
                                         │                                          (свой: mcp_server/server.py
                                         │                                           по stdio; или fetch/filesystem)
                                         │                                                   │ HTTP
                                         │                                                   ▼
                                         │                                     https://jsonplaceholder.typicode.com
                                         │
                                         │   пайплайн: три инструмента композиции по реплике, из формы или API
                                         │        └─► Pipeline.run_pipeline ──► PipelineStore
                                         │                                             │
                                         │                                             ▼
                                         │                                    pipeline_runs / pipeline_steps (SQLite)
                                         │
                                         │   планировщик: три инструмента из агента, формы или MCP-сервера
                                         │        └─► POST /scheduler/tasks ──► ScheduleService.create_task
                                         │                                             │
                                         │                                             ▼
                                         │                                    scheduled_tasks (SQLite)
                                         │                                             │ сверка раз в 5 с
                                         │                                             ▼
                                    TaskScheduler (lifespan) ──► APScheduler ──► тик задачи (пул потоков)
                                         │                                             │
                                         │                                             ▼
                                         │                              scheduled_jobs.tick (напрямую, без MCP)
                                         │                                    │
                                         │                                    ├─► reminders / collected_data / periodic_summaries
                                         │                                    └─► notifications (очередь уведомлений)
                                         ├─ prepare_context() ──► стратегия (наследовано
                                         │     из дня 10): sliding_window / sticky_facts /
                                         │     branching / summary (ContextCompressor)
                                         └─ факты (facts) / ветки (checkpoints)
                                    SQLAlchemy → SQLite (day19/agents.db)
                                    таблицы: agents                (конфигурация + strategy/window_size,
                                                                    user_id, current_session_id, current_task_id)
                                             user_profiles          (персонализация: user_id)
                                             short_term_messages    (краткосрочная память: session_id)
                                             working_memory         (рабочая память: task_id + key)
                                             long_term_memory       (долговременная: category + key)
                                             summaries              (конспекты, append-only)
                                             token_usage            (метрики хода + токены по слоям)
                                             facts                  (факты sticky_facts)
                                             checkpoints            (снимки/ветки branching)
                                             task_states            (состояние задачи: task_id уникален)
                                             task_transitions       (журнал переходов задачи)
                                             scheduled_tasks        (задачи фона: расписание, состояние, next_run_at)
                                             task_runs              (журнал запусков: prepare/tick, ok/error)
                                             reminders              (напоминания: scheduled/done)
                                             notifications          (очередь уведомлений: reminder/summary/error)
                                             collected_data         (собранные записи: имя сбора, payload)
                                             periodic_summaries     (регулярные сводки: период, метрики, текст)
                                             pipeline_runs          (запуски пайплайна: имя, статус, начало, конец, длительность)
                                             pipeline_steps         (шаги прогона: инструмент, аргументы, результат, время, статус)
```

Поток одного сообщения: **пользователь → авто-обновление состояния задачи по
реплике (`apply_task_intent`; недопустимый переход отклоняется и попадает в
журнал) → сборка блоков системного сообщения (профиль → системный промпт →
инварианты → рабочая память → долговременная память → конспект → факты →
состояние задачи с допустимыми следующими этапами) и `prepare_context()` по
стратегии → проверка запроса на инварианты → шаг пайплайна (`apply_pipeline`: по
ключевым словам реплики прогнать `search → summarize → save_to_file` синхронно и
дописать блок «## Результат пайплайна» в системное сообщение; реплика с
пайплайном одиночным инструментом уже не разбирается) → шаг MCP (`apply_mcp_tool`:
по ключевым словам реплики вызвать инструмент и дописать блок данных в системное
сообщение; если инструмент планировщика — задача регистрируется вызовом
`POST /scheduler/tasks`, а `record["schedule"]` рассказывает, что запланировано) →
аварийная обрезка при переполнении → API → проверка предложения
модели о переходе (недопустимое заменяет ответ отказом) → пост-проверка ответа на
инварианты → метрики (включая токены по слоям) в БД → пост-ходовое действие
стратегии (сжатие / сохранение фактов / снимок ветки) → ответ** (детали —
[docs/architecture.md](docs/architecture.md)).

Фон идёт **мимо** этого потока: `TaskScheduler` живёт в процессе бэкенда, получает
из `scheduled_tasks` расписание очередной задачи и выполняет её тик в пуле потоков
APScheduler — без обращения к MCP и без блокировки цикла событий. Инструмент
планировщика вызывается один раз (в момент создания задачи), а дальше работает
расписание; результат каждого запуска ложится в `task_runs`, накопленные данные —
в свои таблицы, а уведомления ждут в `notifications` до прочтения. Разбор — в
[docs/architecture.md](docs/architecture.md) (раздел «Планировщик и фоновые
задачи»).

Пайплайн идёт **по тому же пути вызова**, что и одиночный инструмент: шаг делает
`Pipeline.run_pipeline`, который через `MCPToolRunner` проверяет соединение и
аргументы и зовёт `MCPRegistry.call_tool`. Разница в том, что аргументы шага
собираются из данных запуска и результатов предыдущих шагов, результат каждого
шага ложится в `pipeline_steps`, а исход прогона описывает отдельная
стейт-машина. Запуск из интерфейса или API идёт в **фоновом потоке**
(`threading.Thread`): поток получает терминальный статус даже при исключении, а
интерфейс опрашивает `GET /pipelines/runs/{run_id}` раз в секунду — так и
получается «прогресс в реальном времени».

## Организация кода

Код дня разложен по слоям: у каждого слоя своя папка, файл лежит в папке
**своего** слоя, а не в «ближайшей». Пустой корень `backend/` (только
`__init__.py`) — не случайность, а критерий: если в нём появился модуль, значит
он не нашёл свой слой.

| Слой | Папка | Зачем |
|---|---|---|
| Конфигурация и зависимости | `backend/core/` | Настройки дня (лимиты, цены, пути `.env`/`agents.db`, блоки настроек планировщика и пайплайна) и доступ роутов к менеджеру агентов, реестру MCP, планировщику и службе пайплайнов |
| Домен | `backend/domain/` | Чистые правила и данные без БД, LLM и HTTP: FSM задачи, сжатия, **MCP-подключения и MCP-вызова**, **планировщика (состояние задачи и напоминания)**, **пайплайна (спецификация, маппинг данных, условие шага, FSM прогона, распознавание реплики и блок промпта)**, граф допуска и guards переходов, стратегии, факты, слои памяти, профиль, тексты промпта, разбор цели MCP, структура инструмента, распознавание запроса к инструменту и каталог серверов, спецификации трёх инструментов планировщика, формы расписания, агрегация сводок и распознавание реплик о фоновых задачах |
| Доступ к данным | `backend/storage/` | Движок и сессии SQLite, реэкспорт ORM, `TaskStateStore`, `SchedulerStore`, `SchedulerDataStore` и `PipelineStore`, преобразования ORM-строк в словари |
| Прикладные сервисы | `backend/services/` | Оркестрация домена и хранилища: суммаризация (`ContextCompressor`), переходы задачи (`TaskStateMachine`), **MCP** (`MCPClient` с `list_tools`/`call_tool`, `MCPRegistry`, `MCPToolRunner`, `MCPEventLoop`, `mcp_transport`, `mcp_errors`), **планировщик** (`TaskScheduler`, `ScheduleService`, действия инструментов, HTTP-источник, мост к APScheduler) и **пайплайн** (`Pipeline` с журналом шагов, `PipelineService` с фоновым запуском) |
| Агенты | `backend/agents/` | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` и его миксины |
| ORM-таблицы | `backend/models/` | SQLAlchemy-модели по доменам (агент, память, контекст, профиль, задача, планировщик, пайплайн) |
| Схемы API | `backend/schemas/` | Pydantic-модели запросов/ответов по доменам (включая `scheduler` и `pipeline`) |
| HTTP | `backend/api/` | FastAPI-роутеры по доменам, `lifespan.py` (таблицы → агенты → планировщик) и сборка `app` (`backend.api.main:app`) |
| Утилиты | `backend/utils/` | Слой объявлен обязательным, но в дне 19 пуст: общий код живёт в repo-level `shared/` |
| Интерфейс | `frontend/` | Streamlit по секциям: транспорт, подписи, панели, разделы (включая «🔌 MCP», «🗓 Планировщик» и «🔀 Пайплайны») и уведомления области чата |
| Скрипты | `scripts/` | Прогоны демонстраций и сборка отчётов (в `docs/reports/`) |
| Тесты | `tests/unit`, `tests/integration`, `tests/e2e` | Классификация по фикстурам: чистые модули / временная БД и агент / `TestClient` |

Правило для будущих дней: **новая сущность сразу определяется в свой слой**
(настройка — `core/`, чистая функция — `domain/`, запрос к БД — `storage/`,
эндпоинт — `api/`, схема — `schemas/`, таблица — `models/`, панель —
`frontend/`). Каждый пакет слоя имеет `__init__.py` с реэкспортом публичных
имён — это и есть публичный контракт слоя.

## Структура

```
day19/
├── app.py               # Streamlit, точка входа (67 строк): set_page_config →
│                        # common.init_state() → sidebar.render_sidebar() → chat_section.render_main_area()
├── frontend/            # интерфейс по секциям (21 модуль, карта — в STRUCTURE.md)
│   ├── api_client.py    # HTTP-транспорт бэкенда (requests): BACKEND_URL (DAY19_BACKEND_URL), BackendError, request_json
│   ├── mcp_api.py       # запросы MCP-раздела: /mcp/status, /mcp/connect, /mcp/disconnect, /mcp/tools, /mcp/call, /mcp/servers
│   ├── mcp_call.py      # каталог серверов (GET /mcp/servers) и ручной вызов инструмента по форме аргументов
│   ├── mcp_ask.py       # блок «🤖 Спросить агента»: агент сам вызывает инструмент и отвечает по данным
│   ├── scheduler_api.py # запросы раздела планировщика: /scheduler/tasks, /tools, /reminders, /collected, /summaries, /notifications, /status
│   ├── pipeline_api.py  # запросы раздела пайплайнов: /pipelines/run, /runs, /runs/{id}, /runs/{id}/steps
│   ├── common.py        # подписи (TASK_STAGE_LABELS, MCP_*, SCHEDULE_*, PIPELINE_*), schedule_note, run_task_action, st.session_state
│   ├── notifications.py # уведомления планировщика в области чата (фрагмент с автообновлением раз в 5 с)
│   ├── sidebar.py       # боковая панель: список агентов, создание агента, стратегия, задача и сессия
│   ├── chat_section.py  # раздел «💬 Чат и память», переключатель семи разделов и строка «🔀 Пайплайн: …» в сводке хода
│   ├── context_panels.py# панели контекста: токены, сжатие, сравнение режимов, ветки, факты
│   ├── memory_panels.py # панели трёх слоёв памяти и индикатор «что ушло в последний запрос»
│   ├── profile_section.py     # раздел «👤 Профиль пользователя»: форма, переключение, предпросмотр
│   ├── profile_comparison.py  # сравнение двух профилей на одном вопросе (временные агенты)
│   ├── invariant_panel.py     # раздел «📏 Инварианты»: таблица правил, форма, проверка текста
│   ├── mcp_section.py         # раздел «🔌 MCP»: подключение, статус, таблица инструментов, вызов, «Спросить агента»
│   ├── scheduler_section.py   # раздел «🗓 Планировщик»: задачи, форма создания, напоминания, сводки, история запусков
│   ├── pipeline_section.py    # раздел «🔀 Пайплайны»: форма запуска, прогресс по шагам (раз в 1 с), схема потока, история (раз в 5 с)
│   ├── task_panel.py          # раздел «🧭 Состояние задачи»: состояние, схема FSM, вкладки журнала
│   └── task_transitions.py    # кнопки-этапы с блокировкой и причиной, флаги, пауза/продолжение
├── mcp_server/          # СВОЙ MCP-сервер дня 19 (транспорт stdio, JSON-RPC по stdin/stdout)
│   ├── config.py        # адрес jsonplaceholder, таймаут, границы limit/id, адрес бэкенда дня, имя/версия и инструкция сервера,
│   │                    # пути каталога output/, корня источников file:, базы дня и чтение ключа DeepSeek
│   ├── schemas.py       # TypedDict-структуры ответов (UserInfo, …, ReminderScheduled, CollectionStarted, SummaryReady, SearchResult, SummaryResult, SavedFile) → outputSchema
│   ├── api_client.py    # JsonPlaceholderClient: HTTP-запросы к jsonplaceholder (get_user/get_post/list_user_posts/list_posts/list_users) и ExternalAPIError (404 с объяснением)
│   ├── backend_api.py   # ScheduleBackendClient: POST /scheduler/tasks (тела трёх инструментов планировщика)
│   ├── search_sources.py # источник поиска: posts/users, file:<путь> внутри дня, sqlite:<таблица> только на чтение; SearchSourceError
│   ├── summarize_logic.py # чистая логика сводки: стиль, длина, промпт, разбор ключевых пунктов, агрегация без LLM
│   ├── llm_client.py    # ленивый клиент DeepSeek для summarize: available() и summarize(), LLMUnavailable
│   ├── file_writer.py   # запись файла в каталог output/: формат, имя, замена расширения, SavedFile
│   ├── pipeline_tools.py # три инструмента композиции (search, summarize, save_to_file) и register_pipeline_tools
│   ├── data/notes.md    # заметки дня — источник file: по умолчанию для офлайн-прогона пайплайна
│   └── server.py        # MCPServer + девять инструментов (@server.tool()), ToolError, --api-base/--backend-url/--timeout/--output-dir/--file-root/--db-path/--llm, server.run("stdio")
├── scripts/             # прогоны демонстраций и сборка отчётов (не пакет, находят корень дня сами)
│   ├── pipeline_demo.py # день 19: оркестрация четырёх сценариев пайплайна на своём stdio-сервере и сборка отчёта (--report/--output-dir/--llm/--db/--tests/--json)
│   ├── pipeline_scenarios.py # что именно проверяют четыре сценария (успех, пустой поиск, ошибка шага, агент) и офлайн-заглушка модели
│   ├── pipeline_report.py # сборка markdown-отчёта прогона (разделы 1–9, таблица инструментов, трассировка шагов и схема таблиц)
│   ├── scheduler_demo.py # унаследовано из дня 18: оркестрация четырёх сценариев планировщика и сборка отчёта (--report/--tests/--source-url/--keep-db)
│   ├── scheduler_scenarios.py # что именно проверяют четыре сценария и как печатают результат
│   ├── scheduler_report.py # сборка markdown-отчёта прогона (разделы 1–9, таблица инструментов и схема таблиц)
│   ├── scheduler_stand.py # изолированный бэкенд прогона: своя БД, офлайн-заглушка модели, детерминированный источник (--serve/--db/--port)
│   ├── mcp_tool_demo.py # унаследовано из дня 17: каталог, три вызова, три отказа и шаг агента (--target/--api-base/--live/--report)
│   ├── mcp_tool_report.py # сборка markdown-отчёта прогона (разделы 1–7)
│   ├── mcp_demo.py      # унаследовано из дня 16: подключение к MCP-серверу и печать списка инструментов (--json/--target/--timeout)
│   ├── controlled_transitions_demo.py # унаследовано из дня 15: правила допуска, пауза в новом процессе, отказ агента
│   ├── transitions_report.py # сборка отчёта контролируемых переходов
│   ├── video_scenario.py  # унаследовано из дня 15: точка входа прогона кадров (--all/--auto/--ui/--reset/--serve)
│   ├── video_scenario_checks.py # печать кадров и проверок (VideoChecks), отчёт о финале
│   ├── video_scenario_client.py # HTTP-клиент прогона и путь БД video_scenario.db
│   ├── video_scenario_frames.py # кадры 0–9 по HTTP: домен, проверки, перезапуск бэкенда
│   ├── video_scenario_ui.py # UI-кадры сценария: реальный рендер через streamlit.testing AppTest
│   ├── video_scenario_browser.py # набор действий в браузере: клики, сверки, человеческий темп
│   ├── video_scenario_browser_frames.py # кадры 0–9 в настоящем браузере (Playwright, Chromium)
│   ├── video_scenario_stand.py # стенд для съёмки: живой Streamlit в браузере + чек-лист кадров
│   ├── video_scenario_server.py # бэкенд прогона: заглушка DeepSeek, uvicorn на своей БД, жизненный цикл процесса
│   ├── task_state_demo.py # прогон пяти фаз состояния задачи (--all/--phase/--reset), каждая — новый процесс
│   ├── task_demo_report.py# сборка markdown-фрагментов отчёта демонстрации
│   ├── personalization_comparison.py # унаследовано из дня 12: прогон трёх профилей (API или --no-api)
│   ├── comparison_report.py # сборка отчёта сравнения профилей
│   └── comparison_stub.py   # офлайн-заглушка DeepSeek (её же использует task_state_demo.py)
├── backend/
│   ├── api/             # FastAPI: 9 роутеров по доменам + main.py (сборка app, 79 строк) + lifespan.py
│   ├── core/            # config.py (настройки, пути .env и agents.db, цели MCP, блоки планировщика и пайплайна), dependencies.py (get_manager, get_mcp_registry, get_scheduler, get_schedule_service, get_pipeline_service, *_or_404)
│   ├── domain/          # чистые правила: strategies, task_fsm, task_prompt, task_intent, task_state_machine,
│   │                    # task_proposal, context_fsm, context_policy, fact_extractor, memory_layers, profiles,
│   │                    # profile_values, demo_profiles, invariant_values, invariant_rules, invariant_prompt,
│   │                    # demo_invariants, mcp_connection_fsm, mcp_target, mcp_tools, mcp_tool_call, mcp_intent,
│   │                    # mcp_prompt, mcp_servers, scheduler_values, scheduler_fsm, schedule_spec,
│   │                    # schedule_timing, aggregation, schedule_intent, scheduler_prompt,
│   │                    # pipeline_spec, pipeline_mapping, pipeline_fsm, pipeline_intent, pipeline_prompt
│   ├── services/        # compressor (суммаризация и конспект), task_state (контракт переходов и отказ),
│   │                    # invariant_checker (правила → LLM), mcp_transport (адаптеры MCP SDK),
│   │                    # mcp_client (MCPClient: list_tools и call_tool), mcp_loop (цикл событий в
│   │                    # daemon-потоке), mcp_errors, mcp_registry (MCPRegistry), mcp_tool_runner
│   │                    # (правила допуска → вызов → отчёт), source_fetch (единственный HTTP фона),
│   │                    # scheduled_jobs (prepare/tick трёх инструментов), apscheduler_bridge (мост к
│   │                    # APScheduler), scheduler (TaskScheduler), schedule_service (ScheduleService),
│   │                    # pipeline (Pipeline: шаги, маппинг, журнал), pipeline_service (PipelineService: фоновый запуск)
│   ├── storage/         # database.py (движок, сессии, реэкспорт ORM), task_store.py, invariant_store.py, memory_rows.py,
│   │                    # scheduler_store.py (задачи и журнал запусков), scheduler_data_store.py (накопленное),
│   │                    # scheduler_rows.py (проекции ORM-строк планировщика),
│   │                    # pipeline_store.py (запуски и шаги пайплайна), pipeline_rows.py (их проекции)
│   ├── agents/          # agent.py (в т.ч. шаги apply_pipeline, apply_mcp_tool и планировщика), memory.py, profile_store.py, agent_manager.py, manager_*.py (7 миксинов)
│   ├── models/          # ORM-таблицы SQLAlchemy по доменам: agents, short_term_messages, working_memory,
│   │                    # long_term_memory, summaries, token_usage, facts, checkpoints, user_profiles,
│   │                    # task_states, task_transitions, invariants, scheduled_tasks, task_runs, reminders,
│   │                    # notifications, collected_data, periodic_summaries, pipeline_runs, pipeline_steps
│   │                    # (реэкспорт — через storage/database.py)
│   ├── schemas/         # Pydantic-схемы API по доменам: agent, context, invariant, mcp, memory, pipeline, profile, scheduler, task
│   └── utils/           # своего кода нет: общий живёт в repo-level shared/
├── tests/               # pytest: файлы в подпапках unit/ (33 файла), integration/ (32), e2e/ (11); точный счёт тестов — в STRUCTURE.md
│                        # общие фейки и фикстуры: conftest.py, support.py, mcp_fakes.py (MCP-фейки),
│                        # pipeline_fakes.py (каталог и клиент трёх инструментов композиции),
│                        # scheduler_fakes.py (фейк источника и стенд планировщика), stub_api.py и
│                        # backend_stub.py (локальные стенды для тестов на настоящем stdio)
├── STRUCTURE.md         # карта модулей дня: раскладка по слоям, что импортируется из shared/, лимит 400 строк
├── docs/
│   ├── architecture.md  # компоненты и модульная структура, схема БД, слои памяти, персонализация, FSM, переходы, инварианты, MCP-сервер и инструменты, планировщик, пайплайны
│   ├── api.md           # 78 эндпоинтов с примерами и кодами ошибок
│   ├── usage.md         # инструкция дня 19: установка и запуск, три инструмента композиции, запуск и чтение пайплайна, история, условия перехода, сценарии проверки
│   └── reports/         # pipeline_demo.md (день 19), scheduler_demo.md (день 18), mcp_tool_demo.md (день 17), mcp_demo.md (день 16) + унаследованные controlled_transitions_demo.md, task_state_demo.md, personalization_comparison.md
├── invariants_demo.md   # отчёт дня 14: три сценария инвариантов (унаследован)
├── pytest.ini           # конфигурация pytest: testpaths = tests, pythonpath = . tests
├── conftest.py          # добавляет корень day19 в sys.path (импорт `from backend.agents.agent import Agent`)
├── pyproject.toml       # зависимости дня: apscheduler, fastapi, uvicorn, streamlit, openai, requests,
│                        # sqlalchemy, tiktoken, httpx, pytest, pandas, mcp (менеджер — uv);
│                        # dev-группа: playwright — прогон кадров в настоящем браузере (--auto)
├── uv.lock              # точные версии всех пакетов — фиксируется в Git
├── .agents/skills/      # скиллы библиотек (uvx library-skills --copy): fastapi, developing-with-streamlit
├── .python-version      # 3.14 — версия интерпретатора для `uv sync`
├── agents.db            # SQLite: агенты, слои памяти, профили, задачи, инварианты, задачи планировщика, запуски и шаги пайплайна (в .gitignore по *.db)
├── output/              # каталог результатов пайплайна (save_to_file пишет только сюда); run-success.md — артефакт демонстрации
├── personalization_demo.db # отдельная БД отчёта персонализации: появляется после прогона скрипта
├── task_state_demo.db   # отдельная БД демонстрации состояния задачи (пересоздаётся скриптом)
├── invariants_demo.db   # отдельная БД прогона отчёта инвариантов (пересоздаётся скриптом)
├── controlled_transitions_demo.db # отдельная БД демонстрации переходов (пересоздаётся скриптом)
├── video_scenario.db    # отдельная БД автопроверки кадров сценария (пересоздаётся скриптом)
└── .env.example         # шаблон ключа DEEPSEEK_API_KEY и адреса бэкенда DAY19_BACKEND_URL
```

## Установка и запуск

Менеджер зависимостей — **uv** (заменяет `pip`, `virtualenv` и `pip-tools`):
прямые зависимости объявлены в `pyproject.toml`, точные версии всех пакетов
зафиксированы в `uv.lock`, версия интерпретатора — в `.python-version` (`3.14`).
`uv sync` создаёт `.venv` и приводит его ровно к содержимому лока; активировать
окружение не нужно — `uv run <команда>` подхватывает `.venv` проекта сам.

```bash
cd day19
uv sync
uv run playwright install chromium   # один раз: браузер для режима --auto
copy .env.example .env   # затем впишите DEEPSEEK_API_KEY=sk-...
```

Планировщик фона — библиотека **`apscheduler`** (`apscheduler>=3.11.3,<4.0`, класс
`apscheduler.schedulers.asyncio.AsyncIOScheduler`); ставится тем же `uv sync`,
отдельной команды запуска у фона нет — он поднимается в `lifespan` бэкенда.
`playwright` объявлен в dev-группе `pyproject.toml` и нужен только режиму
`--auto` (проход кадров в настоящем браузере); сам Chromium ставится командой
выше в пользовательский кэш и в репозиторий не попадает.

Пайплайн новых зависимостей не требует: инструменты композиции живут в том же
MCP-сервере дня, журнал — в той же SQLite, а `summarize` обращается к DeepSeek
через общий клиент `shared/`; без ключа он собирает сводку сам, поэтому
`scripts/pipeline_demo.py` работает офлайн с флагом `--llm off` (по умолчанию).

В `day19/.env` нужен ключ `DEEPSEEK_API_KEY=sk-...` (для шага агента и генерации,
а также для сводки `summarize` через LLM);
адрес бэкенда для интерфейса и MCP-сервера задаёт `DAY19_BACKEND_URL` (по
умолчанию `http://127.0.0.1:8000`), его указывают, только если бэкенд слушает
другой порт.

Терминал 1 (бэкенд):

```bash
uv run uvicorn backend.api.main:app --reload --port 8000
```

Терминал 2 (фронтенд): откройте <http://localhost:8501>.

```bash
uv run streamlit run app.py
```

Свой MCP-сервер запускается отдельной командой только для ручной проверки — его
интерфейс это JSON-RPC на stdin/stdout:

```bash
uv run python mcp_server/server.py                       # --help: --api-base, --backend-url, --timeout, --output-dir, --file-root, --db-path, --llm
uv run python mcp_server/server.py --api-base http://127.0.0.1:8765   # стенд вместо сети
uv run python mcp_server/server.py --backend-url http://127.0.0.1:8100  # API дня на другом порту
uv run python mcp_server/server.py --llm off --output-dir output --db-path agents.db  # офлайн: сводка агрегацией
```

При подключении из приложения сервер поднимается сам: цель
`uv run python mcp_server/server.py` — команда **stdio**, и реестр бэкенда
запускает её дочерним процессом. Важно сначала выполнить `uv sync`: иначе первый
`uv run` в дочернем процессе синхронизирует окружение и может не уложиться в
`MCP_TIMEOUT`. Три инструмента планировщика ходят не в jsonplaceholder, а в API
дня (`POST /scheduler/tasks`), поэтому бэкенд к моменту их вызова должен быть
запущен. Инструменты композиции работают и без бэкенда: `search` читает
jsonplaceholder, файл внутри папки дня или таблицу SQLite дня, а `save_to_file`
пишет только в каталог `output/` (его можно переопределить флагом `--output-dir`).

Автотесты дня:

```bash
uv run pytest -q      # автотесты дня, офлайн (ключа и сети не требуют; счёт — в STRUCTURE.md)
```

Инструкция дня 19 (установка и запуск, три инструмента композиции, запуск
пайплайна из интерфейса и API, чтение шагов, условия перехода, сценарии
проверки) — в
[docs/usage.md](docs/usage.md); эндпоинты с примерами — в [docs/api.md](docs/api.md);
как всё устроено внутри — в [docs/architecture.md](docs/architecture.md);
Swagger — на `http://127.0.0.1:8000/docs`.

Серверы официального набора требуют внешних команд: `uvx` (идёт с `uv`) — для
`uvx mcp-server-fetch`, `npx` (Node ≥ 18) — для
`npx -y @modelcontextprotocol/server-filesystem .`. Своему серверу, кроме `uv`,
ничего не нужно. Проверка одной командой:

```bash
uv run python scripts/mcp_tool_demo.py    # каталог → три вызова → три отказа → шаг агента
```

Сквозной прогон четырёх сценариев пайплайна (успех, пустой поиск, ошибка на
втором шаге, запуск через агента) офлайн, без ключа и сети; он поднимает свой
stdio-сервер дня с источником `file:mcp_server/data/notes.md`, пишет файл в
`day19/output/` и собирает отчёт:

```bash
uv run python scripts/pipeline_demo.py --report docs/reports/pipeline_demo.md
uv run python scripts/pipeline_demo.py --llm auto --report docs/reports/pipeline_demo.md  # сводка через DeepSeek (нужен ключ в .env)
uv run python scripts/pipeline_demo.py --tests --report docs/reports/pipeline_demo.md     # плюс прогон автотестов
```

Сквозной прогон четырёх сценариев планировщика (напоминание через 30 секунд, сбор
каждые 10 секунд, сводка каждые 20 секунд, восстановление после перезапуска) —
около двух минут; он поднимает изолированный бэкенд со своей БД и офлайн-источником
и собирает отчёт:

```bash
uv run python scripts/scheduler_demo.py --report docs/reports/scheduler_demo.md
uv run python scripts/scheduler_demo.py --tests --report docs/reports/scheduler_demo.md  # плюс прогон автотестов
uv run python scripts/scheduler_demo.py --source-url https://jsonplaceholder.typicode.com/posts  # живой источник
```

Доказательства: пайплайн —
[docs/reports/pipeline_demo.md](docs/reports/pipeline_demo.md) (три инструмента
композиции, четыре сценария, трассировка шагов с колонками «шаг | инструмент |
входные данные | выходные данные | время выполнения | статус», схема двух таблиц);
планировщик —
[docs/reports/scheduler_demo.md](docs/reports/scheduler_demo.md) (таблица трёх
инструментов, четыре сценария, схема шести таблиц); MCP-инструменты —
[docs/reports/mcp_tool_demo.md](docs/reports/mcp_tool_demo.md) (свой сервер,
вызовы, отказы и блок данных в промпте); унаследованные — MCP-клиент
[docs/reports/mcp_demo.md](docs/reports/mcp_demo.md), контролируемые переходы
[docs/reports/controlled_transitions_demo.md](docs/reports/controlled_transitions_demo.md),
состояние задачи [docs/reports/task_state_demo.md](docs/reports/task_state_demo.md),
инварианты [invariants_demo.md](invariants_demo.md), персонализация
[docs/reports/personalization_comparison.md](docs/reports/personalization_comparison.md).

## Отслеживание версий библиотек

Библиотеки дня везут официальные AI-скиллы **внутри пакета** (FastAPI —
`.venv/Lib/site-packages/fastapi/.agents/skills/fastapi`, Streamlit —
`.../streamlit/.agents/skills/developing-with-streamlit`), поэтому скилл всегда
описывает именно ту версию, что стоит в `.venv`. `uvx library-skills` находит
такие скиллы в зависимостях дня и кладёт их в `.agents/skills/`
**относительными симлинками**, поэтому при обновлении библиотеки через `uv`
содержимое скилла меняется автоматически — обновлять скиллы вручную не нужно
(и не следует: их пересобирает команда).

Симлинки относительные и закоммичены в Git (`mode 120000`, цель —
`../../.venv/Lib/site-packages/...`). До `uv sync` они «битые» — это нормально,
после установки зависимостей оживают.

```bash
cd day19
uv sync                       # зависимости из pyproject.toml / uv.lock
uvx library-skills            # установить/обновить скиллы (интерактивно)
uvx library-skills list       # посмотреть скиллы
uvx library-skills --check    # проверить целостность (код 1 при дрейфе)
```

Если в системе нет прав на символические ссылки (Windows без режима
разработчика), CLI падает с `Could not create symlink` — тогда запускать с
флагом `--copy`; скиллы станут копиями, авто-обновление пропадёт и команду
`uvx library-skills` нужно повторять после апгрейда библиотек.

В этой рабочей копии так и получилось: `day19/.agents/skills/` содержит
**копии** (`fastapi`, `developing-with-streamlit`, `library-skills`), а не
симлинки. Это вендорный код библиотек, а не код дня: проверка лимита строк в
[STRUCTURE.md](STRUCTURE.md) каталог `.agents/` исключает.

Скиллы видны агенту omp, если сессия запущена **из папки `day19`** (провайдер
`agents` ищет `<проект>/.agents/skills/<имя>/SKILL.md`, поднимаясь от `cwd`
вверх). Для сессии из корня репозитория путь добавлен в `.omp/config.yml`
(`skills.customDirectories: day19/.agents/skills`) — там же он ищет только на
один уровень вглубь, поэтому скиллы каталога подхватываются целиком.

## Тесты

```bash
cd day19
uv run pytest -q      # автотесты дня
```

Файлов: `unit/` — 33, `integration/` — 32, `e2e/` — 11; точный счёт тестов и
раскладка по файлам — в [STRUCTURE.md](STRUCTURE.md). Наборы дней 16–18
(инструменты MCP, планировщик) наследуются; меняется только ожидаемый каталог
сервера дня — в нём теперь девять имён.

Новые файлы дня 19 (композиция инструментов и пайплайн):

| Файл | Что проверяет |
|---|---|
| `tests/unit/test_pipeline_spec.py` | `DEFAULT_PIPELINE` проходит валидацию и содержит три инструмента; отказы конфигурации (пустой `steps`, шаг без `tool`, больше `PIPELINE_STEPS_MAX`, неизвестное условие, `steps` не список) |
| `tests/unit/test_pipeline_mapping.py` | `{имя}` целиком и внутри строки, `$steps.<i>.<путь>` включая индекс списка, отсутствующий путь или заглушка → `PipelineMappingError`, все четыре условия перехода и `equals` без `value` |
| `tests/unit/test_pipeline_fsm.py` | таблица переходов прогона, негативные пары → `UnknownPipelineEvent`, `allowed_events` |
| `tests/unit/test_pipeline_intent.py` | реплика из задания → `query == "RAG"`, источник по умолчанию, `rag.md`; две группы слов → `None`; стиль, формат и источник берутся из реплики |
| `tests/unit/test_pipeline_prompt.py` | блок «## Результат пайплайна» для `completed` и `stopped`, пустая строка для `failed` и нераспознанной реплики |
| `tests/unit/test_search_sources.py` | файловый источник (блоки, фильтр, выход за пределы папки дня, нет файла), SQLite-источник (фильтр, `limit`, неизвестная таблица), неизвестный вид источника, API-источник на фейковом клиенте |
| `tests/unit/test_summarize_logic.py` | нормализация стиля, зажим длины, все три стиля агрегации, разбор ключевых пунктов из ответа LLM, состав промпта |
| `tests/unit/test_file_writer.py` | три формата (в т.ч. точная форма JSON), замена расширения, запрет пути в имени, `size_bytes` против файла на диске, ошибки формата и длины |
| `tests/integration/test_pipeline_store.py` | запуск и шаги в SQLite: порядок шагов, свежие запуски первыми, фильтр статуса, обновление, каскадное удаление, отсутствующий запуск |
| `tests/integration/test_pipeline_execution.py` | три сценария прогона на фейковом реестре (успех, досрочная остановка по условию, ошибка на втором шаге) и прогон без соединения — `failed` с `not_connected` |
| `tests/integration/test_pipeline_service.py` | фоновый запуск возвращает `running` и доходит до терминального статуса, отчёт даёт `failed_at_step`/`error`/`message`, список запусков, удаление, отсутствующий запуск |
| `tests/integration/test_pipeline_agent.py` | шаг пайплайна в агенте: блок в системном промпте и поле `pipeline`; обычная реплика пайплайн не запускает, при запущенном пайплайне одиночный инструмент не вызывается |
| `tests/e2e/test_pipelines_api.py` | контракт пяти эндпоинтов `/pipelines`: синхронный и фоновый запуск, 400 на невалидную конфигурацию и неизвестный статус, `200`/`404`, удаление, поле `pipeline` в ответе генерации |
| `tests/pipeline_fakes.py` | фейки композиции: каталог трёх инструментов со схемами, клиент с ответом по имени инструмента и с ошибкой инструмента |

Новые файлы дня 18 (планировщик фоновых задач, унаследованы):

| Файл | Тестов | Что проверяет |
|---|---|---|
| `tests/unit/test_scheduler_fsm.py` | 15 | таблица переходов двух машин (задача и напоминание), негативные пары → `UnknownSchedulerEvent` (в т.ч. повторный `fire`), `allowed_events` и `can` |
| `tests/unit/test_schedule_spec.py` | 38 | `schedule_for` для трёх инструментов, `validate_arguments` по каждому коду причины (лишний и отсутствующий аргумент, границы, тип, URL без схемы и длиннее лимита), `normalize_schedule` (`interval`/`cron`/`date` и кривые значения), `next_run_at`, `default_task_name`, каталог `tool_specs` |
| `tests/unit/test_aggregation.py` | 10 | числовые поля (`count`/`avg`/`min`/`max`) на плоском и вложенном payload, `bool` вне числовых, категориальные `unique` и `samples`, `sources`, пустой период, обрезка по `max_fields`, подстроки текста сводки |
| `tests/unit/test_schedule_intent.py` | 18 | три реплики инструментов с разбором времени и URL («напомни мне через 5 минут проверить почту» → `delay_seconds = 300`), реплики без триггеров → `None`, инструмент вне каталога → `None`, регресс дня 17 (`get_user` по-прежнему распознаётся) |
| `tests/unit/test_scheduler_prompt.py` | 9 | `render_schedule_report` для `done` и `None` для отказа, сбоя, отсутствия вызова и не-планировщицкого инструмента; пустой `render_scheduler_block` при отказе |
| `tests/integration/test_scheduler_service.py` | 17 | `create_task` для трёх инструментов: строка `scheduled_tasks`, немедленный результат (`reminders` + `reminder_id` в аргументах, запись `collected_data`, `periodic_summaries`), журнал с `phase = "prepare"`, `run_now=False`, коды отказов, пауза/возобновление, удаление задачи вместе с запусками, отметка уведомления прочитанным |
| `tests/integration/test_scheduler_ticks.py` | 7 | тик напоминания (`reminders.status = "done"`, уведомление, задача `completed`), повторный тик → отказ, тик сбора (новая запись при другом ответе источника), сбой источника → `task_runs.status = "error"` + уведомление и задача остаётся активной, тик сводки с метриками за период |
| `tests/integration/test_scheduler_restore.py` | 3 | восстановление после «перезапуска»: активные задачи возвращаются, просроченный `next_run_at` пересчитан, `paused` и `completed` не регистрируются |
| `tests/integration/test_scheduler_apscheduler.py` | 2 | настоящая связка с APScheduler: задача с интервалом 1 с действительно порождает запуск в журнале, `status()["running"]` и корректная остановка |
| `tests/integration/test_scheduler_agent.py` | 8 | шаг агента: реплика-напоминание вызывает `schedule_reminder` с нужными аргументами и даёт `record["schedule"]["registered"] = True`, реплика-сводка — `generate_summary`, без соединения — `None` при `record["mcp"]["reason_code"] = "not_connected"` |
| `tests/integration/test_mcp_scheduler_tools.py` | 8 | настоящий stdio-сервер дня со стендом API: каталог из шести унаследованных инструментов (данные и планировщик — у файла свой список), `structuredContent` трёх инструментов планировщика, ошибка бэкенда приходит как `is_error` с текстом причины, а не обрывом связи |
| `tests/e2e/test_scheduler_api.py` | 17 | контракт `/scheduler`: каталог, создание задачи (201 и результат инструмента), 400 на незнакомый инструмент и плохое расписание, 422 на невалидное тело, список со блоком `scheduler`, `pause`/`resume` (200 и 409), `DELETE` (200/404), история, принудительный запуск, напоминания, собранные записи, сводки, уведомления и их отметка, статус, поле `schedule` в ответе генерации |

Новые файлы дня 17 (унаследованы):

| Файл | Тестов | Что проверяет |
|---|---|---|
| `tests/unit/test_mcp_tool_call.py` | 43 | таблица переходов FSM вызова (сверка с `HANDLERS`), негативные пары → `UnknownMCPToolCallEvent`, `admission_reason` по каждому коду причины, форма `MCPToolCallOutcome` и свойство `called` |
| `tests/unit/test_mcp_intent.py` | 21 | приоритет правил («посты пользователя» — не `get_user`), морфология фраз, номер аргумента (первое число), пустая реплика и инструмент вне каталога → `None` |
| `tests/unit/test_mcp_prompt.py` | 9 | блок данных для `done` (заголовок, инструмент, JSON аргументов и результата, инструкция), пустая строка для `idle`/`rejected`/`failed`, текст вместо JSON при пустом `structured` |
| `tests/unit/test_mcp_servers.py` | 11 | три записи каталога в объявленном порядке, `connected` ровно у одной цели, `tool_count` только у подключённого, неразобранная цель не даёт исключения |
| `tests/unit/test_mcp_tools.py` | 15 | четыре поля контракта инструмента (`output_schema` и его глубокая копия), нормализация пустой схемы, `MCPToolResult.to_dict()` с копиями аргументов и результата |
| `tests/integration/test_mcp_server_stdio.py` | 5 | **свой** `mcp_server/server.py` дочерним процессом: каталог из **девяти** инструментов дня, `input_schema`/`output_schema`, успешный вызов и 404 как `is_error` (внешний API подменён стендом), а новые тесты вызывают `search` (источник `file:`), `summarize` и `save_to_file` по-настоящему (в день 19 файл расширен) |
| `tests/integration/test_mcp_tool_runner.py` | 10 | раннер: успех, ошибка инструмента (`tool_error`), сбой связи (`transport`), отказ правил (`not_connected`/`unknown_tool`/`bad_arguments`), `call_for_prompt` по реплике и без ключевых слов |
| `tests/integration/test_mcp_agent.py` | 8 | шаг агента: инструмент вызван по ключевым словам, данные в системном промпте (`record["system_prompt"]`), отказ аргументов и сбой инструмента ход не роняют, без соединения — `detected: false` |
| `tests/e2e/test_mcp_call_api.py` | 13 | контракт `POST /mcp/call` (409/400/422/502 и 200 с `is_error`), `GET /mcp/servers`, `output_schema` в `/mcp/tools`, поле `mcp` ответа генерации |

Новые файлы дня 16 (унаследованы):

| Файл | Тестов | Что проверяет |
|---|---|---|
| `tests/unit/test_mcp_connection_fsm.py` | 24 | таблица FSM подключения (10 переходов) и её сверка с графом, негативные пары → `UnknownMCPConnectionEvent`, идемпотентное отключение, `can`/`allowed_events`/`reset` |
| `tests/unit/test_mcp_target.py` | 23 | выбор транспорта по виду цели, разбор команды (кавычки, обратные слэши Windows-путей), `sse://` → `http://`, приоритет явного транспорта, ошибки разбора |
| `tests/unit/test_mcp_tools.py` | 8 | нормализация `name`/`description`/`input_schema`, ошибка на инструмент без имени, глубокая копия схемы в `to_dict` |
| `tests/integration/test_mcp_stdio.py` | 5 | **настоящий** MCP-сервер по stdio (`tests/mcp_echo_server.py`): соединение, непустой список с описанием и схемой, согласие кэша и `refresh`, отключение и повторное подключение, контекстный менеджер |
| `tests/integration/test_mcp_client_errors.py` | 4 | команда не найдена, недоступный HTTP-адрес, состояние `ERROR`, повтор подключения, разбор цели до соединения |
| `tests/integration/test_mcp_registry.py` | 7 | реестр: статус без подключения, число инструментов до/после `tools()`, закрытие прежнего соединения, `disconnect`/`close`, видимая ошибка после сбоя |
| `tests/e2e/test_mcp_api.py` | 7 | четыре эндпоинта: `200/400/409/422/502`, форма `/mcp/tools` с `count`, `refresh`, статус `error` после 502, отключение без соединения |

Фейки MCP живут в `tests/mcp_fakes.py`: `FakeMCPClient` повторяет публичный
контракт `MCPClient` вместе с `call_tool`, а `FAKE_TOOL_CATALOG` (шесть
инструментов: три читают внешний API, три ставят фоновые задачи) и
`make_mcp_factory` собирают сценарии. Фейки композиции — в
`tests/pipeline_fakes.py`: `PIPELINE_TOOL_CATALOG` (три инструмента пайплайна со
схемами аргументов) и `FakePipelineClient`, который отвечает **по имени
инструмента** (успехом или ошибкой), поэтому проверяются обе ветки шага, а не
только успех. Фейки планировщика — в
`tests/scheduler_fakes.py`: `FakeFetcher` (очередь ответов источника, режим
ошибки) и `SchedulerStub` (планировщик без таймеров для e2e-тестов). Тесты API
внешних серверов не поднимают, а `tests/integration/test_mcp_stdio.py` проверяет
реальное stdio-соединение на своём сервере из `tests/mcp_echo_server.py`, а
`tests/integration/test_mcp_server_stdio.py` и
`tests/integration/test_mcp_scheduler_tools.py` — на сервере дня со стендами
внешнего API и бэкенда (сеть не нужна).

Новые файлы дня 15 (унаследованы):

| Файл | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_task_state_machine.py` | 332 | 106 | граф `ALLOWED_TRANSITIONS` (все 25 пар), guards по флагам, `get_allowed_next_stages`/`get_blocked_stages`, `cleared_flags`, `guard_context`, расхождение графа и классов-этапов |
| `tests/unit/test_task_transition_texts.py` | 167 | 114 | дословные тексты отказа и подсказки для каждой недопустимой пары, длина причины ≤ 200 символов, `intent_refusal_notice` |
| `tests/unit/test_task_proposal.py` | 89 | 49 | распознавание всех фраз предложения модели, регистр, границы слов, самый дальний этап при нескольких совпадениях, `None` без фраз |
| `tests/integration/test_task_transitions.py` | 204 | 18 | журнал отклонённых попыток (`accepted = False`), отказ не меняет состояние, флаги через сервис, пауза и продолжение |
| `tests/e2e/test_task_transitions_api.py` | 191 | 7 | эндпоинты `transition`/`allowed-next`/`context`: 400 с причиной и подсказкой, 422 на пустое тело флагов и неизвестный этап, `accepted: false` в журнале |

Обновлены под новое поведение (числа — фактические):

| Файл | Строк | Тестов | Что изменилось |
|---|---|---|---|
| `tests/unit/test_task_fsm.py` | 340 | 59 | `InvalidTransitionError` вместо `InvalidTaskTransition`, пауза из `done` — ошибка, проверки графа переехали в `test_task_state_machine.py` |
| `tests/unit/test_task_prompt.py` | 230 | 33 | новый литерал блока с «Допустимые следующие этапы», «нет» при пустом списке |
| `tests/integration/test_task_state.py` | 372 | 39 | флаги на каждой границе этапов, точные тексты guard-отказов, `set_flags`, сброс флагов при откате |
| `tests/integration/test_task_store.py` | 273 | 13 | `paused_from_stage` в колонке, `accepted` в журнале, `log_rejection` не меняет состояние |
| `tests/integration/test_task_manager.py` | 232 | 15 | `transition_task` без умолчаний на стороне миксина, `set_task_flags` |
| `tests/integration/test_task_agent.py` | 265 | 15 | уведомление о неприменённом намерении, отказ на предложение модели, блок промпта с допустимыми этапами |
| `tests/e2e/test_task_api.py` | 345 | 27 | 400 с причиной и подсказкой, `allowed-next`, флаги через `PATCH`, `accepted: false` |

Унаследованные от дня 14 тесты инвариантов (141 тест, 7 файлов) не менялись:

| Файл | Что проверяет |
|---|---|
| `tests/unit/test_invariant_values.py` | значения `Enum`, списки для API-валидации, подписи, тексты ошибок на неизвестную категорию/важность |
| `tests/unit/test_invariant_rules.py` | правила-термины по всем 14 средствам, привязка правила к описанию инварианта, согласие пользователя снимает нарушение, границы слов, форма нарушения |
| `tests/unit/test_invariant_prompt.py` | дословный блок промпта, тексты отказа и предупреждения, сообщение для LLM-проверки |
| `tests/integration/test_invariant_manager.py` | CRUD правил, уникальность имени, фильтры по категории и активности, ошибки 404/409/422, независимость от диалога агента |
| `tests/integration/test_invariant_checker.py` | правила → LLM, мусор и сбой модели, пустой текст, дедупликация и приоритет вердиктов в `merged_with` |
| `tests/integration/test_invariant_agent.py` | блок в системном промпте, отказ без вызова DeepSeek, предупреждение вместе с ответом, пост-проверка ответа, сбой LLM-слоя не роняет ход |
| `tests/e2e/test_invariant_api.py` | шесть эндпоинтов: коды 201/404/409/422, фильтры списка, проверка текста, поле `invariants` в ответе генерации, корневой ответ и OpenAPI |

Отдельно проверено, что проверка инвариантов **не меняет поведение** при пустой
таблице правил: промпт без блока, `checked == []`, ни одного лишнего вызова
клиента — поэтому правки в унаследованных наборах дня 13 не потребовались.

Тесты работают офлайн: клиент DeepSeek подменяется фейком (`tests/support.py`),
база — временная SQLite. Рядом живут наследованные наборы дней 9–13: слои памяти
(`MemoryManager`: сессии, upsert по задаче и категории, отбор релевантных
записей; `Agent`: блоки памяти в системном сообщении, `new_session`, `set_task`,
восстановление сессии/задачи из БД), десять эндпоинтов `/memory/...`,
`prepare_context` всех четырёх стратегий, факты, ветки, FSM сжатия, политика,
хранилище, компрессор, метрики, персонализация, состояние задачи и API дня 9.

Унаследованные тесты дня 13 (состояние задачи), 8 файлов, обновлены там, где
день 15 изменил поведение (см. таблицу «Обновлены под новое поведение»). Не
менялся только `tests/unit/test_task_intent.py` (63 теста): распознавание
намерения реплики (`пауза`/`продолжи`/`откат`/`подтверждаю`) по таблице фраз с
приоритетом групп и границами слов.

## Наследовано из дня 11: стратегии и сжатие

Атрибут агента `strategy` принимает одно из четырёх значений (`Enum Strategy`,
`backend/domain/strategies.py`); сборка контекста — метод `Agent.prepare_context()`:

| Стратегия | Что уходит в DeepSeek | Сильная сторона |
|---|---|---|
| 🪟 `sliding_window` | системный промпт + последние `window_size` реплик | самый дешёвый и предсказуемый |
| 📌 `sticky_facts` | системный промпт (+факты «ключ: значение») + последние N | детали не теряются — факты хранятся в таблице `facts` |
| 🌿 `branching` | системный промпт + вся история активной ветки | ничего не теряет + ветвление диалога (`checkpoints`) |
| 🗜 `summary` | системный промпт (+конспект) + последние непокрытые реплики | сбалансированный компромисс (день 9) |

Здесь стратегия решает ровно одно: **как собрать краткосрочный слой** — сколько
последних реплик сессии уходит в запрос и в каком виде. Рабочая и долговременная
память подставляются блоками системного сообщения независимо от стратегии,
поэтому смена стратегии их не затрагивает. Блок профиля пользователя
подставляется так же — независимо от стратегии, но раньше всех остальных блоков
(см. «Как профиль попадает в запрос»), а блок состояния задачи — независимо от
стратегии и последним (см. «Состояние задачи»).

Переключатель — в сайдбаре («⚙️ Стратегия контекста»): выпадающий список
стратегии + слайдер `window_size`. Сравнение четырёх стратегий с таблицей
качества/стабильности/расхода токенов — в
[`../day10/comparison.md`](../day10/comparison.md); подробная инструкция по
стратегиям, сжатию, фактам и веткам — в
[`../day10/docs/usage.md`](../day10/docs/usage.md).

## Возможности

* **Три инструмента композиции на своём сервере**: `search` (источники
  `posts`/`users`/`file:<путь>`/`sqlite:<таблица>`), `summarize` (DeepSeek, а без
  ключа — движок агрегации) и `save_to_file` (только каталог `output/`, форматы
  `txt`/`md`/`json`). Источник `file:` не выходит за пределы папки дня, а
  `sqlite:` открывает базу дня **только на чтение**.
* **Декларативный пайплайн**: конфигурация `search-summarize-save` — три шага,
  аргументы которых собираются из данных запуска (`{имя}`) и результатов
  предыдущих шагов (`$steps.<i>.<путь>`), с условиями перехода
  `non_empty`/`empty`/`equals`/`contains`. Свою конфигурацию можно прислать в API,
  а встроенная живёт в одном месте — `backend/domain/pipeline_spec.py`.
* **Журнал и три исхода прогона**: каждый шаг ложится строкой в `pipeline_steps`
  (аргументы, результат, время, статус) даже при отказе маппинга; прогон
  заканчивается как `completed`, `stopped` (условие шага не выполнено — например
  «нет данных для обработки» на пустом поиске) или `failed` (`failed_at_step` и
  текст причины). Ошибка инструмента приходит данными (`reason_code`), а не
  исключением.
* **Запуск пайплайна агентом**: реплика «найди статьи про RAG, сделай сводку и
  сохрани в файл» распознаётся по ключевым словам, пайплайн идёт синхронно до
  проверки лимита контекста и до шага одиночного инструмента, а результат
  подставляется блоком «## Результат пайплайна» (`record["pipeline"]`).
* **Раздел «🔀 Пайплайны»**: форма запуска, прогресс по шагам с обновлением раз в
  секунду (`@st.fragment(run_every="1s")`), схема потока данных с объёмами на
  переходах, путь сохранённого файла и история запусков с деталями шагов и
  удалением; в чате — строка «🔀 Пайплайн: …» в сводке хода.
* **Пять эндпоинтов `/pipelines`**: запуск (синхронно или в фоновом потоке),
  список запусков с фильтром статуса, отчёт запуска, его шаги и удаление — всего в
  API дня **78** эндпоинтов.
* **Сквозной прогон и отчёт**: `uv run python scripts/pipeline_demo.py --report
  docs/reports/pipeline_demo.md` проходит четыре сценария офлайн (успех, пустой
  поиск, ошибка шага, запуск через агента) на своём stdio-сервере с источником
  `mcp_server/data/notes.md` и собирает отчёт с трассировкой шагов; 26 из 26
  проверок, доказательство —
  [docs/reports/pipeline_demo.md](docs/reports/pipeline_demo.md).
* **Фоновые задачи в процессе бэкенда**: `TaskScheduler` поднимает
  `AsyncIOScheduler` в `lifespan` и останавливает его на выходе; тик — обычная
  функция, поэтому APScheduler выполняет её в пуле потоков и цикл событий FastAPI
  не блокируется.
* **Три инструмента с отложенным и периодическим выполнением**:
  `schedule_reminder` (разовое напоминание через N секунд), `collect_data`
  (периодический сбор JSON по адресу) и `generate_summary` (регулярная сводка по
  накопленным данным) — всего в каталоге MCP-сервера дня девять инструментов:
  эти три, три инструмента данных и три инструмента композиции.
* **Задачи переживают перезапуск**: источник правды — таблица `scheduled_tasks`,
  APScheduler держит таймеры в памяти; при старте `sync_from_db()` снимает
  таймеры удалённых задач, ставит новые активные и записывает фактическое
  `next_run_time`, а пропущенный запуск догоняется сразу.
* **Сверка БД и таймеров раз в 5 секунд** (`SCHEDULER_SYNC_SECONDS`): задача,
  созданная другим процессом (MCP-сервером через `POST /scheduler/tasks`),
  подхватывается без перезапуска.
* **Один код-путь для инструмента, API и интерфейса**: тела трёх инструментов —
  один вызов `POST /scheduler/tasks`; проверка аргументов, расписание и
  немедленное действие живут в `ScheduleService.create_task`, а единственный
  писатель в SQLite — процесс бэкенда.
* **Распознавание фоновой задачи по реплике**: «напомни мне через 30 секунд
  проверить почту», «собирай данные с …/posts каждые 10 секунд», «покажи сводку
  за последний час» — правила дня 18 проверяются раньше правил дня 17, а правила
  пайплайна (день 19) — раньше их обеих, поэтому реплика про поиск со сводкой и
  файлом не уходит в одиночный инструмент. В ответе
  генерации видно поле `schedule` (что запланировано и с каким расписанием).
* **Напоминания и очередь уведомлений**: тик помечает напоминание выполненным
  (`reminders.status = "done"`) и кладёт уведомление в `notifications`; область
  чата показывает непрочитанные с кнопкой «✔ Прочитано» и обновляется сама раз в
  5 секунд.
* **Сводки с метриками**: `aggregate_records` считает по накопленным записям
  числовые поля (`count`/`avg`/`min`/`max`), категориальные (`unique` и примеры),
  источники и типы payload; текст сводки и `key_metrics` лежат в
  `periodic_summaries`, а пустой период — тоже сводка (`total_records = 0`).
* **Состояние задачи как FSM**: `active → paused → active` и
  `active → completed`; недопустимое событие — отказ 409 с текстом, список задач
  отдаёт `allowed_events`, поэтому кнопки интерфейса рисуются по ответу API.
* **Раздел «🗓 Планировщик»**: таблица задач со расписанием и метками запусков,
  форма создания по аргументам инструмента, пауза/возобновление/запуск сейчас/
  удаление, напоминания с фильтром, сводки с кнопкой «Показать текст» и журнал
  запусков выбранной задачи.
* **Сквозной прогон и отчёт**: `uv run python scripts/scheduler_demo.py --report
  docs/reports/scheduler_demo.md` проходит четыре сценария задания на
  изолированном стенде (своя БД, офлайн-заглушка модели, детерминированный
  источник) и собирает отчёт с таблицей инструментов и схемой шести таблиц;
  доказательство — [docs/reports/scheduler_demo.md](docs/reports/scheduler_demo.md).
* **Свой MCP-сервер в дне**: `day19/mcp_server/` (транспорт stdio, имя
  `day19-pipeline`, версия `1.2.0`) с **девятью**
  инструментами: три читают jsonplaceholder — `get_user`, `get_post`,
  `list_user_posts`, три ставят фоновые задачи — `schedule_reminder`,
  `collect_data`, `generate_summary`, три собирают пайплайн — `search`,
  `summarize`, `save_to_file`. Запускается
  `uv run python mcp_server/server.py`, а при подключении по stdio поднимается
  дочерним процессом.
* **Вызов инструмента**: `POST /mcp/call` и `MCPClient.call_tool` (`tools/call`);
  `structuredContent` ответа разбирается в `MCPToolResult`, ошибка инструмента
  приходит данными (`is_error`), а отказ запроса — кодами 400/409/502.
* **Правила допуска перед вызовом**: соединение, инструмент в каталоге,
  обязательные аргументы и типы по `input_schema` (`admission_reason`), а
  жизненный цикл вызова — стейт-машина `MCPToolCallFSM` с кодами причин отказа.
* **Агент вызывает инструмент сам**: по ключевым словам реплики (`mcp_intent`)
  агент вызывает инструмент, подставляет данные блоком в системный промпт этого
  же запроса и показывает в ответе, что вызвал (`record["mcp"]`).
* **Каталог серверов**: `GET /mcp/servers` — свой сервер дня и два сервера
  официального набора (fetch, filesystem); `connected` истинно ровно у одной
  цели, сравнение — по нормализованному виду команды.
* **Понятные ошибки вместо traceback**: одна строка «что делали → что случилось
  → что проверить» (нет команды в PATH, истёк таймаут, проверьте URL, id вне
  диапазона) — её показывают плашка интерфейса, `detail` ответа API
  (`400`/`409`/`502`) и консольный скрипт.
* **Одно соединение и корректное закрытие**: реестр держит один клиент, новое
  подключение закрывает прежнее, `POST /mcp/disconnect` и остановка бэкенда
  завершают сессию и дочерний процесс stdio-сервера.
* **Скрипт сквозного прогона**: `uv run python scripts/mcp_tool_demo.py`
  (`--target`, `--api-base`, `--timeout`, `--live`, `--tests`, `--json`,
  `--report`) проходит каталог, три успешных вызова, три отказа и шаг агента;
  ключ DeepSeek не нужен (офлайн-заглушка), `--live` берёт настоящую модель.
* **Доказательство прогона**:
  [docs/reports/mcp_tool_demo.md](docs/reports/mcp_tool_demo.md) — сервер дня,
  каталог с обеими схемами, вызовы и отказные случаи, фрагмент системного
  промпта с блоком данных.
* **Контролируемые переходы по явному графу**: `ALLOWED_TRANSITIONS` в
  `backend/domain/task_state_machine.py` — единственный источник правил допуска;
  то, чего в графе нет (`planning → done`, `paused → done`), отклоняется с
  объяснением, а не выполняется молча.
* **Согласование на границах этапов**: три перехода прямого хода требуют флага
  (`plan_approved`, `implementation_complete`, `validation_passed`); реплика
  пользователя флаг не подставляет — его выставляют явно в панели задачи
  (чекбоксы) или через `PATCH /tasks/{id}/context`.
* **Журнал отклонённых попыток**: строки `task_transitions` с `accepted = False`
  показывают, что именно пробовали сделать, почему отказано и когда; состояние
  задачи при отказе не меняется.
* **Отказ на предложение модели**: ответ «задача завершена» на непройденном этапе
  заменяется объяснением (`🚧 Ответ предлагает переход в done…`), а неприменённое
  намерение реплики даёт уведомление (`⚠️ Переход по реплике … не выполнен`).
* **Движение назад сбрасывает согласования**: флаг этапа-цели и всех последующих
  этапов очищается (`cleared_flags`), поэтому откат нельзя «переиграть» старым
  подтверждением.
* **Инварианты проекта в отдельной таблице**: правила (`invariants`) не лежат в
  истории сообщений — их не вымывает сжатие контекста; блок активных правил
  подставляется в системный промпт каждого запроса сразу после роли агента.
* **Проверка предложения перед выдачей**: сначала детерминированные правила (без
  сети), при неоднозначности — один вызов LLM со списком правил; результат виден
  в ответе генерации (`invariants.verdict`, `violations`, `checked`).
* **Отказ при нарушении hard-инварианта**: агент объясняет, какое правило нарушено,
  и не обращается к DeepSeek вовсе (токены не тратятся); нарушение soft даёт
  предупреждение в начале ответа, но решение предлагается.
* **Раздел «📏 Инварианты»**: таблица правил с фильтрами, форма создания, правка,
  включение-выключение и удаление, а также проверка любого текста тем же путём,
  что у агента.
* **Доказательство трёх исходов**: [`invariants_demo.md`](invariants_demo.md) —
  три сценария офлайн (`uv run python scripts/invariants_demo.py`), без ключа и
  сети: разрешено / предупреждение / отказ.
* **Посев правил одной командой**: `uv run python scripts/seed_invariants.py`
  (идемпотентно, `--reset` пересобирает список).
* **Состояние задачи как конечный автомат**: этапы `planning` → `execution` →
  `validation` → `done`, шаги внутри этапа, ожидаемое действие и журнал
  переходов; допуск считает граф `ALLOWED_TRANSITIONS` с guard-условиями, а
  состояние живёт в SQLite (`task_states`, `task_transitions`) и читается на
  каждый запрос, поэтому переживает перезапуск процесса.
* **Пауза и продолжение с того же места**: `POST /tasks/{id}/pause` сохраняет
  этап в колонку `paused_from_stage` (шаг остаётся в `current_step`),
  `POST /tasks/{id}/resume` возвращает в них же — агенту не нужно объяснять, где
  он остановился. Явное продолжение в другой доступный этап — тоже разрешённый
  переход, а не «телепорт» мимо правил.
* **Обновление состояния обычной репликой**: «пауза», «продолжи», «подтверждаю»,
  «вернись на предыдущий этап» меняют состояние до сборки контекста, поэтому
  блок в промпте этого же запроса уже описывает новое состояние; недопустимая
  реплика отклоняется и не роняет диалог.
* **Раздел «🧭 Состояние задачи»**: подпись «задача · агент · обновлено», этап и
  шаг, ожидаемое действие, допустимые следующие этапы, ASCII-схема переходов,
  кнопки-этапы (недоступные заблокированы, причина — в подсказке), кнопка
  «⏭ Следующий шаг», пауза/продолжение, чекбоксы флагов и журнал в двух вкладках:
  выполненные переходы и отклонённые попытки.
* **Доказательство переживания рестарта**: `docs/reports/task_state_demo.md` — пять фаз в пяти
  отдельных процессах, от постановки задачи до `done`.
* **Доказательство правил допуска**:
  [`docs/reports/controlled_transitions_demo.md`](docs/reports/controlled_transitions_demo.md) —
  две фазы в разных процессах: недопустимые переходы с причинами, флаги
  согласования, продолжение после паузы и отказ агента на предложение модели
  (`uv run python scripts/controlled_transitions_demo.py`, офлайн).
* **Автопроверка кадров сценария видео**:
  `uv run python scripts/video_scenario.py --all` проходит кадры §8 инструкции
  `docs/usage.md` и печатает доказательство каждого — проверки по HTTP плюс
  реальный рендер интерфейса через Streamlit AppTest, а пауза доказывается
  вторым процессом бэкенда (два разных pid на одной БД). Расхождение кода и
  кадра — `✗` и код возврата 1; прогон офлайн, на своей `video_scenario.db`.
* **Автоматический проход в настоящем браузере**:
  `uv run python scripts/video_scenario.py --auto` поднимает тот же
  изолированный бэкенд и живой Streamlit, открывает Chromium и сам проходит
  кадры §8 в темпе демонстрации — пауза между действиями (`--pace`, по умолчанию
  **2 с**), набор текста по символам (`--typing`, 120 мс), наведение и прокрутка
  перед кликом, поэтому **весь прогон укладывается в 3–4 минуты** (замерено
  3 мин 37 с в окне и 3 мин 34 с без окна) и годится для записи целиком;
  `--pace 6` замедляет показ, `--pace 0.15 --typing 1` — машинная проверка за
  минуту. В терминале рядом идут строки «▸ …» о текущем действии и проверки
  `✓`/`✗`. Кадры сверяются тем, что видно в DOM (карточка задачи, подписи и
  блокировка кнопок, причины отказа, ответ агента), а содержимое журнала —
  по HTTP: он рисуется `st.dataframe` (canvas) и из DOM не читается.
  Нужен один раз `uv run playwright install chromium`.
* **Стенд для съёмки видео**: `uv run python scripts/video_scenario.py --ui`
  поднимает живой `streamlit run app.py` на том же изолированном бэкенде
  (своя БД, свой порт, `DAY19_BACKEND_URL`), открывает адрес в браузере и
  печатает чек-лист кадров §8 — что нажать и что должно получиться; кадр 5
  (пауза) доказывается по Enter: стенд перезапускает бэкенд на той же БД и
  печатает прочитанное из SQLite состояние.
* **Персонализация каждого запроса**: профиль пользователя (`user_profiles`)
  подставляется первым блоком системного сообщения при любой стратегии
  контекста, а ответ генерации показывает, что именно применилось (`profile`,
  `system_prompt`).
* **Три готовых профиля одной кнопкой**: «Строгий технический», «Дружелюбный
  наставник» и «Оркестратор процесса» из `backend/domain/demo_profiles.py`; рядом —
  форма создания профиля, редактирование всех полей, предпросмотр блока промпта
  и удаление профиля.
* **Сравнение двух профилей на одном вопросе** в интерфейсе (два ответа рядом +
  «что повлияло на ответ» и системный промпт) и офлайн-отчёт
  [`docs/reports/personalization_comparison.md`](docs/reports/personalization_comparison.md)
  (`uv run python scripts/personalization_comparison.py --no-api` — без сети и ключа).
* **Живое применение настроек**: `PUT /users/{user_id}/profile` сразу рассылает
  профиль агентам пользователя (`applied_to_agents`), `PATCH /agents/{agent_id}`
  переключает профиль живого агента — перезапуск бэкенда не нужен.
* **Три явных слоя памяти**: краткосрочная (сессия), рабочая (задача),
  долговременная (профиль/предпочтения/решения/знания) — отдельные таблицы со
  своим ключом и жизненным циклом, общий `MemoryManager`.
* **Явная маршрутизация «что куда»**: записи в рабочую и долговременную память
  попадают только через формы вкладок или `POST /memory/...`, профиль — только
  через раздел «👤 Профиль пользователя» или `/users/...`; ход диалога пишет
  лишь краткосрочную пару реплик.
* **Разбивка контекста по слоям** в ответе `POST /agents/{id}/generate`
  (`memory.layers`: что использовано, сколько записей и токенов) и в UI —
  индикатор «🧭 Что ушло в последний запрос» с ключевыми словами отбора.
* **Слои памяти в UI**: три вкладки — панели «👤 Краткосрочная» (реплики сессии +
  очистка), «🗂 Рабочая» (форма upsert-записи задачи), «🧠 Долговременная»
  (фильтр по категории, уверенность 0–1, удаление записи).
* **Задача и сессия в сайдбаре**: переключатель активной задачи, создание новой
  задачи, кнопка «🆕 Новая сессия» (обнуляет краткосрочный слой, сохраняя
  рабочую, долговременную память и профиль).

Наследовано из дней 9–10: четыре стратегии контекста (`sliding_window`,
`sticky_facts`, `branching`, `summary` с переключателем на живом агенте), сжатие
истории в конспект (`summaries`, FSM, экономия токенов), факты «ключ: значение»
(`facts`), ветвление истории (`checkpoints`), подсчёт токенов (tiktoken) и
таблица `token_usage` с расходом по слоям.
Ошибки без traceback, при сбое генерации память не портится, UI жив при
недоступном бэкенде (паттерн дней 6–10).

## Ограничения

- **Пайплайн — линейная цепочка.** Шаг идёт за шагом, условие может только
  остановить прогон целиком: ветвлений (выбор продолжения по значению) и
  параллельного запуска независимых шагов нет.
- **Повторов упавших шагов нет.** Ошибка шага останавливает прогон; политик
  retry, таймаутов на шаг и компенсации побочных эффектов (удалить созданный файл
  при отказе) день не делает. Возобновления «продолжить с шага 2» по записанным
  результатам тоже нет — повторный запуск это новый прогон.
- **Прогон из интерфейса и API живёт в потоке бэкенда.** Фоновый запуск — это
  `threading.Thread` процесса бэкенда, поэтому при его остановке прогон
  обрывается; сессии короткие (на операцию), а движок дня
  (`shared/db_base.make_engine`) создаётся с `check_same_thread=False`.
- **Сводка без ключа — агрегация.** Модель отвечает непредсказуемо, поэтому
  демонстрация и тесты идут с `--llm off` и движком `aggregation`; при живом
  ключе текст сводки — ответ DeepSeek, и его длина оценивается по факту.
- **`save_to_file` пишет только в каталог дня `output/`.** Абсолютный путь в
  имени файла или `..` — отказ; расширение заменяется на запрошенный формат.
  Источник `file:` у `search` тоже не выходит за пределы папки дня, а источник
  `sqlite:` читает только три разрешённые таблицы (`collected_data`,
  `periodic_summaries`, `pipeline_steps`).
- **Распознавание пайплайна в реплике — эвристика.** Нужны фразы всех трёх групп
  (поиск, сводка, сохранение); запрос берётся из оборота «про …» либо из первых
  слов реплики, поэтому сложные формулировки могут дать не тот `query`.
- **Один экземпляр приложения на одну БД.** Планировщик живёт в процессе бэкенда:
  второй экземпляр на той же `day19/agents.db` получит собственную копию таймеров
  и будет выполнять те же задачи. День рассчитан на один процесс.
- **Доставки уведомлений вне приложения нет.** Уведомление — строка в
  `notifications` и плашка в области чата; писем, push и сообщений в мессенджеры
  день не отправляет, пока интерфейс закрыт, уведомление просто ждёт прочтения.
- **cron — только через переопределение расписания.** Три инструмента создают
  расписания `date` и `interval`; для cron нужно передать
  `schedule_type: "cron"` и `schedule_value: {"cron": "*/5 * * * *"}` в
  `POST /scheduler/tasks`. Ближайший запуск cron-задачи в БД пишет APScheduler,
  а не домен.
- **Сбор данных зависит от внешнего адреса.** Тик `collect_data` делает настоящий
  HTTP-запрос: без сети, при 4xx/5xx или если тело ответа больше
  `COLLECT_MAX_BYTES = 262144` байт, запуск пишется как `task_runs.status = "error"`
  с уведомлением, а задача остаётся активной и повторится. Источник должен
  отдавать JSON: произвольный текст инструмент не разбирает.
- **Уведомление о сводке — только первые 200 символов** её текста
  (`NOTIFICATION_SUMMARY_MAX`); полный текст лежит в `periodic_summaries.content`
  и открывается в интерфейсе кнопкой «📄 Показать текст».
- **Фоновые задачи не восстанавливают таймеры между процессами.** Источник правды
  (`scheduled_tasks`) переживает рестарт, но сверка БД и таймеров идёт раз в
  5 секунд: после записи задачи другим процессом возможна пауза до этого
  интервала, а пропущенный запуск догоняется сразу только у `interval`/`date`.
- **Напоминание без своего `reminder_id` не выдаётся.** Номер напоминания
  дописывается в аргументы задачи при регистрации; если строку задачи отредактировать
  в БД руками и убрать поле, тик вернёт ошибку «не с чем связать» (в журнале —
  `status = "error"`).
- **MCP-подключение не переживает рестарт бэкенда.** Оно живёт в памяти процесса
  (`MCPRegistry`), таблиц у подсистемы нет: после перезапуска `/mcp/status`
  отвечает `disconnected`, и подключиться нужно снова. Остальное состояние дня
  (память, профили, задачи, инварианты, метаданные планировщика, запуски и шаги
  пайплайна) — в SQLite.
- **Одно MCP-подключение на процесс.** Подключение к другому серверу закрывает
  прежнее — реестра по имени у дня нет; поэтому каталог `GET /mcp/servers` — это
  список известных целей, а не открытых соединений.
- **Вызовы идут наружу, в живой внешний API.** Свой сервер читает
  jsonplaceholder.typicode.com по HTTP: без сети инструмент вернёт «Внешний API
  недоступен», а офлайн-прогон подменяет его локальным стендом
  (`tests/stub_api.py`) — тем же приёмом тесты обходятся без сети. У инструментов
  композиции есть офлайн-путь: источники `file:` и `sqlite:` читают файл дня и
  базу дня, поэтому демонстрация пайплайна проходит без сети (внешняя лента
  нужна только источникам `posts`/`users`).
- **Выбор инструмента — эвристика по ключевым словам**, а не решение LLM: она не
  понимает смысл реплики и не разбирает несколько инструментов в одном запросе.
  Фразы и приоритет — `INTENT_RULES` в `backend/domain/mcp_intent.py`.
- **В промпт уходит только успешный результат.** Отказ правил, ошибка инструмента
  и обрыв связи видны в отчёте `record["mcp"]`, но блока данных в системном
  промпте не дают — модель отвечает без этих данных.
- **Аргументы проверяются по `input_schema`, но не приводятся к типу.** Строка
  `"1"` вместо числа — это отказ `bad_arguments`, а не «понимание» аргумента.
- **Живой проверки HTTP/SSE-транспорта нет.** Обе ветки покрыты тестами разбора
  цели и ошибок, но прогон дня шёл на stdio: своём сервере и серверах
  `mcp-fetch`/`server-filesystem`.
- **stdio-серверы официального набора зависят от внешних команд.**
  `uvx mcp-server-fetch` требует `uv`, `npx …server-filesystem` — Node ≥ 18; без
  команды подключение падает с подсказкой про PATH, но не поднимает сервер само.
  Своему серверу дня, кроме `uv`, ничего не нужно.
- **Наследованные скрипты прогона кадров дня 15** (`scripts/video_scenario*.py`)
  проверяют прежний сценарий (контролируемые переходы) и ссылаются на §8
  инструкции, которого в `usage.md` дня 19 нет: файл описывает инструменты
  композиции и пайплайн.
- Один процесс бэкенда и один файл `day19/agents.db` (в `.gitignore` по `*.db`).
  Прогон отчёта персонализации работает на отдельной базе
  `day19/personalization_demo.db`, демонстрация состояния задачи — на
  `day19/task_state_demo.db`, демонстрация контролируемых переходов — на
  `day19/controlled_transitions_demo.db`, демонстрация MCP-инструментов — во
  временном каталоге (`mcp_tool_demo.db`, удаляется после прогона), прогон
  пайплайна — тоже во временном каталоге (`<tmp>/agents.db` из `--db`,
  удаляется вместе с ним, а файл-артефакт пишется в `day19/output/`), прогон
  планировщика — тоже во временном каталоге (`scheduler_run.db`, остаётся при
  `--keep-db`), автопроверка
  кадров сценария видео — на `day19/video_scenario.db` (плюс временный
  `video_scenario.db.pid` с pid
  бэкенда прогона, он удаляется после чтения); все четыре базы пересоздаются при
  прогоне с `--reset`/стартом. Прогон кадров `--all` и стенд `--ui` делят одну
  `video_scenario.db`, поэтому одновременно идёт только один из них: второй
  честно скажет, что БД занята, и попросит остановить первый (Ctrl+C).
- `task_id` уникален **глобально**, а не в пределах агента: состояние ищется по
  одному `task_id`. Два агента не могут вести задачи с одинаковым именем.
- Откат возможен ровно на один этап назад (`validation → execution`,
  `execution → planning`); из `planning`, `done` и `paused` откат не описан.
  Пауза разрешена из `planning`, `execution` и `validation`; из `done` пауза
  **отклоняется** — этап терминальный (день 15).
- Переходы прямого хода требуют флага согласования, а флаги не выставляются
  автоматически: пока пользователь не отметил «📝 План утверждён», задача не
  выйдет из `planning` даже по реплике «подтверждаю» — переход будет отклонён с
  объяснением. Движение назад сбрасывает согласования (`cleared_flags`), поэтому
  после откролла флаг придётся выставить заново.
- Предложение модели распознаётся таблицей фраз (`backend/domain/task_proposal.py`),
  а не структурированным протоколом: «задача завершена» в середине рассуждения
  тоже считается предложением перейти в `done` (и будет отклонено, если этап не
  пройден). Фразы и приоритет — `STAGE_PROPOSAL_PHRASES`.
- Отклонённая попытка перехода меняет только журнал (`accepted = False`) и не
  меняет состояние задачи; такую строку нельзя «отменить» через API — она
  остаётся историей попыток.
- Распознавание намерения в реплике — эвристика по фразам
  (`backend/domain/task_intent.py`), а не LLM: «готово» в середине рассуждения о работе
  тоже считается подтверждением шага. Фразы и приоритет групп — в таблице
  `INTENT_PHRASES`.
- `new_session()` удаляет данные, производные от старого диалога: реплики его
  сессии, конспекты (`summaries`) и факты (`facts`). Рабочая и долговременная
  память, снимки веток (`checkpoints`) и метрики (`token_usage`) сохраняются,
  то есть счётчик токенов и стоимость живут дольше одной сессии; профиль
  пользователя `new_session()` тоже не трогает.
- Долговременные записи добавляются вручную (через UI или API) — LLM-извлечения
  профиля и предпочтений нет; переноса `facts` в долговременную память тоже нет
  (при необходимости их пишут в категорию `knowledge`).
- Профиль заполняется вручную (форма раздела «👤 Профиль пользователя» или
  `POST/PUT /users/{user_id}/profile`) — автоматического извлечения предпочтений
  из диалога нет, как и переноса записей долговременной памяти в профиль.
- `PUT /users/{user_id}/profile` — **замена**: поля, не переданные в запросе,
  сбрасываются в «не настроено»; `created_at` сохраняется, `updated_at` растёт.
- Внешнего ключа между `user_profiles` и `agents` нет: после удаления профиля
  агенты продолжают работать — просто без персонализации.
- Стиль и формат ответа модель соблюдает приблизительно (наблюдения — в
  `docs/reports/personalization_comparison.md`): обязательна подстановка блока профиля в
  промпт каждого запроса, а длина и разметка оцениваются по факту ответа.
- Отбор долговременных записей для контекста — эвристика по ключевым словам с
  добором по уверенности (детерминированная, без эмбеддингов); в запрос уходит
  не больше `LONG_TERM_LIMIT = 5` записей.
- Активная ветка (branching) хранится в памяти и сбрасывается при рестарте
  бэкенда; дерево веток в `checkpoints` при этом сохраняется.
- Переключение ветки перезаписывает краткосрочный слой (`short_term_messages`)
  снимком выбранной ветки.
- Извлечение фактов — эвристика (`ключ: значение`), а не LLM-извлечение.
- Оценки tiktoken (`cl100k_base`) приблизительны: DeepSeek использует свой
  токенизатор; для запроса/ответа приоритет — фактические `usage` API.
- Лимиты контекста 8K/32K демонстрационные; правка — `MODEL_TOKEN_LIMITS` в
  `backend/core/config.py`.
- Суммаризация всегда идёт на `deepseek-chat` (temperature 0.2); при коротких
  репликах конспект может оказаться дороже заменяемых сообщений.
- Проверка инвариантов по умолчанию добавляет **один вызов DeepSeek на ход** —
  но только тот ход, который дошёл до генерации и в котором детерминированные
  правила нарушений не нашли. Отказ по hard-инварианту в запросе вызова не делает
  вовсе. Нулевая стоимость — `INVARIANT_LLM_CHECK = False` в
  `backend/core/config.py` (так работает офлайн-отчёт `scripts/invariants_demo.py`).
- Сбой LLM-слоя проверки не отменяет ход: вердикт считается по правилам, а
  причина попадает в `invariants.note`. Это значит, что при недоступном API
  семантическое нарушение (которое правила не видят) останется незамеченным.
- Детерминированные правила ловят упоминание средства, а не смысл: «не используем
  React» тоже даст сигнал. Правило действует, только если само описание инварианта
  называет это средство, — поэтому список запрещённого в описании должен быть явным.
- Имена инвариантов уникальны **глобально**: повторное имя — 409. Демо-правила,
  уже заведённые вручную, при посеве не дублируются (`--reset` пересоберёт список).
- Инварианты — глобальные: они описывают проект и одинаковы для всех агентов;
  персональных правил «для одного агента» нет.
