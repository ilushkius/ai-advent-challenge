"""Тексты инвариантов: блок промпта, отказ, предупреждение и запрос к LLM (день 14).

Что это.
    Все формулировки, которые видит модель и пользователь, собраны в одном
    модуле: блок активных инвариантов в системном промпте, текст отказа при
    нарушении hard-инварианта, текст предупреждения при нарушении soft и
    сообщение для LLM-проверки текста.

Почему отдельный модуль.
    Литералы проверяются тестами дословно (``tests/unit/test_invariant_prompt.py``),
    а собирать их из разных мест кода — значит ловить расхождение между тем, что
    ушло в промпт, и тем, что показано пользователю. Тот же приём — у блока
    состояния задачи (``backend/domain/task_prompt.py``).

Функции принимают обычные словари (строки из БД или из API) и не знают ни про
сервисные dataclass-ы, ни про транспорт, поэтому модуль чистый.
"""
from typing import List, Sequence

__all__ = [
    "INVARIANTS_FOOTER",
    "INVARIANTS_HEADER",
    "REFUSAL_FOOTER",
    "REFUSAL_HEADER",
    "WARNING_HEADER",
    "invariant_line",
    "render_check_user_message",
    "render_invariants_block",
    "render_violation_refusal",
    "render_violation_warning",
    "violation_line",
]

INVARIANTS_HEADER = "Ты обязан соблюдать следующие инварианты:"
INVARIANTS_FOOTER = (
    "Если запрос пользователя или твоё предлагаемое решение нарушает хотя бы один из них, "
    "ты обязан отказаться и объяснить причину."
)
REFUSAL_HEADER = "Отказ: предложение нарушает инварианты проекта."
REFUSAL_FOOTER = "Предложение не выполнено: измените запрос или обновите список инвариантов."
WARNING_HEADER = "⚠️ Предупреждение: ответ может нарушать soft-инварианты проекта."


def invariant_line(invariant: dict) -> str:
    """Одна строка списка инвариантов: ``- [hard] Имя (architecture): Описание``."""
    return (
        f"- [{invariant.get('severity')}] {invariant.get('name')} "
        f"({invariant.get('category')}): {invariant.get('description')}"
    )


def render_invariants_block(invariants: Sequence[dict]) -> str:
    """Блок системного промпта: заголовок + строки инвариантов + условие отказа.

    Пустая последовательность — пустая строка: агент без инвариантов (или со
    всеми выключенными) получает ровно тот же промпт, что и до дня 14.
    """
    items = list(invariants or ())
    if not items:
        return ""
    lines: List[str] = [INVARIANTS_HEADER]
    lines.extend(invariant_line(item) for item in items)
    lines.append("")
    lines.append(INVARIANTS_FOOTER)
    return "\n".join(lines)


def violation_line(violation: dict) -> str:
    """Строка нарушения: ``- [hard] Имя (architecture): причина``."""
    return (
        f"- [{violation.get('severity')}] {violation.get('name')} "
        f"({violation.get('category')}): {violation.get('reason')}"
    )


def render_violation_refusal(violations: Sequence[dict]) -> str:
    """Текст отказа: заголовок + строки нарушений + что делать дальше."""
    lines: List[str] = [REFUSAL_HEADER]
    lines.extend(violation_line(violation) for violation in violations or ())
    lines.append(REFUSAL_FOOTER)
    return "\n".join(lines)


def render_violation_warning(violations: Sequence[dict]) -> str:
    """Текст предупреждения: заголовок + строки нарушений (ответ предлагается)."""
    lines: List[str] = [WARNING_HEADER]
    lines.extend(violation_line(violation) for violation in violations or ())
    return "\n".join(lines)


def render_check_user_message(text: str, invariants: Sequence[dict]) -> str:
    """Сообщение пользователя для LLM-проверки: список инвариантов и сам текст.

    Список даётся теми же строками, что и блок системного промпта, — модель
    сверяет предложение с теми же формулировками, что видит при генерации.
    """
    lines: List[str] = ["Инварианты:"]
    lines.extend(invariant_line(invariant) for invariant in invariants or ())
    lines.append("")
    lines.append("Проверяемый текст:")
    lines.append(text)
    return "\n".join(lines)
