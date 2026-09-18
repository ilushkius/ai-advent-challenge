"""Доменный слой дня 15: чистые правила и данные, без БД, LLM и транспорта.

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
- ``task_state_machine`` — граф допуска переходов этапов и guard-условия (день 15);
- ``task_proposal`` — распознавание предложения модели перейти в другой этап;
- ``task_prompt`` — блок состояния задачи для системного промпта;
- ``task_intent`` — распознавание намерения реплики («пауза», «продолжи»).
- ``invariant_values`` — категории, важность и вердикты инвариантов (день 14);
- ``invariant_rules`` — детерминированные правила проверки текста;
- ``invariant_prompt`` — блок инвариантов, тексты отказа и предупреждения;
- ``demo_invariants`` — четыре демонстрационных инварианта (по одному на категорию).

Импорт ``AVAILABLE_CATEGORIES`` из ``invariant_values`` переименован на входе
слоя в ``AVAILABLE_INVARIANT_CATEGORIES``: у слоя уже есть
``AVAILABLE_CATEGORIES`` — категории долговременной памяти (``memory_layers``), и
два разных значения под одним именем в одном пространстве имён — это скрытая
ошибка, а не удобство.

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
from .demo_invariants import DEMO_INVARIANTS
from .demo_profiles import (
    DEMO_FEATURE_REQUEST,
    DEMO_PROFILES,
    DEMO_QUESTION,
    demo_profile,
    demo_titles,
)
from .fact_extractor import extract_facts, merge_facts, normalize_key
from .invariant_prompt import (
    INVARIANTS_FOOTER,
    INVARIANTS_HEADER,
    REFUSAL_FOOTER,
    REFUSAL_HEADER,
    WARNING_HEADER,
    invariant_line,
    render_check_user_message,
    render_invariants_block,
    render_violation_refusal,
    render_violation_warning,
    violation_line,
)
from .invariant_rules import (
    DETERMINISTIC_RULES,
    PAID_SERVICES_RULE,
    DeterministicRule,
    deterministic_violations,
)
from .invariant_values import (
    CATEGORY_LABELS,
    SEVERITY_LABELS,
    VERDICT_ALLOWED,
    VERDICT_REFUSAL,
    VERDICT_WARNING,
    InvariantCategory,
    InvariantSeverity,
    InvariantValueError,
    category_from_value,
    severity_from_value,
)
from .invariant_values import AVAILABLE_CATEGORIES as AVAILABLE_INVARIANT_CATEGORIES
from .invariant_values import AVAILABLE_SEVERITIES as AVAILABLE_INVARIANT_SEVERITIES
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
    InvalidTransitionError,
    PausedState,
    PlanningState,
    TaskEvent,
    TaskStage,
    TaskStageBase,
    TaskStep,
    UnknownTaskEvent,
    ValidationState,
    first_step,
    next_step,
    rollback_target,
    stage_from_value,
    stage_state_from_value,
    step_from_value,
    steps_of,
)
from .task_intent import INTENT_PHRASES, TaskIntent, classify_task_intent
from .task_proposal import STAGE_PROPOSAL_PHRASES, detect_stage_proposal
from .task_state_machine import (
    ALLOWED_TRANSITIONS,
    FLAG_IMPLEMENTATION_COMPLETE,
    FLAG_PLAN_APPROVED,
    FLAG_VALIDATION_PASSED,
    GUARDS,
    STAGE_DISPLAY_ORDER,
    STAGE_FLAG,
    TASK_FLAGS,
    can_transition,
    cleared_flags,
    get_allowed_next_stages,
    get_blocked_stages,
    guard_context,
    intent_refusal_notice,
    is_transition_allowed,
    transition_error_message,
    transition_explanation,
    transition_hint,
)
from .task_prompt import (
    EXPECTED_ACTIONS,
    TASK_STATE_HEADER,
    build_prompt_block,
    default_expected_action,
    previous_stages_text,
    render_task_state_block,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AVAILABLE_CATEGORIES",
    "AVAILABLE_INVARIANT_CATEGORIES",
    "AVAILABLE_INVARIANT_SEVERITIES",
    "AVAILABLE_STRATEGIES",
    "CATEGORY_LABELS",
    "DEMO_FEATURE_REQUEST",
    "DEMO_INVARIANTS",
    "DEMO_PROFILES",
    "DEMO_QUESTION",
    "DETERMINISTIC_RULES",
    "EXPECTED_ACTIONS",
    "FLAG_IMPLEMENTATION_COMPLETE",
    "FLAG_PLAN_APPROVED",
    "FLAG_VALIDATION_PASSED",
    "GUARDS",
    "INTENT_PHRASES",
    "INVARIANTS_FOOTER",
    "INVARIANTS_HEADER",
    "PAID_SERVICES_RULE",
    "REFUSAL_FOOTER",
    "REFUSAL_HEADER",
    "SEVERITY_LABELS",
    "STAGE_DISPLAY_ORDER",
    "STAGE_FLAG",
    "STAGE_PROPOSAL_PHRASES",
    "TASK_FLAGS",
    "TASK_STATE_HEADER",
    "VERDICT_ALLOWED",
    "VERDICT_REFUSAL",
    "VERDICT_WARNING",
    "WARNING_HEADER",
    "CompressionPlan",
    "CompressionPolicy",
    "ContextEvent",
    "ContextMachine",
    "ContextState",
    "DeterministicRule",
    "DoneState",
    "ExecutionState",
    "InvalidTransitionError",
    "InvariantCategory",
    "InvariantSeverity",
    "InvariantValueError",
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
    "can_transition",
    "category_from_value",
    "classify_task_intent",
    "cleared_flags",
    "default_expected_action",
    "demo_profile",
    "demo_titles",
    "detect_stage_proposal",
    "deterministic_violations",
    "extract_facts",
    "first_step",
    "get_allowed_next_stages",
    "get_blocked_stages",
    "guard_context",
    "intent_refusal_notice",
    "invariant_line",
    "is_transition_allowed",
    "merge_facts",
    "next_step",
    "normalize_constraints",
    "normalize_instructions",
    "normalize_key",
    "normalize_preferences",
    "plan_compression",
    "previous_stages_text",
    "query_keywords",
    "render_check_user_message",
    "render_invariants_block",
    "render_long_term_block",
    "render_task_state_block",
    "render_violation_refusal",
    "render_violation_warning",
    "render_working_block",
    "rollback_target",
    "severity_from_value",
    "stage_from_value",
    "stage_state_from_value",
    "state_from_value",
    "step_from_value",
    "steps_of",
    "strategy_from_value",
    "transition_error_message",
    "transition_explanation",
    "transition_hint",
    "violation_line",
]
