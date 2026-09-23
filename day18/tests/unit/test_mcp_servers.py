"""Тесты каталога MCP-серверов (день 18): что предлагает ``GET /mcp/servers``.

Каталог отвечает на два вопроса: какие цели вообще можно подключить и которая из
них подключена сейчас. Совпадение целей проверяется по нормализованному виду
(``parse_target``), поэтому подключённым подсвечивается сервер даже при другой
записи команды, а неразобранная цель не роняет запрос.
"""
import pytest

from backend.core import config
from backend.domain.mcp_servers import (
    KNOWN_SERVERS,
    SERVER_KEY_DAY18,
    SERVER_KEY_FETCH,
    SERVER_KEY_FILESYSTEM,
    server_records,
)


def test_catalog_lists_known_servers_in_order():
    """Каталог отдаёт известные серверы в объявленном порядке: свой — первым."""
    records = server_records(None)
    assert [item["key"] for item in records] == [
        SERVER_KEY_DAY18, SERVER_KEY_FETCH, SERVER_KEY_FILESYSTEM,
    ]
    assert records[0]["target"] == config.MCP_DEFAULT_TARGET
    assert records[0]["description"] and records[0]["label"]


def test_nothing_connected_means_zero_tool_counts():
    """Без подключения в каталоге нет ни одного подключённого сервера."""
    records = server_records(None, tool_count=7)
    assert all(not item["connected"] for item in records)
    assert all(item["tool_count"] == 0 for item in records)


def test_connected_server_is_the_only_one_marked():
    """Число инструментов достаётся ровно подключённому серверу."""
    records = server_records(config.MCP_DEFAULT_TARGET, tool_count=3)
    connected = [item for item in records if item["connected"]]
    assert len(connected) == 1
    assert connected[0]["key"] == SERVER_KEY_DAY18
    assert connected[0]["tool_count"] == 3
    assert all(item["tool_count"] == 0 for item in records if not item["connected"])


def test_equivalent_target_wording_counts_as_connected():
    """Цель сравнивается нормализованно: кавычки в команде не прячут подключение."""
    quoted = 'uv run python "mcp_server/server.py"'
    assert quoted != config.MCP_DEFAULT_TARGET
    assert server_records(quoted)[0]["connected"] is True


def test_other_known_server_can_be_connected():
    """Подключение к серверу официального набора отмечается у него, а не у своего."""
    records = server_records(config.MCP_FETCH_TARGET, tool_count=1)
    keys = [item["key"] for item in records if item["connected"]]
    assert keys == [SERVER_KEY_FETCH]


@pytest.mark.parametrize("target", ["", "   ", "sse://", "http://"])
def test_unparsable_target_does_not_break_catalog(target):
    """Неразобранная цель — «никто не подключён», а не исключение."""
    records = server_records(target)
    assert [item["connected"] for item in records] == [False, False, False]


def test_server_option_matches_normalizes_both_sides():
    """``matches`` нормализует и свою цель, и пришедшую из реестра."""
    option = KNOWN_SERVERS[0]
    assert option.matches(config.MCP_DEFAULT_TARGET) is True
    assert option.matches(config.MCP_FETCH_TARGET) is False
    assert option.matches(None) is False


def test_server_option_to_dict_shape():
    """Запись каталога — плоский словарь контракта ответа."""
    payload = KNOWN_SERVERS[1].to_dict(connected=True, tool_count=4)
    assert set(payload) == {"key", "label", "target", "description", "connected",
                            "tool_count"}
    assert payload["connected"] is True and payload["tool_count"] == 4
