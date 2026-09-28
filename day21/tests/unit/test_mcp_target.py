"""Тесты разбора цели MCP-подключения (день 16): транспорт, URL, команда запуска.

Проверяется выбор транспорта по виду строки, перевод схемы ``sse://`` в
``http://`` (SSE-эндпоинт — обычный HTTP-ресурс), разбор команды запуска с
кавычками и обратными слэшами Windows-путей и ошибки разбора: пустая цель,
неизвестный транспорт, URL там, где нужна команда, и наоборот.
"""
import pytest

from backend.domain.mcp_target import (
    MCPTargetError,
    MCPTransport,
    detect_transport,
    parse_target,
    parse_transport,
    split_command,
)


@pytest.mark.parametrize("raw,expected", [
    ("uvx mcp-server-fetch", MCPTransport.STDIO),
    ("npx -y @modelcontextprotocol/server-filesystem .", MCPTransport.STDIO),
    ("stdio: uvx mcp-server-fetch", MCPTransport.STDIO),
    ("http://127.0.0.1:9000/mcp", MCPTransport.STREAMABLE_HTTP),
    ("https://mcp.example.com/mcp", MCPTransport.STREAMABLE_HTTP),
    ("sse://127.0.0.1:9000/sse", MCPTransport.SSE),
])
def test_transport_detected_by_shape(raw, expected):
    """Транспорт выбирается по виду цели, когда он не задан явно."""
    assert detect_transport(raw) is expected
    assert parse_target(raw).transport is expected


def test_stdio_target_splits_command_and_args():
    """Команда stdio разбирается на исполняемый файл и аргументы."""
    target = parse_target("npx -y @modelcontextprotocol/server-filesystem .")
    assert target.command == "npx"
    assert target.args == ("-y", "@modelcontextprotocol/server-filesystem", ".")
    assert target.url == ""
    assert target.label() == "npx -y @modelcontextprotocol/server-filesystem ."


def test_stdio_prefix_is_optional():
    """Префикс ``stdio:`` задаёт транспорт явно и не попадает в команду."""
    target = parse_target("stdio: uvx mcp-server-fetch")
    assert (target.transport, target.command, target.args) == (
        MCPTransport.STDIO, "uvx", ("mcp-server-fetch",)
    )


def test_windows_path_with_spaces_survives_split():
    """Обратные слэши и пробелы пути не съедаются разбором команды."""
    command, args = split_command('npx -y pkg "C:\\Program Files\\dir"')
    assert command == "npx"
    assert args == ("-y", "pkg", "C:\\Program Files\\dir")


def test_sse_scheme_becomes_http_url():
    """``sse://host/sse`` — это HTTP-эндпоинт; схема переводится в ``http://``."""
    target = parse_target("sse://127.0.0.1:9000/sse")
    assert target.transport is MCPTransport.SSE
    assert target.url == "http://127.0.0.1:9000/sse"


def test_http_url_kept_as_is():
    """Для Streamable HTTP URL не переписывается."""
    target = parse_target("https://mcp.example.com/mcp")
    assert target.transport is MCPTransport.STREAMABLE_HTTP
    assert target.url == "https://mcp.example.com/mcp"


@pytest.mark.parametrize("raw,transport,expected", [
    ("http://127.0.0.1:9000/mcp", "sse", MCPTransport.SSE),
    ("https://mcp.example.com/mcp", "http", MCPTransport.STREAMABLE_HTTP),
    ("sse://127.0.0.1:9000/sse", "sse", MCPTransport.SSE),
    ("uvx mcp-server-fetch", "stdio", MCPTransport.STDIO),
])
def test_explicit_transport_wins_over_shape(raw, transport, expected):
    """Явно заданный транспорт сильнее автоопределения по виду строки."""
    target = parse_target(raw, transport)
    assert target.transport is expected
    if expected is MCPTransport.STDIO:
        assert (target.command, target.url) == ("uvx", "")
    else:
        assert target.url.startswith("http")


def test_explicit_transport_conflicting_with_scheme_rejected():
    """Схема цели и явный транспорт противоречат друг другу — ошибка разбора."""
    with pytest.raises(MCPTargetError):
        parse_target("sse://127.0.0.1:9000/sse", MCPTransport.STREAMABLE_HTTP)


def test_transport_value_is_normalized():
    """Регистр и пробелы в значении транспорта не важны (значение идёт из UI)."""
    assert parse_transport(" AUTO ") is MCPTransport.AUTO
    assert parse_transport("Stdio") is MCPTransport.STDIO


@pytest.mark.parametrize("raw", ["", "   ", "\n"])
def test_empty_target_rejected(raw):
    """Пустая цель — ошибка с подсказкой, а не подключение «в никуда»."""
    with pytest.raises(MCPTargetError) as exc:
        parse_target(raw)
    assert "цель" in str(exc.value).lower()


@pytest.mark.parametrize("value", ["ws", "grpc", "tcp", "авто"])
def test_unknown_transport_rejected(value):
    """Неизвестный транспорт — ошибка со списком допустимых значений."""
    with pytest.raises(MCPTargetError) as exc:
        parse_transport(value)
    assert "stdio" in str(exc.value)


def test_transport_enum_passes_through():
    """Значение-enum принимается как есть (его отдаёт Pydantic-схема API)."""
    assert parse_transport(MCPTransport.AUTO) is MCPTransport.AUTO
    assert parse_target("uvx mcp-server-fetch", MCPTransport.AUTO).transport is MCPTransport.STDIO


@pytest.mark.parametrize("raw,transport", [
    ("uvx mcp-server-fetch", "http"),          # команда там, где нужен URL
    ("stdio: ", "stdio"),                      # пустая команда после префикса
    ("'незакрытая кавычка", "stdio"),          # обрыв кавычки при разборе
    ("http://", "http"),                       # URL без адреса сервера
])
def test_unparsable_target_rejected(raw, transport):
    """Несогласованная цель не доходит до подключения — падает на разборе."""
    with pytest.raises(MCPTargetError):
        parse_target(raw, transport)
