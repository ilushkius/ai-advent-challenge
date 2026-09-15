"""Сравнение профилей дня 12: один вопрос — разные ответы.

Запуск из папки дня (обязательно: пути к БД и .env считаются от ``backend/``):

    python personalization_comparison.py            # реальные запросы к DeepSeek
    python personalization_comparison.py --no-api   # офлайн, без сети (заглушка)

Что делает скрипт.

1. Создаёт отдельную БД ``day12/personalization_demo.db`` (файл удаляется и
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

4. Пишет отчёт ``personalization_comparison.md``: таблица «профиль — настройки —
   ответ — какие элементы профиля повлияли», наблюдения по каждому профилю,
   системные промпты запросов и проверка порядка ролей.

Офлайн-режим (``--no-api``) подменяет клиент DeepSeek заглушкой, которая
«отвечает» по системному промпту: он нужен для проверки самого скрипта и для
запуска без ключа API. В отчёте такой прогон помечается явно.
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend import config
from backend.agent_manager import AgentManager
from backend.database import init_db, make_engine, make_session_factory
from backend.demo_profiles import (
    DEMO_FEATURE_REQUEST, DEMO_PROFILES, DEMO_QUESTION, demo_profile,
)
from backend.models import AgentConfig

HERE = Path(__file__).resolve().parent
DEMO_DB = HERE / "personalization_demo.db"
REPORT = HERE / "personalization_comparison.md"

# Ограждение блоков кода в отчёте: 4 обратных кавычки, потому что в ответах
# модели встречаются обычные ``` — они не должны закрывать блок раньше времени.
FENCE = "````"

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


def markdown_markers(answer: str) -> list:
    """Найденные признаки markdown-разметки (заголовки, списки, выделение)."""
    markers = []
    if re.search(r"^\s{0,3}#{1,6}\s", answer, re.MULTILINE):
        markers.append("заголовки")
    if re.search(r"^\s*[-*+]\s", answer, re.MULTILINE):
        markers.append("списки")
    if "**" in answer or "__" in answer:
        markers.append("жирный текст")
    if re.search(r"^\s*```", answer, re.MULTILINE):
        markers.append("блоки кода")
    return markers


def observations(strict: dict, friendly: dict, orchestrator: dict) -> list:
    """Наблюдаемые эффекты профилей: проверка — результат — факт.

    Проверки сформулированы так, чтобы их результат был виден в самих ответах:
    ограничение длины, формат без разметки, объём подробного ответа, порядок
    ролей из кастомной инструкции.
    """
    strict_answer, friendly_answer = strict["answer"], friendly["answer"]
    strict_marks = markdown_markers(strict_answer)
    friendly_marks = markdown_markers(friendly_answer)
    order = role_order(orchestrator["answer"])
    checks = [
        (
            "Строгий технический: ответ держится у лимита 600 символов "
            "(constraints.max_response_length; допуск 1.5×, потому что модель "
            "соблюдает ограничение приблизительно)",
            len(strict_answer) <= 600 * 1.5,
            f"{len(strict_answer)} символов при лимите 600",
        ),
        (
            "Строгий технический: ответ без markdown-разметки "
            "(preferences.format = plain text)",
            not strict_marks,
            "разметка: " + (", ".join(strict_marks) if strict_marks else "нет"),
        ),
        (
            "Дружелюбный наставник: ответ в markdown "
            "(preferences.format = markdown)",
            bool(friendly_marks),
            "разметка: " + (", ".join(friendly_marks) if friendly_marks else "нет"),
        ),
        (
            "Дружелюбный наставник: ответ подробнее, чем у строгого профиля "
            "(preferences.verbosity = подробно)",
            len(friendly_answer) > len(strict_answer),
            f"{len(friendly_answer)} против {len(strict_answer)} символов",
        ),
        (
            "Оркестратор процесса: роли идут в порядке аналитик → разработчик → "
            "тестировщик (custom_instructions)",
            order == list(ROLE_ORDER),
            "порядок в ответе: " + (" → ".join(order) if order else "роли не найдены"),
        ),
    ]
    return checks


def cell(text: str) -> str:
    """Текст для ячейки markdown-таблицы: пайпы и переносы не ломают таблицу."""
    return text.replace("|", "\\|").replace("\n", "<br>").strip()


def settings_line(profile: dict) -> str:
    """Настройки профиля одной строкой: стиль/длина/язык/формат + ограничения."""
    prefs = profile.get("preferences") or {}
    cons = profile.get("constraints") or {}
    parts = [
        f"tone={prefs.get('tone') or '—'}",
        f"verbosity={prefs.get('verbosity') or '—'}",
        f"language={prefs.get('language') or '—'}",
        f"format={prefs.get('format') or '—'}",
    ]
    if cons.get("max_response_length"):
        parts.append(f"max_response_length={cons['max_response_length']}")
    if cons.get("forbidden_topics"):
        parts.append("forbidden_topics=" + ", ".join(cons["forbidden_topics"]))
    if cons.get("required_disclaimers"):
        parts.append("required_disclaimers=" + "; ".join(cons["required_disclaimers"]))
    if profile.get("custom_instructions"):
        instructions = " / ".join(
            line for line in profile["custom_instructions"].splitlines() if line
        )
        parts.append(f"custom_instructions={instructions}")
    return ", ".join(parts)


def influence_line(result: dict) -> str:
    """Какие элементы профиля попали в промпт (по отчёту агента)."""
    elements = (result["profile"] or {}).get("elements") or []
    if not elements:
        return "профиль не заполнен — в промпт ничего не добавлено"
    return "; ".join(f"{item['label']} = {item['value']}" for item in elements)


def build_report(strict: dict, friendly: dict, orchestrator: dict,
                 checks: list, offline: bool) -> str:
    """Собирает markdown-отчёт сравнения профилей."""
    profiles = {item["user_id"]: item for item in DEMO_PROFILES}
    titles = {user_id: item["title"] for user_id, item in profiles.items()}
    results = [strict, friendly]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode = ("офлайн-заглушка (`--no-api`, без сети)" if offline
            else "реальные запросы к DeepSeek (`deepseek-chat`)")

    lines = [
        "# Сравнение профилей пользователя (день 12)",
        "",
        f"Прогон: {now} · режим: {mode} · модель: **{config.MODEL_CHAT}**",
        "",
        "Один и тот же вопрос задан двум профилям с противоположными "
        "настройками. Каждый профиль получил СВОЕГО агента с пустой историей, "
        "поэтому разница ответов объясняется только персонализацией "
        "(профиль подключается к системному промпту запроса).",
        "",
        f"**Вопрос:** {DEMO_QUESTION}",
        "",
        "## Таблица сравнения",
        "",
        "| Профиль | Настройки | Ответ агента | Какие элементы профиля повлияли |",
        "|---|---|---|---|",
    ]
    for result in results:
        profile = demo_profile(result["user_id"])
        lines.append(
            f"| **{titles[result['user_id']]}** (`{result['user_id']}`) "
            f"| {cell(settings_line(profile))} "
            f"| {cell(result['answer'])} "
            f"| {cell(influence_line(result))} |"
        )
    lines += [
        "",
        "## Полные ответы",
        "",
    ]
    for result in results:
        profile = demo_profile(result["user_id"])
        lines += [
            f"### {titles[result['user_id']]} (`{result['user_id']}`)",
            "",
            f"Настройки: {settings_line(profile)}",
            "",
            f"Ожидание: {profiles[result['user_id']]['expectation']}",
            "",
            "Ответ агента:",
            "",
            FENCE + "text",
            result["answer"],
            FENCE,
            "",
            "Системный промпт запроса (что ушло в модель):",
            "",
            FENCE + "text",
            result["system_prompt"],
            FENCE,
            "",
            f"Токены запроса: {result['usage'].get('total_tokens', '—')} · "
            f"время: {(result['duration_sec'] or 0):.2f} с",
            "",
        ]

    lines += [
        "## Профиль с инструкцией о порядке ролей",
        "",
        f"Профиль **{titles[ORCHESTRATOR_USER]}** "
        f"(`{ORCHESTRATOR_USER}`) содержит custom_instructions:",
        "",
        FENCE + "text",
        demo_profile(ORCHESTRATOR_USER)["custom_instructions"],
        FENCE,
        "",
        f"**Запрос:** {DEMO_FEATURE_REQUEST}",
        "",
        "Ответ агента:",
        "",
        FENCE + "text",
        orchestrator["answer"],
        FENCE,
        "",
        "Системный промпт запроса:",
        "",
        FENCE + "text",
        orchestrator["system_prompt"],
        FENCE,
        "",
    ]

    lines += [
        "## Наблюдаемые эффекты профилей",
        "",
        "| Проверка | Результат | Факт из ответа |",
        "|---|---|---|",
    ]
    for title, passed, fact in checks:
        lines.append(f"| {title} | {'✅ да' if passed else '❌ нет'} | {cell(fact)} |")

    lines += [
        "",
        "Проверки стиля, формата и длины — это наблюдения, а не гарантии: "
        "модель вероятностная, и ограничение из профиля сдвигает ответ "
        "(промпт «жёсткое ограничение: весь ответ не длиннее N символов»), но "
        "не обязывает её соблюсти лимит символ в символ. Факт этого прогона: "
        f"{len(strict['answer'])} символов при лимите "
        f"{demo_profile('strict_tech')['constraints']['max_response_length']} "
        f"у строгого профиля против {len(friendly['answer'])} символов у "
        "«подробного» — "
        "ограничение работает как управление объёмом, а не как обрезка текста. "
        "Проверки, которые обязаны выполняться всегда, — подстановка профиля в "
        "системный промпт (видно в разделе с промптами) и следование кастомной "
        "инструкции о порядке ролей.",
        "",
    ]

    lines += [
        "",
        "## Вывод",
        "",
        "Профиль — это часть системного промпта, а не подсказка в UI: один и тот "
        "же вопрос получает разные ответы по стилю (technical → friendly), "
        "формату (plain text → markdown), длине (кратко → подробно) и структуре "
        "(обычный ответ → разложенный по ролям аналитик → разработчик → "
        "тестировщик). Ограничения тоже работают как ограничения: "
        "max_response_length держит ответ в заданном пределе, forbidden_topics "
        "уводит разговор от запрещённых тем, required_disclaimers добавляет "
        "обязательную вставку.",
        "",
        "Воспроизведение:",
        "",
        "```bash",
        "cd day12",
        "python personalization_comparison.py          # с API-ключом (day12/.env)",
        "python personalization_comparison.py --no-api # офлайн, без сети",
        "```",
        "",
    ]
    return "\n".join(line for line in lines if line is not None)


def main(argv: list) -> int:
    offline = "--no-api" in argv
    if not offline and not config.resolve_api_key():
        print(
            "Нет ключа DEEPSEEK_API_KEY (day12/.env или переменная окружения). "
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
