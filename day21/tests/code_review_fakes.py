"""Фейки AI-ревью PR (день 32) для юнит-тестов службы.

Отдельный модуль, как ``dev_assistant_fakes.py``: кейсов и фейков хватает на два
теста с параметризацией, а держать их в тестовом файле нельзя — он вышел бы за
предел 400 строк. Настоящие зависимости здесь не участвуют: индекс — фейк (отдаёт
документацию и код изменённых файлов или падает), MCP-клиент — фейк (пишет вызовы и
отдаёт diff по имени инструмента), клиент GitHub — фейк (отдаёт diff, файлы и ссылку на
комментарий), модель — ``RagStubClient`` из ``rag_fakes.py``.

Настоящий корпус и настоящий процесс ``dev_server`` проверяет slow-интеграция
(``tests/integration/test_code_review_flow.py``): здесь проверяется разбор ответа
модели, отказы шагов и то, откуда служба берёт diff и список файлов.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Tuple

from backend.domain import code_review, dev_assistant
from backend.domain.mcp_tools import MCPToolResult, make_tool_info
from backend.services.code_review_service import CodeReviewService
from backend.services.github_client import GitHubClient
from backend.services.index_service import IndexNotBuiltError
from backend.services.mcp_errors import MCPConnectionError

#: Небольшой diff трёх файлов корпуса: пути реальные, поэтому имена файлов в
#: находках модели можно сверять с полем ``source`` фрагментов RAG.
PR_DIFF = """diff --git a/day21/backend/api/main.py b/day21/backend/api/main.py
--- a/day21/backend/api/main.py
+++ b/day21/backend/api/main.py
@@ -1,3 +1,5 @@
 from fastapi import FastAPI
 
+from . import code_review
 from .lifespan import lifespan
diff --git a/day21/backend/services/index_service.py b/day21/backend/services/index_service.py
--- a/day21/backend/services/index_service.py
+++ b/day21/backend/services/index_service.py
@@ -150,3 +150,6 @@ class IndexService:
     def search(self, query: str, top_k=None, strategy: str = ""):
         index = self._loaded_index(strategy)
+        rows = self.store.rows_by_ids([1, 2])
+        session = database.SessionLocal()
         return rows
diff --git a/day21/docs/usage.md b/day21/docs/usage.md
--- a/day21/docs/usage.md
+++ b/day21/docs/usage.md
@@ -3,3 +3,4 @@
 
 Раздел с командами запуска.
+Новая команда ревью: scripts/run_local_pr_review.py
"""

#: Адрес PR: его отдаёт фейк GitHub и его же проверяют тесты службы.
PR_URL = "https://github.com/owner/repo/pull/42"

#: Файлы, которые служба обязана назвать своими: список приходит из payload или MCP.
CHANGED_FILES = ["day21/backend/api/main.py",
                 "day21/backend/services/index_service.py",
                 "day21/docs/usage.md"]

#: Фрагменты документации проекта (slug-и — как у ``dev_assistant.DOCUMENTATION_SLUGS``).
DOCS_HITS = [
    {"chunk_id": "doc-1", "source": "day21-docs-architecture.md", "title": "Архитектура",
     "section": "Слои", "score": 0.81, "vector_score": 0.7, "lexical_score": 0.5,
     "rerank_score": None, "content": "Слои: domain → services → storage."},
    {"chunk_id": "doc-2", "source": "day21-docs-usage.md", "title": "Инструкция",
     "section": "Запуск", "score": 0.62, "vector_score": 0.5, "lexical_score": 0.4,
     "rerank_score": None, "content": "Запуск: uv run uvicorn backend.api.main:app."},
]

#: Фрагменты кода изменённых файлов: ключ — slug файла (``document_sources.source_slug``).
CODE_HITS = {
    "day21-backend-api-main.py": [
        {"chunk_id": "code-1", "source": "day21-backend-api-main.py", "title": "main.py",
         "section": "module", "score": 0.9, "vector_score": 0.8, "lexical_score": 0.6,
         "rerank_score": None, "content": "app = FastAPI(...)"},
    ],
    "day21-backend-services-index_service.py": [
        {"chunk_id": "code-2", "source": "day21-backend-services-index_service.py",
         "title": "index_service.py", "section": "IndexService.search", "score": 0.77,
         "vector_score": 0.6, "lexical_score": 0.5, "rerank_score": None,
         "content": "def search(self, query, top_k=None, strategy=\"\")"},
    ],
}

#: Канонический ответ модели по контракту: риски специально идут НЕ по порядку —
#: сортировка P0 → P3 проверяется на них.
REVIEW_JSON = json.dumps({
    "bugs": [
        {"file": "day21/backend/services/index_service.py", "line": "152",
         "issue": "Запрос к базе идёт из слоя служб мимо ChunkStore", "priority": "P0"},
        {"file": "day21/docs/usage.md", "issue": "Команда ревью не описана в разделе",
         "priority": "P2"},
    ],
    "architecture_issues": [
        {"file": "day21/backend/services/index_service.py",
         "issue": "Служба индекса читает базу напрямую",
         "recommendation": "Ходить в базу через ChunkStore", "priority": "P1"},
    ],
    "recommendations": ["Закрывать сессию через context manager",
                        "Вынести имена колонок в одно место"],
    "risks": [
        {"priority": "P3", "file": "day21/docs/usage.md",
         "risk": "Раздел инструкции останется неполным"},
        {"priority": "P0", "file": "day21/backend/services/index_service.py",
         "risk": "Утечка соединений с базой под нагрузкой"},
        {"priority": "P1", "file": "day21/backend/api/main.py",
         "risk": "Импорт code_review в main.py замыкает цикл"},
    ],
}, ensure_ascii=False)

#: Ответ модели без JSON: структура не разбирается, но текст сохраняется.
REVIEW_TEXT_ONLY = "Ревью: в index_service.py нет закрытия сессии."


class FakeIndexService:
    """Служба поиска без индекса: отдаёт документацию и код файлов из запроса.

    Настоящий поиск ранжирует всё вместе, поэтому фейк тоже возвращает общий список
    (документация плюс фрагменты файлов, чьи slug-и упомянуты в запросе) — фильтры
    по ``source`` остаются на службе и проверяются на нём же.
    """

    def __init__(self, docs=None, code=None, error: Optional[Exception] = None,
                 detail_misses=()) -> None:
        self.docs = list(DOCS_HITS if docs is None else docs)
        self.code = dict(CODE_HITS if code is None else code)
        self.error = error
        #: Slug-и, которые находятся ТОЛЬКО по запросу из одного пути: так проверяется
        #: второй запрос службы, когда добавленные строки увели выдачу от файла.
        self.detail_misses = set(detail_misses)
        self.calls: list = []

    def search(self, query: str, top_k=None, strategy: str = ""):
        self.calls.append({"query": query, "top_k": top_k, "strategy": strategy})
        if self.error is not None:
            raise self.error
        text = str(query or "").replace("/", "-")
        hits = list(self.docs)
        for slug, found in self.code.items():
            if slug not in text:
                continue
            if slug in self.detail_misses and len(text) > len(slug):
                continue
            hits.extend(found)
        return hits


class FakeMCP:
    """MCP-клиент без транспорта: записывает вызовы и отдаёт diff по имени инструмента."""

    def __init__(self, error: Optional[Exception] = None,
                 diff: str = PR_DIFF, files=None, tool_error: str = "") -> None:
        self.error = error
        self.diff = diff
        self.files = list(CHANGED_FILES if files is None else files)
        self.tool_error = tool_error
        self.calls: list = []
        self.connected = True
        self.closed = False

    def list_tools(self, *, refresh: bool = False):
        return [make_tool_info(name, f"Инструмент {name}") for name in dev_assistant.TOOLS]

    def call_tool(self, name: str, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        if self.error is not None:
            raise self.error
        if self.tool_error:
            return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                                 text=self.tool_error, is_error=True, duration_ms=3)
        if name == code_review.TOOL_CHANGED_FILES:
            structured = {"base": "day30", "head": "day31", "count": len(self.files),
                          "truncated": False, "files": self.files}
            return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                                 structured=structured, text="ok", duration_ms=2)
        return MCPToolResult(tool=name, arguments=dict(arguments or {}),
                             structured={"result": self.diff}, text=self.diff,
                             duration_ms=2)

    def close(self) -> None:
        self.closed = True


class FailingStdioClient:
    """Подмена ``MCPClient``, у которой сервер не поднимается (нет процесса/команды)."""

    def __init__(self, target, **kwargs) -> None:
        self.target = target
        self.calls: list = []

    def connect(self):
        raise MCPConnectionError("сервер не отвечает")

    def list_tools(self, *, refresh: bool = False):
        return []

    def close(self) -> None:
        pass


class FakeGitHub:
    """Клиент GitHub без сети: URL разбирает настоящим образцом, остальное — из полей.

    Подменяет ``GitHubClient`` целиком: тесты службы проверяют не HTTP (его проверяет
    ``tests/unit/test_github_client.py``), а то, что служба делает с ответами GitHub —
    берёт diff и файлы, кладёт ``github_meta`` и публикует ревью по флагу.
    """

    parse_repo_url = staticmethod(GitHubClient.parse_repo_url)

    def __init__(self, diff: str = PR_DIFF, files=None, error: Optional[Exception] = None,
                 comment_error: Optional[Exception] = None) -> None:
        self.diff = diff
        self.files = list(CHANGED_FILES if files is None else files)
        self.error = error
        self.comment_error = comment_error
        self.posted: list = []
        self.closed = False

    def get_repo(self, owner: str, repo: str) -> dict:
        return {"full_name": f"{owner}/{repo}", "html_url": f"https://github.com/{owner}/{repo}"}

    def get_pr(self, owner: str, repo: str, pr_number: int) -> dict:
        return {"number": int(pr_number), "state": "open", "title": "тестовый PR",
                "html_url": PR_URL}

    def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        if self.error is not None:
            raise self.error
        return self.diff

    def get_changed_files(self, owner: str, repo: str, pr_number: int) -> list:
        return [{"filename": path, "status": "modified", "additions": 1, "deletions": 0,
                 "changes": 1, "patch": "@@"} for path in self.files]

    def post_review_comment(self, owner: str, repo: str, pr_number: int, body: str) -> dict:
        if self.comment_error is not None:
            raise self.comment_error
        self.posted.append(str(body))
        return {"html_url": f"{PR_URL}#pullrequestreview-1"}

    def health(self) -> dict:
        return {"status": "ok", "service": "github", "api_base": "https://api.github.com",
                "authenticated": True, "token": "ghp_***",
                "rate_limit": {"limit": 5000, "remaining": 4999, "used": 1,
                               "reset": 1791918354}, "error": ""}

    def close(self) -> None:
        self.closed = True


def payload(**overrides) -> dict:
    """Базовый payload ревью: diff и изменённые файлы уже переданы."""
    data = {"diff": PR_DIFF, "changed_files": list(CHANGED_FILES),
            "base": "day30", "head": "day31", "pr_label": "diff day30..day31"}
    data.update(overrides)
    return data


@dataclass
class Case:
    """Кейс параметризации: payload плюс отказы фейков и ожидания проверок."""

    name: str
    payload: dict
    mcp_error: Optional[Exception] = None
    index_error: Optional[Exception] = None
    llm_error: Optional[Exception] = None
    expect_mcp_tools: Tuple[str, ...] = ()
    expect_parsed: bool = True
    expect_warning: str = ""
    expect_sources: bool = True


#: Пять кейсов: diff из payload, diff и файлы из MCP, сбой MCP на списке файлов,
#: недоступная модель и пустой индекс корпуса.
CASES: Tuple[Case, ...] = (
    Case(name="payload", payload=payload()),
    Case(name="mcp", payload={"base": "day30", "head": "day31",
                              "pr_label": "diff day30..day31"},
         expect_mcp_tools=(code_review.TOOL_PR_DIFF, code_review.TOOL_CHANGED_FILES)),
    Case(name="mcp_error", payload=payload(changed_files=[]),
         mcp_error=MCPConnectionError("сервер не отвечает"),
         expect_mcp_tools=(code_review.TOOL_CHANGED_FILES,),
         expect_warning=code_review.WARN_MCP_UNAVAILABLE[:20]),
    Case(name="llm_error", payload=payload(), llm_error=RuntimeError("сеть недоступна"),
         expect_parsed=False),
    Case(name="index_empty", payload=payload(),
         index_error=IndexNotBuiltError("индекс не построен"),
         expect_warning=code_review.WARN_INDEX_EMPTY[:20], expect_sources=False),
)


def make_service(*, index=None, mcp=None, client=None, github=None,
                 **kwargs) -> CodeReviewService:
    """Служба на фейках: подставленные зависимости вместо служб процесса."""
    return CodeReviewService(index_service=index if index is not None else FakeIndexService(),
                             mcp_client=mcp if mcp is not None else FakeMCP(),
                             llm_client=client,
                             github_client=github if github is not None else FakeGitHub(),
                             sleep=lambda _seconds: None, **kwargs)
