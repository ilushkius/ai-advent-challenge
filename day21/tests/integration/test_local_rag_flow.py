"""Сквозной прогон дня 28 на настоящих весах: локальный retrieval и настоящая Ollama.

Проверяется связка целиком: FAISS-индекс дня 22 с диска, настоящая модель эмбеддингов
из кэша ``index/models`` и настоящая Ollama на ``localhost:11434``. Запрет на загрузку
весов (autouse-фикстура ``isolated_indexing``) снимается явно: обычные тесты не должны
молча тянуть сотни мегабайт, а этому тесту нужны настоящие векторы, иначе проверить
локальный цикл нельзя. Генерация не подменяется и не мокается — ответ приходит от
модели.

База только читается: ``document_chunks`` в ``day21/agents.db`` — источник метаданных
для векторов индекса (сам индекс лежит файлом). Файлы тест не пишет.
"""
import pytest
import requests

from backend.core import config
from backend.domain import rag_mode, rag_quotes
from backend.services.index_service import IndexService
from backend.services.rag_service import RAGService
from backend.storage.chunk_store import ChunkStore

from rag_fakes import RagStubReranker

pytestmark = pytest.mark.slow

#: Вопрос с ответом в корпусе: значение есть в ``document_loader`` дня 21.
QUESTION = "Чему равен CHARS_PER_PAGE в document_loader?"

#: Вопрос вне корпуса: ответа в документах дня быть не может.
OUTSIDE_QUESTION = "Как приготовить борщ на ужин?"


@pytest.fixture
def ollama_ready():
    """Пропускает тест, если Ollama недоступна: без неё локальный цикл не проверить."""
    try:
        requests.get(f"{config.LOCAL_LLM_URL}/api/tags", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(f"Ollama недоступна ({config.LOCAL_LLM_URL}): {exc}")


@pytest.fixture
def real_embedder(monkeypatch):
    """Настоящая модель эмбеддингов: slow-тесту нужны настоящие векторы.

    Autouse-фикстура ``isolated_indexing`` запрещает загрузку весов, поэтому запрет
    снимается явно, а готовая модель передаётся службе параметром ``backend``:
    ``_load`` уже никого не трогает. Веса лежат в ``day21/index/models`` (их скачала
    индексация дня 21) — сети не нужно.
    """
    from sentence_transformers import SentenceTransformer

    from backend.services.embedding_service import EmbeddingService

    model = SentenceTransformer(config.EMBEDDING_MODEL,
                                cache_folder=str(config.INDEX_MODELS_DIR),
                                local_files_only=True)
    monkeypatch.setattr(EmbeddingService, "_load", lambda self: None)
    return EmbeddingService(backend=model)


@pytest.fixture
def real_store():
    """Настоящее хранилище чанков (только чтение): метаданные строк индекса дня 22."""
    return ChunkStore()


@pytest.fixture
def local_rag_service(ollama_ready, real_embedder, real_store):
    """Служба RAG дня 28: индекс дня 22 с диска, настоящий эмбеддер, настоящая Ollama."""
    index_service = IndexService(embedder=real_embedder, store=real_store,
                                 index_dir=config.INDEX_DIR)
    index_path = index_service.path_for(rag_mode.RAG_DEFAULT_STRATEGY)
    if not index_path.exists():
        pytest.skip(f"индекс дня 22 не собран ({index_path}): scripts/index_rag_corpus.py")
    if not real_store.chunks(rag_mode.RAG_DEFAULT_STRATEGY, limit=1):
        pytest.skip("в document_chunks нет чанков корпуса: соберите индекс дня 22")
    return RAGService(index_service=index_service, store=real_store,
                      rerank_service=RagStubReranker())


def test_local_rag_answers_from_corpus(local_rag_service):
    """Ответ локальной модели по корпусу: источник, цитаты, токены и время на месте."""
    record = local_rag_service.rag_query(QUESTION, top_k=3, provider="local")

    assert record["provider"] == "local"
    assert record["mode"] == rag_quotes.RAG_MODE_RAG, record.get("warning")
    assert record["sources"], "источники пусты: индекс и база разошлись"
    sources = [item["source"] for item in record["sources"]]
    assert "day21-backend-services-document_loader.py" in sources
    assert record["answer"].strip()
    assert record["quotes"], "цитаты прикрепляются к использованным фрагментам"
    assert record["tokens"]["model"] == config.LOCAL_LLM_MODEL
    assert record["duration_ms"] > 0


def test_local_rag_dont_know_without_model_call(local_rag_service):
    """Вопрос вне корпуса: режим «не знаю», модель не вызывалась и токенов нет."""
    record = local_rag_service.rag_query(OUTSIDE_QUESTION, top_k=3, provider="local")

    assert record["mode"] == rag_quotes.RAG_MODE_DONT_KNOW
    assert record["provider"] == "local"
    assert record["sources"] == [] and record["quotes"] == []
    assert record["tokens"] is None
