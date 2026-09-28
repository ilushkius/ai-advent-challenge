"""Сжатие промптов: комментарии, JSON в блоках, дубли строк, пробелы (день 21).

Проверяется главное свойство модуля: он убирает украшения разметки и ничего не
теряет по смыслу. Отсюда три группы проверок — «сжатое стало короче», «смысл на
месте» (JSON разбирается в тот же объект, код внутри блока не переформатирован) и
«повторное сжатие ничего не меняет» (идемпотентность: блоки могут проходить через
компрессор дважды — при сборке промпта и при дописывании блока агентом).
"""
import json

from backend.services.prompt_compressor import (
    PromptCompressor,
    compress_text,
    dedupe_lines,
    dedupe_paragraphs,
    minify_json_blocks,
    normalize_whitespace,
    remove_comments,
)
from shared.token_counter import count_tokens


def test_remove_comments_keeps_words_apart():
    """Комментарий заменяется пробелом: соседние слова не склеиваются."""
    assert remove_comments("до<!-- невидимое -->после") == "до после"
    assert remove_comments("<!-- верхний -->\nтекст") == " \nтекст"
    assert remove_comments("текст") == "текст"


def test_remove_comments_multiline():
    """Многострочный комментарий убирается целиком."""
    text = "начало\n<!--\nслужебная\nшапка\n-->\nконец"
    assert "служебная" not in remove_comments(text)
    assert "конец" in remove_comments(text)


def test_normalize_whitespace():
    """Хвостовые пробелы, серии пробелов и пустых строк приводятся к одному виду."""
    assert normalize_whitespace("строка   с   пробелами   \n\n\n\nвторая") == \
        "строка с пробелами\n\nвторая"
    assert normalize_whitespace("а\t\tб") == "а б"
    assert normalize_whitespace("") == ""


def test_dedupe_lines_collapses_neighbours():
    """Подряд идущие одинаковые строки склеиваются, разные и пустые остаются."""
    assert dedupe_lines("- ok\n- ok\n- ok\n- нет\n") == "- ok\n- нет\n"
    # Сравнение без хвостовых пробелов: журнал генератора различается только ими.
    assert dedupe_lines("- ok  \n- ok\n") == "- ok  \n"
    assert dedupe_lines("а\n\nб") == "а\n\nб"


def test_dedupe_paragraphs_drops_repeat():
    """Абзац-дубль, идущий сразу за оригиналом, выбрасывается."""
    assert dedupe_paragraphs("повтор\n\nповтор\n\nразное") == "повтор\n\nразное"
    assert dedupe_paragraphs("а\n\nб\n\nа") == "а\n\nб\n\nа"


def test_minify_json_blocks_only_valid_json():
    """Минифицируется только разбираемый JSON; код и битый JSON целы."""
    payload = {"b": 2, "a": [1, {"c": "тест"}]}
    block = f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    minified = minify_json_blocks(block)
    inner = minified.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert "\n" not in inner
    assert json.loads(inner) == payload

    broken = "```json\n{не json}\n```"
    assert minify_json_blocks(broken) == broken
    code = "```python\nx = {'a': 1}\n```"
    assert minify_json_blocks(code) == code


def test_compress_minifies_json_and_keeps_it_valid():
    """JSON в блоке минифицирован, но разбирается в тот же объект."""
    payload = {"step": "search", "count": 3, "items": ["а", "б"]}
    text = f"## Шаг\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=4)}\n```"
    result = compress_text(text)
    inner = result.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert json.loads(inner) == payload
    assert "    " not in result
    assert len(result) < len(text)


def test_compress_minifies_bare_fence():
    """Блок без языка минифицируется: там лежит JSON ответа инструмента."""
    result = compress_text('```\n{"actions": [1, 2]}\n```')
    assert result == '```\n{"actions":[1,2]}\n```'


def test_compress_does_not_touch_code_fence_formatting():
    """Пробелы внутри блока кода не трогаются: пример должен остаться рабочим."""
    text = "Пояснение.\n\n```python\nif x:\n    return  1\n\n\n    return 2\n```"
    result = compress_text(text)
    assert "    return  1" in result
    assert "\n\n\n" in result


def test_compress_collapses_duplicates_and_comments():
    """Проза: комментарии, дубли строк и серии пробелов уходят."""
    text = "<!-- шапка -->\n- ok\n- ok\n- ok\n\nчастая   строка\nчастая   строка\n"
    result = compress_text(text)
    assert result == "- ok\n\nчастая строка"


def test_compress_minifies_whole_block_json():
    """Голый JSON (без забора) минифицируется, содержимое строк не портится."""
    text = '{\n  "message": "два  пробела",\n  "items": [1, 2, 3]\n}'
    result = compress_text(text)
    assert result == '{"message":"два  пробела","items":[1,2,3]}'
    assert json.loads(result) == json.loads(text)


def test_compress_keeps_prose_that_is_not_json():
    """Текст, не разбираемый как JSON, идёт обычным путём (пробелы сжимаются)."""
    assert compress_text("обычный   текст") == "обычный текст"
    assert compress_text("42") == "42"


def test_compress_empty_and_whitespace_only():
    """Пустая строка и строка из пробелов дают пустую строку."""
    assert compress_text("") == ""
    assert compress_text("   \n\n \t\n") == ""


def test_compress_is_idempotent():
    """Повторное сжатие результата ничего не меняет."""
    text = (
        "<!-- служебное -->\n"
        "## Раздел\n\n"
        "повтор\n\nповтор\n\n"
        "- ok\n- ok\n- ok\n\n"
        "```json\n" + json.dumps({"a": {"b": [1, 2]}}, ensure_ascii=False, indent=2) + "\n```\n\n"
        "хвост   с   пробелами\n\n\n\n"
    )
    once = compress_text(text)
    assert compress_text(once) == once


def test_compress_keeps_meaningful_text():
    """Смысловые строки остаются на месте: модуль ничего не «ужимает» по смыслу."""
    lines = [f"шаг {index}: сделано" for index in range(20)]
    result = compress_text("\n".join(lines))
    assert all(line in result for line in lines)


def test_compressor_stats_and_reset():
    """Статистика считает вызовы, токены до/после и экономию; reset её обнуляет."""
    compressor = PromptCompressor()
    assert compressor.stats == {"calls": 0, "tokens_before": 0, "tokens_after": 0,
                                "saved_tokens": 0, "saved_percent": 0.0}

    payload = {"steps": [{"tool": "search", "count": index} for index in range(10)]}
    text = f"```json\n{json.dumps(payload, indent=4)}\n```"
    compressor.compress(text)
    stats = compressor.stats
    assert stats["calls"] == 1
    assert stats["tokens_before"] == count_tokens(text)
    assert stats["tokens_after"] > 0
    assert stats["saved_tokens"] == stats["tokens_before"] - stats["tokens_after"]
    assert stats["saved_tokens"] > 0
    assert stats["saved_percent"] > 0

    compressor.reset()
    assert compressor.stats["calls"] == 0
    assert compressor.stats["saved_percent"] == 0.0


def test_compressor_saves_tokens_on_json_block():
    """На реальном блоке с JSON экономия измеряется в токенах tiktoken."""
    payload = {"key_points": [f"пункт {index} с текстом" for index in range(8)]}
    text = f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    compressor = PromptCompressor()
    result = compressor.compress(text)
    assert count_tokens(result) < count_tokens(text)
    assert compressor.stats["saved_tokens"] > 0


def test_compress_blocks_keeps_order_and_count():
    """Список блоков сжимается по порядку и не меняет длину; статистика — по вызовам."""
    compressor = PromptCompressor()
    blocks = ["а\n\n\n\nб", "```json\n{\"a\": 1}\n```", "   "]
    result = compressor.compress_blocks(blocks)
    assert len(result) == len(blocks)
    assert result[0] == "а\n\nб"
    assert result[1] == '```json\n{"a":1}\n```'
    assert result[2] == ""
    assert compressor.stats["calls"] == 3


def test_compress_empty_counts_as_call_without_savings():
    """Пустой блок: результат пуст, экономии нет, деление на ноль не падает."""
    compressor = PromptCompressor()
    assert compressor.compress("") == ""
    assert compressor.stats["calls"] == 1
    assert compressor.stats["saved_tokens"] == 0
    assert compressor.stats["saved_percent"] == 0.0


def test_compress_custom_counter_is_used():
    """Счётчик токенов подменяем: тесты и офлайн-сценарии не зависят от tiktoken."""
    compressor = PromptCompressor(counter=len)
    compressor.compress("абв")
    assert compressor.stats["tokens_before"] == 3
