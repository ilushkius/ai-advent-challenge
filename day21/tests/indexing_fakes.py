"""Фейки индексации дня 21: эмбеддер на хешах слов и маленький набор документов.

``FakeEmbedder`` — не «заглушка ради заглушки»: вектор строится суммой хешей слов
текста, поэтому одинаковый текст даёт одинаковый вектор, а текст с общими словами —
близкий. Из-за этого поиск в тестах ведёт себя осмысленно (запрос «раздел B» находит
чанк с этими словами), и метрики precision@k проверяются на настоящем разделении
релевантного и нерелевантного, а не на случайных числах.

``make_documents`` пишет три документа (markdown с заголовками, plain text и
Python-модуль с декоратором) и возвращает их как ``Document`` — так сервисные тесты
получают вход чанкинга без сбора из репозитория.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np

from backend.domain.document_sources import Document

#: Документ markdown: заголовок, вступление, две секции и одна вложенная.
MARKDOWN_TEXT = """# Правила дня

Вступление: короткий абзац о правилах проекта и о том, зачем они нужны.

## Раздел A

Первый раздел рассказывает про чанкинг фиксированного размера: окно по токенам
с перекрытием соседних окон. Здесь достаточно слов, чтобы секция набрала минимум.

### Вложенный подраздел A.1

Подраздел про эмбеддинги и векторный индекс, который тоже относится к разделу A.

## Раздел B

Второй раздел рассказывает про структурный чанкинг: секции markdown, определения
кода и абзацы plain text. Слов здесь тоже достаточно для отдельного чанка.
"""

#: Документ plain text: три абзаца без заголовков.
PLAIN_TEXT = """Первый абзац про поиск по индексу документов и про метрики качества.

Второй абзац про то, что покрытие считается по объединению интервалов чанков.

Третий абзац про журнал запусков в SQLite и про то, зачем он нужен в фоне.
"""

#: Документ Python: модульный докстринг, декоратор, класс и функции.
CODE_TEXT = '''"""Модуль примера: состояния и переходы."""
from __future__ import annotations

import enum

DEFAULT_LIMIT = 5


class State(enum.Enum):
    """Состояние примера."""

    IDLE = "idle"
    DONE = "done"


def helper(value: int) -> int:
    """Функция-помощник."""
    return value + 1


@staticmethod
def decorated(value: int) -> int:
    """Функция с декоратором: её секция начинается со строки декоратора."""
    return value * 2
'''


class FakeEmbedder:
    """Эмбеддер на хешах слов: детерминированный, без модели и без сети.

    Размерность мала (8) намеренно: тестам нужен не семантический поиск, а
    воспроизводимая близость «общие слова → большая оценка».
    """

    dimension = 8
    model_name = "fake: хеши слов (8)"

    @property
    def loaded(self) -> bool:
        """Фейк «загружен» всегда: грузить нечего."""
        return True

    def encode(self, texts):
        """Векторы текстов формы ``(n, 8)``, ``float32``, единичной длины."""
        items = [str(text) for text in texts]
        if not items:
            return np.zeros((0, self.dimension), dtype=np.float32)
        rows = np.zeros((len(items), self.dimension), dtype=np.float32)
        for index, text in enumerate(items):
            for word in re.findall(r"\w+", text.lower()):
                bucket = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
                rows[index, bucket % self.dimension] += 1.0
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (rows / norms).astype(np.float32)

    def encode_one(self, text: str):
        """Вектор одного текста формы ``(8,)``."""
        return self.encode([text])[0]

    def warmup(self) -> bool:
        """Прогрев не нужен: модель уже «готова»."""
        return True

    def reset(self) -> None:
        """Сброс состояния (у фейка его нет)."""


def make_documents(base: Path) -> list[Document]:
    """Пишет три тестовых документа в ``base`` и возвращает их описания."""
    base.mkdir(parents=True, exist_ok=True)
    plan = (
        ("rules.md", "markdown", "Правила дня", "ru", MARKDOWN_TEXT),
        ("notes.txt", "docs", "Заметки", "ru", PLAIN_TEXT),
        ("sample.py", "code", "Модуль примера: состояния и переходы", "ru", CODE_TEXT),
    )
    documents: list[Document] = []
    for name, kind, title, language, text in plan:
        path = base / name
        path.write_text(text, encoding="utf-8")
        documents.append(Document(
            source=name, path=path, title=title, kind=kind, language=language,
            text=text, chars=len(text), truncated=False,
        ))
    return documents


def documents_by_source(documents: list[Document]) -> dict[str, Document]:
    """Документы по имени файла — удобно в проверках чанкинга."""
    return {document.source: document for document in documents}
