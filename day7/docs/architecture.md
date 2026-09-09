# Архитектура дня 7 — «Агент с контекстной памятью»

## Роль и компоненты

Приложение — чат-хаб LLM-агентов с долговременной памятью диалога. Агенты живут
на **бэкенде** (FastAPI), пользователь общается с ними через **фронтенд**
(Streamlit) по HTTP. Диалог каждого агента сохраняется в **SQLite** и при
каждом запросе целиком отправляется в DeepSeek — модель помнит предыдущие
реплики. Ключ DeepSeek читает только бэкенд.

```
┌──────────────┐  HTTP (requests)  ┌──────────────────┐  HTTPS (openai SDK)
│  Streamlit   │ ────────────────► │     FastAPI      │ ──────────────► DeepSeek API
│  app.py      │ ◄──────────────── │  backend/main.py │ ◄────────────── https://api.deepseek.com
│  порт 8501   │   JSON            │    порт 8000     │   Chat Completions
└──────────────┘                   └──────────────────┘
        чат (роль+текст)                    │
                                           ▼
                            ┌─────────────────────────────┐
                            │  AgentManager (синглтон)    │
                            │  dict[agent_id -> Agent]    │
                            └─────────────────────────────┘
                                           │ создаёт / восстанавливает / хранит
                              ┌────────────┴─────────────────────────┐
                              ▼                                      ▼
                        Agent «A»                                Agent «B»
                        config + self.messages                  config + self.messages
                              │                                      │
                              └────────────┬─────────────────────────┘
                                           ▼
                            ┌─────────────────────────────┐
                            │ SQLAlchemy → SQLite         │
                            │ agents.db: agents (конфиг)  │
                            │           messages (диалог) │
                            └─────────────────────────────┘
```

## Классы

```mermaid
classDiagram
    class AgentConfig {
        +str name
        +str model = "deepseek-chat"
        +float temperature = 0.7
        +str system_prompt = ""
        +int max_tokens = 2048
    }
    class Agent {
        +str agent_id
        +AgentConfig config
        +datetime created_at
        +list messages  "диалог [{'role','content'}]"
        +generate(prompt) dict
        +load_history()
        +save_message(role, content)
        +clear_history() int
        +history_rows() list
    }
    class AgentManager {
        -dict _agents
        -Lock _lock
        +create_agent(cfg) str
        +restore_from_db() int
        +get_agent_history(id) list
        +clear_agent_history(id) int
        +generate_response(id, prompt) dict
        +remove_agent(id) bool
    }
    class Message {
        +int id  PK
        +str agent_id  FK -> agents.agent_id, index
        +str role
        +str content  Text
        +datetime timestamp
    }
    class AgentRecord {
        +str agent_id  PK
        +str name, model
        +float temperature
        +str system_prompt  Text
        +int max_tokens
        +datetime created_at
    }
    class FastAPI {
        POST /agents
        GET /agents
        GET /agents/{id}
        DELETE /agents/{id}
        POST /agents/{id}/generate
        GET /agents/{id}/history
        DELETE /agents/{id}/history
    }
    AgentManager "1" o-- "*" Agent : хранит
    Agent --> AgentConfig : конфигурация
    FastAPI --> AgentManager : get_manager()
    Agent ..> Message : сохраняет/читает
    Agent ..> AgentRecord : восстанавливается из
```

Ключевые решения:

- **Agent владеет памятью диалога**: `self.messages` — копия в памяти в
  LLM-формате; источник правды — таблица `messages` в SQLite (см. ниже).
  `generate(prompt)` добавляет реплику пользователя, шлёт в DeepSeek **всю**
  историю (системный промпт — первым, если задан), добавляет ответ ассистента
  и сохраняет обе реплики **одной транзакцией**. При сбое API реплика
  откатывается — «user без ответа» в истории не появляется.
- **AgentManager** — синглтон процесса; при старте приложения
  `restore_from_db()` пересоздаёт агентов из `agents`, каждый агент в
  конструкторе сам загружает свой диалог (`load_history()`).
- **SQLAlchemy-слой** в `backend/database.py`: движок, сессии, ORM-модели.
  Внешние ключи включаются явно (`PRAGMA foreign_keys=ON`), сессия — на
  операцию (`check_same_thread=False` из-за пула потоков FastAPI).
- **Ключ** `DEEPSEEK_API_KEY` резолвится в момент генерации: `day7/.env` →
  переменная окружения → понятная ошибка без вызова сети. Клиент создаётся
  фабрикой `_make_client()` — офлайн-проверки подменяют её фейком.

## Схема БД (`day7/agents.db`)

Файл создаётся автоматически при старте бэкенда (`init_db()`).

| Таблица | Поле | Тип | Примечание |
| --- | --- | --- | --- |
| `agents` | `agent_id` | String | первичный ключ |
| | `name` | String(100) | имя агента |
| | `model` | String(100) | `deepseek-chat` / `deepseek-reasoner` |
| | `temperature` | Float | 0.0–2.0 |
| | `system_prompt` | **Text** | роль агента (длинный текст) |
| | `max_tokens` | Integer | 1–8192 |
| | `created_at` | DateTime | момент создания |
| `messages` | `id` | **Integer** | первичный ключ, автоинкремент |
| | `agent_id` | **String** | **ForeignKey → agents.agent_id**, `ondelete=CASCADE`, **index** |
| | `role` | String(16) | `user` / `assistant` |
| | `content` | **Text** | текст реплики (длинные промпты) |
| | `timestamp` | **DateTime** | момент реплики (UTC) |

Связь — **один-ко-многим**: у одного агента много сообщений. При удалении
агента его сообщения удаляются каскадом. В `messages` хранятся только реплики
диалога; системный промпт агента — конфигурация (таблица `agents`).

## Потоки взаимодействия

```mermaid
sequenceDiagram
    participant U as Streamlit (пользователь)
    participant F as FastAPI
    participant M as AgentManager
    participant A as Agent
    participant D as SQLite
    participant X as DeepSeek API

    U->>F: POST /agents {name, model, temperature, system_prompt, max_tokens}
    F->>M: create_agent(cfg)
    M->>D: INSERT agents (commit)
    M->>A: Agent(cfg, id) → load_history() (пусто)
    M-->>F: agent_id
    F-->>U: 201 {agent_id, ..., message_count: 0}

    U->>F: POST /agents/{id}/generate {prompt}
    F->>M: generate_response(id, prompt)
    M->>A: generate(prompt)
    A->>A: self.messages += user(prompt)
    A->>X: chat.completions.create(messages=system? + ВСЯ история)
    X-->>A: ответ + usage
    A->>A: self.messages += assistant(ответ)
    A->>D: INSERT user + assistant (одна транзакция)
    A-->>M: запись {response, usage, duration_sec, ...}
    M->>D: SELECT messages (актуальный диалог)
    M-->>F: запись + messages[]
    F-->>U: 200 {..., messages: [user, assistant, ...]}

    U->>F: DELETE /agents/{id}/history
    F->>M: clear_agent_history(id)
    A->>D: DELETE FROM messages WHERE agent_id=... (commit)
    F-->>U: {status: cleared, message_count: 0}

    Note over M,D: рестарт бэкенда
    M->>D: init_db(); SELECT agents
    M->>A: для каждой строки Agent(cfg, id, created_at)
    A->>D: load_history() → self.messages = [user, assistant, ...]
```

**Поток данных** (кратко): пользователь → интерфейс → агент → история → БД →
API → ответ → история → БД.

## Модель данных ответа генерации

`POST /agents/{id}/generate` возвращает `GenerateResponse`:

| Поле | Тип | Смысл |
| --- | --- | --- |
| `status` | `"ok"`/`"error"` | чем закончилась генерация |
| `response` / `error` | str? | текст ответа / понятная ошибка |
| `model`, `finish_reason` | str? | модель и причина завершения |
| `usage` | dict? | `prompt_tokens`, `completion_tokens`, `total_tokens` |
| `duration_sec` | float? | время запроса |
| `timestamp` | datetime | момент попытки |
| `messages` | [MessageOut] | **актуальный диалог** (обновлённая история с id и временем) |

`GET /agents/{id}/history` возвращает `[MessageOut]` — сообщения диалога по
возрастанию времени (хронология чата).

## Контракт ошибок API

- `404` — неизвестный `agent_id` (тело `{"detail": "Агент … не найден"}`);
- `422` — невалидное тело (Pydantic/FastAPI);
- `502` — сбой генерации (сеть, DeepSeek, «ключ не задан»): тело
  `{agent_id, status: "error", error: "…", messages: <неизменный диалог>, ...}` —
  без traceback; история не изменяется, агент и сервер продолжают работать.

## Масштабирование и ограничения

- **Память после рестарта** — главное отличие от дня 6: агенты и диалоги живут
  в SQLite; объекты в памяти — только кэш, актуализируемый на каждой операции и
  при старте.
- **Один процесс**: FastAPI обслуживает потоки, но БД одна (SQLite — один
  писатель). Для продакшена с несколькими процессами потребуется серверная БД
  (Postgres/Redis) — HTTP-контракт сохранится.
- **Синхронная генерация** — FastAPI держит поток на время вызова DeepSeek;
  для сотен одновременных запросов — асинхронные endpoint'ы/очередь.
- **Контекст DeepSeek ~64K токенов** — очень длинный диалог может не уместиться:
  кнопка «Очистить историю» / новый агент. Автообрезка — вне скоупа дня.

