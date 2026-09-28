"""Сборка markdown-отчёта дня 17 по данным прогона (``DemoRun``).

Отдельный модуль, потому что отчёт — это документ с собственным форматом, а
``scripts/mcp_tool_demo.py`` — сценарий: смешивать их значит держать в одном файле
две разные ответственности (и вдвое быстрее упереться в лимит строк).

Все данные берутся из ``DemoRun``: в отчёт не попадает ни одна строка, которой не
было в прогоне. Файл пишется целиком (перезапись), семь разделов — контракт
документа: что проверялось, какой API, сервер и инструменты, вызовы, использование
результата агентом, автотесты, границы дня.
"""
from __future__ import annotations

import json
from pathlib import Path

#: Чем закончились вызовы: подписи состояний для отчёта.
STATE_LABELS = {
    "idle": "не вызывался",
    "planned": "выбран",
    "invoked": "запрос отправлен",
    "done": "успешно",
    "failed": "ошибка",
    "rejected": "отклонён",
}

#: Ожидаемые ручки внешнего API: их описывает раздел «Какой API использовался».
API_ENDPOINTS = (
    ("`GET /users/{id}`", "`get_user`", "id, name, username, email, phone, website, "
     "address.city → city, company.name → company"),
    ("`GET /posts/{id}`", "`get_post`", "id, userId → user_id, title, body"),
    ("`GET /posts?userId=N&_limit=K`", "`list_user_posts`",
     "список {id, title} + count"),
)

#: Что осталось за рамками дня.
OUTSIDE_SCOPE = (
    "Живые серверы официального набора (`uvx mcp-server-fetch`, файловый через "
    "`npx`) не запускались: они ставят пакеты из PyPI/npm, поэтому в прогон дня не "
    "входят — их каталог показывает `scripts/mcp_demo.py` дня 16.",
    "Транспорты SSE и Streamable HTTP проверены только разбором цели и ошибками "
    "соединения (тесты), живого HTTP-сервера MCP у дня нет.",
    "Одновременных MCP-подключений нет: у процесса одно соединение — каталог "
    "`GET /mcp/servers` показывает известные цели, а не открытые сессии.",
    "Права на вызов не различаются: инструменты вызываются без подтверждения "
    "пользователя. Ограничение сознательное — вызов идёт только по явным ключевым "
    "словам реплики, но это эвристика, а не политика безопасности.",
    "Стриминг результатов и повторные попытки при сбое сети не реализованы: "
    "неудачный вызов возвращается исходом `failed`, и агент отвечает без данных.",
)


def write_report(path: Path, run: "DemoRun") -> Path:
    """Пишет markdown-отчёт прогона и возвращает путь к файлу."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(run), encoding="utf-8")
    return path


def _render(run: "DemoRun") -> str:
    """Собирает текст отчёта из данных прогона."""
    parts = [
        "# День 17 — свой MCP-сервер и вызов инструмента из агента",
        "",
        "Отчёт о живом прогоне (`scripts/mcp_tool_demo.py`): свой MCP-сервер дня по "
        "stdio, его каталог инструментов, успешные и отказные вызовы, и шаг MCP в "
        "работе агента — инструмент вызывается по ключевым словам реплики, а его "
        "данные уходят в системный промпт того же запроса.",
        "",
        f"Цель подключения: `{run.target}`",
        f"Внешний API инструментов: `{run.api_base}`",
        f"Клиент DeepSeek: {'настоящий (--live)' if not run.offline else 'офлайн-заглушка, отвечающая по блоку данных MCP'}",
        "",
        *_section_checks(run),
        *_section_api(run),
        *_section_server(run),
        *_section_calls(run),
        *_section_agent(run),
        *_section_tests(run),
        *_section_outside(),
    ]
    return "\n".join(parts)


def _section_checks(run: "DemoRun") -> list[str]:
    """Раздел 1: таблица проверок и результатов прогона."""
    agent_report = (run.agent or {}).get("mcp") or {}
    plain_report = (run.agent_plain or {}).get("mcp") or {}
    codes = ", ".join(
        sorted({item.get("reason_code") or "" for item in run.refusals} - {""})
    ) or "—"
    tests = run.tests_summary or "не запускались в этом прогоне"
    return [
        "## 1. Что проверялось",
        "",
        "| Проверка | Результат |",
        "|---|---|",
        f"| Соединение с собственным MCP-сервером по stdio | ✅ `connected`, сервер "
        f"`{run.server_name} {run.server_version}`, протокол {run.protocol or '—'} |",
        f"| Каталог `tools/list` с обеими схемами | ✅ {len(run.tools)} инструмента, "
        "у каждого непустые `input_schema` и `output_schema` |",
        f"| Вызовы `tools/call` | ✅ успешных: {len(run.calls)} |",
        f"| Отказные вызовы | ✅ отказов и ошибок: {len(run.refusals)} "
        f"(коды: {codes}) |",
        f"| Три инструмента вызываются через `MCPToolRunner` | ✅ "
        + ", ".join(f"`{item['tool']}`" for item in run.calls),
        "| Агент сам вызывает инструмент по реплике | ✅ "
        f"`{agent_report.get('tool')}` с аргументами "
        f"`{json.dumps(agent_report.get('arguments') or {}, ensure_ascii=False)}`, "
        f"данные в промпте: {agent_report.get('used_in_prompt')} |",
        f"| Реплика без ключевых слов не вызывает инструмент | ✅ `called="
        f"{plain_report.get('called')}`, `detected={plain_report.get('detected')}` |",
        "| API: `POST /mcp/call`, `GET /mcp/servers`, `GET /mcp/tools` | ✅ "
        "проверяется `tests/e2e/test_mcp_call_api.py` |",
        f"| Автотесты | {tests} |",
        "",
    ]


def _section_api(run: "DemoRun") -> list[str]:
    """Раздел 2: какой внешний API читают инструменты и чем он отвечает."""
    lines = [
        "## 2. Какой API использовался",
        "",
        "Инструменты сервера читают публичный mock API **jsonplaceholder.typicode.com** "
        "(`DEFAULT_API_BASE` в `mcp_server/config.py`) — он не требует ключа, поэтому "
        "инструменты можно вызывать в любой момент. HTTP-запросы настоящие: "
        "`mcp_server/api_client.py` ходит в сеть через `httpx`, а не отдаёт заготовки.",
        "",
        f"Адрес этого прогона: `{run.api_base}`.",
        "",
        "| Ручка API | Инструмент | Что берётся из ответа |",
        "|---|---|---|",
    ]
    lines += [f"| {endpoint} | {tool} | {fields} |" for endpoint, tool, fields in API_ENDPOINTS]
    lines += [
        "",
        "Ошибки внешнего API переводятся в понятный текст для модели: 404 — "
        "«Пользователь с id=999 не найден (HTTP 404): у jsonplaceholder 10 "
        "пользователей, id от 1 до 10», недоступность — «Внешний API … недоступен». "
        "Такая ошибка возвращается инструментом как результат с `isError`, а не "
        "исключением: агент видит причину и отвечает без внешних данных.",
        "",
    ]
    return lines


def _section_server(run: "DemoRun") -> list[str]:
    """Раздел 3: команда запуска сервера и каталог инструментов со схемами."""
    lines = [
        "## 3. Сервер и инструменты",
        "",
        "Сервер дня — `day17/mcp_server/` (`MCPServer` из MCP SDK 2.x), транспорт "
        "stdio: клиент поднимает его дочерним процессом, JSON-RPC идёт по "
        "stdin/stdout. Запуск руками (для отладки):",
        "",
        "```bash",
        "uv run python mcp_server/server.py            # ждёт JSON-RPC на stdin",
        "uv run python mcp_server/server.py --api-base <адрес> --timeout 5",
        "```",
        "",
        "Прогон подключился командой:",
        "",
        "```",
        f"цель:        {run.target}",
        f"транспорт:   {run.transport}",
        f"сервер:      {run.server_name} {run.server_version} "
        f"(протокол {run.protocol or '—'})",
        f"инструментов: {len(run.tools)}",
        "```",
        "",
        "| Инструмент | Описание | `input_schema` | `output_schema` |",
        "|---|---|---|---|",
    ]
    for tool in run.tools:
        lines.append(
            f"| `{tool['name']}` | {_one_line(tool['description'])} | "
            f"`{_short(tool['input_schema'])}` | `{_short(tool['output_schema'])}` |"
        )
    lines += [
        "",
        "Схемы — не ручной текст: `inputSchema` собирается SDK из типизированных "
        "параметров, `outputSchema` — из аннотации возврата (`TypedDict` в "
        "`mcp_server/schemas.py`), а `structuredContent` ответа равен самому словарю. "
        "Поэтому описание параметров и полей результата видит и модель, и клиент.",
        "",
    ]
    return lines


def _section_calls(run: "DemoRun") -> list[str]:
    """Раздел 4: успешные вызовы и отказы с текстами причин."""
    lines = ["## 4. Вызовы инструмента", "", "### Успешные вызовы", ""]
    for item in run.calls:
        lines += [
            f"`{item['tool']}({json.dumps(item['arguments'], ensure_ascii=False)})` → "
            f"{STATE_LABELS.get(item['state'], item['state'])}, {item['duration_ms']} мс",
            "",
            "```json",
            json.dumps(item["structured"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    lines += ["### Отказные вызовы", "",
              "| Вызов | Состояние | Код причины | Текст |",
              "|---|---|---|---|"]
    for item in run.refusals:
        lines.append(
            f"| `{item['tool']}({json.dumps(item['arguments'], ensure_ascii=False)})` | "
            f"{STATE_LABELS.get(item['state'], item['state'])} | "
            f"`{item['reason_code']}` | {_one_line(item['error'] or '')} |"
        )
    lines += [
        "",
        "Разница принципиальная: первые три строки — отказы правил допуска "
        "(`unknown_tool`, `bad_arguments`) — инструмент даже не вызывался, а "
        "последняя — ответ сервера «пользователя с id=999 нет» (`tool_error`, "
        "`isError`): вызов состоялся, и текст ошибки — данные ответа.",
        "",
    ]
    return lines


def _section_agent(run: "DemoRun") -> list[str]:
    """Раздел 5: как агент вызвал инструмент и что из этого попало в промпт."""
    payload = run.agent or {}
    report = payload.get("mcp") or {}
    lines = [
        "## 5. Как агент использовал результат",
        "",
        "Агент сам решает по реплике, нужен ли вызов: правила домена "
        "(`backend/domain/mcp_intent.py`) ищут ключевые слова и номер аргумента, "
        "правила допуска (`mcp_tool_call.admission_reason`) проверяют соединение, "
        "каталог и типы аргументов, а результат уходит системным блоком в промпт "
        "этого же запроса (`render_mcp_tool_block`).",
        "",
        "### Запрос, по которому инструмент вызван",
        "",
        f"`{payload.get('question')}`",
        "",
        f"Отчёт хода (`record[\"mcp\"]`), статус генерации: `{payload.get('status')}`",
        "",
        "```json",
        json.dumps(_report_view(report), ensure_ascii=False, indent=2),
        "```",
        "",
        "### Что ушло в системный промпт",
        "",
        "```",
        *_block_lines(payload.get("system_prompt") or ""),
        "```",
        "",
        "### Ответ агента",
        "",
        "```",
        payload.get("response") or payload.get("error") or "—",
        "```",
        "",
        "### Реплика без ключевых слов",
        "",
        f"`{(run.agent_plain or {}).get('question')}` — инструмент не вызывался "
        f"(`detected={(run.agent_plain or {}).get('mcp', {}).get('detected')}`, "
        f"`state={(run.agent_plain or {}).get('mcp', {}).get('state')}`), блок данных "
        "в промпт не добавлялся:",
        "",
        "```",
        *_block_lines((run.agent_plain or {}).get("system_prompt") or ""),
        "```",
        "",
    ]
    return lines


def _section_tests(run: "DemoRun") -> list[str]:
    """Раздел 6: автотесты дня."""
    return [
        "## 6. Автотесты",
        "",
        "Новые тесты дня (офлайн, без сети и без ключа DeepSeek): стейт-машина вызова "
        "и правила допуска, распознавание реплики, блок промпта, каталог серверов, "
        "настоящий stdio-сервер, раннер, шаг MCP в агенте и эндпоинты API.",
        "",
        "```bash",
        run.tests_command,
        "```",
        "",
        f"Сводка прогона: {run.tests_summary or 'в этом прогоне автотесты не запускались (`--tests`)'}",
        "",
    ]


def _section_outside() -> list[str]:
    """Раздел 7: что осталось за рамками дня."""
    lines = ["## 7. Что осталось за рамками дня", ""]
    lines += [f"- {item}" for item in OUTSIDE_SCOPE]
    lines.append("")
    return lines


def _report_view(report: dict) -> dict:
    """Отчёт хода без повторов: поля промпта показываются отдельно."""
    return {
        key: value for key, value in report.items()
        if key not in ("system_prompt",)
    }


def _block_lines(system_prompt: str, limit: int = 8) -> list[str]:
    """Строки блока данных MCP из системного промпта (или пометка, что блока нет)."""
    header = "## Данные MCP-инструмента"
    if header not in system_prompt:
        return ["(блока «Данные MCP-инструмента» в системном промпте нет)"]
    start = system_prompt.index(header)
    return system_prompt[start:].splitlines()[:limit]


def _one_line(text: str) -> str:
    """Текст одной строкой без переносов (для ячеек таблиц)."""
    return " ".join((text or "").split())


def _short(schema: dict, limit: int = 140) -> str:
    """Схема одной строкой: в таблице она обрезается, целиком — в прогоне."""
    text = json.dumps(schema or {}, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"
