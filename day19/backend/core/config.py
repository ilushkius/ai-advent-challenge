"""Конфигурация бэкенда дня 17: DeepSeek, дефолты агентов, стратегии, память, профиль.

День 12 развивает день 11: к конфигурации добавляются константы профиля
пользователя (``DEFAULT_USER_ID``, границы ``constraints`` и произвольных
инструкций — см. раздел «Профиль пользователя»). Три слоя памяти, стратегии
управления контекстом и дефолты агента остаются из дня 11.

Ключ DEEPSEEK_API_KEY ищется в следующем порядке (конвенция проекта):
1. файл `.env` в папке дня (day19/backend/core/config.py -> day19/.env);
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
# Новая стратегия агента по умолчанию — «summary» (сжатие истории из дня 9),
# остальные три добавляются днём 11: sliding_window, sticky_facts, branching.
# Список значений — в backend/strategies.py (Enum Strategy), здесь — дефолт и
# диапазон окна для стратегий со «скользящим окном».
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
# Цель подключения по умолчанию — СОБСТВЕННЫЙ MCP-сервер дня 17 (stdio): та же
# строка стоит в поле цели раздела «🔌 MCP» (frontend/mcp_section.DEFAULT_TARGET,
# осознанная копия: frontend не импортирует backend) и в каталоге GET /mcp/servers.
# сервер читает jsonplaceholder.typicode.com и публикует инструменты get_user,
# get_post и list_user_posts.
MCP_DEFAULT_TARGET = "uv run python mcp_server/server.py"
# Серверы официального набора MCP — альтернативы для сравнения (они же в каталоге
# GET /mcp/servers): fetch ставится через uvx (Node не нужен), файловый — через npx.
MCP_FETCH_TARGET = "uvx mcp-server-fetch"
MCP_FILESYSTEM_TARGET = "npx -y @modelcontextprotocol/server-filesystem ."
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
# Пайплайн описывается декларативно (шаги, аргументы, условия перехода), а его
# прогон логируется в таблицы pipeline_runs/pipeline_steps: по ним читается
# история, строится отчёт и видно, какой шаг остановил прогон.
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

# Персистентное хранилище дня: SQLite-файл в папке дня (day19/agents.db).
# Путь считается от этого файла (backend/core/config.py -> ../../), поэтому не
# зависит от рабочей директории запуска. Файл в git не попадает (правило *.db).
DB_PATH = Path(__file__).resolve().parents[2] / "agents.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# Путь к .env дня: этот файл лежит в day19/backend/core/, значит .env — в day19/.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def read_key_from_env_file(path=ENV_FILE):
    """Достаёт DEEPSEEK_API_KEY из файла .env (общий парсер без python-dotenv).

    Понимает строки `KEY=VALUE` и `export KEY=VALUE`, пропускает пустые строки и
    комментарии, снимает кавычки со значения. При отсутствии файла — None.
    """
    return _read_key_from_env_file(path)


def resolve_api_key():
    """Возвращает ключ DeepSeek: day19/.env → переменная окружения → None."""
    key = read_key_from_env_file()
    if key:
        return key
    return os.environ.get("DEEPSEEK_API_KEY") or None
