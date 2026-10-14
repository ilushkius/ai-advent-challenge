"""Ассистент поддержки пользователей (день 33): чистые правила ответа на вопрос клиента.

Один модуль на весь контракт, потому что читателей у него пять и они не должны
расходиться: служба (``services/support_service``) собирает по нему контекст,
роутер — тела ответов, MCP-сервер — путь к базе (``DB_PATH``), скрипты — сценарии
демо и вердикт строки, Streamlit-раздел — подписи, кнопки-подсказки и раскрывашки,
тесты — ожидаемые области и предупреждения. Здесь только чистые функции и данные:
ни HTTP, ни диска, ни модели.

Три источника одного ответа. Ассистент отвечает по ДОКУМЕНТАЦИИ ПОДДЕРЖКИ
(фрагменты RAG-индекса корпуса дня 22 — FAQ, разборы симптомов и справочник API) и
по КОНТЕКСТУ КЛИЕНТА: профилю пользователя и его тикету, которые отдаёт свой
MCP-сервер ``mcp_servers/support_server``. Область продукта (``detect_area``)
добавляет третий, справочный блок: раздел продукта с коротким FAQ. Что именно
подтягивать, решает вызывающий (поля ``user_id``/``ticket_id`` вопроса), а область —
ключевые слова вопроса.

Почему ключевые слова, а не модель. Определение области — служебный шаг, который
решает, нужен ли лишний вызов MCP; вызов модели перед каждым вопросом стоил бы
дороже и отвечал бы неувереннее, чем таблица подстрок. Список слов — данные
(``AREA_WORDS``): расширять его значит добавлять слово, а не переписывать логику.

Почему ненайденная запись — предупреждение, а не отказ. Профиль может быть не
найден (опечатка в id), тикет — удалён, область — неизвестна. Ответ по одной
документации всё равно полезен клиенту: служба отвечает, а причину показывает
предупреждением (``WARN_USER_NOT_FOUND``, ``WARN_TICKET_NOT_FOUND``) и вердиктом
строки отчёта (``verdict``).

Документация поддержки в корпусе — не копия в ``documents/rag_corpus/``, а записи
таблицы ``domain/rag_corpus_spec.RAG_CORPUS_SOURCES``: корпус дня 22 — производная от
этой таблицы, и добавление файла в неё (шаг пересборки
``scripts/reindex_with_support.py``) — единственный способ попасть в индекс.
``SUPPORT_SOURCES`` перечисляет ровно те файлы, за которые отвечает ассистент, а
``SUPPORT_MIN_CHUNKS`` — минимум чанков на стратегию, ниже которого ответ по
документации считается неполным (скрипт пересборки и скрипт демо сообщают об этом
неуспешным кодом).
"""
from __future__ import annotations

import json
from typing import Any

from .document_sources import source_slug

#: Идентификатор в журнале расходов (``llm_usage``): строки поддержки видно отдельно.
AGENT_ID = "support"

#: Цель MCP-подключения: свой stdio-сервер дня, а не флот дня 20 из
#: ``mcp_servers.json`` (там остаются три сервера, и их раздел не меняется).
SUPPORT_SERVER_TARGET = "uv run python mcp_servers/support_server/server.py"

#: Имя сервера в ответах API и в панели раздела.
SUPPORT_SERVER_NAME = "support_server"

#: Имена инструментов сервера ``support_server``: они уходят в ``tools/call`` и
#: показываются в разделе интерфейса.
TOOL_GET_USER = "get_user"
TOOL_GET_TICKET = "get_ticket"
TOOL_LIST_USER_TICKETS = "list_user_tickets"
TOOL_GET_PRODUCT_INFO = "get_product_info"
#: Пятый инструмент: список пользователей базы. Нужен интерфейсу — селектор
#: пользователей наполняется из MCP, а не из константного списка id.
TOOL_LIST_USERS = "list_users"
TOOLS = (TOOL_GET_USER, TOOL_GET_TICKET, TOOL_LIST_USER_TICKETS,
         TOOL_GET_PRODUCT_INFO, TOOL_LIST_USERS)

#: Сколько фрагментов документации берёт поиск по индексу поддержки.
DEFAULT_TOP_K = 5
#: Сколько последних сообщений тикета уходит в промпт.
MAX_TICKET_MESSAGES = 5
#: Предел текста одного сообщения в промпте.
MESSAGE_CHARS_MAX = 600
#: Предел блока тикета в промпте, символы (~1500 токенов).
TICKET_CONTEXT_MAX_CHARS = 3600
#: Путь к базе поддержки от корня дня: читает его только MCP-сервер
#: (``config.DB_PATH``), служба ходит в данные инструментами.
DB_PATH = "backend/data/support_db.json"

#: Области продукта: значение аргумента ``product_area`` и ключ блока.
AREA_AUTH = "auth"
AREA_BILLING = "billing"
AREA_API = "api"
AREA_INTEGRATIONS = "integrations"
AREA_NOTIFICATIONS = "notifications"
PRODUCT_AREAS = (AREA_AUTH, AREA_BILLING, AREA_API, AREA_INTEGRATIONS, AREA_NOTIFICATIONS)
AREA_LABELS = {
    AREA_AUTH: "Авторизация и вход",
    AREA_BILLING: "Оплата и тарифы",
    AREA_API: "API и ключи доступа",
    AREA_INTEGRATIONS: "Интеграции",
    AREA_NOTIFICATIONS: "Уведомления",
}
#: Слова-маркеры областей: подстрока в нормализованном нижнем регистре вопроса.
#: Побеждает область с большим числом РАЗНЫХ сработавших слов, при равенстве —
#: первая в порядке ``PRODUCT_AREAS``.
AREA_WORDS = {
    AREA_AUTH: ("авторизац", "вход", "войти", "логин", "пароль", "токен", "сесси", "auth"),
    AREA_BILLING: ("оплат", "плат", "списан", "деньг", "тариф", "подписк", "счет", "счёт",
                   "возврат", "цена", "billing"),
    AREA_API: ("api", "апи", "ключ", "endpoint", "эндпоинт", "лимит"),
    AREA_INTEGRATIONS: ("интеграц", "webhook", "вебхук", "slack", "telegram", "zapier"),
    AREA_NOTIFICATIONS: ("уведомлен", "письм", "email", "sms", "рассылк", "оповещен"),
}

#: Документация поддержки, за которую отвечает ассистент: три файла — FAQ, разборы
#: симптомов и справочник API. Пути — от корня репозитория, как в таблице
#: источников корпуса.
SUPPORT_SOURCES = (
    "day21/docs/support/faq.md",
    "day21/docs/support/troubleshooting.md",
    "day21/docs/support/api_reference.md",
)
#: Имена документов в корпусе (``documents/rag_corpus/``): по ним скрипты и демо
#: узнают, что фрагмент ответа пришёл из документации поддержки.
SUPPORT_SLUGS = tuple(source_slug(path) for path in SUPPORT_SOURCES)
#: Минимум чанков документации поддержки на стратегию: ниже него ответы по FAQ и
#: разборам симптомов неполны.
SUPPORT_MIN_CHUNKS = 20

#: Системный промпт: ответ обязан опираться на контекст и называть шаги решения.
SYSTEM_PROMPT = ("Ты — ассистент поддержки пользователей. Ответь пользователю, учитывая его "
                 "профиль, тикет и документацию. Будь вежлив, конкретен, укажи шаги решения. "
                 "Если передан тикет — упомяни его тему, статус и приоритет. Если данных нет — "
                 "предложи создать тикет.")
#: Шапки блоков контекста: по ним модель видит, откуда пришли данные.
CONTEXT_DOCS_HEADER = "=== FAQ И ДОКУМЕНТАЦИЯ ПОДДЕРЖКИ (фрагменты RAG) ==="
CONTEXT_USER_HEADER = "=== ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ (MCP) ==="
CONTEXT_TICKET_HEADER = "=== ТИКЕТ (MCP) ==="
CONTEXT_PRODUCT_HEADER = "=== РАЗДЕЛ ПРОДУКТА (MCP) ==="
EMPTY_CONTEXT_ANSWER = ("Данных нет: индекс поддержки пуст, а MCP-сервер недоступен. "
                        "Пересоберите индекс (`uv run python scripts/reindex_with_support.py`) "
                        "и проверьте сервер `mcp_servers/support_server/server.py`.")
LLM_UNAVAILABLE_ANSWER = "Провайдер «{provider}» недоступен: {error}"
OLLAMA_UNAVAILABLE_ANSWER = ("Ollama не запущена: {error}. DeepSeek работает независимо — "
                             "переключите провайдер в разделе.")
WARN_INDEX_EMPTY = "Индекс поддержки пуст: {error}"
WARN_MCP_UNAVAILABLE = "MCP-сервер поддержки недоступен: {error}"
WARN_TOOL_FAILED = "MCP-инструмент {tool} вернул ошибку: {error}"
WARN_USER_NOT_FOUND = "Профиль пользователя {user_id} не найден: контекст недоступен"
WARN_TICKET_NOT_FOUND = "Тикет {ticket_id} не найден: контекст недоступен"
CONTEXT_UNAVAILABLE = "контекст недоступен"

#: Признаки ответа без контекста: по ним ``verdict`` отличает сбой от содержания.
_PROVIDER_PREFIX = LLM_UNAVAILABLE_ANSWER.split("{")[0]
_OLLAMA_PREFIX = "Ollama не запущена"
_USER_MISSING = WARN_USER_NOT_FOUND.split("{")[0]
_TICKET_MISSING = WARN_TICKET_NOT_FOUND.split("{")[0]

#: Сценарии демо-прогона: подпись, вопрос и контекст клиента. Идентификаторы
#: обязаны существовать в базе поддержки (``backend/data/support_db.json``).
DEMO_SCENARIOS = (
    {"label": "Авторизация: тикет про вход",
     "question": "Почему не работает авторизация?", "user_id": "", "ticket_id": "ticket_007"},
    {"label": "Смена тарифа: пользователь на бесплатном тарифе",
     "question": "Как сменить тариф?", "user_id": "user_001", "ticket_id": ""},
    {"label": "Оплата: двойное списание",
     "question": "Почему списали деньги дважды?", "user_id": "", "ticket_id": "ticket_002"},
    {"label": "Общий вопрос без контекста",
     "question": "Как получить API-ключ?", "user_id": "", "ticket_id": ""},
    {"label": "Открытый тикет пользователя",
     "question": "Мой тикет всё ещё не решён", "user_id": "user_003", "ticket_id": ""},
)

__all__ = ["AGENT_ID", "AREA_API", "AREA_AUTH", "AREA_BILLING", "AREA_INTEGRATIONS",
           "AREA_LABELS", "AREA_NOTIFICATIONS", "AREA_WORDS", "CONTEXT_DOCS_HEADER",
           "CONTEXT_PRODUCT_HEADER", "CONTEXT_TICKET_HEADER", "CONTEXT_UNAVAILABLE",
           "CONTEXT_USER_HEADER", "DB_PATH", "DEFAULT_TOP_K", "DEMO_SCENARIOS",
           "EMPTY_CONTEXT_ANSWER", "LLM_UNAVAILABLE_ANSWER", "MAX_TICKET_MESSAGES",
           "MESSAGE_CHARS_MAX", "OLLAMA_UNAVAILABLE_ANSWER", "PRODUCT_AREAS",
           "SUPPORT_MIN_CHUNKS", "SUPPORT_SERVER_NAME", "SUPPORT_SERVER_TARGET",
           "SUPPORT_SLUGS", "SUPPORT_SOURCES", "SYSTEM_PROMPT",
           "TICKET_CONTEXT_MAX_CHARS", "TOOLS", "TOOL_GET_PRODUCT_INFO", "TOOL_GET_TICKET",
           "TOOL_GET_USER", "TOOL_LIST_USERS", "TOOL_LIST_USER_TICKETS",
           "WARN_INDEX_EMPTY", "WARN_MCP_UNAVAILABLE", "WARN_TICKET_NOT_FOUND",
           "WARN_TOOL_FAILED", "WARN_USER_NOT_FOUND", "detect_area",
           "normalize_question", "render_context", "ticket_block", "verdict"]


def normalize_question(text: object) -> str:
    """Вопрос клиента: пробелы схлопнуты, регистр сохранён.

    Пустая строка — «вопроса нет»: служба отвечает на неё отказом (400), а не
    поиском по индексу пустой строки. Ведущей команды у ассистента поддержки нет —
    вопрос задаётся формой раздела, а не строкой чата.
    """
    return " ".join(str(text or "").split())


def detect_area(question: str) -> str:
    """Область продукта по числу РАЗНЫХ сработавших подстрок ``AREA_WORDS``.

    Побеждает область с большим счётом, при равенстве — первая в порядке
    ``PRODUCT_AREAS`` (обход строго с заменой на «больше»). Ноль попаданий — пустая
    строка: тогда раздел продукта в контекст не тянется, а ответ строится по
    документации и контексту клиента.
    """
    text = str(question or "").lower()
    area, score = "", 0
    for candidate in PRODUCT_AREAS:
        hits = sum(1 for word in AREA_WORDS[candidate] if word in text)
        if hits > score:
            area, score = candidate, hits
    return area


def render_context(hits: list[dict], user_context: Any = None,
                   ticket_context: Any = None, product_context: Any = None) -> str:
    """Контекст ответа: документация поддержки и три блока MCP через пустую строку.

    Фрагмент документации показывается с адресом (источник, заголовок, секция): без
    него модель не сможет сослаться на файл, а раскрывашка «📚 Источники» —
    совпасть с тем, на что она опиралась. Блоки MCP печатаются JSON-ом: структуру
    профиля, тикета и раздела продукта модель видит без догадок, а поля вроде
    ``status`` и ``priority`` читает по именам.
    """
    blocks: list[str] = []
    if hits:
        lines = [CONTEXT_DOCS_HEADER]
        for position, hit in enumerate(hits, start=1):
            lines.append(f"[{position}] источник: {hit.get('source') or ''} · "
                         f"заголовок: {hit.get('title') or ''} · "
                         f"секция: {hit.get('section') or ''}")
            lines.append(str(hit.get("content") or ""))
        blocks.append("\n".join(lines))
    for header, value in ((CONTEXT_USER_HEADER, user_context),
                          (CONTEXT_TICKET_HEADER, ticket_context),
                          (CONTEXT_PRODUCT_HEADER, product_context)):
        if value:
            blocks.append(header + "\n" + json.dumps(value, ensure_ascii=False, indent=1))
    return "\n\n".join(blocks)


def ticket_block(ticket: Any) -> dict:
    """Тикет для промпта и ответа: последние сообщения и обрезка длинных текстов.

    В контекст уходят только ``MAX_TICKET_MESSAGES`` последних сообщений: в старых
    лежит история, которая к текущему вопросу не относится, а платить за неё
    токенами приходится на каждом запросе. Текст одного сообщения режется до
    ``MESSAGE_CHARS_MAX``, а если и после этого JSON длиннее
    ``TICKET_CONTEXT_MAX_CHARS`` — длинные тексты укорачиваются дальше: так блок
    тикета не вытесняет из промпта документацию и профиль.
    """
    source = dict(ticket or {})
    source.pop("error", None)
    messages = [dict(item) for item in (source.get("messages") or [])
                if isinstance(item, dict)]
    kept = messages[-MAX_TICKET_MESSAGES:]
    for item in kept:
        text = str(item.get("text") or "")
        if len(text) > MESSAGE_CHARS_MAX:
            item["text"] = text[:MESSAGE_CHARS_MAX - 1] + "…"
    block = {**source, "messages": kept}
    while _json_size(block) > TICKET_CONTEXT_MAX_CHARS:
        longest = max(kept, key=lambda item: len(str(item.get("text") or "")), default=None)
        text = str((longest or {}).get("text") or "")
        if not text:
            break
        cut = max(0, len(text) - (len(text) // 5 or 1))
        longest["text"] = text[:cut].rstrip() + "…"
    return block


def verdict(record: dict) -> str:
    """Вердикт строки демо-прогона: чем подтверждён ответ.

    Порядок проверок — от худшего к лучшему, и он существенный: недоступный
    провайдер важнее любых источников (ответа модели нет), «нет данных» — отказ
    службы, ошибка инструмента — предупреждение поверх ответа, недоступный контекст
    клиента важнее остатка, а последние строки говорят, что именно подкрепило ответ.
    """
    answer = str(record.get("answer") or "")
    if answer.startswith(_PROVIDER_PREFIX) or answer.startswith(_OLLAMA_PREFIX):
        return "❌ провайдер недоступен"
    if answer == EMPTY_CONTEXT_ANSWER:
        return "❌ нет данных"
    used = list(record.get("mcp_tools_used") or [])
    if any(not item.get("ok", True) for item in used):
        return "⚠️ MCP-инструмент с ошибкой"
    if any(str(warning).startswith((_USER_MISSING, _TICKET_MISSING))
           for warning in record.get("warnings") or []):
        return "⚠️ контекст недоступен"
    user, ticket = record.get("user_context"), record.get("ticket_context")
    if user and ticket:
        return "✅ контекст пользователя и тикета"
    if user:
        return "✅ контекст пользователя"
    if ticket:
        return "✅ контекст тикета"
    if list(record.get("sources") or []):
        return "✅ источники"
    return "⚠️ только модель"


def _json_size(value: Any) -> int:
    """Длина JSON-представления блока: мера блока тикета в символах промпта."""
    return len(json.dumps(value, ensure_ascii=False, indent=1))
