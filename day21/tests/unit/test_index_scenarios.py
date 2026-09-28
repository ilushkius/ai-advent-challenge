"""Тестовые запросы, источники документов и их метаданные (день 21).

Проверяется ground truth демонстрации: пять запросов ссылаются на РЕАЛЬНЫЕ
документы набора (опечатка в slug'е дала бы вечный recall 0, и это выглядело бы как
плохая стратегия, а не как ошибка данных), набор достаточно велик для сравнения, а
метаданные документа (язык, заголовок, усечение) определяются без сети.
"""
from backend.domain.document_sources import (
    DOCUMENT_SOURCES,
    DOCUMENT_SUFFIXES,
    KIND_CODE,
    KIND_DOCS,
    KIND_GUIDE,
    KIND_README,
    TRUNCATION_MARKER,
    detect_language,
    detect_title,
    source_slug,
    truncate,
)
from backend.domain.index_scenarios import (
    DEMO_QUERIES,
    queries_as_dicts,
    validate_queries,
)

#: «Страница» отчёта: по ней меряется объём набора документов.
CHARS_PER_PAGE = 1800


def test_queries_are_valid():
    """Пять запросов проходят проверку: непустые и со существующими источниками."""
    assert len(DEMO_QUERIES) == 5
    assert validate_queries() == []


def test_expected_sources_exist_in_document_sources():
    """Ожидаемые источники — реальные slug'и набора документов."""
    known = {source_slug(source.path) for source in DOCUMENT_SOURCES}
    for query in DEMO_QUERIES:
        assert query.expected_sources, query.query
        assert set(query.expected_sources) <= known


def test_queries_cover_different_days():
    """Запросы разнесены по разным дням: поиск должен различать темы."""
    sources = [source for query in DEMO_QUERIES for source in query.expected_sources]
    days = {source.split("-")[0] for source in sources}
    assert len(days) >= 4


def test_queries_as_dicts_shape():
    """Запросы для API и интерфейса отдаются словарями с ожидаемыми полями."""
    payload = queries_as_dicts()
    assert len(payload) == 5
    for item in payload:
        assert set(item) == {"query", "expected_sources", "note"}
        assert isinstance(item["expected_sources"], list)
        assert item["note"]


def test_document_set_is_large_enough():
    """Набор документов: 25 источников и не меньше 20 страниц текста."""
    assert len(DOCUMENT_SOURCES) == 25
    total = sum(source.max_chars for source in DOCUMENT_SOURCES)
    assert total >= 20 * CHARS_PER_PAGE


def test_document_set_has_all_kinds():
    """В наборе есть все четыре вида источников: README, docs, код и корневые гайды."""
    kinds = {source.kind for source in DOCUMENT_SOURCES}
    assert kinds == {KIND_README, KIND_DOCS, KIND_CODE, KIND_GUIDE}


def test_source_paths_are_relative_and_unique():
    """Пути источников уникальны и заданы от корня репозитория (прямые слэши)."""
    paths = [source.path for source in DOCUMENT_SOURCES]
    assert len(set(paths)) == len(paths)
    assert all(not path.startswith("/") and "\\" not in path for path in paths)


def test_source_slug_replaces_slashes_and_case():
    """Имя документа в ``documents/`` — путь источника без слэшей в нижнем регистре."""
    assert source_slug("day9/backend/context_fsm.py") == "day9-backend-context_fsm.py"
    assert source_slug("day20/README.md") == "day20-readme.md"
    assert source_slug("AGENTS.md") == "agents.md"


def test_document_suffixes_cover_markdown_text_and_code():
    """Загрузчик принимает за документы markdown, текст и python-файлы."""
    assert set(DOCUMENT_SUFFIXES) == {".md", ".txt", ".py"}


# ---------- метаданные ----------
def test_detect_language_by_cyrillic_share():
    """Язык определяется по доле кириллицы среди букв."""
    assert detect_language("Это русский текст с достаточной долей кириллицы") == "ru"
    assert detect_language("This is an English sentence") == "en"
    assert detect_language("") == "en"
    assert detect_language("12345 !!!") == "en"


def test_detect_title_of_markdown():
    """Заголовок markdown — первый заголовок ATX."""
    assert detect_title("# Правила дня\n\nтекст", KIND_README, "doc.md") == "Правила дня"


def test_detect_title_of_code_uses_module_docstring():
    """Заголовок кода — первая строка модульного докстринга."""
    text = '"""Модуль примера: состояния и переходы."""\nimport enum\n'
    assert detect_title(text, KIND_CODE, "sample.py") == "Модуль примера: состояния и переходы."


def test_detect_title_falls_back_to_file_name():
    """Без заголовка и докстринга остаётся имя файла без расширения."""
    assert detect_title("просто текст без заголовка", KIND_DOCS, "notes.md") == "notes"
    assert detect_title("", KIND_DOCS, "empty.md") == "empty"


def test_truncate_marks_cut_documents():
    """Усечение ставит маркер: «документ на 2 КБ» не должен выглядеть полным."""
    long_text = "x" * 100
    cut, was_cut = truncate(long_text, 10)
    assert was_cut is True
    assert cut.startswith("x" * 10)
    assert cut.endswith(TRUNCATION_MARKER)


def test_truncate_keeps_short_documents_intact():
    """Короткий документ не меняется и не получает маркер."""
    assert truncate("коротко", 100) == ("коротко", False)
    assert truncate("коротко", 0) == ("коротко", False)
