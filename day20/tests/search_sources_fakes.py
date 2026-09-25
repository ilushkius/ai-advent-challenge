"""Данные и помощники тестов источников ``search`` (день 19).

Вынесено из ``tests/unit/test_search_sources*.py``: тесты разложены по видам
источника (файл дня, таблица SQLite, лента внешнего API), а материал у них общий —
те же заметки, те же строки таблиц и та же заглушка клиента jsonplaceholder.
Копировать их в три файла значило бы править одно место трижды.

Здесь же настройка процесса источников (``search_sources.configure`` держит корень
файлов и путь базы в модуле): помощник ставит их через ``monkeypatch``, поэтому
после теста значения возвращаются сами.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from mcp_server import api_client, config, search_sources

#: Блоки файла-источника: первый — самая первая строка блока (заголовок).
NOTES = (
    "RAG: что такое\nПоиск по документам и гибридный ранжировщик.",
    "FSM: состояния агента\nГраф переходов и обработчики событий.",
    "Планировщик задач\nФоновые запуски по расписанию.",
)

#: Строки таблицы шагов пайплайна (как их пишет ``Pipeline``).
STEP_ROWS = (
    (1, "search", '{"query": "RAG"}', "Найдено 3 элемента"),
    (2, "summarize", '{"style": "short"}', "Сводка про RAG"),
    (3, "save_to_file", '{"filename": "итог.md"}', "Файл сохранён"),
)

#: Строки таблицы собранных данных: у неё есть колонка ``source_url``.
DATA_ROWS = (
    (1, "Заметки про RAG", "https://example.test/rag", "chunking и эмбеддинги"),
    (2, "Заметки про FSM", "https://example.test/fsm", "состояния и события"),
)

#: Записи лент jsonplaceholder: первого поста тело длиннее лимита содержимого.
POSTS = (
    {"id": 1, "userId": 7, "title": "RAG и документы", "body": "A" * 1200},
    {"id": 2, "userId": 8, "title": "Flask и роуты", "body": "Про сервер и роуты"},
)

USERS = (
    {"id": 1, "name": "Leanne Graham", "username": "Bret", "email": "bret@test.io",
     "address": {"city": "Gwenborough"}, "company": {"name": "Romaguera"}},
    {"id": 2, "name": "Ervin Howell", "username": "Antonette", "email": "anton@test.io",
     "address": {"city": "Wisokyburgh"}, "company": {"name": "Deckow"}},
)

#: Адрес заглушки — с хвостовым слэшем: в ``url`` он должен остаться один.
API_BASE = "https://jsonplaceholder.test/api/"


class FakeClient:
    """Офлайн-заглушка клиента jsonplaceholder: страницы постов и пользователей."""

    def __init__(self, posts=POSTS, users=USERS, error=None) -> None:
        self.base_url = API_BASE
        self.calls: list[tuple[str, int]] = []
        self._posts = list(posts)
        self._users = list(users)
        self._error = error

    def _page(self, name: str, rows: list, limit: int) -> list:
        """Записывает вызов, отдаёт не больше ``limit`` записей или ошибку среды."""
        self.calls.append((name, limit))
        if self._error is not None:
            raise self._error
        return rows[:limit]

    def list_posts(self, limit: int = config.SEARCH_API_ROWS) -> list:
        """Страница постов: сырые словари, как у настоящего клиента."""
        return self._page("posts", self._posts, limit)

    def list_users(self, limit: int = config.SEARCH_API_ROWS) -> list:
        """Страница пользователей: сырые словари, как у настоящего клиента."""
        return self._page("users", self._users, limit)


def configure_sources(tmp_path, monkeypatch) -> Path:
    """Ставит корень файлов и путь базы источников; возвращает корень дня."""
    root = tmp_path / "day"
    root.mkdir()
    monkeypatch.setattr(search_sources, "_file_root", root)
    monkeypatch.setattr(search_sources, "_db_path", tmp_path / "day.db")
    return root


def make_sqlite_db(root: Path) -> Path:
    """Создаёт базу дня с двумя таблицами поиска: шаги пайплайна и собранные данные."""
    path = root.parent / "day.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE pipeline_steps (id INTEGER PRIMARY KEY, tool_name TEXT, "
            "input_args TEXT, output_result TEXT)"
        )
        connection.executemany(
            "INSERT INTO pipeline_steps VALUES (?, ?, ?, ?)", STEP_ROWS
        )
        connection.execute(
            "CREATE TABLE collected_data (id INTEGER PRIMARY KEY, name TEXT, "
            "source_url TEXT, payload TEXT)"
        )
        connection.executemany(
            "INSERT INTO collected_data VALUES (?, ?, ?, ?)", DATA_ROWS
        )
    return path


def install_fake_api(monkeypatch) -> Callable[..., FakeClient]:
    """Возвращает установщик заглушки клиента jsonplaceholder вместо клиента модуля."""
    def install(**kwargs) -> FakeClient:
        client = FakeClient(**kwargs)
        monkeypatch.setattr(api_client, "_client", client)
        return client
    return install


def write_notes(root: Path, blocks, name: str = "notes.md") -> str:
    """Пишет файл-источник из блоков через пустую строку; отдаёт строку ``file:``."""
    (root / name).write_text("\n\n".join(blocks), encoding="utf-8")
    return f"file:{name}"
