# Структура дня 12

Карта модулей дня 12 после рефакторинга (коммит `9c7021c`): что где лежит и за
что отвечает. Правила структуры — в [`../AGENTS.md`](../AGENTS.md) и
[`../docs/architecture.md`](../docs/architecture.md).

**Главное правило: любой `.py` файл ≤ 400 строк** (`app.py` ≤ 100,
`backend/main.py` ≤ 80). Файл подошёл к ~350 строкам — дели на модули по
доменам, не дожидаясь 401-й строки.

## Раскладка

```
day12/
├── app.py                    # точка входа Streamlit (40 строк): set_page_config + вызовы секций
├── ui/                       # Streamlit UI по секциям (8 модулей)
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным
│   ├── routers/              # эндпоинты по доменам (4 роутера)
│   ├── models/               # Pydantic-схемы API по доменам (4 модуля)
│   ├── manager_*.py          # миксины AgentManager по доменам
│   └── tables.py             # ORM-таблицы SQLAlchemy
├── tests/                    # pytest: 314 тестов (офлайн)
├── docs/                     # architecture.md, usage.md, api.md
├── personalization_comparison.py  # прогон отчёта (реальный API или --no-api)
├── personalization_comparison.md  # отчёт персонализации
├── comparison_report.py      # сборка отчёта сравнения профилей
├── comparison_stub.py        # офлайн-заглушка сравнения
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── requirements.txt, .env.example
└── agents.db                 # SQLite (в .gitignore по *.db)
```

## `ui/` — интерфейс Streamlit (по секциям)

| Модуль | Строк | Назначение |
|---|---|---|
| `ui/__init__.py` | 6 | Описание пакета; модули не выполняют `st.*` на импорте |
| `ui/api_client.py` | 267 | HTTP-транспорт к бэкенду (`requests`), `BACKEND_URL` / `DAY12_BACKEND_URL`, `BackendError` |
| `ui/common.py` | 180 | Подписи, форматтеры, `st.session_state`: init, флеш-сообщения, выбор активного агента |
| `ui/sidebar.py` | 191 | Боковая панель: агенты, создание агента, стратегия, задача и сессия (`render_sidebar()`) |
| `ui/chat_section.py` | 254 | Раздел «💬 Чат и память», сборка страницы (`render_main_area()`) |
| `ui/context_panels.py` | 324 | Панели контекста: токены, сжатие, сравнение режимов, ветки, факты |
| `ui/memory_panels.py` | 229 | Панели трёх слоёв памяти, индикатор «что ушло в запрос» |
| `ui/profile_section.py` | 322 | Раздел «👤 Профиль пользователя»: CRUD профилей, предпросмотр промпта |
| `ui/profile_comparison.py` | 129 | Сравнение двух профилей на одном вопросе (временные агенты) |

## `backend/routers/` — эндпоинты по доменам

| Модуль | Строк | Эндпоинтов | Домен |
|---|---|---|---|
| `backend/routers/__init__.py` | 1 | — | Описание пакета |
| `backend/routers/agents.py` | 243 | 11 | CRUD агентов, генерация, диалог, статистика токенов |
| `backend/routers/context.py` | 140 | 9 | Сжатие истории, стратегии, ветки, факты |
| `backend/routers/memory.py` | 180 | 10 | Слои памяти (`/memory/short-term`, `/working`, `/long-term`), сессия, задача |
| `backend/routers/profiles.py` | 126 | 6 | Профили пользователей `/users...`, `GET /agents/{id}/profile` |

Всего 36 эндпоинтов. Пути внутри роутеров абсолютные, префиксов нет;
подключение — в `backend/main.py`. Доступ к менеджеру и 404 —
`backend/dependencies.py`.

## `backend/models/` — Pydantic-схемы API по доменам

| Модуль | Строк | Домен |
|---|---|---|
| `backend/models/__init__.py` | 122 | Реэкспорт всех схем (импорт — из `backend.models`) |
| `backend/models/agent.py` | 315 | Агент, генерация, метрики использования токенов |
| `backend/models/context.py` | 218 | Сжатие истории, стратегии, ветки, факты |
| `backend/models/memory.py` | 173 | Три слоя памяти агента |
| `backend/models/profile.py` | 170 | Профиль пользователя и его вклад в промпт |

ORM-таблицы (`AgentRecord`, `ShortTermMessage`, `WorkingMemory`,
`LongTermMemory`, `Summary`, `TokenUsage`, `Fact`, `Checkpoint`,
`UserProfile`) лежат в `backend/tables.py` (383 строки) и реэкспортируются через
`backend/database.py`. Это расхождение с целевой раскладкой `AGENTS.md`
(`models/` — ORM, `schemas/` — Pydantic) зафиксировано в `AGENTS.md`, раздел
«Известные расхождения со снимками».

## Остальные модули `backend/`

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/__init__.py` | 45 | Описание пакета + добавление корня репозитория в `sys.path` (для `shared/`) |
| `backend/config.py` | 148 | Настройки: URL/модели DeepSeek, дефолты, лимиты и цены, сжатие, стратегии, память, профиль, пути `.env` и `agents.db` |
| `backend/strategies.py` | 62 | `Enum Strategy` и проверка значения |
| `backend/context_fsm.py` | 256 | Стейт-машина сжатия (`Enum` + паттерн State) |
| `backend/context_policy.py` | 173 | Чистая арифметика сжатия |
| `backend/fact_extractor.py` | 96 | Эвристика извлечения фактов |
| `backend/memory_layers.py` | 143 | Представления слоёв памяти и их тексты |
| `backend/memory.py` | 286 | `MemoryManager`: хранение трёх слоёв |
| `backend/profile_values.py` | 335 | Перечисления и нормализация значений профиля |
| `backend/profiles.py` | 204 | Блок персонализации для системного промпта |
| `backend/profile_store.py` | 291 | Чтение/запись профиля в SQLite |
| `backend/demo_profiles.py` | 107 | Демонстрационные профили |
| `backend/compressor.py` | 326 | `ContextCompressor`: план, суммаризация, конспект |
| `backend/agent.py` | 1515 ⚠️ | `Agent`: память, токены, `prepare_context`, стратегии, факты, ветки, профиль |
| `backend/manager_agents.py` | 233 | Миксин пула агентов |
| `backend/manager_profiles.py` | 119 | Миксин профилей пользователей |
| `backend/manager_context.py` | 107 | Миксин сжатия, стратегий, веток, фактов |
| `backend/manager_usage.py` | 107 | Миксин статистики токенов (SQL-агрегаты) |
| `backend/manager_memory.py` | 88 | Миксин трёх слоёв памяти |
| `backend/agent_manager.py` | 71 | `AgentManager` — синглтон из миксинов |
| `backend/dependencies.py` | 25 | `get_manager`, `agent_or_404` для роутеров |
| `backend/main.py` | 84 | Сборка `app`: `lifespan`, CORS, `include_router` |

## Что импортируется из `shared/`

| Модуль дня | Импорт | Зачем |
|---|---|---|
| `backend/__init__.py` | — (добавляет корень репозитория в `sys.path`) | Чтобы `from shared...` работал из любого модуля дня |
| `backend/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens` | Клиент DeepSeek, локальный подсчёт токенов |
| `backend/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API, чтение `DEEPSEEK_API_KEY` |
| `backend/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/tables.py` | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/main.py` | `shared.logging_utils.get_logger` | Логгер бэкенда |

Модули `ui/` обращаются к бэкенду только по HTTP (`ui/api_client.py`), поэтому
`shared/` напрямую не импортируют.

## Известные расхождения

| Файл | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agent.py` | 1515 | 400 | Домен `Agent` (память, стратегии, токены, профиль, генерация) ещё не разложен на миксины — расхождение унаследовано от дня 11 |

Лимиты `app.py` (40 ≤ 100) и `backend/main.py` (84 > 80) — по `main.py`
превышение на 4 строки, оно зафиксировано в `AGENTS.md` («Известные расхождения
со снимками») и подлежит устранению при следующей правке дня.

## Проверка лимита строк

Из папки `day12` (`.venv` исключён):

```powershell
.venv/Scripts/python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод сегодня: `[('backend\\agent.py', 1515)]`.
