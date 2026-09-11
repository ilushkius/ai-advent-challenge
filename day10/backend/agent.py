"""Класс Agent дня 9 — агент со сжатием истории и контролем токенов.

День 9 развивает день 8. Хранение остаётся «двухслойным»:

- ``self.messages`` — копия ПОЛНОЙ истории диалога в LLM-формате
  ``[{"role": "user"/"assistant", "content": ...}, ...]``;
- SQLite — источник правды: таблица ``messages`` (полная история, не
  удаляется), таблица ``summaries`` (конспекты, append-only) и
  ``token_usage`` (метрики ходов).

Главное отличие от дня 8: **в запрос уходит не вся история**. Из БД берутся
непокрытые конспектом реплики, последние ``keep_last_messages`` отправляются
«как есть», а всё более старое заменяется конспектом (таблица ``summaries``):

    payload = [system (+конспект)] + последние N реплик + новый промпт

Полная история при этом никуда не исчезает: сжатие уменьшает только запрос,
поэтому старые реплики остаются доступны в БД и в интерфейсе.

Состояние процесса сжатия ведёт стейт-машина (``context_fsm.py``): IDLE →
TRACKING → SUMMARY_PENDING → SUMMARIZING → TRACKING/ERROR. Сжатие запускается
ПОСЛЕ успешного хода (в той же транзакции сохраняется пара реплик и метрики),
поэтому неудачная суммаризация не портит ответ пользователю: ход помечается
ошибкой сжатия, а повтор произойдёт на следующем ходу.

Контроль лимита контекста (наследие дня 8) остаётся аварийным предохранителем:
если даже сжатый запрос не влезает в лимит модели, самые старые реплики
ПРОПУСКАЮТСЯ в этом запросе (``trimmed_messages``) — но, в отличие от дня 8,
из БД они не удаляются.

Фабрики для офлайн-проверок: клиент создаётся ``_make_client()`` (подменяется
фейком), фабрика сессий БД передаётся через ``session_factory``.
"""
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func

from . import config, database
from .compressor import CompressionError, ContextCompressor
from .context_fsm import ContextEvent, ContextMachine, ContextState, ContextStateBase
from .database import Checkpoint, Fact, Message, Summary, TokenUsage
from .fact_extractor import extract_facts
from .models import AgentConfig
from .strategies import Strategy

# Кэш кодировки tiktoken на процесс (лениво, см. _get_tokenizer ниже).
_TOKENIZER = None


def _get_tokenizer():
    """Возвращает кодировку tiktoken `cl100k_base` (загружается один раз)."""
    global _TOKENIZER
    if _TOKENIZER is None:
        import tiktoken  # локальный импорт: нужен только при подсчёте токенов

        _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    return _TOKENIZER


class AgentError(Exception):
    """Понятная ошибка уровня агента (нет ключа, сбой API и т.п.)."""


@dataclass(frozen=True)
class PayloadPlan:
    """Как собран контекст для одного запроса (и что было бы без сжатия)."""

    full_payload: List[dict] = field(default_factory=list)
    sent_payload: List[dict] = field(default_factory=list)
    full_context_tokens: int = 0
    sent_context_tokens: int = 0
    kept_messages: int = 0
    covered_messages: int = 0
    summarized_messages: int = 0
    summary_tokens: int = 0
    summary_used: bool = False

    @property
    def saved_tokens(self) -> int:
        """Сколько токенов запроса сэкономлено сжатием (оценка tiktoken)."""
        return max(0, self.full_context_tokens - self.sent_context_tokens)


class Agent:
    """Один LLM-агент: конфигурация, диалог в SQLite, сжатие истории, метрики."""

    def __init__(
        self,
        cfg: AgentConfig,
        agent_id: str,
        created_at: Optional[datetime] = None,
        session_factory=None,
    ) -> None:
        self.agent_id = agent_id
        self.config = cfg
        self.created_at = created_at or datetime.now(timezone.utc)
        self._session_factory = session_factory or database.SessionLocal
        # Стратегия управления контекстом (день 10): значение из конфигурации,
        # окно — для sliding_window/sticky_facts. Активная ветка (branching)
        # хранится в памяти процесса: на рестарте она не восстанавливается.
        self.strategy: str = cfg.strategy
        self.window_size: int = cfg.window_size
        self.active_branch_id: Optional[int] = None
        # История диалога в памяти: [{"role": ..., "content": ...}, ...].
        self.messages: List[Dict[str, str]] = []
        # Стейт-машина сжатия: живёт в памяти процесса, но её состояние всегда
        # восстановимо из БД (см. refresh_context_state).
        self.machine = ContextMachine()
        self.compressor = ContextCompressor(self)
        # Старт приложения/создание агента: загружаем историю из БД.
        self.load_history()

    # --- публичные поля ---
    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def message_count(self) -> int:
        """Число реплик диалога (без учёта системного промпта)."""
        return len(self.messages)

    def apply_config(self, cfg: AgentConfig) -> None:
        """Заменяет конфигурацию агента (используется PATCH /agents/{id})."""
        self.config = cfg
        self.strategy = cfg.strategy
        self.window_size = cfg.window_size

    # --- подсчёт токенов ---
    def count_tokens(self, text: str) -> int:
        """Число токенов текста в кодировке `cl100k_base` (tiktoken).

        Пустой текст = 0 токенов. Подсчёт локальный и приблизительный:
        DeepSeek использует собственный токенизатор, поэтому числа близки к
        фактическим, но не обязаны совпадать с `usage` API.
        """
        if not text:
            return 0
        return len(_get_tokenizer().encode(str(text)))

    @property
    def context_limit_tokens(self) -> int:
        """Лимит контекста модели агента (демо-значения из config)."""
        return config.MODEL_TOKEN_LIMITS.get(
            self.config.model, config.MODEL_TOKEN_LIMITS[config.MODEL_CHAT]
        )

    def _count_messages(self, messages) -> int:
        """Токены списка сообщений (сумма токенов содержимого каждого)."""
        return sum(self.count_tokens(item.get("content", "")) for item in messages)

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Стоимость хода в $ по тарифам модели (приблизительно, 6 знаков)."""
        price = config.MODEL_PRICES.get(
            self.config.model, config.MODEL_PRICES[config.MODEL_CHAT]
        )
        return round(
            prompt_tokens / 1_000_000 * price["in"]
            + completion_tokens / 1_000_000 * price["out"],
            6,
        )

    # --- доступ к БД ---
    @contextmanager
    def _session(self):
        """Короткая сессия SQLAlchemy на операцию (потокобезопасно)."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def _fetch_rows(self) -> List[Message]:
        """Все сообщения агента из БД в хронологическом порядке."""
        with self._session() as session:
            return (
                session.query(Message)
                .filter(Message.agent_id == self.agent_id)
                .order_by(Message.timestamp.asc(), Message.id.asc())
                .all()
            )

    # --- история: загрузка / сохранение / очистка ---
    def load_history(self) -> None:
        """Загружает полную историю диалога из БД в self.messages."""
        self.messages = [
            {"role": row.role, "content": row.content} for row in self._fetch_rows()
        ]

    def history_rows(self) -> List[Dict]:
        """Сообщения диалога с метаданными (для API): id, роль, текст, время.

        Флаг ``summarized`` показывает, покрыта ли реплика конспектом: фронтенд
        рисует на этой границе маркер «предыдущая часть диалога сжата».
        """
        watermark = self.compressor.watermark()
        rows = self._fetch_rows()
        return [
            {
                "id": row.id,
                "agent_id": row.agent_id,
                "role": row.role,
                "content": row.content,
                "timestamp": row.timestamp,
                "summarized": row.id <= watermark,
            }
            for row in rows
        ]

    def save_message(self, role: str, content: str) -> Dict:
        """Сохраняет одну реплику в БД и добавляет её в self.messages."""
        timestamp = datetime.now(timezone.utc)
        with self._session() as session:
            row = Message(
                agent_id=self.agent_id, role=role, content=content,
                timestamp=timestamp,
            )
            session.add(row)
            session.commit()
        self.messages.append({"role": role, "content": content})
        return {
            "id": row.id, "agent_id": self.agent_id, "role": role,
            "content": content, "timestamp": timestamp,
        }

    def _save_turn(self, user_content: str, assistant_content: str,
                   metrics: Optional[dict] = None) -> None:
        """Сохраняет пару реплик + метрики токенов одной транзакцией.

        Если сервер упадёт между отдельными commit'ами, в истории осталась бы
        реплика user без ответа. Одна транзакция исключает и это, и расхождение
        диалога с записью ``token_usage``.
        """
        now = datetime.now(timezone.utc)
        rows = [
            Message(
                agent_id=self.agent_id, role="user", content=user_content,
                timestamp=now,
            ),
            Message(
                agent_id=self.agent_id, role="assistant",
                content=assistant_content, timestamp=now,
            ),
        ]
        if metrics:
            rows.append(TokenUsage(
                agent_id=self.agent_id, timestamp=now,
                prompt_tokens=metrics.get("prompt_tokens", 0),
                completion_tokens=metrics.get("completion_tokens", 0),
                total_tokens=metrics.get("total_tokens", 0),
                history_tokens=metrics.get("history_tokens", 0),
                response_tokens=metrics.get("response_tokens", 0),
                cost=metrics.get("cost", 0.0),
                mode=metrics.get("mode", "full"),
                full_context_tokens=metrics.get("full_context_tokens", 0),
                sent_context_tokens=metrics.get("sent_context_tokens", 0),
                saved_tokens=metrics.get("saved_tokens", 0),
                summary_tokens=metrics.get("summary_tokens", 0),
                summarized_messages=metrics.get("summarized_messages", 0),
                summary_used=metrics.get("summary_used", False),
            ))
        with self._session() as session:
            session.add_all(rows)
            session.commit()

    def clear_history(self) -> int:
        """Удаляет историю, конспекты и метрики агента из БД и памяти.

        Полный сброс диалога: удаляются ``messages``, ``summaries`` и
        ``token_usage`` — «новый диалог» начинает счёт токенов и конспектов с
        нуля. Возвращает число удалённых реплик.
        """
        with self._session() as session:
            session.query(TokenUsage).filter(
                TokenUsage.agent_id == self.agent_id
            ).delete()
            session.query(Summary).filter(
                Summary.agent_id == self.agent_id
            ).delete()
            session.query(Fact).filter(
                Fact.agent_id == self.agent_id
            ).delete()
            session.query(Checkpoint).filter(
                Checkpoint.agent_id == self.agent_id
            ).delete()
            deleted = (
                session.query(Message)
                .filter(Message.agent_id == self.agent_id)
                .delete()
            )
            session.commit()
        self.messages = []
        self.active_branch_id = None
        self.refresh_context_state()
        return deleted

    # --- вызов DeepSeek ---
    def _make_client(self):
        """Создаёт OpenAI-совместимый клиент DeepSeek.

        Ключ резолвится в момент вызова (не при создании агента). Без ключа
        кидаем AgentError ДО сетевого вызова — поведение проверяемо офлайн.
        """
        api_key = config.resolve_api_key()
        if not api_key:
            raise AgentError(
                "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day9/.env "
                "или в переменной окружения и перезапустите запрос."
            )
        import openai  # локальный импорт: модуль нужен только при реальном вызове
        return openai.OpenAI(
            base_url=config.DEEPSEEK_BASE_URL,
            api_key=api_key,
            timeout=config.REQUEST_TIMEOUT,
        )

    def _system_message(self, summary_text: str = "",
                        facts: Optional[Dict[str, str]] = None) -> List[dict]:
        """Системное сообщение агента: роль + (опц.) конспект и/или факты.

        Конспект и факты вкладываются в существующее system-сообщение, а не
        добавляются отдельными: так поведение не зависит от того, как провайдер
        обрабатывает несколько system-сообщений подряд.
        """
        parts = []
        if self.config.system_prompt:
            parts.append(self.config.system_prompt)
        if summary_text:
            parts.append(
                "Конспект предыдущей части диалога (используй как память о том, "
                "что обсуждалось раньше):\n" + summary_text
            )
        if facts:
            lines = [f"- {key}: {value}" for key, value in sorted(facts.items())]
            parts.append(
                "Известные факты диалога (ключ-значение, используй как опорные "
                "данные; более свежие значения важнее старых):\n" + "\n".join(lines)
            )
        if not parts:
            return []
        return [{"role": "system", "content": "\n\n".join(parts)}]

    def _context_tokens_for(self, messages) -> int:
        """Оценка токенов контекста: системный промпт + список сообщений."""
        return self._count_messages(self._system_message() + list(messages))

    # --- сборка payload со сжатием (ядро дня 9) ---
    def build_payloads(self, prompt: str) -> PayloadPlan:
        """Строит два варианта запроса: полный (день 8) и сжатый (день 9).

        Полный — «что было бы без сжатия»: системный промпт + ВСЯ история +
        новый промпт. Сжатый — «что уходит фактически»: системный промпт с
        конспектом + последние ``keep_last_messages`` непокрытых реплик + новый
        промпт. Обе оценки нужны для метрик экономии, поэтому считаются всегда.
        """
        policy = self.compressor.policy
        rows = self._fetch_rows()
        watermark = self.compressor.watermark()
        uncovered = [row for row in rows if row.id > watermark]
        latest = self.compressor.latest_row()

        summary_text = ""
        if policy.enabled and latest is not None:
            summary_text = latest.content

        if policy.enabled:
            # «Последние N как есть» — хвост непокрытой конспектом истории.
            keep_rows = uncovered[-policy.keep_last:]
        else:
            # Сжатие выключено: в запрос уходит вся история (поведение дня 8).
            keep_rows = rows

        def to_messages(source: Sequence[Message]) -> List[dict]:
            return [{"role": row.role, "content": row.content} for row in source]

        tail = [{"role": "user", "content": prompt}]
        full_payload = self._system_message() + to_messages(rows) + tail
        sent_payload = self._system_message(summary_text) + to_messages(keep_rows) + tail

        summary_tokens = self.count_tokens(summary_text) if summary_text else 0
        covered_messages = len(rows) - len(uncovered) if policy.enabled else 0
        return PayloadPlan(
            full_payload=full_payload,
            sent_payload=sent_payload,
            full_context_tokens=self._count_messages(full_payload),
            sent_context_tokens=self._count_messages(sent_payload),
            kept_messages=len(keep_rows),
            covered_messages=covered_messages,
            summarized_messages=latest.covered_messages if summary_text else 0,
            summary_tokens=summary_tokens,
            summary_used=bool(summary_text),
        )

    # --- подготовка контекста по стратегии (ядро дня 10) ---
    def prepare_context(self, prompt: str) -> dict:
        """Формирует список сообщений для LLM в зависимости от стратегии.

        Возвращает словарь с ``payload`` (готовый список сообщений) и
        метаданными для метрик (оценки токенов, режим, факты к сохранению).
        Сама генерация (`generate`) дальше делает аварийную обрезку, вызов API
        и сохранение метрик; здесь — только сборка контекста. Стратегия
        ``summary`` сохраняет поведение дня 9 (сжатие конспектом).
        """
        strategy = self.strategy
        if strategy == Strategy.SLIDING_WINDOW.value:
            return self._prepare_sliding_window(prompt)
        if strategy == Strategy.STICKY_FACTS.value:
            return self._prepare_sticky_facts(prompt)
        if strategy == Strategy.BRANCHING.value:
            return self._prepare_branching(prompt)
        # summary — сжатие истории (день 9), стратегия по умолчанию.
        return self._prepare_summary(prompt)

    def _prepare_sliding_window(self, prompt: str) -> dict:
        """Скользящее окно: system + последние N реплик + новый промпт."""
        rows = self._fetch_rows()
        recent = rows[-self.window_size:]
        tail = [{"role": "user", "content": prompt}]
        body = [{"role": r.role, "content": r.content} for r in recent]
        full_body = [{"role": r.role, "content": r.content} for r in rows]
        payload = self._system_message() + body + tail
        full_payload = self._system_message() + full_body + tail
        return {
            "payload": payload,
            "context_tokens": self._count_messages(payload),
            "full_context_tokens": self._count_messages(full_payload),
            "mode": Strategy.SLIDING_WINDOW.value,
            "summary_used": False,
            "summary_tokens": 0,
            "kept_messages": len(recent),
            "summarized_messages": 0,
            "covered_messages": 0,
            "new_facts": {},
        }

    def _prepare_sticky_facts(self, prompt: str) -> dict:
        """Липкие факты: system (+факты) + последние N реплик + новый промпт.

        Факты извлекаются из новой реплики пользователя (эвристика
        `extract_facts`), сливаются с уже сохранёнными и попадают в payload.
        Новые факты сохраняются в таблицу `facts` ПОСЛЕ успешного хода (в
        `generate`), чтобы неудачный запрос не мутировал память фактов.
        """
        existing = self._current_facts()
        new_facts = extract_facts(prompt)
        merged = dict(existing)
        merged.update(new_facts)
        rows = self._fetch_rows()
        recent = rows[-self.window_size:]
        tail = [{"role": "user", "content": prompt}]
        body = [{"role": r.role, "content": r.content} for r in recent]
        full_body = [{"role": r.role, "content": r.content} for r in rows]
        payload = self._system_message(facts=merged) + body + tail
        full_payload = self._system_message(facts=merged) + full_body + tail
        return {
            "payload": payload,
            "context_tokens": self._count_messages(payload),
            "full_context_tokens": self._count_messages(full_payload),
            "mode": Strategy.STICKY_FACTS.value,
            "summary_used": False,
            "summary_tokens": 0,
            "kept_messages": len(recent),
            "summarized_messages": 0,
            "covered_messages": 0,
            "new_facts": new_facts,
        }

    def _prepare_branching(self, prompt: str) -> dict:
        """Ветвление: system + вся история активной ветки + новый промпт."""
        rows = self._fetch_rows()
        tail = [{"role": "user", "content": prompt}]
        body = [{"role": r.role, "content": r.content} for r in rows]
        payload = self._system_message() + body + tail
        tokens = self._count_messages(payload)
        return {
            "payload": payload,
            "context_tokens": tokens,
            "full_context_tokens": tokens,
            "mode": Strategy.BRANCHING.value,
            "summary_used": False,
            "summary_tokens": 0,
            "kept_messages": len(rows),
            "summarized_messages": 0,
            "covered_messages": 0,
            "new_facts": {},
        }

    def _prepare_summary(self, prompt: str) -> dict:
        """Сжатие (день 9): конспект + последние непокрытые реплики + промпт."""
        plan = self.build_payloads(prompt)
        mode = "compressed" if plan.summary_used else "full"
        return {
            "payload": plan.sent_payload,
            "context_tokens": plan.sent_context_tokens,
            "full_context_tokens": plan.full_context_tokens,
            "mode": mode,
            "summary_used": plan.summary_used,
            "summary_tokens": plan.summary_tokens,
            "kept_messages": plan.kept_messages,
            "summarized_messages": plan.summarized_messages,
            "covered_messages": plan.covered_messages,
            "new_facts": {},
        }

    # --- факты (стратегия sticky_facts) ---
    def _current_facts(self) -> Dict[str, str]:
        """Текущие факты агента из таблицы `facts` (ключ → значение)."""
        with self._session() as session:
            rows = (
                session.query(Fact)
                .filter(Fact.agent_id == self.agent_id)
                .order_by(Fact.key.asc())
                .all()
            )
        return {row.key: row.value for row in rows}

    def _upsert_facts(self, facts: Dict[str, str]) -> None:
        """Записывает/обновляет факты в таблице `facts` (по уникальному ключу)."""
        if not facts:
            return
        now = datetime.now(timezone.utc)
        with self._session() as session:
            for key, value in facts.items():
                row = (
                    session.query(Fact)
                    .filter(Fact.agent_id == self.agent_id, Fact.key == key)
                    .first()
                )
                if row is None:
                    session.add(Fact(
                        agent_id=self.agent_id, key=key, value=value,
                        updated_at=now,
                    ))
                else:
                    row.value = value
                    row.updated_at = now
            session.commit()

    def list_facts(self) -> List[dict]:
        """Факты агента для API/UI (список «ключ/значение/время»)."""
        with self._session() as session:
            rows = (
                session.query(Fact)
                .filter(Fact.agent_id == self.agent_id)
                .order_by(Fact.key.asc())
                .all()
            )
        return [
            {"key": row.key, "value": row.value, "updated_at": row.updated_at}
            for row in rows
        ]

    # --- ветвление (стратегия branching) ---
    def _checkpoint_snapshot(self) -> List[dict]:
        """Снимок текущей истории в виде списка {role, content}."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages]

    def _replace_history(self, snapshot: Sequence[dict]) -> None:
        """Заменяет историю агента (БД + память) заданным снимком.

        Используется при переключении/создании ветки: таблица `messages`
        отражает активную ветку, а остальные ветки сохраняются в `checkpoints`.
        """
        now = datetime.now(timezone.utc)
        with self._session() as session:
            session.query(Message).filter(
                Message.agent_id == self.agent_id
            ).delete()
            for item in snapshot:
                session.add(Message(
                    agent_id=self.agent_id, role=item["role"],
                    content=item["content"], timestamp=now,
                ))
            session.commit()
        self.messages = [
            {"role": item["role"], "content": item["content"]} for item in snapshot
        ]

    def _branch_dict(self, row: Checkpoint) -> dict:
        """ORM-строка чекпоинта → словарь для API/UI."""
        return {
            "id": row.id,
            "agent_id": row.agent_id,
            "parent_id": row.parent_id,
            "message_count": len(row.messages or []),
            "created_at": row.created_at,
            "is_active": row.id == self.active_branch_id,
        }

    def create_branch(self, checkpoint_id: Optional[int] = None) -> dict:
        """Создаёт новую ветку (чекпоинт) и делает её активной.

        При ``checkpoint_id`` ветка наследует снимок указанного чекпоинта
        (родитель — этот чекпоинт); при ``None`` — снимок текущей истории
        (ветвление от текущего сообщения, родитель — активная ветка).
        """
        with self._session() as session:
            if checkpoint_id is not None:
                parent = (
                    session.query(Checkpoint)
                    .filter(
                        Checkpoint.agent_id == self.agent_id,
                        Checkpoint.id == checkpoint_id,
                    )
                    .first()
                )
                if parent is None:
                    raise AgentError(
                        f"Чекпоинт {checkpoint_id} не найден у агента "
                        f"{self.agent_id}"
                    )
                snapshot = list(parent.messages)
                parent_id = checkpoint_id
            else:
                snapshot = self._checkpoint_snapshot()
                parent_id = self.active_branch_id
            row = Checkpoint(
                agent_id=self.agent_id, parent_id=parent_id, messages=snapshot,
                created_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
        self.active_branch_id = row.id
        self._replace_history(snapshot)
        return self._branch_dict(row)

    def switch_branch(self, branch_id: int) -> dict:
        """Переключает активную ветку: история заменяется снимком ветки."""
        with self._session() as session:
            row = (
                session.query(Checkpoint)
                .filter(
                    Checkpoint.agent_id == self.agent_id,
                    Checkpoint.id == branch_id,
                )
                .first()
            )
        if row is None:
            raise AgentError(
                f"Ветка {branch_id} не найдена у агента {self.agent_id}"
            )
        self._replace_history(list(row.messages))
        self.active_branch_id = branch_id
        return self._branch_dict(row)

    def list_branches(self) -> List[dict]:
        """Все чекпоинты/ветки агента по возрастанию id (дерево по parent_id)."""
        with self._session() as session:
            rows = (
                session.query(Checkpoint)
                .filter(Checkpoint.agent_id == self.agent_id)
                .order_by(Checkpoint.id.asc())
                .all()
            )
        return [self._branch_dict(row) for row in rows]

    def _snapshot_branch_tip(self) -> None:
        """Обновляет снимок активной ветки после успешного хода (branching).

        Если ветки ещё нет — создаётся корневой чекпоинт; иначе снимок активной
        ветки перезаписывается текущей историей (кончик ветки «растёт»).
        """
        snapshot = self._checkpoint_snapshot()
        with self._session() as session:
            if self.active_branch_id is None:
                row = Checkpoint(
                    agent_id=self.agent_id, parent_id=None, messages=snapshot,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(row)
                session.commit()
                self.active_branch_id = row.id
            else:
                row = (
                    session.query(Checkpoint)
                    .filter(Checkpoint.id == self.active_branch_id)
                    .first()
                )
                if row is not None:
                    row.messages = snapshot
                    session.commit()

    def _emergency_trim(self, payload: List[dict], limit: int):
        """Аварийный предохранитель: укорачивает готовый payload до лимита.

        Реплики из БД НЕ удаляются: они просто не попадают в этот запрос,
        оставаясь в истории. Из payload выкидываются самые старые ЦЕЛЫЕ пары,
        чтобы «хвост» начинался с вопроса пользователя. Возвращает
        (payload, tokens, trimmed) либо None, если даже без истории запрос
        длиннее лимита.
        """
        payload = list(payload)
        last = payload[-1]
        body = payload[:-1]
        system = []
        if body and body[0].get("role") == "system":
            system, body = body[:1], body[1:]

        # drop — сколько самых старых реплик не отправляем в этом запросе.
        # Шаг 2 сохраняет пары «вопрос-ответ» и роль user в начале хвоста.
        for drop in range(0, len(body) + 1, 2):
            candidate = system + body[drop:] + [last]
            tokens = self._count_messages(candidate)
            if tokens <= limit:
                return candidate, tokens, drop
        # Пустая история тоже не влезает — сообщение само по себе слишком длинное.
        tail = system + [last]
        if self._count_messages(tail) > limit:
            return None
        return tail, self._count_messages(tail), len(body)

    # --- стейт-машина сжатия ---
    @property
    def context_state(self) -> ContextStateBase:
        """Текущее состояние процесса сжатия."""
        return self.machine.state

    def state_value(self) -> str:
        """Состояние FSM строкой (для API/UI)."""
        return self.machine.state_value()

    def _enter_tracking(self) -> None:
        """Приводит машину в TRACKING по допустимым переходам.

        TRACKING — «копим реплики»: накопительный переход только из IDLE
        (TURN_ADDED) и из ERROR (TURN_ADDED); из SUMMARY_PENDING и SUMMARIZING
        сначала нужно выйти в состояние, из которого TURN_ADDED допустим.
        """
        current = self.machine.state.state
        if current is ContextState.SUMMARIZING:
            self.machine.dispatch(ContextEvent.SUMMARY_READY)
        elif current is ContextState.ERROR:
            self.machine.dispatch(ContextEvent.TURN_ADDED)
        elif current is ContextState.SUMMARY_PENDING:
            self.machine.dispatch(ContextEvent.RESET)
        if self.machine.state.state is ContextState.IDLE:
            self.machine.dispatch(ContextEvent.TURN_ADDED)

    def _force_idle(self) -> None:
        """Возвращает машину в IDLE (сжатие выключено или сжимать нечего)."""
        if self.machine.state.state is ContextState.SUMMARIZING:
            self.machine.dispatch(ContextEvent.SUMMARY_READY)
        if self.machine.state.state is not ContextState.IDLE:
            self.machine.dispatch(ContextEvent.RESET)

    def refresh_context_state(self) -> str:
        """Синхронизирует FSM с фактическим состоянием БД.

        Вызывается при старте агента и после смены настроек: состояние не
        хранится в БД намеренно — оно полностью выводимо из watermark, истории
        и порога сжатия, поэтому рестарт не может его «испортить».
        """
        policy = self.compressor.policy
        if not policy.enabled:
            self._force_idle()
            return self.state_value()
        plan = self.compressor.plan()
        if plan.should_compress:
            self._enter_tracking()
            self.machine.dispatch(ContextEvent.THRESHOLD_REACHED)  # -> SUMMARY_PENDING
        elif plan.uncovered_count > 0:
            self._enter_tracking()
        else:
            self._force_idle()
        return self.state_value()

    def compress_now(self, force: bool = False) -> dict:
        """Запускает сжатие (при необходимости) и возвращает отчёт о попытке.

        Порядок переходов FSM: TRACKING → SUMMARY_PENDING → SUMMARIZING →
        TRACKING (успех) либо ERROR (сбой). Сбой не поднимается наружу: агент
        продолжает работать без нового конспекта, повтор — на следующем ходу.
        """
        policy = self.compressor.policy
        report = {
            "attempted": False,
            "created": False,
            "error": None,
            "summarized_messages": 0,
            "state": self.state_value(),
        }
        if not policy.enabled:
            self._force_idle()
            report["error"] = "Сжатие истории выключено для этого агента"
            report["state"] = self.state_value()
            return report

        plan = self.compressor.plan(force=force)
        if not plan.should_compress:
            if plan.uncovered_count > 0:
                self._enter_tracking()
            else:
                self._force_idle()
            report["state"] = self.state_value()
            return report

        self._enter_tracking()
        self.machine.dispatch(ContextEvent.THRESHOLD_REACHED)  # -> SUMMARY_PENDING
        self.machine.dispatch(ContextEvent.SUMMARY_REQUESTED)  # -> SUMMARIZING
        report["attempted"] = True
        try:
            outcome = self.compressor.summarize(force=force)
        except CompressionError as exc:
            self.machine.dispatch(ContextEvent.SUMMARY_FAILED)  # -> ERROR
            report["error"] = str(exc)
            report["state"] = self.state_value()
            return report
        self.machine.dispatch(ContextEvent.SUMMARY_READY)  # -> TRACKING
        report["created"] = outcome.created
        report["summarized_messages"] = outcome.covered_messages
        report["state"] = self.state_value()
        return report

    def saved_tokens_from_usage(self) -> int:
        """Сумма сэкономленных токенов по всем ходам агента (таблица token_usage)."""
        with self._session() as session:
            total = (
                session.query(func.coalesce(func.sum(TokenUsage.saved_tokens), 0))
                .filter(TokenUsage.agent_id == self.agent_id)
                .scalar()
            )
        return int(total or 0)

    # --- генерация ---
    def generate(self, prompt: str) -> dict:
        """Отправляет запрос в DeepSeek с контекстом по текущей стратегии.

        1) ``prepare_context`` собирает payload согласно стратегии (скользящее
           окно / липкие факты / ветвление / сжатие-конспект);
        2) аварийная обрезка, если даже собранный запрос не влезает в лимит
           модели (реплики из БД при этом не удаляются);
        3) вызов API; при успехе метрики хода сохраняются в ``token_usage`` той
           же транзакцией, что и пара реплик;
        4) после успешного хода — действие стратегии: сжатие конспекта
           (summary), сохранение фактов (sticky_facts) или снимок ветки
           (branching).
        """
        timestamp = datetime.now(timezone.utc)
        limit = self.context_limit_tokens
        record: dict = {
            "agent_id": self.agent_id,
            "status": "error",
            "prompt": prompt,
            "response": None,
            "error": None,
            "model": self.config.model,
            "finish_reason": None,
            "usage": None,
            "token_metrics": None,
            "context": None,
            "duration_sec": None,
            "timestamp": timestamp,
        }

        # 1) пользовательский ход — в память (в БД — только при успехе).
        self.messages.append({"role": "user", "content": prompt})

        ctx = self.prepare_context(prompt)
        payload = ctx["payload"]
        sent_tokens = ctx["context_tokens"]
        trimmed = 0
        warning = None

        # 2) контроль лимита: стратегия уже сократила запрос, но одно огромное
        #    сообщение всё ещё может его переполнить.
        if sent_tokens > limit:
            trimmed_result = self._emergency_trim(payload, limit)
            if trimmed_result is None:
                self.messages.pop()  # откат: БД не менялась
                record["error"] = (
                    f"Сообщение длиннее лимита контекста модели ({limit} "
                    f"токенов): примерно {self.count_tokens(prompt)} токенов. "
                    "Сократите сообщение и повторите."
                )
                record["context"] = {
                    "max_model_tokens": limit,
                    "warning": None,
                    "state": self.state_value(),
                }
                return record
            payload, sent_tokens, trimmed = trimmed_result
            warning = (
                f"⚠️ Контекст не поместился: оценка запроса "
                f"{ctx['context_tokens']} токенов больше лимита {limit}. "
                f"{trimmed} самых старых реплик не отправлены в этом запросе "
                "(в истории они сохранены)."
            )

        started = time.perf_counter()
        try:
            client = self._make_client()
            response = client.chat.completions.create(
                model=self.config.model,
                messages=payload,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
        except AgentError as exc:
            self.messages.pop()  # откат: сбой ДО вызова сети
            record["error"] = str(exc)
        except Exception as exc:  # сеть/API DeepSeek/неожиданное: не валим сервер
            self.messages.pop()  # откат: ответа не было — история не меняется
            record["error"] = f"Сбой запроса к DeepSeek: {exc}"
        else:
            choice = response.choices[0] if response.choices else None
            answer = ""
            if choice is not None and choice.message is not None:
                answer = choice.message.content or ""
            record["status"] = "ok"
            record["response"] = answer
            if choice is not None:
                record["finish_reason"] = choice.finish_reason

            # 3) метрики токенов: фактические из usage API (если есть), иначе оценки.
            response_est = self.count_tokens(answer)
            prompt_used = sent_tokens
            completion_used = response_est
            total_used = sent_tokens + response_est
            usage = getattr(response, "usage", None)
            if usage is not None:
                api_prompt = getattr(usage, "prompt_tokens", None)
                api_completion = getattr(usage, "completion_tokens", None)
                api_total = getattr(usage, "total_tokens", None)
                if api_prompt is not None:
                    prompt_used = int(api_prompt)
                if api_completion is not None:
                    completion_used = int(api_completion)
                if api_total is not None:
                    total_used = int(api_total)
                else:
                    total_used = prompt_used + completion_used
                record["usage"] = {
                    "prompt_tokens": prompt_used,
                    "completion_tokens": completion_used,
                    "total_tokens": total_used,
                }

            mode = ctx["mode"]
            token_metrics = {
                "prompt_tokens": prompt_used,
                "completion_tokens": completion_used,
                "total_tokens": total_used,
                "history_tokens": max(0, sent_tokens - self.count_tokens(prompt)),
                "response_tokens": response_est,
                "cost": self._estimate_cost(prompt_used, completion_used),
                "mode": mode,
                "full_context_tokens": ctx["full_context_tokens"],
                "sent_context_tokens": sent_tokens,
                "saved_tokens": max(0, ctx["full_context_tokens"] - sent_tokens),
                "summary_tokens": ctx["summary_tokens"],
                "summarized_messages": ctx["summarized_messages"],
                "summary_used": ctx["summary_used"],
            }
            record["token_metrics"] = token_metrics

            # 4) ход ассистента + атомарное сохранение пары и метрик в БД.
            self.messages.append({"role": "assistant", "content": answer})
            self._save_turn(prompt, answer, metrics=token_metrics)

            # 5) пост-ходовые действия по стратегии.
            if self.strategy == Strategy.SUMMARY.value:
                # Конспект обновится для следующих запросов (день 9).
                compression_report = self.compress_now()
            else:
                compression_report = {
                    "attempted": False, "created": False, "error": None,
                    "summarized_messages": 0, "state": self.state_value(),
                }
                if self.strategy == Strategy.STICKY_FACTS.value:
                    # Факты из новой реплики + из ответа ассистента.
                    new_facts = dict(ctx.get("new_facts") or {})
                    new_facts.update(extract_facts(answer))
                    self._upsert_facts(new_facts)
                elif self.strategy == Strategy.BRANCHING.value:
                    # Снимок активной ветки растёт вместе с диалогом.
                    self._snapshot_branch_tip()

            saved_percent = 0.0
            if ctx["full_context_tokens"]:
                saved_percent = round(
                    100.0 * token_metrics["saved_tokens"] / ctx["full_context_tokens"],
                    1,
                )
            record["context"] = {
                "max_model_tokens": limit,
                "payload_tokens": prompt_used,
                "context_tokens": sent_tokens,
                "remaining_tokens": max(0, limit - sent_tokens),
                "over_limit": bool(trimmed),
                "trimmed_messages": trimmed,
                "warning": warning,
                "state": compression_report["state"],
                "strategy": self.strategy,
                "compression": {
                    "enabled": self.strategy == Strategy.SUMMARY.value
                    and self.compressor.policy.enabled,
                    "mode": mode,
                    "summary_used": ctx["summary_used"],
                    "summary_tokens": ctx["summary_tokens"],
                    "kept_messages": ctx["kept_messages"],
                    "summarized_messages": ctx["summarized_messages"],
                    "covered_messages": ctx["covered_messages"],
                    "full_context_tokens": ctx["full_context_tokens"],
                    "sent_context_tokens": sent_tokens,
                    "saved_tokens": token_metrics["saved_tokens"],
                    "saved_percent": saved_percent,
                    "error": compression_report["error"],
                },
            }
        finally:
            record["duration_sec"] = round(time.perf_counter() - started, 3)

        return record

    def compare_modes(self, prompt: str, call_api: bool = False) -> dict:
        """Сравнивает два режима контекста на одном промпте, НЕ меняя историю.

        Без ``call_api`` считаются только токены обоих вариантов (работает без
        ключа и без сети). С ``call_api=True`` выполняются два реальных вызова
        DeepSeek — «полная история» и «конспект + последние N реплик» — чтобы
        сравнить и ответы, и расход.
        """
        plan = self.build_payloads(prompt)
        result = {
            "agent_id": self.agent_id,
            "prompt": prompt,
            "call_api": call_api,
            "history_messages": self.message_count,
            "full": {
                "mode": "full",
                "sent_context_tokens": plan.full_context_tokens,
                "full_context_tokens": plan.full_context_tokens,
                "summary_used": False,
                "kept_messages": self.message_count,
                "summarized_messages": 0,
            },
            "compressed": {
                "mode": "compressed",
                "sent_context_tokens": plan.sent_context_tokens,
                "full_context_tokens": plan.full_context_tokens,
                "summary_used": plan.summary_used,
                "kept_messages": plan.kept_messages,
                "summarized_messages": plan.summarized_messages,
            },
            "saved_tokens": plan.saved_tokens,
            "saved_percent": (
                round(100.0 * plan.saved_tokens / plan.full_context_tokens, 1)
                if plan.full_context_tokens else 0.0
            ),
            "warning": None,
        }
        if not call_api:
            return result

        for side, payload in (("full", plan.full_payload),
                              ("compressed", plan.sent_payload)):
            started = time.perf_counter()
            try:
                client = self._make_client()
                response = client.chat.completions.create(
                    model=self.config.model,
                    messages=payload,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
            except Exception as exc:  # нет ключа/сеть/лимиты — сообщаем, не падаем
                result[side]["error"] = f"Сбой запроса к DeepSeek: {exc}"
                result[side]["duration_sec"] = round(
                    time.perf_counter() - started, 3
                )
                continue
            choice = response.choices[0] if response.choices else None
            answer = ""
            if choice is not None and choice.message is not None:
                answer = choice.message.content or ""
            usage = getattr(response, "usage", None)
            result[side]["response"] = answer
            result[side]["duration_sec"] = round(time.perf_counter() - started, 3)
            if usage is not None:
                result[side]["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
                result[side]["completion_tokens"] = getattr(
                    usage, "completion_tokens", None
                )
                result[side]["total_tokens"] = getattr(usage, "total_tokens", None)
            result[side]["cost"] = self._estimate_cost(
                result[side].get("prompt_tokens") or plan.sent_context_tokens,
                result[side].get("completion_tokens") or 0,
            )
        errors = [result["full"].get("error"), result["compressed"].get("error")]
        if any(errors):
            result["warning"] = "Часть сравнения не выполнена: " + "; ".join(
                err for err in errors if err
            )
        return result

    def summary_state(self) -> dict:
        """Состояние сжатия агента для API/UI (конспект, watermark, экономика).

        Состояние FSM пересчитывается из БД: сжатие могло стать нужным из-за
        реплик, добавленных другим процессом/сессией, а хранится оно не в БД, а
        выводится из watermark и порога.
        """
        self.refresh_context_state()
        policy = self.compressor.policy
        history = self.compressor.history()
        latest = history[-1] if history else None
        economics = self.compressor.economics()
        rows = self._fetch_rows()
        uncovered = self.compressor.uncovered_rows()
        plan = self.compressor.plan()
        return {
            "agent_id": self.agent_id,
            "model": self.model,
            "enabled": policy.enabled,
            "keep_last_messages": policy.keep_last,
            "summarize_every": policy.summarize_every,
            "state": self.state_value(),
            "message_count": len(rows),
            "summary_count": len(history),
            "covered_messages": len(rows) - len(uncovered),
            "uncovered_messages": len(uncovered),
            "current": latest,
            "history": history,
            "total_source_tokens": economics["total_source_tokens"],
            "total_summary_tokens": economics["total_summary_tokens"],
            "summary_cost": economics["summary_cost"],
            "saved_tokens": economics["saved_tokens"],
            "net_saved_tokens": economics["net_saved_tokens"],
            "next_compression_in": max(
                0, policy.keep_last + policy.summarize_every - len(uncovered)
            ),
        }
