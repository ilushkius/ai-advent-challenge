"""Конфигурация бэкенда дня 17: DeepSeek, дефолты агентов, стратегии, память, профиль.

День 12 развивает день 11: к конфигурации добавляются константы профиля
пользователя (``DEFAULT_USER_ID``, границы ``constraints`` и произвольных
инструкций — см. раздел «Профиль пользователя»). Три слоя памяти, стратегии
управления контекстом и дефолты агента остаются из дня 11.

Ключ DEEPSEEK_API_KEY ищется в следующем порядке (конвенция проекта):
1. файл `.env` в папке дня (day21/backend/core/config.py -> day21/.env);
2. переменная окружения DEEPSEEK_API_KEY;
3. если нигде нет — `None` (генерация вернёт понятную ошибку без вызова сети).
"""
import os
from pathlib import Path

from shared.deepseek_utils import (
    DEEPSEEK_BASE_URL,
    read_key_from_env_file as _read_key_from_env_file,
)

# Доступные модели DeepSeek (ограничения deepseek-reasoner — см. docs/api.md).
MODEL_CHAT = "deepseek-chat"          # основная модель, по умолчанию
MODEL_REASONER = "deepseek-reasoner"  # может игнорировать temperature

# Дефолты конфигурации нового агента.
DEFAULT_MODEL = MODEL_CHAT
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2048
DEFAULT_SYSTEM_PROMPT = ""

# Диапазоны валидации (используются в Pydantic-схемах models.py).
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0
MAX_TOKENS_MIN = 1
MAX_TOKENS_MAX = 8192

# Лимит контекста модели в токенах — демонстрационный (значения из задания дня 8).
# Реальный контекст DeepSeek (~64K) шире: лимиты сделаны меньше, чтобы переполнение
# было легко показать в учебном демо. Увеличение — правка одной строки ниже.
MODEL_TOKEN_LIMITS = {
    MODEL_CHAT: 8000,       # deepseek-chat
    MODEL_REASONER: 32000,  # deepseek-reasoner
}

# Приблизительные тарифы DeepSeek, $ за 1 млн токенов (вход / выход).
# Используются для расчёта cost в token_usage; актуальные цены — на platform.deepseek.com.
MODEL_PRICES = {
    MODEL_CHAT: {"in": 0.27, "out": 1.10},
    MODEL_REASONER: {"in": 0.55, "out": 2.19},
}

# Таймаут HTTP-вызовов к DeepSeek (секунды).
REQUEST_TIMEOUT = 60.0

# --- Сжатие истории (день 9) -------------------------------------------------
# Дефолты нового агента: сжатие включено, последние 6 реплик идут «как есть»,
# в конспект уходит порция, когда непокрытых реплик накопилось не меньше 10.
DEFAULT_SUMMARY_ENABLED = True
DEFAULT_KEEP_LAST_MESSAGES = 6
DEFAULT_SUMMARIZE_EVERY = 10

# Диапазоны валидации настроек сжатия (Pydantic-схемы models.py).
KEEP_LAST_MIN = 2
KEEP_LAST_MAX = 20
SUMMARIZE_EVERY_MIN = 2
SUMMARIZE_EVERY_MAX = 40

# Суммаризация всегда идёт на этой модели и при низкой температуре: конспект —
# задача извлечения фактов, а не творчества, а deepseek-reasoner может
# игнорировать temperature (поведение провайдера, см. docs/api.md).
SUMMARY_MODEL = MODEL_CHAT
SUMMARY_TEMPERATURE = 0.2
SUMMARY_MAX_TOKENS = 512

# --- Стратегии управления контекстом (день 11) -------------------------------
# Стратегия по умолчанию — «summary»; список значений — в domain/strategies.py,
# здесь — дефолт и диапазон окна для скользящего окна.
DEFAULT_STRATEGY = "summary"
DEFAULT_WINDOW_SIZE = 10

# Диапазоны валидации window_size (Pydantic-схемы models.py).
WINDOW_SIZE_MIN = 2
WINDOW_SIZE_MAX = 50

# --- Слои памяти (день 11) ---------------------------------------------------
# Идентификатор задачи по умолчанию: рабочая память всегда привязана к задаче.
DEFAULT_TASK_ID = "default"
TASK_ID_MAX = 64
SESSION_ID_LENGTH = 8

# Сколько релевантных записей долговременной памяти подставлять в контекст.
LONG_TERM_LIMIT = 5
# Размер страницы по умолчанию для GET /memory/short-term и /memory/working.
SHORT_TERM_API_LIMIT = 50
# Валидация записей памяти.
MEMORY_KEY_MAX = 200
MEMORY_VALUE_MAX = 16000
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0

# --- Профиль пользователя (день 12) -----------------------------------------
# Идентификатор пользователя по умолчанию: если профиль не выбран, агент
# работает без персонализации (пустой профиль не даёт блоков промпта).
DEFAULT_USER_ID = "default"
USER_ID_MAX = 64
PROFILE_NAME_MAX = 100

# Границы полей constraints (Pydantic-схемы models.py + нормализация profiles.py).
MAX_RESPONSE_LENGTH_MIN = 20
MAX_RESPONSE_LENGTH_MAX = 8000
FORBIDDEN_TOPICS_MAX = 20
TOPIC_MAX = 100
DISCLAIMERS_MAX = 20
DISCLAIMER_MAX = 500

# Произвольные инструкции: общий лимит текста (поле Text в SQLite) и границы
# одной инструкции/их числа.
CUSTOM_INSTRUCTIONS_MAX = 4000
INSTRUCTION_MAX = 500
CUSTOM_INSTRUCTIONS_MAX_ITEMS = 30

# --- Состояние задачи (день 13) ---------------------------------------------
# Границы значений полей таблиц task_states/task_transitions; значения этапов и
# шагов — члены Enum из backend/task_fsm.py (валидация — там, здесь только длины).
TASK_STAGE_MAX = 32
TASK_STEP_MAX = 32
EXPECTED_ACTION_MAX = 500
TASK_REASON_MAX = 200

# --- Инварианты (день 14) ----------------------------------------------------
# Границы полей таблицы invariants; категории и важность — члены Enum из
# backend/domain/invariant_values.py (валидация — там, здесь только длины).
INVARIANT_NAME_MAX = 100
INVARIANT_DESCRIPTION_MAX = 2000
INVARIANT_CATEGORY_MAX = 32
INVARIANT_SEVERITY_MAX = 16

# Проверка через LLM: включается, когда детерминированные правила нарушений не
# нашли (семантические случаи — «предложи решение на платном API»). Выключение —
# правка одной строки: тогда проверка идёт только правилами и внешних вызовов не
# добавляет (так работает офлайн-скрипт отчёта scripts/invariants_demo.py).
INVARIANT_LLM_CHECK = True
INVARIANT_CHECK_MAX_TOKENS = 512
INVARIANT_CHECK_TEMPERATURE = 0.0

# --- MCP (день 17) -----------------------------------------------------------
# Цель по умолчанию — свой MCP-сервер дня (stdio); та же строка стоит в разделе
# «🔌 MCP» (frontend/mcp_section.DEFAULT_TARGET — осознанная копия, frontend не
# импортирует backend).
MCP_DEFAULT_TARGET = "uv run python mcp_server/server.py"
# Таймаут подключения и запросов к MCP-серверу (секунды).
MCP_TIMEOUT = 30.0
# Сколько страниц tools/list читать (курсор — часть протокола MCP): защита от
# бесконечной пагинации, если сервер всегда возвращает nextCursor.
MCP_MAX_TOOL_PAGES = 20
# Граница длины цели подключения (Pydantic-схема POST /mcp/connect).
MCP_TARGET_MAX = 500
# Границы вызова инструмента (Pydantic-схема POST /mcp/call): имя инструмента —
# из GET /mcp/tools, аргументы — по input_schema инструмента.
MCP_TOOL_NAME_MAX = 100

# --- Планировщик фоновых задач (день 18) -------------------------------------
# Фон живёт в процессе бэкенда: APScheduler (AsyncIOScheduler) запускается в
# lifespan и останавливается при завершении. Метаданные задач — в SQLite
# (таблица scheduled_tasks), поэтому после перезапуска задачи восстанавливаются.
SCHEDULER_TIMEZONE = "UTC"
# Как часто сверять таблицу scheduled_tasks с задачами APScheduler (секунды):
# задачи, добавленные другим процессом (MCP-сервером через POST /scheduler/tasks),
# подхватываются не позже этого интервала.
SCHEDULER_SYNC_SECONDS = 5
# Сколько секунд «прощается» пропущенный запуск (пока приложение было выключено):
# задача, у которой next_run_at в прошлом, выполняется сразу при восстановлении.
SCHEDULER_MISFIRE_GRACE = 60
# Границы интервала периодических задач (секунды) и задержки напоминания.
SCHEDULE_INTERVAL_MIN = 1
SCHEDULE_INTERVAL_MAX = 86400
# Границы полей таблиц планировщика.
SCHEDULE_NAME_MAX = 100
SCHEDULE_TOOL_MAX = 64
SCHEDULE_VALUE_MAX = 200          # длина cron-строки
REMINDER_TEXT_MAX = 500
NOTIFICATION_TEXT_MAX = 1000
SCHEDULER_LIST_LIMIT = 100        # сколько задач/напоминаний/сводок отдаёт список
SCHEDULER_RUNS_LIMIT = 50         # сколько запусков отдаёт история
# Сбор данных: таймаут и предел тела ответа (защита от гигантского JSON).
COLLECT_TIMEOUT = 10.0
COLLECT_MAX_BYTES = 262144
COLLECT_URL_MAX = 500
# Агрегация сводки: сколько полей и примеров значений попадает в key_metrics.
AGGREGATION_MAX_FIELDS = 30
AGGREGATION_SAMPLES = 5

# --- Композиция MCP-инструментов (день 19) -----------------------------------
# Пайплайн описывается декларативно, прогон логируется в pipeline_runs и
# pipeline_steps: по ним читается история и видно, какой шаг остановил прогон.
#: Длины полей таблиц пайплайна (валидация — в domain/pipeline_spec.py).
PIPELINE_NAME_MAX = 100
PIPELINE_TOOL_MAX = 64
PIPELINE_STATUS_MAX = 16
#: Больше этого числа шагов пайплайн не принимается: длинная цепочка вызовов —
#: это уже не декларация, а программа.
PIPELINE_STEPS_MAX = 10
#: Сколько запусков и сколько шагов отдают списки API.
PIPELINE_RUNS_LIMIT = 50
PIPELINE_STEPS_LIMIT = 100
#: Границы аргументов запуска (Pydantic-схемы backend/schemas/pipeline.py).
PIPELINE_QUERY_MAX = 200
PIPELINE_FILENAME_MAX = 80
PIPELINE_SUMMARY_MAX = 4000
#: Период опроса запуска в интерфейсе (строкой — так его принимает st.fragment).
PIPELINE_POLL_SECONDS = "1s"

# --- Оркестрация MCP-серверов (день 20) ---------------------------------------
# Флот серверов — данные (mcp_servers.json); детали — в day20/STRUCTURE.md.
#: Файл конфигурации флота в корне дня (правится без изменения кода).
MCP_SERVERS_FILE = Path(__file__).resolve().parents[2] / "mcp_servers.json"
#: Рабочий каталог команд флота: путь сервера в конфигурации задан от корня дня,
#: поэтому дочерний процесс запускается из day21/, а не из cwd пользователя.
MCP_FLEET_CWD = str(Path(__file__).resolve().parents[2])
#: Границы полей конфигурации флота (валидация — в domain/mcp_server_spec.py).
MCP_SERVER_NAME_MAX = 64
MCP_SERVER_DESCRIPTION_MAX = 300
MCP_FLEET_TOOLS_MAX = 200
#: Длины полей таблиц оркестрации (валидация — в domain/orchestration_spec.py).
ORCH_QUERY_MAX = 500
ORCH_NAME_MAX = 100
ORCH_STATUS_MAX = 16
ORCH_SERVER_MAX = 64
ORCH_TOOL_MAX = 64
ORCH_STEPS_MAX = 12
#: Сколько запусков и сколько шагов отдают списки API.
ORCH_RUNS_LIMIT = 50
ORCH_STEPS_LIMIT = 100
#: Периоды опроса интерфейса (строками — так их принимает st.fragment).
ORCH_POLL_SECONDS = "1s"
ORCH_HISTORY_SECONDS = "5s"
#: Параметры промпта планировщика плана (services/orchestration_planner.py).
#: Модель здесь не задаётся: её выбирает таблица `LLM_TASK_MODELS` по типу
#: задачи `orchestration` (см. раздел «Оптимизация затрат на LLM» ниже).
ORCH_PLAN_TEMPERATURE = 0.0
ORCH_PLAN_MAX_TOKENS = 800

# --- Индексация документов и поиск (день 21) ----------------------------------
# Документы собираются в documents/, режутся на чанки, эмбеддинги ложатся в FAISS,
# метаданные чанков и журнал прогонов — в SQLite. documents/ и index/ — производные
# данные: их собирает код, в git они не попадают.
#: Папка собранных документов и её манифест (метаданные каждого файла).
DOCUMENTS_DIR = Path(__file__).resolve().parents[2] / "documents"
DOCUMENTS_MANIFEST = DOCUMENTS_DIR / "manifest.json"
#: Векторные индексы и кэш весов модели эмбеддингов.
INDEX_DIR = Path(__file__).resolve().parents[2] / "index"
INDEX_MODELS_DIR = INDEX_DIR / "models"
INDEX_FILES = {
    "fixed": INDEX_DIR / "fixed.index",
    "structural": INDEX_DIR / "structural.index",
}
#: Модель эмбеддингов: мультиязычная MiniLM понимает русский, весит ~470 МБ.
EMBEDDING_MODEL = os.environ.get(
    "DAY21_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
#: Базовый `max_seq_length` этой модели — 128 токенов, и тогда чанк в 512 токенов
#: молча обрезался бы: сравнение стратегий потеряло бы смысл.
EMBEDDING_MAX_SEQ_LENGTH = 512
#: Размер батча эмбеддингов (память против скорости).
EMBEDDING_BATCH_SIZE = 32
#: Параметры чанкинга: окно фиксированной стратегии и перекрытие соседних окон.
CHUNK_SIZE_TOKENS = 512
CHUNK_OVERLAP_TOKENS = 50
#: Секция короче этого числа токенов не становится отдельным чанком (сливается).
CHUNK_MIN_SECTION_TOKENS = 20
#: Сколько попаданий отдают поиск, агент и интерфейс.
INDEX_DEFAULT_TOP_K = 5
INDEX_MAX_TOP_K = 20
INDEX_AGENT_TOP_K = 3
INDEX_AGENT_STRATEGY = "structural"
#: Периоды опроса интерфейса (строками — так их принимает st.fragment).
INDEX_POLL_SECONDS = "1s"
INDEX_HISTORY_SECONDS = "5s"
#: Сколько запусков отдаёт история и сколько примеров чанков — GET /indexing/chunks.
INDEX_RUNS_LIMIT = 20
INDEX_DEFAULT_LIMIT = 5
#: Длины полей таблиц индексации и строки отчёта о поиске агента.
INDEX_SOURCE_MAX = 128
INDEX_TITLE_MAX = 200
INDEX_SECTION_MAX = 200
INDEX_STRATEGY_MAX = 16
INDEX_CHUNK_ID_MAX = 200
INDEX_STATUS_MAX = 16
INDEX_QUERY_MAX = 500

# --- Оптимизация затрат на LLM (день 21) --------------------------------------
# Кэш контекста DeepSeek считает попадание дешевле ввода (цена попадания — доля от
# цены ввода), тип задачи выбирает модель, непиковые часы дают скидку провайдера,
# длина ответа ограничивается под задачу.
#: Цена попадания в кэш как доля цены обычного ввода (DeepSeek: кэш-хит дешевле).
LLM_CACHE_INPUT_RATIO = 0.1
#: Типы задач: ими подписывается каждый запрос в журнале `llm_usage` и по ним
#: выбирается модель и предел длины ответа.
LLM_TASK_CHAT = "chat"                  # ответ агента в диалоге
LLM_TASK_SUMMARY = "summarize"          # конспект истории (сжатие контекста)
LLM_TASK_CLASSIFY = "classify"          # проверка инвариантов, короткие решения
LLM_TASK_KEYWORDS = "keywords"          # извлечение ключевых слов и фактов
LLM_TASK_ORCHESTRATION = "orchestration"  # план шагов по каталогу флота
LLM_TASK_CODE = "code"                  # длинная генерация и рассуждения
LLM_TASK_INDEXING = "indexing"          # тяжёлая пакетная обработка документов
#: Модель под задачу: простые — дешёвая (MODEL_CHAT), сложные — основная
#: (MODEL_REASONER). Список — данные: правка строки меняет маршрутизацию.
LLM_TASK_MODELS = {
    LLM_TASK_CHAT: MODEL_CHAT,
    LLM_TASK_SUMMARY: MODEL_CHAT,
    LLM_TASK_CLASSIFY: MODEL_CHAT,
    LLM_TASK_KEYWORDS: MODEL_CHAT,
    LLM_TASK_ORCHESTRATION: MODEL_REASONER,
    LLM_TASK_CODE: MODEL_REASONER,
    LLM_TASK_INDEXING: MODEL_REASONER,
}
LLM_TASK_DEFAULT = LLM_TASK_CHAT
#: Предел длины ответа по умолчанию и для задач с длинным выводом.
LLM_MAX_RESPONSE_TOKENS = 1000
LLM_MAX_RESPONSE_TOKENS_LONG = 4000
#: Предел по типу задачи: он же уходит в `max_tokens` запроса (но не выше
#: пользовательского лимита агента).
LLM_TASK_MAX_TOKENS = {
    LLM_TASK_CHAT: LLM_MAX_RESPONSE_TOKENS,
    LLM_TASK_SUMMARY: 512,
    LLM_TASK_CLASSIFY: 256,
    LLM_TASK_KEYWORDS: 256,
    LLM_TASK_ORCHESTRATION: 800,
    LLM_TASK_CODE: LLM_MAX_RESPONSE_TOKENS_LONG,
    LLM_TASK_INDEXING: LLM_MAX_RESPONSE_TOKENS_LONG,
}
#: Сколько последних запросов отдаёт журнал расходов и глубина строк таблицы.
LLM_USAGE_LIMIT = 50
LLM_USAGE_MODEL_MAX = 64
LLM_USAGE_TYPE_MAX = 32
LLM_USAGE_AGENT_MAX = 64
#: Периоды агрегации для статистики расходов (дни, за которые считаем).
LLM_USAGE_PERIODS = {"day": 1, "week": 7, "month": 30, "all": 0}
LLM_USAGE_PERIOD_DEFAULT = "week"
#: Планирование тяжёлых задач на непиковые часы DeepSeek (UTC).
#: Непик: будни 00–01, 04–06, 10–24 и все выходные; пик: будни 01–04 и 06–10.
OFF_PEAK_WEEKDAY_HOURS_UTC = ((0, 1), (4, 6), (10, 24))
PEAK_WEEKDAY_HOURS_UTC = ((1, 4), (6, 10))
#: Оценка скидки провайдера на непиковых часах (проценты) — для прогноза экономии.
OFF_PEAK_DISCOUNT_PERCENT = 50
#: Few-shot примеры для стабильного префикса промпта. Пусто по умолчанию:
#: примеры стоят токенов в КАЖДОМ запросе, а задачи дня уже описаны промптом,
#: инвариантами и каталогом инструментов. Непустой текст попадёт в кэшируемый
#: префикс, поэтому после первого запроса будет стоить десятую часть ввода.
PROMPT_EXAMPLES = ""
#: Общие инструкции для стабильного префикса промпта. Пусто по умолчанию:
#: предел длины ответа добавляет сам строитель промптов (одна строка в
#: непустом системном промпте), а всё, что дописано здесь, платится в КАЖДОМ
#: запросе. Слот оставлен, чтобы инструкции задавались данными, а не кодом.
PROMPT_GENERAL_INSTRUCTIONS = ""
#: Предел длины стабильного префикса промпта: он кэшируется целиком, поэтому
#: раздутый префикс дороже, чем кажется.
PROMPT_STABLE_PREFIX_MAX = 6000

# Заголовок и описание FastAPI-приложения (backend/api/main.py).
API_TITLE = "Агенты DeepSeek + индексация документов и RAG — День 23"
API_DESCRIPTION = (
    "FastAPI-бэкенд веб-приложения дня 23: три слоя памяти в SQLite, профиль "
    "пользователя, КОНТРОЛИРУЕМЫЕ ПЕРЕХОДЫ состояния задачи, ИНВАРИАНТЫ, "
    "MCP-ИНСТРУМЕНТЫ своего сервера, ПЛАНИРОВЩИК ФОНОВЫХ ЗАДАЧ (APScheduler), "
    "ДЕКЛАРАТИВНЫЙ ПАЙПЛАЙН, ОРКЕСТРАЦИЯ ФЛОТА из трёх MCP-серверов и "
    "ИНДЕКСАЦИЯ ДОКУМЕНТОВ и РЕЖИМ RAG: две стратегии чанкинга, эмбеддинги "
    "sentence-transformers в FAISS, метаданные чанков в SQLite, сравнение стратегий "
    "и поиск по индексу, ответ по корпусу с контекстом и без него, ПЕРЕФОРМУЛИРОВКА "
    "ЗАПРОСА, РЕРАНКЕР КРОСС-ЭНКОДЕРОМ и ПОРОГ ОТСЕЧЕНИЯ. Эндпоинты: /mcp/... (5), "
    "/mcp/servers/... (3), /scheduler/... (14), /pipelines/... (5), /orchestration/... (6), /indexing/... (9), /rag/... (4)."
)
API_VERSION = "16.0.0"

# Персистентное хранилище дня: SQLite-файл в папке дня (day21/agents.db).
# Путь считается от этого файла (backend/core/config.py -> ../../), поэтому не
# зависит от рабочей директории запуска. Файл в git не попадает (правило *.db).
DB_PATH = Path(__file__).resolve().parents[2] / "agents.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# Путь к .env дня: этот файл лежит в day21/backend/core/, значит .env — в day21/.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def read_key_from_env_file(path=ENV_FILE):
    """Достаёт DEEPSEEK_API_KEY из файла .env (общий парсер без python-dotenv).

    Понимает строки `KEY=VALUE` и `export KEY=VALUE`, пропускает пустые строки и
    комментарии, снимает кавычки со значения. При отсутствии файла — None.
    """
    return _read_key_from_env_file(path)


def resolve_api_key():
    """Возвращает ключ DeepSeek: day21/.env → переменная окружения → None."""
    key = read_key_from_env_file()
    if key:
        return key
    return os.environ.get("DEEPSEEK_API_KEY") or None
