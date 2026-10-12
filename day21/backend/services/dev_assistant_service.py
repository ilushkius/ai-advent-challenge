"""Ассистент разработчика (день 31): ответ ``/help`` по документации и git-контексту.

Что делает служба.
    ``handle_help`` на один вопрос собирает ДВА источника и склеивает их в один
    контекст: фрагменты RAG-индекса по документации проекта (корпус дня 22) и
    ответы инструментов MCP-сервера разработки (ветка, коммит, изменённые файлы,
    diff, структура). Что именно подтягивать — решает домен (``dev_assistant.
    classify_question`` и ``plan_tools``), а служба только исполняет план: иначе
    правило «git-вопрос начинается с get_git_branch» жило бы в двух местах.

Почему отдельный модуль, а не метод мини-чата.
    У мини-чата источник один — корпус, а ответ дополняют память и история. Здесь
    источников два, второй живёт в ДРУГОМ ПРОЦЕССЕ (stdio-сервер), и ключевое
    поведение службы — пережить его отсутствие: ответ по документации должен
    получиться даже тогда, когда MCP-сервер не поднялся. Отказы поэтому приходят
    ДАННЫМИ (``warnings``), а не стеком: 500 в разделе интерфейса не объяснил бы
    ничего.

Почему свой клиент MCP, а не флот дня 20.
    Флот из ``mcp_servers.json`` — три сервера проекта, и его состав закреплён
    разделом «🌐 Оркестрация». Ассистенту нужен четвёртый сервер (``dev_server``),
    у которого нет ни флота, ни отчётов: он подключается одним клиентом на процесс
    и закрывается при остановке бэкенда (``api/lifespan.py``).

Провайдер ответа.
    По умолчанию DeepSeek (``config.LLM_PROVIDER``), локальная Ollama — второй
    провайдер переключателя дней 26–29. Путь к модели один для всего проекта
    (``rag_llm.client_for``/``answer``/``call_with_retry``): повторы, профиль
    локальной модели и журнал расходов у ассистента те же, что у RAG и мини-чата.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger

from ..core import config
from ..domain import dev_assistant, llm_provider, rag_mode
from . import rag_llm, rag_records
from .index_service import IndexNotBuiltError, get_index_service
from .mcp_client import MCPClient
from .mcp_errors import MCPError
from .rag_errors import RAGUpstreamError

logger = get_logger(__name__)

#: Имя сервера в ответе ``GET /dev-assistant/tools`` и в панели раздела.
DEV_SERVER_NAME = "dev_server"

#: Пустое состояние репозитория: возвращается, когда инструмент не ответил.
_EMPTY_GIT = {"branch": "", "last_commit": "", "modified_files": [],
              "clean": True, "repo_root": ""}

__all__ = ["DEV_SERVER_NAME", "DevAssistantMCPError", "DevAssistantService",
           "get_dev_assistant_service", "make_dev_assistant_client"]


def make_dev_assistant_client():
    """Клиент DeepSeek ассистента: ключ резолвится в момент вызова.

    Ключ читается не на импорте: служба собирается на старте приложения, а ключ к
    моменту первого вопроса может быть ещё не задан.
    """
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day21/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)


class DevAssistantMCPError(RuntimeError):
    """MCP-сервер разработки не поднялся: служба отвечает данными, а не стеком."""


class DevAssistantService:
    """Ответы ``/help``: документация проекта из RAG плюс контекст git через MCP."""

    def __init__(self, *, index_service=None, llm_client: Optional[Any] = None,
                 mcp_client: Optional[Any] = None,
                 mcp_target: str = dev_assistant.DEV_SERVER_TARGET,
                 mcp_cwd: Optional[object] = None,
                 top_k: int = dev_assistant.DEFAULT_TOP_K,
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
    def top_k(self) -> int:
        """Сколько фрагментов документации берёт поиск (значение конструктора)."""
        return self._top_k

    @property
    def server(self) -> Any:
        """MCP-клиент сервера разработки: подменённый или подключённый один раз.

        Соединение держится на процесс: каждый вопрос поднимать stdio-сервер заново
        значило бы платить секунды за то же самое. Сбой подключения — не состояние
        клиента, а ``DevAssistantMCPError``: вызывающий код отвечает по RAG.
        """
        if self._mcp_client is not None:
            return self._mcp_client
        with self._lock:
            if self._server is None:
                self._server = self._connect()
            return self._server

    def _connect(self) -> Any:
        """Поднимает stdio-сервер и читает его каталог; сбой — ``DevAssistantMCPError``."""
        client = MCPClient(self._mcp_target,
                           cwd=self._mcp_cwd if self._mcp_cwd is not None
                           else config.MCP_FLEET_CWD)
        try:
            client.connect()
            client.list_tools()
        except MCPError as exc:
            client.close()
            raise DevAssistantMCPError(str(exc)) from exc
        return client

    def llm_client_for(self, provider: Optional[str] = None) -> Any:
        """Клиент ответа провайдера; подменённый клиент важнее имени провайдера.

        ``provider=None`` уходит в ``rag_llm.client_for`` только тогда, когда
        заглушки нет: так тесты и скрипты отвечают без сети, а рабочая служба
        выбирает клиент по имени провайдера.
        """
        return rag_llm.client_for(
            self._llm_clients, None if self._llm_client is not None else provider, None,
            stub=self._llm_client, agent_id=dev_assistant.AGENT_ID,
            client_factory=make_dev_assistant_client)

    # ---------- ответ на вопрос ----------
    def handle_help(self, question: str, provider: Optional[str] = None) -> dict:
        """Ответ на вопрос ``/help``: контекст двух источников, источники и инструменты.

        Пустой вопрос — ``ValueError`` (роутер отвечает 400): искать пустую строку в
        индексе бессмысленно. Незнакомый провайдер — тоже ``ValueError``, а сбой
        модели — ``RAGUpstreamError`` (502) либо, при уже собранном контексте,
        честный текст в поле ``answer`` с предупреждением: раздел не должен падать
        из-за недоступной Ollama, если индекс и git доступны.
        """
        started = time.perf_counter()
        text = dev_assistant.normalize_question(question)
        if not text:
            raise ValueError("Пустой вопрос: напишите «/help <вопрос>»")
        name = llm_provider.resolve(provider)
        client = self.llm_client_for(provider)
        kind = dev_assistant.classify_question(text)
        warnings: list = []
        sources: list = []
        used: list = []
        hits: list = []
        tool_blocks: list = []
        if kind in (dev_assistant.KIND_DOCS, dev_assistant.KIND_MIXED):
            hits = self._search_docs(text, warnings)
            sources = [rag_records.source(hit) for hit in hits]
        if kind in (dev_assistant.KIND_GIT, dev_assistant.KIND_MIXED):
            tool_blocks = self._call_tools(text, kind, warnings, used)
        context = dev_assistant.render_context(hits, tool_blocks)
        answer = self._answer(client, name, text, context, warnings)
        return {
            "question": text,
            "question_type": kind,
            "answer": answer,
            "sources": sources,
            "mcp_tools_used": used,
            "duration_ms": self._elapsed_ms(started),
            "provider": name,
            "warnings": warnings,
        }

    def _search_docs(self, question: str, warnings: list) -> list:
        """Фрагменты документации по вопросу; пустой индекс — предупреждение, не отказ."""
        try:
            return list(self.index_service.search(
                question, top_k=self._top_k, strategy=rag_mode.RAG_DEFAULT_STRATEGY))
        except IndexNotBuiltError as exc:
            logger.warning("Ассистент: индекс документации недоступен: %s", exc)
            warnings.append(dev_assistant.WARN_INDEX_EMPTY.format(error=exc))
            return []

    def _call_tools(self, question: str, kind: str, warnings: list, used: list) -> list:
        """Вызовы инструментов плана: записи журнала и блоки контекста.

        Недоступный сервер или обрыв связи отменяет весь план (записи в ``used``
        остаются с ``ok=False``): частичный ответ по мёртвому соединению выглядел бы
        как ответ по живому. Ошибка ОДНОГО инструмента — не обрыв: остальные шаги
        плана выполняются, а причина видна в ``warnings`` и в записи инструмента.
        """
        plan = dev_assistant.plan_tools(kind, question)
        if not plan:
            return []
        try:
            client = self.server
        except DevAssistantMCPError as exc:
            warnings.append(dev_assistant.WARN_MCP_UNAVAILABLE.format(error=exc))
            used.extend({"tool": name, "ok": False, "duration_ms": 0, "error": str(exc)}
                        for name, _ in plan)
            return []
        blocks: list = []
        for position, (name, arguments) in enumerate(plan):
            try:
                result = client.call_tool(name, arguments)
            except MCPError as exc:
                warnings.append(dev_assistant.WARN_MCP_UNAVAILABLE.format(error=exc))
                used.extend({"tool": planned, "ok": False, "duration_ms": 0,
                             "error": str(exc)} for planned, _ in plan[position:])
                return []
            used.append({"tool": name, "ok": not result.is_error,
                         "duration_ms": int(result.duration_ms),
                         "error": result.text if result.is_error else ""})
            if result.is_error:
                warnings.append(dev_assistant.WARN_TOOL_FAILED.format(tool=name,
                                                                     error=result.text))
                continue
            block = _tool_block(name, result)
            if block is None:
                warnings.append(dev_assistant.WARN_TOOL_TEXT_ONLY.format(tool=name))
            else:
                blocks.append(block)
        return blocks

    def _answer(self, client: Any, name: str, question: str, context: str,
                warnings: list) -> str:
        """Ответ модели по собранному контексту; без контекста модель не вызывается."""
        if not context:
            logger.warning("Ассистент: нет ни документации, ни MCP-контекста")
            return dev_assistant.EMPTY_CONTEXT_ANSWER
        try:
            result = rag_llm.answer(self._sleep, client, system=dev_assistant.SYSTEM_PROMPT,
                                    context=context, question=question,
                                    agent_id=dev_assistant.AGENT_ID)
        except RAGUpstreamError as exc:
            warnings.append(str(exc))
            template = (dev_assistant.OLLAMA_UNAVAILABLE_ANSWER
                        if name == llm_provider.PROVIDER_LOCAL
                        else dev_assistant.LLM_UNAVAILABLE_ANSWER)
            return template.format(provider=llm_provider.label(name), error=exc)
        return rag_llm.response_text(result)

    # ---------- панели раздела ----------
    def tools(self) -> dict:
        """Каталог инструментов dev-сервера; сбой подключения — данные, не исключение.

        Всегда 200: панель «🛠 MCP-инструменты» показывает причину, а не падает,
        потому что сервер поднимается лениво и его отсутствие — штатный случай.
        """
        try:
            client = self.server
            infos = list(client.list_tools())
        except (DevAssistantMCPError, MCPError) as exc:
            logger.warning("Ассистент: каталог инструментов недоступен: %s", exc)
            return {"server": DEV_SERVER_NAME, "connected": False, "count": 0,
                    "tools": [], "error": str(exc)}
        return {"server": DEV_SERVER_NAME,
                "connected": bool(getattr(client, "connected", True)),
                "count": len(infos), "tools": [tool.to_dict() for tool in infos],
                "error": ""}

    def git_context(self) -> dict:
        """Ветка, коммит и изменённые файлы — панель «🌱 Git» раздела."""
        try:
            client = self.server
            result = client.call_tool(dev_assistant.TOOL_GIT_BRANCH, {})
        except (DevAssistantMCPError, MCPError) as exc:
            logger.warning("Ассистент: git-контекст недоступен: %s", exc)
            return dict(_EMPTY_GIT, error=str(exc))
        if result.is_error:
            return dict(_EMPTY_GIT, error=str(result.text or "инструмент вернул ошибку"))
        structured = result.structured if isinstance(result.structured, dict) else {}
        return {
            "branch": str(structured.get("branch") or ""),
            "last_commit": str(structured.get("last_commit") or ""),
            "modified_files": [str(item)
                               for item in structured.get("modified_files") or []],
            "clean": bool(structured.get("clean", True)),
            "repo_root": str(structured.get("repo_root") or ""),
            "error": "",
        }

    # ---------- жизненный цикл ----------
    def close(self) -> None:
        """Закрывает СВОЁ соединение со сервером разработки (подменённое не трогает)."""
        with self._lock:
            client = self._server
            self._server = None
        if client is not None:
            client.close()

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        """Миллисекунды от отметки ``started`` — время ответа в отчёте и в разделе."""
        return int((time.perf_counter() - started) * 1000)


def _tool_block(name: str, result) -> Optional[dict]:
    """Блок контекста одного инструмента: структура или текст, пустой — ``None``.

    Инструмент, вернувший строку, приходит от SDK обёрнутым в ``{"result": "…"}``:
    разворачивать эту обёртку здесь, а не в контексте, — иначе модель получила бы
    JSON вокруг текста diff и не увидела бы сами строки.
    """
    structured = result.structured
    if isinstance(structured, dict) and set(structured) == {"result"} \
            and isinstance(structured["result"], str):
        structured = None
    if isinstance(structured, dict) and structured:
        return {"tool": name, "structured": structured, "text": ""}
    if isinstance(structured, list) and structured:
        return {"tool": name, "structured": structured, "text": ""}
    text = str(result.text or "")
    if text:
        return {"tool": name, "structured": None, "text": text}
    return None


#: Служба процесса: соединение с dev-сервером одно на процесс, как и у остальных служб.
_service: Optional[DevAssistantService] = None
_service_lock = threading.Lock()


def get_dev_assistant_service() -> DevAssistantService:
    """Служба ассистента разработчика процесса (точка подмены: ``main.get_dev_assistant_service``)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = DevAssistantService()
        return _service
