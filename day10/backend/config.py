"""Конфигурация бэкенда дня 10: DeepSeek, дефолты агентов, стратегии контекста.

День 10 развивает день 9: к сжатию истории добавляются три новые стратегии
управления контекстом (sliding_window, sticky_facts, branching) и переключатель
между ними. Здесь — их дефолты (``DEFAULT_STRATEGY``, ``DEFAULT_WINDOW_SIZE``)
и диапазон ``window_size``.

Ключ DEEPSEEK_API_KEY ищется в следующем порядке (конвенция проекта):
1. файл `.env` в папке дня (day10/backend/config.py -> day10/.env);
2. переменная окружения DEEPSEEK_API_KEY;
3. если нигде нет — `None` (генерация вернёт понятную ошибку без вызова сети).
"""
import os
from pathlib import Path

# Официальный endpoint DeepSeek (OpenAI-совместимый Chat Completions).
# ВАЖНО: корректный адрес — https://api.deepseek.com (с поддоменом "api."),
# адрес https://deepseek.com без "api." не принимает API-запросы.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

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

# --- Стратегии управления контекстом (день 10) -------------------------------
# Новая стратегия агента по умолчанию — «summary» (сжатие истории из дня 9),
# остальные три добавляются днём 10: sliding_window, sticky_facts, branching.
# Список значений — в backend/strategies.py (Enum Strategy), здесь — дефолт и
# диапазон окна для стратегий со «скользящим окном».
DEFAULT_STRATEGY = "summary"
DEFAULT_WINDOW_SIZE = 10

# Диапазоны валидации window_size (Pydantic-схемы models.py).
WINDOW_SIZE_MIN = 2
WINDOW_SIZE_MAX = 50

# Персистентное хранилище дня 10: SQLite-файл в папке дня (day10/agents.db).
# Путь считается от этого файла (backend/config.py -> ../), поэтому не зависит
# от рабочей директории запуска. Файл в git не попадает (правило *.db).
DB_PATH = Path(__file__).resolve().parents[1] / "agents.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# Путь к .env дня 10: этот файл лежит в day10/backend/, значит .env — в day10/.
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def read_key_from_env_file(path=ENV_FILE):
    """Достаёт DEEPSEEK_API_KEY из файла .env (локальный парсер, без python-dotenv).

    Понимает строки `KEY=VALUE` и `export KEY=VALUE`, пропускает пустые строки и
    комментарии, снимает кавычки со значения. При отсутствии файла — None.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" in line:
                    name, value = line.split("=", 1)
                    if name.strip() == "DEEPSEEK_API_KEY":
                        return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def resolve_api_key():
    """Возвращает ключ DeepSeek: day9/.env → переменная окружения → None."""
    key = read_key_from_env_file()
    if key:
        return key
    return os.environ.get("DEEPSEEK_API_KEY") or None
