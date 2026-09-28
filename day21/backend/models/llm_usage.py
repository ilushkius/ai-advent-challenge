"""ORM-таблица журнала расходов на LLM (день 21).

Одна таблица ``llm_usage`` (LLMUsage) отвечает на вопрос «сколько стоило и почему»:
одна строка — один ЗАПРОС к модели, с момента запроса (``timestamp``), моделью и
типом задачи (``request_type`` — значения ``config.LLM_TASK_*``: по ним видно, за
что именно заплачены деньги), разбивкой ввода на попадание в кэш контекста
(``cache_hit_tokens``) и промах (``cache_miss_tokens``), токенами ответа и оценкой
стоимости (``cost_estimate``).

Журнал лежит в SQLite, а не в памяти процесса: расходы читают три разных
потребителя (сводка «Расходы» в интерфейсе, отчёт об оптимизации, сравнение «до и
после»), и после перезапуска приложения цифры обязаны сохраниться — иначе «до»
пришлось бы набирать заново.

Почему ``cost_estimate`` — колонка, а не пересчёт на чтении: прайс провайдера
меняется, и старые записи должны сохранять ту цену, по которой они реально
произошли; формула лежит в ``domain/llm_cost.py``, а не здесь. Колонка подписана
как оценка именно поэтому.

``agent_id`` пустой у служебных запросов (сжатие контекста, проверка инвариантов,
пакетная индексация): у них нет своего агента в диалоге, и приписывать их
случайному было бы неправдой, а подсчёт по агенту от этого не страдает — фильтр
идёт по ``agent_id``.

Размеры строк — из ``config`` (та же конвенция, что у остальных таблиц дня).
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from shared.db_base import Base

from ..core import config


class LLMUsage(Base):
    """Строка журнала расходов на LLM (таблица llm_usage, день 21)."""

    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: Агент, по чьей инициативе ушёл запрос; NULL — служебный вызов без агента.
    agent_id = Column(String(config.LLM_USAGE_AGENT_MAX), nullable=True, index=True)
    #: Момент запроса (UTC). Индексируется: по нему строится окно периода и график
    #: «расход по дням», и это самый частый фильтр журнала.
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True,
                       default=datetime.utcnow)
    model = Column(String(config.LLM_USAGE_MODEL_MAX), nullable=False)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    #: Ввод, попавший в префиксный кэш контекста (дешевле обычного ввода).
    cache_hit_tokens = Column(Integer, nullable=False, default=0)
    #: Ввод, ушедший по полной цене: промах кэша.
    cache_miss_tokens = Column(Integer, nullable=False, default=0)
    #: Оценка стоимости в долларах (формула — ``domain/llm_cost.estimate_cost``).
    cost_estimate = Column(Float, nullable=False, default=0.0)
    #: Тип задачи: значение ``config.LLM_TASK_*`` (chat, summarize, indexing, …).
    request_type = Column(String(config.LLM_USAGE_TYPE_MAX), nullable=False, index=True)
    #: Момент записи строки: может отличаться от ``timestamp`` (запись после ответа).
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
