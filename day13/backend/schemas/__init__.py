"""Pydantic-схемы API дня 13: единое место моделей, разложенное по доменам.

Схемы перенесены из монолитного ``models.py`` без изменений и реэкспортируются
отсюда, поэтому код дня (и тесты) импортирует их из ``backend.schemas``.
ORM-таблицы — отдельный пакет ``backend/models/``.

- ``agent.py``   — агент, генерация, метрики использования токенов;
- ``context.py`` — сжатие истории, стратегии, ветки, факты;
- ``memory.py``  — три слоя памяти агента;
- ``profile.py`` — профиль пользователя и его вклад в промпт;
- ``task.py``    — состояние задачи дня 13: этап, шаг, переходы и журнал.
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
    TaskCreateIn,
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
    "TaskCreateIn",
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
