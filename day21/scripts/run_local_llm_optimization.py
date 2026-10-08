"""Прогон оптимизации локальной модели (день 29): профили и кванты на кейсе RAG.

Скрипт ходит в бэкенд по HTTP (``POST /llm/tune``) — тем же путём, что и кнопка
«🚀 Прогнать сравнение профилей» в интерфейсе: отчёт подтверждает то, что видно в UI, а
не отдельную копию прогона. Поиск по корпусу у всех вариантов один и тот же (FAISS дня
22 и sentence-transformers), поэтому сравниваются только параметры генерации и тег
модели.

Прогон идёт **по одному варианту «профиль × модель» за запрос**: четыре варианта — это
десятки минут локальной модели, и один запрос на всё не влез бы в предел ожидания и не
показывал бы прогресса. Сводка (пары «до/после», лучший вариант) считается доменом
``backend.domain.local_tuning_eval`` — тем же, что и на бэкенде, и в интерфейсе.

Отчёт пишется один раз и перезаписывается при повторном прогоне: раздел «Выводы»
дописывает человек по факту прогона (для черновика — ``--report
docs/reports/local_llm_optimization.draft.md``).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests

DAY_ROOT = Path(__file__).resolve().parents[1]
# Пакет backend лежит в корне дня: добавляем его в sys.path, чтобы запуск работал из
# любой рабочей директории (как в scripts/comparison_report.py).
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.domain import local_tuning_eval  # noqa: E402  (после правки sys.path)

from local_tuning_report import render_report  # noqa: E402  (модуль рядом)

#: Адрес бэкенда: переопределяется ``--backend`` или переменной окружения.
BACKEND_URL = os.environ.get("DAY21_BACKEND_URL", "http://127.0.0.1:8000")

#: Предел ожидания варианта: десять вопросов локальной модели плюс прогрев весов.
REPORT_TIMEOUT = 3600.0

#: Предел ожидания справки о прогоне (``/rag/config``, ``/llm/provider``).
CONFIG_TIMEOUT = 30.0

#: Отчёт по умолчанию — рядом с отчётами предыдущих дней.
DEFAULT_REPORT = "docs/reports/local_llm_optimization.md"

#: Профили по умолчанию: «до оптимизации» рядом с «после».
DEFAULT_PROFILES = "baseline,tuned"

#: Подпись пустой ячейки.
DASH = "—"


def main(argv=None) -> int:
    """Прогоняет варианты через эндпоинт, пишет отчёт и печатает сводку."""
    args = _parse_args(argv)
    backend = str(args.backend).rstrip("/")
    try:
        config = requests.get(f"{backend}/rag/config", timeout=CONFIG_TIMEOUT).json()
        provider = requests.get(f"{backend}/llm/provider",
                                timeout=CONFIG_TIMEOUT).json()
        questions = _questions(backend, args.limit)
    except requests.RequestException as exc:
        return _offline(backend, exc)
    if not questions:
        print("вопросы не загрузились: проверьте GET /rag/demo-questions")
        return 1
    models = _split(args.models) or [str(provider.get("local_model") or "")]
    profiles = _split(args.profiles) or _default_profiles(provider)
    print(f"прогон: моделей {len(models)}, профилей {len(profiles)}, "
          f"вопросов {len(questions)}, top_k {args.top_k}")
    started = time.perf_counter()
    result, code = _variants(backend, questions, models, profiles, args)
    if code:
        return code
    elapsed = time.perf_counter() - started
    text = render_report(result, config=config, provider=provider, models=models,
                         elapsed=elapsed)
    target = _target(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    _print_run(result, target, elapsed)
    return 1 if _failed_rows(result) else 0


def _variants(backend: str, questions: list, models: list, profiles: list,
              args) -> tuple[dict, int]:
    """Один запрос на вариант: строки накапливаются, сводка считается доменом."""
    variants: list = []
    params: dict = {}
    before: dict = {}
    result_base: dict = {}
    pairs = [(model, name) for model in models for name in profiles]
    for index, (model, name) in enumerate(pairs, start=1):
        print(f"[{index}/{len(pairs)}] {model} · {name} …", flush=True)
        try:
            response = requests.post(
                f"{backend}/llm/tune",
                json={"questions": questions, "models": [model], "profiles": [name],
                      "top_k": int(args.top_k), "strategy": args.strategy},
                timeout=REPORT_TIMEOUT)
        except requests.RequestException as exc:
            return {}, _offline(backend, exc)
        if response.status_code != 200:
            print(f"бэкенд ответил {response.status_code}: {response.text}")
            return {}, 1
        payload = response.json()
        variants.extend(payload.get("variants") or [])
        params.update({item["profile"]: item for item in payload.get("profiles") or []})
        before = payload.get("ps_before") or before
        print("     " + _variant_line(payload))
        result_base = {"url": payload.get("url"), "model": payload.get("model"),
                       "ollama_version": payload.get("ollama_version") or "",
                       "active_profile": payload.get("active_profile") or "",
                       "top_k": payload.get("top_k"), "strategy": payload.get("strategy")}
    summary = local_tuning_eval.summary(variants)
    return {**result_base, "profiles": list(params.values()), "variants": variants,
            "pairs": summary["pairs"], "best": summary["best"],
            "total_ms": summary["total_ms"], "ps_before": before}, 0


def _questions(backend: str, limit: int = 0) -> list:
    """Тексты контрольных вопросов с бэкенда (``GET /rag/demo-questions``)."""
    payload = requests.get(f"{backend}/rag/demo-questions",
                           timeout=CONFIG_TIMEOUT).json()
    texts = [str(item.get("question") or "").strip()
             for item in (payload.get("questions") or [])]
    texts = [text for text in texts if text]
    return texts[:max(1, int(limit))] if limit else texts


def _print_run(result: dict, target: Path, elapsed: float) -> None:
    """Печать сводки по вариантам, вердиктов пар и пути отчёта."""
    for variant in result.get("variants") or []:
        params, summary = variant.get("params") or {}, variant.get("summary") or {}
        resources = variant.get("resources") or {}
        print(f"{params.get('profile')} · {params.get('model')}: совпало "
              f"{summary.get('verdict_ok')}/{summary.get('questions')}, цитаты "
              f"{summary.get('quotes_verified')}, опора {summary.get('grounding_ok')}, "
              f"ср. время {int(summary.get('avg_ms') or 0) / 1000:.2f} с, "
              f"{float(summary.get('avg_tokens_per_second') or 0.0):.1f} токенов/с, "
              f"VRAM {float(resources.get('vram_mb') or 0.0):.0f} МБ")
    for pair in result.get("pairs") or []:
        print(f"пара {pair.get('model')}: {pair.get('verdict')} "
              f"(разница {int(pair.get('quality_delta') or 0):+d}, "
              f"ускорение {float(pair.get('speedup') or 0.0)}×)")
    print(f"лучший вариант: {result.get('best') or DASH}, ошибок в строках: "
          f"{len(_failed_rows(result))}, время прогона: {elapsed:.1f} с")
    print(f"отчёт: {target}")


def _variant_line(payload: dict) -> str:
    """Строка консоли по ответу одного варианта: качество, время и токены."""
    variant = (payload.get("variants") or [{}])[0]
    params, summary = variant.get("params") or {}, variant.get("summary") or {}
    return (f"{params.get('profile')} готов: совпало {summary.get('verdict_ok')}/"
            f"{summary.get('questions')}, ср. время "
            f"{int(summary.get('avg_ms') or 0) / 1000:.2f} с, "
            f"{float(summary.get('avg_tokens_per_second') or 0.0):.1f} токенов/с, "
            f"ошибок {summary.get('errors')}")


def _offline(backend: str, exc: Exception) -> int:
    """Бэкенд недоступен: подсказки по запуску и код возврата 1."""
    print(f"бэкенд недоступен ({backend}): {exc}")
    print("что нужно для прогона (из папки day21/):")
    print("  1) uv run uvicorn backend.api.main:app --port 8000")
    print("  2) ollama serve  (и модель: ollama list)")
    print("  3) корпус RAG проиндексирован (scripts/prepare_rag_corpus.py, "
          "scripts/index_rag_corpus.py)")
    print("  4) другой адрес: --backend http://127.0.0.1:<port>")
    return 1


def _failed_rows(result: dict) -> list:
    """Строки с режимом ``error``: код возврата 1 (часть прогона не удалась)."""
    return [(variant.get("params") or {}).get("profile")
            for variant in result.get("variants") or []
            for row in (variant.get("rows") or []) if row.get("mode") == "error"]


def _split(value) -> list:
    """Список из строки через запятую: пустые значения пропускаются."""
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _default_profiles(provider: dict) -> list:
    """Профили по умолчанию: оба, как их называет бэкенд (``GET /llm/provider``)."""
    return [str(item) for item in (provider.get("profiles") or [])] or \
        _split(DEFAULT_PROFILES)


def _parse_args(argv):
    """Аргументы прогона: отчёт, адрес бэкенда, модели, профили, top_k, стратегия."""
    parser = argparse.ArgumentParser(
        description="Прогон профилей и квантов локальной модели на вопросах корпуса.")
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help="путь к markdown-отчёту (по умолчанию %(default)s)")
    parser.add_argument("--backend", default=BACKEND_URL,
                        help="адрес бэкенда (по умолчанию %(default)s)")
    parser.add_argument("--models", default=None,
                        help="теги моделей Ollama через запятую: второй тег — сравнение "
                             "квантов (по умолчанию модель конфига)")
    parser.add_argument("--profiles", default=DEFAULT_PROFILES,
                        help="профили настройки через запятую (по умолчанию "
                             "%(default)s)")
    parser.add_argument("--top-k", type=int, default=5,
                        help="сколько фрагментов корпуса идёт в контекст (по умолчанию "
                             "%(default)s)")
    parser.add_argument("--strategy", default=None,
                        help="стратегия поиска (по умолчанию — стратегия бэкенда)")
    parser.add_argument("--limit", type=int, default=0,
                        help="сколько первых вопросов брать (0 — все)")
    return parser.parse_args(argv)


def _target(value: str) -> Path:
    """Путь отчёта: относительный считается от корня дня."""
    path = Path(value)
    return path if path.is_absolute() else DAY_ROOT / path


if __name__ == "__main__":
    sys.exit(main())
