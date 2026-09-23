"""Печать проверок прогона кадров дня 17: ``VideoChecks`` и отчёт о финале.

Что это.
    Слой отчёта, общий для всех режимов прогона: ``--all`` (AppTest), ``--auto``
    (браузер), ``--ui`` (стенд), а также для кадров движения по HTTP
    (``video_scenario_frames.move``). Проверка печатает ``✓`` с доказательством
    или ``✗`` с тем, что получилось, и останавливает прогон исключением
    ``ScenarioFailed`` — поэтому расхождение кода и кадра видно в выводе и в коде
    возврата, а не «прошло молча».

Почему отдельный модуль, а не часть точки входа.
    Точка входа запускается как ``__main__``, поэтому её импорт по имени
    (``from video_scenario import …``) создаёт ВТОРУЮ копию модуля: исключение
    из копии не ловится ``except`` в ``__main__``, и падение печаталось
    трассировкой вместо строки «✗ прогон остановлен». Общие классы живут здесь и
    импортируются всеми режимами как один и тот же объект.
"""
from typing import Any


class ScenarioFailed(Exception):
    """Расхождение кода и кадра: прогон останавливается с кодом возврата 1."""


def short(text: str, limit: int = 120) -> str:
    """Обрезка доказательства одной строкой: вывод остаётся читаемым."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


class VideoChecks:
    """Печать кадров и проверок; расхождение останавливает прогон."""

    def __init__(self) -> None:
        self.frames = 0
        self.checks = 0

    def frame(self, number: int, title: str) -> None:
        """Заголовок кадра (нумерация — как в §8 инструкции)."""
        self.frames += 1
        print(f"\n=== Кадр {number} — {title} ===", flush=True)

    def final(self) -> None:
        """Последний блок прогона: в сводке он считается кадром."""
        self.frames += 1
        print("\n=== Финал ===", flush=True)

    def check(self, label: str, ok: bool, evidence: str = "") -> None:
        """Проверка кадра: ``✓`` с доказательством либо ``✗`` и остановка."""
        self.checks += 1
        if ok:
            suffix = f" · {short(evidence)}" if evidence else ""
            print(f"  ✓ {label}{suffix}", flush=True)
            return
        print(f"  ✗ {label} · получено: {short(evidence, 400)}", flush=True)
        raise ScenarioFailed(label)


def summary(checks: VideoChecks, backend: Any, first_pid: int) -> None:
    """Финал: сколько кадров и проверок пройдено и на какой БД шёл прогон.

    ``backend`` — процесс бэкенда прогона (``video_scenario_server.Backend``):
    нужны только его ``pid`` и ``port``, поэтому тип не проверяется.
    """
    checks.final()
    print(f"Все кадры пройдены: {checks.frames}, проверок: {checks.checks}")
    print(f"бэкенд: процесс 1 (pid {first_pid}) и процесс 2 (pid {backend.pid}), "
          f"порт {backend.port}")
    print(f"БД прогона: {backend.db.name}; agents.db не изменялся")
