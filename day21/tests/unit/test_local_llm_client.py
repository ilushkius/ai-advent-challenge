"""Тесты клиента локальной модели (день 26): HTTP к Ollama без сети.

``requests.post`` подменяется фейком: проверяется ровно то, что уходит в Ollama
(адрес ``/api/chat``, модель, ``stream=false``, системное сообщение отдельным
элементом, предел ответа по типу задачи) и что возвращается наружу (форма словаря,
которую читают ``rag_llm.response_text``/``usage_dict``). Негативные случаи —
недоступная Ollama, HTTP-ошибка, не-JSON и пустой ответ: каждый обязан стать
``LocalLLMError``, а не тихим пустым ответом.
"""
import json

import pytest
import requests

from backend.core import config
from backend.services import local_llm_client
from backend.services.local_llm_client import LocalLLMClient, LocalLLMError

URL = "http://localhost:11434/api/chat"


class FakeResponse:
    """Ответ ``requests.post``: тело в виде JSON или текста плюс статус."""

    def __init__(self, body, status_code=200, raw=None) -> None:
        self.status_code = status_code
        self._body = body
        self._raw = raw

    def json(self):
        """Разобранное тело; ``raw`` подменяет его (не-JSON — ошибка разбора)."""
        if self._raw is not None:
            raise ValueError(self._raw)
        return self._body

    @property
    def text(self):
        """Тело как текст — попадает в сообщение об ошибке статуса."""
        return "" if self._body is None else json.dumps(self._body, ensure_ascii=False)


def ollama_body(content="Ответ модели", model="qwen2.5-coder:14b",
                prompt_eval_count=42, eval_count=7) -> dict:
    """Тело ответа Ollama: сообщение и счётчики токенов."""
    return {"model": model, "message": {"role": "assistant", "content": content},
            "prompt_eval_count": prompt_eval_count, "eval_count": eval_count}


def make_client(response, **kwargs) -> tuple[LocalLLMClient, list]:
    """Клиент на фейковом ``post``: возвращает клиента и список вызовов."""
    calls: list = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": json, "timeout": timeout})
        return response

    return LocalLLMClient(post=fake_post, **kwargs), calls


def test_generate_with_context_posts_chat_request():
    """Вызов RAG: системное сообщение отдельно, контекст и вопрос — одним блоком."""
    client, calls = make_client(FakeResponse(ollama_body()))

    result = client.generate_with_context(system="Ты — ассистент", context="К",
                                          question="В", task_type="code")

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == URL
    assert call["payload"]["model"] == config.LOCAL_LLM_MODEL
    assert call["payload"]["stream"] is False
    assert call["timeout"] == config.LOCAL_LLM_TIMEOUT
    messages = call["payload"]["messages"]
    assert messages[0] == {"role": "system", "content": "Ты — ассистент"}
    assert messages[-1]["role"] == "user" and "К\n\nВ" in messages[-1]["content"]
    assert call["payload"]["options"]["num_predict"] == \
        config.LLM_TASK_MAX_TOKENS["code"]
    assert result["provider"] == "local"
    assert result["answer"] == "Ответ модели"


def test_generate_with_context_without_context_asks_question_only():
    """Пустой блок контекста не оставляет лишних переводов строк в сообщении."""
    client, calls = make_client(FakeResponse(ollama_body()))

    client.generate_with_context(system="", context="  ", question="  Вопрос?  ")

    messages = calls[0]["payload"]["messages"]
    assert [item["role"] for item in messages] == ["user"]
    assert messages[0]["content"] == "Вопрос?"
    assert calls[0]["payload"]["options"]["temperature"] == config.DEFAULT_TEMPERATURE


def test_result_shape_feeds_rag_helpers():
    """Словарь ответа: токены Ollama, нулевые кэш и цена, замер времени."""
    client, _calls = make_client(FakeResponse(ollama_body(
        prompt_eval_count=120, eval_count=30, model="qwen2.5-coder:7b")))

    result = client.generate("2+2?")

    assert result["model"] == "qwen2.5-coder:7b"
    assert result["answer"] == "Ответ модели"
    assert result["duration_ms"] >= 0
    tokens = result["tokens"]
    assert tokens["prompt_tokens"] == 120 and tokens["completion_tokens"] == 30
    assert tokens["cache_hit_tokens"] == 0
    assert tokens["cache_miss_tokens"] == 120
    assert tokens["cache_hit_percent"] == 0.0 and tokens["cost_estimate"] == 0.0


def test_generate_uses_single_user_message_and_limit():
    """Демо-запрос: одно пользовательское сообщение и явный предел ответа."""
    client, calls = make_client(FakeResponse(ollama_body()))

    client.generate("Напиши код", max_tokens=800)

    assert [item["role"] for item in calls[0]["payload"]["messages"]] == ["user"]
    assert calls[0]["payload"]["options"]["num_predict"] == 800


def test_generate_without_limit_uses_default_max_response():
    """Без типа задачи и предела берётся общий предел длины ответа дня 21."""
    client, calls = make_client(FakeResponse(ollama_body()))

    client.generate("Вопрос")

    assert calls[0]["payload"]["options"]["num_predict"] == \
        config.LLM_MAX_RESPONSE_TOKENS


def test_unavailable_ollama_raises_with_hint():
    """Недоступная Ollama: понятный текст с адресом и подсказкой про `ollama serve`."""
    def failing_post(url, json=None, timeout=None):
        raise requests.ConnectionError("connection refused")

    client = LocalLLMClient(post=failing_post)

    with pytest.raises(LocalLLMError) as exc:
        client.generate("Вопрос")

    assert config.LOCAL_LLM_URL in str(exc.value)
    assert "ollama serve" in str(exc.value)


def test_http_error_status_raises():
    """HTTP-статус не 200: в текст попадают код и тело ответа."""
    client, _calls = make_client(FakeResponse({"error": "model not found"},
                                              status_code=404))

    with pytest.raises(LocalLLMError) as exc:
        client.generate("Вопрос")

    assert "404" in str(exc.value) and "model not found" in str(exc.value)


def test_broken_json_raises():
    """Не-JSON тело: ошибка разбора переводится в ``LocalLLMError``."""
    client, _calls = make_client(FakeResponse(None, raw="<html>заглушка</html>"))

    with pytest.raises(LocalLLMError):
        client.generate("Вопрос")


# ---------- оптимизация профиля (день 29) ----------
def test_context_window_goes_to_options_only_when_set():
    """Окно контекста задаёт профиль: без него Ollama берёт своё значение (день 26)."""
    default_client, default_calls = make_client(FakeResponse(ollama_body()))
    tuned_client, tuned_calls = make_client(FakeResponse(ollama_body()), num_ctx=8192)

    default_client.generate("Вопрос")
    tuned_client.generate("Вопрос")

    assert "num_ctx" not in default_calls[0]["payload"]["options"]
    assert tuned_calls[0]["payload"]["options"]["num_ctx"] == 8192


def test_speed_and_load_metrics_from_ollama_body():
    """Скорость генерации — по ``eval_duration``, прогрев — по ``load_duration``."""
    body = ollama_body(eval_count=40)
    body["eval_duration"] = 2_000_000_000
    body["load_duration"] = 3_500_000_000
    client, _calls = make_client(FakeResponse(body))

    tokens = client.generate("Вопрос")["tokens"]

    assert tokens["tokens_per_second"] == 20.0
    assert tokens["load_ms"] == 3500


def test_speed_falls_back_to_request_time(monkeypatch):
    """Нет ``eval_duration`` (другая сборка Ollama) — скорость по времени запроса."""
    stamps = iter([100.0, 102.5])
    monkeypatch.setattr(local_llm_client.time, "perf_counter", lambda: next(stamps))
    client, _calls = make_client(FakeResponse(ollama_body(eval_count=10)))

    result = client.generate("Вопрос")

    assert result["duration_ms"] == 2500
    assert result["tokens"]["tokens_per_second"] == 4.0
    assert result["tokens"]["load_ms"] == 0, "поля нет — прогрев считается нулевым"


def test_speed_of_empty_answer_is_zero():
    """Нет токенов вывода — скорость 0.0, а не деление на ноль."""
    body = ollama_body(eval_count=0)
    body["eval_duration"] = 1_000_000_000
    client, _calls = make_client(FakeResponse(body))

    assert client.generate("Вопрос")["tokens"]["tokens_per_second"] == 0.0


def test_context_window_is_positive_even_if_configured_with_zero():
    """Нулевое окно из окружения не уходит в Ollama: значение зажимается до единицы."""
    client, calls = make_client(FakeResponse(ollama_body()), num_ctx=0)

    client.generate("Вопрос")

    assert calls[0]["payload"]["options"]["num_ctx"] == 1


def test_empty_message_raises():
    """Пустой ответ модели — ошибка, а не пустая строка в отчёте."""
    client, _calls = make_client(FakeResponse({"message": {}}))

    with pytest.raises(LocalLLMError):
        client.generate("Вопрос")
