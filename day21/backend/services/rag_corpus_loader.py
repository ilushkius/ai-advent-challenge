"""Загрузчик корпуса RAG: каталог ``documents/rag_corpus`` и источники дня 21.

Наследник ``DocumentLoader``: сборка, чтение и манифест те же, отличается только
набор источников (файлы дня 21 из ``domain/rag_corpus_spec``) и папка
(``documents/rag_corpus`` — рядом с документами индексации, чтобы корпуса не
смешивались, а ``documents/`` целиком оставалась производными данными).

Корпус — производные данные: в git он не попадает, поэтому ``ensure_documents``
собирает его сам, если папки нет. ``status`` отвечает на вопрос «хватает ли корпуса
для отчёта» (объём в страницах против минимума), ``validate`` — на вопрос «все ли
источники на месте», причём ДО сборки: ``DocumentLoader.collect`` пропустил бы
пропавший файл с записью в журнал, и корпус оказался бы тихо неполным.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from shared.logging_utils import get_logger

from ..core import config
from ..domain import rag_corpus_spec
from ..domain.document_sources import DocumentSource
from .document_loader import CHARS_PER_PAGE, DocumentLoader

logger = get_logger(__name__)


class RagCorpusLoader(DocumentLoader):
    """Загрузчик корпуса режима RAG: папка ``documents/rag_corpus`` и файлы дня 21."""

    def __init__(self, documents_dir: Optional[object] = None,
                 sources: Optional[Sequence[DocumentSource]] = None,
                 repo_root: Optional[object] = None) -> None:
        # Пустой кортеж источников — это «ничего не собирать» (тесты и ручные
        # прогоны), поэтому проверяется именно None, а не ложность значения.
        self._rag_sources = (rag_corpus_spec.RAG_CORPUS_SOURCES
                             if sources is None else tuple(sources))
        super().__init__(
            documents_dir=documents_dir or (config.DOCUMENTS_DIR
                                            / rag_corpus_spec.RAG_CORPUS_SUBDIR),
            sources=self._rag_sources,
            repo_root=repo_root,
        )

    @property
    def sources(self) -> Sequence[DocumentSource]:
        """Источники корпуса: таблица дня 21 или подменённый набор."""
        return self._rag_sources

    def status(self) -> Dict[str, Any]:
        """Состояние корпуса: документы, символы, страницы, готовность к отчёту.

        Число документов считается по файлам в папке, а объём — по манифесту: файл
        могли удалить руками, и тогда число в манифесте разошлось бы с фактом.
        """
        manifest = self.manifest()
        files = self._document_files()
        chars = int(manifest.get("total_chars") or 0)
        pages = rag_corpus_spec.corpus_pages(chars, CHARS_PER_PAGE)
        return {
            "corpus_dir": str(self.documents_dir),
            "documents": len(files),
            "chars": chars,
            "pages": pages,
            "min_pages": rag_corpus_spec.RAG_CORPUS_MIN_PAGES,
            "subdir": rag_corpus_spec.RAG_CORPUS_SUBDIR,
            "ready": bool(files) and pages >= rag_corpus_spec.RAG_CORPUS_MIN_PAGES,
        }

    def validate(self) -> List[str]:
        """Проблемы состава корпуса: пропавшие файлы и суффиксы вне загрузчика."""
        problems = rag_corpus_spec.validate_sources(self._rag_sources)
        for problem in problems:
            logger.warning("Корпус RAG: %s", problem)
        return problems

    def ensure_documents(self) -> List[Any]:
        """Гарантирует корпус: пустая папка → сборка, иначе чтение файлов."""
        problems = self.validate()
        if problems:
            logger.warning("Корпус RAG собирается с проблемами: %d", len(problems))
        return super().ensure_documents()


#: Единственный загрузчик корпуса процесса (папка ``documents/rag_corpus``).
_loader: Optional[RagCorpusLoader] = None


def get_rag_corpus_loader() -> RagCorpusLoader:
    """Загрузчик корпуса RAG: одна штука на процесс."""
    global _loader
    if _loader is None:
        _loader = RagCorpusLoader()
    return _loader


__all__ = ["RagCorpusLoader", "get_rag_corpus_loader"]
