"""Константы MCP-сервера дня 19: внешний API, бэкенд дня, границы аргументов.

Модуль без зависимости от SDK: его импортируют и сервер, и HTTP-клиенты, и
инструменты композиции (``search_sources``, ``summarize_logic``, ``file_writer``,
``llm_client``), и тесты.

День 19 добавляет к инструментам дня 18 три инструмента КОМПОЗИЦИИ — ``search``,
``summarize`` и ``save_to_file``. Их источники и каталог вывода живут в папке дня:
локальный файл заметок (``mcp_server/data/notes.md``), таблицы SQLite дня и
каталог ``output/``. Границы этих источников заданы здесь, чтобы и инструмент, и
тест, и отчёт ссылались на одни и те же пути.
"""
import os
import sys
from pathlib import Path

#: Корень дня (day20/mcp_server/config.py → day20/) и корень репозитория: из
#: последнего импортируется общий пакет shared/ (чтение ключа из .env). Приём тот
#: же, что в backend/__init__.py: MCP-сервер запускается ОТДЕЛЬНЫМ процессом, где
#: корень репозитория в sys.path не попадает.
DAY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DAY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.deepseek_utils import read_key_from_env_file  # noqa: E402

#: Публичный mock API: пользователи, посты, комментарии. Читается по HTTP, без
#: ключа и регистрации — поэтому сервер можно прогнать в любой момент.
DEFAULT_API_BASE = "https://jsonplaceholder.typicode.com"

#: Таймаут одного HTTP-запроса к внешнему API (секунды).
DEFAULT_TIMEOUT = 10.0

#: Бэкенд дня (FastAPI): его API ставит фоновые задачи планировщика. Подменяется
#: аргументом ``--backend-url`` у сервера и переменной окружения ``DAY20_BACKEND_URL``.
BACKEND_URL = os.environ.get("DAY20_BACKEND_URL", "http://127.0.0.1:8000")

#: Таймаут запроса к бэкенду дня (секунды): постановка задачи делает первый сбор,
#: поэтому он больше таймаута внешнего API.
BACKEND_TIMEOUT = 30.0

#: Инструменты планировщика собственного сервера: их тела — вызов бэкенда дня.
SCHEDULER_TOOLS = ("schedule_reminder", "collect_data", "generate_summary")

#: Больше этого числа постов за один вызов инструмент не возвращает: ответ
#: должен остаться читаемым и для модели, и для человека.
MAX_POSTS_LIMIT = 20

#: Постов у jsonplaceholder — 100, пользователей — 10: границы подсказываются в
#: текстах ошибок, чтобы «id=999» не выглядел сбоем сервера.
MAX_POST_ID = 100
MAX_USER_ID = 10

#: Имя и версия сервера: уходят клиенту в ответе ``initialize``.
SERVER_NAME = "day20-tools"
SERVER_VERSION = "1.3.0"

#: Инструкция сервера: клиент показывает её модели рядом с каталогом инструментов.
SERVER_INSTRUCTIONS = (
    "Девять инструментов. Чтение данных jsonplaceholder.typicode.com: get_user "
    "(данные пользователя), get_post (пост по id), list_user_posts (посты "
    "пользователя) — параметры это целые идентификаторы. Планирование фоновых "
    "задач через API дня: schedule_reminder (разовое напоминание через N секунд), "
    "collect_data (периодический сбор данных по адресу каждые N секунд), "
    "generate_summary (регулярная сводка по накопленным данным каждые N секунд). "
    "Композиция: search (найти данные в источнике: jsonplaceholder, локальный "
    "файл или таблица SQLite дня), summarize (сводка списка элементов и ключевые "
    "пункты), save_to_file (сохранить текст в файл формата txt/md/json в каталоге "
    "дня output/)."
)

# --- Инструменты композиции (день 19) ----------------------------------------
#: Каталог результатов пайплайна: ``save_to_file`` пишет ТОЛЬКО сюда.
OUTPUT_DIR = DAY_ROOT / "output"
#: Корень локальных источников поиска: ``file:<путь>`` разрешается только внутри дня.
FILE_ROOT = DAY_ROOT
#: База дня для источника ``sqlite:<таблица>`` (открывается только на чтение).
DB_PATH = DAY_ROOT / "agents.db"
#: Файл .env дня — тот же, что читает бэкенд (day20/.env).
ENV_FILE = DAY_ROOT / ".env"

#: Границы аргументов ``search``.
SEARCH_QUERY_MAX = 200
SEARCH_SOURCE_MAX = 200
SEARCH_LIMIT_MIN = 1
SEARCH_LIMIT_MAX = 20
SEARCH_DEFAULT_LIMIT = 5
SEARCH_CONTENT_MAX = 1000
SEARCH_TITLE_MAX = 120
#: Сколько записей jsonplaceholder читать до фильтра (у постов их 100, у
#: пользователей 10): фильтр идёт по прочитанной странице, а не по всей ленте.
SEARCH_API_ROWS = 100

#: Таблицы дня, доступные источнику ``sqlite:<таблица>``: имя → текстовые колонки,
#: по которым ищет запрос. Список закрытый: произвольный SQL не выполняется.
SQLITE_SOURCES = {
    "collected_data": ("name", "source_url", "payload"),
    "periodic_summaries": ("name", "content"),
    "pipeline_steps": ("tool_name", "input_args", "output_result"),
}

#: Границы аргументов ``summarize``.
SUMMARY_STYLES = ("short", "detailed", "bullets")
SUMMARY_STYLE_DEFAULT = "short"
SUMMARY_MAX_LENGTH_MIN = 50
SUMMARY_MAX_LENGTH_MAX = 4000
SUMMARY_DEFAULT_MAX_LENGTH = 600
SUMMARY_ITEMS_MAX = 200
#: Сколько строк (пунктов) даёт агрегация и сколько — ветка LLM.
SUMMARY_LINES_MAX = 5
SUMMARY_KEY_POINTS_MAX = 7

#: Параметры вызова DeepSeek внутри инструмента ``summarize``.
LLM_MODEL = "deepseek-chat"
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 512
LLM_TIMEOUT = 30.0

#: Границы аргументов ``save_to_file``.
FILE_NAME_MAX = 80
FILE_CONTENT_MAX = 20000
SAVE_FORMATS = ("txt", "md", "json")
SAVE_FORMAT_DEFAULT = "md"

#: Инструменты композиции: ими описывается пайплайн дня и его шаги в БД.
PIPELINE_TOOLS = ("search", "summarize", "save_to_file")


def resolve_api_key():
    """Ключ DeepSeek: day20/.env → переменная окружения → None.

    Ищется и в файле дня, и в окружении, потому что ``summarize`` может работать
    и как отдельный процесс MCP-сервера (файл ``.env`` рядом), и внутри прогона с
    уже поднятой переменной.
    """
    return read_key_from_env_file(ENV_FILE) or os.environ.get("DEEPSEEK_API_KEY") or None
