"""Собственный MCP-сервер дня 18: чтение jsonplaceholder и планировщик задач.

Пакет из пяти модулей, каждый со своей работой:

- ``config`` — константы сервера: адрес внешнего API и бэкенда дня, таймауты, имя
  и версия, инструкция для клиента, границы аргументов;
- ``schemas`` — ``TypedDict``-структуры ответов; из них MCP SDK собирает
  ``outputSchema`` инструмента (``structuredContent`` ответа — сам словарь);
- ``api_client`` — HTTP-часть чтения: ``JsonPlaceholderClient`` с понятными
  ошибками (``ExternalAPIError``) вместо «сырых» ответов ``httpx``;
- ``backend_api`` — HTTP-часть планировщика: ``ScheduleBackendClient`` ставит
  задачи через ``POST /scheduler/tasks`` бэкенда дня (единственный писатель в БД);
- ``server`` — ``MCPServer`` с шестью инструментами и точкой входа.

Инструменты делятся на две группы: чтение данных (``get_user``, ``get_post``,
``list_user_posts``) и планирование фоновой работы (``schedule_reminder``,
``collect_data``, ``generate_summary``). Вторая группа требует запущенного бэкенда
дня: фон обслуживает его планировщик, а не MCP-сервер.

Запуск (транспорт stdio: JSON-RPC по stdin/stdout, сервер поднимает клиент):

    uv run python mcp_server/server.py
    uv run python mcp_server/server.py --api-base https://jsonplaceholder.typicode.com

Транспорт stdio — это не HTTP: процесс ждёт сообщения протокола MCP на stdin,
поэтому руками его запускают только для отладки (после запуска он выглядит
«зависшим» — на самом деле ждёт ``initialize``). В приложении дня его запускает
``backend/services/mcp_client.py`` как дочерний процесс по цели
``uv run python mcp_server/server.py`` (см. ``config.MCP_DEFAULT_TARGET``).
"""
