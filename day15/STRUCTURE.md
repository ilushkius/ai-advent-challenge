# Структура дня 15

Карта модулей дня 15: что где лежит и за что отвечает. Правила структуры — в
[`../AGENTS.md`](../AGENTS.md) и [`../docs/architecture.md`](../docs/architecture.md).

**Главные правила раскладки.** Любой `.py` ≤ 400 строк (`app.py` ≤ 100,
`backend/api/main.py` ≤ 80). Файл лежит в папке **своего слоя**: конфигурация —
в `core/`, чистые правила — в `domain/`, доступ к БД — в `storage/`, прикладные
сервисы — в `services/`, агент и его менеджер — в `agents/`, ORM — в `models/`,
Pydantic-схемы — в `schemas/`, HTTP — в `api/`. Сваливать файлы в корень
`backend/` нельзя.

День 15 — копия дня 14 (`day14/` не изменяется, это снимок) плюс
**контролируемые переходы состояний задачи**: явный граф допуска
`ALLOWED_TRANSITIONS`, guard-условия на флаги согласования, отказ с объяснением
причины и журнал отклонённых попыток (`task_transitions.accepted`). Агент
дополнительно распознаёт в ответе модели предложение перейти в этап и заменяет
такой ответ отказом, если переход недопустим. Унаследованное сохранено
полностью: инварианты (день 14), состояние задачи как конечный автомат
(день 13), персонализация профилем (день 12), три слоя памяти и четыре стратегии
контекста (день 11).

## Раскладка

```
day15/
├── app.py                    # точка входа Streamlit (58 строк): set_page_config + вызовы секций
├── frontend/                 # Streamlit UI по секциям (11 модулей + __init__.py)
├── backend/                  # FastAPI-бэкенд, домен и доступ к данным
│   ├── __init__.py           # описание пакета + корень репозитория в sys.path (для shared/)
│   ├── api/                  # FastAPI: 6 роутеров по доменам + сборка app (main.py)
│   ├── core/                 # config, dependencies — настройки и доступ к менеджеру
│   ├── domain/               # чистые правила и данные: FSM и граф переходов, стратегии, профиль, инварианты, тексты
│   ├── services/             # прикладные сервисы: compressor, task_state, invariant_checker
│   ├── storage/              # доступ к БД: database, task_store, invariant_store, memory_rows
│   ├── agents/               # Agent, MemoryManager, ProfileStore, AgentManager + миксины
│   ├── models/               # ORM-таблицы SQLAlchemy по доменам
│   ├── schemas/              # Pydantic-схемы API по доменам
│   └── utils/                # своего кода нет (общий — в repo-level shared/)
├── tests/                    # pytest: 1013 тестов (unit/, integration/, e2e/)
├── docs/                     # architecture.md, usage.md, api.md, reports/
├── scripts/                  # прогоны демонстраций и сборка отчётов
│   ├── controlled_transitions_demo.py # правила допуска, пауза в новом процессе, отказ агента
│   ├── transitions_report.py # сборка отчёта контролируемых переходов
│   ├── video_scenario.py     # точка входа прогона: CLI (--all/--auto/--ui/--reset/--serve) и оркестрация
│   ├── video_scenario_checks.py # печать кадров и проверок (VideoChecks) и отчёт о финале
│   ├── video_scenario_client.py # HTTP-клиент прогона и путь БД video_scenario.db
│   ├── video_scenario_frames.py # кадры 0–9 по HTTP: домен, отказ, перезапуск бэкенда, журнал
│   ├── video_scenario_ui.py  # UI-кадры сценария: реальный рендер через streamlit.testing AppTest
│   ├── video_scenario_browser.py # набор действий в браузере: клики, сверки, человеческий темп
│   ├── video_scenario_browser_frames.py # кадры 0–9 в настоящем браузере (Chromium)
│   ├── video_scenario_stand.py # стенд для съёмки: живой Streamlit + браузер + чек-лист кадров
│   ├── video_scenario_server.py # бэкенд прогона на изолированной БД: заглушка DeepSeek и жизненный цикл процесса
│   ├── invariants_demo.py    # три сценария инвариантов → invariants_demo.md (офлайн)
│   ├── seed_invariants.py    # посев демо-инвариантов в БД (--reset/--db)
│   ├── task_state_demo.py    # демонстрация состояния задачи (--all/--phase/--reset)
│   ├── task_demo_report.py   # сборка отчёта демонстрации
│   ├── personalization_comparison.py  # унаследованный прогон отчёта персонализации (день 12)
│   ├── comparison_report.py  # сборка отчёта сравнения профилей
│   └── comparison_stub.py    # офлайн-заглушка (её же используют демо состояния задачи и переходов)
├── invariants_demo.md        # отчёт о трёх сценариях инвариантов (в корне дня — по заданию дня 14)
├── conftest.py, pytest.ini   # конфигурация pytest (pythonpath = . tests)
├── pyproject.toml, uv.lock   # зависимости (uv): прямые — в pyproject, точные версии — в локе
├── .agents/skills/           # AI-скиллы библиотек (uvx library-skills); в этой копии — копии, не симлинки
├── .python-version           # 3.14 (версия для `uv sync`)
├── .env.example              # шаблон ключа DEEPSEEK_API_KEY
└── agents.db                 # SQLite (в .gitignore по *.db)
```

Отчёты прогонов лежат в `docs/reports/`: `controlled_transitions_demo.md` —
новый артефакт дня 15, `task_state_demo.md` и `personalization_comparison.md`
**унаследованы от дня 13**. Отчёт `invariants_demo.md` — в корне дня: путь задан
заданием дня 14, в `docs/reports/` он не дублируется. Скрипты в `scripts/` не
пакет: они находят корень дня (`Path(__file__).resolve().parents[1]`) и добавляют
его в `sys.path` сами, поэтому `uv run python scripts/<script>.py` работает из
любой рабочей директории.

## Слои `backend/`

| Слой | Модули | Назначение |
|---|---|---|
| `core/` | `config.py` (172), `dependencies.py` (53), `__init__.py` (22) | Настройки дня и зависимости роутов: `get_manager`, `agent_or_404`, `task_or_404`, `invariant_or_404` |
| `domain/` | 17 модулей + `__init__.py` (254) | Чистые правила и данные: FSM задачи и сжатия, граф допуска и guards переходов, стратегии, факты, слои памяти, профиль, инварианты, тексты промпта. Знают только stdlib, `core.config` и соседей по слою |
| `storage/` | `database.py` (46), `task_store.py` (278), `invariant_store.py` (255), `memory_rows.py` (47), `__init__.py` (72) | Движок и сессии, ORM-строки → словари, `TaskStateStore` (включая журнал отклонённых попыток), `InvariantManager` |
| `services/` | `compressor.py` (329), `task_state.py` (392), `invariant_checker.py` (296), `__init__.py` (59) | `ContextCompressor`, `TaskStateMachine` (граф, guards, единая точка отказа) и `InvariantChecker`: оркестрация домена и хранилища |
| `agents/` | `agent.py` (1825 ⚠️), `memory.py` (291), `profile_store.py` (292), `agent_manager.py` (85), `manager_*.py` (7 файлов), `__init__.py` (57) | `Agent`, `MemoryManager`, `ProfileStore`, `AgentManager` из миксинов |
| `models/` | `agent.py` (93), `message.py` (41), `context.py` (157), `memory.py` (81), `user_profile.py` (57), `task_state.py` (119), `invariant.py` (51), `__init__.py` (46) | ORM-таблицы SQLAlchemy: `agents`, `short_term_messages`, `summaries`/`token_usage`/`facts`/`checkpoints`, `working_memory`/`long_term_memory`, `user_profiles`, `task_states`/`task_transitions`, `invariants` |
| `schemas/` | `agent.py` (331), `context.py` (218), `memory.py` (173), `profile.py` (170), `task.py` (170), `invariant.py` (149), `__init__.py` (161) | Pydantic-схемы API по доменам, реэкспорт из `schemas/__init__.py` |
| `api/` | `agents.py` (266), `context.py` (140), `memory.py` (180), `profiles.py` (126), `tasks.py` (246), `invariants.py` (139), `main.py` (80), `__init__.py` (15) | 53 эндпоинта по доменам и сборка `app` |
| `utils/` | `__init__.py` (9) | Своего кода нет: общий (клиент DeepSeek, база, токены, логи) — в repo-level `shared/` |

Пакеты `core`, `domain`, `services`, `storage`, `agents`, `models`, `schemas`,
`api` содержат `__init__.py` с реэкспортом публичных имён слоя — это
единственное место, где видно публичный контракт слоя. `api/__init__.py`
намеренно **не** импортирует `main`: `core.dependencies.get_manager` тянет
`api.main` лениво, и ранний импорт создал бы цикл `api → core → api`.

Два импорта отложены намеренно (разрыв циклов `storage ⇄ agents` и
`core ⇄ agents`); поведение от этого не меняется:
`storage/task_store.py` берёт `MemoryManager` внутри свойства `memory_manager`, а
`core/dependencies.py` — `AgentManager` только под `TYPE_CHECKING` (для аннотации).

## Состояние задачи (день 13) — модули и что в них изменил день 15

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/task_fsm.py` | 366 | FSM шагов ВНУТРИ этапа: `TaskStage`/`TaskStep`/`TaskEvent` (`Enum`), классы-этапы с `handle(event, step)`, `STAGE_STEPS`, `InvalidTransitionError`. Таблицы переходов между этапами здесь больше нет — она в `task_state_machine.py` |
| `backend/domain/task_prompt.py` | 190 | Тексты блока состояния для системного промпта: ожидаемые действия, завершённые этапы, допустимые следующие этапы, `render_task_state_block` |
| `backend/domain/task_intent.py` | 89 | Распознавание намерения в реплике (`пауза`/`продолжи`/`откат`/`подтверждаю`) по таблице фраз с приоритетом групп |
| `backend/storage/task_store.py` | 278 | `TaskStateStore`: единственное место работы с таблицами `task_states`/`task_transitions` (чтение, журнал, запись перехода, `log_rejection`, `set_flags`) |
| `backend/services/task_state.py` | 392 | `TaskStateMachine`: публичный контракт переходов (create/pause/resume/advance/rollback/transition_to/set_flags) и единая точка отказа `_reject` |
| `backend/models/task_state.py` | 119 | ORM: `TaskState` (`task_states`, колонка `paused_from_stage`) и `TaskTransition` (`task_transitions`, колонка `accepted`) |
| `backend/agents/manager_tasks.py` | 96 | Миксин `TaskOpsMixin`: тонкие обёртки для API; умолчания шага и действия разрешает сервис |
| `backend/schemas/task.py` | 170 | Схемы API: `TaskStateOut`, `TaskTransitionOut`, `TaskBlockedOut`, `TaskAllowedNextOut`, `TaskFlagsIn`, `TaskCreateIn`, `TaskRollbackIn`, `TaskTransitionIn`, `TaskHistoryOut` |
| `backend/api/tasks.py` | 246 | Роутер: 11 эндпоинтов состояния задачи |
| `frontend/task_panel.py` | 181 | Раздел «🧭 Состояние задачи»: этап, шаг, схема FSM, вкладки журнала; кнопки переходов — в `task_transitions.py` |

Почему `TaskStateMachine` и `TaskStateStore` — разные модули: это граница слоёв
`services/` и `storage/` (та же, что у `ContextCompressor` и `MemoryManager`):
поведение (какие переходы допустимы) отдельно от хранения (сессии SQLAlchemy и
таблицы). Машину читают, не отвлекаясь на ORM; хранилище тестируется без
автомата. Побочный эффект — оба файла укладываются в лимит 400 строк (вместе они
дали бы 670).

## Контролируемые переходы (день 15) — новые модули

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/task_state_machine.py` | 381 | Единственный источник правил допуска: граф `ALLOWED_TRANSITIONS`, `GUARDS` и флаги (`FLAG_PLAN_APPROVED`, `FLAG_IMPLEMENTATION_COMPLETE`, `FLAG_VALIDATION_PASSED`, `STAGE_FLAG`, `TASK_FLAGS`), тексты отказа и подсказки (`transition_explanation`, `transition_error_message`, `transition_hint`, `intent_refusal_notice`), запросы к состоянию (`can_transition`, `is_transition_allowed`, `get_allowed_next_stages`, `get_blocked_stages`, `guard_context`, `cleared_flags`), `STAGE_DISPLAY_ORDER` |
| `backend/domain/task_proposal.py` | 91 | Распознавание предложения модели перейти в этап: `STAGE_PROPOSAL_PHRASES`, `detect_stage_proposal` (при нескольких совпадениях — самый дальний этап) |
| `frontend/task_transitions.py` | 188 | Блок переходов панели задачи: кнопки-этапы с `disabled` и причиной в `help`, «🔒 Заблокированные переходы», «⏭ Следующий шаг», пауза/продолжение с выбором этапа возврата, чекбоксы флагов и «💾 Сохранить флаги». Продолжение в свой этап идёт эндпоинтом `/resume` (сохраняет шаг, как обещает подпись), в другой этап — прямым переходом |
| `scripts/controlled_transitions_demo.py` | 396 | Офлайн-демонстрация в два процесса: недопустимые переходы с причинами, флаги согласования, пауза и продолжение, отказ агента на предложение модели → `docs/reports/controlled_transitions_demo.md` |
| `scripts/transitions_report.py` | 138 | Сборка markdown-отчёта контролируемых переходов |
| `scripts/video_scenario.py` | 275 | Точка входа: CLI (`--all`/`--auto`/`--ui`/`--reset`/`--serve`), оркестрация кадров 0–9 по HTTP (`run`) и в браузере (`run_in_browser`) и один контур отказа (`_guarded`: занятая БД, неготовый бэкенд, невыполненное действие кадра и расхождение проверки — строка «✗ прогон остановлен» и код 1) |
| `scripts/video_scenario_checks.py` | 69 | Печать кадров и проверок: `VideoChecks` (``✓``/``✗`` с доказательством), `ScenarioFailed` — остановка прогона, `summary` — финал с двумя pid и именем БД |
| `scripts/video_scenario_client.py` | 83 | HTTP-клиент прогона (`ApiClient` — те же запросы, что делает фронтенд) и путь БД прогона `video_scenario.db`; конфигурация агента прогона |
| `scripts/video_scenario_browser.py` | 219 | Набор действий в реальном браузере (`BrowserActions`): прокрутка и наведение перед кликом, набор текста по символам, ожидание строки на странице, сверка блокировки кнопок, флаги, темп демонстрации кадров (`--pace` — по умолчанию 2 с на действие, `--typing` — 120 мс на символ: весь прогон 3–4 минуты) |
| `scripts/video_scenario_browser_frames.py` | 267 | Кадры 0–9 в настоящем браузере: класс `Walk(BrowserActions)` и заголовки кадров — что нажать и что должно появиться на экране |
| `scripts/video_scenario_frames.py` | 356 | Кадры 0–9: таблицы домена, проверки по HTTP, перезапуск бэкенда с доказательством двух pid, журнал двух задач |
| `scripts/video_scenario_ui.py` | 386 | UI-кадры кадров 0–9 через `streamlit.testing.v1.AppTest`: реальный рендер `app.py`, нажатия кнопок и чтение карточки, подписей, причин отказа и вкладок журнала |
| `scripts/video_scenario_stand.py` | 148 | Стенд для съёмки (режим `--ui`): поднимает живой `streamlit run app.py` на изолированном бэкенде прогона, открывает адрес в браузере, печатает чек-лист кадров §8 и по Enter доказывает кадр 5 (перезапуск бэкенда, два pid, состояние из SQLite) |
| `scripts/video_scenario_server.py` | 306 | Бэкенд прогона и UI-стенда: офлайн-заглушка DeepSeek, uvicorn на `video_scenario.db` (подмены `main.get_manager`, `database.init_db`, `Agent._make_client`) и жизненный цикл процессов (`Backend`: старт, готовность, pid, остановка; `UiServer`: `streamlit run` и эндпоинт здоровья) |

**Почему прогон кадров — восемь модулей, а не один скрипт.** Прогон делает
разные вещи разными средствами: печатает проверки и останавливается на
расхождении (`video_scenario_checks.py`), ходит в бэкенд по HTTP
(`video_scenario_client.py`), проходит кадры по API (`video_scenario_frames.py`),
рендерит интерфейс без браузера (`video_scenario_ui.py`), ведёт настоящий
браузер (`video_scenario_browser.py` — действия, `video_scenario_browser_frames.py`
— кадры), поднимает стенд для съёмки (`video_scenario_stand.py`) и запускает
процессы бэкенда и Streamlit (`video_scenario_server.py`); точка входа
(`video_scenario.py`) остаётся CLI и оркестрацией. Одним файлом это 2106 строк —
впятеро больше лимита 400 из `AGENTS.md`, а смешивать HTTP, Streamlit, Playwright
и uvicorn в одном модуле значило бы, что дочернему процессу бэкенда импортируется
ещё и AppTest с Chromium.

Отдельная причина, по которой общие части (`checks`, `client`) вынесены из точки
входа: она запускается как ``__main__``, и её импорт по имени (``from
video_scenario import …``) создаёт ВТОРУЮ копию модуля. Исключение из копии не
ловится ``except`` в ``__main__`` — падение печаталось трассировкой вместо строки
«✗ прогон остановлен». Теперь все режимы импортируют один и тот же объект класса.

Границы совпадают с границами исполнения: бэкенд прогона, Streamlit и браузер —
разные процессы у разных режимов, а строгая проверка (`--all`, AppTest), проход в
браузере (`--auto`, Playwright) и стенд (`--ui`, кадры проходит человек) — три
режима с одними и теми же кадрами §8.

**Разделение обязанностей двух модулей домена.** `backend/domain/task_fsm.py`
отвечает на вопрос «что происходит ВНУТРИ этапа»: события
(`advance`/`rollback`/`pause`/`resume`), шаги этапа и явные ошибки на неописанное
событие (`UnknownTaskEvent`, `InvalidTransitionError`). `task_state_machine.py`
отвечает на вопрос «можно ли ПЕРЕЙТИ из этапа в этап»: таблица
`ALLOWED_TRANSITIONS`, guard-условия `GUARDS` и тексты отказа. Поэтому автомат
шагов и проверка графа вызываются подряд: последний шаг `planning` не выпускает
задачу в `execution`, пока не выставлен флаг `plan_approved`, — отказ приходит из
guard, а не из класса этапа. Разделение заодно держит `task_fsm.py` в лимите
400 строк.

## Инварианты (день 14) — новые модули

| Модуль | Строк | Назначение |
|---|---|---|
| `backend/domain/invariant_values.py` | 120 | Значения инварианта: `InvariantCategory`/`InvariantSeverity` (`Enum`), вердикты (`VERDICT_ALLOWED`/`WARNING`/`REFUSAL`), подписи, `category_from_value`/`severity_from_value` (неизвестное → `InvariantValueError`) |
| `backend/domain/invariant_rules.py` | 159 | Детерминированный слой проверки: `DeterministicRule` (gate — признак в описании инварианта, signal — в тексте, exclude — согласие пользователя), `DETERMINISTIC_RULES` (15 правил), `deterministic_violations` |
| `backend/domain/invariant_prompt.py` | 102 | Тексты: блок инвариантов для системного промпта, отказ (`render_violation_refusal`), предупреждение, сообщение для LLM-проверки |
| `backend/domain/demo_invariants.py` | 71 | Четыре демонстрационных правила — по одному на категорию (UI, посев, отчёт) |
| `backend/storage/invariant_store.py` | 255 | `InvariantManager`: единственное место работы с таблицей `invariants` (чтение, CRUD, включение-выключение, проекция в словарь) |
| `backend/services/invariant_checker.py` | 296 | `InvariantChecker`: правила → (при неоднозначности) один вызов LLM; `InvariantCheckResult`/`InvariantViolation`, `merged_with` для объединения вердиктов запроса и ответа |
| `backend/models/invariant.py` | 51 | ORM: `Invariant` (`invariants`) |
| `backend/agents/manager_invariants.py` | 69 | Миксин `InvariantOpsMixin`: CRUD и проверка текста для API |
| `backend/schemas/invariant.py` | 149 | Схемы API: `InvariantIn`, `InvariantUpdateIn`, `InvariantOut`, `InvariantCheckIn`, `InvariantCheckOut`, `InvariantViolationOut` |
| `backend/api/invariants.py` | 139 | Роутер: 6 эндпоинтов инвариантов |
| `frontend/invariant_panel.py` | 254 | Раздел «📏 Инварианты»: таблица, форма создания, правка, включение-выключение, удаление, проверка текста |
| `scripts/seed_invariants.py` | 90 | Посев демо-инвариантов в БД дня (`--reset`, `--db`), идемпотентно, без сети |
| `scripts/invariants_demo.py` | 271 | Три сценария (разрешено / предупреждение / отказ) офлайн, заглушка DeepSeek, LLM-слой выключен → `invariants_demo.md` |

Почему правил два слоя (домен и сервис) и почему проверка не в агенте: правила —
чистые функции над строками (`deterministic_violations` проверяются без БД), а
`InvariantChecker` — прикладная логика (читает таблицу, зовёт LLM, объединяет
вердикты). `Agent` только решает, КОГДА проверять: запрос — до вызова модели
(детерминированно, чтобы не платить за отказ), ответ — после и вместе с LLM-слоем.
Хранилище отдельно от правил по той же границе, что `task_store.py` и
`task_state.py`: `InvariantManager` тестируется без правил, правила — без БД.

Ключевое свойство механизма: инварианты живут в СВОЕЙ таблице, а не в истории
сообщений. Их не «вымывает» сжатие контекста, они одинаковы для всех агентов и
видны в промпте каждого запроса; выключенное правило остаётся в таблице и
возвращается одной кнопкой, не набирая текст заново.

## `frontend/` — интерфейс Streamlit (по секциям)

| Модуль | Строк | Назначение |
|---|---|---|
| `frontend/__init__.py` | 18 | Описание пакета; модули не выполняют `st.*` на импорте |
| `frontend/api_client.py` | 386 | HTTP-транспорт к бэкенду (`requests`), `BACKEND_URL` / `DAY15_BACKEND_URL`, `BackendError`, функции дня 13 (`api_*_task*`), дня 14 (`api_*_invariant*`) и дня 15 (`api_task_allowed_next`, `api_set_task_flags`) |
| `frontend/common.py` | 294 | Подписи (`TASK_STAGE_LABELS`, `TASK_FLAG_LABELS`, `INVARIANT_*_LABELS`), форматтеры, `invariant_notice`, `stage_button_label`, `blocked_reason`, единый путь мутаций панели задачи `run_task_action`, `st.session_state`: init, флеш-сообщения, выбор активного агента |
| `frontend/sidebar.py` | 191 | Боковая панель: агенты, создание агента, стратегия, задача и сессия (`render_sidebar()`) |
| `frontend/chat_section.py` | 288 | Раздел «💬 Чат и память», переключатель четырёх разделов, блок предупреждения/отказа по инвариантам над вводом, сборка страницы (`render_main_area()`) |
| `frontend/context_panels.py` | 324 | Панели контекста: токены, сжатие, сравнение режимов, ветки, факты |
| `frontend/memory_panels.py` | 229 | Панели трёх слоёв памяти, индикатор «что ушло в запрос» |
| `frontend/profile_section.py` | 322 | Раздел «👤 Профиль пользователя»: CRUD профилей, предпросмотр промпта |
| `frontend/profile_comparison.py` | 129 | Сравнение двух профилей на одном вопросе (временные агенты) |
| `frontend/task_panel.py` | 181 | Раздел «🧭 Состояние задачи»: состояние, схема FSM, допустимые этапы, вкладки журнала |
| `frontend/task_transitions.py` | 180 | Блок переходов: кнопки-этапы, причины отказа, флаги согласования, пауза/продолжение (`render_transitions`) |
| `frontend/invariant_panel.py` | 254 | Раздел «📏 Инварианты»: таблица правил, форма, правка, включение-выключение, удаление, проверка текста |

## `backend/api/` — эндпоинты по доменам

| Модуль | Строк | Эндпоинтов | Домен |
|---|---|---|---|
| `backend/api/__init__.py` | 15 | — | Описание пакета и реэкспорт роутеров (без `main`) |
| `backend/api/agents.py` | 266 | 11 | CRUD агентов, генерация, диалог, статистика токенов |
| `backend/api/context.py` | 140 | 9 | Сжатие истории, стратегии, ветки, факты |
| `backend/api/memory.py` | 180 | 10 | Слои памяти (`/memory/short-term`, `/working`, `/long-term`), сессия, задача |
| `backend/api/profiles.py` | 126 | 6 | Профили пользователей `/users...`, `GET /agents/{id}/profile` |
| `backend/api/tasks.py` | 246 | 11 | Состояние задачи: создание, список, чтение, `allowed-next`, журнал, пауза, продолжение, шаг, откат, флаги согласования, переход |
| `backend/api/invariants.py` | 139 | 6 | Инварианты: CRUD правил проекта и проверка текста (`/invariants/check`) |
| `backend/api/main.py` | 80 | — | Сборка `app`: `lifespan`, CORS, `include_router` |

Всего 53 эндпоинта (45 унаследованных дней 1–13 + 6 инвариантов дня 14 +
2 новых дня 15: `GET /tasks/{id}/allowed-next`, `PATCH /tasks/{id}/context`).
Пути внутри роутеров абсолютные, префиксов нет; подключение — в
`backend/api/main.py`. Доступ к менеджеру и 404/409 —
`backend/core/dependencies.py` (`get_manager`, `agent_or_404`, `task_or_404`,
`invariant_or_404`).

## `backend/schemas/` — Pydantic-схемы API, `backend/models/` — ORM

Разделение слоёв: Pydantic-схемы API — в `backend/schemas/` (реэкспорт из
`schemas/__init__.py`, импорт — `from backend.schemas import ...`), ORM-таблицы —
в `backend/models/*.py` (реэкспорт из `backend/storage/database.py`, импорт —
`from backend.storage.database import ...`). Это целевая раскладка `AGENTS.md`:
расхождение дня 12 (схемы в `models/`, ORM в `tables.py`) устранено.

| Схемы (`backend/schemas/`) | Строк | Домен |
|---|---|---|
| `schemas/__init__.py` | 161 | Реэкспорт всех схем (импорт — из `backend.schemas`) |
| `schemas/agent.py` | 331 | Агент, генерация (включая поля `task_state`, `task_intent`, `task_proposal` и `invariants`), метрики использования токенов |
| `schemas/context.py` | 218 | Сжатие истории, стратегии, ветки, факты |
| `schemas/invariant.py` | 149 | Инварианты и результат проверки текста |
| `schemas/memory.py` | 173 | Три слоя памяти агента |
| `schemas/profile.py` | 170 | Профиль пользователя и его вклад в промпт |
| `schemas/task.py` | 170 | Состояние задачи: этап, шаг, переходы, `accepted`, `allowed_next`/`blocked`, флаги согласования, журнал |

| ORM (`backend/models/`) | Строк | Таблицы |
|---|---|---|
| `models/agent.py` | 93 | `agents` (`AgentRecord`) и его `relationship`-связи |
| `models/message.py` | 41 | `short_term_messages` (`ShortTermMessage`) |
| `models/memory.py` | 81 | `working_memory`, `long_term_memory` |
| `models/context.py` | 157 | `summaries`, `token_usage`, `facts`, `checkpoints` |
| `models/user_profile.py` | 57 | `user_profiles` (`UserProfile`) |
| `models/task_state.py` | 119 | `task_states` (`TaskState`, включая колонку `paused_from_stage`), `task_transitions` (`TaskTransition`, включая `accepted`) |
| `models/invariant.py` | 51 | `invariants` (`Invariant`) |
| `models/__init__.py` | 46 | Реэкспорт ORM-классов (импорт из `backend.storage.database`) |

ORM разложен по доменам не из-за лимита строк, а по правилу слоя: файл лежит в
папке своего домена (в дне 12 ради лимита хватало пары `tables.py` +
`tables_task.py`). Строковые имена в `relationship("TaskState", ...)` не
меняются — SQLAlchemy разрешает их по registry, а все модули `models/`
импортируются из `storage/database.py`, поэтому регистрация таблиц та же, что и
до рефакторинга. Таблица `invariants` добавлена днём 14: **12 таблиц** на день
(было 11), при этом `invariants` ни с чем не связана по FK — правила проекта
живут отдельно от агентов и диалога.

## Тесты

`tests/` — 1013 тестов `pytest`, офлайн (временная SQLite + фейк клиента
DeepSeek), разложены по трём подпапкам **по фикстурам**: без БД и агента —
`unit/`, с временной БД и `Agent` — `integration/`, через `TestClient` —
`e2e/`. `tests/conftest.py` и `tests/support.py` остаются в корне `tests/`: на
них опирается `pythonpath = . tests` из `pytest.ini` и импорт
`from support import ...`.

| Подпапка | Файлов | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/` | 13 | 648 | Чистые модули: FSM сжатия и задачи, граф допуска и guards переходов, тексты отказа, распознавание предложения модели, политика сжатия, извлечение фактов, значения профиля, значения/правила/тексты инвариантов |
| `tests/integration/` | 16 | 252 | Хранилище, сервисы и агент на временной БД: `TaskStateStore`/`TaskStateMachine` (включая журнал отказов и флаги согласования), `InvariantManager`/`InvariantChecker`, `MemoryManager`, `ProfileStore`, `ContextCompressor`, `AgentManager` |
| `tests/e2e/` | 7 | 113 | API через `TestClient`: 53 эндпоинта, коды 200/201/400/404/409/422, полный цикл задачи, поля `task_state`/`task_intent`/`task_proposal` и `invariants` в ответе генерации |

Наследованные наборы дня 14 (инварианты) и дни 11–12 (память, персонализация,
сжатие, стратегии) в дне 15 не менялись: при пустой таблице `invariants` проверка
не добавляет вызовов, а задача, не пересекающая границ этапов, ведёт себя как
раньше.

Не менялись — новые файлы дня 14 (подпапка — по фикстурам; тестов в файле):

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_invariant_values.py` | 81 | 17 | `Enum`-значения, списки для API, подписи, тексты ошибок на неизвестное значение |
| `tests/unit/test_invariant_rules.py` | 124 | 28 | Правила-термины по всем 14 средствам, привязка к описанию инварианта, согласие пользователя снимает нарушение, границы слов, форма нарушения |
| `tests/unit/test_invariant_prompt.py` | 150 | 12 | Дословный блок промпта, тексты отказа и предупреждения, сообщение для LLM-проверки |
| `tests/integration/test_invariant_manager.py` | 225 | 24 | CRUD инвариантов, уникальность имени, фильтры, ошибки 404/409/422, независимость от диалога агента |
| `tests/integration/test_invariant_checker.py` | 311 | 21 | Правила → LLM, сбои и мусор от модели, пустой текст, дедупликация и приоритет вердиктов в `merged_with` |
| `tests/integration/test_invariant_agent.py` | 243 | 14 | Блок в системном промпте, отказ без вызова DeepSeek, предупреждение с ответом, пост-проверка ответа, сбой LLM-слоя |
| `tests/e2e/test_invariant_api.py` | 328 | 25 | Шесть эндпоинтов: коды, фильтры, проверка текста, поле `invariants` в генерации, корневой ответ, OpenAPI |

Новые файлы дня 15 (подпапка — по фикстурам; тестов в файле):

| Модуль | Строк | Тестов | Что проверяет |
|---|---|---|---|
| `tests/unit/test_task_state_machine.py` | 334 | 106 | Граф `ALLOWED_TRANSITIONS` (все 25 пар), guards по флагам, `get_allowed_next_stages`/`get_blocked_stages`, `cleared_flags`, `guard_context`, расхождение графа и классов-этапов |
| `tests/unit/test_task_transition_texts.py` | 167 | 114 | Дословные тексты отказа и подсказки для каждой недопустимой пары, длина причины ≤ 200 символов, `intent_refusal_notice` |
| `tests/unit/test_task_proposal.py` | 89 | 49 | Распознавание всех фраз предложения модели, регистр, границы слов, самый дальний этап при нескольких совпадениях, `None` без фраз |
| `tests/integration/test_task_transitions.py` | 204 | 18 | Журнал отклонённых попыток (`accepted = False`), отказ не меняет состояние, флаги через сервис, пауза и продолжение |
| `tests/e2e/test_task_transitions_api.py` | 191 | 7 | Эндпоинты `transition`/`allowed-next`/`context`: 400 с причиной и подсказкой, 422 на пустое тело флагов и неизвестный этап, `accepted: false` в журнале |

Обновлены под новое поведение дня 15 (числа строк и тестов — фактические):

| Модуль | Строк | Тестов | Что изменилось |
|---|---|---|---|
| `tests/unit/test_task_fsm.py` | 340 | 59 | `InvalidTransitionError` вместо `InvalidTaskTransition`, пауза из `done` — ошибка, проверки графа переехали в `test_task_state_machine.py` |
| `tests/unit/test_task_prompt.py` | 230 | 33 | Новый литерал блока с «Допустимые следующие этапы», «нет» при пустом списке |
| `tests/integration/test_task_state.py` | 372 | 39 | Флаги на каждой границе этапов, точные тексты guard-отказов, `set_flags`, сброс флагов при откате |
| `tests/integration/test_task_store.py` | 273 | 13 | `paused_from_stage` в колонке, `accepted` в журнале, `log_rejection` не меняет состояние |
| `tests/integration/test_task_manager.py` | 232 | 15 | `transition_task` без умолчаний на стороне миксина, `set_task_flags` |
| `tests/integration/test_task_agent.py` | 265 | 15 | Уведомление о неприменённом намерении, отказ на предложение модели, блок промпта с допустимыми этапами |
| `tests/e2e/test_task_api.py` | 345 | 27 | 400 с причиной и подсказкой, `allowed-next`, флаги через `PATCH`, `accepted: false` |

Из унаследованных файлов дня 13 не менялся только `tests/unit/test_task_intent.py`
(115 строк, 63 теста): распознавание намерения реплики по таблице фраз с
приоритетом групп и границами слов.

## Что импортируется из `shared/`

| Модуль дня | Импорт | Зачем |
|---|---|---|
| `backend/__init__.py` | — (добавляет корень репозитория в `sys.path`) | Чтобы `from shared...` работал из любого модуля дня |
| `backend/agents/agent.py` | `shared.deepseek_client.make_client`, `shared.token_counter.count_tokens`, `shared.logging_utils.get_logger` | Клиент DeepSeek, подсчёт токенов, логи отказа и неприменимого намерения |
| `backend/core/config.py` | `shared.deepseek_utils.DEEPSEEK_BASE_URL`, `read_key_from_env_file` | Адрес API, чтение `DEEPSEEK_API_KEY` |
| `backend/storage/database.py` | `shared.db_base.Base`, `init_db`, `make_engine`, `make_session_factory` | Движок и сессии SQLite |
| `backend/models/*.py` | `shared.db_base.Base` | База для ORM-классов дня |
| `backend/storage/task_store.py` | `shared.logging_utils.get_logger` | Отладочный лог записанного перехода |
| `backend/storage/invariant_store.py` | `shared.logging_utils.get_logger` | Отладочный лог созданного/изменённого инварианта |
| `backend/services/invariant_checker.py` | `shared.deepseek_client.make_client`, `shared.logging_utils.get_logger` | Клиент для LLM-слоя проверки и лог причины, по которой проверка не выполнена |
| `backend/api/main.py` | `shared.logging_utils.get_logger` | Логгер бэкенда |

Модули `frontend/` обращаются к бэкенду только по HTTP
(`frontend/api_client.py`), поэтому `shared/` напрямую не импортируют.

## Известные расхождения

| Файл | Строк | Лимит | Причина |
|---|---|---|---|
| `backend/agents/agent.py` | 1825 | 400 | Домен `Agent` (память, стратегии, токены, профиль, состояние задачи и переходы, инварианты, генерация) не разложен на миксины — расхождение унаследовано от дней 11–13 (в день 13 было 1603 строки, в день 14 — 1727; +98 дали контролируемые переходы дня 15: отчёт о намерении реплики, проверка предложения модели, уведомление и отказ вместо ответа), рефакторинг `Agent` в день 15 не входил |
| `invariants_demo.md` лежит в корне дня | — | — | Путь задан заданием дня 14; в `docs/reports/` файл не дублируется (там лежат `controlled_transitions_demo.md` дня 15 и унаследованные отчёты дня 13) |
| `done` не пускает никуда | — | — | Терминальность `done` (день 15) — следствие требования «контролируемые переходы»: пауза из `done` отклоняется с объяснением, а не выполняется молча; поведение дня 13, разрешавшее `done → paused`, обновлено вместе с тестами и документацией |
| ORM разложен на 7 модулей `models/*.py` | 41–157 | 400 | Домен один (таблицы дня), но по правилу слоя файл лежит в папке своего домена; заодно снят вопрос лимита, который в дне 12 решался парой `tables.py` + `tables_task.py` |
| `backend/agents/profile_store.py` (292) и `backend/agents/memory.py` (291) | — | — | Имена модулей сохранены (в целевом списке слоя они могли бы называться `profile_manager.py` / `memory_manager.py`) |
| `INVARIANT_LLM_CHECK` добавляет вызов DeepSeek | — | — | По умолчанию проверка ОТВЕТА идёт в LLM, когда детерминированные правила молчат: это осознанная цена семантической проверки, выключается одной строкой в `backend/core/config.py` (так работает офлайн-отчёт `scripts/invariants_demo.py`) |

Лимиты `app.py` (58 ≤ 100) и `backend/api/main.py` (80 ≤ 80) соблюдены.

## Проверка лимита строк

Из папки `day15` (исключены `.venv` и вендорный `.agents/`):

```powershell
uv run python -c "from pathlib import Path; print([(str(p), len(p.read_text(encoding='utf-8').splitlines())) for p in sorted(Path('.').rglob('*.py')) if '.venv' not in p.parts and '.agents' not in p.parts and len(p.read_text(encoding='utf-8').splitlines()) > 400])"
```

Ожидаемый вывод сегодня: `[('backend\\agents\\agent.py', 1825)]`.

Каталог `.agents/` исключён не для красоты: в этой копии скиллы библиотек
скопированы (а не слинкованы), и шаблоны Streamlit внутри них длиннее 400 строк.
Это код библиотеки, а не дня; в дне 14 те же скиллы — симлинки, поэтому `**` в их
содержимое не заходит и команда дня 14 обходится без исключения.
