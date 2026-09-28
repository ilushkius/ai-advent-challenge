"""ORM-таблицы оркестрации MCP-серверов (день 20).

Две таблицы, по одной на вопрос «что происходило при прогоне»:

- ``orchestration_runs`` (OrchestrationRun) — ЗАПУСК: реплика-запрос, план шагов
  (``plan`` — данные, а не ссылка), статус (``running``/``completed``/``stopped``/
  ``failed`` — значения ``OrchestrationState``), начало, конец, общая длительность
  и список серверов, которые реально участвовали (``servers_used``). Строка
  переживает рестарт: по ней читается история и видно, чем закончился прогон;
- ``orchestration_steps`` (OrchestrationStep) — ШАГ ЗАПУСКА: порядковый номер,
  СЕРВЕР (``server_name``) и инструмент на нём, входные аргументы (уже разрешённые
  значения, а не шаблон), выходной результат (структура ответа инструмента), время
  выполнения, статус (``ok``/``failed``/``stopped``) и текст ошибки.

Требование дня — «каждый шаг логировать с указанием сервера, инструмента, входных
аргументов и результата» — выполняется ровно этими колонками: журнал читается
целиком строкой, а не собирается из логов процессов. Ошибка шага — тоже строка
журнала (``status`` и ``error_message``); шаг, пропущенный по условию, — ``stopped``
с сообщением условия.

Удаление запуска уносит его шаги каскадом (``ondelete="CASCADE"``): история шагов
без запуска смысла не имеет.

Границы строк — из ``config`` (та же конвенция, что у таблиц пайплайна и планировщика).
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from shared.db_base import Base

from ..core import config


class OrchestrationRun(Base):
    """Запуск оркестрации (таблица orchestration_runs, день 20)."""

    __tablename__ = "orchestration_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    #: Реплика-запрос, из которой собран план (заголовок запуска в истории и UI).
    query = Column(String(config.ORCH_QUERY_MAX), nullable=False)
    #: План шагов целиком: имя, шаги с аргументами и условиями перехода.
    plan = Column(JSON, nullable=False, default=dict)
    #: Статус: значение ``OrchestrationState`` (running/completed/stopped/failed).
    status = Column(String(config.ORCH_STATUS_MAX), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    #: Сколько миллисекунд занял прогон целиком (0 — прогон ещё идёт).
    total_duration_ms = Column(Integer, nullable=False, default=0)
    #: Серверы, участвовавшие в прогоне, в порядке первого появления.
    servers_used = Column(JSON, nullable=False, default=list)

    steps = relationship(
        "OrchestrationStep",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="OrchestrationStep.step_index",
    )


class OrchestrationStep(Base):
    """Шаг запуска оркестрации (таблица orchestration_steps, день 20)."""

    __tablename__ = "orchestration_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        Integer,
        ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: Номер шага в плане (с нуля): по нему читается порядок прогона.
    step_index = Column(Integer, nullable=False)
    #: Имя сервера флота, который получил вызов (маршрутизация по имени инструмента).
    server_name = Column(String(config.ORCH_SERVER_MAX), nullable=False)
    tool_name = Column(String(config.ORCH_TOOL_MAX), nullable=False)
    #: Аргументы, с которыми инструмент вызван (после разрешения ссылок плана).
    input_args = Column(JSON, nullable=False, default=dict)
    #: Результат шага: структура ответа инструмента, текст и код причины.
    output_result = Column(JSON, nullable=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    status = Column(String(config.ORCH_STATUS_MAX), nullable=False)
    error_message = Column(Text, nullable=True)

    run = relationship("OrchestrationRun", back_populates="steps")
