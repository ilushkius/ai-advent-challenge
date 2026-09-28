"""Фейки и утилиты тестов планировщика (день 18).

Три вещи, без которых тесты дня либо ходили бы в сеть, либо зависели от таймеров:

- ``FakeFetcher`` — детерминированный «внешний API»: очередь ответов, запись
  вызовов и режим ошибки. Через него проверяется и первый сбор, и повторный тик,
  и сбой источника (``SourceFetchError`` без сети);
- ``posts_payload`` — ответ в форме jsonplaceholder: он же служит материалом для
  проверки агрегации;
- ``SchedulerStub`` — планировщик без APScheduler: тот же публичный контракт
  ``TaskScheduler``, но ``start``/``shutdown`` — no-op, а ``register``/``run_tick``
  делегируют настоящему ``TaskScheduler`` без запущенных таймеров. Им подменяется
  ``main.get_scheduler`` в e2e-тестах, поэтому TestClient не заводит фоновых
  задач, а поведение (запись расписания, журнал запусков) остаётся настоящим.
"""
from __future__ import annotations

from typing import Any, Optional

from backend.services.scheduler import TaskScheduler
from backend.services.source_fetch import SourceFetchError

__all__ = ["FakeFetcher", "SchedulerStub", "posts_payload"]


def posts_payload(count: int = 3, user_id: int = 1) -> list[dict[str, Any]]:
    """Ответ-список постов в форме jsonplaceholder (поля id, userId, title, body)."""
    return [
        {"id": index, "userId": user_id, "title": f"post {index}",
         "body": f"тело поста {index}"}
        for index in range(1, count + 1)
    ]


class FakeFetcher:
    """Фейковый источник данных: очередь ответов вместо HTTP-запроса.

    ``answers`` задаётся при создании (или остаётся пустой — тогда каждый вызов
    отдаёт ``posts_payload``). ``fail_with`` включает режим ошибки: вызовы
    считаются, но данных не отдают — так проверяется путь «сбор упал, задача
    осталась активной».
    """

    def __init__(self, answers: Optional[list[Any]] = None,
                 fail_with: Optional[str] = None) -> None:
        self._answers = list(answers or [])
        self._fail_with = fail_with
        self.calls: list[str] = []

    @property
    def call_count(self) -> int:
        """Сколько раз источник запрашивали."""
        return len(self.calls)

    def __call__(self, url: str, *_args, **_kwargs) -> Any:
        """Возвращает следующий ответ или падает с ``SourceFetchError``."""
        self.calls.append(url)
        if self._fail_with:
            raise SourceFetchError(self._fail_with)
        if self._answers:
            return self._answers.pop(0)
        return posts_payload(2 + len(self.calls) % 3)

    def push(self, payload: Any) -> None:
        """Добавляет ответ в конец очереди (порядок вызовов предсказуем)."""
        self._answers.append(payload)

    def fail(self, reason: str) -> None:
        """Включает режим ошибки источника."""
        self._fail_with = reason


class SchedulerStub:
    """Планировщик без таймеров: контракт ``TaskScheduler``, но без APScheduler.

    ``start`` и ``shutdown`` ничего не делают, остальное делегируется настоящему
    ``TaskScheduler``: расписание считается и пишется в БД, тики исполняются по
    требованию (``run_tick``), а фоновых задач в тестах не появляется.
    """

    def __init__(self, scheduler: TaskScheduler) -> None:
        self._scheduler = scheduler
        self.started = False

    @property
    def inner(self) -> TaskScheduler:
        """Настоящий планировщик, которому делегируются операции."""
        return self._scheduler

    @property
    def running(self) -> bool:
        """Заглушка «работает» ровно после ``start`` (для честного статуса)."""
        return self.started

    def start(self) -> None:
        """Ничего не запускает: таймеры в тестах не нужны."""
        self.started = True

    def shutdown(self) -> None:
        """Ничего не останавливает."""
        self.started = False

    def status(self) -> dict[str, Any]:
        """Статус настоящего планировщика с честным признаком «запущен»."""
        return {**self._scheduler.status(), "running": self.started}

    def __getattr__(self, name: str):
        """Любая другая операция (register/pause/resume/run_tick) — у настоящего."""
        return getattr(self._scheduler, name)
