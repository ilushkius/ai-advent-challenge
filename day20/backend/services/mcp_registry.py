"""Реестр MCP-подключений дня 20: активное соединение плюс флот серверов.

Две роли в одном объекте, потому что обе — про «кто именно получит вызов»:

- **активное соединение** (день 16/17) — то, что открывает пользователь в разделе
  «🔌 MCP»: ``connect``/``disconnect``/``status``/``tools``/``call_active_tool``.
  Роуты ``/mcp/...`` работают ровно с ним, семантика дня 17 не изменилась;
- **флот** (день 20) — серверы из ``mcp_servers.json``: реестр держит по одному
  ``MCPClient`` на сервер (``connect_all``), кэширует каталог каждого
  (``tools/list``, в памяти и в файле конфигурации) и МАРШРУТИЗИРУЕТ вызов по
  имени инструмента (``find_tool_by_name`` → ``call_tool_on``). Оркестратору не
  нужно знать, какой сервер умеет ``summarize``: он спрашивает реестр.

Дубли имён инструментов. Если два сервера публикуют один инструмент, выигрывает
первый в порядке записей файла (``logger.warning`` о дубле): так маршрутизация
остаётся предсказуемой, а добавление сервера не меняет поведение уже работающих
вызовов. Ошибкой это не считается — дубль может быть осознанным (сервер-замена).

Сбой одного сервера не мешает остальным: ``connect_all`` не бросает исключений,
а кладёт текст причины в запись сервера (``error``) и состояние — в его FSM.
Так интерфейс и API показывают «три сервера, один не поднялся» вместо падения
приложения на старте.

Состояние одного сервера (конфигурация, соединение, каталог, ошибка) живёт в
отдельном модуле — ``mcp_fleet_state.FleetMember``: реестр остаётся про
маршрутизацию и жизненный цикл, а запись сервера читается им же в API.

Тесты подменяют фабрики клиентов (``client_factory`` для активного соединения,
``fleet_factory`` для серверов флота) — реестр тогда работает на фейке и не
поднимает настоящий MCP-сервер.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from shared.logging_utils import get_logger

from ..core import config, mcp_server_config
from ..domain.mcp_server_spec import MCPServerSpec, MCPServerSpecError
from ..domain.mcp_target import MCPTransport
from ..domain.mcp_tools import MCPFleetTool, MCPToolInfo, MCPToolResult
from .mcp_client import MCPClient, MCPError, MCPNotConnectedError
from .mcp_errors import MCPUnknownServerError, MCPUnknownToolError
from .mcp_fleet_state import FleetMember

logger = get_logger(__name__)

#: Как реестр зовёт фабрику клиента флота: цель, таймаут и рабочий каталог.
FleetFactory = Callable[[MCPServerSpec], MCPClient]


class MCPRegistry:
    """Активное MCP-подключение процесса плюс флот серверов из конфигурации."""

    def __init__(
        self,
        client_factory: Callable[..., MCPClient] = MCPClient,
        *,
        fleet_factory: FleetFactory | None = None,
        servers_file: str | Path | None = None,
        cwd: str | None = None,
    ):
        self._client_factory = client_factory
        self._fleet_factory = fleet_factory
        self._servers_file = Path(servers_file or config.MCP_SERVERS_FILE)
        self._cwd = config.MCP_FLEET_CWD if cwd is None else cwd
        self._client: MCPClient | None = None
        self._fleet: dict[str, FleetMember] = {}

    # ---------- активное соединение (день 16/17) ----------
    @property
    def client(self) -> MCPClient | None:
        """Текущий клиент активного соединения (None, если его ещё не открывали)."""
        return self._client

    def connect(self, target: str, transport: MCPTransport | str = MCPTransport.AUTO) -> MCPClient:
        """Открывает новое активное соединение, закрывая прежнее.

        Исключение пробрасывается наружу: роутер переводит его в 400 (не разобрана
        цель) или 502 (сервер недоступен). Клиент при этом остаётся в реестре —
        ``GET /mcp/status`` показывает состояние ``error`` и текст причины, а не
        «нет подключения вообще».
        """
        self._drop()
        client = self._client_factory(target, transport=transport)
        self._client = client
        client.connect()
        return client

    def disconnect(self) -> None:
        """Закрывает активное соединение (если его нет — безопасный no-op)."""
        self._drop()

    def tools(self, *, refresh: bool = False) -> list[MCPToolInfo]:
        """Инструменты активного соединения (без соединения — исключение)."""
        if self._client is None:
            raise MCPNotConnectedError(
                "Подключение к MCP-серверу не установлено: сначала POST /mcp/connect"
            )
        return self._client.list_tools(refresh=refresh)

    def call_active_tool(self, tool_name: str,
                         arguments: dict[str, Any] | None = None) -> MCPToolResult:
        """Вызывает инструмент АКТИВНОГО соединения (без него — исключение).

        Правила допуска — в домене (``backend/domain/mcp_tool_call``), а оркеструет
        их ``MCPToolRunner``: здесь только транспорт, и единственное соединение
        процесса решает, кто получит вызов. Вызов во флоте идёт другим путём —
        ``call_tool`` (маршрутизация по имени инструмента).
        """
        if self._client is None:
            raise MCPNotConnectedError(
                "Подключение к MCP-серверу не установлено: сначала POST /mcp/connect"
            )
        return self._client.call_tool(tool_name, arguments)

    def status(self) -> dict:
        """Состояние активного соединения для ``GET /mcp/status`` и ответов connect."""
        client = self._client
        if client is None:
            return {
                "connected": False,
                "state": "disconnected",
                "target": None,
                "transport": None,
                "transport_label": None,
                "server_name": "",
                "server_version": "",
                "protocol": "",
                "tool_count": 0,
                "error": None,
                "allowed_events": ["connect"],
            }
        server = client.server_info
        return {
            "connected": client.connected,
            "state": client.state.value,
            "target": client.target.label(),
            "transport": client.target.transport.value,
            "transport_label": client.target.transport.label,
            "server_name": server.get("name", ""),
            "server_version": server.get("version", ""),
            "protocol": server.get("protocol", ""),
            "tool_count": len(client.tools),
            "error": client.last_error,
            "allowed_events": [event.value for event in client.allowed_events()],
        }

    # ---------- флот серверов (день 20) ----------
    def connect_all(self) -> list[dict]:
        """Поднимает флот по файлу конфигурации: подключить новых, обновить упавших.

        Перечитывает файл: новые серверы подключаются, исчезнувшие закрываются,
        уже подключённые не трогаются (кроме добора каталога, если он пуст).
        Сбой отдельного сервера не бросает исключение — он остаётся в списке с
        текстом причины, поэтому приложение стартует и с одним живым сервером.
        """
        try:
            specs = mcp_server_config.load_specs(self._servers_file)
        except MCPServerSpecError as exc:
            logger.error("Флот MCP: конфигурация не разобрана: %s", exc)
            return self.servers()
        names = {spec.name for spec in specs}
        for name in [item for item in self._fleet if item not in names]:
            self._drop_member(name)
        for spec in specs:
            member = self._fleet.get(spec.name)
            if member is None:
                member = FleetMember(spec=spec)
                self._fleet[spec.name] = member
            else:
                member.spec = spec
            if member.connected:
                if not member.tools:
                    self._read_tools(member)
                continue
            self._open(member)
        return self.servers()

    def disconnect_all(self) -> None:
        """Закрывает соединения всех серверов флота (записи конфигурации остаются)."""
        for member in self._fleet.values():
            self._close_member(member)

    def refresh_tools(self) -> list[dict]:
        """Перечитывает каталог каждого подключённого сервера и пишет кэш в файл."""
        for name, member in self._fleet.items():
            if not member.connected:
                continue
            self._read_tools(member, refresh=True)
            self._save_cache(name, member)
        return self.servers()

    def servers(self) -> list[dict]:
        """Записи серверов флота для ``GET /mcp/servers`` (в порядке файла)."""
        return [
            member.spec.to_status(
                connected=member.connected,
                state=member.state,
                tool_count=len(member.catalog()),
                error=member.error,
            )
            for member in self._fleet.values()
        ]

    def tools_of(self, server_name: str) -> list[MCPToolInfo]:
        """Каталог сервера флота (неизвестный сервер — ``MCPUnknownServerError``)."""
        return list(self._member(server_name).catalog())

    def list_all_tools(self) -> list[MCPFleetTool]:
        """Плоский каталог флота: инструмент плюс имя его сервера."""
        return [
            MCPFleetTool(server=name, tool=tool)
            for name, member in self._fleet.items()
            for tool in member.catalog()
        ]

    def find_tool_by_name(self, tool_name: str) -> str | None:
        """Имя сервера, публикующего инструмент (None — такого инструмента нет).

        При дублях выигрывает первый сервер в порядке файла: маршрут предсказуем и
        не зависит от того, какой сервер поднялся быстрее.
        """
        found: list[str] = [
            item.server for item in self.list_all_tools() if item.name == tool_name
        ]
        if not found:
            return None
        if len(found) > 1:
            logger.warning("Флот MCP: инструмент %s публикуют несколько серверов %s — "
                           "вызов пойдёт в %s", tool_name, ", ".join(found), found[0])
        return found[0]

    def connected(self, server_name: str | None = None) -> bool:
        """Есть ли соединение: у сервера флота либо у активного (``None``)."""
        if server_name is None:
            return self._client is not None and self._client.connected
        member = self._fleet.get(server_name)
        return member is not None and member.connected

    def ensure_connected(self, server_name: str) -> MCPClient:
        """Соединение с сервером флота, при необходимости — открыть его сейчас.

        Так работает динамическая маршрутизация: сервер, который не поднялся на
        старте (или упал), подключается ровно тогда, когда до него дошёл шаг плана.
        """
        member = self._member(server_name)
        if member.connected:
            return member.client  # type: ignore[return-value]
        self._open(member, raise_errors=True)
        if not member.connected:
            raise MCPError(member.error or f"Сервер «{server_name}» не подключён")
        return member.client  # type: ignore[return-value]

    def call_tool_on(self, server_name: str, tool_name: str,
                     arguments: dict[str, Any] | None = None) -> MCPToolResult:
        """Вызывает инструмент КОНКРЕТНОГО сервера флота (подключая его при нужде)."""
        return self.ensure_connected(server_name).call_tool(tool_name, arguments)

    def call_tool(self, tool_name: str,
                  arguments: dict[str, Any] | None = None) -> MCPToolResult:
        """Вызывает инструмент флота: сервер выбирается по имени инструмента.

        Неизвестный инструмент — ``MCPUnknownToolError`` со списком известных: это
        отказ маршрутизации, а не сбой сервера, и текст должен это объяснять.
        """
        server_name = self.find_tool_by_name(tool_name)
        if server_name is None:
            known = ", ".join(item.name for item in self.list_all_tools()) or "нет"
            raise MCPUnknownToolError(
                f"Инструмент «{tool_name}» не публикует ни один сервер флота. "
                f"Известны: {known}"
            )
        return self.call_tool_on(server_name, tool_name, arguments)

    def fleet_status(self) -> dict:
        """Сводка флота для API: серверы, их число, сколько подключено и инструментов."""
        servers = self.servers()
        return {
            "servers": servers,
            "count": len(servers),
            "connected": sum(1 for item in servers if item["connected"]),
            "total_tools": sum(int(item["tool_count"]) for item in servers),
        }

    # ---------- закрытие ----------
    def close(self) -> None:
        """Закрывает активное соединение и всех серверов флота (lifespan)."""
        self._drop()
        self.disconnect_all()

    # ---------- внутреннее ----------
    def _member(self, server_name: str) -> FleetMember:
        """Запись сервера флота (неизвестный сервер — ``MCPUnknownServerError``)."""
        member = self._fleet.get(server_name)
        if member is None:
            known = ", ".join(self._fleet) or "нет"
            raise MCPUnknownServerError(
                f"Сервер «{server_name}» не зарегистрирован; известны: {known}"
            )
        return member

    def _factory_for(self, member: FleetMember) -> Callable[[], MCPClient]:
        """Фабрика клиента сервера: переданная флоту либо общая фабрика дня."""
        if self._fleet_factory is not None:
            return lambda: self._fleet_factory(member.spec)  # type: ignore[misc]
        return lambda: self._client_factory(
            member.spec.target, timeout=config.MCP_TIMEOUT, cwd=self._cwd
        )

    def _open(self, member: FleetMember, *, raise_errors: bool = False) -> None:
        """Подключает сервер флота, записывая причину отказа в его запись."""
        self._close_member(member)
        client = self._factory_for(member)()
        member.client = client
        try:
            client.connect()
        except MCPError as exc:
            member.error = str(exc)
            logger.error("Флот MCP: сервер %s не подключился: %s", member.spec.name, exc)
            if raise_errors:
                raise
            return
        except Exception as exc:  # noqa: BLE001 — сбой сервера не роняет приложение
            member.error = str(exc)
            logger.error("Флот MCP: сервер %s не подключился: %s", member.spec.name, exc)
            if raise_errors:
                raise MCPError(str(exc)) from exc
            return
        member.error = None
        logger.info("Флот MCP: сервер %s подключён", member.spec.name)
        self._read_tools(member)

    def _read_tools(self, member: FleetMember, *, refresh: bool = False) -> None:
        """Читает ``tools/list`` сервера; пусто — остаётся кэш из файла конфигурации."""
        client = member.client
        if client is None or not client.connected:
            return
        try:
            member.tools = list(client.list_tools(refresh=refresh))
        except MCPError as exc:
            member.error = str(exc)
            logger.warning("Флот MCP: каталог %s не прочитан: %s", member.spec.name, exc)
            return
        if member.tools:
            member.error = None

    def _save_cache(self, name: str, member: FleetMember) -> None:
        """Пишет прочитанный каталог в файл конфигурации (ошибка — не сбой сервера)."""
        try:
            mcp_server_config.save_tools_cache(name, member.tools, self._servers_file)
        except MCPServerSpecError as exc:
            logger.warning("Флот MCP: кэш %s не записан: %s", name, exc)

    def _drop_member(self, name: str) -> None:
        """Закрывает и забывает сервер флота (его больше нет в конфигурации)."""
        member = self._fleet.pop(name, None)
        if member is not None:
            self._close_member(member)

    def _close_member(self, member: FleetMember) -> None:
        """Закрывает соединение сервера, оставляя запись в списке флота."""
        client, member.client = member.client, None
        if client is None:
            return
        try:
            client.close()
        except Exception as exc:  # noqa: BLE001 — закрытие не должно ломать запрос
            logger.error("Флот MCP: не удалось закрыть %s: %s", member.spec.name, exc)

    def _drop(self) -> None:
        """Закрывает и забывает активный клиент (общий шаг disconnect/close/connect)."""
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.close()
        except Exception as exc:  # noqa: BLE001 — закрытие не должно ломать запрос
            logger.error("MCP: не удалось закрыть прошлое соединение: %s", exc)


_registry: MCPRegistry | None = None


def get_mcp_registry() -> MCPRegistry:
    """Единственный реестр MCP процесса (ленивый singleton)."""
    global _registry
    if _registry is None:
        _registry = MCPRegistry()
    return _registry
