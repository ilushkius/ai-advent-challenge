"""AI-ревью PR (день 32): diff, RAG-контекст и структурированное ревью от модели.

Что делает служба.
    ``review_pr`` собирает ревью целиком: берёт diff (из payload или через MCP
    ``get_pr_diff``), список изменённых файлов (из payload, через MCP
    ``get_changed_files`` или из самого diff-а), подтягивает ДВА источника контекста
    (документация проекта и код изменённых файлов из RAG-индекса корпуса дня 22),
    режет diff до 2000 строк, зовёт модель по JSON-контракту и разбирает её ответ в
    структуру: баги, архитектурные проблемы, рекомендации, риски P0–P3.

Почему отдельный модуль, а не расширение ассистента разработчика.
    У ассистента дня 31 вопрос идёт от человека и ответ — текст; здесь на входе diff,
    на выходе структура, а MCP-инструменты другие. Общий у них только способ
    подключения к своему stdio-серверу (``mcp_servers/dev_server``) и путь к модели.

Два источника diff-а: локальный (payload или MCP по ``base``/``head``) и GitHub REST API
(``review_github_pr`` → ``services/code_review_github.py``); поиск контекста вынесен в
``services/code_review_context.py``, клиент GitHub — в ``services/github_client.py``.

Отказы приходят ДАННЫМИ: нет индекса корпуса — ревью состоится по diff-у, и причина
попадёт в ``warnings``; модель не ответила — честный текст в ``review_text``.
Исключения остались там, где ревью невозможно: ``ValueError`` — diff-а нет и взять
его негде (400), ``CodeReviewError`` — MCP не поднялся (502).

Провайдер ответа.
    По умолчанию DeepSeek (``config.LLM_PROVIDER``), локальная Ollama — второй
    провайдер переключателя дней 26–29; путь к модели общий с RAG и мини-чатом.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger

from ..core import config
from ..domain import code_review, dev_assistant, llm_provider, rag_mode
from . import code_review_context, code_review_github, rag_llm, rag_records
from .github_client import GitHubClient
from .index_service import get_index_service
from .mcp_client import MCPClient
from .mcp_errors import MCPError
from .rag_errors import RAGUpstreamError

logger = get_logger(__name__)

__all__ = ["CodeReviewError", "CodeReviewService", "get_code_review_service",
           "make_code_review_client"]


def make_code_review_client():
    """Клиент DeepSeek ревью: ключ резолвится в момент вызова.

    Как у остальных служб: служба собирается на старте приложения, а ключ к моменту
    первого запроса может быть ещё не задан.
    """
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day21/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)


def _tool_text(result) -> str:
    """Текст результата инструмента: у строковых ответов — из обёртки ``{"result": …}``.

    ``get_pr_diff`` возвращает ``str``, и SDK оборачивает его в ``{"result": …}``;
    разворачивать обёртку здесь, а не в контексте, — иначе модель получила бы JSON
    вокруг текста diff и не увидела бы сами строки.
    """
    structured = result.structured
    if isinstance(structured, dict) and set(structured) == {"result"} \
            and isinstance(structured["result"], str):
        return structured["result"]
    return str(result.text or "")


class CodeReviewError(RuntimeError):
    """Diff не добыть: он не передан и MCP-сервер разработки не ответил."""


class CodeReviewService:
    """Ревью PR: diff, контекст документации и кода, структурированный ответ модели."""

    def __init__(self, *, index_service=None, llm_client: Optional[Any] = None,
                 mcp_client: Optional[Any] = None,
                 mcp_target: str = dev_assistant.DEV_SERVER_TARGET,
                 mcp_cwd: Optional[object] = None,
                 top_k: int = code_review.DEFAULT_TOP_K,
                 github_client: Optional[Any] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._index_service = index_service
        self._llm_client = llm_client
        self._llm_clients: Dict[str, Any] = {}
        self._mcp_client = mcp_client
        self._mcp_target = mcp_target
        self._mcp_cwd = mcp_cwd
        self._top_k = int(top_k)
        self._github_client = github_client
        self._github_owned = github_client is None
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
        """MCP-клиент dev-сервера: подменённый или подключённый один раз на процесс.

        Сбой подключения — не состояние клиента, а ``CodeReviewError``: без diff-а
        ревью невозможно, и служба говорит об этом исключением, а не пустым ответом.
        """
        if self._mcp_client is not None:
            return self._mcp_client
        with self._lock:
            if self._server is None:
                self._server = self._connect()
            return self._server

    @property
    def github(self) -> Any:
        """Клиент GitHub: подменённый в тестах или один на процесс (ленивый)."""
        if self._github_client is None:
            self._github_client = GitHubClient()
        return self._github_client

    def _connect(self) -> Any:
        """Поднимает stdio-сервер и читает его каталог; сбой — ``CodeReviewError``."""
        client = MCPClient(self._mcp_target,
                           cwd=self._mcp_cwd if self._mcp_cwd is not None
                           else config.MCP_FLEET_CWD)
        try:
            client.connect()
            client.list_tools()
        except MCPError as exc:
            client.close()
            raise CodeReviewError(str(exc)) from exc
        return client

    def llm_client_for(self, provider: Optional[str] = None) -> Any:
        """Клиент ответа провайдера; подменённый клиент важнее имени провайдера."""
        return rag_llm.client_for(
            self._llm_clients, None if self._llm_client is not None else provider, None,
            stub=self._llm_client, agent_id=code_review.AGENT_ID,
            client_factory=make_code_review_client)

    # ---------- ревью ----------
    def review_pr(self, payload: dict, provider: Optional[str] = None) -> dict:
        """Ревью PR: diff, контекст двух источников и структура находок от модели.

        ``payload`` — тело запроса ``POST /review/pr``: готовые ``diff`` и
        ``changed_files`` важнее пары ``base``/``head`` (их тогда не нужно добывать
        через MCP), а ``pr_label``/``owner``/``repo``/``pr_number`` нужны только для
        подписи ревью. Пустой diff без ref-ов — ``ValueError`` (400), недоступный
        MCP при отсутствии diff-а — ``CodeReviewError`` (502).
        """
        started = time.perf_counter()
        name = llm_provider.resolve(provider)
        client = self.llm_client_for(provider)
        warnings: list = []
        used: list = []
        payload = dict(payload or {})
        diff = str(payload.get("diff") or "").strip()
        changed = [str(item).strip() for item in (payload.get("changed_files") or [])
                   if str(item).strip()]
        base = str(payload.get("base") or "").strip()
        head = str(payload.get("head") or "").strip()
        if not diff:
            if not base or not head:
                raise ValueError(code_review.NO_DIFF_ERROR)
            diff = self._fetch_diff(base, head, used, warnings)
            if not diff.strip():
                raise ValueError(code_review.EMPTY_DIFF_ERROR)
        if not changed:
            if base and head:
                changed = self._changed_files(base, head, used, warnings)
            if not changed:
                changed = code_review.changed_files_from_diff(diff)
        diff_info = code_review.truncate_diff(diff, code_review.MAX_DIFF_LINES)
        if diff_info["truncated"]:
            warnings.append(code_review.WARN_DIFF_TRUNCATED.format(
                kept=diff_info["kept_lines"], total=diff_info["total_lines"],
                files=", ".join(diff_info["omitted_files"]) or "—"))
        query = code_review.context_query(changed, diff)
        docs_hits = code_review_context.search_docs(self.index_service, query,
                                                    self._top_k, warnings)
        code_hits = code_review_context.search_code(self.index_service, changed, diff,
                                                    self._top_k, warnings)
        label = str(payload.get("pr_label") or "") or self._label(payload, base, head)
        review_text, parsed = self._review(client, name, label, changed, diff_info,
                                           docs_hits, code_hits, warnings)
        return {
            "review_text": review_text,
            "bugs": parsed["bugs"],
            "architecture_issues": parsed["architecture_issues"],
            "recommendations": parsed["recommendations"],
            "risks": parsed["risks"],
            "sources": _sources(docs_hits + code_hits),
            "mcp_tools_used": used,
            "changed_files": changed,
            "duration_ms": self._elapsed_ms(started),
            "provider": name,
            "warnings": warnings,
        }

    def review_github_pr(self, repo_url: str, pr_number: int, provider: str = "deepseek",
                         post_comment: bool = False) -> dict:
        """Ревью PR из GitHub: URL и номер → diff, файлы, RAG-контекст и ответ модели."""
        return code_review_github.review_github_pr(self, repo_url, pr_number,
                                                   provider=provider,
                                                   post_comment=post_comment)

    def github_health(self) -> dict:
        """Готовность GitHub: доступность API, признак токена и остаток лимита."""
        return self.github.health()

    def _review(self, client: Any, name: str, label: str, changed: list,
                diff_info: dict, docs_hits: list, code_hits: list,
                warnings: list) -> tuple[str, dict]:
        """Ответ модели и его разбор; недоступная модель — текст отказа, не исключение.

        Структура ревью без ответа модели бессмысленна, поэтому при сбое провайдера
        разбор не делается: ``parsed=False`` и пустые списки находок честнее, чем
        структура, которой модель не давала.
        """
        context = code_review.render_context(docs_hits, code_hits, changed, diff_info)
        question = code_review.review_question(label, changed)
        try:
            result = rag_llm.answer(self._sleep, client,
                                    system=code_review.SYSTEM_PROMPT, context=context,
                                    question=question, agent_id=code_review.AGENT_ID)
        except RAGUpstreamError as exc:
            logger.warning("Ревью: модель не ответила: %s", exc)
            warnings.append(str(exc))
            text = code_review.LLM_UNAVAILABLE_ANSWER.format(
                provider=llm_provider.label(name), error=exc)
            return text, {"bugs": [], "architecture_issues": [],
                          "recommendations": [], "risks": []}
        text = rag_llm.response_text(result)
        parsed = code_review.normalize_review(text)
        if not parsed["parsed"]:
            logger.warning("Ревью: ответ модели не разобран: %s", parsed["error"])
            warnings.append(code_review.WARN_JSON.format(error=parsed["error"]))
        return text, parsed

    # ---------- инструменты MCP ----------
    def _fetch_diff(self, base: str, head: str, used: list, warnings: list) -> str:
        """Diff двух ref через MCP; недоступный сервер — ``CodeReviewError`` (502)."""
        try:
            result = self.server.call_tool(code_review.TOOL_PR_DIFF,
                                           {"base": base, "head": head})
        except (CodeReviewError, MCPError) as exc:
            used.append(_use(code_review.TOOL_PR_DIFF, False, 0, str(exc)))
            warnings.append(code_review.WARN_MCP_UNAVAILABLE.format(error=exc))
            raise CodeReviewError(
                code_review.WARN_MCP_UNAVAILABLE.format(error=exc)) from exc
        used.append(_use(code_review.TOOL_PR_DIFF, not result.is_error,
                         int(result.duration_ms), result.text if result.is_error else ""))
        if result.is_error:
            warnings.append(code_review.WARN_TOOL_FAILED.format(
                tool=code_review.TOOL_PR_DIFF, error=result.text))
            return ""
        return _tool_text(result)

    def _changed_files(self, base: str, head: str, used: list, warnings: list) -> list:
        """Имена файлов PR через MCP; сбой — предупреждение и пустой список.

        Пустой список не ошибка: вызывающий возьмёт имена из самого diff-а, поэтому
        недоступный инструмент понижает качество якоря для RAG-контекста, а не ревью.
        """
        tool = code_review.TOOL_CHANGED_FILES
        try:
            result = self.server.call_tool(tool, {"base": base, "head": head})
        except (CodeReviewError, MCPError) as exc:
            used.append(_use(tool, False, 0, str(exc)))
            warnings.append(code_review.WARN_MCP_UNAVAILABLE.format(error=exc))
            return []
        used.append(_use(tool, not result.is_error, int(result.duration_ms),
                         result.text if result.is_error else ""))
        if result.is_error:
            warnings.append(code_review.WARN_TOOL_FAILED.format(tool=tool,
                                                                error=result.text))
            return []
        structured = result.structured if isinstance(result.structured, dict) else {}
        return [str(item) for item in structured.get("files") or [] if str(item).strip()]

    def _label(self, payload: dict, base: str, head: str) -> str:
        """Метка ревью: ``owner/repo#номер``, иначе ``base..head``, иначе «без метки»."""
        owner = str(payload.get("owner") or "").strip()
        repo = str(payload.get("repo") or "").strip()
        number = payload.get("pr_number") or 0
        if owner and repo and number:
            return f"{owner}/{repo}#{number}"
        return f"{base}..{head}" if base and head else "без метки"

    # ---------- панель и жизненный цикл ----------
    def health(self) -> dict:
        """Готовность службы ревью: провайдер, инструменты MCP, предел diff-а.

        Ни MCP, ни индекс здесь не трогаются: это ответ о конфигурации, а не проверка
        доступности — проверка заняла бы секунды, а эндпоинт нужен для мониторинга.
        """
        return {"status": "ok", "service": "code-review",
                "default_provider": llm_provider.normalize_provider(config.LLM_PROVIDER),
                "providers": list(llm_provider.PROVIDERS),
                "mcp_tools": [code_review.TOOL_PR_DIFF, code_review.TOOL_CHANGED_FILES],
                "index_strategy": rag_mode.RAG_DEFAULT_STRATEGY,
                "max_diff_lines": code_review.MAX_DIFF_LINES,
                "report_path": code_review.REPORT_PATH}

    def close(self) -> None:
        """Закрывает СВОИ соединения: dev-сервер и клиент GitHub (подменённые не трогает)."""
        with self._lock:
            client = self._server
            self._server = None
            github = self._github_client if self._github_owned else None
            if self._github_owned:
                self._github_client = None
        if client is not None:
            client.close()
        if github is not None:
            github.close()

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        """Миллисекунды от отметки ``started`` — время ревью в ответе и в отчёте."""
        return int((time.perf_counter() - started) * 1000)


def _use(tool: str, ok: bool, duration_ms: int, error: str) -> dict:
    """Запись журнала вызовов MCP: та же форма, что у ассистента разработчика."""
    return {"tool": tool, "ok": bool(ok), "duration_ms": int(duration_ms),
            "error": str(error or "")}


def _sources(hits: list) -> list:
    """Ссылки на использованные фрагменты без дублей по ``chunk_id``.

    Документация и код изменённых файлов могут вернуть один и тот же чанк: в списке
    источников он должен стоять один раз, иначе отчёт покажет дубль и завышенное
    число «источников RAG».
    """
    sources: list = []
    seen: set = set()
    for hit in hits:
        key = str(hit.get("chunk_id") or "")
        if key in seen:
            continue
        seen.add(key)
        sources.append(rag_records.source(hit))
    return sources


#: Служба процесса: соединение с dev-сервером одно на процесс, как у остальных служб.
_service: Optional[CodeReviewService] = None
_service_lock = threading.Lock()


def get_code_review_service() -> CodeReviewService:
    """Служба ревью процесса (точка подмены: ``main.get_code_review_service``)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = CodeReviewService()
        return _service
