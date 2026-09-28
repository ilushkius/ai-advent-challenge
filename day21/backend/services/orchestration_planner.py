"""Планировщик плана оркестрации на DeepSeek (день 20).

Модель получает КАТАЛОГ ФЛОТА (серверы и их инструменты) и реплику пользователя,
а возвращает план шагов: «какие инструменты с каких серверов вызвать и в каком
порядке». Всё, что можно проверить офлайн (текст каталога, промпт, разбор ответа),
лежит в домене (``backend/domain/orchestration_plan.py``); здесь только вызов API.

Почему неудача планировщика — не ошибка приложения. План — это лишь один из
способов его получить: если ключа нет, сеть не ответила или модель вернула мусор,
оркестратор переходит на эвристику (``heuristic_plan``) и продолжает работу.
Поэтому ``plan`` возвращает ``Optional[dict]`` и НИКОГДА не бросает: «модель не
ответила» не должно превращаться в «прогон не состоялся».

Клиент создаётся лениво и один на процесс (как в ``Agent._make_client``): вызовов
может быть много, соединение на каждый никто не заводит. Фабрику можно подменить
(``client_factory``) — этим пользуются тесты и сценарии демонстрации.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger

from ..core import config
from ..domain.mcp_tools import MCPFleetTool
from ..domain.orchestration_plan import build_plan_prompt, parse_plan

logger = get_logger(__name__)


class OrchestrationPlanner:
    """Строит план шагов моделью DeepSeek; при любой неудаче — ``None``."""

    def __init__(self, client_factory: Optional[Callable[..., object]] = None) -> None:
        self._client_factory = client_factory
        self._client = None

    @property
    def client_factory(self) -> Callable[..., object]:
        """Фабрика клиента: переданная или ``shared.deepseek_client.make_client``."""
        return self._client_factory or make_client

    def available(self) -> bool:
        """Есть ли ключ DeepSeek (без ключа планировщик молча уступает эвристике)."""
        return bool(config.resolve_api_key())

    def plan(self, query: str,
             tools: Sequence[MCPFleetTool]) -> Optional[dict]:
        """План шагов от модели: ``None`` — ключа нет, сбой вызова или ответ не разобран."""
        if not tools:
            logger.info("Оркестрация: каталог флота пуст — план моделью не строится")
            return None
        key = config.resolve_api_key()
        if not key:
            logger.info("Оркестрация: ключа DeepSeek нет — план построит эвристика")
            return None
        try:
            response = self._get_client(key).chat.completions.create(
                model=config.ORCH_PLAN_MODEL,
                messages=build_plan_prompt(query, tools),
                temperature=config.ORCH_PLAN_TEMPERATURE,
                max_tokens=config.ORCH_PLAN_MAX_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001 — план не критичен, есть эвристика
            logger.warning("Оркестрация: планировщик не ответил: %s", exc)
            return None
        text = _text_of(response)
        if not text:
            logger.warning("Оркестрация: планировщик вернул пустой ответ")
            return None
        plan = parse_plan(text)
        if plan is None:
            logger.warning("Оркестрация: план модели не разобран (ответ %d символов)",
                           len(text))
            return None
        logger.info("Оркестрация: план модели — %d шагов", len(plan["steps"]))
        return plan

    def _get_client(self, key: str):
        """Клиент DeepSeek процесса: создаётся при первом обращении."""
        if self._client is None:
            self._client = self.client_factory(key, timeout=config.REQUEST_TIMEOUT)
            logger.debug("Оркестрация: клиент DeepSeek создан")
        return self._client


def _text_of(response: object) -> str:
    """Текст ответа модели (``""`` — ответ пуст или у него нет содержимого)."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return str(getattr(message, "content", "") or "").strip()
