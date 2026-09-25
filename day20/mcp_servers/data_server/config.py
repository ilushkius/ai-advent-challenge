"""Константы MCP-сервера обработки данных (день 20): границы аргументов и DeepSeek.

Модуль без зависимости от MCP SDK: его импортируют и тела инструментов
(``summarize``, ``keywords``, ``dates``, ``aggregate``), и клиент модели
(``llm_client``), и тесты. Поэтому границы значений заданы здесь один раз, а не
разбросаны по проверкам.

Сервер обработки данных ничего не читает из сети: на вход идут списки элементов
(их приносит сервер поиска), на выход — сводка, ключевые слова, отобранные записи
и группы агрегации. Единственный внешний вызов — DeepSeek в инструменте
``summarize``, и он необязателен: без ключа сводку собирает агрегация.
"""
import os
import sys
from pathlib import Path

#: Корень дня (day20/mcp_servers/data_server/config.py → day20/) и корень
#: репозитория: из последнего импортируется общий пакет shared/ (чтение ключа
#: из .env). Приём тот же, что в mcp_server/config.py: сервер запускается
#: ОТДЕЛЬНЫМ процессом, где корень репозитория в sys.path не попадает.
DAY_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DAY_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.deepseek_utils import read_key_from_env_file  # noqa: E402

#: Границы полей элемента: заголовок и тело обрезаются, чтобы ответ инструмента
#: и промпт модели оставались обозримыми.
TITLE_MAX = 120
CONTENT_MAX = 1000

#: Инструмент ``summarize``: виды сводки и границы её длины.
SUMMARY_STYLES = ("short", "detailed", "bullets")
SUMMARY_STYLE_DEFAULT = "short"
SUMMARY_MAX_LENGTH_MIN = 50
SUMMARY_MAX_LENGTH_MAX = 4000
SUMMARY_DEFAULT_MAX_LENGTH = 600
#: Сколько элементов инструмент вообще берёт в сводку.
SUMMARY_ITEMS_MAX = 200
#: Сколько строк даёт агрегация (сводка модели ограничена ``max_length``).
SUMMARY_LINES_MAX = 5
#: Сколько ключевых пунктов (заголовков) инструмент возвращает.
KEY_POINTS_MAX = 7
SUMMARY_KEY_POINTS_MAX = KEY_POINTS_MAX

#: Инструмент ``extract_keywords``: границы числа слов и глубина отбора.
KEYWORDS_MIN = 1
KEYWORDS_MAX = 20
KEYWORDS_DEFAULT = 7
#: Частоты считаются по всем словам, а в кандидаты берутся только первые
#: ``KEYWORDS_TOP_N`` — редкий «шум» в топ не попадает.
KEYWORDS_TOP_N = 30

#: Служебные слова русского и английского: в ключевые слова они не попадают.
#: Множество, а не список: проверка на каждом слове текста должна быть O(1).
STOPWORDS = frozenset({
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то",
    "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за",
    "бы", "по", "ее", "мне", "было", "вот", "от", "меня", "еще", "нет", "о",
    "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли", "если", "уже",
    "или", "ни", "быть", "был", "него", "до", "вас", "нибудь", "опять", "уж",
    "вам", "ведь", "там", "потом", "себя", "ничего", "ей", "может", "они",
    "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем",
    "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже", "себе",
    "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому", "этого",
    "какой", "совсем", "ним", "здесь", "этом", "один", "почти", "мой", "тем",
    "чтобы", "нее", "сейчас", "были", "куда", "зачем", "всех", "никогда",
    "можно", "при", "наконец", "два", "об", "другой", "хоть", "после", "над",
    "больше", "тот", "через", "эти", "нас", "про", "всего", "них", "какая",
    "много", "разве", "три", "эту", "моя", "впрочем", "хорошо", "свою",
    "этой", "перед", "иногда", "лучше", "чуть", "том", "нельзя", "такой",
    "им", "более", "всегда", "конечно", "всю", "между", "the", "a", "an",
    "and", "or", "but", "if", "of", "to", "in", "on", "at", "by", "for",
    "with", "from", "as", "is", "are", "was", "were", "be", "been", "it",
    "its", "this", "that", "these", "those", "not", "no", "do", "does",
    "did", "so", "than", "then", "there", "their", "them", "they", "we",
    "you", "your", "he", "she", "his", "her", "i", "me", "my", "will",
    "would", "can", "could", "should", "about", "into", "over", "after",
})

#: Форматы даты, которые понимает инструмент ``filter_by_date``: ISO-8601
#: разбирается ``datetime.fromisoformat``, остальные — этими шаблонами.
DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M:%S")
FILTER_DEFAULT_FIELD = "created_at"
#: Предел числа записей в ответах ``filter_by_date`` и ``aggregate``.
ITEMS_MAX = 200
FILTER_LIMIT_DEFAULT = 20
AGGREGATE_METRICS = ("count", "sum", "avg", "min", "max")
AGGREGATE_LIMIT_DEFAULT = 20

#: Параметры вызова DeepSeek внутри инструмента ``summarize``.
LLM_MODEL = "deepseek-chat"
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 512
LLM_TIMEOUT = 30.0

#: Файл .env дня — тот же, что читает бэкенд (day20/.env).
ENV_FILE = DAY_ROOT / ".env"

#: Имя и версия сервера: уходят клиенту в ответе ``initialize``.
SERVER_NAME = "day20-data"
SERVER_VERSION = "1.0.0"

#: Инструкция сервера: клиент показывает её модели рядом с каталогом инструментов.
SERVER_INSTRUCTIONS = (
    "Четыре инструмента обработки данных. summarize(items, style, max_length) — "
    "сводка списка элементов (у каждого элемента поля title и content): style это "
    "short, detailed или bullets, max_length — предел длины текста; без ключа "
    "DeepSeek сводку собирает агрегация по заголовкам. extract_keywords(text, "
    "limit) — ключевые слова текста по частоте. filter_by_date(items, field, "
    "since, until, limit) — отбор записей по дате: field это имя поля с датой, "
    "since и until — границы (ISO-8601 или ДД.ММ.ГГГГ), записи без разобранной "
    "даты возвращаются в счётчике skipped. aggregate(items, group_by, metric, "
    "value_field, limit) — группировка записей: metric это count, sum, avg, min "
    "или max, для всех метрик кроме count обязателен value_field с числом. "
    "Примеры: summarize(items=[{\"title\": \"RAG\"}], style=\"bullets\") — сводка; "
    "extract_keywords(text=\"RAG и поиск\", limit=5); "
    "filter_by_date(items=[...], since=\"2026-01-01\"); "
    "aggregate(items=[...], group_by=\"status\", metric=\"sum\", "
    "value_field=\"amount\")."
)


def resolve_api_key():
    """Ключ DeepSeek: day20/.env → переменная окружения → None.

    Ищется и в файле дня, и в окружении, потому что ``summarize`` может работать
    и как отдельный процесс MCP-сервера (файл ``.env`` рядом), и внутри прогона с
    уже поднятой переменной.
    """
    return read_key_from_env_file(ENV_FILE) or os.environ.get("DEEPSEEK_API_KEY") or None
