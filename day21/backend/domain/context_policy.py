"""Чистая арифметика сжатия контекста (день 9).

Что это.
    Задание дня: «храните последние N сообщений как есть; остальное заменяйте
    summary (например, каждые 10 сообщений)». Здесь живёт только арифметика —
    никаких запросов к API, БД и UI:

    - `CompressionPolicy` — настройки: сколько последних реплик оставлять
      (`keep_last`) и через сколько непокрытых реплик запускать суммаризацию
      (`summarize_every`);
    - `plan_compression` — по настройкам и числу непокрытых реплик решает,
      надо ли сжимать, сколько самых старых реплик уйдёт в конспект и сколько
      последних останутся как есть;
    - `split_uncovered` — режет реальную последовательность реплик по плану
      на две части: «в конспект» и «оставить как есть».

    Все dataclass'ы заморожены (`frozen=True`): план и настройки — значения,
    их нельзя случайно изменить по месту.

Как запустить.
    Только стандартная библиотека, побочных эффектов на импорте нет:

        # из папки day9
        python -m pytest -q tests/unit/test_context_policy.py

    Пример:

        policy = CompressionPolicy(keep_last=6, summarize_every=10)
        plan = plan_compression(policy, uncovered_count=16)
        plan.should_compress   # True: backlog = 16 - 6 = 10 >= 10
        plan.summarize_count   # 10 — столько самых старых реплик в конспект
        plan.keep_count        # 6  — столько последних остаются как есть
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Sequence

__all__ = [
    "CompressionPolicy",
    "CompressionPlan",
    "ContextPayload",
    "plan_compression",
    "split_uncovered",
]


@dataclass(frozen=True)
class CompressionPolicy:
    """Настройки сжатия контекста.

    Атрибуты:
        enabled: включено ли сжатие (при `False` история никогда не сжимается).
        keep_last: N — сколько последних непокрытых реплик всегда уходят в
            запрос как есть.
        summarize_every: порог — сжимаем, только если непокрытых реплик
            накопилось не меньше, чем `keep_last + summarize_every`.
    """

    enabled: bool = True
    keep_last: int = 6
    summarize_every: int = 10

    def __post_init__(self) -> None:
        # Проверяем инварианты сразу при создании: политика с keep_last=0 или
        # summarize_every=0 не имеет смысла и молча ломала бы план.
        if self.keep_last < 1:
            raise ValueError(
                f"keep_last должен быть не меньше 1, получено {self.keep_last}"
            )
        if self.summarize_every < 1:
            raise ValueError(
                "summarize_every должен быть не меньше 1, "
                f"получено {self.summarize_every}"
            )

    @classmethod
    def from_dict(cls, data: dict) -> "CompressionPolicy":
        """Собрать политику из словаря (восстановление из БД/API).

        Отсутствующие ключи берутся из значений по умолчанию полей dataclass,
        поэтому словарь может быть частичным.
        """
        defaults = {field.name: field.default for field in fields(cls)}
        values = {name: data.get(name, default) for name, default in defaults.items()}
        return cls(**values)


@dataclass(frozen=True)
class CompressionPlan:
    """Результат планирования: что делать с непокрытой историей.

    Атрибуты:
        should_compress: запускать ли суммаризацию.
        summarize_count: сколько САМЫХ СТАРЫХ непокрытых реплик уйдёт в конспект.
        keep_count: сколько последних непокрытых реплик останутся как есть.
        uncovered_count: сколько непокрытых реплик было на входе (для сверки).
    """

    should_compress: bool
    summarize_count: int
    keep_count: int
    uncovered_count: int


def plan_compression(policy: CompressionPolicy, uncovered_count: int) -> CompressionPlan:
    """Решить, надо ли сжимать историю, и посчитать размеры частей.

    Семантика:
        - `uncovered_count < 0` → `ValueError` (отрицательных реплик не бывает);
        - `backlog = uncovered_count - keep_last` — сколько реплик останется
          «лишними» после того, как последние `keep_last` мы оставим как есть;
        - сжимаем, только если сжатие включено и `backlog >= summarize_every`;
        - при сжатии в конспект уходит ровно `backlog` самых старых реплик,
          а `keep_last` последних остаются как есть;
        - без сжатия в запрос уходит вся непокрытая история
          (`summarize_count=0`, `keep_count=uncovered_count`).
    """
    if uncovered_count < 0:
        raise ValueError(
            f"uncovered_count не может быть отрицательным, получено {uncovered_count}"
        )

    backlog = uncovered_count - policy.keep_last
    should_compress = policy.enabled and backlog >= policy.summarize_every

    if should_compress:
        return CompressionPlan(
            should_compress=True,
            summarize_count=backlog,
            keep_count=policy.keep_last,
            uncovered_count=uncovered_count,
        )

    return CompressionPlan(
        should_compress=False,
        summarize_count=0,
        keep_count=uncovered_count,
        uncovered_count=uncovered_count,
    )


@dataclass(frozen=True)
class ContextPayload:
    """Готовая к отправке история: что уйдёт в конспект и что — как есть.

    Атрибуты:
        to_summarize: кортеж самых старых реплик для нового конспекта.
        to_keep: кортеж последних реплик, которые уходят в запрос дословно.
    """

    to_summarize: tuple
    to_keep: tuple


def split_uncovered(uncovered: Sequence, plan: CompressionPlan) -> ContextPayload:
    """Разрезать непокрытую историю по плану на две части.

    Длина входа обязана совпадать с `plan.uncovered_count` — иначе план и данные
    разошлись, и это явная ошибка (`ValueError`), а не повод молча отрезать
    что-то не то. Вход не мутируется: результат — новые кортежи.
    """
    if len(uncovered) != plan.uncovered_count:
        raise ValueError(
            "Длина истории не совпадает с планом: "
            f"получено {len(uncovered)}, ожидалось {plan.uncovered_count}"
        )

    return ContextPayload(
        to_summarize=tuple(uncovered[: plan.summarize_count]),
        to_keep=tuple(uncovered[plan.summarize_count :]),
    )
