"""Тесты клиента удалённой модели (день 30): OpenAI-форма и счётчик частоты без сети.

``requests.post``/``requests.get`` подменяются фейками (``post=``/``get=`` в
конструкторе), поэтому проверяется ровно то, что уходит в сервис через туннель:
эндпоинт ``/chat/completions``, модель, сообщения, ``stream=false``, температура,
``top_p``, предел ответа и расширение Ollama ``options.num_ctx``. Отдельно —
клиентский счётчик частоты: он обязан отказать на N+1-м запросе в минуту (по смыслу
429) и пропустить запрос после окна, а ``GET /models`` не должен тратить бюджет.
"""
import json

import pytest
import requests

from backend.core import config
from backend.services.remote_llm_client import (DEFAULT_TOP_P, RemoteLLMClient,
                                                RemoteLLMError, RemoteSettings,
                                                RateLimitExceeded)

BASE_URL = "https://xxxx.trycloudflare.com/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"
MODELS_URL = f"{BASE_URL}/models"


class FakeResponse:
    """Ответ ``requests``: тело JSON или текстом плюс статус."""

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
        """Тело текстом — попадает в сообщение об ошибке статуса."""
        return "" if self._body is None else json.dumps(self._body, ensure_ascii=False)


def chat_body(content="Париж", model="qwen2.5-coder:7b", prompt_tokens=12,
              completion_tokens=3) -> dict:
    """Тело ответа сервиса в OpenAI-форме: выбор, счётчики токенов, модель."""
    return {"model": model, "choices": [{"message": {"role": "assistant",
                                                     "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens,
                      "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens}}


def models_body(*names: str) -> dict:
    """Тело ``GET /models``: список доступных по туннелю моделей."""
    return {"object": "list", "data": [{"id": name} for name in names]}


def make_client(response, *, clock=None, rate_limit=10, max_context=4096,
                **kwargs) -> tuple[RemoteLLMClient, list, list]:
    """Клиент на фейковых ``post``/``get``: возвращает клиента и списки вызовов."""
    posts: list = []
    gets: list = []

    def fake_post(url, json=None, headers=None, timeout=None):
        posts.append({"url": url, "payload": json, "headers": headers,
                      "timeout": timeout})
        return response

    def fake_get(url, headers=None, timeout=None):
        gets.append({"url": url, "headers": headers, "timeout": timeout})
        return response

    settings = RemoteSettings.from_values(url=BASE_URL, model="qwen2.5-coder:7b",
                                          api_key="ollama", rate_limit=rate_limit,
                                          max_context=max_context)
    client = RemoteLLMClient(settings=settings, post=fake_post, get=fake_get, **kwargs)
    if clock is not None:
        client._now = lambda: clock[0]
    return client, posts, gets


def test_chat_posts_openai_request():
    """Запрос уходит в OpenAI-формате: эндпоинт, модель, сообщения, лимит и num_ctx."""
    client, posts, _ = make_client(FakeResponse(chat_body()))

    result = client.chat([{"role": "user", "content": "Столица Франции?"}],
                         max_tokens=128)

    assert len(posts) == 1
    call = posts[0]
    assert call["url"] == CHAT_URL
    assert call["headers"]["Authorization"] == "Bearer ollama"
    assert call["timeout"] == config.REMOTE_LLM_TIMEOUT
    payload = call["payload"]
    assert payload["model"] == "qwen2.5-coder:7b"
    assert payload["messages"] == [{"role": "user", "content": "Столица Франции?"}]
    assert payload["stream"] is False
    assert payload["max_tokens"] == 128
    assert payload["temperature"] == config.DEFAULT_TEMPERATURE
    assert payload["top_p"] == DEFAULT_TOP_P
    assert payload["options"] == {"num_ctx": 4096}
    assert result["answer"] == "Париж"
    assert result["provider"] == "remote"
    assert result["tokens"]["total_tokens"] == 15
    assert result["rate_limit"] == {"limit": 10, "used": 1,
                                    "window_seconds": config.REMOTE_LLM_RATE_WINDOW_SECONDS}


def test_generate_with_context_sends_system_and_context():
    """RAG-вызов: системный промпт отдельным сообщением, контекст — вместе с вопросом."""
    client, posts, _ = make_client(FakeResponse(chat_body()))

    client.generate_with_context(system="Ты — ассистент", context="Фрагмент",
                                 question="Что тут?", task_type="code")

    messages = posts[0]["payload"]["messages"]
    assert messages == [{"role": "system", "content": "Ты — ассистент"},
                        {"role": "user", "content": "Фрагмент\n\nЧто тут?"}]
    assert posts[0]["payload"]["max_tokens"] == config.LLM_TASK_MAX_TOKENS["code"]


def test_rate_limiter_blocks_after_limit_and_lets_window_slide():
    """N запросов проходят, N+1-й отклоняет клиент; после окна минуты счёт снова пуст."""
    clock = [1000.0]
    client, posts, _ = make_client(FakeResponse(chat_body()), clock=clock,
                                   rate_limit=3)

    for _ in range(3):
        client.generate("ок")
    assert len(posts) == 3
    with pytest.raises(RateLimitExceeded) as exc:
        client.generate("ок")
    assert "Rate limit exceeded" in str(exc.value)
    assert exc.value.status_code == 429
    assert exc.value.limit == 3
    assert len(posts) == 3, "отклонённый запрос не должен уходить в сеть"

    clock[0] += config.REMOTE_LLM_RATE_WINDOW_SECONDS
    client.generate("ок")
    assert len(posts) == 4


def test_list_models_does_not_spend_rate_budget():
    """Проверка связи — не вызов модели: GET /models не тратит минуту демо."""
    client, _, gets = make_client(FakeResponse(models_body("qwen2.5-coder:7b", "llama3")),
                                  rate_limit=2)

    data = client.list_models()
    client.list_models()

    assert [call["url"] for call in gets] == [MODELS_URL, MODELS_URL]
    assert data == {"models": ["qwen2.5-coder:7b", "llama3"], "count": 2,
                    "url": MODELS_URL, "base_url": BASE_URL}
    assert client.rate_limit_state()["used"] == 0


def test_server_429_and_failures_become_clear_errors():
    """Отказы говорят, что случилось: 429 сервера, обрыв связи, пустой ответ, нет адреса."""
    client, _, _ = make_client(FakeResponse({"error": "too many"}, status_code=429),
                               rate_limit=1)
    with pytest.raises(RateLimitExceeded) as exc:
        client.generate("ок")
    assert "429" in str(exc.value) and "сервер" in str(exc.value).lower()

    client, _, _ = make_client(FakeResponse(None, raw="boom"))
    with pytest.raises(RemoteLLMError):
        client.generate("ок")

    client, _, _ = make_client(FakeResponse(chat_body(content="")))
    with pytest.raises(RemoteLLMError):
        client.generate("ок")

    broken = RemoteLLMClient(settings=RemoteSettings.from_values(rate_limit=5),
                             post=lambda *args, **kwargs: pytest.fail("запрос без адреса"))
    assert broken.base_url == "", "в .env нет REMOTE_LLM_URL — тест ждёт пустой адрес"
    with pytest.raises(RemoteLLMError) as exc:
        broken.generate("ок")
    assert "Base URL" in str(exc.value)

    def failing_post(*args, **kwargs):
        raise requests.ConnectionError("tunnel closed")

    client, _, _ = make_client(FakeResponse(chat_body()))
    client._post = failing_post
    with pytest.raises(RemoteLLMError) as exc:
        client.generate("ок")
    assert "Cloudflare" in str(exc.value)
