"""Посев демонстрационных инвариантов в БД дня (скрипт офлайн, без сети).

Что делает.
    Заводит четыре инварианта из ``backend/domain/demo_invariants.py`` — по одному
    на каждую категорию — в ``day17/agents.db`` (или в БД, указанной ``--db``).
    Тем же списком пользуются кнопка в интерфейсе и отчёт
    ``scripts/invariants_demo.py``, поэтому значения в UI и в отчёте не расходятся.

Зачем отдельный скрипт.
    ``invariants_demo.db`` пересоздаётся при каждом прогоне отчёта, а рабочая
    ``agents.db`` должна получать правила осознанно: посев идемпотентен
    (существующее имя не дублируется), а ``--reset`` пересобирает список заново.

Запуск из папки day17/:

    uv run python scripts/seed_invariants.py
    uv run python scripts/seed_invariants.py --reset
    uv run python scripts/seed_invariants.py --db some.db
"""
import argparse
import sys
from pathlib import Path

# Скрипты лежат в day17/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from backend.domain.demo_invariants import DEMO_INVARIANTS  # noqa: E402
from backend.storage.database import init_db, make_engine, make_session_factory  # noqa: E402
from backend.storage.invariant_store import InvariantManager  # noqa: E402

DEFAULT_DB = DAY_ROOT / "agents.db"


def build_manager(db_path: Path) -> InvariantManager:
    """Хранилище инвариантов на БД по указанному пути (таблицы создаются)."""
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)
    return InvariantManager(session_factory=make_session_factory(engine))


def reset(manager: InvariantManager) -> None:
    """Удаляет все инварианты: ``--reset`` пересобирает список с нуля."""
    removed = 0
    for item in manager.get_all_invariants(active_only=False):
        removed += 1 if manager.delete_invariant(item["id"]) else 0
    print(f"удалено инвариантов: {removed}")


def seed(manager: InvariantManager) -> None:
    """Сеет демо-инварианты: существующие имена не дублируются (идемпотентно)."""
    existing = {item["name"] for item in manager.get_all_invariants(active_only=False)}
    for item in DEMO_INVARIANTS:
        if item["name"] in existing:
            print(f"уже есть: {item['name']}")
            continue
        created = manager.add_invariant(**item)
        print(
            f"создан #{created['id']}: {created['name']} "
            f"[{created['category']}/{created['severity']}]"
        )


def main() -> int:
    """Разбирает аргументы и выполняет посев; возвращает код выхода."""
    parser = argparse.ArgumentParser(
        description="Завести демонстрационные инварианты дня 14 в SQLite.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB),
                        help=f"путь к файлу БД (по умолчанию {DEFAULT_DB.name})")
    parser.add_argument("--reset", action="store_true",
                        help="удалить все инварианты перед посевом")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = (Path.cwd() / db_path).resolve()
    manager = build_manager(db_path)
    print(f"БД: {db_path}")
    if args.reset:
        reset(manager)
    seed(manager)
    print(f"активных инвариантов: {len(manager.get_all_invariants())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
