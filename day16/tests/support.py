"""Общие фейки и утилиты тестов дня 16 (импортируется как ``from support import ...``).

Тесты не ходят в сеть и не пишут в рабочую БД `day11/agents.db`: движок создаётся
на временном файле (`tmp_path`), а клиент DeepSeek подменяется `FakeClient`.
Подменяется ровно одна точка — `Agent._make_client`, поэтому проверяется реальная
логика агента (сборка payload со слоями памяти, метрики, транзакции), а не
заглушка вместо неё.

Сюда же вынесен `seed_dialog` — наполнение краткосрочного слоя без вызовов API.

Для дня 16 здесь лежит ``FakeMCPClient``: тесты реестра и эндпоинтов ``/mcp``
подменяют им настоящий клиент (``MCPClient`` поднимал бы дочерний процесс или
ходил в сеть). Состояние подключения у фейка настоящее — стейт-машина
``backend.domain.mcp_connection_fsm``, поэтому FSM проверяется и через API.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.core import config
from backend.agents.agent import Agent
from backend.domain.demo_invariants import DEMO_INVARIANTS
from backend.services.compressor import SUMMARY_SYSTEM_PROMPT
from backend.services.invariant_checker import INVARIANT_CHECK_SYSTEM_PROMPT
from backend.storage.database import AgentRecord
from backend.schemas import AgentConfig
from backend.agents.profile_store import ProfileStore
from backend.services.task_state import TaskStateMachine
from backend.storage.invariant_store import InvariantManager
from backend.domain.mcp_connection_fsm import (
    MCPConnectionEvent,
    MCPConnectionFSM,
    MCPConnectionState,
)
from backend.domain.mcp_target import MCPTransport, parse_target
from backend.domain.mcp_tools import MCPToolInfo
from backend.services.mcp_client import MCPConnectionError, MCPNotConnectedError


# ---------- фейковый клиент DeepSeek ----------
class FakeUsage:
    """usage-блок ответа: числа запроса/ответа, как у OpenAI SDK."""

    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class FakeResponse:
    """Минимальный ответ chat.completions: choices[0].message.content + usage."""

    def __init__(self, content: str, prompt_tokens: int = 100,
                 completion_tokens: int = 20) -> None:
        self.choices = [
            SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop"
            )
        ]
        self.usage = FakeUsage(prompt_tokens, completion_tokens)


class FakeCompletions:
    """chat.completions: записывает вызовы и отвечает по роли запроса."""

    def __init__(self, owner: "FakeClient") -> None:
        self._owner = owner

    def create(self, model, messages, temperature=None, max_tokens=None):
        self._owner.calls.append(
            {"model": model, "messages": messages, "temperature": temperature}
        )
        system_text = messages[0].get("content") if messages else None
        is_summary = bool(messages and system_text == SUMMARY_SYSTEM_PROMPT)
        is_invariant_check = bool(messages and system_text == INVARIANT_CHECK_SYSTEM_PROMPT)
        if is_summary and self._owner.summary_error is not None:
            raise self._owner.summary_error
        if is_invariant_check and self._owner.invariant_error is not None:
            raise self._owner.invariant_error
        if not is_summary and not is_invariant_check and self._owner.error is not None:
            raise self._owner.error
        if self._owner.responses:
            return self._owner.responses.pop(0)
        # Вызовы различаются системным промптом роли: конспектёр, контролёр
        # инвариантов, генератор ответа.
        if is_summary:
            return FakeResponse(
                self._owner.summary_reply,
                prompt_tokens=self._owner.summary_prompt_tokens,
                completion_tokens=self._owner.summary_completion_tokens,
            )
        if is_invariant_check:
            return FakeResponse(
                self._owner.invariant_reply,
                prompt_tokens=self._owner.invariant_prompt_tokens,
                completion_tokens=self._owner.invariant_completion_tokens,
            )
        return FakeResponse(
            self._owner.reply,
            prompt_tokens=self._owner.prompt_tokens,
            completion_tokens=self._owner.completion_tokens,
        )


class FakeClient:
    """Фейковый клиент DeepSeek с записью всех вызовов."""

    def __init__(
        self,
        reply: str = "Ответ ассистента",
        summary_reply: str = "- Пользователь спросил о погоде\n- Обсудили планы",
        error: Exception | None = None,
        summary_error: Exception | None = None,
        responses: list | None = None,
        prompt_tokens: int = 100,
        completion_tokens: int = 20,
        summary_prompt_tokens: int = 50,
        summary_completion_tokens: int = 10,
        invariant_reply: str = '{"violations": []}',
        invariant_error: Exception | None = None,
        invariant_prompt_tokens: int = 50,
        invariant_completion_tokens: int = 10,
    ) -> None:
        self.reply = reply
        self.summary_reply = summary_reply
        self.error = error
        self.summary_error = summary_error
        self.responses = list(responses or [])
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.summary_prompt_tokens = summary_prompt_tokens
        self.summary_completion_tokens = summary_completion_tokens
        # Ответ контролёра инвариантов по умолчанию — «нарушений нет»: тесты без
        # правил проекта и тесты с чистым текстом не должны зависеть от этой ветки.
        self.invariant_reply = invariant_reply
        self.invariant_error = invariant_error
        self.invariant_prompt_tokens = invariant_prompt_tokens
        self.invariant_completion_tokens = invariant_completion_tokens
        self.calls: list = []
        self.chat = SimpleNamespace(completions=FakeCompletions(self))

    @property
    def generate_calls(self) -> list:
        """Только вызовы генерации (без суммаризации и без проверки инвариантов)."""
        return [
            call for call in self.calls
            if not (call["messages"]
                    and call["messages"][0].get("content") in (
                        SUMMARY_SYSTEM_PROMPT, INVARIANT_CHECK_SYSTEM_PROMPT))
        ]

    @property
    def summary_calls(self) -> list:
        """Только вызовы суммаризации."""
        return [
            call for call in self.calls
            if call["messages"]
            and call["messages"][0].get("content") == SUMMARY_SYSTEM_PROMPT
        ]

    @property
    def invariant_calls(self) -> list:
        """Только вызовы проверки инвариантов (контролёр, не генерация)."""
        return [
            call for call in self.calls
            if call["messages"]
            and call["messages"][0].get("content") == INVARIANT_CHECK_SYSTEM_PROMPT
        ]


def seed_dialog(agent: Agent, turns: int) -> None:
    """Наполняет краткосрочный слой сессии парами user/assistant без вызовов API."""
    for index in range(turns):
        agent.save_message("user", f"Вопрос номер {index} про токены и контекст")
        agent.save_message("assistant", f"Ответ номер {index} с подробностями")


DEFAULT_AGENT_PARAMS = {
    "name": "Тестовый агент",
    "summary_enabled": True,
    "keep_last_messages": 2,
    "summarize_every": 2,
}


def seed_profile(session_factory, user_id: str, **data):
    """Создаёт профиль пользователя в тестовой БД (наследовано из дня 12).

    Обёртка над ``ProfileStore.create``: тестам агента и API нужен профиль «как
    из интерфейса», а не ручная вставка строки в user_profiles.
    """
    return ProfileStore(session_factory=session_factory).create(user_id, **data)


def create_task(session_factory, agent_id: str, task_id: str,
                stage: str = "planning") -> dict:
    """Заводит состояние задачи в тестовой БД (день 13).

    Обёртка над ``TaskStateMachine.create``: тестам агента и API нужно состояние
    «как из интерфейса», а не ручная вставка строки в task_states. Работает от
    имени ``agent_id``, поэтому строка агента должна уже существовать (её создаёт
    ``create_agent``).
    """
    return TaskStateMachine(session_factory=session_factory).create(
        agent_id, task_id, stage
    )


def seed_invariant(session_factory, name: str, description: str, category: str,
                   severity: str) -> dict:
    """Заводит инвариант в тестовой БД (день 14).

    Обёртка над ``InvariantManager.add_invariant``: тестам агента и API нужны
    правила «как из интерфейса», а не ручная вставка строки в invariants.
    """
    return InvariantManager(session_factory=session_factory).add_invariant(
        name, description, category, severity
    )


def seed_demo_invariants(session_factory) -> list[dict]:
    """Сеет весь демонстрационный набор инвариантов и возвращает строки БД."""
    manager = InvariantManager(session_factory=session_factory)
    return [manager.add_invariant(**item) for item in DEMO_INVARIANTS]


# ---------- фейковый MCP-клиент (день 16) ----------
#: Инструменты, которые «возвращает» фейковый сервер в тестах.
FAKE_MCP_TOOLS = (
    MCPToolInfo(name="echo", description="Возвращает текст",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}}),
    MCPToolInfo(name="add", description="Складывает числа",
                input_schema={"type": "object", "properties": {"a": {"type": "integer"}}}),
)

#: Ответ ``initialize`` фейкового сервера.
FAKE_MCP_SERVER = {"name": "fake-mcp", "version": "1.0.0", "protocol": "2025-11-25"}


class FakeMCPClient:
    """MCP-клиент без транспорта: настоящая FSM подключения, вместо сессии — список.

    Повторяет публичный контракт ``MCPClient`` (``target``, ``state``,
    ``connected``, ``tools``, ``server_info``, ``last_error``, ``allowed_events``,
    ``connect``, ``list_tools``, ``close``). ``fail`` задаёт сценарий «сервер
    недоступен»: ``connect`` уходит в ``error`` и падает с ``MCPConnectionError``
    — так проверяются 502 у ``/mcp/connect`` и состояние ``error`` у статуса.
    """

    def __init__(self, target, *, transport=MCPTransport.AUTO, timeout=None,
                 fail: str | None = None, tools=None):
        self._target = parse_target(target, transport)
        self._fsm = MCPConnectionFSM()
        self._tools = tuple(FAKE_MCP_TOOLS if tools is None else tools)
        self._fail = fail
        self._last_error: str | None = None
        self._listed = False
        self.closed = False
        self.list_calls = 0

    @property
    def target(self):
        return self._target

    @property
    def state(self) -> MCPConnectionState:
        return self._fsm.state

    @property
    def connected(self) -> bool:
        return self._fsm.state is MCPConnectionState.CONNECTED

    @property
    def tools(self):
        """Как у настоящего клиента: пусто до первого ``list_tools``."""
        return self._tools if self._listed else ()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def server_info(self) -> dict:
        return dict(FAKE_MCP_SERVER) if self.connected else {}

    def allowed_events(self):
        return self._fsm.allowed_events()

    def connect(self) -> "FakeMCPClient":
        self._fsm.handle(MCPConnectionEvent.CONNECT)
        if self._fail:
            self._fsm.handle(MCPConnectionEvent.FAIL)
            self._last_error = self._fail
            raise MCPConnectionError(self._fail)
        self._fsm.handle(MCPConnectionEvent.CONNECTED)
        return self

    def list_tools(self, *, refresh: bool = False):
        if not self.connected:
            raise MCPNotConnectedError(
                f"Соединение с MCP-сервером не установлено (состояние {self.state.value})"
            )
        self.list_calls += 1
        self._listed = True
        return list(self._tools)

    def close(self) -> None:
        self.closed = True
        if self._fsm.can(MCPConnectionEvent.DISCONNECT):
            self._fsm.handle(MCPConnectionEvent.DISCONNECT)


def make_mcp_factory(**client_kwargs):
    """Фабрика фейковых клиентов: ``factory.created`` — все созданные экземпляры.

    Реестр зовёт фабрику как ``MCPClient(target, transport=...)``, поэтому
    сигнатура совпадает; список ``created`` нужен тестам, чтобы убедиться, что
    прежнее соединение закрыто, а не забыто.
    """
    created: list[FakeMCPClient] = []

    def factory(target, *, transport=MCPTransport.AUTO, timeout=None):
        client = FakeMCPClient(target, transport=transport, timeout=timeout,
                               **client_kwargs)
        created.append(client)
        return client

    factory.created = created
    return factory


def create_agent(session_factory, agent_id: str, cfg=None, ensure_record: bool = True,
                 session_id: str | None = None, task_id: str | None = None,
                 **overrides) -> Agent:
    """Создаёт агента ВМЕСТЕ со строкой в таблице agents (иначе FK не пустит реплики).

    В приложении запись делает ``AgentManager.create_agent``; тестам нужен тот же
    инвариант («агент есть в БД»), но без менеджера — он проверяется отдельно.
    ``ensure_record=False`` строит второй объект Agent поверх уже существующей
    записи — так эмулируется рестарт бэкенда.

    ``session_id``/``task_id`` — активные сессия и задача агента (день 11): они же
    пишутся в строку ``agents``, чтобы вторая сборка Agent их увидела.
    """
    if cfg is None:
        params = dict(DEFAULT_AGENT_PARAMS)
        params.update(overrides)
        cfg = AgentConfig(**params)
    session_id = session_id or uuid.uuid4().hex[:config.SESSION_ID_LENGTH]
    task_id = task_id or config.DEFAULT_TASK_ID
    if ensure_record:
        with session_factory() as session:
            session.add(AgentRecord(
                agent_id=agent_id, name=cfg.name, model=cfg.model,
                temperature=cfg.temperature, system_prompt=cfg.system_prompt,
                max_tokens=cfg.max_tokens, summary_enabled=cfg.summary_enabled,
                keep_last_messages=cfg.keep_last_messages,
                summarize_every=cfg.summarize_every,
                strategy=cfg.strategy, window_size=cfg.window_size,
                current_session_id=session_id, current_task_id=task_id,
                user_id=cfg.user_id,
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()
    return Agent(cfg, agent_id=agent_id, session_factory=session_factory,
                 session_id=session_id, task_id=task_id)
