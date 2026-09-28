"""Загрузчик документов: сборка из источников, манифест и эвристики (день 21).

Проверяется путь «источники репозитория → папка documents/ + manifest.json» и его
устойчивость: пропавший источник не роняет сборку, а незнакомый файл в папке не
теряется — иначе документ выпал бы из статистики и из отчёта молча.
"""
import json

from backend.domain.document_sources import (
    KIND_CODE,
    KIND_DOCS,
    DocumentSource,
)
from backend.services.document_loader import DocumentLoader

#: Длинный файл: он проверяет усечение с маркером.
LONG_TEXT = "# Длинный документ\n\n" + "строка текста\n" * 40
#: Короткий код: заголовок берётся из модульного докстринга.
CODE = '"""Модуль примера."""\nimport enum\n\n\nclass State(enum.Enum):\n    """Состояние."""\n\n    IDLE = "idle"\n'


def _repo(tmp_path):
    """Создаёт поддельный репозиторий: два файла-источника под именами дня."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "docs" / "long.md").write_text(LONG_TEXT, encoding="utf-8")
    (tmp_path / "src" / "sample.py").write_text(CODE, encoding="utf-8")
    return tmp_path


def _loader(tmp_path, sources=None, max_chars=60):
    """Загрузчик на поддельном репозитории и отдельной папке документов."""
    return DocumentLoader(
        documents_dir=tmp_path / "documents",
        sources=sources if sources is not None else (
            DocumentSource("docs/long.md", KIND_DOCS, max_chars),
            DocumentSource("src/sample.py", KIND_CODE, 10_000),
        ),
        repo_root=_repo(tmp_path),
    )


def test_collect_writes_documents_and_manifest(tmp_path):
    """Сборка пишет файлы документов и манифест с метаданными каждого."""
    loader = _loader(tmp_path)
    manifest = loader.collect()
    sources = [item["source"] for item in manifest["documents"]]
    assert sources == ["docs-long.md", "src-sample.py"]
    assert manifest["total_chars"] == sum(item["chars"] for item in manifest["documents"])
    for item in manifest["documents"]:
        assert (loader.documents_dir / item["source"]).exists()
    stored = json.loads((loader.documents_dir / "manifest.json").read_text(encoding="utf-8"))
    assert stored == manifest


def test_collect_marks_truncated_documents(tmp_path):
    """Усечённый документ получает маркер в файле и признак в манифесте."""
    loader = _loader(tmp_path)
    manifest = loader.collect()
    truncated = next(item for item in manifest["documents"]
                     if item["source"] == "docs-long.md")
    assert truncated["truncated"] is True
    assert truncated["chars"] <= 60 + len("\n\n<!-- документ усечён -->")
    text = (loader.documents_dir / "docs-long.md").read_text(encoding="utf-8")
    assert "<!-- документ усечён -->" in text
    # Второй источник короткий и целиком помещается в предел.
    assert next(item for item in manifest["documents"]
                if item["source"] == "src-sample.py")["truncated"] is False


def test_collect_uses_domain_metadata(tmp_path):
    """Заголовок, вид и язык документа берутся из домена, а не из имени файла."""
    loader = _loader(tmp_path, max_chars=10_000)
    manifest = loader.collect()
    markdown = next(item for item in manifest["documents"]
                    if item["source"] == "docs-long.md")
    code = next(item for item in manifest["documents"]
                if item["source"] == "src-sample.py")
    assert markdown["title"] == "Длинный документ"
    assert markdown["kind"] == KIND_DOCS
    assert code["title"] == "Модуль примера."
    assert code["kind"] == KIND_CODE
    assert markdown["language"] == "ru"


def test_collect_skips_missing_source(tmp_path):
    """Пропавший источник пропускается с записью в лог, а не роняет сборку."""
    sources = (
        DocumentSource("docs/long.md", KIND_DOCS, 1000),
        DocumentSource("docs/gone.md", KIND_DOCS, 1000),
    )
    loader = _loader(tmp_path, sources=sources)
    manifest = loader.collect()
    assert [item["source"] for item in manifest["documents"]] == ["docs-long.md"]


def test_load_documents_takes_metadata_from_manifest(tmp_path):
    """Чтение папки берёт заголовок и язык из манифеста, а не пересчитывает."""
    loader = _loader(tmp_path, max_chars=10_000)
    loader.collect()
    stored = json.loads((loader.documents_dir / "manifest.json").read_text(encoding="utf-8"))
    stored["documents"][0]["title"] = "Заголовок из манифеста"
    (loader.documents_dir / "manifest.json").write_text(
        json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    documents = loader.load_documents()
    assert documents[0].title == "Заголовок из манифеста"
    assert documents[0].chars == len(documents[0].text)


def test_load_documents_describes_unknown_file(tmp_path):
    """Файл, которого нет в манифесте, получает метаданные эвристиками и попадает в него."""
    loader = _loader(tmp_path)
    loader.collect()
    (loader.documents_dir / "свои-заметки.md").write_text(
        "# Мои заметки\n\nтекст\n", encoding="utf-8")
    documents = loader.load_documents()
    extra = next(item for item in documents if item.source == "свои-заметки.md")
    assert extra.title == "Мои заметки"
    manifest = loader.manifest()
    assert any(item["source"] == "свои-заметки.md" for item in manifest["documents"])
    assert manifest["total_chars"] == sum(int(item["chars"]) for item in manifest["documents"])


def test_ensure_documents_collects_when_folder_is_empty(tmp_path):
    """Пустая папка собирается из источников: свежий клон работает одной кнопкой."""
    loader = _loader(tmp_path)
    assert loader.manifest()["documents"] == []
    documents = loader.ensure_documents()
    assert [document.source for document in documents] == ["docs-long.md", "src-sample.py"]
    assert loader.manifest()["documents"]


def test_ensure_documents_reads_existing_folder(tmp_path):
    """Заполненная папка только читается: повторная сборка не нужна."""
    loader = _loader(tmp_path)
    loader.collect()
    (loader.documents_dir / "docs-long.md").write_text("# Переписанный\n\nтекст\n",
                                                       encoding="utf-8")
    documents = {document.source: document for document in loader.ensure_documents()}
    assert documents["docs-long.md"].text.startswith("# Переписанный")


def test_manifest_survives_broken_json(tmp_path):
    """Битый манифест читается как пустой: сборка не падает на испорченном файле."""
    loader = _loader(tmp_path)
    loader.documents_dir.mkdir(parents=True, exist_ok=True)
    (loader.documents_dir / "manifest.json").write_text("{не json", encoding="utf-8")
    assert loader.manifest() == {"documents": [], "total_chars": 0}
