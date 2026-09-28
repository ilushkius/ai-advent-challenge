"""Собственный MCP-сервер дня 19: девять инструментов — данные, план, композиция.

Первые три инструмента читают jsonplaceholder (``get_user``, ``get_post``,
``list_user_posts``) и работают как в дне 17. Вторые три — ПЛАНИРОВЩИК дня 18:
``schedule_reminder`` (разовое напоминание), ``collect_data`` (периодический сбор
данных) и ``generate_summary`` (регулярная сводка). Их тела — один вызов
``POST /scheduler/tasks`` бэкенда дня (``mcp_server/backend_api.py``): фон живёт в
процессе бэкенда, и единственный писатель в SQLite — тоже он.

Третьи три — КОМПОЗИЦИЯ дня 19 (``mcp_server/pipeline_tools.py``): ``search``
ищет данные в источнике (лента внешнего API, файл внутри папки дня или таблица базы
дня — только на чтение), ``summarize`` сводит список элементов моделью DeepSeek, а
без ключа или с ``--llm off`` — агрегацией, ``save_to_file`` пишет текст в файл
каталога ``output/``. Эти три инструмента вызываются по очереди одним пайплайном
(``backend/services/pipeline.py``), и выход одного становится входом следующего.

Сервер собран на ``mcp.server.mcpserver.MCPServer`` (mcp 2.x) и общается с
клиентом по stdio: JSON-RPC идёт через stdin/stdout, ошибки и логи — в stderr.
Из чего SDK собирает контракт инструмента:

- **имя** — имя функции;
- **описание** — её докстринг (его читает модель, поэтому там и параметры, и
  пример вызова);
- **inputSchema** — типизированные параметры (``user_id: int`` → ``integer``);
- **outputSchema** — аннотация возврата ``TypedDict`` (``mcp_server/schemas.py``),
  а ``structuredContent`` ответа становится самим словарём.

Запуск руками (сервер ждёт JSON-RPC на stdin — это транспорт протокола, а не
зависание; ``--api-base`` подменяет внешний API, ``--backend-url`` — бэкенд дня,
``--llm off`` выключает DeepSeek внутри ``summarize``, ``--output-dir`` задаёт
каталог файлов ``save_to_file``, ``--file-root`` и ``--db-path`` — корень
источников ``file:`` и базу источника ``sqlite:``):

    uv run python mcp_server/server.py
    uv run python mcp_server/server.py --api-base http://127.0.0.1:8080 --timeout 5
    uv run python mcp_server/server.py --backend-url http://127.0.0.1:8000
    uv run python mcp_server/server.py --llm off --output-dir output
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Пакетный контекст: при запуске файлом (``python mcp_server/server.py``) корень
# дня в sys.path не попадает, поэтому импорты ниже — абсолютные от корня дня.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from mcp_server import backend_api, file_writer, llm_client, search_sources  # noqa: E402
from mcp_server.api_client import ExternalAPIError, configure, get_client  # noqa: E402
from mcp_server.config import (  # noqa: E402
    BACKEND_URL,
    DB_PATH,
    DEFAULT_API_BASE,
    DEFAULT_TIMEOUT,
    FILE_ROOT,
    OUTPUT_DIR,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    SERVER_VERSION,
)
from mcp_server.pipeline_tools import register_pipeline_tools  # noqa: E402
from mcp_server.schemas import (  # noqa: E402
    CollectionStarted,
    PostInfo,
    ReminderScheduled,
    SummaryReady,
    UserInfo,
    UserPosts,
)

server = MCPServer(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=SERVER_INSTRUCTIONS,
)


def _run(call, *args):
    """Вызов внешнего сервиса с переводом его ошибки в ошибку инструмента.

    ``ToolError`` SDK превращает в результат ``isError`` с нашим текстом —
    именно так объяснение («у jsonplaceholder 10 пользователей») доходит до
    модели. Необёрнутое исключение стало бы для клиента строкой
    ``Error executing tool get_user``: причина теряется.

    Ловятся обе ошибки дня: внешнего API (``ExternalAPIError``) и бэкенда
    планировщика (``BackendAPIError`` — отказ постановки задачи с текстом причины).
    """
    try:
        return call(*args)
    except (ExternalAPIError, backend_api.BackendAPIError) as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
def get_user(user_id: int) -> UserInfo:
    """Возвращает данные пользователя по его id.

    Параметр user_id — целое число (у jsonplaceholder 10 пользователей, id от 1
    до 10). Возвращает объект с полями id, name, username, email, city, phone,
    website, company. Пример вызова: get_user(user_id=1).

    Если пользователя с таким id нет, инструмент сообщает об ошибке (HTTP 404).
    """
    return _run(get_client().get_user, user_id)


@server.tool()
def get_post(post_id: int) -> PostInfo:
    """Возвращает пост по его id.

    Параметр post_id — целое число (у jsonplaceholder 100 постов, id от 1 до
    100). Возвращает объект с полями id, user_id, title, body: user_id — автор
    поста. Пример вызова: get_post(post_id=1).

    Если поста с таким id нет, инструмент сообщает об ошибке (HTTP 404).
    """
    return _run(get_client().get_post, post_id)


@server.tool()
def list_user_posts(user_id: int, limit: int = 5) -> UserPosts:
    """Возвращает посты пользователя.

    Параметры: user_id — целое число (кто автор), limit — сколько постов вернуть
    (от 1 до 20, по умолчанию 5). Возвращает объект с полями user_id, count и
    posts — список записей с id и title. Пример: list_user_posts(user_id=1,
    limit=3).
    """
    return _run(get_client().list_user_posts, user_id, limit)


# ---------- инструменты планировщика: тела — вызов API дня (день 18) ----------
def _scheduled(tool: str, arguments: dict, builder):
    """Ставит задачу через API дня и собирает структуру ответа инструмента.

    Постановку делает бэкенд дня (единственный писатель в SQLite, и фон живёт
    там же). Неудача немедленного шага — это данные: ``message`` объясняет, что
    задача всё равно поставлена, и причина едет модели текстом.
    """
    payload = _run(backend_api.get_client().schedule_tool, tool, arguments)
    if payload.get("result") is None and payload.get("error"):
        raise ToolError(f"{payload.get('message', '')} — {payload['error']}".strip())
    return builder(payload)


def _task_of(payload: dict) -> dict:
    """Задача из ответа бэкенда (поле ``task``)."""
    task = payload.get("task")
    if not isinstance(task, dict):
        raise ToolError("Бэкенд дня не вернул задачу планировщика")
    return task


def _moment(value) -> str:
    """Момент времени строкой (в ответе API он уже ISO-8601)."""
    return "" if value is None else str(value)


@server.tool()
def schedule_reminder(text: str, delay_seconds: int) -> ReminderScheduled:
    """Сохраняет напоминание и заводит фоновую задачу на его выдачу.

    Параметры: text — текст напоминания (до 500 символов); delay_seconds — через
    сколько секунд напомнить (от 1 до 86400). Напоминание сразу сохраняется в
    таблицу reminders, задача — в планировщик дня: через delay_seconds секунд она
    помечает напоминание выполненным и кладёт уведомление в очередь (его видно в
    интерфейсе). Пример: schedule_reminder(text="позвонить клиенту",
    delay_seconds=300).
    """
    def build(payload: dict) -> ReminderScheduled:
        task = _task_of(payload)
        result = payload.get("result") or {}
        reminder = result.get("reminder") or {}
        return ReminderScheduled(
            task_id=int(task.get("id", 0)),
            reminder_id=int(result.get("reminder_id") or reminder.get("id") or 0),
            text=str(reminder.get("text", text)),
            remind_at=_moment(reminder.get("remind_at")),
            status=str(reminder.get("status", "scheduled")),
            next_run_at=_moment(task.get("next_run_at")),
            message=str(payload.get("message", "")),
        )

    return _scheduled("schedule_reminder",
                      {"text": text, "delay_seconds": delay_seconds}, build)


@server.tool()
def collect_data(source_url: str, interval_seconds: int, name: str) -> CollectionStarted:
    """Периодически читает URL и накапливает ответы в базе дня.

    Параметры: source_url — адрес HTTP/HTTPS, откуда читать JSON (до 500
    символов); interval_seconds — период сбора в секундах (от 1 до 86400); name —
    имя сбора (им записи попадают в таблицу collected_data, по нему же их берёт
    сводка). Первый запрос выполняется сразу, дальше — каждые interval_seconds.
    Пример: collect_data(source_url="https://jsonplaceholder.typicode.com/posts",
    interval_seconds=10, name="posts").

    Если источник недоступен, инструмент сообщает об ошибке: сама задача при этом
    остаётся поставленной и повторит попытку по расписанию.
    """
    def build(payload: dict) -> CollectionStarted:
        task = _task_of(payload)
        collection = (payload.get("result") or {}).get("collection") or {}
        return CollectionStarted(
            task_id=int(task.get("id", 0)),
            name=str(collection.get("name", name)),
            source_url=str(collection.get("source_url", source_url)),
            interval_seconds=int(interval_seconds),
            next_run_at=_moment(task.get("next_run_at")),
            records_saved=int(collection.get("records_saved", 0)),
            message=str(payload.get("message", "")),
        )

    return _scheduled("collect_data",
                      {"source_url": source_url, "interval_seconds": interval_seconds,
                       "name": name}, build)


@server.tool()
def generate_summary(name: str, interval_seconds: int) -> SummaryReady:
    """Периодически агрегирует накопленные данные в сводку.

    Параметры: name — имя сводки (по нему отбираются записи collected_data);
    interval_seconds — и период агрегации, и период повтора (от 1 до 86400).
    Первая сводка считается сразу за прошедший интервал, дальше — каждые
    interval_seconds: инструмент считает число записей за период, для числовых
    полей — среднее, минимум и максимум, для строковых — сколько уникальных
    значений, и складывает текст сводки в таблицу periodic_summaries.
    Пример: generate_summary(name="posts", interval_seconds=20).
    """
    def build(payload: dict) -> SummaryReady:
        task = _task_of(payload)
        result = payload.get("result") or {}
        summary = result.get("summary") or {}
        aggregate = result.get("aggregate") or {}
        return SummaryReady(
            task_id=int(task.get("id", 0)),
            summary_id=int(summary.get("id", 0)),
            name=str(summary.get("name", name)),
            period_start=_moment(summary.get("period_start") or aggregate.get("period_start")),
            period_end=_moment(summary.get("period_end") or aggregate.get("period_end")),
            total_records=int(summary.get("total_records", 0)),
            summary_text=str(summary.get("content") or aggregate.get("summary_text") or ""),
            key_metrics=dict(summary.get("key_metrics") or aggregate.get("key_metrics") or {}),
            next_run_at=_moment(task.get("next_run_at")),
            message=str(payload.get("message", "")),
        )

    return _scheduled("generate_summary",
                      {"name": name, "interval_seconds": interval_seconds}, build)


# ---------- инструменты композиции: search → summarize → save_to_file (день 19) --
# Регистрация одним вызовом: тела инструментов лежат в ``pipeline_tools.py`` —
# рядом со своей логикой (источники поиска, правила сводки, запись файла), а не в
# этом модуле, который держит имя, версию и инструкцию сервера.
register_pipeline_tools(server)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки сервера (основной транспорт — stdio)."""
    parser = argparse.ArgumentParser(
        prog="server.py",
        description=(
            "MCP-сервер дня 19: инструменты get_user, get_post, list_user_posts "
            "поверх jsonplaceholder.typicode.com, инструменты планировщика "
            "schedule_reminder, collect_data, generate_summary через API дня и "
            "инструменты композиции search, summarize, save_to_file."
        ),
        epilog=(
            "Транспорт — stdio: сервер читает JSON-RPC со stdin и пишет ответы в "
            "stdout. Запускать вручную нужно для отладки; в приложении дня его "
            "поднимает MCP-клиент дочерним процессом:\n"
            "  uv run python mcp_server/server.py\n"
            "Инструменты планировщика ставят задачи в бэкенд дня, поэтому он "
            "должен быть запущен (uvicorn backend.api.main:app --port 8000).\n"
            "Инструменты композиции работают офлайн: search читает ленту внешнего "
            "API, файл внутри папки дня (--file-root) или таблицу базы дня "
            "(--db-path, только на чтение), summarize сводит найденное моделью "
            "DeepSeek, а при --llm off — агрегацией, save_to_file пишет результат "
            "в каталог --output-dir."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-base", default=DEFAULT_API_BASE,
        help=f"адрес внешнего API (по умолчанию {DEFAULT_API_BASE})",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"таймаут HTTP-запроса к внешнему API, с (по умолчанию {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--backend-url", default=BACKEND_URL,
        help=(
            "адрес бэкенда дня для инструментов планировщика "
            f"(по умолчанию {BACKEND_URL})"
        ),
    )
    parser.add_argument(
        "--output-dir", default=str(OUTPUT_DIR),
        help=(
            "каталог, куда save_to_file пишет результат "
            f"(по умолчанию {OUTPUT_DIR})"
        ),
    )
    parser.add_argument(
        "--file-root", default=str(FILE_ROOT),
        help=(
            "корень источников file: — путь источника разрешается только внутри "
            f"этого каталога (по умолчанию {FILE_ROOT})"
        ),
    )
    parser.add_argument(
        "--db-path", default=str(DB_PATH),
        help=(
            "база дня для источника sqlite: — открывается только на чтение "
            f"(по умолчанию {DB_PATH})"
        ),
    )
    parser.add_argument(
        "--llm", choices=("auto", "off"), default="auto",
        help=(
            "использовать ли DeepSeek в инструменте summarize: auto — если найден "
            "ключ, off — всегда агрегация (демо и тесты идут без сети)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Настраивает клиентов, источники и каталог вывода и запускает сервер по stdio."""
    args = parse_args(argv)
    configure(args.api_base, args.timeout)
    backend_api.configure(args.backend_url)
    search_sources.configure(file_root=args.file_root, db_path=args.db_path)
    file_writer.configure(args.output_dir)
    llm_client.configure(enabled=args.llm != "off")
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
