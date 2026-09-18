"""Pydantic-схемы API дня 15: единое место моделей, разложенное по доменам.

Схемы перенесены из монолитного ``models.py`` без изменений и реэкспортируются
отсюда, поэтому код дня (и тесты) импортирует их из ``backend.schemas``.
ORM-таблицы — отдельный пакет ``backend/models/``.

- ``agent.py``   — агент, генерация, метрики использования токенов;
- ``context.py`` — сжатие истории, стратегии, ветки, факты;
- ``invariant.py`` — инварианты проекта дня 14 и результат проверки текста;
- ``memory.py``  — три слоя памяти агента;
- ``profile.py`` — профиль пользователя и его вклад в промпт;
- ``task.py``    — состояние задачи: этап, шаг, контролируемые переходы (день 15),
  флаги-согласования и журнал попыток.
"""

from .agent import (
    AgentConfig,
    AgentPatch,
    AgentSummary,
    AgentInfo,
    GenerateRequest,
    MessageOut,
    TokenMetrics,
    UsageOut,
    UsageSummary,
    GenerateResponse,
)

from .context import (
    CompressionInfo,
    ContextInfo,
    SummaryOut,
    SummaryInfo,
    SummarizeRequest,
    CompareRequest,
    CompareSide,
    CompareResult,
    StrategySetRequest,
    StrategiesOut,
    BranchCreateRequest,
    BranchOut,
    BranchListOut,
    FactOut,
    FactsOut,
)

from .invariant import (
    InvariantCheckIn,
    InvariantCheckOut,
    InvariantIn,
    InvariantOut,
    InvariantUpdateIn,
    InvariantViolationOut,
)

from .memory import (
    MemoryLayerInfo,
    MemoryInfo,
    ShortTermMessageIn,
    ShortTermMessageOut,
    ShortTermOut,
    ShortTermClearOut,
    WorkingEntryIn,
    WorkingEntryOut,
    WorkingMemoryOut,
    LongTermEntryIn,
    LongTermEntryOut,
    LongTermMemoryOut,
    LongTermDeleteOut,
    SessionOut,
    TaskSetRequest,
    TaskOut,
)

from .profile import (
    UserPreferences,
    UserConstraints,
    UserProfileIn,
    UserProfileOut,
    UserProfileDeleteOut,
    ProfileElementOut,
    AppliedProfileOut,
)

from .task import (
    TaskAllowedNextOut,
    TaskBlockedOut,
    TaskCreateIn,
    TaskFlagsIn,
    TaskHistoryOut,
    TaskRollbackIn,
    TaskStateOut,
    TaskTransitionIn,
    TaskTransitionOut,
)

__all__ = [
    "AgentConfig",
    "AgentInfo",
    "AgentPatch",
    "AgentSummary",
    "AppliedProfileOut",
    "BranchCreateRequest",
    "BranchListOut",
    "BranchOut",
    "CompareRequest",
    "CompareResult",
    "CompareSide",
    "CompressionInfo",
    "ContextInfo",
    "FactOut",
    "FactsOut",
    "GenerateRequest",
    "GenerateResponse",
    "InvariantCheckIn",
    "InvariantCheckOut",
    "InvariantIn",
    "InvariantOut",
    "InvariantUpdateIn",
    "InvariantViolationOut",
    "LongTermDeleteOut",
    "LongTermEntryIn",
    "LongTermEntryOut",
    "LongTermMemoryOut",
    "MemoryInfo",
    "MemoryLayerInfo",
    "MessageOut",
    "ProfileElementOut",
    "SessionOut",
    "ShortTermClearOut",
    "ShortTermMessageIn",
    "ShortTermMessageOut",
    "ShortTermOut",
    "StrategiesOut",
    "StrategySetRequest",
    "SummarizeRequest",
    "SummaryInfo",
    "SummaryOut",
    "TaskAllowedNextOut",
    "TaskBlockedOut",
    "TaskCreateIn",
    "TaskFlagsIn",
    "TaskHistoryOut",
    "TaskOut",
    "TaskRollbackIn",
    "TaskSetRequest",
    "TaskStateOut",
    "TaskTransitionIn",
    "TaskTransitionOut",
    "TokenMetrics",
    "UsageOut",
    "UsageSummary",
    "UserConstraints",
    "UserPreferences",
    "UserProfileDeleteOut",
    "UserProfileIn",
    "UserProfileOut",
    "WorkingEntryIn",
    "WorkingEntryOut",
    "WorkingMemoryOut",
]
