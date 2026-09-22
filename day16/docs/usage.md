# День 16 — MCP-клиент: установка и использование

Инструкция по приложению дня 16. День добавляет **MCP-клиент**: подключение к
внешнему MCP-серверу (Model Context Protocol) и получение списка его инструментов
(`get_tools`). Инструменты в работе агента не вызываются — задача дня в том,
чтобы установить соединение и показать каталог.

Приложение — тот же агент с тремя слоями памяти, профилем пользователя,
контролируемыми переходами задачи и инвариантами, что и в дне 15; новое — раздел
«🔌 MCP» в интерфейсе, эндпоинты `/mcp/...` в API и скрипт `scripts/mcp_demo.py`.
Как устроено внутри — [architecture.md](architecture.md), эндпоинты с примерами —
[api.md](api.md), доказательства прогона — [reports/mcp_demo.md](reports/mcp_demo.md),
карта модулей — [../STRUCTURE.md](../STRUCTURE.md).

## 1. Что нужно для запуска

|Компонент|Зачем|Проверка|
|---|---|---|
|Python 3.14 и `uv`|зависимости дня и запуск|`uv --version`|
|Node ≥ 18 (`npx`)|файловый MCP-сервер `@modelcontextprotocol/server-filesystem`|`npx --version`|
|`uvx` (идёт с `uv`)|fetch-сервер `mcp-server-fetch`|`uvx --version`|
|Ключ `DEEPSEEK_API_KEY`|только для чата; MCP-раздел работает без ключа|`day16/.env`|

MCP-часть **не требует ключа**: MCP-серверы запускаются локально по stdio, а
инструменты только читаются. Ключ DeepSeek нужен лишь для генерации в разделе
«💬 Чат и память».

## 2. Установка и запуск

Менеджер зависимостей — `uv`: прямые зависимости в `pyproject.toml`, точные
версии — в `uv.lock`, интерпретатор — `.python-version`. Активировать окружение
не нужно, `uv run` сам находит `.venv`.

```bash
cd day16
uv sync                  # создать .venv по uv.lock (в том числе mcp)
cp .env.example .env     # затем впишите DEEPSEEK_API_KEY=sk-... (для чата)
```

Терминал 1 — бэкенд (MCP-подключение живёт в его процессе):

```bash
uv run uvicorn backend.api.main:app --port 8000
```

Терминал 2 — интерфейс: <http://localhost:8501>

```bash
uv run streamlit run app.py
```

Проверка перед работой:

```bash
uv run python scripts/mcp_demo.py      # подключение и список инструментов в консоли
uv run pytest -q                       # 1097 тестов дня
```

## 3. Как подключиться к MCP-серверу

### Через интерфейс

1. Откройте <http://localhost:8501> (бэкенд уже запущен на порту 8000).
2. В переключателе разделов вверху выберите **«🔌 MCP»**.
3. В поле «URL или команда запуска MCP-сервера» введите цель (по умолчанию
   подставлено `uvx mcp-server-fetch`).
4. Транспорт оставьте `auto` — он определяется по виду цели:

   |Что ввели|Транспорт|
   |---|---|
   |`uvx mcp-server-fetch`, `npx -y …`|stdio — сервер запускается дочерним процессом|
   |`http://127.0.0.1:9000/mcp`|Streamable HTTP|
   |`sse://127.0.0.1:9000/sse`|SSE|

   Явный выбор транспорта в селекторе сильнее автоопределения.
5. Нажмите **«🔌 Подключиться»**. Плашка статуса станет зелёной: имя и версия
   сервера, согласованная версия протокола, число инструментов; ниже появятся
   «допустимые события» — что можно сделать в этом состоянии (`fail`,
   `disconnect`).

Если соединение не установлено, раздел показывает подсказку: под полем ввода
виден пример цели, а список инструментов не рисуется — «пусто» и «не подключено»
различаются.

### Готовые цели для копирования

|Сервер|Цель|Инструментов|
|---|---|---|
|fetch (PyPI, нужен `uvx`)|`uvx mcp-server-fetch`|1 (`fetch`)|
|filesystem (npm, нужен `npx`)|`npx -y @modelcontextprotocol/server-filesystem .`|14|
|любой HTTP-сервер|`http://127.0.0.1:9000/mcp` + транспорт `http`|зависит от сервера|
|любой SSE-сервер|`sse://127.0.0.1:9000/sse`|зависит от сервера|

Цели можно задавать как с префиксом (`stdio: uvx mcp-server-fetch`), так и без
него; кавычки в команде сохраняются вместе с пробелами и обратными слэшами
(`npx -y pkg "C:\Program Files\dir"`).

### Через API (то же самое, без интерфейса)

```bash
curl -X POST http://127.0.0.1:8000/mcp/connect \
     -H "Content-Type: application/json" \
     -d '{"target": "uvx mcp-server-fetch"}'
```

Ответ — состояние подключения:

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

### Из кода (минимальный скрипт)

```python
from backend.services.mcp_client import MCPClient

client = MCPClient("uvx mcp-server-fetch")   # stdio; для HTTP — "http://host:port/mcp"
client.connect()                             # initialize + согласование протокола
for tool in client.list_tools():             # tools/list → name, description,
    print(tool.name, tool.input_schema)      #              input_schema
client.disconnect()                          # закрыть соединение (и процесс stdio)
```

Готовый скрипт с читаемым выводом и разбором ошибок:

```bash
uv run python scripts/mcp_demo.py
uv run python scripts/mcp_demo.py --target "npx -y @modelcontextprotocol/server-filesystem ."
uv run python scripts/mcp_demo.py --target http://127.0.0.1:9000/mcp --transport http
uv run python scripts/mcp_demo.py --json          # то же, но JSON (как GET /mcp/tools)
uv run python scripts/mcp_demo.py --timeout 5     # короче ждать сервер
```

## 4. Как посмотреть список инструментов

**В интерфейсе.** Раздел «🔌 MCP» рисует под статусом таблицу
`name` / `description` / `input_schema` (схема — одной строкой) и подпись
«Инструментов: N». Полная JSON Schema аргументов выбранного инструмента — в
раскладке «🧾 Полная input_schema инструмента» (`st.json`).

**Обновить список.** Кнопка **«🔄 Обновить список инструментов»** — запрос идёт с
`refresh=true`, то есть сервер опрашивается заново (без нажатия список берётся из
кэша открытой сессии).

**Через API.**

```bash
curl http://127.0.0.1:8000/mcp/tools
curl "http://127.0.0.1:8000/mcp/tools?refresh=true"   # перезапросить у сервера
```

```json
{
  "tools": [
    {"name": "fetch",
     "description": "Fetches a URL from the internet …",
     "input_schema": {"properties": {"url": {"type": "string"}}, "required": ["url"]}}
  ],
  "count": 1,
  "target": "uvx mcp-server-fetch",
  "transport": "stdio",
  "server_name": "mcp-fetch",
  "server_version": "1.30.0"
}
```

Без соединения этот запрос возвращает **409** с текстом «Соединение с
MCP-сервером не установлено…» — так список и статус не путаются.

## 5. Как отключиться

- В интерфейсе: кнопка **«⏏ Отключиться»** — соединение закрывается, сервер-stdio
  (процесс `npx`/`uvx`) завершается, плашка становится «⚪ не подключено».
- Через API: `curl -X POST http://127.0.0.1:8000/mcp/disconnect -d '{}'`.
- Повторное отключение без соединения — безопасный no-op (не ошибка).
- Остановка бэкенда (Ctrl+C) тоже закрывает соединение: `lifespan` вызывает
  `get_mcp_registry().close()`, поэтому дочерние процессы не остаются висеть.
- Новое подключение к другому серверу закрывает прежнее: у процесса одно
  активное MCP-соединение.

## 6. Статус подключения

```bash
curl http://127.0.0.1:8000/mcp/status
```

|Поле|Значение|
|---|---|
|`connected`|открыто ли соединение прямо сейчас|
|`state`|состояние стейт-машины: `disconnected` → `connecting` → `connected` / `error`|
|`target`, `transport`, `transport_label`|куда и как подключены|
|`server_name`, `server_version`, `protocol`|что ответил сервер на `initialize` (пусто без соединения)|
|`tool_count`|сколько инструментов уже получено|
|`error`|текст последней ошибки соединения|
|`allowed_events`|что допустимо в этом состоянии (`connect` / `disconnect` / `fail`)|

Ошибка не сбрасывает состояние молча: после неудачной попытки статус показывает
`state: "error"` и текст причины, а новое подключение разрешено
(`allowed_events: ["connect", "disconnect"]`).

## 7. Сценарии тестирования

### 7.1 Успешное подключение и непустой список (stdio)

```bash
uv run python scripts/mcp_demo.py
```

Ожидаемо: `состояние: connected`, `сервер: mcp-fetch 1.30.0`,
`инструментов: 1`, ниже — `fetch` с описанием и схемой аргументов.

```bash
uv run python scripts/mcp_demo.py --target "npx -y @modelcontextprotocol/server-filesystem ."
```

Ожидаемо: `secure-filesystem-server 0.2.0`, **14** инструментов
(`read_text_file`, `write_file`, `directory_tree`, …).

### 7.2 Через API: подключение → список → отключение

```bash
curl -X POST http://127.0.0.1:8000/mcp/connect -H "Content-Type: application/json" -d "{\"target\": \"uvx mcp-server-fetch\"}"
curl http://127.0.0.1:8000/mcp/tools            # 200, count = 1
curl -X POST http://127.0.0.1:8000/mcp/disconnect -d "{}"
curl http://127.0.0.1:8000/mcp/tools            # 409 — соединения нет
```

### 7.3 Неверный URL — понятная ошибка

```bash
uv run python scripts/mcp_demo.py --target http://127.0.0.1:9/mcp --transport http --timeout 5
```

Ожидаемо: код выхода 1 и строка
«Не удалось подключиться к MCP-серверу [Streamable HTTP] http://127.0.0.1:9/mcp:
All connection attempts failed (проверьте URL и что сервер поднят)».

Через API та же цель:

```bash
curl -i -X POST http://127.0.0.1:8000/mcp/connect -H "Content-Type: application/json" -d "{\"target\": \"http://127.0.0.1:9/mcp\"}"
```

Ожидаемо: `502` с этим текстом в `detail`; затем `GET /mcp/status` →
`"state": "error"` и тот же текст в `error`.

### 7.4 Команды нет в PATH

```bash
uv run python scripts/mcp_demo.py --target "day16-no-such-command" --timeout 5
```

Ожидаемо: код выхода 1 и подсказка «команда 'day16-no-such-command' не найдена —
проверьте, что она установлена и есть в PATH (npx или uvx)».

### 7.5 Неразобранная цель и неизвестный транспорт

```bash
curl -i -X POST http://127.0.0.1:8000/mcp/connect -H "Content-Type: application/json" -d "{\"target\": \"   \"}"
```

Ожидаемо: `400` «Пустая цель подключения: укажите URL MCP-сервера или команду
запуска». Транспорт вне списка (`"transport": "ws"`) — `422` от Pydantic.

### 7.6 Вкладка «🔌 MCP» в интерфейсе

1. Выберите раздел «🔌 MCP» — статус «⚪ не подключено» и подсказка внизу.
2. `uvx mcp-server-fetch` → «🔌 Подключиться» → «🟢 подключено», таблица с `fetch`.
3. «🔄 Обновить список инструментов» → подпись «Список инструментов обновлён».
4. Введите `http://127.0.0.1:9/mcp` и нажмите «Подключиться» → красная плашка с
   текстом ошибки, состояние снова «⚪ не подключено».
5. «⏏ Отключиться» → статус «⚪ не подключено», список исчезает.

### 7.7 Автотесты

```bash
uv run pytest -q                                     # весь день: 1097 тестов
uv run pytest -q tests/unit/test_mcp_connection_fsm.py tests/unit/test_mcp_target.py \
                tests/unit/test_mcp_tools.py tests/integration/test_mcp_registry.py \
                tests/integration/test_mcp_stdio.py tests/integration/test_mcp_client_errors.py \
                tests/e2e/test_mcp_api.py             # только MCP: 84 теста
```

Тесты MCP офлайн: `tests/integration/test_mcp_stdio.py` поднимает **свой**
MCP-сервер (`tests/mcp_echo_server.py`, два инструмента) тем же интерпретатором,
что и тесты, — сеть и установка пакетов не нужны. Остальные тесты работают на
фейковом клиенте (`FakeMCPClient` в `tests/support.py`).

## 8. Ссылки

- [reports/mcp_demo.md](reports/mcp_demo.md) — прогон дня: серверы, команды,
  полученные списки инструментов, ошибки и их решения.
- [api.md](api.md) — эндпоинты `/mcp` с примерами и кодами ошибок.
- [architecture.md](architecture.md) — раздел «MCP-интеграция»: `MCPClient`,
  транспорты, жизненный цикл соединения, стейт-машина.
- [../README.md](../README.md) — возможности приложения и что нового в дне.
- [../STRUCTURE.md](../STRUCTURE.md) — карта модулей дня.
- Swagger: <http://127.0.0.1:8000/docs>.
