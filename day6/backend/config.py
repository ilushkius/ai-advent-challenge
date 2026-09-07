"""Конфигурация бэкенда дня 6: URL DeepSeek, дефолты агентов, чтение ключа API.

Ключ DEEPSEEK_API_KEY ищется в следующем порядке (конвенция проекта):
1. файл `.env` в папке дня 6 (day6/backend/config.py -> ../.env);
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

# Таймаут HTTP-вызовов к DeepSeek (секунды).
REQUEST_TIMEOUT = 60.0

# Путь к .env дня 6: этот файл лежит в day6/backend/, значит .env — в day6/.
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
    """Возвращает ключ DeepSeek: day6/.env → переменная окружения → None."""
    key = read_key_from_env_file()
    if key:
        return key
    return os.environ.get("DEEPSEEK_API_KEY") or None
