"""DeepSeek внутри инструмента ``summarize`` сервера обработки данных (день 20).

Ключ берётся из ``day20/.env`` или переменной окружения (``config.resolve_api_key``),
клиент создаётся ЛЕНИВО и живёт в модуле один на процесс: инструмент вызывается из
цепочки оркестрации много раз, а соединение на каждый вызов никто не заводит.

Главное правило модуля: **отсутствие LLM — не ошибка инструмента**. ``available()``
отвечает, можно ли вообще звать модель (режим ``--llm off`` выключает её
принудительно), а ``summarize`` бросает ``LLMUnavailable`` — инструмент ловит его и
переходит на агрегацию (``summarize.aggregate_summary``). Так демо, тесты и прогон
без ключа остаются рабочими, а с ключом дают настоящую сводку.
"""
from __future__ import annotations

from mcp_servers.data_server import config  # первый: он добавляет корень репозитория
from shared.logging_utils import get_logger

logger = get_logger(__name__)

_client = None
_enabled = True
_timeout = config.LLM_TIMEOUT


class LLMUnavailable(RuntimeError):
    """LLM недоступна: нет ключа, режим ``off`` или ошибка вызова."""


def configure(enabled: bool | None = None, timeout: float | None = None) -> None:
    """Режим работы LLM: ``enabled=False`` (``--llm off``) выключает её принудительно."""
    global _enabled, _timeout, _client
    if enabled is not None:
        _enabled = bool(enabled)
        if not _enabled:
            _client = None
    if timeout is not None:
        _timeout = float(timeout)
        _client = None


def available() -> bool:
    """Можно ли звать модель: режим не выключен и ключ найден."""
    if not _enabled:
        return False
    return bool(config.resolve_api_key())


def summarize(prompt: list[dict], *, max_tokens: int = config.LLM_MAX_TOKENS) -> str:
    """Один вызов чата: текст ответа или ``LLMUnavailable`` с понятной причиной."""
    if not _enabled:
        raise LLMUnavailable("LLM выключена режимом --llm off")
    key = config.resolve_api_key()
    if not key:
        raise LLMUnavailable(
            "Ключ DeepSeek не найден: укажите DEEPSEEK_API_KEY в day20/.env "
            "или в переменной окружения"
        )
    try:
        client = _get_client(key)
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=prompt,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 — любой сбой LLM = переход к агрегации
        logger.warning("summarize: вызов DeepSeek не удался: %s", exc)
        raise LLMUnavailable(f"Сбой вызова DeepSeek: {exc}") from exc
    choices = getattr(response, "choices", None) or []
    if not choices or getattr(choices[0], "message", None) is None:
        raise LLMUnavailable("DeepSeek вернул ответ без содержимого")
    text = choices[0].message.content or ""
    if not text.strip():
        raise LLMUnavailable("DeepSeek вернул пустой ответ")
    return text


def _get_client(key: str):
    """Клиент процесса: создаётся при первом обращении и переиспользуется."""
    global _client
    if _client is None:
        from shared.deepseek_client import make_client

        _client = make_client(key, timeout=_timeout)
        logger.debug("summarize: клиент DeepSeek создан (timeout=%s)", _timeout)
    return _client
