"""Служба удалённой LLM (день 30): пять шагов демо и общий клиентский счётчик частоты.

Интерфейс прогоняет демо отдельными HTTP-запросами по шагам, а не одним длинным
вызовом: только так прогресс-бар отражает реальный ход, а на медленной модели в
Colab видно, какой именно шаг ждёт. Из этого следует главное решение службы —
клиенты живут в реестре по настройкам (``_clients``): счётчик частоты обязан
пережить отдельные запросы шагов, иначе каждый шаг начинался бы с чистой минуты и
шаг про 429 не сработал бы никогда.

Ошибку шага служба НЕ выбрасывает, а кладёт строкой в таблицу (``status="error"`` и
текст причины в поле ответа): недоступный туннель должен показать, на каком шаге
прогон оборвался, а не заменить всю таблицу одной красной плашкой. Исключение —
пустой адрес: это ошибка настройки, и её видно до первого запроса.
"""
from __future__ import annotations

import time
from typing import Optional

from shared.logging_utils import get_logger

from ..core import config
from ..domain import llm_provider
from ..domain.remote_demo import (DEMO_STEPS, STEP_CONNECTION, STEP_KEYS,
                                  STEP_RATE_LIMIT, step_question, step_title,
                                  summarize_rows)
from . import llm_factory
from .remote_llm_client import (RateLimitExceeded, RemoteLLMClient, RemoteLLMError,
                                RemoteSettings)

logger = get_logger(__name__)

__all__ = ["DEMO_STEPS", "STEP_KEYS", "check_connection", "get_client",
           "max_tokens_for", "reset_client_cache", "run_step", "step_question",
           "step_title", "summarize"]

#: Роль для трёх вопросов демо: короткий ответ нужен, чтобы таблица читалась.
DEMO_SYSTEM = "Ты — ассистент демонстрации. Отвечай кратко и по делу."
#: Промпт шага про частоту: ответ в одно слово, поэтому совсем короткий предел.
RATE_LIMIT_PROMPT = "Ответь одним словом: ок"
RATE_LIMIT_MAX_TOKENS = 4

#: Сводка по строкам прогона — арифметика домена, здесь под общим с интерфейсом именем.
summarize = summarize_rows

#: Реестр клиентов: ключ — настройки. Один клиент на настройки значит один счётчик
#: частоты на все шаги прогона (см. модульный докстринг).
_clients: dict[tuple, RemoteLLMClient] = {}


def get_client(settings: Optional[RemoteSettings] = None) -> RemoteLLMClient:
    """Клиент удалённой модели для этих настроек (``None`` — значения ``.env``).

    Клиент собирается фабрикой провайдеров, а не напрямую: путь ``provider=remote``
    тот же, что у остальных провайдеров, и его проверяет отдельный тест фабрики.
    """
    settings = settings or RemoteSettings.from_config()
    key = (settings.base_url, settings.model, settings.api_key, settings.rate_limit,
           settings.max_context, settings.timeout)
    client = _clients.get(key)
    if client is None:
        client = llm_factory.get_llm_client(llm_provider.PROVIDER_REMOTE,
                                           remote_settings=settings)
        _clients[key] = client
    return client


def reset_client_cache() -> None:
    """Забыть клиентов: тесты и смена настроек не должны тянуть чужой счётчик."""
    _clients.clear()


def max_tokens_for(key: str) -> int:
    """Предел ответа шага: у кода он выше, чем у вопроса про столицу."""
    limits = config.REMOTE_LLM_DEMO_MAX_TOKENS
    return int(limits.get(key, config.LLM_MAX_RESPONSE_TOKENS))


# ---------- шаги ----------
def check_connection(settings: Optional[RemoteSettings] = None,
                     client: Optional[RemoteLLMClient] = None) -> dict:
    """``GET /models``: результат проверки связи строкой для индикатора интерфейса.

    Счётчик частоты не расходуется: проверка связи — не вызов модели.
    """
    client = client or get_client(settings)
    started = time.perf_counter()
    try:
        data = client.list_models()
    except RemoteLLMError as exc:
        logger.warning("Проверка связи с удалённой моделью не прошла: %s", exc)
        return {"ok": False, "message": str(exc), "models": [], "count": 0,
                "url": client.base_url, "model": client.model,
                "duration_ms": _ms(started),
                "rate_limit": client.rate_limit_state()}
    models = list(data.get("models") or [])
    return {"ok": True,
            "message": f"✅ Соединение установлено, доступно {len(models)} моделей",
            "models": models, "count": len(models), "url": client.base_url,
            "model": client.model, "duration_ms": _ms(started),
            "rate_limit": client.rate_limit_state()}


def run_step(key: str, settings: Optional[RemoteSettings] = None, reset: bool = False,
             client: Optional[RemoteLLMClient] = None) -> dict:
    """Один шаг демо строкой таблицы: ошибка шага не рушит прогон.

    ``reset`` очищает счётчик частоты перед шагом — интерфейс передаёт его на первом
    шаге прогона, чтобы предыдущий прогон не съедал бюджет минуты.
    """
    client = client or get_client(settings)
    if reset:
        client.reset_rate_limit()
    if key == STEP_CONNECTION:
        return _connection_row(client)
    if key == STEP_RATE_LIMIT:
        return _rate_limit_row(client)
    return _ask_row(client, key)


def _connection_row(client: RemoteLLMClient) -> dict:
    """Строка шага 1: имя эндпоинта в поле вопроса, результат — в ответе."""
    result = check_connection(client=client)
    names = ", ".join(result["models"][:5])
    answer = result["message"] + (f": {names}" if names else "")
    return _row(STEP_CONNECTION, step_question(STEP_CONNECTION), answer,
                result["duration_ms"], "ok" if result["ok"] else "error",
                model=result["model"], calls=0, models=result["models"],
                rate_limit=result["rate_limit"])


def _ask_row(client: RemoteLLMClient, key: str) -> dict:
    """Строка шага с вопросом к модели: вопрос, ответ, время, токены."""
    question = step_question(key)
    started = time.perf_counter()
    try:
        result = client.generate_with_context(system=DEMO_SYSTEM, context="",
                                              question=question,
                                              max_tokens=max_tokens_for(key))
    except RemoteLLMError as exc:
        return _row(key, question, str(exc), _ms(started), "error",
                    model=client.model, calls=0)
    return _row(key, question, result["answer"], int(result["duration_ms"]), "ok",
                model=result["model"], calls=1, tokens=result["tokens"],
                rate_limit=result.get("rate_limit"))


def _rate_limit_row(client: RemoteLLMClient) -> dict:
    """Строка шага 5: N запросов проходят, N+1 отклоняет клиентский счётчик.

    Счётчик начинается заново: три вопроса демо уже потратили часть минуты, и без
    сброса отказ наступил бы на (N-2)-м запросе шага — в таблице было бы «лимит N»,
    а отказ после семи запросов. Со сбросом строка означает ровно то, что обещает
    подпись: N запросов прошли, N+1 отклонён.

    Шаг отправляет запросы по одному и останавливается на первом отказе — так в
    таблице видно и сколько запросов реально ушло, и текст отказа. Если отказ не
    наступил за ``2N`` запросов (очень медленная модель: окно в 60 с успевает
    обновиться между вызовами), это тоже результат, и он честно помечен ошибкой.
    """
    limit = client.rate_limit
    client.reset_rate_limit()
    question = f"{limit + 1} запросов подряд при лимите {limit}/мин"
    started = time.perf_counter()
    sent = 0
    sample = ""
    message = ""
    for _ in range(limit * 2):
        try:
            result = client.generate(RATE_LIMIT_PROMPT,
                                     max_tokens=RATE_LIMIT_MAX_TOKENS)
        except RateLimitExceeded as exc:
            message = (f"Rate limit exceeded: {limit} запросов в минуту — "
                       f"{sent}-й запрос прошёл, {sent + 1}-й отклонён клиентом")
            logger.info("Счётчик частоты сработал на запросе %s (%s)", sent + 1, exc)
            break
        except RemoteLLMError as exc:
            return _row(STEP_RATE_LIMIT, question, str(exc), _ms(started), "error",
                        model=client.model, calls=sent, limit=limit, sent=sent)
        sent += 1
        sample = result["answer"]
        if sent >= limit + 1:
            break
    if not message:
        return _row(STEP_RATE_LIMIT, question,
                    f"Лимит не сработал: {sent} запросов подряд при пределе "
                    f"{limit}/мин — окно {int(config.REMOTE_LLM_RATE_WINDOW_SECONDS)} с "
                    f"обновилось быстрее, чем заполнился счётчик",
                    _ms(started), "error", model=client.model, calls=sent,
                    limit=limit, sent=sent, sample=sample, blocked=0)
    return _row(STEP_RATE_LIMIT, question, message, _ms(started), "ok",
                model=client.model, calls=sent, limit=limit, sent=sent, blocked=1,
                sample=sample, rate_limit=client.rate_limit_state())


def _row(key: str, question: str, answer: str, duration_ms: int, status: str, *,
         model: str = "", calls: int = 0, tokens: Optional[dict] = None,
         rate_limit: Optional[dict] = None, **extra) -> dict:
    """Строка таблицы демо: одинаковые поля у всех шагов, свои — через ``extra``."""
    row = {
        "step": key,
        "title": step_title(key),
        "question": question,
        "answer": str(answer or ""),
        "duration_ms": int(duration_ms),
        "provider": llm_provider.PROVIDER_REMOTE,
        "model": model or "",
        "status": status,
        "calls": int(calls),
    }
    if tokens:
        row["tokens"] = dict(tokens)
    if rate_limit:
        row["rate_limit"] = dict(rate_limit)
    row.update(extra)
    return row


def _ms(started: float) -> int:
    """Миллисекунды с момента ``started`` (``time.perf_counter``)."""
    return int((time.perf_counter() - started) * 1000)
