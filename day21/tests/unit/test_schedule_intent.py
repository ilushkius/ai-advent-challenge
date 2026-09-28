"""Распознавание реплик трёх инструментов планировщика (день 18).

Проверяются реплики как их пишет человек: временной оборот превращается в секунды,
адрес источника — в аргумент сбора, а служебные слова не попадают в текст
напоминания. Отдельно проверяются два «нет»: реплика без триггеров и инструмент,
которого нет в каталоге подключённого сервера, — план не выдаётся, потому что
обещать вызов несуществующего инструмента нельзя.
"""
import pytest

from backend.domain.mcp_intent import classify_tool_call
from backend.domain.schedule_intent import (
    FALLBACK_REMINDER_TEXT,
    classify_schedule_intent,
    extract_url,
    parse_delay_seconds,
    parse_interval_seconds,
    parse_period_seconds,
    reminder_text,
    url_name,
)

#: Каталог своего сервера дня: три инструмента планировщика и три инструмента чтения.
CATALOG = ("get_user", "get_post", "list_user_posts",
           "schedule_reminder", "collect_data", "generate_summary")


def test_reminder_utterance_gives_delay_and_text():
    """«напомни мне через 5 минут проверить почту» → напоминание на 300 секунд."""
    intent = classify_schedule_intent("Напомни мне через 5 минут проверить почту", CATALOG)
    assert intent is not None
    assert intent.tool == "schedule_reminder"
    assert intent.arguments == {"text": "проверить почту", "delay_seconds": 300}


@pytest.mark.parametrize("text,seconds", [
    ("напомни через 30 секунд", 30),
    ("напомни мне через 1 час купить хлеб", 3600),
    ("напомни через 2 минуты", 120),
])
def test_delay_parsing_units(text, seconds):
    """Единицы времени переводятся в секунды, число берётся из реплики."""
    assert parse_delay_seconds(text) == seconds
    intent = classify_schedule_intent(text, CATALOG)
    assert intent is not None and intent.arguments["delay_seconds"] == seconds


def test_reminder_without_content_gets_placeholder():
    """Реплика без содержания даёт текст-заглушку, а не пустое напоминание."""
    intent = classify_schedule_intent("напомни через 30 секунд", CATALOG)
    assert intent is not None
    assert intent.arguments["text"] == FALLBACK_REMINDER_TEXT
    assert reminder_text("напомни мне через 30 секунд") == FALLBACK_REMINDER_TEXT


def test_collect_utterance_gives_url_period_and_name():
    """«собирай данные с <url> каждые 10 секунд» → сбор с адресом, периодом и именем."""
    intent = classify_schedule_intent(
        "Собирай данные с https://jsonplaceholder.typicode.com/posts каждые 10 секунд",
        CATALOG,
    )
    assert intent is not None
    assert intent.tool == "collect_data"
    assert intent.arguments == {
        "source_url": "https://jsonplaceholder.typicode.com/posts",
        "interval_seconds": 10,
        "name": "posts",
    }


def test_collect_without_url_is_not_a_call():
    """Без адреса собирать нечего: правило пропускается, а не выдаёт пустую задачу."""
    assert classify_schedule_intent("собирай данные каждые 10 секунд", CATALOG) is None


def test_summary_utterance_uses_period_of_the_question():
    """«покажи сводку за последний час» → сводка с периодом в час."""
    intent = classify_schedule_intent("Покажи сводку за последний час", CATALOG)
    assert intent is not None
    assert intent.tool == "generate_summary"
    assert intent.arguments["interval_seconds"] == 3600


@pytest.mark.parametrize("text,seconds", [
    ("покажи сводку за последние 5 минут", 300),
    ("покажи сводку за минуту", 60),
    ("покажи сводку каждые 20 секунд", 20),
])
def test_summary_period_parsing(text, seconds):
    """Период сводки читается и из оборота «за последние…», и из «каждые…»."""
    assert (parse_interval_seconds(text) or parse_period_seconds(text)) == seconds
    intent = classify_schedule_intent(text, CATALOG)
    assert intent is not None and intent.arguments["interval_seconds"] == seconds


@pytest.mark.parametrize("text", [
    "Сколько будет 2+2?",
    "Расскажи анекдот",
    "какие у нас планы на завтра",
])
def test_plain_utterances_are_not_scheduler_intents(text):
    """Реплика без ключевых слов планировщика — не намерение."""
    assert classify_schedule_intent(text, CATALOG) is None


def test_tool_absent_from_catalog_is_skipped():
    """Инструмента нет у подключённого сервера — обещать его вызов нельзя."""
    assert classify_schedule_intent("напомни мне через 30 секунд", ("get_user",)) is None
    assert classify_schedule_intent("покажи сводку за час", ("collect_data",)) is None


def test_url_extraction_and_name():
    """Адрес берётся целиком (без хвостовой пунктуации), имя — последний сегмент."""
    assert extract_url("собирай с https://example.test/posts каждые 5 секунд.") == (
        "https://example.test/posts"
    )
    assert extract_url("нет адреса") is None
    assert url_name("https://jsonplaceholder.typicode.com/posts") == "posts"
    # Без пути имя берётся из хоста (без зоны), с путём-файлом — из имени файла.
    assert url_name("https://example.test") == "example"
    assert url_name("https://example.test/data.json?v=1") == "data"


def test_reading_tools_still_recognised():
    """Регресс дня 17: реплики про пользователя и пост не ушли в планировщик."""
    plan = classify_tool_call("Найди информацию о пользователе с ID 1", CATALOG)
    assert plan is not None and plan.tool == "get_user"
    assert plan.arguments == {"user_id": 1}


def test_scheduler_intent_wins_for_its_own_phrases():
    """Общий распознаватель отдаёт планировщицкие реплики инструментам дня 18."""
    plan = classify_tool_call("напомни мне через 30 секунд проверить почту", CATALOG)
    assert plan is not None
    assert plan.tool == "schedule_reminder"
    assert plan.arguments == {"text": "проверить почту", "delay_seconds": 30}
