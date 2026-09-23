"""Проверка текста на нарушение инвариантов проекта (день 14): ``InvariantChecker``.

Что это.
    Сервис, который отвечает на вопрос «нарушает ли этот текст правила проекта».
    Порядок проверки — от дешёвого к дорогому: сначала детерминированные правила
    (``backend/domain/invariant_rules.py``, без сети), и только если правила
    молчат — один вызов DeepSeek со списком активных инвариантов. Результат —
    ``InvariantCheckResult``: что проверено, что нарушено, чем проверено и, если
    LLM не отвечал, почему.

Почему отдельный модуль.
    Правила — домен, обращение к модели — прикладная логика: агент и API должны
    получать готовый вердикт, не зная, чем он получен (детерминированным слоем или
    LLM). Сбой внешнего вызова проверку не ломает: вердикт правил остаётся, а
    причина попадает в ``note``, поэтому проверка никогда не «съедает» ход.

Кто кого проверяет.
    ``Agent.generate`` проверяет сначала ЗАПРОС пользователя (детерминированно —
    нарушение hard-инварианта останавливает ход до вызова модели и экономит
    токены), затем ОТВЕТ модели (здесь и работает LLM-слой) и объединяет оба
    вердикта через ``merged_with``: жёсткое нарушение в любом из них побеждает.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger

from ..core import config
from ..domain.invariant_prompt import render_check_user_message
from ..domain.invariant_rules import deterministic_violations
from ..domain.invariant_values import (
    VERDICT_ALLOWED,
    VERDICT_REFUSAL,
    VERDICT_WARNING,
)
from ..storage.invariant_store import InvariantManager

__all__ = [
    "INVARIANT_CHECK_SYSTEM_PROMPT",
    "InvariantCheckResult",
    "InvariantChecker",
    "InvariantViolation",
    "make_checker_client",
]

logger = get_logger(__name__)

# Протокол ответа модели: строгий JSON, потому что разбирать «почти JSON» —
# значит угадывать, какое правило нарушено и нужно ли отказывать.
INVARIANT_CHECK_SYSTEM_PROMPT = (
    "Ты — контролёр инвариантов проекта. Проверь текст на нарушение списка инвариантов "
    "и ответь ТОЛЬКО JSON-объектом вида "
    '{"violations": [{"name": "<имя инварианта>", "reason": "<почему нарушен>"}]}. '
    'Если нарушений нет, ответь {"violations": []}. Никакого текста вокруг JSON.'
)

# Источник нарушения: детерминированное правило или модель (попадает в API и UI).
SOURCE_DETERMINISTIC = "deterministic"
SOURCE_LLM = "llm"


@dataclass(frozen=True)
class InvariantViolation:
    """Одно нарушение: какой инвариант нарушен, насколько жёстко и почему."""

    name: str
    category: str
    severity: str
    reason: str
    source: str

    def to_dict(self) -> dict:
        """Словарь в форме схемы API (``InvariantViolationOut``)."""
        return {
            "name": self.name,
            "category": self.category,
            "severity": self.severity,
            "reason": self.reason,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InvariantViolation":
        """Обратное превращение: словари приходят из детерминированных правил."""
        return cls(
            name=data.get("name", ""),
            category=data.get("category", ""),
            severity=data.get("severity", ""),
            reason=data.get("reason", ""),
            source=data.get("source", SOURCE_DETERMINISTIC),
        )


@dataclass(frozen=True)
class InvariantCheckResult:
    """Итог проверки текста: что проверено, что нарушено, чем проверено."""

    text: str = ""
    checked: List[str] = field(default_factory=list)
    violations: List[InvariantViolation] = field(default_factory=list)
    llm_used: bool = False
    note: str = ""

    @property
    def verdict(self) -> str:
        """Исход проверки: отказ при hard-нарушении, предупреждение при soft."""
        if not self.violations:
            return VERDICT_ALLOWED
        if any(item.severity == "hard" for item in self.violations):
            return VERDICT_REFUSAL
        return VERDICT_WARNING

    def violation_dicts(self) -> List[dict]:
        """Нарушения словарями: их подставляют в тексты отказа и предупреждения."""
        return [item.to_dict() for item in self.violations]

    def to_dict(self) -> dict:
        """Словарь в форме схемы API (``InvariantCheckOut``)."""
        return {
            "checked": list(self.checked),
            "llm_used": self.llm_used,
            "verdict": self.verdict,
            "violations": self.violation_dicts(),
            "note": self.note,
        }

    def merged_with(self, other: "InvariantCheckResult") -> "InvariantCheckResult":
        """Объединяет два вердикта: запрос проверяется до ответа, ответ — после.

        Правила объединения:

        - ``checked`` — имена обоих результатов без повторов (``self`` → ``other``);
        - ``violations`` — сначала нарушения ``self``, затем нарушения ``other``,
          чьё имя инварианта ещё не встречалось: одно правило не должно попадать в
          отказ дважды только потому, что нарушено и в запросе, и в ответе;
        - ``llm_used`` — истина, если модель звали хотя бы раз;
        - ``note`` — первая непустая причина: она и объясняет пропуск LLM-слоя.
        """
        checked = list(self.checked)
        for name in other.checked:
            if name not in checked:
                checked.append(name)
        seen = {item.name for item in self.violations}
        violations = list(self.violations)
        for item in other.violations:
            if item.name not in seen:
                seen.add(item.name)
                violations.append(item)
        return InvariantCheckResult(
            text=other.text or self.text,
            checked=checked,
            violations=violations,
            llm_used=self.llm_used or other.llm_used,
            note=self.note or other.note,
        )


def make_checker_client():
    """Клиент DeepSeek для проверки текста (ключ резолвится в момент вызова).

    Ключ резолвится здесь, а не при создании агента: проверка может случиться в
    любом ходу, а ключ в окружении появляется независимо от старта процесса.
    Без ключа поднимается ``RuntimeError`` с понятным текстом — сервис ловит любое
    исключение и оставляет вердикт правил, поэтому тип исключения не важен.
    """
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day18/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)


def _strip_json_fence(content: str) -> str:
    """Снимает возможные обрамляющие ```json … ``` — иначе разбор всегда падал бы."""
    text = (content or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_violations(content: str, invariants: List[dict]) -> List[InvariantViolation]:
    """Разбирает ответ модели в нарушения (неизвестные имена игнорируются).

    Категория и важность берутся из инварианта, а не из ответа модели: модель
    называет правило, жёсткость правила решает проект.
    """
    payload = json.loads(_strip_json_fence(content))
    if not isinstance(payload, dict) or "violations" not in payload:
        raise ValueError("в ответе нет ключа 'violations'")
    raw = payload["violations"]
    if not isinstance(raw, list):
        raise ValueError("'violations' — не список")

    by_name = {item["name"]: item for item in invariants}
    violations: List[InvariantViolation] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("элемент 'violations' — не объект")
        name = entry.get("name")
        reason = entry.get("reason")
        if not isinstance(name, str) or not isinstance(reason, str):
            raise ValueError("в нарушении нет строковых 'name' и 'reason'")
        invariant = by_name.get(name)
        if invariant is None:
            logger.debug("Модель назвала неизвестный инвариант %r — пропускаю", name)
            continue
        violations.append(InvariantViolation(
            name=invariant["name"],
            category=invariant["category"],
            severity=invariant["severity"],
            reason=reason,
            source=SOURCE_LLM,
        ))
    return violations


class InvariantChecker:
    """Проверка текста на нарушение активных инвариантов проекта.

    Порядок: детерминированные правила, затем (если правил не хватило и
    ``use_llm``) один вызов LLM. Сбой вызова или неразобранный ответ не ломают
    ход: вердикт правил остаётся, причина попадает в ``note``.
    """

    def __init__(self, session_factory=None, client_factory=None) -> None:
        self._session_factory = session_factory
        self._client_factory = client_factory or make_checker_client

    def check(self, text: str, use_llm: Optional[bool] = None,
              invariants: Optional[List[dict]] = None) -> InvariantCheckResult:
        """Проверяет текст; ``invariants`` задают явно в тестах и в скриптах.

        Без активных инвариантов проверка ничего не делает (``checked=[]``,
        вердикт ``allowed``) — поведение агента без правил проекта совпадает с
        днём 13. Пустой текст проверяется «на правилах» без обращения к модели.
        """
        if invariants is None:
            manager = InvariantManager(session_factory=self._session_factory)
            invariants = manager.get_all_invariants(active_only=True)
        checked = [item["name"] for item in invariants]
        if not invariants:
            return InvariantCheckResult(text=text)
        if not text or not text.strip():
            return InvariantCheckResult(text=text, checked=checked)

        violations: List[InvariantViolation] = []
        for invariant in invariants:
            for raw in deterministic_violations(text, invariant):
                violations.append(InvariantViolation.from_dict(raw))
        if violations:
            return InvariantCheckResult(text=text, checked=checked, violations=violations)

        if use_llm is None:
            use_llm = config.INVARIANT_LLM_CHECK
        if not use_llm:
            return InvariantCheckResult(text=text, checked=checked)

        try:
            found = self._ask_llm(text, invariants)
        except Exception as exc:  # сеть, отсутствие ключа, неразобранный ответ
            reason = (
                f"ответ LLM не разобран: {exc}"
                if isinstance(exc, ValueError)
                else f"проверка LLM не выполнена: {exc}"
            )
            logger.debug("Инварианты: %s", reason)
            return InvariantCheckResult(text=text, checked=checked, note=reason)

        return InvariantCheckResult(
            text=text, checked=checked, violations=found, llm_used=True
        )

    def _ask_llm(self, text: str, invariants: List[dict]) -> List[InvariantViolation]:
        """Один вызов модели: список инвариантов и проверяемый текст."""
        client = self._client_factory()
        response = client.chat.completions.create(
            model=config.MODEL_CHAT,
            messages=[
                {"role": "system", "content": INVARIANT_CHECK_SYSTEM_PROMPT},
                {"role": "user", "content": render_check_user_message(text, invariants)},
            ],
            temperature=config.INVARIANT_CHECK_TEMPERATURE,
            max_tokens=config.INVARIANT_CHECK_MAX_TOKENS,
        )
        return _parse_violations(response.choices[0].message.content, invariants)
