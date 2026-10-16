"""Инвентарь эндпоинтов дня для корневой точки ``GET /`` (вынесен в день 35).

Данные, а не разметка маршрутов: список групп и полный перечень эндпоинтов нужен
человеку, который открыл корень API, и он никак не участвует в маршрутизации. До дня 35
словарь жил прямо в теле ``root()`` (``backend/api/agents.py``), но файл упёрся в лимит
400 строк: день 35 добавил шесть своих эндпоинтов в перечень и группу дня 34, которая
там отсутствовала (её пропустили), — и словарь переехал сюда целиком.

Ключи словаря: ``name``/``docs`` — что это за приложение, дальше по группе на домен
(``agents``, ``memory``, ``scheduler``, ``indexing``, ``llm``, ``rag`` и так далее) со
строкой-перечислением эндпоинтов, и ``endpoints`` — полный список «МЕТОД /путь».
Группы и список описывают ОДНО И ТО ЖЕ, поэтому при добавлении эндпоинта правятся оба
места: список читают тесты (``tests/e2e/test_api.py`` ищет в нём конкретные пути) и он
же отвечает на вопрос «что здесь вообще есть».

Роутер остаётся точкой входа: ``backend/api/agents.py`` импортирует ``APP_INFO`` и
возвращает его из ``GET /`` — поведение прежнее, меняется только место хранения данных.
"""
from __future__ import annotations

__all__ = ["APP_INFO"]

#: Ответ корневой точки ``GET /``: имя приложения, группы эндпоинтов по доменам и
#: их полный перечень (тот же текст, что отдавался из ``root()`` до дня 35).
APP_INFO = {
    "name": "Агенты DeepSeek с индексацией документов и RAG — День 24",
    "docs": "/docs",
    "memory": "/agents/{agent_id}/memory/... (short-term | working | long-term)",
    "personalization": "/users, /users/{user_id}/profile, /agents/{agent_id}/profile",
    "tasks": "/agents/{agent_id}/tasks, /tasks/{task_id}/state, ... (11 эндпоинтов)",
    "task_transitions": "/tasks/{task_id}/transition, /tasks/{task_id}/allowed-next, /tasks/{task_id}/context",
    "invariants": "/invariants, /invariants/{invariant_id}, /invariants/check (6 эндпоинтов)",
    "mcp": ("/mcp/connect, /mcp/disconnect, /mcp/status, /mcp/tools, "
            "/mcp/call (5 эндпоинтов — активное соединение раздела «MCP»)"),
    "mcp_servers": ("/mcp/servers, /mcp/servers/{name}/tools, "
                    "/mcp/servers/refresh (3 эндпоинта — флот серверов)"),
    "scheduler": ("/scheduler/tasks, /scheduler/tasks/{task_id}/pause|resume|run|history, "
                  "/scheduler/tools, /scheduler/status, /scheduler/reminders, "
                  "/scheduler/collected, /scheduler/summaries, /scheduler/notifications "
                  "(14 эндпоинтов)"),
    "pipelines": ("/pipelines/run, /pipelines/runs, /pipelines/runs/{run_id}, "
                  "/pipelines/runs/{run_id}/steps, /pipelines/runs/{run_id} "
                  "(5 эндпоинтов)"),
    "orchestration": ("/orchestration/run, /orchestration/demo, "
                      "/orchestration/runs, /orchestration/runs/{run_id}, "
                      "/orchestration/runs/{run_id}/steps, "
                      "DELETE /orchestration/runs/{run_id} (6 эндпоинтов)"),
    "indexing": ("POST /indexing/run, POST /indexing/demo, GET /indexing/status, "
                 "GET /indexing/stats, GET /indexing/search, GET /indexing/chunks, "
                 "GET /indexing/runs, GET /indexing/runs/{run_id}, "
                 "POST /indexing/clear (9 эндпоинтов)"),
    "llm": ("/llm/usage, /llm/status, /llm/estimate, /llm/models, /llm/peak, "
            "/llm/provider, /llm/local-demo, /llm/tune (8 эндпоинтов — журнал "
            "расходов, кэш контекста, непиковые часы, провайдер, демо локальной "
            "модели и оптимизация её профилей)"),
    "remote_llm": ("GET /llm/remote-config, POST /llm/remote/check, "
                   "POST /llm/remote/step (3 эндпоинта — удалённая LLM в Google "
                   "Colab: настройки раздела, проверка соединения по туннелю и "
                   "шаг демо одной кнопкой)"),
    "rag": ("POST /rag/query, GET /rag/config, POST /rag/compare, "
            "POST /rag/compare_modes, GET /rag/demo-questions, POST /rag/demo-run, "
            "POST /rag/compare_providers "
            "(7 эндпоинтов — поиск по корпусу, режим без RAG, сравнение ответов, "
            "сравнение режимов отбора, вопросы демо, прогон демо, сравнение "
            "провайдеров)"),
    "mini_chat": ("POST /mini-chat/sessions, "
                  "POST /mini-chat/sessions/{session_id}/messages, "
                  "GET /mini-chat/sessions/{session_id}/memory, "
                  "GET /mini-chat/sessions/{session_id}/history, "
                  "DELETE /mini-chat/sessions/{session_id} "
                  "(5 эндпоинтов — мини-чат с RAG и памятью задачи)"),
    "dev_assistant": ("POST /dev-assistant/help, GET /dev-assistant/tools, "
                      "GET /dev-assistant/git-context (3 эндпоинта — ассистент "
                      "разработчика: ответ по документации проекта и состоянию "
                      "репозитория через свой MCP-сервер dev_server)"),
    "code_review": ("POST /review/pr, GET /review/health, POST /review/github-pr, "
                    "GET /review/github-health (4 эндпоинта — AI-ревью PR: diff и "
                    "файлы из запроса или через MCP, либо из GitHub REST API по URL "
                    "и номеру PR; контекст корпуса RAG, структурированное ревью и "
                    "публикация комментария)"),
    "support": ("POST /support/ask, GET /support/users, "
                "GET /support/users/{user_id}, GET /support/tickets, "
                "GET /support/tickets/{ticket_id} (5 эндпоинтов — ассистент "
                "поддержки: FAQ и документация поддержки из корпуса RAG плюс "
                "профиль клиента и его тикет через свой MCP-сервер "
                "support_server)"),
    "file_assistant": ("POST /file-assistant/execute, GET /file-assistant/history, "
                       "GET /file-assistant/diff/{run_id} (3 эндпоинта — ассистент "
                       "файлов: цель в план шагов и исполнение через свой MCP-сервер "
                       "file_server с diff-ом прогона)"),
    "release": ("POST /release/prepare, GET /release/tags, GET /release/health, "
                "GET /release/metrics, GET /release/history, POST /release/export "
                "(6 эндпоинтов — подготовка релиза: версия по коммитам диапазона, "
                "раздел CHANGELOG, проверки готовности, выгрузка и запись файлов "
                "через MCP)"),
    "endpoints": [
        "POST /agents", "GET /agents", "GET /agents/{agent_id}",
        "PATCH /agents/{agent_id}", "DELETE /agents/{agent_id}",
        "POST /agents/{agent_id}/generate",
        "GET /agents/{agent_id}/history",
        "DELETE /agents/{agent_id}/history",
        "POST /agents/{agent_id}/summarize",
        "GET /agents/{agent_id}/summary",
        "POST /agents/{agent_id}/compare",
        "GET /agents/{agent_id}/usage",
        "GET /agents/{agent_id}/usage/graph",
        "POST /agents/{agent_id}/strategy",
        "GET /agents/{agent_id}/strategies",
        "POST /agents/{agent_id}/branches",
        "GET /agents/{agent_id}/branches",
        "POST /agents/{agent_id}/branches/{branch_id}/switch",
        "GET /agents/{agent_id}/facts",
        "POST /agents/{agent_id}/memory/short-term",
        "GET /agents/{agent_id}/memory/short-term",
        "DELETE /agents/{agent_id}/memory/short-term",
        "POST /agents/{agent_id}/memory/working",
        "GET /agents/{agent_id}/memory/working",
        "POST /agents/{agent_id}/memory/long-term",
        "GET /agents/{agent_id}/memory/long-term",
        "DELETE /agents/{agent_id}/memory/long-term/{entry_id}",
        "POST /agents/{agent_id}/memory/session",
        "PUT /agents/{agent_id}/memory/task",
        "GET /users",
        "GET /users/{user_id}/profile",
        "POST /users/{user_id}/profile",
        "PUT /users/{user_id}/profile",
        "DELETE /users/{user_id}/profile",
        "GET /agents/{agent_id}/profile",
        "POST /agents/{agent_id}/tasks",
        "GET /agents/{agent_id}/tasks",
        "GET /tasks/{task_id}/state",
        "GET /tasks/{task_id}/history",
        "GET /tasks/{task_id}/allowed-next",
        "PATCH /tasks/{task_id}/context",
        "POST /tasks/{task_id}/pause",
        "POST /tasks/{task_id}/resume",
        "POST /tasks/{task_id}/advance",
        "POST /tasks/{task_id}/rollback",
        "POST /tasks/{task_id}/transition",
        "POST /invariants",
        "GET /invariants",
        "GET /invariants/{invariant_id}",
        "PUT /invariants/{invariant_id}",
        "DELETE /invariants/{invariant_id}",
        "POST /invariants/check",
        "POST /mcp/connect",
        "POST /mcp/disconnect",
        "GET /mcp/status",
        "GET /mcp/tools",
        "POST /mcp/call",
        "GET /mcp/servers",
        "GET /mcp/servers/{name}/tools",
        "POST /mcp/servers/refresh",
        "GET /scheduler/tasks",
        "POST /scheduler/tasks",
        "DELETE /scheduler/tasks/{task_id}",
        "POST /scheduler/tasks/{task_id}/pause",
        "POST /scheduler/tasks/{task_id}/resume",
        "POST /scheduler/tasks/{task_id}/run",
        "GET /scheduler/tasks/{task_id}/history",
        "GET /scheduler/tools",
        "GET /scheduler/status",
        "GET /scheduler/reminders",
        "GET /scheduler/collected",
        "GET /scheduler/summaries",
        "GET /scheduler/notifications",
        "POST /scheduler/notifications/{notification_id}/read",
        "POST /pipelines/run",
        "GET /pipelines/runs",
        "GET /pipelines/runs/{run_id}",
        "GET /pipelines/runs/{run_id}/steps",
        "DELETE /pipelines/runs/{run_id}",
        "POST /orchestration/run",
        "POST /orchestration/demo",
        "GET /orchestration/runs",
        "GET /orchestration/runs/{run_id}",
        "GET /orchestration/runs/{run_id}/steps",
        "DELETE /orchestration/runs/{run_id}",
        "POST /indexing/run",
        "POST /indexing/demo",
        "GET /indexing/status",
        "GET /indexing/stats",
        "GET /indexing/search",
        "GET /indexing/chunks",
        "GET /indexing/runs",
        "GET /indexing/runs/{run_id}",
        "POST /indexing/clear",
        "GET /llm/usage",
        "GET /llm/status",
        "POST /llm/estimate",
        "GET /llm/models",
        "GET /llm/peak",
        "GET /llm/provider",
        "POST /llm/local-demo",
        "POST /llm/tune",
        "GET /llm/remote-config",
        "POST /llm/remote/check",
        "POST /llm/remote/step",
        "POST /rag/query",
        "GET /rag/config",
        "POST /rag/compare",
        "POST /rag/compare_modes",
        "POST /rag/compare_providers",
        "GET /rag/demo-questions",
        "POST /rag/demo-run",
        "POST /mini-chat/sessions",
        "POST /mini-chat/sessions/{session_id}/messages",
        "GET /mini-chat/sessions/{session_id}/memory",
        "GET /mini-chat/sessions/{session_id}/history",
        "DELETE /mini-chat/sessions/{session_id}",
        "POST /dev-assistant/help",
        "GET /dev-assistant/tools",
        "GET /dev-assistant/git-context",
        "POST /review/pr",
        "GET /review/health",
        "POST /review/github-pr",
        "GET /review/github-health",
        "POST /support/ask",
        "GET /support/users",
        "GET /support/users/{user_id}",
        "GET /support/tickets",
        "GET /support/tickets/{ticket_id}",
        "POST /file-assistant/execute",
        "GET /file-assistant/history",
        "GET /file-assistant/diff/{run_id}",
        "POST /release/prepare",
        "GET /release/tags",
        "GET /release/health",
        "GET /release/metrics",
        "GET /release/history",
        "POST /release/export",
    ],
}
