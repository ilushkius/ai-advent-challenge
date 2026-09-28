"""Три инструмента КОМПОЗИЦИИ собственного MCP-сервера дня 19.

Инструменты собраны здесь, а регистрируются в ``server.py`` (``register_pipeline_tools``):
сервер держит имя, версию и инструкцию, а тела инструментов читаются рядом со
своей логикой.

Контракт тот же, что у инструментов дня 17/18 (AGENTS.md):

- параметры типизированы (из аннотаций SDK собирает ``inputSchema``), а докстринг
  описывает параметры и пример вызова — его читает модель;
- возврат — ``TypedDict`` из ``mcp_server/schemas.py`` (из него собирается
  ``outputSchema``), поэтому ``structuredContent`` ответа равен самому словарю, а
  не склеенной руками строке;
- ошибка инструмента — данные: ``ToolError`` с понятным текстом («стиль не
  поддержан», «файла нет»), а не исключение наружу.

Композиция — это последовательность вызовов, где выход одного инструмента служит
входом другого, поэтому форма ответов важна: пайплайн обращается к их полям
(``items``, ``summary_text``, ``filename``) через маппинг ``$steps.<i>.structured.*``.
"""
from __future__ import annotations

from typing import Any, Dict, List

from mcp.server.mcpserver.exceptions import ToolError

# Импорт ``config`` идёт первым: он добавляет корень репозитория в sys.path, без
# чего пакет ``shared/`` (общий для дней) не виден из процесса MCP-сервера.
from mcp_server import config, file_writer, llm_client, search_sources, summarize_logic
from mcp_server.schemas import SavedFile, SearchResult, SummaryResult
from shared.logging_utils import get_logger

logger = get_logger(__name__)


def search(query: str, source: str = "posts",
           limit: int = config.SEARCH_DEFAULT_LIMIT) -> SearchResult:
    """Ищет данные в источнике и возвращает найденные элементы.

    Параметры: query — что искать (подстрока без учёта регистра, до 200 символов;
    пустая строка — все записи источника); source — откуда искать: ``posts`` или
    ``users`` (лента jsonplaceholder), ``file:<путь>`` (файл ВНУТРИ папки дня,
    например ``file:mcp_server/data/notes.md``) или ``sqlite:<таблица>`` (таблица
    дня: ``collected_data``, ``periodic_summaries``, ``pipeline_steps``); limit —
    сколько элементов вернуть (1..20, по умолчанию 5).

    Возвращает объект с полями query, source, source_kind, count и items — массивом
    найденного (id, title, content, url, metadata). Пример: search(query="RAG",
    source="file:mcp_server/data/notes.md", limit=3).

    Если источник не поддержан, файла нет, таблица недоступна или внешний API не
    ответил, инструмент сообщает об ошибке с причиной.
    """
    try:
        kind, items = search_sources.search_items(query, source, limit)
    except search_sources.SearchSourceError as exc:
        raise ToolError(str(exc)) from exc
    return SearchResult(
        query=query,
        source=source,
        source_kind=kind,
        count=len(items),
        items=items,
    )


def summarize(items: List[Dict[str, Any]], style: str = config.SUMMARY_STYLE_DEFAULT,
              max_length: int = config.SUMMARY_DEFAULT_MAX_LENGTH) -> SummaryResult:
    """Собирает сводку по списку элементов и выделяет ключевые пункты.

    Параметры: items — список элементов (обычно результат инструмента search:
    каждый элемент это словарь с полями title и content); style — вид сводки:
    ``short`` (одна строка, по умолчанию), ``detailed`` (нумерованный список),
    ``bullets`` (список пунктов); max_length — предел длины текста сводки
    (50..4000 символов, по умолчанию 600).

    Возвращает объект с полями summary_text, key_points, total_items, style_used и
    engine: ``llm`` — сводку собрала модель DeepSeek, ``aggregation`` — сводка
    собрана из заголовков элементов (так работает прогон без ключа и без сети).
    Пример: summarize(items=[{"title": "RAG"}, {"title": "Чанкинг"}],
    style="bullets", max_length=400).

    Пустой список — ошибка: сводить нечего.
    """
    try:
        payload = summarize_logic.items_payload(items)
        style_used = summarize_logic.normalize_style(style)
    except summarize_logic.SummarizeError as exc:
        raise ToolError(str(exc)) from exc
    if not payload:
        raise ToolError("Список элементов пуст — сводить нечего")
    if llm_client.available():
        try:
            prompt = summarize_logic.build_prompt(payload, style_used, max_length)
            text = llm_client.summarize(prompt)
            return summarize_logic.llm_summary(text, payload, style_used, max_length)
        except Exception as exc:  # noqa: BLE001 — сбой LLM не делает шаг неуспешным
            logger.warning("summarize: LLM недоступна, перехожу к агрегации: %s", exc)
    return summarize_logic.aggregate_summary(payload, style_used, max_length)


def save_to_file(content: str, filename: str = "pipeline_result.md",
                 format: str = config.SAVE_FORMAT_DEFAULT) -> SavedFile:
    """Сохраняет текст в файл каталога дня ``output/``.

    Параметры: content — текст для записи (до 20000 символов, обычно
    ``summary_text`` предыдущего шага); filename — имя файла без пути (по
    умолчанию ``pipeline_result.md``; расширение заменяется на запрошенный формат);
    format — ``md`` (по умолчанию), ``txt`` или ``json``.

    Возвращает объект с полями filename, filepath (абсолютный путь — по нему файл
    открывают), size_bytes, format и saved_at. Пример:
    save_to_file(content="# Сводка\\nRAG — это …", filename="rag-summary.md").

    Если имя содержит путь или «..», формат не поддержан или текст длиннее
    предела — инструмент сообщает об ошибке.
    """
    try:
        return file_writer.save(content, filename, format)
    except file_writer.SaveFileError as exc:
        raise ToolError(str(exc)) from exc


def register_pipeline_tools(server) -> None:
    """Регистрирует три инструмента композиции на сервере дня."""
    server.tool()(search)
    server.tool()(summarize)
    server.tool()(save_to_file)
