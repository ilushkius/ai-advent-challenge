"""Оценка RAG (день 22): 10 контрольных вопросов и правило вердикта.

Вопросы — измерительный инструмент отчёта ``docs/reports/rag_modes.md``, а не
демонстрация: каждый спрашивает про ФАКТ ИЗ ФАЙЛА дня 21, которого нет в общих
знаниях модели (имя константы, её значение, порядок вызовов, точный текст ошибки).
Если модель отвечает такой факт без контекста — значит, она отвечала по памяти
модели, а не по корпусу, и сравнение с RAG теряет смысл. Поэтому в каждом вопросе
назван файл: поиск получает шанс найти релевантный чанк, а не только ключевое слово.

Список лежит в доменном слое (как ``index_scenarios.DEMO_QUERIES`` дня 21): его
читают отчёт, тесты и скрипт прогона, поэтому формулировки и эталоны хранятся
в одном месте. Вердикт считается механически — по вхождению ключевых фактов в
текст ответа без учёта регистра: это эвристика, и в отчёте она названа эвристикой.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

#: Вердикты сравнения ответов «с RAG» и «без RAG» по доле найденных фактов.
VERDICT_BETTER = "лучше"
VERDICT_WORSE = "хуже"
VERDICT_SAME = "равно"


@dataclass(frozen=True)
class RagQuestion:
    """Контрольный вопрос с эталонными фактами и ожидаемыми источниками корпуса."""

    question: str
    #: Литералы, которые обязаны быть в верном ответе (проверка вхождением).
    key_facts: tuple[str, ...]
    #: Пути источников корпуса от корня репозитория (для колонки «источники»).
    expected_sources: tuple[str, ...]
    #: Эталонная формулировка факта: она идёт в колонку «ожидание» отчёта.
    note: str


#: Контрольный набор: 10 вопросов, порядок = порядок строк в отчёте.
RAG_QUESTIONS: tuple[RagQuestion, ...] = (
    RagQuestion(
        question="Чему равно EXCERPT_CHARS в day21/backend/domain/indexing_prompt.py и "
                 "какой заголовок печатает render_index_block?",
        key_facts=("EXCERPT_CHARS", "300", "Контекст из индекса документов"),
        expected_sources=("day21/backend/domain/indexing_prompt.py",),
        note="EXCERPT_CHARS = 300; INDEX_BLOCK_HEADER = "
             "«## Контекст из индекса документов»",
    ),
    RagQuestion(
        question="Сколько символов в одной «странице» при подсчёте объёма документов: "
                 "чему равен CHARS_PER_PAGE в day21/backend/services/document_loader.py?",
        key_facts=("CHARS_PER_PAGE", "1800"),
        expected_sources=("day21/backend/services/document_loader.py",),
        note="CHARS_PER_PAGE = 1800",
    ),
    RagQuestion(
        question="Чему равен PREVIEW_CHARS в day21/backend/services/index_service.py и "
                 "какое сообщение бросается, если индекс стратегии пуст?",
        key_facts=("PREVIEW_CHARS", "300", "Индекс стратегии", "пуст"),
        expected_sources=("day21/backend/services/index_service.py",),
        note="PREVIEW_CHARS = 300; IndexNotBuiltError(f«Индекс стратегии {strategy!r} "
             "пуст: сначала выполните индексацию»)",
    ),
    RagQuestion(
        question="С какой долей кириллицы текст считается русским (CYRILLIC_RATIO) и "
                 "сколько записей в таблице DOCUMENT_SOURCES "
                 "(day21/backend/domain/document_sources.py)?",
        key_facts=("CYRILLIC_RATIO", "0.15", "DOCUMENT_SOURCES", "25"),
        expected_sources=("day21/backend/domain/document_sources.py",),
        note="CYRILLIC_RATIO = 0.15; в таблице DOCUMENT_SOURCES 25 записей",
    ),
    RagQuestion(
        question="Какой поток прогрева моделей создаёт при старте "
                 "day21/backend/api/lifespan.py (threading.Thread, daemon=True, name=) "
                 "и что запускается до этого потока?",
        key_facts=("init_db", "restore_from_db", "model-warmup"),
        expected_sources=("day21/backend/api/lifespan.py",),
        note="database.init_db() → get_manager().restore_from_db() → "
             "get_scheduler().start() → get_mcp_registry().connect_all() → "
             "get_index_service().load_all(); поток name=«model-warmup» прогревает "
             "эмбеддер и реранкер (день 23)",
    ),
    RagQuestion(
        question="Как ChunkStore.add_chunks проставляет embedding_id и какие id "
                 "пропускает rows_by_ids (day21/backend/storage/chunk_store.py)?",
        key_facts=("embedding_id", "flush", "-1", "пропускаются"),
        expected_sources=("day21/backend/storage/chunk_store.py",),
        note="вставка идёт пачкой с flush(), затем строкам проставляется "
             "orm.embedding_id = orm.id; rows_by_ids пропускает id, которых нет в БД "
             "(например, -1 — «пустая ячейка» FAISS), порядок результата = порядок ids",
    ),
    RagQuestion(
        question="Какие значения у INDEX_AGENT_TOP_K и INDEX_AGENT_STRATEGY и чему "
                 "равен INDEX_MAX_TOP_K (day21/backend/core/config.py)?",
        key_facts=("INDEX_AGENT_TOP_K", "INDEX_AGENT_STRATEGY", "structural",
                   "INDEX_MAX_TOP_K", "20"),
        expected_sources=("day21/backend/core/config.py",),
        note="INDEX_AGENT_TOP_K = 3, INDEX_AGENT_STRATEGY = «structural», "
             "INDEX_MAX_TOP_K = 20",
    ),
    RagQuestion(
        question="Какое исключение и с каким текстом бросает LLMClient, если не передан "
                 "client_factory (day21/backend/services/llm_client.py)?",
        key_facts=("RuntimeError", "client_factory", "Agent._make_client"),
        expected_sources=("day21/backend/services/llm_client.py",),
        note="RuntimeError(«LLMClient без client_factory: передайте фабрику клиента "
             "(в приложении это Agent._make_client)»)",
    ),
    RagQuestion(
        question="Какие хосты пропускает тестовый гвард no_real_network и как строится "
                 "временная SQLite-база в тестах (day21/tests/conftest.py)?",
        key_facts=("no_real_network", "127.", "localhost", "schema_template"),
        expected_sources=("day21/tests/conftest.py",),
        note="разрешены префиксы («127.», «localhost», «::1», «0.0.0.0»), иначе "
             "AssertionError; фикстура schema_template (session) создаёт файл схемы, "
             "а session_factory копирует его в tmp_path/«test.db»",
    ),
    RagQuestion(
        question="Какие поля у TestQuery и что делает validate_queries "
                 "(day21/backend/domain/index_scenarios.py)?",
        key_facts=("TestQuery", "query", "expected_sources", "validate_queries"),
        expected_sources=("day21/backend/domain/index_scenarios.py",),
        note="@dataclass(frozen=True) TestQuery(query, expected_sources, note) и "
             "DEMO_QUERIES из пяти записей; validate_queries() возвращает список "
             "проблем (пустой список = всё валидно)",
    ),
)


def question_as_dict(question: RagQuestion) -> dict[str, Any]:
    """Вопрос словарём: так его читают отчёт, тесты и ответ API оценки."""
    return {
        "question": question.question,
        "key_facts": list(question.key_facts),
        "expected_sources": list(question.expected_sources),
        "note": question.note,
    }


def facts_found(answer: str, question: RagQuestion) -> tuple[str, ...]:
    """Какие эталонные факты встречаются в ответе (вхождение без учёта регистра)."""
    text = str(answer or "").lower()
    return tuple(fact for fact in question.key_facts if fact.lower() in text)


def fact_score(answer: str, question: RagQuestion) -> float:
    """Доля найденных эталонных фактов: 0.0 — ничего, 1.0 — все."""
    if not question.key_facts:
        return 0.0
    return round(len(facts_found(answer, question)) / len(question.key_facts), 4)


def verdict(with_score: float, without_score: float) -> str:
    """Сравнение ответов по доле найденных фактов: лучше, хуже или равно."""
    if with_score > without_score:
        return VERDICT_BETTER
    if with_score < without_score:
        return VERDICT_WORSE
    return VERDICT_SAME


def source_matches(source: str, expected: str) -> bool:
    """Совпадает ли источник поиска с ожидаемым путём (сравнение по буквам и цифрам).

    Источники корпуса — слаги вроде ``day21-backend-domain-indexing_prompt.py``, а
    ожидания записаны путями репозитория. Регистр, ``/``, ``-`` и ``_`` различий не
    создают, поэтому в отчёте находится тот же файл.
    """
    left, right = _key(source), _key(expected)
    return bool(left) and bool(right) and (left == right or left in right or right in left)


def expected_found(sources: Iterable[str], question: RagQuestion) -> bool:
    """Встретился ли в выдаче поиска хотя бы один ожидаемый источник вопроса."""
    hits = [str(source or "") for source in sources]
    return any(
        source_matches(source, expected)
        for source in hits
        for expected in question.expected_sources
    )


def _key(value: Any) -> str:
    """Ключ сравнения имён: только буквы и цифры, нижний регистр."""
    return "".join(char for char in str(value or "").lower() if char.isalnum())


__all__ = [
    "RAG_QUESTIONS",
    "RagQuestion",
    "VERDICT_BETTER",
    "VERDICT_SAME",
    "VERDICT_WORSE",
    "expected_found",
    "fact_score",
    "facts_found",
    "question_as_dict",
    "source_matches",
    "verdict",
]
