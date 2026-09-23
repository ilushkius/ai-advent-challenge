"""Детерминированные правила проверки инвариантов (день 14).

Что это.
    Первый и самый дешёвый слой ``InvariantChecker``: правила «средство/риск из
    описания инварианта → то же средство в проверяемом тексте». Правила ищут
    признаки прямо в тексте и не обращаются ни к сети, ни к БД, поэтому
    проверяются модульными тестами (``tests/unit/test_invariant_rules.py``).

Почему отдельный модуль.
    Проверка инварианта — доменное правило, а не транспорт и не хранение:
    тексты для промпта живут в ``invariant_prompt.py``, значения — в
    ``invariant_values.py``, а здесь только сопоставление строк. Сервис
    (``backend/services/invariant_checker.py``) вызывает
    ``deterministic_violations`` и лишь при молчании правил идёт в LLM.

Как правило привязывается к инварианту.
    ``gate`` ищется в ОПИСАНИИ инварианта: правило действует, только если сам
    инвариант упоминает это средство («Только Python, без JavaScript-фреймворков»
    включает правило JavaScript, а «Состояние задачи в SQLite» — нет). ``signal``
    ищется в проверяемом тексте, ``exclude`` снимает нарушение — например,
    явное согласие пользователя для бизнес-правила о платных сервисах.

Границы применимости.
    Правила намеренно консервативны: они ловят упоминание средства, а не смысл
    предложения, поэтому «не используем React» тоже даст сигнал. Точные,
    семантические случаи разбирает LLM-слой того же сервиса, и только он
    вызывается, когда правила молчат.
"""
import re
from dataclasses import dataclass
from typing import List, Optional

from .invariant_values import InvariantCategory

__all__ = [
    "DETERMINISTIC_RULES",
    "PAID_SERVICES_RULE",
    "TERM_EXPLANATION",
    "DeterministicRule",
    "deterministic_violations",
]


@dataclass(frozen=True)
class DeterministicRule:
    """Правило «признак инварианта → сигнал в тексте».

    ``gate`` — что ищем в ОПИСАНИИ инварианта, чтобы правило к нему привязалось;
    ``signal`` — что ищем в проверяемом тексте; ``exclude`` — если найдено,
    нарушения нет (например, согласие пользователя снимает нарушение).
    ``explanation`` — шаблон причины с подстановками ``{label}`` и ``{name}``.
    """

    category: str
    label: str
    gate: re.Pattern
    signal: re.Pattern
    explanation: str
    exclude: Optional[re.Pattern] = None


# Причина для правил-терминов: в тексте упомянуто средство, запрещённое инвариантом.
TERM_EXPLANATION = "текст упоминает {label}, а инвариант «{name}» это запрещает"

# Правило бизнес-правил: платный вариант допустим только с явного согласия
# пользователя. В отличие от правил-терминов, у него разные gate и signal, и есть
# exclude: нарушение снимается, только если согласие выражено утвердительно
# («если пользователь согласен», «согласие получено»). Отрицание («согласие
# пользователя не нужно») согласием не считается — это и есть нарушение.
PAID_SERVICES_RULE = DeterministicRule(
    category=InvariantCategory.BUSINESS_RULES.value,
    label="платный вариант",
    gate=re.compile(r"платн|подписк", re.IGNORECASE),
    signal=re.compile(r"платн|подписк|premium|\bpaid\b", re.IGNORECASE),
    explanation=(
        "текст предлагает платный вариант без явного согласия пользователя, "
        "а инвариант «{name}» это запрещает"
    ),
    exclude=re.compile(
        r"(согласи\w*|разрешени\w*|одобрени\w*)\s+\w+\s+(получен\w*|есть|дано|имеется)"
        r"|пользовател\w*\s+соглас\w*"
        r"|\bconsent given\b",
        re.IGNORECASE,
    ),
)


def _term_rule(category: InvariantCategory, label: str, pattern: str) -> DeterministicRule:
    """Правило-термин: одно и то же выражение и в описании инварианта, и в тексте."""
    compiled = re.compile(pattern, re.IGNORECASE)
    return DeterministicRule(
        category=category.value,
        label=label,
        gate=compiled,
        signal=compiled,
        explanation=TERM_EXPLANATION,
    )


# Порядок правил — порядок категорий и средств; он же порядок строк в отчёте.
DETERMINISTIC_RULES: tuple[DeterministicRule, ...] = (
    _term_rule(InvariantCategory.ARCHITECTURE, "Flask", r"\bflask\b"),
    _term_rule(InvariantCategory.ARCHITECTURE, "Django", r"\bdjango\b"),
    _term_rule(InvariantCategory.ARCHITECTURE, "Bottle", r"\bbottle\b"),
    _term_rule(InvariantCategory.ARCHITECTURE, "Tornado", r"\btornado\b"),
    _term_rule(InvariantCategory.TECH_DECISIONS, "Redis", r"\bredis\b"),
    _term_rule(InvariantCategory.TECH_DECISIONS, "Memcached", r"\bmemcached\b"),
    _term_rule(InvariantCategory.TECH_DECISIONS, "MongoDB", r"\bmongo\s?db\b"),
    _term_rule(InvariantCategory.TECH_DECISIONS, "Kafka", r"\bkafka\b"),
    _term_rule(InvariantCategory.STACK_CONSTRAINTS, "JavaScript", r"\bjavascript\b"),
    _term_rule(InvariantCategory.STACK_CONSTRAINTS, "Node.js", r"\bnode\.?js\b"),
    _term_rule(InvariantCategory.STACK_CONSTRAINTS, "TypeScript", r"\btypescript\b"),
    _term_rule(InvariantCategory.STACK_CONSTRAINTS, "React", r"\breact\b"),
    _term_rule(InvariantCategory.STACK_CONSTRAINTS, "Vue", r"\bvue(\.?js)?\b"),
    _term_rule(InvariantCategory.STACK_CONSTRAINTS, "Angular", r"\bangular\b"),
    PAID_SERVICES_RULE,
)


def deterministic_violations(text: str, invariant: dict) -> List[dict]:
    """Нарушения одного инварианта по детерминированным правилам.

    Пустой список — нарушений нет. Словари — в форме схемы API
    (``{"name", "category", "severity", "reason", "source": "deterministic"}``),
    поэтому сервис проверки кладёт их в ``InvariantCheckResult`` без маппинга.

    Правило применяется, если совпала категория, ``gate`` найден в описании
    инварианта, ``exclude`` в тексте не найден, а ``signal`` — найден. Пустой
    текст или инвариант без описания нарушением не считается.
    """
    if not text or not text.strip():
        return []
    description = invariant.get("description") or ""
    category = invariant.get("category") or ""
    if not description.strip() or not category:
        return []

    violations: List[dict] = []
    for rule in DETERMINISTIC_RULES:
        if rule.category != category:
            continue
        if rule.gate.search(description) is None:
            continue
        if rule.exclude is not None and rule.exclude.search(text) is not None:
            continue
        if rule.signal.search(text) is None:
            continue
        violations.append(
            {
                "name": invariant.get("name") or "",
                "category": category,
                "severity": invariant.get("severity") or "",
                "reason": rule.explanation.format(
                    label=rule.label, name=invariant.get("name") or ""
                ),
                "source": "deterministic",
            }
        )
    return violations
