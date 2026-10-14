"""Ассистент поддержки пользователей (день 33): FAQ, профиль и тикет в одном ответе.

Что делает служба.
    ``answer`` собирает на один вопрос клиента ТРИ источника и склеивает их в один
    контекст: фрагменты RAG-индекса по документации поддержки (FAQ, разборы
    симптомов, справочник API), профиль клиента и его тикет из MCP-сервера
    поддержки, а также раздел продукта, определённый по словам вопроса. Что именно
    подтягивать, решает вызывающий (``user_id``/``ticket_id`` вопроса) и домен
    (``support.detect_area``), а служба только исполняет это: иначе правило «тикет
    подтягивает своего пользователя» жило бы в двух местах.

Почему отдельный модуль, а не метод мини-чата.
    У мини-чата источник один — корпус, а ответ дополняют память и история. Здесь
    источник второй живёт в ДРУГОМ ПРОЦЕССЕ (stdio-сервер поддержки), и ключевое
    поведение службы — пережить его отсутствие: ответ по документации должен
    получиться даже тогда, когда MCP-сервер не поднялся или профиль не найден.
    Отказы поэтому приходят ДАННЫМИ (``warnings``), а не стеком: 500 в разделе
    интерфейса не объяснил бы ничего.

Почему свой клиент MCP, а не флот дня 20.
    Флот из ``mcp_servers.json`` — три сервера проекта, и его состав закреплён
    разделом «🌐 Оркестрация». Поддержке нужен пятый сервер (``support_server``),
    у которого нет ни флота, ни отчётов: он подключается одним клиентом на процесс
    и закрывается при остановке бэкенда (``api/lifespan.py``).

Провайдер ответа.
    По умолчанию DeepSeek (``config.LLM_PROVIDER``), локальная Ollama — второй
    провайдер переключателя дней 26–29. Путь к модели один для всего проекта
    (``rag_llm.client_for``/``answer``): повторы, профиль локальной модели и журнал
    расходов у поддержки те же, что у RAG и мини-чата.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger

from ..core import config
from ..domain import llm_provider, rag_mode, support
from . import rag_llm, rag_records
from .index_service import IndexNotBuiltError, get_index_service
from .mcp_client import MCPClient
from .mcp_errors import MCPError
from .rag_errors import RAGUpstreamError

logger = get_logger(__name__)

__all__ = ["SupportMCPError", "SupportService", "get_support_service", "make_support_client"]


def make_support_client():
    """Клиент DeepSeek службы поддержки: ключ резолвится в момент вызова.

    Как у остальных служб: служба собирается на старте приложения, а ключ к моменту
    первого вопроса может быть ещё не задан.
    """
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day21/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)


class SupportMCPError(RuntimeError):
    """MCP-сервер поддержки не поднялся: служба отвечает по RAG, а не стеком."""


class SupportService:
    """Ответы клиенту: документация поддержки из RAG плюс профиль и тикет через MCP."""

    def __init__(self, *, index_service=None, llm_client: Optional[Any] = None,
                 mcp_client: Optional[Any] = None,
                 mcp_target: str = support.SUPPORT_SERVER_TARGET,
                 mcp_cwd: Optional[object] = None,
                 top_k: int = support.DEFAULT_TOP_K,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._index_service = index_service
        self._llm_client = llm_client
        self._llm_clients: Dict[str, Any] = {}
        self._mcp_client = mcp_client
        self._mcp_target = mcp_target
        self._mcp_cwd = mcp_cwd
        self._top_k = int(top_k)
        self._sleep = sleep
        self._server: Optional[Any] = None
        self._lock = threading.RLock()

    # ---------- зависимости ----------
    @property
    def index_service(self):
        """Служба индексов: переданная или служба процесса (индекс общий с RAG)."""
        if self._index_service is None:
            self._index_service = get_index_service()
        return self._index_service

    @property
    def server(self) -> Any:
        """MCP-клиент сервера поддержки: подменённый или подключённый один раз.

        Соединение держится на процесс: каждый вопрос поднимать stdio-сервер заново
        значило бы платить секунды за то же самое. Сбой подключения — не состояние
        клиента, а ``SupportMCPError``: вызывающий код отвечает по RAG.
        """
        if self._mcp_client is not None:
            return self._mcp_client
        with self._lock:
            if self._server is None:
                self._server = self._connect()
            return self._server

    def _connect(self) -> Any:
        """Поднимает stdio-сервер и читает его каталог; сбой — ``SupportMCPError``."""
        client = MCPClient(self._mcp_target,
                           cwd=self._mcp_cwd if self._mcp_cwd is not None
                           else config.MCP_FLEET_CWD)
        try:
            client.connect()
            client.list_tools()
        except MCPError as exc:
            client.close()
            raise SupportMCPError(str(exc)) from exc
        return client

    def llm_client_for(self, provider: Optional[str] = None) -> Any:
        """Клиент ответа провайдера; подменённый клиент важнее имени провайдера."""
        return rag_llm.client_for(
            self._llm_clients, None if self._llm_client is not None else provider, None,
            stub=self._llm_client, agent_id=support.AGENT_ID,
            client_factory=make_support_client)

    # ---------- ответ на вопрос ----------
    def answer(self, question: str, user_id: Optional[str] = None,
               ticket_id: Optional[str] = None, provider: Optional[str] = None) -> dict:
        """Ответ клиенту: контекст трёх источников, источники и вызовы инструментов.

        Пустой вопрос — ``ValueError`` (роутер отвечает 400): искать пустую строку в
        индексе бессмысленно. Незнакомый провайдер — тоже ``ValueError``, а сбой
        модели при уже собранном контексте — честный текст в поле ``answer`` с
        предупреждением: раздел не должен падать из-за недоступной Ollama, если
        документация и MCP-данные доступны.
        """
        started = time.perf_counter()
        text = support.normalize_question(question)
        if not text:
            raise ValueError("Пустой вопрос: напишите вопрос о продукте")
        name = llm_provider.resolve(provider)
        client = self.llm_client_for(provider)
        warnings: list = []
        used: list = []
        ticket_context = user_context = product_context = None
        if ticket_id:
            ticket_context, user_id = self._read_ticket(ticket_id, user_id, warnings, used)
        if user_id:
            user_context = self._read_user(user_id, warnings, used)
        area = support.detect_area(text)
        if area:
            product_context = self._read_product(area, warnings, used)
        hits = self._search_docs(text, warnings)
        context = support.render_context(hits, user_context, ticket_context, product_context)
        return {
            "answer": self._answer(client, name, text, context, warnings),
            "sources": [rag_records.source(hit) for hit in hits],
            "user_context": user_context,
            "ticket_context": ticket_context,
            "product_context": product_context,
            "mcp_tools_used": used,
            "duration_ms": self._elapsed_ms(started),
            "provider": name,
            "warnings": warnings,
        }

    def _read_ticket(self, ticket_id: str, user_id: Optional[str], warnings: list,
                     used: list) -> Tuple[Optional[dict], Optional[str]]:
        """Тикет и id клиента: профиль из тикета подтягивается, если не задан вопросом.

        Клиент часто называет тикет, не называя себя: тикет знает своего владельца,
        и второй запрос за профилем получается бесплатным по смыслу. Ненайденный
        тикет — предупреждение и ``None``: ответ по документации всё равно полезен.
        """
        structured = self._call(support.TOOL_GET_TICKET, {"ticket_id": str(ticket_id)},
                                warnings, used)
        if structured is None:
            return None, user_id
        if structured.get("error"):
            warnings.append(support.WARN_TICKET_NOT_FOUND.format(ticket_id=ticket_id))
            return None, user_id
        block = support.ticket_block(structured)
        return block, user_id or str(block.get("user_id") or "")

    def _read_user(self, user_id: str, warnings: list, used: list) -> Optional[dict]:
        """Профиль клиента без служебного поля ``error``; ненайденный — предупреждение."""
        structured = self._call(support.TOOL_GET_USER, {"user_id": str(user_id)},
                                warnings, used)
        if structured is None:
            return None
        if structured.get("error"):
            warnings.append(support.WARN_USER_NOT_FOUND.format(user_id=user_id))
            return None
        return {key: value for key, value in structured.items() if key != "error"}

    def _read_product(self, area: str, warnings: list, used: list) -> Optional[dict]:
        """Раздел продукта по области вопроса; неизвестная область — предупреждение."""
        structured = self._call(support.TOOL_GET_PRODUCT_INFO, {"product_area": area},
                                warnings, used)
        if structured is None:
            return None
        if structured.get("error"):
            warnings.append(support.WARN_TOOL_FAILED.format(
                tool=support.TOOL_GET_PRODUCT_INFO, error=structured["error"]))
            return None
        return {key: value for key, value in structured.items() if key != "error"}

    def _call(self, name: str, arguments: dict, warnings: list, used: list) -> Optional[dict]:
        """Один вызов MCP-инструмента: запись журнала и структурированный результат.

        Недоступный сервер или обрыв связи — не исключение для вызывающего, а
        предупреждение и запись с ``ok=False``: служба продолжает по RAG. Результат
        без структуры (SDK отдаёт текст обёрткой ``{"result": …}``) считается
        пустым: модель не получила данных, а раздел показывает запись инструмента.
        """
        try:
            client = self.server
        except SupportMCPError as exc:
            warnings.append(support.WARN_MCP_UNAVAILABLE.format(error=exc))
            used.append({"tool": name, "ok": False, "duration_ms": 0, "error": str(exc)})
            return None
        try:
            result = client.call_tool(name, dict(arguments))
        except MCPError as exc:
            warnings.append(support.WARN_MCP_UNAVAILABLE.format(error=exc))
            used.append({"tool": name, "ok": False, "duration_ms": 0, "error": str(exc)})
            return None
        used.append({"tool": name, "ok": not result.is_error,
                     "duration_ms": int(result.duration_ms),
                     "error": result.text if result.is_error else ""})
        if result.is_error:
            warnings.append(support.WARN_TOOL_FAILED.format(tool=name, error=result.text))
            return None
        structured = result.structured
        if isinstance(structured, dict) and structured \
                and set(structured) != {"result"}:
            return structured
        return None

    def _search_docs(self, question: str, warnings: list) -> list:
        """Фрагменты документации поддержки; пустой индекс — предупреждение, не отказ."""
        try:
            return list(self.index_service.search(
                question, top_k=self._top_k, strategy=rag_mode.RAG_DEFAULT_STRATEGY))
        except IndexNotBuiltError as exc:
            logger.warning("Поддержка: индекс документации недоступен: %s", exc)
            warnings.append(support.WARN_INDEX_EMPTY.format(error=exc))
            return []

    def _answer(self, client: Any, name: str, question: str, context: str,
                warnings: list) -> str:
        """Ответ модели по собранному контексту; без контекста модель не вызывается."""
        if not context:
            logger.warning("Поддержка: нет ни документации, ни MCP-контекста")
            return support.EMPTY_CONTEXT_ANSWER
        try:
            result = rag_llm.answer(self._sleep, client, system=support.SYSTEM_PROMPT,
                                    context=context, question=question,
                                    agent_id=support.AGENT_ID)
        except RAGUpstreamError as exc:
            warnings.append(str(exc))
            template = (support.OLLAMA_UNAVAILABLE_ANSWER
                        if name == llm_provider.PROVIDER_LOCAL
                        else support.LLM_UNAVAILABLE_ANSWER)
            return template.format(provider=llm_provider.label(name), error=exc)
        return rag_llm.response_text(result)

    # ---------- панели раздела ----------
    def users(self) -> dict:
        """Каталог клиентов поддержки; сбой подключения — данные, не исключение.

        Всегда 200: селектор пользователей раздела показывает причину, а не падает,
        потому что сервер поднимается лениво и его отсутствие — штатный случай.
        """
        try:
            client = self.server
            result = client.call_tool(support.TOOL_LIST_USERS, {})
        except (SupportMCPError, MCPError) as exc:
            logger.warning("Поддержка: каталог пользователей недоступен: %s", exc)
            return {"count": 0, "users": [], "error": str(exc)}
        if result.is_error:
            return {"count": 0, "users": [],
                    "error": str(result.text or "инструмент вернул ошибку")}
        structured = result.structured if isinstance(result.structured, dict) else {}
        users = [item for item in structured.get("users") or [] if isinstance(item, dict)]
        return {"count": int(structured.get("count") or len(users)), "users": users,
                "error": str(structured.get("error") or "")}

    def user(self, user_id: str) -> dict:
        """Один профиль клиента; сбой подключения пробрасывается (роутер отвечает 502).

        Панельной паре «список — запись» нужны разные политики отказов: список
        показывается целиком с причиной, а запись отвечает 404/502, чтобы адрес
        ``/support/users/{id}`` не возвращал 200 на несуществующий профиль.
        """
        result = self.server.call_tool(support.TOOL_GET_USER, {"user_id": str(user_id)})
        structured = result.structured if isinstance(result.structured, dict) else {}
        error = str(result.text or "") if result.is_error else str(structured.get("error") or "")
        if error:
            return {"user": None, "error": error}
        return {"user": {key: value for key, value in structured.items() if key != "error"},
                "error": ""}

    def ticket(self, ticket_id: str) -> dict:
        """Один тикет целиком; сбой подключения пробрасывается (роутер отвечает 502)."""
        result = self.server.call_tool(support.TOOL_GET_TICKET,
                                       {"ticket_id": str(ticket_id)})
        structured = result.structured if isinstance(result.structured, dict) else {}
        error = str(result.text or "") if result.is_error else str(structured.get("error") or "")
        if error:
            return {"ticket": None, "error": error}
        return {"ticket": {key: value for key, value in structured.items()
                           if key != "error"}, "error": ""}

    def user_tickets(self, user_id: str) -> dict:
        """Тикеты клиента для селектора тикета; сбой подключения — данные, не исключение."""
        try:
            client = self.server
            result = client.call_tool(support.TOOL_LIST_USER_TICKETS,
                                      {"user_id": str(user_id)})
        except (SupportMCPError, MCPError) as exc:
            logger.warning("Поддержка: тикеты пользователя недоступны: %s", exc)
            return {"user_id": str(user_id), "count": 0, "tickets": [], "error": str(exc)}
        if result.is_error:
            return {"user_id": str(user_id), "count": 0, "tickets": [],
                    "error": str(result.text or "инструмент вернул ошибку")}
        structured = result.structured if isinstance(result.structured, dict) else {}
        tickets = [item for item in structured.get("tickets") or []
                   if isinstance(item, dict)]
        return {"user_id": str(structured.get("user_id") or user_id),
                "count": int(structured.get("count") or len(tickets)),
                "tickets": tickets, "error": str(structured.get("error") or "")}

    # ---------- жизненный цикл ----------
    def close(self) -> None:
        """Закрывает СВОЁ соединение с сервером поддержки (подменённое не трогает)."""
        with self._lock:
            client = self._server
            self._server = None
        if client is not None:
            client.close()

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        """Миллисекунды от отметки ``started`` — время ответа в отчёте и в разделе."""
        return int((time.perf_counter() - started) * 1000)


#: Служба процесса: соединение с сервером поддержки одно на процесс, как у остальных.
_service: Optional[SupportService] = None
_service_lock = threading.Lock()


def get_support_service() -> SupportService:
    """Служба поддержки процесса (точка подмены: ``main.get_support_service``)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = SupportService()
        return _service
