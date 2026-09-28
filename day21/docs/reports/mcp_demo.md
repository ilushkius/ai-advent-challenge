# День 16 — MCP-клиент: подключение и список инструментов

Отчёт о прогоне MCP-клиента дня 16: какой сервер использовался, какой командой
запускался, что вернул `tools/list`, какие проблемы встретились и как решены.

Прогон офлайн-часть (тесты, `scripts/mcp_demo.py` на тестовом stdio-сервере) и
живую часть (настоящие общедоступные MCP-серверы) разделяет: живые серверы ставят
пакеты из PyPI/npm, поэтому их запуск не входит в `pytest`, но именно их вывод
приведён ниже — это и есть доказательство дня.

## 1. Что проверялось

| Проверка | Как воспроизвести | Результат |
|---|---|---|
| Соединение с MCP-сервером по stdio | `uv run python scripts/mcp_demo.py` | ✅ `connected`, сервер `mcp-fetch 1.30.0` |
| Список инструментов не пуст | там же | ✅ 1 инструмент (`fetch`) с описанием и `input_schema` |
| Второй сервер, больше инструментов | `uv run python scripts/mcp_demo.py --target "npx -y @modelcontextprotocol/server-filesystem ."` | ✅ 14 инструментов |
| Ходы соединения видны в API | `POST /mcp/connect` → `GET /mcp/status` → `GET /mcp/tools` → `POST /mcp/disconnect` | ✅ `disconnected → connected → disconnected`, после закрытия `/mcp/tools` даёт 409 |
| Неверный URL | `uv run python scripts/mcp_demo.py --target http://127.0.0.1:9/mcp --transport http --timeout 5` | ✅ код выхода 1 и понятная строка ошибки |
| Команда не найдена | `uv run python scripts/mcp_demo.py --target "day16-no-such-command" --timeout 5` | ✅ код выхода 1, подсказка про PATH |
| Вкладка «🔌 MCP» в интерфейсе | `uv run streamlit run app.py` + `uv run uvicorn backend.api.main:app --port 8000` | ✅ статус, таблица инструментов, обновление списка, отключение |
| Автотесты | `uv run pytest -q` | ✅ 1097 passed |

## 2. Какой сервер и какой командой

Использованы два **общедоступных** MCP-сервера официального набора
(Model Context Protocol servers):

1. **fetch** — `uvx mcp-server-fetch` (пакет `mcp-server-fetch` из PyPI; нужен
   только `uv`, Node не требуется). Это сервер по умолчанию —
   `config.MCP_DEFAULT_TARGET`, он же подставлен в поле вкладки «🔌 MCP».
2. **filesystem** — `npx -y @modelcontextprotocol/server-filesystem .` (пакет из
   npm; нужен Node ≥ 18). Даёт 14 инструментов — удобно показать, что список
   приходит целиком, а не одним инструментом.

Оба запускаются **локально по stdio**: бэкенд поднимает их дочерним процессом
(`npx`/`uvx`), а обмен идёт JSON-RPC по stdin/stdout. Сеть нужна только на
установку пакета — сам протокол локальный.

Транспорт HTTP/SSE в этом прогоне не проверялся живым сервером: общедоступных
MCP-серверов с открытым HTTP-эндпоинтом, которым можно доверять без ключа, нет.
Обе ветки транспорта зафиксированы тестами (разбор цели и ошибки соединения —
`tests/unit/test_mcp_target.py`, `tests/integration/test_mcp_client_errors.py`),
а сам транспорт `streamable_http_client`/`sse_client` — из MCP SDK.

## 3. Полученный список инструментов

### fetch-сервер (1 инструмент)

```
цель:       uvx mcp-server-fetch
транспорт:  stdio (дочерний процесс)
состояние:  connected
сервер:     mcp-fetch 1.30.0
протокол:   2025-11-25
инструментов: 1
```

|name|description (начало)|input_schema (аргументы)|
|---|---|---|
|`fetch`|«Fetches a URL from the internet and optionally extracts its contents as markdown…»|`url` (string, обязательный), `max_length` (integer, по умолчанию 5000), `start_index` (integer, 0), `raw` (boolean, false)|

Команда и её вывод целиком (так это выглядит на видео):

```
=== MCP-демо дня 16 ===
минимальный код:
    client = MCPClient("uvx mcp-server-fetch")
    client.connect()
    tools = client.list_tools()
    client.disconnect()

цель:       uvx mcp-server-fetch
транспорт:  stdio (дочерний процесс)
состояние:  connected
сервер:     mcp-fetch 1.30.0
протокол:   2025-11-25
инструментов: 1

1. fetch
   описание: Fetches a URL from the internet and optionally extracts its contents as markdown.
   input_schema:
     {
       "description": "Parameters for fetching a URL.",
       "properties": {
         "url": {
           "description": "URL to fetch",
           "format": "uri",
           "minLength": 1,
           "title": "Url",
           "type": "string"
         },
         "max_length": { … "Maximum number of characters to return." … },
         "start_index": { … "On return output starting at this character index …" … },
         "raw": { … "Get the actual HTML content of the requested page …" … }
       },
       "required": [ "url" ],
       "title": "Fetch",
       "type": "object"
     }
```

Схема напечатана как есть (в отчёте середина сокращена — целиком она выдаётся
командой `uv run python scripts/mcp_demo.py --json`).

### filesystem-сервер (14 инструментов)

```
сервер:     secure-filesystem-server 0.2.0
протокол:   2025-11-25
count = 14
```

`read_file`, `read_text_file`, `read_media_file`, `read_multiple_files`,
`write_file`, `edit_file`, `create_directory`, `list_directory`,
`list_directory_with_sizes`, `directory_tree`, `move_file`, `search_files`,
`get_file_info`, `list_allowed_directories`.

### То же через API

`GET /mcp/tools` отдаёт этот же каталог по контракту дня — список и количество:

```json
{
  "tools": [
    {
      "name": "fetch",
      "description": "Fetches a URL from the internet and optionally extracts its contents as markdown. …",
      "input_schema": { "properties": { "url": { "type": "string" }, … }, "required": ["url"], "type": "object" }
    }
  ],
  "count": 1,
  "target": "uvx mcp-server-fetch",
  "transport": "stdio",
  "server_name": "mcp-fetch",
  "server_version": "1.30.0"
}
```

## 4. Ходы соединения через API (живой прогон)

```
GET  /mcp/status                                  -> 200 {"connected": false, "state": "disconnected", "allowed_events": ["connect"]}
POST /mcp/connect {"target": "uvx mcp-server-fetch"} -> 200 {"connected": true, "state": "connected",
                                                            "server_name": "mcp-fetch", "server_version": "1.30.0",
                                                            "protocol": "2025-11-25", "tool_count": 0,
                                                            "allowed_events": ["fail", "disconnect"]}
GET  /mcp/tools                                   -> 200 count = 1 (инструмент fetch)
POST /mcp/disconnect                              -> 200 {"connected": false, "state": "disconnected"}
GET  /mcp/tools                                   -> 409 "Подключение к MCP-серверу не установлено: сначала POST /mcp/connect"
```

`tool_count` в ответе `POST /mcp/connect` равен нулю осознанно: подключение ещё
не запрашивало список, а `GET /mcp/tools` — отдельный шаг. В интерфейсе это
учтено: раздел читает список перед отрисовкой статуса, поэтому число в статусе не
отстаёт на проход.

## 5. Ошибки и понятные сообщения

Недоступный HTTP-эндпоинт (`--transport http`, закрытый порт):

```
$ uv run python scripts/mcp_demo.py --target http://127.0.0.1:9/mcp --transport http --timeout 5
MCP: Не удалось подключиться к MCP-серверу [Streamable HTTP] http://127.0.0.1:9/mcp: All connection attempts failed (проверьте URL и что сервер поднят)
ОШИБКА: Не удалось подключиться к MCP-серверу [Streamable HTTP] http://127.0.0.1:9/mcp: All connection attempts failed (проверьте URL и что сервер поднят)
MCP: Соединение с MCP-сервером оборвалось [Streamable HTTP] http://127.0.0.1:9/mcp: All connection attempts failed (проверьте URL и что сервер поднят)
$ echo $?
1
```

Команды нет в PATH:

```
$ uv run python scripts/mcp_demo.py --target "day16-no-such-command" --timeout 5
ОШИБКА: Не удалось подключиться к MCP-серверу [stdio (дочерний процесс)] day16-no-such-command: [WinError 2] Не удается найти указанный файл (команда 'day16-no-such-command' не найдена — проверьте, что она установлена и есть в PATH (npx или uvx))
```

В интерфейсе та же строка приходит красной плашкой («ошибка подключения: …»), а
состояние в разделе остаётся `⚪ не подключено`.
Через API это `502` с этой же строкой в `detail`, а `GET /mcp/status` показывает
`"state": "error"` и текст последней ошибки — то есть отказ виден и в диалоге, и в
статусе, без traceback.

Живой прогон:

```
POST /mcp/connect {"target": "http://127.0.0.1:9/mcp"}
  -> 502 {"detail": "Не удалось подключиться к MCP-серверу [Streamable HTTP] http://127.0.0.1:9/mcp:
                   All connection attempts failed (проверьте URL и что сервер поднят)"}
GET  /mcp/status
  -> 200 {"connected": false, "state": "error", "error": "…тот же текст…",
          "allowed_events": ["connect", "disconnect"]}
```

## 6. Возникшие проблемы и решения

**1. Контексты MCP SDK живут в task-group anyio — вход и выход должны быть в одной
задаче.** Первая версия клиента открывала транспорт и сессию отдельной корутиной
(`run_coroutine_threadsafe` на каждое действие), а закрывала другой: при закрытии
SDK падал с `Attempted to exit cancel scope in a different task than it was
entered in`. Решение — долгоживущая задача `MCPClient._serve` в служебном цикле
событий: она открывает `AsyncExitStack`, сообщает о готовности через
`threading.Event` и закрывает контексты после события `shutdown` — то есть вход и
выход происходят в одном task. Синхронные `connect()`/`list_tools()`/
`disconnect()` остались удобными для FastAPI и Streamlit.

**2. Ожидание готовности: пропущенный сигнал.** После перехода на долгоживущую
задачу `connect()` зависал до таймаута: сигнал о готовности ставился только в
`finally` (после закрытия), а не сразу после `initialize`. Нашлось трассировкой
потоков (`faulthandler.dump_traceback_later`): служебный поток стоял в `_poll`
без таймеров, то есть `initialize` уже прошёл. Решение — `ready.set()` сразу после
`initialize` (и в `finally` — вторая постановка для пути с ошибкой).

**3. Имя поля курсора в mcp 2.x.** В `ListToolsResult` поле называется
`next_cursor` (не `nextCursor`): итерация по страницам падала на
`'ListToolsResult' object has no attribute 'nextCursor'`. Заодно постраничный
разбор получил предел `config.MCP_MAX_TOOL_PAGES = 20` — защита от сервера,
который всегда возвращает курсор.

**4. Текст ошибки был один на все случаи.** Общая функция форматирования всегда
начинала с «Не удалось подключиться…», из-за чего ошибка `tools/list` выглядела
как ошибка подключения. Решение — словарь `ACTION_LABELS` (`connect` / `tools` /
`serve`) в `backend/services/mcp_errors.py`.

**5. Дублирование логов при закрытии.** `disconnect()` логировал ошибку ещё раз
после `_await_close`, который логировал её сам: в консоли появлялись две
одинаковые строки. Решение — логирование и перевод FSM остались в одном месте
(`_await_close` → `_note_failure`).

**6. Лимит 400 строк.** `backend/services/mcp_client.py` вырос до 442 строк,
`frontend/api_client.py` — до 410. Оба разделены: ошибки и тексты переехали в
`backend/services/mcp_errors.py`, HTTP-запросы раздела — в `frontend/mcp_api.py`
(транспорт `request_json` остался общим в `api_client.py`). Сейчас превышает лимит
только унаследованный `backend/agents/agent.py` (1825 строк, как в дне 15).

**7. Симлинки скиллов библиотек на Windows.** `uvx library-skills --all` не смог
создать симлинки (`WinError 1314`), поэтому скиллы поставлены копированием
(`--copy`), как в дне 15; команда в отчёте о состоянии — `uvx library-skills
--check --tool-skill` (код 0).

## 7. Что осталось за рамками дня

- **Вызов инструментов** (`tools/call`) не реализован: по заданию дня клиент
  только устанавливает соединение и читает каталог (`get_tools`).
- **HTTP/SSE-сервер** вживую не поднимался (см. §2): обе ветки покрыты тестами,
  но живой прогон был на stdio-серверах.
- **Подключение не переживает рестарт бэкенда**: это соединение с внешним
  процессом, а не данные домена; после перезапуска нужно нажать «🔌 Подключиться»
  снова (`/mcp/status` честно скажет `disconnected`).
