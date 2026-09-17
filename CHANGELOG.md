# История изменений

Формат записи: **дата — тип — краткое описание**, затем список затронутых
файлов и папок. Типы: `feat` (новая функциональность), `refactor` (изменение
структуры кода), `docs` (документация), `rules` (правила для агента и процесса),
`chore` (прочее: инфраструктура, скиллы, служебные изменения).

## 2026-09-17 — feat — day14: инварианты агента (таблица invariants, InvariantChecker, отказ при нарушении hard)

День 14 — рабочая копия дня 13 плюс **система инвариантов**: правила проекта,
которые агент не имеет права нарушать. Правила хранятся в отдельной таблице
`invariants` (не в истории сообщений — их не вымывает сжатие контекста), блок
активных правил подставляется в системный промпт каждого запроса сразу после роли
агента, а предложение проверяется перед выдачей: сначала детерминированными
правилами (регулярные выражения, без сети), при неоднозначности — одним вызовом
LLM. Нарушение `hard`-инварианта превращается в отказ с именем правила и причиной
(DeepSeek при отказе в запросе не вызывается вовсе), нарушение `soft` — в
предупреждение перед ответом, но решение предлагается. Вердикты запроса и ответа
объединяются (`merged_with`), поэтому нарушение из запроса не теряется за чистым
ответом модели, а одно правило не называется дважды. Проверка текста доступна
отдельно (шесть эндпоинтов `/invariants...` и раздел «📏 Инварианты»). Код дней
1–13 не изменялся.

* `day14/` — новый день целиком (копия `day13/` с заменой токенов `day13`→`day14`):
  `pyproject.toml` (`name = "day14"`), `uv.lock`, `.python-version`, `app.py`,
  `frontend/`, `backend/`, `tests/`, `scripts/`, `docs/`, `README.md`,
  `STRUCTURE.md`, `.agents/skills/` (относительные симлинки, `uvx library-skills`);
* `day14/backend/domain/invariant_values.py`, `invariant_rules.py`,
  `invariant_prompt.py`, `demo_invariants.py` — значения (категории, важность,
  вердикты), детерминированные правила (15 правил: 14 по средствам + платные
  сервисы с исключением «согласие пользователя»), тексты промпта/отказа/предупреждения
  и четыре демо-правила;
* `day14/backend/models/invariant.py`, `day14/backend/storage/invariant_store.py` —
  ORM-таблица `invariants` (12-я таблица дня, без FK) и `InvariantManager` (CRUD,
  фильтры, включение-выключение, ошибки 404/409/422);
* `day14/backend/services/invariant_checker.py` — `InvariantChecker` (правила →
  LLM, строгий JSON-протокол, `note` при сбое) и `InvariantCheckResult` с
  `merged_with`;
* `day14/backend/agents/manager_invariants.py`, `day14/backend/agents/agent.py` —
  миксин `InvariantOpsMixin` и интеграция в `Agent`: блок инвариантов в
  `_system_message`, проверка запроса до вызова DeepSeek, пост-проверка ответа,
  `_refuse_by_invariants`, поле `record["invariants"]`;
* `day14/backend/schemas/invariant.py`, `day14/backend/api/invariants.py`,
  `day14/backend/api/main.py` — схемы, шесть эндпоинтов и сборка приложения
  (версия `8.0.0`, всего 51 эндпоинт);
* `day14/frontend/invariant_panel.py`, `common.py`, `api_client.py`,
  `chat_section.py`, `app.py` — раздел «📏 Инварианты», подписи и
  `invariant_notice`, шесть функций HTTP-клиента, блок предупреждения/отказа над
  полем ввода, четвёртый раздел;
* `day14/scripts/seed_invariants.py`, `day14/scripts/invariants_demo.py` — посев
  демо-правил и офлайн-прогон трёх сценариев;
* `day14/invariants_demo.md` — отчёт: разрешено / предупреждение / отказ, с
  таблицей вызовов модели по сценариям;
* `day14/tests/unit/test_invariant_values.py`, `test_invariant_rules.py`,
  `test_invariant_prompt.py`, `day14/tests/integration/test_invariant_manager.py`,
  `test_invariant_checker.py`, `test_invariant_agent.py`,
  `day14/tests/e2e/test_invariant_api.py` — 141 новый тест;
* `day14/README.md`, `day14/STRUCTURE.md`, `day14/docs/architecture.md`,
  `day14/docs/api.md`, `day14/docs/usage.md` — документация дня (в `usage.md`
  добавлен §8 и сдвинута нумерация §9…§17 вместе со ссылками `§N`);
* `AGENTS.md` — пункт про проверку инвариантов при изменении архитектуры;
* `.omp/config.yml` — `skills.customDirectories: day14/.agents/skills`;
* `CHANGELOG.md` — эта запись.

Проверка: `uv run pytest -q` — **725 passed** (584 унаследованных от дня 13 +
141 новый; унаследованные не правились); `uv sync` и `uv lock --check` — код 0;
`uvx library-skills --check --tool-skill` — код 0; `python -m py_compile` — без
ошибок; лимит строк — превышает только унаследованный `backend/agents/agent.py`
(1727; `app.py` 50 ≤ 100, `backend/api/main.py` 79 ≤ 80); прогон
`scripts/invariants_demo.py` — `allowed` / `warning` / `refusal` (в отказе 0
вызовов DeepSeek); smoke бэкенда без ключа: `POST /agents/{id}/generate` с
запросом про Flask отдаёт отказ, `/invariants/check` — `refusal` на «поднимем
Redis» и `allowed` на чистый текст. Дни 1–13 не изменялись.

## 2026-09-16 — chore — day13: скиллы библиотек через uvx library-skills, верхние границы зависимостей

AI-скиллы библиотек дня теперь отслеживаются версией самой библиотеки.
`uvx library-skills 0.0.19` просканировал зависимости дня и создал в
`day13/.agents/skills/` относительные симлинки на скиллы, лежащие **внутри**
пакетов: `fastapi` → `.venv/Lib/site-packages/fastapi/.agents/skills/fastapi`
(0.141.1) и `developing-with-streamlit` →
`.venv/Lib/site-packages/streamlit/.agents/skills/developing-with-streamlit`
(1.64.0), плюс скопированный скилл самого инструмента
`.agents/skills/library-skills/` (тул-скилл объясняет агенту команды
discover/install/check). Скиллы в Git — симлинки (`mode 120000`, цель
`../../.venv/...`), поэтому при апгрейде библиотеки через `uv` содержимое
обновляется само; `uvx library-skills --check --tool-skill` завершается кодом 0,
дрейфа нет. Заодно у прямых зависимостей `day13` появились верхние границы
(`fastapi>=0.141,<0.142` … `uvicorn[standard]>=0.53,<0.54`; для `0.x` —
следующий минор, для `>=1.0` — следующий мажор): `uv lock` не сдвинул ни одной
версии из 66, `uv sync --locked` и `uv lock --check` — код 0.

* `day13/.agents/skills/` — новый каталог: два симлинка (mode `120000`) и
  скопированный `library-skills/` (`SKILL.md` + `.library-skills.json`);
* `day13/pyproject.toml` — верхние границы у десяти прямых зависимостей;
* `day13/uv.lock` — только `requires-dist`-спекы пакета `day13`, версии пакетов
  не изменились;
* `day13/README.md` — новый раздел «Отслеживание версий библиотек»;
* `day13/STRUCTURE.md` — `.agents/skills/` в дереве дня;
* `AGENTS.md` — подраздел «Скиллы библиотек: uvx library-skills» (правила,
  таблица команд, ограничения) и пункт в `## Definition of Done`;
* `README.md` — упоминание `uvx library-skills` в §1 «Зависимости приложений»;
* `.omp/config.yml` — `skills.customDirectories: day13/.agents/skills`: провайдер
  `agents` ищет `.agents/skills` от `cwd` вверх, поэтому скиллы дня не были
  видны сессии, запущенной из корня репозитория;
* `CHANGELOG.md` — эта запись.

Проверка: `uvx library-skills --check --tool-skill` — код 0 (обе записи
`up to date`); `git ls-files -s day13/.agents/skills` — два `120000` и два
`100644`; `omp read skill://developing-with-streamlit` из корня репозитория
отдаёт `SKILL.md` Streamlit'а; `uv lock --check` — код 0;
`uv run uvicorn backend.api.main:app` + `AppTest` — 32 пути в `/openapi.json`,
0 исключений, 15 кнопок, 3 вкладки; `uv run pytest -q` — **584 passed**.
Дни 1–12 не тронуты.

## 2026-09-16 — chore — day13 переведён на uv (pyproject.toml + uv.lock вместо requirements.txt)

Менеджер зависимостей дня 13 — `uv` вместо `pip`/`venv`: прямые зависимости
объявлены в `pyproject.toml`, точные версии всех 66 разрешённых пакетов
зафиксированы в `uv.lock`, интерпретатор — в `.python-version` (`3.14`). Файл
`requirements.txt` удалён, состав зависимостей сохранён полностью (fastapi,
uvicorn[standard], streamlit, openai, requests, sqlalchemy, tiktoken, httpx,
pytest, pandas). Дни 1–12 не тронуты: они остаются снимками с `requirements.txt`.

* `day13/pyproject.toml`, `day13/uv.lock`, `day13/.python-version` — новые файлы
  (`uv init --no-package` + `uv add -r requirements.txt`); флага `--requirements`
  у `uv init` в uv 0.12.15 нет;
* `day13/requirements.txt` — удалён;
* `day13/README.md` — раздел «Быстрый старт» заменён на «Установка и запуск»
  (`uv sync`, `uv run streamlit run app.py`,
  `uv run uvicorn backend.api.main:app --reload --port 8000`), тесты —
  `uv run pytest -q`, дерево дня обновлено;
* `day13/STRUCTURE.md` — дерево дня и команда замера лимита строк (`uv run python`);
* `day13/docs/usage.md` — §1 переписан на `uv sync`, раздел «Состав
  `requirements.txt`» → «Состав зависимостей», все команды `.venv/Scripts/python …`
  → `uv run …`;
* `day13/docs/architecture.md` — новый раздел «Зависимости (uv)» (три файла, роль
  `uv.lock`, `--no-package`), uv добавлен в описание стека;
* `day13/docs/api.md`, `day13/pytest.ini` — команды запуска через `uv run`;
* `day13/scripts/*.py`, `day13/docs/reports/*.md`, `day13/frontend/task_panel.py` —
  тексты команд в докстрингах, отчётах и комментариях переведены на `uv run`
  (генераторы отчётов печатают те же команды, что и раньше, но в форме uv);
* `README.md` (корень) — установка дня 13 (`uv sync`) и его блок в «Как
  запустить», строка про uv в таблице стека;
* `AGENTS.md` — правило uv для всех дней, инструкция для `day14+` и порядок
  миграции существующего дня, пункт в Definition of Done;
* `.clauderules`, `.gitignore` — снимки `day1`–`day12` оговорены явно; `!uv.lock`
  добавлен в исключения (широкое `*.lock` вырезало лок из Git);
* `.omp/skills/day-docs-structure/SKILL.md`,
  `.omp/skills/tdd-pytest-workflow/SKILL.md` — команды шага установки и запуска
  тестов приведены к uv.

Проверено: `uv sync` (`.venv` под управлением uv), `uv run pytest -q` — 584 passed,
`uv run uvicorn backend.api.main:app` — Swagger `/docs` и 32 эндпоинта из
`openapi.json` отвечают 200, `uv run streamlit run app.py` — страница 200,
`AppTest` без исключений (все разделы дня рисуются).

## 2026-09-16 — refactor — day13: ключи формы «➕ Создать задачу» разведены по разделам

Раздел «🧭 Состояние задачи» падал с `StreamlitDuplicateElementKey` сразу после
создания агента: ключи виджетов Streamlit глобальны для скрипта, и форма
состояния занимала тот же ключ `task_create_form_<agent_id>`, что и форма задачи
слоя памяти в боковой панели (обе рисуются одновременно).

* `day13/frontend/task_panel.py` — форма состояния переименована в
  `task_state_create_<agent_id>`, её виджеты получили явные ключи
  `task_state_new_id_*`, `task_state_stage_*`, `task_state_create_btn_*` (200 → 206
  строк: 3 ключа + комментарий о глобальности ключей);
* `day13/frontend/sidebar.py` не менялся — ключ `task_create_form_<agent_id>`
  остаётся за формой задачи слоя памяти (`api_set_task`).

Проверено пробой `AppTest` + реальный бэкенд: до правки — исключение с ключом
`task_create_form_<agent_id>`, после — оба раздела рисуются, создание состояния
заводит задачу на этапе `planning`; `pytest` дня — 584 passed.

## 2026-09-16 — refactor — day13 разложен по слоям (api, core, models, schemas, services, storage, domain, agents, utils)

`day13/` переразложен без изменения поведения: в корне `backend/` лежали 31
модуль, теперь там только `__init__.py` и девять папок-слоёв. Файл лежит в папке
своего слоя, у каждой папки `__init__.py` с реэкспортом публичных имён.

Перемещения:

* `backend/config.py`, `dependencies.py` → `backend/core/`;
* `backend/strategies.py`, `context_fsm.py`, `context_policy.py`,
  `fact_extractor.py`, `memory_layers.py`, `profiles.py`, `profile_values.py`,
  `demo_profiles.py`, `task_fsm.py`, `task_prompt.py`, `task_intent.py` →
  `backend/domain/`;
* `backend/database.py`, `task_store.py` → `backend/storage/` (+ новый
  `memory_rows.py` — ORM-строки памяти → словари, вынесены из
  `domain/memory_layers.py`, чтобы домен остался без SQLAlchemy);
* `backend/compressor.py`, `task_state.py` → `backend/services/`;
* `backend/agent.py`, `agent_manager.py`, `manager_*.py`, `memory.py`,
  `profile_store.py` → `backend/agents/`;
* Pydantic-схемы `backend/models/*.py` → `backend/schemas/*.py`;
* `backend/tables.py` (393 строки) разложен на `backend/models/{agent,message,memory,context,user_profile}.py`,
  `backend/tables_task.py` → `backend/models/task_state.py`;
* `backend/routers/*.py` → `backend/api/*.py`, `backend/main.py` →
  `backend/api/main.py` (точка запуска — `uvicorn backend.api.main:app --port 8000`);
* `ui/` → `frontend/`, прогоны демонстраций → `scripts/`, отчёты →
  `docs/reports/`, тесты → `tests/unit/`, `tests/integration/`, `tests/e2e/`;
* новый пустой слой `backend/utils/` (свой код дня живёт в `shared/`).

Импорты переписаны по слоям (абсолютные и относительные); два импорта отложены
намеренно, чтобы не замыкать циклы `storage ⇄ agents` и `core ⇄ agents`
(`TaskStateStore.memory_manager`, аннотация `AgentManager` под `TYPE_CHECKING`).
`backend/core/config.py` пересчитан на новый уровень вложенности
(`parents[1]` → `parents[2]`), поэтому `agents.db` и `.env` по-прежнему ищутся в
корне дня; скрипты в `scripts/` сами добавляют корень дня в `sys.path`, а
демо-база и отчёты остались в корне дня и `docs/reports/`.

**Поведение не изменилось: те же 45 эндпоинтов и 584 теста; команда запуска —
`uvicorn backend.api.main:app`.** Проверено: `pytest -q` — 584 passed; openapi
до/после — побайтово одинаково (32 пути, 45 операций, 56 схем); схема БД
до/после — те же 11 таблиц и колонки; набор node-id тестов тот же; E2E-цикл
задачи по API (создание → шаги → пауза → продолжение → откат → завершение →
журнал из 15 переходов) и сохранение состояния после перезапуска бэкенда;
раздел «🧭 Состояние задачи» в браузере (шаг, пауза, продолжение); офлайн-прогоны
`scripts/task_state_demo.py --all --no-api` (5 фаз) и
`scripts/personalization_comparison.py --no-api`. Найденный при проверке UI
дубликат ключа формы (`task_create_form_<agent>` в `task_panel` и `sidebar`) —
баг дня 13, существовавший до рефакторинга, не тронут.

**Затронуто:** `day13/**` (все модули переехали, импорты переписаны;
`backend/__init__.py`, `backend/core/config.py`, `backend/storage/task_store.py`,
`backend/core/dependencies.py`, `backend/domain/memory_layers.py`, `app.py`,
`frontend/__init__.py`, `pytest.ini`, `scripts/*.py`, `docs/reports/*.md`,
`STRUCTURE.md`, `README.md`, `docs/architecture.md`, `docs/usage.md`,
`docs/api.md`), `AGENTS.md` (раздел «Структура дня», лимиты, известные
расхождения), `.omp/skills/fastapi-streamlit-day-structure/SKILL.md`
(раскладка по девяти слоям), `README.md`, `docs/architecture.md`,
`docs/usage.md`, `CHANGELOG.md`.

Код `day1/`–`day12/` не изменялся.

## 2026-09-16 — feat — состояние задачи как конечный автомат (день 13)

Создан `day13/` — копия `day12/` (агент с трёхслойной памятью и профилем
пользователя) плюс **состояние задачи как FSM**. Состояние живёт в SQLite
(таблицы `task_states` и `task_transitions`, всего 11 таблиц) и переживает
перезапуск процесса:

* `backend/task_fsm.py` — этапы (`planning` / `execution` / `validation` /
  `done` / `paused`), шаги внутри этапа (`gather_requirements`, `define_scope`,
  `create_plan`, `implement`, `test_locally`, `review`, `run_tests`,
  `finalize`), события (`advance` / `rollback` / `pause` / `resume`), паттерн
  State и явные ошибки `UnknownTaskEvent` / `InvalidTaskTransition`.
* `backend/task_store.py` — `TaskStateStore`: единственное место работы с
  таблицами состояния задачи (журнал переходов, снимок рабочей памяти);
  `backend/task_state.py` — `TaskStateMachine`: переходы и валидация. Домен
  разложен на два модуля: вместе они дали бы 441 строку при лимите 400.
* `backend/task_prompt.py` — блок состояния в системном промпте: добавляется
  **последним** (после профиля, рабочей и долговременной памяти, конспекта и
  фактов) в системное сообщение каждого запроса — этап, шаг, ожидаемое
  действие, перечень завершённых этапов.
* `backend/task_intent.py` — авто-обновление состояния по реплике пользователя
  (`пауза` → `pause`, `продолжи` → `resume`, `откат` → `rollback`,
  `подтверждаю` → `advance`) с приоритетом групп и совпадением на границе
  слова; применяется до сборки контекста, поэтому блок в промпте того же
  запроса уже описывает новое состояние. Недопустимое намерение не роняет
  диалог — пишется в лог.
* Девять эндпоинтов (`backend/routers/tasks.py`): `POST /agents/{id}/tasks`,
  `GET /agents/{id}/tasks`, `GET /tasks/{id}/state`, `GET /tasks/{id}/history`,
  `POST /tasks/{id}/pause|resume|advance|rollback|transition`; всего 45
  эндпоинтов, версия приложения — `7.0.0`. Недопустимый переход — 400,
  повторная задача — 409, неизвестная — 404.
* Раздел «🧭 Состояние задачи» в UI (`ui/task_panel.py`): этап, шаг, ожидаемое
  действие, ASCII-схема переходов, кнопки «Пауза» / «Продолжить» / «Следующий
  шаг» / «Откат на предыдущий этап» / «Завершить задачу», журнал переходов.
* Отчёт `day13/task_state_demo.md`: пять фаз, каждая в отдельном процессе, —
  доказательство «пауза → перезапуск → продолжение с того же места».

Тесты: **584** (+270 к дню 12) — FSM, промпт состояния, распознавание
намерения, хранение, менеджер, агент, API. `day13/backend/agent.py`
(1597 строк) превышает лимит 400 — расхождение унаследовано от дня 12.

**Затронуто:** `day13/**` (новые: `backend/task_fsm.py`, `backend/task_prompt.py`,
`backend/task_intent.py`, `backend/task_store.py`, `backend/task_state.py`,
`backend/tables_task.py`, `backend/manager_tasks.py`, `backend/models/task.py`,
`backend/routers/tasks.py`, `ui/task_panel.py`, `task_state_demo.py`,
`task_demo_report.py`, `tests/test_task_*.py`; изменённые: `backend/agent.py`,
`backend/tables.py`, `backend/database.py`, `backend/config.py`,
`backend/main.py`, `backend/models/agent.py`, `backend/models/__init__.py`,
`backend/manager_agents.py`, `backend/dependencies.py`,
`backend/routers/agents.py`, `app.py`, `ui/api_client.py`, `ui/common.py`,
`ui/chat_section.py`, `tests/support.py`, `tests/conftest.py`,
`day13/STRUCTURE.md`, `day13/README.md`, `day13/docs/**`), `README.md`,
`docs/architecture.md`, `docs/usage.md`, `CHANGELOG.md`.

Код `day1/`–`day12/` не изменялся.

## 2026-09-16 — chore — процедурные правила вынесены в скиллы omp.sh

Создана система проектных скиллов в `.omp/skills/`; `AGENTS.md` сокращён —
дублирующиеся разделы заменены ссылками на скиллы. Скиллы:
`python-fsm-agent` (правила FSM, вынесены из `AGENTS.md`; отдельного файла скилла
до этого не существовало), `fastapi-streamlit-day-structure` (раскладка файлов
дня и лимиты 400/100/80 строк), `shared-modules-usage` (работа с `shared/` и его
подключение), `tdd-pytest-workflow` (TDD и `pytest`), `day-docs-structure`
(README/STRUCTURE/CHANGELOG дня). Видимость скиллов проверена запуском omp.sh:
свежая сессия видит все пять, `skill://<name>` отдаёт тело.

**Затронуто:** `.omp/skills/python-fsm-agent/SKILL.md`,
`.omp/skills/fastapi-streamlit-day-structure/SKILL.md`,
`.omp/skills/shared-modules-usage/SKILL.md`,
`.omp/skills/tdd-pytest-workflow/SKILL.md`,
`.omp/skills/day-docs-structure/SKILL.md` (новые), `AGENTS.md`, `README.md`,
`CHANGELOG.md`. Код в `dayN/` и `.clauderules` не менялись.

## 2026-09-15 — docs — документация приведена в соответствие с рефакторингом дня 12

Описана модульная структура дня 12 и общий пакет `shared/`: разделы про
структуру проекта, правила разработки и общие модули в корневом README, новые
`docs/architecture.md` и `docs/usage.md`, карта модулей дня 12, исправлены
ссылки на монолитные `backend/models.py` и `backend/main.py` в документации дня.

**Затронуто:** `README.md`, `docs/architecture.md` (новый), `docs/usage.md`
(новый), `CHANGELOG.md` (новый), `day12/STRUCTURE.md` (новый),
`day12/README.md`, `day12/docs/architecture.md`, `day12/docs/usage.md`,
`day12/docs/api.md`, `AGENTS.md`. Код в `dayN/` не менялся.

## 2026-09-15 — rules — правила структуры файлов и модулей в `AGENTS.md`

В `AGENTS.md` добавлены разделы «Структура файлов» (лимит 400 строк на `.py`,
`app.py` ≤ 100, `backend/main.py` ≤ 80, раскладка `ui/` · `backend/routers/` ·
`backend/models/` · `backend/schemas/` · `shared/`), «Запрещено», «Обязательно»
(`STRUCTURE.md` дня, Plan Mode, проверка лимитов) и «Известные расхождения со
снимками»; в `Definition of Done` — два пункта про лимиты и `STRUCTURE.md`.

**Затронуто:** `AGENTS.md` (коммит `024e6a7`). Существующие правила не
изменялись — только дополнены.

## 2026-09-15 — refactor — модульная структура дня 12 и общий пакет `shared/`

Приложение дня 12 разложено по модулям, общий код вынесен в `shared/`:

* `app.py` — 1852 строки → 40 (только точка входа); интерфейс вынесен в пакет
  `ui/` из 8 модулей по секциям: `api_client`, `common`, `sidebar`,
  `chat_section`, `context_panels`, `memory_panels`, `profile_section`,
  `profile_comparison`.
* `backend/main.py` — 660 строк → 84 (только сборка `app` и `include_router`);
  эндпоинты разложены по роутерам `backend/routers/` (`agents`, `context`,
  `memory`, `profiles` — 36 эндпоинтов), зависимости API-слоя — в
  `backend/dependencies.py`.
* `backend/models.py` (845 строк) → пакет `backend/models/` с Pydantic-схемами по
  доменам (`agent`, `context`, `memory`, `profile`) и реэкспортом из
  `models/__init__.py`; ORM-таблицы вынесены в `backend/tables.py`, а
  `backend/database.py` стал тонким слоем над `shared/db_base.py`.
* `backend/agent_manager.py` — 637 строк → 71 (синглтон); методы разложены по
  миксинам `backend/manager_agents.py`, `manager_context.py`, `manager_memory.py`,
  `manager_profiles.py`, `manager_usage.py`.
* `backend/profiles.py` — 343 строки → 204, значения профиля вынесены в
  `backend/profile_values.py`; `backend/memory.py` дополнен
  `backend/memory_layers.py`; отчётные скрипты — `comparison_report.py`,
  `comparison_stub.py`, `personalization_comparison.py` (364 → 108 строк).
* Создан общий пакет `shared/` с кодом, не меняющимся между днями:
  `deepseek_client.py`, `db_base.py`, `token_counter.py`, `logging_utils.py`
  (`deepseek_utils.py` существовал ранее).

**Затронуто:** `day12/app.py`, `day12/ui/**` (новый), `day12/backend/**`
(`main.py`, `dependencies.py` (новый), `routers/**` (новый), `models/**`
(новый), `tables.py` (новый), `manager_*.py` (новые), `database.py`,
`agent_manager.py`, `agent.py`, `config.py`, `memory.py`, `memory_layers.py`,
`profiles.py`, `profile_values.py`, `models.py` (удалён — заменён пакетом),
`day12/comparison_report.py`, `day12/comparison_stub.py`,
`day12/personalization_comparison.py`), `shared/db_base.py`,
`shared/deepseek_client.py`, `shared/token_counter.py`,
`shared/logging_utils.py` (коммит `9c7021c`, 40 файлов).
