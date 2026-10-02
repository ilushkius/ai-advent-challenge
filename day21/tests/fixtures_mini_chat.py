"""Фикстуры мини-чата дня 25: служба без индекса, заглушки модели, временная БД.

Тот же приём, что у ``fixtures_rag.py``: файл импортируется в ``tests/conftest.py``,
поэтому pytest видит фикстуры как объявленные там. Отбор подменён
(``FakeRagService``), а клиенты — настоящие ``LLMClient`` на заглушке: журнал расходов
пишется во временную базу, сеть не задействована вовсе, и тесты идут офлайн.
"""
import pytest

from backend.services.llm_client import LLMClient
from backend.services.mini_chat_memory import MINI_CHAT_AGENT_ID
from backend.services.mini_chat_service import MiniChatService
from backend.services.rag_errors import RAGUpstreamError
from backend.storage.llm_usage_store import LLMUsageStore

from mini_chat_fakes import (HIT_WEAK, FakeRagService, FakeRetrieval,
                             MiniChatStubClient, make_stages)


def make_client(stub: MiniChatStubClient, session_factory) -> LLMClient:
    """Обёртка вызова LLM на заглушке и временном журнале расходов."""
    return LLMClient(agent_id=MINI_CHAT_AGENT_ID, client_factory=lambda: stub,
                     store=LLMUsageStore(session_factory=session_factory))


def build_service(stub: MiniChatStubClient, session_factory, retrieval=None) -> MiniChatService:
    """Служба мини-чата на заглушке: единая сборка для фикстур и отдельных тестов."""
    return MiniChatService(
        rag_service=FakeRagService(retrieval),
        session_factory=session_factory,
        llm_client=make_client(stub, session_factory),
        memory_client=make_client(stub, session_factory),
    )


@pytest.fixture
def mini_chat_stub():
    """Заглушка клиента DeepSeek: ответ по корпусу и JSON памяти задачи."""
    return MiniChatStubClient()


@pytest.fixture
def mini_chat_service(session_factory, mini_chat_stub):
    """Служба мини-чата: готовые ступени отбора, заглушка модели, временная база."""
    return build_service(mini_chat_stub, session_factory)


@pytest.fixture
def mini_chat_weak_service(session_factory, mini_chat_stub):
    """Служба на слабой выдаче: лучший фрагмент ниже порога — режим «не знаю»."""
    retrieval = FakeRetrieval(stages=make_stages(hits=[HIT_WEAK],
                                                candidates=[HIT_WEAK]))
    return build_service(mini_chat_stub, session_factory, retrieval)


@pytest.fixture
def mini_chat_broken_service(session_factory):
    """Служба на падающем клиенте: после повторов ответ уходит в режим «error»."""
    stub = MiniChatStubClient(error=RAGUpstreamError("DeepSeek недоступен"),
                              error_times=None)
    return build_service(stub, session_factory)
