"""Git-история проекта для ассистента релиза (день 35): пять инструментов чтения.

Модуль отделён от ``tools.py`` по двум причинам: тот файл стоит ровно на пределе 400
строк, а предмет здесь другой — ``tools.py`` работает с файлами внутри ``--file-root``,
а эти пять инструментов читают ИСТОРИЮ репозитория и файлов не трогают. Всё, что они
делают, — только чтение: ни тегов, ни веток, ни индекса они не меняют, поэтому
``dry_run`` на них не распространяется (см. службу релиза).

Корень репозитория берётся из ``config.REPO_ROOT``, а не из ``--file-root``: теги,
коммиты и метрики проекта описывают репозиторий целиком, и рабочая область файловых
инструментов их не сужает. Один вызов ``subprocess`` на все инструменты — общий
``diffing.run_git``: та же кодировка, тот же таймаут, тот же разбор кода возврата.

Два инструмента прощают незнакомый ref, потому что вызывающий их собирает теги из
``get_tags``, а до первого тега проекта (``day1``, которого в репозитории нет) релиз
всё равно нужен: диапазон с неизвестным началом читается как «вся история». Границы
аргументов (``REF_MAX``, ``MAX_RELEASE_*``) объявлены в ``config`` и проверяются
здесь: длинный ref — ошибка инструмента, а обрезка длинной выдачи — штатное поведение.
"""
from __future__ import annotations

import re
import subprocess

from mcp.server.mcpserver.exceptions import ToolError

# ``config`` импортируется ДО ``shared``: он добавляет корень репозитория в
# ``sys.path``, и только после этого общий пакет ``shared/`` находится при запуске
# сервера файлом (тот же приём, что в ``server.py`` и ``diffing.py``).
from mcp_servers.file_server import config
from mcp_servers.file_server.diffing import run_git

from shared.logging_utils import get_logger

logger = get_logger(__name__)

__all__ = ["get_changed_files_between", "get_commit_stats", "get_commits_between",
           "get_project_metrics", "get_tags"]


def _rev(ref: str) -> str | None:
    """Хеш коммита по ref или ``None``, если такого ref нет (длинный ref — ошибка).

    Отсутствие ref — ШТАТНЫЙ ответ: ``git rev-parse --quiet`` возвращает код 1, когда
    имени не существует, и решение «чем заменить» принимает ``_resolve``.
    """
    name = str(ref or "").strip()
    if not name:
        return None
    if len(name) > config.REF_MAX:
        raise ToolError(f"Реф длиннее {config.REF_MAX} символов: {name[:30]}…")
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"],
            cwd=config.REPO_ROOT, capture_output=True, text=True,
            encoding=config.ENCODING, errors="replace", timeout=config.GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"git не сработал: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"git не сработал: таймаут {config.GIT_TIMEOUT:g} с") from exc
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip() or None


def _resolve(from_tag: str, to_tag: str) -> tuple[str | None, str]:
    """Границы диапазона: незнакомый ref начала — ``None`` (вся история), конца — ``HEAD``.

    Подмена видна только в журнале сервера: инструмент отвечает данными, а пометку
    «тега нет» ставит служба релиза, сравнивая запрошенные теги со списком ``get_tags``.
    """
    start = _rev(from_tag)
    if start is None:
        logger.warning("get_commits_between: ref %r не найден, взята вся история",
                       str(from_tag or "").strip() or None)
    end = _rev(to_tag)
    if end is None:
        end = "HEAD"
        logger.warning("get_commits_between: ref %r не найден, взято HEAD",
                       str(to_tag or "").strip() or None)
    return start, end


def _range(start: str | None, end: str) -> str:
    """Диапазон для git: без известного начала — вся история до ``end`` включительно."""
    return f"{start}..{end}" if start else end


def get_tags() -> list[dict]:
    """Теги репозитория с датами и коммитами (пустой список — тегов нет).

    Порядок — по дате создания от новых к старым: так список раздела интерфейса
    начинается с самого свежего тега. Разделитель полей — служебный символ ``\\x1f``
    в самом шаблоне, а не ``%x1f``: язык ``for-each-ref`` подстановок ``%xx`` не знает
    и печатал бы их буквально.
    """
    raw = run_git("for-each-ref", "--sort=-creatordate",
                  "--format=%(refname:short)\x1f%(creatordate:iso-strict)"
                  "\x1f%(objectname:short)", "refs/tags")
    tags: list[dict] = []
    for line in raw.splitlines():
        fields = line.split("\x1f")
        if len(fields) != 3 or not fields[0].strip():
            if line.strip():
                logger.warning("get_tags: строка тега не разобрана: %r", line)
            continue
        name, date, commit = (field.strip() for field in fields)
        tags.append({"name": name, "date": date, "commit": commit})
    return tags


def get_commits_between(from_tag: str, to_tag: str) -> list[dict]:
    """Коммиты диапазона ``from_tag..to_tag`` (новые сверху) с заголовком и текстом.

    Слияния не возвращаются (``--no-merges``): их заголовок — «Merge …», и в CHANGELOG
    он ничего не добавляет. Пустой диапазон — пустой список, а не ошибка. Длина
    ограничена ``config.MAX_RELEASE_COMMITS``.
    """
    start, end = _resolve(from_tag, to_tag)
    raw = run_git("log", "--no-merges", _range(start, end),
                  "--format=%h%x1f%an%x1f%ad%x1f%s%x1f%b%x1e", "--date=iso-strict")
    commits: list[dict] = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        fields = record.split("\x1f")
        if len(fields) < 4:
            logger.warning("get_commits_between: запись коммита не разобрана: %r",
                           record[:120])
            continue
        commit_hash, author, date, subject = (field.strip() for field in fields[:4])
        body = fields[4] if len(fields) > 4 else ""
        commits.append({
            "hash": commit_hash,
            "author": author,
            "date": date,
            "subject": subject,
            "message": " ".join(f"{subject} {body}".split()).strip(),
        })
        if len(commits) >= config.MAX_RELEASE_COMMITS:
            break
    return commits


def get_changed_files_between(from_tag: str, to_tag: str) -> list[str]:
    """Изменённые в диапазоне пути от корня репозитория (сортированы, без дублей).

    Обычный случай — ``git diff`` двух ref-ов. Когда начало диапазона неизвестно (вся
    история), пути собираются из самих коммитов: у ``git diff`` пары «начало..конец»
    для корневого коммита не существует, и его файлы иначе потерялись бы.
    """
    start, end = _resolve(from_tag, to_tag)
    raw = (run_git("diff", "--name-only", f"{start}..{end}") if start else
           run_git("log", "--no-merges", "--name-only", "--format=", end))
    paths = {line.strip() for line in raw.splitlines() if line.strip()}
    return sorted(paths)[:config.MAX_RELEASE_FILES]


def get_commit_stats(tag: str) -> dict:
    """Файлы и строки одного коммита: сколько файлов, вставок и удалений.

    У бинарного файла ``git`` печатает ``-`` вместо счётчиков: файл считается, а
    строки — нет (иначе разбор падал бы на первом же изображении).
    """
    sha = _rev(tag)
    if sha is None:
        raise ToolError(f"Реф не найден: {tag}")
    raw = run_git("show", "--numstat", "--format=%h%x1f%an%x1f%ad%x1f%s",
                  "--date=iso-strict", sha)
    lines = raw.splitlines()
    header = (lines[0].split("\x1f") if lines else []) + [""] * 4
    commit_hash, author, date, subject = (field.strip() for field in header[:4])
    files = insertions = deletions = 0
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, _path = parts
        files += 1
        insertions += int(added) if added.isdigit() else 0
        deletions += int(removed) if removed.isdigit() else 0
    return {"ref": str(tag).strip(), "commit": commit_hash, "author": author,
            "date": date, "subject": subject, "files": files,
            "insertions": insertions, "deletions": deletions}


def get_project_metrics() -> dict:
    """Метрики проекта: теги, коммиты, файлы .py, тесты, MCP-серверы, ассистенты.

    Правила подсчёта названы прямо, чтобы число было проверяемым: ``py_files`` —
    отслеживаемые git файлы ``.py`` под ``day21/``; ``tests`` — строки, начинающиеся
    с ``def test_``, во всех ``*.py`` каталога ``day21/tests``; ``mcp_servers`` —
    ``mcp_server*/server.py`` и ``mcp_servers/*/server.py`` в корне дня;
    ``assistants`` — вхождения подписи ``(Day NN)`` в переключателе разделов
    ``day21/frontend/main_sections.py``.
    """
    return {
        "tags": len(get_tags()),
        "commits": int(run_git("rev-list", "--count", "HEAD").strip() or 0),
        "py_files": sum(1 for rel in run_git("ls-files", "day21").splitlines()
                        if rel.strip().endswith(".py")),
        "tests": _count_tests(),
        "mcp_servers": len(list(config.DAY_ROOT.glob("mcp_server*/server.py")))
                       + len(list(config.DAY_ROOT.glob("mcp_servers/*/server.py"))),
        "assistants": _count_assistants(),
    }


def _count_tests() -> int:
    """Тесты каталога ``day21/tests``: строки, начинающиеся с ``def test_``."""
    total = 0
    for path in (config.DAY_ROOT / "tests").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding=config.ENCODING, errors="replace")
        except OSError as exc:  # нечитаемый файл не должен рушить метрики
            logger.warning("_count_tests: файл не прочитан: %s (%s)", path, exc)
            continue
        total += sum(1 for line in text.splitlines() if line.startswith("def test_"))
    return total


def _count_assistants() -> int:
    """Ассистенты: вхождения подписи раздела ``(Day NN)`` в переключателе разделов."""
    try:
        text = (config.DAY_ROOT / "frontend" / "main_sections.py").read_text(
            encoding=config.ENCODING, errors="replace")
    except OSError:
        return 0
    return len(re.findall(r"\(Day \d+\)", text))
