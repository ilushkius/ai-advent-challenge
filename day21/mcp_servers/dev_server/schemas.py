"""Структуры ответов инструментов сервера разработки (``TypedDict``).

Из аннотаций возврата SDK собирает ``outputSchema`` инструмента, а
``structuredContent`` ответа становится самим словарём — поэтому ответы описаны
типами, а не склеенными строками. Все поля обязательны: инструмент заполняет их
всегда (пустые значения — пустая строка, пустой список или ``False``).

Три инструмента из шести описаны типами здесь — ``get_git_branch``, ``list_files``
и ``get_changed_files``; три остальных отдают готовые значения: ``get_git_diff`` и
``get_pr_diff`` возвращают текст diff (``str``), а ``get_project_structure`` —
вложенное дерево произвольной формы. Рекурсивный ``TypedDict`` для дерева дал бы
``outputSchema`` с перекрёстной ссылкой, и SDK собирал бы её на каждом вызове; форма
дерева описана в докстринге инструмента, а ``dict`` остаётся честной аннотацией.
"""
from typing import List, TypedDict


class GitBranchInfo(TypedDict):
    """Состояние репозитория: ветка, последний коммит, изменения и корень.

    ``modified_files`` — пути от корня репозитория (у переименования — НОВЫЙ путь);
    ``clean`` равен ``not modified_files``, то есть «рабочее дерево чисто».
    """

    branch: str
    last_commit: str
    modified_files: List[str]
    clean: bool
    repo_root: str


class FileList(TypedDict):
    """Файлы одного каталога: каталог, фильтр, число, признак обрезки и имена.

    ``directory`` — путь от корня репозитория, каким его передали; ``count`` — длина
    ``files`` (после фильтра и обрезки), ``truncated`` — признак того, что файлов
    было больше лимита.
    """

    directory: str
    extension: str
    count: int
    truncated: bool
    files: List[str]


class ChangedFiles(TypedDict):
    """Ответ ``get_changed_files``: ref-ы, число имён и сами имена.

    ``base``/``head`` — проверенные ref-ы запроса, ``count`` — длина ``files``,
    ``truncated`` — файлов было больше ``config.MAX_CHANGED_FILES``.
    """

    base: str
    head: str
    count: int
    truncated: bool
    files: List[str]
