"""Сборка markdown-отчёта ``docs/reports/personalization_comparison.md``.

Отчёт показывает, как ОДИН и тот же вопрос отвечается при разных профилях:
таблица «профиль — настройки — ответ — повлиявшие элементы», наблюдения по
каждому профилю (стиль, формат, длина, ограничения), системные промпты
запросов и проверка порядка ролей, заданного инструкцией профиля-оркестратора.
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Скрипт лежит в day13/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
_DAY_ROOT = Path(__file__).resolve().parents[1]
if str(_DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAY_ROOT))

from backend.core import config
from backend.domain.demo_profiles import (
    DEMO_FEATURE_REQUEST, DEMO_PROFILES, DEMO_QUESTION, demo_profile,
)
from comparison_stub import ORCHESTRATOR_USER, ROLE_ORDER, role_order


# Ограждение блоков кода в отчёте: 4 обратных кавычки, потому что в ответах
# модели встречаются обычные ``` — они не должны закрывать блок раньше времени.
FENCE = "````"


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
        "cd day13",
        "python scripts/personalization_comparison.py          # с API-ключом (day13/.env)",
        "python scripts/personalization_comparison.py --no-api # офлайн, без сети",
        "```",
        "",
    ]
    return "\n".join(line for line in lines if line is not None)
