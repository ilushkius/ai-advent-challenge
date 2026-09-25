"""ORM-таблицы пайплайна MCP-инструментов (день 19).

Две таблицы, по одной на вопрос «что происходило при прогоне»:

- ``pipeline_runs`` (PipelineRun) — ЗАПУСК ПАЙПЛАЙНА: имя конфигурации, статус
  (``running``/``completed``/``stopped``/``failed`` — значения ``PipelineState``),
  начало, конец и общая длительность. Строка переживает рестарт: по ней читается
  история запусков и определяется, чем закончился прогон;
- ``pipeline_steps`` (PipelineStep) — ШАГ ЗАПУСКА: порядковый номер, инструмент, его
  ВХОДНЫЕ АРГУМЕНТЫ (``input_args`` — уже разрешённые значения, а не шаблон),
  ВЫХОДНОЙ РЕЗУЛЬТАТ (``output_result`` — структура ответа инструмента), время
  выполнения, статус (``ok``/``failed``/``stopped``) и текст ошибки.

Журнал шагов и есть требование дня: «каждый шаг логировать с входными аргументами,
выходным результатом и временем выполнения», поэтому колонки лежат в одной строке,
а не собираются из логов. Ошибка шага — тоже строка журнала: у неё заполнены
``status`` и ``error_message``; у шага, пропущенного по условию, — ``stopped`` и
сообщение условия.

Удаление запуска уносит его шаги каскадом (``ondelete="CASCADE"``): история шагов
без запуска не имеет смысла.

Границы строк — из ``config`` (та же конвенция, что у таблиц памяти и планировщика).
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


class PipelineRun(Base):
    """Запуск пайплайна (таблица pipeline_runs, день 19)."""

    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_name = Column(String(config.PIPELINE_NAME_MAX), nullable=False)
    #: Статус запуска: значение ``PipelineState`` (idle/running/completed/stopped/failed).
    status = Column(String(config.PIPELINE_STATUS_MAX), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    #: Сколько миллисекунд занял прогон целиком (0 — прогон ещё идёт).
    total_duration_ms = Column(Integer, nullable=False, default=0)

    steps = relationship(
        "PipelineStep",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PipelineStep.step_index",
    )


class PipelineStep(Base):
    """Шаг запуска пайплайна (таблица pipeline_steps, день 19)."""

    __tablename__ = "pipeline_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        Integer,
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: Номер шага в конфигурации (с нуля): по нему читается порядок прогона.
    step_index = Column(Integer, nullable=False)
    tool_name = Column(String(config.PIPELINE_TOOL_MAX), nullable=False)
    #: Аргументы, с которыми инструмент вызван (после разрешения ссылок пайплайна).
    input_args = Column(JSON, nullable=False, default=dict)
    #: Результат шага: структура ответа инструмента, текст и код причины.
    output_result = Column(JSON, nullable=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    status = Column(String(config.PIPELINE_STATUS_MAX), nullable=False)
    error_message = Column(Text, nullable=True)

    run = relationship("PipelineRun", back_populates="steps")
