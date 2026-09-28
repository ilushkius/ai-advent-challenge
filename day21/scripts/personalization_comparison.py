"""Сравнение профилей дня 12 (скрипт унаследован в день 13): один вопрос — разные ответы.

Запуск из папки дня (обязательно: пути к БД и .env считаются от ``backend/``):

    uv run python scripts/personalization_comparison.py            # реальные запросы к DeepSeek
    uv run python scripts/personalization_comparison.py --no-api   # офлайн, без сети (заглушка)

Что делает скрипт.

1. Создаёт отдельную БД ``day17/personalization_demo.db`` (файл удаляется и
   создаётся заново, поэтому прогон воспроизводим) и три профиля из
   ``backend/demo_profiles.py`` — те же, что в интерфейсе, поэтому отчёт и UI не
   расходятся:

   - ``strict_tech`` — «Строгий технический»: технический стиль, кратко,
     plain text, ограничение 600 символов;
   - ``friendly_mentor`` — «Дружелюбный наставник»: дружелюбно, подробно,
     markdown, инструкции «объясняй простыми словами, используй аналогии» и
     «обращайся по имени»;
   - ``process_orchestrator`` — «Оркестратор процесса»: инструкция про порядок
     ролей на запрос «напиши фичу» (аналитик → разработчик → тестировщик).

2. Создаёт по агенту на профиль (персонализация подключается при инициализации
   агента) и задаёт ОДИН и тот же вопрос двум первым профилям. Свои агенты и
   пустая история — чтобы разница ответов объяснялась только профилем.

3. Просит третий профиль «напиши фичу: экспорт отчётов в Excel» и проверяет по
   тексту ответа, что роли идут именно в порядке аналитик → разработчик →
   тестировщик (то есть инструкция учтена, а не просто лежит в промпте).

4. Пишет отчёт ``docs/reports/personalization_comparison.md``: таблица «профиль — настройки —
   ответ — какие элементы профиля повлияли», наблюдения по каждому профилю,
   системные промпты запросов и проверка порядка ролей.

Офлайн-режим (``--no-api``) подменяет клиент DeepSeek заглушкой, которая
«отвечает» по системному промпту: он нужен для проверки самого скрипта и для
запуска без ключа API. В отчёте такой прогон помечается явно.
"""
import sys
from pathlib import Path

# Скрипт лежит в day17/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
_DAY_ROOT = Path(__file__).resolve().parents[1]
if str(_DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAY_ROOT))

from backend.core import config
from backend.domain.demo_profiles import DEMO_FEATURE_REQUEST, DEMO_QUESTION
from comparison_report import build_report, observations
from comparison_stub import (
    COMPARISON_USERS, DAY_ROOT, ORCHESTRATOR_USER, ROLE_ORDER, ask,
    ensure_profiles, prepare_manager, role_order,
)

REPORT = DAY_ROOT / "docs" / "reports" / "personalization_comparison.md"


def main(argv: list) -> int:
    offline = "--no-api" in argv
    if not offline and not config.resolve_api_key():
        print(
            "Нет ключа DEEPSEEK_API_KEY (day17/.env или переменная окружения). "
            "Запустите с --no-api для офлайн-прогона со заглушкой.",
            file=sys.stderr,
        )
        return 2

    manager = prepare_manager()
    ensure_profiles(manager)

    print(f"вопрос: {DEMO_QUESTION}")
    strict = ask(manager, COMPARISON_USERS[0], DEMO_QUESTION, offline)
    friendly = ask(manager, COMPARISON_USERS[1], DEMO_QUESTION, offline)
    print("ответ строгого профиля: "
          f"{len(strict['answer'])} символов, "
          f"элементов профиля: {len(strict['profile']['elements'])}")
    print("ответ дружелюбного профиля: "
          f"{len(friendly['answer'])} символов, "
          f"элементов профиля: {len(friendly['profile']['elements'])}")

    print(f"запрос про порядок ролей: {DEMO_FEATURE_REQUEST}")
    orchestrator = ask(manager, ORCHESTRATOR_USER, DEMO_FEATURE_REQUEST, offline)
    order = role_order(orchestrator["answer"])
    print("порядок ролей в ответе: " + (" → ".join(order) if order else "роли не найдены"))

    checks = observations(strict, friendly, orchestrator)
    for title, passed, fact in checks:
        print(f"{'✅' if passed else '❌'} {title}: {fact}")

    # Персонализация обязана быть в промпте: иначе отчёт бесполезен.
    for result in (strict, friendly, orchestrator):
        assert result["profile"]["personalized"], (
            f"профиль {result['user_id']} не попал в системный промпт"
        )
        assert result["system_prompt"], "пустой системный промпт запроса"
    assert order == list(ROLE_ORDER), (
        "инструкция о порядке ролей не отражена в ответе: " + str(order)
    )
    # Проверки стиля/формата/длины — наблюдения, а не гарантии: модель
    # вероятностная, и промпт-ограничение сдвигает ответ, но не обязывает его
    # точно соблюсти. Их результат попадает в отчёт как факт прогона.
    passed_checks = sum(1 for _, passed, _ in checks if passed)
    print(f"наблюдений выполнено: {passed_checks} из {len(checks)}")

    REPORT.write_text(
        build_report(strict, friendly, orchestrator, checks, offline),
        encoding="utf-8",
    )
    print(f"отчёт записан: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
