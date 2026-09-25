"""MCP-сервер обработки данных дня 20: четыре инструмента над списками и текстом.

Сервер — отдельный процесс по stdio (JSON-RPC через stdin/stdout), не импортирует
ни ``backend/``, ни другие серверы флота: его поднимает реестр дня
(``backend/services/mcp_registry.py``) и вызывает инструменты по имени.

Инструменты:

- ``summarize(items, style, max_length)`` — сводка списка элементов и ключевые
  пункты: с ключом DeepSeek её собирает модель (``engine="llm"``), без ключа или
  с ``--llm off`` — агрегация по заголовкам (``engine="aggregation"``);
- ``extract_keywords(text, limit)`` — ключевые слова текста по частоте;
- ``filter_by_date(items, field, since, until, limit)`` — отбор записей по дате;
- ``aggregate(items, group_by, metric, value_field, limit)`` — группировка и метрика.

Модули пакета: ``config`` (границы аргументов и DeepSeek), ``schemas``
(``TypedDict`` — из них SDK собирает ``outputSchema``), ``summarize`` и
``llm_client`` (ветка модели), ``keywords``, ``dates``, ``aggregate`` (чистая
логика инструментов) и ``server`` (объявление сервера и запуск по stdio).

Запуск из папки дня::

    uv run python mcp_servers/data_server/server.py --llm off
"""
