# Запуск и общие модули

Практическая часть междневных изменений: как запускать активный день 12 после
рефакторинга и как пользоваться общим пакетом `shared/`. Установка, проверки и
FAQ конкретного дня — в [`../day12/docs/usage.md`](../day12/docs/usage.md),
устройство модулей — в [`architecture.md`](architecture.md) и
[`../day12/STRUCTURE.md`](../day12/STRUCTURE.md).

## Запуск day12 после рефакторинга

**Команды не изменились** — рефакторинг затронул раскладку кода, а не точки
входа: `backend.main:app` по-прежнему собирается из `backend/routers/`, а
Streamlit-страницу по-прежнему запускает `app.py` (теперь он вызывает секции
пакета `ui/`). Из папки `day12`:

**Подготовка (один раз):**

```powershell
cd day12
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
copy .env.example .env      # затем впишите DEEPSEEK_API_KEY=sk-...
```

**Терминал 1 — бэкенд (FastAPI + uvicorn, порт 8000):**

```powershell
cd day12
.venv/Scripts/python -m uvicorn backend.main:app --port 8000
```

При старте создаются таблицы SQLite (`day12/agents.db`) и восстанавливаются
агенты из базы. Swagger — `http://127.0.0.1:8000/docs`, список эндпоинтов —
`curl.exe http://127.0.0.1:8000/`.

**Терминал 2 — интерфейс (Streamlit, порт 8501):**

```powershell
cd day12
.venv/Scripts/python -m streamlit run app.py
```

**Тесты и проверки (из папки `day12`):**

```powershell
.venv/Scripts/python -m pytest -q                  # автотесты дня 12
.venv/Scripts/python -m py_compile backend/main.py backend/routers/agents.py backend/routers/context.py backend/routers/memory.py backend/routers/profiles.py backend/dependencies.py ui/api_client.py ui/chat_section.py ui/sidebar.py app.py
```

> **CWD важен.** Приложение ищет `.env` в текущей директории, поэтому и
> `uvicorn`, и `streamlit` запускаются **из папки дня**. Пакет `shared/`
> подключается автоматически: `day12/backend/__init__.py` добавляет корень
> репозитория в `sys.path`.

Офлайн-прогон отчёта персонализации (без запросов к API):

```powershell
.venv/Scripts/python personalization_comparison.py --no-api
```

## Работа с `shared/`

`shared/` — пакет в корне репозитория с кодом, который **не меняется между
днями**: клиент DeepSeek, база SQLAlchemy, подсчёт токенов, логирование. Копия
такого кода внутри `dayN/` запрещена — см. `AGENTS.md`, раздел «Запрещено».

**Как импортировать в новом дне.** День добавляет корень репозитория в `sys.path`
один раз — в `backend/__init__.py` (так сделано в дне 12):

```python
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]   # day12/backend/__init__.py → корень репозитория
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

После этого модули дня импортируют общие помощники обычной строкой:

```python
from shared.deepseek_client import make_client       # клиент OpenAI SDK → DeepSeek
from shared.token_counter import count_tokens        # локальная оценка токенов (tiktoken)
from shared.db_base import Base, make_engine, init_db, make_session_factory
from shared.logging_utils import get_logger, configure_logging
from shared.deepseek_utils import read_key_from_env_file, DEEPSEEK_BASE_URL
```

Что где лежит:

| Нужно | Модуль | Имя |
|---|---|---|
| Клиент DeepSeek | `shared/deepseek_client.py` | `make_client(api_key, base_url, timeout)` |
| Ключ из `.env`, endpoint, stop-строки, `usage` → dict | `shared/deepseek_utils.py` | `read_key_from_env_file`, `DEEPSEEK_BASE_URL`, `parse_stop_sequences`, `usage_to_dict` |
| База SQLAlchemy/SQLite | `shared/db_base.py` | `Base`, `make_engine`, `init_db`, `make_session_factory` |
| Токены | `shared/token_counter.py` | `count_tokens`, `get_tokenizer` |
| Логи | `shared/logging_utils.py` | `get_logger`, `configure_logging` |

Правила работы с `shared/`: ORM-классы дня наследуются от `shared.db_base.Base`;
движок создаётся `make_engine(...)` (SQLite с `check_same_thread=False` и
`PRAGMA foreign_keys=ON`), сессии — `make_session_factory(engine)`; логгер
берётся из `shared.logging_utils.get_logger(__name__)` (вывод включается только
явным `configure_logging()` в приложении); `openai` и `tiktoken` импортируются
лениво, поэтому импорт модулей остаётся дешёвым и офлайн-тесты не требуют сети.

## Проверка структуры перед коммитом

Лимит размера файлов (из папки дня, `.venv` исключён):

```powershell
.venv/Scripts/python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Проверять нужно до коммита: правило «любой `.py` ≤ 400 строк» (`app.py` ≤ 100,
`backend/main.py` ≤ 80) — из `AGENTS.md`. Известные превышения в снимках
`day8/`–`day12/` перечислены в `AGENTS.md` («Известные расхождения со
снимками») и в `STRUCTURE.md` соответствующего дня; в дне 12 это
`backend/agent.py` (1515 строк).

Чек-лист междневного изменения:

1. Новый модуль лежит в своём домене (`ui/`, `backend/routers/`,
   `backend/models/`, `shared/`), а не в «ближайшем» файле.
2. Обновлён `STRUCTURE.md` дня (список модулей и назначение каждого).
3. Обновлён [`../CHANGELOG.md`](../CHANGELOG.md) (дата, тип, что затронуто).
4. `pytest` из папки дня зелёный, `py_compile` по изменённым файлам без ошибок.
