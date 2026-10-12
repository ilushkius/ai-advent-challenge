"""HTTP-часть раздела «🧑‍💻 Ассистент разработчика» (день 31).

Транспорт общий — ``frontend/api_client.py``; здесь три запроса дня 31: вопрос
``/help``, каталог инструментов dev-сервера и git-контекст.

Предел ожидания — ``LONG_TIMEOUT`` у вопроса: он один раз идёт к модели (DeepSeek
отвечает десятками секунд, локальная Ollama — с прогревом весов ещё дольше), а
панели раздела (инструменты и git) отвечают мгновенно и пользуются общим пределом.
"""
from .api_client import LONG_TIMEOUT, request_json


def api_dev_help(question: str, provider: str = "") -> dict:
    """POST /dev-assistant/help -> ответ, источники RAG и вызовы MCP-инструментов."""
    payload = {"question": question}
    if provider:
        payload["provider"] = provider
    return request_json("POST", "/dev-assistant/help", timeout=LONG_TIMEOUT, json=payload)


def api_dev_tools() -> dict:
    """GET /dev-assistant/tools -> каталог инструментов dev-сервера (всегда 200)."""
    return request_json("GET", "/dev-assistant/tools")


def api_dev_git_context() -> dict:
    """GET /dev-assistant/git-context -> ветка, коммит и изменённые файлы."""
    return request_json("GET", "/dev-assistant/git-context")
