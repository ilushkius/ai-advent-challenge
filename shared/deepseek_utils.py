"""
============================================================
 Общие утилиты AI-челленджа (папка shared/)
============================================================

Сюда вынесен код, который раньше дублировался в приложениях каждого дня
(day2/app.py, day3/app.py и далее):

* DEEPSEEK_BASE_URL      — корректный endpoint DeepSeek (OpenAI-совместимый);
* read_key_from_env_file — чтение DEEPSEEK_API_KEY из файла .env;
* parse_stop_sequences   — разбор stop-строк из UI ("А, Б" -> ["А", "Б"]);
* usage_to_dict          — объект Usage от OpenAI SDK -> обычный dict.

Пакет лежит в корне репозитория, поэтому приложение дня подключает его так:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from shared.deepseek_utils import (...)
"""

# Официальный endpoint DeepSeek (синтаксис полностью совместим с OpenAI SDK).
# ВАЖНО: корректный адрес — https://api.deepseek.com (с поддоменом "api").
# Адрес "https://deepseek.com" без "api." не принимает API-запросы.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def read_key_from_env_file(path=".env"):
    """Достаёт DEEPSEEK_API_KEY из файла .env."""
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


def parse_stop_sequences(raw):
    """'КРИТИКА, Конец' -> ['КРИТИКА', 'Конец'] (убираем пробелы и пустые элементы)."""
    if not raw or not raw.strip():
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def usage_to_dict(usage):
    """Объект Usage от OpenAI SDK -> обычный dict для session_state и лога."""
    if usage is None:
        return {}
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }
