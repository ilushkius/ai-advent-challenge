"""Замер «до и после» для отчёта об оптимизации затрат на LLM (день 21).

Здесь только ИЗМЕРЕНИЕ: сценарий диалога и тяжёлой задачи собирается из реальных
текстов дня (профиль, инварианты, каталог инструментов, память, состояние задачи,
блоки результатов инструментов, артефакты прогонов), токены считает
``shared.token_counter``, деньги — формулы домена ``llm_cost``. Сеть и ключ DeepSeek
не нужны.

Модуль вынесен из ``cost_optimization_report.py``: там рендер отчёта, и вместе они
перевалили за лимит 400 строк. Соседи по прогонам дня разделены так же
(``indexing_scenarios.py`` и ``indexing_report.py``).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Скрипты лежат в day21/scripts/, а пакеты backend и shared — в корне дня
# и в корне репозитория: добавляем корень дня в sys.path (как другие скрипты дня).
DAY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for _path in (DAY_ROOT, SCRIPT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from backend.core import config  # noqa: E402
from backend.core.prompt_builder import PromptBuilder  # noqa: E402
from backend.domain.demo_invariants import DEMO_INVARIANTS  # noqa: E402
from backend.domain.invariant_prompt import render_invariants_block  # noqa: E402
from backend.domain.llm_cost import estimate_cost, prices_for, savings_summary  # noqa: E402
from backend.domain.profiles import PROFILE_HEADER  # noqa: E402
from shared.token_counter import count_tokens  # noqa: E402

#: Путь отчёта по умолчанию.
DEFAULT_REPORT = "docs/reports/cost_optimization.md"

#: Сколько запросов подряд имитируем: стабильный префикс кэшируется со второго.
REQUESTS = 6

#: Допущение: длина ответа ассистента (в токенах). Одинакова для «было» и «стало» —
#: иначе сравнение было бы про разную длину ответов, а не про стоимость одного хода.
ANSWER_TOKENS = 180

#: Допущение: предел ответа до оптимизации — лимит агента по умолчанию.
LEGACY_MAX_TOKENS = config.DEFAULT_MAX_TOKENS

#: Конфигурация флота дня: из неё берётся каталог инструментов для стабильного префикса.
FLEET_FILE = DAY_ROOT / "mcp_servers.json"

#: Артефакты дня для тяжёлой ноги: именно этот текст пакетная обработка отдаёт модели.
HEAVY_ARTIFACTS = ("orchestration_demo.md", "indexing_demo.md")

#: На каких ходах сценария агент получал данные инструментов (МCP/пайплайн/индекс):
#: шаг с инструментом бывает не в каждом ходу, и его блок дописывается в промпт
#: только на этих ходах — так и ведёт себя день.
TOOL_TURNS = (1, 4)

#: Типовые реплики диалога (текст реальный — вопросы, которые день умеет).
DIALOGUE = (
    "как устроена оркестрация MCP-серверов в этом проекте?",
    "а что делает реестр флота при маршрутизации вызова?",
    "покажи, как пайплайн передаёт данные между шагами",
    "чем отличается фиксированный чанкинг от структурного?",
    "какие метрики сравнения считает день 21?",
    "и как это влияет на стоимость запросов к модели?",
)

#: Блоки памяти и состояния задачи: типовые записи дня (объём — допущение).
WORKING_MEMORY = (
    "Рабочая память (задача: разобраться со стоимостью запросов):\n"
    "- цель: снизить расход токенов без изменения логики агентов\n"
    "- решение: стабильный префикс промпта + сжатие динамической части\n"
    "- открыто: замер экономии на реальных данных дня"
)
LONG_TERM_MEMORY = (
    "Долговременная память (что уже известно):\n"
    "- проект: ai-challenge, день 21 надстраивает день 20\n"
    "- индекс документов: FAISS + SQLite, две стратегии чанкинга\n"
    "- оркестрация: флот из трёх MCP-серверов, маршрутизация по инструменту\n"
    "- планировщик: APScheduler в процессе бэкенда"
)
SUMMARY_TEXT = (
    "Конспект предыдущей части диалога: обсуждали слои памяти агента, стратегии "
    "сжатия контекста и то, как конспект подставляется вместо старых реплик."
)
FACTS = {"проект": "ai-challenge", "день": "21", "формат ответа": "кратко"}
TASK_BLOCK = (
    "СОСТОЯНИЕ ЗАДАЧИ (день 13):\nТекущий этап: execution\nТекущий шаг: implement\n"
    "Ожидаемое действие: продолжить реализацию оптимизации\n"
    "Допустимые следующие этапы: validation, paused"
)

def real_mcp_block() -> str:
    """Блок данных MCP-инструмента, собранный НАСТОЯЩИМ рендерером дня.

    Рукописный блок врал бы в главном: реальный `render_mcp_tool_block` пишет JSON
    одной строкой (`json.dumps(..., sort_keys=True)`), то есть минифицировать в нём
    нечего. Проверять сжатие на «красивом» JSON значило бы показывать экономию,
    которой в дне нет.
    """
    from backend.domain.mcp_prompt import render_mcp_tool_block
    from backend.domain.mcp_tool_call import MCPToolCallOutcome, MCPToolCallState
    from backend.domain.mcp_tools import MCPToolResult

    payload = {
        "count": 5,
        "items": [
            {"id": index, "kind": "file" if index < 4 else "db",
             "title": title, "source": source,
             "content": text,
             "metadata": {"file": f"output/{name}.md", "format": "md"},
             "created_at": "2026-09-28T18:16:02+00:00"}
            for index, (title, source, name, text) in enumerate([
                ("demo-scenario", "search_server", "demo-scenario",
                 "Оркестрация флота MCP-серверов: реестр держит по соединению на сервер "
                 "и маршрутизирует вызов по имени инструмента."),
                ("pipeline_result", "data_server", "pipeline_result",
                 "Пайплайн композиции: search собирает элементы, summarize сводит их в "
                 "текст, save_to_file пишет файл."),
                ("indexing_demo", "search_server", "indexing_demo",
                 "Индексация документов: две стратегии чанкинга, эмбеддинги в FAISS, "
                 "метаданные чанков в SQLite."),
                ("scheduler_demo", "data_server", "scheduler_demo",
                 "Планировщик фоновых задач: метаданные задач лежат в SQLite, поэтому "
                 "задачи переживают перезапуск."),
                ("run-success", "storage_server", "run-success",
                 "Строка в базе сервера хранения о успешном прогоне сценария."),
            ])
        ],
    }
    result = MCPToolResult(tool="list_saved", arguments={"kind": "all"},
                           structured=payload, text="", is_error=False, duration_ms=12)
    outcome = MCPToolCallOutcome(state=MCPToolCallState.DONE, detected=True,
                                 connected=True, accepted=True, tool="list_saved",
                                 arguments={"kind": "all"}, result=result)
    return render_mcp_tool_block(outcome)


def real_rag_block() -> str:
    """Блок поиска по индексу: НАСТОЯЩИЕ чанки документов дня и настоящий рендерер."""
    from backend.domain.chunking import ChunkStrategy
    from backend.domain.document_sources import Document
    from backend.domain.indexing_prompt import render_index_block
    from backend.services.chunker import chunk_document

    base = DAY_ROOT / "documents"
    if not base.exists():
        return ""
    hits: list[dict] = []
    for path in sorted(base.glob("*.md"))[:3]:
        text = path.read_text(encoding="utf-8", errors="replace")
        document = Document(source=path.name, path=path, title=path.stem, kind="readme",
                            language="ru", text=text, chars=len(text),
                            truncated="<!-- документ усечён -->" in text)
        chunks = chunk_document(document, ChunkStrategy.STRUCTURAL)
        for chunk in chunks[:2]:
            hits.append({"source": chunk.source, "section": chunk.section,
                         "score": 0.57, "content": chunk.content,
                         "preview": chunk.content[:300]})
    return render_index_block(hits[:5])


def compression_scope(builder: PromptBuilder) -> dict:
    """Где сжатие реально работает: документ с маркером усечения и JSON в заборе.

    Блоки инструментов дня уже компактны (JSON одной строкой), поэтому сжатие в них
    экономит считаные токены. Механизм рассчитан на другой материал, и это честно
    показать отдельным замером: текст документа дня (с маркером усечения-комментарием
    и рыхлыми пробелами) и JSON в ограждении — ровно то, что описано в правилах
    сжатия.
    """
    import json as json_module

    base = DAY_ROOT / "documents"
    text = ""
    for path in sorted(base.glob("*.md"))[:2] if base.exists() else []:
        text += path.read_text(encoding="utf-8", errors="replace") + "\n\n"
    fenced = ("Метрики прогона:\n```json\n" + json_module.dumps(
        {"fixed": {"chunks": 127, "tokens_avg": 396.6},
         "structural": {"chunks": 156, "tokens_avg": 298.6},
         "comparison": [["чанков", "127", "156", "окно против секций"]]},
        ensure_ascii=False, indent=4) + "\n```\n")
    material = text + fenced
    before = count_tokens(material)
    after = count_tokens(builder.compressor.compress(material))
    return {"tokens_before": before, "tokens_after": after,
            "saved_tokens": max(0, before - after),
            "saved_percent": round((before - after) / before * 100, 1) if before else 0.0}


def fleet_catalog() -> str:
    """Каталог инструментов флота из ``mcp_servers.json`` (пусто — файла нет).

    Читается тот же файл, по которому работает приложение: описания инструментов в
    стабильном префиксе — это реальные тексты дня, а не выдумка для отчёта.
    """
    if not FLEET_FILE.exists():
        return ""
    try:
        payload = json.loads(FLEET_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    specs = payload.get("servers") if isinstance(payload, dict) else payload
    if not isinstance(specs, list):
        return ""
    lines: list[str] = []
    for spec in specs:
        tools = spec.get("tools_cache") or []
        if not tools:
            continue
        lines.append(f"Сервер {spec.get('name')}:")
        for tool in tools:
            description = str(tool.get("description") or "").split(".")[0]
            lines.append(f"- {tool['name']}: {description}")
    return ("Доступные MCP-инструменты (вызов через раздел MCP):\n" + "\n".join(lines)
            if lines else "")


def demo_profile_block() -> str:
    """Блок профиля пользователя — так его собирает день 12."""
    return (
        f"{PROFILE_HEADER}\n"
        "Обращайся к пользователю по имени: Инженер.\n"
        "Стиль: технический, кратко, plain text.\n"
        "Ограничения пользователя (выполняй буквально):\n"
        "- Отвечай не длиннее 600 символов\n"
        "Дополнительные инструкции пользователя (выполняй буквально):\n"
        "- Всегда предлагай два варианта решения"
    )


def scenario_blocks() -> tuple[dict, list[str]]:
    """Стабильные части и динамические блоки сценария диалога."""
    stable = {
        "profile": demo_profile_block(),
        "system": "Ты — ассистент проекта ai-challenge. Отвечай по существу.",
        "invariants": render_invariants_block(DEMO_INVARIANTS),
        "tools": fleet_catalog(),
        "examples": config.PROMPT_EXAMPLES,
        "general": config.PROMPT_GENERAL_INSTRUCTIONS,
    }
    dynamic = [
        WORKING_MEMORY, LONG_TERM_MEMORY, SUMMARY_TEXT,
        "Известные факты диалога:\n" + "\n".join(
            f"- {key}: {value}" for key, value in sorted(FACTS.items())),
        TASK_BLOCK,
    ]
    return stable, dynamic


def legacy_system_text(stable: dict, dynamic: list[str]) -> str:
    """Собрать системный промпт так, как это делалось ДО дня 21.

    Порядок тот же (профиль → промпт агента → инварианты → память → конспект →
    факты → задача → данные инструментов), но без сжатия, без разделения на зоны и
    без строки о пределе длины ответа: именно это и было «до».
    """
    parts = [stable["profile"], stable["system"], stable["invariants"],
             stable["tools"], *dynamic]
    return "\n\n".join(part for part in parts if part)


def dialogue_measure(builder: PromptBuilder) -> dict:
    """Нога «диалог»: несколько запросов подряд с растущей историей."""
    stable, dynamic = scenario_blocks()
    builder.reset()
    legacy_cost = 0.0
    new_cost = 0.0
    legacy_tokens = 0
    new_tokens = 0
    saved_tokens = 0
    cache_hit_tokens = 0
    stable_tokens = 0
    max_tokens = 0
    for index, question in enumerate(DIALOGUE[:REQUESTS]):
        history = [{"role": "user" if turn % 2 == 0 else "assistant",
                    "content": DIALOGUE[turn]} for turn in range(index)]
        # На ходах с шагом инструмента к динамической части добавляются его блоки.
        turn_dynamic = list(dynamic)
        if index in TOOL_TURNS:
            turn_dynamic = [*dynamic, real_mcp_block(), real_rag_block()]
        legacy_text = legacy_system_text(stable, turn_dynamic)
        built = builder.build(**stable, dynamic=turn_dynamic, user_query=question,
                              history=history, task_type=config.LLM_TASK_CHAT,
                              max_response_tokens=LEGACY_MAX_TOKENS)
        model = config.LLM_TASK_MODELS[config.LLM_TASK_CHAT]
        history_tokens = sum(count_tokens(item["content"])
                             for item in built["messages"][1:])
        legacy_tokens_i = count_tokens(legacy_text) + history_tokens
        new_tokens_i = count_tokens(str(built["system"])) + history_tokens
        legacy_cost += estimate_cost(model=model, prompt_tokens=legacy_tokens_i,
                                     completion_tokens=ANSWER_TOKENS)
        # «Стало»: стабильный префикс со второго запроса приходит из кэша контекста.
        hit = min(int(built["stable_tokens"]), new_tokens_i) if built["cache_hit"] else 0
        new_cost += estimate_cost(model=model, prompt_tokens=new_tokens_i,
                                  completion_tokens=ANSWER_TOKENS,
                                  cache_hit_tokens=hit)
        legacy_tokens += legacy_tokens_i
        new_tokens += new_tokens_i
        saved_tokens += int(built["saved_tokens"])
        cache_hit_tokens += hit
        stable_tokens = int(built["stable_tokens"])
        max_tokens = int(built["max_tokens"])
    return {
        "model": config.LLM_TASK_MODELS[config.LLM_TASK_CHAT],
        "legacy_cost": round(legacy_cost, 6),
        "new_cost": round(new_cost, 6),
        "legacy_tokens": legacy_tokens,
        "new_tokens": new_tokens,
        "saved_tokens": saved_tokens,
        "cache_hit_tokens": cache_hit_tokens,
        "stable_tokens": stable_tokens,
        "max_tokens": max_tokens,
        "build_stats": builder.stats(),
    }


def heavy_measure(builder: PromptBuilder) -> dict:
    """Нога «тяжёлая задача»: пакетная обработка реальных артефактов дня.

    Меряются два рычага сразу — сжатие динамического блока и перенос в непиковые
    часы. Скидка провайдера — допущение, поэтому она показана отдельной строкой.
    """
    model = config.LLM_TASK_MODELS[config.LLM_TASK_INDEXING]
    text = "\n".join(
        (DAY_ROOT / "docs" / "reports" / name).read_text(encoding="utf-8", errors="replace")
        for name in HEAVY_ARTIFACTS
        if (DAY_ROOT / "docs" / "reports" / name).exists()
    )
    tokens_before = count_tokens(text) if text else 0
    tokens_after = count_tokens(builder.compressor.compress(text)) if text else 0
    discount = int(config.OFF_PEAK_DISCOUNT_PERCENT)
    cost_before = estimate_cost(model=model, prompt_tokens=tokens_before,
                                completion_tokens=ANSWER_TOKENS)
    cost_after = estimate_cost(model=model, prompt_tokens=tokens_after,
                               completion_tokens=ANSWER_TOKENS) * (100 - discount) / 100
    return {
        "model": model,
        "files": sum(1 for name in HEAVY_ARTIFACTS
                     if (DAY_ROOT / "docs" / "reports" / name).exists()),
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "compressed_tokens": max(0, tokens_before - tokens_after),
        "cost_before": round(cost_before, 6),
        "cost_after": round(cost_after, 6),
        "discount_percent": discount,
    }


def measure(builder: PromptBuilder) -> dict:
    """Полный замер: обе ноги нагрузки плюс сводка рычагов."""
    dialogue = dialogue_measure(builder)
    heavy = heavy_measure(builder)
    summary = savings_summary(
        model=dialogue["model"],
        prompt_tokens=dialogue["legacy_tokens"],
        completion_tokens=0,
        cache_hit_tokens=dialogue["cache_hit_tokens"],
        compressed_tokens=dialogue["saved_tokens"],
        max_response_tokens=dialogue["max_tokens"],
        off_peak_share=0.0,
    )
    # Вклад непика считаем по тяжёлой ноге: это та нагрузка, которую планировщик
    # переносит в дешёвое окно флагом `prefer_off_peak`.
    compression = compression_scope(builder)
    summary["off_peak"] = {
        "discount_percent": heavy["discount_percent"],
        "saving": round(heavy["cost_before"] - heavy["cost_after"], 6),
    }
    return {
        "dialogue": dialogue,
        "heavy": heavy,
        "summary": summary,
        "compression": compression,
        "requests": REQUESTS,
        "answer_tokens": ANSWER_TOKENS,
        "legacy_max_tokens": LEGACY_MAX_TOKENS,
    }


