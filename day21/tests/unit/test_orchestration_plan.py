"""Тесты построения плана: каталог флота, промпт планировщика и разбор ответа (день 20).

Требование дня звучит как «определи, какие инструменты с каких серверов нужно
вызвать и в каком порядке», поэтому проверяется именно это: в системной части
промпта есть ключевая формулировка, а каталог перечисляет ВСЕ три сервера с их
инструментами и схемами аргументов. Разбор ответа намеренно терпимый (модель может
обернуть JSON в markdown), но негодный план равен отсутствию плана — ``None``, а не
исключение: у оркестратора всегда есть эвристика.

``heuristic_plan`` проверяется на полном, урезанном и пустом каталоге: шаги
отфильтровываются по доступным инструментам, а ссылки ``$steps.<i>`` (и зависящие от
них шаги) — перенумеровываются или выпадают, иначе прогон упал бы на маппинге.
"""
import json

import pytest

from backend.domain.mcp_tools import MCPFleetTool, MCPToolInfo
from backend.domain.orchestration_plan import (
    PLANNER_SYSTEM_PROMPT,
    _remap,
    build_plan_prompt,
    catalog_text,
    heuristic_plan,
    parse_plan,
)
from backend.domain.orchestration_spec import (
    DEMO_PLAN,
    REASON_BAD_QUERY,
    OrchestrationRejected,
)


def _fleet_tools() -> list[MCPFleetTool]:
    """Флот как плоский каталог: инструмент плюс имя его сервера."""
    return [
        MCPFleetTool(server="search_server", tool=MCPToolInfo(
            name="search_web", description="Поиск в ленте и в Википедии",
            input_schema={"type": "object", "required": ["query"],
                          "properties": {"query": {"type": "string"}}})),
        MCPFleetTool(server="data_server", tool=MCPToolInfo(
            name="summarize", description="Сводка списка элементов",
            input_schema={"type": "object", "required": ["items"],
                          "properties": {"items": {"type": "array"}}})),
        MCPFleetTool(server="storage_server", tool=MCPToolInfo(
            name="save_to_file", description="Файл в каталоге output/",
            input_schema={"type": "object", "required": ["content"],
                          "properties": {"content": {"type": "string"}}})),
    ]


# ---------- каталог и промпт ----------
def test_catalog_groups_tools_by_server():
    """Каталог называет каждый сервер и его инструменты с описанием и аргументами."""
    text = catalog_text(_fleet_tools())
    for server in ("search_server", "data_server", "storage_server"):
        assert f"Сервер {server}" in text
    assert "- search_web: Поиск в ленте и в Википедии" in text
    assert '"query"' in text and '"items"' in text and '"content"' in text


def test_catalog_of_empty_fleet_is_explicit():
    """Пустой каталог — это текст, а не пустая строка: модель должна понять причину."""
    assert "Каталог пуст" in catalog_text([])


def test_prompt_requires_servers_and_order():
    """Системная часть промпта содержит требование дня про серверы и порядок."""
    prompt = build_plan_prompt("найди данные и сохрани в базу", _fleet_tools())
    assert [message["role"] for message in prompt] == ["system", "user"]
    system = prompt[0]["content"]
    assert ("Определи, какие инструменты с каких серверов нужно вызвать и в каком "
            "порядке") in system
    assert PLANNER_SYSTEM_PROMPT == system
    user = prompt[1]["content"]
    assert "найди данные и сохрани в базу" in user
    for server in ("search_server", "data_server", "storage_server"):
        assert server in user
    assert "steps" in user and "$steps.0.structured.items" in user


# ---------- разбор ответа ----------
def _plan_payload() -> dict:
    return {"name": "chain", "steps": [
        {"tool": "search_web", "args": {"query": "{query}"}},
        {"tool": "summarize", "args": {"items": "$steps.0.structured.items"}},
    ]}


def test_parse_plan_plain_json():
    """Чистый JSON разбирается и нормализуется."""
    plan = parse_plan(json.dumps(_plan_payload(), ensure_ascii=False))
    assert plan == _plan_payload()


def test_parse_plan_from_markdown_fence():
    """JSON в ```-обёртке разбирается: модель часто её добавляет."""
    text = "Вот план:\n```json\n" + json.dumps(_plan_payload(), ensure_ascii=False) + \
           "\n```\nПояснение после."
    assert parse_plan(text) == _plan_payload()


def test_parse_plan_ignores_braces_inside_strings():
    """Скобка внутри строкового аргумента не ломает баланс блока."""
    payload = {"name": "n", "steps": [{"tool": "save_to_file",
                                       "args": {"content": "текст } с } скобками"}}]}
    plan = parse_plan("ответ: " + json.dumps(payload, ensure_ascii=False))
    assert plan["steps"][0]["args"]["content"] == "текст } с } скобками"


#: Ответы, из которых план не собирается.
BROKEN = (
    pytest.param("", id="empty"),
    pytest.param("никакого JSON здесь нет", id="no-json"),
    pytest.param("{не json}", id="invalid-json"),
    pytest.param('{"name": "n", "steps": []}', id="no-steps"),
    pytest.param('{"name": "n"}', id="no-steps-key"),
    pytest.param('["шаг"]', id="json-list"),
    pytest.param('{"name": "n", "steps": [{"args": {}}]}', id="tool-missing"),
    pytest.param('{"name": "n", "steps": [{"tool": "a", "args": []}]}', id="args-not-dict"),
)


@pytest.mark.parametrize("text", BROKEN)
def test_parse_plan_returns_none_on_broken_answer(text):
    """Негодный ответ модели — ``None`` (оркестратор перейдёт на эвристику)."""
    assert parse_plan(text) is None


# ---------- эвристика ----------
def test_heuristic_plan_with_full_catalog_is_demo_plan():
    """Полный каталог даёт ровно демо-сценарий (пять шагов, те же ссылки)."""
    names = [step["tool"] for step in DEMO_PLAN["steps"]]
    plan = heuristic_plan("найди данные и сохрани в базу", names)
    assert [step["tool"] for step in plan["steps"]] == names
    assert plan["name"] == "heuristic-chain"
    assert plan["steps"][1]["args"]["items"] == "$steps.0.structured.items"
    assert "$steps.3.structured.filepath" in str(plan["steps"][4]["args"])


def test_heuristic_plan_drops_unavailable_tools():
    """Каталог без части инструментов даёт только выполнимые шаги (в исходном порядке)."""
    names = [step["tool"] for step in DEMO_PLAN["steps"]]
    plan = heuristic_plan("запрос",
                          [name for name in names if name != "extract_keywords"])
    # Без ``extract_keywords`` выпадают и шаги, которые ссылаются на его выход:
    # ``save_to_file`` (ключевые слова в тексте) и ``save_to_db`` (файл и слова).
    assert [step["tool"] for step in plan["steps"]] == ["search_web", "summarize"]

    plan2 = heuristic_plan("запрос", [name for name in names if name != "save_to_db"])
    assert [step["tool"] for step in plan2["steps"]] == [
        "search_web", "summarize", "extract_keywords", "save_to_file"]


def test_heuristic_plan_drops_chain_when_source_is_lost():
    """Потерянный источник забирает с собой всю зависящую от него цепочку.

    Без ``search_web`` без данных остаются и ``summarize``, и ``extract_keywords``
    (он сводит текст сводки), и оба шага записи — выполнить нечего, поэтому отказ
    (роутер отдаст 400), а не план, падающий на маппинге.
    """
    names = [step["tool"] for step in DEMO_PLAN["steps"]]
    with pytest.raises(OrchestrationRejected) as exc:
        heuristic_plan("запрос", [name for name in names if name != "search_web"])
    assert exc.value.reason_code == REASON_BAD_QUERY


def test_heuristic_plan_keeps_only_resolvable_references():
    """Сохранённые ссылки указывают на предыдущие шаги плана, а не в пустоту."""
    names = [step["tool"] for step in DEMO_PLAN["steps"]]
    plan = heuristic_plan("запрос", [name for name in names if name != "save_to_file"])
    for index, step in enumerate(plan["steps"]):
        for number in _referenced_steps(step["args"]):
            assert number < index, "ссылка обязана указывать на предыдущий шаг"


def _referenced_steps(value) -> list[int]:
    """Номера шагов, на которые ссылаются аргументы (для проверки ссылок)."""
    import re

    found: list[int] = []
    if isinstance(value, dict):
        for item in value.values():
            found.extend(_referenced_steps(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_referenced_steps(item))
    elif isinstance(value, str):
        found.extend(int(number) for number in re.findall(r"\$steps\.(\d+)\.", value))
    return found


def test_remap_moves_references_to_new_positions():
    """Перенумерация ссылок: ``$steps.2`` становится ``$steps.1``.

    Механизм правит и вложенные структуры (строка текста в аргументе шага), и не
    трогает строки без ссылок: без него шаг ссылался бы на несуществующий номер и
    прогон падал бы на маппинге.
    """
    args = {"content": "Сводка:\n$steps.2.structured.text\n$steps.2.structured.joined",
            "meta": {"file": "$steps.3.structured.filepath", "plain": "без ссылок"},
            "items": ["$steps.0.structured.items"], "count": 5}
    remapped = _remap(args, {2: 1, 3: 2, 0: 0})
    assert remapped["content"] == "Сводка:\n$steps.1.structured.text\n$steps.1.structured.joined"
    assert remapped["meta"]["file"] == "$steps.2.structured.filepath"
    assert remapped["meta"]["plain"] == "без ссылок"
    assert remapped["items"] == ["$steps.0.structured.items"]
    assert remapped["count"] == 5


def test_heuristic_plan_rejects_empty_catalog():
    """Пустой каталог — отказ с кодом ``bad_query`` (роутер отдаёт 400)."""
    with pytest.raises(OrchestrationRejected) as exc:
        heuristic_plan("запрос", [])
    assert exc.value.reason_code == REASON_BAD_QUERY
    assert "не выполним" in exc.value.message
