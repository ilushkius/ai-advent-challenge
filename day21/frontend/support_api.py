"""HTTP-часть раздела «🎧 Поддержка пользователей» (день 33).

Транспорт общий — ``frontend/api_client.py``; здесь четыре запроса дня 33: вопрос с
контекстом клиента, каталог пользователей, тикеты клиента и один тикет целиком.

Предел ожидания — ``LONG_TIMEOUT`` у вопроса: он один раз идёт к модели (DeepSeek
отвечает десятками секунд, локальная Ollama — с прогревом весов ещё дольше), а
запросы к MCP-серверу поддержки (каталог, тикеты) отвечают мгновенно и пользуются
общим пределом.
"""
from .api_client import LONG_TIMEOUT, request_json


def api_support_ask(question: str, user_id: str = "", ticket_id: str = "",
                    provider: str = "") -> dict:
    """POST /support/ask -> ответ, источники RAG и контекст клиента из MCP.

    Пустые ``user_id``/``ticket_id``/``provider`` в тело не попадают: «поле не
    задано» и «поле пустое» для службы одно и то же, но лишние поля в запросе
    мешают читать журнал вызовов.
    """
    payload = {"question": question}
    if user_id:
        payload["user_id"] = user_id
    if ticket_id:
        payload["ticket_id"] = ticket_id
    if provider:
        payload["provider"] = provider
    return request_json("POST", "/support/ask", timeout=LONG_TIMEOUT, json=payload)


def api_support_users() -> dict:
    """GET /support/users -> каталог клиентов поддержки (всегда 200)."""
    return request_json("GET", "/support/users")


def api_support_tickets(user_id: str) -> dict:
    """GET /support/tickets?user_id=… -> тикеты клиента (всегда 200)."""
    return request_json("GET", "/support/tickets", params={"user_id": user_id})


def api_support_ticket(ticket_id: str) -> dict:
    """GET /support/tickets/{ticket_id} -> тикет целиком с историей сообщений."""
    return request_json("GET", f"/support/tickets/{ticket_id}")
