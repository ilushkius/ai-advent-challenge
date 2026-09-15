"""Создание OpenAI-совместимого клиента DeepSeek (папка shared/).

Пакет ``openai`` импортируется лениво, внутри функции: он нужен только при
реальном обращении к API, поэтому импорт модуля остаётся дешёвым. Ключ здесь НЕ
резолвится и ошибки про отсутствующий ключ НЕ бросаются — это дело приложения
дня (в дне 12 ключ проверяет ``Agent._make_client``).
"""
from .deepseek_utils import DEEPSEEK_BASE_URL
from .logging_utils import get_logger

logger = get_logger(__name__)

#: Таймаут HTTP-вызовов к DeepSeek по умолчанию, секунды.
DEFAULT_TIMEOUT = 60.0


def make_client(
    api_key: str,
    base_url: str = DEEPSEEK_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT,
):
    """Создаёт клиент DeepSeek с заданным ключом, адресом и таймаутом."""
    import openai  # локальный импорт: модуль нужен только при реальном вызове

    logger.debug("DeepSeek: создаю клиент %s (timeout=%s)", base_url, timeout)
    return openai.OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
