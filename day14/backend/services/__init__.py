"""Прикладной слой дня 14: сервисы, оркеструющие доменные правила и хранилище.

- ``compressor`` — ``ContextCompressor``: вызов суммаризации и запись конспекта;
- ``task_state`` — ``TaskStateMachine``: переходы состояния задачи (валидация по
  ``backend.domain.task_fsm``, запись через ``backend.storage.task_store``);
- ``invariant_checker`` — ``InvariantChecker``: проверка текста на нарушение
  инвариантов (сначала детерминированные правила, затем — при неоднозначности —
  один вызов DeepSeek).

Сервисы знают про домен и хранилище, но не про HTTP и не про Streamlit.
"""

from . import compressor, invariant_checker, task_state
from .compressor import SUMMARY_SYSTEM_PROMPT, CompressionError, ContextCompressor
from .invariant_checker import (
    INVARIANT_CHECK_SYSTEM_PROMPT,
    InvariantCheckResult,
    InvariantChecker,
    InvariantViolation,
    make_checker_client,
)
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
    "INVARIANT_CHECK_SYSTEM_PROMPT",
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
    "InvariantCheckResult",
    "InvariantChecker",
    "InvariantViolation",
    "TaskExistsError",
    "TaskNotFoundError",
    "TaskStateMachine",
    "compressor",
    "invariant_checker",
    "make_checker_client",
    "task_state",
]
