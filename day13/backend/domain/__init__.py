"""Доменный слой дня 13: чистые правила и данные, без БД, LLM и транспорта.

Модули:

- ``strategies`` — ``Enum Strategy`` и проверка допустимости значения;
- ``context_fsm`` — стейт-машина сжатия (день 9: ``Enum`` + паттерн State);
- ``context_policy`` — чистая арифметика сжатия (когда сжимать, что оставить);
- ``fact_extractor`` — эвристика извлечения фактов «ключ → значение»;
- ``memory_layers`` — категории и тексты блоков трёх слоёв памяти;
- ``profile_values`` — значения профиля: ``Enum``-перечисления и нормализация;
- ``profiles`` — сборка блока персонализации для системного промпта;
- ``demo_profiles`` — демонстрационные профили для офлайн-сравнения;
- ``task_fsm`` — стейт-машина состояния задачи (этапы, шаги, переходы);
- ``task_prompt`` — блок состояния задачи для системного промпта;
- ``task_intent`` — распознавание намерения реплики («пауза», «продолжи»).

Импорты слоя — только стандартная библиотека, ``backend.core.config`` и модули
этого же слоя.
"""

from .context_fsm import (
    ContextEvent,
    ContextMachine,
    ContextState,
    UnknownContextEvent,
    state_from_value,
)
from .context_policy import CompressionPlan, CompressionPolicy, plan_compression
from .demo_profiles import (
    DEMO_FEATURE_REQUEST,
    DEMO_PROFILES,
    DEMO_QUESTION,
    demo_profile,
    demo_titles,
)
from .fact_extractor import extract_facts, merge_facts, normalize_key
from .memory_layers import (
    AVAILABLE_CATEGORIES,
    MemoryCategory,
    query_keywords,
    render_long_term_block,
    render_working_block,
)
from .profile_values import (
    ProfileValueError,
    normalize_constraints,
    normalize_instructions,
    normalize_preferences,
)
from .profiles import build_profile_prompt
from .strategies import AVAILABLE_STRATEGIES, Strategy, strategy_from_value
from .task_fsm import (
    DoneState,
    ExecutionState,
    InvalidTaskTransition,
    PausedState,
    PlanningState,
    TaskEvent,
    TaskStage,
    TaskStageBase,
    TaskStep,
    UnknownTaskEvent,
    ValidationState,
    first_step,
    is_valid_transition,
    next_step,
    rollback_target,
    stage_from_value,
    stage_state_from_value,
    step_from_value,
    steps_of,
)
from .task_intent import INTENT_PHRASES, TaskIntent, classify_task_intent
from .task_prompt import (
    EXPECTED_ACTIONS,
    TASK_STATE_HEADER,
    build_prompt_block,
    default_expected_action,
    previous_stages_text,
    render_task_state_block,
)

__all__ = [
    "AVAILABLE_CATEGORIES",
    "AVAILABLE_STRATEGIES",
    "DEMO_FEATURE_REQUEST",
    "DEMO_PROFILES",
    "DEMO_QUESTION",
    "EXPECTED_ACTIONS",
    "INTENT_PHRASES",
    "TASK_STATE_HEADER",
    "CompressionPlan",
    "CompressionPolicy",
    "ContextEvent",
    "ContextMachine",
    "ContextState",
    "DoneState",
    "ExecutionState",
    "InvalidTaskTransition",
    "MemoryCategory",
    "PausedState",
    "PlanningState",
    "ProfileValueError",
    "Strategy",
    "TaskEvent",
    "TaskIntent",
    "TaskStage",
    "TaskStageBase",
    "TaskStep",
    "UnknownContextEvent",
    "UnknownTaskEvent",
    "ValidationState",
    "build_profile_prompt",
    "build_prompt_block",
    "classify_task_intent",
    "default_expected_action",
    "demo_profile",
    "demo_titles",
    "extract_facts",
    "first_step",
    "is_valid_transition",
    "merge_facts",
    "next_step",
    "normalize_constraints",
    "normalize_instructions",
    "normalize_key",
    "normalize_preferences",
    "plan_compression",
    "previous_stages_text",
    "query_keywords",
    "render_long_term_block",
    "render_task_state_block",
    "render_working_block",
    "rollback_target",
    "stage_from_value",
    "stage_state_from_value",
    "state_from_value",
    "step_from_value",
    "steps_of",
    "strategy_from_value",
]
