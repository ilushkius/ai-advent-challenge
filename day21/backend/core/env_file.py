"""Файл ``.env`` дня: путь, парсер строк ``NAME=VALUE`` и ключ DeepSeek.

Вынесено из ``config`` (день 26), когда конфигурация упёрлась в предел 400 строк:
чтение ``.env`` — отдельная обязанность, у неё нет ни констант дня, ни домена.
Формат тот же, что у общего парсера ``shared.deepseek_utils``: без ``python-dotenv``,
с поддержкой ``export``, комментариев и кавычек; отсутствие файла — не ошибка.

Резолвер ключа (``resolve_api_key``) остаётся в ``config``: он читает окружение дня
и потому вызывается как ``config.resolve_api_key()`` — тесты подменяют его точкой
входа ``config.read_key_from_env_file``, которую ``config`` реэкспортирует отсюда.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from shared.deepseek_utils import read_key_from_env_file as _read_key_from_env_file

#: Путь к .env дня: этот файл лежит в day21/backend/core/, значит .env — в day21/.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

__all__ = ["ENV_FILE", "read_env_value", "read_key_from_env_file"]


def _parse_env_file(path=ENV_FILE) -> Dict[str, str]:
    """Пары ``NAME=VALUE`` файла ``.env``: нет файла — пустой словарь.

    Пропускает пустые строки и комментарии, снимает ``export`` и кавычки. Значения
    не интерпретируются: числа и адреса разбирает тот, кто их читает.
    """
    values: Dict[str, str] = {}
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
                    values[name.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return {}
    return values


def read_env_value(name: str, path=ENV_FILE) -> Optional[str]:
    """Значение переменной из ``.env``; ``None`` — нет файла или нет переменной."""
    return _parse_env_file(path).get(str(name))


def read_key_from_env_file(path=ENV_FILE):
    """Достаёт DEEPSEEK_API_KEY из файла .env (общий парсер без python-dotenv).

    Понимает строки `KEY=VALUE` и `export KEY=VALUE`, пропускает пустые строки и
    комментарии, снимает кавычки со значения. При отсутствии файла — None.
    """
    return _read_key_from_env_file(path)
