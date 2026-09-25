"""Флот MCP-серверов дня 20: три независимых процесса по stdio.

Каждый сервер — отдельный пакет со своим ``config.py``, ``schemas.py``, телами
инструментов и точкой входа ``server.py``:

- ``search_server/`` — поиск данных: ``search_web`` (лента jsonplaceholder или
  Википедия), ``search_local`` (файл внутри папки дня), ``fetch_url`` (страница по
  HTTP → текст);
- ``data_server/`` — обработка данных: ``summarize`` (сводка списка элементов),
  ``extract_keywords``, ``filter_by_date``, ``aggregate``;
- ``storage_server/`` — сохранение и выдача: ``save_to_file`` (каталог ``output/``),
  ``save_to_db`` (файл ``storage.db``), ``list_saved``, ``load_from_file``.

Серверы НЕ импортируют друг друга и код ``backend/``: связывает их не общий модуль,
а клиент-оркестратор (``backend/services/mcp_registry.py``), который поднимает
каждый процесс отдельно и маршрутизирует вызов по имени инструмента.

Запуск (из папки дня; транспорт — stdio, JSON-RPC через stdin/stdout)::

    uv run python mcp_servers/search_server/server.py
    uv run python mcp_servers/data_server/server.py --llm off
    uv run python mcp_servers/storage_server/server.py --output-dir output

Конфигурация флота лежит данными в ``day20/mcp_servers.json`` (имя сервера,
команда запуска, описание, кэш ``tools/list``) — реестр дня читает этот файл,
поэтому новый сервер добавляется правкой JSON, без изменения кода.
"""
