"""Фикстуры режима RAG (день 22).

Вынесены из `tests/conftest.py` тем же приёмом, что фикстуры индексации: файл
импортируется обратно в conftest, поэтому pytest видит фикстуры как объявленные
там. Корпус — два маленьких документа (`tests/rag_fakes.py`), индекс — на фейковом
эмбеддере, модель — заглушка: тесты RAG идут офлайн.
"""
import pytest

from backend.domain.rag_mode import RAG_STRATEGIES
from backend.services.chunker import chunk_document
from backend.services.index_service import IndexService
from backend.services.llm_client import LLMClient
from backend.services.rag_corpus_loader import RagCorpusLoader
from backend.services.rag_service import AGENT_ID, CHUNK_STRATEGIES, RAGService
from backend.storage.llm_usage_store import LLMUsageStore

from rag_fakes import RagStubClient, write_corpus


@pytest.fixture
def rag_corpus_dir(tmp_path):
    """Папка тестового корпуса: два markdown-документа с редким литералом."""
    return write_corpus(tmp_path)


@pytest.fixture
def rag_loader(rag_corpus_dir):
    """Загрузчик тестового корпуса: файлы берутся из папки, а не из репозитория."""
    return RagCorpusLoader(documents_dir=rag_corpus_dir, sources=())


@pytest.fixture
def rag_documents(rag_loader):
    """Документы тестового корпуса так, как их видит индексация."""
    return rag_loader.ensure_documents()


@pytest.fixture
def rag_index_service(tmp_path, fake_embedder, chunk_store, rag_documents):
    """Служба индексов с обоими индексами RAG: фейковый эмбеддер, временная БД."""
    service = IndexService(embedder=fake_embedder, store=chunk_store,
                           index_dir=tmp_path / "index")
    for strategy in RAG_STRATEGIES:
        chunks = [chunk for document in rag_documents
                  for chunk in chunk_document(document, CHUNK_STRATEGIES[strategy])]
        service.index_chunks(chunks, strategy)
    return service


@pytest.fixture
def empty_index_service(tmp_path, fake_embedder, chunk_store):
    """Служба индексов без единого чанка: проверяет отказ «индекс пуст»."""
    return IndexService(embedder=fake_embedder, store=chunk_store,
                        index_dir=tmp_path / "empty-index")


@pytest.fixture
def rag_usage_store(session_factory):
    """Журнал расходов RAG на временной БД."""
    return LLMUsageStore(session_factory=session_factory)


@pytest.fixture
def rag_stub():
    """Заглушка клиента DeepSeek: пишет вызовы и отвечает текстом про корпус."""
    return RagStubClient()


@pytest.fixture
def rag_client(rag_usage_store, rag_stub):
    """Обёртка вызова LLM на заглушке и временном журнале расходов."""
    client = LLMClient(agent_id=AGENT_ID, client_factory=lambda: rag_stub,
                       store=rag_usage_store)
    client.stub = rag_stub
    return client


@pytest.fixture
def rag_service(rag_loader, rag_index_service, chunk_store, rag_client):
    """Служба RAG на тестовом корпусе: без пауз между попытками."""
    return RAGService(index_service=rag_index_service, loader=rag_loader,
                      store=chunk_store, llm_client=rag_client,
                      sleep=lambda _seconds: None)
