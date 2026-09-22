"""Каталог MCP-серверов дня 17: что вообще можно подключить (``GET /mcp/servers``).

Процесс держит одно MCP-подключение (``MCPRegistry``), поэтому «серверы» — это
не список открытых соединений, а каталог известных целей: свой сервер дня
(``day17/mcp_server``) и два сервера официального набора для сравнения. Каталог
отвечает на вопросы «что ещё посмотреть» и «кто из них подключён сейчас».

Сравнение целей идёт по нормализованному виду (``parse_target``), а не по строке
из поля ввода: «uv  run  python …» и «uv run python …» — одна и та же цель,
поэтому подключённым подсвечивается тот сервер, который реально открыт, даже если
пользователь набрал команду иначе. Неразобранная цель (пустая строка) не даёт
исключения — она просто ничему не соответствует.

Модуль чистый: ``config`` и ``mcp_target``, никаких HTTP и Streamlit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from ..core import config
from .mcp_target import MCPTargetError, parse_target

#: Ключи серверов каталога: попадают в ответ API и в подписи интерфейса.
SERVER_KEY_DAY17 = "day17-jsonplaceholder"
SERVER_KEY_FETCH = "fetch"
SERVER_KEY_FILESYSTEM = "filesystem"


@dataclass(frozen=True, slots=True)
class MCPServerOption:
    """Сервер каталога: ключ, подпись, цель подключения и описание возможностей."""

    key: str
    label: str
    target: str
    description: str

    def matches(self, target_label: Optional[str]) -> bool:
        """Указывает ли ``target_label`` на эту цель (сравнение по нормализованному виду)."""
        if not target_label:
            return False
        try:
            return parse_target(target_label).label() == parse_target(self.target).label()
        except MCPTargetError:
            return False

    def to_dict(self, *, connected: bool, tool_count: int) -> dict[str, Any]:
        """Запись каталога: ``connected`` — истина только у открытого соединения."""
        return {
            "key": self.key,
            "label": self.label,
            "target": self.target,
            "description": self.description,
            "connected": connected,
            "tool_count": tool_count,
        }


#: Каталог известных серверов: свой — первым, ему же достаётся подпись в UI.
KNOWN_SERVERS: tuple[MCPServerOption, ...] = (
    MCPServerOption(
        key=SERVER_KEY_DAY17,
        label="День 17: свой MCP-сервер (jsonplaceholder)",
        target=config.MCP_DEFAULT_TARGET,
        description=(
            "Собственный сервер дня по stdio: инструменты get_user, get_post и "
            "list_user_posts читают https://jsonplaceholder.typicode.com "
            "(пользователи, посты и посты пользователя)."
        ),
    ),
    MCPServerOption(
        key=SERVER_KEY_FETCH,
        label="Официальный набор: fetch (uvx)",
        target=config.MCP_FETCH_TARGET,
        description=(
            "Fetch-сервер MCP (нужен uvx): загружает URL и возвращает содержимое "
            "страницы в markdown — полезен, чтобы сравнить свой сервер с готовым."
        ),
    ),
    MCPServerOption(
        key=SERVER_KEY_FILESYSTEM,
        label="Официальный набор: filesystem (npx)",
        target=config.MCP_FILESYSTEM_TARGET,
        description=(
            "Файловый сервер MCP (нужен Node): чтение и запись файлов в "
            "разрешённых каталогах; запускается через npx."
        ),
    ),
)


def server_records(connected_target: Optional[str],
                   tool_count: int = 0,
                   servers: Sequence[MCPServerOption] = KNOWN_SERVERS) -> list[dict[str, Any]]:
    """Записи каталога в объявленном порядке; число инструментов — у подключённого."""
    records: list[dict[str, Any]] = []
    for server in servers:
        connected = server.matches(connected_target)
        records.append(server.to_dict(
            connected=connected,
            tool_count=tool_count if connected else 0,
        ))
    return records
