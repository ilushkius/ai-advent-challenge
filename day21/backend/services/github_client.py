"""Клиент GitHub REST API (день 32): URL репозитория и номер PR → diff, файлы, комментарий.

Отдельный модуль, а не часть службы ревью: у GitHub своя предметная область — код
ответа, признаки исчерпанного rate limit, маска токена в логах и health по
``GET /rate_limit``. Служба ревью только пользуется результатом: она берёт diff и
список файлов, а весь HTTP, тексты ошибок и заголовки ``Accept`` живут здесь.

Токен необязателен: без ``GITHUB_TOKEN`` публичные репозитории читаются анонимно
(лимит 60 запросов в час на IP вместо 5000 с токеном), а публикация комментария
требует токена с правом на запись. Токен читается из окружения, затем из
``day21/.env``, уходит в заголовке ``Authorization: Bearer`` и наружу отдаётся только
маской (``mask_token``) — ни в лог, ни в health он не попадает целиком.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from shared.logging_utils import get_logger

from ..core.env_file import read_env_value

logger = get_logger(__name__)

API_BASE = "https://api.github.com"
TOKEN_ENV = "GITHUB_TOKEN"
ACCEPT_JSON = "application/vnd.github.v3+json"
ACCEPT_DIFF = "application/vnd.github.v3.diff"
REQUEST_TIMEOUT = 30.0
USER_AGENT = "day21-code-review"
TOKEN_MASK_CHARS = 4
#: Образец URL репозитория: https-форма, .git и scp-форма git@github.com:owner/repo.git.
REPO_URL_PATTERN = re.compile(
    r"^(?:git@github\.com:|https?://(?:www\.)?github\.com/|ssh://git@github\.com/)"
    r"([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
REPO_URL_ERROR = ("Не похоже на URL репозитория GitHub: {url} (ожидается "
                  "https://github.com/owner/repo, https://github.com/owner/repo.git "
                  "или git@github.com:owner/repo.git)")
UNAVAILABLE_ERROR = "GitHub недоступен: {error}"
ERROR_TEXTS = {
    401: "GitHub отклонил токен (401): проверьте GITHUB_TOKEN в day21/.env",
    403: "GitHub отказал в доступе (403): у токена нет прав на это действие",
    404: "GitHub не нашёл {what} (404): проверьте URL репозитория и номер PR",
    422: "GitHub отклонил запрос (422): проверьте параметры запроса",
}
RATE_LIMIT_ERROR = ("GitHub rate limit исчерпан (403): осталось {remaining} из {limit} "
                    "запросов, сброс в {reset} UTC — подождите или задайте GITHUB_TOKEN "
                    "в day21/.env (с токеном лимит 5000 в час)")

__all__ = ["ACCEPT_DIFF", "ACCEPT_JSON", "API_BASE", "ERROR_TEXTS", "GitHubClient",
           "GitHubError", "RATE_LIMIT_ERROR", "REPO_URL_ERROR", "REPO_URL_PATTERN",
           "REQUEST_TIMEOUT", "TOKEN_ENV", "TOKEN_MASK_CHARS", "UNAVAILABLE_ERROR",
           "USER_AGENT", "github_token", "mask_token"]


def github_token() -> str:
    """Токен GitHub из переменной окружения или day21/.env; пусто — анонимный доступ."""
    return str(os.environ.get(TOKEN_ENV) or read_env_value(TOKEN_ENV) or "").strip()


def mask_token(token: str) -> str:
    """Токен для логов и health: первые 4 символа и звёздочки (короткий — только звёзды)."""
    text = str(token or "")
    if not text:
        return ""
    return f"{text[:TOKEN_MASK_CHARS]}***" if len(text) > TOKEN_MASK_CHARS else "***"


class GitHubError(RuntimeError):
    """Ошибка GitHub API: текст для человека, HTTP-код и путь запроса."""

    def __init__(self, message: str, status_code: int = 0, url: str = "") -> None:
        super().__init__(message)
        self.message = str(message)
        self.status_code = int(status_code)
        self.url = str(url)


class GitHubClient:
    """Тонкая обёртка над REST API: разбор URL, четыре чтения PR и публикация ревью."""

    def __init__(self, *, token: Optional[str] = None, base_url: str = API_BASE,
                 timeout: float = REQUEST_TIMEOUT, transport: Optional[Any] = None) -> None:
        self.token = github_token() if token is None else str(token or "")
        self.base_url = str(base_url)
        self.timeout = float(timeout)
        headers = {"Accept": ACCEPT_JSON, "User-Agent": USER_AGENT}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout,
                                    headers=headers, transport=transport)
        logger.info("GitHub API: %s, токен %s", self.base_url,
                    mask_token(self.token) or "не задан")

    def close(self) -> None:
        """Закрывает HTTP-соединения клиента."""
        self._client.close()

    @staticmethod
    def parse_repo_url(url: str) -> Tuple[str, str]:
        """Пара ``(owner, repo)`` из URL репозитория; негодный URL — ``GitHubError``.

        Понимает ``https://github.com/owner/repo``, форму с ``.git``, хвостовым ``/`` и
        scp-форму ``git@github.com:owner/repo.git``: именно так URL выглядит в задании и
        в выводе ``git remote -v``. Мусор отклоняется явно — дальше он превратился бы в
        404 от GitHub без объяснения причины.
        """
        match = REPO_URL_PATTERN.match(str(url or "").strip())
        if not match:
            raise GitHubError(REPO_URL_ERROR.format(url=str(url or "").strip()))
        return match.group(1), match.group(2)

    def get_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        """``GET /repos/{owner}/{repo}``: полное имя, видимость, ветка по умолчанию."""
        return dict(self._request("GET", f"/repos/{owner}/{repo}",
                                 what="репозиторий").json() or {})

    def get_pr(self, owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
        """``GET /repos/{owner}/{repo}/pulls/{n}``: метаданные PR (номер, ссылка, статус)."""
        return dict(self._request("GET", self._pr_path(owner, repo, pr_number),
                                  what="PR").json() or {})

    def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Unified diff PR: тот же запрос, что ``get_pr``, но ``Accept: …v3.diff``."""
        response = self._request("GET", self._pr_path(owner, repo, pr_number),
                                 accept=ACCEPT_DIFF, what="PR")
        return str(response.text or "")

    def get_changed_files(self, owner: str, repo: str,
                          pr_number: int) -> List[Dict[str, Any]]:
        """``GET …/pulls/{n}/files``: файлы PR с патчем, добавлениями и удалениями."""
        response = self._request("GET", f"{self._pr_path(owner, repo, pr_number)}/files",
                                 what="PR")
        return list(response.json() or [])

    def post_review_comment(self, owner: str, repo: str, pr_number: int,
                            body: str) -> Dict[str, Any]:
        """``POST …/pulls/{n}/reviews``: публикует ревью комментарием (``COMMENT``).

        Событие именно ``COMMENT``: ``APPROVE`` и ``REQUEST_CHANGES`` меняют состояние
        PR, а от автоматического ревью этого не ждут — оно только оставляет текст.
        """
        response = self._request("POST", f"{self._pr_path(owner, repo, pr_number)}/reviews",
                                 what="PR", json={"body": str(body), "event": "COMMENT"})
        return dict(response.json() or {})

    def health(self) -> Dict[str, Any]:
        """Готовность GitHub: доступность API, признак токена и остаток лимита.

        Исключений не поднимает: эндпоинт нужен для мониторинга, поэтому отказ
        возвращается данными (``status="degraded"`` и текст причины).
        """
        result = {"status": "ok", "service": "github", "api_base": self.base_url,
                  "authenticated": bool(self.token), "token": mask_token(self.token),
                  "rate_limit": {}, "error": ""}
        try:
            payload = dict(self._request("GET", "/rate_limit", what="лимит").json() or {})
        except GitHubError as exc:
            result["status"] = "degraded"
            result["error"] = str(exc)
            return result
        core = dict((payload.get("resources") or {}).get("core") or {})
        result["rate_limit"] = {key: int(core.get(key) or 0)
                                for key in ("limit", "remaining", "used", "reset")}
        return result

    @staticmethod
    def _pr_path(owner: str, repo: str, pr_number: int) -> str:
        """Путь PR: одно место, чтобы номер всегда попадал в адрес целым числом."""
        return f"/repos/{owner}/{repo}/pulls/{int(pr_number)}"

    def _request(self, method: str, path: str, *, accept: str = ACCEPT_JSON,
                 what: str = "объект", **kwargs) -> httpx.Response:
        """Запрос к API: ошибка транспорта и HTTP ≥ 400 — ``GitHubError`` с текстом.

        Тело отказа в текст исключения целиком не попадает (оно уходит в лог): человеку
        нужна причина и код, а не дамп JSON на экран.
        """
        started = time.perf_counter()
        try:
            response = self._client.request(method, path, headers={"Accept": accept},
                                            **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError(UNAVAILABLE_ERROR.format(error=exc.__class__.__name__),
                              0, path) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info("GitHub %s %s → %s (%s мс)", method, path, response.status_code,
                    duration_ms)
        if response.status_code >= 400:
            raise GitHubError(self._error_text(response, what), response.status_code,
                              path)
        return response

    @staticmethod
    def _error_text(response: httpx.Response, what: str) -> str:
        """Текст отказа по коду ответа: лимит отличается от прочих 403 по заголовкам."""
        status = int(response.status_code)
        if status == 404:
            return ERROR_TEXTS[404].format(what=what)
        if status == 403:
            return GitHubClient._rate_limit_text(response) or ERROR_TEXTS[403]
        if status in ERROR_TEXTS:
            return ERROR_TEXTS[status]
        return f"GitHub вернул HTTP {status}: {GitHubClient._message(response)}"

    @staticmethod
    def _rate_limit_text(response: httpx.Response) -> str:
        """Текст про исчерпанный лимит, если 403 — именно про него, иначе пустая строка."""
        remaining = str(response.headers.get("X-RateLimit-Remaining") or "")
        if remaining != "0" and "rate limit" not in GitHubClient._message(response).lower():
            return ""
        return RATE_LIMIT_ERROR.format(
            remaining=remaining or "0",
            limit=str(response.headers.get("X-RateLimit-Limit") or "0"),
            reset=str(response.headers.get("X-RateLimit-Reset") or "0"))

    @staticmethod
    def _message(response: httpx.Response) -> str:
        """Поле ``message`` ответа GitHub (пусто, если тело не JSON или поля нет)."""
        try:
            payload = response.json()
        except ValueError:
            return ""
        if isinstance(payload, dict):
            return str(payload.get("message") or "")
        return ""
