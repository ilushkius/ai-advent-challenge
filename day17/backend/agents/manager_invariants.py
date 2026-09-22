"""Миксин инвариантов (день 14): CRUD правил проекта и проверка текста.

Часть ``AgentManager`` (``backend/agent_manager.py``): тонкие обёртки над
``InvariantManager`` (хранилище) и ``InvariantChecker`` (проверка) для API-слоя.
Миксин ничего не кэширует: и хранилище, и контролёр создаются на вызов, поэтому
правка списка правил видна со следующего запроса агента, а не после перезапуска
процесса.
"""
from typing import List, Optional

from ..services.invariant_checker import InvariantChecker
from ..storage.invariant_store import InvariantManager

__all__ = ["InvariantOpsMixin"]


class InvariantOpsMixin:
    """Инварианты: CRUD и проверка текста."""

    @property
    def _invariants(self) -> InvariantManager:
        """Хранилище инвариантов на фабрике сессий менеджера."""
        return InvariantManager(session_factory=self._session_factory)

    # --- чтение ---
    def get_invariant(self, invariant_id: int) -> Optional[dict]:
        """Инвариант по id (``None`` — такого правила нет)."""
        return self._invariants.get_invariant(invariant_id)

    def list_invariants(self, category: Optional[str] = None,
                        active_only: bool = False) -> List[dict]:
        """Инварианты по алфавиту: можно отфильтровать по категории и активности.

        По умолчанию отдаются и выключенные: раздел интерфейса должен показывать
        выключенное правило, чтобы его можно было вернуть. Список для промпта и
        проверки берётся отдельно — ``active_invariants``.
        """
        if category:
            return self._invariants.get_invariants_by_category(category)
        return self._invariants.get_all_invariants(active_only=active_only)

    def active_invariants(self) -> List[dict]:
        """Активные инварианты для системного промпта и проверки."""
        return self._invariants.get_all_invariants(active_only=True)

    # --- запись ---
    def create_invariant(self, data: dict) -> dict:
        """Создаёт инвариант из тела запроса (лишние ключи игнорируются)."""
        return self._invariants.add_invariant(
            name=data.get("name"), description=data.get("description"),
            category=data.get("category"), severity=data.get("severity"),
        )

    def update_invariant(self, invariant_id: int, data: dict) -> dict:
        """Меняет переданные поля инварианта (пустое тело — без изменений)."""
        return self._invariants.update_invariant(invariant_id, data)

    def delete_invariant(self, invariant_id: int) -> bool:
        """Удаляет инвариант; ``False`` — правила с таким id не было."""
        return self._invariants.delete_invariant(invariant_id)

    # --- проверка ---
    def check_text(self, text: str, use_llm: bool = True) -> dict:
        """Проверяет текст на нарушение активных инвариантов (словарь схемы API)."""
        checker = InvariantChecker(
            session_factory=self._session_factory,
            client_factory=self._client_factory,
        )
        return checker.check(text, use_llm=use_llm).to_dict()
