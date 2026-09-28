"""Инструмент ``extract_keywords`` (день 20): частоты, служебные слова и порядок.

Проверяются правила, из-за которых ключевое слово действительно ключевое: регистр
не важен, служебные слова выбрасываются, порядок — частота по убыванию, а при
равной частоте — алфавит. Порядок детерминирован: результат едет в журнал шагов
оркестрации и в отчёт прогона, и «дрожащий» список там недопустим.
"""
import pytest

from mcp.server.mcpserver.exceptions import ToolError

from mcp_servers.data_server import config, keywords


def test_frequent_word_comes_first():
    """Самое частое слово стоит первым, словоформы приводятся к нижнему регистру."""
    result = keywords.extract_keywords("RAG поиск RAG чанкинг", limit=5)
    assert result["keywords"] == ["rag", "поиск", "чанкинг"]
    assert result["count"] == 3
    assert result["engine"] == "frequency"
    assert result["joined"] == "rag, поиск, чанкинг"


def test_stopwords_are_dropped():
    """Служебные слова в ключевые не попадают, даже если они частые."""
    result = keywords.extract_keywords("и в на поиск поиск и в", limit=5)
    assert result["keywords"] == ["поиск"]
    assert "и" not in result["keywords"] and "в" not in result["keywords"]
    assert "на" in config.STOPWORDS


def test_equal_frequencies_are_ordered_alphabetically():
    """При равной частоте порядок алфавитный, а не «как в тексте»."""
    result = keywords.extract_keywords("яблоко банан вишня", limit=5)
    assert result["keywords"] == ["банан", "вишня", "яблоко"]


def test_the_same_text_gives_the_same_result():
    """Повторный вызов на том же тексте даёт тот же список: порядок полный."""
    text = "поиск чанкинг поиск эмбеддинг агент поиск агент"
    assert keywords.extract_keywords(text)["keywords"] == \
        keywords.extract_keywords(text)["keywords"]


@pytest.mark.parametrize("limit,expected", [(0, config.KEYWORDS_MIN),
                                            (999, config.KEYWORDS_MAX)])
def test_limit_is_clamped(limit, expected):
    """Границы ``limit``: ноль поднимается до минимума, большое значение — до максимума."""
    text = " ".join(f"t{index:02d}" for index in range(1, 26))
    result = keywords.extract_keywords(text, limit=limit)
    assert len(result["keywords"]) == expected == result["count"]


@pytest.mark.parametrize("text", ["", "   ", "\n\t ", None])
def test_empty_text_is_a_tool_error(text):
    """Пустой текст — ошибка инструмента с понятной причиной, а не пустой ответ."""
    with pytest.raises(ToolError, match="Нет текста"):
        keywords.extract_keywords(text)


def test_stopwords_only_text_returns_no_words():
    """Текст из одних служебных слов — пустой, но не ошибочный результат."""
    result = keywords.extract_keywords("и а на", limit=5)
    assert result["keywords"] == []
    assert result["count"] == 0 and result["joined"] == ""


def test_joined_matches_keywords():
    """``joined`` — те же слова одной строкой через запятую."""
    result = keywords.extract_keywords("агент память агент профиль профиль", limit=10)
    assert result["joined"] == ", ".join(result["keywords"])


def test_counts_helper_limits_candidates():
    """``keyword_counts`` отдаёт кандидатов не больше запрошенного числа."""
    text = " ".join(f"t{index:02d}" for index in range(1, 26))
    ranked = keywords.keyword_counts(text, top_n=3)
    assert len(ranked) == 3
    assert [count for _, count in ranked] == [1, 1, 1]
    assert [word for word, _ in ranked] == ["t01", "t02", "t03"]
