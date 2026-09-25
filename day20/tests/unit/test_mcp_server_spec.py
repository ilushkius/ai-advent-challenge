"""Тесты конфигурации флота MCP-серверов как данных (день 20).

Флот описывается файлом ``mcp_servers.json``, поэтому разбор и проверка записей —
граница между «человек правит файл» и «приложение запускает процессы». Проверяется
то, без чего сервер нельзя запустить или различить: отсутствующий файл (не ошибка —
флот просто пуст), битый JSON, дубли имён, пустые имя и команда, аргументы не
списком, кэш инструментов не списком и сборка цели одной строкой (её парсит
``parse_target``, поэтому токены с пробелами обязаны быть в кавычках).
"""
import json

import pytest

from backend.core import config
from backend.domain.mcp_server_spec import (
    SERVERS_KEY,
    MCPServerSpec,
    MCPServerSpecError,
    dump_specs,
    find_spec,
    load_server_specs,
    validate_specs,
)
from backend.domain.mcp_target import MCPTransport, parse_target


def _record(**overrides) -> dict:
    """Запись сервера в форме файла конфигурации."""
    base = {"name": "search_server", "command": "uv",
            "args": ["run", "python", "mcp_servers/search_server/server.py"],
            "description": "Поиск данных", "tools_cache": []}
    base.update(overrides)
    return base


# ---------- чтение файла ----------
def test_missing_file_is_empty_fleet(tmp_path):
    """Отсутствующего файла достаточно, чтобы поднять приложение без флота."""
    assert load_server_specs(tmp_path / "нет.json") == []


def test_broken_json_is_an_error(tmp_path):
    """Испорченный файл — ошибка: молча пустой флот скрыл бы причину."""
    path = tmp_path / "mcp_servers.json"
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(MCPServerSpecError) as exc:
        load_server_specs(path)
    assert "не разобран" in str(exc.value)


def test_file_without_servers_key_means_empty_fleet(tmp_path):
    """Файл без ключа ``servers`` — пустой флот, а не ошибка разбора."""
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({"описание": "ещё не настроено"}, ensure_ascii=False),
                    encoding="utf-8")
    assert load_server_specs(path) == []


def test_loads_three_servers_in_file_order(tmp_path):
    """Порядок записей сохраняется: он же порядок маршрутизации вызовов."""
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({SERVERS_KEY: [
        _record(name="search_server"), _record(name="data_server"),
        _record(name="storage_server")]}, ensure_ascii=False), encoding="utf-8")
    specs = load_server_specs(path)
    assert [spec.name for spec in specs] == ["search_server", "data_server",
                                            "storage_server"]
    assert specs[0].command == "uv"
    assert specs[0].args[-1].endswith("search_server/server.py")
    assert specs[0].description == "Поиск данных"


# ---------- проверка записей ----------
#: Негодные конфигурации: значение и фрагмент текста отказа.
REJECTED = (
    pytest.param("строка", "должна быть объектом", id="not-list"),
    pytest.param([7], "должна быть объектом", id="record-not-dict"),
    pytest.param([_record(name="")], "не указано имя", id="empty-name"),
    pytest.param([_record(name="   ")], "не указано имя", id="blank-name"),
    pytest.param([_record(name=5)], "не указано имя", id="name-not-str"),
    pytest.param([_record(name="x" * 65)], "длиннее", id="name-too-long"),
    pytest.param([_record(command="")], "не указана команда", id="empty-command"),
    pytest.param([_record(command=7)], "не указана команда", id="command-not-str"),
    pytest.param([_record(args="run python")], "списком строк", id="args-not-list"),
    pytest.param([_record(args=[1, 2])], "списком строк", id="args-not-str-items"),
    pytest.param([_record(description=7)], "должно быть строкой", id="description-not-str"),
    pytest.param([_record(tools_cache={"name": "echo"})], "списком объектов",
                 id="cache-not-list"),
    pytest.param([_record(tools_cache=["echo"])], "списком объектов",
                 id="cache-items-not-dict"),
    pytest.param([_record(), _record()], "объявлен дважды", id="duplicate-name"),
)


@pytest.mark.parametrize("payload,expected", REJECTED)
def test_invalid_records_are_rejected(payload, expected):
    """Негодная запись отвергается с текстом, объясняющим причину."""
    with pytest.raises(MCPServerSpecError) as exc:
        validate_specs(payload)
    assert expected in str(exc.value)


def test_validate_normalizes_and_truncates_description():
    """Проверка чистит поля: имя и команда без пробелов, описание — в границах."""
    spec = validate_specs([_record(name="  search_server  ", command="  uv  ",
                                  description="я" * 500, tools_cache=[
                                      {"name": "search_web"}])])[0]
    assert spec.name == "search_server"
    assert spec.command == "uv"
    assert len(spec.description) == config.MCP_SERVER_DESCRIPTION_MAX
    assert spec.tools_cache == ({"name": "search_web"},)


def test_validate_accepts_bare_list_and_dict_payload():
    """Обе формы файла принимались бы: список записей и объект с ключом ``servers``."""
    assert len(validate_specs([_record()])) == 1
    assert len(validate_specs({SERVERS_KEY: [_record()]})) == 1
    assert validate_specs({SERVERS_KEY: []}) == []


# ---------- цель и сериализация ----------
def test_target_is_parsed_by_mcp_target_parser():
    """Цель флота разбирается тем же парсером, что и цель ручного подключения."""
    spec = MCPServerSpec(name="search_server", command="uv",
                         args=("run", "python", "mcp_servers/search_server/server.py"))
    target = parse_target(spec.target)
    assert target.transport is MCPTransport.STDIO
    assert target.command == "uv"
    assert target.args[-1] == "mcp_servers/search_server/server.py"


def test_target_quotes_tokens_with_spaces():
    """Токен с пробелом (путь к интерпретатору) не разваливает команду на части."""
    spec = MCPServerSpec(name="echo_server", command=r"C:\Program Files\Python\python.exe",
                         args=("C:\\мои файлы\\server.py",))
    target = parse_target(spec.target)
    assert target.command == r"C:\Program Files\Python\python.exe"
    assert target.args == (r"C:\мои файлы\server.py",)


def test_to_status_and_to_dict_shapes():
    """Запись для API несёт состояние подключения, запись для файла — только конфигурацию."""
    spec = MCPServerSpec(name="data_server", command="uv", args=("run", "x.py"),
                         description="Данные")
    status = spec.to_status(connected=True, state="connected", tool_count=4)
    assert status["connected"] is True and status["tool_count"] == 4
    assert status["target"] == "uv run x.py" and status["transport"] == "stdio"
    assert status["error"] is None
    assert set(spec.to_dict()) == {"name", "command", "args", "description", "tools_cache"}


def test_dump_specs_round_trip(tmp_path):
    """Записанный файл читается обратно теми же значениями (кэш инструментов включён)."""
    specs = validate_specs([_record(tools_cache=[{"name": "search_web",
                                                 "description": "поиск"}])])
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps(dump_specs(specs), ensure_ascii=False), encoding="utf-8")
    restored = load_server_specs(path)
    assert restored == specs
    assert restored[0].tools_cache[0]["name"] == "search_web"


def test_find_spec_by_name():
    """Поиск сервера по имени: есть — запись, нет — ``None``."""
    specs = validate_specs([_record(name="search_server"), _record(name="data_server")])
    assert find_spec(specs, "data_server").name == "data_server"
    assert find_spec(specs, "storage_server") is None
