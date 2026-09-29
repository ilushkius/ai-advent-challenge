"""Фейки режима RAG (день 22): тестовый корпус и клиент DeepSeek без сети.

Корпус — два markdown-документа с редким литералом ``CHARS_PER_PAGE``: фейковый
эмбеддер ищет по совпадению слов, поэтому в тексте есть и литерал из вопроса, и
слова ответа заглушки. Так проверяется вся связка «вопрос → фрагменты → блок
контекста → ответ», не выходя в сеть.

Ответ заглушки подобран под ``rag_mode.grounding_share``: опора считается по ЦЕЛЫМ
словам длиной от пяти символов, поэтому ``1800`` в неё не попадает, а ``корпус``,
``равен``, ``символов`` и ``страницу`` попадают — эти словоформы есть в документе.
"""
from types import SimpleNamespace

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
            choices=[SimpleNamespace(message=SimpleNamespace(content=owner.reply),
                                     finish_reason="stop")],
            usage=owner.usage,
        )


class RagStubClient:
    """Клиент DeepSeek для тестов RAG: те же четыре параметра, что у SDK."""

    def __init__(self, reply=None, error=None, error_times=None, usage=None) -> None:
        self.calls: list = []
        self.reply = GROUNDED_REPLY if reply is None else reply
        self.error = error
        self.error_times = error_times
        self.usage = usage if usage is not None else RagStubUsage()
        self.chat = SimpleNamespace(completions=RagStubCompletions(self))
