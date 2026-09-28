# День 17 — свой MCP-сервер и вызов инструмента из агента

Отчёт о живом прогоне (`scripts/mcp_tool_demo.py`): свой MCP-сервер дня по stdio, его каталог инструментов, успешные и отказные вызовы, и шаг MCP в работе агента — инструмент вызывается по ключевым словам реплики, а его данные уходят в системный промпт того же запроса.

Цель подключения: `uv run python mcp_server/server.py`
Внешний API инструментов: `https://jsonplaceholder.typicode.com`
Клиент DeepSeek: офлайн-заглушка, отвечающая по блоку данных MCP

## 1. Что проверялось

| Проверка | Результат |
|---|---|
| Соединение с собственным MCP-сервером по stdio | ✅ `connected`, сервер `day17-jsonplaceholder 1.0.0`, протокол 2025-11-25 |
| Каталог `tools/list` с обеими схемами | ✅ 3 инструмента, у каждого непустые `input_schema` и `output_schema` |
| Вызовы `tools/call` | ✅ успешных: 3 |
| Отказные вызовы | ✅ отказов и ошибок: 3 (коды: bad_arguments, tool_error, unknown_tool) |
| Три инструмента вызываются через `MCPToolRunner` | ✅ `get_user`, `get_post`, `list_user_posts`
| Агент сам вызывает инструмент по реплике | ✅ `get_user` с аргументами `{"user_id": 1}`, данные в промпте: True |
| Реплика без ключевых слов не вызывает инструмент | ✅ `called=False`, `detected=False` |
| API: `POST /mcp/call`, `GET /mcp/servers`, `GET /mcp/tools` | ✅ проверяется `tests/e2e/test_mcp_call_api.py` |
| Автотесты | 1222 passed, 209 warnings in 90.82s (0:01:30) |

## 2. Какой API использовался

Инструменты сервера читают публичный mock API **jsonplaceholder.typicode.com** (`DEFAULT_API_BASE` в `mcp_server/config.py`) — он не требует ключа, поэтому инструменты можно вызывать в любой момент. HTTP-запросы настоящие: `mcp_server/api_client.py` ходит в сеть через `httpx`, а не отдаёт заготовки.

Адрес этого прогона: `https://jsonplaceholder.typicode.com`.

| Ручка API | Инструмент | Что берётся из ответа |
|---|---|---|
| `GET /users/{id}` | `get_user` | id, name, username, email, phone, website, address.city → city, company.name → company |
| `GET /posts/{id}` | `get_post` | id, userId → user_id, title, body |
| `GET /posts?userId=N&_limit=K` | `list_user_posts` | список {id, title} + count |

Ошибки внешнего API переводятся в понятный текст для модели: 404 — «Пользователь с id=999 не найден (HTTP 404): у jsonplaceholder 10 пользователей, id от 1 до 10», недоступность — «Внешний API … недоступен». Такая ошибка возвращается инструментом как результат с `isError`, а не исключением: агент видит причину и отвечает без внешних данных.

## 3. Сервер и инструменты

Сервер дня — `day17/mcp_server/` (`MCPServer` из MCP SDK 2.x), транспорт stdio: клиент поднимает его дочерним процессом, JSON-RPC идёт по stdin/stdout. Запуск руками (для отладки):

```bash
uv run python mcp_server/server.py            # ждёт JSON-RPC на stdin
uv run python mcp_server/server.py --api-base <адрес> --timeout 5
```

Прогон подключился командой:

```
цель:        uv run python mcp_server/server.py
транспорт:   stdio (дочерний процесс)
сервер:      day17-jsonplaceholder 1.0.0 (протокол 2025-11-25)
инструментов: 3
```

| Инструмент | Описание | `input_schema` | `output_schema` |
|---|---|---|---|
| `get_user` | Возвращает данные пользователя по его id. Параметр user_id — целое число (у jsonplaceholder 10 пользователей, id от 1 до 10). Возвращает объект с полями id, name, username, email, city, phone, website, company. Пример вызова: get_user(user_id=1). Если пользователя с таким id нет, инструмент сообщает об ошибке (HTTP 404). | `{"properties": {"user_id": {"title": "User Id", "type": "integer"}}, "required": ["user_id"], "type": "object", "title": "get_userArguments"…` | `{"properties": {"id": {"title": "Id", "type": "integer"}, "name": {"title": "Name", "type": "string"}, "username": {"title": "Username", "ty…` |
| `get_post` | Возвращает пост по его id. Параметр post_id — целое число (у jsonplaceholder 100 постов, id от 1 до 100). Возвращает объект с полями id, user_id, title, body: user_id — автор поста. Пример вызова: get_post(post_id=1). Если поста с таким id нет, инструмент сообщает об ошибке (HTTP 404). | `{"properties": {"post_id": {"title": "Post Id", "type": "integer"}}, "required": ["post_id"], "type": "object", "title": "get_postArguments"…` | `{"properties": {"id": {"title": "Id", "type": "integer"}, "user_id": {"title": "User Id", "type": "integer"}, "title": {"title": "Title", "t…` |
| `list_user_posts` | Возвращает посты пользователя. Параметры: user_id — целое число (кто автор), limit — сколько постов вернуть (от 1 до 20, по умолчанию 5). Возвращает объект с полями user_id, count и posts — список записей с id и title. Пример: list_user_posts(user_id=1, limit=3). | `{"properties": {"user_id": {"title": "User Id", "type": "integer"}, "limit": {"default": 5, "title": "Limit", "type": "integer"}}, "required…` | `{"properties": {"user_id": {"title": "User Id", "type": "integer"}, "count": {"title": "Count", "type": "integer"}, "posts": {"items": {"$re…` |

Схемы — не ручной текст: `inputSchema` собирается SDK из типизированных параметров, `outputSchema` — из аннотации возврата (`TypedDict` в `mcp_server/schemas.py`), а `structuredContent` ответа равен самому словарю. Поэтому описание параметров и полей результата видит и модель, и клиент.

## 4. Вызовы инструмента

### Успешные вызовы

`get_user({"user_id": 1})` → успешно, 451 мс

```json
{
  "id": 1,
  "name": "Leanne Graham",
  "username": "Bret",
  "email": "Sincere@april.biz",
  "city": "Gwenborough",
  "phone": "1-770-736-8031 x56442",
  "website": "hildegard.org",
  "company": "Romaguera-Crona"
}
```

`get_post({"post_id": 1})` → успешно, 327 мс

```json
{
  "id": 1,
  "user_id": 1,
  "title": "sunt aut facere repellat provident occaecati excepturi optio reprehenderit",
  "body": "quia et suscipit\nsuscipit recusandae consequuntur expedita et cum\nreprehenderit molestiae ut ut quas totam\nnostrum rerum est autem sunt rem eveniet architecto"
}
```

`list_user_posts({"user_id": 1, "limit": 3})` → успешно, 234 мс

```json
{
  "user_id": 1,
  "count": 3,
  "posts": [
    {
      "id": 1,
      "title": "sunt aut facere repellat provident occaecati excepturi optio reprehenderit"
    },
    {
      "id": 2,
      "title": "qui est esse"
    },
    {
      "id": 3,
      "title": "ea molestias quasi exercitationem repellat qui ipsa sit aut"
    }
  ]
}
```

### Отказные вызовы

| Вызов | Состояние | Код причины | Текст |
|---|---|---|---|
| `no_such_tool({})` | отклонён | `unknown_tool` | Инструмент «no_such_tool» не найден в каталоге сервера. Доступны: get_user, get_post, list_user_posts |
| `get_user({})` | отклонён | `bad_arguments` | Не указан обязательный аргумент «user_id» инструмента «get_user». Укажите число в запросе (например, «пользователь 3») или передайте аргументы через POST /mcp/call. |
| `get_user({"user_id": 999})` | ошибка | `tool_error` | Error executing tool get_user: Пользователь с id=999 не найден (HTTP 404): у jsonplaceholder 10 пользователей, id от 1 до 10. |

Разница принципиальная: первые три строки — отказы правил допуска (`unknown_tool`, `bad_arguments`) — инструмент даже не вызывался, а последняя — ответ сервера «пользователя с id=999 нет» (`tool_error`, `isError`): вызов состоялся, и текст ошибки — данные ответа.

## 5. Как агент использовал результат

Агент сам решает по реплике, нужен ли вызов: правила домена (`backend/domain/mcp_intent.py`) ищут ключевые слова и номер аргумента, правила допуска (`mcp_tool_call.admission_reason`) проверяют соединение, каталог и типы аргументов, а результат уходит системным блоком в промпт этого же запроса (`render_mcp_tool_block`).

### Запрос, по которому инструмент вызван

`Найди информацию о пользователе с ID 1`

Отчёт хода (`record["mcp"]`), статус генерации: `ok`

```json
{
  "state": "done",
  "detected": true,
  "connected": true,
  "called": true,
  "accepted": true,
  "tool": "get_user",
  "arguments": {
    "user_id": 1
  },
  "result": {
    "tool": "get_user",
    "arguments": {
      "user_id": 1
    },
    "structured": {
      "id": 1,
      "name": "Leanne Graham",
      "username": "Bret",
      "email": "Sincere@april.biz",
      "city": "Gwenborough",
      "phone": "1-770-736-8031 x56442",
      "website": "hildegard.org",
      "company": "Romaguera-Crona"
    },
    "text": "{\n  \"id\": 1,\n  \"name\": \"Leanne Graham\",\n  \"username\": \"Bret\",\n  \"email\": \"Sincere@april.biz\",\n  \"city\": \"Gwenborough\",\n  \"phone\": \"1-770-736-8031 x56442\",\n  \"website\": \"hildegard.org\",\n  \"company\": \"Romaguera-Crona\"\n}",
    "is_error": false,
    "duration_ms": 253
  },
  "is_error": false,
  "reason_code": null,
  "error": null,
  "duration_ms": 253,
  "used_in_prompt": true,
  "added_tokens": 149
}
```

### Что ушло в системный промпт

```
## Данные MCP-инструмента
Инструмент: get_user
Аргументы: {"user_id": 1}
Результат (JSON): {"city": "Gwenborough", "company": "Romaguera-Crona", "email": "Sincere@april.biz", "id": 1, "name": "Leanne Graham", "phone": "1-770-736-8031 x56442", "username": "Bret", "website": "hildegard.org"}

Используй эти данные как источник правды в ответе и не выдумывай поля, которых здесь нет.
```

### Ответ агента

```
[офлайн-заглушка] данные MCP-инструмента в запросе: {"city": "Gwenborough", "company": "Romaguera-Crona", "email": "Sincere@april.biz", "id": 1, "name": "Leanne Graham", "phone": "1-770-736-8031 x56442", "username": "Bret", "website": "hildegard.org"}
```

### Реплика без ключевых слов

`Сколько будет 2+2?` — инструмент не вызывался (`detected=False`, `state=idle`), блок данных в промпт не добавлялся:

```
(блока «Данные MCP-инструмента» в системном промпте нет)
```

## 6. Автотесты

Новые тесты дня (офлайн, без сети и без ключа DeepSeek): стейт-машина вызова и правила допуска, распознавание реплики, блок промпта, каталог серверов, настоящий stdio-сервер, раннер, шаг MCP в агенте и эндпоинты API.

```bash
uv run pytest -q
```

Сводка прогона: 1222 passed, 209 warnings in 90.82s (0:01:30)

## 7. Что осталось за рамками дня

- Живые серверы официального набора (`uvx mcp-server-fetch`, файловый через `npx`) не запускались: они ставят пакеты из PyPI/npm, поэтому в прогон дня не входят — их каталог показывает `scripts/mcp_demo.py` дня 16.
- Транспорты SSE и Streamable HTTP проверены только разбором цели и ошибками соединения (тесты), живого HTTP-сервера MCP у дня нет.
- Одновременных MCP-подключений нет: у процесса одно соединение — каталог `GET /mcp/servers` показывает известные цели, а не открытые сессии.
- Права на вызов не различаются: инструменты вызываются без подтверждения пользователя. Ограничение сознательное — вызов идёт только по явным ключевым словам реплики, но это эвристика, а не политика безопасности.
- Стриминг результатов и повторные попытки при сбое сети не реализованы: неудачный вызов возвращается исходом `failed`, и агент отвечает без данных.
