"""Тесты терпимости обвязки RAG к словарю локального клиента (день 26).

``rag_llm`` — единственное место, где ответ модели превращается в текст и в расход.
Облако отдаёт ``LLMCallResult``, локальная модель — словарь, поэтому проверяется,
что оба вида читаются одинаково: иначе пришлось бы дублировать разбор формы ответа
и в ``RAGService``, и в ``MiniChatService``.
"""
from backend.services import rag_llm
from backend.services.local_llm_client import LocalLLMClient

LOCAL_RESULT = {
    "provider": "local",
    "model": "qwen2.5-coder:14b",
    "answer": "  Ответ локальной модели  ",
    "duration_ms": 1234,
    "tokens": {
        "model": "qwen2.5-coder:14b", "prompt_tokens": 512,
        "completion_tokens": 64, "cache_hit_tokens": 0,
        "cache_miss_tokens": 512, "cache_hit_percent": 0.0, "cost_estimate": 0.0,
    },
}


def test_response_text_reads_local_answer():
    """Текст ответа: строка без внешних пробелов, как и у облачного клиента."""
    assert rag_llm.response_text(LOCAL_RESULT) == "Ответ локальной модели"


def test_response_text_tolerates_missing_answer():
    """Пустой или отсутствующий ответ — пустая строка, а не исключение."""
    assert rag_llm.response_text({"tokens": {}}) == ""
    assert rag_llm.response_text({"answer": None}) == ""


def test_usage_dict_returns_local_tokens_without_extra_keys():
    """Расход: из словаря берётся только блок токенов — без ``provider`` и ``answer``."""
    usage = rag_llm.usage_dict(LOCAL_RESULT)

    assert usage == LOCAL_RESULT["tokens"]
    assert usage is not LOCAL_RESULT["tokens"]   # копия: запись не портит ответ
    assert rag_llm.usage_dict({"provider": "local"}) is None


def test_completion_tokens_reads_both_shapes():
    """Токены ответа: у словаря — из ``tokens``, у объекта — атрибутом."""
    assert rag_llm.completion_tokens(LOCAL_RESULT) == 64
    assert rag_llm.completion_tokens({"tokens": {}}) == 0
    assert rag_llm.completion_tokens(None) == 0


def test_client_answer_matches_helpers_shape():
    """Форма ответа ``LocalLLMClient`` читается теми же помощниками: стык не разъедется."""
    client = LocalLLMClient(post=lambda url, json=None, timeout=None: FakeResponse())

    result = client.generate("Вопрос")

    assert rag_llm.response_text(result) == "Ответ Ollama"
    assert rag_llm.completion_tokens(result) == 5
    assert rag_llm.usage_dict(result)["prompt_tokens"] == 11


class FakeResponse:
    """Ответ фейкового ``requests.post``: тело как у Ollama."""

    status_code = 200

    def json(self) -> dict:
        """Тело с сообщением и счётчиками токенов."""
        return {"model": "stub:1b", "message": {"content": "Ответ Ollama"},
                "prompt_eval_count": 11, "eval_count": 5}
