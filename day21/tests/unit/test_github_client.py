"""Юнит-тесты клиента GitHub REST API (день 32): разбор URL, запросы, ошибки, health.

Проверяется ОДНО поведение — что клиент отдаёт службе ревью и что говорит при отказе:
пара ``owner/repo`` из трёх форм URL, заголовки запросов (``Accept`` у diff-а,
``Authorization`` при токене), тексты ошибок с кодом ответа, признак исчерпанного rate
limit, тело публикации комментария и готовность с маской токена.

Сеть не нужна: транспорт — ``httpx.MockTransport``, сокеты не открываются, поэтому
autouse-запрет сети (``tests/conftest.py``) остаётся в силе. Живой GitHub API проверяет
отдельный slow-тест с маркером ``github``
(``tests/integration/test_github_pr_flow.py``).
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.services.github_client import (ACCEPT_DIFF, ACCEPT_JSON, TOKEN_ENV,
                                           GitHubClient, GitHubError, github_token,
                                           mask_token)

#: Ответы GitHub, какими их видит клиент: формы взяты из живого API.
REPO_JSON = {"full_name": "owner/repo", "default_branch": "main"}
PR_URL = "https://github.com/owner/repo/pull/7"
PR_JSON = {"number": 7, "title": "тестовый PR", "html_url": PR_URL}
FILES_JSON = [{"filename": "day21/backend/api/main.py", "status": "modified", "additions": 1,
               "deletions": 0, "changes": 1, "patch": "@@"}]
DIFF_TEXT = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n+x\n"
RATE_JSON = {"resources": {"core": {"limit": 60, "remaining": 54, "used": 6,
                                   "reset": 1791918354}}}

#: Токен длиннее маски — проверяются и заголовок, и маска.
TOKEN = "ghp_1234567890"


class FakeAPI:
    """Транспорт-хендлер: разводит пути GitHub и записывает полученные запросы."""

    def __init__(self, *, error: Exception = None, status: int = 0,
                 message: str = "", headers: dict = None) -> None:
        self.requests: list = []
        self.error = error
        self.status = status
        self.message = message
        self.headers = dict(headers or {})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.status:
            return httpx.Response(self.status, json={"message": self.message},
                                  headers=self.headers)
        path = request.url.path
        if path == "/rate_limit":
            return httpx.Response(200, json=RATE_JSON)
        if path == "/repos/owner/repo":
            return httpx.Response(200, json=REPO_JSON)
        if path == "/repos/owner/repo/pulls/7":
            if request.headers.get("accept") == ACCEPT_DIFF:
                return httpx.Response(200, text=DIFF_TEXT)
            return httpx.Response(200, json=PR_JSON)
        if path == "/repos/owner/repo/pulls/7/files":
            return httpx.Response(200, json=FILES_JSON)
        if path == "/repos/owner/repo/pulls/7/reviews":
            return httpx.Response(200, json={"html_url": f"{PR_URL}#pullrequestreview-1"})
        return httpx.Response(404, json={"message": "Not Found"})

    def path(self, index: int = -1) -> str:
        """Путь запроса по номеру в журнале (по умолчанию последнего)."""
        return self.requests[index].url.path


def make_client(api: FakeAPI, token: str = TOKEN) -> GitHubClient:
    """Клиент на подменённом транспорте: ни одного настоящего соединения."""
    return GitHubClient(token=token, transport=httpx.MockTransport(api))


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/owner/repo", ("owner", "repo")),
    ("https://github.com/owner/repo.git", ("owner", "repo")),
    ("git@github.com:owner/repo.git", ("owner", "repo")),
    ("https://github.com/fastapi/fastapi/", ("fastapi", "fastapi")),
    ("  https://github.com/owner/repo  ", ("owner", "repo")),
])
def test_parse_repo_url_forms(url, expected):
    """Три формы URL из задания и хвостовой слэш дают пару owner/repo."""
    assert GitHubClient.parse_repo_url(url) == expected


@pytest.mark.parametrize("url", ["not a url", "github.com/a/b", "",
                                "https://github.com/a/b/tree/main"])
def test_parse_repo_url_rejects_garbage(url):
    """Мусор отклоняется явно: иначе он превратился бы в 404 без объяснения."""
    with pytest.raises(GitHubError) as exc:
        GitHubClient.parse_repo_url(url)
    assert "Не похоже на URL репозитория GitHub" in str(exc.value)


def test_requests_carry_accept_and_token():
    """Чтения PR идут своими путями: Accept diff-а и Bearer-токен — в заголовках."""
    api = FakeAPI()
    client = make_client(api)
    try:
        assert client.get_repo("owner", "repo") == REPO_JSON
        assert client.get_pr("owner", "repo", 7) == PR_JSON
        assert client.get_pr_diff("owner", "repo", 7) == DIFF_TEXT
        assert client.get_changed_files("owner", "repo", 7) == FILES_JSON
    finally:
        client.close()
    paths = [request.url.path for request in api.requests]
    assert paths == ["/repos/owner/repo", "/repos/owner/repo/pulls/7",
                     "/repos/owner/repo/pulls/7", "/repos/owner/repo/pulls/7/files"]
    assert api.requests[0].headers["accept"] == ACCEPT_JSON
    assert api.requests[2].headers["accept"] == ACCEPT_DIFF
    assert api.requests[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_anonymous_client_has_no_authorization():
    """Без токена клиент читает публичные репозитории анонимно — заголовка нет."""
    api = FakeAPI()
    client = make_client(api, token="")
    try:
        client.get_repo("owner", "repo")
    finally:
        client.close()
    assert "authorization" not in api.requests[0].headers


def test_post_review_comment_sends_body_and_event():
    """Публикация — POST отзыва с телом ревью и событием COMMENT; ссылка из ответа."""
    api = FakeAPI()
    client = make_client(api)
    try:
        comment = client.post_review_comment("owner", "repo", 7, "## ревью")
    finally:
        client.close()
    assert comment["html_url"] == f"{PR_URL}#pullrequestreview-1"
    request = api.requests[-1]
    assert request.method == "POST"
    assert request.url.path == "/repos/owner/repo/pulls/7/reviews"
    assert json.loads(request.content.decode("utf-8")) == {"body": "## ревью",
                                                           "event": "COMMENT"}


@pytest.mark.parametrize("status,expected", [
    (404, "GitHub не нашёл PR (404)"),
    (401, "GitHub отклонил токен (401)"),
    (422, "GitHub отклонил запрос (422)"),
])
def test_error_texts_by_status(status, expected):
    """Коды отказа переводятся в текст с причиной и HTTP-кодом."""
    client = make_client(FakeAPI(status=status, message="Ошибка"))
    try:
        with pytest.raises(GitHubError) as exc:
            client.get_pr("owner", "repo", 7)
    finally:
        client.close()
    assert exc.value.status_code == status
    assert str(exc.value).startswith(expected)


def test_rate_limit_403_is_told_apart():
    """403 с нулевым остатком — это лимит, а не «нет прав»: текст говорит о сбросе."""
    api = FakeAPI(status=403, message="API rate limit exceeded",
                  headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "60",
                           "X-RateLimit-Reset": "1791918354"})
    client = make_client(api)
    try:
        with pytest.raises(GitHubError) as exc:
            client.get_pr("owner", "repo", 7)
    finally:
        client.close()
    assert "rate limit исчерпан" in str(exc.value)
    assert "1791918354" in str(exc.value)
    other = make_client(FakeAPI(status=403, message="Resource not accessible"))
    try:
        with pytest.raises(GitHubError) as exc:
            other.get_pr("owner", "repo", 7)
    finally:
        other.close()
    assert "нет прав" in str(exc.value)


def test_transport_failure_is_unavailable():
    """Сбой транспорта: код 0 и текст про недоступность, а не «HTTP 0»."""
    client = make_client(FakeAPI(error=httpx.ConnectError("нет соединения")))
    try:
        with pytest.raises(GitHubError) as exc:
            client.get_repo("owner", "repo")
    finally:
        client.close()
    assert exc.value.status_code == 0
    assert "GitHub недоступен: ConnectError" in str(exc.value)


def test_health_reports_limit_and_degrades():
    """Готовность: остаток лимита при живом API и ``degraded`` при отказе — без исключений."""
    client = make_client(FakeAPI())
    try:
        health = client.health()
    finally:
        client.close()
    assert health["status"] == "ok" and health["authenticated"] is True
    assert health["rate_limit"] == {"limit": 60, "remaining": 54, "used": 6,
                                    "reset": 1791918354}
    assert health["token"] == "ghp_***"
    broken = make_client(FakeAPI(error=httpx.ConnectError("нет соединения")))
    try:
        degraded = broken.health()
    finally:
        broken.close()
    assert degraded["status"] == "degraded" and degraded["rate_limit"] == {}
    assert "недоступен" in degraded["error"]


def test_token_from_environment_and_mask(monkeypatch):
    """Токен читается из окружения, наружу отдаётся маской; пустой — пустая строка."""
    monkeypatch.setenv(TOKEN_ENV, "ghp_abcdefgh")
    assert github_token() == "ghp_abcdefgh"
    assert mask_token("ghp_abcdefgh") == "ghp_***"
    assert mask_token("abc") == "***"
    assert mask_token("") == ""
