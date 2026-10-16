"""Проверки готовности релиза (день 35): тесты, покрытие и файлы документации.

Отдельный модуль, а не метод службы, по двум причинам. Первая: проверки идут
подпроцессами (``uv run pytest`` — десятки секунд), а служба в это время держит
открытое соединение с MCP-сервером и уже собранные тексты релиза — читать это в одном
файле с логикой релиза тяжело. Вторая: их подменяют в тестах и в скрипте прогона
(``--no-checks``), и подменяется ровно одна функция ``run_checks``, а не фрагмент
службы.

Две команды — потому что это два разных ответа на вопрос «готов ли релиз»: тесты
отвечают «код работает», покрытие — «насколько он проверен». Оба прогона идут без
``-m not slow``-исключений наоборот: быстрый набор, никакой сети и никаких живых
API — релиз не должен зависеть от доступности чужих сервисов.

Провал проверки НЕ исключение: результат возвращается данными (``passed: false`` и
заметки), и решение «останавливать ли релиз» принимает вызывающий код. Так ``dry_run``
честно показывает непройденные проверки, а реальный прогон всё равно записывает файлы —
история релиза важнее красной строки отчёта.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from ..core import config
from ..domain import release

__all__ = ["COMMANDS", "FILES", "TAIL_CHARS", "coverage_percent", "default_runner",
           "failed_names", "run_checks"]

#: Команды проверок: имя и аргументы (запускаются в папке дня, где лежит ``pytest.ini``).
COMMANDS = (("tests", ("uv", "run", "pytest", "-m", "not slow", "-q")),
            ("coverage", ("uv", "run", "pytest", "--cov=backend", "--cov-report=term", "-q")))
#: Файлы, наличие которых проверяется: ключ → путь от корня репозитория.
FILES = {"readme": "README.md", "docs": "day21/docs/architecture.md"}
#: Сколько хвоста вывода команды уходит в ответ: ошибка pytest печатается в конце.
TAIL_CHARS = 400


def default_runner(argv: tuple[str, ...], *, cwd: str,
                   timeout: float) -> tuple[int, str, str]:
    """Запускает команду проверки и возвращает ``(код, stdout, stderr)``.

    Отсутствие команды и таймаут — тоже результат (код ``-1`` и текст причины), а не
    исключение: проверка «не выполнилась» и проверка «провалилась» для отчёта одно и
    то же, а подготовка релиза из-за них не встаёт.
    """
    try:
        completed = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=timeout,
                                   check=False)
    except FileNotFoundError as exc:
        return -1, "", f"команда не найдена: {exc}"
    except subprocess.TimeoutExpired as exc:
        return -1, "", f"таймаут {timeout:g} с: {exc}"
    return int(completed.returncode), completed.stdout or "", completed.stderr or ""


def coverage_percent(output: str) -> float | None:
    """Процент покрытия из строк ``TOTAL`` вывода pytest-cov (``None`` — не разобран).

    Берётся ПОСЛЕДНЕЕ совпадение в строке: у ``TOTAL`` перед процентом идут колонки
    ``miss``/``cover``, и первым числом с процентом оказывается покрытие в скобках.
    """
    percent: float | None = None
    for line in str(output or "").splitlines():
        if not line.strip().startswith("TOTAL"):
            continue
        matches = re.findall(r"(\d+(?:\.\d+)?)%", line)
        if matches:
            percent = float(matches[-1])
    return percent


def run_checks(*, runner: Optional[Callable] = None, cwd: Optional[str] = None,
               timeout: Optional[float] = None,
               exists: Optional[Callable[[str], bool]] = None) -> dict:
    """Прогоняет команды проверок и смотрит наличие файлов; отказов не бросает.

    ``cwd`` по умолчанию — папка дня (``config.MCP_FLEET_CWD``): ``uv run`` должен
    видеть ``pytest.ini`` дня. Пути файлов при этом считаются от корня РЕПОЗИТОРИЯ —
    того же, что у инструментов git-истории.
    """
    run = runner or default_runner
    workdir = str(cwd or config.MCP_FLEET_CWD)
    limit = float(timeout if timeout is not None else release.CHECK_TIMEOUT)
    present = exists or _exists
    notes: list[str] = []
    commands: list[dict] = []
    outputs: dict[str, str] = {}
    for name, argv in COMMANDS:
        started = time.perf_counter()
        code, out, err = run(argv, cwd=workdir, timeout=limit)
        outputs[name] = f"{out}{err}"
        commands.append({
            "name": name,
            "command": " ".join(argv),
            "returncode": int(code),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "tail": outputs[name][-TAIL_CHARS:],
        })
    tests_passed = commands[0]["returncode"] == 0
    percent = coverage_percent(outputs.get("coverage", ""))
    if percent is None:
        notes.append(release.CHECKS_MISSING_METRICS)
        percent = 0.0
    files = {key: {"path": rel, "exists": bool(present(rel))}
             for key, rel in FILES.items()}
    readme_exists = files["readme"]["exists"]
    docs_exists = files["docs"]["exists"]
    return {
        "tests_passed": bool(tests_passed),
        "coverage_percent": float(percent),
        "readme_exists": readme_exists,
        "docs_exists": docs_exists,
        "passed": bool(tests_passed and readme_exists and docs_exists),
        "notes": notes,
        "files": files,
        "commands": commands,
    }


def _exists(rel: str) -> bool:
    """Есть ли путь в корне репозитория (``day21/`` — корень папки дня, репозиторий — выше)."""
    root = Path(__file__).resolve().parents[2].parent
    return (root / rel).exists()


def failed_names(checks: dict) -> list[str]:
    """Имена непройденных проверок: проваленные команды и отсутствующие файлы.

    Отдельная функция, потому что эти имена нужны в двух местах: в заметках прогона
    (служба) и в вердикте отчёта (``scripts/demo_release.py``). Считаются они по
    одному правилу — «команда вернула не ноль» и «файла нет».
    """
    failed = [str(command.get("name")) for command in (checks.get("commands") or [])
              if int(command.get("returncode") or 0) != 0]
    for key, value in (checks.get("files") or {}).items():
        if isinstance(value, dict) and not value.get("exists"):
            failed.append(str(value.get("path") or key))
    return failed
