"""Тесты проверки декларативной конфигурации пайплайна (день 19).

Пайплайн — данные, которые приходят телом запроса, поэтому ``validate_pipeline``
обязан отвергать всё, из чего прогон неоднозначен: не словарь, пустой список шагов,
шаг без инструмента, ``args`` не словарь, условие без ``path`` или с чужим ``op``.
Отказы проверяются вместе с текстом (в тексте видно номер шага и допустимые операторы)
и с кодом причины ``bad_config`` — роутер превращает его в HTTP 400. Отдельно
проверяется, что возврат — нормализованная копия, а не ссылка на ``DEFAULT_PIPELINE``.
"""
import copy

import pytest

from backend.core import config
from backend.domain.pipeline_spec import (
    DEFAULT_PIPELINE,
    DEFAULT_PIPELINE_NAME,
    GUARD_OPS,
    MSG_NO_DATA,
    REASON_BAD_CONFIG,
    PipelineRejected,
    validate_pipeline,
)

#: Негодные конфигурации: значение и фрагмент текста отказа (номер шага — в тексте).
REJECTED = (
    pytest.param(None, "не задана", id="none"),
    pytest.param(["search"], "должна быть объектом", id="not-dict"),
    pytest.param("search", "должна быть объектом", id="string"),
    pytest.param({}, "непустой список шагов", id="no-steps-key"),
    pytest.param({"steps": []}, "непустой список шагов", id="empty-steps"),
    pytest.param({"steps": {"tool": "search"}}, "непустой список шагов", id="steps-not-list"),
    pytest.param({"steps": "search"}, "непустой список шагов", id="steps-string"),
    pytest.param({"steps": [None]}, "Шаг 0 должен быть объектом", id="step-none"),
    pytest.param({"steps": [{"tool": "search"}, 7]}, "Шаг 1 должен быть объектом",
                 id="second-step-not-dict"),
    pytest.param({"steps": [{"args": {}}]}, "У шага 0 не указан инструмент",
                 id="tool-missing"),
    pytest.param({"steps": [{"tool": "   "}]}, "не указан инструмент", id="tool-blank"),
    pytest.param({"steps": [{"tool": 5}]}, "не указан инструмент", id="tool-not-str"),
    pytest.param({"steps": [{"tool": "search", "args": ["query"]}]}, "объектом «args»",
                 id="args-not-dict"),
    pytest.param({"steps": [{"tool": "search"}, {"tool": "summarize", "args": 3}]},
                 "шага 1 должны быть объектом", id="second-step-bad-args"),
    pytest.param({"steps": [{"tool": "search", "guard": "non_empty"}]}, "объектом «guard»",
                 id="guard-not-dict"),
    pytest.param({"steps": [{"tool": "search", "guard": {"op": "non_empty"}}]},
                 "нужен путь «path»", id="guard-no-path"),
    pytest.param({"steps": [{"tool": "search", "guard": {"path": "", "op": "empty"}}]},
                 "нужен путь «path»", id="guard-empty-path"),
    pytest.param({"steps": [{"tool": "search", "guard": {"path": 7, "op": "empty"}}]},
                 "нужен путь «path»", id="guard-path-not-str"),
    pytest.param({"steps": [{"tool": "search", "guard": {"path": "$steps.0.x"}}]},
                 "не поддержано", id="guard-no-op"),
    pytest.param({"steps": [{"tool": "search", "guard": {"path": "$steps.0.x", "op": "big"}}]},
                 "не поддержано", id="guard-unknown-op"),
    pytest.param({"name": 42, "steps": [{"tool": "search"}]}, "должно быть строкой",
                 id="name-not-str"),
    pytest.param({"name": "x" * (config.PIPELINE_NAME_MAX + 1), "steps": [{"tool": "search"}]},
                 f"не длиннее {config.PIPELINE_NAME_MAX}", id="name-too-long"),
    pytest.param(
        {"steps": [{"tool": "search"} for _ in range(config.PIPELINE_STEPS_MAX + 1)]},
        "Шагов больше предела",
        id="too-many-steps",
    ),
)


@pytest.mark.parametrize("pipeline,patch", REJECTED)
def test_invalid_configuration_is_rejected(pipeline, patch):
    """Негодная конфигурация отвергается с кодом ``bad_config`` и понятным текстом."""
    with pytest.raises(PipelineRejected) as exc:
        validate_pipeline(pipeline)

    assert exc.value.reason_code == REASON_BAD_CONFIG
    assert patch in str(exc.value)
    assert exc.value.message == str(exc.value)


def test_steps_limit_boundary_is_inclusive():
    """Ровно ``PIPELINE_STEPS_MAX`` шагов принимается, на один больше — уже отказ."""
    allowed = {"steps": [{"tool": "search"} for _ in range(config.PIPELINE_STEPS_MAX)]}

    assert len(validate_pipeline(allowed)["steps"]) == config.PIPELINE_STEPS_MAX

    with pytest.raises(PipelineRejected) as exc:
        validate_pipeline({**allowed, "steps": allowed["steps"] + [{"tool": "search"}]})
    assert str(config.PIPELINE_STEPS_MAX + 1) in str(exc.value)


def test_default_pipeline_is_valid_and_has_three_tools_in_order():
    """Встроенный пайплайн проходит проверку: три инструмента композиции по порядку."""
    validated = validate_pipeline(DEFAULT_PIPELINE)

    assert validated["name"] == DEFAULT_PIPELINE_NAME
    assert tuple(step["tool"] for step in validated["steps"]) == (
        "search",
        "summarize",
        "save_to_file",
    )


def test_default_pipeline_steps_link_outputs_to_inputs():
    """Шаги связаны ссылками на выходы предыдущих: сводка берёт элементы поиска."""
    steps = validate_pipeline(DEFAULT_PIPELINE)["steps"]

    assert steps[0]["args"]["source"] == "{source}"
    assert steps[1]["args"]["items"] == "$steps.0.structured.items"
    assert steps[2]["args"]["content"] == "$steps.1.structured.summary_text"


def test_default_pipeline_summarize_guard_stops_on_empty_search():
    """Условный переход стоит на сводке: пустой поиск останавливает прогон досрочно."""
    guard = validate_pipeline(DEFAULT_PIPELINE)["steps"][1]["guard"]

    assert guard["path"] == "$steps.0.structured.items"
    assert guard["op"] == "non_empty"
    assert guard["message"] == MSG_NO_DATA


def test_search_and_save_steps_have_no_guard():
    """У поиска и сохранения нет условий: прерывать прогон на них нечем."""
    steps = validate_pipeline(DEFAULT_PIPELINE)["steps"]

    assert "guard" not in steps[0]
    assert "guard" not in steps[2]


def test_validation_does_not_modify_the_source_config():
    """Проверка ничего не пишет во входную конфигурацию (она может быть константой модуля)."""
    before = copy.deepcopy(DEFAULT_PIPELINE)

    validate_pipeline(DEFAULT_PIPELINE)

    assert DEFAULT_PIPELINE == before


def test_result_is_a_normalized_copy():
    """Возврат — копия: правка результата и его шагов не задевает ``DEFAULT_PIPELINE``."""
    validated = validate_pipeline(DEFAULT_PIPELINE)

    assert validated is not DEFAULT_PIPELINE
    assert validated["steps"] is not DEFAULT_PIPELINE["steps"]
    assert validated["steps"][0] is not DEFAULT_PIPELINE["steps"][0]
    assert validated["steps"][1]["guard"] is not DEFAULT_PIPELINE["steps"][1]["guard"]

    validated["steps"][0]["tool"] = "summarize"
    validated["steps"][1]["guard"]["op"] = "empty"
    validated["steps"].append({"tool": "search", "args": {}})

    assert DEFAULT_PIPELINE["steps"][0]["tool"] == "search"
    assert DEFAULT_PIPELINE["steps"][1]["guard"]["op"] == "non_empty"
    assert len(DEFAULT_PIPELINE["steps"]) == 3


def test_name_defaults_when_missing_or_empty():
    """Имя по умолчанию подставляется и при отсутствии поля, и при пустой строке."""
    for pipeline in ({"steps": [{"tool": "search"}]},
                     {"name": "", "steps": [{"tool": "search"}]},
                     {"name": None, "steps": [{"tool": "search"}]}):
        assert validate_pipeline(pipeline)["name"] == DEFAULT_PIPELINE_NAME


def test_name_at_limit_is_accepted():
    """Имя ровно в предел длины принимается как есть."""
    name = "п" * config.PIPELINE_NAME_MAX

    assert validate_pipeline({"name": name, "steps": [{"tool": "search"}]})["name"] == name


def test_tool_is_stripped_and_args_default_to_empty_dict():
    """Имя инструмента нормализуется, а отсутствующие аргументы становятся пустым словарём."""
    validated = validate_pipeline({"steps": [{"tool": "  summarize  "}]})

    assert validated["steps"][0] == {"tool": "summarize", "args": {}}


@pytest.mark.parametrize("op", GUARD_OPS)
def test_all_declared_guard_ops_are_accepted(op):
    """Каждый объявленный оператор условия проходит проверку и переносится целиком."""
    guard = {"path": "$steps.0.structured.items", "op": op, "value": "x", "message": "стоп"}

    validated = validate_pipeline({"steps": [{"tool": "summarize", "guard": guard}]})

    assert validated["steps"][0]["guard"] == guard


def test_unknown_guard_op_lists_all_allowed_ops():
    """Текст отказа перечисляет все допустимые операторы условия."""
    with pytest.raises(PipelineRejected) as exc:
        validate_pipeline(
            {"steps": [{"tool": "summarize", "guard": {"path": "$steps.0.x", "op": "exotic"}}]}
        )

    assert str(exc.value) == (
        "Условие «exotic» не поддержано. Допустимы: " + ", ".join(GUARD_OPS)
    )


def test_step_index_and_unknown_tool_policy():
    """Номер шага в тексте — индекс в списке, а чужой инструмент проверкой не отсекается."""
    with pytest.raises(PipelineRejected) as exc:
        validate_pipeline({"steps": [{"tool": "search"}, {"tool": ""}]})
    assert str(exc.value) == "У шага 1 не указан инструмент «tool»"

    assert validate_pipeline({"steps": [{"tool": "no_such_tool"}]})["steps"][0]["tool"] == (
        "no_such_tool"
    )
