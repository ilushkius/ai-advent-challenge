"""Конфигурация бэкенда дня 13: DeepSeek, дефолты агентов, стратегии, память, профиль.

День 12 развивает день 11: к конфигурации добавляются константы профиля
пользователя (``DEFAULT_USER_ID``, границы ``constraints`` и произвольных
инструкций — см. раздел «Профиль пользователя»). Три слоя памяти, стратегии
управления контекстом и дефолты агента остаются из дня 11.

Ключ DEEPSEEK_API_KEY ищется в следующем порядке (конвенция проекта):
1. файл `.env` в папке дня (day13/backend/config.py -> day13/.env);
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

# Персистентное хранилище дня 13: SQLite-файл в папке дня (day13/agents.db).
# Путь считается от этого файла (backend/config.py -> ../), поэтому не зависит
# от рабочей директории запуска. Файл в git не попадает (правило *.db).
DB_PATH = Path(__file__).resolve().parents[1] / "agents.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# Путь к .env дня 13: этот файл лежит в day13/backend/, значит .env — в day13/.
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def read_key_from_env_file(path=ENV_FILE):
    """Достаёт DEEPSEEK_API_KEY из файла .env (общий парсер без python-dotenv).

    Понимает строки `KEY=VALUE` и `export KEY=VALUE`, пропускает пустые строки и
    комментарии, снимает кавычки со значения. При отсутствии файла — None.
    """
    return _read_key_from_env_file(path)


def resolve_api_key():
    """Возвращает ключ DeepSeek: day13/.env → переменная окружения → None."""
    key = read_key_from_env_file()
    if key:
        return key
    return os.environ.get("DEEPSEEK_API_KEY") or None
