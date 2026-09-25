"""Константы MCP-сервера поиска (день 20): внешние API, границы аргументов, пути.

Модуль без зависимости от SDK: его импортируют и ``server.py``, и тела
инструментов (``web.py``, ``local.py``, ``fetch.py``), и тесты.

Сервер — ОТДЕЛЬНЫЙ процесс флота дня (``mcp_servers/search_server/server.py``),
поэтому корни путей вычисляются от файла: ``DAY_ROOT`` = папка дня (``day20/``),
``REPO_ROOT`` = корень репозитория — из него импортируется общий пакет ``shared/``.
Приём тот же, что в ``mcp_server/config.py`` и ``backend/__init__.py``, только на
уровень выше (``parents[2]`` вместо ``parents[1]``).
"""
import sys
from pathlib import Path

#: Корень дня (day20/mcp_servers/search_server/config.py → day20/) и корень
#: репозитория: последний кладётся в sys.path ради общего пакета shared/
#: (логирование). MCP-сервер запускается отдельным процессом, где ни корень дня,
#: ни корень репозитория в sys.path не попадают.
DAY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DAY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Публичный mock API (jsonplaceholder): лента постов и пользователей читается по
#: HTTP без ключа, поэтому сервер прогоняется в любой момент. Подменяется
#: аргументом ``--api-base`` — тесты ставят вместо него локальный стенд.
DEFAULT_API_BASE = "https://jsonplaceholder.typicode.com"

#: API Википедии (opensearch): поиск статей по названию без ключа и регистрации.
WIKI_API_BASE = "https://ru.wikipedia.org/w/api.php"

#: Таймаут одного HTTP-запроса (секунды): и к ленте, и к Википедии, и к странице
#: инструмента ``fetch_url``.
DEFAULT_TIMEOUT = 10.0

#: Больше этого числа элементов инструмент поиска не возвращает: ответ должен
#: остаться читаемым и для модели, и для человека.
MAX_ITEMS = 20

#: Сколько записей ленты читать до фильтра (у jsonplaceholder 100 постов и 10
#: пользователей): фильтр идёт по прочитанной странице, а не по всей ленте.
MAX_PAGE_ROWS = 100

#: Пределы текста элемента и его заголовка: длинное поле обрезается, а не рвёт
#: ответ.
CONTENT_MAX = 1000
TITLE_MAX = 120

#: Границы аргумента ``max_chars`` инструмента ``fetch_url``: 200 символов —
#: минимум, при котором текст ещё о чём-то говорит, 20000 — предел читаемости.
FETCH_MAX_CHARS_MIN = 200
FETCH_MAX_CHARS_MAX = 20000
FETCH_MAX_CHARS_DEFAULT = 4000

#: Корень файлов инструмента ``search_local``: читать разрешено только файлы
#: ВНУТРИ папки дня (подменяется аргументом ``--file-root``).
FILE_ROOT = DAY_ROOT

#: Имя и версия сервера: уходят клиенту в ответе ``initialize``.
SERVER_NAME = "day20-search"
SERVER_VERSION = "1.0.0"

#: Инструкция сервера: клиент показывает её модели рядом с каталогом инструментов.
SERVER_INSTRUCTIONS = (
    "Три инструмента поиска данных. search_web поиск в ленте внешнего API "
    "(source=posts или users, фильтр — подстрока запроса) или в Википедии "
    "(source=wikipedia, поиск статей по названию); пример: "
    "search_web(query=\"RAG\", source=\"posts\", limit=5). search_local поиск по "
    "блокам файла ВНУТРИ папки дня (блоки разделяются пустыми строками); пример: "
    "search_local(query=\"RAG\", path=\"mcp_server/data/notes.md\", limit=3). "
    "fetch_url читает страницу http:// или https:// и возвращает её текст без "
    "тегов, обрезанный до max_chars; пример: fetch_url(url=\"https://example.com\", "
    "max_chars=2000)."
)
