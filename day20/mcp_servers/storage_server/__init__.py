"""MCP-сервер ``storage_server`` (день 20): сохранение и выдача результата.

Четыре инструмента: ``save_to_file`` (файл в каталог ``output/``), ``save_to_db``
(строка в базу ``storage.db``), ``list_saved`` (список сохранённого) и
``load_from_file`` (чтение сохранённого файла). Сервер независим от остальных двух
серверов флота и от кода ``backend/``: он говорит по stdio (JSON-RPC через
stdin/stdout), а маршрутизирует вызовы к нему клиент-оркестратор дня.

Модули пакета:

- ``config`` — константы: каталоги ``output/`` и ``storage.db``, границы
  аргументов, имя, версия и инструкция сервера;
- ``schemas`` — ``TypedDict``-структуры ответов (``outputSchema`` инструментов);
- ``files`` — запись и чтение файлов каталога вывода;
- ``db`` — строки базы ``storage.db`` на ``sqlite3``;
- ``server`` — ``MCPServer`` с четырьмя инструментами и точкой входа.

Запуск из папки дня::

    uv run python mcp_servers/storage_server/server.py --output-dir output --db-path storage.db
"""
