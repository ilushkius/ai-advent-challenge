"""Три слоя памяти агента (день 11): менеджер, категории и чистые помощники.

Что это.
    День 11 заменяет единую историю диалога тремя явными слоями со своими
    таблицами:

    - **краткосрочная** (``short_term_messages``) — текущий диалог одной сессии
      (``session_id``): последние реплики уходят в запрос, остальные доступны в
      БД до конца сессии; очищается при ``Agent.new_session()``;
    - **рабочая** (``working_memory``) — данные текущей задачи (``task_id``):
      цель, ограничения, промежуточные решения; переживает смену сессии;
    - **долговременная** (``long_term_memory``) — профиль, предпочтения, решения
      и знания; переживает и сессии, и задачи.

Что здесь.
    * ``MemoryCategory`` — ``Enum`` категорий долговременного слоя (значение —
      строка, попадающая в БД/API/UI без маппинга);
    * чистые функции ``query_keywords`` / ``render_working_block`` /
      ``render_long_term_block`` — отбор и текстовая форма блоков памяти,
      тестируются без БД;
    * ``MemoryManager`` — единственная точка доступа к трём таблицам: upsert,
      чтение, очистка, отбор релевантных записей.

Границы.
    Модуль не знает ни про LLM, ни про FastAPI/Streamlit: он читает и пишет
    SQLite через переданную фабрику сессий. Класс ``Agent`` решает, ЧТО из
    каждого слоя попадёт в контекст; ``MemoryManager`` — только хранилище.
"""
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from . import config, database
from .database import LongTermMemory, ShortTermMessage, WorkingMemory


class MemoryCategory(str, Enum):
    """Категории долговременной памяти (значение — строка для БД/API/UI)."""

    PROFILE = "profile"        # профиль пользователя
    PREFERENCE = "preference"  # устойчивые предпочтения
    DECISION = "decision"      # важные решения
    KNOWLEDGE = "knowledge"    # знания


AVAILABLE_CATEGORIES = tuple(item.value for item in MemoryCategory)

# Подстроки, по которым запрос «узнаёт» категорию долговременной памяти
# («расскажи про мой профиль» → записи категории profile).
CATEGORY_HINTS = {
    MemoryCategory.PROFILE.value: ("профил",),
    MemoryCategory.PREFERENCE.value: ("предпочт",),
    MemoryCategory.DECISION.value: ("решен", "решили"),
    MemoryCategory.KNOWLEDGE.value: ("знан",),
}

# Стоп-слова для отбора релевантных записей долговременной памяти.
STOPWORDS = frozenset({
    "что", "как", "для", "это", "все", "при", "или", "его", "ещё", "еще",
    "the", "and", "for", "with", "that", "this",
})

WORKING_HEADER = (
    "Рабочая память (данные текущей задачи, используй как опорные; при "
    "противоречии важнее свежая реплика):"
)
LONG_TERM_HEADER = (
    "Долговременная память (профиль, предпочтения, решения, знания — "
    "устойчивые данные о пользователе):"
)


def query_keywords(text: str) -> List[str]:
    """Ключевые слова запроса: нижний регистр, слова длиной >= 3 без стоп-слов.

    Чистая функция: одинаковый вход всегда даёт одинаковый результат, порядок
    слов сохраняется, дубликаты убираются.
    """
    words = re.findall(r"[a-zа-яё0-9]+", (text or "").lower())
    result: List[str] = []
    for word in words:
        if len(word) < 3 or word in STOPWORDS or word in result:
            continue
        result.append(word)
    return result


def render_working_block(entries: List[dict]) -> str:
    """Текст блока рабочей памяти для системного сообщения.

    Пустой список → пустая строка (блок в системное сообщение не добавляется).
    Записи печатаются по алфавиту ключей: текст детерминирован.
    """
    if not entries:
        return ""
    lines = [WORKING_HEADER]
    for entry in sorted(entries, key=lambda item: item["key"]):
        lines.append(f"- {entry['key']}: {entry['value']}")
    return "\n".join(lines)


def render_long_term_block(entries: List[dict]) -> str:
    """Текст блока долговременной памяти (с категорией и уверенностью).

    Пустой список → пустая строка. Сортировка по (category, key) — текст
    детерминирован. ``confidence`` печатается без хвостовых нулей (``:g``).
    """
    if not entries:
        return ""
    lines = [LONG_TERM_HEADER]
    ordered = sorted(entries, key=lambda item: (item["category"], item["key"]))
    for entry in ordered:
        confidence = float(entry.get("confidence", 1.0))
        lines.append(
            f"- [{entry['category']}] {entry['key']}: {entry['value']} "
            f"(уверенность {confidence:g})"
        )
    return "\n".join(lines)


def _short_term_dict(row: ShortTermMessage) -> dict:
    """ORM-строка краткосрочного слоя → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content,
        "created_at": row.created_at,
    }


def _working_dict(row: WorkingMemory) -> dict:
    """ORM-строка рабочей памяти → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "task_id": row.task_id,
        "key": row.key,
        "value": row.value,
        "updated_at": row.updated_at,
    }


def _long_term_dict(row: LongTermMemory) -> dict:
    """ORM-строка долговременной памяти → словарь для API/UI."""
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "category": row.category,
        "key": row.key,
        "value": row.value,
        "confidence": row.confidence,
        "updated_at": row.updated_at,
    }


class MemoryManager:
    """Управляет тремя слоями памяти агента в SQLite.

    Конструктор принимает фабрику сессий (``database.SessionLocal`` или фабрику
    на временной БД в тестах); методы принимают ``agent_id`` явно, поэтому один
    менеджер обслуживает всех агентов.
    """

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or database.SessionLocal

    def _session(self):
        """Короткая сессия SQLAlchemy на операцию (как в Agent/AgentManager)."""
        return self._session_factory()

    # --- краткосрочная память ---
    def add_short_term(self, agent_id: str, session_id: str, role: str,
                       content: str) -> dict:
        """Добавляет реплику в краткосрочный слой указанной сессии."""
        if not (session_id or "").strip():
            raise ValueError("session_id не может быть пустым")
        if not (role or "").strip():
            raise ValueError("role не может быть пустым")
        if not (content or "").strip():
            raise ValueError("content не может быть пустым")
        with self._session() as session:
            row = ShortTermMessage(
                agent_id=agent_id, session_id=session_id, role=role,
                content=content, created_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            return _short_term_dict(row)

    def get_short_term(self, agent_id: str, session_id: str,
                       limit: Optional[int] = None) -> List[dict]:
        """Реплики сессии в хронологическом порядке.

        ``limit=None`` → все реплики; иначе — последние ``limit``, но всё равно
        в хронологическом порядке (срез хвоста, порядок не переворачивается).
        """
        with self._session() as session:
            rows = (
                session.query(ShortTermMessage)
                .filter(
                    ShortTermMessage.agent_id == agent_id,
                    ShortTermMessage.session_id == session_id,
                )
                .order_by(ShortTermMessage.id.asc())
                .all()
            )
            if limit is not None:
                rows = rows[-limit:] if limit > 0 else []
            return [_short_term_dict(row) for row in rows]

    def clear_short_term(self, agent_id: str, session_id: str) -> int:
        """Удаляет реплики сессии; возвращает число удалённых (0 — не ошибка)."""
        with self._session() as session:
            deleted = (
                session.query(ShortTermMessage)
                .filter(
                    ShortTermMessage.agent_id == agent_id,
                    ShortTermMessage.session_id == session_id,
                )
                .delete()
            )
            session.commit()
            return int(deleted or 0)

    def count_short_term(self, agent_id: str, session_id: str) -> int:
        """Число реплик сессии в краткосрочном слое."""
        with self._session() as session:
            return int(
                session.query(ShortTermMessage)
                .filter(
                    ShortTermMessage.agent_id == agent_id,
                    ShortTermMessage.session_id == session_id,
                )
                .count()
            )

    # --- рабочая память ---
    def add_working(self, agent_id: str, task_id: str, key: str, value: str) -> dict:
        """Upsert записи рабочей памяти по (agent_id, task_id, key)."""
        if not (key or "").strip():
            raise ValueError("key не может быть пустым")
        if not (value or "").strip():
            raise ValueError("value не может быть пустым")
        now = datetime.now(timezone.utc)
        with self._session() as session:
            row = (
                session.query(WorkingMemory)
                .filter(
                    WorkingMemory.agent_id == agent_id,
                    WorkingMemory.task_id == task_id,
                    WorkingMemory.key == key,
                )
                .first()
            )
            if row is None:
                row = WorkingMemory(
                    agent_id=agent_id, task_id=task_id, key=key, value=value,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.value = value
                row.updated_at = now
            session.commit()
            return _working_dict(row)

    def get_working(self, agent_id: str, task_id: str) -> List[dict]:
        """Все записи рабочей памяти задачи (сортировка по ключу)."""
        with self._session() as session:
            rows = (
                session.query(WorkingMemory)
                .filter(
                    WorkingMemory.agent_id == agent_id,
                    WorkingMemory.task_id == task_id,
                )
                .order_by(WorkingMemory.key.asc())
                .all()
            )
            return [_working_dict(row) for row in rows]

    def list_tasks(self, agent_id: str) -> List[str]:
        """Идентификаторы задач агента (для селектора в UI), по алфавиту."""
        with self._session() as session:
            rows = (
                session.query(WorkingMemory.task_id)
                .filter(WorkingMemory.agent_id == agent_id)
                .distinct()
                .all()
            )
            return sorted({row[0] for row in rows})

    # --- долговременная память ---
    def add_long_term(self, agent_id: str, category: str, key: str, value: str,
                      confidence: float = 1.0) -> dict:
        """Upsert записи долговременной памяти по (agent_id, category, key)."""
        if category not in AVAILABLE_CATEGORIES:
            raise ValueError(
                f"неизвестная категория {category!r}; допустимые: "
                f"{', '.join(AVAILABLE_CATEGORIES)}"
            )
        if not (key or "").strip():
            raise ValueError("key не может быть пустым")
        if not (value or "").strip():
            raise ValueError("value не может быть пустым")
        confidence = float(confidence)
        if not (config.CONFIDENCE_MIN <= confidence <= config.CONFIDENCE_MAX):
            raise ValueError("confidence должен быть в диапазоне 0..1")
        now = datetime.now(timezone.utc)
        with self._session() as session:
            row = (
                session.query(LongTermMemory)
                .filter(
                    LongTermMemory.agent_id == agent_id,
                    LongTermMemory.category == category,
                    LongTermMemory.key == key,
                )
                .first()
            )
            if row is None:
                row = LongTermMemory(
                    agent_id=agent_id, category=category, key=key, value=value,
                    confidence=confidence, updated_at=now,
                )
                session.add(row)
            else:
                row.value = value
                row.confidence = confidence
                row.updated_at = now
            session.commit()
            return _long_term_dict(row)

    def get_long_term(self, agent_id: str, category: Optional[str] = None) -> List[dict]:
        """Записи долговременной памяти агента (все категории или одна)."""
        with self._session() as session:
            query = session.query(LongTermMemory).filter(
                LongTermMemory.agent_id == agent_id
            )
            if category is not None:
                query = query.filter(LongTermMemory.category == category)
            rows = (
                query.order_by(
                    LongTermMemory.category.asc(), LongTermMemory.key.asc()
                ).all()
            )
            return [_long_term_dict(row) for row in rows]

    def delete_long_term(self, agent_id: str, entry_id: int) -> bool:
        """Удаляет запись по id; False — записи не было (API отвечает 404)."""
        with self._session() as session:
            deleted = (
                session.query(LongTermMemory)
                .filter(
                    LongTermMemory.agent_id == agent_id,
                    LongTermMemory.id == entry_id,
                )
                .delete()
            )
            session.commit()
            return bool(deleted)

    def select_long_term(self, agent_id: str, query: str,
                         limit: int = config.LONG_TERM_LIMIT) -> List[dict]:
        """Отбирает релевантные записи долговременной памяти для запроса.

        Счёт записи — число ключевых слов запроса, входящих подстрокой в её
        ``key`` или ``value`` (вес 1), плюс 1, если запрос упоминает категорию
        (``профиль``, ``предпочтение``, ``решение``, ``знание``). Записи со
        счётом 0 добираются самыми уверенными — так профиль пользователя
        попадает в контекст даже при отсутствии совпадений. Функция
        детерминирована: одинаковый вход → одинаковый результат.
        """
        entries = self.get_long_term(agent_id)
        if not entries or limit <= 0:
            return []
        lowered = (query or "").lower()
        keywords = query_keywords(query)
        scored = []
        for entry in entries:
            haystack = f"{entry['key']} {entry['value']}".lower()
            score = sum(1 for word in keywords if word in haystack)
            for hint in CATEGORY_HINTS.get(entry["category"], ()):
                if hint in lowered:
                    score += 1
                    break
            scored.append((score, entry))
        relevant = sorted(
            (item for item in scored if item[0] > 0),
            key=lambda item: (-item[0], -float(item[1]["confidence"]), item[1]["key"]),
        )
        if len(relevant) < limit:
            chosen_ids = {item[1]["id"] for item in relevant}
            rest = sorted(
                (item for item in scored if item[1]["id"] not in chosen_ids),
                key=lambda item: (-float(item[1]["confidence"]), item[1]["key"]),
            )
            relevant = relevant + rest[: limit - len(relevant)]
        return [entry for _, entry in relevant[:limit]]


def new_session_id() -> str:
    """Короткий идентификатор новой сессии краткосрочной памяти."""
    return uuid.uuid4().hex[: config.SESSION_ID_LENGTH]
