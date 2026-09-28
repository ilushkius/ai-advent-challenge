"""Сборка набора документов дня 21 в папку ``documents/`` (день 21).

Документы — ПРОИЗВОДНЫЕ данные: их собирает код из источников репозитория
(``domain/document_sources.py``), в git они не попадают. Причина в том, что
человеческий шаг «положи файлы в папку» сломал бы обещание «демо запускается одной
кнопкой»: на свежем клоне папки нет, и кнопка не работала бы. Поэтому
``ensure_documents`` собирает набор сам, если папка пуста или в ней нет манифеста.

Манифест (``documents/manifest.json``) хранит метаданные каждого документа —
источник, вид, язык, заголовок, размер и признак усечения. Он нужен затем, что
заголовок и язык не восстановить по имени файла, а усечённый документ внешне
неотличим от короткого. Файл, которого в манифесте нет (человек положил свой),
не теряется: метаданные определяются эвристиками домена и дописываются в манифест.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from shared.logging_utils import get_logger

from ..core import config
from ..domain.document_sources import (
    DOCUMENT_SUFFIXES,
    TRUNCATION_MARKER,
    DOCUMENT_SOURCES,
    Document,
    DocumentSource,
    detect_language,
    detect_title,
    source_slug,
    truncate,
)

logger = get_logger(__name__)

#: Сколько символов в «странице» — для отчёта о размере набора документов.
CHARS_PER_PAGE = 1800


class DocumentLoader:
    """Читает источники репозитория, пишет документы и их манифест."""

    def __init__(self, documents_dir: Optional[object] = None,
                 sources: Optional[Sequence[DocumentSource]] = None,
                 repo_root: Optional[object] = None) -> None:
        loader_file = Path(__file__).resolve()
        self._documents_dir = (Path(documents_dir) if documents_dir is not None
                               else config.DOCUMENTS_DIR)
        self._sources = tuple(sources) if sources is not None else DOCUMENT_SOURCES
        # backend/services/document_loader.py → корень репозитория в parents[3].
        self._repo_root = (Path(repo_root) if repo_root is not None
                           else loader_file.parents[3])

    @property
    def documents_dir(self) -> Path:
        """Папка собранных документов."""
        return self._documents_dir

    @property
    def repo_root(self) -> Path:
        """Корень репозитория: от него считаются пути источников."""
        return self._repo_root

    def collect(self) -> Dict[str, Any]:
        """Пересобирает документы и манифест; возвращает манифест.

        Отсутствующий источник (файл переименовали или удалили) не роняет сборку:
        он пропускается с записью в лог — иначе одна правка в репозитории ломала бы
        весь день.
        """
        self._documents_dir.mkdir(parents=True, exist_ok=True)
        documents: list[dict[str, Any]] = []
        for source in self._sources:
            origin = self._repo_root / source.path
            if not origin.exists():
                logger.warning("Источник документов пропущен (нет файла): %s", source.path)
                continue
            text = origin.read_text(encoding="utf-8", errors="replace")
            content, truncated = truncate(text, source.max_chars)
            slug = source_slug(source.path)
            title = detect_title(content, source.kind, slug)
            (self._documents_dir / slug).write_text(content, encoding="utf-8")
            documents.append({
                "source": slug,
                "path": source.path,
                "kind": source.kind,
                "language": detect_language(content),
                "title": title,
                "chars": len(content),
                "truncated": truncated,
            })
        manifest = {
            "documents": documents,
            "total_chars": sum(int(item["chars"]) for item in documents),
        }
        self._write_manifest(manifest)
        logger.info("Документы собраны: %d файлов, %d символов (~%d страниц)",
                    len(documents), manifest["total_chars"],
                    manifest["total_chars"] // CHARS_PER_PAGE)
        return manifest

    def load_documents(self) -> List[Document]:
        """Читает папку документов, метаданные берёт из манифеста.

        Файл, которого в манифесте нет, получает метаданные эвристиками и попадает
        в манифест: так ручная копия документа в папку не выпадает из статистики и
        из отчёта.
        """
        manifest = self.manifest()
        known = {str(item.get("source") or ""): item for item in manifest["documents"]}
        documents: list[Document] = []
        unknown: list[dict[str, Any]] = []
        for path in sorted(self._documents_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in DOCUMENT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            meta = known.get(path.name)
            if meta is None:
                meta = self._describe(path.name, text)
                unknown.append(meta)
            documents.append(Document(
                source=path.name,
                path=path,
                title=str(meta.get("title") or path.stem),
                kind=str(meta.get("kind") or "docs"),
                language=str(meta.get("language") or detect_language(text)),
                text=text,
                chars=len(text),
                truncated=bool(meta.get("truncated")),
            ))
        if unknown:
            manifest["documents"].extend(unknown)
            manifest["total_chars"] = sum(
                int(item.get("chars") or 0) for item in manifest["documents"])
            self._write_manifest(manifest)
            logger.info("В манифест дописаны незнакомые документы: %d", len(unknown))
        return documents

    def ensure_documents(self) -> List[Document]:
        """Гарантирует набор документов: пустая папка → сборка, иначе чтение.

        Именно этот вызов делает кнопку «🚀 Запустить демо-индексацию»
        работоспособной на свежем клоне: папки документов там ещё нет.
        """
        if self.manifest()["documents"] and self._document_files():
            return self.load_documents()
        logger.info("Папка документов пуста — собираю набор из источников репозитория")
        self.collect()
        return self.load_documents()

    def manifest(self) -> Dict[str, Any]:
        """Манифест документов; отсутствующий или битый файл — пустой манифест."""
        path = self._documents_dir / "manifest.json"
        if not path.exists():
            return {"documents": [], "total_chars": 0}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Манифест документов не прочитан (%s): собираю заново", exc)
            return {"documents": [], "total_chars": 0}
        documents = data.get("documents") if isinstance(data, dict) else None
        return {
            "documents": list(documents or []),
            "total_chars": int(data.get("total_chars") or 0) if isinstance(data, dict) else 0,
        }

    # ---------- внутреннее ----------
    def _document_files(self) -> List[Path]:
        """Файлы-документы в папке (по расширениям, без манифеста)."""
        if not self._documents_dir.exists():
            return []
        return [path for path in sorted(self._documents_dir.iterdir())
                if path.is_file() and path.suffix.lower() in DOCUMENT_SUFFIXES]

    def _describe(self, source: str, text: str) -> Dict[str, Any]:
        """Метаданные незнакомого документа: вид, язык, заголовок, усечение."""
        kind = "code" if text.lstrip().startswith(("\"\"\"", "'''", "import ")) else "docs"
        return {
            "source": source,
            "path": source,
            "kind": kind,
            "language": detect_language(text),
            "title": detect_title(text, kind, source),
            "chars": len(text),
            "truncated": TRUNCATION_MARKER in text,
        }

    def _write_manifest(self, manifest: Dict[str, Any]) -> None:
        """Пишет манифест в UTF-8 рядом с документами."""
        self._documents_dir.mkdir(parents=True, exist_ok=True)
        path = self._documents_dir / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                        encoding="utf-8")


#: Единственный загрузчик процесса (папка и источники дня).
_loader: Optional[DocumentLoader] = None


def get_document_loader() -> DocumentLoader:
    """Загрузчик документов дня: одна штука на процесс."""
    global _loader
    if _loader is None:
        _loader = DocumentLoader()
    return _loader
