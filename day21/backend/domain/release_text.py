"""Разметка релиза (день 35): пути файлов, группы, вердикты и готовые тексты.

Вынесено из ``release.py``, потому что тот файл упёрся бы в предел 400 строк, а
предмет здесь отдельный: там — промпты, арифметика версий и разбор ответов модели,
здесь — превращение групп в тексты файлов и порядок этих текстов. Направление
импорта одно: ``release`` берёт отсюда разметку и РЕЭКСПОРТИРУЕТ её, поэтому служба
и тесты видят по-прежнему один модуль ``backend.domain.release``.

Почему шапка раздела и место вставки живут здесь, а не в службе. Идемпотентность
повторного прогона держится на двух правилах: «заголовок версии уже есть — файл не
меняется» (``release_heading``) и «раздел встаёт ПЕРЕД первой шапкой файла»
(``insert_changelog_section``, ``changelog_anchor``). Оба правила — про ФОРМАТ
файла, и проверяются юнит-тестами без git, MCP и модели.
"""
from __future__ import annotations

import difflib

__all__ = ["CHANGELOG_PATH", "GROUP_ORDER", "GROUP_TITLES", "MAX_KEY_CHANGES",
           "METRIC_KEYS", "METRIC_LABELS", "README_ANCHOR", "README_PATH",
           "README_SECTION_TITLE", "RELEASE_NOTES_PATH", "SECTION_ORDER",
           "changelog_anchor", "insert_changelog_section", "key_items", "metrics_line",
           "release_heading", "render_changelog_section", "render_readme_section",
           "render_release_notes", "unified_diff"]

#: Пути файлов релиза. ``RELEASE_NOTES_PATH`` — внутри папки дня (там его место по
#: заданию дня), а не в корне: корневой ``RELEASE_NOTES.md`` не создаётся.
CHANGELOG_PATH = "CHANGELOG.md"
README_PATH = "README.md"
RELEASE_NOTES_PATH = "day21/docs/RELEASE_NOTES.md"

#: Якорь вставки раздела в README: раздел результата встаёт ПЕРЕД структурой
#: репозитория, чтобы «что построено» читалось раньше карты папок.
README_ANCHOR = "## Структура репозитория"
README_SECTION_TITLE = "## Результат 35-дневного челленджа"

#: Предел ключевых пунктов CHANGELOG: остальное сворачивается в «Minor changes».
MAX_KEY_CHANGES = 20
#: Группы изменений: ``GROUP_ORDER`` — порядок разбора и подсчёта, ``GROUP_TITLES`` —
#: заголовки разделов (в ответе модели ключи те же, что здесь).
GROUP_ORDER = ("breaking", "added", "changed", "fixed", "removed")
GROUP_TITLES = {"breaking": "Breaking", "added": "Added", "changed": "Changed",
                "fixed": "Fixed", "removed": "Removed"}
#: Порядок заголовков в готовом разделе CHANGELOG: сначала то, что пользователь
#: получает, в конце — то, что он теряет.
SECTION_ORDER = ("added", "changed", "fixed", "removed", "breaking")

#: Подписи метрик проекта: одна строка на метрику — три русские формы числа.
METRIC_LABELS = (("tags", "тег", "тега", "тегов"),
                 ("commits", "коммит", "коммита", "коммитов"),
                 ("py_files", "файл .py", "файла .py", "файлов .py"),
                 ("tests", "тест", "теста", "тестов"),
                 ("mcp_servers", "MCP-сервер", "MCP-сервера", "MCP-серверов"),
                 ("assistants", "ассистент", "ассистента", "ассистентов"))
#: Порядок метрик в строке (и в таблице раздела интерфейса).
METRIC_KEYS = tuple(key for key, *_forms in METRIC_LABELS)


def key_items(groups: dict) -> list[str]:
    """Все пункты групп одним списком в порядке ``GROUP_ORDER``."""
    return [item for key in GROUP_ORDER for item in (groups.get(key) or [])]


def render_changelog_section(version: str, date: str, groups: dict,
                             minor_count: int) -> str:
    """Раздел CHANGELOG версии: шапка, пять групп и строка «Minor changes»."""
    blocks = [f"## [{version}] - {date}"]
    for key in SECTION_ORDER:
        items = [str(item) for item in (groups.get(key) or [])]
        bullets = "\n".join(f"- {item}" for item in items) if items else "- Нет изменений."
        blocks.append(f"### {GROUP_TITLES[key]}\n{bullets}")
    minor = (f"- Прочие изменения: {minor_count} коммитов (полный список — `git log`)."
             if minor_count else "- Прочих изменений нет.")
    blocks.append(f"### Minor changes\n{minor}")
    return "\n\n".join(blocks)


def release_heading(version: str) -> str:
    """Шапка раздела релиза — по ней видно, писался ли этот релиз уже."""
    return f"## [{version}]"


def changelog_anchor(current: str) -> str | None:
    """Первая строка ``## …`` текущего CHANGELOG — место вставки раздела (``None`` — нет)."""
    for line in str(current or "").splitlines():
        if line.startswith("## "):
            return line
    return None


def insert_changelog_section(current: str, section: str) -> str:
    """Вставляет раздел ПЕРЕД первой шапкой файла (файл newest-first, добавление в конец — нет)."""
    anchor = changelog_anchor(current)
    if anchor is None:
        return section if not str(current or "").strip() else f"{current}\n{section}"
    head, _, tail = str(current).partition(anchor)
    return f"{head}{section}\n{anchor}{tail}"


def render_release_notes(version: str, date: str, groups: dict, minor_count: int,
                         metrics: dict | None) -> str:
    """Короткие заметки о релизе: пять ключевых пунктов, как обновиться и метрики."""
    items = key_items(groups)[:5]
    bullets = "\n".join(f"- {item}" for item in items) if items else (
        "- Ключевых изменений не распознано: смотрите `CHANGELOG.md`.")
    return "\n".join([
        f"# Релиз {version} — {date}",
        "",
        "Итог 35-дневного челленджа ai-challenge: агентная система с RAG, MCP и "
        "ассистентами.",
        "",
        "## Ключевые изменения",
        bullets,
        "",
        "## Как обновиться",
        "1. `git pull`, затем `uv sync` в папке `day21/`.",
        "2. `uv run pytest -m \"not slow\"` — убедиться, что тесты проходят.",
        "3. `DEEPSEEK_API_KEY` — в `day21/.env` (образец — `day21/.env.example`).",
        "4. Локальная модель необязательна: `ollama serve` и `LLM_PROVIDER=local`.",
        "",
        f"Метрики релиза: {metrics_line(metrics) or 'не собраны'}",
        "Полный список изменений — `CHANGELOG.md`.",
    ])


def render_readme_section(version: str, date: str, metrics: dict | None) -> str:
    """Раздел результата челленджа для README: что построено, стек и метрики."""
    return "\n".join([
        README_SECTION_TITLE,
        "",
        f"Челлендж завершён релизом **{version}** ({date}): тридцать пять дней "
        "практикума по LLM сведены в одну агентную систему.",
        "",
        "**Что построено:** память агента и FSM состояния задачи с инвариантами; "
        "MCP-клиент и флот серверов; планировщик фоновых задач; декларативные "
        "пайплайны и оркестрация нескольких серверов; индексация корпуса документов "
        "(FAISS) и RAG со ссылками на источники; мини-чат по корпусу; локальная и "
        "удалённая LLM как второй провайдер; ассистенты — разработчика, ревью кода, "
        "поддержки пользователей, файлов и подготовки релиза.",
        "",
        "**Стек:** Python 3.14, FastAPI, Streamlit, SQLAlchemy + SQLite, FAISS, "
        "sentence-transformers, MCP SDK (stdio), DeepSeek API, Ollama, pytest.",
        "",
        f"**Метрики:** {metrics_line(metrics) or 'не собраны (MCP-инструмент метрик недоступен)'}",
        "",
        f"Полная история — [`{CHANGELOG_PATH}`]({CHANGELOG_PATH}), заметки о релизе — "
        f"[`{RELEASE_NOTES_PATH}`]({RELEASE_NOTES_PATH}).",
    ])


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Русская форма существительного по числу (1 тег, 2 тега, 5 тегов)."""
    tail = abs(int(count)) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def metrics_line(metrics: dict | None, *, keys: tuple = METRIC_KEYS) -> str:
    """Строка метрик проекта («14 тегов, 70 коммитов, …»); пустые метрики — пустая строка."""
    if not metrics:
        return ""
    labels = {key: forms for key, *forms in METRIC_LABELS}
    parts = []
    for key in keys:
        value = metrics.get(key)
        if not isinstance(value, int) or key not in labels:
            continue
        one, few, many = labels[key]
        parts.append(f"{value} {_plural(value, one, few, many)}")
    return ", ".join(parts)


def unified_diff(path: str, old: str, new: str) -> str:
    """Unified diff двух текстов (``a/путь`` → ``b/путь``); равные тексты — пустая строка."""
    return "\n".join(difflib.unified_diff(str(old or "").splitlines(),
                                          str(new or "").splitlines(),
                                          fromfile=f"a/{path}", tofile=f"b/{path}",
                                          lineterm=""))
