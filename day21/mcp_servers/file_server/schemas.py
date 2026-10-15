"""Структуры ответов инструментов сервера файлов (``TypedDict``).

Из аннотаций возврата SDK собирает ``outputSchema`` инструмента, а
``structuredContent`` ответа становится самим словарём — поэтому ответы описаны
типами, а не склеенными строками. Все поля обязательны: инструмент заполняет их
всегда (пустые значения — пустая строка, пустой список или ``False``), и клиенту
не приходится проверять каждое поле на существование.

Описанные здесь ответы — только у инструментов с ОБЪЕКТОМ в корне. Три инструмента
отдают коллекции и текст: ``search_in_files`` — список совпадений,
``list_files`` — список имён, ``get_file_diff`` — сам diff. SDK публикует
``outputSchema`` лишь для объекта в корне, поэтому их ответы приходят клиенту
текстом JSON (список) или текстом как есть (diff), и разбирает их служба
(``FileAssistantService._payload``). Так же устроены ``get_git_diff`` у
``dev_server`` и ``search_local`` у ``search_server``.
"""
from typing import TypedDict


class FileContent(TypedDict):
    """Содержимое прочитанного файла: путь, размеры, признак обрезки и текст.

    ``size_bytes`` — размер файла на диске ЦЕЛИКОМ, ``chars`` — сколько символов
    вернулось (не больше ``max_bytes``), ``lines`` — строк в возвращённом тексте,
    ``truncated`` — файл длиннее лимита, ``modified_at`` — время правки ISO-8601 UTC.
    """

    path: str
    size_bytes: int
    chars: int
    lines: int
    truncated: bool
    extension: str
    modified_at: str
    content: str


class WriteResult(TypedDict):
    """Результат записи файла: что записали, в каком режиме и что получилось.

    ``created`` — файла до записи не было (по нему служба раскладывает путь в
    ``files_created`` или ``files_modified``), ``size_bytes``/``chars``/``lines``
    описывают файл ПОСЛЕ записи.
    """

    path: str
    mode: str
    created: bool
    size_bytes: int
    chars: int
    lines: int
    written_at: str


class PatchResult(TypedDict):
    """Результат точечной замены: заменено вхождений и сколько нашлось всего.

    ``occurrences`` больше единицы — признак неоднозначного якоря: заменено ПЕРВОЕ
    вхождение, и модель видит, что в файле есть ещё такие же фрагменты.
    """

    path: str
    replaced: int
    occurrences: int
    size_bytes: int
    chars: int
    lines: int
    patched_at: str


__all__ = ["FileContent", "PatchResult", "WriteResult"]
