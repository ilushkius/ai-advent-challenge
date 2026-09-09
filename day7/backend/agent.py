"""Класс Agent дня 7 — агент с контекстной памятью диалога.

Агент — самодостаточная сущность: конфигурация (модель, температура, системный
промпт, лимит токенов) + полная история диалога. История живёт в двух местах:

- ``self.messages`` — копия в памяти в LLM-формате
  ``[{"role": "user"/"assistant", "content": ...}, ...]`` (системный промпт
  сюда не входит — он конфигурация, D3);
- таблица ``messages`` в SQLite — источник правды: каждая реплика сохранена с
  ролью, текстом и временной меткой и переживает рестарт бэкенда.

При создании агент загружает свою историю из БД (``load_history()``), поэтому
новый агент стартует с пустым диалогом, а восстановленный после рестарта — с
полным. ``generate(prompt)`` добавляет сообщение пользователя в историю,
отправляет в DeepSeek ВСЮ историю, добавляет ответ ассистента и сохраняет пару
записей одной транзакцией; при сбое API история не изменяется (D4).

Фабрики для офлайн-проверок: клиент создаётся ``_make_client()`` (подменяется
фейком), фабрика сессий БД передаётся через ``session_factory``.
"""
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import config, database
from .database import Message
from .models import AgentConfig


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

    def _save_turn(self, user_content: str, assistant_content: str) -> None:
        """Сохраняет пару реплик одной транзакцией (атомарно, D4).

        Если сервер упадёт между двумя отдельными commit'ами, в истории осталась
        бы реплика user без ответа. Одна транзакция этого исключает.
        """
        now = datetime.now(timezone.utc)
        with self._session() as session:
            session.add_all([
                Message(
                    agent_id=self.agent_id, role="user", content=user_content,
                    timestamp=now,
                ),
                Message(
                    agent_id=self.agent_id, role="assistant",
                    content=assistant_content, timestamp=now,
                ),
            ])
            session.commit()

    def clear_history(self) -> int:
        """Удаляет все сообщения агента из БД и памяти. Возвращает их число."""
        with self._session() as session:
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
                "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day7/.env "
                "или в переменной окружения и перезапустите запрос."
            )
        import openai  # локальный импорт: модуль нужен только при реальном вызове
        return openai.OpenAI(
            base_url=config.DEEPSEEK_BASE_URL,
            api_key=api_key,
            timeout=config.REQUEST_TIMEOUT,
        )

    def generate(self, prompt: str) -> dict:
        """Отправляет запрос в DeepSeek с полным контекстом диалога.

        1) user-сообщение добавляется в self.messages;
        2) в API уходит ВСЯ история (системный промпт — первым, если задан);
        3) при успехе ответ ассистента добавляется в историю, и пара реплик
           сохраняется в БД одной транзакцией;
        4) при сбое user-сообщение откатывается, БД не меняется — история не
           портится (запись со status="error" без traceback).
        """
        timestamp = datetime.now(timezone.utc)
        record: dict = {
            "agent_id": self.agent_id,
            "status": "error",
            "prompt": prompt,
            "response": None,
            "error": None,
            "model": self.config.model,
            "finish_reason": None,
            "usage": None,
            "duration_sec": None,
            "timestamp": timestamp,
        }

        # 1) пользовательский ход — в историю диалога.
        self.messages.append({"role": "user", "content": prompt})

        # 2) payload: системный промпт (если задан) + вся история диалога.
        payload: List[dict] = []
        if self.config.system_prompt:
            payload.append({"role": "system", "content": self.config.system_prompt})
        payload.extend(self.messages)

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
            usage = getattr(response, "usage", None)
            if usage is not None:
                record["usage"] = {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
            # 3) ход ассистента + атомарное сохранение пары в БД.
            self.messages.append({"role": "assistant", "content": answer})
            self._save_turn(prompt, answer)
        finally:
            record["duration_sec"] = round(time.perf_counter() - started, 3)

        return record

