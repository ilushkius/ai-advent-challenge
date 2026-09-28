"""Инструмент ``fetch_url`` сервера поиска (день 20): страница по HTTP → текст.

Страница берётся у локального стенда (``stub_api_base``, ручка ``/html``): HTTP
настоящий, сети нет. Проверяются очистка HTML (теги, ``<script>``, ``<style>``,
HTML-сущности), обрезка до ``max_chars`` с флагом ``truncated``, пропуск не-HTML
содержимого как есть и три отказа: не-http схема, не-2xx ответ и недоступный
узел — каждый обязан быть ``ToolError`` с причиной.
"""
from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from stub_api import HTML_PAGE, SCRIPT_TEXT, STYLE_TEXT

from mcp_servers.search_server import config, fetch


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    """Снимок настроек модуля: ``configure`` внутри теста не течёт в соседние тесты."""
    for name in ("_timeout", "_http_client"):
        monkeypatch.setattr(fetch, name, getattr(fetch, name))


def test_html_page_is_cleaned_to_text(stub_api_base):
    """HTML → текст: теги сняты, script/style выброшены, сущности раскодированы."""
    result = fetch.fetch_url(f"{stub_api_base}/html")

    assert result["url"] == f"{stub_api_base}/html"
    assert result["status"] == 200
    assert result["content_type"].startswith("text/html")
    # Текст страницы начинается с <title>: он тоже текст, и терять его незачем.
    assert result["text"].startswith("Стенд дня 20")
    assert "Заголовок стенда" in result["text"]
    assert "Первый абзац «страницы» для чтения." in result["text"]
    assert '"кавычки"' in result["text"] and "& амперсанд" in result["text"]
    assert "&laquo;" not in result["text"] and "<p>" not in result["text"]
    # Содержимое script/style — не текст страницы, и в ответ инструмента не едет.
    assert SCRIPT_TEXT not in result["text"] and "alert" not in result["text"]
    assert STYLE_TEXT not in result["text"] and "color: red" not in result["text"]
    assert result["truncated"] is False
    assert result["chars"] == len(result["text"])


def test_long_page_is_truncated(stub_api_base):
    """Текст длиннее ``max_chars`` обрезается, и это видно по флагу ``truncated``."""
    full = fetch.fetch_url(f"{stub_api_base}/html", max_chars=config.FETCH_MAX_CHARS_MAX)
    result = fetch.fetch_url(f"{stub_api_base}/html", max_chars=config.FETCH_MAX_CHARS_MIN)

    assert len(full["text"]) > config.FETCH_MAX_CHARS_MIN, "страница стенда коротка"
    assert result["truncated"] is True
    assert result["chars"] == config.FETCH_MAX_CHARS_MIN
    assert result["text"] == full["text"][:config.FETCH_MAX_CHARS_MIN]
    assert "Четвёртый абзац" not in result["text"]


def test_max_chars_below_minimum_is_clamped(stub_api_base):
    """Слишком маленький ``max_chars`` зажимается до минимума, а не обнуляет текст."""
    result = fetch.fetch_url(f"{stub_api_base}/html", max_chars=10)
    assert result["chars"] == config.FETCH_MAX_CHARS_MIN
    assert result["truncated"] is True


def test_non_html_content_is_returned_as_is(stub_api_base):
    """Не-HTML содержимое (JSON стенда) не чистится: теги снимать не из чего."""
    result = fetch.fetch_url(f"{stub_api_base}/posts/1", max_chars=500)

    assert result["content_type"].startswith("application/json")
    assert result["text"].startswith("{") and '"title": "Post 1"' in result["text"]
    assert result["truncated"] is False


def test_non_http_scheme_is_rejected():
    """Схема кроме http(s) — ошибка до запроса: локальные файлы не читаются."""
    with pytest.raises(ToolError) as exc:
        fetch.fetch_url("file:///C:/Windows/win.ini")
    assert "должен начинаться с http:// или https://" in str(exc.value)


def test_not_found_reports_the_status_code(stub_api_base):
    """Ответ 404 — ``ToolError`` с кодом в тексте, а не пустая страница."""
    with pytest.raises(ToolError) as exc:
        fetch.fetch_url(f"{stub_api_base}/posts/999")
    assert "ответил кодом 404" in str(exc.value)


def test_unreachable_host_is_reported():
    """Недоступный узел — ``ToolError`` с причиной, а не исключение httpx."""
    fetch.configure(timeout=1.0)
    with pytest.raises(ToolError) as exc:
        fetch.fetch_url("http://127.0.0.1:1/")
    assert "Не удалось запросить" in str(exc.value)


def test_html_to_text_drops_hidden_blocks():
    """Проверка самой очистки: комментарии, script и style не попадают в текст."""
    cleaned = fetch.html_to_text(
        "<html><body><!-- скрыто --><p>видно</p>"
        f"<script>{SCRIPT_TEXT}</script><style>{STYLE_TEXT}</style></body></html>"
    )
    assert "видно" in cleaned
    assert "скрыто" not in cleaned
    assert SCRIPT_TEXT not in cleaned and STYLE_TEXT not in cleaned


def test_html_page_fixture_contains_hidden_blocks():
    """Стенд обязан отдавать и script, и style: иначе очистка не проверена."""
    assert "<script>" in HTML_PAGE and "<style>" in HTML_PAGE
