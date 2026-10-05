"""Тесты домена дня 24: порог релевантности, цитаты и оценка опоры ответа.

Три предмета, которые задание дня требует закрепить тестами:

* порог ``RAG_RELEVANCE_THRESHOLD`` сравнивается с максимумом косинуса фрагментов и
  читается из окружения, ``day21/.env`` или значения по умолчанию;
* цитаты детерминированы (собираются из текста чанков, а не моделью) и не длиннее
  ``QUOTE_MAX_CHARS``;
* ``quotes_verified``/``confidence`` различают ответ, подтверждённый контекстом, и
  ответ, где цитат в тексте не видно.

Фикстура ``rag_service`` опускает боевой порог до нуля: эмбеддер в тестах фейковый,
его косинус ниже реального, а эти тесты проверяют цитаты и режимы, а не отбор. Сам
порог проверяют тесты ниже — подменой константы, ``is_weak`` и разбором источников
значения.
"""
from backend.domain import rag_quotes
from rag_fakes import GROUNDED_REPLY, UNGROUNDED_REPLY

EMPTY_ANSWER = "   "


def test_mode_rag_has_sources_and_quotes(rag_service):
    """Ответ по корпусу несёт источник, цитату, уверенность и не имеет предупреждений."""
    record = rag_service.rag_query("Чему равен CHARS_PER_PAGE?")
    assert record["mode"] == rag_quotes.RAG_MODE_RAG
    assert record["sources"]
    assert record["quotes"]
    assert len(record["quotes"][0]["quote"]) <= rag_quotes.QUOTE_MAX_CHARS
    assert set(record["quotes"][0]) == set(rag_quotes.QUOTE_KEYS)
    assert record["confidence"] == rag_quotes.CONFIDENCE_HIGH
    assert record["quotes_verified"] is True
    assert record["warning"] == ""


def test_quotes_are_deterministic_prefix():
    """Цитата — начало текста до конца предложения; длинный текст режется по лимиту."""
    assert rag_quotes.quote_of("Первое предложение. Второе предложение.") == "Первое предложение."
    assert rag_quotes.quote_of("x" * 500) == "x" * 200
    assert rag_quotes.quotes_from_items(
        [{"source": "a.py", "section": "s", "chunk_id": "1", "text": "Короткий факт."}]
    ) == [{"source": "a.py", "section": "s", "chunk_id": "1", "quote": "Короткий факт."}]


def test_mode_dont_know_below_threshold(rag_service, rag_stub, monkeypatch):
    """Порог выше любого косинуса: режим «не знаю», модель не вызывается."""
    monkeypatch.setattr(rag_quotes, "RAG_RELEVANCE_THRESHOLD", 1.5)
    record = rag_service.rag_query("Чему равен CHARS_PER_PAGE?")
    assert record["mode"] == rag_quotes.RAG_MODE_DONT_KNOW
    assert record["answer"] == rag_quotes.DONT_KNOW_ANSWER
    assert record["sources"] == []
    assert record["quotes"] == []
    assert record["confidence"] == rag_quotes.CONFIDENCE_NONE
    assert "Недостаточно контекста" in record["warning"]
    assert record["tokens"] is None
    assert rag_stub.calls == []


def test_mode_rag_above_threshold(rag_service, rag_stub, monkeypatch):
    """Достижимый порог: ответ по корпусу с источниками, цитатами и одним вызовом модели."""
    monkeypatch.setattr(rag_quotes, "RAG_RELEVANCE_THRESHOLD", 0.0)
    record = rag_service.rag_query("Чему равен CHARS_PER_PAGE?")
    assert record["mode"] == rag_quotes.RAG_MODE_RAG
    assert record["sources"]
    assert record["quotes"]
    assert len(rag_stub.calls) == 1


def test_is_weak_uses_max_vector_score():
    """Порог сравнивается с максимумом по фрагментам, а не с первым из них."""
    assert rag_quotes.is_weak([{"vector_score": 0.61}], 0.6) is False
    assert rag_quotes.is_weak([{"vector_score": 0.59}], 0.6) is True
    assert rag_quotes.is_weak([], 0.6) is True
    assert rag_quotes.is_weak([{"vector_score": 0.59}, {"vector_score": 0.9}], 0.6) is False


def test_threshold_resolution(tmp_path):
    """Порядок источников порога: окружение, затем файл, затем значение по умолчанию."""
    missing = tmp_path / "нет"
    assert rag_quotes.resolve_relevance_threshold(
        env={"RAG_RELEVANCE_THRESHOLD": "0.75"}, path=missing) == 0.75
    env_file = tmp_path / ".env"
    env_file.write_text('# комментарий\nRAG_RELEVANCE_THRESHOLD="0.42"\n',
                        encoding="utf-8")
    assert rag_quotes.resolve_relevance_threshold(env={}, path=env_file) == 0.42
    assert rag_quotes.resolve_relevance_threshold(
        env={"RAG_RELEVANCE_THRESHOLD": "abc"}, path=env_file) == 0.6
    assert rag_quotes.resolve_relevance_threshold(
        env={"RAG_RELEVANCE_THRESHOLD": "1.5"}, path=env_file) == 0.6


def test_verify_citations(rag_service):
    """Проверка опоры: цитата либо входит в ответ, либо пересекается с ним по словам."""
    quotes = rag_service.rag_query("Чему равен CHARS_PER_PAGE?")["quotes"]
    assert rag_quotes.verify_citations(GROUNDED_REPLY, quotes) is True
    assert rag_quotes.verify_citations(UNGROUNDED_REPLY, quotes) is False
    overlapping = [{"quote": "Одной странице равен CHARS_PER_PAGE: 1800 символов на страницу."}]
    answer = "На страницу приходится 1800 символов, значение задаёт CHARS_PER_PAGE."
    assert rag_quotes.verify_citations(answer, overlapping) is True
    assert rag_quotes.verify_citations(EMPTY_ANSWER, quotes) is False


def test_no_rag_query_has_no_quotes(rag_service):
    """Ответ без RAG: цитат нет, уверенность нулевая."""
    record = rag_service.no_rag_query("вопрос что-нибудь")
    assert record["mode"] == rag_quotes.RAG_MODE_NO_RAG
    assert record["quotes"] == []
    assert record["quotes_verified"] is False
    assert record["confidence"] == 0.0
