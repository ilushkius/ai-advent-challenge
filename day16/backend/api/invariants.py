"""Роутер API дня 16: инварианты проекта и проверка текста.

Шесть эндпоинтов:

- ``POST   /invariants`` — создать инвариант;
- ``GET    /invariants`` — список (фильтры ``category`` и ``active_only``);
- ``GET    /invariants/{invariant_id}`` — один инвариант;
- ``PUT    /invariants/{invariant_id}`` — изменить переданные поля;
- ``DELETE /invariants/{invariant_id}`` — удалить;
- ``POST   /invariants/check`` — проверить текст на нарушение активных правил.

Контракт ошибок: неизвестный id — 404; занятое имя — 409; неизвестная категория
или важность — 422 (их проверяет домен, роутер только переводит исключение в код);
невалидное тело — 422 от Pydantic.

Инварианты хранятся ОТДЕЛЬНО от диалога — в таблице ``invariants``, не в
сообщениях: список правил не зависит от истории и не «вымывается» сжатием
контекста, а правка правила видна агенту со следующего запроса.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from ..core import dependencies
from ..domain.invariant_values import InvariantValueError
from ..schemas import (
    InvariantCheckIn, InvariantCheckOut, InvariantIn, InvariantOut,
    InvariantUpdateIn,
)
from ..storage.invariant_store import InvariantExistsError, InvariantNotFoundError

router = APIRouter()


# ---------- инварианты (день 14) ----------
@router.post(
    "/invariants",
    response_model=InvariantOut,
    status_code=201,
    summary="Создать инвариант",
    description=(
        "Создаёт правило проекта: имя (уникально), описание, категорию и "
        "важность. Правило сразу активно и попадает в системный промпт агентов "
        "со следующего запроса. Повторное имя — 409, неизвестная категория или "
        "важность — 422."
    ),
)
def create_invariant(body: InvariantIn):
    return _mutate(lambda manager: manager.create_invariant(body.model_dump()))


@router.get(
    "/invariants",
    response_model=List[InvariantOut],
    summary="Список инвариантов",
    description=(
        "Все инварианты по алфавиту имён. `category` фильтрует по категории "
        "(неизвестная — 422), `active_only=true` оставляет только включённые; по "
        "умолчанию видны и выключенные правила — их можно вернуть в работу."
    ),
)
def list_invariants(category: Optional[str] = None, active_only: bool = False):
    return _mutate(lambda manager: manager.list_invariants(
        category=category, active_only=active_only
    ))


@router.get(
    "/invariants/{invariant_id}",
    response_model=InvariantOut,
    summary="Один инвариант",
    description="Инвариант по id; неизвестный id — 404.",
)
def get_invariant(invariant_id: int):
    return dependencies.invariant_or_404(invariant_id)


@router.put(
    "/invariants/{invariant_id}",
    response_model=InvariantOut,
    summary="Изменить инвариант",
    description=(
        "Меняет только переданные поля (`name`, `description`, `category`, "
        "`severity`, `is_active`). Пустое тело не меняет ничего: `updated_at` не "
        "двигается. Неизвестный id — 404, имя занято — 409, неизвестная "
        "категория или важность — 422."
    ),
)
def update_invariant(invariant_id: int, body: InvariantUpdateIn):
    return _mutate(lambda manager: manager.update_invariant(
        invariant_id, body.model_dump(exclude_unset=True)
    ))


@router.delete(
    "/invariants/{invariant_id}",
    summary="Удалить инвариант",
    description=(
        "Удаляет правило из таблицы invariants; неизвестный id — 404. "
        "Выключение без удаления — `PUT /invariants/{id}` с `{\"is_active\": false}`."
    ),
)
def delete_invariant(invariant_id: int):
    deleted = _mutate(lambda manager: manager.delete_invariant(invariant_id))
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Инвариант {invariant_id} не найден"
        )
    return {"id": invariant_id, "deleted": True}


@router.post(
    "/invariants/check",
    response_model=InvariantCheckOut,
    summary="Проверить текст на инварианты",
    description=(
        "Проверяет текст так же, как агент проверяет ход: сначала "
        "детерминированные правила (без сети), и только если они нарушений не "
        "нашли — один вызов LLM (`use_llm=false` отключает его). Вердикт: "
        "`allowed`, `warning` (нарушен soft-инвариант) или `refusal` (hard). "
        "Если активных инвариантов нет — проверять нечего: `checked` пуст."
    ),
)
def check_invariants(body: InvariantCheckIn):
    return _mutate(lambda manager: manager.check_text(
        body.text, use_llm=body.use_llm
    ))


def _mutate(call):
    """Контракт ошибок инвариантов: 404 — нет id, 409 — имя занято, 422 — значение."""
    try:
        return call(dependencies.get_manager())
    except InvariantNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvariantExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvariantValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
