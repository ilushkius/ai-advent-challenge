"""Ассистент разработчика (день 31): контракт команды ``/help <вопрос>``.

Один модуль на весь контракт, потому что читателей у него четыре и они не должны
расходиться: служба (``services/dev_assistant_service``) строит по нему план вызовов
и контекст ответа, роутер — тела ответов, скрипты — вопросы демо и вердикт строки,
Streamlit-раздел — подписи, примеры вопросов и раскрывашки, тесты — ожидаемые типы
вопросов. Здесь только чистые функции и данные: ни HTTP, ни диска, ни модели.

Два источника ответа, один вопрос. Ассистент отвечает по ДОКУМЕНТАЦИИ проекта
(фрагменты RAG-индекса корпуса дня 22) и по СОСТОЯНИЮ РЕПОЗИТОРИЯ (инструменты
MCP-сервера ``mcp_servers/dev_server``). Какой источник нужен — решает тип вопроса
(``classify_question``): «как устроена память агента?» — документация, «что в
текущей git-ветке?» — git. Вопрос про оба («какие файлы изменены и как устроен
RAG?») получает оба источника: смешанный тип это не компромисс, а норма — именно
так разработчик и спрашивает.

Почему ключевые слова, а не модель. Классификация — служебный шаг, который решает,
какие инструменты вызвать; лишний вызов модели перед каждым вопросом стоил бы
дороже и отвечал бы неувереннее, чем таблица подстрок. Список слов — данные
(``GIT_WORDS``, ``DOCS_WORDS``): расширять его значит добавлять слово, а не
переписывать логику.

Документация проекта в корпусе — не копия в ``documents/rag_corpus/``, а записи
таблицы источников ``domain/rag_corpus_spec.RAG_CORPUS_SOURCES``: корпус дня 22 —
производная от этой таблицы, и добавление файла в неё (шаг пересборки
``scripts/reindex_with_docs.py``) — единственный способ попасть в индекс.
``DOCUMENTATION_SOURCES`` здесь перечисляет ровно те файлы, за которые отвечает
ассистент, а ``DOCUMENTATION_MIN_CHUNKS`` — минимум чанков на стратегию, ниже
которого ответ по документации считается ненадёжным (скрипт пересборки и скрипт
демо сообщают об этом неуспешным кодом).
"""
from __future__ import annotations

import json
import re

from .document_sources import source_slug

#: Идентификатор в журнале расходов (``llm_usage``): строки ассистента видно отдельно.
AGENT_ID = "dev-assistant"

#: Цель MCP-подключения: свой stdio-сервер дня, а не флот дня 20 из
#: ``mcp_servers.json`` (там остаются три сервера, и их раздел не меняется).
DEV_SERVER_TARGET = "uv run python mcp_servers/dev_server/server.py"

#: Типы вопросов: ``docs`` — только документация, ``git`` — только репозиторий,
#: ``mixed`` — оба источника.
KIND_DOCS = "docs"
KIND_GIT = "git"
KIND_MIXED = "mixed"
KINDS = (KIND_DOCS, KIND_GIT, KIND_MIXED)
KIND_LABELS = {
    KIND_DOCS: "документация",
    KIND_GIT: "git и файлы",
    KIND_MIXED: "документация + git",
}

#: Имена инструментов сервера ``dev_server``: они уходят в ``tools/call`` и
#: показываются в разделе интерфейса.
TOOL_GIT_BRANCH = "get_git_branch"
TOOL_LIST_FILES = "list_files"
TOOL_GIT_DIFF = "get_git_diff"
TOOL_PROJECT_STRUCTURE = "get_project_structure"
TOOLS = (TOOL_GIT_BRANCH, TOOL_LIST_FILES, TOOL_GIT_DIFF, TOOL_PROJECT_STRUCTURE)

#: Умолчания аргументов плана вызовов и поиска по документации.
DEFAULT_TOP_K = 5
DEFAULT_TREE_DEPTH = 3
DEFAULT_DIFF_LINES = 50
DEFAULT_FILE_DIRECTORY = "day21"

#: Документация проекта, за которую отвечает ассистент: восемь файлов от README дня
#: до правил репозитория. Пути — от корня репозитория, как в таблице источников.
DOCUMENTATION_SOURCES = (
    "day21/README.md",
    "day21/docs/architecture.md",
    "day21/docs/usage.md",
    "day21/docs/api.md",
    "README.md",
    "ARCHITECT_PROMPT.md",
    "WORKFLOW.md",
    "AGENTS.md",
)
#: Имена документов в корпусе (``documents/rag_corpus/``): по ним скрипты и демо
#: узнают, что фрагмент ответа пришёл из документации проекта.
DOCUMENTATION_SLUGS = tuple(source_slug(path) for path in DOCUMENTATION_SOURCES)
#: Минимум чанков документации на стратегию: ниже него ответы по документации неполны.
DOCUMENTATION_MIN_CHUNKS = 30

#: Примеры вопросов: кнопки-подсказки в разделе и вопросы демо-прогона. Список
#: покрывает оба источника и смешанный случай.
DEMO_QUESTIONS = (
    "/help как устроена память агента?",
    "/help что в текущей git-ветке?",
    "/help покажи структуру проекта",
    "/help какие файлы изменены?",
    "/help как запустить тесты?",
)

#: Слова-маркеры источников: подстрока в нормализованном нижнем регистре вопроса.
GIT_WORDS = ("git", "ветк", "branch", "коммит", "commit", "diff", "дифф",
             "изменен", "изменён", "modified", "статус", "status", "файл", "file",
             "структур", "папк", "каталог", "дерев", "репозитор")
DOCS_WORDS = ("документац", "архитектур", "как устро", "как работ", "как запуст",
              "тест", "pytest", "rag", "readme", "объясни", "описан", "почему",
              "зачем", "память")
#: Слова, по которым к плану добавляется инструмент (git-ветка в плане всегда первая).
STRUCTURE_WORDS = ("структур", "папк", "каталог", "дерев")
DIFF_WORDS = ("diff", "дифф", "изменен", "изменён", "modified", "commit", "коммит")
FILE_LIST_WORDS = ("список файл", "list_files", "файлы в ", "какие файлы есть")

#: Системный промпт: ответ обязан опираться на контекст и называть источники.
SYSTEM_PROMPT = ("Ты — ассистент разработчика проекта. Отвечай на вопрос, используя "
                 "документацию проекта и контекст git. Всегда указывай источники "
                 "(файл + секция) и использованные MCP-инструменты. Если данных нет — "
                 "скажи честно.")
#: Шапки блоков контекста: по ним модель видит, откуда пришли данные.
CONTEXT_DOCS_HEADER = "=== ДОКУМЕНТАЦИЯ ПРОЕКТА (фрагменты RAG) ==="
CONTEXT_GIT_HEADER = "=== СОСТОЯНИЕ РЕПОЗИТОРИЯ (MCP) ==="
EMPTY_CONTEXT_ANSWER = ("Данных нет: индекс документации пуст, а MCP-инструменты "
                        "недоступны. Пересоберите индекс (`uv run python "
                        "scripts/reindex_with_docs.py`) и проверьте сервер "
                        "`mcp_servers/dev_server/server.py`.")
LLM_UNAVAILABLE_ANSWER = "Провайдер «{provider}» недоступен: {error}"
OLLAMA_UNAVAILABLE_ANSWER = ("Ollama не запущена: {error}. DeepSeek работает "
                             "независимо — переключите провайдер в разделе.")
WARN_INDEX_EMPTY = "Индекс документации пуст: {error}"
WARN_MCP_UNAVAILABLE = "MCP-сервер разработки недоступен: {error}"
WARN_TOOL_FAILED = "MCP-инструмент {tool} вернул ошибку: {error}"
WARN_TOOL_TEXT_ONLY = "MCP-инструмент {tool} вернул текст без структурированного результата"

#: Ведущая команда ``/help``: снимается вместе с пробелами после неё.
_HELP_PREFIX = re.compile(r"^/help\b\s*", re.IGNORECASE)

__all__ = ["AGENT_ID", "CONTEXT_DOCS_HEADER", "CONTEXT_GIT_HEADER",
           "DEFAULT_DIFF_LINES", "DEFAULT_FILE_DIRECTORY", "DEFAULT_TOP_K",
           "DEFAULT_TREE_DEPTH", "DEMO_QUESTIONS", "DEV_SERVER_TARGET",
           "DIFF_WORDS", "DOCS_WORDS", "DOCUMENTATION_MIN_CHUNKS",
           "DOCUMENTATION_SLUGS", "DOCUMENTATION_SOURCES", "EMPTY_CONTEXT_ANSWER",
           "FILE_LIST_WORDS", "GIT_WORDS", "KINDS", "KIND_DOCS", "KIND_GIT",
           "KIND_LABELS", "KIND_MIXED", "LLM_UNAVAILABLE_ANSWER",
           "OLLAMA_UNAVAILABLE_ANSWER", "STRUCTURE_WORDS", "SYSTEM_PROMPT",
           "TOOLS", "TOOL_GIT_BRANCH", "TOOL_GIT_DIFF", "TOOL_LIST_FILES",
           "TOOL_PROJECT_STRUCTURE", "WARN_INDEX_EMPTY", "WARN_MCP_UNAVAILABLE",
           "WARN_TOOL_FAILED", "WARN_TOOL_TEXT_ONLY", "classify_question",
           "normalize_question", "plan_tools", "render_context", "verdict"]


def normalize_question(text: object) -> str:
    """Вопрос без ведущей команды ``/help``: пробелы схлопнуты, регистр сохранён.

    Пустая строка — «вопроса нет»: служба отвечает на неё отказом (400), а не
    поиском по индексу пустой строки. Команда снимается до схлопывания пробелов,
    поэтому ``"  /HELP   что в ветке?  "`` даёт тот же вопрос, что и ввод без неё.
    """
    compact = " ".join(str(text or "").split())
    return _HELP_PREFIX.sub("", compact, count=1).strip()


def _word_hits(words: tuple[str, ...], text: str) -> int:
    """Сколько РАЗНЫХ маркеров встретилось в тексте: счёт, а не вес."""
    return sum(1 for word in words if word in text)


def classify_question(question: str) -> str:
    """Тип вопроса по маркерам: ``docs``, ``git`` или ``mixed``.

    Сработали и git-, и docs-слова — ``mixed`` (оба источника нужны). Сработали
    только git-слова — ``git``. Всё остальное — ``docs``: документация проекта
    запасной путь по умолчанию, и «просто вопрос о проекте» не должен остаться
    без ответа из-за отсутствия знакомых слов.
    """
    text = str(question or "").lower()
    git_score = _word_hits(GIT_WORDS, text)
    docs_score = _word_hits(DOCS_WORDS, text)
    if git_score and docs_score:
        return KIND_MIXED
    if git_score:
        return KIND_GIT
    return KIND_DOCS


def plan_tools(kind: str, question: str) -> list[tuple[str, dict]]:
    """План вызовов MCP: пары «имя инструмента, аргументы» для типа вопроса.

    Вопросу по документации инструменты не нужны — пустой план. Git-вопрос всегда
    начинается с ``get_git_branch``: ветка, коммит, статус и изменённые файлы —
    то, с чего начинается любой разговор про состояние репозитория. Остальные
    инструменты добавляются по словам вопроса (структура, diff, список файлов),
    поэтому дерево проекта не тянется в контекст вопроса про commit.
    """
    if kind == KIND_DOCS:
        return []
    text = str(question or "").lower()
    plan = [(TOOL_GIT_BRANCH, {})]
    if _word_hits(STRUCTURE_WORDS, text):
        plan.append((TOOL_PROJECT_STRUCTURE, {"max_depth": DEFAULT_TREE_DEPTH}))
    if _word_hits(DIFF_WORDS, text):
        plan.append((TOOL_GIT_DIFF, {"lines": DEFAULT_DIFF_LINES}))
    if _word_hits(FILE_LIST_WORDS, text):
        plan.append((TOOL_LIST_FILES, {"directory": DEFAULT_FILE_DIRECTORY,
                                       "extension": ""}))
    return plan


def render_context(hits: list[dict], tool_blocks: list[dict]) -> str:
    """Контекст ответа: блок документации и блок MCP через пустую строку.

    Фрагмент документации показывается с адресом (источник, заголовок, секция):
    без него модель не сможет сослаться на файл, а раздел «📚 Источники» — совпасть
    с тем, на что она опиралась. Ответ инструмента печатается как JSON, чтобы
    структуру результата было видно модели без догадок; инструмент, отдавший только
    текст, попадает в контекст самим текстом.
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
    if tool_blocks:
        lines = [CONTEXT_GIT_HEADER]
        for block in tool_blocks:
            tool = str(block.get("tool") or "")
            structured = block.get("structured")
            if structured is None:
                lines.append(f"{tool}:\n{block.get('text') or ''}")
            else:
                lines.append(f"{tool}:\n{json.dumps(structured, ensure_ascii=False, indent=1)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def verdict(record: dict) -> str:
    """Вердикт строки демо-прогона: чем подтверждён ответ.

    Порядок проверок — от худшего к лучшему, и он существенный: недоступный
    провайдер важнее любых источников (ответа модели нет), «нет данных» — отказ
    службы, ошибка инструмента — предупреждение поверх ответа, а последние четыре
    строки говорят, что именно подкрепило ответ.
    """
    answer = str(record.get("answer") or "")
    if answer.startswith("Провайдер «") or answer.startswith("Ollama не запущена"):
        return "❌ провайдер недоступен"
    if answer == EMPTY_CONTEXT_ANSWER:
        return "❌ нет данных"
    used = list(record.get("mcp_tools_used") or [])
    if any(not item.get("ok", True) for item in used):
        return "⚠️ MCP-инструмент с ошибкой"
    ok_tools = [item for item in used if item.get("ok")]
    sources = list(record.get("sources") or [])
    if sources and ok_tools:
        return "✅ источники + MCP"
    if sources:
        return "✅ источники"
    if ok_tools:
        return "✅ MCP"
    return "⚠️ только модель"
