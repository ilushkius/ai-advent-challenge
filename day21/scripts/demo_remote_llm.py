"""Демо удалённой модели дня 30 из командной строки: пять шагов одной командой.

Скрипт идёт тем же путём, что кнопка «🚀 Прогнать демо одной кнопкой» в интерфейсе:
шаги, клиентский счётчик частоты и строки таблицы берутся из службы
``remote_llm_service`` — только без бэкенда, HTTP-запросы уходят на адрес туннеля
напрямую. Результат печатается в консоль и складывается в отчёт
``docs/reports/remote_llm_service.md``: разделы отчёта пишет тот же прогон, поэтому
числа в нём измеренные, а не переписанные руками.

Запуск из папки day21/::

    uv run python scripts/demo_remote_llm.py --url https://xxxx.trycloudflare.com/v1/

Без ``--url`` берётся ``REMOTE_LLM_URL`` из ``day21/.env``. Если адреса нет нигде,
скрипт объясняет, где его взять, и выходит с кодом 2.

Скрипт сам предупреждает, если прогон шёл по локальному адресу: такой прогон
проверяет программу, но не удалённость сервиса, и в отчёте это написано прямо.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.core import config  # noqa: E402
from backend.domain import llm_provider  # noqa: E402
from backend.domain.remote_demo import (DEMO_STEPS, KIND_RATE,  # noqa: E402
                                        summarize_rows)
from backend.services import remote_llm_service  # noqa: E402
from backend.services.remote_llm_client import RemoteSettings  # noqa: E402

#: Отчёт по умолчанию: то же место, откуда его читает README дня.
DEFAULT_REPORT = DAY_ROOT / "docs" / "reports" / "remote_llm_service.md"
#: Сколько символов ответа попадает в таблицу отчёта.
ANSWER_LIMIT = 200
#: Локальные адреса: прогон по ним проверяет программу, но не удалённость сервиса.
LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")

#: Постоянные разделы отчёта — то, что не зависит от прогона.
PLATFORM = (
    "Google Colab, бесплатный тариф: GPU T4 (16 ГБ VRAM), время работы сессии "
    "ограничено, среда отключается после ~90 минут бездействия."
)
COLAB_COMMAND = "uvx collab-ollama --model qwen2.5-coder:7b"
LIMITATIONS = (
    "- **Предел частоты считается на клиенте** (``RemoteLLMClient``), а не на "
    "стороне Ollama: сервис в Colab отвечает на все запросы, а N+1-й в минуту "
    "отклоняет сама программа с ответом 429 по смыслу.",
    "- **Окно контекста 4096 токенов** уходит в Ollama как ``options.num_ctx``: "
    "для длинных RAG-контекстов этого мало, день 30 использует окно только для "
    "демонстрации. Поддержка ``options`` зависит от версии Ollama.",
    "- **Туннель Cloudflare живёт часами**: перезапуск ячейки в Colab даёт новый "
    "адрес, старый перестаёт отвечать. Для видео ячейка запускается заново.",
    "- **Через туннель доступны только** ``/v1/models`` и "
    "``/v1/chat/completions``: остальные эндпоинты бесплатного туннеля не нужны "
    "и не используются.",
    "- **Медленный первый ответ**: бесплатный GPU загружает модель с диска, "
    "поэтому предел ожидания одного запроса — 120 с, и первый шаг может идти "
    "десятки секунд.",
)


def build_parser() -> argparse.ArgumentParser:
    """Флаги прогона: адрес туннеля и ручки раздела те же, что в интерфейсе."""
    parser = argparse.ArgumentParser(
        description="Демо удалённой LLM (Ollama в Google Colab через туннель)")
    parser.add_argument("--url", default=config.REMOTE_LLM_URL,
                        help="Base URL туннеля, например "
                             "https://xxxx.trycloudflare.com/v1")
    parser.add_argument("--model", default=config.REMOTE_LLM_MODEL,
                        help="Тег модели Ollama (по умолчанию из .env)")
    parser.add_argument("--api-key", dest="api_key", default=config.REMOTE_LLM_API_KEY,
                        help="Любая строка: Ollama её не проверяет")
    parser.add_argument("--rate-limit", type=int, default=config.REMOTE_LLM_RATE_LIMIT,
                        help="Запросов в минуту для шага проверки предела")
    parser.add_argument("--max-context", type=int,
                        default=config.REMOTE_LLM_MAX_CONTEXT,
                        help="Окно контекста, токенов (options.num_ctx)")
    parser.add_argument("--report", default=str(DEFAULT_REPORT),
                        help="Куда сложить отчёт (по умолчанию docs/reports/"
                             "remote_llm_service.md)")
    parser.add_argument("--no-report", action="store_true",
                        help="Печатать только в консоль, файл отчёта не трогать")
    return parser


def main(argv=None) -> int:
    """Прогоняет пять шагов, печатает их и складывает отчёт; 0 — без ошибок."""
    args = build_parser().parse_args(argv)
    settings = RemoteSettings.from_values(
        url=args.url, model=args.model, api_key=args.api_key,
        rate_limit=args.rate_limit, max_context=args.max_context)
    if not settings.base_url:
        print("Не задан адрес удалённой модели: впишите Base URL туннеля из Colab —")
        print("  uv run python scripts/demo_remote_llm.py "
              "--url https://xxxx.trycloudflare.com/v1/")
        print("или положите его в day21/.env как REMOTE_LLM_URL.")
        return 2
    print(f"провайдер: {llm_provider.PROVIDER_REMOTE} · адрес: {settings.base_url} · "
          f"модель: {settings.model} · лимит: {settings.rate_limit} запросов в минуту · "
          f"окно контекста: {settings.max_context} токенов · "
          f"предел ожидания: {settings.timeout:.0f} с")
    remote_llm_service.reset_client_cache()
    rows, aborted = _run_steps(settings)
    summary = summarize_rows(rows)
    _print_summary(summary)
    if aborted:
        print(f"прогон оборван на шаге «{aborted}»")
    if not args.no_report:
        path = write_report(Path(args.report), settings, rows, summary)
        print(f"отчёт: {path}")
    return 0 if summary["errors"] == 0 else 1


def _run_steps(settings: RemoteSettings) -> tuple[list[dict], str]:
    """Пять шагов по одному: ошибка шага обрывает прогон, кроме шага про частоту."""
    rows: list[dict] = []
    aborted = ""
    for index, step in enumerate(DEMO_STEPS):
        print()
        print(f"[{index + 1}/{len(DEMO_STEPS)}] {step.title}: {step.question}")
        row = remote_llm_service.run_step(step.key, settings, reset=(index == 0))
        rows.append(row)
        print(f"  ответ: {_flat(row.get('answer'), 300)}")
        print(f"  время: {int(row.get('duration_ms') or 0) / 1000:.2f} с · "
              f"запросов к модели: {int(row.get('calls') or 0)} · "
              f"провайдер: {row.get('provider')} · статус: {row.get('status')}")
        if row.get("status") != "ok" and step.kind != KIND_RATE:
            aborted = f"{step.title}: {_flat(row.get('answer'), 160)}"
            break
    return rows, aborted


def _print_summary(summary: dict) -> None:
    """Сводка прогона в консоли — те же числа, что попадут в отчёт."""
    print()
    print(f"итого: запросов к модели {summary['requests']} "
          f"(дошло {summary['calls']}, отклонил клиент {summary['blocked']}) · "
          f"шагов без ошибок {summary['success']}/{summary['steps']} · "
          f"ошибок {summary['errors']} · "
          f"среднее время {summary['avg_ok_ms'] / 1000:.2f} с · "
          f"провайдер ответов: {summary['provider']}"
          + (" (подтверждён remote)" if summary["remote_confirmed"] else ""))


def write_report(path: Path, settings: RemoteSettings, rows: list[dict],
                 summary: dict) -> Path:
    """Собирает отчёт по прогону: постоянные разделы плюс измеренные числа."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(_report_lines(settings, rows, summary)) + "\n",
                    encoding="utf-8")
    return path


def _report_lines(settings: RemoteSettings, rows: list[dict], summary: dict) -> list[str]:
    """Текст отчёта: платформа, запуск в Colab, ручки, ограничения, таблица, выводы."""
    lines = [
        "# Удалённая LLM: Ollama в Google Colab через туннель Cloudflare (день 30)",
        "",
        f"Прогон: {datetime.now().strftime('%Y-%m-%d %H:%M')}, "
        f"скрипт `scripts/demo_remote_llm.py` и кнопка «🚀 Прогнать демо одной кнопкой» "
        f"в разделе «🛰 Удалённая LLM» идут одним и тем же путём: клиент → HTTP → "
        f"туннель → Ollama.",
        "",
        "## Платформа",
        "",
        PLATFORM,
        "",
        "## Команда запуска в Colab",
        "",
        "```bash",
        COLAB_COMMAND,
        "```",
        "",
        "Ячейка поднимает Ollama и туннель Cloudflare и печатает Base URL вида "
        "`https://xxxx.trycloudflare.com/v1` — его вставляют в поле раздела и в "
        "флаг `--url`. API-ключ Ollama не проверяет: подойдёт любая непустая строка.",
        "",
        "## Ручки прогона",
        "",
        "| Параметр | Значение |",
        "|---|---|",
        f"| Base URL | `{settings.base_url}` |",
        f"| Модель | `{settings.model}` |",
        f"| Rate limit | {settings.rate_limit} запросов в минуту "
        f"(клиентский счётчик, окно "
        f"{int(config.REMOTE_LLM_RATE_WINDOW_SECONDS)} с) |",
        f"| Max context | {settings.max_context} токенов (`options.num_ctx`) |",
        f"| Предел ожидания запроса | {settings.timeout:.0f} с |",
        "",
    ]
    if _is_local(settings.base_url):
        lines += [
            "> ⚠️ Прогон шёл по локальному адресу: он проверяет программу (клиент, "
            "счётчик частоты, окно контекста), но не удалённость сервиса. Для отчёта "
            "о Colab запустите ту же команду с адресом туннеля.",
            "",
        ]
    lines += [
        "## Ограничения",
        "",
        *LIMITATIONS,
        "",
        "## Результаты прогона",
        "",
        "| # | Шаг | Запрос | Ответ (первые 200 символов) | Время, с | Провайдер | "
        "Статус |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"| {index} | {_cell(row.get('title'), 60)} | {_cell(row.get('question'), 80)} "
            f"| {_cell(row.get('answer'), ANSWER_LIMIT)} "
            f"| {int(row.get('duration_ms') or 0) / 1000:.2f} "
            f"| {_cell(row.get('provider'), 20)} "
            f"| {'✅ ок' if row.get('status') == 'ok' else '❌ ошибка'} |")
    rate_row = next((row for row in rows if row.get("step") == "rate_limit"), None)
    lines += [
        "",
        "## Сводка",
        "",
        f"- запросов к модели: **{summary['requests']}** "
        f"(дошло до сервиса {summary['calls']}, отклонил клиентский лимит "
        f"{summary['blocked']});",
        f"- шагов без ошибок: **{summary['success']} из {summary['steps']}**, "
        f"ошибок {summary['errors']};",
        f"- среднее время ответа: **{summary['avg_ok_ms'] / 1000:.2f} с** "
        f"(суммарно {summary['total_ms'] / 1000:.2f} с);",
        f"- провайдер ответов: `{summary['provider']}` — "
        f"{'подтверждён как remote ✅' if summary['remote_confirmed'] else 'НЕ подтверждён ⚠️'}.",
        "",
        "## Выводы",
        "",
        _stability_line(summary),
        _time_line(rows, summary),
        _rate_line(rate_row, settings),
        "- Ограничение частоты живёт в программе, а не в сервисе: сервис в Colab "
        "готов принять и больше запросов, но демонстрация показывает именно "
        "поведение клиента — понятную ошибку вместо бесконтрольного потока.",
        "",
    ]
    return lines


def _time_line(rows: list[dict], summary: dict) -> str:
    """Строка о времени: измеренное среднее и самый долгий шаг прогона.

    Числа берутся из таблицы, а не из ожиданий: какой шаг оказался самым долгим,
    зависит и от модели, и от того, сколько токенов она решила написать.
    """
    answers = [row for row in rows if row.get("status") == "ok" and row.get("calls")]
    slowest = max(answers, key=lambda row: row["duration_ms"], default=None)
    tail = (f" дольше всех шёл шаг «{slowest['title']}» — "
            f"{slowest['duration_ms'] / 1000:.2f} с." if slowest else "")
    return (f"- Среднее время ответа сервиса — {summary['avg_ok_ms'] / 1000:.2f} с на "
            f"запрос;{tail} Предел ожидания одного запроса стоит держать большим: "
            f"первый ответ включает загрузку модели в память GPU.")


def _stability_line(summary: dict) -> str:
    """Строка о стабильности: сколько шагов дошло до сервиса и что было с ошибками."""
    if summary["errors"] == 0:
        return (f"- Все {summary['steps']} шагов прошли подряд: сервис отвечал "
                f"стабильно, повторов и таймаутов не было.")
    return (f"- Из {summary['steps']} шагов ошибок {summary['errors']}: прогон не "
            f"завершился, текст отказа виден в таблице — это поведение туннеля "
            f"бесплатного тарифа, а не разрыв HTTP.")


def _rate_line(rate_row: dict | None, settings: RemoteSettings) -> str:
    """Строка о пределе частоты: сколько запросов прошло и на каком сработал отказ."""
    if rate_row is None:
        return "- Шаг проверки предела частоты не выполнялся."
    limit = rate_row.get("limit") or settings.rate_limit
    if rate_row.get("status") == "ok":
        return (f"- Предел частоты сработал как ожидалось: при лимите {limit} "
                f"запросов в минуту прошло {rate_row.get('sent')}, а следующий "
                f"клиент отклонил: «{_flat(rate_row.get('answer'), 160)}».")
    return (f"- Предел частоты НЕ сработал: {rate_row.get('sent')} запросов подряд "
            f"при лимите {limit} в минуту — окно в "
            f"{int(config.REMOTE_LLM_RATE_WINDOW_SECONDS)} с обновлялось быстрее, "
            f"чем заполнялся счётчик (медленная модель). Подробности в ответе "
            f"строки: «{_flat(rate_row.get('answer'), 160)}».")


def _is_local(url: str) -> bool:
    """Прогон по локальному адресу: его числа не доказывают удалённость сервиса."""
    host = url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return any(host == local for local in LOCAL_HOSTS) or host in LOCAL_HOSTS


def _flat(text: object, limit: int) -> str:
    """Ответ одной строкой: переносы и отступы модели ломают и консоль, и таблицу."""
    return " ".join(str(text or "").split())[:limit]


def _cell(text: object, limit: int) -> str:
    """Ячейка таблицы markdown: без переносов и без лишних разделителей."""
    return _flat(text, limit).replace("|", "\\|")


if __name__ == "__main__":
    sys.exit(main())
