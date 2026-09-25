"""Константы MCP-сервера ``storage_server`` (день 20): каталоги, границы, тексты.

Сервер сохранения и выдачи — третий из трёх независимых серверов флота дня 20.
Он пишет результат оркестрации ДВУМЯ способами: файлом в ``day20/output/``
(инструмент ``save_to_file``) и строкой в СВОЮ базу ``day20/storage.db``
(инструмент ``save_to_db``). Отдельный файл базы — не прихоть: ``agents.db``
пишет ровно один процесс (бэкенд дня), а ``storage_server`` запускается отдельным
процессом по stdio, поэтому общий файл сделал бы двух писателей.

Каталог вывода и файл базы настраиваются аргументами ``--output-dir`` и
``--db-path``; тесты передают сюда временные пути, поэтому в репозиторий ничего
лишнего не попадает.
"""
import sys
from pathlib import Path

#: Корень дня (day20/mcp_servers/storage_server/config.py → day20/) и корень
#: репозитория: из последнего импортируется общий пакет shared/ (логгер). Приём
#: тот же, что в mcp_server/config.py дня 19: сервер запускается ОТДЕЛЬНЫМ
#: процессом, где корень репозитория в sys.path не попадает.
DAY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DAY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Каталог файлов результатов: ``save_to_file`` пишет ТОЛЬКО сюда.
OUTPUT_DIR = DAY_ROOT / "output"

#: Файл базы сохранённых строк: отдельный от ``agents.db`` (единственный писатель
#: в базу дня — процесс бэкенда; этот сервер работает своим процессом).
DB_PATH = DAY_ROOT / "storage.db"

#: Таблица сохранённых строк в ``storage.db``.
DB_TABLE = "saved_records"

#: Форматы файлов ``save_to_file`` и формат по умолчанию.
SAVE_FORMATS = ("txt", "md", "json")
SAVE_FORMAT_DEFAULT = "md"

#: Границы аргументов ``save_to_file``.
FILE_NAME_MAX = 80
FILE_CONTENT_MAX = 20000

#: Границы аргумента ``limit`` у ``list_saved`` и ``list_rows``.
LIST_LIMIT_MIN = 1
LIST_LIMIT_MAX = 50
LIST_LIMIT_DEFAULT = 10

#: Границы строк записи в ``storage.db``.
TITLE_MAX = 200
KIND_MAX = 64
SOURCE_MAX = 200

#: Виды выборки инструмента ``list_saved``: файлы, строки базы или и то и другое.
LIST_KINDS = ("all", "file", "row")

#: Имя и версия сервера: уходят клиенту в ответе ``initialize``.
SERVER_NAME = "day20-storage"
SERVER_VERSION = "1.0.0"

#: Инструкция сервера: клиент показывает её модели рядом с каталогом инструментов.
SERVER_INSTRUCTIONS = (
    "Сервер сохранения и выдачи данных дня 20. Четыре инструмента: "
    "save_to_file (запись текста файлом в каталог output/; параметры content — текст "
    "до 20000 символов, filename — имя без пути, format — md/txt/json; пример: "
    "save_to_file(content=\"Сводка:\\nRAG — это …\", filename=\"rag-summary.md\")), "
    "save_to_db (запись строки в базу storage.db; параметры kind — вид записи, title — "
    "заголовок, content — текст, source — источник, metadata — объект; пример: "
    "save_to_db(kind=\"orchestration\", title=\"Сводка\", content=\"…\", "
    "source=\"search_web\")), "
    "list_saved (список сохранённого; параметры kind — all/file/row, limit — сколько "
    "записей (1..50, по умолчанию 10); пример: list_saved(kind=\"row\", limit=5)), "
    "load_from_file (чтение сохранённого файла по имени; параметр filename — имя без "
    "пути; пример: load_from_file(filename=\"rag-summary.md\")). "
    "Инструменты возвращают структурированные данные, а ошибки — понятным текстом "
    "с причиной (чужой формат, опасное имя, слишком длинный текст)."
)
