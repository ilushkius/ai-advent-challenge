"""Ассистент файлов (день 34): цель → план шагов → исполнение через MCP → отчёт.

Что делает служба. ``execute_goal`` берёт ЦЕЛЬ («найди все места, где используется
``IndexService``»), просит модель собрать план вызовов инструментов файлового сервера,
ПРОВЕРЯЕТ этот план правилами домена, исполняет шаги через MCP-сервер ``file_server``,
собирает diff изменённых файлов и отчитывается сводкой. Разбор плана, проверка путей,
вторая фаза ``$generate``, предполагаемый diff и вердикт — в домене
(``backend/domain/file_assistant*``); вызовы инструментов и журнал шагов —
в ``file_mcp`` и ``file_run``; здесь только контракт дня: вызовы модели, режим
``dry_run``, история запусков и запись в БД.

Почему свой клиент MCP, а не флот дня 20. Флот из ``mcp_servers.json`` — три сервера
проекта, и его состав закреплён разделом «🌐 Оркестрация». Ассистенту файлов нужен
четвёртый сервер (``file_server``), у которого нет ни флота, ни отчётов: он
подключается одним клиентом на процесс и закрывается при остановке бэкенда
(``api/lifespan.py``). Так же сделаны дни 31–33.

Почему dry_run не «почти правда». В этом режиме ``write_file`` и ``apply_patch`` не
вызываются вовсе, а diff считается по аргументам плана
(``file_assistant_report.presumed_diff``): обещание «файлы не меняются» должно
выполняться буквально, иначе режим бесполезен. Отсюда отдельный статус ``dry_run``
в истории: по нему видно, что прогон был репетицией.

Провайдер ответа. По умолчанию DeepSeek (``config.LLM_PROVIDER``), локальная Ollama —
второй провайдер переключателя дней 26–29. Путь к модели один для всего проекта
(``rag_llm.client_for``/``call_with_retry``/``answer``): повторы, профиль локальной
модели и журнал расходов у ассистента файлов те же, что у RAG и мини-чата. Новых типов
задач в ``config.LLM_TASK_MODELS`` не появляется: план шагов идёт как
``config.LLM_TASK_ORCHESTRATION`` (тот же случай, что у планировщика флота), генерация
текста правки — как ``config.LLM_TASK_CODE``.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger

from ..core import config
from ..domain import file_assistant, llm_provider
from ..domain import file_assistant_plan as plan_rules
from ..storage.file_assistant_store import FileAssistantRunNotFoundError, FileAssistantStore
from . import rag_llm
from .file_mcp import FileMCPCalls
from .file_run import FileRun
from .rag_errors import RAGUpstreamError

logger = get_logger(__name__)

__all__ = ["FileAssistantError", "FileAssistantService", "get_file_assistant_service",
           "make_file_assistant_client"]


def make_file_assistant_client():
    """Клиент DeepSeek службы: ключ резолвится в момент вызова (как у дней 31–33).

    Служба собирается на старте приложения, а ключ к моменту первого прогона может
    быть ещё не задан: ``.env`` правится без перезапуска.
    """
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day21/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)


class FileAssistantError(RuntimeError):
    """Сбой прогона ассистента файлов (роутер переводит в 500).

    Плана нет — показывать нечего, поэтому, в отличие от дней 31–33, здесь отказ
    приходит исключением, а не честным текстом в ответе: файлы при этом не тронуты.
    """


class FileAssistantService:
    """Прогон цели: план от модели, исполнение шагов через MCP, diff и отчёт."""

    def __init__(self, *, llm_client: Optional[Any] = None,
                 mcp_client: Optional[Any] = None,
                 mcp_target: str = file_assistant.FILE_SERVER_TARGET,
                 mcp_cwd: Optional[object] = None,
                 store: Optional[Any] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._llm_client = llm_client
        self._llm_clients: Dict[str, Any] = {}
        self._mcp = FileMCPCalls(target=mcp_target, cwd=mcp_cwd, client=mcp_client)
        #: Хранилище без состояния, как ``SchedulerStore``/``PipelineStore``: своего
        #: синглтона на процесс ему не нужно, поэтому оно создаётся сразу.
        self._store = store if store is not None else FileAssistantStore()
        self._sleep = sleep

    # ---------- зависимости ----------
    @property
    def mcp(self) -> FileMCPCalls:
        """Обвязка вызовов файлового сервера (одна на прогон и на процесс)."""
        return self._mcp

    @property
    def server(self) -> Any:
        """MCP-клиент файлового сервера: подменённый или подключённый один раз."""
        return self._mcp.server

    def llm_client_for(self, provider: Optional[str] = None) -> Any:
        """Клиент ответа провайдера; подменённый клиент важнее имени провайдера."""
        return rag_llm.client_for(
            self._llm_clients, None if self._llm_client is not None else provider, None,
            stub=self._llm_client, agent_id=file_assistant.AGENT_ID,
            client_factory=make_file_assistant_client)

    # ---------- контракт ----------
    def execute_goal(self, goal: str, provider: str = "deepseek",
                     dry_run: bool = False) -> dict:
        """Выполняет цель целиком: план, шаги, diff, сводка и запись истории.

        Пустая цель — ``ValueError`` (роутер отвечает 400), незнакомый провайдер —
        тоже ``ValueError``. Негодный план — ``PlanRejected`` (422 с проблемами и сырым
        ответом модели). Недоступная модель — ``FileAssistantError`` (500): без плана
        исполнять нечего, и запуск закрывается статусом ``failed``, а не остаётся
        висеть в ``running``.
        """
        text = file_assistant.normalize_goal(goal)
        if not text:
            raise ValueError(file_assistant.REASON_EMPTY_GOAL)
        name = llm_provider.resolve(provider)
        started = time.perf_counter()
        client = self.llm_client_for(provider)
        run_id = self._store.create_run(goal=text, status=file_assistant.STATUS_RUNNING,
                                       started_at=datetime.now(timezone.utc))["id"]
        try:
            plan = self._plan(text, client)
        except (RAGUpstreamError, file_assistant.PlanRejected) as exc:
            self._close_run(run_id)
            if isinstance(exc, RAGUpstreamError):
                raise FileAssistantError(
                    file_assistant.PLAN_FAILED_ANSWER.format(error=exc)) from exc
            raise
        outcome = FileRun(goal=text, plan=plan, client=client, mcp=self._mcp,
                          dry_run=dry_run, sleep=self._sleep).execute()
        status = self._status(outcome["failed"], dry_run)
        self._store.update_run(
            run_id, status=status, finished_at=datetime.now(timezone.utc),
            plan=outcome["plan"], steps=outcome["steps"],
            files_read=outcome["files_read"], files_modified=outcome["files_modified"],
            files_created=outcome["files_created"], diff=outcome["diff"])
        return {
            "run_id": run_id,
            "goal": text,
            "plan": outcome["plan"],
            "steps_executed": outcome["steps"],
            "files_read": outcome["files_read"],
            "files_modified": outcome["files_modified"],
            "files_created": outcome["files_created"],
            "diff": outcome["diff"],
            "summary": outcome["summary"],
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "provider": name,
            "status": status,
            "dry_run": bool(dry_run),
        }

    def history(self, limit: int = file_assistant.HISTORY_LIMIT) -> dict:
        """История запусков: свежие сверху (``diff`` в список не входит — он объёмный)."""
        runs = self._store.list_runs(limit)
        return {"count": len(runs), "runs": runs}

    def diff_of(self, run_id: int) -> dict:
        """Diff и файлы одного запуска; нет такого — ``FileAssistantRunNotFoundError``."""
        record = self._store.run(run_id)
        if record is None:
            raise FileAssistantRunNotFoundError(
                f"Запуск ассистента файлов {run_id} не найден")
        return {"run_id": record["id"], "status": record["status"],
                "goal": record["goal"], "diff": record["diff"],
                "files_read": record["files_read"],
                "files_modified": record["files_modified"],
                "files_created": record["files_created"],
                "started_at": record["started_at"],
                "finished_at": record["finished_at"]}

    # ---------- план ----------
    def _plan(self, goal: str, client: Any) -> list:
        """План шагов от модели: повтор с подсказкой, если ответ не разобран как JSON.

        Каталог инструментов уходит блоком контекста, а не в вопрос: он одинаков для
        всех целей, поэтому стоит в стабильном префиксе запроса и попадает в кэш
        контекста DeepSeek. Вторая попытка идёт с ``PLAN_RETRY_HINT``: модель, ответившая
        прозой, обычно справляется, когда её прямо просят вернуть JSON.
        """
        system, question = file_assistant.build_plan_prompt(goal)
        raw = ""
        for attempt in range(file_assistant.MAX_GENERATE_ATTEMPTS):
            result = rag_llm.call_with_retry(
                self._sleep, client.generate_with_context, system=system,
                context=file_assistant.catalog_text(), question=question,
                task_type=config.LLM_TASK_ORCHESTRATION,
                agent_id=file_assistant.AGENT_ID, temperature=0.0,
                max_tokens=config.ORCH_PLAN_MAX_TOKENS)
            raw = rag_llm.response_text(result)
            plan = plan_rules.parse_plan(raw)
            if plan is not None:
                return plan
            logger.warning("Ассистент файлов: план не разобран (попытка %d из %d)",
                           attempt + 1, file_assistant.MAX_GENERATE_ATTEMPTS)
            question = f"{question}\n\n{file_assistant.PLAN_RETRY_HINT}"
        raise file_assistant.PlanRejected([file_assistant.REASON_BAD_JSON], raw=raw)

    # ---------- вспомогательное ----------
    @staticmethod
    def _status(failed: bool, dry_run: bool) -> str:
        """Статус прогона: ``dry_run`` важнее сбоя — в этом режиме файлы не менялись."""
        if dry_run:
            return file_assistant.STATUS_DRY_RUN
        return file_assistant.STATUS_FAILED if failed else file_assistant.STATUS_COMPLETED

    def _close_run(self, run_id: int) -> None:
        """Закрывает запуск после сбоя ДО исполнения шагов (плана нет — и шагов нет)."""
        self._store.update_run(run_id, status=file_assistant.STATUS_FAILED,
                              finished_at=datetime.now(timezone.utc))

    # ---------- жизненный цикл ----------
    def close(self) -> None:
        """Закрывает СВОЁ соединение с файловым сервером (подменённое не трогает)."""
        self._mcp.close()


#: Служба процесса: соединение с файловым сервером одно на процесс, как у остальных.
_service: Optional[FileAssistantService] = None
_service_lock = threading.Lock()


def get_file_assistant_service() -> FileAssistantService:
    """Служба ассистента файлов процесса (точка подмены: ``main.get_file_assistant_service``)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = FileAssistantService()
        return _service
