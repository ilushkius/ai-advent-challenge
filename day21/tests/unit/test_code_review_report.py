"""Юнит-тесты разметки отчёта ревью (день 32): markdown и секции файла отчёта.

Проверяется ОДНО поведение — что получает читатель отчёта и комментария в PR: набор
разделов markdown, таблица рисков в порядке приоритетов, обрезка полного ответа модели
и сборка файла отчёта из секций (замена одноимённой секции без дублей, добавление новой
через разделитель). Разметка — единственная часть дня 32, которая живёт не в службе, а
в домене, поэтому тесты идут без модели, индекса и MCP.

Регрессия, ради которой тест и написан: тело секции начинается со своего заголовка
второго уровня (``## 🤖 AI-ревью``), и раньше граница секции искалась по нему — замена
секции оставляла старое тело под новым и отчёт копил дубли.
"""
from __future__ import annotations

from backend.domain import code_review, code_review_report

#: Ответ модели, каким его видит разметка: находки плюс служебные поля ревью.
RECORD = {
    "review_text": "полный ответ модели",
    "bugs": [{"file": "a.py", "line": "3", "issue": "проблема|с трубой", "priority": "P0"}],
    "architecture_issues": [{"file": "b.py", "issue": "слои", "recommendation": "вынести",
                             "priority": "P2"}],
    "recommendations": ["закрывать сессию"],
    "risks": [{"priority": "P0", "file": "a.py", "risk": "утечка"}],
    "sources": [{"source": "day21-docs-usage.md", "section": "Запуск", "score": 0.5}],
    "mcp_tools_used": [],
    "changed_files": ["a.py"],
    "duration_ms": 12,
    "provider": "deepseek",
    "warnings": ["предупреждение шага"],
}


def test_render_markdown_has_all_sections():
    """Markdown ревью: разделы, приоритет с подписью и обрезка полного ответа."""
    text = code_review_report.render_markdown(RECORD, label="PR #7")

    for header in ("## 🤖 AI-ревью: PR #7", "### Изменённые файлы", "### Потенциальные баги",
                   "### Архитектурные проблемы", "### Рекомендации", "### Риски (P0 — P3)",
                   "### Источники RAG", "### Предупреждения"):
        assert header in text
    assert "_Провайдер: deepseek · 12 мс · файлов: 1 · источников RAG: 1_" in text
    assert "| P0 (критично) | a.py | утечка |" in text
    assert "проблема\\|с трубой" in text
    assert "<details><summary>Полный ответ модели</summary>" in text
    empty = code_review_report.render_markdown({}, label="пусто")
    assert "— не найдено" in empty and "— нет" in empty
    assert "<details>" not in empty


#: Запись ревью из GitHub: у локального ревью блока «GitHub PR» нет.
GITHUB_RECORD = dict(RECORD, github_meta={
    "owner": "owner", "repo": "repo", "pr_number": 42,
    "pr_url": "https://github.com/owner/repo/pull/42",
    "changed_files_count": 4, "diff_lines": 222})


def test_render_github_meta_block():
    """Таблица «GitHub PR»: ссылка, размеры и различение публикации комментария."""
    block = code_review_report.render_github_meta(GITHUB_RECORD)

    assert block.startswith("### GitHub PR")
    assert ("| PR | [https://github.com/owner/repo/pull/42]"
            "(https://github.com/owner/repo/pull/42) |") in block
    assert "| Репозиторий | `owner/repo` |" in block
    assert "| Изменённых файлов | 4 |" in block and "| Строк в diff | 222 |" in block
    assert "| Комментарий | не публиковался |" in block
    posted = code_review_report.render_github_meta(
        dict(GITHUB_RECORD, posted=True,
             comment_url="https://github.com/owner/repo/pull/42#pullrequestreview-9"))
    assert ("| Комментарий | [опубликован]"
            "(https://github.com/owner/repo/pull/42#pullrequestreview-9) |") in posted
    assert code_review_report.render_github_meta(RECORD) == ""


def test_report_header_of_github_mode():
    """Заголовок GitHub-отчёта: свой скрипт и команда запуска, а не локальный diff."""
    text = code_review_report.upsert_report_section(
        "", "Ревью PR fastapi/fastapi#16481", "тело",
        header=code_review_report.github_report_header())

    assert code_review.GITHUB_REPORT_TITLE in text
    assert "scripts/run_github_pr_review.py" in text
    assert "--pr-number 16481" in text
    assert code_review.REPORT_TITLE not in text
    assert "## Ревью PR fastapi/fastapi#16481" in text


def test_report_sections_replace_without_duplicates():
    """Секция отчёта заменяется целиком: тело ревью не считается её границей."""
    first = code_review_report.upsert_report_section(
        "", "Ревью diff day30..day31", code_review_report.render_markdown(RECORD))
    second = code_review_report.upsert_report_section(
        first, "Ревью diff day30..day31",
        code_review_report.render_markdown(dict(RECORD, duration_ms=99)))
    other = code_review_report.upsert_report_section(second, "Синтетический PR", "тело")

    assert second.count(code_review.REPORT_TITLE) == 1
    assert second.count("## 🤖 AI-ревью") == 1
    assert "12 мс" not in second and "99 мс" in second
    assert other.count("## 🤖 AI-ревью") == 1
    assert (other.index("\n## Синтетический PR\n")
            > other.index("\n## Ревью diff day30..day31\n"))
    assert code_review_report.SECTION_MARKER.format(title="Синтетический PR") in other
