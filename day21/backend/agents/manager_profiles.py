"""Миксин профилей пользователей (день 12): CRUD и раздача профиля агентам.

Часть ``AgentManager`` (``backend/agent_manager.py``): профиль хранится в
``ProfileStore``, а живые агенты пользователя получают его немедленно
(``Agent.apply_profile``), поэтому следующий запрос уже использует новые
настройки.
"""
from typing import List, Optional

from .agent import Agent
from .profile_store import (
    ProfileData, ProfileNotFoundError, ProfileStore, empty_profile,
)


class ProfileOpsMixin:
    """CRUD профилей пользователей и раздача профиля живым агентам."""

    # --- профили пользователей (день 12) ---
    def profile_store(self) -> ProfileStore:
        """Хранилище профилей на той же фабрике сессий, что и агенты."""
        return ProfileStore(session_factory=self._session_factory)

    def _agents_of_user(self, user_id: str) -> List[Agent]:
        """Живые агенты пользователя (чтобы применить профиль без рестарта)."""
        with self._lock:
            return [
                agent for agent in self._agents.values()
                if agent.user_id == user_id
            ]

    @staticmethod
    def _profile_kwargs(profile_data: Optional[dict]) -> dict:
        """Данные профиля из тела запроса → именованные аргументы хранилища."""
        data = dict(profile_data or {})
        unknown = sorted(
            set(data) - {"name", "preferences", "constraints", "custom_instructions"}
        )
        if unknown:
            raise ValueError(
                "неизвестные поля профиля: " + ", ".join(unknown)
            )
        return {
            "name": data.get("name") or "",
            "preferences": data.get("preferences"),
            "constraints": data.get("constraints"),
            "custom_instructions": data.get("custom_instructions") or "",
        }

    def _apply_profile_to_agents(self, data: ProfileData) -> int:
        """Раздаёт профиль живым агентам пользователя; возвращает их число."""
        agents = self._agents_of_user(data.user_id)
        for agent in agents:
            agent.apply_profile(data)
        return len(agents)

    def get_user_profile(self, user_id: str) -> Optional[dict]:
        """Профиль пользователя или None, если профиля нет (API отвечает 404)."""
        data = self.profile_store().get(user_id)
        return data.as_dict() if data is not None else None

    def require_user_profile(self, user_id: str) -> ProfileData:
        """Профиль или ``ProfileNotFoundError`` (для API-слоя и скриптов)."""
        data = self.profile_store().get(user_id)
        if data is None:
            raise ProfileNotFoundError(
                f"Профиль пользователя {user_id} не найден"
            )
        return data

    def create_user_profile(self, user_id: str,
                            profile_data: Optional[dict] = None) -> dict:
        """Создаёт профиль пользователя (``ProfileExistsError`` при дубле).

        Профиль сразу раздаётся живым агентам пользователя: если агент уже
        создан, персонализация включается со следующего запроса, перезапуск не
        нужен.
        """
        data = self.profile_store().create(
            user_id, **self._profile_kwargs(profile_data)
        )
        self._apply_profile_to_agents(data)
        return data.as_dict()

    def update_user_profile(self, user_id: str,
                            profile_data: Optional[dict] = None) -> dict:
        """Заменяет настройки профиля (``ProfileNotFoundError``, если нет).

        Возвращает обновлённый профиль; живые агенты пользователя получают его
        немедленно, поэтому «профиль можно изменить в любой момент».
        """
        data = self.profile_store().update(
            user_id, **self._profile_kwargs(profile_data)
        )
        applied = self._apply_profile_to_agents(data)
        result = data.as_dict()
        result["applied_to_agents"] = applied
        return result

    def delete_user_profile(self, user_id: str) -> bool:
        """Удаляет профиль; агенты пользователя теряют персонализацию.

        False — профиля не было. Агенты НЕ удаляются: они остаются с пустым
        профилем (персонализация выключена) и отвечают как обычно.
        """
        deleted = self.profile_store().delete(user_id)
        if deleted:
            blank = empty_profile(user_id)
            for agent in self._agents_of_user(user_id):
                agent.apply_profile(blank)
        return deleted

    def list_user_profiles(self) -> List[dict]:
        """Все профили пользователей (для селектора в интерфейсе)."""
        return [data.as_dict() for data in self.profile_store().list_all()]

    def get_agent_profile(self, agent_id: str) -> dict:
        """Профиль, применяемый к запросам агента: настройки + вклад в промпт."""
        return self.require_agent(agent_id).profile_state()
