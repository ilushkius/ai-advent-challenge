"""Класс Agent дня 19 — агент с памятью, задачей, инвариантами, MCP и пайплайном.

День 17 добавляет **MCP-инструменты**: перед сборкой контекста агент сам решает
по ключевым словам реплики, нужен ли вызов инструмента внешнего сервера
(``backend/domain/mcp_intent.py``), проверяет допуск вызова правилами
(``mcp_tool_call.admission_reason``: соединение, каталог, аргументы) и при успехе
дописывает полученные данные системным блоком «## Данные MCP-инструмента» в
промпт этого же запроса. Отчёт хода (``record["mcp"]``) показывает инструмент,
аргументы, состояние вызова и ошибку, а добавленные токены входят в контроль
лимита контекста. Неудача вызова ход не роняет: агент отвечает без внешних данных.

День 19 добавляет **пайплайн MCP-инструментов**: реплика вида «найди статьи про
RAG, сделай сводку и сохрани в файл» распознаётся эвристикой
(``backend/domain/pipeline_intent.py``) и запускает декларативный прогон
(``backend/services/pipeline.py``) — шаги идут по порядку, данные передаются
маппингом, а журнал пишется в ``pipeline_steps``. Отчёт хода
(``record["pipeline"]``) показывает статус прогона, его шаги и итог, а результат
успешного прогона уходит в системный промпт блоком «## Результат пайплайна».
Шаг пайплайна стоит ПЕРЕД шагом одиночного MCP-инструмента и заменяет его: если
реплика — пайплайн, разбирать её ещё и как одиночный вызов не нужно.

День 15 добавил **контролируемые переходы** состояния задачи: состояние
описывается явным графом (``backend/domain/task_state_machine.py``), переход
вперёд требует согласования этапа (флаг ``plan_approved``,
``implementation_complete``, ``validation_passed``), а недопустимая попытка
отклоняется с объяснением и попадает в журнал (``task_transitions.accepted =
False``). Агент участвует в этом с двух сторон: реплика-намерение пользователя
(«продолжи», «подтверждаю») выполняется только если переход разрешён — иначе
ответ начинается с уведомления ``intent_refusal_notice``, а предложение самого
модели перейти в другой этап распознаётся (``task_proposal.py``) и при
недопустимости заменяется отказом (``🚧 Ответ предлагает переход в …``).
Блок состояния в системном промпте называет допустимые следующие этапы и прямо
запрещает пробовать недопустимые.

День 14 добавляет **инварианты** — правила проекта, которые агент не имеет
права нарушать: активные правила из таблицы ``invariants`` подставляются блоком
в системный промпт каждого запроса, а предложение проверяется ПЕРЕД выдачей
(сначала детерминированные правила, при неоднозначности — вызов LLM,
``backend/services/invariant_checker.py``). Нарушение hard-инварианта
превращает ответ в ОТКАЗ (``_refuse_by_invariants``: DeepSeek не вызывается,
токены не тратятся), нарушение soft — в предупреждение в начале ответа.
Проверка хода видна в отчёте генерации (``record["invariants"]``).

День 12 добавляет персонализацию: у агента есть ``user_id``, и при каждом
формировании контекста в системное сообщение подставляется блок, собранный из
профиля пользователя (``backend/profiles.py``): обращение по имени, стиль,
формат, длина ответа, ограничения и произвольные инструкции. Профиль читается из
SQLite при инициализации агента (``reload_profile()`` обновляет его на лету),
поэтому смена профиля в интерфейсе влияет на следующий же запрос. Отчёт
генерации возвращает применённый профиль (по элементам) и итоговый системный
промпт.

Слои памяти и стратегии управления контекстом — из дня 11.

День 11 развивает день 10: единая история диалога заменяется **тремя явными
слоями памяти** со своими таблицами и своим жизненным циклом.

- **Краткосрочная** (``short_term_messages``) — текущий диалог одной сессии
  (``self.session_id``). В памяти процесса её зеркалит
  ``self.short_term_messages``: ``[{"role": ..., "content": ...}, ...]``.
  Очищается ``new_session()`` или ``DELETE /memory/short-term``.
- **Рабочая** (``working_memory``) — данные активной задачи
  (``self.task_id``): цель, ограничения, решения. Переживает смену сессии,
  меняется ``set_task()``.
- **Долговременная** (``long_term_memory``) — профиль, предпочтения, решения и
  знания. Переживает и сессии, и задачи.

Хранилищем всех трёх слоёв заведует ``MemoryManager`` (``memory.py``); Agent
решает, ЧТО из каждого слоя уйдёт в запрос, и возвращает разбивку токенов по
слоям (``record["memory"]``).

Сжатие истории (стратегия ``summary``), ветвление, факты и контроль лимита
контекста из дней 9–10 сохраняются: конспект по-прежнему заменяет старые
реплики краткосрочного слоя только В ЗАПРОСЕ. Полная история сессии из БД не
удаляется, пока сессия активна; ``new_session()`` удаляет её вместе с
производными (конспекты, факты), но не трогает рабочую и долговременную память.

Фабрики для офлайн-проверок: клиент создаётся ``_make_client()`` (подменяется
фейком), фабрика сессий БД передаётся через ``session_factory``.
"""
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence
from uuid import uuid4

from sqlalchemy import func

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger
from shared.token_counter import count_tokens

from ..core import config
from ..storage import database
from ..services.compressor import CompressionError, ContextCompressor
from ..domain.context_fsm import (
    ContextEvent, ContextMachine, ContextState, ContextStateBase,
)
from ..models.context import Checkpoint, Fact, Summary, TokenUsage
from ..models.message import ShortTermMessage
from ..domain.fact_extractor import extract_facts
from ..domain.invariant_prompt import (
    render_invariants_block, render_violation_refusal, render_violation_warning,
)
from ..domain.invariant_values import VERDICT_REFUSAL, VERDICT_WARNING
from ..domain.mcp_prompt import render_mcp_tool_block
from ..domain.orchestration_intent import classify_orchestration_intent
from ..domain.orchestration_prompt import render_orchestration_block
from ..domain.pipeline_intent import classify_pipeline_intent
from ..domain.pipeline_prompt import render_pipeline_block
from ..domain.scheduler_prompt import render_schedule_report, render_scheduler_block
from .memory import (
    MemoryManager, query_keywords, render_long_term_block, render_working_block,
)
from ..schemas import AgentConfig
from .profile_store import ProfileData, ProfileStore, empty_profile
from ..services.invariant_checker import InvariantCheckResult, InvariantChecker
from ..services.mcp_tool_runner import MCPToolRunner
from ..storage.invariant_store import InvariantManager
from ..domain.strategies import Strategy
from ..domain.task_fsm import (
    InvalidTransitionError, TaskStage, UnknownTaskEvent,
)
from ..domain.task_intent import TaskIntent, classify_task_intent
from ..domain.task_prompt import render_task_state_block
from ..domain.task_proposal import detect_stage_proposal
from ..domain.task_state_machine import (
    guard_context,
    intent_refusal_notice,
    is_transition_allowed,
    transition_explanation,
)
from ..services.task_state import TaskStateMachine

logger = get_logger(__name__)


def _empty_pipeline_report() -> dict:
    """Пустой отчёт шага пайплайна: реплика не распознана или шаг пропущен.

    Одна форма на два случая: интерфейс и API разбирают поле ``pipeline`` ответа
    генерации всегда, поэтому у «не запускался» должны быть те же ключи, что у
    прогона (иначе потребитель различал бы «нет прогона» и «прогон без деталей»).
    """
    return {
        "detected": False, "run_id": None, "status": "", "message": "",
        "failed_at_step": None, "error": None, "steps": [], "count": 0,
        "total_duration_ms": 0, "used_in_prompt": False, "added_tokens": 0,
    }


class AgentError(Exception):
    """Понятная ошибка уровня агента (нет ключа, сбой API и т.п.)."""


@dataclass(frozen=True)
class MemoryContext:
    """Данные трёх слоёв памяти, собранные для конкретного запроса.

    ``working`` / ``long_term`` — записи слоёв, ``working_text`` /
    ``long_term_text`` — их текстовые блоки для системного сообщения (пустая
    строка, если слой пуст), ``*_tokens`` — оценки tiktoken этих блоков,
    ``keywords`` — ключевые слова запроса, по которым отобран долговременный
    слой.
    """

    task_id: str = config.DEFAULT_TASK_ID
    working: List[dict] = field(default_factory=list)
    long_term: List[dict] = field(default_factory=list)
    working_text: str = ""
    long_term_text: str = ""
    working_tokens: int = 0
    long_term_tokens: int = 0
    keywords: List[str] = field(default_factory=list)


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
    # Токены краткосрочного слоя в отправленном payload: конспект считается
    # отдельно (summary_tokens), потому что это сжатие того же слоя.
    short_term_tokens: int = 0

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
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        mcp_registry=None,
        pipeline_service=None,
        orchestration_service=None,
    ) -> None:
        self.agent_id = agent_id
        self.config = cfg
        self.created_at = created_at or datetime.now(timezone.utc)
        self._session_factory = session_factory or database.SessionLocal
        # Слои памяти: краткосрочная привязана к сессии, рабочая — к задаче,
        # долговременная — к агенту целиком. Хранилищем заведует MemoryManager.
        self.session_id: str = session_id or uuid4().hex[:config.SESSION_ID_LENGTH]
        self.task_id: str = task_id or config.DEFAULT_TASK_ID
        self.memory = MemoryManager(session_factory=self._session_factory)
        # Стратегия управления контекстом (день 11): значение из конфигурации,
        # окно — для sliding_window/sticky_facts. Активная ветка (branching)
        # хранится в памяти процесса: на рестарте она не восстанавливается.
        self.strategy: str = cfg.strategy
        self.window_size: int = cfg.window_size
        self.active_branch_id: Optional[int] = None
        # Персонализация (день 12): профиль пользователя читается из БД при
        # инициализации агента и подставляется в системный промпт каждого
        # запроса. Пустой профиль (записи нет) = агент работает как обычно.
        self.user_id: str = cfg.user_id
        self.profile_store = ProfileStore(session_factory=self._session_factory)
        self.profile: ProfileData = self.profile_store.load(self.user_id)
        # Зеркало краткосрочного слоя текущей сессии:
        # [{"role": ..., "content": ...}, ...].
        self.short_term_messages: List[Dict[str, str]] = []
        # Стейт-машина сжатия: живёт в памяти процесса, но её состояние всегда
        # восстановимо из БД (см. refresh_context_state).
        self.machine = ContextMachine()
        self.compressor = ContextCompressor(self)
        # Состояние задачи (день 13): строка в task_states читается из БД по
        # task_id, поэтому машина не держит состояние в памяти и переживает
        # рестарт; атрибут есть всегда, состояние может отсутствовать.
        self.task_state_machine = TaskStateMachine(
            session_factory=self._session_factory, memory=self.memory,
        )
        # Инварианты (день 14): правила проекта в отдельной таблице invariants.
        # Хранилище создаётся на фабрике сессий агента и читает БД в момент
        # проверки, поэтому правка списка правил видна со следующего запроса.
        self.invariants = InvariantManager(session_factory=self._session_factory)
        # MCP-инструменты (день 17): реестр подключения к MCP-серверу. None —
        # реестр процесса (см. MCPToolRunner.registry); в тестах сюда приходит
        # фейковый реестр, поэтому агент не поднимает настоящий сервер.
        self._mcp_registry = mcp_registry
        # Пайплайн композиции (день 19): служба запусков. None — служба процесса
        # (см. свойство ``pipeline_service``); в тестах сюда приходит служба на
        # фейковом реестре, поэтому агент не поднимает настоящий MCP-сервер.
        self._pipeline_service = pipeline_service
        self._orchestration_service = orchestration_service
        # Старт приложения/создание агента: загружаем краткосрочный слой.
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
        """Число реплик краткосрочной памяти текущей сессии."""
        return len(self.short_term_messages)

    def apply_config(self, cfg: AgentConfig) -> None:
        """Заменяет конфигурацию агента (используется PATCH /agents/{id}).

        Смена ``user_id`` перечитывает профиль: персонализация следующего
        запроса определяется новым пользователем.
        """
        self.config = cfg
        self.strategy = cfg.strategy
        self.window_size = cfg.window_size
        if cfg.user_id != self.user_id:
            self.user_id = cfg.user_id
            self.reload_profile()

    # --- персонализация (день 12) ---
    def reload_profile(self) -> ProfileData:
        """Перечитывает профиль пользователя из БД (смена профиля на лету)."""
        self.profile = self.profile_store.load(self.user_id)
        return self.profile

    def apply_profile(self, profile: Optional[ProfileData] = None) -> ProfileData:
        """Ставит агенту готовый профиль (менеджер передаёт обновлённый).

        Отличие от ``reload_profile``: лишнего чтения из БД нет — менеджер уже
        получил запись после UPDATE и раздаёт её живым агентам пользователя.
        """
        if profile is not None:
            self.profile = profile
            self.user_id = profile.user_id
        return self.profile

    def profile_report(self) -> dict:
        """Применённый профиль для ответа API: элементы и их вклад в промпт.

        Ключ ``instructions`` — разобранные произвольные инструкции (списком),
        ключ ``prompt_block`` — весь блок персонализации, ушедший в системный
        промпт. Поля совпадают с ``AppliedProfileOut``: иначе FastAPI отбросил
        бы лишние ключи и в ответе генерации оказался бы пустой список.
        """
        prompt = self.profile.prompt
        return {
            "user_id": self.profile.user_id,
            "name": self.profile.name,
            "personalized": prompt.personalized,
            "summary": self.profile.summary,
            "elements": prompt.elements_as_dicts(),
            "prompt_block": prompt.text,
            "instructions": list(self.profile.instructions),
        }

    def profile_state(self) -> dict:
        """Профиль агента для UI: настройки + промпт (без блоков памяти задачи).

        ``system_prompt`` — системное сообщение, которое уйдёт со следующим
        запросом, если у агента нет своей роли и слои памяти пусты: так в
        интерфейсе видно «вклад профиля» отдельно от роли агента.
        """
        state = self.profile.as_dict()
        prompt = self.profile.prompt
        # custom_instructions остаётся текстом (поле БД), instructions — списком
        # (то, что ушло в промпт): имена не пересекаются с текстом профиля.
        state["instructions"] = list(self.profile.instructions)
        state["elements"] = prompt.elements_as_dicts()
        state["prompt_block"] = prompt.text
        state["system_prompt"] = self._system_text(self._system_message())
        return state

    # --- подсчёт токенов ---
    def count_tokens(self, text: str) -> int:
        """Число токенов текста в кодировке `cl100k_base` (tiktoken).

        Пустой текст = 0 токенов. Подсчёт локальный и приблизительный:
        DeepSeek использует собственный токенизатор, поэтому числа близки к
        фактическим, но не обязаны совпадать с `usage` API.
        """
        if not text:
            return 0
        return count_tokens(text)

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

    def _fetch_rows(self) -> List[ShortTermMessage]:
        """Реплики краткосрочного слоя текущей сессии в хронологическом порядке."""
        with self._session() as session:
            return (
                session.query(ShortTermMessage)
                .filter(
                    ShortTermMessage.agent_id == self.agent_id,
                    ShortTermMessage.session_id == self.session_id,
                )
                .order_by(ShortTermMessage.created_at.asc(), ShortTermMessage.id.asc())
                .all()
            )

    # --- краткосрочный слой: загрузка / сохранение / очистка ---
    def load_history(self) -> None:
        """Загружает краткосрочный слой сессии из БД в self.short_term_messages."""
        self.short_term_messages = [
            {"role": row.role, "content": row.content} for row in self._fetch_rows()
        ]

    def history_rows(self) -> List[Dict]:
        """Реплики сессии с метаданными (для API): id, роль, текст, время.

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
                "created_at": row.created_at,
                "summarized": row.id <= watermark,
            }
            for row in rows
        ]

    def save_message(self, role: str, content: str) -> Dict:
        """Сохраняет одну реплику в краткосрочный слой и в память процесса."""
        created_at = datetime.now(timezone.utc)
        with self._session() as session:
            row = ShortTermMessage(
                agent_id=self.agent_id, session_id=self.session_id, role=role,
                content=content, created_at=created_at,
            )
            session.add(row)
            session.commit()
        self.short_term_messages.append({"role": role, "content": content})
        return {
            "id": row.id, "agent_id": self.agent_id, "session_id": self.session_id,
            "role": role, "content": content, "created_at": created_at,
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
            ShortTermMessage(
                agent_id=self.agent_id, session_id=self.session_id, role="user",
                content=user_content, created_at=now,
            ),
            ShortTermMessage(
                agent_id=self.agent_id, session_id=self.session_id, role="assistant",
                content=assistant_content, created_at=now,
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
                short_term_tokens=metrics.get("short_term_tokens", 0),
                working_tokens=metrics.get("working_tokens", 0),
                long_term_tokens=metrics.get("long_term_tokens", 0),
            ))
        with self._session() as session:
            session.add_all(rows)
            session.commit()

    def clear_history(self) -> int:
        """Полный сброс краткосрочного слоя, конспектов, фактов и метрик агента.

        Удаляются все реплики агента (все сессии), ``summaries``,
        ``token_usage``, ``facts`` и ``checkpoints`` — «новый диалог» начинает
        счёт токенов и конспектов с нуля. Рабочая и долговременная память НЕ
        очищаются: это данные задачи и профиля, а не диалога. Возвращает число
        удалённых реплик.
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
                session.query(ShortTermMessage)
                .filter(ShortTermMessage.agent_id == self.agent_id)
                .delete()
            )
            session.commit()
        self.short_term_messages = []
        self.active_branch_id = None
        self.refresh_context_state()
        return deleted

    # --- слои памяти (день 11) ---
    def new_session(self) -> dict:
        """Начинает новую сессию: краткосрочный слой прошлой сессии очищается.

        Удаляются данные, производные от старого диалога (реплики его сессии,
        конспекты, факты) и сбрасывается активная ветка. Рабочая и долговременная
        память, снимки веток (``checkpoints``), метрики (``token_usage``) и
        конфигурация агента сохраняются.
        """
        previous = self.session_id
        new_id = uuid4().hex[:config.SESSION_ID_LENGTH]
        with self._session() as session:
            deleted = (
                session.query(ShortTermMessage)
                .filter(
                    ShortTermMessage.agent_id == self.agent_id,
                    ShortTermMessage.session_id == previous,
                )
                .delete()
            )
            session.query(Summary).filter(
                Summary.agent_id == self.agent_id
            ).delete()
            session.query(Fact).filter(
                Fact.agent_id == self.agent_id
            ).delete()
            record = (
                session.query(database.AgentRecord)
                .filter(database.AgentRecord.agent_id == self.agent_id)
                .first()
            )
            if record is not None:
                record.current_session_id = new_id
            session.commit()
        self.session_id = new_id
        self.short_term_messages = []
        self.active_branch_id = None
        self.refresh_context_state()
        return {
            "agent_id": self.agent_id,
            "previous_session_id": previous,
            "session_id": new_id,
            "deleted_messages": int(deleted or 0),
        }

    def set_task(self, task_id: str) -> dict:
        """Переключает активную задачу (рабочая память фильтруется по task_id)."""
        task_id = (task_id or "").strip()
        if not task_id:
            raise AgentError("task_id не может быть пустым")
        if len(task_id) > config.TASK_ID_MAX:
            raise AgentError(
                f"task_id длиннее {config.TASK_ID_MAX} символов"
            )
        with self._session() as session:
            record = (
                session.query(database.AgentRecord)
                .filter(database.AgentRecord.agent_id == self.agent_id)
                .first()
            )
            if record is not None:
                record.current_task_id = task_id
            session.commit()
        self.task_id = task_id
        return {
            "agent_id": self.agent_id,
            "task_id": task_id,
            "entries": len(self.memory.get_working(self.agent_id, task_id)),
        }

    def build_memory_context(self, prompt: str) -> MemoryContext:
        """Собирает данные трёх слоёв для запроса и считает токены по слоям.

        Краткосрочный слой в контекст собирает стратегия (``prepare_context``);
        здесь — рабочая память активной задачи (все записи) и релевантные записи
        долговременной памяти (отбор по ключевым словам запроса + добор по
        уверенности, см. ``MemoryManager.select_long_term``).
        """
        working = self.memory.get_working(self.agent_id, self.task_id)
        long_term = self.memory.select_long_term(self.agent_id, prompt)
        working_text = render_working_block(working)
        long_term_text = render_long_term_block(long_term)
        return MemoryContext(
            task_id=self.task_id,
            working=working,
            long_term=long_term,
            working_text=working_text,
            long_term_text=long_term_text,
            working_tokens=self.count_tokens(working_text),
            long_term_tokens=self.count_tokens(long_term_text),
            keywords=query_keywords(prompt),
        )

    def memory_state(self) -> dict:
        """Сводка слоёв для API/UI: сессия, задача, счётчики и токены."""
        rows = self._fetch_rows()
        short_term_tokens = self._count_messages(
            [{"role": row.role, "content": row.content} for row in rows]
        )
        working = self.memory.get_working(self.agent_id, self.task_id)
        long_term = self.memory.get_long_term(self.agent_id)
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "short_term": {"count": len(rows), "tokens": short_term_tokens},
            "working": {
                "count": len(working),
                "tokens": self.count_tokens(render_working_block(working)),
            },
            "long_term": {
                "count": len(long_term),
                "tokens": self.count_tokens(render_long_term_block(long_term)),
            },
        }

    def short_term_rows(self, session_id: Optional[str] = None,
                        limit: Optional[int] = None) -> List[dict]:
        """Реплики краткосрочного слоя (по умолчанию — текущей сессии)."""
        return self.memory.get_short_term(
            self.agent_id, session_id or self.session_id, limit=limit
        )

    def add_short_term(self, role: str, content: str) -> dict:
        """Добавляет реплику в краткосрочный слой текущей сессии (обёртка)."""
        row = self.memory.add_short_term(self.agent_id, self.session_id, role, content)
        self.short_term_messages.append({"role": role, "content": content})
        return row

    def clear_short_term(self, session_id: Optional[str] = None) -> int:
        """Очищает краткосрочный слой указанной (или текущей) сессии."""
        target = session_id or self.session_id
        deleted = self.memory.clear_short_term(self.agent_id, target)
        if target == self.session_id:
            self.load_history()
        return deleted

    def working_rows(self, task_id: Optional[str] = None) -> List[dict]:
        """Записи рабочей памяти задачи (по умолчанию — активной)."""
        return self.memory.get_working(self.agent_id, task_id or self.task_id)

    def add_working(self, key: str, value: str,
                    task_id: Optional[str] = None) -> dict:
        """Upsert записи рабочей памяти (по умолчанию — активной задачи)."""
        return self.memory.add_working(
            self.agent_id, task_id or self.task_id, key, value
        )

    def long_term_rows(self, category: Optional[str] = None) -> List[dict]:
        """Записи долговременной памяти (все категории или одна)."""
        return self.memory.get_long_term(self.agent_id, category)

    def add_long_term(self, category: str, key: str, value: str,
                      confidence: float = 1.0) -> dict:
        """Upsert записи долговременной памяти."""
        return self.memory.add_long_term(
            self.agent_id, category, key, value, confidence=confidence
        )

    def delete_long_term(self, entry_id: int) -> bool:
        """Удаляет запись долговременной памяти по id (False — не было)."""
        return self.memory.delete_long_term(self.agent_id, entry_id)

    # --- состояние задачи (день 13) ---
    def task_state(self) -> Optional[dict]:
        """Текущее состояние задачи агента (``None`` — состояние не заведено)."""
        return self.task_state_machine.get_state(self.task_id)

    def task_state_block(self) -> str:
        """Блок «Текущий этап…» для системного промпта (``""`` — состояния нет).

        Читается из БД на каждый запрос, поэтому после перезапуска процесса
        агент видит, где остановился, и не просит объяснять заново.
        """
        state = self.task_state()
        if state is None:
            return ""
        return render_task_state_block(
            state["stage"], state["current_step"], state["expected_action"],
            state["allowed_next"],
            resume_stage=state["paused_from_stage"],
        )

    def apply_task_intent(self, prompt: str) -> Optional[dict]:
        """Обновляет состояние задачи по реплике пользователя (день 15).

        Возвращает отчёт о попытке: ``{"intent", "applied", "reason",
        "allowed_next"}``. ``None`` — намерения нет, задача не заведена или она
        завершена (как в дне 14: завершённая задача на реплики не реагирует).

        Отклонённый переход не роняет генерацию: он попадает в журнал попыток
        (``accepted=False``), возвращается в отчёте и превращается в
        уведомление в ответе (``intent_refusal_notice``) — пользователь видит,
        что именно не сработало, почему и куда задача может перейти.
        """
        intent = classify_task_intent(prompt)
        if intent is None:
            return None
        state = self.task_state()
        if state is None or state["stage"] == TaskStage.DONE.value:
            return None
        try:
            if intent is TaskIntent.PAUSE:
                updated = self.task_state_machine.pause(self.task_id)
            elif intent is TaskIntent.RESUME:
                updated = self.task_state_machine.resume(self.task_id)
            elif intent is TaskIntent.ADVANCE:
                updated = self.task_state_machine.advance_step(self.task_id)
            else:
                target = state["rollback_stage"]
                if target is None:
                    return None
                updated = self.task_state_machine.rollback(
                    self.task_id, target, reason="откат по реплике пользователя"
                )
        except (InvalidTransitionError, UnknownTaskEvent) as exc:
            reason = str(exc)
            logger.debug(
                "Намерение %s не применено к задаче %s: %s",
                intent.value, self.task_id, reason,
            )
            return {
                "intent": intent.value,
                "applied": False,
                "reason": reason,
                # Состояние после отказа прежнее — читаем его заново, чтобы
                # уведомление называло доступные этапы, а не «куда-нибудь».
                "allowed_next": list(state.get("allowed_next") or []),
            }
        return {
            "intent": intent.value,
            "applied": True,
            "reason": None,
            "allowed_next": list(updated.get("allowed_next") or []),
        }

    # --- пайплайн (день 19), MCP-инструменты (день 17) и планировщик (день 18) ---
    @property
    def pipeline_service(self):
        """Служба пайплайнов: переданная или служба процесса (ленивый singleton)."""
        if self._pipeline_service is None:
            from ..services.pipeline_service import get_pipeline_service

            self._pipeline_service = get_pipeline_service()
        return self._pipeline_service

    @property
    def orchestration_service(self):
        """Служба оркестрации: переданная или служба процесса (ленивый singleton)."""
        if self._orchestration_service is None:
            from ..services.orchestration_service import get_orchestration_service

            self._orchestration_service = get_orchestration_service()
        return self._orchestration_service

    def apply_orchestration(self, prompt: str, payload: List[dict]) -> dict:
        """Шаг оркестрации (день 20): по реплике — флоу по серверам и его результат.

        Прогон идёт СИНХРОННО: ответ агента должен опираться на данные этого же
        хода, поэтому фоновый прогон здесь был бы бессмысленным. Данные успешного
        прогона дописываются системным блоком в готовый ``payload`` — их видит
        модель, и они же попадают в ``record["system_prompt"]``.

        Решение принимает эвристика домена (``classify_orchestration_intent``), и
        правило у неё УЗКОЕ (сохранение в базу/БД/sqlite или явное упоминание
        оркестрации): реплика дня 19 «найди …, сделай сводку и сохрани в файл»
        обязана остаться пайплайном — её контракт закреплён тестом, а пайплайн
        умеет писать только файл. Оркестрация — путь для запросов, которые
        затрагивают несколько серверов сразу.
        """
        empty = {
            "detected": False, "run_id": None, "status": "", "message": "",
            "plan_source": "", "servers_used": [], "tools_used": [], "steps": [],
            "count": 0, "failed_at_step": None, "error": None,
            "total_duration_ms": 0, "used_in_prompt": False, "added_tokens": 0,
        }
        intent = classify_orchestration_intent(prompt)
        if intent is None:
            return empty
        try:
            report = self.orchestration_service.start_run(
                intent.query, plan=None, initial_args=intent.arguments,
                background=False,
            )
        except Exception as exc:  # noqa: BLE001 — сбой прогона не роняет ход
            logger.error("Оркестрация по реплике не удалась: %s", exc)
            return {**empty, "detected": True, "status": "failed", "error": str(exc)}
        # Признак «реплика распознана» дописывается до рендера блока: у отчёта
        # прогона его нет (прогон не знает, почему его запустили), а блок собирается
        # только для распознанной реплики.
        block = render_orchestration_block({**report, "detected": True})
        added = 0
        if block:
            self._append_system_block(payload, block)
            added = self.count_tokens(block)
        return {
            **report,
            "detected": True,
            "used_in_prompt": bool(block),
            "added_tokens": added,
            "tools_used": [step["tool_name"] for step in report.get("steps", [])],
        }

    def apply_pipeline(self, prompt: str, payload: List[dict]) -> dict:
        """Шаг пайплайна (день 19): по реплике — прогон и его результат в промпт.

        Пайплайн запускается СИНХРОННО: ответ агента должен опираться на данные
        этого же хода, поэтому ждать фоновый прогон было бы бессмысленно. Данные
        успешного прогона дописываются системным блоком в готовый ``payload`` —
        их видит модель, и они же попадают в ``record["system_prompt"]``.

        Решение принимает эвристика домена (``classify_pipeline_intent``), а не
        модель: прогон оставляет побочные эффекты (файл в ``output/`` и запись в
        журнале запусков), поэтому выполняется только по явным ключевым словам
        всех трёх действий — «найди», «сводка», «сохрани в файл».
        """
        empty = _empty_pipeline_report()
        intent = classify_pipeline_intent(prompt)
        if intent is None:
            return empty
        report = self.pipeline_service.start_pipeline(
            intent.pipeline, intent.arguments, background=False
        )
        # Признак «реплика распознана» дописывается до рендера блока: у отчёта
        # прогона его нет (прогон не знает, почему его запустили), а блок собирается
        # только для распознанной реплики.
        block = render_pipeline_block({**report, "detected": True})
        added = 0
        if block:
            self._append_system_block(payload, block)
            added = self.count_tokens(block)
        return {**report, "detected": True, "used_in_prompt": bool(block),
                "added_tokens": added}

    def apply_mcp_tool(self, prompt: str, payload: List[dict]) -> dict:
        """Шаг MCP (день 17) и планировщика (день 18): по реплике — вызов и данные в промпт.

        Возвращает отчёт для ответа API: был ли инструмент вызван, какой именно, с
        какими аргументами, чем закончилось и сколько токенов добавили блоки. Данные
        успешного вызова дописываются системным блоком в готовый ``payload`` — их
        видит модель, и они же попадают в ``record["system_prompt"]``.

        Инструменты планировщика (``schedule_reminder``, ``collect_data``,
        ``generate_summary``) идут тем же путём, но добавляют второй блок: он
        сообщает модели, что фоновая задача УЖЕ зарегистрирована, — иначе модель
        отвечает «я не умею планировать». Отчёт об этом — ``schedule`` в
        возвращаемом словаре (``record["schedule"]``).

        Решение принимает эвристика домена (``classify_tool_call``), а не модель:
        вызов инструмента — действие с побочным эффектом (наружу уходит HTTP-запрос,
        а у планировщика — ещё и фоновая задача), и в этом дне он выполняется только
        по явным ключевым словам реплики. Неудача вызова ход не роняет: отказ или
        сбой видны в отчёте, ответ агента строится без внешних данных.
        """
        runner = MCPToolRunner(self._mcp_registry)
        outcome = runner.call_for_prompt(prompt)
        block = render_mcp_tool_block(outcome)
        scheduler_block = render_scheduler_block(outcome)
        added = 0
        if block:
            self._append_system_block(payload, block)
            added = self.count_tokens(block)
        if scheduler_block:
            self._append_system_block(payload, scheduler_block)
            added += self.count_tokens(scheduler_block)
        return {
            **outcome.to_dict(),
            "used_in_prompt": bool(block or scheduler_block),
            "added_tokens": added,
            "schedule": render_schedule_report(outcome),
        }

    @staticmethod
    def _append_system_block(payload: List[dict], block: str) -> None:
        """Дописывает блок в системное сообщение запроса (создаёт его, если нужно).

        Системное сообщение ровно одно (``_system_message``), но payload может
        прийти и без него — например, при пустом системном промпте. Тогда блок
        становится первым сообщением: порядок «system → остальное» — требование
        провайдера, а не деталь реализации.
        """
        for item in payload:
            if item.get("role") == "system":
                item["content"] = "\n\n".join(filter(None, [item.get("content"), block]))
                return
        payload.insert(0, {"role": "system", "content": block})

    # --- инварианты (день 14) ---
    def invariant_rows(self, active_only: bool = True) -> List[dict]:
        """Инварианты проекта из БД (по умолчанию — только активные).

        Список читается на каждый запрос, а не кэшируется: включённое правило
        начинает действовать со следующего хода, выключенное — перестаёт.
        """
        return self.invariants.get_all_invariants(active_only=active_only)

    def invariants_block(self) -> str:
        """Блок «Ты обязан соблюдать…» для системного промпта (``""`` — правил нет)."""
        return render_invariants_block(self.invariant_rows())

    @property
    def invariant_checker(self) -> InvariantChecker:
        """Контролёр инвариантов на фабрике сессий агента и его клиенте DeepSeek.

        Создаётся НА ВЫЗОВ, а не в ``__init__``: ``client_factory`` привязывается
        к текущему атрибуту ``_make_client``, поэтому подмена клиента в тестах
        (``monkeypatch.setattr(agent, "_make_client", ...)``) видна контролёру.
        """
        return InvariantChecker(
            session_factory=self._session_factory, client_factory=self._make_client,
        )

    def check_invariants(self, text: str,
                         use_llm: Optional[bool] = None) -> InvariantCheckResult:
        """Проверка текста на нарушение активных инвариантов проекта.

        ``use_llm=None`` — решение принимает конфигурация дня
        (``config.INVARIANT_LLM_CHECK``): проверка запроса вызывается с явным
        ``False``, чтобы не платить за вызов, когда нарушение видно правилами.
        """
        return self.invariant_checker.check(text, use_llm=use_llm)

    def _refuse_by_invariants(self, record: dict, prompt: str,
                              check: InvariantCheckResult,
                              started: float) -> dict:
        """Отказ по hard-инварианту: ответ-объяснение вместо вызова DeepSeek.

        Ход состоялся как диалог (реплика пользователя и отказ сохраняются в
        краткосрочный слой), но токенов не потрачено: DeepSeek не вызывается.
        Остальные поля записи (``profile``, ``task_state``, ``system_prompt``,
        ``memory``) заполнены вызывающим кодом до проверки, поэтому отказ в API
        выглядит так же, как обычный ответ. ``duration_sec`` измеряет саму
        проверку: без него поле осталось бы ``None``, а клиенты ждут число.
        """
        refusal = render_violation_refusal(check.violation_dicts())
        self.short_term_messages.append({"role": "assistant", "content": refusal})
        self._save_turn(prompt, refusal)
        record["status"] = "ok"
        record["response"] = refusal
        record["duration_sec"] = round(time.perf_counter() - started, 3)
        record["invariants"] = check.to_dict()
        record["context"] = {
            "max_model_tokens": self.context_limit_tokens,
            "warning": None,
            "state": self.state_value(),
            "strategy": self.strategy,
        }
        logger.debug(
            "Запрос агента %s отклонён инвариантами: %s",
            self.agent_id, ", ".join(item.name for item in check.violations),
        )
        return record

    # --- вызов DeepSeek ---
    def _make_client(self):
        """Создаёт OpenAI-совместимый клиент DeepSeek.

        Ключ резолвится в момент вызова (не при создании агента). Без ключа
        кидаем AgentError ДО сетевого вызова — поведение проверяемо офлайн.
        """
        api_key = config.resolve_api_key()
        if not api_key:
            raise AgentError(
                "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day20/.env "
                "или в переменной окружения и перезапустите запрос."
            )
        return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)

    @staticmethod
    def _system_text(payload) -> str:
        """Текст системного сообщения из готового payload (или пустая строка).

        Системное сообщение собирается ровно одно (см. ``_system_message``),
        поэтому берём первое и оно же единственное.
        """
        for item in payload or []:
            if item.get("role") == "system":
                return item.get("content", "")
        return ""

    def _system_message(self, summary_text: str = "",
                        facts: Optional[Dict[str, str]] = None,
                        memory: Optional[MemoryContext] = None) -> List[dict]:
        """Системное сообщение агента: профиль + роль + инварианты + блоки памяти/задачи.

        Порядок блоков: ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ (персонализация дня 12) →
        системный промпт агента → ИНВАРИАНТЫ (день 14) → рабочая память →
        долговременная память → конспект → факты → СОСТОЯНИЕ ЗАДАЧИ (день 13).
        Профиль идёт первым: это постоянная инструкция пользователя, одинаковая
        во всех запросах, и она не должна теряться за блоками памяти.
        Инварианты — сразу после роли агента: это правила проекта, которые
        сильнее любых пожеланий в диалоге и должны читаться до фактов и памяти.
        Состояние задачи идёт последним: это КОНКРЕТНАЯ точка, с которой надо
        продолжать, и она должна читаться сразу после общей рамки. Блок задачи
        (день 15) называет допустимые следующие этапы и запрещает пробовать
        недопустимые — модель видит ту же границу, что и правила допуска. Все
        блоки вкладываются в существующее system-сообщение, а не добавляются
        отдельными: так поведение не зависит от того, как провайдер обрабатывает
        несколько system-сообщений подряд.
        """
        parts = []
        profile_block = self.profile.prompt.text
        if profile_block:
            parts.append(profile_block)
        if self.config.system_prompt:
            parts.append(self.config.system_prompt)
        invariant_block = self.invariants_block()
        if invariant_block:
            parts.append(invariant_block)
        if memory is not None:
            if memory.working_text:
                parts.append(memory.working_text)
            if memory.long_term_text:
                parts.append(memory.long_term_text)
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
        task_block = self.task_state_block()
        if task_block:
            parts.append(task_block)
        if not parts:
            return []
        return [{"role": "system", "content": "\n\n".join(parts)}]

    def _context_tokens_for(self, messages) -> int:
        """Оценка токенов контекста: системный промпт + список сообщений."""
        return self._count_messages(self._system_message() + list(messages))

    # --- сборка payload со сжатием (ядро дня 9) ---
    def build_payloads(self, prompt: str,
                       memory: Optional[MemoryContext] = None) -> PayloadPlan:
        """Строит два варианта запроса: полный («без сжатия») и сжатый.

        Полный — «что было бы без сжатия»: системный промпт с блоками памяти +
        ВСЯ история сессии + новый промпт. Сжатый — «что уходит фактически»:
        системный промпт с блоками памяти и конспектом + последние
        ``keep_last_messages`` непокрытых реплик + новый промпт. Обе оценки нужны
        для метрик экономии, поэтому считаются всегда.
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

        def to_messages(source: Sequence[ShortTermMessage]) -> List[dict]:
            return [{"role": row.role, "content": row.content} for row in source]

        tail = [{"role": "user", "content": prompt}]
        full_payload = self._system_message(memory=memory) + to_messages(rows) + tail
        sent_payload = (
            self._system_message(summary_text, memory=memory)
            + to_messages(keep_rows) + tail
        )

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
            short_term_tokens=self._count_messages(to_messages(keep_rows)),
        )

    # --- подготовка контекста по стратегии (ядро дня 11) ---
    def prepare_context(self, prompt: str) -> dict:
        """Формирует список сообщений для LLM в зависимости от стратегии.

        Возвращает словарь с ``payload`` (готовый список сообщений) и
        метаданными для метрик (оценки токенов по слоям, режим, факты к
        сохранению). Сама генерация (`generate`) дальше делает аварийную обрезку,
        вызов API и сохранение метрик; здесь — только сборка контекста. Стратегия
        ``summary`` сохраняет поведение дня 9 (сжатие конспектом).
        """
        memory = self.build_memory_context(prompt)
        strategy = self.strategy
        if strategy == Strategy.SLIDING_WINDOW.value:
            return self._prepare_sliding_window(prompt, memory)
        if strategy == Strategy.STICKY_FACTS.value:
            return self._prepare_sticky_facts(prompt, memory)
        if strategy == Strategy.BRANCHING.value:
            return self._prepare_branching(prompt, memory)
        # summary — сжатие истории (день 9), стратегия по умолчанию.
        return self._prepare_summary(prompt, memory)

    def _prepare_sliding_window(self, prompt: str,
                                memory: Optional[MemoryContext] = None) -> dict:
        """Скользящее окно: system + последние N реплик + новый промпт."""
        memory = memory or self.build_memory_context(prompt)
        rows = self._fetch_rows()
        recent = rows[-self.window_size:]
        tail = [{"role": "user", "content": prompt}]
        body = [{"role": r.role, "content": r.content} for r in recent]
        full_body = [{"role": r.role, "content": r.content} for r in rows]
        payload = self._system_message(memory=memory) + body + tail
        full_payload = self._system_message(memory=memory) + full_body + tail
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
            "memory": memory,
            "short_term_tokens": self._count_messages(body),
        }

    def _prepare_sticky_facts(self, prompt: str,
                              memory: Optional[MemoryContext] = None) -> dict:
        """Липкие факты: system (+память и факты) + последние N реплик + промпт.

        Факты извлекаются из новой реплики пользователя (эвристика
        `extract_facts`), сливаются с уже сохранёнными и попадают в payload.
        Новые факты сохраняются в таблицу `facts` ПОСЛЕ успешного хода (в
        `generate`), чтобы неудачный запрос не мутировал память фактов.
        """
        memory = memory or self.build_memory_context(prompt)
        existing = self._current_facts()
        new_facts = extract_facts(prompt)
        merged = dict(existing)
        merged.update(new_facts)
        rows = self._fetch_rows()
        recent = rows[-self.window_size:]
        tail = [{"role": "user", "content": prompt}]
        body = [{"role": r.role, "content": r.content} for r in recent]
        full_body = [{"role": r.role, "content": r.content} for r in rows]
        payload = self._system_message(facts=merged, memory=memory) + body + tail
        full_payload = (
            self._system_message(facts=merged, memory=memory) + full_body + tail
        )
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
            "memory": memory,
            "short_term_tokens": self._count_messages(body),
        }

    def _prepare_branching(self, prompt: str,
                           memory: Optional[MemoryContext] = None) -> dict:
        """Ветвление: system + вся история активной ветки + новый промпт."""
        memory = memory or self.build_memory_context(prompt)
        rows = self._fetch_rows()
        tail = [{"role": "user", "content": prompt}]
        body = [{"role": r.role, "content": r.content} for r in rows]
        payload = self._system_message(memory=memory) + body + tail
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
            "memory": memory,
            "short_term_tokens": self._count_messages(body),
        }

    def _prepare_summary(self, prompt: str,
                         memory: Optional[MemoryContext] = None) -> dict:
        """Сжатие (день 9): конспект + последние непокрытые реплики + промпт."""
        memory = memory or self.build_memory_context(prompt)
        plan = self.build_payloads(prompt, memory=memory)
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
            "memory": memory,
            "short_term_tokens": plan.short_term_tokens,
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
        """Снимок краткосрочного слоя сессии в виде списка {role, content}."""
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self.short_term_messages
        ]

    def _replace_history(self, snapshot: Sequence[dict]) -> None:
        """Заменяет краткосрочный слой текущей сессии заданным снимком.

        Используется при переключении/создании ветки: таблица
        ``short_term_messages`` отражает активную ветку, а остальные ветки
        сохраняются в ``checkpoints``.
        """
        now = datetime.now(timezone.utc)
        with self._session() as session:
            session.query(ShortTermMessage).filter(
                ShortTermMessage.agent_id == self.agent_id,
                ShortTermMessage.session_id == self.session_id,
            ).delete()
            for item in snapshot:
                session.add(ShortTermMessage(
                    agent_id=self.agent_id, session_id=self.session_id,
                    role=item["role"], content=item["content"], created_at=now,
                ))
            session.commit()
        self.short_term_messages = [
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
           окно / липкие факты / ветвление / сжатие-конспект) и блоки рабочей и
           долговременной памяти;
        2) аварийная обрезка, если даже собранный запрос не влезает в лимит
           модели (реплики из БД при этом не удаляются);
        3) вызов API; при успехе метрики хода сохраняются в ``token_usage`` той
           же транзакцией, что и пара реплик;
        4) после успешного хода — действие стратегии: сжатие конспекта
           (summary), сохранение фактов (sticky_facts) или снимок ветки
           (branching).

        Отчёты о контролируемых переходах (день 15) — в ``record``:
        ``task_intent`` — что сделала реплика пользователя (``applied`` и
        ``reason``, если переход отклонён), ``task_proposal`` — какое предложение
        модели было отклонено и почему; в ответе отклонённое предложение
        заменяется отказом (``🚧``), а неприменённое намерение — уведомлением
        (``⚠️``).

        Шаг пайплайна (день 19) — в ``record["pipeline"]``: распознана ли в реплике
        композиция инструментов, чем закончился прогон (``status``,
        ``failed_at_step``, ``message``, ``error``), сколько шагов записано и ушёл
        ли результат в системный промпт (``used_in_prompt``, ``added_tokens``).
        ``None`` — пайплайн не запускался.

        Шаг MCP (день 17) — в ``record["mcp"]``: какой инструмент распознан в
        реплике, с какими аргументами вызван, чем закончился вызов
        (``state``/``reason_code``/``error``), и ушли ли его данные в системный
        промпт (``used_in_prompt``, ``added_tokens``). Реплика, запустившая
        пайплайн, одиночным вызовом не разбирается, поэтому ``mcp`` в этом случае
        остаётся ``None``.

        Шаг планировщика (день 18) — в ``record["schedule"]``: зарегистрирована ли
        фоновая задача (``registered``), какой инструмент её поставил, что за
        задача и чем она ответила (``message``, ``summary``). ``None`` — фоновой
        задачи не появилось: реплика не распознана, вызов отклонён или сорвался.
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
            "memory": None,
            "profile": None,
            "task_state": None,
            "task_intent": None,
            "task_proposal": None,
            "invariants": None,
            "orchestration": None,
            "pipeline": None,
            "mcp": None,
            "schedule": None,
            "system_prompt": "",
            "duration_sec": None,
            "timestamp": timestamp,
        }

        # 1) пользовательский ход — в память (в БД — только при успехе).
        self.short_term_messages.append({"role": "user", "content": prompt})

        # Состояние задачи (день 13): реплика может его изменить («пауза»,
        # «продолжи», «подтверждаю», «вернись на предыдущий этап»). Переход
        # делается ДО сборки контекста, поэтому системный промпт этого же
        # запроса уже описывает новое состояние. Отчёт о попытке (день 15)
        # нужен, чтобы отклонённый переход стал виден пользователю: раньше
        # «нажал — и ничего» ничем не отличалось от «перехода не было».
        record["task_intent"] = self.apply_task_intent(prompt)

        ctx = self.prepare_context(prompt)
        payload = ctx["payload"]
        sent_tokens = ctx["context_tokens"]
        memory_ctx = ctx["memory"]
        trimmed = 0
        warning = None

        # Персонализация (день 12): отчёт о применённом профиле и итоговый
        # системный промпт считаются ДО вызова API — они видны и при 502.
        record["profile"] = self.profile_report()
        # Состояние задачи (день 13): то же — считается ДО вызова API.
        record["task_state"] = self.task_state()
        record["system_prompt"] = self._system_text(payload)

        # Отчёт по слоям считается ДО вызова API: он нужен и при ошибке
        # генерации (проверяемо без ключа, слои уже прочитаны из БД).
        record["memory"] = {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "keywords": memory_ctx.keywords,
            "short_term_tokens": ctx["short_term_tokens"],
            "working_tokens": memory_ctx.working_tokens,
            "long_term_tokens": memory_ctx.long_term_tokens,
            "total_tokens": (
                ctx["short_term_tokens"] + memory_ctx.working_tokens
                + memory_ctx.long_term_tokens
            ),
            "layers": [
                {
                    "layer": "short_term",
                    "used": ctx["short_term_tokens"] > 0,
                    "entries": ctx["kept_messages"],
                    "tokens": ctx["short_term_tokens"],
                    "details": f"сессия {self.session_id}, режим {ctx['mode']}",
                },
                {
                    "layer": "working",
                    "used": bool(memory_ctx.working),
                    "entries": len(memory_ctx.working),
                    "tokens": memory_ctx.working_tokens,
                    "details": f"задача {self.task_id}",
                },
                {
                    "layer": "long_term",
                    "used": bool(memory_ctx.long_term),
                    "entries": len(memory_ctx.long_term),
                    "tokens": memory_ctx.long_term_tokens,
                    "details": (
                        "ключевые слова: " + ", ".join(memory_ctx.keywords)
                        if memory_ctx.keywords else "по уверенности"
                    ),
                },
            ],
        }

        # Инварианты (день 14): ЗАПРОС проверяется детерминированными правилами ДО
        # вызова DeepSeek — нарушение hard-инварианта останавливает ход, не тратя
        # токены. LLM для запроса не зовём: очевидное ловят правила, а семантику
        # видно по ответу (см. пост-проверку ниже).
        started = time.perf_counter()
        request_check = self.check_invariants(prompt, use_llm=False)
        record["invariants"] = request_check.to_dict()
        if request_check.verdict == VERDICT_REFUSAL:
            return self._refuse_by_invariants(record, prompt, request_check, started)

        # Пайплайн (день 19): реплика вида «найди …, сделай сводку и сохрани в
        # файл» запускает декларативный прогон из нескольких инструментов, и его
        # результат уходит в системный промпт этого же запроса. Шаг стоит ПОСЛЕ
        # проверки запроса инвариантами (она бесплатна и локальна, а прогон —
        # действие с побочными эффектами: HTTP наружу и файл на диске) и ДО
        # контроля лимита, потому что добавленный блок обязан в этот лимит войти.
        orchestration_report = self.apply_orchestration(prompt, payload)
        record["orchestration"] = orchestration_report
        if orchestration_report["used_in_prompt"]:
            sent_tokens += orchestration_report["added_tokens"]
            record["system_prompt"] = self._system_text(payload)

        # Пайплайн (день 19): реплика вида «найди ..., сделай сводку и сохрани в
        # файл» запускает декларативный прогон. Реплика, распознанная как
        # оркестрация, дальше не разбирается: один запрос — один автоматизм, иначе
        # одна реплика запустила бы два прогона с побочными эффектами.
        pipeline_report = (_empty_pipeline_report()
                           if orchestration_report["detected"]
                           else self.apply_pipeline(prompt, payload))
        record["pipeline"] = pipeline_report
        if pipeline_report["used_in_prompt"]:
            sent_tokens += pipeline_report["added_tokens"]
            record["system_prompt"] = self._system_text(payload)

        # MCP-инструмент (день 17): агент сам решает по ключевым словам реплики,
        # нужен ли вызов, вызывает инструмент и кладёт данные в системный промпт
        # этого же запроса. Как и шаг MCP, он идёт до контроля лимита. Реплика,
        # распознанная как пайплайн или оркестрация, одиночным вызовом больше не
        # разбирается: один и тот же запрос не должен запускать инструменты двумя
        # путями.
        mcp_report = {}
        if not pipeline_report["detected"] and not orchestration_report["detected"]:
            mcp_report = self.apply_mcp_tool(prompt, payload)
            record["mcp"] = mcp_report
        # Планировщик (день 18): зарегистрирована ли фоновая задача по реплике.
        # Отчёт берётся из того же шага: `schedule` — часть его результата, поэтому
        # вызов инструмента и решение о том, что показать пользователю, не могут
        # разойтись. Он тоже виден и при 502 (задача уже стоит).
        if mcp_report:
            record["schedule"] = mcp_report["schedule"]
            if mcp_report["used_in_prompt"]:
                sent_tokens += mcp_report["added_tokens"]
                record["system_prompt"] = self._system_text(payload)

        # 2) контроль лимита: стратегия уже сократила запрос, но одно огромное
        #    сообщение всё ещё может его переполнить.
        if sent_tokens > limit:
            trimmed_result = self._emergency_trim(payload, limit)
            if trimmed_result is None:
                self.short_term_messages.pop()  # откат: БД не менялась
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
            self.short_term_messages.pop()  # откат: сбой ДО вызова сети
            record["error"] = str(exc)
        except Exception as exc:  # сеть/API DeepSeek/неожиданное: не валим сервер
            self.short_term_messages.pop()  # откат: ответа не было — история не меняется
            record["error"] = f"Сбой запроса к DeepSeek: {exc}"
        else:
            choice = response.choices[0] if response.choices else None
            answer = ""
            if choice is not None and choice.message is not None:
                answer = choice.message.content or ""

            # Контролируемые переходы (день 15): ответ модели проверяется на
            # предложение перейти в другой этап. Недопустимое предложение не
            # выполняется и не остаётся в ответе — вместо него уходит отказ с
            # причиной и подсказкой. Допустимое предложение перехода не делает:
            # этапы двигает пользователь (кнопкой или репликой-намерением).
            intent_report = record["task_intent"]
            intent_note = ""
            if intent_report and not intent_report["applied"]:
                intent_note = intent_refusal_notice(
                    intent_report["intent"], intent_report["reason"],
                    intent_report["allowed_next"],
                )

            state = record["task_state"]
            proposal = detect_stage_proposal(answer)
            if (
                proposal is not None
                and state is not None
                and proposal.value == state["stage"]
            ):
                # Модель говорит о ТЕКУЩЕМ этапе («приступаю к реализации», когда
                # задача уже на реализации) — это описание работы, а не переход:
                # наказывать за него отказом значило бы ломать нормальный ответ.
                proposal = None
            refusal = None
            if proposal is not None and state is not None:
                context = guard_context(state)
                if not is_transition_allowed(state["stage"], proposal, context):
                    message, hint = transition_explanation(
                        state["stage"], proposal, context
                    )
                    refusal = (
                        f"🚧 Ответ предлагает переход в {proposal.value}, но это "
                        f"недопустимо. {message} {hint}"
                    )
                    record["task_proposal"] = {
                        "proposed": proposal.value,
                        "allowed_next": list(state["allowed_next"]),
                        "reason": message,
                        "hint": hint,
                    }

            if refusal is not None:
                answer = (f"{intent_note}\n\n" if intent_note else "") + refusal
            elif intent_note:
                answer = intent_note + "\n\n" + answer

            # Инварианты (день 14): ответ модели проверяется ПЕРЕД сохранением и
            # выдачей — hard-нарушение заменяет ответ отказом, soft добавляет
            # предупреждение в начало ответа. Здесь работает LLM-слой: очевидные
            # нарушения уже отсеяны правилами, поэтому вызов идёт только когда
            # правила молчат. Вердикты запроса и ответа объединяются (худший
            # побеждает), чтобы предупреждение из запроса не потерялось.
            answer_check = self.check_invariants(answer)
            invariants_check = request_check.merged_with(answer_check)
            record["invariants"] = invariants_check.to_dict()
            if invariants_check.verdict == VERDICT_REFUSAL:
                answer = render_violation_refusal(invariants_check.violation_dicts())
            elif invariants_check.verdict == VERDICT_WARNING:
                answer = (
                    render_violation_warning(invariants_check.violation_dicts())
                    + "\n\n" + answer
                )

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
                # Фактический расход по слоям памяти (день 11).
                "short_term_tokens": ctx["short_term_tokens"],
                "working_tokens": memory_ctx.working_tokens,
                "long_term_tokens": memory_ctx.long_term_tokens,
            }
            record["token_metrics"] = token_metrics

            # 4) ход ассистента + атомарное сохранение пары и метрик в БД.
            self.short_term_messages.append({"role": "assistant", "content": answer})
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

        Ограничение: инварианты здесь не проверяются (ни запрос, ни ответы).
        Это служебное сравнение режимов контекста, а не ход диалога: оно не
        сохраняет реплики и не должно ни отказывать, ни предупреждать.
        """
        plan = self.build_payloads(prompt, memory=self.build_memory_context(prompt))
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
