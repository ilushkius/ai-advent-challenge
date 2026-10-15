"""Ассистент файлов (день 34): словарь дня — инструменты, промпты, статусы, сценарии.

Что делает день. Пользователь ставит ЦЕЛЬ («найди все места, где используется
``IndexService``», «обнови ``docs/usage.md``», «сгенерируй ADR»), а не команду
«открой файл X». Из цели рождается план вызовов инструментов файлового сервера,
план исполняется, и пользователь получает отчёт: что прочитано, что найдено, что
изменено и какой получился diff.

Три модуля домена делят эту работу по смыслу:

- ``file_assistant.py`` (этот) — СЛОВАРЬ: имена инструментов и их каталог для
  промпта, статусы прогона и шага, границы плана, тексты промптов, причины отказов,
  формулировки вердикта и сценарии демо-прогона. Никакой логики: здесь только то,
  о чём договорились служба, сервер, роутер, раздел интерфейса и отчёт;
- ``file_assistant_plan.py`` — ПРАВИЛА ПЛАНА: разбор ответа модели, валидация шагов,
  проверка путей, маркер ``$generate`` и вторая фаза (разрешение аргументов);
- ``file_assistant_report.py`` — ЖУРНАЛ И ВЕРДИКТ: текст журнала шагов для промпта и
  отчёта, предполагаемый diff для ``dry_run`` и вердикт строки прогона.

Почему каталог инструментов задаётся данными, а не читается у сервера. План обязан
быть воспроизводимым: промпт планировщика с одним и тем же текстом попадает в кэш
контекста DeepSeek, и прогоны сравнимы. Каталог из ``TOOL_DESCRIPTIONS`` — часть
этого текста, поэтому он лежит рядом с промптом, а расхождение с сервером ловит
интеграционный тест (он сверяет имена инструментов с настоящим каталогом).

Почему план в две фазы. Текст правки нельзя назвать до выполнения предыдущих шагов:
чтобы вставить раздел в ``docs/usage.md``, нужно сначала прочитать файл и выбрать
якорь, а чтобы пропатчить найденный файл — знать путь из результатов поиска. Поэтому
первая фаза отдаёт только СКЕЛЕТ плана, а на месте неизвестных аргументов стоит
маркер ``GENERATE_MARK``; вторая фаза подставляет конкретные значения, когда
результаты уже есть.
"""
from __future__ import annotations

from typing import Iterable

#: Идентификатор в журнале расходов (``llm_usage``): вызовы ассистента файлов
#: видны отдельной строкой, а не как «чат».
AGENT_ID = "files"

#: Имя сервера и цель MCP-подключения: свой stdio-сервер дня, а не флот дня 20 из
#: ``mcp_servers.json`` (там остаются три сервера, и их раздел не меняется).
FILE_SERVER_NAME = "file_server"
FILE_SERVER_TARGET = "uv run python mcp_servers/file_server/server.py"

#: Имена инструментов сервера ``file_server``: они уходят в ``tools/call`` и
#: показываются в разделе интерфейса.
TOOL_READ_FILE = "read_file"
TOOL_SEARCH_IN_FILES = "search_in_files"
TOOL_LIST_FILES = "list_files"
TOOL_WRITE_FILE = "write_file"
TOOL_APPLY_PATCH = "apply_patch"
TOOL_GET_FILE_DIFF = "get_file_diff"
TOOLS = (TOOL_READ_FILE, TOOL_SEARCH_IN_FILES, TOOL_LIST_FILES,
         TOOL_WRITE_FILE, TOOL_APPLY_PATCH, TOOL_GET_FILE_DIFF)
#: Инструменты, меняющие файлы: только они подчиняются ``dry_run`` и формируют
#: ``files_modified``/``files_created``.
WRITE_TOOLS = (TOOL_WRITE_FILE, TOOL_APPLY_PATCH)
#: Инструменты, которые ничего не меняют: читают содержимое, ищут образец, смотрят
#: каталог и diff. Список задан явно, а не «все остальные»: новая операция чтения
#: обязана попасть сюда, а не оказаться записанной в файлы.
READ_TOOLS = (TOOL_READ_FILE, TOOL_SEARCH_IN_FILES, TOOL_LIST_FILES,
              TOOL_GET_FILE_DIFF)
#: Инструменты с обязательным аргументом ``directory`` (у остальных обязателен ``path``).
DIRECTORY_TOOLS = (TOOL_LIST_FILES, TOOL_SEARCH_IN_FILES)

#: Каталог инструментов для промпта планировщика и подписей UI: одна строка на
#: инструмент — что делает и какие аргументы принимает. Отдельно от докстрингов
#: сервера, потому что здесь текст ПЛАНА: модели нужно ровно то, без чего шаг не
#: собрать.
TOOL_DESCRIPTIONS = {
    TOOL_READ_FILE: "прочитать файл проекта: path, max_bytes (по умолчанию 100000)",
    TOOL_SEARCH_IN_FILES: "найти образец по файлам каталога: pattern, directory, "
                          "file_glob (по умолчанию *.py)",
    TOOL_LIST_FILES: "перечислить имена файлов каталога: directory, extension",
    TOOL_WRITE_FILE: "записать файл целиком: path, content, mode (overwrite|append)",
    TOOL_APPLY_PATCH: "заменить первый фрагмент в файле: path, old_text, new_text",
    TOOL_GET_FILE_DIFF: "показать diff файла относительно HEAD: path",
}

#: Маркер аргумента, который нельзя назвать до выполнения предыдущих шагов.
GENERATE_MARK = "$generate"

#: Статусы прогона: ``dry_run`` — план выполнен без правок файлов.
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_DRY_RUN = "dry_run"

#: Статусы шага: ``skipped`` — шаг не выполнялся (прогон остановлен на сбое) или
#: выполнялся только «на бумаге» (``dry_run``).
STEP_OK = "ok"
STEP_FAILED = "failed"
STEP_SKIPPED = "skipped"

#: Границы плана и выдачи.
FILE_PLAN_MAX_STEPS = 12
HISTORY_LIMIT = 20
MAX_PATH_CHARS = 240
#: Сколько символов результата одного шага уходит в промпт разрешения аргументов и
#: в отчёт: длинный ``read_file`` в контекст целиком не влезает.
CONTEXT_STEP_CHARS = 1500
#: Предел всего контекста разрешения аргументов и сводки.
MAX_CONTEXT_CHARS = 12000
#: Попытки разбора JSON-плана и разрешения аргументов: вторая попытка идёт с
#: подсказкой о том, что именно не разобралось.
MAX_GENERATE_ATTEMPTS = 2
#: Причина внутреннего шага чтения: служба читает файл сама, чтобы дать модели
#: текущее содержимое перед правкой, и это должно быть видно в журнале.
INTERNAL_READ_REASON = "внутренний шаг: текущее содержимое файла перед изменением"

#: Системная инструкция планировщика: правила формата и дисциплины путей.
PLAN_SYSTEM_PROMPT = (
    "Ты — планировщик вызовов MCP-инструментов файлового сервера проекта. "
    "По цели пользователя составь план шагов и ответь ТОЛЬКО объектом JSON, без "
    "markdown и без пояснений.\n"
    "Формат ответа: {\"steps\": [{\"step_index\": 0, \"tool\": \"<имя>\", "
    "\"arguments\": {...}, \"reason\": \"<зачем шаг>\"}]}.\n"
    "Правила: (1) step_index идут с нуля и подряд; (2) tool — только имя из "
    "каталога инструментов; (3) пути относительны корня проекта (day21/), а "
    "каталог для поиска и списка файлов указывай как \".\"; (4) аргументы давай "
    "такими, какими их ждёт инструмент: pattern в search_in_files — регулярное "
    "выражение Python, поэтому спецсимволы в нём экранируй (для поиска вызова — "
    "\"IndexService\\\\(\", для простого имени — \"IndexService\"); (5) прежде чем "
    "менять файл, прочитай его; (6) аргумент, который нельзя назвать до выполнения "
    "предыдущих шагов (текст нового раздела, старый фрагмент для apply_patch, путь, "
    f"который вернёт поиск), записывай строкой \"{GENERATE_MARK}\"; (7) не "
    "выдумывай содержимое файлов — то, чего не знаешь, оставляй маркером; "
    f"(8) в плане не больше {FILE_PLAN_MAX_STEPS} шагов."
)

#: Подсказка-пример ответа (уходит в пользовательское сообщение).
PLAN_JSON_HINT = (
    "Пример ответа для цели «добавь раздел в docs/usage.md»:\n"
    "{\"steps\": ["
    "{\"step_index\": 0, \"tool\": \"read_file\", "
    "\"arguments\": {\"path\": \"docs/usage.md\"}, "
    "\"reason\": \"увидеть структуру файла и выбрать якорь\"}, "
    "{\"step_index\": 1, \"tool\": \"apply_patch\", "
    f"\"arguments\": {{\"path\": \"docs/usage.md\", \"old_text\": \"{GENERATE_MARK}\", "
    f"\"new_text\": \"{GENERATE_MARK}\"}}, "
    "\"reason\": \"вставить новый раздел перед разделом частых ошибок\"}"
    "]}"
)

#: Подсказка ко второй попытке: ответ модели не разобран.
PLAN_RETRY_HINT = "Предыдущий ответ не разобран. Верни строго JSON без markdown."

#: Системная инструкция второй фазы: подставить конкретные аргументы вместо маркера.
GENERATE_SYSTEM_PROMPT = (
    "Ты — исполнитель плана файловых операций. Для указанных шагов подставь "
    "конкретные значения аргументов вместо маркера "
    f"\"{GENERATE_MARK}\" и ответь ТОЛЬКО объектом JSON: "
    "{\"steps\": [{\"step_index\": <номер шага>, \"arguments\": {...}}]}.\n"
    "Правила: (1) old_text бери ДОСЛОВНО из прочитанного содержимого файла — это "
    "якорь замены, и он должен встречаться в файле буквально; (2) пути бери из "
    "результатов поиска и списка файлов, а не придумывай; (3) новый текст пиши так, "
    "чтобы файл остался корректным целиком (тот же язык, тот же стиль заголовков); "
    "(4) в ответе перечисли ВСЕ запрошенные номера шагов."
)

#: Системная инструкция сводки: отчёт по журналу, без вымысла.
SUMMARY_SYSTEM_PROMPT = (
    "Ты — ассистент файлов проекта. По журналу выполненного плана и его diff-у "
    "кратко отчитайся пользователю: что прочитано, что найдено (с путями и номерами "
    "строк), что создано и что изменено. Опирайся ТОЛЬКО на журнал и diff: не "
    "выдумывай ни файлов, ни строк, которых в них нет. Пиши по-русски, коротко, "
    "списком, и назови пути файлов."
)

REASON_EMPTY_GOAL = "Пустая цель: опишите, что нужно сделать с файлами проекта"
REASON_BAD_JSON = "План не разобран как JSON"
REASON_EMPTY_PLAN = "План пуст: ни одного шага"
REASON_NOT_OBJECT = "План должен быть объектом JSON, а не {kind}"
REASON_UNKNOWN_TOOL = "шаг {index}: неизвестный инструмент «{tool}»"
REASON_BAD_ARGS = "шаг {index}: аргументы должны быть объектом JSON"
REASON_BAD_INDEX = "шаг {index}: номера шагов должны идти подряд с нуля"
REASON_TOO_MANY_STEPS = "в плане не больше {limit} шагов, получено {count}"
REASON_BAD_PATH = "шаг {index}: путь вне проекта или не относительный: {path}"
REASON_MISSING_PATH = "шаг {index}: у инструмента {tool} нет аргумента path"
REASON_MISSING_DIRECTORY = ("шаг {index}: у инструмента {tool} нет аргумента "
                            "directory")
REASON_GENERATE_FAILED = "шаг {index}: не удалось получить аргументы для {tool}: {error}"
REASON_PATCH_ANCHOR = "шаг {index}: old_text не найден в файле {path}"
WARN_MCP_UNAVAILABLE = "MCP-сервер файлов недоступен: {error}"
WARN_TOOL_FAILED = "MCP-инструмент {tool} вернул ошибку: {error}"
DRY_RUN_NOTE = "dry_run: write_file и apply_patch не вызывались, показан предполагаемый diff"
PLAN_FAILED_ANSWER = "План не выполнен: {error}"

#: Текст предполагаемого diff-а, когда правка ничего не меняет.
NO_PRESUMED_DIFF = "(изменений нет)"

#: Формулировки вердикта строки прогона: сбой шага, провал прогона, ``dry_run``,
#: отсутствие ожидаемого изменения и достигнутая цель.
VERDICT_STEP_FAILED = "❌ шаг {index} ({tool}): {error}"
VERDICT_RUN_FAILED = "❌ прогон не выполнен"
VERDICT_DRY_RUN = "🧪 dry_run: план выполнен, файлы не изменены"
VERDICT_EXPECTED_MISSING = "⚠️ ожидаемого изменения нет: {path}"
VERDICT_DONE = "✅ цель достигнута"

#: Сценарии демо-прогона: подпись, цель и файлы, которыми цель подтверждается.
#: Ожидания намеренно только по ФАЙЛАМ: «какие инструменты выберет модель» — её
#: решение, и проверять надо достигнутый результат, а не выбранный способ.
DEMO_SCENARIOS = (
    {"label": "Использование IndexService",
     "goal": "Найди все места, где используется IndexService, и покажи, как он вызывается",
     "expect_modified": (), "expect_created": ()},
    {"label": "Раздел про ассистента файлов в usage.md",
     "goal": "Обнови docs/usage.md: добавь раздел про ассистента файлов",
     "expect_modified": ("docs/usage.md",), "expect_created": ()},
    {"label": "ADR о выборе DeepSeek",
     "goal": "Сгенерируй ADR о выборе DeepSeek как основного провайдера и сохрани его "
             "в docs/adr/0001-deepseek-primary.md",
     "expect_modified": (), "expect_created": ("docs/adr/0001-deepseek-primary.md",)},
)

__all__ = ["AGENT_ID", "CONTEXT_STEP_CHARS", "DEMO_SCENARIOS", "DIRECTORY_TOOLS",
           "DRY_RUN_NOTE", "FILE_PLAN_MAX_STEPS", "FILE_SERVER_NAME",
           "FILE_SERVER_TARGET", "GENERATE_MARK", "GENERATE_SYSTEM_PROMPT",
           "HISTORY_LIMIT", "INTERNAL_READ_REASON", "MAX_CONTEXT_CHARS",
           "MAX_GENERATE_ATTEMPTS", "MAX_PATH_CHARS", "NO_PRESUMED_DIFF",
           "PLAN_FAILED_ANSWER", "PLAN_JSON_HINT", "PLAN_RETRY_HINT",
           "PLAN_SYSTEM_PROMPT", "PlanRejected", "READ_TOOLS", "REASON_BAD_ARGS",
           "REASON_BAD_INDEX", "REASON_BAD_JSON", "REASON_BAD_PATH",
           "REASON_EMPTY_GOAL", "REASON_EMPTY_PLAN", "REASON_GENERATE_FAILED",
           "REASON_MISSING_DIRECTORY", "REASON_MISSING_PATH", "REASON_NOT_OBJECT",
           "REASON_PATCH_ANCHOR", "REASON_TOO_MANY_STEPS", "REASON_UNKNOWN_TOOL",
           "STATUS_COMPLETED", "STATUS_DRY_RUN", "STATUS_FAILED", "STATUS_RUNNING",
           "STEP_FAILED", "STEP_OK", "STEP_SKIPPED", "SUMMARY_SYSTEM_PROMPT",
           "TOOL_APPLY_PATCH", "TOOL_DESCRIPTIONS", "TOOL_GET_FILE_DIFF",
           "TOOL_LIST_FILES", "TOOL_READ_FILE", "TOOL_SEARCH_IN_FILES",
           "TOOL_WRITE_FILE", "TOOLS", "VERDICT_DONE", "VERDICT_DRY_RUN",
           "VERDICT_EXPECTED_MISSING", "VERDICT_RUN_FAILED",
           "VERDICT_STEP_FAILED", "WARN_MCP_UNAVAILABLE", "WARN_TOOL_FAILED",
           "WRITE_TOOLS", "build_plan_prompt", "catalog_text", "normalize_goal"]


class PlanRejected(Exception):
    """План негоден: ``problems`` — что именно не так, ``raw`` — сырой ответ модели.

    Исключение, а не ``None``, потому что отказ плана — это ОТВЕТ пользователю:
    роутер переводит его в 422 с текстом каждой проблемы и сырым ответом модели,
    чтобы причину было видно без чтения логов. У планировщика оркестрации дня 20
    наоборот — там всегда есть эвристика, и отказ равен ``None``.
    """

    def __init__(self, problems: Iterable[str], raw: str = "") -> None:
        self.problems = [str(item) for item in problems]
        self.raw = str(raw or "")
        super().__init__("; ".join(self.problems) or "План негоден")


def normalize_goal(goal: object) -> str:
    """Цель пользователя: пробелы схлопнуты, регистр сохранён.

    Регистр важен: цель содержит имена классов (``IndexService``) и пути, а
    приведение к нижнему регистру сломало бы и то, и другое.
    """
    return " ".join(str(goal or "").split())


def catalog_text() -> str:
    """Каталог инструментов текстом: «- имя: описание» построчно.

    Порядок фиксирован порядком ``TOOLS``: промпт планировщика должен быть ОДНИМ и
    тем же при одинаковой цели, иначе кэш контекста DeepSeek не попадает, а прогоны
    перестают быть сравнимыми.
    """
    return "\n".join(f"- {name}: {TOOL_DESCRIPTIONS[name]}" for name in TOOLS)


def build_plan_prompt(goal: str) -> tuple[str, str]:
    """Сообщения планировщика: системные правила и запрос с примером формата.

    Каталог инструментов в пользовательское сообщение НЕ входит: он одинаков для всех
    целей и уходит отдельным блоком контекста (``catalog_text``), то есть стоит в
    стабильном префиксе запроса и попадает в кэш контекста DeepSeek. В вопросе
    остаётся то, что меняется от прогона к прогону, — цель и пример ответа.
    """
    user = "\n\n".join([f"Цель: {normalize_goal(goal)}", PLAN_JSON_HINT])
    return PLAN_SYSTEM_PROMPT, user
