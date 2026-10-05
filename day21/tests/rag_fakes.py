"""Фейки режима RAG: тестовый корпус, клиент DeepSeek без сети и реранкер без модели.

Корпус — два markdown-документа с редким литералом ``CHARS_PER_PAGE``: фейковый
эмбеддер ищет по совпадению слов, поэтому в тексте есть и литерал из вопроса, и
слова ответа заглушки. Так проверяется вся связка «вопрос → фрагменты → блок
контекста → ответ», не выходя в сеть.

Ответ заглушки подобран под ``rag_mode.grounding_share``: опора считается по ЦЕЛЫМ
словам длиной от пяти символов, поэтому ``1800`` в неё не попадает, а ``корпус``,
``равен``, ``символов`` и ``страницу`` попадают — эти словоформы есть в документе.

``RagStubReranker`` ставится вместо кросс-энкодера: балл фрагмента — доля слов
запроса, найденных в его тексте. Модель в тестах не грузится вообще (её загрузку
запрещает autouse-фикстура ``isolated_indexing``), а формулы отбора всё равно
проверяются целиком.
"""
import re
from types import SimpleNamespace

from backend.domain import rag_filter

#: Документ с литералом вопроса: на него обязан находиться фрагмент.
RAG_MARKDOWN_A = """# Правила корпуса

Корпус лежит в папке documents/rag_corpus и собирается скриптом из файлов дня 21.

## Подсчёт объёма

Одной странице равен CHARS_PER_PAGE: 1800 символов. Столько символов берёт подсчёт
на одну страницу, поэтому десять страниц корпуса — это 18000 символов.
"""

#: Второй документ: кандидат в выдачу, но литерала вопроса в нём нет.
RAG_MARKDOWN_B = """# Заметки о вердикте

## Опора ответа

Доля слов ответа, найденных в контексте, сравнивается с порогом: ниже порога
вердикт сообщает, что низкая уверенность — фактов из корпуса в ответе нет.

## Отказы режима

Пустой вопрос отвергается сразу, а сбой вызова модели повторяется несколько раз
и завершается откатом на ответ без контекста.
"""

#: Ответ с опорой: слова документа A присутствуют, поэтому опора есть.
GROUNDED_REPLY = "Корпус: CHARS_PER_PAGE равен 1800 символов на страницу."

#: Ответ без опоры: ни одного слова из корпуса — вердикт «низкая уверенность».
UNGROUNDED_REPLY = "Погода сегодня отличная, гулять приятно."


def write_corpus(base):
    """Пишет два документа тестового корпуса в ``base/rag_corpus``."""
    folder = base / "rag_corpus"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "rules.md").write_text(RAG_MARKDOWN_A, encoding="utf-8")
    (folder / "verdict.md").write_text(RAG_MARKDOWN_B, encoding="utf-8")
    return folder


class RagStubUsage:
    """Блок `usage` ответа: токены и поля кэша контекста."""

    def __init__(self, prompt_tokens=1200, completion_tokens=40,
                 cache_hit_tokens=900, cache_miss_tokens=300) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.prompt_cache_hit_tokens = cache_hit_tokens
        self.prompt_cache_miss_tokens = cache_miss_tokens


class RagStubCompletions:
    """`chat.completions`: пишет вызов, падает заданное число раз, отвечает текстом."""

    def __init__(self, owner: "RagStubClient") -> None:
        self._owner = owner

    def create(self, model, messages, temperature=None, max_tokens=None):
        owner = self._owner
        owner.calls.append({"model": model, "messages": messages,
                            "temperature": temperature, "max_tokens": max_tokens})
        # error_times=None — падать всегда: тогда не удаётся и откат на ответ без RAG.
        if owner.error is not None and (owner.error_times is None
                                        or len(owner.calls) <= owner.error_times):
            raise owner.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=owner.text(len(owner.calls))), finish_reason="stop")],
            usage=owner.usage,
        )


class RagStubClient:
    """Клиент DeepSeek для тестов RAG: те же четыре параметра, что у SDK.

    ``replies`` — ответ по номеру вызова (последний повторяется): он нужен режиму
    с переформулировкой, где первый вызов возвращает поисковый запрос, а второй —
    ответ по найденному контексту. Пустой ``replies`` означает один ``reply``.
    """

    def __init__(self, reply=None, replies=None, error=None, error_times=None,
                 usage=None) -> None:
        self.calls: list = []
        self.reply = GROUNDED_REPLY if reply is None else reply
        self.replies = [str(item) for item in (replies or [])]
        self.error = error
        self.error_times = error_times
        self.usage = usage if usage is not None else RagStubUsage()
        self.chat = SimpleNamespace(completions=RagStubCompletions(self))

    def text(self, call_number: int) -> str:
        """Текст ответа для вызова № ``call_number`` (счёт с единицы)."""
        if not self.replies:
            return self.reply
        return self.replies[min(call_number - 1, len(self.replies) - 1)]


class RagStubReranker:
    """Реранкер без модели: балл — доля слов запроса, найденных в тексте фрагмента.

    Числа детерминированы (никакой сети и весов), поэтому тесты проверяют формулу и
    порядок, а не качество модели. ``scores`` подменяет расчёт целиком — этим
    проверяется рассинхрон числа баллов и кандидатов; ``error`` — сбой реранкера.
    """

    def __init__(self, scores=None, error=None, loaded=True,
                 model_name="fake: реранкер по словам запроса") -> None:
        self.calls: list = []
        self.scores = None if scores is None else list(scores)
        self.error = error
        self._loaded = loaded
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        """Имя модели реранкера: у заглушки — своё, чтобы его было видно в отчёте."""
        return self._model_name

    @property
    def loaded(self) -> bool:
        """Загружена ли «модель»: у заглушки это просто флаг."""
        return self._loaded

    def score(self, query: str, texts) -> list:
        """Баллы фрагментов в ``[0, 1]``: доля слов запроса, найденных в тексте."""
        self.calls.append({"query": query, "texts": list(texts)})
        if self.error is not None:
            raise self.error
        if self.scores is not None:
            return rag_filter.normalize_rerank_scores(self.scores)
        words = [word.lower() for word in re.findall(r"\w+", str(query or ""))
                 if len(word) > 2]
        raw = []
        for text in texts:
            haystack = str(text or "").lower()
            found = sum(1 for word in words if word in haystack)
            raw.append(found / len(words) if words else 0.0)
        return rag_filter.normalize_rerank_scores(raw)

    def warmup(self) -> bool:
        """Прогрев заглушки: загрузка не нужна, поэтому всегда успех."""
        self._loaded = True
        return True

    def reset(self) -> None:
        """Сброс «модели»: у заглушки — только флаг."""
        self._loaded = False


class LocalDictStubClient:
    """Клиент локального провайдера для тестов: словарь вместо ``LLMCallResult``.

    Копия формы ``LocalLLMClient`` (день 26) без HTTP: ``generate_with_context`` и
    ``generate`` отдают словарь с ``answer``/``duration_ms``/``tokens``. Именно так
    проверяется, что службы читают ответ через ``rag_llm.response_text`` и
    ``usage_dict``, а не через атрибуты объекта SDK.
    """

    def __init__(self, answer: str = None, error: Exception = None,
                 model: str = "stub-local:1b") -> None:
        self.answer = GROUNDED_REPLY if answer is None else answer
        self.error = error
        self.model = model
        self.calls: list = []

    def _result(self, call: dict) -> dict:
        """Ответ в форме ``LocalLLMClient``: те же поля, нулевые кэш и цена."""
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return {
            "provider": "local",
            "model": self.model,
            "answer": str(self.answer).strip(),
            "duration_ms": 12,
            "tokens": {
                "model": self.model, "prompt_tokens": 100,
                "completion_tokens": 0, "cache_hit_tokens": 0,
                "cache_miss_tokens": 100, "cache_hit_percent": 0.0,
                "cost_estimate": 0.0,
            },
        }

    def generate_with_context(self, **kwargs) -> dict:
        """Тот же вызов, что у сервисного клиента RAG и мини-чата."""
        return self._result(dict(kwargs))

    def generate(self, prompt: str, max_tokens=None) -> dict:
        """Один запрос демо локальной модели: промпт и предел ответа."""
        return self._result({"prompt": prompt, "max_tokens": max_tokens})
