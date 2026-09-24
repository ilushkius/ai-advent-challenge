# День 19 — MCP-инструменты композиции и декларативный пайплайн

Инструкция по приложению дня 19. День добавляет к агенту дня 18 **три MCP-инструмента
композиции** на собственном MCP-сервере дня и **декларативный пайплайн**, который
соединяет их в последовательность «найти → свести → сохранить»:

|Инструмент|Что делает|
|---|---|
|`search`|ищет элементы в источнике: лента jsonplaceholder (`posts`, `users`), файл внутри папки дня (`file:<путь>`) или таблица SQLite дня (`sqlite:<таблица>`)|
|`summarize`|собирает сводку списка элементов и выделяет ключевые пункты: DeepSeek, а без ключа — агрегация по заголовкам|
|`save_to_file`|пишет текст в файл формата `txt`/`md`/`json` в каталоге дня `output/`|

Пайплайн — это данные, а не код: конфигурация (имя, шаги, аргументы, условия перехода)
проверяется, шаги выполняются по порядку, и каждый шаг логируется в SQLite
(`pipeline_runs`, `pipeline_steps`) с входными аргументами, выходным результатом и
временем выполнения. Прогон останавливается на первом неуспешном шаге, а ошибка шага —
это данные (`reason_code` + текст), а не падение процесса.

В приложении появился раздел «🔀 Пайплайны» (запуск, прогресс по шагам раз в секунду,
схема потока данных, история запусков), API вырос на пять эндпоинтов `/pipelines/*`
(всего 78), а реплика «найди статьи про RAG, сделай сводку и сохрани в файл»
распознаётся агентом и запускает пайплайн до обращения к модели. Прогон дня — скриптами
`scripts/pipeline_demo.py` и `scripts/pipeline_report.py` с отчётом
[reports/pipeline_demo.md](reports/pipeline_demo.md).

Как устроено внутри — [architecture.md](architecture.md), эндпоинты с примерами —
[api.md](api.md), карта модулей — [../STRUCTURE.md](../STRUCTURE.md).

## 1. Что нужно для запуска

|Компонент|Зачем|Проверка|
|---|---|---|
|Python 3.14 и `uv`|зависимости дня и запуск|`uv --version`|
|Ключ `DEEPSEEK_API_KEY`|не обязателен: включает ветку LLM в `summarize` и ответы чата|`day19/.env`|
|Порт 8000|API дня; в его процессе работают планировщик и фоновые прогоны пайплайна|`curl http://127.0.0.1:8000/` → `"pipelines": "/pipelines/run, …"`|
|Сеть до jsonplaceholder|только для источников `posts`/`users`; источники `file:` и `sqlite:` работают офлайн|`curl -s -o /dev/null -w "%{http_code}" https://jsonplaceholder.typicode.com/posts` → `200`|
|Соединение с MCP-сервером дня|шаги пайплайна вызывают инструменты только через него|раздел «🔀 Пайплайны» → «🔌 Подключиться к серверу дня»|

Пайплайн работает **без ключа DeepSeek**: если ключ не задан (или MCP-сервер запущен с
`--llm off`), `summarize` собирает сводку агрегацией — из заголовков элементов, с полем
`engine: "aggregation"`. Ключ включает ветку LLM (`engine: "llm"`) и нужен ещё для
ответов агента в чате. Сбой LLM не делает шаг неуспешным: инструмент сообщает об этом в
лог и переходит к агрегации.

Соединение с MCP-сервером обязательно: без него шаги получают
`reason_code: "not_connected"` и прогон завершается статусом `failed` — это видно в
журнале шагов (`GET /pipelines/runs/{run_id}/steps`).

## 2. Установка и запуск

Менеджер зависимостей — `uv`: прямые зависимости в `pyproject.toml`, точные версии — в
`uv.lock`, интерпретатор — `.python-version`. Активировать окружение не нужно, `uv run`
сам находит `.venv`. Все команды — из папки дня:

```bash
cd day19
uv sync                  # создать .venv по uv.lock
cp .env.example .env     # затем впишите DEEPSEEK_API_KEY=sk-... (не обязательно)
```

`uv sync` нужно выполнить **до** первого запуска: и бэкенд, и `uv run streamlit`
поднимаются в этом окружении.

Терминал 1 — бэкенд. В его процессе живут планировщик и фоновые прогоны пайплайна,
поэтому фон существует, пока работает бэкенд:

```bash
uv run uvicorn backend.api.main:app --port 8000
```

Терминал 2 — интерфейс: <http://localhost:8501>

```bash
uv run streamlit run app.py
```

Ключ бэкенд читает так: `day19/.env` → переменная окружения `DEEPSEEK_API_KEY` (файла
нет — ключ можно задать только окружением). Адрес бэкенда фронтенд и MCP-сервер берут из
`DAY19_BACKEND_URL` (по умолчанию `http://127.0.0.1:8000`); переменная нужна, только если
порт нестандартный.

Подключение к своему MCP-серверу дня (он публикует девять инструментов) — из интерфейса
в разделе «🔀 Пайплайны» кнопкой «🔌 Подключиться к серверу дня» или в разделе «🔌 MCP»
(там же кнопка «🤖 Спросить агента»). Через API то же самое:

```bash
curl -X POST http://127.0.0.1:8000/mcp/connect \
     -H "Content-Type: application/json" \
     -d '{"target": "uv run python mcp_server/server.py"}'
curl http://127.0.0.1:8000/mcp/tools      # count: 9
```

Сервер дня запускается бэкендом как дочерний процесс; вручную его флаги выглядят так
(значения по умолчанию — свои для папки дня):

```bash
uv run python mcp_server/server.py --llm off \
     --output-dir output --file-root . --db-path agents.db \
     --api-base https://jsonplaceholder.typicode.com
```

|Флаг|По умолчанию|Смысл|
|---|---|---|
|`--output-dir`|`day19/output`|каталог, куда `save_to_file` пишет файлы (только внутрь него)|
|`--file-root`|`day19/`|корень локальных источников `file:<путь>`|
|`--db-path`|`day19/agents.db`|база источника `sqlite:<таблица>` (открывается только на чтение)|
|`--llm`|`auto`|`auto` — `summarize` может звать DeepSeek, `off` — всегда агрегация|

Проверка перед работой:

```bash
uv run python scripts/pipeline_demo.py   # четыре сценария пайплайна в консоли
uv run pytest -q                         # автотесты дня
```

## 3. Три инструмента композиции

Инструменты живут на **собственном MCP-сервере дня** (`day19-pipeline`, версия `1.2.0`).
Всего сервер публикует **девять инструментов**: шесть прежних (данные jsonplaceholder
`get_user`, `get_post`, `list_user_posts` и планировщик `schedule_reminder`,
`collect_data`, `generate_summary`) и три новых инструмента композиции. Пайплайн
использует только композицию — остальные шесть доступны одиночным вызовом из чата.

|Инструмент|Параметры|Что возвращает|Где читает/пишет|
|---|---|---|---|
|`search`|`query` (string, до 200 символов); `source` (string, по умолчанию `posts`); `limit` (integer, 1..20, по умолчанию 5)|`query`, `source`, `source_kind`, `count`, `items` — массив элементов `id`, `title`, `content`, `url`, `metadata`|читает: ленту jsonplaceholder, файл внутри папки дня, таблицу SQLite дня|
|`summarize`|`items` (array&lt;object&gt;, обязательный, до 200 элементов); `style` (`short` \| `detailed` \| `bullets`, по умолчанию `short`); `max_length` (integer, 50..4000, по умолчанию 600)|`summary_text`, `key_points`, `total_items`, `style_used`, `engine` (`llm` \| `aggregation`)|читает DeepSeek, если есть ключ и режим не `off`; ничего не пишет|
|`save_to_file`|`content` (string, до 20000 символов); `filename` (string, по умолчанию `pipeline_result.md`); `format` (`md` \| `txt` \| `json`, по умолчанию `md`)|`filename`, `filepath` (абсолютный путь), `size_bytes`, `format`, `saved_at`|пишет **только** в `day19/output/`; расширение заменяется на запрошенный формат|

Источники `search` (`source`):

|Значение|Что это|Поведение|
|---|---|---|
|`posts`|лента jsonplaceholder|читает страницу постов и фильтрует её подстрокой `query` без учёта регистра по `title` + `body`; пустой `query` — все прочитанные записи|
|`users`|лента jsonplaceholder|то же по `name` + `username` + `email` + `city` + `company`|
|`file:<путь>`|файл **внутри** папки дня, например `file:mcp_server/data/notes.md`|путь обязан быть относительным и после разрешения остаться внутри папки дня, иначе ошибка; файл читается UTF-8, режется на блоки по пустым строкам, фильтр — подстрока в блоке; заголовок блока — его первая непустая строка|
|`sqlite:<таблица>`|таблица дня, только чтение|разрешены ровно три таблицы: `collected_data`, `periodic_summaries`, `pipeline_steps`; соединение открывается в режиме read-only, произвольный SQL не выполняется|

Неизвестный источник, отсутствующий файл, путь за пределами папки дня, недоступная
таблица и ошибка внешнего API приходят **ошибкой инструмента** (`isError`) с понятным
текстом: «Доступны: posts, users, file:&lt;путь&gt;, sqlite:&lt;таблица&gt;», «Файл
источника не найден: …», «Источник «file:…» выходит за пределы папки дня». Шаг пайплайна
от такого ответа становится `failed`, а не падает процессом.

## 4. Как запустить пайплайн

### Через интерфейс

1. Откройте <http://localhost:8501> и выберите раздел **«🔀 Пайплайны»**.
2. Если MCP не подключён, нажмите **«🔌 Подключиться к серверу дня»** — без соединения
   шаги не выполнятся.
3. Заполните форму **«▶ Запустить пайплайн»** — это ровно аргументы запуска
   встроенного пайплайна:

|Поле|Значения|По умолчанию|
|---|---|---|
|Источник поиска|«файл дня: заметки про RAG», «jsonplaceholder: посты», «jsonplaceholder: пользователи», «SQLite: шаги прошлых запусков»|файл дня `mcp_server/data/notes.md`|
|Запрос|строка поиска|`RAG`|
|Сколько элементов взять|1..20|5|
|Стиль сводки|«Кратко» (`short`), «Подробно» (`detailed`), «Пунктами» (`bullets`)|«Кратко»|
|Имя файла|имя без пути; расширение заменится на формат|`rag-summary.md`|
|Формат файла|«Markdown» (`md`), «Текст» (`txt`), «JSON» (`json`)|«Markdown»|

4. Нажмите **«▶ Запустить пайплайн»** — прогон стартует в фоновом потоке бэкенда, а
   раздел показывает прогресс: полосу «шагов пройдено», строку на шаг (инструмент,
   время, статус) и раскрывающийся отчёт по шагу с входными и выходными данными.
   Прогресс обновляется раз в секунду, пока прогон не получит терминальный статус.
   По завершении видно итог и путь сохранённого файла.

### Через API

`POST /pipelines/run` принимает `pipeline` (декларативная конфигурация, необязательно),
`initial_args` (аргументы запуска) и `background`. Без поля `pipeline` выполняется
встроенный пайплайн `search-summarize-save`: декларация живёт в одном месте —
`backend/domain/pipeline_spec.py`, поэтому интерфейс присылает только аргументы.
При `background: false` шаги выполняются в этом же запросе и весь отчёт возвращается
сразу (удобно для скриптов и проверок); при `background: true` ответ приходит со
статусом `running`, а прогресс читается через `GET /pipelines/runs/{run_id}`.

```bash
curl -X POST http://127.0.0.1:8000/pipelines/run \
     -H "Content-Type: application/json" \
     -d '{"initial_args": {"query": "RAG",
                           "source": "file:mcp_server/data/notes.md",
                           "limit": 5,
                           "style": "short",
                           "max_length": 600,
                           "filename": "api-run.md",
                           "format": "md"},
          "background": false}'
```

Ожидаемо `200` и тело (значения `id`, времена и размер файла — из фактического прогона):

```json
{
  "run_id": 1,
  "pipeline_name": "search-summarize-save",
  "status": "completed",
  "steps": [
    {"id": 1, "run_id": 1, "step_index": 0, "tool_name": "search",
     "input_args": {"query": "RAG", "source": "file:mcp_server/data/notes.md", "limit": 5},
     "output_result": {"reason_code": null, "structured": {"query": "RAG",
        "source": "file:mcp_server/data/notes.md", "source_kind": "file",
        "count": 5, "items": ["…"]}, "text": "…", "is_error": false, "duration_ms": 94},
     "duration_ms": 94, "status": "ok", "error_message": null},
    {"id": 2, "run_id": 1, "step_index": 1, "tool_name": "summarize",
     "input_args": {"items": ["…"], "style": "short", "max_length": 600},
     "output_result": {"reason_code": null, "structured": {"summary_text": "Найдено 5 элементов. …",
        "key_points": ["…"], "total_items": 5, "style_used": "short",
        "engine": "aggregation"}, "text": "…", "is_error": false, "duration_ms": 7},
     "duration_ms": 7, "status": "ok", "error_message": null},
    {"id": 3, "run_id": 1, "step_index": 2, "tool_name": "save_to_file",
     "input_args": {"content": "Найдено 5 элементов. …", "filename": "api-run.md", "format": "md"},
     "output_result": {"reason_code": null, "structured": {"filename": "api-run.md",
        "filepath": "…/day19/output/api-run.md", "size_bytes": 266, "format": "md",
        "saved_at": "2026-09-24T16:04:20+00:00"}, "text": "…", "is_error": false,
        "duration_ms": 7},
     "duration_ms": 7, "status": "ok", "error_message": null}
  ],
  "count": 3,
  "failed_at_step": null,
  "message": "пайплайн выполнен",
  "error": null,
  "total_duration_ms": 108,
  "background": false
}
```

Собственную конфигурацию можно прислать целиком — шаг описывается данными: `tool`,
`args` (шаблон с ссылками `{имя}` на аргументы запуска и `$steps.<i>.<путь>` на выход
предыдущего шага) и `guard` (условие перехода):

```bash
curl -X POST http://127.0.0.1:8000/pipelines/run \
     -H "Content-Type: application/json" \
     -d '{"pipeline": {"name": "my-pipeline", "steps": [
            {"tool": "search",
             "args": {"query": "{query}", "source": "{source}", "limit": "{limit}"}},
            {"tool": "summarize",
             "guard": {"path": "$steps.0.structured.items", "op": "non_empty",
                       "message": "нет данных для обработки"},
             "args": {"items": "$steps.0.structured.items", "style": "{style}",
                      "max_length": "{max_length}"}},
            {"tool": "save_to_file",
             "args": {"content": "$steps.1.structured.summary_text",
                      "filename": "{filename}", "format": "{format}"}}]},
          "initial_args": {"query": "RAG", "source": "file:mcp_server/data/notes.md",
                           "limit": 5, "style": "bullets", "max_length": 400,
                           "filename": "my-run.md", "format": "txt"},
          "background": true}'
```

При `background: true` ответ содержит `run_id` и статус `running`; дальше клиент
опрашивает `GET /pipelines/runs/{run_id}`.

## 5. Как посмотреть историю

Журнал прогонов лежит в SQLite (`day19/agents.db`, таблицы `pipeline_runs` и
`pipeline_steps`), поэтому история переживает перезапуск бэкенда. В разделе
«🔀 Пайплайны» она видна таблицей (номер, пайплайн, статус, начало, длительность, число
шагов) с деталями шагов выбранного запуска; история обновляется раз в 5 секунд. Через
API — четыре точки:

```bash
curl "http://127.0.0.1:8000/pipelines/runs?limit=10"      # история, свежие первыми
curl "http://127.0.0.1:8000/pipelines/runs?status=failed"  # только неудачные прогоны
curl "http://127.0.0.1:8000/pipelines/runs/1"              # запуск + все его шаги
curl "http://127.0.0.1:8000/pipelines/runs/1/steps"        # только шаги
curl -X DELETE "http://127.0.0.1:8000/pipelines/runs/1"    # удалить запуск и шаги
```

|Запрос|Что отдаёт|
|---|---|
|`GET /pipelines/runs?status=&limit=`|`{"runs": […], "count": N}`: строки запусков (`id`, `pipeline_name`, `status`, `started_at`, `finished_at`, `total_duration_ms`), свежие первыми; `limit` по умолчанию 50|
|`GET /pipelines/runs/{run_id}`|`{"run": {…}, "steps": […], "count": N, "failed_at_step": …, "message": …, "error": …}` — та же форма, что у отчёта о запуске|
|`GET /pipelines/runs/{run_id}/steps`|`{"run_id": …, "steps": […], "count": N}` — только шаги, по возрастанию `step_index`|
|`DELETE /pipelines/runs/{run_id}`|`{"status": "deleted", "run_id": …}`; шаги удаляются каскадом вместе с запуском|

**Фильтр `status`** принимает ровно четыре значения прогона — `running`, `completed`,
`stopped`, `failed`; неизвестное значение даёт `400` с перечнем допустимых. Запуск с
`running` — это нормальное состояние фонового прогона: он ещё выполняется, и его новая
строка появляется раньше первого шага (её создаёт сервис, а не поток прогона, поэтому
гонки «запуск ещё не записан» нет).

Пример ответа истории:

```json
{
  "runs": [
    {"id": 2, "pipeline_name": "search-summarize-save", "status": "stopped",
     "started_at": "2026-09-24T16:04:21+00:00", "finished_at": "2026-09-24T16:04:21+00:00",
     "total_duration_ms": 12},
    {"id": 1, "pipeline_name": "search-summarize-save", "status": "completed",
     "started_at": "2026-09-24T16:04:20+00:00", "finished_at": "2026-09-24T16:04:20+00:00",
     "total_duration_ms": 108}
  ],
  "count": 2
}
```

Удаление опасных последствий не имеет: `save_to_file` уже записал файл в `day19/output/`,
и удаление запуска его не трогает — история говорит о прогонах, а не о файлах.

## 6. Как читать результаты шагов

У каждого шага в журнале есть `input_args` (аргументы вызова — ссылки пайплайна уже
разрешены), `output_result`, `duration_ms`, `status` и `error_message`. Форма
`output_result` **одна и та же у всех инструментов и у успеха, и у неудачи**:

```json
{
  "reason_code": null,
  "structured": {"…": "структурированный ответ инструмента (outputSchema)"},
  "text": "текстовое представление ответа",
  "is_error": false,
  "duration_ms": 94
}
```

|Поле|Смысл|
|---|---|
|`structured`|структурированный ответ инструмента: у `search` — `count` и `items`, у `summarize` — `summary_text` и `key_points`, у `save_to_file` — `filepath` и `size_bytes`. Именно сюда смотрят ссылки маппинга `$steps.<i>.structured.<поле>`|
|`text`|тот же ответ строкой (то, что уходит модели при одиночном вызове)|
|`reason_code`|`null` у выполнившегося вызова; иначе причина отказа: `not_connected`, `unknown_tool`, `bad_arguments`, `transport`, `tool_error`|
|`is_error`|`true`, если инструмент ответил ошибкой (`ToolError`); `false` — если вызов прошёл|
|`duration_ms`|сколько занял вызов (дублирует `duration_ms` самого шага)|

Форма одинакова у всех шагов намеренно: путь маппинга
`$steps.<i>.structured.<поле>` определён всегда, а значит, конфигурация со ссылкой на
результат описывается одинаково и для удачного шага, и для неудачного.

|Статус шага|Когда ставится|
|---|---|
|`ok`|инструмент выполнился (даже если вернул пустой результат — пустая выдача `search` это `ok`)|
|`failed`|вызов не прошёл (`not_connected`, `bad_arguments`, `transport`, `tool_error`) **или** шаг не собрался: не нашлась ссылка `$steps.`/заглушка `{имя}`|
|`stopped`|условие перехода шага не выполнено — инструмент не вызывался вовсе, прогон завершается досрочно|

Итог прогона (`status` запуска и отчёт) читается по трём полям отчёта:

- `run.status` — `running` | `completed` | `stopped` | `failed` (значения состояний
  стейт-машины прогона попадают в БД и API без маппинга);
- `message` — человеческая формулировка: «пайплайн выполнен», «пайплайн остановлен:
  шаг завершился ошибкой», сообщение условия перехода (для `stopped`) или «пайплайн
  выполняется»;
- `failed_at_step` — номер шага конфигурации (с нуля), на котором прогон остановился;
  `error` — текст ошибки этого шага. У досрочного завершения `failed_at_step` — `null`, а
  причина лежит в `error_message` шага со статусом `stopped`.

**`stopped` — это не `failed`.** `failed` означает, что шаг сломался; `stopped`
означает решение не вызывать инструмент: условие перехода не выполнено (например,
`search` ничего не нашёл). Файл после `stopped` не создаётся, а в системный промпт агента
такой итог попадает как «нет данных для обработки» — модель не должна отвечать так,
будто сводка есть. Ошибка инструмента (`is_error: true`) наоборот делает шаг `failed` и
прогон останавливает: ошибка шага — это конец пайплайна, а не «продолжим с мусором».

Прогон всегда получает терминальный статус: даже если в фоновом потоке случится
непредвиденное исключение, сервис ловит его, пишет в лог и ставит запуску `failed` — иначе
интерфейс вечно показывал бы «выполняется».

## 7. Условные переходы и ошибки

### Условия перехода (`guard`)

У шага может быть условие — словарь `{"path": "…", "op": "…", "message": "…"}`, где
`path` — путь в результатах предыдущих шагов, `op` — один из четырёх операторов:

|Оператор|Истина, когда|
|---|---|
|`non_empty`|значение — непустой список, словарь или строка|
|`empty`|отрицание `non_empty`|
|`equals`|значение точно равно `value` из условия|
|`contains`|подстрока входит в строку или элемент входит в список|

Если условие не выполнено, шаг получает статус `stopped` и в `error_message` —
`message` условия (по умолчанию «условие шага не выполнено»), а прогон завершается
статусом `stopped`. Во встроенном пайплайне так работает второй шаг: условие

```json
{"path": "$steps.0.structured.items", "op": "non_empty",
 "message": "нет данных для обработки"}
```

останавливает прогон, когда `search` не нашёл ни одного элемента, — `summarize` не
вызывается, файл не создаётся, а итог прогона равен «нет данных для обработки».
Неизвестный оператор, условие `equals` без ключа `value` и условие без `path`/`op` —
ошибка: шаг `failed`, прогон останавливается.

### Ошибки шагов

|Ситуация|Что в журнале шага|Статус прогона|
|---|---|---|
|ссылка не нашлась: нет `{query}` в аргументах запуска или нет пути `$steps.1.structured.summary_text`|`status: "failed"`, `error_message`: «Аргумент запуска «query» не передан» / «Путь «…» не найден в результатах шагов», `output_result: null`, `duration_ms: 0`|`failed`, `failed_at_step` — номер шага|
|негодные аргументы (`items` передана строка вместо массива, `limit` вне 1..20, неизвестный `style`)|`reason_code: "bad_arguments"`, `is_error: true`, `text` с причиной|`failed`|
|инструмент ответил ошибкой (стиль не поддержан, файла-источника нет, таблица недоступна, внешний API не ответил)|`reason_code: "tool_error"`, `is_error: true`, `text` — текст `ToolError`|`failed`|
|имени инструмента нет в каталоге сервера|`reason_code: "unknown_tool"`|`failed`|
|MCP не подключён|`reason_code: "not_connected"`|`failed`|
|сбой транспорта MCP|`reason_code: "transport"`|`failed`|
|условие шага не выполнено|`status: "stopped"`, `error_message` — сообщение условия, инструмент не вызывался|`stopped`, `failed_at_step: null`|

Строка журнала пишется **всегда**, включая шаги, которые упали на маппинге, — иначе
причина остановки не доехала бы до истории и отчёта. Прогон останавливается на первом
не-`ok` шаге, поэтому шаги после сломанного в журнале не появляются.

### Коды API

|Код|Когда|
|---|---|
|`400`|негодная конфигурация пайплайна (`name`/`steps`/`tool`/`guard` не проходят проверку) или неизвестный `status` в фильтре истории|
|`404`|запрошен запуск, которого нет: `GET /pipelines/runs/{run_id}`, `…/steps`, `DELETE`|
|`422`|невалидное тело запроса (Pydantic): например, `background` не булево|

Ошибка в теле ответа — стандартная для FastAPI: `{"detail": "текст причины"}` (например,
`{"detail": "Запуск пайплайна 999 не найден"}` или
`{"detail": "Неизвестный статус запуска «broken»; допустимы: completed, failed, running, stopped"}`).

## 8. Сценарии тестирования

Все команды — из папки `day19`; бэкенд для API-сценариев запущен на порту 8000, MCP
подключён. Сценарии 8.1–8.3 идут на локальных заметках дня
(`mcp_server/data/notes.md`, в них есть абзацы про RAG) — сеть не нужна.

### 8.1 Успешный пайплайн

Раздел «🔀 Пайплайны» → источник «файл дня: заметки про RAG», запрос `RAG`, элементов
5, стиль «Кратко», имя файла `rag.md`, формат «Markdown» → «▶ Запустить пайплайн».

Ожидаемо: статус «✅ выполнен», три шага со статусом `ok` —

- `🔎 search` — нашлось 5 элементов (`source_kind: "file"`);
- `🧾 summarize` — ключевые пункты, движок `aggregation` (без ключа DeepSeek);
- `💾 save_to_file` — файл `rag.md`.

Внизу раздела — путь сохранённого файла; файл лежит в `day19/output/rag.md`. Через API то
же самое — запросом из раздела 4 с `"filename": "api-run.md"`.

### 8.2 Пустой результат поиска — досрочное завершение

То же самое, но запрос, которого в заметках нет, — `квантовые вычисления`.

Ожидаемо: статус «⏹ остановлен досрочно», `message` — «нет данных для обработки»,
`failed_at_step` пуст, в журнале **два** шага: `search` — `ok` с `count: 0`, `summarize` —
`stopped` с текстом условия, третий шаг не запускался, файл не создан.

```bash
curl -X POST http://127.0.0.1:8000/pipelines/run \
     -H "Content-Type: application/json" \
     -d '{"initial_args": {"query": "квантовые вычисления",
                           "source": "file:mcp_server/data/notes.md",
                           "limit": 5, "style": "short", "max_length": 600,
                           "filename": "run-stopped.md", "format": "md"},
          "background": false}'
```

### 8.3 Ошибка на втором шаге

Две причины падения одного и того же шага:

1. **Негодные аргументы.** Конфигурация со ссылкой на строку вместо массива: у шага
   `summarize` аргумент `items` заменён на `"$steps.0.structured.query"`. Ожидаемо:
   `status: "failed"`, `failed_at_step: 1`, шаг 0 — `ok`, у шага 1
   `reason_code: "bad_arguments"`, третий шаг не запускался, файл не создан.
2. **Ошибка инструмента.** Аргументы верные, но `style = "exotic"`. Ожидаемо: шаг 1 —
   `failed`, `is_error: true`, текст «Стиль «exotic» не поддержан…», прогон — `failed`.

```bash
curl -X POST http://127.0.0.1:8000/pipelines/run \
     -H "Content-Type: application/json" \
     -d '{"initial_args": {"query": "RAG", "source": "file:mcp_server/data/notes.md",
                           "limit": 5, "style": "exotic", "max_length": 600,
                           "filename": "run-failed.md", "format": "md"},
          "background": false}'
```

### 8.4 Запуск пайплайна через агента

В разделе «💬 Чат и память» отправьте реплику:
**«найди статьи про RAG, сделай сводку и сохрани в файл»**.

Ожидаемо:

- пайплайн распознан по ключевым словам (поиск + сводка + сохранение — нужны все три
  группы) и выполнен **синхронно**, до обращения к модели;
- в сводке хода появилась строка «🔀 Пайплайн: ✅ выполнен — пайплайн выполнен» (то же
  поле `pipeline` есть в ответе `POST /agents/{agent_id}/generate`);
- в системный промпт ушёл блок «## Результат пайплайна» с шагами и объёмами, а одиночный
  вызов MCP-инструмента не потребовался (`record["mcp"] is null`): пайплайн-реплика не
  разбирается ещё и как одиночный вызов;
- файл создан в `day19/output/` (имя выводится из запроса: `rag.md`).

Обычная реплика (например, «объясни, что такое RAG, в двух предложениях») пайплайн не
запускает: в отчёте хода `detected: false`, поле `pipeline` остаётся пустым.

### 8.5 Автотесты

```bash
uv run pytest -q
```

Автотесты дня офлайн: MCP-сервер подменяется фейковым клиентом (в интеграционных
тестах — поднимается настоящий сервер по stdio с временными каталогами и базой), прогон
идёт на временной БД в `tmp_path`. Покрыты переходы стейт-машины прогона, правила
маппинга и условий, проверка конфигурации, распознавание реплики, рендер блока в промпт,
источники `search`, логика `summarize` и запись файла, журнал хранилища, выполнение
пайплайна, служба с фоновым потоком, шаг пайплайна в агенте и контракт `/pipelines/*`.
Точное число файлов и тестов — в [../STRUCTURE.md](../STRUCTURE.md).

### 8.6 Автоматический прогон четырёх сценариев

```bash
uv run python scripts/pipeline_demo.py --report docs/reports/pipeline_demo.md
```

Скрипт поднимает изолированный стенд (своя БД во временном каталоге, свой MCP-сервер по
stdio с `--llm off`, источник — заметки дня), вызывает инструменты по-настоящему через
сервер и прогоняет те же четыре сценария: успех, пустой поиск, ошибка шага и запуск из
чата. Ключ `--report` собирает по этому прогону отчёт
[docs/reports/pipeline_demo.md](reports/pipeline_demo.md): таблица проверок, таблица трёх
инструментов, обязательная таблица шагов успешного прогона (**шаг | инструмент | входные
данные | выходные данные | время выполнения | статус**), содержимое сохранённого файла,
разбор досрочного завершения и ошибки шага, схема таблиц `pipeline_runs`/`pipeline_steps`
и итог автотестов. Весь прогон проходит 26 проверок из 26; артефакт прогона —
`day19/output/run-success.md` (остаётся в репозитории как приложение к отчёту).

С реальной моделью внутри `summarize` (нужен ключ и сеть):

```bash
uv run python scripts/pipeline_demo.py --llm auto --report docs/reports/pipeline_demo.md
```

Полезные ключи:

```bash
uv run python scripts/pipeline_demo.py --output-dir output   # куда писать файлы прогона
uv run python scripts/pipeline_demo.py --db agents.db         # БД прогона вместо временной
uv run python scripts/pipeline_demo.py --tests               # добавить в отчёт сводку pytest
uv run python scripts/pipeline_demo.py --json                # итог прогона как JSON
```

Код выхода `1` — если какая-то проверка сценария не прошла.

## 9. Где что лежит и что почитать дальше

|Что|Где|
|---|---|
|Декларация пайплайна: имя, шаги, условия, сообщения|`backend/domain/pipeline_spec.py`|
|Маппинг `{имя}` / `$steps.<i>.<путь>` и вычисление условий|`backend/domain/pipeline_mapping.py`|
|Стейт-машина прогона (IDLE → RUNNING → COMPLETED/STOPPED/FAILED)|`backend/domain/pipeline_fsm.py`|
|Распознавание реплики про пайплайн и её аргументы|`backend/domain/pipeline_intent.py`|
|Блок «## Результат пайплайна» в системном промпте|`backend/domain/pipeline_prompt.py`|
|Цикл шагов: маппинг → условие → вызов → журнал → переход FSM|`backend/services/pipeline.py`|
|Запуск (фон или синхронно), история, удаление|`backend/services/pipeline_service.py`|
|Таблицы журнала `pipeline_runs` / `pipeline_steps`|`backend/models/pipeline.py`, `backend/storage/pipeline_store.py`|
|Пять эндпоинтов `/pipelines/*`|`backend/api/pipelines.py`, схемы — `backend/schemas/pipeline.py`|
|Три инструмента композиции и их тела|`mcp_server/pipeline_tools.py`|
|Источники `search` (API, файл, SQLite)|`mcp_server/search_sources.py`|
|Правила сводки и агрегация|`mcp_server/summarize_logic.py`, ветка LLM — `mcp_server/llm_client.py`|
|Запись файла в `output/`|`mcp_server/file_writer.py`|
|Раздел интерфейса и его HTTP-помощники|`frontend/pipeline_section.py`, `frontend/pipeline_api.py`|
|Прогон сценариев и сборка отчёта|`scripts/pipeline_demo.py`, `scripts/pipeline_scenarios.py`, `scripts/pipeline_report.py`|

- [api.md](api.md) — пять эндпоинтов `/pipelines/*` с телами, ответами и кодами, а также
  поле `pipeline` ответа генерации.
- [architecture.md](architecture.md) — раздел «Композиция MCP-инструментов»: правила
  маппинга, граф переходов прогона, поток данных, схема двух таблиц, фоновый поток и
  опрос интерфейса.
- [reports/pipeline_demo.md](reports/pipeline_demo.md) — отчёт прогона четырёх сценариев
  (создаётся командой из раздела 8.6).
- [../STRUCTURE.md](../STRUCTURE.md) — карта модулей дня, таблицы слоёв, эндпоинты и
  лимиты строк.
- [../README.md](../README.md) — возможности приложения и что нового в дне.
- [../../AGENTS.md](../../AGENTS.md) — правило дня: композиция MCP-инструментов
  описывается декларативно, каждый шаг логируется с входом, выходом и временем.
- Swagger: <http://127.0.0.1:8000/docs>.
