"""Сборка отчёта об оптимизации затрат на LLM: «до и после» (день 21).

Скрипт запуска: замеряет сценарий (``cost_optimization_measure.py``) и пишет
``docs/reports/cost_optimization.md``. Здесь только рендер markdown и CLI: числа
приходят из замера, формулы стоимости — из домена ``llm_cost``, поэтому отчёт не
может разойтись с журналом ``llm_usage`` и ``GET /llm/usage``.

Запуск из папки day21/::

    uv run python scripts/cost_optimization_report.py
    uv run python scripts/cost_optimization_report.py --report docs/reports/cost_optimization.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня
# и в корне репозитория: добавляем корень дня в sys.path (как другие скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.core import config  # noqa: E402
from backend.core.prompt_builder import PromptBuilder  # noqa: E402
from backend.domain.llm_cost import prices_for  # noqa: E402
from cost_optimization_measure import (  # noqa: E402
    DEFAULT_REPORT,
    LEGACY_MAX_TOKENS,
    REQUESTS,
    measure,
)

def summary_rows(data: dict) -> list[str]:
    """Строки таблицы «нагрузка дня»: две ноги и общий итог.

    Ввод диалога показан дважды: «всего» почти не меняется (новый промпт добавляет
    строку о пределе ответа), а «по полной цене» падает — платит пользователь именно
    за промахи кэша, потому что попадание дешевле обычного ввода.
    """
    dialogue = data["dialogue"]
    heavy = data["heavy"]
    legacy_miss = dialogue["legacy_tokens"]
    new_miss = max(0, dialogue["new_tokens"] - dialogue["cache_hit_tokens"])
    change = ((new_miss - legacy_miss) / legacy_miss * 100) if legacy_miss else 0.0
    dialogue_percent = (1 - dialogue["new_cost"] / dialogue["legacy_cost"]) * 100 \
        if dialogue["legacy_cost"] else 0.0
    heavy_percent = (1 - heavy["cost_after"] / heavy["cost_before"]) * 100 \
        if heavy["cost_before"] else 0.0
    total_before = dialogue["legacy_cost"] + heavy["cost_before"]
    total_after = dialogue["new_cost"] + heavy["cost_after"]
    total_percent = (1 - total_after / total_before) * 100 if total_before else 0.0
    return [
        "| нагрузка дня | было, $ | стало, $ | экономия |",
        "|---|---|---|---|",
        f"| диалог: {data['requests']} запросов (ввод {dialogue['legacy_tokens']} → "
        f"{dialogue['new_tokens']} токенов, из них по полной цене {legacy_miss} → "
        f"{new_miss}, {change:+.1f}%) | {dialogue['legacy_cost']:.6f} "
        f"| {dialogue['new_cost']:.6f} | {dialogue_percent:.1f}% (кэш контекста + сжатие) |",
        f"| тяжёлая задача: пакетная обработка {heavy['files']} артефактов "
        f"({heavy['tokens_before']} → {heavy['tokens_after']} токенов ввода) "
        f"| {heavy['cost_before']:.6f} | {heavy['cost_after']:.6f} "
        f"| {heavy_percent:.1f}% (сжатие + непик {heavy['discount_percent']}%) |",
        f"| **итого за день** | **{total_before:.6f}** | **{total_after:.6f}** "
        f"| **{total_percent:.1f}%** |",
    ]


def lever_rows(data: dict) -> list[str]:
    """Строки таблицы «вклад каждого рычага» — по одной на рычаг.

    Доля считается от стоимости «было» по всему дню. Строка предела длины ответа
    помечена как оценка сверху: она ограничивает вывод, но не сокращает полученный
    ответ, поэтому в итог не входит.
    """
    dialogue = data["dialogue"]
    heavy = data["heavy"]
    summary = data["summary"]
    base = dialogue["legacy_cost"] + heavy["cost_before"] or 1.0

    def share(value: float) -> float:
        """Доля экономии от стоимости «было» в процентах."""
        return value / base * 100

    compression_saving = (summary["compression"]["saving"]
                          + (heavy["cost_before"] - heavy["cost_after"])
                          - summary["off_peak"]["saving"])
    return [
        f"| кэш контекста (стабильный префикс промпта) | {dialogue['cache_hit_tokens']} "
        f"токенов ввода отдано из кэша при цене "
        f"{int(config.LLM_CACHE_INPUT_RATIO * 100)}% от обычного ввода "
        f"| {summary['cache']['saving']:.6f} | {share(summary['cache']['saving']):.1f} |",
        f"| сжатие промптов | снято "
        f"{dialogue['saved_tokens'] + heavy['compressed_tokens']} токенов "
        f"(пробелы, комментарии, повторы, минификация JSON) "
        f"| {compression_saving:.6f} | {share(compression_saving):.1f} |",
        f"| непиковые часы DeepSeek | скидка {heavy['discount_percent']}% на тяжёлой "
        f"задаче (планировщик переносит её флагом `prefer_off_peak`) "
        f"| {summary['off_peak']['saving']:.6f} "
        f"| {share(summary['off_peak']['saving']):.1f} |",
        f"| предел длины ответа (оценка сверху) | {data['legacy_max_tokens']} → "
        f"{dialogue['max_tokens']} токенов по типу задачи "
        f"| {summary['response_limit']['saving']:.6f} "
        f"| {share(summary['response_limit']['saving']):.1f} |",
        f"| выбор модели по задаче | простые задачи не уходят на основную модель "
        f"(`{config.MODEL_CHAT}` вместо `{config.MODEL_REASONER}`) | — "
        f"| — (считается по типам задач, а не по токенам) |",
    ]


def write_report(path: Path, data: dict, *, now: datetime) -> Path:
    """Собрать markdown-отчёт из замера."""
    dialogue = data["dialogue"]
    heavy = data["heavy"]
    summary = data["summary"]
    model = dialogue["model"]
    prices = prices_for(model)
    cheap = [kind for kind, chosen in config.LLM_TASK_MODELS.items()
             if chosen == config.MODEL_CHAT]
    dear = [kind for kind in config.LLM_TASK_MODELS if kind not in cheap]
    compressed_total = dialogue["saved_tokens"] + heavy["compressed_tokens"]
    lines = [
        "# День 21 — оптимизация затрат на LLM: отчёт «до и после»",
        "",
        "Отчёт собран `scripts/cost_optimization_report.py` на **реальных текстах дня** "
        "(профиль, инварианты, каталог флота, память, состояние задачи, данные "
        "инструментов, артефакты прогонов) и реальном счётчике токенов "
        "`shared.token_counter` (tiktoken `cl100k_base`). Сеть и ключ DeepSeek не "
        "нужны: стоимость считается формулами домена `backend/domain/llm_cost.py` — "
        "теми же, что пишут журнал `llm_usage` и отдают `GET /llm/usage`.",
        "",
        f"* дата прогона: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"* модель диалога: `{model}` (ввод ${prices['in']}/1M, вывод ${prices['out']}/1M, "
        f"попадание в кэш — {int(config.LLM_CACHE_INPUT_RATIO * 100)}% цены ввода)",
        f"* диалог: {data['requests']} запросов подряд одного агента (стабильный префикс "
        f"кэшируется со второго), ответ — {data['answer_tokens']} токенов (допущение, "
        "одинаковое для «было» и «стало»)",
        f"* тяжёлая задача: пакетная обработка {heavy['files']} артефактов дня "
        f"({heavy['tokens_before']} токенов ввода), скидка непика "
        f"{heavy['discount_percent']}% (допущение провайдера)",
        "",
        "## Итог",
        "",
    ]
    lines += summary_rows(data)
    lines += [
        "",
        "Строка «предел длины ответа» в таблице рычагов — оценка СВЕРХУ: она "
        f"показывает, сколько не потратится, если долгий ответ упрётся в потолок "
        f"({data['legacy_max_tokens']} раньше против {dialogue['max_tokens']} теперь). "
        "В итог она не включена, потому что фактическая длина ответа от потолка не "
        "зависит.",
        "",
        "## Вклад каждого рычага",
        "",
        "| рычаг | как измерено | экономия, $ | доля от стоимости «было», % |",
        "|---|---|---|---|",
    ]
    lines += lever_rows(data)
    lines += [
        "",
        "## Как это работает в коде",
        "",
        "| механизм | модуль | что делает |",
        "|---|---|---|",
        "| стабильный префикс + динамический хвост | `backend/core/prompt_builder.py` "
        "| собирает промпт по зонам, кэширует префикс по содержимому, сжимает динамику "
        "и ловит динамические данные (метки времени, hex-id) в префиксе |",
        "| сжатие промптов | `backend/services/prompt_compressor.py` "
        "| убирает комментарии, лишние пробелы и повторы, минифицирует JSON в блоках |",
        "| модель по типу задачи | `backend/services/llm_client.py` (`select_model`) "
        f"| простые задачи — `{config.MODEL_CHAT}`, сложные — `{config.MODEL_REASONER}` |",
        "| предел длины ответа | `LLM_TASK_MAX_TOKENS` в конфиге "
        f"| по умолчанию {config.LLM_MAX_RESPONSE_TOKENS} токенов, для длинных задач — "
        f"{config.LLM_MAX_RESPONSE_TOKENS_LONG} |",
        "| журнал расходов | `backend/models/llm_usage.py`, `storage/llm_usage_store.py` "
        "| пишет каждый запрос: модель, тип, токены, `cache_hit`/`cache_miss`, стоимость |",
        "| непиковые часы | `backend/domain/peak_hours.py`, `services/scheduler.py` "
        f"| непик: будни 00–01, 04–06, 10–24 UTC и все выходные; скидка "
        f"{config.OFF_PEAK_DISCOUNT_PERCENT}%; `prefer_off_peak` переносит первый запуск |",
        "",
        "## Маршрутизация моделей",
        "",
        f"На дешёвой модели (`{config.MODEL_CHAT}`) идут {len(cheap)} типа задач из "
        f"{len(config.LLM_TASK_MODELS)}: " + ", ".join(f"`{kind}`" for kind in cheap)
        + ". Основную модель получают " + ", ".join(f"`{kind}`" for kind in dear)
        + ": это задачи, где короткая модель ошибается, а ошибка дороже разницы в "
        "тарифе. В отчёте маршрутизация показана отдельной строкой: она не входит в "
        "процент экономии, потому что сравнение считается на одном и том же наборе "
        "запросов.",
        "",
        "## Измеренные факты прогона",
        "",
        "| величина | значение |",
        "|---|---|",
        f"| стабильный префикс промпта | {dialogue['stable_tokens']} токенов "
        "(кэшируется сервером DeepSeek) |",
        f"| попаданий в кэш приложения | {dialogue['build_stats'].get('cache_hits', 0)} "
        f"из {dialogue['build_stats'].get('requests', 0)} сборок промпта |",
        f"| токенов снято сжатием в блоках дня | {compressed_total} "
        f"(диалог {dialogue['saved_tokens']} + тяжёлая задача {heavy['compressed_tokens']}) |",
        f"| сжатие на материале, для которого оно сделано (документ с маркером "
        f"усечения + JSON в заборе) | {data['compression']['tokens_before']} → "
        f"{data['compression']['tokens_after']} токенов "
        f"({data['compression']['saved_percent']}%) |",
        f"| тяжёлая задача | {heavy['tokens_before']} токенов ввода, "
        f"${heavy['cost_before']:.6f} в пик → ${heavy['cost_after']:.6f} в непик |",
        "",
        "## Допущения (влияют на числа)",
        "",
        f"* длина ответа ассистента — {data['answer_tokens']} токенов, одинаковая для "
        "«было» и «стало»: иначе сравнение было бы про разную длину ответов;",
        "* скидка непиковых часов — тариф провайдера, а не измерение: планировщик "
        "переносит задачу флагом `prefer_off_peak`, а размер скидки останется за "
        "провайдером;",
        "* мера «по полной цене» — токены, оплаченные как обычный ввод: попадание в "
        "кэш контекста считается по доле цены ввода (`LLM_CACHE_INPUT_RATIO`);",
        "* объём блоков памяти и диалога задан сценарием (текст — реальный, длина — "
        "типовая): абсолютные суммы поэтому оценочные, а ПРОЦЕНТЫ устойчивы, потому "
        "что обе стороны считаются на одних и тех же текстах.",
        "",
        "## Воспроизведение",
        "",
        "```bash",
        "cd day21",
        "uv run python scripts/cost_optimization_report.py            # пересобрать отчёт",
        "uv run pytest -q tests/unit/test_llm_cost.py tests/integration/test_llm_client.py",
        "uv run python scripts/indexing_demo.py                       # тяжёлая задача дня",
        "uv run python scripts/cost_optimization_verify.py            # живой прогон диалога",
        "```",
        "",
        "Живые числа (а не замер сценария) видны в интерфейсе: вкладка «💰 Расходы» — "
        "«Итоги периода», «Кэш промптов и сжатие», «Последние запросы»; через API — "
        "`GET /llm/usage`, `GET /llm/status`, `POST /llm/estimate`.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    """Замеряет сценарий и пишет отчёт; печатает сводку в консоль."""
    args = _parse_args(argv)
    builder = PromptBuilder(max_response_tokens=LEGACY_MAX_TOKENS)
    data = measure(builder)
    path = write_report(Path(args.report), data, now=datetime.now(timezone.utc))
    dialogue = data["dialogue"]
    heavy = data["heavy"]
    total_before = dialogue["legacy_cost"] + heavy["cost_before"]
    total_after = dialogue["new_cost"] + heavy["cost_after"]
    print(f"диалог: {data['requests']} запросов, ввод {dialogue['legacy_tokens']} → "
          f"{dialogue['new_tokens']} токенов, из них по полной цене "
          f"{dialogue['legacy_tokens']} → "
          f"{max(0, dialogue['new_tokens'] - dialogue['cache_hit_tokens'])}")
    print(f"диалог: ${dialogue['legacy_cost']:.6f} → ${dialogue['new_cost']:.6f} "
          f"({(1 - dialogue['new_cost'] / dialogue['legacy_cost']) * 100:.1f}%)")
    print(f"тяжёлая задача: ${heavy['cost_before']:.6f} → ${heavy['cost_after']:.6f} "
          f"(сжатие {heavy['compressed_tokens']} токенов + непик "
          f"{heavy['discount_percent']}%)")
    print(f"итого за день: ${total_before:.6f} → ${total_after:.6f} "
          f"({(1 - total_after / total_before) * 100:.1f}%)")
    scope = data["compression"]
    print(f"сжатие на своём материале: {scope['tokens_before']} → "
          f"{scope['tokens_after']} токенов ({scope['saved_percent']}%)")
    print(f"отчёт: {path}")
    return 0


def _parse_args(argv):
    """Разбирает аргументы: куда писать отчёт."""
    parser = argparse.ArgumentParser(
        description="Отчёт об оптимизации затрат на LLM (день 21): «до и после»",
    )
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help=f"куда писать отчёт (по умолчанию {DEFAULT_REPORT})")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
