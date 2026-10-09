"""Роутер API дня 30: удалённая локальная LLM (Ollama в Colab через Cloudflare Tunnel).

Три эндпоинта — ручки раздела, проверка связи и один шаг прогона:

- ``GET /llm/remote-config`` — значения из ``day21/.env`` (адрес, модель, ключ, предел
  частоты, окно контекста), границы слайдеров и пять шагов прогона: раздел
  интерфейса рисуется по этому ответу, поэтому предзаполненное поле UI и настройка,
  которой реально отвечает служба, приходят из одного места;
- ``POST /llm/remote/check`` — ``GET {base_url}/models``: связь есть или причина
  отказа. Недоступный туннель — это результат проверки (``ok=false`` в 200), а не
  ошибка API: красный индикатор раздела показывает текст причины, не роняя страницу;
- ``POST /llm/remote/step`` — ОДИН шаг сценария (``connection``, ``fact``, ``logic``,
  ``code``, ``rate_limit``). Шаги идут отдельными запросами, чтобы прогресс-бар
  отражал реальный ход; служба держит клиентов в реестре, поэтому клиентский счётчик
  частоты переживает эти запросы и шаг про 429 срабатывает.

Пустой адрес — единственная ошибка, которую роутер отдаёт кодом (400): это ошибка
настройки, и её видно до первого запроса к модели. Ошибка внутри шага возвращается
строкой таблицы со ``status="error"`` — прогон показывает, где оборвался, а не
превращает всю таблицу в одну красную плашку.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import config
from ..domain import llm_provider, remote_demo
from ..schemas.remote_llm import (RemoteCheckIn, RemoteCheckOut, RemoteConfigOut,
                                  RemoteRowOut, RemoteSettingsIn, RemoteStepIn,
                                  RemoteStepInfoOut)
from ..services import remote_llm_service
from ..services.remote_llm_client import RemoteSettings

router = APIRouter()

#: Что сказать, если адрес не заполнен ни в UI, ни в конфиге: туннель живёт часами.
_NO_URL = ("Не задан адрес удалённой модели: впишите Base URL туннеля из Colab "
           "(REMOTE_LLM_URL в day21/.env или поле в разделе «🛰 Удалённая LLM»)")


def _settings(payload: RemoteSettingsIn) -> RemoteSettings:
    """Настройки шага: значения UI поверх конфига, пустой адрес — 400.

    Пределы слайдеров здесь уже зажаты (``RemoteSettings.from_values``), повторная
    проверка не нужна: схема отвергла бы значения вне диапазона раньше.
    """
    settings = RemoteSettings.from_values(url=payload.url, model=payload.model,
                                          api_key=payload.api_key,
                                          rate_limit=payload.rate_limit,
                                          max_context=payload.max_context)
    if not settings.base_url:
        raise HTTPException(status_code=400, detail=_NO_URL)
    return settings


def _step_key(payload: RemoteStepIn) -> str:
    """Ключ шага из тела запроса: неизвестный шаг — 400 со списком допустимых."""
    key = str(payload.step or "").strip()
    if key not in remote_demo.STEP_KEYS:
        raise HTTPException(
            status_code=400,
            detail=(f"Неизвестный шаг демо: {key or '—'}. "
                    f"Доступны: {', '.join(remote_demo.STEP_KEYS)}"))
    return key


@router.get(
    "/llm/remote-config",
    summary="Настройки удалённой LLM и шаги демо",
    description=(
        "Значения дня 30 из ``day21/.env`` плюс границы ручек интерфейса: ``url``, "
        "``model``, ``api_key``, ``rate_limit``, ``max_context``, ``timeout``, окно "
        "счётчика частоты, минимумы и максимумы обоих слайдеров и список пяти шагов "
        "демо (``key``, ``title``, ``question``, ``kind``). Раздел интерфейса "
        "рисуется ровно по этому ответу, поэтому поле URL предзаполнено тем же "
        "значением, которым отвечает служба."
    ),
)
def llm_remote_config() -> RemoteConfigOut:
    """Раздел «Удалённая LLM»: предзаполненные поля, границы слайдеров и шаги."""
    return RemoteConfigOut(
        provider=llm_provider.PROVIDER_REMOTE,
        label=llm_provider.label(llm_provider.PROVIDER_REMOTE),
        url=config.REMOTE_LLM_URL,
        model=config.REMOTE_LLM_MODEL,
        api_key=config.REMOTE_LLM_API_KEY,
        rate_limit=config.REMOTE_LLM_RATE_LIMIT,
        max_context=config.REMOTE_LLM_MAX_CONTEXT,
        timeout=config.REMOTE_LLM_TIMEOUT,
        rate_window_seconds=config.REMOTE_LLM_RATE_WINDOW_SECONDS,
        rate_limit_min=config.REMOTE_LLM_RATE_LIMIT_MIN,
        rate_limit_max=config.REMOTE_LLM_RATE_LIMIT_MAX,
        max_context_min=config.REMOTE_LLM_MAX_CONTEXT_MIN,
        max_context_max=config.REMOTE_LLM_MAX_CONTEXT_MAX,
        steps=[RemoteStepInfoOut(key=step.key, title=step.title,
                                 question=step.question, kind=step.kind)
               for step in remote_demo.DEMO_STEPS],
    )


@router.post(
    "/llm/remote/check",
    summary="Проверить связь с удалённой LLM",
    description=(
        "``GET {base_url}/models`` с настройками из тела: ``ok=true`` и число "
        "доступных моделей либо ``ok=false`` с текстом причины (туннель закрылся, "
        "ячейка в Colab остановлена, адрес не тот). Счётчик частоты не расходуется: "
        "проверка связи — не вызов модели. Пустой адрес — 400."
    ),
)
def llm_remote_check(payload: RemoteCheckIn) -> RemoteCheckOut:
    """Связь с удалённым сервисом: зелёный или красный индикатор раздела."""
    settings = _settings(payload.settings)
    return RemoteCheckOut(**remote_llm_service.check_connection(settings))


@router.post(
    "/llm/remote/step",
    summary="Один шаг демо удалённой LLM",
    description=(
        "Выполняет шаг ``step`` (``connection`` — GET /models, ``fact``/``logic``/"
        "``code`` — вопрос к модели, ``rate_limit`` — N+1 запрос подряд) и возвращает "
        "строку таблицы: запрос, ответ, время, провайдер (``remote``), статус, токены, "
        "состояние счётчика частоты. ``reset=true`` начинает шаг с чистого счётчика: "
        "интерфейс передаёт его на первом шаге прогона. Ошибка шага приходит строкой "
        "со ``status=\"error\"``, неизвестный шаг и пустой адрес — 400."
    ),
)
def llm_remote_step(payload: RemoteStepIn) -> RemoteRowOut:
    """Шаг сценария: строка таблицы либо 400 про сам запрос."""
    settings = _settings(payload.settings)
    key = _step_key(payload)
    return RemoteRowOut(**remote_llm_service.run_step(key, settings,
                                                     reset=payload.reset))
