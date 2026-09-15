"""Роутер API дня 12: сжатие истории, стратегии, ветки и факты.

Эндпоинты перенесены из монолитного ``backend/main.py`` дословно (пути, тексты
описаний, коды ответов): изменений логики нет, добавлен только префикс
``@router.`` и обращение к менеджеру через ``backend.dependencies``.
"""
from fastapi import APIRouter

from .. import dependencies
from ..models import (
    BranchCreateRequest, BranchListOut, CompareRequest, CompareResult, FactsOut,
    StrategiesOut, StrategySetRequest, SummarizeRequest, SummaryInfo,
)

router = APIRouter()


# ---------- сжатие истории (день 9) ----------
@router.post(
    "/agents/{agent_id}/summarize",
    summary="Сжать историю сейчас",
    description=(
        "Принудительное сжатие: старые реплики (всё выше keep_last_messages) "
        "уходят в конспект. Без force=True срабатывает только при набранном "
        "пороге summarize_every — иначе возвращается created:false с причиной."
    ),
)
def summarize(agent_id: str, body: SummarizeRequest):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().force_summarize(agent_id, force=body.force)


@router.get(
    "/agents/{agent_id}/summary",
    response_model=SummaryInfo,
    summary="Состояние сжатия агента",
    description=(
        "Текущий конспект, watermark (сколько реплик покрыто), история "
        "конспектов и экономика: сэкономленные токены за вычетом стоимости "
        "вызовов суммаризации."
    ),
)
def get_summary(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_summary(agent_id)


@router.post(
    "/agents/{agent_id}/compare",
    response_model=CompareResult,
    summary="Сравнить режимы без сжатия и со сжатием",
    description=(
        "Считает токены обоих вариантов контекста для одного промпта; при "
        "call_api=true делает два реальных вызова DeepSeek и возвращает оба "
        "ответа. История диалога не изменяется."
    ),
)
def compare(agent_id: str, body: CompareRequest):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().compare_modes(
        agent_id, body.prompt, call_api=body.call_api
    )


# ---------- стратегии управления контекстом (день 11) ----------
@router.post(
    "/agents/{agent_id}/strategy",
    response_model=StrategiesOut,
    summary="Сменить стратегию управления контекстом",
    description=(
        "Меняет стратегию агента (sliding_window | sticky_facts | branching | "
        "summary) и, опционально, размер скользящего окна. Диалог не теряется."
    ),
)
def set_strategy(agent_id: str, body: StrategySetRequest):
    dependencies.agent_or_404(agent_id)
    manager = dependencies.get_manager()
    manager.set_strategy(agent_id, body.strategy, window_size=body.window_size)
    return manager.get_strategy_state(agent_id)


@router.get(
    "/agents/{agent_id}/strategies",
    response_model=StrategiesOut,
    summary="Текущая стратегия и список доступных",
    description="Возвращает текущую стратегию агента, window_size и все доступные.",
)
def get_strategies(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_strategy_state(agent_id)


@router.post(
    "/agents/{agent_id}/branches",
    response_model=BranchListOut,
    summary="Создать ветку (чекпоинт)",
    description=(
        "Создаёт ветку. При checkpoint_id — ветка наследует снимок указанного "
        "чекпоинта; без него — снимок текущего состояния (от текущего сообщения). "
        "Новая ветка становится активной."
    ),
)
def create_branch(agent_id: str, body: BranchCreateRequest):
    dependencies.agent_or_404(agent_id)
    dependencies.get_manager().create_branch(agent_id, body.checkpoint_id)
    return dependencies.get_manager().list_branches(agent_id)


@router.get(
    "/agents/{agent_id}/branches",
    response_model=BranchListOut,
    summary="Дерево веток агента",
    description="Все чекпоинты/ветки агента с parent_id и флагом активной ветки.",
)
def list_branches(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().list_branches(agent_id)


@router.post(
    "/agents/{agent_id}/branches/{branch_id}/switch",
    response_model=BranchListOut,
    summary="Переключить активную ветку",
    description="Заменяет историю агента снимком выбранной ветки и делает её активной.",
)
def switch_branch(agent_id: str, branch_id: int):
    dependencies.agent_or_404(agent_id)
    dependencies.get_manager().switch_branch(agent_id, branch_id)
    return dependencies.get_manager().list_branches(agent_id)


@router.get(
    "/agents/{agent_id}/facts",
    response_model=FactsOut,
    summary="Факты агента (sticky_facts)",
    description="Текущие факты диалога «ключ → значение» с временем обновления.",
)
def get_facts(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_facts(agent_id)
