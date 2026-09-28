"""Структуры ответов инструментов ``storage_server`` (``TypedDict``).

Из этих структур MCP SDK собирает ``outputSchema`` инструмента, поэтому
``structuredContent`` ответа равен самому словарю, а не склеенной руками строке.
Структуры те же, что у инструментов сохранения дня 19, плюс записи базы и выдача
сохранённого файла.
"""
from typing import List, TypedDict


class SavedFile(TypedDict):
    """Файл записан: имя, путь, размер, формат и момент записи."""

    filename: str
    filepath: str
    size_bytes: int
    format: str
    saved_at: str


class SavedRecord(TypedDict):
    """Строка записана в базу: id, вид, заголовок, источник, размер и момент."""

    row_id: int
    kind: str
    title: str
    source: str
    size_bytes: int
    created_at: str


class SavedFileInfo(TypedDict):
    """Сведения о файле каталога вывода для списка ``list_saved``."""

    filename: str
    filepath: str
    size_bytes: int
    format: str
    saved_at: str


class SavedRecordInfo(TypedDict):
    """Сведения о строке базы для списка ``list_saved``."""

    row_id: int
    kind: str
    title: str
    source: str
    created_at: str


class SavedList(TypedDict):
    """Результат ``list_saved``: файлы, строки базы, их общее число и вид выборки."""

    files: List[SavedFileInfo]
    rows: List[SavedRecordInfo]
    count: int
    kind: str


class LoadedFile(TypedDict):
    """Прочитанный файл: имя, путь, число символов, формат и сам текст."""

    filename: str
    filepath: str
    chars: int
    format: str
    text: str
