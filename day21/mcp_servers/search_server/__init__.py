"""MCP-сервер поиска данных (день 20): ``search_web``, ``search_local``, ``fetch_url``.

Отдельный процесс по stdio: флот дня поднимает его командой из ``mcp_servers.json``
(``uv run python mcp_servers/search_server/server.py``), а вызовы маршрутизирует
клиент-оркестратор по имени инструмента. Пакет НЕ импортирует ни ``backend/``, ни
``mcp_server/``, ни соседние серверы флота: связывает их только протокол MCP.

Слои пакета:

- ``config.py`` — константы, бутстрап путей (``shared/`` из корня репозитория) и
  границы аргументов;
- ``schemas.py`` — структуры ответов инструментов (``TypedDict`` → ``outputSchema``);
- ``web.py`` — лента jsonplaceholder и Википедия (``search_web``);
- ``local.py`` — поиск по блокам файла внутри папки дня (``search_local``);
- ``fetch.py`` — страница по HTTP → текст (``fetch_url``);
- ``server.py`` — сборка ``MCPServer``, разбор аргументов и точка входа.
"""
