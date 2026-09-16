---
name: fastapi-streamlit-day-structure
description: "File layout and size limits for new FastAPI + Streamlit days in the ai-challenge project. Use this whenever creating a new day app (day13+), refactoring a monolithic day into modules, splitting large files (over 400 lines), or structuring backend/frontend/shared directories by layer. Triggers: new day, create day app, refactor day, split file, restructure backend, refactor backend, ui, frontend, file layout, 400 lines limit."
---

# Раскладка файлов дня (FastAPI + Streamlit)

Правила целевые: для новых дней (`day13/` и далее) и для кода, который осознанно
рефакторится. Снимки прошлых дней под них не переписываются (см. `AGENTS.md`,
раздел «Известные расхождения со снимками»). Эталон — `day13/`; карта модулей —
`day13/STRUCTURE.md`.

## Раскладка

Файл лежит в папке **своего слоя**. Обязательный состав слоёв один и тот же для
любого дня с бэкендом: девять папок в `backend/` (папка может быть пустой, если
в дне нет таких сущностей — но `__init__.py` в ней есть). Пакет слоя содержит
`__init__.py` с реэкспортом публичных имён — это публичный контракт слоя.

```
dayN/
├── app.py            Streamlit, точка входа (≤ 100 строк): только вызовы секций
├── frontend/         интерфейс по секциям (или одностраничный `app.py` в корне)
├── backend/
│   ├── __init__.py   описание пакета (+ корень репозитория в sys.path для shared/)
│   ├── api/          FastAPI: роутеры по доменам + main.py (сборка app, ≤ 80 строк)
│   ├── core/         config (настройки, лимиты, цены, пути .env/БД), dependencies
│   ├── domain/       чистые правила и данные: без БД, LLM и HTTP
│   ├── services/     прикладная логика: оркестрация domain и storage
│   ├── storage/      доступ к БД: движок и сессии, хранилища, реэкспорт ORM
│   ├── agents/       агент, его память/профиль и менеджер (миксины — manager_*.py)
│   ├── models/       ORM-таблицы SQLAlchemy по доменам
│   ├── schemas/      Pydantic-схемы API по доменам
│   └── utils/        утилиты дня; пусто, если всё общее живёт в shared/
├── scripts/          прогоны демонстраций и сборка отчётов
├── tests/            unit/ (без БД), integration/ (временная БД и агент), e2e/ (TestClient)
└── docs/             architecture.md, usage.md, api.md, reports/ (отчёты прогонов)
```

Слои раскрываются так (образцы имён — из `day13/`):

- `frontend/` — Streamlit по секциям: `sidebar.py`, `chat_section.py`,
  `common.py` (подписи, форматтеры, `st.session_state`), `api_client.py`
  (HTTP-клиент к бэкенду), `<domain>_panels.py` / `<domain>_section.py` для
  разделов. Модули не выполняют `st.*` на импорте; `app.py` только вызывает
  секции. Не влезает в 400 строк или распадается на два домена — рядом кладётся
  ещё один модуль `frontend/<domain>.py`.
- `backend/api/` — FastAPI по доменам: `agents.py`, `context.py`, `memory.py`,
  `profiles.py`, `tasks.py`; эндпоинт лежит в файле своего домена, пути внутри
  роутеров абсолютные (`/agents/...`), префиксы не вводятся.
- `backend/schemas/` — Pydantic-схемы API по доменам (те же имена:
  `agent.py`, `context.py`, `memory.py`, `profile.py`, `task.py`), реэкспорт всех
  имён через `schemas/__init__.py`.
- `backend/models/` — ORM-таблицы SQLAlchemy по доменам (`agent.py` — `agents` и
  его `relationship`, `message.py`, `memory.py`, `context.py`, `user_profile.py`,
  `task_state.py`); реэкспорт классов — через `backend/storage/database.py`,
  который создаёт движок и фабрику сессий (`make_engine` / `init_db` /
  `make_session_factory` из `shared/db_base.py`).
- `backend/domain/` — чистые правила: FSM (состояния/события — `Enum`, переходы —
  паттерн State, см. скилл `python-fsm-agent`), стратегии, эвристики, шаблоны
  текстов, значения с нормализацией.
- `backend/storage/` — `database.py` (движок, сессии, реэкспорт ORM),
  `<domain>_store.py` (единственное место работы с таблицами домена),
  `<domain>_rows.py` (ORM-строка → словарь для API/UI).
- `backend/services/` — `<domain>_service.py` / `<domain>_state.py`: то, что
  оркеструет `domain` и `storage` (вызовы LLM, переходы, запись конспекта).
- `backend/agents/` — `agent.py`, `memory.py`, `profile_store.py`,
  `agent_manager.py`; крупный класс менеджера собирается из миксинов
  `manager_<domain>.py`, а не растёт одним файлом.
- `backend/core/config.py` — настройки и дефолты (URL/модели, лимиты, цены, пути
  БД и `.env`), `backend/core/dependencies.py` — зависимости роутов
  (`get_manager`, `<entity>_or_404`).
- `backend/api/main.py` — **только сборка `app` (≤ 80 строк):** `FastAPI(...)`,
  CORS, `lifespan`, `include_router(...)`.
- `backend/utils/` — утилиты дня; если общий код не меняется между днями, он
  живёт в `shared/` (скилл `shared-modules-usage`).

Обратные связи слоёв запрещены: `domain` не знает про БД, HTTP и Streamlit;
`frontend/` общается с бэкендом только по HTTP. Цикл импортов разрывается
локальным импортом внутри функции или `TYPE_CHECKING` — с комментарием, зачем.

## Лимиты

- Любой `.py` — **≤ 400 строк**. Файл подошёл к ~350 строкам — уже дели на модули
  по доменам, не дожидаясь 401-й строки.
- `app.py` ≤ 100 строк, `backend/api/main.py` ≤ 80 строк.

Команда проверки лимита строк (из папки дня; `.venv` исключён):

```powershell
.venv\Scripts\python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

## Запреты

- Складывать всю логику в один файл, если он превышает 400 строк.
- Складывать модули в корень `backend/`: там только `__init__.py` — модуль без
  своей папки означает, что слой не определён.
- Создавать `utils.py` / `helpers.py` без чёткой доменной принадлежности — вместо
  этого `shared/<domain>.py` (или `<пакет>/<domain>.py`, если код относится к
  одному домену дня).

## Правила работы

- **Новая сущность** — сразу определить её слой и положить в соответствующий
  модуль (`frontend/`, `backend/api/`, `backend/domain/`, `backend/storage/`,
  `backend/services/`, `backend/agents/`, `backend/models/`, `backend/schemas/`,
  `scripts/`, `tests/{unit,integration,e2e}/`, `shared/`), а не в «ближайший» файл.
- **Перед началом работы** посмотреть структуру `dayN-1/` и переиспользовать её
  паттерны: имена модулей, слои, конвенции тестов.
- **При конфликте** «паттерн `dayN-1/`» и «правила структуры» приоритет у правил
  структуры: паттерн повторяем, раскладку файлов делаем по правилам, а
  расхождение отмечаем в `STRUCTURE.md` нового дня.

## Эталон

`day13/` — полная карта модулей и их назначение в `day13/STRUCTURE.md`
(девять слоёв `backend/`, `frontend/`, `scripts/`, `tests/{unit,integration,e2e}/`,
`docs/reports/`).
