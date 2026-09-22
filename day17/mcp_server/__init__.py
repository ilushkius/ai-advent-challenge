"""Собственный MCP-сервер дня 17: инструменты поверх jsonplaceholder.typicode.com.

Пакет из четырёх модулей, каждый со своей работой:

- ``config`` — константы сервера: адрес внешнего API, таймаут, имя и версия,
  инструкция для клиента, границы аргументов;
- ``schemas`` — ``TypedDict``-структуры ответов; из них MCP SDK собирает
  ``outputSchema`` инструмента (``structuredContent`` ответа — сам словарь);
- ``api_client`` — HTTP-часть: ``JsonPlaceholderClient`` с понятными ошибками
  (``ExternalAPIError``) вместо «сырых» ответов ``httpx``;
- ``server`` — ``MCPServer`` с тремя инструментами и точкой входа.

Запуск (транспорт stdio: JSON-RPC по stdin/stdout, сервер поднимает клиент):

    uv run python mcp_server/server.py
    uv run python mcp_server/server.py --api-base https://jsonplaceholder.typicode.com

Транспорт stdio — это не HTTP: процесс ждёт сообщения протокола MCP на stdin,
поэтому руками его запускают только для отладки (после запуска он выглядит
«зависшим» — на самом деле ждёт ``initialize``). В приложении дня его запускает
``backend/services/mcp_client.py`` как дочерний процесс по цели
``uv run python mcp_server/server.py`` (см. ``config.MCP_DEFAULT_TARGET``).
"""
