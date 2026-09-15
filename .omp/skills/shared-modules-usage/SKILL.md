---
name: shared-modules-usage
description: "How to use and extend shared/ modules in the ai-challenge project. Use this whenever code needs a DeepSeek API client, SQLAlchemy Base/engine/session, token counting via tiktoken, or logging — anything that does not change between days. Also use when deciding whether new code should go to shared/ or stay in the day folder. Triggers: import shared, DeepSeek client, database base, make_engine, count tokens, tiktoken, logging, common utility, shared/ module."
---

# Общий пакет `shared/`

`shared/` — пакет в корне репозитория для кода, который **не меняется между
днями**. Копия такого кода внутри `dayN/` запрещена.

## Что лежит в `shared/`

| Модуль | Публичные имена | Назначение |
|---|---|---|
| `shared/deepseek_utils.py` | `DEEPSEEK_BASE_URL`, `read_key_from_env_file`, `parse_stop_sequences`, `usage_to_dict` | Endpoint DeepSeek (`https://api.deepseek.com`), чтение `DEEPSEEK_API_KEY` из `.env`, разбор stop-строк из UI, объект `Usage` → dict |
| `shared/deepseek_client.py` | `make_client(api_key, base_url, timeout)`, `DEFAULT_TIMEOUT = 60.0` | Клиент OpenAI SDK → DeepSeek; `openai` импортируется лениво (импорт модуля дешёвый, офлайн-тесты не требуют сети) |
| `shared/db_base.py` | `Base`, `make_engine`, `init_db`, `make_session_factory` | Декларативная база SQLAlchemy; движок SQLite с `check_same_thread=False` (пул потоков FastAPI) и `PRAGMA foreign_keys=ON`; создание таблиц; фабрика сессий |
| `shared/token_counter.py` | `count_tokens`, `get_tokenizer` | Локальная оценка токенов через tiktoken (`cl100k_base`); кодировка кэшируется на процесс, `tiktoken` импортируется лениво |
| `shared/logging_utils.py` | `get_logger`, `configure_logging`, `DEFAULT_FORMAT` | Единственный источник настроек логирования: `get_logger` не добавляет хендлеров (вывод по умолчанию выключен), включает вывод только явный `configure_logging()` в приложении |

## Правило

Код, который **не меняется между днями**, обязан жить в `shared/` и не
дублироваться между днями. Если один и тот же код понадобился в `dayN/` и
`dayN+1/` и он не отличается между ними — он переезжает в `shared/`.

## Как подключать `shared/` из дня

Корень репозитория добавляется в `sys.path` один раз — в `backend/__init__.py`
дня (пример: `day12/backend/__init__.py`):

```python
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]   # dayN/backend/__init__.py → корень репозитория
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

Дальше модули дня импортируют общие помощники обычной строкой — без хаков в
тестах и без копий кода:

```python
from shared.deepseek_client import make_client
from shared.token_counter import count_tokens
from shared.db_base import Base, make_engine, init_db, make_session_factory
from shared.logging_utils import get_logger, configure_logging
from shared.deepseek_utils import read_key_from_env_file, DEEPSEEK_BASE_URL
```

## Что НЕ должно лежать в `shared/`

- Логика конкретного дня (правила домена, политики, эвристики).
- FSM конкретного дня (`context_fsm.py` — модуль дня, см. скилл `python-fsm-agent`).
- ORM-таблицы конкретного дня (`backend/tables.py`).
- Pydantic-схемы API конкретного дня (`backend/models/`).

## Что можно выносить в `shared/`

- Обёртки над внешними API (клиент DeepSeek).
- База SQLAlchemy: `Base`, движок, фабрика сессий.
- Подсчёт токенов (tiktoken).
- Логирование.
- Любые утилиты без доменной привязки к конкретному дню (ключ из `.env`,
  парсинг stop-строк, `usage` → dict).

Правка `shared/` меняет поведение всех дней сразу: после изменения прогони тесты
дня, который его использует.
