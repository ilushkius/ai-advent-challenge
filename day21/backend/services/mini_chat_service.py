"""Мини-чат дня 25: RAG-контекст, память задачи и история диалога в одном ответе.

Почему отдельный модуль, а не режим ``RAGService``: ``rag_query`` принимает один
вопрос, а мини-чату нужно ещё два входа — память задачи (четыре ключа рабочей
памяти дня 11) и скользящее окно диалога, — и на сбое модели задание требует режим
``error``, тогда как ``rag_query`` уходит в откат ``mode="rag"``. Поэтому промпт
собирается здесь, а отбор фрагментов берётся у дней 22–24 как есть, через публичное
свойство ``rag_service.retrieval``: ни один файл дней 21–24 при этом не правится.

Память мини-чата лежит в той же базе ``agents.db``: краткосрочные реплики и рабочая
память держат внешний ключ на ``agents.agent_id``, поэтому у служебного агента
``mini-chat`` есть ровно одна строка-якорь (живого ``Agent`` мини-чат не создаёт).
``session_id`` — из дня 11, ``task_id = "mc-" + session_id``: связь детерминированная,
и перезапуск бэкенда не теряет память задачи.

Правила памяти задачи (четыре ключа, JSON-значения, полная замена) живут в
``mini_chat_memory``: здесь отбор фрагментов, промпт и вызов модели.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger
from shared.token_counter import count_tokens

from ..agents.memory import MemoryManager, new_session_id
from ..core import config
from ..domain import llm_provider, local_tuning, rag_mode, rag_quotes
from ..domain.local_tuning import TuningProfile
from ..storage.database import AgentRecord, SessionLocal
from . import llm_factory, mini_chat_memory, rag_llm, rag_records
from .mini_chat_memory import MINI_CHAT_AGENT_ID
from .rag_errors import RAGUpstreamError
from .rag_retrieval import RAGStages
from .rag_service import get_rag_service

logger = get_logger(__name__)

#: Префикс ``task_id`` рабочей памяти: ``mc-<session_id>`` переживает перезапуск бэкенда.
MINI_CHAT_TASK_PREFIX = "mc-"
#: Скользящее окно диалога (день 10): сколько последних реплик идёт в промпт ответа.
MINI_CHAT_HISTORY_MESSAGES = config.DEFAULT_WINDOW_SIZE
#: Сколько реплик видит извлекатель памяти: столько же, сколько ответ.
MINI_CHAT_MEMORY_MESSAGES = config.DEFAULT_WINDOW_SIZE
#: Предел ожидания извлечения памяти: извлечение — вспомогательный шаг, ответ важнее.
MINI_CHAT_EXTRACT_TIMEOUT = 5.0

#: Режимы ответа: ``error`` — повторный сбой модели; остальные — из дня 24.
MINI_CHAT_MODE_ERROR = "error"
MINI_CHAT_MODE_RAG = rag_quotes.RAG_MODE_RAG
MINI_CHAT_MODE_DONT_KNOW = rag_quotes.RAG_MODE_DONT_KNOW

#: Системный промпт тот же, что у RAG: стабильный префикс и те же правила цитирования.
MINI_CHAT_SYSTEM_PROMPT = rag_mode.RAG_SYSTEM_PROMPT

MINI_CHAT_ERROR_ANSWER = "Не удалось получить ответ: {error}. Попробуйте ещё раз."
MINI_CHAT_MEMORY_STALE_WARNING = ("Память задачи не обновлена: модель не ответила за "
                                  "{timeout} с, показано предыдущее состояние.")

__all__ = ["MINI_CHAT_AGENT_ID", "MiniChatService", "MiniChatSessionError",
           "get_mini_chat_service", "make_mini_chat_client"]


def make_mini_chat_client(timeout: float = config.REQUEST_TIMEOUT):
    """Клиент DeepSeek мини-чата: у извлечения памяти свой предел ожидания."""
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day21/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, timeout)


class MiniChatSessionError(ValueError):
    """Сессия мини-чата не найдена: роутер переводит её в HTTP 404."""


class MiniChatService:
    """Мини-чат: отбор фрагментов дня 22–24 плюс память задачи и история диалога."""

    def __init__(self, *, rag_service=None, memory: Optional[MemoryManager] = None,
                 session_factory=None, llm_client: Optional[Any] = None,
                 memory_client: Optional[Any] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._rag_service = rag_service
        self._memory = memory
        self._session_factory = session_factory
        self._llm_client = llm_client
        self._llm_clients: Dict[str, Any] = {}
        self._memory_client = memory_client
        self._memory_clients: Dict[str, Any] = {}
        self._sleep = sleep
        self._sessions: Dict[str, dict] = {}
        self._lock = threading.Lock()

    # ---------- зависимости ----------
    @property
    def session_factory(self):
        """Фабрика сессий: та же, что у памяти и строки агента (одна база)."""
        if self._session_factory is None:
            self._session_factory = SessionLocal
        return self._session_factory

    @property
    def memory(self) -> MemoryManager:
        """Менеджер памяти дня 11 на фабрике сессий службы."""
        if self._memory is None:
            self._memory = MemoryManager(session_factory=self.session_factory)
        return self._memory

    @property
    def rag_service(self):
        """Служба RAG: источник отбора фрагментов (свойство ``retrieval``)."""
        if self._rag_service is None:
            self._rag_service = get_rag_service()
        return self._rag_service

    @property
    def llm_client(self) -> Any:
        """Клиент ответа: предел ожидания ``config.REQUEST_TIMEOUT``, повторы дня 22."""
        return self.llm_client_for(None)

    def llm_client_for(self, provider: Optional[str] = None,
                       profile: Optional[TuningProfile] = None) -> Any:
        """Клиент ответа: кэш службы по паре «провайдер + профиль» дня 29.

        Профиль не задан — берётся профиль по умолчанию локального провайдера.
        """
        return rag_llm.client_for(
            self._llm_clients, provider, local_tuning.profile_for(provider, profile),
            stub=self._llm_client, agent_id=MINI_CHAT_AGENT_ID,
            client_factory=make_mini_chat_client, session_factory=self.session_factory)

    @property
    def memory_client(self) -> Any:
        """Клиент извлечения памяти: свой предел ожидания и одна попытка."""
        return self.memory_client_for(None)

    def memory_client_for(self, provider: Optional[str] = None,
                          profile: Optional[TuningProfile] = None) -> Any:
        """Клиент извлечения памяти: предел 5 с у облака, общий у локальной модели.

        Профиль дня 29 — тот же, что у ответа; иначе Ollama перезагрузила бы веса.
        """
        name = llm_provider.resolve(provider)
        return rag_llm.client_for(
            self._memory_clients, provider,
            local_tuning.profile_for(provider, profile), stub=self._memory_client,
            agent_id=MINI_CHAT_AGENT_ID, timeout=self.memory_timeout(name),
            session_factory=self.session_factory,
            client_factory=lambda: make_mini_chat_client(MINI_CHAT_EXTRACT_TIMEOUT))

    @staticmethod
    def memory_timeout(provider: str) -> float:
        """Предел ожидания извлечения памяти: 5 с у облака, общий — у Ollama."""
        return (config.LOCAL_LLM_TIMEOUT if provider == llm_provider.PROVIDER_LOCAL
                else MINI_CHAT_EXTRACT_TIMEOUT)

    # ---------- сессии ----------
    def _ensure_agent(self, session_id: str, task_id: str, user_id: str) -> None:
        """Строка-якорь служебного агента: только внешний ключ памяти, не ``Agent``."""
        with self.session_factory() as session:
            if session.get(AgentRecord, MINI_CHAT_AGENT_ID) is not None:
                return
            session.add(AgentRecord(
                agent_id=MINI_CHAT_AGENT_ID,
                name="Мини-чат: RAG и память задачи",
                model=config.MODEL_CHAT,
                temperature=config.DEFAULT_TEMPERATURE,
                system_prompt=config.DEFAULT_SYSTEM_PROMPT,
                max_tokens=config.DEFAULT_MAX_TOKENS,
                created_at=datetime.now(timezone.utc),
                current_session_id=session_id,
                current_task_id=task_id,
                user_id=user_id,
            ))
            session.commit()

    def start_session(self, user_id: Optional[str] = None) -> dict:
        """Новая сессия мини-чата: ``session_id`` дня 11 и связанный ``task_id``."""
        session_id = new_session_id()
        task_id = MINI_CHAT_TASK_PREFIX + session_id
        user_id = str(user_id or config.DEFAULT_USER_ID)
        self._ensure_agent(session_id, task_id, user_id)
        entry = {"session_id": session_id, "task_id": task_id,
                 "user_id": user_id,
                 "created_at": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            self._sessions[session_id] = entry
        return dict(entry)

    def _known_session(self, session_id: str) -> Optional[dict]:
        """Сессия из реестра или восстановленная по репликам (перезапуск бэкенда)."""
        if not session_id:
            return None
        with self._lock:
            entry = self._sessions.get(session_id)
        if entry is not None:
            return entry
        if self.memory.count_short_term(MINI_CHAT_AGENT_ID, session_id) <= 0:
            return None
        entry = {"session_id": session_id,
                 "task_id": MINI_CHAT_TASK_PREFIX + session_id,
                 "user_id": config.DEFAULT_USER_ID, "created_at": ""}
        with self._lock:
            return self._sessions.setdefault(session_id, entry)

    def _require_session(self, session_id: str) -> dict:
        """Сессия или ``MiniChatSessionError`` (роутер переводит в 404)."""
        entry = self._known_session(session_id)
        if entry is None:
            raise MiniChatSessionError(f"Сессия не найдена: {session_id!r}")
        return entry

    def end_session(self, session_id: str) -> dict:
        """Закрывает сессию: реплики удаляются, память задачи — нет.

        Удаления записей рабочей памяти в API дня 11 нет, поэтому четыре ключа
        остаются до следующего сообщения; повторный вызов идемпотентен.
        """
        with self._lock:
            found = self._sessions.pop(session_id, None)
        deleted = self.memory.clear_short_term(MINI_CHAT_AGENT_ID, session_id)
        task_id = (found or {}).get("task_id") or (MINI_CHAT_TASK_PREFIX + session_id)
        return {"session_id": session_id, "task_id": task_id, "deleted": deleted}

    # ---------- ответ ----------
    def chat(self, session_id: str, user_message: str,
             top_k: Optional[int] = None,
             provider: Optional[str] = None) -> dict:
        """Ответ по корпусу с источниками, памятью задачи и обновлением памяти.

        ``provider`` выбирает, кто отвечает и обновляет память (``deepseek`` или
        ``local``); он же попадает в запись ответа.
        """
        entry = self._require_session(session_id)
        text = str(user_message or "").strip()
        if not text:
            raise ValueError("Введите текст сообщения")
        provider_name = llm_provider.resolve(provider)
        profile = local_tuning.active(provider_name)
        history = self.memory.get_short_term(
            MINI_CHAT_AGENT_ID, session_id, limit=MINI_CHAT_HISTORY_MESSAGES)
        self.memory.add_short_term(MINI_CHAT_AGENT_ID, session_id, "user", text)
        started = time.perf_counter()
        stages = self.rag_service.retrieval.run(
            text, query="", top_k=top_k, mode=None, rerank=False)
        elapsed = self._elapsed_ms(started)
        if not stages.hits or rag_quotes.is_weak(stages.candidates):
            record = rag_records.dont_know(text, stages, elapsed)
        else:
            # Клиент выбирается по ИСХОДНОМУ аргументу: ``None`` — значит «как у
            # службы» (подменённый клиент тестов или провайдер конфига), а не
            # обязательно облако.
            record = self._answer_record(entry, history, stages, text, elapsed,
                                         self.llm_client_for(provider, profile), profile)
        self.memory.add_short_term(
            MINI_CHAT_AGENT_ID, session_id, "assistant", record["answer"])
        dialog = self.memory.get_short_term(
            MINI_CHAT_AGENT_ID, session_id, limit=MINI_CHAT_MEMORY_MESSAGES)
        updated = self.update_task_memory(session_id, dialog, provider=provider)
        record.update({
            "session_id": session_id, "task_id": entry["task_id"], "question": text,
            "provider": provider_name,
            "duration_ms": self._elapsed_ms(started),
            "task_memory": self.get_task_memory(session_id),
            "memory_updated": updated,
            "memory_warning": ("" if updated else
                               MINI_CHAT_MEMORY_STALE_WARNING.format(
                                   timeout=self.memory_timeout(provider_name))),
        })
        return record

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        """Миллисекунды от метки времени: у поля ``duration_ms`` целочисленная шкала."""
        return int((time.perf_counter() - started) * 1000)

    def _answer_record(self, entry: dict, history: List[dict], stages: RAGStages,
                       text: str, elapsed: int, client: Any,
                       profile: Optional[TuningProfile] = None) -> dict:
        """Ответ по контексту: промпт с памятью и историей, повторы дня 22, режим ``error``."""
        items = rag_mode.fit_context(rag_mode.render_context(stages.hits))
        context = self._prompt_context(entry, history, items)
        try:
            result = rag_llm.answer(
                self._sleep, client,
                system=local_tuning.prompt_for(profile, MINI_CHAT_SYSTEM_PROMPT),
                context=context, question=text, agent_id=MINI_CHAT_AGENT_ID,
                profile=profile)
        except RAGUpstreamError as exc:
            return self._error_record(text, exc, elapsed)
        answer = rag_llm.response_text(result)
        record = {
            "mode": MINI_CHAT_MODE_RAG,
            "answer": answer,
            "sources": [rag_records.source(hit) for hit in stages.hits],
            "grounding": rag_mode.grounding_verdict(rag_mode.grounding_share(
                answer, [item["text"] for item in items])),
            "chunks_used": len(items),
            "context_tokens": count_tokens(context),
            "tokens": rag_llm.usage_dict(result),
            "fallback": False,
            "warning": "",
        }
        record.update(rag_quotes.citation_block(answer, items))
        record.update(rag_records.selection(stages))
        return record

    def _error_record(self, question: str, error: Exception, duration_ms: int) -> dict:
        """Запись режима ``error``: повторный сбой модели, источников нет."""
        record = {
            "mode": MINI_CHAT_MODE_ERROR,
            "answer": MINI_CHAT_ERROR_ANSWER.format(error=error),
            "sources": [], "quotes": [], "quotes_verified": False,
            "confidence": rag_quotes.CONFIDENCE_NONE, "grounding": "",
            "fallback": True, "warning": str(error), "chunks_used": 0,
            "context_tokens": 0, "tokens": None, "duration_ms": duration_ms,
        }
        record.update(rag_records.selection(None))
        return record

    # ---------- промпт ----------
    def _prompt_context(self, entry: dict, history: List[dict],
                        items: List[dict]) -> str:
        """Контекст запроса: RAG-блок → память задачи → история диалога.

        Порядок держит стабильный префикс (системный промпт плюс RAG-блок) в кэше
        контекста DeepSeek, а напоминание о цели ставит ближе к вопросу.
        """
        blocks = [rag_mode.render_rag_block(items),
                  mini_chat_memory.memory_block(self.memory, entry["task_id"]),
                  mini_chat_memory.dialog_block(history)]
        return "\n\n".join(block for block in blocks if block)

    # ---------- память задачи ----------
    def get_task_memory(self, session_id: str) -> dict:
        """Память задачи сессии: четыре поля, счётчик реплик и метка обновления."""
        entry = self._require_session(session_id)
        return mini_chat_memory.task_memory(
            self.memory, session_id, entry["task_id"])

    def get_history(self, session_id: str, limit: Optional[int] = None) -> dict:
        """История диалога сессии: роль, текст и время каждой реплики."""
        entry = self._require_session(session_id)
        rows = self.memory.get_short_term(
            MINI_CHAT_AGENT_ID, session_id, limit=limit)
        messages = []
        for row in rows:
            created = row.get("created_at")
            messages.append({
                "role": row["role"], "content": row["content"],
                "created_at": (created.isoformat()
                               if hasattr(created, "isoformat") else None),
            })
        return {"session_id": session_id, "task_id": entry["task_id"],
                "messages": messages}

    def extract_task_memory(self, dialog_history: List[dict],
                            provider: Optional[str] = None) -> Optional[dict]:
        """Память задачи из диалога: ``None`` — не удалось, предыдущее сохраняется."""
        return mini_chat_memory.extract_payload(self.memory_client_for(provider),
                                                dialog_history)

    def update_task_memory(self, session_id: str,
                           dialog_history: Optional[List[dict]] = None,
                           provider: Optional[str] = None) -> bool:
        """Переписывает четыре ключа памяти задачи целиком; ``False`` — не удалось."""
        entry = self._require_session(session_id)
        dialog = (self.memory.get_short_term(MINI_CHAT_AGENT_ID, session_id)
                  if dialog_history is None else dialog_history)
        payload = self.extract_task_memory(dialog, provider=provider)
        if payload is None:
            return False
        mini_chat_memory.store_payload(self.memory, entry["task_id"], payload)
        return True


#: Служба процесса: одна на процесс, как у остальных служб дня.
_service: Optional[MiniChatService] = None
_service_lock = threading.Lock()


def get_mini_chat_service() -> MiniChatService:
    """Служба мини-чата процесса (единственный инстанс)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = MiniChatService()
    return _service
