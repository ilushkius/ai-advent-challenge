"""Фейки мини-чата дня 25: отбор без индекса, клиент DeepSeek без сети.

Мини-чат отличается от режима RAG только сборкой промпта и памятью задачи, поэтому
отбор подменяется целиком: ``FakeRetrieval`` возвращает заранее собранные ступени
``RAGStages`` и пишет вызовы, ``FakeRagService`` отдаёт его через свойство
``retrieval`` — так проверяется связка «вопрос → контекст + память + история → ответ»
без настоящего индекса.

Заглушка клиента отвечает по вопросу вызова: на вопрос извлекателя памяти — строка
``MEMORY_JSON``, на всё остальное — ``GROUNDED_REPLY`` из ``rag_fakes``. Один объект
обслуживает и клиент ответа, и клиент извлечения, поэтому журнал ``calls`` показывает
и вызовы ответа, и вызовы извлечения: тесты различают их по вопросу.
"""
from types import SimpleNamespace

from rag_fakes import GROUNDED_REPLY

from backend.services.mini_chat_memory import MINI_CHAT_EXTRACT_QUESTION
from backend.services.rag_retrieval import RAGStages

#: Ответ извлекателя памяти: ровно тот JSON, который описан в системном промпте.
MEMORY_JSON = (
    '{"goal": "Настроить RAG-поиск по документации FastAPI", '
    '"terms": ["CHARS_PER_PAGE"], '
    '"constraints": ["не менять основной app.py"], '
    '"clarifications": ["нужны источники в каждом ответе"]}'
)

#: Фрагмент в форме выдачи поиска: балл выше порога релевантности (0.6).
HIT = {
    "chunk_id": "c1",
    "source": "rules.md",
    "title": "Правила корпуса",
    "section": "Подсчёт",
    "strategy": "rag_corpus_structural",
    "score": 0.91,
    "vector_score": 0.91,
    "lexical_score": 1.0,
    "rerank_score": None,
    "content": ("CHARS_PER_PAGE равен 1800 символов на страницу. "
                "Корпус собран из документации проекта."),
}

#: Тот же фрагмент с просевшим баллом: контекст слабее порога.
HIT_WEAK = {**HIT, "score": 0.2, "vector_score": 0.2}


def make_stages(hits=None, candidates=None, question="Чему равен CHARS_PER_PAGE?"):
    """Ступени отбора без обращения к индексу: те же поля, что у настоящего отбора."""
    hit_list = [HIT] if hits is None else list(hits)
    candidate_list = hit_list if candidates is None else list(candidates)
    return RAGStages(
        question=question,
        query="",
        mode="baseline",
        strategy="rag_corpus_structural",
        limit=5,
        candidate_limit=30,
        min_score=None,
        score_field="score",
        candidates=candidate_list,
        hits=hit_list,
        reranked=False,
        rerank_warning="",
        rewrite_warning="",
    )


class FakeRetrieval:
    """Отбор без индекса и без модели: пишет вызовы, возвращает готовые ступени."""

    def __init__(self, stages=None, error=None) -> None:
        self.stages = make_stages() if stages is None else stages
        self.error = error
        self.calls: list = []

    def run(self, question, *, query=None, top_k=None, strategy=None, mode=None,
            min_score=None, top_k_candidates=None, rerank=None,
            rewrite_warning=""):
        """Запоминает аргументы отбора и отдаёт ступени (или бросает заданную ошибку)."""
        self.calls.append({
            "question": question, "query": query, "top_k": top_k,
            "strategy": strategy, "mode": mode, "min_score": min_score,
            "top_k_candidates": top_k_candidates, "rerank": rerank,
            "rewrite_warning": rewrite_warning,
        })
        if self.error is not None:
            raise self.error
        return self.stages


class FakeRagService:
    """Служба RAG без индекса: мини-чату нужен только вход в отбор."""

    def __init__(self, retrieval=None) -> None:
        self._retrieval = FakeRetrieval() if retrieval is None else retrieval

    @property
    def retrieval(self):
        """Тот же публичный вход, что у ``RAGService``: отбор фрагментов."""
        return self._retrieval


class MiniChatStubCompletions:
    """`chat.completions`: пишет вызов, падает заданное число раз, отвечает текстом."""

    def __init__(self, owner: "MiniChatStubClient") -> None:
        self._owner = owner

    def create(self, model, messages, temperature=None, max_tokens=None):
        owner = self._owner
        owner.calls.append({"model": model, "messages": messages,
                            "temperature": temperature, "max_tokens": max_tokens})
        # error_times=None — падать всегда: тогда не выходит ни ответ, ни извлечение.
        if owner.error is not None and (owner.error_times is None
                                        or len(owner.calls) <= owner.error_times):
            raise owner.error
        content = owner.memory if MINI_CHAT_EXTRACT_QUESTION in messages[-1]["content"] \
            else owner.answer
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                     finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                                  prompt_cache_hit_tokens=0,
                                  prompt_cache_miss_tokens=100),
        )


class MiniChatStubClient:
    """Клиент DeepSeek для тестов мини-чата: те же четыре параметра, что у SDK.

    ``answer`` — текст ответа по корпусу, ``memory`` — текст ответа извлекателя
    памяти. Один объект годится и для клиента ответа, и для клиента извлечения.
    """

    def __init__(self, answer=GROUNDED_REPLY, memory=MEMORY_JSON, error=None,
                 error_times=None) -> None:
        self.calls: list = []
        self.answer = answer
        self.memory = memory
        self.error = error
        self.error_times = error_times
        self.chat = SimpleNamespace(completions=MiniChatStubCompletions(self))

    def answer_calls(self) -> list:
        """Вызовы ответа: те, где вопрос извлекателя памяти не приходил."""
        return [call for call in self.calls
                if MINI_CHAT_EXTRACT_QUESTION not in call["messages"][-1]["content"]]

    def memory_calls(self) -> list:
        """Вызовы извлечения памяти: их отличает вопрос извлекателя."""
        return [call for call in self.calls
                if MINI_CHAT_EXTRACT_QUESTION in call["messages"][-1]["content"]]


class BrokenPayloadClient(MiniChatStubClient):
    """Модель отвечает не JSON: память задачи не обновляется, предыдущее сохраняется."""

    def __init__(self, answer=GROUNDED_REPLY, error=None, error_times=None) -> None:
        super().__init__(answer=answer, memory="не json", error=error,
                         error_times=error_times)
