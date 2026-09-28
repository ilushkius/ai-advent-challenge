"""Фикстуры индексации документов (день 21).

Вынесены из `tests/conftest.py`: тот упёрся в лимит 400 строк (правила дня). Файл
импортируется обратно в conftest, поэтому тесты видят фикстуры под теми же
именами, что и раньше. Фейки индексации — в `tests/indexing_fakes.py`.
"""
import pytest

from backend.services.document_loader import DocumentLoader
from backend.services.index_service import IndexService
from backend.services.indexing_service import IndexingService
from backend.storage.chunk_store import ChunkStore
from backend.storage.index_run_store import IndexRunStore

from indexing_fakes import FakeEmbedder, make_documents


@pytest.fixture(autouse=True)
def isolated_indexing(tmp_path, monkeypatch):
    """Уводит индексацию от рабочих файлов дня и запрещает загрузку модели.

    Две ловушки, которые эта фикстура закрывает для ВСЕХ тестов дня:

    * ``lifespan`` приложения зовёт ``load_all``/``save_all`` у службы индексов
      процесса — то есть читал и писал бы рабочие ``day21/index/*.index`` и держал
      бы их в общем singleton между тестами. Поэтому ``main.get_index_service``
      подменяется службой на ``tmp_path``: файлов там нет, писать нечего;
    * модель эмбеддингов весит сотни мегабайт и требует сети. ``warmup`` в
      демон-потоке старта попытался бы её загрузить, поэтому ``EmbeddingService._load``
      заменён функцией-ошибкой: случайная загрузка настоящей модели = падение теста
      (у ``warmup`` исключение ловится, поэтому старт приложения не ломается).
    """
    import backend.api.main as main

    from backend.services import embedding_service as embedding_module
    from backend.services import index_service as index_module
    from backend.services import indexing_service as indexing_module
    from backend.services.embedding_service import EmbeddingService
    from backend.services.index_service import IndexService

    monkeypatch.setattr(indexing_module, "_service", None)
    monkeypatch.setattr(index_module, "_service", None)
    monkeypatch.setattr(embedding_module, "_service", None)

    def no_real_model(_self):
        """Настоящая модель в тестах не загружается (сеть и сотни мегабайт)."""
        raise AssertionError("тест попытался загрузить настоящую модель эмбеддингов")

    monkeypatch.setattr(EmbeddingService, "_load", no_real_model)

    isolated = IndexService(embedder=EmbeddingService(),
                            index_dir=tmp_path / "index-isolated")
    monkeypatch.setattr(main, "get_index_service", lambda: isolated)
    yield isolated


@pytest.fixture
def documents_dir(tmp_path):
    """Папка с тремя тестовыми документами: markdown, plain text и Python."""
    base = tmp_path / "documents"
    make_documents(base)
    return base


@pytest.fixture
def documents(documents_dir):
    """Три тестовых документа как ``Document`` (метаданные — эвристиками домена)."""
    return DocumentLoader(documents_dir=documents_dir,
                          sources=()).ensure_documents()


@pytest.fixture
def document_loader(documents_dir):
    """Загрузчик на тестовой папке: сборка из репозитория тесту не нужна."""
    return DocumentLoader(documents_dir=documents_dir, sources=())


@pytest.fixture
def fake_embedder():
    """Эмбеддер на хешах слов: детерминированный, без модели и без сети."""
    return FakeEmbedder()


@pytest.fixture
def chunk_store(session_factory):
    """Хранилище чанков на временной БД."""
    return ChunkStore(session_factory=session_factory)


@pytest.fixture
def index_run_store(session_factory):
    """Хранилище запусков индексации на временной БД."""
    return IndexRunStore(session_factory=session_factory)


@pytest.fixture
def index_service(tmp_path, fake_embedder, chunk_store):
    """Служба индексов на фейковом эмбеддере, временной БД и временном каталоге."""
    return IndexService(embedder=fake_embedder, store=chunk_store,
                        index_dir=tmp_path / "index")


@pytest.fixture
def indexing_service(index_service, document_loader, index_run_store):
    """Служба индексации: те же три документа, фейковый эмбеддер, временная БД."""
    return IndexingService(index_service=index_service, loader=document_loader,
                           run_store=index_run_store)
