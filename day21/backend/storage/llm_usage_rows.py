"""ORM-строки журнала расходов → словари для API/UI (день 21).

Преобразование живёт здесь, а не в хранилище: одну и ту же форму записи видят
статистика (``LLMUsageStore.stats``), вкладка «Расходы», логирование cache_hit/
cache_miss и отчёт об оптимизации — и второй экземпляр преобразования неизбежно
разошёлся бы с первым (та же причина, что у ``index_rows.py``).

Метки времени приводит к UTC-aware ``as_utc`` из ``scheduler_rows``: SQLite хранит
наивные значения, и без приведения один и тот же момент читался бы то как UTC, то
как локальное время. Отдельная копия помощника была бы копированием.

Числа дня (``cost_estimate``) не округляются здесь: округление — дело того, кто
считает метрику (формула в ``domain/llm_cost.py`` кладёт уже округлённое значение),
а словарь отдаёт записанное как есть.
"""
from __future__ import annotations

from typing import Any

from ..models.llm_usage import LLMUsage
from .scheduler_rows import as_utc

__all__ = ["llm_usage_dict"]


def llm_usage_dict(row: LLMUsage) -> dict[str, Any]:
    """Строка журнала расходов для API/UI: токены, кэш, цена и тип запроса."""
    moment = as_utc(row.timestamp)
    created = as_utc(row.created_at)
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "timestamp": moment.isoformat() if moment else None,
        "model": row.model,
        "prompt_tokens": int(row.prompt_tokens or 0),
        "completion_tokens": int(row.completion_tokens or 0),
        "cache_hit_tokens": int(row.cache_hit_tokens or 0),
        "cache_miss_tokens": int(row.cache_miss_tokens or 0),
        "cost_estimate": float(row.cost_estimate or 0.0),
        "request_type": row.request_type,
        "created_at": created.isoformat() if created else None,
    }
