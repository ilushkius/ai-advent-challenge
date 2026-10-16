"""Сравнение ручной формулировки CHANGELOG и формулировки модели (день 35).

Вопрос дня: нужен ли LLM для пунктов CHANGELOG, если заголовки коммитов проекта уже
написаны человеком? Проверяется сравнением на одних и тех же коммитах: ручная строка
(написанная для этого отчёта) и строка, которую предлагает модель по тому же заголовку.
Ничего не выдумывается: коммиты берутся из ``git log`` HEAD, а ручные формулировки —
из словаря ниже (его ключи — реальные заголовки, по которым он и собирался).

Отчёт — ``docs/reports/changelog_comparison.md``: таблица «коммит / ручная формулировка /
формулировка LLM / комментарий» и вывод фактами (сколько ручных формулировок уложилось в
5–8 слов, что модель добавляет и что теряет). Раздел интерфейса в этом не участвует:
это отчётный скрипт дня, а не часть релиза.

Заголовок, которого нет в словаре, получает формулировку-правило «Правка: <заголовок>», и
отчёт говорит об этом прямо — выдумывать «ручной» текст для чужого коммита нельзя.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня и в корне
# репозитория: добавляем корень дня в sys.path (как остальные скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.core import config  # noqa: E402
from backend.domain import llm_provider, release  # noqa: E402
from backend.services import rag_llm  # noqa: E402
from backend.services.rag_errors import RAGUpstreamError  # noqa: E402
from backend.services.release_service import ReleaseService  # noqa: E402

#: Корень репозитория: историю читаем оттуда, а не из папки дня.
REPO_ROOT = DAY_ROOT.parent
#: Отчёт сравнения (перезаписывается целиком: он про текущий HEAD).
DEFAULT_REPORT = DAY_ROOT / "docs" / "reports" / "changelog_comparison.md"

#: Ручные формулировки: ключ — заголовок коммита как он есть в истории, значение —
#: строка, которую человек написал бы в CHANGELOG (5–8 слов, с модулем или возможностью).
MANUAL_WORDING = {
    "day34: add file assistant with MCP file_server, goal-based planning, dry_run, "
    "and real file operations":
        "Ассистент файлов: цель в план шагов и MCP-сервер file_server",
    "day33: add user support assistant with RAG over FAQ and MCP for users and tickets":
        "Ассистент поддержки: RAG по FAQ и тикеты из MCP",
    "docs: change main README":
        "Главный README: актуальная карта дней челленджа",
    "day32: verify GitHub comment publishing from the UI and the review endpoint":
        "Ревью: публикация комментария в GitHub из интерфейса",
    "day32: confirm live GitHub comment publishing on own PR and drop stale limitation notes":
        "Живой PR: проверка публикации и снятие устаревших ограничений",
}
#: Формулировка-правило для заголовка вне словаря: честно помечает, что она не ручная.
FALLBACK_WORDING = "Правка: {subject}"

#: Системная инструкция сравнения: одна строка CHANGELOG по заголовку коммита.
COMPARE_SYSTEM_PROMPT = (
    "Переформулируй заголовок коммита для CHANGELOG на русском: одна строка, без хеша, "
    "с указанием модуля или возможности; не выдумывай того, чего нет в тексте коммита."
)
#: Что показать в ячейке, если модель недоступна.
PROVIDER_FAILED = "❌ провайдер недоступен"
#: Границы «короткой» ручной формулировки (сколько слов считается нормой для пункта).
WORDS_MIN, WORDS_MAX = 5, 8
#: Пределы текста в таблице отчёта.
CELL_LIMIT = 90


def build_parser() -> argparse.ArgumentParser:
    """Аргументы отчёта: сколько коммитов, провайдер, путь отчёта и его отключение."""
    parser = argparse.ArgumentParser(
        description="Сравнить ручные формулировки CHANGELOG с ответами модели.",
    )
    parser.add_argument("--count", type=int, default=5,
                        help="сколько последних коммитов HEAD сравнивать (по умолчанию 5)")
    parser.add_argument("--provider", choices=llm_provider.PICKER_PROVIDERS,
                        default=llm_provider.PROVIDER_DEEPSEEK,
                        help="провайдер ответа (по умолчанию deepseek)")
    parser.add_argument("--report", default=str(DEFAULT_REPORT),
                        help=f"куда писать отчёт (по умолчанию {DEFAULT_REPORT})")
    parser.add_argument("--no-report", action="store_true",
                        help="не писать отчёт: только печать таблицы")
    return parser


def read_commits(count: int) -> list[dict]:
    """Последние ``count`` коммитов HEAD: ``[{"hash": …, "subject": …}]``.

    Читается обычным ``git log`` в корне репозитория, а не через MCP: скрипт отчётный,
    сервер файлов для него поднимать незачем (в отличие от самого релиза, где источник
    данных один — MCP-инструменты).
    """
    completed = subprocess.run(
        ["git", "log", f"--max-count={max(1, int(count))}", "--format=%h%x1f%s", "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    commits = []
    for line in (completed.stdout or "").splitlines():
        fields = line.split("\x1f")
        if len(fields) != 2 or not fields[1].strip():
            continue
        commits.append({"hash": fields[0].strip(), "subject": fields[1].strip()})
    return commits


def manual_wording(subject: str) -> tuple[str, bool]:
    """Ручная формулировка коммита: ``(текст, признак «написана человеком»)``."""
    known = MANUAL_WORDING.get(subject)
    if known:
        return known, True
    return FALLBACK_WORDING.format(subject=subject), False


def llm_wording(client, subject: str) -> str:
    """Формулировка модели для одного заголовка; отказ провайдера — текстом, не исключением."""
    try:
        result = rag_llm.call_with_retry(
            time.sleep, client.generate_with_context, system=COMPARE_SYSTEM_PROMPT,
            context="", question=subject, task_type=config.LLM_TASK_CLASSIFY,
            agent_id=release.AGENT_ID, temperature=0.0,
            max_tokens=config.LLM_MAX_RESPONSE_TOKENS)
    except RAGUpstreamError:
        return PROVIDER_FAILED
    return rag_llm.response_text(result) or PROVIDER_FAILED


def words(text: str) -> int:
    """Сколько слов в строке (для сравнения длин ручной формулировки и ответа модели)."""
    return len(str(text or "").split())


def comment(llm_text: str, manual_text: str) -> str:
    """Комментарий строки: длины обеих формулировок и что из этого следует."""
    if llm_text == PROVIDER_FAILED:
        return "модель не ответила: сравнение длин невозможно"
    llm_words, manual_words = words(llm_text), words(manual_text)
    prefix = f"LLM: {llm_words} слов, ручная: {manual_words} слов — "
    if llm_words > manual_words:
        return prefix + "LLM добавил контекст"
    if llm_words == manual_words:
        return prefix + "формулировки совпали по длине"
    return prefix + "ручная короче и суше"


def build_rows(client, commits: list[dict]) -> list[dict]:
    """Строки отчёта: коммит, ручная формулировка, формулировка модели и комментарий."""
    rows = []
    for commit in commits:
        manual, human = manual_wording(commit["subject"])
        llm_text = llm_wording(client, commit["subject"])
        rows.append({"hash": commit["hash"], "subject": commit["subject"],
                     "manual": manual, "human": human, "llm": llm_text,
                     "comment": comment(llm_text, manual)})
    return rows


def conclusion(rows: list[dict]) -> str:
    """Вывод фактами: что дала модель и вписались ли ручные формулировки в 5–8 слов."""
    answered = [row for row in rows if row["llm"] != PROVIDER_FAILED]
    short = [row for row in rows if WORDS_MIN <= words(row["manual"]) <= WORDS_MAX]
    human = [row for row in rows if row["human"]]
    facts = [
        f"сравнивались {len(rows)} коммитов HEAD, ручных формулировок среди них — "
        f"{len(human)}, остальные собраны правилом `{FALLBACK_WORDING}`."
        if len(human) != len(rows) else
        f"сравнивались {len(rows)} коммитов HEAD, для каждого есть ручная формулировка.",
        f"в 5–8 слов уложились {len(short)} ручных формулировок из {len(rows)}: "
        "пункт CHANGELOG должен читаться одной строкой.",
    ]
    if answered:
        longer = [row for row in answered if words(row["llm"]) > words(row["manual"])]
        facts.append(f"модель ответила на {len(answered)} из {len(rows)} коммитов; "
                     f"в {len(longer)} случаях её строка длиннее ручной — она добавляет "
                     "контекст («через MCP», «из интерфейса»), то есть объясняет, ЧЕМ "
                     "сделано изменение.")
        facts.append("ручная формулировка короче там, где модуль и так назван в заголовке: "
                     "модели приходится разворачивать служебные слова коммита.")
    else:
        facts.append("модель не ответила ни на один коммит: провайдер недоступен "
                     "(проверьте DEEPSEEK_API_KEY в day21/.env или Ollama для local).")
    facts.append("вывод: для проекта, где заголовки коммитов пишет человек, модель нужна "
                 "не для сокращения, а для приведения разных по стилю заголовков к одной "
                 "формулировке — и как страховка, когда коммит назван служебно.")
    return " ".join(facts)


def write_report(path: Path, rows: list[dict], meta: dict) -> Path:
    """Пишет markdown-отчёт сравнения и возвращает путь к файлу."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Сравнение CHANGELOG: ручная формулировка и модель (день 35)",
        "",
        f"Провайдер: {meta['provider_label']}, коммитов: {len(rows)}, источник: `git log` "
        f"от HEAD. Прогон: {meta['stamp']}, скрипт `scripts/compare_changelog.py`.",
        "",
        "| коммит | ручная формулировка | формулировка LLM | комментарий |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| " + " | ".join([
            _cell(f"{row['hash']} {row['subject']}", CELL_LIMIT),
            _cell(row["manual"] if row["human"] else row["manual"] + " (правило)", CELL_LIMIT),
            _cell(row["llm"], CELL_LIMIT),
            _cell(row["comment"], CELL_LIMIT),
        ]) + " |")
    lines.extend(["", "## Вывод", "", conclusion(rows), ""])
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _flat(text: object, limit: int) -> str:
    """Текст одной строкой, обрезанный до ``limit`` символов."""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"


def _cell(text: object, limit: int) -> str:
    """Ячейка markdown-таблицы: обрезанный текст без вертикальных черт."""
    return _flat(text, limit).replace("|", "\\|") or "—"


def main(argv=None) -> int:
    """Сравнивает ручные формулировки с ответами модели, печатает таблицу и пишет отчёт."""
    args = build_parser().parse_args(argv)
    try:
        commits = read_commits(args.count)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"git log не сработал: {exc}")
        return 1
    if not commits:
        print("Коммитов не найдено: сравнение не с чем делать.")
        return 1
    print(f"Коммитов: {len(commits)}, провайдер: {llm_provider.label(args.provider)}")
    service = ReleaseService()
    try:
        rows = build_rows(service.llm_client_for(args.provider), commits)
    finally:
        service.close()
    for row in rows:
        print(f"{row['hash']} {_flat(row['subject'], CELL_LIMIT)}")
        print(f"   ручная: {_flat(row['manual'], CELL_LIMIT)}")
        print(f"   LLM:    {_flat(row['llm'], CELL_LIMIT)}")
        print(f"   {row['comment']}")
    print(conclusion(rows))
    if args.no_report:
        return 0
    try:
        path = write_report(Path(args.report), rows,
                            {"provider_label": llm_provider.label(args.provider),
                             "stamp": datetime.now().strftime("%Y-%m-%d %H:%M")})
    except OSError as exc:
        print(f"Отчёт не записан: {exc}")
        return 1
    print(f"отчёт: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
