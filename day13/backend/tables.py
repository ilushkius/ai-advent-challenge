"""ORM-таблицы дня 13 (SQLAlchemy/SQLite): агенты, память и профили.

Хранилище агента с тремя слоями памяти и профилями пользователей (день 12).
Таблицы:

- ``agents`` (AgentRecord) — конфигурация агента, включая настройки сжатия
  (``summary_enabled``, ``keep_last_messages``, ``summarize_every``), стратегию
  сборки контекста и текущие ``current_session_id`` / ``current_task_id``;
- ``short_term_messages`` (ShortTermMessage) — КРАТКОСРОЧНАЯ память: реплики
  текущего диалога, привязанные к ``session_id`` (см. ``Agent.new_session``).
  История не удаляется при сжатии — конспект лишь заменяет старые реплики в
  ЗАПРОСЕ, но не в хранилище;
- ``working_memory`` (WorkingMemory) — РАБОЧАЯ память задачи: пары
  ``key → value``, привязанные к ``task_id`` (цель, ограничения, решения);
- ``long_term_memory`` (LongTermMemory) — ДОЛГОВРЕМЕННАЯ память: профиль,
  предпочтения, решения и знания, живущие между сессиями и задачами;
- ``summaries`` (Summary) — конспекты (append-only, текущий = последняя запись):
  content (Text), covered_from_message_id / covered_to_message_id (границы
  покрытых реплик, watermark), covered_messages (сколько реплик покрыто),
  source_tokens / summary_tokens (экономика), prompt_tokens / completion_tokens
  / cost (сколько стоил сам вызов суммаризации), created_at;
- ``token_usage`` (TokenUsage) — метрики одного успешного хода. День 8 хранил
  prompt/completion/total/history/response/cost; день 9 добавляет
  ``mode`` ("full" | "compressed"), ``full_context_tokens`` (сколько токенов
  ушло бы без сжатия), ``sent_context_tokens`` (сколько ушло фактически),
  ``saved_tokens`` (разница), ``summary_tokens`` / ``summarized_messages``
  (из чего собран конспект этого хода) и ``summary_used`` (применялся ли он).

- ``checkpoints`` (Checkpoint) — снимки истории для стратегии branching;
- ``user_profiles`` (UserProfile, день 12) — ПЕРСОНАЛИЗАЦИЯ: профиль
  пользователя (``user_id`` уникален), который подключается к системному
  промпту каждого запроса. ``preferences`` (JSON: tone/verbosity/language/
  format), ``constraints`` (JSON: max_response_length/forbidden_topics/
  required_disclaimers), ``custom_instructions`` (Text) и метки времени.

Агент ссылается на профиль через ``agents.user_id`` (день 12): один профиль
применяется ко всем агентам пользователя, профиль живёт между сессиями и
задачами и меняется через ``/users/{user_id}/profile`` на лету.

Таблицы состояния задачи дня 13 (``task_states``, ``task_transitions``) лежат
отдельным доменным модулем — ``backend/tables_task.py``: этот файл уже подошёл
к лимиту 400 строк, и две новые таблицы вывели бы его за лимит.

Классы наследуются от общей декларативной базы ``shared/db_base.Base``, а сам
движок и фабрика сессий живут в ``backend/database.py``: он же
реэкспортирует эти классы, поэтому остальной код дня импортирует таблицы из
``backend.database``.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.db_base import Base

from . import config


class AgentRecord(Base):
    """Строка таблицы agents — сохраняемая конфигурация агента."""

    __tablename__ = "agents"

    agent_id = Column(String, primary_key=True)
    name = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    temperature = Column(Float, nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    max_tokens = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    # Настройки сжатия истории (день 9). Дефолты — константы config, чтобы
    # существующие строки БД читались осмысленно и без миграции.
    summary_enabled = Column(
        Boolean, nullable=False, default=config.DEFAULT_SUMMARY_ENABLED
    )
    keep_last_messages = Column(
        Integer, nullable=False, default=config.DEFAULT_KEEP_LAST_MESSAGES
    )
    summarize_every = Column(
        Integer, nullable=False, default=config.DEFAULT_SUMMARIZE_EVERY
    )

    # Стратегия управления контекстом (день 11). Дефолты — константы config,
    # чтобы существующие строки БД читались осмысленно и без миграции.
    strategy = Column(String(32), nullable=False, default=config.DEFAULT_STRATEGY)
    window_size = Column(Integer, nullable=False, default=config.DEFAULT_WINDOW_SIZE)

    # Слои памяти (день 11): строка agents — источник правды о том, какая сессия
    # краткосрочной памяти и какая задача рабочей памяти сейчас активны.
    current_session_id = Column(String(32), nullable=False)
    current_task_id = Column(String(64), nullable=False, default=config.DEFAULT_TASK_ID)

    # Персонализация (день 12): пользователь, чей профиль подключается к
    # системному промпту каждого запроса агента. Не FK: профиль — отдельная
    # сущность, его удаление не должно уносить агентов (они просто теряют
    # персонализацию и отвечают как обычно).
    user_id = Column(
        String(config.USER_ID_MAX), nullable=False, index=True,
        default=config.DEFAULT_USER_ID,
    )

    short_term_messages = relationship(
        "ShortTermMessage",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    working_entries = relationship(
        "WorkingMemory",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    long_term_entries = relationship(
        "LongTermMemory",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    summaries = relationship(
        "Summary",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    task_states = relationship(
        "TaskState",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ShortTermMessage(Base):
    """Одна реплика краткосрочной памяти агента (таблица short_term_messages).

    Краткосрочная память — текущий диалог в рамках одной сессии (``session_id``):
    последние N реплик уходят в запрос, остальные доступны в БД до конца сессии.
    Очищается при старте новой сессии (``Agent.new_session``) или по команде
    (``DELETE /agents/{id}/memory/short-term``).
    """

    __tablename__ = "short_term_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    session_id = Column(String(32), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    agent = relationship("AgentRecord", back_populates="short_term_messages")


class Summary(Base):
    """Конспект части диалога (таблица summaries).

    Append-only: каждая успешная суммаризация добавляет новую строку, поэтому
    история сжатий видна в интерфейсе, а текущий конспект агента — последняя
    запись. Поля ``covered_from_message_id``/``covered_to_message_id`` образуют
    watermark: всё, что старше ``covered_to_message_id``, уже описано в
    конспекте и в запрос не уходит.
    """

    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    content = Column(Text, nullable=False)
    covered_from_message_id = Column(Integer, nullable=False)
    covered_to_message_id = Column(Integer, nullable=False)
    covered_messages = Column(Integer, nullable=False, default=0)
    source_tokens = Column(Integer, nullable=False, default=0)
    summary_tokens = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cost = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False)

    agent = relationship("AgentRecord", back_populates="summaries")


class TokenUsage(Base):
    """Метрики токенов одного успешного хода диалога (таблица token_usage).

    Базовые поля — из дня 8 (prompt/completion/total/history/response/cost).
    Поля дня 9 описывают эффект сжатия:
    - ``mode`` — "full" (сжатие выключено) или "compressed";
    - ``full_context_tokens`` — оценка запроса, если бы ушла вся история;
    - ``sent_context_tokens`` — оценка фактически отправленного запроса;
    - ``saved_tokens`` — full_context_tokens - sent_context_tokens;
    - ``summary_tokens`` / ``summarized_messages`` — конспект хода;
    - ``summary_used`` — был ли конспект в payload.

    День 11 добавляет фактический расход по слоям памяти: ``short_term_tokens``,
    ``working_tokens``, ``long_term_tokens`` (оценки tiktoken для блоков,
    ушедших в запрос).
    """

    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    history_tokens = Column(Integer, nullable=False, default=0)
    response_tokens = Column(Integer, nullable=False, default=0)
    cost = Column(Float, nullable=False, default=0.0)

    mode = Column(String(16), nullable=False, default="full")
    full_context_tokens = Column(Integer, nullable=False, default=0)
    sent_context_tokens = Column(Integer, nullable=False, default=0)
    saved_tokens = Column(Integer, nullable=False, default=0)
    summary_tokens = Column(Integer, nullable=False, default=0)
    summarized_messages = Column(Integer, nullable=False, default=0)
    summary_used = Column(Boolean, nullable=False, default=False)

    # Расход по слоям памяти (день 11): токены блоков, ушедших в запрос.
    short_term_tokens = Column(Integer, nullable=False, default=0)
    working_tokens = Column(Integer, nullable=False, default=0)
    long_term_tokens = Column(Integer, nullable=False, default=0)


class Fact(Base):
    """Один факт диалога «ключ → значение» (таблица facts, стратегия sticky_facts).

    Пара (agent_id, key) уникальна: повторное извлечение того же ключа обновляет
    ``value`` и ``updated_at``, а не плодит дубли. Экстракция — эвристическая
    (см. backend/fact_extractor.py), факты отправляются в LLM блоком в
    системном сообщении вместе с последними репликами.
    """

    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint("agent_id", "key", name="uq_facts_agent_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class WorkingMemory(Base):
    """Запись рабочей памяти агента (таблица working_memory).

    Рабочая память — данные текущей задачи (``task_id``): цель, ограничения,
    промежуточные решения, планы. Живёт дольше одной реплики, но привязана к
    задаче и НЕ очищается при старте новой сессии. Пара
    (agent_id, task_id, key) уникальна: повторная запись обновляет value.
    """

    __tablename__ = "working_memory"
    __table_args__ = (
        UniqueConstraint("agent_id", "task_id", "key", name="uq_working_agent_task_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    task_id = Column(String(64), nullable=False, index=True)
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    agent = relationship("AgentRecord", back_populates="working_entries")


class LongTermMemory(Base):
    """Запись долговременной памяти агента (таблица long_term_memory).

    Долговременная память — профиль пользователя, устойчивые предпочтения,
    важные решения и знания. Живёт между сессиями и задачами: не очищается ни
    ``new_session()``, ни сменой задачи. Пара (agent_id, category, key) уникальна:
    повторная запись обновляет value/confidence/updated_at.
    """

    __tablename__ = "long_term_memory"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "category", "key", name="uq_long_term_agent_category_key"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category = Column(String(32), nullable=False, index=True)
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, default=1.0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    agent = relationship("AgentRecord", back_populates="long_term_entries")


class Checkpoint(Base):
    """Снимок истории диалога в точке ветвления (таблица checkpoints, branching).

    ``messages`` — JSON-список ``[{"role": ..., "content": ...}, ...]`` — полный
    снимок истории на момент создания. ``parent_id`` указывает на чекпоинт,
    от которого создана ветка (None — корень). Активная ветка хранится в памяти
    агента (``Agent.active_branch_id``) и обновляется после каждого успешного
    хода в режиме branching; переключение заменяет краткосрочную память агента
    снимком выбранной ветки.
    """

    __tablename__ = "checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(
        String,
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    parent_id = Column(Integer, nullable=True)
    messages = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


# Персонализация (день 12): профиль пользователя, подключаемый к системному
# промпту каждого запроса. Таблица не связана FK с agents намеренно: профиль —
# самостоятельная сущность (есть CRUD /users/{user_id}/profile), а агент лишь
# ссылается на user_id. Удаление профиля оставляет агентов работоспособными.
class UserProfile(Base):
    """Профиль пользователя (таблица user_profiles).

    Поля:

    - ``id`` — первичный ключ строки (Integer, autoincrement);
    - ``user_id`` — уникальный идентификатор пользователя (String, index):
      по нему профиль и подключается к запросам агента;
    - ``name`` — имя для обращения («Обращайся ко мне по имени»);
    - ``preferences`` — JSON: tone / verbosity / language / format (значения —
      варианты из backend/profiles.py, незаполненное поле = None);
    - ``constraints`` — JSON: max_response_length / forbidden_topics /
      required_disclaimers;
    - ``custom_instructions`` — Text: произвольные инструкции пользователя,
      одна инструкция на строку (см. profiles.normalize_instructions);
    - ``created_at`` / ``updated_at`` — метки времени (UTC).

    JSON-поля хранятся в SQLite как TEXT: SQLAlchemy сериализует словарь сам,
    поэтому чтение всегда даёт dict, а не строку.
    """

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String(config.USER_ID_MAX), nullable=False, unique=True, index=True,
    )
    name = Column(String(config.PROFILE_NAME_MAX), nullable=False, default="")
    preferences = Column(JSON, nullable=False, default=dict)
    constraints = Column(JSON, nullable=False, default=dict)
    custom_instructions = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
