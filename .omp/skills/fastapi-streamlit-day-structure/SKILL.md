---
name: fastapi-streamlit-day-structure
description: "File layout and size limits for new FastAPI + Streamlit days in the ai-challenge project. Use this whenever creating a new day app (day13+), refactoring a monolithic day into modules, splitting large files (over 400 lines), or structuring backend/ui/shared directories. Triggers: new day, create day app, refactor day, split file, restructure backend, file layout, 400 lines limit."
---

# Раскладка файлов дня (FastAPI + Streamlit)

Правила целевые: для новых дней (`day13/` и далее) и для кода, который осознанно
рефакторится. Снимки прошлых дней под них не переписываются (см. `AGENTS.md`,
раздел «Известные расхождения со снимками»).

## Раскладка

- `app.py` — **только точка входа (≤ 100 строк):** `st.set_page_config`,
  инициализация состояния и вызовы секций. Логики панелей, запросов и
  форматирования в `app.py` нет.
- `ui/` — Streamlit UI по секциям: `ui/sidebar.py` (боковая панель),
  `ui/chat_section.py` (основная область), `ui/memory_panels.py` (панели слоёв
  памяти), `ui/profile_section.py` (раздел «Профиль пользователя»),
  `ui/api_client.py` (HTTP-клиент к бэкенду), `ui/common.py` (подписи,
  форматтеры, состояние страницы).
  Не влезает в 400 строк или распадается на два домена — рядом кладётся ещё один
  модуль `ui/<domain>.py` (в `day12/` так появились `ui/common.py`,
  `ui/context_panels.py`, `ui/profile_comparison.py`).
- `backend/routers/` — FastAPI по доменам: `agents.py`, `memory.py`,
  `profiles.py`, `context.py`. Эндпоинт лежит в файле своего домена; пути внутри
  роутеров абсолютные (`/agents/...`), префиксы не вводятся.
- `backend/models/` — Pydantic-схемы API по доменам (те же имена:
  `agent.py`, `context.py`, `memory.py`, `profile.py`), реэкспорт всех имён через
  `models/__init__.py`, чтобы остальной код импортировал схемы из одного места.
- `backend/tables.py` — SQLAlchemy ORM-таблицы.

**Развод по именам (ORM и схемы API не в одном файле-свалке):**

- цель — ORM-таблицы (`agent.py`, `memory.py`, `profile.py`, `context.py`) в
  `backend/models/`, а Pydantic-схемы API — в `backend/schemas/` с реэкспортом из
  `schemas/__init__.py`;
- вариант, применённый в `day12/` — Pydantic-схемы занимают `backend/models/`, а
  ORM-таблицы вынесены в `backend/tables.py` (реэкспорт через
  `backend/database.py`). Выбор фиксируется в `STRUCTURE.md` дня; расхождение с
  целью отмечено в `AGENTS.md`, раздел «Известные расхождения со снимками».
- `backend/config.py` — настройки и дефолты (URL/модели, лимиты, цены, пути БД и
  `.env`).
- `backend/dependencies.py` — зависимости роутов: `get_manager`, `agent_or_404`.
- `backend/manager_<domain>.py` — миксины `AgentManager` по доменам; крупный класс
  менеджера собирается из них, а не растёт одним файлом.
- `backend/main.py` — **только сборка `app` (≤ 80 строк):** `FastAPI(...)`, CORS,
  `lifespan`, `include_router(...)`.

## Лимиты

- Любой `.py` — **≤ 400 строк**. Файл подошёл к ~350 строкам — уже дели на модули
  по доменам, не дожидаясь 401-й строки.
- `app.py` ≤ 100 строк, `backend/main.py` ≤ 80 строк.

Команда проверки лимита строк (из папки дня, PowerShell; `.venv` исключён):

```powershell
.venv\Scripts\python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

## Запреты

- Складывать всю логику в один файл, если он превышает 400 строк.
- Создавать `utils.py` / `helpers.py` без чёткой доменной принадлежности — вместо
  этого `shared/<domain>.py` (или `<пакет>/<domain>.py`, если код относится к
  одному домену дня).

## Правила работы

- **Новая сущность** — сразу определить её домен и положить в соответствующий
  модуль (`ui/`, `backend/routers/`, `backend/models/`, `backend/tables.py`,
  `shared/`), а не в «ближайший» файл.
- **Перед началом работы** посмотреть структуру `dayN-1/` и переиспользовать её
  паттерны: имена модулей, слои, конвенции тестов.
- **При конфликте** «паттерн `dayN-1/`» и «правила структуры» приоритет у правил
  структуры: паттерн повторяем, раскладку файлов делаем по правилам, а
  расхождение отмечаем в `STRUCTURE.md` нового дня.

## Эталон

`day12/` — полная карта модулей и их назначение в `day12/STRUCTURE.md`.
