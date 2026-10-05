"""Демо локальной модели дня 26: три запроса к Ollama из программы.

Скрипт — обёртка над ``local_llm_demo.run_demo()``: тот же набор запросов, что
отдаёт ``POST /llm/local-demo``, но без бэкенда — клиент идёт в Ollama напрямую по
HTTP (``POST /api/chat``). Здесь только вывод: вопрос, ответ, время, токены и
эвристика качества. Сеть не нужна никому, кроме Ollama: DeepSeek не вызывается.

Запуск из папки day21/::

    uv run python scripts/demo_local_llm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.core import config  # noqa: E402
from backend.domain import llm_provider  # noqa: E402
from backend.services.local_llm_client import LocalLLMError  # noqa: E402
from backend.services.local_llm_demo import run_demo  # noqa: E402


def main(argv=None) -> int:
    """Прогоняет три запроса и печатает отчёт; 0 — модель ответила на все."""
    del argv
    print(f"провайдер демо: {llm_provider.PROVIDER_LOCAL} (по умолчанию в конфиге: "
          f"{config.LLM_PROVIDER}) · модель: {config.LOCAL_LLM_MODEL} · "
          f"адрес: {config.LOCAL_LLM_URL} · таймаут: {config.LOCAL_LLM_TIMEOUT} с")
    try:
        result = run_demo()
    except LocalLLMError as exc:
        print(f"Ollama недоступен: {exc}")
        print(f"проверьте: `ollama serve` и `ollama pull {config.LOCAL_LLM_MODEL}`")
        return 1
    for row in result["rows"]:
        tokens = row["tokens"]
        print()
        print(f"[{row['key']}] {row['title']}: {row['question']}")
        print(f"ответ: {row['answer']}")
        print(f"время: {row['duration_ms']} мс · токены: "
              f"{tokens.get('prompt_tokens', 0)} вход / "
              f"{tokens.get('completion_tokens', 0)} выход · "
              f"качество (эвристика): {row['quality']}/5")
    total = int(result["total_ms"])
    count = len(result["rows"]) or 1
    print()
    print(f"итого: {count} запроса за {total} мс, в среднем {total // count} мс; "
          f"провайдер {result['provider']}, модель {result['model']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
