"""Сжатие промптов перед отправкой в модель (день 21).

Зачем модуль. Вход в модель оплачивается по токенам, а значительная часть
динамических блоков промпта — это «водянистая» разметка: HTML-комментарии,
JSON, отформатированный с отступами, продублированные строки журнала и
нагенерированные пробелы. Всё это не несёт смысла, но стоит денег, поэтому
динамическая часть промпта проходит через ``PromptCompressor.compress``.

Чего модуль НЕ делает. Он не сокращает и не перефразирует текст: никакого
«обрезания» и «ужатия смысла» здесь нет. Убираются только украшения разметки,
поэтому результат идемпотентен, а решение о том, что важно, остаётся за автором
блока промпта. Стабильный префикс промпта (профиль, системные правила,
инварианты) не сжимается вообще — см. ``backend/core/prompt_builder.py``: сжатие
префикса меняло бы самый длинный общий префикс запроса и убивало кэш контекста.

Все шаги — чистые функции модуля над строкой, в этом порядке:

1. ``remove_comments`` — убирает ``<!-- ... -->`` (в том числе многострочные);
2. ``minify_json_blocks`` — минифицирует JSON внутри блоков в тройных бэктиках,
   если содержимое разбирается ``json.loads``; блок, который не разбирается, не
   трогается вовсе. Блок, целиком состоящий из JSON без забора (так приходят
   результаты инструментов), минифицируется целиком — и тогда общие правила
   пробелов к нему не применяются: они бы испортили значение строки;
3. ``dedupe_lines`` — склеивает подряд идущие одинаковые строки;
   ``dedupe_paragraphs`` — выбрасывает абзац-дубль, идущий сразу за своим
   оригиналом (журналы и списки статусов часто дублируют одно и то же);
4. ``normalize_whitespace`` — хвостовые пробелы, три и более переводов строки →
   два, несколько пробелов подряд → один;
5. обрезка ведущих и хвостовых пустых строк (это делает ``compress_text``).

Шаги 1–4 идут по ТЕКСТУ ВНЕ блоков кода, шаг 2 — только по блокам кода: проглотить
пробелы внутри примера кода значило бы сломать сам пример, поэтому блоки в тройных
бэктиках неприкосновенны (кроме минификации JSON в них).
"""
from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional, Sequence

from shared.logging_utils import get_logger
from shared.token_counter import count_tokens

logger = get_logger(__name__)

__all__ = [
    "PromptCompressor",
    "compress_text",
    "dedupe_lines",
    "dedupe_paragraphs",
    "minify_json_blocks",
    "minify_json_text",
    "normalize_whitespace",
    "remove_comments",
]

#: Блок кода в тройных бэктиках. Язык берётся из первой строки (`` ```json ``),
#: тело — до ближайшего закрывающего забора (нежадно, чтобы не съесть два блока).
FENCE_RE = re.compile(r"```[ \t]*([^\n`]*)\n?(.*?)```", re.DOTALL)

#: HTML/Markdown-комментарий, в том числе многострочный.
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: Хвостовые пробелы строки и серии пробелов/пустых строк.
TRAILING_SPACE_RE = re.compile(r"[ \t]+$", re.MULTILINE)
MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
BLANK_LINES_RE = re.compile(r"\n{3,}")

#: Разделитель абзацев вместе с самим разделителем (нужен, чтобы собрать текст
#: обратно без потери переводов строки).
PARAGRAPH_SEP_RE = re.compile(r"((?:\n[ \t]*){2,})")

#: Языки блока, содержимое которых пробуем читать как JSON. Пустая строка —
#: забор без языка: там часто лежит JSON из ответа инструмента.
JSON_LANGUAGES = ("json", "")

#: Скалярный JSON (``42``, ``"текст"``) не минифицируется: выигрыша нет, а блок
#: без языка с одиноким числом — скорее фрагмент кода, чем документ JSON.
JSON_CONTAINERS = (dict, list)


def remove_comments(text: str) -> str:
    """Убирает ``<!-- ... -->``: на месте комментария остаётся пробел.

    Пробел, а не пустая строка: иначе ``до<!-- x -->после`` склеилось бы в одно
    слово и смысл текста изменился бы.
    """
    return COMMENT_RE.sub(" ", text)


def minify_json_text(text: str) -> Optional[str]:
    """Минифицирует текст целиком, если это JSON-объект/массив; иначе ``None``.

    Нужно для блоков БЕЗ забора: результат инструмента часто передаётся как
    «голый» JSON. Минификация через ``json.loads``/``json.dumps`` безопасна —
    она меняет только пробелы МЕЖДУ токенами, а содержимое строк остаётся
    посимвольно тем же. Общие правила пробелов к такому блоку не применяются:
    они бы испортили значение строки с двумя пробелами подряд.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, JSON_CONTAINERS):
        return None
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _minify_match(match: "re.Match[str]") -> str:
    """Минифицирует один блок кода, если внутри валидный JSON-объект/массив."""
    language = match.group(1).strip()
    if language.lower() not in JSON_LANGUAGES:
        return match.group(0)
    minified = minify_json_text(match.group(2))
    if minified is None:
        return match.group(0)
    return f"```{match.group(1)}\n{minified}\n```"


def minify_json_blocks(text: str) -> str:
    """Минифицирует JSON внутри блоков в тройных бэктиках; прочие блоки целы."""
    return FENCE_RE.sub(_minify_match, text)


def dedupe_lines(text: str) -> str:
    """Склеивает подряд идущие одинаковые строки, оставляя первую.

    Сравниваются строки без хвостовых пробелов: в сгенерированных журналах
    ``- ok`` и ``- ok  `` — одна и та же запись. Пустые строки не трогаются:
    за пустые строки отвечает ``normalize_whitespace``.
    """
    if not text:
        return text
    result: List[str] = []
    previous: Optional[str] = None
    for line in text.split("\n"):
        key = line.rstrip()
        if key and key == previous:
            continue
        result.append(line)
        previous = key
    return "\n".join(result)


def dedupe_paragraphs(text: str) -> str:
    """Выбрасывает абзац, полностью повторяющий предыдущий (остаётся первый)."""
    if not text:
        return text
    parts = PARAGRAPH_SEP_RE.split(text)
    result: List[str] = []
    previous = ""
    for index in range(0, len(parts), 2):
        paragraph = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        key = paragraph.strip()
        if key and key == previous:
            continue
        result.append(paragraph + separator)
        if key:
            previous = key
    return "".join(result)


def normalize_whitespace(text: str) -> str:
    """Хвостовые пробелы, серии пробелов и пустых строк — к одному виду.

    Хвостовые пробелы убираются ПЕРВЫМИ: иначе строка из одних пробелов не стала
    бы пустой и правило «три перевода строки → два» её бы не увидело.
    """
    text = TRAILING_SPACE_RE.sub("", text)
    text = MULTI_SPACE_RE.sub(" ", text)
    return BLANK_LINES_RE.sub("\n\n", text)


def _compress_prose(text: str) -> str:
    """Шаги 1, 3, 4 над фрагментом ВНЕ блоков кода."""
    if not text:
        return text
    text = remove_comments(text)
    text = dedupe_lines(text)
    text = dedupe_paragraphs(text)
    return normalize_whitespace(text)


def compress_text(text: str) -> str:
    """Сжимает текст целиком: правила по прозе и минификация JSON в блоках.

    Функция чистая и идемпотентная: повторный вызов над результатом ничего не
    меняет (шаги сравнимы между собой, а блоки кода после первой минификации уже
    минимальны). Порядок «проза, затем JSON» не важен: правила этих шагов не
    пересекаются по областям текста.
    """
    if not text:
        return ""
    if FENCE_RE.search(text) is None:
        # Блок целиком — JSON (результат инструмента без забора): минифицируем его
        # и не применяем общие правила пробелов, чтобы не портить значения строк.
        minified = minify_json_text(text.strip())
        if minified is not None:
            return minified
    segments: List[str] = []
    position = 0
    for match in FENCE_RE.finditer(text):
        segments.append(_compress_prose(text[position:match.start()]))
        segments.append(match.group(0))
        position = match.end()
    segments.append(_compress_prose(text[position:]))
    # Минификация идёт по собранному тексту: она правит только блоки кода.
    return minify_json_blocks("".join(segments)).strip()


class PromptCompressor:
    """Сжатие динамических блоков промпта с накоплением статистики.

    Экземпляр хранит счётчики вызовов и токенов (до/после), потому что экономию
    показывают интерфейсу и отчёту. Логика сжатия — чистые функции модуля, класс
    отвечает только за статистику и подменяемый счётчик токенов.
    """

    def __init__(self, *, counter: Optional[Callable[[str], int]] = None) -> None:
        self._counter: Callable[[str], int] = counter or count_tokens
        self._calls = 0
        self._tokens_before = 0
        self._tokens_after = 0

    def compress(self, text: str) -> str:
        """Сжимает один блок текста и записывает статистику по нему."""
        before = self._counter(text)
        result = compress_text(text)
        after = self._counter(result)
        self._calls += 1
        self._tokens_before += before
        self._tokens_after += after
        if before > after:
            logger.debug("промпт сжат: %d → %d токенов", before, after)
        return result

    def compress_blocks(self, blocks: Sequence[str]) -> List[str]:
        """Сжимает список блоков, сохраняя их порядок и число."""
        return [self.compress(block) for block in blocks]

    @property
    def stats(self) -> Dict[str, object]:
        """Накопленная статистика: вызовы, токены до/после, экономия.

        ``saved_tokens`` — разница «до − после» по всем вызовам. Отрицательной
        она может быть только при неудачном стечении обстоятельств (минификация
        изменила разбиение на токены в сторону роста) — это честнее, чем
        показывать ноль и скрывать регресс.
        """
        saved = self._tokens_before - self._tokens_after
        percent = round(saved * 100 / self._tokens_before, 1) if self._tokens_before else 0.0
        return {
            "calls": self._calls,
            "tokens_before": self._tokens_before,
            "tokens_after": self._tokens_after,
            "saved_tokens": saved,
            "saved_percent": percent,
        }

    def reset(self) -> None:
        """Обнуляет статистику (тесты и повторный замер экономии)."""
        self._calls = 0
        self._tokens_before = 0
        self._tokens_after = 0
