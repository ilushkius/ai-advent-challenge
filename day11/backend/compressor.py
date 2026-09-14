"""Сжатие истории (день 9): превращение старых реплик в конспект.

Логика модуля — три шага, каждый проверяем отдельно:

1. **что сжимать** — ``ContextCompressor.uncovered_rows()`` берёт реплики,
   которые ещё не покрыты последним конспектом (сравнение с watermark
   ``covered_to_message_id``), а решение «пора ли» принимает чистая функция
   ``plan_compression`` из ``context_policy.py``;
2. **как сжимать** — ``build_summary_prompt`` собирает запрос к DeepSeek:
   прошлый конспект (если есть) + новая порция реплик одним текстом. Модель
   конспектирования всегда ``config.SUMMARY_MODEL`` при низкой температуре:
   конспект — извлечение фактов, а не творчество;
3. **куда сохранять** — результат пишется строкой в таблицу ``summaries``
   (append-only, текущий конспект = последняя строка). Краткосрочный слой
   (``short_term_messages``) при этом НЕ удаляется: конспект лишь заменяет
   старые реплики сессии в запросе.

Ошибка суммаризации не должна ломать диалог: ``CompressionError`` ловит
вызывающий код (``Agent.generate``), ход всё равно уходит в модель, а в
состоянии FSM выставляется ERROR с повтором на следующем ходу.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from . import config
from .context_policy import CompressionPlan, CompressionPolicy, plan_compression
from .database import ShortTermMessage, Summary

# Инструкция для модели-конспектёра. Пишем по-русски и явно запрещаем
# домысливать: конспект подставляется в диалог вместо фактов, и галлюцинация
# здесь дороже, чем потеря детали.
SUMMARY_SYSTEM_PROMPT = (
    "Ты — архивариус диалога. Сжимай переписку в плотный конспект на русском "
    "языке. Сохраняй: факты, имена, числа, договорённости, вопросы без ответа, "
    "ограничения и предпочтения пользователя. Не добавляй ничего от себя, не "
    "делай выводов и оценок. Пиши списком коротких пунктов, без вступлений."
)

# Сколько знаков «сырой» реплики показывать модели при конспектировании.
# Реплики в диалоге короткие (учебное демо), поэтому обрезка не нужна; на
# больших текстах конспект всё равно дешевле полной истории.
ROLE_LABELS = {"user": "Пользователь", "assistant": "Ассистент"}


class CompressionError(Exception):
    """Сжатие невозможно или не удалось (нет ключа, сбой API, нечего сжимать)."""


@dataclass(frozen=True)
class CompressionOutcome:
    """Результат одной суммаризации (строка таблицы summaries)."""

    created: bool
    summary_id: Optional[int] = None
    content: str = ""
    covered_from_message_id: int = 0
    covered_to_message_id: int = 0
    covered_messages: int = 0
    source_tokens: int = 0
    summary_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    error: Optional[str] = None


def build_summary_prompt(previous: str, chunk_text: str) -> List[dict]:
    """Собирает messages для вызова суммаризации.

    Прошлый конспект идёт отдельным блоком: так модель обновляет уже сжатое
    описание, а не описывает порцию с нуля (иначе теряется начало диалога).
    """
    parts = []
    if previous:
        parts.append("Текущий конспект диалога:\n" + previous)
    parts.append("Новые реплики диалога:\n" + chunk_text)
    parts.append(
        "Обнови конспект: соедини прошлое описание с новыми репликами. "
        "Верни только текст конспекта."
    )
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def render_chunk(rows: Sequence[ShortTermMessage]) -> str:
    """Текст порции реплик для конспектирования: «Роль: текст» построчно."""
    lines = []
    for row in rows:
        label = ROLE_LABELS.get(row.role, row.role)
        lines.append(f"{label}: {row.content}")
    return "\n".join(lines)


class ContextCompressor:
    """Сжатие истории одного агента: план, вызов суммаризации, запись конспекта.

    Компрессор не хранит состояние сам: конспект и его watermark читаются из
    БД, поэтому рестарт бэкенда не теряет ни сжатое описание, ни границы.
    Подсчёт токенов делегируется агенту (``agent.count_tokens``), клиент
    DeepSeek — тоже агенту (``agent._make_client``) — так в тестах подменяется
    ровно одна точка.
    """

    def __init__(self, agent) -> None:
        self.agent = agent

    # --- настройки и состояние ---
    @property
    def policy(self) -> CompressionPolicy:
        """Политика сжатия из конфигурации агента (чистая структура)."""
        cfg = self.agent.config
        return CompressionPolicy(
            enabled=cfg.summary_enabled,
            keep_last=cfg.keep_last_messages,
            summarize_every=cfg.summarize_every,
        )

    def latest_row(self) -> Optional[Summary]:
        """Последний конспект агента или None (диалог ещё не сжимался)."""
        with self.agent._session() as session:
            return (
                session.query(Summary)
                .filter(Summary.agent_id == self.agent.agent_id)
                .order_by(Summary.id.desc())
                .first()
            )

    def watermark(self) -> int:
        """id последней реплики, покрытой конспектом (0 — конспекта нет)."""
        row = self.latest_row()
        return row.covered_to_message_id if row is not None else 0

    def uncovered_rows(self) -> List[ShortTermMessage]:
        """Реплики, ещё не покрытые конспектом (id > watermark), по порядку."""
        watermark = self.watermark()
        rows = self.agent._fetch_rows()
        return [row for row in rows if row.id > watermark]

    # --- план сжатия ---
    def plan(self, force: bool = False) -> CompressionPlan:
        """План сжатия по текущему состоянию БД.

        ``force=True`` (кнопка «Сжать сейчас») игнорирует порог
        ``summarize_every``, но всё равно уважает ``keep_last``: последние N
        реплик никогда не уходят в конспект.
        """
        policy = self.policy
        uncovered = self.uncovered_rows()
        plan = plan_compression(policy, len(uncovered))
        if force and policy.enabled and len(uncovered) > policy.keep_last:
            plan = CompressionPlan(
                should_compress=True,
                summarize_count=len(uncovered) - policy.keep_last,
                keep_count=policy.keep_last,
                uncovered_count=len(uncovered),
            )
        return plan

    # --- суммаризация ---
    def summarize(self, force: bool = False) -> CompressionOutcome:
        """Сжимает старые реплики в конспект и сохраняет его в БД.

        Бросает ``CompressionError``, если сжимать нечего (порог не набран, а
        ``force`` не задан, либо непокрытых реплик не больше keep_last) или если
        вызов модели не удался — вызывающий код решает, как деградировать.
        """
        policy = self.policy
        if not policy.enabled:
            raise CompressionError("Сжатие истории выключено для этого агента")

        plan = self.plan(force=force)
        if not plan.should_compress:
            raise CompressionError(
                "Сжимать пока нечего: непокрытых реплик "
                f"{plan.uncovered_count}, порог сжатия — "
                f"{policy.keep_last} последних + {policy.summarize_every} новых."
            )

        uncovered = self.uncovered_rows()
        # Граница по паре: остаток не должен начинаться с ответа ассистента.
        chunk = self._compress_slice(uncovered, plan.summarize_count)
        if not chunk:
            raise CompressionError("Нет реплик для конспектирования")

        previous_row = self.latest_row()
        previous = previous_row.content if previous_row is not None else ""
        prompt = build_summary_prompt(previous, render_chunk(chunk))

        started = datetime.now(timezone.utc)
        try:
            client = self.agent._make_client()
            response = client.chat.completions.create(
                model=config.SUMMARY_MODEL,
                messages=prompt,
                temperature=config.SUMMARY_TEMPERATURE,
                max_tokens=config.SUMMARY_MAX_TOKENS,
            )
        except Exception as exc:  # нет ключа, сеть, лимиты — ход не ломаем
            raise CompressionError(f"Сбой суммаризации: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        content = ""
        if choice is not None and choice.message is not None:
            content = (choice.message.content or "").strip()
        if not content:
            raise CompressionError("Модель вернула пустой конспект")

        usage = getattr(response, "usage", None)
        prompt_tokens = self.agent.count_tokens(
            "\n".join(item["content"] for item in prompt)
        )
        completion_tokens = self.agent.count_tokens(content)
        if usage is not None:
            api_prompt = getattr(usage, "prompt_tokens", None)
            api_completion = getattr(usage, "completion_tokens", None)
            if api_prompt is not None:
                prompt_tokens = int(api_prompt)
            if api_completion is not None:
                completion_tokens = int(api_completion)

        source_tokens = self.agent.count_tokens(render_chunk(chunk))
        summary_tokens = self.agent.count_tokens(content)
        price = config.MODEL_PRICES.get(
            config.SUMMARY_MODEL, config.MODEL_PRICES[config.MODEL_CHAT]
        )
        cost = round(
            prompt_tokens / 1_000_000 * price["in"]
            + completion_tokens / 1_000_000 * price["out"],
            6,
        )

        row = Summary(
            agent_id=self.agent.agent_id,
            content=content,
            covered_from_message_id=chunk[0].id,
            covered_to_message_id=chunk[-1].id,
            covered_messages=len(chunk),
            source_tokens=source_tokens,
            summary_tokens=summary_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            created_at=started,
        )
        with self.agent._session() as session:
            session.add(row)
            session.commit()

        return CompressionOutcome(
            created=True,
            summary_id=row.id,
            content=content,
            covered_from_message_id=chunk[0].id,
            covered_to_message_id=chunk[-1].id,
            covered_messages=len(chunk),
            source_tokens=source_tokens,
            summary_tokens=summary_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
        )

    @staticmethod
    def _compress_slice(uncovered: Sequence[ShortTermMessage],
                        count: int) -> List[ShortTermMessage]:
        """Срез на сжатие с выравниванием границы по паре реплик.

        Если первый оставляемый остаток — ответ ассистента, он тоже уходит в
        конспект: «хвост» истории обязан начинаться с реплики пользователя.
        """
        chunk = list(uncovered[:count])
        tail_start = count
        if tail_start < len(uncovered) and uncovered[tail_start].role == "assistant":
            chunk.append(uncovered[tail_start])
        return chunk

    def history(self) -> List[dict]:
        """Все конспекты агента по возрастанию (для интерфейса/API)."""
        with self.agent._session() as session:
            rows = (
                session.query(Summary)
                .filter(Summary.agent_id == self.agent.agent_id)
                .order_by(Summary.id.asc())
                .all()
            )
        return [self._to_dict(row) for row in rows]

    def economics(self) -> dict:
        """Экономика сжатия: сколько токенов сэкономлено и сколько стоят конспекты.

        ``net_saved_tokens`` — честная экономия: сэкономленные токены запросов
        минус собственные токены вызовов суммаризации.
        """
        rows = self.history()
        saved = self.agent.saved_tokens_from_usage()
        summary_tokens = sum(row["prompt_tokens"] + row["completion_tokens"]
                             for row in rows)
        return {
            "summary_count": len(rows),
            "total_source_tokens": sum(row["source_tokens"] for row in rows),
            "total_summary_tokens": sum(row["summary_tokens"] for row in rows),
            "summary_cost": round(sum(row["cost"] for row in rows), 6),
            "saved_tokens": saved,
            "net_saved_tokens": saved - summary_tokens,
        }

    @staticmethod
    def _to_dict(row: Summary) -> dict:
        """ORM-строка summaries → обычный словарь (для API/UI)."""
        return {
            "id": row.id,
            "agent_id": row.agent_id,
            "content": row.content,
            "covered_from_message_id": row.covered_from_message_id,
            "covered_to_message_id": row.covered_to_message_id,
            "covered_messages": row.covered_messages,
            "source_tokens": row.source_tokens,
            "summary_tokens": row.summary_tokens,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "cost": row.cost,
            "created_at": row.created_at,
        }
