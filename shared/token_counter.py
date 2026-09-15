"""Локальная оценка токенов через tiktoken (папка shared/).

DeepSeek использует собственный токенизатор, поэтому кодировка ``cl100k_base``
из tiktoken даёт приблизительное, но стабильное число токенов — этого достаточно
для демонстрации экономии контекста. Кодировка загружается лениво и кэшируется
на процесс, поэтому tiktoken нужен только при первом подсчёте.
"""
from .logging_utils import get_logger

logger = get_logger(__name__)

# Кэш кодировки tiktoken на процесс (лениво, см. get_tokenizer ниже).
_TOKENIZER = None


def get_tokenizer():
    """Возвращает кодировку tiktoken `cl100k_base` (загружается один раз)."""
    global _TOKENIZER
    if _TOKENIZER is None:
        import tiktoken  # локальный импорт: нужен только при подсчёте токенов

        logger.debug("tiktoken: загружаю кодировку cl100k_base")
        _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    return _TOKENIZER


def count_tokens(text: str) -> int:
    """Число токенов текста в кодировке `cl100k_base` (tiktoken).

    Пустой текст = 0 токенов. Подсчёт локальный и приблизительный:
    DeepSeek использует собственный токенизатор, поэтому числа близки к
    фактическим, но не обязаны совпадать с `usage` API.
    """
    if not text:
        return 0
    return len(get_tokenizer().encode(str(text)))
