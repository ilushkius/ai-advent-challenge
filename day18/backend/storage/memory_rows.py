"""ORM-строки памяти → словари для API/UI (единственное место с ORM в этом слое).

Чистые правила слоёв памяти (категории, отбор релевантного, тексты блоков)
живут в ``backend/domain/memory_layers.py`` и ничего не знают про SQLAlchemy;
здесь — три преобразования «ORM-строка → dict», которые нужны хранилищу
(``backend/agents/memory.py``), поэтому им место в слое доступа к БД.
"""

from ..models.memory import LongTermMemory, WorkingMemory
from ..models.message import ShortTermMessage


def _short_term_dict(row: ShortTermMessage) -> dict:
    """ORM-строка краткосрочного слоя → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content,
        "created_at": row.created_at,
    }


def _working_dict(row: WorkingMemory) -> dict:
    """ORM-строка рабочей памяти → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "task_id": row.task_id,
        "key": row.key,
        "value": row.value,
        "updated_at": row.updated_at,
    }


def _long_term_dict(row: LongTermMemory) -> dict:
    """ORM-строка долговременной памяти → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "category": row.category,
        "key": row.key,
        "value": row.value,
        "confidence": row.confidence,
        "updated_at": row.updated_at,
    }
