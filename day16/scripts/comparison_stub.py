"""Офлайн-часть сравнения профилей: демо-БД, заглушка DeepSeek и вопросы агентам.

Скрипт ``personalization_comparison.py`` создаёт отдельную БД
(``day16/personalization_demo.db``), три профиля демонстрации и по агенту на
профиль, а затем задаёт им вопросы. Здесь живёт «инфраструктура» прогона:
менеджер на временной БД, создание профилей, вопрос агенту и проверка порядка
ролей в ответе профиля-оркестратора.

Заглушка ``StubClient`` (режим ``--no-api``) «отвечает» по системному промпту,
поэтому скрипт можно прогнать без ключа API и без сети.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

# Скрипты лежат в day16/scripts/, а пакет backend — в корне дня: добавляем
# корень дня в sys.path, чтобы запуск работал из любой рабочей директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.agents.agent_manager import AgentManager
from backend.storage.database import init_db, make_engine, make_session_factory
from backend.domain.demo_profiles import DEMO_PROFILES
from backend.schemas import AgentConfig


DEMO_DB = DAY_ROOT / "personalization_demo.db"


# Профили отчёта: два противоположных + профиль с инструкцией о порядке ролей.
COMPARISON_USERS = ("strict_tech", "friendly_mentor")
ORCHESTRATOR_USER = "process_orchestrator"


# Роли, порядок которых задан инструкцией профиля-оркестратора.
ROLE_ORDER = ("аналитик", "разработчик", "тестировщик")


class StubClient:
    """Заглушка DeepSeek для офлайн-прогона: «отвечает» по системному промпту.

    Не имитирует модель, а показывает, что скрипт дошёл до вызова: в ответ
    попадают фрагменты системного промпта (стиль, формат, инструкции), поэтому
    проверяются и сохранение профиля, и его подстановка в запрос.
    """

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature=None, max_tokens=None):
        system = ""
        user = ""
        for message in messages:
            if message.get("role") == "system":
                system = message.get("content", "")
            elif message.get("role") == "user":
                user = message.get("content", "")
        content = (
            "[офлайн-заглушка] запрос: " + user.strip()
            + "\n[офлайн-заглушка] профиль в промпте: "
            + " / ".join(
                line for line in system.splitlines() if line and line != system.splitlines()[0]
            )
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=len(system) // 4 + len(user) // 4,
                completion_tokens=len(content) // 4,
                total_tokens=(len(system) + len(user) + len(content)) // 4,
            ),
        )


def prepare_manager() -> AgentManager:
    """Менеджер на чистой демо-базе (файл пересоздаётся для воспроизводимости)."""
    if DEMO_DB.exists():
        DEMO_DB.unlink()
    engine = make_engine(f"sqlite:///{DEMO_DB.as_posix()}")
    init_db(engine)
    return AgentManager(session_factory=make_session_factory(engine))


def ensure_profiles(manager: AgentManager) -> None:
    """Создаёт три профиля демонстрации (те же данные, что в интерфейсе)."""
    for item in DEMO_PROFILES:
        created = manager.create_user_profile(item["user_id"], item["profile"])
        assert created["summary"], f"пустое описание профиля {item['user_id']}"
        print(f"профиль {item['user_id']}: {created['summary']}")


def ask(manager: AgentManager, user_id: str, question: str,
        offline: bool) -> dict:
    """Создаёт агента профиля, задаёт вопрос и возвращает результат.

    Агент на каждый профиль свой: общий агент «помнил» бы предыдущий ответ, и
    сравнение перестало бы быть честным.
    """
    agent_id = manager.create_agent(AgentConfig(
        name=f"Агент профиля {user_id}", user_id=user_id,
    ))
    agent = manager.require_agent(agent_id)
    if offline:
        # Офлайн-прогон без сети: подменяем только точку вызова DeepSeek.
        agent._make_client = lambda: StubClient()  # noqa: SLF001
    record = agent.generate(question)
    assert record["status"] == "ok", record.get("error")
    answer = record["response"] or ""
    assert answer.strip(), "модель вернула пустой ответ"
    return {
        "user_id": user_id,
        "agent_id": agent_id,
        "answer": answer,
        "system_prompt": record["system_prompt"],
        "profile": record["profile"],
        "usage": record.get("usage") or {},
        "duration_sec": record.get("duration_sec"),
        "offline": offline,
    }


def role_order(answer: str) -> list:
    """Роли инструкции в порядке первого упоминания в ответе."""
    positions = {}
    lowered = answer.lower()
    for role in ROLE_ORDER:
        index = lowered.find(role)
        if index >= 0:
            positions[role] = index
    return [role for role, _ in sorted(positions.items(), key=lambda kv: kv[1])]
