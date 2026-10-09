"""Pydantic-схемы дня 30: удалённая локальная LLM (Ollama в Colab через туннель).

Контракт строки таблицы (``RemoteRowOut``) намеренно повторяет форму словарей
службы (``services/remote_llm_service``) и домена демо (``domain/remote_demo``):
роутер не переупаковывает данные, а только объявляет их. Поля-ручки интерфейса
(``RemoteSettingsIn``) едут вместе с каждым шагом: слайдеры видны на экране и
применяются к прогону, а UI нигде не хранит «текущий клиент» у себя.

Настройки здесь описаны как «пусто — значение ``day21/.env``»: интерфейс шлёт только
заполненные поля, а пустая строка или ноль означают «как в конфиге», поэтому
незаполненный адрес не превращается в пустую строку, а ноль — в нулевой предел
частоты. Границы слайдеров объявлены теми же константами ``config``, что и в
разделе интерфейса, — один источник границ на весь день.

Модуль отдельный от ``schemas/__init__.py``: тот стоит на пределе 400 строк, поэтому
схемы дня 30 импортируются напрямую (``from ..schemas.remote_llm import …``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..core import config
from ..domain import llm_provider
from .rag import RagTokensOut


class RemoteSettingsIn(BaseModel):
    """Ручки раздела: адрес туннеля, модель, ключ, предел частоты и окно контекста."""

    url: str = Field("", max_length=config.REMOTE_LLM_URL_MAX,
                     description="Base URL туннеля, например "
                                 "https://xxxx.trycloudflare.com/v1 — пусто: REMOTE_LLM_URL")
    model: str = Field("", max_length=config.REMOTE_LLM_MODEL_MAX,
                       description="Тег модели Ollama; пусто: REMOTE_LLM_MODEL")
    api_key: str = Field("", max_length=config.REMOTE_LLM_API_KEY_MAX,
                         description="Любая строка (Ollama её не проверяет); "
                                     "пусто: REMOTE_LLM_API_KEY")
    rate_limit: int = Field(0, ge=0, le=config.REMOTE_LLM_RATE_LIMIT_MAX,
                            description=f"Запросов в минуту, 0 — из конфига; "
                                        f"слайдер: {config.REMOTE_LLM_RATE_LIMIT_MIN}"
                                        f"…{config.REMOTE_LLM_RATE_LIMIT_MAX}")
    max_context: int = Field(0, ge=0, le=config.REMOTE_LLM_MAX_CONTEXT_MAX,
                             description=f"Окно контекста (options.num_ctx), 0 — из "
                                         f"конфига; слайдер: "
                                         f"{config.REMOTE_LLM_MAX_CONTEXT_MIN}"
                                         f"…{config.REMOTE_LLM_MAX_CONTEXT_MAX}")


class RemoteCheckIn(BaseModel):
    """Тело проверки связи: только настройки, шага здесь нет."""

    settings: RemoteSettingsIn = Field(default_factory=RemoteSettingsIn,
                                       description="Настройки раздела")


class RemoteCheckOut(BaseModel):
    """Результат ``GET {base_url}/models``: зелёный или красный индикатор раздела."""

    ok: bool = Field(False, description="Связь есть (индикатор в интерфейсе)")
    message: str = Field("", description="Текст для индикатора: успех или причина отказа")
    models: List[str] = Field([], description="Имена моделей, доступных по туннелю")
    count: int = Field(0, description="Сколько моделей вернул сервис")
    url: str = Field("", description="Адрес, к которому шёл запрос")
    model: str = Field("", description="Модель, выбранная для прогона")
    duration_ms: int = Field(0, description="Сколько шёл запрос списка моделей")
    rate_limit: Dict[str, Any] = Field(default_factory=dict,
                                       description="Состояние клиентского счётчика: limit, used")


class RemoteStepIn(BaseModel):
    """Один шаг прогона: настройки и ключ шага из ``domain/remote_demo.STEP_KEYS``."""

    settings: RemoteSettingsIn = Field(default_factory=RemoteSettingsIn,
                                       description="Настройки раздела")
    step: str = Field(..., description="connection | fact | logic | code | rate_limit")
    reset: bool = Field(False, description="Начать шаг с чистого счётчика частоты")


class RemoteRowOut(BaseModel):
    """Строка таблицы прогона: шаг, запрос, ответ, время, провайдер, статус.

    Свои поля есть только у тех шагов, где они что-то значат: ``models`` — у
    проверки связи, ``limit``/``sent``/``blocked``/``sample`` — у проверки частоты.
    Поэтому они необязательные, а не «пустые у всех».
    """

    step: str = Field(..., description="Ключ шага")
    title: str = Field("", description="Подпись шага для таблицы")
    question: str = Field("", description="Что отправлено (для проверки связи — эндпоинт)")
    answer: str = Field("", description="Ответ модели или текст отказа")
    duration_ms: int = Field(0, description="Сколько шёл шаг")
    provider: str = Field(llm_provider.PROVIDER_REMOTE,
                          description="Кто ответил (всегда remote)")
    model: str = Field("", description="Модель, ответившая на шаг")
    status: str = Field("ok", description="ok | error")
    calls: int = Field(0, description="Сколько HTTP-запросов ушло на шаге")
    tokens: Optional[RagTokensOut] = Field(None, description="Токены шага, если был вызов")
    rate_limit: Optional[Dict[str, Any]] = Field(None, description="Счётчик частоты после шага")
    limit: Optional[int] = Field(None, description="Предел частоты на шаге про частоту")
    sent: Optional[int] = Field(None, description="Сколько запросов прошло до отказа")
    blocked: Optional[int] = Field(None, description="Сколько запросов отклонил клиент")
    sample: Optional[str] = Field(None, description="Ответ последнего прошедшего запроса")
    models: Optional[List[str]] = Field(None, description="Модели сервиса (шаг проверки связи)")


class RemoteStepInfoOut(BaseModel):
    """Описание шага для интерфейса: подпись, вопрос и вид проверки."""

    key: str = Field(..., description="Ключ шага")
    title: str = Field("", description="Подпись шага")
    question: str = Field("", description="Что будет отправлено")
    kind: str = Field("", description="check | ask | rate")


class RemoteConfigOut(BaseModel):
    """GET /llm/remote-config — значения из ``.env`` и границы ручек интерфейса.

    Значения по умолчанию отдаёт бэкенд, а не фронтенд: иначе предзаполненное поле
    UI и настройка, которой реально отвечает служба, могли бы разойтись.
    """

    provider: str = Field(llm_provider.PROVIDER_REMOTE, description="Имя провайдера")
    label: str = Field("", description="Подпись провайдера для интерфейса")
    url: str = Field("", description="REMOTE_LLM_URL из .env (может быть пустым)")
    model: str = Field("", description="REMOTE_LLM_MODEL из .env")
    api_key: str = Field("", description="REMOTE_LLM_API_KEY из .env")
    rate_limit: int = Field(0, description="REMOTE_LLM_RATE_LIMIT из .env")
    max_context: int = Field(0, description="REMOTE_LLM_MAX_CONTEXT из .env")
    timeout: float = Field(0.0, description="Предел ожидания одного запроса, с")
    rate_window_seconds: float = Field(0.0, description="Окно счётчика частоты, с")
    rate_limit_min: int = Field(0, description="Нижняя граница слайдера частоты")
    rate_limit_max: int = Field(0, description="Верхняя граница слайдера частоты")
    max_context_min: int = Field(0, description="Нижняя граница окна контекста")
    max_context_max: int = Field(0, description="Верхняя граница окна контекста")
    steps: List[RemoteStepInfoOut] = Field([], description="Пять шагов прогона по порядку")
