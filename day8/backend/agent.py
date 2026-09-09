"""Класс Agent дня 8 — агент с контекстной памятью и контролем токенов.

Агент — самодостаточная сущность: конфигурация (модель, температура, системный
промпт, лимит токенов) + полная история диалога. История живёт в двух местах:

- ``self.messages`` — копия в памяти в LLM-формате
  ``[{"role": "user"/"assistant", "content": ...}, ...]`` (системный промпт
  сюда не входит — он конфигурация);
- таблица ``messages`` в SQLite — источник правды: каждая реплика сохранена с
  ролью, текстом и временной меткой и переживает рестарт бэкенда.

День 8 добавляет подсчёт токенов (tiktoken, кодировка ``cl100k_base`` —
приближение к токенизатору DeepSeek): ``count_tokens(text)`` и метрики каждого
хода ``generate(prompt)``. Перед вызовом DeepSeek агент оценивает токены
запроса (история + новое сообщение) и, если оценка превышает лимит модели
(``config.MODEL_TOKEN_LIMITS``), автоматически удаляет самые старые ЦЕЛЫЕ пары
сообщений — из памяти и из БД — пока контекст не влезет, и возвращает
предупреждение об обрезке. Метрики успешного хода (prompt/completion/total/
history/response токены + стоимость) сохраняются в таблицу ``token_usage`` той
же транзакцией, что и пара реплик.

Фабрики для офлайн-проверок: клиент создаётся ``_make_client()`` (подменяется
фейком), фабрика сессий БД передаётся через ``session_factory``.
"""
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import config, database
from .database import Message, TokenUsage
from .models import AgentConfig

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


class Agent:
    """Один LLM-агент: конфигурация + вызов DeepSeek + диалог в SQLite."""

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
        # История диалога в памяти: [{"role": ..., "content": ...}, ...].
        self.messages: List[Dict[str, str]] = []
        # Старт приложения/создание агента: загружаем историю из БД (для нового
        # агента записей ещё нет — история остаётся пустой).
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

    # --- подсчёт токенов (требование дня 8) ---
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
        """Лимит контекста модели агента (демо-значения из config, см. D5)."""
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

    # --- история: загрузка / сохранение / очистка (требование задачи) ---
    def load_history(self) -> None:
        """Загружает историю диалога из БД в self.messages."""
        self.messages = [
            {"role": row.role, "content": row.content} for row in self._fetch_rows()
        ]

    def history_rows(self) -> List[Dict]:
        """Сообщения диалога с метаданными (для API): id, role, content, время."""
        rows = self._fetch_rows()
        return [
            {
                "id": row.id,
                "agent_id": row.agent_id,
                "role": row.role,
                "content": row.content,
                "timestamp": row.timestamp,
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
        """Сохраняет пару реплик + метрики токенов одной транзакцией (D4).

        Если сервер упадёт между отдельными commit'ами, в истории осталась бы
        реплика user без ответа. Одна транзакция исключает и это, и расхождение
        диалога с записью ``token_usage``: ``metrics`` (ключи — колонки
        token_usage: prompt_tokens, completion_tokens, total_tokens,
        history_tokens, response_tokens, cost) кладётся той же транзакцией.
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
            ))
        with self._session() as session:
            session.add_all(rows)
            session.commit()

    def clear_history(self) -> int:
        """Удаляет все сообщения и метрики токенов агента из БД и памяти.

        Возвращает число удалённых сообщений. Метрики ``token_usage`` удаляются
        вместе с историей: «новый диалог» начинает счёт токенов с нуля.
        """
        with self._session() as session:
            session.query(TokenUsage).filter(
                TokenUsage.agent_id == self.agent_id
            ).delete()
            deleted = (
                session.query(Message)
                .filter(Message.agent_id == self.agent_id)
                .delete()
            )
            session.commit()
        self.messages = []
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
                "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day8/.env "
                "или в переменной окружения и перезапустите запрос."
            )
        import openai  # локальный импорт: модуль нужен только при реальном вызове
        return openai.OpenAI(
            base_url=config.DEEPSEEK_BASE_URL,
            api_key=api_key,
            timeout=config.REQUEST_TIMEOUT,
        )

    def _system_message(self) -> List[dict]:
        """Системное сообщение агента (пустой список, если промпт не задан)."""
        if self.config.system_prompt:
            return [{"role": "system", "content": self.config.system_prompt}]
        return []

    def _context_tokens_for(self, messages) -> int:
        """Оценка токенов контекста: системный промпт + список сообщений."""
        return self._count_messages(self._system_message() + list(messages))

    def generate(self, prompt: str) -> dict:
        """Отправляет запрос в DeepSeek с контролем токенов (день 8).

        1) user-сообщение добавляется в self.messages (в память);
        2) оцениваются токены запроса (системный промпт + история + новое
           сообщение); при превышении лимита модели самые старые ЦЕЛЫЕ пары
           сообщений удаляются (память + БД) до вписывания в лимит, факт
           обрезки попадает в record["context"]["warning"];
        3) если даже без истории сообщение длиннее лимита — возвращается
           ошибка без вызова API и без изменения БД;
        4) при успехе метрики токенов (prompt/completion/total — из usage API
           при наличии, иначе оценки; history/response — оценки; cost — по
           тарифу) сохраняются в token_usage той же транзакцией, что и пара
           реплик; при сбое временное user-сообщение откатывается (status=
           "error" без traceback).
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
        history_before = self.messages[:-1]

        hist_est = self._context_tokens_for(history_before)  # системный+история
        msg_est = self.count_tokens(prompt)
        payload_est = hist_est + msg_est
        was_over_est = payload_est  # для текста предупреждения
        trimmed = 0
        over_limit = False

        # 2) контроль лимита: автообрезка самых старых ЦЕЛЫХ пар (D5).
        if payload_est > limit:
            over_limit = True
            best_keep = None
            # keep сохраняет чётность истории: с начала уходят только пары.
            for keep in range(len(history_before),
                              (len(history_before) % 2) - 1, -2):
                if self._context_tokens_for(history_before[:keep]) + msg_est \
                        <= limit:
                    best_keep = keep
                    break
            if best_keep is None:
                # Крайний случай: даже с пустой историей не влезает.
                self.messages.pop()  # откат: БД не менялась
                record["error"] = (
                    f"Сообщение длиннее лимита контекста модели ({limit} "
                    f"токенов): примерно {msg_est} токенов. Сократите "
                    "сообщение и повторите."
                )
                return record
            trimmed = len(history_before) - best_keep
            if trimmed:
                # Удаляем самые старые `trimmed` сообщений из БД (в памяти —
                # срезом ниже), сохраняя согласованность «память = БД».
                rows = self._fetch_rows()
                drop_ids = [row.id for row in rows[:trimmed]]
                with self._session() as session:
                    session.query(Message).filter(
                        Message.agent_id == self.agent_id,
                        Message.id.in_(drop_ids),
                    ).delete(synchronize_session=False)
                    session.commit()
                self.messages = self.messages[trimmed:]
                hist_est = self._context_tokens_for(self.messages[:-1])
                payload_est = hist_est + msg_est

        warning = None
        if trimmed:
            warning = (
                f"⚠️ Контекст модели переполнен: оценка запроса "
                f"{was_over_est} токенов больше лимита {limit}. Удалено "
                f"{trimmed} самых старых сообщений, запрос отправлен с "
                "сокращённой историей."
            )

        payload = self._system_message() + self.messages

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

            # 3) метрики токенов: фактические из usage API (если есть),
            #    иначе локальные оценки tiktoken (D3).
            response_est = self.count_tokens(answer)
            prompt_used = payload_est
            completion_used = response_est
            total_used = payload_est + response_est
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

            context_after = self._context_tokens_for(self.messages)
            token_metrics = {
                "prompt_tokens": prompt_used,
                "completion_tokens": completion_used,
                "total_tokens": total_used,
                "history_tokens": hist_est,
                "response_tokens": response_est,
                "cost": self._estimate_cost(prompt_used, completion_used),
            }
            record["token_metrics"] = token_metrics
            record["context"] = {
                "max_model_tokens": limit,
                "payload_tokens": prompt_used,
                "context_tokens": context_after,
                "remaining_tokens": max(0, limit - context_after),
                "over_limit": over_limit,
                "trimmed_messages": trimmed,
                "warning": warning,
            }

            # 4) ход ассистента + атомарное сохранение пары и метрик в БД.
            self.messages.append({"role": "assistant", "content": answer})
            self._save_turn(prompt, answer, metrics=token_metrics)
        finally:
            record["duration_sec"] = round(time.perf_counter() - started, 3)

        return record

