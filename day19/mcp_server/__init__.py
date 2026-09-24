"""Собственный MCP-сервер дня 19: данные, план и композиция инструментов.

Пакет из десяти модулей, каждый со своей работой:

- ``config`` — константы сервера: адрес внешнего API и бэкенда дня, таймауты, имя
  и версия, инструкция для клиента, границы аргументов, каталоги источников и
  вывода инструментов композиции;
- ``schemas`` — ``TypedDict``-структуры ответов; из них MCP SDK собирает
  ``outputSchema`` инструмента (``structuredContent`` ответа — сам словарь);
- ``api_client`` — HTTP-часть чтения: ``JsonPlaceholderClient`` с понятными
  ошибками (``ExternalAPIError``) вместо «сырых» ответов ``httpx``;
- ``backend_api`` — HTTP-часть планировщика: ``ScheduleBackendClient`` ставит
  задачи через ``POST /scheduler/tasks`` бэкенда дня (единственный писатель в БД);
- ``search_sources`` — источники инструмента ``search``: лента внешнего API, файл
  внутри папки дня и таблицы SQLite дня (только чтение);
- ``summarize_logic`` — чистая логика ``summarize``: стиль, промпт, разбор
  ключевых пунктов и агрегация (движок без LLM);
- ``llm_client`` — необязательный вызов DeepSeek внутри ``summarize``: без ключа
  инструмент переходит на агрегацию;
- ``file_writer`` — запись результата ``save_to_file`` в каталог ``output/``;
- ``pipeline_tools`` — три инструмента композиции и их регистрация на сервере;
- ``server`` — ``MCPServer`` с девятью инструментами и точкой входа.

Инструменты делятся на три группы: чтение данных (``get_user``, ``get_post``,
``list_user_posts``), планирование фоновой работы (``schedule_reminder``,
``collect_data``, ``generate_summary``) и композиция (``search``, ``summarize``,
``save_to_file``). Вторая группа требует запущенного бэкенда дня: фон обслуживает
его планировщик, а не MCP-сервер. Третья работает автономно и вызывается по
очереди декларативным пайплайном дня (``backend/services/pipeline.py``).

Запуск (транспорт stdio: JSON-RPC по stdin/stdout, сервер поднимает клиент):

    uv run python mcp_server/server.py
    uv run python mcp_server/server.py --api-base https://jsonplaceholder.typicode.com
    uv run python mcp_server/server.py --llm off --output-dir output

Транспорт stdio — это не HTTP: процесс ждёт сообщения протокола MCP на stdin,
поэтому руками его запускают только для отладки (после запуска он выглядит
«зависшим» — на самом деле ждёт ``initialize``). В приложении дня его запускает
``backend/services/mcp_client.py`` как дочерний процесс по цели
``uv run python mcp_server/server.py`` (см. ``config.MCP_DEFAULT_TARGET``).
"""
