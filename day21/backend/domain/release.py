"""Подготовка релиза (день 35): словарь, промпты, арифметика версий и разбор ответов.

Модуль чистый: ``re`` и ``json_text`` — ни модели, ни MCP, ни БД. Поэтому его правила
проверяются юнит-тестами без сети и файлов, а служба (``release_service``) остаётся
сшивкой: собрать данные через MCP, спросить модель, разложить ответ по правилам
отсюда и записать файлы. Разметка (пути файлов, группы, готовые тексты и diff) живёт
в ``release_text.py`` и РЕЭКСПОРТИРУЕТСЯ отсюда: у потребителя по-прежнему один
модуль ``backend.domain.release``, а предел 400 строк держится на обоих.

Что здесь живёт и почему именно так:

- **версия** — модель отдаёт только ТИП изменения (``major``/``minor``/``patch``), а
  число считает ``bump_version`` от базовой версии: «модель называет цифру» давало бы
  версию, не связанную с историей. База читается из шапки ``CHANGELOG.md``
  (``latest_version``); файла нет — база ``1.0.0``. Если модель недоступна или её
  ответ не разобран, тип определяется ПРАВИЛОМ по меткам коммитов (``pick_bump``):
  подготовка релиза не должна зависеть от доступности облака;
- **группы CHANGELOG** — пять групп Keep a Changelog (``breaking``/``added``/
  ``changed``/``fixed``/``removed``) и жёсткий предел ключевых пунктов
  (``MAX_KEY_CHANGES``): остальное сворачивается в строку «Minor changes» со счётчиком
  коммитов, а не исчезает молча (``cap_groups`` возвращает и число отброшенных);
- **промпты** — два, а не один: тип версии — короткое решение, пункты CHANGELOG —
  разбор всей пачки коммитов. Обеим задачам запрещено выдумывать и велено вернуть
  ровно один объект JSON.

Ответы модели разбираются терпимо: JSON берётся первым сбалансированным объектом
(``json_text.first_json_object``), лишние пункты и не-строки отбрасываются, потому
что форматирование ответа — не то, ради чего стоит проваливать подготовку релиза.
"""
from __future__ import annotations

import re

from .json_text import first_json_object
from .release_text import (
    CHANGELOG_PATH,
    GROUP_ORDER,
    GROUP_TITLES,
    MAX_KEY_CHANGES,
    METRIC_KEYS,
    METRIC_LABELS,
    README_ANCHOR,
    README_PATH,
    README_SECTION_TITLE,
    RELEASE_NOTES_PATH,
    SECTION_ORDER,
    changelog_anchor,
    insert_changelog_section,
    key_items,
    metrics_line,
    release_heading,
    render_changelog_section,
    render_readme_section,
    render_release_notes,
    unified_diff,
)

__all__ = [
    # словарь дня
    "AGENT_ID", "BASE_VERSION_FALLBACK", "BUMP_ORDER", "CHANGELOG_HINT",
    "CHANGELOG_PATH", "CHANGELOG_RETRY_HINT", "CHANGELOG_SYSTEM_PROMPT",
    "CHECK_TIMEOUT", "COMMITS_MAX",
    "COMMIT_BATCH", "FILES_IN_PROMPT", "FILE_SERVER_NAME", "FILE_SERVER_TARGET",
    "GIT_TOOLS", "GROUP_ORDER", "GROUP_TITLES", "HISTORY_LIMIT", "MAX_KEY_CHANGES",
    "METRIC_KEYS", "METRIC_LABELS", "PARSER_ATTEMPTS", "README_ANCHOR", "README_PATH",
    "README_SECTION_TITLE", "RELEASE_MAX_READ_BYTES", "RELEASE_NOTES_PATH",
    "SECTION_ORDER", "STATUS_COMPLETED", "STATUS_DRY_RUN", "STATUS_FAILED",
    "STATUS_MAX", "STATUS_RUNNING", "TAG_MAX", "TOOL_APPLY_PATCH",
    "TOOL_CHANGED_FILES_BETWEEN", "TOOL_COMMITS_BETWEEN", "TOOL_COMMIT_STATS",
    "TOOL_GET_FILE_DIFF", "TOOL_GET_TAGS", "TOOL_PROJECT_METRICS", "TOOL_READ_FILE",
    "TOOL_WRITE_FILE", "VERSION_HINT", "VERSION_MAX", "VERSION_RETRY_HINT",
    "VERSION_SYSTEM_PROMPT",
    # правила
    "bump_version", "build_changelog_prompt", "build_version_prompt", "cap_groups",
    "changelog_anchor", "insert_changelog_section", "key_items", "latest_version",
    "merge_groups", "metrics_line", "parse_changelog_groups",
    "parse_version_suggestion", "pick_bump", "release_heading",
    "render_changelog_section", "render_readme_section", "render_release_notes",
    "unified_diff", "version_tuple",
]

#: Идентификатор в журнале расходов (``llm_usage``): вызовы релиза видны отдельной
#: строкой, а не как «чат».
AGENT_ID = "release"

#: Имя сервера и цель MCP-подключения. Аргумент ``--file-root ..`` важнее остального
#: текста цели: рабочая область инструментов становится корнем РЕПОЗИТОРИЯ, поэтому
#: файлы релиза (``CHANGELOG.md``, ``README.md``, ``day21/docs/RELEASE_NOTES.md``)
#: лежат в области записи, а рабочее дерево дня остаётся нетронутым. Инструменты git
#: при этом всё равно работают в корне репозитория — он у них не из ``--file-root``.
FILE_SERVER_NAME = "file_server"
FILE_SERVER_TARGET = "uv run python mcp_servers/file_server/server.py --file-root .."

#: Имена инструментов: пять читающих git-историю (``GIT_TOOLS``) и четыре файловых,
#: которыми служба читает текущие тексты и пишет результат.
TOOL_GET_TAGS = "get_tags"
TOOL_COMMITS_BETWEEN = "get_commits_between"
TOOL_CHANGED_FILES_BETWEEN = "get_changed_files_between"
TOOL_COMMIT_STATS = "get_commit_stats"
TOOL_PROJECT_METRICS = "get_project_metrics"
GIT_TOOLS = (TOOL_GET_TAGS, TOOL_COMMITS_BETWEEN, TOOL_CHANGED_FILES_BETWEEN,
             TOOL_COMMIT_STATS, TOOL_PROJECT_METRICS)
TOOL_READ_FILE = "read_file"
TOOL_WRITE_FILE = "write_file"
TOOL_APPLY_PATCH = "apply_patch"
TOOL_GET_FILE_DIFF = "get_file_diff"

#: Предел чтения файла (``CHANGELOG.md`` перевалил за 100 КБ): предпросмотр diff-а
#: считается по прочитанному, и признак обрезки попадает в заметки.
RELEASE_MAX_READ_BYTES = 400_000
#: База версии, когда шапки с версией в ``CHANGELOG.md`` нет.
BASE_VERSION_FALLBACK = "1.0.0"

#: Пределы запроса и выдачи: коммиты идут пачками (модель отвечает проще на коротком
#: списке), но не больше ``COMMITS_MAX`` всего; файлов в промпте — первые 40.
COMMIT_BATCH = 50
COMMITS_MAX = 400
FILES_IN_PROMPT = 40
#: Сколько запусков отдаёт история релиза.
HISTORY_LIMIT = 20
#: Границы полей строки ``release_runs``.
TAG_MAX = 120
VERSION_MAX = 16
REASON_MAX = 400
STATUS_MAX = 16
#: Предел прогона проверок: два ``pytest`` подряд укладываются в него с запасом.
CHECK_TIMEOUT = 900.0

#: Статусы запуска: ``dry_run`` — предпросмотр без правок файлов.
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_DRY_RUN = "dry_run"

#: Типы изменения от слабого к сильному: сильнейшее предложение побеждает, а порядок
#: списка — единственное место, где «major сильнее patch» записано.
BUMP_ORDER = ("patch", "minor", "major")

# --- Сообщения (тексты уходят в ответ API, в заметки и в вердикт) -------------
REASON_EMPTY_TAGS = "Укажите теги: от какого к какому собирать изменения"
REASON_NO_COMMITS = "Между {from_tag} и {to_tag} нет коммитов: релиз собирать не из чего"
REASON_BAD_VERSION = "Версия должна быть в формате X.Y.Z: {version!r}"
REASON_VERSION_BELOW = "Заданная версия {given} ниже предложенной {suggested}: {reason}"
REASON_EXPLICIT = "версия задана явно и не ниже предложенной {suggested} ({reason})"
FALLBACK_REASON = ("модель недоступна или ответ не разобран: версия определена правилом "
                   "по метке коммитов ({rule})")
FALLBACK_CHANGELOG_NOTE = ("модель недоступна: пункты CHANGELOG собраны из заголовков "
                           "коммитов")
WARN_MCP_UNAVAILABLE = "MCP-сервер файлов недоступен: {error}"
WARN_TOOL_FAILED = "MCP-инструмент {tool} вернул ошибку: {error}"
WARN_METRICS_UNAVAILABLE = "метрики проекта не собраны: {error}"
WARN_TAGS_UNAVAILABLE = "список тегов не получен: {error}"
WARN_CHANGELOG_MISSING = "{path} не найден: раздел релиза будет создан с нуля"
WARN_CHANGELOG_TRUNCATED = "{path} прочитан не полностью: diff в предпросмотре неполон"
WARN_SECTION_EXISTS = "раздел {heading} уже есть в {path}: файл не менялся"
WARN_WRITE_FAILED = "запись {path} не удалась: {error}"
WARN_CHECKS_FAILED = "проверки готовности не пройдены: {failed}"
TAG_MISSING_FROM = "{tag} (нет тега → корень истории)"
TAG_MISSING_TO = "{tag} (нет тега → HEAD)"
CHECKS_MISSING_METRICS = "покрытие не разобрано из вывода pytest --cov"
VERDICT_READY = "✅ релиз {version} готов: проверки пройдены, файлы записаны"
VERDICT_NOT_READY = "⚠️ релиз {version}: проверки не пройдены ({failed})"
VERDICT_DRY_RUN = "🧪 dry_run: показан план, файлы не изменены"
VERDICT_FAILED = "❌ подготовка релиза не выполнена: {error}"

# --- Промпты ------------------------------------------------------------------
VERSION_SYSTEM_PROMPT = (
    "Ты определяешь тип следующей версии проекта по SemVer. Правила: BREAKING CHANGE в "
    "тексте коммита или «!» после типа (feat!) — major; тип feat — minor; fix, chore, docs и "
    "всё остальное — patch. Коммиты проекта подписаны «dayN: …», поэтому дополнительно: "
    "major — если добавлен или несовместимо изменён публичный интерфейс (HTTP-эндпоинт, "
    "MCP-инструмент, раздел интерфейса, таблица БД); minor — новая функциональность без слома "
    "совместимости; patch — исправления, документация и служебные правки. Верни СТРОГО один "
    "объект JSON без markdown: {\"suggested_version\": \"major\"|\"minor\"|\"patch\", "
    "\"reason\": \"одно предложение по-русски\", \"breaking_changes\": [\"…\"], "
    "\"features\": [\"…\"], \"fixes\": [\"…\"]}. Не больше 5 пунктов в каждом списке, "
    "каждый пункт — короткая строка до 60 символов, без хешей. Пиши только то, что есть "
    "в коммитах."
)
VERSION_HINT = "Проанализируй коммиты ниже и верни только объект JSON."
CHANGELOG_SYSTEM_PROMPT = (
    "Ты пишешь CHANGELOG проекта в формате Keep a Changelog на русском языке. Сгруппируй "
    "изменения по смыслу: breaking (несовместимые изменения), added (добавлено), changed "
    "(изменено), fixed (исправлено), removed (удалено). Не больше 20 ключевых пунктов всего: "
    "выбирай важное для пользователя. Не перечисляй хеши коммитов, не повторяй один пункт "
    "дважды; каждый пункт — одна строка без точки в конце, с указанием модуля или "
    "возможности. Верни СТРОГО один объект JSON без markdown: {\"breaking\": [\"…\"], "
    "\"added\": [\"…\"], \"changed\": [\"…\"], \"fixed\": [\"…\"], \"removed\": [\"…\"]}. "
    "Пустая группа — пустой список. Ничего не выдумывай."
)
CHANGELOG_HINT = "Сформируй пункты CHANGELOG по коммитам ниже и верни только объект JSON."

#: Подсказка ко второй попытке: ответ модели не разобран или обрезан лимитом токенов.
#: Длинный ответ (модель пересказывает заголовки коммитов целиком) упирается в предел
#: ``LLM_MAX_RESPONSE_TOKENS`` и приходит без закрывающей скобки — поэтому подсказка
#: ограничивает не только формат, но и длину пункта.
VERSION_RETRY_HINT = ("Предыдущий ответ не разобран или обрезан. Верни СТРОГО один объект "
                      "JSON без markdown: не больше 3 пунктов в каждом списке, каждый пункт — "
                      "короткая строка до 60 символов.")
CHANGELOG_RETRY_HINT = ("Предыдущий ответ не разобран или обрезан. Верни СТРОГО один объект "
                        "JSON без markdown: не больше 20 пунктов всего, каждый пункт — "
                        "короткая строка до 80 символов.")
#: Попытки разбора ответа модели: вторая идёт с подсказкой о неразобранном ответе.
PARSER_ATTEMPTS = 2


# --- Промпты: сборка запроса ------------------------------------------------
def _commit_lines(commits: list[dict]) -> str:
    """Коммиты списком «- заголовок»: одна строка на коммит, без хешей и дат."""
    return "\n".join(f"- {str(commit.get('subject') or '').strip()}" for commit in commits)


def build_version_prompt(commits: list[dict], *, total: int) -> tuple[str, str]:
    """Сообщения анализа версии: системные правила и пачка коммитов с их числом."""
    question = (f"{VERSION_HINT}\n\nКоммиты (показано {len(commits)} из {total}):\n"
                f"{_commit_lines(commits)}")
    return VERSION_SYSTEM_PROMPT, question


def build_changelog_prompt(commits: list[dict], changed_files: list[str]) -> tuple[str, str]:
    """Сообщения генератора CHANGELOG: та же пачка коммитов плюс изменённые файлы."""
    paths = list(changed_files)[:FILES_IN_PROMPT]
    files = "\n".join(f"- {path}" for path in paths)
    question = (f"{CHANGELOG_HINT}\n\nИзменённые файлы (первые {FILES_IN_PROMPT}):\n{files}"
                f"\n\nКоммиты (показано {len(commits)}):\n{_commit_lines(commits)}")
    return CHANGELOG_SYSTEM_PROMPT, question


# --- Версия ------------------------------------------------------------------
def version_tuple(text: str) -> tuple[int, int, int] | None:
    """Разбирает ``X.Y.Z`` (с необязательной ведущей ``v``); иначе ``None``."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(text or "").strip())
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def latest_version(changelog_text: str) -> str | None:
    """Версия первой шапки ``## [X.Y.Z]`` в CHANGELOG (``None`` — шапок нет)."""
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", str(changelog_text or ""), re.MULTILINE)
    return match.group(1) if match else None


def bump_version(base: str, bump: str) -> str:
    """Применяет тип изменения к базовой версии (неизвестный тип или база — ``ValueError``)."""
    parsed = version_tuple(base)
    if parsed is None:
        raise ValueError(REASON_BAD_VERSION.format(version=base))
    if bump not in BUMP_ORDER:
        raise ValueError(f"Неизвестный тип изменения версии: {bump!r}. "
                         f"Доступны: {', '.join(BUMP_ORDER)}")
    major, minor, patch = parsed
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def pick_bump(commits: list[dict]) -> tuple[str, str]:
    """Тип изменения ПРАВИЛОМ по меткам коммитов: ``(bump, причина)``.

    Правило — второй эшелон: оно работает, когда модель недоступна, и повторяет её
    правила (BREAKING CHANGE или ``feat!`` — major, ``feat`` — minor, остальное —
    patch). Так подготовка релиза не зависит от облака.
    """
    for commit in commits:
        text = f"{commit.get('subject') or ''} {commit.get('message') or ''}"
        if "BREAKING CHANGE" in text or re.match(r"^[a-z]+(\([^)]*\))?!:",
                                                 str(commit.get("subject") or "")):
            return "major", "BREAKING CHANGE в коммитах"
    for commit in commits:
        if re.match(r"^feat", str(commit.get("subject") or "")):
            return "minor", "метка feat в коммитах"
    return "patch", "меток feat и BREAKING CHANGE нет"


def parse_version_suggestion(text: str) -> dict | None:
    """Разбирает ответ модели об версии; негодный ответ — ``None`` (работает правило)."""
    payload = first_json_object(str(text or ""))
    if not isinstance(payload, dict):
        return None
    bump = payload.get("suggested_version")
    reason = payload.get("reason")
    if bump not in BUMP_ORDER or not isinstance(reason, str) or not reason.strip():
        return None
    lists: dict[str, list[str]] = {}
    for key in ("breaking_changes", "features", "fixes"):
        value = payload.get(key)
        if not isinstance(value, list):
            return None
        lists[key] = _clean_items(value)
    return {"suggested_version": bump, "reason": reason.strip(), **lists}


# --- Группы CHANGELOG --------------------------------------------------------
def _clean_items(raw: list, limit: int = MAX_KEY_CHANGES) -> list[str]:
    """Строки списка без пустых и дублей, не больше ``limit`` пунктов."""
    items: list[str] = []
    seen: set[str] = set()
    for value in raw:
        text = str(value).strip() if isinstance(value, str) else ""
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def parse_changelog_groups(text: str) -> dict | None:
    """Разбирает ответ модели о пунктах CHANGELOG; пустой ответ — ``None``.

    Ключи необязательны (пропущенная группа — пустая), а не-строки отбрасываются:
    модель, положившая в список объект, не должна ронять подготовку релиза.
    """
    payload = first_json_object(str(text or ""))
    if not isinstance(payload, dict):
        return None
    groups = {key: _clean_items(payload.get(key) or []) for key in GROUP_ORDER}
    return groups if any(groups.values()) else None


def merge_groups(batches: list[dict]) -> dict:
    """Склеивает группы нескольких пачек: порядок сохраняется, дубли убираются."""
    merged = {key: [] for key in GROUP_ORDER}
    for groups in batches:
        for key in GROUP_ORDER:
            merged[key] = _clean_items([*merged[key], *(groups.get(key) or [])])
    return merged


def cap_groups(groups: dict, limit: int = MAX_KEY_CHANGES) -> tuple[dict, int]:
    """Обрезает пункты до ``limit`` в порядке групп; ``(группы, сколько отброшено)``.

    Порядок обрезки — ``GROUP_ORDER``: предел задевает хвост (служебные и удалённые
    изменения), а несовместимые изменения остаются в разделе всегда.
    """
    capped: dict[str, list[str]] = {key: [] for key in GROUP_ORDER}
    kept = dropped = 0
    for key in GROUP_ORDER:
        for item in groups.get(key) or []:
            if kept < limit:
                capped[key].append(str(item))
                kept += 1
            else:
                dropped += 1
    return capped, dropped
