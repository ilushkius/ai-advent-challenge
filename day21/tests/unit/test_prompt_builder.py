"""Промпт по зонам и кэш стабильного префикса (день 21).

Тесты фиксируют две вещи, ради которых модуль существует: (1) порядок зон —
стабильный префикс (профиль первым) выше динамики, хвостовая инструкция последняя;
(2) повторный запрос с тем же префиксом попадает в кэш, причём смена динамической
части кэш НЕ ломает (иначе экономия на кэше контекста была бы нулевой), а смена
стабильной части — ломает. Отдельно проверяется защита от изменчивого префикса:
метка времени в профиле делает попадание невозможным, и об этом пишется в лог.

Счётчик токенов в тестах подменён на «число слов»: он детерминирован, мгновенен и
не тянет tiktoken, а сами правила (зоны, кэш, зажим лимита) от токенизатора не
зависят. Интеграция с общим счётчиком проверяется отдельным тестом.
"""
import logging

import pytest

from backend.core import config
from backend.core.prompt_builder import (
    PromptBuilder,
    get_prompt_builder,
    looks_dynamic,
    reset_prompt_builder,
)
from backend.services.prompt_compressor import PromptCompressor
from shared.token_counter import count_tokens


def word_counter(text: str) -> int:
    """Счётчик «токенов» = число слов (детерминированная замена tiktoken в тестах)."""
    return len(text.split())


def test_looks_dynamic_finds_timestamp_and_hex_id():
    """Метка времени, 32-символьный hex и UUID распознаются как динамика."""
    assert looks_dynamic("обновлено 2026-09-28T18:16:02") is True
    assert looks_dynamic("ключ a1b2c3d4e5f60718293a4b5c6d7e8f90") is True
    assert looks_dynamic("id 3f2504e0-4f89-11d3-9a0c-0305e82c3301") is True


def test_looks_dynamic_ignores_stable_text():
    """Обычный текст и одна дата без времени динамикой не считаются."""
    assert looks_dynamic("") is False
    assert looks_dynamic("Ты — ассистент. Отвечай по-русски.") is False
    assert looks_dynamic("дата рождения: 2026-09-28") is False
    assert looks_dynamic("abc123") is False


def test_zones_order_stable_then_dynamic_then_tail():
    """Зоны идут строго по порядку, хвостовая инструкция — последняя."""
    builder = PromptBuilder(counter=word_counter)
    result = builder.build(profile="ПРОФИЛЬ", system="СИСТЕМА", general="ОБЩЕЕ",
                           dynamic=["ДИНАМИКА"], tool_results=["РЕЗУЛЬТАТ"],
                           user_query="вопрос")
    text = result["system"]
    assert text.index("ПРОФИЛЬ") < text.index("СИСТЕМА") < text.index("ОБЩЕЕ")
    assert text.index("ОБЩЕЕ") < text.index("ДИНАМИКА") < text.index("РЕЗУЛЬТАТ")
    assert text.strip().endswith("токенов.")
    assert str(result["max_tokens"]) in text


def test_profile_is_the_first_stable_part():
    """Профиль открывает промпт: он одинаков во всех запросах пользователя."""
    builder = PromptBuilder(counter=word_counter)
    result = builder.build(system="СИСТЕМА", profile="# Профиль\nИмя: Аня",
                           invariants="ИНВАРИАНТ")
    assert result["system"].startswith("# Профиль")


def test_stable_prefix_assembles_in_order_without_cache_side_effects():
    """Публичный ``stable_prefix`` собирает зоны и не трогает кэш и счётчики."""
    builder = PromptBuilder(counter=word_counter)
    text = builder.stable_prefix(profile="# Профиль", invariants="Инвариант",
                                 general="Общее")
    assert text == "# Профиль\n\nИнвариант\n\nОбщее"
    assert builder.stats()["cache_size"] == 0
    assert builder.stats()["requests"] == 0


def test_empty_input_has_no_system_message():
    """Полностью пустой ввод: ни system-сообщения, ни токенов, ни хвоста."""
    builder = PromptBuilder(counter=word_counter)
    result = builder.build()
    assert result == {"messages": [], "system": "", "max_tokens": 1000,
                      "stable_tokens": 0, "dynamic_tokens": 0, "saved_tokens": 0,
                      "cache_hit": False}


def test_only_user_query_does_not_breed_system_message():
    """Без стабильной части и динамики system не появляется: инструкция — это шум."""
    builder = PromptBuilder(counter=word_counter)
    result = builder.build(user_query="просто вопрос")
    assert result["system"] == ""
    assert result["messages"] == [{"role": "user", "content": "просто вопрос"}]


def test_messages_are_system_history_user():
    """Порядок сообщений: system, затем история, затем текущий вопрос."""
    builder = PromptBuilder(counter=word_counter)
    result = builder.build(
        system="СИСТЕМА", user_query="вопрос",
        history=[{"role": "user", "content": "раньше"},
                 {"role": "assistant", "content": "ответ"}])
    assert result["messages"] == [
        {"role": "system", "content": result["system"]},
        {"role": "user", "content": "раньше"},
        {"role": "assistant", "content": "ответ"},
        {"role": "user", "content": "вопрос"},
    ]


def test_history_and_query_stay_out_of_system():
    """История и текущий вопрос не попадают в system-сообщение."""
    builder = PromptBuilder(counter=word_counter)
    result = builder.build(system="СИСТЕМА", user_query="ТЕКУЩИЙ ВОПРОС",
                           history=[{"role": "user", "content": "СТАРАЯ РЕПЛИКА"}])
    assert "ТЕКУЩИЙ ВОПРОС" not in result["system"]
    assert "СТАРАЯ РЕПЛИКА" not in result["system"]


def test_repeated_prefix_comes_from_cache():
    """Второй вызов с теми же частями: попадание в кэш, первая — промах."""
    builder = PromptBuilder(counter=word_counter)
    first = builder.build(profile="ПРОФИЛЬ", system="СИСТЕМА", user_query="раз")
    second = builder.build(profile="ПРОФИЛЬ", system="СИСТЕМА", user_query="два")
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert builder.cache_hits == 1
    assert builder.cache_misses == 1
    assert builder.stats()["cache_size"] == 1
    # Вопрос уходит только в messages — system обеих сборок совпадает (префикс и
    # его токены взяты из кэша, повторного подсчёта нет).
    assert first["system"] == second["system"]
    assert first["stable_tokens"] == second["stable_tokens"] == word_counter("ПРОФИЛЬ\n\nСИСТЕМА")
    assert first["messages"] != second["messages"]


def test_cached_prefix_is_not_recounted():
    """Токены кэшированного префикса не считаются второй раз (иначе кэш бесполезен)."""
    texts = []

    def recording_counter(text: str) -> int:
        texts.append(text)
        return len(text.split())

    builder = PromptBuilder(counter=recording_counter)
    builder.build(profile="ПРОФИЛЬ", system="СИСТЕМА")
    builder.build(profile="ПРОФИЛЬ", system="СИСТЕМА")
    assert texts.count("ПРОФИЛЬ\n\nСИСТЕМА") == 1
    assert builder.stats()["stable_tokens"] == 2 * word_counter("ПРОФИЛЬ\n\nСИСТЕМА")


def test_dynamic_change_does_not_invalidate_prefix():
    """Смена динамических блоков сохраняет попадание в кэш стабильного префикса."""
    builder = PromptBuilder(counter=word_counter)
    builder.build(system="СИСТЕМА", dynamic=["первый блок состояния"])
    result = builder.build(system="СИСТЕМА", dynamic=["другое состояние задачи"],
                           tool_results=["свежий результат инструмента"])
    assert result["cache_hit"] is True
    assert builder.cache_hits == 1
    assert builder.cache_misses == 1


def test_stable_change_makes_it_a_miss():
    """Смена стабильной части — промах: общего префикса больше нет."""
    builder = PromptBuilder(counter=word_counter)
    builder.build(system="СИСТЕМА")
    result = builder.build(system="ДРУГАЯ СИСТЕМА")
    assert result["cache_hit"] is False
    assert builder.cache_hits == 0
    assert builder.cache_misses == 2
    assert builder.stats()["cache_size"] == 2


def test_prefix_with_timestamp_is_not_cached(caplog):
    """Метка времени в профиле: промах, пустой кэш и предупреждение в лог."""
    builder = PromptBuilder(counter=word_counter)
    profile = "Профиль\nОбновлено: 2026-09-28T18:16:02"
    with caplog.at_level(logging.WARNING):
        first = builder.build(profile=profile)
        second = builder.build(profile=profile)
    assert first["cache_hit"] is False
    assert second["cache_hit"] is False
    assert builder.cache_hits == 0
    assert builder.stats()["cache_size"] == 0
    assert "в кэш не кладу" in caplog.text


def test_prefix_with_hex_id_is_not_cached():
    """Hex-id в системной части — такая же изменчивая динамика: в кэш не идёт."""
    builder = PromptBuilder(counter=word_counter)
    builder.build(system="session " + "a" * 32)
    assert builder.stats()["cache_size"] == 0
    assert builder.cache_hits == 0


@pytest.mark.parametrize("task_type,expected", [
    (config.LLM_TASK_CHAT, 1000),
    (config.LLM_TASK_INDEXING, 4000),
    (config.LLM_TASK_SUMMARY, 512),
])
def test_max_tokens_by_task_type(task_type, expected):
    """Предел ответа берётся по типу задачи (без зажима пользовательским лимитом)."""
    builder = PromptBuilder(counter=word_counter)
    assert builder.max_tokens_for(task_type) == expected
    # Пользовательский лимит выше предела задачи — побеждает предел задачи.
    result = PromptBuilder(counter=word_counter, max_response_tokens=8000).build(
        system="СИСТЕМА", task_type=task_type)
    assert result["max_tokens"] == expected


def test_max_tokens_is_clamped_by_user_limit():
    """Длинная задача зажимается лимитом агента, по умолчанию — общий предел дня."""
    builder = PromptBuilder(counter=word_counter)
    result = builder.build(system="СИСТЕМА", task_type=config.LLM_TASK_INDEXING,
                           max_response_tokens=300)
    assert result["max_tokens"] == 300
    default_result = builder.build(system="СИСТЕМА",
                                   task_type=config.LLM_TASK_INDEXING)
    assert default_result["max_tokens"] == config.LLM_MAX_RESPONSE_TOKENS
    assert builder.max_tokens_for(None) == config.LLM_MAX_RESPONSE_TOKENS
    assert builder.max_tokens_for("неизвестный тип") == config.LLM_MAX_RESPONSE_TOKENS


def test_compression_shrinks_dynamic_zone_and_reports_savings():
    """Сжатие динамики уменьшает dynamic_tokens и заполняет saved_tokens."""
    block = ("<!-- служебный комментарий -->\n- ok\n- ok\n- ok\n\n"
             "много    пробелов")
    builder = PromptBuilder(counter=word_counter)
    squeezed = builder.build(system="СИСТЕМА", dynamic=[block])
    raw = PromptBuilder(counter=word_counter).build(system="СИСТЕМА",
                                                    dynamic=[block], compress=False)
    assert squeezed["dynamic_tokens"] < raw["dynamic_tokens"]
    assert squeezed["saved_tokens"] > 0
    assert raw["saved_tokens"] == 0
    assert "служебный комментарий" not in squeezed["system"]
    assert "служебный комментарий" in raw["system"]
    assert squeezed["saved_tokens"] == raw["dynamic_tokens"] - squeezed["dynamic_tokens"]


def test_compression_off_keeps_stable_tokens_identical():
    """Выключенное сжатие не трогает стабильный префикс и его токены."""
    builder = PromptBuilder(counter=word_counter)
    result = builder.build(system="СИСТЕМА", dynamic=["блок состояния"],
                           compress=False)
    assert result["stable_tokens"] == word_counter("СИСТЕМА")
    assert "блок состояния" in result["system"]


def test_compress_method_shrinks_single_block():
    """Публичный ``compress`` сжимает один блок (им агент допишет контекст хода)."""
    builder = PromptBuilder(counter=word_counter)
    assert isinstance(builder.compressor, PromptCompressor)
    block = "- ok\n- ok\n- ok\n\nконец"
    squeezed = builder.compress(block)
    assert squeezed == "- ok\n\nконец"
    assert word_counter(squeezed) < word_counter(block)
    assert builder.compress("") == ""
    # Счётчики сжатия живут в компрессоре, а не в статистике строителя.
    assert builder.compressor.stats["calls"] == 1
    assert builder.stats()["saved_tokens"] == 0


def test_stats_counts_and_hit_percent():
    """Статистика: запросы, попадания, доля попаданий и суммарные токены."""
    builder = PromptBuilder(counter=word_counter)
    for _ in range(3):
        builder.build(system="СИСТЕМА")
    stats = builder.stats()
    assert stats["requests"] == 3
    assert stats["cache_misses"] == 1
    assert stats["cache_hits"] == 2
    assert stats["cache_hit_percent"] == pytest.approx(66.7)
    assert stats["stable_tokens"] == 3 * word_counter("СИСТЕМА")


def test_stats_without_requests():
    """Без запросов доля попаданий — 0.0, а не деление на ноль."""
    builder = PromptBuilder(counter=word_counter)
    stats = builder.stats()
    assert stats["requests"] == 0
    assert stats["cache_hit_percent"] == 0.0
    assert stats["cache_size"] == 0


def test_reset_clears_cache_and_counters():
    """reset обнуляет кэш и счётчики: следующий вызов снова промах."""
    builder = PromptBuilder(counter=word_counter)
    builder.build(system="СИСТЕМА")
    builder.build(system="СИСТЕМА")
    builder.reset()
    assert builder.cache_hits == 0
    assert builder.cache_misses == 0
    assert builder.stats()["cache_size"] == 0
    assert builder.stats()["requests"] == 0
    assert builder.build(system="СИСТЕМА")["cache_hit"] is False


def test_default_counter_is_the_shared_token_counter():
    """По умолчанию токены считает общий ``shared.token_counter.count_tokens``."""
    builder = PromptBuilder()
    result = builder.build(system="Ты — ассистент дня 21.", user_query="привет")
    assert result["stable_tokens"] == count_tokens("Ты — ассистент дня 21.")
    assert result["dynamic_tokens"] == 0
    assert result["messages"][0]["content"].startswith("Ты — ассистент дня 21.")


def test_singleton_is_lazy_and_resettable():
    """Singleton один на процесс и сбрасывается для изоляции тестов."""
    reset_prompt_builder()
    first = get_prompt_builder()
    assert get_prompt_builder() is first
    reset_prompt_builder()
    assert get_prompt_builder() is not first
