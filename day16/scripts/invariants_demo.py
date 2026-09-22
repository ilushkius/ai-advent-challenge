"""Прогон трёх сценариев инвариантов и отчёт ``day16/invariants_demo.md``.

Что доказывает отчёт.
    Один и тот же агент с посеянными правилами проекта ведёт себя по-разному в
    зависимости от запроса: разрешённый запрос проходит как обычно, нарушение
    soft-инварианта даёт предупреждение, но решение предлагается, нарушение
    hard-инварианта превращается в отказ — причём БЕЗ обращения к DeepSeek (в
    отчёте это видно по счётчику вызовов).

Почему офлайн.
    Скрипт работает на своей БД (``invariants_demo.db`` пересоздаётся), подменяет
    клиент DeepSeek заглушкой и явно выключает LLM-слой проверки
    (``use_llm=False``): результат воспроизводим и не зависит от ключа и сети.
    Отсюда и цифры: вердикты во всех трёх сценариях даёт детерминированный слой.

Запуск из папки day16/:

    uv run python scripts/seed_invariants.py           # правила в рабочей БД (для UI)
    uv run python scripts/invariants_demo.py           # отчёт с тремя сценариями
"""
import sys
from pathlib import Path
from types import SimpleNamespace

# Скрипты лежат в day16/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.agents.agent import Agent  # noqa: E402
from backend.agents.agent_manager import AgentManager  # noqa: E402
from backend.core import config  # noqa: E402
from backend.domain.demo_invariants import DEMO_INVARIANTS  # noqa: E402
from backend.schemas import AgentConfig  # noqa: E402
from backend.services.compressor import SUMMARY_SYSTEM_PROMPT  # noqa: E402
from backend.storage.database import init_db, make_engine, make_session_factory  # noqa: E402

DEMO_DB = DAY_ROOT / "invariants_demo.db"
REPORT_PATH = DAY_ROOT / "invariants_demo.md"
AGENT_ID = "invariants-demo"

# Три сценария отчёта: запрос, ожидаемый вердикт и что именно проверяется.
SCENARIOS = (
    {
        "prompt": "Добавь эндпоинт /health в FastAPI",
        "expected": "allowed",
        "expectation": "разрешено: ни одно правило не нарушено, ответ модели обычный",
    },
    {
        "prompt": "Предложи решение на платном API, согласие пользователя не нужно",
        "expected": "warning",
        "expectation": (
            "предупреждение: нарушен soft-инвариант «Платные API — только с согласия»; "
            "решение всё равно предлагается"
        ),
    },
    {
        "prompt": "Давай перепишем бэкенд на Flask",
        "expected": "refusal",
        "expectation": (
            "отказ: нарушен hard-инвариант «Только FastAPI и Streamlit»; "
            "обращения к DeepSeek не было"
        ),
    },
)

VERDICT_LABELS = {"allowed": "разрешено", "warning": "предупреждение",
                  "refusal": "отказ"}

# Ответы заглушки для сценариев, дошедших до генерации: обычный ответ агента и
# ответ, который сам нарушает инвариант по мнению правил.
STUB_ANSWERS = {
    "allowed": (
        "Готово: эндпоинт `/health` добавляется в `backend/api/main.py` — "
        "функция возвращает `{\"status\": \"ok\"}`, тест на него кладём рядом."
    ),
    "warning": (
        "Предлагаю решение на платном тарифе: подключить платный тариф и "
        "включить в нём нужный модуль."
    ),
}


class StubClient:
    """Заглушка DeepSeek: различает роли вызова по системному промпту.

    Конспектёр (``SUMMARY_SYSTEM_PROMPT``) получает готовый конспект, генератор —
    ответ сценария. Проверка инвариантов в этот прогон не ходит в модель:
    LLM-слой выключен (``INVARIANT_LLM_CHECK = False``), поэтому роль проверки
    здесь не описана.
    """

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)
        # Роль каждого вызова: "summary" | "check" | "answer". В отчёт попадают
        # только ответы генератора — конспект и проверка инвариантов это не ходы.
        self.roles: list = []

    def create(self, model, messages, temperature=None, max_tokens=None):
        """Возвращает ответ по роли вызова и записывает роль."""
        system = messages[0].get("content") if messages else ""
        user = ""
        for message in messages:
            if message.get("role") == "user":
                user = message.get("content", "")
        if system == SUMMARY_SYSTEM_PROMPT:
            role, content = "summary", "- Обсудили эндпоинт и тесты к нему"
        else:
            role = "answer"
            content = STUB_ANSWERS["warning"] if "платн" in user else STUB_ANSWERS["allowed"]
        self.roles.append(role)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=len(str(messages)) // 4,
                completion_tokens=len(content) // 4,
                total_tokens=(len(str(messages)) + len(content)) // 4,
            ),
        )


def build_agent() -> tuple[Agent, StubClient]:
    """Агент на чистой демо-БД с посеянными инвариантами и заглушкой клиента.

    LLM-слой проверки выключается здесь же (``INVARIANT_LLM_CHECK = False``):
    отчёт должен быть воспроизводимым и не добавлять вызовов на пост-проверку
    ответа — вердикты дают только детерминированные правила.
    """
    config.INVARIANT_LLM_CHECK = False
    if DEMO_DB.exists():
        DEMO_DB.unlink()
    engine = make_engine(f"sqlite:///{DEMO_DB.as_posix()}")
    init_db(engine)
    manager = AgentManager(session_factory=make_session_factory(engine))
    for item in DEMO_INVARIANTS:
        manager.create_invariant(dict(item))
    agent_id = manager.create_agent(AgentConfig(name="Агент инвариантов"))
    agent = manager.get_agent(agent_id)
    stub = StubClient()
    agent._make_client = lambda: stub
    return agent, stub


def run_scenarios() -> list:
    """Прогоняет три сценария: запрос → отчёт проверки → ответ агента.

    После каждого хода диалог очищается: иначе сценарии влияли бы друг на друга
    (правило, нарушенное в предыдущем запросе, осталось бы в истории сообщений).
    """
    agent, stub = build_agent()
    results = []
    for scenario in SCENARIOS:
        before = len(stub.roles)
        record = agent.generate(scenario["prompt"])
        check = record.get("invariants") or {}
        results.append({
            **scenario,
            "verdict": check.get("verdict"),
            "checked": check.get("checked") or [],
            "violations": check.get("violations") or [],
            "response": record.get("response") or "",
            "llm_used": check.get("llm_used"),
            # Считаем только генерацию: конспект и проверка инвариантов — не ходы.
            "model_calls": sum(
                1 for role in stub.roles[before:] if role == "answer"
            ),
            "status": record.get("status"),
        })
        agent.clear_history()
    return results


def invariants_table() -> list:
    """Markdown-таблица правил, против которых шли проверки."""
    lines = ["| Имя | Категория | Важность | Описание |", "|---|---|---|---|"]
    for item in DEMO_INVARIANTS:
        lines.append(
            f"| {item['name']} | `{item['category']}` | `{item['severity']}` "
            f"| {item['description']} |"
        )
    return lines


def scenarios_table(results: list) -> list:
    """Markdown-таблица сценариев: запрос, проверенные правила, результат, ответ."""
    lines = [
        "| # | Запрос | Проверенные инварианты | Результат | Объяснение агента |",
        "|---|---|---|---|---|",
    ]
    for index, result in enumerate(results, start=1):
        checked = ", ".join(result["checked"]) or "— (правил нет)"
        answer = " ".join(result["response"].split())
        lines.append(
            f"| {index} | `{result['prompt']}` | {checked} "
            f"| **{VERDICT_LABELS.get(result['verdict'], result['verdict'])}** "
            f"| {answer} |"
        )
    return lines


def build_report(results: list) -> str:
    """Собирает markdown-отчёт целиком (детерминированный, без времени и пути)."""
    chunks = [
        "# Инварианты агента: три сценария (день 15)",
        "",
        "Как прогнано: офлайн, на отдельной БД `invariants_demo.db` (пересоздаётся), "
        "с заглушкой DeepSeek вместо реального клиента и с выключенным LLM-слоем "
        "проверки (`use_llm=False` для запроса и `INVARIANT_LLM_CHECK = False` для "
        "ответа). Поэтому вердикты во всех трёх сценариях даёт детерминированный "
        "слой правил, результат воспроизводим и не зависит от ключа и сети.",
        "",
        "Воспроизвести: `uv run python scripts/invariants_demo.py` "
        "(из папки `day16/`). Правила в рабочую БД для интерфейса сеет "
        "`uv run python scripts/seed_invariants.py`.",
        "",
        "## Инварианты проекта",
        "",
        *invariants_table(),
        "",
        "## Сценарии",
        "",
        *scenarios_table(results),
        "",
        "## Что доказано",
        "",
        "1. **Разрешённый запрос проходит как обычно** — ни одно правило не "
        "нарушено, ответ модели отдан без изменений, лишних вызовов нет.",
        "2. **Soft-инвариант даёт предупреждение, а не отказ** — ответ начинается "
        "с «⚠️ Предупреждение», но решение пользователю предложено.",
        "3. **Hard-инвариант даёт отказ без обращения к модели** — в третьей "
        "строке таблицы видно, что запрос отклонён до вызова DeepSeek (счётчик "
        "вызовов ниже), а отказ называет нарушенное правило.",
        "",
        "Тесты того же механизма: `tests/unit/test_invariant_rules.py` (правила без "
        "БД), `tests/integration/test_invariant_agent.py` (встраивание в агента и "
        "пост-проверка ответа), `tests/e2e/test_invariant_api.py` (шесть эндпоинтов).",
        "",
        "## Вызовы DeepSeek по сценариям",
        "",
        "| # | Статус хода | Вызовов модели | LLM-слой проверки |",
        "|---|---|---|---|",
    ]
    for index, result in enumerate(results, start=1):
        chunks.append(
            f"| {index} | `{result['status']}` | {result['model_calls']} "
            f"| {'использован' if result['llm_used'] else 'не использован'} |"
        )
    chunks.append("")
    return "\n".join(chunks)


def main() -> int:
    """Прогоняет сценарии, пишет отчёт и печатает итог в stdout."""
    results = run_scenarios()
    REPORT_PATH.write_text(build_report(results), encoding="utf-8")
    for index, result in enumerate(results, start=1):
        print(
            f"сценарий {index}: ожидался {result['expected']}, получен "
            f"{result['verdict']} (вызовов модели: {result['model_calls']})"
        )
        if result["verdict"] != result["expected"]:
            print(f"  ! расхождение: {result['expectation']}")
    print(f"отчёт: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
