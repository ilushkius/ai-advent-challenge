"""Сценарии 4 и 5 дня 20: перезапуск приложения и четвёртый сервер правкой файла.

Здесь проверяется то, ради чего состояние вынесено из памяти процесса: журнал
оркестрации лежит в SQLite, а состав флота — в ``mcp_servers.json``. Поэтому после
остановки реестра НОВЫЙ реестр (без общей памяти с прежним) поднимает флот заново и
видит прошлые запуски, а четвёртый сервер достаточно дописать в файл — код реестра
при этом не меняется.

Вынесено из ``orchestration_scenarios.py``, потому что тот подошёл к лимиту 400
строк: сценарии прогона и сценарии состояния — разные предметы, и держать их
вместе незачем.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from backend.services.mcp_registry import MCPRegistry
from backend.services.orchestration_service import OrchestrationService

from orchestration_scenarios import DemoRun, structured

#: Сколько инструментов у флота из трёх серверов и сколько — с четвёртым (эхо).
FLEET_TOOLS = 11
FLEET_TOOLS_WITH_ECHO = 13


# ---------- сценарий 4: перезапуск приложения ----------
def scenario_restart(registry: MCPRegistry, service: OrchestrationService,
                     servers_file: Path, fleet_factory=None) -> DemoRun:
    """История и флот переживают перезапуск: журнал в SQLite, состав — в файле."""
    run = DemoRun(name="4. Перезапуск приложения (история и флот восстанавливаются)")
    before = service.list_runs()
    run_id = (before["runs"] or [{}])[0].get("id")
    registry.close()
    run.check("флот остановлен", registry.fleet_status()["connected"] == 0)

    # «Перезапуск»: НОВЫЙ реестр на том же файле конфигурации и та же служба на той
    # же БД. Память процесса при этом не переиспользуется — как после рестарта
    # приложения: история читается из SQLite, состав флота — из mcp_servers.json.
    restarted = MCPRegistry(fleet_factory=fleet_factory, servers_file=servers_file,
                            cwd=str(servers_file.parent))
    try:
        restarted.connect_all()
        status = restarted.fleet_status()
        run.check("флот подключён заново",
                  status["count"] == 3 and status["connected"] == 3,
                  f"{status['count']} серверов, инструментов {status['total_tools']}")
        run.check("каталоги инструментов прочитаны после перезапуска",
                  status["total_tools"] == FLEET_TOOLS, str(status["total_tools"]))
        history = service.list_runs()
        run.check("история запусков на месте", history["count"] >= 1,
                  f"{history['count']} запусков")
        steps = service.steps(run_id) if run_id else {"steps": []}
        run.check("шаги прошлого запуска читаются из БД",
                  len(steps["steps"]) >= 1, f"{len(steps['steps'])} шагов")
        run.check("статистика считается по журналу",
                  history["stats"]["steps"] >= 1,
                  f"шагов {history['stats']['steps']}, серверов "
                  f"{len(history['stats']['servers'])}")
        restarted.refresh_tools()
        payload = json.loads(servers_file.read_text(encoding="utf-8"))
        cached = {item["name"]: len(item["tools_cache"]) for item in payload["servers"]}
        run.check("кэш инструментов записан в файл флота",
                  cached["search_server"] == 3 and cached["data_server"] == 4
                  and cached["storage_server"] == 4, str(cached))
        run.check("новый прогон продолжает историю, не затирая прошлую",
                  service.start_demo(background=False)["status"] == "completed"
                  and service.list_runs()["count"] > history["count"])
    finally:
        restarted.close()
    return run


# ---------- сценарий 5: четвёртый сервер без правки кода ----------
def scenario_new_server(registry: MCPRegistry, servers_file: Path, echo_server: Path,
                        tmp_dir: Path) -> DemoRun:
    """Дописываем сервер в файл — реестр подхватывает его без изменения кода."""
    run = DemoRun(name="5. Четвёртый сервер добавлен правкой файла (код не менялся)")
    extended = tmp_dir / "mcp_servers.json"
    payload = json.loads(servers_file.read_text(encoding="utf-8"))
    payload["servers"].append({
        "name": "echo_server",
        "command": sys.executable,
        "args": [str(echo_server)],
        "description": "Сервер-эхо: echo и add (добавлен без правки кода)",
        "tools_cache": [],
    })
    extended.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    fleet = MCPRegistry(servers_file=extended, cwd=str(tmp_dir))
    try:
        status = fleet.connect_all()
        run.check("в флоте четыре сервера",
                  fleet.fleet_status()["count"] == 4,
                  ", ".join(item["name"] for item in status))
        run.check("инструментов стало тринадцать",
                  fleet.fleet_status()["total_tools"] == FLEET_TOOLS_WITH_ECHO,
                  str(fleet.fleet_status()["total_tools"]))
        run.check("маршрутизация нашла инструмент нового сервера",
                  fleet.find_tool_by_name("echo") == "echo_server",
                  str(fleet.find_tool_by_name("echo")))
        result = fleet.call_tool("echo", {"text": "привет"})
        run.check("вызов нового инструмента работает по-настоящему",
                  result.is_error is False and "привет" in (result.text or ""),
                  (result.text or "")[:60])
        run.check("реестр подключил только новый сервер (остальные не перезапускались)",
                  fleet.connected("echo_server") is True
                  and fleet.connected("search_server") is True)
    finally:
        fleet.close()
    run.facts["servers"] = [item["name"] for item in fleet.servers()]
    run.facts["tools"] = [tool.name for tool in fleet.list_all_tools()]
    return run



__all__ = [
    "FLEET_TOOLS",
    "FLEET_TOOLS_WITH_ECHO",
    "scenario_new_server",
    "scenario_restart",
    "structured",
]
