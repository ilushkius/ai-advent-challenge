"""Diff файла относительно ``HEAD``: git и синтез для нового файла (день 34).

Модуль вынесен из ``tools.py``, потому что diff — не операция с файлом, а работа с
git: две команды, разбор кода возврата и сборка diff-а для файла, которого git ещё
не знает. Инструменты (``tools.py``) вызывают три функции отсюда, а правило «что
делать с неотслеживаемым файлом» живёт в одном месте.

Почему не ``git diff`` для всего. ``git diff HEAD`` показывает изменения
ОТСЛЕЖИВАЕМЫХ файлов, поэтому только что созданный файл (обычный результат дня 34 —
новый ADR) вернул бы пустоту, и в отчёте прогона у сценария создания не было бы
diff-а. Поэтому у добавленного файла diff синтезируется из его строк через
``difflib.unified_diff``: формат тот же, что у git, и читается он так же.

``errors="replace"`` не даёт упасть на выводе с чужой кодировкой (git может вернуть
пути в CP1251), а таймаут важнее полноты: подвисшая команда оставила бы вызов
инструмента без ответа.
"""
from __future__ import annotations

import difflib
import subprocess

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.file_server import config

__all__ = ["git_diff", "is_tracked", "synthetic_diff"]


def is_tracked(rel: str) -> bool:
    """Отслеживает ли git файл (``ls-files --error-unmatch``, код 1 — не отслеживает).

    ``git ls-files`` возвращает 1, когда файла нет в индексе, — это ШТАТНЫЙ ответ,
    а не сбой команды, поэтому ``CalledProcessError`` здесь не поднимается: иначе
    созданный файл («есть на диске, но не в индексе») заканчивался бы ошибкой
    инструмента вместо diff-а.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel],
            cwd=config.REPO_ROOT, capture_output=True, text=True,
            encoding=config.ENCODING, errors="replace", timeout=config.GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"git не сработал: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"git не сработал: таймаут {config.GIT_TIMEOUT:g} с") from exc
    if completed.returncode not in (0, 1):
        raise ToolError(f"git не сработал: {str(completed.stderr or '').strip()}")
    return completed.returncode == 0


def git_diff(rel: str) -> str:
    """Unified diff отслеживаемого файла относительно ``HEAD`` (путь от корня репозитория).

    Пустая строка означает «файл не менялся»: решение о тексте ``config.NO_CHANGES``
    принимает инструмент, потому что это формулировка для модели, а не свойство git.
    """
    return _git("diff", "--no-color", "HEAD", "--", rel).strip()


def synthetic_diff(rel: str, text: str) -> str:
    """Diff добавленного файла: шапка ``new file mode`` плюс ``unified_diff`` из пустоты."""
    body = list(difflib.unified_diff([], text.splitlines(), fromfile="/dev/null",
                                     tofile=f"b/{rel}", lineterm=""))
    return "\n".join([f"diff --git a/{rel} b/{rel}", "new file mode 100644", *body])


def _git(*args: str) -> str:
    """Вывод команды git в корне репозитория; сбой — ``ToolError``."""
    try:
        completed = subprocess.run(
            ["git", *args], cwd=config.REPO_ROOT, capture_output=True, text=True,
            encoding=config.ENCODING, errors="replace", check=True,
            timeout=config.GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"git не сработал: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"git не сработал: таймаут {config.GIT_TIMEOUT:g} с") from exc
    except subprocess.CalledProcessError as exc:
        stderr = str(exc.stderr or "").strip()
        raise ToolError(f"git не сработал: {stderr or exc}") from exc
    return completed.stdout or ""
