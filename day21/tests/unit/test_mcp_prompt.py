"""Тесты блока данных MCP для системного промпта (день 17).

Блок — единственный путь, которым результат инструмента попадает к модели,
поэтому проверяется и его состав (имя инструмента, JSON аргументов, JSON
результата, инструкция «не выдумывать поля»), и обратный случай: когда вызова не
было или он не удался, промпт остаётся пустым — модель не должна видеть «данные»,
которых нет.
"""
import pytest

from backend.domain.mcp_prompt import (
    MCP_BLOCK_FOOTER,
    MCP_BLOCK_HEADER,
    render_mcp_tool_block,
)
from backend.domain.mcp_tool_call import MCPToolCallOutcome, MCPToolCallState
from backend.domain.mcp_tools import MCPToolResult

USER_PAYLOAD = {"id": 1, "name": "Leanne Graham", "city": "Gwenborough"}


def _done_outcome(structured=USER_PAYLOAD, text="") -> MCPToolCallOutcome:
    """Успешный исход вызова с готовым результатом (или только текстом)."""
    return MCPToolCallOutcome(
        state=MCPToolCallState.DONE, detected=True, connected=True, accepted=True,
        tool="get_user", arguments={"user_id": 1},
        result=MCPToolResult(tool="get_user", structured=structured, text=text,
                             duration_ms=1),
    )


def test_block_contains_header_tool_arguments_result_and_instruction():
    """В блоке есть заголовок, инструмент, аргументы, результат и запрет выдумывать."""
    block = render_mcp_tool_block(_done_outcome())
    assert block.startswith(MCP_BLOCK_HEADER)
    assert "Инструмент: get_user" in block
    assert 'Аргументы: {"user_id": 1}' in block
    assert '"name": "Leanne Graham"' in block
    assert MCP_BLOCK_FOOTER in block


def test_block_json_is_deterministic():
    """Ключи отсортированы: одинаковый результат даёт одинаковый блок (его видно в отчётах)."""
    first = render_mcp_tool_block(_done_outcome())
    second = render_mcp_tool_block(_done_outcome(structured=dict(reversed(
        list(USER_PAYLOAD.items())))))
    assert first == second


def test_block_falls_back_to_tool_text_without_structured_content():
    """Инструмент без ``outputSchema`` отвечает текстом — он и попадает в блок."""
    outcome = _done_outcome(structured=None, text="Leanne Graham, Gwenborough")
    block = render_mcp_tool_block(outcome)
    assert "Leanne Graham, Gwenborough" in block


@pytest.mark.parametrize("state", [
    MCPToolCallState.IDLE,
    MCPToolCallState.PLANNED,
    MCPToolCallState.INVOKED,
    MCPToolCallState.REJECTED,
    MCPToolCallState.FAILED,
])
def test_no_block_without_successful_call(state):
    """Отказ, сбой и «вызов не потребовался» промпт не меняют."""
    outcome = MCPToolCallOutcome(state=state, detected=True, connected=True,
                                 tool="get_user", arguments={"user_id": 1})
    assert render_mcp_tool_block(outcome) == ""


def test_no_block_when_result_missing():
    """Состояние ``done`` без результата — противоречие, блок не собирается."""
    outcome = MCPToolCallOutcome(state=MCPToolCallState.DONE, detected=True)
    assert render_mcp_tool_block(outcome) == ""
