"""Роутер API дня 14: профили пользователей и профиль агента.

Эндпоинты перенесены из монолитного ``backend/main.py`` дословно (пути, тексты
описаний, коды ответов): изменений логики нет, добавлен только префикс
``@router.`` и обращение к менеджеру через ``backend.core.dependencies``.
"""
from typing import List

from fastapi import APIRouter, HTTPException

from ..core import dependencies
from ..schemas import (
    AppliedProfileOut, UserProfileDeleteOut, UserProfileIn, UserProfileOut,
)
from ..agents.profile_store import ProfileExistsError, ProfileNotFoundError

router = APIRouter()


# ---------- персонализация: профили пользователей (день 12) ----------
@router.get(
    "/users",
    response_model=List[UserProfileOut],
    summary="Список профилей пользователей",
    description=(
        "Все профили из таблицы user_profiles: настройки, ограничения, "
        "произвольные инструкции и однострочное описание (поле summary). "
        "Используется селектором пользователя в интерфейсе."
    ),
)
def list_users():
    return dependencies.get_manager().list_user_profiles()


@router.get(
    "/users/{user_id}/profile",
    response_model=UserProfileOut,
    summary="Профиль пользователя",
    description=(
        "Профиль по user_id: preferences (tone/verbosity/language/format), "
        "constraints (max_response_length/forbidden_topics/required_disclaimers) "
        "и custom_instructions. Если профиля нет — 404."
    ),
)
def get_user_profile(user_id: str):
    profile = dependencies.get_manager().get_user_profile(user_id)
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"Профиль пользователя {user_id} не найден"
        )
    return profile


@router.post(
    "/users/{user_id}/profile",
    response_model=UserProfileOut,
    status_code=201,
    summary="Создать профиль пользователя",
    description=(
        "Создаёт профиль. Если профиль с таким user_id уже есть — 409. "
        "Незаполненные поля означают «не персонализировать» и в промпт не "
        "попадают. Если у пользователя уже есть агенты, профиль применяется к "
        "ним сразу (applied_to_agents)."
    ),
)
def create_user_profile(user_id: str, body: UserProfileIn):
    try:
        return dependencies.get_manager().create_user_profile(user_id, body.model_dump())
    except ProfileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put(
    "/users/{user_id}/profile",
    response_model=UserProfileOut,
    summary="Обновить профиль пользователя",
    description=(
        "Заменяет настройки профиля целиком (created_at сохраняется, "
        "updated_at обновляется). Профиль обязателен: если его нет — 404 "
        "(создавайте через POST). Живые агенты пользователя получают новые "
        "настройки немедленно: поле applied_to_agents — сколько агентов "
        "обновлено."
    ),
)
def update_user_profile(user_id: str, body: UserProfileIn):
    try:
        return dependencies.get_manager().update_user_profile(user_id, body.model_dump())
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/users/{user_id}/profile",
    response_model=UserProfileDeleteOut,
    summary="Удалить профиль пользователя",
    description=(
        "Удаляет профиль; агенты пользователя остаются, но теряют "
        "персонализацию (профиль считается пустым). Если профиля нет — 404."
    ),
)
def delete_user_profile(user_id: str):
    if not dependencies.get_manager().delete_user_profile(user_id):
        raise HTTPException(
            status_code=404, detail=f"Профиль пользователя {user_id} не найден"
        )
    return {"status": "deleted", "user_id": user_id}


@router.get(
    "/agents/{agent_id}/profile",
    response_model=AppliedProfileOut,
    summary="Профиль, применяемый к запросам агента",
    description=(
        "Профиль пользователя агента и его вклад в системный промпт: "
        "elements — по элементам (обращение, стиль, формат, длина, ограничения, "
        "инструкции), prompt_block — блок персонализации, system_prompt — "
        "системное сообщение без блоков памяти текущего запроса."
    ),
)
def get_agent_profile(agent_id: str):
    dependencies.agent_or_404(agent_id)
    return dependencies.get_manager().get_agent_profile(agent_id)
