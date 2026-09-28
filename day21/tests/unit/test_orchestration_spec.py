"""Тесты проверки плана и встроенного демо-сценария (день 20).

План приходит и телом запроса, и от модели, поэтому ``validate_plan`` обязан
отвергать всё, из чего прогон неоднозначен: не словарь, пустой список шагов, шаг
без инструмента, ``args`` не словарь, условие без ``path`` или с чужим ``op``.
Отказы проверяются вместе с текстом и кодом причины (``bad_plan`` — HTTP 400).

Отдельно проверяется СТРУКТУРА ``DEMO_PLAN``: пять шагов по трём серверам, порядок
инструментов и ссылки ``$steps.<i>``, по которым данные переходят между серверами.
Это контракт дня: кнопка «🚀 Запустить демо-сценарий» запускает именно его.
"""
import copy

import pytest

from backend.core import config
from backend.domain.orchestration_spec import (
    DEFAULT_PLAN_NAME,
    DEMO_LIMIT,
    DEMO_PLAN,
    DEMO_QUERY,
    DEMO_STEP_COUNT,
    MSG_COMPLETED,
    MSG_FAILED,
    MSG_RUNNING,
    MSG_STOPPED,
    REASON_BAD_PLAN,
    REASON_BAD_QUERY,
    REASON_NOT_FOUND,
    STEP_FAILED,
    STEP_OK,
    STEP_STOPPED,
    OrchestrationRejected,
    demo_arguments,
    launch_arguments,
    steps_for_prompt,
    validate_plan,
)

#: Негодные планы: значение и фрагмент текста отказа (номер шага — в тексте).
REJECTED = (
    pytest.param(None, "не задан", id="none"),
    pytest.param(["search_web"], "должен быть объектом", id="not-dict"),
    pytest.param({}, "непустой список шагов", id="no-steps-key"),
    pytest.param({"steps": []}, "непустой список шагов", id="empty-steps"),
    pytest.param({"steps": "search_web"}, "непустой список шагов", id="steps-not-list"),
    pytest.param({"steps": [None]}, "Шаг 0 должен быть объектом", id="step-none"),
    pytest.param({"steps": [{"args": {}}]}, "У шага 0 не указан инструмент",
                 id="tool-missing"),
    pytest.param({"steps": [{"tool": "  "}]}, "не указан инструмент", id="tool-blank"),
    pytest.param({"steps": [{"tool": 7}]}, "не указан инструмент", id="tool-not-str"),
    pytest.param({"steps": [{"tool": "a", "args": []}]}, "объектом «args»",
                 id="args-not-dict"),
    pytest.param({"steps": [{"tool": "a", "guard": []}]}, "объектом «guard»",
                 id="guard-not-dict"),
    pytest.param({"steps": [{"tool": "a", "guard": {"op": "non_empty"}}]},
                 "нужен путь «path»", id="guard-without-path"),
    pytest.param({"steps": [{"tool": "a", "guard": {"path": "$steps.0.x", "op": "?"}}]},
                 "не поддержано", id="guard-unknown-op"),
    pytest.param({"name": "x" * (config.ORCH_NAME_MAX + 1),
                  "steps": [{"tool": "a"}]}, "не длиннее", id="name-too-long"),
    pytest.param({"steps": [{"tool": "a"}] * (config.ORCH_STEPS_MAX + 1)},
                 "Шагов больше предела", id="too-many-steps"),
)

#: Порядок инструментов демо-сценария и серверы, которые их публикуют.
DEMO_TOOLS = ("search_web", "summarize", "extract_keywords", "save_to_file",
              "save_to_db")
DEMO_SERVERS = ("search_server", "data_server", "storage_server")


@pytest.mark.parametrize("plan,expected", REJECTED)
def test_invalid_plan_is_rejected_with_reason(plan, expected):
    """Негодный план отвергается с кодом причины ``bad_plan`` (роутер отдаёт 400)."""
    with pytest.raises(OrchestrationRejected) as exc:
        validate_plan(plan)
    assert expected in exc.value.message
    assert exc.value.reason_code == REASON_BAD_PLAN


def test_valid_plan_is_normalized_copy():
    """Проверенный план — копия: правка прогона не меняет конфигурацию вызывающего."""
    source = {"name": "chain", "steps": [
        {"tool": "search_web", "args": {"query": "{query}"}},
        {"tool": "summarize", "args": {"items": "$steps.0.structured.items"},
         "guard": {"path": "$steps.0.structured.items", "op": "non_empty",
                   "message": "нет данных"}},
    ]}
    before = copy.deepcopy(source)
    plan = validate_plan(source)
    assert plan["name"] == "chain"
    assert [step["tool"] for step in plan["steps"]] == ["search_web", "summarize"]
    assert plan["steps"][1]["guard"]["op"] == "non_empty"
    plan["steps"][0]["args"]["query"] = "изменено"
    assert source == before


def test_plan_without_name_gets_default():
    """План без имени получает имя по умолчанию (в журнале всегда есть чем назвать)."""
    plan = validate_plan({"steps": [{"tool": "search_web"}]})
    assert plan["name"] == DEFAULT_PLAN_NAME
    assert plan["steps"][0]["args"] == {}


def test_demo_plan_structure():
    """Демо-план — пять шагов по трём серверам с данными, идущими по ссылкам."""
    plan = validate_plan(DEMO_PLAN)
    assert len(plan["steps"]) == DEMO_STEP_COUNT
    assert tuple(step["tool"] for step in plan["steps"]) == DEMO_TOOLS
    assert plan["name"] == "demo-scenario"
    # Данные переходят между серверами ссылками: шаг 1 берёт items шага 0, шаг 2 —
    # summary_text шага 1, шаг 4 — filepath шага 3 и keywords шага 2.
    assert plan["steps"][1]["args"]["items"] == "$steps.0.structured.items"
    assert plan["steps"][2]["args"]["text"] == "$steps.1.structured.summary_text"
    assert "$steps.3.structured.filepath" in str(plan["steps"][4]["args"])
    assert "$steps.2.structured.joined" in str(plan["steps"][4]["args"])
    # Поиск идёт без фильтра: посты jsonplaceholder — английский текст, русская
    # реплика подстрокой не совпала бы ни с одним из них.
    assert plan["steps"][0]["args"]["query"] == ""
    assert plan["steps"][0]["args"]["source"] == "posts"


def test_demo_servers_are_distinct_in_plan():
    """Сценарий затрагивает три РАЗНЫХ сервера — иначе день был бы про одно соединение."""
    tools = {step["tool"] for step in DEMO_PLAN["steps"]}
    assert len(DEMO_SERVERS) == 3
    assert len(tools) == DEMO_STEP_COUNT


def test_demo_arguments_and_launch_defaults():
    """Аргументы запуска: демо даёт своё имя файла, обычный запуск — из реплики."""
    demo = demo_arguments()
    assert demo["query"] == DEMO_QUERY
    assert demo["limit"] == DEMO_LIMIT
    assert demo["filename"] == "demo-scenario"

    defaults = launch_arguments("Про RAG")
    assert defaults["filename"] == "про-rag.md"
    assert defaults["format"] == "md"
    assert launch_arguments("Про RAG", {"filename": "мой.md", "limit": 3})["filename"] == "мой.md"
    assert launch_arguments("Про RAG", {"limit": 3})["limit"] == 3


def test_steps_for_prompt_and_messages():
    """Строка шагов плана читается в логе и не падает на пустом плане."""
    assert steps_for_prompt(DEMO_PLAN).startswith("search_web → summarize")
    assert steps_for_prompt(None) == "—"
    assert (MSG_RUNNING, MSG_COMPLETED, MSG_STOPPED, MSG_FAILED) == (
        "оркестрация выполняется", "оркестрация выполнена",
        "оркестрация завершена досрочно",
        "оркестрация остановлена: шаг завершился ошибкой",
    )
    assert (STEP_OK, STEP_FAILED, STEP_STOPPED) == ("ok", "failed", "stopped")
    assert (REASON_BAD_QUERY, REASON_BAD_PLAN, REASON_NOT_FOUND) == (
        "bad_query", "bad_plan", "not_found")
