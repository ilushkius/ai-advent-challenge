"""Прикладной слой дня 13: сервисы, оркеструющие доменные правила и хранилище.

- ``compressor`` — ``ContextCompressor``: вызов суммаризации и запись конспекта;
- ``task_state`` — ``TaskStateMachine``: переходы состояния задачи (валидация по
  ``backend.domain.task_fsm``, запись через ``backend.storage.task_store``).

Сервисы знают про домен и хранилище, но не про HTTP и не про Streamlit.
"""

from . import compressor, task_state
from .compressor import SUMMARY_SYSTEM_PROMPT, CompressionError, ContextCompressor
from .task_state import (
    REASON_CREATED,
    REASON_DEFAULT,
    REASON_DONE,
    REASON_NEXT_STEP,
    REASON_PAUSE,
    REASON_RESUME,
    REASON_ROLLBACK,
    START_STAGES,
    TaskExistsError,
    TaskNotFoundError,
    TaskStateMachine,
)

__all__ = [
    "REASON_CREATED",
    "REASON_DEFAULT",
    "REASON_DONE",
    "REASON_NEXT_STEP",
    "REASON_PAUSE",
    "REASON_RESUME",
    "REASON_ROLLBACK",
    "START_STAGES",
    "SUMMARY_SYSTEM_PROMPT",
    "CompressionError",
    "ContextCompressor",
    "TaskExistsError",
    "TaskNotFoundError",
    "TaskStateMachine",
    "compressor",
    "task_state",
]
