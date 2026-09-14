"""Сценарий дня 11: маршрутизация реплик «собираем ТЗ» по трём слоям памяти.

Запуск из папки дня (обязательно: пути к БД и .env считаются от `backend/`):

    python memory_layers_demo.py

Что делает скрипт.

1. Создаёт отдельную БД ``day11/memory_demo.db`` (файл удаляется и создаётся
   заново, поэтому прогон воспроизводим) и агента с ``task_id = "tz-portal"``.
2. Прогоняет 12 реплик сценария «собираем ТЗ»: перед каждой репликой пишет
   данные в рабочую память задачи (цель, стек, срок, бюджет, ограничение,
   критерий приёмки) и в долговременную память (профиль, предпочтение, решение,
   знание), затем делает ход и печатает, сколько записей и токенов ушло из
   каждого слоя.
3. Начинает новую сессию и доказывает, что краткосрочный слой обнулился, а
   рабочая и долговременная память остались привязаны к тому же ``task_id``.
4. Пишет отчёт ``memory_layers_comparison.md`` с фактическими значениями слоёв.

Сеть не используется: клиент DeepSeek подменяется ``DemoClient``. Ожидания
проверяются ``assert`` — расхождение даёт ненулевой код возврата.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.agent import Agent
from backend import config, database
from backend.database import AgentRecord
from backend.models import AgentConfig

HERE = Path(__file__).resolve().parent
DEMO_DB = HERE / "memory_demo.db"
REPORT = HERE / "memory_layers_comparison.md"
AGENT_ID = "demo11"
TASK_ID = "tz-portal"

SCENARIO = [
    {
        "text": "Название проекта: Корпоративный портал",
        "note": "рабочая — цель задачи; долговременная — роль пользователя",
        "working": ("цель", "Корпоративный портал"),
        "long_term": ("profile", "роль_пользователя", "аналитик", 0.9),
    },
    {
        "text": "Стек: Python 3.14 + FastAPI",
        "note": "рабочая — технологический стек; долговременная — знание о команде",
        "working": ("стек", "Python 3.14 + FastAPI"),
        "long_term": ("knowledge", "стек_команды", "Python 3.14 + FastAPI", 0.7),
    },
    {
        "text": "База данных: PostgreSQL",
        "note": "долговременная — принятое решение о СУБД",
        "working": None,
        "long_term": ("decision", "бд", "PostgreSQL", 0.8),
    },
    {
        "text": "Срок: 3 месяца",
        "note": "рабочая — срок относится к текущей задаче",
        "working": ("срок", "3 месяца"),
        "long_term": None,
    },
    {
        "text": "Бюджет: 5000 долларов",
        "note": "рабочая — бюджет задачи",
        "working": ("бюджет", "5000 долларов"),
        "long_term": None,
    },
    {
        "text": "Авторизация: JWT",
        "note": "только краткосрочная: обсуждение в текущей сессии",
        "working": None,
        "long_term": None,
    },
    {
        "text": "Роли пользователей: админ, менеджер, сотрудник",
        "note": "только краткосрочная: деталь реплики, не долговечная настройка",
        "working": None,
        "long_term": None,
    },
    {
        "text": "Интеграции: отправка почты через SMTP",
        "note": "только краткосрочная: обсуждается в диалоге",
        "working": None,
        "long_term": None,
    },
    {
        "text": "Язык интерфейса: русский",
        "note": "долговременная — устойчивое предпочтение пользователя",
        "working": None,
        "long_term": ("preference", "язык_интерфейса", "русский", 0.95),
    },
    {
        "text": "Ограничение: только on-premise, без облака",
        "note": "рабочая — ограничение задачи",
        "working": ("ограничение", "только on-premise"),
        "long_term": None,
    },
    {
        "text": "Отчётность: еженедельные PDF-отчёты",
        "note": "только краткосрочная: деталь обсуждения",
        "working": None,
        "long_term": None,
    },
    {
        "text": "Тестирование: pytest с покрытием не ниже 80%",
        "note": "рабочая — критерий приёмки задачи",
        "working": ("критерий_приёмки", "pytest, покрытие не ниже 80%"),
        "long_term": None,
    },
]


# ---------- фейковый клиент DeepSeek (сеть не используется) ----------
class DemoUsage:
    """usage-блок ответа: числа запроса/ответа, как у OpenAI SDK."""

    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class DemoResponse:
    """Минимальный ответ chat.completions: choices[0].message.content + usage."""

    def __init__(self, content: str) -> None:
        self.choices = [
            SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop"
            )
        ]
        self.usage = DemoUsage(
            prompt_tokens=len(content.split()) + 40,
            completion_tokens=len(content.split()),
        )


class DemoCompletions:
    """chat.completions: детерминированный ответ по последней реплике."""

    def __init__(self, owner: "DemoClient") -> None:
        self._owner = owner

    def create(self, model, messages, temperature=None, max_tokens=None):
        self._owner.calls += 1
        last = ""
        for message in reversed(messages or []):
            if message.get("role") == "user":
                last = message.get("content", "")
                break
        return DemoResponse(f"Принято: {last[:80]}")


class DemoClient:
    """Фейковый клиент DeepSeek: считает вызовы, отвечает без сети."""

    def __init__(self) -> None:
        self.calls = 0
        self.chat = SimpleNamespace(completions=DemoCompletions(self))


def fresh_engine():
    """Движок на чистой демо-БД (файл пересоздаётся — прогон воспроизводим)."""
    DEMO_DB.unlink(missing_ok=True)
    engine = database.make_engine(f"sqlite:///{DEMO_DB.as_posix()}")
    database.init_db(engine)
    return engine


def build_agent(engine, client: DemoClient) -> Agent:
    """Создаёт строку agents + Agent и подменяет клиент DeepSeek фейком."""
    session_factory = database.make_session_factory(engine)
    cfg = AgentConfig(name="Демо памяти")
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(AgentRecord(
            agent_id=AGENT_ID, name=cfg.name, model=cfg.model,
            temperature=cfg.temperature, system_prompt=cfg.system_prompt,
            max_tokens=cfg.max_tokens, summary_enabled=cfg.summary_enabled,
            keep_last_messages=cfg.keep_last_messages,
            summarize_every=cfg.summarize_every, strategy=cfg.strategy,
            window_size=cfg.window_size, current_session_id="demo0001",
            current_task_id=TASK_ID, created_at=now,
        ))
        session.commit()
    agent = Agent(cfg, agent_id=AGENT_ID, created_at=now,
                  session_factory=session_factory, session_id="demo0001",
                  task_id=TASK_ID)
    agent._make_client = lambda: client  # без сети
    return agent


def layer_row(state: dict) -> str:
    """Строка «сколько записей/токенов ушло из каждого слоя»."""
    return (
        f"короткая {state['short_term']['count']}/{state['short_term']['tokens']}"
        f" · рабочая {state['working']['count']}/{state['working']['tokens']}"
        f" · долговременная {state['long_term']['count']}"
        f"/{state['long_term']['tokens']}"
    )


def run_scenario(agent: Agent) -> list:
    """Прогоняет 12 реплик, печатает по строке на шаг, возвращает журнал."""
    agent.set_task(TASK_ID)
    journal = []
    for number, step in enumerate(SCENARIO, start=1):
        if step["working"]:
            key, value = step["working"]
            agent.add_working(key, value)
        if step["long_term"]:
            category, key, value, confidence = step["long_term"]
            agent.add_long_term(category, key, value, confidence)
        record = agent.generate(step["text"])
        memory = record["memory"]
        layers = {layer["layer"]: layer for layer in memory["layers"]}
        journal.append({
            "number": number,
            "text": step["text"],
            "note": step["note"],
            "mode": record["context"]["compression"]["mode"],
            "layers": layers,
            "total_tokens": memory["total_tokens"],
            "keywords": memory["keywords"],
            "answer": record["response"],
        })
        print(f"Шаг {number} · слои: " + layer_row({
            "short_term": {"count": layers["short_term"]["entries"],
                           "tokens": layers["short_term"]["tokens"]},
            "working": {"count": layers["working"]["entries"],
                        "tokens": layers["working"]["tokens"]},
            "long_term": {"count": layers["long_term"]["entries"],
                          "tokens": layers["long_term"]["tokens"]},
        }) + f" · “{record['response']}”")
    return journal


def session_evidence(agent: Agent, memory_before: dict) -> dict:
    """Начинает новую сессию и печатает доказательства разделения слоёв."""
    session = agent.new_session()
    after = agent.memory_state()

    print()
    print("После новой сессии:")
    print(f"  session_id: {session['previous_session_id']} → {session['session_id']}")
    print(f"  краткосрочная: {memory_before['short_term']['count']} → "
          f"{after['short_term']['count']} реплик "
          f"(удалено {session['deleted_messages']})")
    print(f"  рабочая: {memory_before['working']['count']} → "
          f"{after['working']['count']} записей (задача {after['task_id']})")
    print(f"  долговременная: {memory_before['long_term']['count']} → "
          f"{after['long_term']['count']} записей")

    assert memory_before["short_term"]["count"] > 0, "диалог должен был накопиться"
    assert after["short_term"]["count"] == 0, "новая сессия должна обнулить диалог"
    assert after["working"]["count"] == memory_before["working"]["count"], \
        "рабочая память переживает смену сессии"
    assert after["long_term"]["count"] == memory_before["long_term"]["count"], \
        "долговременная память переживает смену сессии"
    assert after["task_id"] == TASK_ID, "задача не должна сбрасываться"
    assert session["session_id"] != session["previous_session_id"], \
        "новая сессия должна получить новый идентификатор"

    # Один ход в новой сессии: рабочая и долговременная память по-прежнему
    # уходят в контекст, хотя краткосрочный слой пуст (в запросе только сам промпт).
    record = agent.generate("Напомни ограничения проекта")
    memory = record["memory"]
    assert memory["short_term_tokens"] == 0, \
        "в новой сессии краткосрочный слой пуст — реплик ещё не было"
    assert memory["working_tokens"] > 0, "рабочая память должна уйти в запрос"
    assert memory["long_term_tokens"] > 0, "долговременная память должна уйти в запрос"

    print()
    print("Ход в новой сессии (слои в контексте запроса):")
    print(f"  короткая {memory['short_term_tokens']} токенов (сессия ещё пуста) · "
          f"рабочая {memory['working_tokens']} · долговременная "
          f"{memory['long_term_tokens']} токенов · всего {memory['total_tokens']}")
    print(f"  ключевые слова: {', '.join(memory['keywords'])}")
    print(f"  ответ: “{record['response']}”")
    return {"session": session, "before": memory_before, "after": after,
            "memory": memory, "record": record}


def render_report(journal: list, evidence: dict, working: list, long_term: list) -> str:
    """Собирает markdown-отчёт с фактическими значениями слоёв."""
    before = evidence["before"]
    after = evidence["after"]
    session = evidence["session"]
    memory = evidence["memory"]

    def example(key: str) -> str:
        for entry in working:
            if entry["key"] == key:
                return f"`{key}: {entry['value']}`"
        return "—"

    def long_example(category: str, key: str) -> str:
        for entry in long_term:
            if entry["category"] == category and entry["key"] == key:
                return (f"`[{entry['category']}] {entry['key']}: {entry['value']}` "
                        f"(уверенность {entry['confidence']:g})")
        return "—"

    lines = [
        "# День 11 — сравнение слоёв памяти агента",
        "",
        "Прогон сценария **«собираем ТЗ»** (12 реплик) на агенте с тремя слоями",
        "памяти. Рабочая память привязана к задаче `task_id = \"tz-portal\"`,",
        "краткосрочная — к сессии, долговременная — к агенту целиком.",
        "Скрипт: [`memory_layers_demo.py`](memory_layers_demo.py) "
        "(фейковый клиент, сеть не используется).",
        "",
        "## Слои памяти",
        "",
        "| Слой памяти | Что хранит | Когда очищается | Как влияет на ответы | Пример данных |",
        "| --- | --- | --- | --- | --- |",
        "| 👤 Краткосрочная (`short_term_messages`) | Реплики текущего диалога"   
        " одной сессии (`session_id`) | `new_session()`,"
        " `DELETE /agents/{id}/memory/short-term`, `DELETE /history` |"
        " Последние N реплик уходят в запрос дословно (стратегия), остальные"
        " остаются в БД | `role=user, content="
        f"\"{journal[9]['text']}\"` |",
        "| 🗂 Рабочая (`working_memory`) | Данные активной задачи (`task_id`):"
        " цель, ограничения, решения, критерии | Не очищается новой сессией;"
        " очищается вручную/сменой задачи | Все записи задачи подставляются"
        " блоком «Рабочая память» в системное сообщение | "
        f"{example('ограничение')} |",
        "| 🧠 Долговременная (`long_term_memory`) | Профиль, устойчивые"
        " предпочтения, важные решения, знания | Только вручную"
        " (`DELETE /memory/long-term/{id}`) | Релевантные записи (совпадение по"
        " ключевым словам, добор по уверенности) идут блоком «Долговременная"
        " память» | " + long_example("preference", "язык_интерфейса") + " |",
        "",
        "## Журнал прогона",
        "",
        "12 реплик сценария; «слои» — сколько записей/токенов ушло в запрос из",
        "каждого слоя (`record[\"memory\"]` ответа `generate`).",
        "",
        "| Шаг | Реплика | Маршрутизация | Короткая (записей/токенов) |"
        " Рабочая | Долговременная | Всего токенов |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for step in journal:
        layers = step["layers"]
        lines.append(
            f"| {step['number']} | {step['text']} | {step['note']} | "
            f"{layers['short_term']['entries']}/{layers['short_term']['tokens']} | "
            f"{layers['working']['entries']}/{layers['working']['tokens']} | "
            f"{layers['long_term']['entries']}/{layers['long_term']['tokens']} | "
            f"{step['total_tokens']} |"
        )
    lines += [
        "",
        "Итог по слоям после 12 реплик: краткосрочная — "
        f"реплик: **{before['short_term']['count']}**, рабочая — "
        f"записей: **{before['working']['count']}**, долговременная — "
        f"записей: **{before['long_term']['count']}**.",
        "",
        "## После новой сессии",
        "",
        "`Agent.new_session()` завершает текущую сессию: реплики её краткосрочного",
        "слоя, конспекты и факты старого диалога удаляются, рабочая память,"
        " долговременная память, ветки и метрики остаются.",
        "",
        "| Слой | До новой сессии | После новой сессии | Что произошло |",
        "| --- | --- | --- | --- |",
        f"| 👤 Краткосрочная | реплик: {before['short_term']['count']} | "
        f"реплик: {after['short_term']['count']} | удалено прошлой сессией: "
        f"{session['deleted_messages']} |",
        f"| 🗂 Рабочая | записей: {before['working']['count']} | "
        f"записей: {after['working']['count']} | сохранена, задача та же |",
        f"| 🧠 Долговременная | записей: {before['long_term']['count']} | "
        f"записей: {after['long_term']['count']} | сохранена |",
        f"| Сессия (`session_id`) | `{session['previous_session_id']}` | "
        f"`{session['session_id']}` | новый идентификатор |",
        f"| Задача (`task_id`) | `{TASK_ID}` | `{after['task_id']}` | не менялась |",
        "",
        "Проверки скрипта (`assert`): короткая "
        f"{before['short_term']['count']} → {after['short_term']['count']}, "
        f"рабочая {before['working']['count']} → {after['working']['count']}, "
        f"долговременная {before['long_term']['count']} → "
        f"{after['long_term']['count']}, `task_id` = `{after['task_id']}`.",
        "",
        "Первый ход в новой сессии подтверждает, что рабочая и долговременная",
        "память по-прежнему уходят в контекст, хотя диалога в краткосрочном слое",
        "ещё нет (в запросе — только сам промпт, поэтому краткосрочный слой даёт",
        "0 токенов):",
        "",
        f"* короткая — {memory['short_term_tokens']} токенов;",
        f"* рабочая — {memory['working_tokens']} токенов;",
        f"* долговременная — {memory['long_term_tokens']} токенов;",
        f"* всего — {memory['total_tokens']} токенов;",
        f"* ключевые слова запроса: {', '.join(memory['keywords'])}.",
        "",
        "## Как воспроизвести",
        "",
        "```powershell",
        "cd day11",
        ".venv/Scripts/python memory_layers_demo.py",
        "```",
        "",
        "Скрипт пересоздаёт `memory_demo.db`, печатает журнал по шагам и",
        "перезаписывает этот файл; при расхождении ожиданий код возврата",
        "ненулевой.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """Прогон сценария целиком: слои, новая сессия, отчёт."""
    engine = fresh_engine()
    client = DemoClient()
    agent = build_agent(engine, client)

    print("День 11 · маршрутизация реплик сценария «собираем ТЗ» по слоям памяти")
    print(f"Агент {AGENT_ID}, задача {TASK_ID}, сессия {agent.session_id}")
    print()
    journal = run_scenario(agent)

    working = agent.working_rows()
    long_term = agent.long_term_rows()
    assert len(working) == 6, f"в рабочей памяти 6 записей, а не {len(working)}"
    assert len(long_term) == 4, \
        f"в долговременной памяти 4 записи, а не {len(long_term)}"
    before = agent.memory_state()

    evidence = session_evidence(agent, before)
    REPORT.write_text(render_report(journal, evidence, working, long_term),
                      encoding="utf-8")

    print()
    print(f"OK: слои проверены (короткая {before['short_term']['count']} → "
          f"{evidence['after']['short_term']['count']}, рабочая "
          f"{before['working']['count']} → {evidence['after']['working']['count']}, "
          f"долговременная {before['long_term']['count']} → "
          f"{evidence['after']['long_term']['count']}, задача "
          f"{evidence['after']['task_id']}); отчёт: {REPORT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
