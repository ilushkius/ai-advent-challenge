"""Юнит-тесты правил релиза (день 35): версии, разбор ответов, группы и разметка.

Модуль чистый, поэтому проверяется без модели, MCP и БД: арифметика версий от базовой
из CHANGELOG, детерминированное правило по меткам коммитов (оно работает, когда модель
недоступна), терпимый разбор JSON-ответов, склейка и обрезка групп и точный вид
разделов. Отдельно — вставка раздела в файл newest-first: от неё зависит
идемпотентность повторного прогона.
"""
from backend.domain import release


def _commit(subject: str, message: str = "") -> dict:
    """Коммит стенда: только поля, которые читают правила."""
    return {"subject": subject, "message": message or subject}


# ---------- версия ----------
def test_version_tuple_accepts_prefix_and_rejects_junk():
    """``X.Y.Z`` и ``vX.Y.Z`` разбираются, всё остальное — ``None``."""
    assert release.version_tuple("1.2.3") == (1, 2, 3)
    assert release.version_tuple("v10.0.7") == (10, 0, 7)
    assert release.version_tuple(" 2.0.0 ") == (2, 0, 0)
    for junk in ("1.2", "1.2.3.4", "abc", "", "1.2.x", "v1"):
        assert release.version_tuple(junk) is None, junk


def test_latest_version_reads_first_release_heading():
    """База версии — первая шапка ``## [X.Y.Z]`` файла (он newest-first)."""
    text = "# История\n\n## [2.1.0] - 2026-01-01\n\n## [2.0.0] - 2025-01-01\n"
    assert release.latest_version(text) == "2.1.0"
    assert release.latest_version("# История\n\n## 2026-01-01 — feat — день 1\n") is None
    assert release.latest_version("") is None


def test_bump_version_applies_type_to_base():
    """Тип изменения применяется к базе: major сбрасывает минор и патч."""
    assert release.bump_version("1.2.3", "major") == "2.0.0"
    assert release.bump_version("1.2.3", "minor") == "1.3.0"
    assert release.bump_version("1.2.3", "patch") == "1.2.4"


def test_bump_version_rejects_unknown_type_and_bad_base():
    """Незнакомый тип и негодная база — ``ValueError`` (роутер отвечает 400)."""
    for bump in ("feature", "", "MINOR"):
        try:
            release.bump_version("1.0.0", bump)
        except ValueError:
            continue
        raise AssertionError(bump)
    try:
        release.bump_version("1.0", "patch")
    except ValueError as exc:
        assert "X.Y.Z" in str(exc)
    else:
        raise AssertionError("негодная база должна быть ошибкой")


def test_pick_bump_reads_commit_labels():
    """Правило без модели: BREAKING → major, ``feat`` → minor, остальное → patch."""
    assert release.pick_bump([_commit("fix: опечатка"),
                             _commit("feat!: сломан публичный интерфейс")]) == (
        "major", "BREAKING CHANGE в коммитах")
    assert release.pick_bump([_commit("refactor(api)!: другой контракт")])[0] == "major"
    assert release.pick_bump([_commit("chore: мелочи"),
                             _commit("feat: новый раздел")]) == (
        "minor", "метка feat в коммитах")
    assert release.pick_bump([_commit("day34: ассистент файлов")]) == (
        "patch", "меток feat и BREAKING CHANGE нет")
    assert release.pick_bump([{"subject": "fix: правка",
                               "message": "fix: правка BREAKING CHANGE в теле"}])[0] == "major"
    assert release.pick_bump([])[0] == "patch"


# ---------- разбор ответов модели ----------
def test_parse_version_suggestion_accepts_valid_json():
    """Годный ответ разбирается: тип, причина и три списка пунктов."""
    text = ('Вот ответ: {"suggested_version": "minor", '
            '"reason": "новая функциональность", "breaking_changes": [], '
            '"features": ["A", "A", 5], "fixes": ["B"]} и всё.')
    parsed = release.parse_version_suggestion(text)
    assert parsed["suggested_version"] == "minor"
    assert parsed["reason"] == "новая функциональность"
    assert parsed["features"] == ["A"]          # не-строки и повторы отброшены
    assert parsed["fixes"] == ["B"] and parsed["breaking_changes"] == []


def test_parse_version_suggestion_rejects_incomplete_answers():
    """Неразобранный, неполный и негодный ответ — ``None`` (работает правило)."""
    assert release.parse_version_suggestion("никакого JSON здесь нет") is None
    assert release.parse_version_suggestion('{"suggested_version": "huge", '
                                            '"reason": "x", "breaking_changes": [], '
                                            '"features": [], "fixes": []}') is None
    assert release.parse_version_suggestion('{"suggested_version": "minor", '
                                            '"reason": "", "breaking_changes": [], '
                                            '"features": [], "fixes": []}') is None
    assert release.parse_version_suggestion('{"suggested_version": "minor", '
                                            '"reason": "x", "breaking_changes": []}') is None
    # обрезанный ответ модели (уперлась в предел токенов) — тоже None
    assert release.parse_version_suggestion('{"suggested_version": "minor", '
                                            '"reason": "x", "features": ["A"') is None


def test_parse_version_suggestion_caps_items():
    """Списки обрезаются до ``MAX_KEY_CHANGES`` даже у щедрого ответа модели."""
    items = ", ".join(f'"пункт {index}"' for index in range(30))
    parsed = release.parse_version_suggestion(
        '{"suggested_version": "patch", "reason": "x", "breaking_changes": [], '
        f'"features": [{items}], "fixes": []}}')
    assert len(parsed["features"]) == release.MAX_KEY_CHANGES


def test_parse_changelog_groups_tolerates_partial_answer():
    """Пропущенные группы — пустые; пустой объект и проза — ``None``."""
    parsed = release.parse_changelog_groups('{"added": ["A"], "fixed": ["B"]}')
    assert parsed["added"] == ["A"] and parsed["fixed"] == ["B"]
    assert parsed["breaking"] == [] and parsed["removed"] == []
    assert release.parse_changelog_groups('{"added": []}') is None
    assert release.parse_changelog_groups("текст без JSON") is None


def test_merge_groups_keeps_order_and_drops_duplicates():
    """Пункты пачек склеиваются в порядке появления, повторы убираются без учёта регистра."""
    merged = release.merge_groups([
        {"added": ["Раздел A", "B"], "fixed": [], "breaking": [], "changed": [], "removed": []},
        {"added": ["раздел a", "C"], "fixed": ["D"], "breaking": [], "changed": [], "removed": []},
    ])
    assert merged["added"] == ["Раздел A", "B", "C"]
    assert merged["fixed"] == ["D"]


def test_cap_groups_limits_items_and_counts_dropped():
    """Обрезка идёт по порядку ``GROUP_ORDER``, отброшенное считается."""
    groups = {key: [] for key in release.GROUP_ORDER}
    groups["added"] = [f"A{index}" for index in range(15)]
    groups["breaking"] = [f"B{index}" for index in range(8)]
    capped, dropped = release.cap_groups(groups, 20)
    assert len(release.key_items(capped)) == 20
    assert dropped == 3
    assert capped["breaking"] == groups["breaking"]      # breaking сохраняется первым


# ---------- разметка ----------
def test_render_changelog_section_has_fixed_heading_order():
    """Заголовки раздела идут Added → Changed → Fixed → Removed → Breaking → Minor."""
    groups = {key: [] for key in release.GROUP_ORDER}
    groups["added"] = ["Новый эндпоинт"]
    section = release.render_changelog_section("1.1.0", "2026-10-16", groups, 3)
    headings = [line for line in section.splitlines() if line.startswith("#")]
    assert headings == ["## [1.1.0] - 2026-10-16", "### Added", "### Changed", "### Fixed",
                        "### Removed", "### Breaking", "### Minor changes"]
    assert "- Новый эндпоинт" in section
    assert "- Нет изменений." in section
    assert "Прочие изменения: 3 коммитов" in section
    assert "Прочих изменений нет." in release.render_changelog_section(
        "1.1.0", "2026-10-16", groups, 0)


def test_insert_changelog_section_puts_release_first():
    """Раздел встаёт ПЕРЕД первой шапкой (файл newest-first), а без шапки — в конец."""
    current = "# История\n\n## [1.0.0] - 2025-01-01\n\nСтарое.\n"
    updated = release.insert_changelog_section(current, "## [1.0.1] - 2026-10-16\n\nНовое.")
    assert updated.index("## [1.0.1]") < updated.index("## [1.0.0]")
    assert updated.startswith("# История\n")
    assert release.changelog_anchor(current) == "## [1.0.0] - 2025-01-01"
    assert release.changelog_anchor("# История\n\nтекст\n") is None
    assert release.insert_changelog_section("", "## [1.0.0] - x") == "## [1.0.0] - x"
    tail = release.insert_changelog_section("# История\n", "## [1.0.0] - x")
    assert tail.endswith("## [1.0.0] - x")


def test_release_heading_matches_render_output():
    """Шапка раздела — то же, что начало готового раздела (по ней и проверяется повтор)."""
    groups = {key: [] for key in release.GROUP_ORDER}
    section = release.render_changelog_section("2.0.0", "2026-10-16", groups, 0)
    assert section.startswith(release.release_heading("2.0.0"))


def test_release_notes_use_five_items_and_metrics():
    """Заметки: пять ключевых пунктов, шаги обновления и строка метрик."""
    groups = {key: [] for key in release.GROUP_ORDER}
    groups["added"] = [f"Пункт {index}" for index in range(7)]
    metrics = {"tags": 14, "commits": 70, "py_files": 579, "tests": 1723,
               "mcp_servers": 7, "assistants": 5}
    text = release.render_release_notes("1.1.0", "2026-10-16", groups, 4, metrics)
    assert text.startswith("# Релиз 1.1.0 — 2026-10-16")
    assert "Пункт 4" in text and "Пункт 5" not in text
    assert "uv sync" in text and "DEEPSEEK_API_KEY" in text
    assert "5 ассистентов" in text and "1723 теста" in text
    empty = release.render_release_notes("1.1.0", "2026-10-16", {}, 0, None)
    assert "Ключевых изменений не распознано" in empty
    assert "Метрики релиза: не собраны" in empty


def test_readme_section_lists_stack_and_links():
    """Раздел README: заголовок, стек, метрики и ссылки на историю и заметки."""
    text = release.render_readme_section("1.1.0", "2026-10-16", {"tags": 14, "assistants": 1})
    assert text.startswith(release.README_SECTION_TITLE)
    assert "**Стек:**" in text and "FastAPI" in text and "Streamlit" in text
    assert "14 тегов, 1 ассистент" in text
    assert f"`{release.CHANGELOG_PATH}`" in text
    assert f"`{release.RELEASE_NOTES_PATH}`" in text
    assert "не собраны" in release.render_readme_section("1.1.0", "2026-10-16", None)


def test_metrics_line_uses_russian_plural_forms():
    """Числа согласуются со словами: 1 тег, 2 тега, 5 тегов, 11 тегов, 21 тег."""
    line = release.metrics_line({"tags": 1, "commits": 22, "py_files": 2, "tests": 5,
                                 "mcp_servers": 11, "assistants": 21})
    assert line == ("1 тег, 22 коммита, 2 файла .py, 5 тестов, 11 MCP-серверов, "
                    "21 ассистент")
    assert release.metrics_line(None) == "" and release.metrics_line({}) == ""
    assert release.metrics_line({"tags": 3, "unknown": 7}) == "3 тега"


def test_unified_diff_is_empty_for_equal_texts():
    """Diff равных текстов пуст, а вставка строки видна как добавление."""
    assert release.unified_diff("CHANGELOG.md", "a\nb", "a\nb") == ""
    diff = release.unified_diff("CHANGELOG.md", "a\n", "x\na\n")
    assert diff.startswith("--- a/CHANGELOG.md\n+++ b/CHANGELOG.md") and "+x" in diff
